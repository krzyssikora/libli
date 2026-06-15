from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MiB
MAX_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MiB


def validate_image_size(file):
    """Reject image uploads larger than MAX_IMAGE_BYTES.

    Only checks in-memory uploads (not committed FieldFiles pointing to storage).
    """
    if getattr(file, "_committed", False):
        return
    if file.size > MAX_IMAGE_BYTES:
        raise ValidationError("Image file too large (max 5 MiB).")


def validate_video_size(file):
    """Reject video uploads larger than MAX_VIDEO_BYTES.

    Only checks in-memory uploads (not committed FieldFiles pointing to storage).
    """
    if getattr(file, "_committed", False):
        return
    if file.size > MAX_VIDEO_BYTES:
        raise ValidationError("Video file too large (max 200 MiB).")


def validate_embed_url(url):
    """Require https and a host that equals or is a subdomain of a whitelisted host."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValidationError("Embed URLs must use https.")
    host = (parts.hostname or "").lower()
    allowed = {d.lower() for d in settings.ALLOWED_EMBED_DOMAINS}
    if not any(host == d or host.endswith("." + d) for d in allowed):
        raise ValidationError("Embed domain is not on the allow-list.")
