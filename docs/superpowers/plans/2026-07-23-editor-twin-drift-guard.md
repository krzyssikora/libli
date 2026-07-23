# Editor Twin-Drift Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-level test that makes drift between the 20 code-identical functions shared by `table_editor.js` and `filltable_editor.js` fail loudly.

**Architecture:** One new test file. It extracts every `function name(…)` body from both editors, normalises away comments and indentation, and enforces a classification contract: every function common to both files is either a declared twin that must stay identical, or a declared divergence with a stated reason. No production code changes.

**Tech Stack:** pytest, Python stdlib only (`re`, `pathlib`).

**Spec:** `docs/superpowers/specs/2026-07-23-editor-twin-drift-guard-design.md` — read it first. It went through 7 review rounds; the divergence reasons and the hazard treatments in particular are load-bearing and were each wrong at least once before being corrected against the real source.

## Global Constraints

- **Tests:** `uv run pytest <paths> -vv`. `ruff`, `pytest` and `python` are **not on PATH** — always `uv run`.
- **Never** set `DJANGO_SETTINGS_MODULE` on a pytest invocation. **Never add `-q`** (`pyproject.toml` already sets `addopts = "-q -m 'not e2e'"`; a single `-v` only cancels it back to default output, so use `-vv` where per-test results must be read). Never pipe pytest through `tail`/`head`.
- **Never** run a bare `-m e2e` sweep. This plan needs no e2e and no database.
- **Lint:** `uv run ruff check .` and `uv run ruff format --check .` must both be clean; CI gates them separately.
- **Stage explicitly by path.** Never `git add -A` or `git add .`.
- **Do not modify `table_editor.js` or `filltable_editor.js`.** Every falsification that edits them is temporary and must be reverted; `git status --porcelain` must show only the new test file when you commit.
- This is a **test-only** change. No migration, no runtime behaviour change.

---

## File Structure

**Created:**
- `tests/test_editor_twin_drift.py` — the extractor, the normaliser, the tripwire, the two classification lists, and the seven checks over them.

**Not modified:** everything else. In particular `courses/static/courses/js/table_editor.js` and `courses/static/courses/js/filltable_editor.js` are read-only inputs.

---

### Task 1: The twin-drift guard

**Files:**
- Create: `tests/test_editor_twin_drift.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_functions(path) -> dict[str, list[str]]` (raw body lines per function name, raising `ValueError` on a duplicate name); `_normalise(body) -> list[str]`; `_hazards(name, body) -> list[str]`; module constants `TWINS` (20 names) and `DIVERGENT` (7 name → reason).

- [ ] **Step 1: Create the file**

```python
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
```

- [ ] **Step 2: Run it green**

```
uv run pytest tests/test_editor_twin_drift.py -vv
```

Expected: 7 passed. This proves only that the guard does not false-positive on the current tree. It proves nothing about whether the guard can *fail* — Steps 3–10 are that proof, and are the substance of this task.

- [ ] **Step 3: Falsify 1 — a twin drifts**

In `filltable_editor.js` only, change one line inside `paintRange` (e.g. `say("range-selected");` → `say("range-cleared");`).

Run: `uv run pytest tests/test_editor_twin_drift.py::test_twins_are_identical -vv`
Expected: FAIL, naming `paintRange` and printing both files' versions of the differing line. **Revert the JS.**

- [ ] **Step 4: Falsify 2 — a new twin goes unclassified**

Append an identical trivial function to each file **after the closing `})();`** — i.e. at true global scope, outside the top-level IIFE that wraps each editor's body. (The "file scope" twins elsewhere sit at 2-space indent *inside* that IIFE; putting the probe outside it avoids any ambiguity and still registers as a `function name(` definition the extractor counts.)

```js
function _driftProbe() {
  return 1;
}
```

Run: `uv run pytest tests/test_editor_twin_drift.py -vv`
Expected: `test_every_common_function_is_classified` FAILS naming `_driftProbe`, **and** `test_expected_function_counts` FAILS naming **both** files (29 vs 28 *and* 37 vs 36 in one message — the test collects both mismatches before asserting) — the count assertion is deliberately sensitive to any new function, classified or not. **Revert both files.**

- [ ] **Step 5: Falsify 3 — a comment-only change must NOT fail**

