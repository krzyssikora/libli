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
    """Worker body: steps 4-8. Returns (data, current_url). Raises only."""
    current_url = submitted_url
    with _open(
        _build_request(current_url), min(TIMEOUT_SECONDS, _remaining(deadline))
    ) as resp:
        data = _read_capped(resp, deadline, max_bytes)
    return data, current_url


def _read_capped(resp, deadline, max_bytes):
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
                exc.close()  # HTTPError only; harmless otherwise
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


def _build_asset(course, user, name, submitted_url, current_url, data, allowed_exts):
    """Steps 9-13, on the request thread."""
    filename = "image.png"  # replaced in Task 7
    digest = hashlib.sha256(data).hexdigest()  # EXACTLY lal_loader/media.py:33's form
    return create_asset(
        course,
        "image",
        ContentFile(data, name=filename),
        user,
        name=name,
        source_url=submitted_url,
        content_hash=digest,
    )
