"""HTML sanitizer for the safe rich-text subset (no scripts or unsafe attrs)."""

import html
import re
import secrets

import nh3

from courses.colour import TC_CLASS_TAGS
from courses.colour import TC_CLASS_VALUES

# Safe subset for styled rich text. NOT the deferred arbitrary-HTML element — no
# scripts, no style/script-bearing attributes.
ALLOWED_TAGS = {
    "p",
    "br",
    # contenteditable (Chrome/Safari) wraps each ENTER-separated line in a <div>;
    # without div here it is stripped, collapsing single-line breaks inline (a single
    # ENTER rendered as a space) while a blank line's <br> survived. Firefox already
    # emits <br>, so it was unaffected. div is structural and carries no script risk.
    "div",
    # Colour carrier. Purely a class hook: no attribute beyond a token-allowlisted
    # class is permitted, so this widens the subset by nothing else.
    "span",
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

# Horizontal-alignment utility classes permitted on block elements of the rich-text
# subset. Token-level allowlist via nh3's allowed_classes — `class` is deliberately
# NOT added to ALLOWED_ATTRIBUTES (that would allow arbitrary class values). Mirrors
# the global .ta-* utilities in courses.css (also used by table cells).
ALIGN_CLASS_VALUES = {"ta-left", "ta-center", "ta-right"}
ALIGN_CLASS_TAGS = {"p", "div", "h2", "h3", "h4", "blockquote", "li"}

# The pre-colour allowlist, frozen. Slice 2's backfill builds its lookup keys by
# replaying the sanitiser AS IT BEHAVED AT IMPORT TIME: nh3 deletes the class
# attribute for a tag that is not an allowed_classes key, but emits an empty
# class="" for one that is. Adding strong/b/i/u/a/span below therefore moves every
# such key off the value the loader actually stored. MEASURED:
#   <strong class="x">y</strong>  ->  <strong>y</strong>          (before)
#                                 ->  <strong class="">y</strong> (after)
# Frozen as a literal, not derived from the live constants, so a later edit to the
# live allowlist cannot silently move the keys.
LEGACY_ALLOWED_CLASSES = {
    "p": {"ta-left", "ta-center", "ta-right"},
    "div": {"ta-left", "ta-center", "ta-right"},
    "h2": {"ta-left", "ta-center", "ta-right"},
    "h3": {"ta-left", "ta-center", "ta-right"},
    "h4": {"ta-left", "ta-center", "ta-right"},
    "blockquote": {"ta-left", "ta-center", "ta-right"},
    "li": {"ta-left", "ta-center", "ta-right"},
}
# sanitize_cell passed NO allowed_classes before this change, so the legacy cell
# behaviour is "no tag is an allowed_classes key" -- deliberately empty, not an
# oversight.
LEGACY_CELL_ALLOWED_CLASSES = {}

# Two independent families merged into one mapping. ALIGN_CLASS_TAGS and
# TC_CLASS_TAGS are currently DISJOINT, so no tag needs a union -- but every entry
# is a fresh set() regardless, because the previous comprehension bound one shared
# set object to all seven keys and any in-place merge would have widened the align
# family for every tag at once.
ALLOWED_CLASSES = {tag: set(ALIGN_CLASS_VALUES) for tag in ALIGN_CLASS_TAGS}
ALLOWED_CLASSES.update({tag: set(TC_CLASS_VALUES) for tag in TC_CLASS_TAGS})


def sanitize_html(value, *, allowed_classes=None):
    """Strip everything outside the safe subset. Idempotent on already-clean input.

    `allowed_classes` is keyword-only and defaults to the live allowlist. The one
    caller that passes it is slice 2's backfill, which replays this sanitiser AS
    IT BEHAVED BEFORE the colour classes existed in order to reconstruct the keys
    the loader actually stored (see LEGACY_ALLOWED_CLASSES above).
    """
    return nh3.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        allowed_classes=ALLOWED_CLASSES if allowed_classes is None else allowed_classes,
        link_rel=None,  # manage rel ourselves via ALLOWED_ATTRIBUTES
        url_schemes=ALLOWED_URL_SCHEMES,
    )


# Cells allow only inline emphasis + line break + the colour carrier. Includes b/i
# (not just strong/em) because document.execCommand("bold"/"italic") emits <b>/<i>.
CELL_TAGS = {"strong", "b", "em", "i", "u", "br", "span"}

# Only cell tags that may carry colour -- br is in CELL_TAGS but not TC_CLASS_TAGS,
# and the block-tag alignment family has no business in a cell.
CELL_ALLOWED_CLASSES = {tag: set(TC_CLASS_VALUES) for tag in CELL_TAGS & TC_CLASS_TAGS}

# Balanced \(...\) (inline) or \[...\] (display), non-greedy, no nesting.
_MATH_SPAN = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.DOTALL)


def _canon_math(span):
    """Canonicalise a math span's text: unescape once, then escape once, so the
    editor path (< already &lt;) and import path (literal <) converge to one
    single-escaped value that is inert to the HTML parser yet decodes to the
    correct textContent for KaTeX. quote=False leaves ' and " untouched."""
    return html.escape(html.unescape(span), quote=False)


def sanitize_cell(value, *, tags=None, allowed_classes=None):
    """Sanitise one table cell's html to CELL_TAGS, protecting balanced LaTeX
    spans from the HTML tokenizer. Idempotent on already-clean input.

    `tags` and `allowed_classes` are keyword-only and default to the live
    allowlists; see sanitize_html for why the backfill overrides them. `tags` exists
    for the backfill's TEST ORACLE only -- it replays the loader over RAW source, so
    it needs the pre-slice-1 tag set to unwrap spans. The backfill's own key
    generator strips spans before calling this and never passes `tags`."""
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
        tags=CELL_TAGS if tags is None else tags,
        attributes={},
        allowed_classes=CELL_ALLOWED_CLASSES
        if allowed_classes is None
        else allowed_classes,
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
    """Plain-text label: unescape entities, collapse whitespace, truncate. Used for
    tab labels, which are plain TEXT (never rich text) but MAY carry inline LaTeX.

    Deliberately NOT run through nh3. An HTML sanitiser reads `<` followed by a
    letter as a tag start and drops everything to the end of input, so a perfectly
    ordinary label like `\\(a<b\\)` was silently stored as `\\(a` — data loss on a
    field whose whole content is authored by hand. Tag-stripping was never the
    barrier that keeps markup out of the page anyway: every sink escapes the label
    (`{{ tab.label }}` in tabselement.html and _element_row.html, `value="…"` in
    _edit_tabs.html, and tabs.js copies the rendered NODES, so a label that is text
    stays text). tests/test_tabs_partial.py pins that escaping."""
    return _WS.sub(" ", html.unescape(value or "")).strip()[:max_length]
