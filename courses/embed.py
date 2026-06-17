"""Parse a pasted <iframe> embed snippet (or a plain URL) down to a single
validated https `src`. Never store raw HTML — only the extracted, whitelisted URL.

First-match-wins error precedence (one deterministic message per case):
  malformed-parse -> multi-iframe (>1) -> no-iframe (0) -> missing-src
  -> non-whitelisted-domain (delegated to validate_embed_url).
"""

from html.parser import HTMLParser

from django.core.exceptions import ValidationError

from courses.validators import validate_embed_url


class _IframeCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.iframes = []  # list of attr-dicts, one per <iframe> anywhere in the input

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.iframes.append({k.lower(): (v or "") for k, v in attrs})


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
        validate_embed_url(text)  # raises on non-https / non-whitelisted
        return text

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
    validate_embed_url(src)  # https + allow-list; never receives ""
    return src
