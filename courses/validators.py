from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError


def validate_embed_url(url):
    """Require https and a host that equals or is a subdomain of a whitelisted host.

    A listed domain like "www.geogebra.org" also authorises subdomains of
    "geogebra.org" (the www-stripped root), so "sub.geogebra.org" is accepted.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ValidationError("Embed URLs must use https.")
    host = (parts.hostname or "").lower()
    # Build a set of base domains that includes each listed domain AND its
    # www-stripped root so that subdomain matching works intuitively.
    bases: set[str] = set()
    for d in settings.ALLOWED_EMBED_DOMAINS:
        d = d.lower()
        bases.add(d)
        if d.startswith("www."):
            bases.add(d[4:])  # also allow subdomains of the bare root
    if not any(host == d or host.endswith("." + d) for d in bases):
        raise ValidationError("Embed domain is not on the allow-list.")
