"""Guard: the colour glue in table_editor.js/filltable_editor.js is unprotected by
issue #169's twin-drift guard.

test_editor_twin_drift.py classifies only NAMED `function name(...)` definitions
(see its own docstring). The colour glue added on top -- the `serialize()` colour
pass, the `input` listener's colour branch, and the toolbar click handler's colour
branch -- lives inside INLINE ANONYMOUS callbacks (`function (e) { ... }` handed
straight to `addEventListener`), which #169's extractor never sees at all. Without a
guard here, a future edit to one twin's colour branch (fixing a bug, say) could land
in only one file and neither #169 nor either editor's own tests would notice, because
neither editor's suite exercises the other file.

This mirrors test_text_colour_toolbars.py's approach for the shared template partial:
read the raw source, assert textually rather than parsing JS.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE_JS = ROOT / "courses/static/courses/js/table_editor.js"
FILL_JS = ROOT / "courses/static/courses/js/filltable_editor.js"
JS_DIR = ROOT / "courses/static/courses/js"


def _dedent(lines):
    """Strip leading/trailing whitespace per line and drop blank lines -- the two
    files sit at different nesting depths (filltable's input-listener colour branch
    is one level deeper, wrapped in an extra `if`), so raw indentation must not be
    part of the comparison."""
    return [ln.strip() for ln in lines if ln.strip()]


def _brace_block(text, anchor):
    """Lines from the line containing `anchor` through the line that balances its
    first `{`. Not a JS parser -- brace-counts on raw text, same approach as
    test_editor_twin_drift.py's `_functions`. Good enough here because neither
    extracted block contains a string, regex or template literal with an unbalanced
    brace."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if anchor in ln)
    depth, started, out = 0, False, []
    for ln in lines[start:]:
        out.append(ln)
        depth += ln.count("{") - ln.count("}")
        if "{" in ln:
            started = True
        if started and depth <= 0:
            break
    return out


def _line(text, needle):
    """The single line containing `needle`, stripped -- for one-line glue sites."""
    for ln in text.splitlines():
        if needle in ln:
            return ln.strip()
    raise AssertionError(f"{needle!r} not found")


def _table_and_fill():
    return TABLE_JS.read_text(encoding="utf-8"), FILL_JS.read_text(encoding="utf-8")


def test_serialize_colour_pass_is_identical():
    """Both editors' serialize() must call mapColours the same way on every cell
    before reading its innerHTML, or one editor could silently serialize an
    unmapped inline colour that the other strips."""
    table, fill = _table_and_fill()
    needle = "window.libliColour.mapColours(td, { dropUnmapped: true })"
    assert _line(table, needle) == _line(fill, needle)


def test_input_listener_colour_branch_is_identical():
    """The isApplying() guard, the mapColours call and the paste-triggered
    tidyPastedSpans call inside each grid's `input` listener must stay identical --
    this is the re-entrancy defect both editors' own e2e regression tests
    (test_clear_through_the_wired_toolbar_removes_the_class and its cell twin)
    exist to catch, and #169 cannot see this branch at all."""
    table, fill = _table_and_fill()
    anchor = "if (window.libliColour && window.libliColour.isApplying()) return;"
    end_needle = "serialize();"

    def _branch(text):
        lines = text.splitlines()
        start = next(i for i, ln in enumerate(lines) if anchor in ln)
        end = next(i for i in range(start, len(lines)) if end_needle in lines[i])
        return _dedent(lines[start : end + 1])

    a, b = _branch(table), _branch(fill)
    assert a == b, (
        "the input listener's colour branch drifted between table_editor.js and "
        f"filltable_editor.js:\n{a}\nvs\n{b}"
    )


def test_toolbar_colour_branch_is_identical():
    """The `data-cmd="colour-*"` dispatch -- slot derivation, the styleWithCSS
    comment, the apply()/serialize() call pair -- must stay identical in both
    toolbar click handlers."""
    table, fill = _table_and_fill()
    anchor = 'if (cmd.indexOf("colour-") === 0 && window.libliColour) {'
    a = _dedent(_brace_block(table, anchor))
    b = _dedent(_brace_block(fill, anchor))
    assert a == b, (
        "the toolbar colour branch drifted between table_editor.js and "
        f"filltable_editor.js:\n{a}\nvs\n{b}"
    )


def _input_listener_bodies(text):
    """Every anonymous `addEventListener("input", function (...) { ... })` callback
    body in `text`, as a raw source slice. Named-function listeners (`addEventListener
    ("input", sync)`) are deliberately not matched -- none of the three known colour
    consumers uses one, and a body-less reference has no branch to check anyway."""
    bodies = []
    pattern = re.compile(
        r"""addEventListener\(\s*['"]input['"]\s*,\s*function\s*\([^)]*\)\s*\{"""
    )
    for m in pattern.finditer(text):
        start = m.end() - 1  # index of the opening '{'
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        bodies.append(text[start : i + 1])
    return bodies


_TRAILING_COMMENT = re.compile(r"//.*$")


def _code_only(body):
    """Strip `//` trailing comments per line before searching for a call
    expression -- otherwise a comment merely NAMING `isApplying()` (as the guard
    comment above every real call site does) satisfies a naive substring search
    with no call present at all. MEASURED: the first draft of this guard's own
    falsification probe proved this -- replacing the real `isApplying()` call with
    a comment saying "isApplying() check removed" left the naive check GREEN."""
    return "\n".join(_TRAILING_COMMENT.sub("", ln) for ln in body.splitlines())


def test_every_mapcolours_input_caller_also_guards_with_isapplying():
    """The opt-in contract documented at text_colour.js:22-27: an `input` listener
    that calls mapColours MUST check isApplying() first, or apply()'s own
    execCommand re-entrantly fires that same `input` event and strips the SENTINEL
    marker before apply() ever finds it (see the "Re-entrancy guard" comment at the
    top of text_colour.js). That defect shipped once already, caught only by an e2e
    test driving the real wired toolbar -- not by any unwired unit test. Scanning
    every JS file, not just the three known consumers (text_toolbar.js,
    table_editor.js, filltable_editor.js), is what would catch a FOURTH caller that
    forgets the guard."""
    problems = []
    for path in sorted(JS_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for body in _input_listener_bodies(text):
            code = _code_only(body)
            if "mapColours(" in code and "isApplying()" not in code:
                problems.append(
                    f"{path.name}: an input-listener callback calls mapColours() "
                    f"without also calling isApplying() first:\n{body}"
                )
    assert not problems, "\n\n".join(problems)


def test_three_known_consumers_are_exactly_the_ones_found():
    """Pins the consumer set so a passing run above cannot be silently vacuous (e.g.
    the regex stopped matching and found zero listeners in every file)."""
    found = set()
    for path in sorted(JS_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for body in _input_listener_bodies(text):
            if "mapColours(" in _code_only(body):
                found.add(path.name)
    assert found == {"text_toolbar.js", "table_editor.js", "filltable_editor.js"}, found
