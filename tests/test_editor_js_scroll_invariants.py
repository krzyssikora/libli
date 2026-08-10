"""Source-level invariant: no scrollIntoView from inside the unit editor's panes.

At >=70rem the editor page is `height:100vh; overflow:hidden` (editor.css), which
PROPAGATES to the viewport — script and the UA can scroll the page, the author
cannot scroll it back. `scrollIntoView` scrolls every scrollport up the chain, so
one call from a module whose content lives inside a `.pane-body` strands the unit
header off-screen until a reload. editor.js exposes `window.libliAlignTopInPane`
for this; it moves the pane and nothing else.

The behavioural counterpart (fill-in table validation) lives in
tests/test_e2e_editor_scroll_containment.py; this file is what keeps the other
pane-resident modules from re-introducing the same call, since none of them has
an e2e test of its own for it.
"""

import re
from pathlib import Path

JS_DIR = (
    Path(__file__).resolve().parent.parent / "courses" / "static" / "courses" / "js"
)

# Modules that render or mutate authoring UI INSIDE a scrolling .pane-body.
PANE_RESIDENT = [
    "editor.js",
    "filltable_editor.js",
    "switchgrid_editor.js",
    "table_editor.js",
    "gallery_editor.js",
    "tabs_editor.js",
    "choicegrid.js",
    "multigrid.js",
    "zone-editor.js",
    "text_toolbar.js",
    "html_element.js",
    "code_field.js",
    "editor_dnd.js",
    "formset_rows.js",
]

# A CALL, not a mention: the explanatory comments in these files name
# scrollIntoView deliberately and must not redden the suite.
CALL = re.compile(r"\.scrollIntoView\s*\(")


def test_no_scrollintoview_in_pane_resident_editor_modules():
    offenders = {}
    for name in PANE_RESIDENT:
        path = JS_DIR / name
        assert path.exists(), f"{name} moved or was renamed — update PANE_RESIDENT"
        hits = [
            i
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if CALL.search(line)
        ]
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"scrollIntoView called from inside the editor panes at {offenders}. "
        "It scrolls the page viewport too, and the editor page's viewport is "
        "overflow:hidden — the author cannot scroll back. Use "
        "window.libliAlignTopInPane(el) instead."
    )


def test_editor_exposes_the_pane_scoped_helper():
    source = (JS_DIR / "editor.js").read_text(encoding="utf-8")
    assert "window.libliAlignTopInPane = alignTopInPane" in source, (
        "editor.js must expose alignTopInPane as window.libliAlignTopInPane — "
        "filltable_editor.js and switchgrid_editor.js call it by that name."
    )


# Bare focus() scrolls every ancestor scrollport, and this page's viewport is
# overflow:hidden. Scoped to the two NEW modules on purpose: 19 pre-existing call
# sites across filltable_editor.js, table_editor.js, gallery_editor.js,
# text_toolbar.js and tabs_editor.js would make a repo-wide version RED on arrival,
# and fixing those is separate work.
FOCUS_OPT_IN = ["formset_rows.js", "switchgate_editor.js"]
FOCUS_CALL = re.compile(r"\.focus\s*\(")


def test_new_modules_never_focus_without_preventscroll():
    """A positive, line-level check: flag any line that CALLS .focus( without also
    mentioning preventScroll. Deliberately not a negative lookahead like
    `\\.focus\\s*\\(\\s*(?!\\{[^)]*preventScroll)` — that form is spacing-sensitive
    (it false-positives on `focus( { preventScroll: true } )`, because `\\s*`
    backtracks to zero and the lookahead then tests a space instead of the brace).
    Comment lines are skipped: filltable_editor.js and unit_nav.js discuss .focus()
    in prose, the mention-vs-call hazard the file's existing CALL comment warns of."""
    offenders = {}
    for name in FOCUS_OPT_IN:
        path = JS_DIR / name
        if not path.exists():
            continue  # module lands in a later task
        hits = [
            i
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if FOCUS_CALL.search(line)
            and "preventScroll" not in line
            and not line.strip().startswith("//")
            and not line.strip().startswith("*")
        ]
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"bare focus() in {offenders}: use focus({{ preventScroll: true }}) — "
        "the editor viewport is overflow:hidden, so a scrolling focus strands the "
        "author"
    )
