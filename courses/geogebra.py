"""Canonicalize a recognized GeoGebra material URL to the worksheet-only embed URL.

GeoGebra publishes one material under several URL shapes; only
``https://www.geogebra.org/material/iframe/id/<ID>`` renders just the worksheet
(share links and the classic ``/material/show`` form render the full page).

This module is both the single GeoGebra URL parser and the single place the GeoGebra
API is called. Parsing functions rebuild recognized ``https`` inputs from scratch
(host + material id, dropping any width/height/border cruft) and return everything
else unchanged for ``validate_embed_url`` to judge; the one network function performs
a single capped GET behind the ``GEOGEBRA_API_LOOKUP`` kill switch. Nothing here
raises — every failure degrades to a neutral value, because these run inside form
validation and inside page render, where an exception would 500 a save or a student
unit page.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache

# Recognized hosts are hardcoded and intentionally decoupled from
# settings.ALLOWED_EMBED_DOMAINS: this function only *rewrites*, it never
# *accepts* (validate_embed_url remains the sole gate).
_GEOGEBRA_HOSTS = ("geogebra.org", "www.geogebra.org")
# base64url superset of GeoGebra's observed base62 material ids, so a legitimate
# id carrying '-'/'_' is never silently rejected.
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CANONICAL = "https://www.geogebra.org/material/iframe/id/{}"

DIM_MAX = 2147483647  # PositiveIntegerField ceiling; public — imported across modules
GEOGEBRA_DEFAULT_SIZE = (800, 600)  # GeoGebra's own iframe-shell fallback -> 4:3
# ^ The shell hardcodes `parameters.width = (parameters.width || 800) * 1`, so a
#   dimensionless embed ALWAYS renders 800x600 whatever the material's authored size.
#   Measured: a 4:3 wrapper leaves a 0.0px gap; today's 16:9 leaves 161.3px at the
#   648px content width. Consumed by frame_ratio step 3 (Task 7).

logger = logging.getLogger(__name__)

_API_PREFIX = "https://api.geogebra.org/"
# A module constant rather than a setting, matching the pattern of
# integrations/delivery.py :: TIMEOUT_SECONDS = 10. This bounds urllib's SOCKET
# ops -- connect() and each individual read(), not the total call -- so a peer
# dribbling bytes slowly can hold the wall clock (and, since this call sits
# inside save_element's row lock, the unit row + worker) well past 3s. Accepted:
# hardcoded host, _NoRedirect, and delivery.py already carries this same shape
# at 10s. The measured 3.29s timeout (blackholed address) validated only the
# connect leg; a blackholed SYN never reaches the read stage.
_TIMEOUT_SECONDS = 3
_MAX_BODY_BYTES = 65536  # ~55x the measured 1,177-byte ws response
_NEGATIVE_TTL_SECONDS = 60
_USER_AGENT = "libli/1.0 (+https://github.com/krzyssikora/libli)"


def usable_dimensions(width, height):
    """True iff both are real, positive, in-range ints (1..DIM_MAX).

    The single definition of "known size", shared by the API parser, clean_url's
    guards, frame_ratio and size_unknown, so the badge and the ratio can never
    disagree. The ceiling lives HERE rather than only in the API parser: width and
    height are absent from IframeElementForm.Meta.fields, so ModelForm._post_clean
    excludes them from full_clean and the PositiveIntegerField range validator never
    runs — an over-range value would reach the DB and 500 on save.

    bool is excluded explicitly: isinstance(True, int) is True in Python, so a
    payload of {"width": true} would otherwise render `aspect-ratio: True / 660`.
    Non-int types are rejected outright, including an integral float like 880.0.
    """
    for value in (width, height):
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if value < 1 or value > DIM_MAX:
            return False
    return True


def _material_id(segments):
    """Return the material id from path segments, or '' if none is extractable.

    Two ordered, bounds-guarded checks (never IndexError):
      (a) first segment == 'm'    -> the segment after it   (share short link)
      (b) a whole segment == 'id' -> the segment after the first such 'id'
    Comparisons are case-sensitive (only the host is lowercased by the caller).
    """
    if segments and segments[0] == "m":
        return segments[1] if len(segments) > 1 else ""
    if "id" in segments:
        i = segments.index("id")
        return segments[i + 1] if len(segments) > i + 1 else ""
    return ""


def geogebra_material_id(url):
    """Return the material id for a recognized https GeoGebra URL, else "".

    Applies _ID_RE, which _material_id does NOT — canonicalize_geogebra_url used to
    apply it afterwards. Without the regex here, ".../m/bad id" would return a truthy
    "bad id" and clean_url would build an API URL containing a raw space.

    Never raises: urlsplit/.hostname can raise ValueError on a malformed authority,
    and this runs during page render (frame_ratio) as well as in clean_url.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return ""
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return ""
        candidate = _material_id(parts.path.split("/")[1:])
        return candidate if _ID_RE.match(candidate) else ""
    except (ValueError, TypeError, IndexError):
        return ""


