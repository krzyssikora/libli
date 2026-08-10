"""Canonicalize a recognized GeoGebra material URL to the worksheet-only embed URL.

GeoGebra publishes one material under several URL shapes; only
``https://www.geogebra.org/material/iframe/id/<ID>`` renders just the worksheet
(share links and the classic ``/material/show`` form render the full page).

This is the single GeoGebra parser: recognized ``https`` inputs are rebuilt from
scratch (host + material id, dropping any width/height/border cruft), and
everything else is returned unchanged for ``validate_embed_url`` to judge. It
never raises — validation stays entirely in ``validate_embed_url``.
"""

import re
from urllib.parse import urlsplit

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
