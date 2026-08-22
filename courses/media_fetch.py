"""Fetch a remote image into a MediaAsset.

Transport is urllib.request, NOT requests -- matching courses/geogebra.py and
integrations/delivery.py, the repo's two existing outbound callers. That choice is
not stylistic: geogebra.py has already measured and documented the two lessons this
module needs (a socket timeout does not bound a call; read1 not read), and requests
would force both to be re-learned in a second dialect.

The worker's boundary rule, copied from geogebra.py: NO ORM, NO cache, NO LOGGING --
it only calls _open, reads bytes, and stores into a result box. create_asset and
everything else stays on the request thread.
"""

import hashlib
import logging
import threading
import urllib.error
import urllib.request
from io import BytesIO
from time import monotonic
from urllib.parse import unquote
from urllib.parse import urljoin
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _

from courses.geogebra import _USER_AGENT
from courses.media import create_asset
from courses.media import truncate_filename
from courses.validators import effective_image_extensions
from courses.validators import effective_max_image_bytes
from courses.validators import validate_fetch_url

logger = logging.getLogger(__name__)

# Params whose value adds nothing beyond the already-rendered message. NOTE `status`
# is interpolated into its message too but is deliberately NOT here: the log line
# carries no other field that identifies which status fired.
#
# CAUTION for translators: ValidationError.__iter__ runs `message %= params`
# whenever params is truthy, even for messages (like "Could not reach the image
# host." and "That URL did not return an image.") that carry no %(name)s
# placeholder -- the params exist only for the log line above. A literal `%`
# landing in either translated string in a future catalog pass turns that
# %-format into a ValueError/KeyError at render time -- a 500 on a rejection
# path. The current Polish catalog is fine; keep this in mind on the next edit.
_MESSAGE_ONLY_PARAMS = {"mib"}

# Hoisted to module level deliberately: raised from four levels of nesting inside
# _fetch's redirect handler this string lands at 89 columns, and `ruff format` reflows
# it to a shape that is STILL 89 -- an E501 no formatter can fix. MEASURED.
_REDIRECT_OFF_ALLOWLIST = _(
    "That URL redirects to a host that is not on the allow-list."
)

MAX_REDIRECT_HOPS = 3
TIMEOUT_SECONDS = 8  # per socket op -- does NOT bound the call
DEADLINE_SECONDS = 20  # total wall clock; the thread join is what enforces it
CHUNK_BYTES = 64 * 1024
MAX_PIXELS = 50_000_000
REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Every constant above is read as a MODULE GLOBAL at call time -- never captured as a
# default argument and never re-exported -- so the deadline tests can monkeypatch them
# down. Both alternatives bind at import and would silently make those tests run for
# the full 20s or pass without exercising the path.


