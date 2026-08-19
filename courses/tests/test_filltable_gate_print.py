"""The @media print gate-hiding rule must not swallow a gated fill-table.

For the three control-shaped gate families the node carrying [data-reveal-gate]
is a button / blanks form / cycler, and hiding it on paper is right. For a
fill-table that node IS the student's work, so the bare selector would delete
the whole table from every printout.
"""

import re
from pathlib import Path

CSS = Path("core/static/core/css/app.css").read_text(encoding="utf-8")
COURSES_CSS = Path("courses/static/courses/css/courses.css").read_text(encoding="utf-8")


def _strip_comments(css):
    # Mirrors courses/tests/test_beforeafter_css.py:14-18. Step 9 adds a CSS
    # COMMENT directly above the rule these assertions look for, and both
    # assertions below scan raw text: a comment mentioning the carve-out
    # selector would satisfy the positive one, and a rewrap that put
    # `[data-reveal-gate]` at the start of a comment line would falsify the
    # negative one on a CORRECT build. Strip comments so neither can happen.
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _print_block(css):
    m = re.search(r"@media print\s*\{(.*?)\n\}", _strip_comments(css), re.S)
    assert m, "no @media print block in app.css"
    return m.group(1)


def test_courses_css_crossref_clause_stays_inside_its_comment():
    # Guards Step 10's edit. That clause is appended to a comment whose closing
    # `*/` sits on the very line being replaced, and a real @media print block
    # (.ba__panel[hidden] et al) begins on the NEXT line -- so a literal append
    # after the terminator emits bare text at top level directly above it.
    #
    # Deliberately NOT an "@media print block still parses" regex: a comment
    # terminator is invisible to a regex, so the block would still match on a
    # broken file and the assertion could not fail. courses.css also holds TEN
    # @media print blocks, so a first-match regex reads the wrong one anyway.
    #
    # Reads COURSES_CSS RAW, deliberately -- do NOT route it through
    # _strip_comments(), which exists for the app.css assertions below. This
    # test's whole subject is text INSIDE a comment; stripping them first
    # would leave it asserting on an empty string.
    i = COURSES_CSS.index("unit-strip__edit are both hidden in print")
    terminator = COURSES_CSS.index("*/", i)
    assert "filltablegate" in COURSES_CSS[i:terminator], (
        "the fill-table carve-out clause landed AFTER the comment's `*/`, "
        "emitting bare text above the @media print block on the next line"
    )


def test_print_hide_rule_excludes_the_filltable_gate():
    block = _print_block(CSS)
    assert re.search(r"\[data-reveal-gate\]:not\(\[data-filltablegate\]\)\s*\{", block)
    # ...and the BARE selector is gone. Boundary-anchored (^ under re.M): the rule
    # starts its own line, so this matches the pre-change text and stops matching
    # after. `}` closes the revert rule on the line directly above (app.css:1136)
    # and is not whitespace, so ^\s* cannot bridge into line 1137 from earlier.
    # A lookbehind-on-colon form was tried and is INERT -- it matches nothing in
    # EITHER state, so it would have been an assertion that could not fail.
    assert not re.search(r"^\s*\[data-reveal-gate\]\s*\{", block, re.M)