Add a comment line inside `newCell` in `table_editor.js` only:

```js
    // a comment that exists in one twin and not the other
```

Run: `uv run pytest tests/test_editor_twin_drift.py -vv`
Expected: **7 passed, still green.** This is the mirror-image proof. Without it the comment-stripping rule is unverified, and a guard that fires on comment edits gets deleted by whoever tires of it first — a slower road to the same unguarded state. **Revert the JS.**

- [ ] **Step 6: Falsify 4 — the extractor is not vacuous**

Break the extractor: change `_DEF` to `re.compile(r"^\s*fnction (\w+)\s*\(")`.

Run: `uv run pytest tests/test_editor_twin_drift.py -vv`
Expected: `test_expected_function_counts` FAILS naming both files (`extracted 0 functions, expected 28` and `… expected 36`). The other checks fail loudly in this state too but for a *different* reason — `test_twins_are_identical` and `test_no_normalisation_hazard_in_twin_bodies` raise `KeyError` (they iterate the fixed `TWINS` list and index `table[name]` on the now-empty extraction), while `test_every_common_function_is_classified` **passes vacuously** (empty `common` → nothing unclassified). That last one is the point: classification-completeness alone cannot detect a broken extractor, which is exactly why `test_expected_function_counts` exists and must count *every* function, not just the classified ones. **Restore `_DEF`.**

- [ ] **Step 7: Falsify 5 — a stale classification is caught**

In `table_editor.js` only, rename `tooBig` to `tooBigX` — its definition (line 238) and its single call site inside `refreshToolbarState` (line 287), so the file stays coherent — leaving `"tooBig"` in `TWINS`.

Run: `uv run pytest tests/test_editor_twin_drift.py::test_no_stale_classification -vv`
Expected: FAIL, naming `tooBig` as classified but no longer common to both files. This is the only falsification that exercises the backward check; falsifications 1–4 would all still pass with it deleted entirely. **Revert the JS.**

- [ ] **Step 8: Falsify 6 — a duplicate name is caught**

Append a second `function msg(k) { return k; }` at file scope in `filltable_editor.js`.

Run: `uv run pytest tests/test_editor_twin_drift.py -vv`
Expected: `test_no_duplicate_function_names` FAILS with `ValueError: filltable_editor.js: duplicate function name 'msg'`. **Revert the JS.**

- [ ] **Step 9: Falsify 7 — a double classification is caught**

Add `"label"` to the `TWINS` list while leaving it in `DIVERGENT`.

Run: `uv run pytest tests/test_editor_twin_drift.py::test_classifications_are_disjoint -vv`
Expected: FAIL, naming `label`. **Revert the list.**

- [ ] **Step 10: Falsify 8 — the normalisation tripwire fires**

Two separate probes, each inside a twin body in `table_editor.js`, reverted between them.

(a) Inside `msg`, add: `var _u = "http://example.com";`
Expected: `test_no_normalisation_hazard_in_twin_bodies` FAILS reporting `` `//` inside a string literal ``.

(b) Instead, inside `msg`, add: ``var _t = `x`;``
Expected: the same test FAILS reporting `template literal in code`.

Confirm in both cases that `test_expected_function_counts` still **passes** — that is the point: the tripwire has no indirect coverage from the count assertion, because normalisation runs after extraction. **Revert the JS.**

- [ ] **Step 11: Confirm the tree is clean, then full suite and lint**

```
git status --porcelain
```

Expected: exactly one line, `?? tests/test_editor_twin_drift.py`. Any modification to either `.js` file means a falsification was not reverted — fix that before going further.

```
uv run pytest -m "not e2e"
uv run ruff check . && uv run ruff format --check .
```

Expected: full suite green (the current baseline is 3770 passed; this adds 7, so expect 3777) and both lint gates clean.

- [ ] **Step 12: Commit**

```bash
git add tests/test_editor_twin_drift.py
git commit -m "test(editor): guard the 20 twin functions against silent drift"
```

---

## Done when

- `tests/test_editor_twin_drift.py` exists with 7 passing checks, and every one of them has been shown to fail for its own stated reason.
- Both editor `.js` files are byte-identical to their state at the start of the task.
- Full non-e2e suite green; `ruff check` and `ruff format --check` both clean.