def canonicalize_geogebra_url(url):
    """Rewrite a recognized https GeoGebra material URL to the worksheet embed URL.

    Anything not recognized — non-https, non-GeoGebra host, a *.geogebra.org
    subdomain, an app link, a missing/malformed id, or any parse failure — is
    returned unchanged. Recognition lives entirely in geogebra_material_id.
    """
    material_id = geogebra_material_id(url)
    return _CANONICAL.format(material_id) if material_id else url


def is_geogebra_iframe_url(url):
    """True only for the canonical shape geogebra_sized_src will rewrite.

    Mirrors that function's guard in FULL — including the easily-missed
    `"width" in segments` disjunct — so frame_ratio can never claim a ratio the
    rendered src does not back up. Deliberately STRICTER in one respect:
    geogebra_sized_src never validates segments[3], so ".../id" (no id) and an id
    failing _ID_RE are True there and False here. Both are degenerate shapes that
    clean_url cannot produce; see the design doc's divergence table.

    Never raises.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return False
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return False
        segments = parts.path.split("/")[1:]
        if segments[:3] != ["material", "iframe", "id"] or "width" in segments:
            return False
        return len(segments) > 3 and bool(_ID_RE.match(segments[3]))
    except (ValueError, TypeError, IndexError):
        return False


def geogebra_sized_src(url, width, height):
    """Append ``/width/W/height/H`` to a canonical GeoGebra material/iframe URL.

    GeoGebra sizes the applet from these path segments and scales it to fill the
    iframe at that aspect ratio; a *dimensionless* URL renders at the material's
    own ratio and will not fill a differently-shaped frame. This is a render-time
    helper — the stored URL stays the minimal canonical form, and the dimensions
    come from the element's captured ``width``/``height`` (the same pair that
    drives the wrapper's aspect ratio, so applet and frame match).

    Returns ``url`` unchanged for a non-GeoGebra URL, a missing/partial dimension
    pair, a non-``material/iframe/id`` path, or a URL that already carries
    ``width``. Never raises.
    """
    if not (width and height):
        return url
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return url
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return url
        segments = parts.path.split("/")[1:]
        if segments[:3] != ["material", "iframe", "id"] or "width" in segments:
            return url
        return f"{url.rstrip('/')}/width/{width}/height/{height}"
    except (ValueError, TypeError, IndexError):
        return url


def geogebra_url_size(url):
    """(W, H) from a canonical GeoGebra URL's /width/W/height/H tail, else (None, None).

    Drives frame_ratio step 0: such a URL sizes the applet itself, so the frame must
    match IT rather than the stored columns or the 16:9 default.

    Scoped to GeoGebra on purpose — a bare "the path contains width" rule would fire
    on other providers and give them an inline ratio they do not have today.

    Positional, not index-searched: the pair must sit at fixed offsets right after the
    id, so a `width` at any other depth is never picked up. Segments AFTER offset 7 are
    ignored -- GeoGebra's real embed src ships .../width/1600/height/763/border/888888/
    sfsb/true, and a `len == 8` rule would reject it, leaving the wrapper at 16:9 while
    the src imposes 1600/763. A trailing repeat therefore loses to the first pair.

    Returns validated ints, NEVER raw path text. frame_ratio's value is interpolated
    into style="aspect-ratio: ...", and Django's autoescape does not escape ';' or ':',
    both legal in a path segment — raw text would let an admin-stored URL inject CSS
    declarations. Never raises.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return None, None
        if (parts.hostname or "").lower() not in _GEOGEBRA_HOSTS:
            return None, None
        segments = parts.path.split("/")[1:]
        if len(segments) < 8 or segments[:3] != ["material", "iframe", "id"]:
            return None, None
        if segments[4] != "width" or segments[6] != "height":
            return None, None
        if not _ID_RE.match(segments[3]):
            return None, None
        raw_width, raw_height = segments[5], segments[7]
        # .isdecimal(), not .isdigit(): isdigit accepts Unicode superscripts that
        # int() then rejects with ValueError.
        if not (raw_width.isdecimal() and raw_height.isdecimal()):
            return None, None
        width, height = int(raw_width), int(raw_height)
        return (width, height) if usable_dimensions(width, height) else (None, None)
    except (ValueError, TypeError, IndexError):
        return None, None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects, so a URL checked at construction cannot be followed elsewhere.

    Duplicated from integrations/delivery.py :: _NoRedirect deliberately rather than
    imported: that module does `from integrations.models import WebhookDelivery` at
    module level, and courses/models.py imports this module at module level — an
    import would pull integrations.models into courses at app-load time. Every
    existing courses -> integrations reference in the repo is a lazy in-function
    import.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Body copied VERBATIM from delivery.py — it RAISES, it does not return None.
        # The raise is then swallowed by fetch_geogebra_dimensions' bare except and
        # degrades to the 4:3 fallback, which is the intended behaviour.
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect refused", headers, fp
        )


