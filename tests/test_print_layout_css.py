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
