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


def canonicalize_geogebra_url(url):
    """Rewrite a recognized https GeoGebra material URL to the worksheet embed URL.

    Anything not recognized — non-https, non-GeoGebra host, a *.geogebra.org
    subdomain, an app link, a missing/malformed id, or any parse failure — is
    returned unchanged.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme != "https":
            return url
        host = (parts.hostname or "").lower()  # .hostname can raise / be None
        if host not in _GEOGEBRA_HOSTS:
            return url
        segments = parts.path.split("/")[1:]  # drop the single leading ''
        candidate = _material_id(segments)
        if _ID_RE.match(candidate):
            return _CANONICAL.format(candidate)
        return url
    except (ValueError, TypeError, IndexError):
        # Backstop: urlsplit/.hostname/.port can raise ValueError on a malformed
        # authority; bounds-guards above already prevent IndexError. Any failure
        # → pass through unchanged (honors the "never raises" contract).
        return url
