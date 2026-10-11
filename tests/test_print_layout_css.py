"""Source tests for the unit print layout (spec test 3).

Both new blocks are APPENDED to their sheets and found by their marker comment,
so each screen rule they override is provably earlier in the file.
"""

import re
from pathlib import Path

from tests.print_css_kit import all_print_css
from tests.print_css_kit import rule_selectors

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "core/static/core/css/app.css").read_text(encoding="utf-8")
APP_MARK = "/* == Print page frame (spec 2026-10-11-print-layout-for-units) == */"


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _after(css, marker):
    """(marker index, comment-free text of everything from the marker on)."""
    i = css.find(marker)
    assert i >= 0, f"marker missing: {marker}"
    return i, _strip_comments(css[i:])


def _before(css, anchor, i):
    """Last occurrence of `anchor` strictly BEFORE index i (the new block itself
    repeats several screen selectors, so a whole-file rfind would find those)."""
    j = css.rfind(anchor, 0, i)
    assert j >= 0, f"screen anchor not found before the print block: {anchor!r}"
    return j


def _hides_are_important(block):
    bad = re.findall(r"display:\s*none(?!\s*!important)", block)
    assert not bad, f"print hide without !important: {bad}"


def test_page_margin():
    # Global safe margin for every page; the units' wider sides (D10) live in
    # the unit-only print header partial so wide non-unit pages keep 180mm.
    assert re.search(r"@page\s*\{\s*margin:\s*15mm;\s*\}", APP)
    partial = (ROOT / "templates/courses/_print_page_header.html").read_text(
        encoding="utf-8"
    )
    assert re.search(r"margin:\s*15mm 25mm;", partial)


def test_app_block_after_screen_rules():
    i, _ = _after(APP, APP_MARK)
    for anchor in (
        ".app-header {",
        ".app-header__cluster {",
        ".app-main {",
        "  .app-header { flex-wrap: wrap;",
        "  .app-main { padding: var(--space-5)",
    ):
        _before(APP, anchor, i)
    # Nothing after the block may restyle these (the block must be LAST for them).
    tail = _strip_comments(APP[i:])
    assert tail.count(".app-main {") == 1 and tail.count(".app-header {") == 1


HIDE = r"\s*\{\s*display:\s*none\s*!important"


def test_app_block_contents():
    _, block = _after(APP, APP_MARK)
    _hides_are_important(block)
    assert re.search(r"\.app-header__spacer,\s*\.app-header__cluster" + HIDE, block)
    assert re.search(r"\.alert--flash" + HIDE, block)
    assert re.search(r"\.app-header\s*\{[^}]*background:\s*none[^}]*border:\s*0", block)
    assert re.search(r"\.app-main\s*\{[^}]*padding:\s*0[^}]*max-width:\s*none", block)


COURSES = (ROOT / "courses/static/courses/css/courses.css").read_text(encoding="utf-8")
COURSES_MARK = (
    "/* == Print layout for units (spec 2026-10-11-print-layout-for-units) == */"
)
TEMPLATES = "\n".join(
    p.read_text(encoding="utf-8") for p in (ROOT / "templates/courses").rglob("*.html")
)
EXTRAS = (ROOT / "courses/templatetags/courses_extras.py").read_text(encoding="utf-8")
GALLERY_JS = (ROOT / "courses/static/courses/js/gallery.js").read_text(encoding="utf-8")

CHROME_HIDES = [
    ".unit-foot",
    ".unit-tree",
    ".unit-drawer",
    ".unit-strip",
    ".draft-banner",
    ".unit-done",
    ".lesson-unit__reset",
    ".quiz-finish",
    ".quiz-results > .btn",
    '.el--question .question__form button[type="submit"]',
]
ACTION_HIDES = [
    # Only the NON-gate fill table's Check is a control; a gated table's Check is
    # the marker that more content waits behind it (D8).
    ".filltable:not([data-filltablegate]) .filltable__confirm",
    ".markdone__save",
    ".switchgrid__confirm",
    "[data-guess-check]",
    # D8: an opened spoiler's "Hide" toggle is a control, not a marker.
    "details.spoiler[open] > .spoiler__toggle",
]


def _courses_block():
    i, block = _after(COURSES, COURSES_MARK)
    return i, block


def _rule_selectors(block, decl_regex):
    """Selectors of every rule in `block` whose body matches decl_regex.

    `block` comes from _after(), which has already stripped /* comments */ — a
    comment before a rule would otherwise be glued onto its first selector."""
    block = _strip_comments(block)
    sels = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", block):
        if re.search(decl_regex, m.group(2)):
            sels += [s.strip() for s in m.group(1).split(",")]
    return sels


def test_courses_block_hides_are_important():
    _, block = _courses_block()
    _hides_are_important(block)


def test_chrome_and_action_hides_present():
    _, block = _courses_block()
    hidden = _rule_selectors(block, r"display:\s*none\s*!important")
    for sel in CHROME_HIDES + ACTION_HIDES:
        assert sel in hidden, f"{sel} not hidden in print"


def test_action_hide_names_exist_in_source():
    src = TEMPLATES + EXTRAS
    for name in [
        "filltable__confirm",
        "data-filltablegate",
        "spoiler__toggle",
        "callout__header",
        "markdone__save",
        "fillgate__confirm",
        "stepper__next",
        "switchgate__confirm",
        "switchgrid__confirm",
        "data-guess-check",
        "unit-done",
        "lesson-unit__reset",
        "quiz-finish",
        "draft-banner",
        "unit-strip",
    ]:
        assert name in src, f"{name} matches nothing in templates/templatetags"


