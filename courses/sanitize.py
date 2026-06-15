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


def sanitize_html(value):
    """Strip everything outside the safe subset. Idempotent on already-clean input."""
    return nh3.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        link_rel=None,  # manage rel ourselves via ALLOWED_ATTRIBUTES
    )
