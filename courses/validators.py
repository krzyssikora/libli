"""Upload validators and effective image/video size and extension limits."""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _

# --- Static caps KEPT for back-compat: frozen migration 0006 + existing tests
#     import these by name (validate_image_size/validate_video_size/MAX_*_BYTES).
#     Do NOT remove. New MediaAsset validation uses validate_image_file below. ---
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MiB


def validate_image_size(file):
    """Static 5 MiB cap (back-compat). Skips already-committed FieldFiles."""
    if getattr(file, "_committed", False):
        return
    if file.size > MAX_IMAGE_BYTES:
        raise ValidationError("Image file too large (max 5 MiB).")


def validate_video_size(file):
    """Static 200 MiB cap (back-compat). Skips already-committed FieldFiles."""
    if getattr(file, "_committed", False):
        return
    if file.size > MAX_VIDEO_BYTES:
        raise ValidationError("Video file too large (max 200 MiB).")


# --- Upload safe set: the permanent security CEILING. Admins may only narrow. ---
SAFE_IMAGE_EXTENSIONS = ("png", "jpg", "jpeg", "gif", "webp")
SAFE_VIDEO_EXTENSIONS = ("mp4", "webm", "ogg", "mov")
MAX_IMAGE_MIB_CEILING = 5
MAX_VIDEO_MIB_CEILING = 200

_MIB = 1024 * 1024


def default_image_extensions():
    # Module-level callable (not a literal) so migrations can serialize the default.
    return list(SAFE_IMAGE_EXTENSIONS)


def default_video_extensions():
    return list(SAFE_VIDEO_EXTENSIONS)


def _site_config():
    # Function-scope import: courses/validators is imported at model-load time, so a
    # top-level `from core.services import ...` risks a core<->courses import cycle.
    from core.services import get_site_config

    return get_site_config()


def _effective_extensions(key, safe):
    stored = _site_config().get(key, list(safe))
    chosen = set(stored)
    return [e for e in safe if e in chosen]  # order = safe-set order; stored ∩ safe


def effective_image_extensions():
    return _effective_extensions("allowed_image_extensions", SAFE_IMAGE_EXTENSIONS)


def effective_video_extensions():
    return _effective_extensions("allowed_video_extensions", SAFE_VIDEO_EXTENSIONS)


def effective_max_image_bytes():
    mib = _site_config().get("max_image_mib", MAX_IMAGE_MIB_CEILING)
    return min(mib, MAX_IMAGE_MIB_CEILING) * _MIB


def effective_max_video_bytes():
    mib = _site_config().get("max_video_mib", MAX_VIDEO_MIB_CEILING)
    return min(mib, MAX_VIDEO_MIB_CEILING) * _MIB


def _validate_file(file, *, extensions, max_bytes, too_big_msg):
    """Extension + size check, skipping already-committed FieldFiles.

    Committed files are skipped for BOTH checks so admin narrowing applies to NEW
    uploads only (never a retroactive rejection on an unrelated edit) and reading
    `.size` never hits absent storage (FileNotFoundError in tests/remote storage).
    New uploads (InMemory/Temporary) lack `_committed`, so getattr -> False.
    """
    if getattr(file, "_committed", False):
        return
    FileExtensionValidator(allowed_extensions=list(extensions))(file)
    if file.size > max_bytes:
        raise ValidationError(too_big_msg)


def validate_image_file(file):
    _validate_file(
        file,
        extensions=effective_image_extensions(),
        max_bytes=effective_max_image_bytes(),
        too_big_msg=_("Image file too large (max %(mib)d MiB).")
        % {"mib": effective_max_image_bytes() // _MIB},
    )


def validate_video_file(file):
    _validate_file(
        file,
        extensions=effective_video_extensions(),
        max_bytes=effective_max_video_bytes(),
        too_big_msg=_("Video file too large (max %(mib)d MiB).")
        % {"mib": effective_max_video_bytes() // _MIB},
    )


def validate_embed_url(url):
    """Require https and a host that equals or is a subdomain of a whitelisted host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValidationError("Embed URLs must use https.")
    host = (parts.hostname or "").lower()
    allowed = {d.lower() for d in settings.ALLOWED_EMBED_DOMAINS}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValidationError("Embed domain is not on the allow-list.")


MAX_FETCH_URL_LENGTH = 500  # matches MediaAsset.source_url's max_length


def validate_fetch_url(url):
    """Guard for server-side image fetches. Returns the STRIPPED url.

    Twin of validate_embed_url, with three differences: it strips, it length-caps
    (source_url is a 500-char column), and it runs URLValidator. Callers MUST use the
    return value -- a bare call whose result is discarded leaves the caller's url
    unstripped, stores "\\nhttps://..." in source_url, and still passes every other
    test in the suite, because they all use clean urls.
    """
    url = (url or "").strip()
    if not url:
        raise ValidationError(_("Enter an image URL."), code="empty")
    if len(url) > MAX_FETCH_URL_LENGTH:
        # Literal 500, matching the spec's pinned error text exactly -- the spec's
        # error table is the single source for the implementation, the view tests AND
        # the .po entries, so parameterising it here would fork the msgid.
        raise ValidationError(
            _("That URL is too long (maximum 500 characters)."), code="too-long"
        )
    try:
        URLValidator()(url)
    except ValidationError as exc:
        raise ValidationError(
            _("That does not look like a valid URL."), code="malformed"
        ) from exc
    parts = urlsplit(url)
    allowed_schemes = (
        {"https", "http"} if settings.ALLOW_HTTP_IMAGE_FETCH else {"https"}
    )
    if parts.scheme not in allowed_schemes:
        raise ValidationError(_("Image URLs must use https."), code="scheme")
    host = (parts.hostname or "").lower()
    allowed = {d.lower() for d in settings.ALLOWED_IMAGE_FETCH_DOMAINS}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValidationError(
            _("That image host is not on the allow-list."), code="host"
        )
    return url