def test_no_print_rule_reveals_gated_content():
    """D8: no print block in either sheet may force unrevealed content visible:
    no stepper step, no reveal-armed pre-hidden block, no hidden gated child."""
    printed = all_print_css()
    revealing = rule_selectors(printed, r"display:\s*(revert|block)")
    for sel in revealing:
        assert "stepper-step" not in sel, f"{sel} force-reveals steps in print"
        assert ".reveal-armed" not in sel, f"{sel} overrides the reveal pre-hide"
        assert "__child[hidden]" not in sel, f"{sel} un-hides a gated child"


# Every gate family's class/attribute name (D8). A print rule whose selector
# mentions any of these and hides something would hide a marker or the
# student's gated work -- whatever the exact selector spelling.
GATE_TOKENS = (
    "reveal-gate",
    "fillgate",
    "switchgate",
    "filltablegate",
    "stepper__next",
)


def test_gate_markers_are_not_hidden_in_print():
    """D8: the button that would reveal more prints as the marker."""
    hidden = rule_selectors(all_print_css(), r"display:\s*none")
    for sel in hidden:
        if sel == ".filltable:not([data-filltablegate]) .filltable__confirm":
            continue  # the NON-gate table's self-check (allowed control)
        for token in GATE_TOKENS:
            assert token not in sel, f"print hides gate-related {sel!r}"
        if "filltable__confirm" in sel:
            raise AssertionError(f"{sel!r} also hides a gated table's Check")


def test_callouts_keep_together():
    """D9: a callout moves whole to the next page rather than leaving its
    heading alone at the bottom; one taller than a page keeps its heading
    with its first child. A summary ("W skrócie") callout has no header
    wrapper -- its h3.callout__title takes that place."""
    _, block = _courses_block()
    assert ".callout" in _rule_selectors(block, r"break-inside:\s*avoid")
    after = _rule_selectors(block, r"break-after:\s*avoid")
    assert ".callout__header" in after
    assert ".callout__title" in after


def test_unit_shell_block_is_scoped():
    _, block = _courses_block()
    blocks = _rule_selectors(block, r"display:\s*block")
    assert "[data-unit-shell]" in blocks
    assert "[data-unit-shell] > .unit-shell__main" in blocks
    assert ".unit-shell" not in blocks  # review_submission.html reuses .unit-shell


STEPPER_SCREEN_HIDE = (
    ".stepper.is-stepping [data-stepper-step]:not(.stepper-shown)"
    " { display: none !important; }"
)


def test_courses_block_after_screen_rules():
    i, _ = _courses_block()
    for anchor in (
        ".unit-shell { display: flex;",
        "  .unit-shell { display: block; }",
        STEPPER_SCREEN_HIDE,
        ".unit-strip { display: flex;",
        ".draft-banner {",
    ):
        _before(COURSES, anchor, i)


D6_AVOID = [
    ".el--image",
    ".el--gallery .gallery__item",
    "img.cell-img",
    ".dragimage__stage",
    ".el--question",
    ".quiz-results__item",
]


def test_d6_break_inside_list():
    _, block = _courses_block()
    avoid = _rule_selectors(block, r"break-inside:\s*avoid")
    for sel in D6_AVOID:
        assert sel in avoid, f"{sel} missing from break-inside: avoid"
    assert ".el__qnum" in _rule_selectors(block, r"break-after:\s*avoid")


def test_d6_class_names_exist():
    src = TEMPLATES + GALLERY_JS
    for name in (
        "el--image",
        "gallery__item",
        "cell-img",
        "dragimage__stage",
        "el--question",
        "quiz-results__item",
        "el__qnum",
        "gallery__bar",
        "gallery__status",
        "gallery__stage",
        "gallery--js",
    ):
        assert name in src, f"{name} matches nothing"


def test_d6_caps():
    _, block = _courses_block()
    assert ".dragimage__img" in _rule_selectors(block, r"max-height:\s*170mm")
    assert ".el--gallery .gallery__frame" in _rule_selectors(
        block, r"max-height:\s*170mm"
    )


def _decl(block, selector):
    """Body of the rule whose selector list contains exactly `selector`."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(block)):
        if selector in [s.strip() for s in m.group(1).split(",")]:
            return m.group(2)
    raise AssertionError(f"no rule for {selector}")


def test_gallery_carousel_reset():
    _, block = _courses_block()
    item = _decl(block, ".el--gallery.gallery--js .gallery__item")
    assert re.search(r"position:\s*static\s*!important", item)
    assert re.search(r"opacity:\s*1\s*!important", item)
    stage = _decl(block, ".el--gallery.gallery--js .gallery__stage")
    assert re.search(r"position:\s*static\s*!important", stage)
    assert re.search(r"min-height:\s*0\s*!important", stage)
    desc = _decl(block, ".el--gallery.gallery--js .gallery__desc")
    assert re.search(r"min-height:\s*0\s*!important", desc)
    hidden = _rule_selectors(block, r"display:\s*none\s*!important")
    assert ".el--gallery .gallery__bar" in hidden
    assert ".el--gallery .gallery__status" in hidden


def test_d6_block_after_screen_rules():
    i, _ = _courses_block()
    for anchor in (
        ".dragimage__img {",
        ".el--gallery .gallery__frame {",
        ".el--gallery.gallery--js .gallery__item {",
    ):
        _before(COURSES, anchor, i)
