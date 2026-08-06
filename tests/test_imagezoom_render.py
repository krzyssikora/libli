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


def _js_code_only(source):
    """JS source with comments stripped.

    A source assertion must not be satisfiable by prose. imagezoom.js's comments quote
    unit_nav.js's own `document.addEventListener("keydown", onKeydown, true)` -- so a
    bare `, true)` regex matched the comment and the capture-phase guard passed even
    with capture removed from the real call. Proven by mutation during review.
    """
    no_block = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", no_block)


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
    "courses/manage/editor/_edit_table.html",
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


JS = REPO / "courses" / "static" / "courses" / "js"

PAGES_THAT_ARM = [
    "courses/lesson_unit.html",
    "courses/quiz_unit.html",
    "courses/manage/editor/editor.html",
]


def test_every_arming_page_ships_the_script_and_its_i18n_after_gallery():
    for rel in PAGES_THAT_ARM:
        source = (TEMPLATES / rel).read_text(encoding="utf-8")
        # A script tag without its i18n blob is a live failure mode, so both together.
        assert "IMAGEZOOM_I18N" in source, rel
        assert "courses/js/imagezoom.js" in source, rel
        assert source.index("courses/js/imagezoom.js") > source.index(
            "courses/js/gallery.js"
        ), f"{rel}: imagezoom.js must load after gallery.js"


def test_editor_rearms_the_preview_with_the_same_literal_the_module_exports():
    # A grep of the call site alone cannot catch a typo'd export, so pin both sides.
    editor = (JS / "editor.js").read_text(encoding="utf-8")
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    assert "window.libliInitImageZoom(preview)" in editor
    assert "window.libliInitImageZoom = " in module


def test_close_handler_focuses_the_trigger():
    # The SOLE guard on this line: Chromium focuses the trigger on mousedown, so
    # <dialog>'s native restore satisfies every e2e assertion even with it deleted.
    # The line exists for WebKit, where a click does not focus a non-form element.
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    assert "if (trigger) trigger.focus();" in module


def test_close_handler_removes_src_rather_than_emptying_it():
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    assert 'removeAttribute("src")' in module
    # `img.src = ""` resolves against the document URL and refetches the HTML page as
    # an image on every close.
    assert re.search(r"\.src\s*=\s*([\"'])\1", module) is None


def test_escape_guard_is_capture_phase_and_uses_stop_immediate():
    # unit_nav.js registers its drawer handler as a CAPTURE listener on document, so a
    # bubble-phase listener on the dialog could never stop it, and stopPropagation
    # cannot stop a same-node/same-phase peer.
    code = _js_code_only((JS / "imagezoom.js").read_text(encoding="utf-8"))
    assert "stopImmediatePropagation()" in code
    assert "dialog && dialog.open" in code  # lazily created: null before the first open
    # The capture flag must be the third argument of the SAME call that stops the event,
    # in code rather than in a comment.
    assert re.search(
        r"stopImmediatePropagation\(\);?[\s\S]{0,120}?\},\s*true\s*\)", code
    ), "Escape listener must be registered capture-phase"


def test_gallery_pairs_inert_with_every_item_level_aria_hidden():
    # Routed through _js_code_only: Task 3 had a nearly identical assertion pass
    # against a comment rather than real code (see its docstring), so every new
    # gallery.js source assertion here is checked against comment-stripped code.
    source = _js_code_only((JS / "gallery.js").read_text(encoding="utf-8"))
    # Per-site, not a total count: gallery.js also sets aria-hidden on the indicator
    # and inside an SVG string, neither of which takes inert.
    assert source.count('it.setAttribute("inert", "")') == 2, "rest-init + settleHidden"
    assert 'out.setAttribute("inert", "")' in source, "outgoing item at fade start"
    assert 'inn.removeAttribute("inert")' in source, "incoming item's clear"


def test_gallery_rescues_focus_before_inerting_the_outgoing_item():
    source = _js_code_only((JS / "gallery.js").read_text(encoding="utf-8"))
    assert "function rescueFocus(" in source
    # Must target the ARMED trigger: tabindex comes from imagezoom.js, not the
    # template, so focus() on a bare [data-zoomable] is a no-op when that script is
    # absent -- and gallery descriptions permit <a href>, so focus CAN sit in an
    # outgoing figure even then.
    assert ".imgzoom-trigger" in source
    # Must skip disabled controls: prev/next are disabled at the boundary slides and
    # focus() on a disabled button drops focus to <body>.
    assert "button:not([disabled])" in source
    # The rescue must run BEFORE the outgoing item is inerted -- and the comparison
    # must anchor on the CALL, not the definition: rescueFocus is defined next to
    # settleHidden, i.e. earlier in the file than show(), so str.index would find the
    # definition and be true no matter where the call sits.
    show_at = source.index("function show(")
    call_at = source.index("rescueFocus(out, inn);", show_at)
    inert_at = source.index('out.setAttribute("inert", "")', show_at)
    assert call_at < inert_at