def _open(request, timeout):
    """The transport seam. Patched by tests; the only place the network is touched."""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _settings_dimensions(node):
    """(W, H) from a node's `settings` block when usable, else (None, None).

    Defensive on `settings`: a non-dict settings block is SKIPPED, not fatal. The outer
    bare `except Exception` would otherwise abort the whole elements scan on one
    malformed entry, silently contradicting "keep scanning".

    What keeps ws_non_g_first.json's `null` and string entries non-fatal is the CALLER's
    own isinstance check in the elements loop, not the node guard below -- every call
    site already passes a dict, so that guard is unreachable by construction. It is kept
    as a second declared defensive branch (alongside the _API_PREFIX check) rather than
    deleted, because this function is the obvious place for a future caller to appear.
    Like _API_PREFIX, it therefore gets no test: a branch that cannot be driven cannot
    be falsified to RED.
    """
    if not isinstance(node, dict):
        return None, None
    block = node.get("settings")
    if not isinstance(block, dict):
        return None, None
    width, height = block.get("width"), block.get("height")
    return (width, height) if usable_dimensions(width, height) else (None, None)


def _dimensions_from_payload(payload, material_id):
    """Apply the selection rule; log which of the FOUR failure modes fired."""
    if not isinstance(payload, dict):
        # Valid JSON that is not an object -- b"[]" or b'"x"' parse fine and would
        # otherwise return here silently, then hit fetch's unlogged cache.set tail.
        # Every other failure path logs; this one must too, or a live API shape change
        # is indistinguishable from a material genuinely having no dimensions.
        logger.warning(
            "geogebra %s: payload is not an object (%s)",
            material_id,
            type(payload).__name__,
        )
        return None, None

    width, height = _settings_dimensions(payload)
    if usable_dimensions(width, height):
        return width, height

    elements = payload.get("elements")
    if not isinstance(elements, list):
        logger.warning(
            "geogebra %s: no usable settings and no elements list", material_id
        )
        return None, None

    sized = []
    for entry in elements:
        if not isinstance(entry, dict) or entry.get("type") != "G":
            continue
        entry_width, entry_height = _settings_dimensions(entry)
        if usable_dimensions(entry_width, entry_height):
            sized.append((entry_width, entry_height))

    if len(sized) == 1:
        return sized[0]
    if sized:
        # The iframe embeds the whole worksheet, so picking one applet's ratio would be
        # a guess. A confidently wrong frame with size_unknown False is worse than the
        # 4:3 fallback plus a badge.
        logger.warning(
            "geogebra %s: multiple sized G elements (%d), refusing to guess",
            material_id,
            len(sized),
        )
    else:
        logger.warning(
            "geogebra %s: no G element yielded usable dimensions", material_id
        )
    return None, None


