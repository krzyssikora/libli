"""Template + source invariants for click-to-enlarge images.

The positive half (`data-zoomable` IS rendered) is what arms the feature. The negative
half (it is NOT in the authoring templates or the drag-to-image stage) is the half that
would rot silently — nothing else would notice an editor thumbnail quietly becoming
clickable, or a graded drag interaction gaining a zoom overlay.

Source-level assertions for the negatives on purpose: two of those templates need a
form/formset context to render, and the claim is about what the template *says*, not
about what one particular context happens to produce.
"""

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
