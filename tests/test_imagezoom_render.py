"""Template + source invariants for click-to-enlarge images.

The positive half (`data-zoomable` IS rendered) is what arms the feature. The negative
half (it is NOT in the authoring templates or the drag-to-image stage) is the half that
would rot silently — nothing else would notice an editor thumbnail quietly becoming
clickable, or a graded drag interaction gaining a zoom overlay.

Source-level assertions for the negatives on purpose: two of those templates need a
form/formset context to render, and the claim is about what the template *says*, not
about what one particular context happens to produce.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import render_to_string

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = REPO / "templates"

HOOK = "data-zoomable"


def _media(url="/media/x.png"):
    return SimpleNamespace(file=SimpleNamespace(url=url))


def test_fragment_anchor_survives_sanitisation():
    """The e2e Tab-traversal cases anchor on a seeded <a href="#">, and four of them
    would fail for an unrelated reason if the sanitiser dropped a bare fragment href.
    Nothing else in this repo seeds one, so pin it here rather than discovering it in
    Playwright.
    """
    from courses.sanitize import sanitize_html

    assert 'href="#"' in sanitize_html('<p><a href="#">Anchor link</a></p>')


def test_image_element_renders_the_hook():
    el = SimpleNamespace(media=_media(), alt="A labelled diagram", figcaption="")
    html = render_to_string("courses/elements/imageelement.html", {"el": el})
    assert HOOK in html


def test_gallery_figure_renders_the_hook():
    html = render_to_string(
        "courses/elements/galleryelement.html",
        {
            "figures": [{"url": "/media/a.png", "alt": "A", "desc": ""}],
            "desc_pos": "below",
        },
    )
    assert HOOK in html


def test_filltable_image_cell_renders_the_hook():
    html = render_to_string(
        "courses/elements/_filltable_cell.html",
        {"cell": {"kind": "image", "media": _media("/media/c.png"), "alt": "Cell"}},
    )
    assert HOOK in html


# Authoring thumbnails and the graded drag-to-image stage must never be armed.
NEVER_ARMED = [
    "courses/manage/editor/_edit_filltable.html",
    "courses/manage/editor/_edit_gallery.html",
    "courses/elements/dragtoimagequestionelement.html",
]


def test_authoring_and_dragimage_templates_have_no_hook():
    for rel in NEVER_ARMED:
        source = (TEMPLATES / rel).read_text(encoding="utf-8")
        assert HOOK not in source, rel


TOKENS_CSS = REPO / "core" / "static" / "core" / "css" / "tokens.css"
COURSES_CSS = REPO / "courses" / "static" / "courses" / "css" / "courses.css"

# Match DECLARATIONS, not substring occurrences: tokens.css also carries a comment
# explaining why this token is deliberately not repeated for dark, and a comment that
# names its own subject must not break the count.
SCRIM_DECL = re.compile(r"--scrim-solid\s*:")


def test_scrim_token_is_declared_once_and_never_in_the_dark_block():
    source = TOKENS_CSS.read_text(encoding="utf-8")
    decls = list(SCRIM_DECL.finditer(source))
    assert len(decls) == 1, f"expected one --scrim-solid declaration, got {len(decls)}"
    # The absence from the dark block IS the light/dark mechanism; this catches a
    # *relocated* definition, which the count alone would not.
    #
    # Anchor on the SELECTOR, not the first occurrence of the string: the comment this
    # token ships with names the `[data-theme="dark"]` block in prose, and that mention
    # sits ABOVE the declaration it documents -- so a plain str.index would find the
    # comment and the assertion would fail for a reason unrelated to the invariant.
    dark_selector = re.search(r'^\[data-theme="dark"\]\s*\{', source, re.MULTILINE)
    assert dark_selector, "tokens.css must still have a dark-theme block"
    assert decls[0].start() < dark_selector.start()


def test_closed_dialog_is_display_none_and_box_rules_are_open_scoped():
    source = COURSES_CSS.read_text(encoding="utf-8")
    assert "dialog.imgzoom:not([open]) { display: none; }" in source
    # Any `display` on the dialog must be [open]-scoped, or it beats the guard above
    # and leaves the overlay permanently covering the page.
    assert ".imgzoom[open] {" in source
    assert re.search(r"^\.imgzoom\s*\{", source, re.MULTILINE) is None


def test_overlay_image_can_only_shrink():
    source = COURSES_CSS.read_text(encoding="utf-8")
    assert ".imgzoom__img { max-width: 100%; max-height: 100%;" in source
    # No 100vw anywhere in the overlay block: vw includes the classic scrollbar.
    block = source[source.index(".imgzoom-trigger") :]
    assert "100vw" not in block
