"""Guard: the 20 functions duplicated across the two table editors must not drift.

`table_editor.js` and `filltable_editor.js` share 163 lines of code-identical
logic across 20 functions -- 11 at file scope, 9 nested inside `wire()`. Nothing
else enforces that they stay in step, so the realistic failure is silent: a
selection bug gets fixed in one editor, its twin is missed, and each editor's own
tests stay green because neither exercises the other's file.

This does NOT remove the duplication. Extraction was considered and rejected in
the spec: the nested twins are closures over `wire()`'s locals and MUTATE
selection state, so lifting them means routing that state through an object and
rewriting ~1,180 lines of both `wire()` bodies. This guard is the cheaper move
that addresses the actual risk, and would be the safety net if extraction is ever
done later.

The contract is a CLASSIFICATION, not a list: every function name present in both
files must appear in exactly one of TWINS or DIVERGENT. That is what stops the
guard rotting -- a new shared helper forces a decision instead of silently
becoming a 21st unguarded twin.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE_JS = ROOT / "courses" / "static" / "courses" / "js" / "table_editor.js"
FILL_JS = ROOT / "courses" / "static" / "courses" / "js" / "filltable_editor.js"

# Total `function name(…)` definitions per file, at ALL nesting depths.
#
# Asserted so a regex regression fails loudly instead of silently extracting
# nothing -- every comparison below trivially passes over an empty set. Counting
# EVERY function, not just the 20 twins, is deliberate: if extraction silently
# missed a newly added shared helper in one file, that name would never look
# "common to both" and the classification check would stay green while an
# unguarded 21st twin existed.
EXPECTED_COUNTS = {TABLE_JS: 28, FILL_JS: 36}

_DEF = re.compile(r"^\s*function (\w+)\s*\(")
_TRAILING_COMMENT = re.compile(r"\s*//.*$")
_ESCAPED = re.compile(r"\\.")


def _functions(path):
    """Every `function name(…)` in the file, mapped to its raw body lines.

    Scans forward independently from each definition rather than consuming
    bodies, so functions nested inside `wire()` are captured alongside
    file-scope ones -- the duplication this guard exists to catch lives at both
    levels.

    Bodies are delimited by counting braces, which is not a JS parser. Four
    things can contribute a non-structural brace: a string literal, a regex
    literal, a template string, and a comment. The first three do not occur in
    either editor; the fourth does (`{% trans %}`, `LAYOUT {r, c}`) but every
    such comment is brace-BALANCED on its own line, so the running count is
    undisturbed. An unbalanced one would swallow the rest of the file and
    collapse the count, which EXPECTED_COUNTS catches.

    Raises on a duplicate name rather than silently keeping the last definition
    and comparing the wrong pair.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    out = {}
    for i, line in enumerate(lines):
        m = _DEF.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in out:
            raise ValueError(
                f"{path.name}: duplicate function name {name!r}; this guard keys "
                f"functions by name and cannot compare the right pair"
            )
        depth, started, body = 0, False, []
        for ln in lines[i:]:
            body.append(ln)
            depth += ln.count("{") - ln.count("}")
            if "{" in ln:
                started = True
            if started and depth <= 0:
                break
        out[name] = body
    return out


def _normalise(body):
    """Body lines reduced to code tokens: no blank lines, no comments, no indent.

    Comments are stripped because three twins -- newCell, rebuildColControls and
    dataCells -- have byte-identical CODE and differ only in that one file
    carries an extra explanatory comment. Comparing raw text would file all three
    as deliberate divergences, parking 29 lines of genuine twin code in the list
    that means "nobody checks these". Each editor should be free to explain
    itself in its own words.

    Indentation is dropped as a side effect, which is required anyway: file-scope
    twins sit at two-space indent and nested ones at four.
    """
    out = []
    for ln in body:
        s = ln.strip()
        if not s or s.startswith("//"):
            continue
        s = _TRAILING_COMMENT.sub("", s).strip()
        if s:
            out.append(s)
    return out


def _hazards(name, body):
    """Lines that would make _normalise() silently WRONG rather than merely wrong.

    A `//` inside a string literal (`var u = "http://x"`) gets truncated by the
    naive stripper, so two genuinely different lines can normalise to the same
    prefix and compare EQUAL -- the guard then reports success while missing real
    drift. Unlike a broken extractor, nothing else detects this: normalisation
    runs after extraction and leaves EXPECTED_COUNTS untouched.

    Neither condition occurs today. Every `//` in both files is a real comment
    that merely FOLLOWS a string on the same line, and every backtick sits inside
    comment prose rather than being a template literal. Rather than write a
    JS-aware tokeniser for a case that does not exist, this fails loudly if one
    is ever introduced, so the stripper can be made quote-aware first.

    Scoped to twin bodies only -- normalisation is applied nowhere else, and a
    whole-file scan would fail CI over an edit to a fill-table-only helper that
    has no twin to drift from.
    """
    problems = []
    for ln in body:
        idx = ln.find("//")
        if idx != -1:
            before = _ESCAPED.sub("", ln[:idx])
            if before.count('"') % 2 or before.count("'") % 2:
                problems.append(f"{name}: `//` inside a string literal: {ln.strip()!r}")
    for s in _normalise(body):
        if "`" in s:
            problems.append(f"{name}: template literal in code: {s!r}")
    return problems