def fetch_geogebra_dimensions(material_id):
    """The material's authored (width, height), or (None, None). All-or-nothing.

    Never raises — a bare `except Exception`, matching courses/embed.py's precedent:
    urlopen can raise RemoteDisconnected, ConnectionResetError, ssl.SSLError,
    UnicodeDecodeError and ValueError, none of which are URLError subclasses, and
    anything escaping into clean_url would 500 the save.
    """
    # Read the flag on EVERY call — capturing it at import would make every
    # override_settings a silent no-op and let the invalid-input tests pass vacuously.
    if not settings.GEOGEBRA_API_LOOKUP:
        return None, None  # no cache read, no cache WRITE, no request

    cache_key = f"geogebra:dims:{material_id}"
    if cache.get(cache_key):
        return None, None

    def _fail(reason):
        logger.warning("geogebra %s: %s", material_id, reason)
        # truthy: None reads as a cache miss
        cache.set(cache_key, True, _NEGATIVE_TTL_SECONDS)
        return None, None

    url = f"{_API_PREFIX}v1.0/materials/{material_id}?scope=basic"
    if not url.startswith(_API_PREFIX):
        # Defensive only and unreachable by construction (material_id has passed
        # _ID_RE, so it cannot introduce a scheme or host). Deliberately untested: a
        # branch that cannot be driven cannot be falsified to RED. The real controls
        # are _ID_RE and _NoRedirect.
        return None, None

    try:
        # S310 justification (mirrors integrations/delivery.py:50,122): the URL is
        # built from a hardcoded _API_PREFIX plus an _ID_RE-validated id, so it cannot
        # carry an attacker-chosen scheme or host, and _NoRedirect stops the opener
        # from following one. NOTE the wording: a comment line whose text begins with
        # a noqa directive naming S310 is parsed by ruff as a suppression directive on
        # a line carrying no diagnostic -- inert today, but a duplicate the moment
        # RUF100 is selected.
        request = urllib.request.Request(  # noqa: S310
            url, headers={"User-Agent": _USER_AGENT}
        )
        with _open(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read(_MAX_BODY_BYTES + 1)  # +1 so oversize is detectable
    except urllib.error.HTTPError as exc:
        # A 4xx/5xx raises from INSIDE _open, so the `with` above is never entered and
        # the error's own fp is never closed — close it explicitly or the 400 test
        # surfaces an unexplained ResourceWarning.
        try:
            exc.close()
        # S110 (try-except-pass) IS enabled and DOES fire here; BLE001 is not.
        # Precedent for S110 on a handler line: tests/capture_help_screenshots.py:460.
        except Exception:  # noqa: BLE001, S110 - closing must never mask the original
            pass
        return _fail(f"HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001 - the never-raises contract
        return _fail(f"lookup failed ({type(exc).__name__})")

    if len(body) > _MAX_BODY_BYTES:
        return _fail(f"response body oversized (>{_MAX_BODY_BYTES} bytes)")

    # The parse AND the selection scan both sit inside this try. Putting
    # _dimensions_from_payload outside it would let anything raising in the scan
    # propagate into clean_url and 500 the save -- the exact outcome the never-raises
    # contract exists to prevent, and worse than the abort the per-entry defensiveness
    # already guards against.
    try:
        payload = json.loads(body)
        width, height = _dimensions_from_payload(payload, material_id)
    except Exception as exc:  # noqa: BLE001 - the never-raises contract
        return _fail(f"unparseable payload ({type(exc).__name__})")

    if not usable_dimensions(width, height):
        cache.set(cache_key, True, _NEGATIVE_TTL_SECONDS)
        return None, None
    return width, height
