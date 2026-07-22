"""Guard: every selector that can match a DATA cell must also match `th`.

A <th> matched by only half the editors' selectors is un-focusable,
un-alignable and invisible to serialization -- and all 48 `header: true`
cells in the imported corpus live in spanning tables, so this is not a corner
case. Two exemptions, named rather than blanket: chrome selectors scoped by
[data-control], and element construction (createElement("td")).

This test must go RED if any single row of the spec's selector inventory is
reverted."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The spec's selector inventory, as an EXPLICIT list rather than a broad regex.
# A general "any bare `td`" scan is unusable here: it matches the JS variable
# `td` (td.dataset, td.className, td.colSpan), unrelated components
# (.choicegrid td), and even `td.tagName === "TH"` -- 113 false positives
# across these four files. Enumerating the sites keeps the guard honest AND
# keeps it falsifiable, which a whitelist-everything regex would not be.
# Needles are chosen to survive the widening edit itself: `.table-editor__grid
# td` (no trailing brace) still matches after the rule becomes
# `.table-editor__grid td, .table-editor__grid th {`.
INVENTORY = [
    # (file, substring identifying the site, what must appear in its WINDOW)
    ("courses/static/courses/js/table_editor.js", 'querySelectorAll("td', "th"),
    ("courses/static/courses/js/table_editor.js", 'closest("td[contenteditable]', "th"),
    ("courses/static/courses/js/filltable_editor.js", 'querySelectorAll("td', "th"),
    (
        "courses/static/courses/js/filltable_editor.js",
        'closest("td[contenteditable]',
        "th",
    ),
    (
        "courses/static/courses/js/filltable_editor.js",
        "td[data-answer] .filltable-editor__answer",
        "th",
    ),
    ("courses/static/courses/css/editor.css", ".table-editor__grid td", "th"),
    ("courses/static/courses/css/editor.css", ".table-editor__grid td:focus", "th"),
    (
        "courses/static/courses/css/courses.css",
        ".el-editor--filltable .table-editor__grid td",
        "th",
    ),
    (
        "courses/static/courses/css/courses.css",
        ".filltable-editor__grid td[data-answer]",
        "th",
    ),
]

# Exempt by design: CONTROL-CELL chrome selectors (a control cell is never a
# <th>) and element construction. Scoped to `td[data-control]` specifically --
# a bare `data-control` test would also swallow
# `querySelectorAll("td:not([data-control]), th:not([data-control])")`, i.e.
# the correctly-widened dataCells line this guard exists to check.
EXEMPT = re.compile(r"td\[data-control\]|createElement")

# CSS selector lists may be split across lines, so a needle's `th` twin can sit
# on the NEXT line. Check a small window rather than the single matched line.
WINDOW = 2

# `th` as a WHOLE token. A bare substring test is vacuous over a 2-line window:
# editor.css:595 is followed by `min-width: 4rem;` -- which contains "th" -- so
# that row would pass whether or not the selector was ever widened. ("this",
# "them", "path" do the same elsewhere.)
TH_TOKEN = re.compile(r"(?<![a-z])th(?![a-z])")


def test_every_inventoried_data_cell_selector_also_matches_th():
    """Any selector that can match a DATA cell must also match `th`.

    A <th> matched by only half the editors' selectors is un-focusable,
    un-alignable and invisible to serialization -- and all 48 `header: true`
    cells in the imported corpus live in spanning tables, so this is not a
    corner case. Must go RED if any single inventory row is reverted."""
    problems = []
    for rel, needle, _required in INVENTORY:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        hits = [
            i for i, ln in enumerate(lines) if needle in ln and not EXEMPT.search(ln)
        ]
        if not hits:
            problems.append(f"{rel}: inventory line vanished: {needle!r}")
            continue
        for i in hits:
            window = " ".join(lines[i : i + WINDOW]).lower()
            if not TH_TOKEN.search(window):
                problems.append(
                    f"{rel}:{i + 1}: {lines[i].strip()!r} does not also match th"
                )
    assert not problems, "\n".join(problems)