# Code-identical in both editors. 11 at file scope, 9 nested inside wire().
TWINS = [
    # file scope
    "colCount",
    "colCtl",
    "dataCells",
    "dataRows",
    "ensureRowControls",
    "handleBtn",
    "newCell",
    "rebuildColControls",
    "refreshControlState",
    "rowCtl",
    "tableContainer",
    # nested inside wire()
    "absorbedNonEmpty",
    "clearRange",
    "headerLocked",
    "msg",
    "paintRange",
    "refreshAlignButtons",
    "refreshHeaderButton",
    "say",
    "tooBig",
]

# Deliberately different, with the reason. Each was verified against a full diff
# of the two bodies -- five of these reasons were wrong on first writing, each by
# naming only the most prominent difference and missing a second.
DIVERGENT = {
    "label": "closes over a different editor root attribute "
    "([data-table-editor] vs [data-filltable-editor])",
    "wire": "the container itself; its nested helpers are classified "
    "individually, so comparing the two bodies would be meaningless",
    "serialize": "fill-table emits three cell kinds (static/answer/image) where "
    "the plain table emits one, AND its payload carries two extra "
    "document-level fields, case_sensitive and prompt",
    "refreshToolbarState": "fill-table adds an `if (!focusCell) return` gate "
    "AFTER the merge/split/header block, so the kind-specific refresh is "
    "skipped with nothing focused; that also moves refreshAlignButtons() "
    "behind the gate",
    "toggleHeaderCell": "fill-table re-keys the live cellStash Map old->new, AND "
    "focuses the cell's answer input rather than the cell -- .focus() is a "
    "no-op on a <td data-answer>, which would strand Alt+Shift+Arrow",
    "cellIsNonEmpty": "BOTH files are image-aware by different mechanisms (the "
    "plain table queries for a nested <img>, fill-table checks the data-image "
    "attribute); fill-table also treats answer cells as always non-empty",
    "afterStructuralEdit": "fill-table additionally calls cellStash.clear() "
    "first, so a stashed cell cannot restore into the wrong node after reshape",
}


def _common():
    table, fill = _functions(TABLE_JS), _functions(FILL_JS)
    return table, fill, sorted(set(table) & set(fill))


def test_expected_function_counts():
    # Collect across both files before asserting, so a single run reports every
    # mismatch rather than aborting on the first -- a bare `assert` inside the
    # loop would hide the second file's count.
    problems = []
    for path, expected in EXPECTED_COUNTS.items():
        found = _functions(path)
        if len(found) != expected:
            problems.append(
                f"{path.name}: extracted {len(found)} functions, expected "
                f"{expected}; the extractor regex has probably stopped matching, "
                f"so every comparison in this file would pass vacuously. Found: "
                f"{sorted(found)}"
            )
    assert not problems, "\n".join(problems)


def test_no_duplicate_function_names():
    # _functions raises on a duplicate; calling it on both files is the check.
    _functions(TABLE_JS)
    _functions(FILL_JS)


def test_classifications_are_disjoint():
    both = sorted(set(TWINS) & set(DIVERGENT))
    assert not both, (
        f"classified as BOTH twin and divergent: {both}. A function belongs in "
        f"exactly one list — converging a divergent function means MOVING it to "
        f"TWINS, not adding it there."
    )


def test_every_common_function_is_classified():
    _t, _f, common = _common()
    unclassified = [n for n in common if n not in TWINS and n not in DIVERGENT]
    assert not unclassified, (
        f"present in both editors but classified in neither list: "
        f"{unclassified}. Add each to TWINS (must stay identical) or to "
        f"DIVERGENT (with the reason it differs)."
    )


def test_no_stale_classification():
    _t, _f, common = _common()
    stale = [n for n in list(TWINS) + list(DIVERGENT) if n not in common]
    assert not stale, (
        f"classified but no longer a function in BOTH editors: {stale}. Remove "
        f"the entry — a stale name would be silently inherited by any later "
        f"function that reused it, pre-excusing a real twin."
    )


def test_no_normalisation_hazard_in_twin_bodies():
    table, fill, _c = _common()
    problems = []
    for name in TWINS:
        problems += _hazards(f"table_editor.js:{name}", table[name])
        problems += _hazards(f"filltable_editor.js:{name}", fill[name])
    assert not problems, (
        "the comment-stripping assumption no longer holds; make _normalise "
        "quote-aware before trusting this guard:\n" + "\n".join(problems)
    )


def test_twins_are_identical():
    table, fill, _c = _common()
    problems = []
    for name in TWINS:
        a, b = _normalise(table[name]), _normalise(fill[name])
        if a == b:
            continue
        first = next(
            (i for i in range(max(len(a), len(b))) if a[i : i + 1] != b[i : i + 1]),
            0,
        )
        problems.append(
            f"{name}: drifted at line {first + 1} of the normalised body\n"
            f"    table_editor.js: {(a[first : first + 1] or ['<missing>'])[0]}\n"
            f"    filltable_editor.js: {(b[first : first + 1] or ['<missing>'])[0]}"
        )
    assert not problems, (
        "these functions are duplicated in both editors and must stay "
        "identical:\n" + "\n".join(problems)
    )