class _BudgetExceeded(Exception):
    """The worker's deadline ran out. Stores nothing, so the caller's empty-box
    branch reports the deadline. Its except clause MUST precede the broad one."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse automatic redirects so each hop can be re-validated.

    Duplicated from geogebra.py/delivery.py rather than imported, for the reason
    geogebra.py documents. Body copied verbatim -- it RAISES, it does not return None.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code, "redirect refused", headers, fp
        )


def _open(request, timeout):
    """The transport seam. Patched by tests; the only place the network is touched."""
    return urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout)


def _build_request(url):
    # The scheme is constrained to http/https by validate_fetch_url before this runs,
    # and _NoRedirect stops the opener following one elsewhere. (This comment must not
    # BEGIN with the directive text -- ruff would read that as a second suppression.)
    return urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "image/*"},
    )


def _remaining(deadline):
    left = deadline - monotonic()
    if left <= 0:
        raise _BudgetExceeded
    return left


def _fetch(submitted_url, deadline, max_bytes):
    """Worker body: steps 4-8. Returns (data, current_url).

    Redirects and non-2xx arrive as RAISED HTTPError, never as returned responses:
    build_opener keeps HTTPErrorProcessor (which raises outside 200-299) and
    _NoRedirect raises on any 3xx. So opener.open() returns ONLY a 2xx.
    """
    current_url = submitted_url
    for hop in range(MAX_REDIRECT_HOPS + 1):  # one initial GET + at most 3 redirects
        # EXACTLY ONE budget check per iteration. It is deliberately fused into the
        # timeout computation rather than written as a separate bare call above: two
        # checks would make the first redundant (the argument is evaluated before
        # _open runs, and _BudgetExceeded escapes both except clauses either way), and
        # a "drop the top-of-loop check" mutant would then be a no-op that no test
        # could catch. One check, one mutant, one RED test.
        hop_timeout = min(TIMEOUT_SECONDS, _remaining(deadline))
        try:
            with _open(_build_request(current_url), hop_timeout) as resp:
                # HTTPErrorProcessor raises only OUTSIDE 200-299, so a 204/206 lands
                # here as a normal response and needs an explicit check.
                if getattr(resp, "status", 200) != 200:
                    raise ValidationError(
                        _("The image host returned an error (status %(status)s)."),
                        code="status",
                        params={"status": resp.status},
                    )
                _check_content_type(resp)  # rejects SVG and any non-image content type
                return _read_capped(resp, deadline, max_bytes), current_url
        except urllib.error.HTTPError as exc:
            # MUST precede the URLError clause below: HTTPError subclasses URLError.
            try:
                if exc.code not in REDIRECT_STATUSES:
                    raise ValidationError(
                        _("The image host returned an error (status %(status)s)."),
                        code="status",
                        params={"status": exc.code},
                    )
                if hop == MAX_REDIRECT_HOPS:
                    raise ValidationError(
                        _("That URL redirects too many times."),
                        code="redirect-too-many",
                    )
                location = (exc.headers or {}).get("Location") or ""
                if not location:
                    raise ValidationError(
                        _("The image host returned an invalid redirect."),
                        code="redirect-invalid",
                    )
                try:
                    target = urljoin(current_url, location)
                    target_host = urlsplit(target).hostname or ""
                except ValueError as bad:
                    # MEASURED: urljoin(..., "//[bad") raises ValueError("Invalid IPv6
                    # URL"), and so does urlsplit on such a target. Both sites sit
                    # inside the `except HTTPError` handler, so the sibling
                    # (TimeoutError, URLError, OSError) clause does NOT catch them --
                    # the ValueError would reach _run's broad handler, be re-raised
                    # unchanged, and surface as a 500 rather than the 422 the error
                    # table promises. Same guard MediaAsset.source_host already uses.
                    raise ValidationError(
                        _("The image host returned an invalid redirect."),
                        code="redirect-invalid",
                    ) from bad
                try:
                    current_url = validate_fetch_url(target)
                except ValidationError as inner:
                    # Replace the underlying rule's message: telling the author their
                    # URL "must use https" when it was the REDIRECT that downgraded is
                    # a false statement about what they typed.
                    raise ValidationError(
                        _REDIRECT_OFF_ALLOWLIST,
                        code="redirect-off-allowlist",
                        params={"target_host": target_host},
                    ) from inner
            finally:
                try:
                    exc.close()  # the `with` was never entered -- close it here
                except Exception:  # noqa: BLE001, S110
                    pass
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            # NOT delivery.py:67's tuple -- that one INCLUDES HTTPError, which would
            # swallow every redirect and status error above. This is delivery.py:144's,
            # plus OSError for mid-read socket failures.
            raise ValidationError(
                _("Could not reach the image host."),
                code="transport",
                params={"exc": type(exc).__name__},
            ) from exc
    # Deliberately undrivable, kept as a guard in the style of geogebra.py:405-412: the
    # `hop == MAX_REDIRECT_HOPS` branch already raises on the last iteration and every
    # other path returns or raises, so the loop cannot fall through. Do NOT write a
    # test for this line -- no input reaches it.
    raise ValidationError(
        _("That URL redirects too many times."), code="redirect-too-many"
    )


MEDIA_TYPE_MAP = {
    "image/png": ("png",),
    "image/jpeg": ("jpg", "jpeg"),
    "image/jpg": ("jpg", "jpeg"),  # non-standard but widely emitted
    "image/gif": ("gif",),
    "image/webp": ("webp",),
}


def _media_type(resp):
    raw = (resp.headers or {}).get("Content-Type") or ""
    return raw.split(";", 1)[0].strip().lower()


def _check_content_type(resp):
    mt = _media_type(resp)
    if mt == "image/svg+xml":
        # Excluded on purpose (active content; the upload path refuses it too). But
        # Wikimedia serves a lot of SVG and IS the default allow-list, so an author
        # WILL paste one -- "did not return an image" would be false and unhelpful.
        raise ValidationError(
            _("That image type is not allowed."),
            code="content-type",
            params={"content_type": mt},
        )
    if mt not in MEDIA_TYPE_MAP:
        raise ValidationError(
            _("That URL did not return an image."),
            code="content-type",
            params={"content_type": mt},
        )


def _read_capped(resp, deadline, max_bytes):
    # ADVISORY ONLY: an absent/non-numeric/negative header is ignored, never a
    # rejection and never a reason to relax the streaming check below. It only saves
    # a pointless transfer. (iter-style reads yield DECOMPRESSED bytes, so a gzipped
    # response can declare a length well under the cap and still exceed it.)
    declared = (resp.headers or {}).get("Content-Length")
    try:
        if declared is not None and int(declared) > max_bytes:
            raise ValidationError(
                _("Image file too large (max %(mib)d MiB)."),
                code="too-large",
                params={"mib": max_bytes // (1024 * 1024)},
            )
    except (TypeError, ValueError):
        pass

    chunks, total = [], 0
    while True:
        _remaining(deadline)  # checked once per chunk
        chunk = resp.read1(CHUNK_BYTES)  # read1, NOT read -- see module docstring
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:  # one chunk past the cap keeps oversize detectable
            raise ValidationError(
                _("Image file too large (max %(mib)d MiB)."),
                code="too-large",
                params={"mib": max_bytes // (1024 * 1024)},
            )
    return b"".join(chunks)


def fetch_image_asset(course, submitted_url, user, name=""):
    submitted_url = validate_fetch_url(submitted_url)  # ASSIGNMENT, not a bare call
    max_bytes = effective_max_image_bytes()  # read ONCE, not per chunk
    allowed_exts = effective_image_extensions()

    box = {}
    deadline = monotonic() + DEADLINE_SECONDS  # computed immediately before start()

    def _run():
        try:
            box["result"] = _fetch(submitted_url, deadline, max_bytes)
        except _BudgetExceeded:
            pass  # stores nothing -> deadline branch
        except BaseException as exc:  # noqa: BLE001 - re-raised on the joiner
            box["exc"] = exc  # store FIRST
            try:
                # Defensive and currently unreachable: _fetch's own `finally`
                # (above) already closes every HTTPError it handles, and no
                # HTTPError escapes it, so `exc` here is never one. Kept as a
                # belt-and-braces guard on the broad `except BaseException` above,
                # in the style of this repo's other deliberately-undrivable guards.
                exc.close()
            except Exception:  # noqa: BLE001, S110
                pass

    thread = threading.Thread(target=_run, name="image-fetch", daemon=True)
    thread.start()
    thread.join(DEADLINE_SECONDS)  # same value as the deadline

    result = dict(box)  # ONE snapshot of a live dict
    if "exc" in result:
        _log_worker_failure(submitted_url, result["exc"])
        raise result["exc"]  # unchanged, whatever its type
    if "result" not in result:
        logger.warning(
            "image fetch: host=%s reason=deadline", urlsplit(submitted_url).hostname
        )
        raise ValidationError(_("Fetching the image took too long."), code="deadline")

    data, current_url = result["result"]
    return _build_asset(
        course, user, name, submitted_url, current_url, data, allowed_exts
    )


def _log_worker_failure(submitted_url, exc):
    """Log once, HERE on the request thread -- the worker must not log.

    Reads BOTH the token and the params defensively: the box may hold a
    non-ValidationError (a genuine worker bug, re-raised as a 500) or a
    ValidationError carrying an error_list/error_dict, which has neither attribute.
    A bare exc.code -- or a bare exc.params -- would raise INSIDE this call and turn
    an intended clean 500 into a different, misleading one.
    """
    if not isinstance(exc, ValidationError):
        return
    code = getattr(exc, "code", None)
    params = getattr(exc, "params", None) or {}
    logger.warning(
        "image fetch: host=%s reason=%s %s",
        urlsplit(submitted_url).hostname,
        code,
        # Omit keys already rendered in the author-facing message (they are not
        # extra diagnostics); keep the rest -- status, target_host, content_type, exc.
        {k: v for k, v in params.items() if k not in _MESSAGE_ONLY_PARAMS},
    )


PILLOW_FORMAT_MAP = {
    "PNG": ("png",),
    "JPEG": ("jpg", "jpeg"),
    # Pillow reports MPO -- not JPEG -- for multi-picture JPEGs, which is what most
    # phone cameras produce and a large share of real web JPEGs. Omitting it would
    # reject them as an unknown format.
    "MPO": ("jpg", "jpeg"),
    "GIF": ("gif",),
    "WEBP": ("webp",),
}


def _verify_payload(data):
    """Return img.format. Rejects anything Pillow cannot open, and over-large canvases.

    Image.open's header sniff is the real format authority; Image.verify() is a no-op
    on the base class and is overridden by only a few plugins (notably PNG). A
    TRUNCATED jpeg/gif/webp passes both, is stored, and fails later inside
    generate_derivatives, which swallows it -- knowingly accepted, so do not write a
    truncation-rejection test.
    """
    from PIL import Image

    try:
        img = Image.open(BytesIO(data))
        fmt, size = img.format, img.size
        # Pixel check BEFORE verify(): PngImageFile.verify() walks chunks and checks
        # CRCs, so the natural huge-IHDR fixture would be rejected as "not a usable
        # image" and this test would fail on a CORRECT build.
        if size[0] * size[1] > MAX_PIXELS:
            raise ValidationError(
                _("That image's dimensions are too large."), code="too-many-pixels"
            )
        img.verify()
    except ValidationError:
        raise
    except Image.DecompressionBombError as exc:
        # Its own clause, BEFORE the broad one: Pillow raises this from Image.open
        # above 2x MAX_IMAGE_PIXELS, i.e. before the size check above can run. Mapping
        # it here keeps both sides of that boundary reporting the same condition.
        raise ValidationError(
            _("That image's dimensions are too large."), code="too-many-pixels"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - the view catches only ValidationError
        raise ValidationError(
            _("That URL did not return a usable image."), code="not-an-image"
        ) from exc
    return fmt


def _derive_filename(current_url, fmt, allowed_exts):
    from courses.validators import SAFE_IMAGE_EXTENSIONS

    candidates = PILLOW_FORMAT_MAP.get(fmt)
    if not candidates:
        raise ValidationError(_("That image type is not allowed."), code="format")
    ext = next((c for c in candidates if c in allowed_exts), None)
    if ext is None:
        raise ValidationError(_("That image type is not allowed."), code="format")

    # Unquote FIRST, then basename: taking the basename first leaves "..%2F..%2Fx.png"
    # intact, which unquotes to "../../x.png" and makes Django's storage raise
    # SuspiciousFileOperation -- a 500, since only ValidationError is caught.
    path = unquote(urlsplit(current_url).path)
    stem = path.rsplit("/", 1)[-1]
    head, dot, tail = stem.rpartition(".")
    # Strip against the FIXED safe universe, never effective_image_extensions(): the
    # latter is intersected with admin config, so under a narrowing to ["jpeg"] a
    # .jpg path would not be stripped and we would store Foo.jpg.jpeg.
    if dot and tail.lower() in SAFE_IMAGE_EXTENSIONS:
        stem = head
    stem = stem.replace("/", "").replace("\\", "").replace("..", "")
    stem = "".join(ch for ch in stem if ch.isprintable()).lstrip(".").strip()
    return truncate_filename(f"{stem or 'image'}.{ext}")


def _build_asset(course, user, name, submitted_url, current_url, data, allowed_exts):
    # Steps 9-13 run HERE, on the request thread, so they log at their own sites --
    # the spec's fourth logging bullet. Without these, four enumerated conditions
    # (empty body, not-a-usable-image, too-many-pixels, unknown format) leave no
    # operator-visible trace at all.
    host = urlsplit(submitted_url).hostname
    try:
        if not data:
            # media_upload gets its empty-file rejection from MediaAssetForm's
            # FileField, which this path bypasses, and MediaAsset.clean() has no
            # lower size bound -- so without this a 200 + Content-Length: 0 creates a
            # real zero-byte asset.
            raise ValidationError(_("The fetched file is empty."), code="empty-body")
        fmt = _verify_payload(data)
        filename = _derive_filename(current_url, fmt, allowed_exts)
    except ValidationError as exc:
        logger.warning(
            "image fetch: host=%s reason=%s", host, getattr(exc, "code", None)
        )
        raise
    digest = hashlib.sha256(data).hexdigest()  # EXACTLY lal_loader/media.py:33's form
    # Written out in full rather than elided: `name=name` in particular is easy to drop
    # on a re-type, and no test in Tasks 4-8 asserts it.
    return create_asset(
        course,
        "image",
        ContentFile(data, name=filename),
        user,
        name=name,
        source_url=submitted_url,
        content_hash=digest,
    )
