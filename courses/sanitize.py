"""HTML sanitizer for the safe rich-text subset (no scripts or unsafe attrs)."""

import html
import re
import secrets

import nh3

# Safe subset for styled rich text. NOT the deferred arbitrary-HTML element — no
# scripts, no style/script-bearing attributes.
ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "h2",
    "h3",
    "h4",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "code",
    "pre",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title", "rel"}}
# Lock scheme allowlist; drop ftp/data/javascript/etc. that nh3 permits by default.
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(value):
    """Strip everything outside the safe subset. Idempotent on already-clean input."""
    return nh3.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        link_rel=None,  # manage rel ourselves via ALLOWED_ATTRIBUTES
        url_schemes=ALLOWED_URL_SCHEMES,
    )


# Cells allow only inline emphasis + line break. Includes b/i (not just
# strong/em) because document.execCommand("bold"/"italic") emits <b>/<i>.
CELL_TAGS = {"strong", "b", "em", "i", "u", "br"}

# Balanced \(...\) (inline) or \[...\] (display), non-greedy, no nesting.
_MATH_SPAN = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)


def _canon_math(span):
    """Canonicalise a math span's text: unescape once, then escape once, so the
    editor path (< already &lt;) and import path (literal <) converge to one
    single-escaped value that is inert to the HTML parser yet decodes to the
    correct textContent for KaTeX. quote=False leaves ' and " untouched."""
    return html.escape(html.unescape(span), quote=False)


def sanitize_cell(value):
    """Sanitise one table cell's html to CELL_TAGS, protecting balanced LaTeX
    spans from the HTML tokenizer. Idempotent on already-clean input."""
    value = value or ""
    nonce = secrets.token_hex(8)
    spans = []

    def _stash(match):
        spans.append(match.group(0))
        # Pure-alphanumeric placeholder: survives nh3.clean unchanged; nonce
        # makes collision with author-typed text effectively impossible.
        return f"litmathspan{nonce}x{len(spans) - 1}xend"

    protected = _MATH_SPAN.sub(_stash, value)
    cleaned = nh3.clean(
        protected,
        tags=CELL_TAGS,
        attributes={},
        url_schemes=set(),
        link_rel=None,
        strip_comments=True,  # spec-mandated; nh3 defaults True, stated explicitly
    )
    placeholder = re.compile(f"litmathspan{nonce}x(\\d+)xend")
    return placeholder.sub(lambda m: _canon_math(spans[int(m.group(1))]), cleaned)


_WS = re.compile(r"\s+")
_BR = re.compile(r"(?i)<br\s*/?>")


def desc_to_alt(value):
    """Plain-text alt derived from a sanitised gallery description: drop math
    spans, turn <br> into a space, strip all tags, unescape entities, collapse
    whitespace. Empty string when the description carries no textual content
    (e.g. math-only) — the caller substitutes a generic "Image n of m" alt then."""
    value = value or ""
    no_math = _MATH_SPAN.sub(" ", value)
    # <br> must become a space BEFORE tag-stripping, or nh3 would concatenate the
    # surrounding words ("line<br>two" -> "linetwo").
    no_br = _BR.sub(" ", no_math)
    # tags=set() strips every remaining tag but keeps (escaped) text content.
    text = nh3.clean(no_br, tags=set(), attributes={}, link_rel=None)
    return _WS.sub(" ", html.unescape(text)).strip()


def sanitize_label(value, max_length=80):
    """Plain-text label: strip every tag, unescape entities, collapse whitespace,
    truncate. Used for tab labels, which are plain text by design (never rich
    text, never math). Applied on BOTH the save and the read path, so a label
    dirtied by a direct DB edit never reaches a template as markup."""
    text = nh3.clean(value or "", tags=set(), attributes={}, link_rel=None)
    return _WS.sub(" ", html.unescape(text)).strip()[:max_length]
