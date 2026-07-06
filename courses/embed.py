"""Parse a pasted <iframe> embed snippet (or a plain URL) down to a single
validated https `src`. Never store raw HTML — only the extracted, whitelisted URL.

First-match-wins error precedence (one deterministic message per case):
  malformed-parse -> multi-iframe (>1) -> no-iframe (0) -> missing-src
  -> non-whitelisted-domain (delegated to validate_embed_url).
"""

from html.parser import HTMLParser

from django.core.exceptions import ValidationError

from courses.geogebra import canonicalize_geogebra_url
from courses.validators import validate_embed_url


class _IframeCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.iframes = []  # list of attr-dicts, one per <iframe> anywhere in the input

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.iframes.append({k.lower(): (v or "") for k, v in attrs})


_INT_MAX = 2147483647  # PositiveIntegerField ceiling


def _dimension(value):
    """A positive int (1.._INT_MAX) from an iframe width/height attribute, else None.

    Strips a trailing 'px'; rejects '', '%', negatives, zero, non-integers
    (e.g. '800.5'), and values above the DB column ceiling.
    """
    value = (value or "").strip()
    if value.lower().endswith("px"):
        value = value[:-2].strip()
    if not value.isdigit():  # rejects '', '%', '-5', '800.5', any non-digit run
        return None
    n = int(value)
    if n <= 0 or n > _INT_MAX:
        return None
    return n


def parse_iframe_dimensions(raw):
    """Return (width, height) from the sole <iframe>'s attributes, or (None, None).

    Reads the `width`/`height` HTML attributes only (not provider-specific URL
    path). Anything but exactly one <iframe> — a plain URL, zero, or many — yields
    (None, None). Never raises, like the rest of this module.
    """
    parser = _IframeCollector()
    try:
        parser.feed((raw or "").strip())
        parser.close()
    except Exception:  # stdlib html.parser rarely raises; treat as unparseable
        return None, None
    if len(parser.iframes) != 1:
        return None, None
    attrs = parser.iframes[0]
    return _dimension(attrs.get("width")), _dimension(attrs.get("height"))


def extract_embed_url(raw):
    """Return a validated https embed URL, or raise ValidationError.

    Dispatch on the trimmed input: a leading '<' means an HTML snippet (parse it);
    otherwise treat it as a plain URL and hand it straight to validate_embed_url.
    """
    text = (raw or "").strip()
    if not text:
        raise ValidationError(
            "Enter an embed URL or paste the embed's <iframe …> code."
        )
    if not text.startswith("<"):
        url = canonicalize_geogebra_url(text)
        validate_embed_url(url)  # raises on non-https / non-whitelisted
        return url

    parser = _IframeCollector()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # stdlib html.parser rarely raises; treat as malformed
        raise ValidationError("Could not parse that embed code.") from exc

    iframes = parser.iframes
    if len(iframes) > 1:
        raise ValidationError("Paste a single embed (found more than one <iframe>).")
    if len(iframes) == 0:
        raise ValidationError(
            "No <iframe> found — paste the embed's <iframe …> code or a direct URL."
        )
    src = iframes[0].get("src", "").strip()
    if not src:
        raise ValidationError("The pasted <iframe> has no src.")
    url = canonicalize_geogebra_url(src)
    validate_embed_url(url)  # https + allow-list; never receives ""
    return url
