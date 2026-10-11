"""Source tests for the unit print layout (spec test 3).

Both new blocks are APPENDED to their sheets and found by their marker comment,
so each screen rule they override is provably earlier in the file.
"""

import re
from pathlib import Path

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
    assert re.search(r"@page\s*\{\s*margin:\s*15mm;\s*\}", APP)


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
    ".filltable__confirm",
    ".markdone__save",
    ".fillgate__confirm",
    ".stepper__next",
    ".switchgate__confirm",
    ".switchgrid__confirm",
    "[data-guess-check]",
]
STEPPER_REVEALS = [
    ".stepper.is-stepping [data-stepper-step]:not(.stepper-shown)",
    ".stepper-armed .stepper [data-stepper-step]:not(.stepper-shown):not(:first-child)",
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


def test_stepper_reveal_covers_post_and_pre_boot():
    _, block = _courses_block()
    revealed = _rule_selectors(block, r"display:\s*revert\s*!important")
    for sel in STEPPER_REVEALS:
        assert sel in revealed


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
