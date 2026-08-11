# Fill-in Table as a Reveal Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `FillTableElement` an optional author checkbox that makes a fully-correct table reveal the following sibling elements in its scope, joining the three existing reveal-gate families.

**Architecture:** The flag is a `gate` key inside the existing `data` JSONField (no migration, no `FORMAT_VERSION` bump). When set, the template stamps `data-reveal-gate data-filltablegate` on the `.filltable` root div, `filltable.js` calls the existing `window.libliRevealCascade` on an all-correct check, and `FillTableElement.render` derives `open: true` into `data-state` from the stored `done` flag so `reveal.js::restoreGates` replays the cascade on reload.

**Tech Stack:** Django 5, PostgreSQL (JSONField), vanilla ES5-style JS (no build step), KaTeX, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-11-filltable-reveal-gate-design.md` — read it before starting. It records *why* several of these choices are shaped the way they are, and three of them look wrong until you read the reasoning.

## Global Constraints

- **No database migration.** `gate` lives in `data`; do not add a model field.
- **No `FORMAT_VERSION` bump.** It stays at 11 (`courses/transfer/schema.py:14`).
- **`courses/state.py` must not change.** `_val_done` stores only `{"done": True}` by design; see spec §4.
- **`reveal.js` gets exactly one change** — the `focusTargetIn` branch in Task 5. Do not touch `scopeOf`, `isGateWrapper`, `cascadeFrom`, or `restoreGates`. **Two sanctioned exceptions, both in Task 9 Step 8's mutant table:** the `isGateWrapper`-`break` mutant (which edits `cascadeFrom`) and the `focusTargetIn`-branch mutant. Both must be edited back and the revert proved with `git diff --quiet courses/static/courses/js/reveal.js`, exactly as Task 3 Step 6 mutant 4 does for the equally-frozen `courses/state.py`.
- **An ungated fill-table must behave byte for byte as it does today.** Every change is conditional on `gate`.
- **Falsify every test before trusting it.** Introduce the named mutant, confirm RED, then remove the mutant *by editing it out* — never `git checkout`, which would discard the new test along with it.
- **Restore the LAST mutant too, and re-run before you stage.** Each falsify step ends on a mutant, and the commit step that follows runs only `ruff` — which does not read JS, templates or CSS at all. So an unreverted final mutant sails through a green lint gate into the commit. **Every commit step that follows a falsify step** therefore begins by re-running that task's own test command and confirming all PASS, before `git add` — that is Tasks 1-7 and 9. (Tasks 8 and 10 introduce no mutants, so their commit steps have nothing to restore.) Where a task mutates a file a Global Constraint freezes (`courses/state.py` in Task 3, `reveal.js` in Task 9), also prove it with `git diff --quiet <file>`.
- **Run tests narrowly.** Start the test-DB container first (`docker compose -f docker-compose.test.yml up -d`); a down container makes the suite look hung for ~4 minutes. Never background a pytest run.
- **Tooling is via `uv run`** — `pytest`, `ruff`, and `python` are not on PATH.
- **Every fenced command block in this plan is `bash`, and some of them require it.** This machine's primary shell is Windows PowerShell 5.1, where `&&` is **not a valid operator** — it is a parser error, not a silent difference. Three of the plan's "prove the mutant is out" gates chain on it (Task 3 Step 7's `git diff --quiet courses/state.py && echo "state.py clean"`, and Task 9 Steps 8 and 10's `… && echo "all three clean"`), and those are exactly the commands most likely to be pasted ad hoc into whatever shell is open. Run them through the Bash tool. If you must use PowerShell, split them: `git diff --quiet <file>; if ($?) { echo "clean" }` — never assume the `&&` form merely printed nothing.
- **Lint before each commit:** `uv run ruff check --no-cache <changed files>` and `uv run ruff format --check <changed files>` (a separate CI gate). `--no-cache` matters: a `# noqa` warning is cached away and the second run falsely reports clean. **`--check` is a gate, not a fixer** — some snippets dictated here are not `ruff format`-clean as pasted (Task 9's `_visible` helper, for one). When `--check` reports "would be reformatted", run bare `uv run ruff format <changed files>` and re-run `--check`; that is expected, not a defect in the snippet.
- **`ruff format` will NOT save you from `E501`.** `E` is selected with no `line-length` override, so the limit is **88 columns**, and the repo is E501-clean today. `ruff format` only re-wraps *bracketed code* — it never rewraps a comment, never splits a string literal, and never parenthesises an assignment target list. Long comments, long string literals and wide unpacking targets must be wrapped **by hand**, and a `ruff check` failure on one of those is a real violation to fix, not the expected `format --check` churn described above. **The dictated snippets are NOT all E501-clean, and which kind of overflow you hit decides what to do.** Sort by what the offending line is:

- **Bracketed code, a dict/list literal, or an `assert x, "msg"` form** → `ruff format` fixes it (it parenthesises and re-wraps these, including assert messages). Expected churn: run bare `uv run ruff format <file>` and move on. Several dictated snippets land here.
- **A comment, a string literal, or an assignment target list** → `ruff format` will **not** touch it. This is a real violation you must wrap by hand. The dictated snippets are pre-wrapped for these cases; keep them that way when pasting.

Remember Task 9's bodies gain 4 columns once the `def` line is added (its nested blocks 8). The cheap check is `uv run ruff check --no-cache <file>` immediately after writing a snippet, not at the commit step.
- **English source strings only** in Tasks 1–9; the Polish catalog and the binary `.mo` are Task 10, deliberately last.
- **The module-level cell constants are shared mutable state — keep every value sanitiser-stable.** Tasks 2, 4, 6, 7 and 9 each define a module-level grid (`_CELLS_WITH_ANSWER`, `_GATE_CELLS`, `_CELLS`) and pass it as `FillTableElement(data={"cells": <the constant>, …})`. `save()` calls `_sanitized_data`, which rewrites cells **in place** (`courses/models.py:1408-1422` — `data["prompt"] = …`, `cell["html"] = sanitize_cell(...)`, and the answer `.strip()`), and `self.data` holds a reference to the constant's own cell dicts. So every element seeded from one constant in a test module shares those dicts, and each `save()` rewrites them for all of them. The values dictated in this plan (`{"kind": "static", "html": "x"}`, `{"kind": "answer", "answer": "4"}` / `"1"`) are all sanitiser **fixed points**, so the mutation is idempotent and nothing breaks. **Keep it that way:** if you ever need un-sanitised HTML or a padded/pipe-delimited answer in one of these constants, make it a zero-arg factory (`def _gate_cells(): return [[{…}]]`) instead, or the first `save()` silently rewrites the fixture out from under every later test in the file.

---

### Task 1: `gate` in the normalizer

**Files:**
- Modify: `courses/models.py` — `FillTableElement` class docstring (~:1268-1271) and `normalize_data` (~:1339-1380)
- Test: `tests/test_filltable_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FillTableElement.normalize_data(data)` gains a `"gate": bool` key in its returned dict. Every later task reads it as `nd["gate"]` (Python) or `data.gate` (template) or `data__gate=True` (ORM).

**Why the guard is two conjuncts, not one:** a gate that can never be *satisfied* strands every following sibling with no author-visible symptom. `FillTableElementForm.clean_data` rejects two grid shapes — no answer cell at all, and an answer cell whose accepted-answer string is blank (`courses/marking.py::blank_matches` loops over an empty accepted list and returns `False` for every input, so such a cell can never be got right). The form is only one write path; `transfer/importer.py::_build_fill_table` and programmatic construction go straight to `normalize_data`. So mirror both rules here.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_model.py`:

```python
def test_normalize_data_gate_defaults_false():
    nd = FillTableElement.normalize_data({"cells": [[{"kind": "answer", "answer": "4"}]]})
    assert nd["gate"] is False


def test_normalize_data_gate_true_on_satisfiable_grid():
    nd = FillTableElement.normalize_data(
        {"gate": True, "cells": [[{"kind": "answer", "answer": "4"}]]}
    )
    assert nd["gate"] is True


def test_normalize_data_gate_coerces_non_boolean():
    nd = FillTableElement.normalize_data(
        {"gate": "yes", "cells": [[{"kind": "answer", "answer": "4"}]]}
    )
    assert nd["gate"] is True


def test_normalize_data_gate_coerces_falsy_non_false():
    # An empty string is the ONLY payload that can falsify the bool() wrapper.
    # `and` returns its last operand, so with a TRUTHY value like "yes" the
    # expression already evaluates to the real bool produced by the final
    # conjunct -- dropping bool() leaves the test above green. With "" the
    # unwrapped form returns "" rather than False, and `is False` catches it.
    nd = FillTableElement.normalize_data(
        {"gate": "", "cells": [[{"kind": "answer", "answer": "4"}]]}
    )
    assert nd["gate"] is False


def test_normalize_data_gate_forced_off_without_answer_cells():
    # A gate with no answer cell can never open: filltable_check returns
    # cells: [] / all_correct: false unconditionally.
    nd = FillTableElement.normalize_data(
        {"gate": True, "cells": [[{"kind": "static", "html": "x"}]]}
    )
    assert nd["gate"] is False


def test_normalize_data_gate_forced_off_with_blank_answer_cell():
    # marking.blank_matches returns False for every input when the accepted
    # list is empty, so this gate could never open either.
    nd = FillTableElement.normalize_data(
        {
            "gate": True,
            "cells": [[{"kind": "answer", "answer": "4"}, {"kind": "answer", "answer": ""}]],
        }
    )
    assert nd["gate"] is False


def test_normalize_data_gate_forced_off_with_pipe_only_answer_cell():
    nd = FillTableElement.normalize_data(
        {"gate": True, "cells": [[{"kind": "answer", "answer": " | "}]]}
    )
    assert nd["gate"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_filltable_model.py -k gate -v
```

Expected: 7 FAILED with `KeyError: 'gate'`.

- [ ] **Step 3: Implement the normalizer change**

In `courses/models.py`, inside `FillTableElement.normalize_data`, immediately after the `border`/`prompt` lines and before the `return`:

```python
        border = data.get("border")          # <- UNCHANGED CONTEXT, already present
        prompt = data.get("prompt")          # <- UNCHANGED CONTEXT, already present
        # A gate that can never be SATISFIED strands every following sibling behind
        # an unsatisfiable check, with no author-visible symptom. TWO grid shapes do
        # that, and FillTableElementForm.clean_data rejects BOTH:
        #   (a) no answer cell at all -- filltable_check returns cells: [] /
        #       all_correct: false unconditionally;
        #   (b) an answer cell whose accepted-answer string is blank --
        #       marking.blank_matches loops over an EMPTY accepted list and returns
        #       False for every input.
        # The form is only one write path: _build_fill_table (model-level only, and
        # _val_fill_table never inspects answers) and programmatic construction both
        # bypass it. So mirror both of the form's rules here.
        from courses.filltable import answer_cells
        from courses.filltable import is_blank_answer

        answers = [ans for _r, _c, ans in answer_cells(cells)]
        gate = (
            bool(data.get("gate"))
            and bool(answers)
            and not any(is_blank_answer(a) for a in answers)
        )
        return {
            "header_row": bool(data.get("header_row")),
            "header_col": bool(data.get("header_col")),
            "case_sensitive": bool(data.get("case_sensitive")),
            "gate": gate,
            "border": border
            if border in TableElement.BORDERS
            else TableElement.DEFAULT_BORDER,
            "prompt": prompt.strip() if isinstance(prompt, str) else "",
            "cells": cells,
        }
```

The first two lines are existing context showing where the insertion goes — the block from `# A gate that can never…` through the closing `}` is what replaces the current `return {…}`. The local import mirrors `canonical_cells`, which already does `from courses.filltable import split_alternatives` inside the method body.

- [ ] **Step 4: Update the class docstring**

`courses/models.py:1268-1271` currently reads:

```python
class FillTableElement(ElementBase):
    """Ungraded self-check table: a JSON grid whose cells are either static
    (rich HTML/math, sanitised at save) or answer cells (a plain accepted-answer
    string). Checked server-side per cell; records no marks, reveals nothing."""
```

Change the final clause:

```python
class FillTableElement(ElementBase):
    """Ungraded self-check table: a JSON grid whose cells are either static
    (rich HTML/math, sanitised at save) or answer cells (a plain accepted-answer
    string). Checked server-side per cell; records no marks. When `data['gate']`
    is set, a fully-correct check reveals the following siblings in scope — see
    reveal.js and the fill-table reveal-gate design doc."""
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_filltable_model.py -v
```

Expected: all PASS, including the pre-existing tests in that file.

- [ ] **Step 6: Falsify — drop each conjunct in turn**

Four separate mutants; the guard has four independent failure modes and a single combined check would let three of them hide:

1. Delete `"gate": gate,` from the returned dict → **all seven** go RED with `KeyError` (every one of them reads `nd["gate"]`). This mutant proves the key exists; mutants 2-4 are the ones that discriminate between the conjuncts and the coercion.
2. Restore it, then change `gate = (...)` to `gate = bool(data.get("gate"))` → `test_normalize_data_gate_forced_off_without_answer_cells` **and** both blank-answer tests go RED.
3. Restore, then drop only the `not any(is_blank_answer(...))` conjunct → the two blank-answer tests go RED, the no-answer-cell test stays GREEN.
4. Restore, then drop the coercion only — `bool(data.get("gate"))` → `data.get("gate")`, keeping both conjuncts → **two** RED: `test_normalize_data_gate_coerces_falsy_non_false` (the `""` payload yields `""`, not `False`) **and** `test_normalize_data_gate_defaults_false` (no `gate` key → `data.get("gate")` is `None`, `and` short-circuits and returns `None`, so `is False` fails). The other five stay GREEN. `test_normalize_data_gate_coerces_non_boolean` stays GREEN despite its name, which is exactly why the `""` case has to exist: `and` returns its last operand, so a truthy `"yes"` yields the final conjunct's real `True` either way.

Remove each mutant by editing it back, never by `git checkout` — that would delete the new tests too.

- [ ] **Step 7: Restore, re-run, lint and commit**

Mutant 4 left the coercion dropped in `courses/models.py` — edit it back, then re-run. `data.get("gate")` is perfectly valid Python, so both ruff gates below accept the mutated file and would commit it with two RED tests:

```bash
uv run pytest tests/test_filltable_model.py -v
```

Expected: all PASS. Then:

```bash
uv run ruff check --no-cache courses/models.py tests/test_filltable_model.py
uv run ruff format --check courses/models.py tests/test_filltable_model.py
git add courses/models.py tests/test_filltable_model.py
git commit -m "feat(filltable): add a gate flag to the normalizer

Suppressed for the two grid shapes that could never satisfy a gate (no
answer cell, or a blank one), mirroring FillTableElementForm.clean_data --
the importer and programmatic construction bypass the form."
```

---

### Task 2: Gate marker in the template, and the print carve-out

**Files:**
- Modify: `templates/courses/elements/filltableelement.html:10-15`
- Modify: `core/static/core/css/app.css:1022`
- Modify: `courses/static/courses/css/courses.css:1995` (comment text only — Step 10)
- Test: `tests/test_filltable_render.py`, and a new `courses/tests/test_filltable_gate_print.py`

**Interfaces:**
- Consumes: `data.gate` from Task 1.
- Produces: a gated table renders `data-reveal-gate data-filltablegate` on the **same node** that carries `data-state`. Tasks 5 and 9 depend on both attributes being on `.filltable` itself.

**Two things here look separable but are not.** The print rule only becomes wrong once the marker exists, so they ship together.

**The co-location invariant.** `reveal.js::storedOpen(btn)` reads `btn.dataset.state` off the node it found via `[data-reveal-gate]`. The template has a second plausible host — the inner `.el.el--filltable` div. Putting the marker there makes `storedOpen` read `undefined` → `false` → prefix-closure `break` → the revealed content is hidden **forever** for a student who already solved the table. The test asserts same-node, not mere presence, because a presence-only assertion stays green under exactly that mutation.

- [ ] **Step 1: Add the imports and the shared grid constant**

`tests/test_filltable_render.py` currently imports only `pytest`, `FillTableElement`, `make_course`, `make_image_asset`. Add four imports, **in two separate places** — ruff selects `I` with `force-single-line = true`, and `bs4` is third-party while `courses`/`tests` are first-party, so pasting these four as one block trips `I001`. Directly under the existing `import pytest`:

```python
from bs4 import BeautifulSoup
```

and into the existing first-party block (after the blank line), in sorted position:

```python
from courses.models import CalloutElement
from courses.models import Element
from courses.models import FillTableElement   # already there
from tests.factories import make_course       # already there
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset  # already there
```

This mirrors `courses/tests/test_reveal_gate_render.py:5-10`.

**Three of these four go unused until Step 3, and that is deliberate.** `CalloutElement`, `Element` and `make_course_with_unit` are only touched by Step 3's `_render_callout_with_filltable_child`, so between here and there the file carries three `F401` violations and ruff selects `F`. Nothing runs `ruff check` until Step 13, so this is inert — noted only because Task 9 Step 10 flags the identical hazard as worth a paragraph, and the silence here would otherwise read as an oversight rather than a decision. Do **not** "fix" it by splitting the import across two steps; add all four now and let Step 13's lint gate be the first to look.

and, at module level below `pytestmark`, the grid every new test uses. **It must contain a non-blank answer cell** — Task 1's guard suppresses `gate` otherwise, and every assertion below would invert:

```python
_CELLS_WITH_ANSWER = [
    [{"kind": "static", "html": "x"}, {"kind": "answer", "answer": "4"}],
]
```

bs4 is already a test dependency (`courses/tests/test_reveal_gate_render.py` and `tests/test_publish_tree.py` use it); only the import is missing.

- [ ] **Step 2: Write the failing render tests**

The file's helper is `def _render(cells, **kw)` (line 10) — **`cells` is the grid, positional; the keyword args go into `data`.** Passing a whole data dict as `cells` makes `normalize_data` fall back to a default 2×2 grid and never see `gate` at all. Call it as the existing tests do:

```python
def test_gated_table_marks_the_root_div():
    html = _render(_CELLS_WITH_ANSWER, gate=True)
    assert "data-reveal-gate" in html
    assert "data-filltablegate" in html


def test_ungated_table_has_no_gate_attributes():
    html = _render(_CELLS_WITH_ANSWER)
    assert "data-reveal-gate" not in html
    assert "data-filltablegate" not in html


def test_gate_marker_is_on_the_same_node_as_data_state():
    # reveal.js::storedOpen reads dataset.state off the node it matched via
    # [data-reveal-gate]. If the marker lands on the inner .el--filltable div
    # instead, storedOpen reads undefined -> the gate never restores and the
    # revealed content is hidden forever.
    html = _render(_CELLS_WITH_ANSWER, gate=True)
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("[data-reveal-gate][data-filltablegate]")
    assert node is not None
    assert node.has_attr("data-state")
    assert "filltable" in node.get("class", [])
```

`_render` calls `el.render()` bare, so `data-state-url` is the empty string here — that is fine and deliberate. **This test pins co-location of the marker with `data-state` only**; `data-state-url` is not asserted, because pinning it would require the lesson-view path and adds nothing to what this test is for. (An unattempted table also legitimately renders `data-state="{}"`, so assert presence via `has_attr`, never a non-empty value.)

**This is a deliberate deviation from spec test 4, recorded here so the final spec-vs-code review does not read it as a dropped requirement.** The spec asks for the lesson-view path "so `data-state-url` is real rather than the empty string a bare `el.render()` produces", and for a **non-empty** `data-state`. Both are declined: `reveal.js`'s `save()` never runs for a fill-table (persistence goes through `filltable.js`'s own `saveFlag`), so a real `data-state-url` proves nothing this test is about; and a value assertion adds nothing to a *co-location* test, which is all this one is for. (Note the spec's non-empty assertion would in fact have **passed** — `_state_context` sets `mine_json = json.dumps(mine)`, so an unattempted table renders the two-character string `"{}"`, not an empty attribute. It is uninformative here, not wrong.) Task 3's tests do go through the lesson view, where the value actually matters and is asserted exactly.

- [ ] **Step 3: Write the direct-child pin**

This guards the pre-hide CSS rather than the cascade, and needs a callout render — no helper for that exists anywhere in the repo, so write one in the same file:

```python
def _render_callout_with_filltable_child(gate):
    """Render a CalloutElement whose only child is a fill-table.

    resolved_children() groups by `parent` alone, so no tab_id is needed.
    """
    _course, unit = make_course_with_unit()
    callout = CalloutElement.objects.create()
    parent_row = Element.objects.create(unit=unit, content_object=callout)
    child = FillTableElement(data={"cells": _CELLS_WITH_ANSWER, "gate": gate})
    child.save()
    Element.objects.create(unit=unit, content_object=child, parent=parent_row)
    return callout.render(
        element=parent_row, state={}, slug=unit.course.slug, node_pk=unit.pk
    )


def test_gated_filltable_is_a_direct_child_of_the_callout_child_wrapper():
    # The pre-hide CSS is
    # `.callout__children > .callout__child:has(> [data-reveal-gate])`.
    # One extra wrapper div between .callout__child and .filltable disarms it
    # silently -- the gate still works on click, but nothing is hidden to begin
    # with, so the student sees the answer before earning it.
    soup = BeautifulSoup(_render_callout_with_filltable_child(gate=True), "html.parser")
    child = soup.select_one(".callout__children > .callout__child")
    assert child is not None
    marked = soup.select_one("[data-reveal-gate]")
    assert marked is not None
    assert marked.parent is child, "the gate marker is not a DIRECT child of .callout__child"
    assert "filltable" in marked.get("class", [])
```

`marked.parent is child` rather than a `:scope >` selector — it does not depend on the installed `soupsieve` version. `CalloutElement.objects.create()` needs no arguments (`courses/models.py:469`).

**On the missing `.lesson-block__body >` twin.** The three existing gate families each pin their *top-level* depth with a regex (`courses/tests/test_reveal_gate_render.py:159`, `courses/tests/test_fillgate_restore.py:92`, `courses/tests/test_switchgate_restore.py:110`, all matching `<div class="lesson-block__body">\s*<…data-reveal-gate`), and `reveal.js::isGateWrapper`'s `.slide` branch depends on exactly that shape — as does every one of Task 9's seven e2e fixtures. This plan deliberately does not mirror the per-family regex: mutant 4 in Step 12 (wrapping the root div) reddens the callout-scoped pin, and the same extra wrapper would break the top-level shape identically, so one test covers both scopes. Noted rather than silently skipped, because the house pattern here is per-family duplication.

**On spec test 5's "and the rendered output is otherwise unchanged" half:** that is delegated to the rest of `tests/test_filltable_render.py` staying green **unmodified** — the file already pins the ungated render's structure in detail, and a fresh snapshot assertion would duplicate it.

- [ ] **Step 4: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_render.py -k gate -v
```

Expected, enumerated (a blanket "FAIL" would hide the one that is green already):
- `test_gated_table_marks_the_root_div` — **FAILS**, attributes absent.
- `test_gate_marker_is_on_the_same_node_as_data_state` — **FAILS**, `select_one` returns `None`.
- `test_gated_filltable_is_a_direct_child_of_the_callout_child_wrapper` — **FAILS**, same reason.
- `test_ungated_table_has_no_gate_attributes` — PASSES already; it asserts an absence. Green before the change is expected, not a mistake — mutant 3 in Step 12 is what proves it can fail.

- [ ] **Step 5: Add the marker to the template**

`templates/courses/elements/filltableelement.html`, the root div (currently lines 10-15):

```html
<div class="filltable" data-filltable{% if data.gate %} data-reveal-gate data-filltablegate{% endif %}
     data-element-pk="{{ eid }}"
     data-check-url="{% url 'courses:filltable_check' eid %}"
     data-success-msg="{% trans 'Great!' %}"
     data-retry-msg="{% trans 'Try again' %}"
     data-state="{{ mine_json }}" data-state-url="{{ save_url }}">
```

Leave every other attribute exactly where it is.

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest tests/test_filltable_render.py -v
```

Expected: all PASS.

- [ ] **Step 7: Write the failing print test**

Create `courses/tests/test_filltable_gate_print.py`. Copy the `_print_block` helper rather than importing it — `courses/tests/` has no `__init__.py`, so cross-root imports are unreliable:

```python
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
    # after. `}` closes the revert rule on the line directly above (app.css:1021)
    # and is not whitespace, so ^\s* cannot bridge into line 1022 from earlier.
    # A lookbehind-on-colon form was tried and is INERT -- it matches nothing in
    # EITHER state, so it would have been an assertion that could not fail.
    assert not re.search(r"^\s*\[data-reveal-gate\]\s*\{", block, re.M)
```

- [ ] **Step 8: Run to verify it fails**

```bash
uv run pytest courses/tests/test_filltable_gate_print.py -v
```

Expected: **both** FAIL, for two different reasons — enumerate them, a blanket "FAIL" hides
which one is which:
- `test_print_hide_rule_excludes_the_filltable_gate` — the block still holds the bare selector.
- `test_courses_css_crossref_clause_stays_inside_its_comment` — `filltablegate` does not occur
  in `courses.css` at all yet (Step 10 adds it); `grep -c filltablegate` on that file returns 0
  today. It goes green only once Step 10's clause lands **inside** the comment.

- [ ] **Step 9: Narrow the print rule**

`core/static/core/css/app.css:1022`, inside the first `@media print` block. Change:

```css
  [data-reveal-gate] { display: none !important; }
```

to:

```css
  /* A fill-table gate's marked node IS the student's work, not a control, so it
     must survive printing. The other three families are buttons/forms/cyclers. */
  [data-reveal-gate]:not([data-filltablegate]) { display: none !important; }
```

- [ ] **Step 10: Amend the stale cross-reference in `courses.css`**

`courses/static/courses/css/courses.css:1995` cites this rule as house precedent. After the carve-out that is no longer universally true.

**The clause goes INSIDE the comment, before the terminator.** Line 1995 already carries the closing `*/`, so a literal append lands *after* it and emits invalid CSS immediately above the `@media print` block on :1996. Replace the line:

```css
   [data-reveal-gate] and .unit-strip__edit are both hidden in print). */
```

with:

```css
   [data-reveal-gate] and .unit-strip__edit are both hidden in print; a
   fill-table gate is carved out -- see the :not([data-filltablegate])
   rule in app.css). */
```

No CSS behaviour changes here; this is prose upkeep. Task 6 makes the same argument about `test_editor_twin_drift.py`'s reason string — a prose guard that quietly rots is worse than none, because it is still read as authoritative.

- [ ] **Step 11: Verify the scope-agreement guard is undisturbed**

```bash
uv run pytest courses/tests/test_filltable_gate_print.py courses/tests/test_reveal_scope_agreement.py -v
```

Expected: all PASS. `test_reveal_scope_agreement.py` must stay green **unmodified** — it asserts the five *scope* selectors appear in the print block, a different rule, and its `@media print\s*\{(.*?)\n\}` regex still captures the narrowed one because the terminating `}` is at column 0.

- [ ] **Step 12: Falsify both**

1. Restore the bare `[data-reveal-gate]` selector → the print test goes RED, `test_reveal_scope_agreement.py` stays GREEN (proving it was never guarding this).
2. **Restore, then** move `data-reveal-gate data-filltablegate` from the root `.filltable` div onto the inner `.el.el--filltable` div → `test_gate_marker_is_on_the_same_node_as_data_state` **and** the direct-child pin go RED (the pin fails on both its last assertions: `marked.parent` becomes the `.filltable` div rather than `.callout__child`, and the inner div's class list is `el el--filltable el--filltable--border-grid`, which contains no `"filltable"` entry), while `test_gated_table_marks_the_root_div` stays GREEN. That last contrast is the point of the co-location test — but note this mutant does **not** separate the two co-location tests from each other; only mutant 4 does.
3. **Restore, then** drop the `{% if data.gate %}…{% endif %}` guard so the marker is emitted unconditionally → `test_ungated_table_has_no_gate_attributes` RED. It is green from the moment it is written, so without this it is never shown to be able to fail — and it is the only render-level guard on the "byte for byte" constraint.
4. **Restore, then** wrap the root `.filltable` div in an extra `<div>` in `filltableelement.html` → the direct-child pin RED while the co-location test stays GREEN. Two tests, two distinct failure modes: co-location survives an extra ancestor, the pre-hide CSS does not. **The restore is load-bearing here:** with mutant 2 still applied the co-location test is already RED, and this mutant's whole point — the GREEN half of the contrast — cannot be observed.
5. **Restore, then** commit Step 10's splice the wrong way: move the new clause to *after*
   line 1995's closing `*/` instead of before it → `test_courses_css_crossref_clause_stays_inside_its_comment`
   RED, everything else GREEN. This reproduces the exact mistake Step 10 warns about, and
   **nothing else in the repo can see it**: `ruff` does not read CSS,
   `test_reveal_scope_agreement.py` reads `app.css` rather than `courses.css`, and Step 13's
   re-run would pass on the broken file. Restore it before Step 13.

- [ ] **Step 13: Restore, re-run, lint and commit**

Mutant 5 — the last one — left the `courses.css` clause spliced outside its comment; edit it back. Then **confirm** (do not re-edit) that mutant 4's extra wrapper div is already out of `filltableelement.html`: Step 12 mutant 5 opens with "**Restore, then**", so it was removed before that mutant was applied. Confirm too that mutant 1's `app.css` carve-out is restored (`[data-reveal-gate]:not([data-filltablegate])`, not the bare selector); `ruff` reads neither the template nor either CSS file, so nothing else would notice. Then re-run before staging:

```bash
uv run pytest tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py -v
```

Expected: all PASS. Then:

```bash
uv run ruff check --no-cache tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py
uv run ruff format --check tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py
git add templates/courses/elements/filltableelement.html core/static/core/css/app.css courses/static/courses/css/courses.css tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py
git commit -m "feat(filltable): stamp the gate marker, carve it out of the print hide rule

The marker and data-state must share a node -- reveal.js::storedOpen reads
dataset.state off whatever it matched. The @media print rule hides gate
CONTROLS; a fill-table's marked node is the student's work, so it is excluded."
```

---

### Task 3: The `done` → `open` render seam

**Files:**
- Modify: `courses/models.py` — `FillTableElement.render` (~:1437-1454)
- Test: `tests/test_filltable_restore.py` (extend `_seed_filltable` first)

**Interfaces:**
- Consumes: `nd["gate"]` (Task 1), the marker (Task 2).
- Produces: a gated, solved table renders `data-state` containing `"open": true`. Task 9's e2e reload tests depend on this.

**This is the subtle one — read spec §4 before writing code.** `reveal.js::storedOpen` tests `blob.open === true` strictly, but a fill-table's blob **can never contain `open`**: `courses/state.py:116` maps `filltableelement` to `_val_done`, which returns `{"done": True}` and discards every other key. So this derivation is not a legacy-compatibility shim — it is the **only** mechanism by which a gated fill-table ever restores. Deleting it does not degrade an edge case; it breaks restore for every gated table.

Two invariants the code must respect:
- **Copy, never mutate.** `_state_context`'s `mine` is a live reference into the caller's state blob; assigning into it leaks `open` to every other reader for the rest of the request.
- **Hoist `normalize_data`.** One `nd`, so the `nd["gate"]` check and the `{**nd, …}` spread cannot drift apart. **This is a consistency win, not an efficiency one** — do not restate it as saving a call. `resolved_cells` itself runs `self.normalize_data(self.data)` internally (`courses/models.py:1491`), and `canonical_cells` reaches it through `resolved_cells`, so the rewritten `render` still normalizes twice per call exactly as the current one does.

- [ ] **Step 1: Extend the seeding helper**

`tests/test_filltable_restore.py:39` hardcodes `FillTableElement(data={"cells": cells})`, so it cannot seed a gated element at all. Add a keyword; existing callers keep the default:

```python
def _seed_filltable(unit, student, cells, blob, gate=False):
    obj = FillTableElement(data={"cells": cells, "gate": gate})
    obj.save()
    row = Element.objects.create(unit=unit, content_object=obj)
    if blob is not None:
        UnitProgress.objects.create(
            student=student, unit=unit, element_state={str(row.pk): blob}
        )
    return row, obj
```

**Keying seam — the file's docstring documents it and these tests will trip over it otherwise:** `UnitProgress.element_state` is **str**-keyed, while `render()`'s `state` argument is **int**-keyed (`courses/views.py:485-494` does the conversion). Seed through the lesson view with str keys; call `render()` directly only with int keys.

- [ ] **Step 2: Write the failing tests**

This file has **no `unit`/`student` fixtures** — every test creates its subjects inline in exactly three lines, and each uses a distinct student slug. Follow that shape precisely, and reuse the file's existing `_lesson_url` helper plus its `data-state` regex idiom (`re.search(r'data-state="([^"]*)"', body)` → `json.loads(html.unescape(...))`); `re`, `json`, and `html` are already imported there.

```python
def test_gated_done_renders_open_in_data_state(client):
    student = make_student(client, "ftbl_gate1")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, _CELLS, {"done": True}, gate=True)

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True, "open": True}


def test_ungated_done_does_not_render_open(client):
    student = make_student(client, "ftbl_gate2")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    _seed_filltable(unit, student, _CELLS, {"done": True}, gate=False)

    body = client.get(_lesson_url(unit)).content.decode()

    m = re.search(r'data-state="([^"]*)"', body)
    assert m and json.loads(html.unescape(m.group(1))) == {"done": True}


def test_render_does_not_mutate_the_callers_state_blob(client):
    # render()'s OWN contract: an INT-keyed state dict, called directly -- not the
    # str-keyed UnitProgress seam. See this module's docstring.
    student = make_student(client, "ftbl_gate3")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    row, obj = _seed_filltable(unit, student, _CELLS, None, gate=True)

    state = {row.pk: {"done": True}}
    obj.render(element=row, state=state, slug=unit.course.slug, node_pk=unit.pk)

    assert state[row.pk] == {"done": True}, "render leaked `open` into the caller's blob"
```

`_CELLS` (line 32 of this file) already contains a non-blank answer cell, so Task 1's guard leaves `gate` on — no new constant is needed here.

And the stored-blob shape, which pins the claim this whole seam rests on:

```python
def test_saved_gated_state_stores_done_only(client):
    # filltable_check writes NOTHING -- it returns {"cells": …, "all_correct": …}
    # only. Persistence is a separate saveFlag POST, so drive that endpoint.
    # Sending `open` is the point: _val_done must strip it, which is WHY the
    # render-time derivation in this task exists.
    student = make_student(client, "ftbl_gate4")
    course, unit = make_course_with_unit()
    # element_state_save guards on get_node_or_404(viewer=...) and then
    # can_access_course -- and NEITHER requires enrolment, so the write is
    # deliberately open to any viewer who can reach the lesson. The Enrollment is
    # here for symmetry with the GET-based tests above, which DO need it because
    # build_lesson_context populates `state` only for enrolled students.
    Enrollment.objects.create(student=student, course=course)
    row, _obj = _seed_filltable(unit, student, _CELLS, None, gate=True)
    resp = client.post(
        reverse("courses:element_state_save", args=[unit.course.slug, unit.pk]),
        data=json.dumps({"element": row.pk, "state": {"done": True, "open": True}}),
        content_type="application/json",
    )
    # else UnitProgress.DoesNotExist masks the real cause
    assert resp.status_code == 200, resp.content
    stored = UnitProgress.objects.get(student=student, unit=unit).element_state
    assert stored[str(row.pk)] == {"done": True}, "`open` must not survive _val_done"
```

(Its mutant is numbered 4 in Step 6 — it is not an aside, because this test is green-on-write and would otherwise never be shown able to fail.)

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_restore.py -k "renders_open or does_not_render_open or mutate_the_callers or stores_done_only" -v
```

Expected, all four named explicitly. The selector terms are deliberately narrow: a bare `-k gate` would sweep in `test_saved_gated_state_stores_done_only` unaccounted for, and a bare `mutate` term would also collect the pre-existing `test_filltable_render_does_not_mutate_self_data_on_done` (line 97) — whose name is near-identical in intent to the new one, making "1 failed, 4 passed" ambiguous to map. `mutate_the_callers` selects only the new test.
- `test_gated_done_renders_open_in_data_state` — **FAILS**, the blob is `{"done": True}`.
- `test_ungated_done_does_not_render_open` — PASSES already.
- `test_render_does_not_mutate_the_callers_state_blob` — PASSES already.
- `test_saved_gated_state_stores_done_only` — PASSES already.

Three of the four assert the *absence* of behaviour that does not exist yet, so they are green before the change. That is expected, not a mistake: they become meaningful only once Step 4 lands, which is exactly why Step 6 falsifies each one against its own mutant.

- [ ] **Step 4: Implement the seam**

Replace `FillTableElement.render` (`courses/models.py:1437-1454`) with:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        nd = self.normalize_data(self.data)  # one nd: the gate check and the spread
        if ctx["mine"].get("done"):
            # Shallow-copied dict, NEVER `self.data["cells"] = ...` -- mutating
            # self.data in place would silently overwrite the student's stored
            # pipe-delimited alternatives in-memory for the rest of the request.
            ctx["data"] = {**nd, "cells": self.canonical_cells}
            if nd["gate"]:
                # reveal.js::storedOpen tests `blob.open === true`, but state.py's
                # _val_done stores only {"done": True} -- NOTHING ever writes
                # `open`. Deriving it here is the ONLY thing that restores the
                # cascade for a gated table. Do not remove it.
                # COPY, never in-place: _state_context's `mine` is a reference
                # into the caller's state blob, and mutating it would leak `open`
                # into every other reader of that blob for this request.
                ctx["mine"] = {**ctx["mine"], "open": True}
                ctx["mine_json"] = json.dumps(ctx["mine"])
        else:
            ctx["data"] = {**nd, "cells": self.resolved_cells}
        return render_to_string("courses/elements/filltableelement.html", ctx)
```

`json` is already imported at module level in `courses/models.py`.

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_filltable_restore.py tests/test_filltable_render.py -v
```

Expected: all PASS, including both files' pre-existing tests. `test_filltable_render.py` is in the command because this step **replaces the whole of `render()`** — hoisting `normalize_data` and restructuring both branches — and that file (including the three tests Task 2 just added to it) drives `render()` through its `_render` helper. Without it the rewrite is unverified against its own render-path coverage until the branch gate.

- [ ] **Step 6: Falsify all four**

1. Remove the whole `if nd["gate"]:` block → `test_gated_done_renders_open_in_data_state` RED. **This is the highest-value mutant in the plan**: without this test, deleting the derivation is invisible to the entire suite and breaks restore for every gated table.
2. Restore, then change the condition to always-true (drop `if nd["gate"]:`) → **two** RED: the new `test_ungated_done_does_not_render_open`, **and** the pre-existing `test_filltable_stored_done_renders_locked_with_data_state` (`tests/test_filltable_restore.py:49`), which seeds an ungated table with `{"done": True}` and asserts the blob equals exactly `{"done": True}`. Step 5 runs the whole file, so expect two failures here, not one — both are reading the same ungated blob.
3. Restore, then change the copy to an in-place mutation:
   ```python
   ctx["mine"]["open"] = True
   ```
   → `test_render_does_not_mutate_the_callers_state_blob` RED.
4. Restore, then **add `open` to `_val_done`'s return in `courses/state.py`** → `test_saved_gated_state_stores_done_only` RED; the other three stay GREEN (they never round-trip through storage). This proves that test reads the stored blob rather than echoing the POST response — which is the entire claim this task's derivation rests on. **Restore `courses/state.py` immediately afterwards**: shipping it unchanged is a Global Constraint, and this is the only step in the plan that touches it. Verify with `git diff --quiet courses/state.py` before moving to Step 7.

- [ ] **Step 7: Restore, re-run, then commit**

Mutant 4 touched `courses/state.py` and mutant 3 touched `courses/models.py`. Prove both are back:

```bash
git diff --quiet courses/state.py && echo "state.py clean"
uv run pytest tests/test_filltable_restore.py tests/test_filltable_render.py -v
```

Expected: the echo fires and all PASS. Then:

```bash
uv run ruff check --no-cache courses/models.py tests/test_filltable_restore.py
uv run ruff format --check courses/models.py tests/test_filltable_restore.py
git add courses/models.py tests/test_filltable_restore.py
git commit -m "feat(filltable): derive open from done for a gated table

state.py's _val_done stores only {done: true}, so nothing ever persists
`open` -- this render-time derivation is the SOLE restore path for a gated
fill-table, not a legacy shim. Copies the state blob rather than mutating
the caller's reference."
```

---

### Task 4: Page-level detection and the prepaint watchdog

**Files:**
- Modify: `courses/views.py` — `build_lesson_context` (:424, :438, and the return dict at :502-529)
- Modify: `courses/static/courses/js/filltable.js` — the boot flag only (top of the IIFE)
- Modify: `templates/courses/lesson_unit.html:11`
- Test: extend `tests/test_filltable_context.py`; new `tests/test_filltable_gate_prepaint.py`; new `courses/tests/test_filltable_gate_query_shape.py`; new `courses/tests/test_filltable_gate_static.py` (boot-flag assertion only; Task 5 extends it)

**Interfaces:**
- Consumes: `data__gate` (Task 1).
- Produces: context keys `has_filltable_gate` (bool), an updated `has_reveal_gate`, and `window.__fillTableBooted`. Task 9's e2e depends on the context keys, because `reveal.js` loads only under `has_reveal_gate`.

**The boot flag ships in THIS task, not Task 5 — the ordering is load-bearing.** The watchdog term added in Step 6 below reads `window.__fillTableBooted`, and `filltable.js` does not assign it today. If the term shipped first, then between this task's commit and Task 5's *every* lesson page carrying a gated fill-table would evaluate `!window.__fillTableBooted` as true at `DOMContentLoaded`, strip `.reveal-armed`, and disarm the pre-hide — the gated content visible from first paint, on a commit whose message claims the feature works. Task 5 consumes this flag; it must not produce it. Assign the flag (Step 5) *before* adding the term (Step 6).

**The mirror-image window — the pre-hide arming before Task 5 supplies the cascade — is real but unreachable, and that is why it is not restructured.** Note it opens *earlier* than this task for some units: on a unit that already carries a Reveal/Fill/Switch gate, `has_reveal_gate` is already true, so the pre-hide arms the moment **Task 2** stamps `data-reveal-gate` on the fill-table; for a unit whose only gate is the fill-table it opens here, at Task 4. Either way, until Task 5 a gated table hides everything after it and solving it reveals nothing until a reload (which Task 3's derivation heals). The difference from the boot-flag hazard is reachability: `gate` cannot be set by any author-facing route until Task 6 adds the checkbox, so the only gated tables in existence across this window are test fixtures. Do not "fix" it by moving the cascade call earlier — that would recreate the ordering problem above.

**This is not cosmetic.** `reveal.js` is loaded only under `{% if has_reveal_gate %}` (`lesson_unit.html:89`). On a unit whose only gate is a fill-table, omitting this term means **the cascade engine never loads at all** and the gate silently does nothing.

**The filter reads the STORED blob; the template reads the NORMALIZED one.** `data__gate=True` matches whatever is in the JSONField, while `{% if data.gate %}` (Task 2) sees `normalize_data`'s output. `FillTableElement.save()` runs `_sanitized_data`, **not** `normalize_data`, so the two agree only because every *production* write path normalizes first — it is a write-path property, not a query property, and Task 7's `test_every_production_write_path_stores_a_real_boolean` is what pins it. They can still diverge on a row built directly, e.g. `objects.create(data={"gate": True, "cells": [[static-only]]})`: the filter matches and arms `has_reveal_gate`, while the template suppresses the marker. That divergence is **inert** — the pre-hide CSS keys on `[data-reveal-gate]`, so with no marker nothing is hidden and the only cost is `reveal.js` loading needlessly.

**The mirror direction is also possible, and also inert** — stated so "inert" is shown for both rather than asserted for one. On a row built directly as `data={"gate": "yes", …}`, `data__gate=True` **misses** (it matches the JSON literal `true` only, never a string), while `normalize_data` coerces `"yes"` to `True` — so the template stamps the marker on a page whose `has_reveal_gate` may be false. Harmless for the same structural reason, from the other side: the pre-hide `<style>` is gated on `has_reveal_gate` too (`lesson_unit.html:38-48`), so nothing is hidden to begin with, and `filltable.js`'s cascade call short-circuits on `window.libliRevealCascade` being undefined when `reveal.js` was never loaded. A stray marker with no engine is dead markup.

Do not "fix" either direction by normalizing at query time; that would cost a full table scan.

**Use the CT-free query shape.** The obvious `FillTableElement.objects.filter(elements__unit=node, ...)` makes `GenericRelation.get_extra_restriction` call `ContentType.objects.get_for_model`, a DB SELECT on a cold cache. `views.py` rejects that pattern in two existing comments (:411-412 and :457-459).

**But do not repeat those comments' claim that `tests/test_html_element.py` guards it — it does not, and Step 8's docstring says so.** **Fix them rather than leaving them, in Step 4(d) below.** Task 2 Step 10 spends a whole step correcting a stale `courses.css` cross-reference on the principle that a prose guard which quietly rots is worse than none, because it is still read as authoritative — and these two make a claim this plan has positively established to be false, in the very function being edited here. Leaving them would apply the opposite standard to the same defect. That test's fixtures hold only `HtmlElement`s, so `has_fill_table` is `False` and this term short-circuits before the queryset exists; and its assertion is `len(q3) == len(q1)` (`tests/test_html_element.py:323`), a *relative* 1-vs-3-element A/B that absorbs any fixed cost equally in both arms. This is precisely why the shape needs a source assertion, and why Step 9's mutant 5 predicts every runtime test staying GREEN.

- [ ] **Step 1: Write the failing view-flag tests**

**Extend `tests/test_filltable_context.py`** — do not create a new file. It already carries exactly the fixtures these tests need: `unit_with_element(el)` (attaches an unsaved concrete element to a fresh unit) and `ctx_for(unit)` (mints a uniquely-named verified user and calls `build_lesson_context`). It also already holds `test_has_fill_table_flag`, `test_has_fill_table_flag_when_nested_in_tab` and `test_has_fill_table_flag_false_without_element`, so the new cases sit directly beside their `has_fill_table` counterparts.

```python
# non-blank: Task 1's guard keeps `gate` on
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]


def test_has_filltable_gate_flag(unit_with_element, ctx_for):
    unit = unit_with_element(FillTableElement(data={"gate": True, "cells": _GATE_CELLS}))
    ctx = ctx_for(unit)
    assert ctx["has_filltable_gate"] is True
    # A unit whose ONLY gate is a gating fill-table must still arm reveal.js --
    # reveal.js is loaded solely under has_reveal_gate.
    assert ctx["has_reveal_gate"] is True


def test_ungated_filltable_sets_neither_gate_flag(unit_with_element, ctx_for):
    unit = unit_with_element(FillTableElement(data={"cells": _GATE_CELLS}))
    ctx = ctx_for(unit)
    assert ctx["has_filltable_gate"] is False
    assert ctx["has_reveal_gate"] is False


def test_has_filltable_gate_flag_when_nested_in_a_callout(ctx_for):
    # The real shape (mat-pp unit 322). Children keep their own `unit` FK, which is
    # why the inner query must NOT be scoped to parent__isnull=True. Mirrors the
    # existing test_has_fill_table_flag_when_nested_in_tab directly above.
    from courses.models import CalloutElement
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    callout = CalloutElement.objects.create()
    join = Element.objects.create(unit=unit, content_object=callout)
    ft = FillTableElement.objects.create(data={"gate": True, "cells": _GATE_CELLS})
    Element.objects.create(unit=unit, content_object=ft, parent=join)
    ctx = ctx_for(unit)
    assert ctx["has_filltable_gate"] is True
    assert ctx["has_reveal_gate"] is True
```

`CalloutElement.objects.create()` needs **no** arguments (`courses/models.py:469` — `kind` defaults to `Kind.EXAMPLE`, `heading`/`body` are `blank=True`). Unlike `TabsElement` it has no `default_data()`, so the tab test's pattern does not apply here.

- [ ] **Step 2: Write the failing prepaint A/B test**

This one needs a rendered page, not a context dict, so it goes in a **new** `tests/test_filltable_gate_prepaint.py`. Write the header out in full — without `pytestmark` the tests ERROR with `RuntimeError: Database access not allowed` rather than failing the way Step 3 predicts:

```python
"""The prepaint watchdog term is driven by has_filltable_gate, not by the mere
presence of a fill-table. Asserted as an A/B: the term's presence in a gated
render alone would prove nothing about what drives it."""

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import FillTableElement
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
```

(`_lesson_url` is copied from `tests/test_filltable_restore.py:26` — `tests/` files do not share it.)

It must be an **A/B** — asserting the watchdog term is present in the gated render alone proves nothing about whether the flag drives it:

```python
def test_prepaint_watchdog_term_appears_only_when_gated(client):
    gated_body = _render_unit_with_filltable(client, "ftbl_pp1", gate=True)
    plain_body = _render_unit_with_filltable(client, "ftbl_pp2", gate=False)

    assert "__fillTableBooted" in gated_body
    assert "__fillTableBooted" not in plain_body
    assert "reveal-armed" in gated_body
    assert "reveal-armed" not in plain_body
```

with the seeding helper written out in the same file:

```python
def _render_unit_with_filltable(client, slug, gate):
    student = make_student(client, slug)
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    ft = FillTableElement.objects.create(
        data={"gate": gate, "cells": [[{"kind": "answer", "answer": "1"}]]}
    )
    Element.objects.create(unit=unit, content_object=ft)
    return client.get(_lesson_url(unit)).content.decode()
```

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py -v
```

Expected: the three context tests FAIL with `KeyError: 'has_filltable_gate'`; the prepaint A/B FAILS on the first `assert "__fillTableBooted" in gated_body`.

- [ ] **Step 4: Implement the view change**

Three edits in `build_lesson_context`:

**(a)** `has_fill_table` is currently assigned at :438, *after* `has_reveal_gate` at :424. **Replace `views.py:421-430` in full** — that is the existing three-line `# Flat query (NOT scoped to parent__isnull=True)…` comment *plus* the `has_reveal_gate` assignment it introduces — with the block below, and delete the old `has_fill_table` assignment from its former position. Replacing the comment too is deliberate: the block's own trailing comment is a superset of it, and leaving the original in place would strand it above the moved `has_fill_table` (which it does not describe) with near-identical prose repeated a few lines down.

```python
    # has_fill_table: plain CT-model filter, moved here unchanged. The block
    # comment below belongs to has_filltable_gate, NOT to this line.
    has_fill_table = node.elements.filter(
        content_type__model="filltableelement"
    ).exists()
    # CT-free by construction, per house convention (see the has_html comment
    # above and the has_stateful_elements one below). A reverse-GenericRelation
    # filter here would make get_extra_restriction resolve FillTableElement's
    # ContentType and emit a cold-cache CT SELECT on every lesson page that
    # HAS a fill-table. NO TEST CAN CATCH THAT -- test_html_element's fixtures
    # hold only HtmlElements, so has_fill_table is False and this whole term
    # short-circuits before the queryset is built; and its assertion is a
    # RELATIVE A/B (len(q3) == len(q1)), which pays any fixed cost in both arms.
    # That is why the shape is pinned by a source assertion instead.
    # Short-circuited on has_fill_table so a unit with no fill-table costs zero
    # extra queries. NOT scoped to parent__isnull=True: a gate nested in a tab
    # or callout keeps its own `unit` FK.
    has_filltable_gate = has_fill_table and FillTableElement.objects.filter(
        pk__in=node.elements.filter(
            content_type__app_label="courses", content_type__model="filltableelement"
        ).values_list("object_id", flat=True),
        data__gate=True,
    ).exists()
    # Flat query (NOT scoped to parent__isnull=True) so a gate nested inside a tab —
    # children keep their own `unit` FK — is still detected. Both gate types arm the
    # pre-hide + reveal.js; only fill-gates need fillgate.js. A gating fill-table
    # arms them too, which is what loads reveal.js on a unit with no other gate.
    has_reveal_gate = (
        node.elements.filter(
            content_type__model__in=[
                "revealgateelement",
                "fillgateelement",
                "switchgateelement",
            ]
        ).exists()
        or has_filltable_gate
    )
```

Delete the now-duplicated `has_fill_table` assignment at its old site.

⚠️ **`:438-440` is a PRE-EDIT line number — do not delete `:438-440` after inserting the block above.** The replacement swaps 10 lines (`:421-430`) for roughly 35, so the old assignment ends up ~25 lines lower and post-edit `:438-440` lands *inside* the freshly inserted comment/`has_filltable_gate` block: following the stated order literally deletes three lines of the code you just added. This is the same hazard Task 5 flags for `filltable.js`. **Either** delete the old assignment **first** and then insert the replacement, **or** key the deletion on its content rather than its position:

```python
    has_fill_table = node.elements.filter(
        content_type__model="filltableelement"
    ).exists()
```

**Step 8's `test_has_fill_table_is_assigned_exactly_once` is the check that this deletion actually happened** — a leftover duplicate is otherwise invisible to the entire suite and to ruff. Note it also catches the mirror mistake: deleting the *new* copy instead of the old one leaves the count at 1 but strands `has_fill_table` below its first use, which is a `NameError` on the first lesson page and fails loudly.

**(b)** `FillTableElement` is **already imported** at `views.py:52`. Do not add a second import — `ruff` will flag it.

**(c)** Add to the return dict (:502-529), next to `has_fill_table`:

```python
        "has_filltable_gate": has_filltable_gate,
```

**(d)** Correct the stale justification in the `has_stateful_elements` comment. Only **one**
of the two comments actually makes the false claim: `:411-412` merely says "app_label-pinned
… to avoid cold-cache ContentType SELECTs" and cites no test, which is fine. The one to fix
is at `:458-459`, whose last clause reads:

```python
    # get_for_model ct-ids were rejected because cold-cache CT SELECTs break
    # tests/test_html_element.py's query-count assertion.
```

Replace those two lines with:

```python
    # get_for_model ct-ids were rejected to avoid cold-cache CT SELECTs. NOT
    # because tests/test_html_element.py catches them -- it does not: its
    # assertion is len(q3) == len(q1), a RELATIVE A/B that pays any fixed cost
    # in both arms. See test_filltable_gate_query_shape.py for why that shape
    # needs a source assertion instead.
```

Prose only — no behaviour changes, and `has_stateful_elements` itself is untouched. This is
the same upkeep Task 2 Step 10 performs on `courses.css`, and it is done here because this
task is already editing this function and has just established the claim is false.

- [ ] **Step 5: Add the boot flag and its source guard — BEFORE the template term**

Create `courses/tests/test_filltable_gate_static.py` with its boot-flag assertion only. Task 5 Step 1 extends this same file with the cascade and saveFlag guards; write the docstring now so that task only appends:

```python
"""Source guards for the fill-table gate's client side.

A boot flag that is never assigned makes lesson_unit.html's watchdog disarm the
pre-hide on EVERY load, quietly defeating it -- with no visible symptom, because
the content is merely revealed early.
"""

from pathlib import Path

SRC = Path("courses/static/courses/js/filltable.js").read_text(encoding="utf-8")


def test_boot_flag_is_assigned():
    assert "window.__fillTableBooted = true" in SRC
```

Confirm it FAILS — `filltable.js` carries no such assignment today (`grep -n Booted` returns nothing):

```bash
uv run pytest courses/tests/test_filltable_gate_static.py -v
```

Then add, at the top of `filltable.js`'s IIFE, immediately after `"use strict";`:

```js
(function () {
  "use strict";

  // Parse-time boot flag, mirroring fillgate.js / switchgate.js: lesson_unit.html's
  // prepaint watchdog disarms the pre-hide at DOMContentLoaded if this is still
  // falsy, so a dead filltable.js cannot trap content permanently hidden.
  window.__fillTableBooted = true;
```

Re-run the same command and confirm it now PASSES. Only then proceed to Step 6 — the term added there reads this flag.

- [ ] **Step 6: Add the watchdog term to the template**

`templates/courses/lesson_unit.html:11`:

```
      if (!window.__revealBooted{% if has_fill_gate %} || !window.__fillGateBooted{% endif %}{% if has_switch_gate %} || !window.__switchGateBooted{% endif %}{% if has_filltable_gate %} || !window.__fillTableBooted{% endif %}) {
```

No change to the script-loading block: `filltable.js` already loads under `has_fill_table`, and `reveal.js` now loads because `has_reveal_gate` includes gating tables.

- [ ] **Step 7: Run to verify they pass**

```bash
uv run pytest tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py \
  courses/tests/test_filltable_gate_static.py tests/test_html_element.py \
  courses/tests/test_reveal_gate_view_flag.py courses/tests/test_reveal_gate_render.py \
  courses/tests/test_switchgate_context.py courses/tests/test_fillgate_restore.py \
  courses/tests/test_switchgate_restore.py -v
```

Expected: all PASS. `tests/test_html_element.py` must stay green **unmodified**.

**The five gate-family files are here for the same reason Task 5 Step 5 runs the two
existing e2e suites: this task redefines a flag they own.** `has_reveal_gate` is consumed by
all three existing gate families, and this step also edits `lesson_unit.html:11` — the
template they render through. `courses/tests/test_reveal_gate_view_flag.py:94-106` asserts
`"reveal-armed" in html` / `not in html` directly, which is exactly the pair a bad
`has_reveal_gate` rewrite flips. All five must stay green **unmodified**; without them a
regression in someone else's gate family surfaces only at the final whole-suite gate, five
commits downstream and expensive to bisect.

- [ ] **Step 8: Write the query-shape source assertion**

Create `courses/tests/test_filltable_gate_query_shape.py`:

```python
"""§7's gate-detection query must stay ContentType-free.

A runtime query-count test cannot guard this and should not be re-added: the
mutant's extra get_for_model(FillTableElement) is gated on has_fill_table, not
on `gate`, so an A/B between a gated and an ungated fill-table unit pays
identical cost in both arms and the delta is 0 in every configuration.
ContentType.objects.clear_cache() does not rescue it either --
build_lesson_context's prefetch_related("content_object") re-warms the cache
in-request, and Django's _add_to_cache populates the (app_label, model) key
alongside the id key. tests/test_html_element.py does not guard it either: its
fixtures hold only HtmlElements, so has_fill_table is False and the term
short-circuits before the mutant is reached.
"""

from pathlib import Path

SRC = Path("courses/views.py").read_text(encoding="utf-8")


def _gate_term(src):
    start = src.index("has_filltable_gate = ")
    return src[start : src.index("has_reveal_gate = ", start)]


def test_gate_query_uses_the_object_id_shape():
    term = _gate_term(SRC)
    assert "object_id" in term
    assert "pk__in" in term
    assert "data__gate=True" in term


def test_gate_query_does_not_use_a_reverse_generic_relation():
    assert "elements__unit=" not in _gate_term(SRC)


def test_has_fill_table_is_assigned_exactly_once():
    # Step 4(a) MOVES has_fill_table above has_filltable_gate; a forgotten
    # deletion at the old site leaves it assigned twice. Nothing else in the
    # repo can see that: it is valid Python, ruff's F811 does not cover plain
    # variable reassignment, the recomputed value is identical so every context
    # test stays green, and test_html_element.py's len(q3) == len(q1) is a
    # RELATIVE A/B that pays the duplicate query in both arms.
    # `"has_fill_table": has_fill_table,` in the return dict does not match --
    # no ` = ` -- and `has_filltable_gate = ` differs in the underscore.
    assert SRC.count("has_fill_table = ") == 1
```

Then **run it green before falsifying**:

```bash
uv run pytest courses/tests/test_filltable_gate_query_shape.py -v
```

Expected: all three PASS immediately — the implementation landed in Step 4, so unlike the rest of the plan these are green-on-write (the same situation Task 3 Step 3 flags for its three already-green tests). Running here matters precisely *because* their first execution would otherwise be under Step 9's mutant: `_gate_term`'s `src.index("has_reveal_gate = ", start)` raises `ValueError` if the block was laid out differently — a broken helper, not a working guard — and under a mutant that reads as success.

- [ ] **Step 9: Falsify everything in this task**

0. Delete `window.__fillTableBooted = true;` from `filltable.js` → `test_boot_flag_is_assigned` RED, everything else GREEN — including the prepaint A/B, which asserts the *template term* is present in the HTML and is indifferent to whether any script assigns the flag. (Numbered 0 because it falsifies Step 5's JS change rather than the view work the other mutants target.)
1. **Restore, then** drop `or has_filltable_gate` from `has_reveal_gate` → `test_has_filltable_gate_flag`, `test_has_filltable_gate_flag_when_nested_in_a_callout` **and** the prepaint A/B go RED — `reveal-armed` is emitted from **two** `{% if has_reveal_gate %}` blocks — the prepaint script (`lesson_unit.html:5-17`) and the pre-hide `<style>` in `extra_css` (`:38-48`) — so both `__fillTableBooted` and every `reveal-armed` occurrence vanish from the gated render. Cite both; `courses/tests/test_reveal_scope_agreement.py:32-39` exists because that duplication trips people up.
2. Restore, then omit `"has_filltable_gate": has_filltable_gate,` from the return dict → **all four** new tests go RED: the three context tests raise `KeyError` reading `ctx["has_filltable_gate"]`, and the prepaint A/B fails on the missing term. The A/B still earns its place — it is the only one that proves the *template* term is driven by the flag rather than by the mere presence of a fill-table, which no context-dict assertion can show.
3. Restore, then scope the inner query to `parent__isnull=True` → the callout test goes RED, the top-level test stays GREEN.
4. Restore, then **drop `data__gate=True` from the filter** (leaving `pk__in=…`) → **three** tests RED: `test_ungated_filltable_sets_neither_gate_flag` (an ungated table now arms both flags), the **prepaint A/B** on `assert "__fillTableBooted" not in plain_body` (its plain arm seeds an ungated fill-table, which now arms `has_reveal_gate` and emits the whole prepaint block), and the query-shape source test on its `data__gate=True` assertion. Everything else GREEN. Without this mutant that test's semantic claim is reddened only by mutant 2's blanket `KeyError` — the "one combined mutant lets the others hide" failure this plan warns about in Tasks 1 and 6.

   Note that the `has_fill_table and` short-circuit in front of the query is **deliberately unguarded**: it is a pure query-count optimisation, and no test can falsify it. `tests/test_html_element.py` pays the same cost in both arms of any A/B, so its delta stays 0 whether the short-circuit is present or not. Do not add a mutant for it expecting a RED.
5. Restore, then rewrite the query as `FillTableElement.objects.filter(elements__unit=node, data__gate=True)` → **both** query-shape source assertions go RED (the rewrite drops `pk__in` and `object_id` as well as adding `elements__unit=`), while **every runtime test stays GREEN**. That second half is the contrast that matters, and exactly why this guard has to be a source assertion.
6. Restore, then **re-add a second `has_fill_table` assignment below the `has_reveal_gate` block** (roughly where it sat pre-edit — the `:438-440` of Step 4(a) is a *pre-edit* number and no longer points there), simulating the forgotten deletion in Step 4(a) → `test_has_fill_table_is_assigned_exactly_once` RED, and **everything else in the entire run GREEN** — including `tests/test_html_element.py`, whose relative `len(q3) == len(q1)` A/B pays the duplicate query in both arms. That total-silence contrast is the whole reason this assertion exists; without the mutant it is green-on-write and never shown able to fail.

- [ ] **Step 10: Restore, re-run, then commit**

Mutant 6 left a duplicate `has_fill_table` assignment in `courses/views.py` — edit it back out, and confirm mutant 5's reverse-generic rewrite was already restored before it. Both are valid Python that ruff accepts happily, so without this re-run the mutated file is committed with source assertions RED:

```bash
uv run pytest tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py \
  courses/tests/test_filltable_gate_static.py courses/tests/test_filltable_gate_query_shape.py \
  tests/test_html_element.py \
  courses/tests/test_reveal_gate_view_flag.py courses/tests/test_reveal_gate_render.py \
  courses/tests/test_switchgate_context.py courses/tests/test_fillgate_restore.py \
  courses/tests/test_switchgate_restore.py -v
```

Expected: all PASS — the five gate-family files included, still **unmodified** (see Step 7).
Then:

```bash
uv run ruff check --no-cache courses/views.py tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py courses/tests/test_filltable_gate_query_shape.py courses/tests/test_filltable_gate_static.py
uv run ruff format --check courses/views.py tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py courses/tests/test_filltable_gate_query_shape.py courses/tests/test_filltable_gate_static.py
git add courses/views.py courses/static/courses/js/filltable.js templates/courses/lesson_unit.html tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py courses/tests/test_filltable_gate_query_shape.py courses/tests/test_filltable_gate_static.py
git commit -m "feat(filltable): detect a gating table at the page level

reveal.js loads only under has_reveal_gate, so without this term the cascade
engine never loads on a unit whose only gate is a fill-table. CT-free query
shape, guarded by a source assertion -- a runtime query-count A/B provably
cannot falsify it. The boot flag ships here rather than with the cascade call:
the watchdog term reads it, so shipping the term first would disarm the
pre-hide on every gated page until that later commit landed."
```

---

### Task 5: Call the cascade, and resolve the focus target

**Files:**
- Modify: `courses/static/courses/js/filltable.js` — `submit`'s all-correct branch only. The boot flag at the top of the IIFE already landed in **Task 4 Step 5**; do not add it again. **Every `filltable.js` line number in this task is a PRE-Task-4 number** (the branch is at ~:57-60 on master): Task 4 Step 5 inserts a blank line, a three-line comment and the assignment at the top of the same IIFE, so by the time this task runs everything below has shifted down by ~5. Key on the code — `if (data.all_correct === true && …)` — not on the line number.
- Modify: `courses/static/courses/js/reveal.js` — `focusTargetIn` (~:106-119)
- Test: `courses/tests/test_reveal_refactor_static.py` (extend), `courses/tests/test_filltable_gate_static.py` (extend — Task 4 created it)

**Interfaces:**
- Consumes: the marker (Task 2), and `window.__fillTableBooted` (Task 4).
- Produces: the live cascade behaviour Task 9's e2e asserts.

**The `saveFlag` line does not change.** Writing `{done: true, open: true}` here would be dead code — `_val_done` strips `open` before it is stored. Leave it exactly as it is.

- [ ] **Step 1: Write the failing static tests**

**Append** to `courses/tests/test_filltable_gate_static.py` — Task 4 Step 5 created it with the module docstring, the `SRC` constant and `test_boot_flag_is_assigned`. Add only:

```python
def test_cascade_call_is_guarded_by_the_gate_attribute():
    # Without the attribute guard an UNGATED table also cascades, moving focus
    # and scrolling on every correct answer.
    assert 'hasAttribute("data-reveal-gate")' in SRC
    assert "window.libliRevealCascade" in SRC


def test_save_flag_stays_done_only():
    # _val_done strips anything else; writing `open` here would be dead code.
    assert "saveFlag(root, { done: true })" in SRC


def test_cascade_keeps_the_solved_table_on_screen():
    # cascadeFrom reads `hideWrapper = opts.hideWrapper !== false`, so OMITTING
    # the option means TRUE: gateWrap.hidden = true, and app.css:1010
    # (.lesson-block[hidden] { display: none !important }) deletes the solved
    # table and its notes from the page. For a button gate that is right -- the
    # control has been consumed. For a fill-table the wrapper IS the student's
    # work. Nothing else catches this: the restore path recomputes hideWrapper
    # itself as gate.matches(RESTORABLE) and is immune.
    assert "{ hideWrapper: false }" in SRC
```

Add to `courses/tests/test_reveal_refactor_static.py`, next to its existing `test_focus_targets_fill_gate_input`:

```python
def test_focus_targets_fill_table_input():
    # Focus resolution must special-case a fill-table gate -- its <div> is not
    # focusable. The :not([disabled]) qualifier is defensive: a disabled input
    # cannot take focus, and cascadeFrom only ever calls focusTargetIn on a
    # just-revealed wrapper, so no reachable path reaches it with disabled
    # inputs today. Pinned so the qualifier is not "cleaned up" later.
    assert "data-filltablegate" in SRC
    assert ".filltable__input:not([disabled])" in SRC
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py -v
```

Expected: **three** FAIL (`test_cascade_call_is_guarded_by_the_gate_attribute`, `test_cascade_keeps_the_solved_table_on_screen`, and `test_focus_targets_fill_table_input`). `test_boot_flag_is_assigned` is GREEN — Task 4 Step 5 already landed the flag. `test_save_flag_stays_done_only` is GREEN already — `filltable.js` reads `window.libliState.saveFlag(root, { done: true });` today (~:59 pre-Task-4, ~5 lines lower once its boot flag has landed), and this task does not change that line. It is a **pin against future drift**, not a TDD test; its mutant is "change the payload to `{ done: true, open: true }`", which belongs in Step 7.

- [ ] **Step 3: Add the cascade call**

In `submit`, replace the all-correct branch (~:57-60 **pre-Task-4**; find it by its
`if (data.all_correct === true && (data.cells || []).length > 0) {` opening line):

```js
        if (data.all_correct === true && (data.cells || []).length > 0) {
          lock(root);
          // The attribute guard is load-bearing: without it an UNGATED table also
          // cascades, adding .reveal-shown to its siblings and -- since `focus`
          // defaults to true -- moving focus and scrolling on every correct answer.
          // The libliRevealCascade guard is a defensive load-order check mirroring
          // fillgate.js/switchgate.js (reveal.js is loaded before this file, and
          // unconditionally in the editor).
          if (root.hasAttribute("data-reveal-gate") && window.libliRevealCascade) {
            // hideWrapper:false -- the solved table stays on screen with its green
            // cells; unlike a button gate, its content IS the student's work.
            window.libliRevealCascade(root, { hideWrapper: false });
          }
          // UNCHANGED: state.py::_val_done stores only {"done": True}, so sending
          // `open` here would be dead code. The restore path derives it in
          // FillTableElement.render instead.
          window.libliState.saveFlag(root, { done: true });
        }
```

- [ ] **Step 4: Add the focus branch**

In `reveal.js::focusTargetIn`, after the `[data-fillgate]` branch and before the `[data-switchgate]` one:

```js
    if (gate.matches("[data-filltablegate]")) {
      // :not([disabled]) is DEFENSIVE BY CHOICE, not a fix for a reachable bug --
      // do not justify it with a causal story. cascadeFrom calls focusTargetIn only
      // when `lastRevealed === firstNew` (reveal.js:174), i.e. on a wrapper that was
      // hidden until this instant, so its inputs cannot have been disabled by a live
      // lock(); and the server-rendered restore path uses readonly, which IS
      // focusable. The qualifier costs nothing and keeps the branch correct if a
      // future change ever routes a locked table through here.
      return gate.querySelector(".filltable__input:not([disabled])");
    }
```

**This is a deliberate correction of spec §6, recorded so the final spec-vs-code review does not read it as a misunderstanding.** The spec argues the qualifier fixes a live bug — that `lock()` disables every input on the success path and `focus()` would therefore be a silent no-op. The code is identical either way, but the reasoning is not: `cascadeFrom` calls `focusTargetIn(lastRevealed)` only when `lastRevealed === firstNew` (`reveal.js:174`), i.e. on a wrapper that was hidden until that instant, so its inputs cannot have been disabled by a live `lock()`; and the restore path renders `readonly`, which is focusable. Keep the qualifier, drop the causal claim.

`test_focus_targets_fill_table_input`'s comment in Step 1 is already written to match this framing — no edit needed there.

**The editor preview will now cascade too, and that is intended.** `editor.html` loads `reveal.js` (:229) and `filltable.js` (:279) unconditionally, and the preview renders real join rows with a real `data-check-url` — so checking a gated table in the preview fires `libliRevealCascade`, adds `.reveal-shown` to preview siblings and moves focus/scroll inside the preview pane. For a preview gate nested in a tabs element `scopeOf` returns a real `[data-tab-panel]`, so it is not a no-op there; a top-level preview gate is inert because `scopeOf` returns null. This matches what `fillgate.js` and `switchgate.js` already do in the preview, so it needs no carve-out — but do not read the "defensive load-order check" comment above as implying the preview never cascades.

This is the **only** `reveal.js` change. Leave `scopeOf`, `isGateWrapper`, `cascadeFrom` and `restoreGates` alone — in particular `cascadeFrom`'s `break` at an already-open downstream gate, whose consequence is a documented, accepted limitation (spec Error handling, pinned by e2e test 26 in Task 9).

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py -v
```

Expected: all PASS.

Then run the two **existing** e2e suites that drive the files this branch has now perturbed:

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable.py tests/test_e2e_reveal_gate.py -m e2e -v
```

Expected: all PASS, both files **unmodified**. This is the first point at which every client-side change exists (Task 2's template, Task 3's `render`, and this task's `filltable.js` + `reveal.js` edits), and these two suites are the direct behavioural guard on the "an ungated fill-table behaves byte for byte as today" constraint. Deferring them to the post-Task-10 sweep would surface a regression five commits downstream with a large blast radius to bisect — this is not a repo-wide sweep, it is the two directly affected neighbours.

- [ ] **Step 6: Falsify**

1. Delete the `hasAttribute("data-reveal-gate") &&` clause → `test_cascade_call_is_guarded_by_the_gate_attribute` RED. (The behavioural counterpart is e2e test 27 in Task 9.)
2. Restore, then **rewrite the call as `window.libliRevealCascade(root)`**, dropping the options object → `test_cascade_keeps_the_solved_table_on_screen` RED. Everything else in *this task* GREEN. (Its behavioural counterpart is e2e test 22's `_visible(page, table_row.pk)` assertion — a **forward reference**: `tests/test_e2e_filltable_gate.py` does not exist until Task 9, so do not go looking for it here. That half is verified by the matching row in Task 9 Step 8's mutant table.) This is the plan's most consequential unguarded line before this mutant existed: the solved table simply vanishes from the page, and every reload-based test stays green because `restoreGates` computes `hideWrapper` for itself.
3. Restore, then delete the `[data-filltablegate]` branch from `focusTargetIn` → `test_focus_targets_fill_table_input` RED.
4. Restore, then drop `:not([disabled])` from that selector → the same test RED. This proves only that the string is pinned — there is deliberately no behavioural counterpart, because no reachable path exercises it (see Step 4).
5. Restore, then change `filltable.js`'s save line to `saveFlag(root, { done: true, open: true })` → `test_save_flag_stays_done_only` RED. This is the drift pin promised in Step 2; without this mutant it is the one test in the task trusted without ever being shown to fail.

The boot flag's mutant is **not** here — it lives with the flag, in Task 4 Step 9 mutant 0.

- [ ] **Step 7: Restore, re-run, then commit**

Mutant 5 left `filltable.js` mutated — edit it back, then re-run before staging. `ruff` does not read JS, so the lint gate below would pass on a mutated build:

```bash
uv run pytest courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py -v
```

Expected: all PASS. Then:

```bash
uv run ruff check --no-cache courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py
uv run ruff format --check courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py
git add courses/static/courses/js/filltable.js courses/static/courses/js/reveal.js courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py
git commit -m "feat(filltable): cascade on a fully-correct gated check

Adds the attribute-guarded libliRevealCascade call and reveal.js's focus
branch; the boot flag landed with the watchdog term it feeds. The saveFlag
payload is deliberately unchanged -- _val_done strips anything but `done`."
```

---

### Task 6: Editor checkbox, and the rejected-save fix

**Files:**
- Modify: `templates/courses/manage/editor/_edit_filltable.html:38`
- Modify: `courses/static/courses/js/filltable_editor.js` (:174, :250, :937)
- Modify: `courses/element_forms.py` — add `FillTableElementForm.grid_data`
- Modify: `tests/test_editor_twin_drift.py:179-181` (reason string only)
- Test: `tests/test_filltable_editor_partial.py`, `tests/test_filltable_form.py`, and one kept e2e in `tests/test_e2e_filltable.py` (Step 8)

**Interfaces:**
- Consumes: `normalize_data`'s `gate` (Task 1).
- Produces: authors can set the flag. Nothing later depends on this.

**Why `grid_data` needs an override.** `_grid_data` (shared with `TableElementForm`) returns `model._sanitized_data(model.normalize_data(parsed))` on the bound-invalid path, deliberately re-rendering the *submitted* grid. But Task 1's suppression forces `gate` to `False` on a subset of the conditions that make `clean_data` raise — the no-answer-cell and blank-answer-cell rules are both a rejection reason *and* a suppression trigger. So an author who ticks the box and forgets one answer gets "An answer cell is blank" **and a silently unticked checkbox**, and their next Save posts `gate: false` from the DOM. The overlap is one-way: `clean_data` also raises via `_scan_spans` (an out-of-range span, checked first), `_caps_ok`, and the course-scope image check, and for those three `normalize_data` leaves `gate` at `True`. Write the override **unconditionally** so it is a no-op on those and correct on all five.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_editor_partial.py`. **That file's helper is `_render(instance)`** (line 22) — it builds `FORM_FOR_TYPE["filltable"](instance=instance)` and renders the partial. `test_partial_has_case_sensitive_checkbox` in the same file is the exact precedent for both the call and the assertion shape:

```python
# non-blank: the guard keeps `gate` on
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]


def test_partial_has_gate_checkbox_unchecked_by_default():
    html = _render(FillTableElement(data={"cells": _GATE_CELLS}))
    assert "data-gate" in html
    assert "data-gate checked" not in html


def test_partial_gate_checkbox_is_checked_for_a_gated_element():
    html = _render(FillTableElement(data={"cells": _GATE_CELLS, "gate": True}))
    assert "data-gate checked" in html
```

And the guard for the editor JS wiring. The checkbox→payload link is the entire authoring feature and nothing else covers it — Task 9's e2e all seed through the ORM, so no test drives the editor UI. This file already reads the editor JS as a `Path` (`FILLTABLE_JS`, line 17), so it costs three lines here:

```python
def test_editor_js_serializes_the_gate_flag():
    src = FILLTABLE_JS.read_text(encoding="utf-8")
    assert 'querySelector("[data-gate]")' in src
    assert "gate: !!(gate && gate.checked)" in src
    assert 'gate.addEventListener("change", serialize)' in src
```

Add to `tests/test_filltable_form.py`. **Use the file's own idiom** — the same rule Task 7 applies to `test_filltable_transfer.py`. It already defines `_data(cells, **kw)` (:27) and `_bind(data_dict)` (:33), which every other test there uses, and both `json` (:1) and `FillTableElementForm` (:5) are already imported, so **no import changes are needed**:

```python
def test_rejected_save_keeps_the_gate_ticked():
    # normalize_data suppresses `gate` for exactly the grid that makes clean_data
    # raise here, so without the grid_data override the author's tick is silently
    # lost and their next Save posts gate: false from the DOM.
    # blank answer -> rejected
    form = _bind(_data([[{"kind": "answer", "answer": ""}]], gate=True))
    assert not form.is_valid()
    assert form.grid_data["gate"] is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_editor_partial.py tests/test_filltable_form.py -k gate -v
```

Expected, enumerated — a blanket "FAIL" would leave Step 8's mutants 4-6 with no baseline to check their *first assertion* / *third assertion* predictions against:

- `test_partial_has_gate_checkbox_unchecked_by_default` — **FAILS** on its first assertion (`"data-gate" in html`); the attribute does not exist yet.
- `test_partial_gate_checkbox_is_checked_for_a_gated_element` — **FAILS**, no `data-gate checked` in the render.
- `test_editor_js_serializes_the_gate_flag` — **FAILS on its first assertion** (`querySelector("[data-gate]")`), so assertions two and three are not yet reached.
- `test_rejected_save_keeps_the_gate_ticked` — **FAILS** on `form.grid_data["gate"] is True`; the shared `_grid_data` hands back `normalize_data`'s suppressed `False`.

- [ ] **Step 3: Add the checkbox**

`templates/courses/manage/editor/_edit_filltable.html`, immediately after the `data-case-sensitive` label on line 38:

```html
    <label><input type="checkbox" data-case-sensitive {% if d.case_sensitive %}checked{% endif %}> {% trans "Case-sensitive" %}</label>
    <label><input type="checkbox" data-gate {% if d.gate %}checked{% endif %}> {% trans "Reveal the rest of this section when all cells are correct" %}</label>
```

**The label names the boundary deliberately.** `cascadeFrom` never leaves `scopeOf`'s scope, so a gated table inside a callout reveals only later `.callout__child`s and nothing after the callout. "Reveal what follows" would overpromise.

- [ ] **Step 4: Wire the editor JS — three sites**

`courses/static/courses/js/filltable_editor.js`:

**(a)** after `var caseSensitive = ...` (~:174):
```js
    var gate = editor.querySelector("[data-gate]");
```

**(b)** in the `serialize` literal, after `case_sensitive` (~:250):
```js
        case_sensitive: !!(caseSensitive && caseSensitive.checked),
        gate: !!(gate && gate.checked),
```

**(c)** in the listener block, after the `caseSensitive` listener (~:937):
```js
    if (caseSensitive) caseSensitive.addEventListener("change", serialize);
    if (gate) gate.addEventListener("change", serialize);
```

- [ ] **Step 5: Add the `grid_data` override**

In `courses/element_forms.py`, replace `FillTableElementForm`'s existing `grid_data` property — **the one whose `def` is at `:1636`**:

⚠️ **There are TWO byte-identical `grid_data` properties in this file** — `TableElementForm`'s (`def` at `:1551`) and `FillTableElementForm`'s (`def` at `:1636`), both exactly `return _grid_data(self)`. A bare search lands on the wrong one first. Disambiguate by position: `class FillTableElementForm(_CourseScopedMediaForm)` opens at `:1575`, so the **second** occurrence is the target. Editing `TableElementForm`'s copy instead hands the plain table a `gate` key it has no field for and leaves `test_rejected_save_keeps_the_gate_ticked` red in a way that reads like a normalizer bug.

```python
    @property
    def grid_data(self):
        d = _grid_data(self)
        # PRESERVE THE AUTHOR'S TICK across a rejected save. normalize_data (which
        # _grid_data runs) suppresses `gate` for the no-answer-cell and
        # blank-answer-cell grids -- which are ALSO two of clean_data's five
        # rejection reasons -- so the shared path would hand the template an
        # unticked box, silently dropping the author's intent while the error
        # message points at the answer cell instead. Unconditional on purpose: a
        # no-op for the other three rejection paths (_scan_spans, _caps_ok, image
        # scope), where normalize_data leaves `gate` alone.
        if self.is_bound and not self.is_valid():
            raw = self.data.get("data")
            if isinstance(raw, str):
                try:
                    submitted = json.loads(raw)
                except ValueError:
                    submitted = None
                if isinstance(submitted, dict):
                    return {**d, "gate": bool(submitted.get("gate"))}
        return d
```

`json` is already imported in `element_forms.py`. The template keeps reading `d.gate`, so no context plumbing changes.

- [ ] **Step 6: Update the twin-drift reason string**

`tests/test_editor_twin_drift.py:179-181` currently says the fill-table `serialize` payload "carries two extra document-level fields, case_sensitive and prompt". There are now three:

```python
    "serialize": "fill-table emits three cell kinds (static/answer/image) where "
    "the plain table emits two (text/image), AND its payload carries three extra "
    "document-level fields, case_sensitive, prompt and gate",
```

The test stays green either way — the reason is prose — but that file's docstring says the classification is the point, so the documentation must not rot.

- [ ] **Step 7: Run to verify they pass**

```bash
uv run pytest tests/test_filltable_editor_partial.py tests/test_filltable_form.py tests/test_editor_twin_drift.py -v
```

Expected: all PASS. `EXPECTED_COUNTS = {TABLE_JS: 30, FILL_JS: 36}` must be untouched — confirm no new `function` was introduced rather than assuming it.

- [ ] **Step 8: Look at the controls row — the only step that opens the editor**

Every other check in this task is a substring assertion on rendered HTML or on JS source; none of them can see a layout regression. The new label is ~54 characters and lands in `.table-editor__controls.filltable-editor__controls`, whose **next flex item** is the `.filltable-editor__prompt-field` label — both are siblings *inside* the same row (`_edit_filltable.html`), not a row and its sibling.

**Get the mechanism right, or the criterion below is unfalsifiable.** This is **not** a basis-weighted-shrink squeeze. `.table-editor__controls` is `display: flex; flex-wrap: wrap` (`courses/static/courses/css/editor.css:788-789`) and `.filltable-editor__prompt-field` is `flex: 1 1 16rem; min-width: 12rem` (`courses/static/courses/css/courses.css:1323-1326`). Flex shrink **cannot** cross `min-width`, and a wrapping row wraps instead of squeezing — so "the Instruction field crushed below 12rem" is a state the CSS cannot produce, and a criterion phrased that way passes on every build, broken or not. That is the same cannot-fail defect this plan rejects at Task 2 Step 7 (the inert lookbehind) and Task 9 Step 9 (`git diff` on an untracked path). The **real** risk is the opposite: the row wraps to more lines and grows taller, pushing the grid down, or a long unbreakable label forces horizontal overflow.

**Reuse the existing editor harness rather than inventing one** — the editor needs a Platform Admin, so a plain `make_student` login will not reach it. `tests/test_e2e_filltable.py` already carries the whole fixture path: **`_editor_context(page, live_server, username, slug)`** (:346 — mints the PA user, a course and a lesson node; `_make_pa_user` at :329 creates only a user and is not enough on its own), **`_seed_filltable_for_images(unit)`** (:376 — a grid whose non-blank answer cell already satisfies the client-side submit guard), `_goto_editor` (:368) and `_open_edit` (:398). Write a scratch test in that file's shape — decorated `@pytest.mark.django_db(transaction=True)` and taking `(page, live_server)`, mirroring `test_author_two_image_cells_with_distinct_alts` (`tests/test_e2e_filltable.py:405`). **The decorator is not optional:** Playwright runs in another thread and cannot see rows held in an uncommitted test transaction, so without it `_goto_editor` lands on an empty editor and you will debug a phantom layout problem. It seeds a fill-table, opens its editor panel, and screenshots `.filltable-editor__controls` to the scratch directory:

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable.py -m e2e -k <your_scratch_test_name> -v
```

**Dark mode needs the user row, not a cookie** — and `_editor_context` returns `(unit, asset_a, asset_b)`, so it hands you no handle on the PA user it created. Re-fetch it, then set the field, *before* calling `_goto_editor` (which calls `_login` internally, so there is no separate login call to sit in front of):

```python
from django.contrib.auth import get_user_model
get_user_model().objects.filter(username="ftbl_gate").update(theme="dark")
```

(`"ftbl_gate"` is the username the Step 8 snippet passes to `_editor_context`; keep the two
in step if you rename it.) This `update()` and the `page.screenshot` calls are the **only**
throwaway lines in this test — everything in the snippet above and below them ships.

Same gotcha Task 9 Step 9 calls out for the student.

**Pin the viewport — the whole risk here is width-dependent, so an unnamed width judges whatever the `page` fixture happens to default to and gives a later reviewer nothing to reproduce.** Capture at two widths, in **one run, as two passes**: set the first width *before* `_goto_editor`, shoot, then resize and shoot again. Playwright reflows on resize, so the second shot needs no reload.

⚠️ **The two `set_viewport_size` calls are a sequence, not alternatives — do not place them adjacently.** Back-to-back, the second overrides the first before the page is ever loaded, only the 1024 layout is ever observed, and the 1280 "common case" capture silently never happens while the step still reports two widths checked.

```python
page.set_viewport_size({"width": 1280, "height": 800})   # BEFORE _goto_editor
_goto_editor(page, live_server, "ftbl_gate", unit)
_open_edit(page, element.pk)
page.locator(".filltable-editor__controls").screenshot(path=<scratch>/controls-1280.png)

page.set_viewport_size({"width": 1024, "height": 800})   # then resize and re-shoot
page.locator(".filltable-editor__controls").screenshot(path=<scratch>/controls-1024.png)
```

**Pass criterion, checked at both widths — measured, not eyeballed**, because the eyeballed version cannot fail (see above). Assert both, then look at the images for anything the numbers miss:

```python
row = page.locator(".filltable-editor__controls")
# 1. No horizontal overflow: a long unbreakable label is the one thing that can
#    force it, and it is invisible in a screenshot cropped to the row.
assert page.evaluate(
    '(() => { const n = document.querySelector(".filltable-editor__controls");'
    " return n.scrollWidth <= n.clientWidth; })()"
) is True
# 2. The Instruction input is still usable, i.e. the field really did wrap onto
#    its own line rather than ending up a sliver. Its min-width guarantees 12rem
#    (192px) for the LABEL; this checks the INPUT inside it, which has
#    `flex: 1; min-width: 0` (courses.css:1327) and so has NO floor of its own.
#    That is the assertion with teeth here.
assert row.locator("input[data-prompt]").bounding_box()["width"] >= 120
```

Wrapping onto its own line is an accepted outcome; a sliver input, or horizontal overflow, is not. Judge dark on its own terms rather than assuming the light result carries. The captures are a throwaway review artifact, not committed.

**Keep the test, drop only the screenshots.** The tick → Save → stored-flag round trip is the one seam in this feature that *no* runtime test crosses: Step 1's three source assertions pin the strings (`querySelector("[data-gate]")`, `gate: !!(gate && gate.checked)`, the `change` listener) but never execute them together, and every Task 9 e2e seeds through the ORM rather than the editor. Since this step already stands up the whole PA-authenticated fixture, keeping a behavioural version costs three lines:

Written out in full — this is the one test in the task that must run as pasted, so the
decorator and the `_editor_context` line are shown rather than described. `_editor_context`
returns a **three**-tuple `(unit, asset_a, asset_b)` (`tests/test_e2e_filltable.py:346-365`);
the two assets are unused here, hence the underscores. Its `username` and `slug` are two
separate arguments, and `_goto_editor` needs the *same* username back:

```python
@pytest.mark.django_db(transaction=True)
def test_editor_gate_checkbox_round_trips(page, live_server):
    # The decorator is NOT optional: Playwright runs in another thread and cannot
    # see rows held in an uncommitted test transaction.
    unit, _asset_a, _asset_b = _editor_context(
        page, live_server, "ftbl_gate", "ftbl-gate"
    )
    # Use the FILE'S OWN IDIOM: a function-local import. tests/test_e2e_filltable.py
    # already imports FillTableElement inside four separate function bodies
    # (:93, :300, :381, :489) and has no module-level import of it. Matching that
    # keeps this a ONE-hunk diff and sidesteps the question of whether a new
    # module-level import should replace the four locals (it should not -- that
    # would be unrelated churn in a feature commit).
    from courses.models import FillTableElement

    # _seed_filltable_for_images returns the Element JOIN ROW (it ends
    # `return add_element(unit, el)`), not the concrete element -- reach the
    # FillTableElement through object_id.
    element = _seed_filltable_for_images(unit)
    obj = FillTableElement.objects.get(pk=element.object_id)

    _goto_editor(page, live_server, "ftbl_gate", unit)
    _open_edit(page, element.pk)
    page.locator("[data-edit-slot] [data-gate]").check()

    # There is NO _save helper in this file -- the two authoring tests save
    # inline (:436-437). Do not copy _save from test_e2e_table_editor.py or
    # test_e2e_table_cell_images.py: both wait on [data-table-editor], the
    # PLAIN-table selector, and would time out here on a correct build.
    page.locator(
        "[data-edit-slot] .editor-form__actions button[type='submit']"
    ).click()
    # MANDATORY before the DB read. transaction=True means both threads share a
    # committed DB, so refresh_from_db() fired before the POST round-trips reads
    # the PRE-save row and fails on a correct build. The detach IS the barrier.
    page.wait_for_selector(
        "[data-edit-slot] [data-filltable-editor]", state="detached"
    )

    obj.refresh_from_db()
    assert obj.data["gate"] is True
```

So: remove the `page.screenshot` calls, the two `page.set_viewport_size(...)` calls and the dark-theme `update()` before Step 10, but **keep the test itself**, named `test_editor_gate_checkbox_round_trips`, and add `tests/test_e2e_filltable.py` to Step 10's `git add` and ruff commands. That converts a throwaway harness into the only end-to-end guard on the authoring path.

If the row does not survive, the fix belongs here (a shorter label, or letting the checkbox wrap) — do not leave it for the branch gate to discover.

⚠️ **If you shorten the label, it is the msgid, and three downstream sites hardcode it.** Update Task 8 Step 1's English snippet, Task 8 Step 2's Polish snippet, and Task 10 Steps 2 and 4 (both the `.po` entry and the `grep` pattern) to the new string *before* running them. Otherwise Task 10's grep matches nothing and its "no `#, fuzzy` in the output" expectation passes trivially on empty output.

- [ ] **Step 9: Falsify**

1. Drop `{% if d.gate %}checked{% endif %}` → `test_partial_gate_checkbox_is_checked_for_a_gated_element` RED.
2. Restore, then hardcode `checked` on the new `<input data-gate>` (drop the `{% if %}` but keep the attribute) → `test_partial_has_gate_checkbox_unchecked_by_default` RED, and the checked-state test stays GREEN. Mutant 1 leaves this test green, so it needs its own.
3. Restore, then **revert `grid_data`'s body to `return _grid_data(self)`** — again `FillTableElementForm`'s copy at `:1636`, **not** `TableElementForm`'s identical one at `:1551` (see Step 5's warning; mutating the wrong class reddens the plain-table tests instead and looks nothing like the failure predicted here) → `test_rejected_save_keeps_the_gate_ticked` RED. Revert the body, do **not** delete the property: removing `FillTableElementForm.grid_data` entirely breaks `{% with d=form.grid_data %}` in `_edit_filltable.html` and reddens the whole of `tests/test_filltable_editor_partial.py` plus `resolved_grid_cells`, which is a different failure and not the one being tested for.
4. Restore, then drop `gate: !!(gate && gate.checked),` from `serialize` → `test_editor_js_serializes_the_gate_flag` RED.
5. Restore, then delete `var gate = editor.querySelector("[data-gate]");` → the same test RED on its *first* assertion.
6. Restore, then delete the `gate.addEventListener("change", serialize);` line → the same test RED on its *third* assertion.

7. Restore, then **remove the `data-gate` attribute from the partial altogether** (drop the whole new `<label>`) → `test_partial_has_gate_checkbox_unchecked_by_default` RED **on its first assertion** (`"data-gate" in html`), and `test_partial_gate_checkbox_is_checked_for_a_gated_element` RED too. Mutant 2 reddens that test's *second* clause only, so without this one its presence clause is falsified solely by the pre-implementation RED — unlike every sibling assertion in this task.

Mutants 4-6 are separate for the reason Task 1 Step 6 gives: that test makes three independent assertions, and one combined mutant would let two of them hide.

**Restore mutant 7 before this block.** The e2e test does `page.locator("[data-edit-slot] [data-gate]").check()`, so with the `<label>` still removed that locator never resolves and the test dies on a 30-second Playwright timeout rather than the assertion predicted below — a failure that looks nothing like the one you are trying to observe.

**Falsify the kept e2e test too — do not skip this.** `test_editor_gate_checkbox_round_trips` (Step 8) is written after the implementation lands, so it is green from birth, and it is the *only* test crossing the tick → Save → stored-flag seam. Trusting it unfalsified is therefore the worst case here, not the safest. **Use mutant 4 specifically** — `gate: !!(gate && gate.checked)` dropped from `serialize`. It is the only one of the three that produces the failure described below:

- **Mutant 6 leaves this test GREEN**, so do not use it. Deleting the `change` listener does not break the save path at all: `filltable_editor.js` registers `document.addEventListener("submit", onSubmit, true)` (:1008, capture phase, "run before the POST") and `onSubmit` calls `editor.__filltableSerialize()` (:979), which re-runs `serialize()` over the live DOM and reads `gate.checked` directly. The listener is a live-preview convenience, behaviourally redundant on submit. It is falsified by `test_editor_js_serializes_the_gate_flag`'s **third** assertion, and only there.
- **Mutant 5 breaks serialisation outright** rather than dropping the flag — deleting `var gate = …` leaves `gate` an undeclared identifier, so `serialize` throws. The test does go red, but for the wrong reason and with a confusing failure.

With mutant 4 in place, run:

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable.py -m e2e -k test_editor_gate_checkbox_round_trips -v
```

Expected: RED on `assert obj.data["gate"] is True` — the checkbox still ticks and the form still saves, but the serialized payload never carries the flag, so the stored row keeps `gate: false`. Then revert the mutant and confirm it goes GREEN again.

- [ ] **Step 10: Restore, re-run, then commit**

**Step 9 already restored both mutants** — mutant 7's `<label>` was put back before the e2e block, and mutant 4 was reverted at the end of it. **Confirm** both are actually back before staging rather than assuming: `ruff` reads neither the template nor the editor JS, so the lint gate below cannot see either, and the re-run is the only thing that would:

```bash
uv run pytest tests/test_filltable_editor_partial.py tests/test_filltable_form.py tests/test_editor_twin_drift.py -v
```

Expected: all PASS. Then confirm Step 8's kept test is green and carries **no** screenshot or theme leftovers:

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable.py -m e2e -k test_editor_gate_checkbox_round_trips -v
# Expect exactly ONE hunk: the new test, whose FillTableElement import is
# function-local per the file's own idiom (Step 8). The four pre-existing
# function-local imports at :93/:300/:381/:489 stay exactly as they are -- do
# not consolidate them into a module-level import, that is unrelated churn.
# Anything else -- a screenshot call, a set_viewport_size call, a theme write --
# is a capture leftover. This file IS tracked, so git diff works here (unlike
# Task 9's still-untracked new file, where it would be silent).
git diff tests/test_e2e_filltable.py
```

Then:

```bash
uv run ruff check --no-cache courses/element_forms.py tests/test_filltable_form.py tests/test_filltable_editor_partial.py tests/test_editor_twin_drift.py tests/test_e2e_filltable.py
uv run ruff format --check courses/element_forms.py tests/test_filltable_form.py tests/test_filltable_editor_partial.py tests/test_editor_twin_drift.py tests/test_e2e_filltable.py
git add templates/courses/manage/editor/_edit_filltable.html courses/static/courses/js/filltable_editor.js courses/element_forms.py tests/test_editor_twin_drift.py tests/test_filltable_editor_partial.py tests/test_filltable_form.py tests/test_e2e_filltable.py
git commit -m "feat(filltable): author checkbox for the gate

Includes a grid_data override: normalize_data suppresses `gate` for exactly
the grids that make clean_data raise, so without it a rejected save silently
unticked the author's checkbox and the next save posted gate: false."
```

---

### Task 7: Transfer export, and the normalizer-routing invariant

**Files:**
- Modify: `courses/transfer/export.py` — `_ser_fill_table`'s return literal (~:306-312)
- Test: `tests/test_filltable_transfer.py`

**Interfaces:**
- Consumes: `normalize_data`'s `gate` (Task 1).
- Produces: `gate` survives export/import round-trips.

The importer needs nothing. `_build_fill_table`'s real tail is a **saved instance inside a `(obj, children)` pair** (`courses/transfer/importer.py:627-630`):

```python
    return (
        _clean_save(FillTableElement(data=FillTableElement.normalize_data(data))),
        (),
    )
```

Both wrappers matter downstream: the pair shape is why Step 1 unpacks `obj, _children = BUILDERS["fill_table"](...)`, and `_clean_save` is what Step 5's mutant 2 warns you to keep. The normalizer supplies `gate` — `False` for a legacy bundle lacking the key, and forced off for a bundle whose grid cannot satisfy it. `_val_fill_table` needs nothing either: it checks only gross structural corruption and does no exact-keys check, which is also why an **older** libli can import a newer bundle — it ignores the unknown key and degrades to an ungated table.

- [ ] **Step 1: Write the failing tests**

**Use the file's own idiom.** `tests/test_filltable_transfer.py` imports `SERIALIZERS`, `BUILDERS`, `VALIDATORS` and `MediaIdMap`, and calls them through the registries — the module-private `_ser_fill_table` / `_build_fill_table` are never imported. Builders return a `(obj, children)` pair. The routing-invariant test additionally needs `json` and `FillTableElementForm`, neither of which the file imports yet. **Placement matters** (`I` is selected with `force-single-line`): `import json` goes on its own as the stdlib block, above the blank line preceding `import pytest`; `from courses.element_forms import FillTableElementForm` goes into the first-party block **between `courses.builder` (:5-6) and `courses.models` (:7)**. Note that block is ruff-ordered, not naively alphabetical — `SERIALIZERS` precedes `MediaIdMap` at :8-9 — so insert by module path and let `ruff check` confirm.

```python
# non-blank: the guard keeps `gate` on
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]


def test_export_carries_the_gate_flag():
    src = FillTableElement.objects.create(data={"gate": True, "cells": _GATE_CELLS})
    payload = SERIALIZERS["fill_table"][1](src, MediaIdMap())
    assert payload["gate"] is True


def test_round_trip_preserves_the_gate_flag():
    src = FillTableElement.objects.create(data={"gate": True, "cells": _GATE_CELLS})
    payload = SERIALIZERS["fill_table"][1](src, MediaIdMap())
    obj, _children = BUILDERS["fill_table"](payload, {})
    assert obj.normalized_data["gate"] is True


def test_legacy_bundle_without_gate_imports_ungated():
    payload = {
        "header_row": False, "header_col": False, "case_sensitive": False,
        "border": "grid", "prompt": "", "cells": _GATE_CELLS,
    }
    obj, _children = BUILDERS["fill_table"](payload, {})
    assert obj.normalized_data["gate"] is False


def test_every_production_write_path_stores_a_real_boolean():
    # views.py's has_filltable_gate uses data__gate=True, which matches the JSON
    # literal `true` only. That is exact rather than fragile BECAUSE every write
    # path routes through normalize_data. There are THREE production write paths:
    # the form, transfer's _build_fill_table, and the LAL loader
    # (courses/lal_loader/builders.py:293 -- it already calls normalize_data).
    # The two exercised below are the two reachable from a bundle or a POST; the
    # LAL path is a one-off import tool and is asserted by inspection, not here.
    form = FillTableElementForm(
        data={"data": json.dumps({"gate": "yes", "cells": _GATE_CELLS})}
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["data"]["gate"] is True   # a real bool, not "yes"

    obj, _children = BUILDERS["fill_table"]({"gate": "yes", "cells": _GATE_CELLS}, {})
    assert obj.data["gate"] is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_transfer.py -k "gate or real_boolean" -v
```

A bare `-k gate` would select only three of these — `test_every_production_write_path_stores_a_real_boolean` contains no "gate" — leaving the enumeration below one short of what the command runs.

Expected, all four enumerated:
- `test_export_carries_the_gate_flag` — **FAILS**, `KeyError: 'gate'`.
- `test_round_trip_preserves_the_gate_flag` — **FAILS**, `assert False is True`: the serializer drops `gate`, so the rebuilt element normalizes it back to `False`.
- `test_legacy_bundle_without_gate_imports_ungated` — PASSES already (Task 1).
- `test_every_production_write_path_stores_a_real_boolean` — PASSES already (Task 1).

- [ ] **Step 3: Add the export line**

`courses/transfer/export.py`, in `_ser_fill_table`'s return literal:

```python
    return {
        "header_row": data["header_row"],
        "header_col": data["header_col"],
        "case_sensitive": data["case_sensitive"],
        "gate": data["gate"],
        "border": data["border"],
        "prompt": data["prompt"],
        "cells": out_rows,
    }
```

**Do not bump `FORMAT_VERSION`.** It stays at 11; see the spec's Risks section for why the silent degradation is preferred over a version gate.

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest tests/test_filltable_transfer.py -v
```

- [ ] **Step 5: Falsify**

1. Delete `"gate": data["gate"],` → the export and round-trip tests go RED.
2. Restore, then **bypass the normalizer on one write path**: `_build_fill_table`'s tail is `_clean_save(FillTableElement(data=FillTableElement.normalize_data(data)))` — change it to `_clean_save(FillTableElement(data=data))`, **keeping `_clean_save`**. Dropping the save too would return an unsaved instance and redden the image-remap and round-trip cases that read the persisted object, muddying the prediction. Expected RED: `test_every_production_write_path_stores_a_real_boolean`, on its second half, where `obj.data["gate"]` is the string `"yes"` rather than `True`. Expected GREEN: everything else in `tests/test_filltable_transfer.py`. This is the mutant the spec names for that test, and it is the whole point of it: the `data__gate=True` ORM filter in Task 4 matches the JSON literal `true` only, which is exact *because* every write path normalizes.
3. Restore, then **flip the absent-key default**: `bool(data.get("gate"))` → `bool(data.get("gate", True))` in `normalize_data` → **only** `test_legacy_bundle_without_gate_imports_ungated` goes RED in this file (its payload omits the key entirely, so it now normalizes to `True`); the other three pass an explicit `gate` value and stay GREEN.

   Do **not** use "delete `"gate": gate,` from the return" as this task's mutant. By now `_ser_fill_table` reads `data["gate"]` directly (Step 3) and `render` reads `nd["gate"]` (Task 3), so deleting the key raises `KeyError` inside the serializer and reddens essentially the whole file — a prediction of one RED would read as a broken mutant rather than an over-broad one. (Expect this mutant to redden `test_normalize_data_gate_defaults_false` in `tests/test_filltable_model.py` too, but that file is not in this step's command.)

Without mutants 2 and 3, those two tests are green-on-write and never shown able to fail — the exact thing the "Falsify every test before trusting it" constraint forbids.

**No coercion mutant here.** `test_every_production_write_path_stores_a_real_boolean` asserts `is True` on a truthy `"yes"` payload, and `and` returns its last operand — so `"yes" and bool(answers) and not any(...)` evaluates to a real `True` with or without the `bool()` wrapper, and this test cannot distinguish them. The coercion is falsified where it lives, by Task 1's `test_normalize_data_gate_coerces_falsy_non_false` (mutant 4 there) — the `""` payload is the only one that discriminates. Do not add a coercion mutant to this task expecting it to redden anything.

- [ ] **Step 6: Restore, re-run, then commit**

Mutant 3 left `normalize_data`'s absent-key default flipped — edit it back, then re-run before staging:

```bash
uv run pytest tests/test_filltable_transfer.py tests/test_filltable_model.py -v
```

Expected: all PASS (`test_filltable_model.py` is included because mutant 3 reddens `test_normalize_data_gate_defaults_false` there, outside this task's usual command).

```bash
uv run ruff check --no-cache courses/transfer/export.py tests/test_filltable_transfer.py
uv run ruff format --check courses/transfer/export.py tests/test_filltable_transfer.py
git add courses/transfer/export.py tests/test_filltable_transfer.py
git commit -m "feat(filltable): carry the gate flag through transfer

Export needs one line; the importer already routes through normalize_data.
No FORMAT_VERSION bump -- an older libli ignores the unknown key and imports
a working ungated table."
```

---

### Task 8: Help documentation

**Files:**
- Modify: `docs/help/course-admin/interactive-elements.md` (the `{el:filltable}` section, ending line 77)
- Modify: `docs/help/course-admin/interactive-elements.pl.md` (the `{el:filltable}` section)

**Interfaces:** none.

The English section currently ends "Records no marks and reveals nothing." (line 77, on one line). The Polish twin ends with the same claim — but **hard-wrapped across lines 89-90**:

```
bardziej, ale zmniejszenie jej poniżej limitu jest jednokierunkowe. Nie
przyznaje punktów i niczego nie odsłania.
```

An exact-match edit keyed on the unwrapped sentence will fail there; the `old_string` must span the newline after `Nie`. The English/Polish asymmetry is easy to miss because only the Polish one wraps.

Both must change. Note that no existing gate-family section states the scope confinement, so there is no sibling wording to mirror — see the note after Step 2.

- [ ] **Step 1: Update the English page**

Replace the final sentence of the `{el:filltable}` section. **The `old_string` is, verbatim** (all on `:77`, starting at column 0 — unlike the Polish twin it does not wrap):

```markdown
is one-way. Records no marks and reveals nothing.
```

Wrapped to the file's own ~75-column hand-wrap; keep it that way, or the paragraph reads as unrelated churn in the diff and invites the next editor to rewrap the lot:

⚠️ **Do not write "everything after it … appears in one go."** `cascadeFrom` **breaks at the next gate wrapper** (`reveal.js:143`), so a correct check reveals only up to *and including* the next gate — which is exactly what Task 9 test 23 pins by asserting `_visible(trailing_row) is False` after table 1 is solved. This section exists because "Records no marks and reveals nothing" rotted into a false claim; replacing it with a *new* false claim, in a file where `tests/test_help.py` inspects no prose, would repeat the defect rather than fix it. The wording below is qualified accordingly, and the chaining sentence then reads as the illustration of that rule rather than an exception to it.

```markdown
is one-way. Records no marks. Tick
**Reveal the rest of this section when all cells are correct** to turn the
table into a reveal gate: what follows it stays hidden until a student
fills every answer cell correctly, and then appears — up to the next gate,
if the section holds another one. Like the other gates (**Show more**,
**Fill in & confirm**, **Choose & confirm**), the reveal also stops at the
edge of whatever contains the table — inside a callout it reveals the rest
of that callout and nothing beyond it. Two gated tables in a row chain: the
first reveals the second, the second reveals what follows.
```

- [ ] **Step 2: Update the Polish page**

Replace the final sentence of the `{el:filltable}` section:

Likewise wrapped to the Polish file's own width — the switch-gate line in particular grew when the name was corrected to *zatwierdź*:

**Mind the splice point.** Unlike the English anchor (`is one-way.`, at column 0 of `:77`), the Polish anchor `jednokierunkowe. Nie` sits at **column 51** of `:89` — `bardziej, ale zmniejszenie jej poniżej limitu jest jednokierunkowe. Nie`. So the first replacement line must be *short*, or the spliced result is a ~125-column line, which is precisely the churn this is trying to avoid. Break immediately after `Nie`:

**Carry the same qualification across** — the twins must agree, and the Polish draft had the identical "pojawia się naraz" overclaim:

```markdown
jednokierunkowe. Nie
przyznaje punktów. Zaznacz **Odsłoń resztę tej sekcji, gdy wszystkie
komórki są poprawne**, aby zamienić tabelę w bramkę odsłaniającą: to, co
znajduje się po niej, pozostaje ukryte, dopóki uczeń nie wypełni poprawnie
każdej komórki z odpowiedzią, a potem się pojawia — aż do następnej bramki,
jeśli sekcja zawiera kolejną. Podobnie jak w pozostałych bramkach
(**Pokaż więcej**, **Uzupełnij i potwierdź**, **Wybierz i zatwierdź**)
odsłanianie zatrzymuje się także na granicy elementu zawierającego tabelę —
wewnątrz ramki odsłoni resztę tej ramki i nic poza nią. Dwie kolejne
bramkowane tabele tworzą łańcuch: pierwsza odsłania drugą, druga odsłania
to, co następuje po niej.
```

The bolded label is still split across the same `wszystkie` / `komórki są poprawne**` line break — Task 10 Step 2's msgid note depends on that, so keep the break where it is if you rewrap anything else.

**Verify the three bolded gate names against the `^## ` headings of each file before pasting.** They are not symmetric across the two languages, and prose mismatches are invisible to `tests/test_help.py`. In Polish the switch-gate is **Wybierz i zatwierdź** (`interactive-elements.pl.md:36`) — *zatwierdź*, not *potwierdź*, even though the fill-gate two lines earlier is **Uzupełnij i potwierdź** (`:27`). English: **Show more** (`:16`), **Fill in & confirm** (`:24`), **Choose & confirm** (`:32`).

**Why the snippets above use plain bolded names rather than links:** that page contains no intra-page links at all (grep for `](interactive-elements` returns zero hits), so a cross-link would both invent a convention and link the page to itself. The bolded form matches the existing prose style.

Note also that none of the three gate sections states the scope confinement: `{el:revealgate}` (:16-22) says only "hides the elements that follow it in the outline", and the other two are similar. So there is no sibling wording to mirror — state the confinement in one sentence of the fill-table section, and accept that it is the first section on the page to say it.

- [ ] **Step 3: Verify the help pages still render**

```bash
uv run pytest tests/test_help.py -v
```

Expected: PASS. There is **no** separate link checker — the command above is the whole gate. What it runs over `interactive-elements.md` / `.pl.md` is four parametrized guards: `test_topic_english_file_exists_and_renders`, `test_topic_polish_file_renders_if_present`, `test_polish_file_is_not_an_english_copy`, and `test_element_icon_slugs_match_sprite`, plus `test_element_topics_leak_no_literal_token` and `test_pl_icon_sequence_matches_en`. None of them inspects prose, which is exactly why the bolded gate names have to be checked by eye in Steps 1-2.

- [ ] **Step 4: Commit**

```bash
git add docs/help/course-admin/interactive-elements.md docs/help/course-admin/interactive-elements.pl.md
git commit -m "docs(filltable): document the reveal-gate checkbox

'Records no marks and reveals nothing' is no longer true. Both language
twins updated, with the scope confinement described as the other three gate
families describe theirs."
```

---

### Task 9: End-to-end behaviour

**Files:**
- Create: `tests/test_e2e_filltable_gate.py`

**Interfaces:** consumes everything above.

**Read `tests/test_e2e_filltable.py` and `tests/test_e2e_reveal_gate.py` first.** Reuse `_login`, `_new_unit`, `_unit_url`, `_text`, `_gate` and `_seed_state` from the reveal-gate file, and the `_INCORRECT` / `_SUCCESS` regexes plus the `_confirm` / `_summary` locators from the fill-table file. **The preamble's import block below is authoritative** — it lists exactly the ten symbols the tests use. Do not also import `_seed_student` (`_new_unit` creates the student), `_CORRECT` or `_RETRY` (no test asserts a per-cell correct class or a retry summary); ruff selects `F`, so an unused import fails the branch gate. Neither file has a gated-fill-table factory, so write one (below).

**Write the module preamble out first — without it the run command selects nothing.** `pyproject.toml:49` sets `addopts = "-q -m 'not e2e'"`, so an e2e file is selected *only* by an explicit marker; and every test in both reference files carries `@pytest.mark.django_db(transaction=True)` (Playwright runs in another thread and cannot see rows held in an uncommitted test transaction). The `_allow_async_unsafe` fixture is defined locally in each e2e file and does **not** transfer through an import.

```python
"""Fill-in table reveal gate, end to end.

Fixtures are TOP-LEVEL (slide-scope) throughout -- see the trap list below.
"""

import os

import pytest
from playwright.sync_api import expect

from courses.models import FillTableElement
from tests.factories import add_element

# `tests/` has an __init__.py, so these are importable rather than copy-pasted.
# (`_allow_async_unsafe` is NOT -- it is a local autouse fixture in each file.)
from tests.test_e2e_filltable import _INCORRECT
from tests.test_e2e_filltable import _SUCCESS
from tests.test_e2e_filltable import _confirm
from tests.test_e2e_filltable import _summary
from tests.test_e2e_reveal_gate import _gate
from tests.test_e2e_reveal_gate import _login
from tests.test_e2e_reveal_gate import _new_unit
from tests.test_e2e_reveal_gate import _seed_state
from tests.test_e2e_reveal_gate import _text
from tests.test_e2e_reveal_gate import _unit_url

pytestmark = pytest.mark.e2e

# NOTE: `_confirm` and `_summary` are scoped to the FIRST .filltable on the page
# (both are `_table(page).locator(...)`, and `_table` is
# `page.locator(".filltable").first`). Use them ONLY in single-table fixtures --
# tests 21, 22, 24 and 25. Tests 23 and 26 have TWO tables, so the shared
# locators would silently drive the wrong one; that is what _block(...)-scoped
# locators are for. Test 27 has only ONE table and could use them, but stays
# _block-scoped for symmetry with 23 and 26 -- not out of necessity.


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Copied from
    # tests/test_e2e_filltable.py:40-45 -- a local fixture, not importable.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield
```

**Test names are fixed, not invented.** Steps 1-7 below show only each test's fixture lines and body — the `def` line is omitted for brevity, but the name is not free: Step 8's mutant table refers to tests by number, and Step 9 selects one by name, so an invented name breaks both. Use exactly these, each preceded by `@pytest.mark.django_db(transaction=True)` and taking `(page, live_server)`:

| # | Function name |
|---|---|
| 21 | `test_wrong_answer_keeps_content_hidden` |
| 22 | `test_correct_answer_reveals` |
| 23 | `test_chained_gates_reveal_in_sequence` |
| 24 | `test_reload_restores_the_revealed_state` |
| 25 | `test_gate_ticked_after_solving_reveals_on_reload` |
| 26 | `test_chained_pretick_heals_only_on_reload` |
| 27 | `test_ungated_table_does_not_cascade` |

Every test carries `@pytest.mark.django_db(transaction=True)`. This is the full shape they all follow:

```python
@pytest.mark.django_db(transaction=True)
def test_wrong_answer_keeps_content_hidden(page, live_server):
    _student, unit = _new_unit("ftg_wrong")     # returns a (student, unit) PAIR
    (table_row, _t), (trailing_row, _tr) = _seed(
        unit, _filltable(gate=True), _text("trailing")
    )
    _login(page, live_server, "ftg_wrong")
    page.goto(_unit_url(live_server, unit))
    # ... step body ...
```

**`_new_unit` returns `(student, unit)`, not a unit** (`tests/test_e2e_reveal_gate.py:75-85`). Binding a single name makes `unit` a 2-tuple, and every test then dies at setup — `Element.objects.create(unit=<tuple>)` / `_unit_url` raising `AttributeError: 'tuple' object has no attribute 'unit_type'`. Use `_student, unit = …` (the leading underscore matches both reference files and keeps ruff quiet), except in **test 26**, which needs the real binding `student, unit = …` because its fixture calls `_seed_state(student, unit, …)`.

Each test needs its own unique username (`_new_unit` and `_login` must be given the same one), as the two reference files do. Each step below opens with its own fixture lines; they are not interchangeable, because `_seed` returns `(join_row, concrete_obj)` pairs and every step unpacks a different shape.

**Five traps this suite must avoid:**

- **A live solve dispatches the state POST but does not wait for it.** `libliState.saveFlag` is fire-and-forget (`state.js:20-31`, `keepalive`, errors swallowed), and `summarize()` runs *before* it in the same `.then`. So `expect(_summary(page)).to_have_class(_SUCCESS)` does **not** mean the blob was committed — reloading straight after races the server and makes tests 24, 25 and 26 intermittently red on a correct build. The repo already solved this; copy `tests/test_e2e_filltable.py:253-261`:
  ```python
  with page.expect_response(
      lambda r: "/state/" in r.url and r.request.method == "POST"
  ) as resp_info:
      _confirm(page).click()
  assert resp_info.value.ok
  page.reload()
  ```
  Use this wherever a step reloads after solving. The plain `expect(...)` synchronisation below is sufficient only for tests that never reload (21, 22, 23, 27).
- **All fixtures must be TOP-LEVEL (slide-scope), not callout children.** `data-element-id` is emitted only by `_lesson_article.html:38` for top-level elements; `calloutelement.html:23` renders children as bare `<div class="callout__child">{% render_element child %}</div>` — no `data-element-id`, no `.lesson-block`. A locator keyed on `.lesson-block[data-element-id=…]` therefore returns `null` for a callout child. Top-level scope also exercises the `.slide` pre-hide selector, and the callout-child *rendering* path is already pinned by Task 2's direct-child unit test.

  **State the loss rather than claiming there is none.** The motivating case (mat-pp unit 322) is callout-nested, and this suite never drives it end to end. Task 2's direct-child test proves only that the marker is a direct child of `.callout__child` in rendered HTML; it says nothing about `scopeOf` resolving to `.callout__children`, about `.callout__children > .callout__child:has(> [data-reveal-gate]) ~ .callout__child` actually hiding, or about the cascade stopping at the callout boundary — which is exactly what Task 8's help copy promises authors. That behaviour is **deliberately out of e2e scope here**: all three of it is scope machinery shared with the existing gate families, already driven by their own callout-scoped e2e, and none of it is touched by this branch. What *is* new — the marker's position and the `data-gate` → marker path — is unit-tested in Task 2. If the callout cascade is ever suspected, the cheapest check is a callout-scoped variant of test 22 locating the child by `.callout__children > .callout__child:nth-child(n)` and calling `checkVisibility()` on it, since `data-element-id` is unavailable there.
- **Assertions must auto-retry.** `filltable.js::submit` is `fetch(...).then(...)` — `paint`, `lock` and `libliRevealCascade` all run in the `.then`. A bare `page.evaluate` does **not** retry, so an assertion fired straight after `click()` samples the DOM before the response lands: test 21 would pass under its own mutant, and 22/23 would be red on a correct build. Synchronise on the widget's own state first, using the file's existing primitives:
  ```python
  _confirm(page).click()
  expect(_summary(page)).to_have_class(_SUCCESS)   # correct path
  # or, for a wrong answer:
  expect(inp).to_have_class(_INCORRECT)
  ```
  and only then read visibility.
- **Use `checkVisibility()`, not Playwright's own visibility notion** — Playwright reports a 1×1 clipped node as visible, so it cannot distinguish pre-hidden content.
- **Never assert `document.activeElement` is *unchanged* after a check.** `lock()` sets `btn.hidden = true` on the Check button (the node a click just focused) and `inp.disabled = true` on every input (the node focused on the Enter path); hiding or disabling the focused element resets `activeElement` to `<body>`. Focus moves on **every** successful check, cascade or not.

**Seeding factory and locator convention** — write these at the top of the new file:

```python
_ANSWER = "4"
_CELLS = [[{"kind": "static", "html": "x"}, {"kind": "answer", "answer": _ANSWER}]]


def _filltable(gate=False):
    """An unsaved gated/ungated fill-table with exactly one answer cell."""
    return FillTableElement(data={"cells": _CELLS, "gate": gate})


def _seed(unit, *objs):
    """Attach each concrete element to `unit` as a TOP-LEVEL row, in order.

    Accepts BOTH saved and unsaved concrete elements: _text() and _gate() use
    .objects.create() and arrive saved (the save() below is then a harmless
    no-op UPDATE), while _filltable() returns an unsaved instance that needs
    it. Do not "tidy" the save() away.

    Returns (join_row, concrete_obj) pairs -- test 25 needs the concrete object
    to flip its `gate` mid-test, which a join row alone cannot reach.
    """
    out = []
    for obj in objs:
        obj.save()
        out.append((add_element(unit, obj), obj))   # tests.factories.add_element
    return out


def _block(join_pk):
    return f".lesson-block[data-element-id='{join_pk}']"


def _visible(page, join_pk):
    # Explicit miss-check: a bare querySelector(...).checkVisibility() throws a
    # raw JS TypeError inside Playwright when the block is absent (wrong pk, a
    # callout-nested fixture with no data-element-id, an element that never
    # rendered) -- the least legible form of exactly the fixture mistake the
    # trap list warns about. Fail with a message that names the pk instead.
    sel = _block(join_pk)
    return page.evaluate(
        f'(() => {{ const n = document.querySelector("{sel}");'
        f' if (!n) throw new Error("no .lesson-block for pk {join_pk}");'
        f" return n.checkVisibility(); }})()"
    )
```

The seven fixtures are then: **21/22** `_seed(unit, _filltable(gate=True), _text("trailing"))`; **23** `_seed(unit, _filltable(gate=True), _filltable(gate=True), _text("trailing"))` — adjacent, nothing between the two tables; **24** as 21/22; **25** deliberately **`_seed(unit, _filltable(gate=False), _text("trailing"))`** — seeded UNGATED, then flipped mid-test. Seeding it gated would make the flip a no-op, write the blob while already gated, and silently collapse test 25 into a duplicate of test 24 — losing the "ordering, not storage" distinction that is its whole reason to exist. On the first load `has_reveal_gate` is false, so there is no prepaint and the trailing element is visible; that is expected, since the assertion only runs after the flip and reload; **26** as 23, with `_seed_state(student, unit, {str(table2_row.pk): {"done": True}})` before the first load (note `_seed_state` keys by **str** — `UnitProgress.element_state` is str-keyed); **27** `_seed(unit, _filltable(gate=False), _text("ungated-trailing"), _gate("Show more"), _text("gated-trailing"))` — the trailing `_gate` is what makes `has_reveal_gate` true so `reveal.js` loads at all (see Step 7).

Run with:
```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -v
```
`-m e2e` is mandatory — without it the whole file is silently deselected and pytest exits 5, which reads as success at a glance.

- [ ] **Step 1: Test 21 — a wrong answer keeps the content hidden**

**This test's complete text is the "full shape" block above** — test 21 is the one used to illustrate it, so its `_new_unit` / `_login` / `page.goto` lines are printed there rather than repeated here. Steps 2-7 each carry their own copies; this step is the only one that does not, and the body below continues directly from that block:

```python
# (setup as in the "full shape" block above:
#  _student, unit = _new_unit("ftg_wrong")
#  (table_row, _t), (trailing_row, _tr) = _seed(
#      unit, _filltable(gate=True), _text("trailing")
#  )
#  _login(page, live_server, "ftg_wrong")
#  page.goto(_unit_url(live_server, unit))
# )
inp = page.locator(".filltable__input").first
inp.fill("nope")
_confirm(page).click()
expect(inp).to_have_class(_INCORRECT)      # <- synchronise BEFORE reading the DOM
assert _visible(page, trailing_row.pk) is False
```

*Mutant: cascade unconditionally, ignoring `all_correct`* — concretely, **move the `if (root.hasAttribute("data-reveal-gate") && window.libliRevealCascade) { … }` call out of the `if (data.all_correct === true && …)` block**, leaving `lock` and `saveFlag` inside it. (Dropping the `all_correct` guard entirely gives the same RED set — 21 only — but move the call rather than restructuring the branch, so `lock`/`saveFlag` behaviour is not also perturbed.)

- [ ] **Step 2: Test 22 — a correct answer reveals**

```python
_student, unit = _new_unit("ftg_correct")
(table_row, _t), (trailing_row, _tr) = _seed(
    unit, _filltable(gate=True), _text("trailing")
)
_login(page, live_server, "ftg_correct")
page.goto(_unit_url(live_server, unit))

inp = page.locator(".filltable__input").first
inp.fill(_ANSWER)
_confirm(page).click()
expect(_summary(page)).to_have_class(_SUCCESS)   # <- synchronise first
expect(inp).to_be_disabled()
assert _visible(page, trailing_row.pk) is True
# The solved table must STAY on screen -- hideWrapper:false. Without it
# cascadeFrom sets gateWrap.hidden, and app.css:1010 removes the table and its
# notes entirely. Both Playwright assertions above are visibility-agnostic, so
# this line is the only behavioural guard on that option.
assert _visible(page, table_row.pk) is True
```

*Mutants: remove the `libliRevealCascade` call; and, separately, drop the `{ hideWrapper: false }` argument.*

- [ ] **Step 3: Test 23 — a chain of two gates, adjacent**

**The fixture must place the two gating tables as immediately adjacent scope children, with nothing between them.** This differs deliberately from mat-pp unit 322, whose tables are separated by a text element: `cascadeFrom` calls `focusTargetIn` only when `lastRevealed === firstNew`, so with anything in between the focus branch never fires and the last assertion here cannot pass.

```python
_student, unit = _new_unit("ftg_chain")
(table1_row, _t1), (table2_row, _t2), (trailing_row, _tr) = _seed(
    unit, _filltable(gate=True), _filltable(gate=True), _text("trailing")
)   # ADJACENT: nothing between the two tables
_login(page, live_server, "ftg_chain")
page.goto(_unit_url(live_server, unit))

# solve table 1 (its inputs are the only enabled ones while table 2 is hidden)
inp1 = page.locator(f"{_block(table1_row.pk)} .filltable__input").first
inp1.fill(_ANSWER)
page.locator(f"{_block(table1_row.pk)} .filltable__confirm").click()
expect(page.locator(f"{_block(table1_row.pk)} .filltable__summary")).to_have_class(_SUCCESS)

assert _visible(page, table2_row.pk) is True
assert _visible(page, trailing_row.pk) is False
# focus landed IN table 2's first enabled input, not on its wrapper div
assert page.evaluate(
    "document.activeElement.classList.contains('filltable__input')"
) is True

inp2 = page.locator(f"{_block(table2_row.pk)} .filltable__input").first
inp2.fill(_ANSWER)
page.locator(f"{_block(table2_row.pk)} .filltable__confirm").click()
expect(page.locator(f"{_block(table2_row.pk)} .filltable__summary")).to_have_class(_SUCCESS)
assert _visible(page, trailing_row.pk) is True
```

*Mutant: delete `cascadeFrom`'s `break` at `isGateWrapper` (`reveal.js:143`)* — table 1 would reveal everything at once. Note the `break` is in `cascadeFrom`'s reveal loop; `isGateWrapper` itself (`:77-83`) is a pure predicate and contains no `break`.

- [ ] **Step 4: Test 24 — reload restores**

```python
_student, unit = _new_unit("ftg_reload")
(table_row, _t), (trailing_row, _tr) = _seed(
    unit, _filltable(gate=True), _text("trailing")
)
_login(page, live_server, "ftg_reload")
page.goto(_unit_url(live_server, unit))

inp = page.locator(".filltable__input").first
inp.fill(_ANSWER)
with page.expect_response(               # AWAIT the state POST -- see trap 1
    lambda r: "/state/" in r.url and r.request.method == "POST"
) as resp_info:
    _confirm(page).click()
assert resp_info.value.ok

page.reload()
expect(page.locator(".filltable__input").first).to_have_js_property("readOnly", True)
assert _visible(page, trailing_row.pk) is True
```

The restored input is `readonly` (server-rendered), not `disabled` — `_filltable_cell.html` renders the `mine.done` branch with `readonly`, while the live `lock()` path uses `disabled`. Asserting the wrong one here fails on a correct build.

*Mutant: remove Task 3's `open` derivation.*

- [ ] **Step 5: Test 25 — pre-tick, single gate**

```python
_student, unit = _new_unit("ftg_pretick")
# seeded UNGATED -- see the fixture note
(table_row, table_obj), (trailing_row, _tr) = _seed(
    unit, _filltable(gate=False), _text("trailing")
)
_login(page, live_server, "ftg_pretick")
page.goto(_unit_url(live_server, unit))
inp = page.locator(".filltable__input").first
inp.fill(_ANSWER)
with page.expect_response(
    lambda r: "/state/" in r.url and r.request.method == "POST"
) as resp_info:
    _confirm(page).click()
assert resp_info.value.ok             # the blob is now stored, table still UNGATED

# Flip the flag. A JSONField cannot be .update()d key-wise, so rebuild the whole
# dict -- dropping `cells` here would empty the grid and silently invalidate the test.
FillTableElement.objects.filter(pk=table_obj.pk).update(
    data={**table_obj.data, "gate": True}
)

page.reload()
assert _visible(page, trailing_row.pk) is True
```

Solve an **ungated** table, then set `gate: true` on it, reload, and assert the following content is visible.

What distinguishes this from test 24 is **ordering, not storage** — test 24 also writes and re-reads a real blob. This is the only test where the blob is written while the table is still ungated, which is the sequence authors will actually create. Keep both.

*Mutant: same as 24 — it must fail here too, or the test is not reading storage.*

- [ ] **Step 6: Test 26 — pre-tick, chained (the documented limitation)**

Seed table 2 `{"done": true}` with table 1 unsolved, tick `gate` on both, load, solve table 1:

```python
# NOTE: `student`, not `_student` -- _seed_state needs it.
student, unit = _new_unit("ftg_prechain")
(table1_row, _t1), (table2_row, _t2), (trailing_row, _tr) = _seed(
    unit, _filltable(gate=True), _filltable(gate=True), _text("trailing")
)
# Table 2 was solved back when both were ungated: seed its blob directly.
_seed_state(student, unit, {str(table2_row.pk): {"done": True}})
_login(page, live_server, "ftg_prechain")
page.goto(_unit_url(live_server, unit))

# Solve table 1, AWAITING the state POST (trap 1) -- this test reloads, so the
# expect(summary) pattern used by test 23 is not sufficient here:
inp1 = page.locator(f"{_block(table1_row.pk)} .filltable__input").first
inp1.fill(_ANSWER)
with page.expect_response(
    lambda r: "/state/" in r.url and r.request.method == "POST"
) as resp_info:
    page.locator(f"{_block(table1_row.pk)} .filltable__confirm").click()
assert resp_info.value.ok

# restoreGates broke at table 1, so table 2's cascade never replayed; and table 2
# is server-rendered done, so it has no Check button to fire it.
assert _visible(page, table2_row.pk) is True
assert _visible(page, trailing_row.pk) is False
page.reload()
assert _visible(page, trailing_row.pk) is True
```

This pins **accepted** behaviour, documented in the spec's Error handling table. It is deliberately the test that goes red if someone later changes `cascadeFrom`'s stop condition — which is the point: that change should be deliberate, not incidental.

- [ ] **Step 7: Test 27 — an ungated table does not cascade**

**The fixture must contain a second, gating element** — a `RevealGateElement`, or a gated fill-table in a different scope — so `has_reveal_gate` is true and `reveal.js` actually loads. Without one, `window.libliRevealCascade` is `undefined`, the mutated line short-circuits on the *other* half of the condition, and this test is green against its own mutant.

Solve the **ungated** table (which has a following sibling in its own scope):

```python
_student, unit = _new_unit("ftg_ungated")
# the trailing _gate is what makes has_reveal_gate true so reveal.js LOADS.
# Unpacked in two statements: a single four-pair target list is 99 columns
# with the def-line indent, and ruff format does NOT parenthesise an
# assignment target list, so E501 would stand.
rows = _seed(
    unit,
    _filltable(gate=False),
    _text("ungated-trailing"),
    _gate("Show more"),
    _text("gated-trailing"),
)
# Only the first two rows are asserted on -- the _gate and its trailing text
# exist solely to make has_reveal_gate true. Do not bind them.
(table_row, _t), (ungated_trailing_row, _ut) = rows[0], rows[1]
_login(page, live_server, "ftg_ungated")
page.goto(_unit_url(live_server, unit))

inp = page.locator(f"{_block(table_row.pk)} .filltable__input").first
inp.fill(_ANSWER)
page.locator(f"{_block(table_row.pk)} .filltable__confirm").click()
expect(page.locator(f"{_block(table_row.pk)} .filltable__summary")).to_have_class(_SUCCESS)

# Bind the selector once: inlining _block(...) into the f-string pushes both
# calls to ~105 columns, and ruff format cannot split a string literal.
sel = _block(ungated_trailing_row.pk)

# THIS is the assertion that discriminates the mutant.
assert page.evaluate(
    f'document.querySelector("{sel}").classList.contains("reveal-shown")'
) is False
# activeElement is <body> here -- lock() hid the Check button. Assert the negative
# that actually distinguishes the mutant:
assert page.evaluate(
    f'!document.querySelector("{sel}").contains(document.activeElement)'
) is True
```

**No `window.scrollY` assertion — deliberately.** An earlier draft asserted the scroll position was unchanged across the check. It cannot be made reliable: `click()` runs Playwright's scroll-into-view actionability step just as `fill()` does, and the response `.then` changes document height in both directions (`lock()` sets the Check button `hidden`, `summarize()` un-hides the summary), so on a scrolled viewport `scrollY` is clamped and the equality fails on a **correct** build. It also adds nothing — the `reveal-shown` assertion above already discriminates the mutant, and the `activeElement` one covers the focus half.

*Mutant: delete the `hasAttribute("data-reveal-gate")` guard in `filltable.js`.* This is the only test defending the "an ungated fill-table behaves byte for byte" guarantee; every other test in this file uses a gated fixture.

- [ ] **Step 8: Run the suite and falsify per item**

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable_gate.py tests/test_e2e_filltable.py tests/test_e2e_reveal_gate.py -m e2e -v
```

The two existing suites run again here (Task 5 ran them first): every server-side and client-side change now exists together, and they must still pass.

**But "unmodified" applies to only one of them by this point — do not "restore" the other.** `tests/test_e2e_reveal_gate.py` must be green and genuinely unmodified. `tests/test_e2e_filltable.py` must be green with **exactly Task 6's one hunk and nothing else**: `test_editor_gate_checkbox_round_trips`, whose `FillTableElement` import is function-local inside it, committed in Task 6 Step 10. Task 5 Step 5's identical "unmodified" wording was correct *at that point*, before Task 6 ran. An implementer who carries that phrasing forward, sees a diff against master here, and reverts it in the spirit of this plan's "edit the mutant back out" rule would delete the only end-to-end guard on the authoring path — and Task 6 is already committed, so nothing downstream would flag its loss.

**There is no single group mutant for this block, and assuming one wastes a debugging session.** Reverting Task 5's `libliRevealCascade` call reddens tests 22, 23 and 26 — but **not** 21, 24, 25 or 27 — because `reveal.js::restoreGates` calls `cascadeFrom` **directly** off `data-state` (line 249) — it never goes through `filltable.js`. The `saveFlag({done: true})` line is unchanged and Task 3 derives `open`, so every reload-based path still works. Under that mutant:

| Test | Under the `libliRevealCascade` mutant | Falsified instead by |
|---|---|---|
| 21 (wrong answer stays hidden) | **GREEN** — a negative assertion; a mutant that reveals nothing passes it trivially | cascading unconditionally, ignoring `all_correct` |
| 22 (correct reveals) | **RED** | — |
| 23 (chain, adjacent) | **RED** | — |
| 24 (reload restores) | **GREEN** — restore path intact | removing Task 3's `open` derivation |
| 25 (pre-tick, single) | **GREEN** — same reason | removing Task 3's `open` derivation |
| 26 (pre-tick, chained) | **RED** — its *first* assertion (`table2_row` visible) runs BEFORE any reload, and on that first load `restoreGates` broke at the unsolved table 1, so the live cascade is the only thing that can reveal table 2 | its *post-reload* assertion is reddened instead by removing Task 3's `open` derivation |
| 27 (ungated no cascade) | **GREEN** — also a negative assertion; nothing cascading is what it wants | deleting the `hasAttribute("data-reveal-gate")` guard (Step 7) |

**These seven mutants touch three source files between them** — four edit `filltable.js` (the `all_correct` move, the cascade removal, the `hasAttribute` guard, `hideWrapper`), one edits `courses/models.py` (the `open` derivation), and **two** edit `reveal.js`, which a Global Constraint otherwise forbids: the `isGateWrapper` `break` **and** the `focusTargetIn` `[data-filltablegate]` branch. Both are covered by the constraint's sanctioned-exception clause and by the single `git diff --quiet` proof below. Edit each mutant back out (never `git checkout`), and before moving to Step 9 prove **all three** are clean and the suite is green:

```bash
git diff --quiet courses/static/courses/js/reveal.js \
                 courses/static/courses/js/filltable.js \
                 courses/models.py && echo "all three clean"
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -v
```

Expected: the echo fires and all seven tests PASS. **Step 9's screenshots must not be taken from a mutated build** — test 22 still passes under both the `isGateWrapper`-break and the `open`-derivation mutants, so the PR's review artifact could otherwise be captured from a broken tree with nothing to signal it, and Step 10 stages only the test file so it would not surface until the branch gate.

So: apply each mutant below one at a time and confirm the **exact** RED set. Do not expect one test per mutant — the `open`-derivation mutant reddens three, and an implementer who was told to expect one will burn a session debugging the other two:

| Mutant | Expected RED | Expected GREEN |
|---|---|---|
| Cascade unconditionally, ignoring `all_correct` | 21 | 22, 23, 24, 25, 26, 27 |
| Remove Task 5's `libliRevealCascade` call | 22, 23, 26 (on its *pre-reload* assertion) | 21, 24, 25, 27 |
| Remove Task 3's `open` derivation | 24, 25, 26 (on its *post-reload* assertion) | 21, 22, 23, 27 |
| Delete the `hasAttribute("data-reveal-gate")` guard | 27 | 21, 22, 23, 24, 25, 26 |
| Delete the `[data-filltablegate]` branch in `focusTargetIn` | 23, on its **focus assertion only** | 21, 22, 24, 25, 26, 27 |
| Drop `{ hideWrapper: false }` from the cascade call | 22, on its **`_visible(table_row)` assertion only** | 21, 23, 24, 25, 26, 27 |
| Delete `cascadeFrom`'s `break` at `isGateWrapper` | 23 and 26, both on their **`_visible(trailing_row) is False`** assertion | 21, 22, 24, 25, 27 |

That last row is the mutant Step 3 names, and it is the **only** one that reddens those two assertions: under every other mutant above they either pass or are never reached (both tests die on an earlier assertion under the cascade-removal mutant). With the `break` gone, solving table 1 walks straight past table 2 to the trailing block and reveals everything at once.

The `hideWrapper` row is narrow for a reason worth knowing: 24, 25 and 26's post-reload assertions all go through `restoreGates`, which computes `hideWrapper: gate.matches(RESTORABLE)` for itself (`reveal.js:249`) and never consults the call site — so the restore path is structurally immune to this mutant, and only a *live-solve* visibility assertion can catch it.

The `focusTargetIn`-branch row exists because Task 5's mutants for the focus branch run while only the *source-string* test exists — without it, test 23's `activeElement` assertion would be the one behavioural claim in the plan defending `focusTargetIn`, trusted without ever being shown able to fail. Under the mutant `focusTargetIn` returns the `.filltable` div, `focus()` on a div with no `tabindex` is a no-op, `activeElement` stays `<body>`, and the assertion is `False`. **Test 23's two visibility assertions stay GREEN under it** — check which assertion failed, not merely that the test did.

Do **not** treat a green test under the `libliRevealCascade` mutant as a broken test — for 21, 24, 25 and 27 that is the correct outcome. Test 26 is the one test appearing in two rows: it straddles both mutants, asserting once before the reload (live cascade) and once after (restore), so it goes red under either — but on a *different* assertion each time. Check which assertion failed, not merely that it failed.

- [ ] **Step 9: Screenshots — a throwaway review artifact, NOT committed**

The three `tests/capture_*.py` scripts are help-doc, publish-flow and title-math harnesses; **none drives a lesson page**, so do not try to extend one. Write a scratch capture instead, reusing this file's own fixtures:

```bash
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -k test_correct_answer_reveals -v
```

(The exact name from the table above — a substring selector like `-k correct` would also sweep in tests 21 and 27.)

with `page.screenshot(path=...)` temporarily added around test 22's reveal — before the click (gated) and after `expect(_summary(page)).to_have_class(_SUCCESS)` (revealed) — writing to a scratch directory outside the repo. Then repeat with the student's `user.theme` set to dark (**the cookie alone is not enough**; set the field on the user row before `_login`). Test 22 binds `_student, unit = _new_unit("ftg_correct")`, so the capture harness has no handle on that row — rebind it to `student` (or re-fetch the user by username) before setting `theme`. This is the same `_student` → `student` rebinding test 26 needs for `_seed_state`.

**Not committed, and not in Step 10's `git add`** — these are four images for the PR description and for your own judgement, not repo artifacts.

- [ ] **REVERT THE CAPTURE EDITS BEFORE STEP 10.** This step mutates the very file Step 10 stages: it adds `page.screenshot(path=…)` calls with a machine-specific absolute path, rebinds `_student` → `student`, and writes `user.theme`. None of that may ship — a committed absolute path breaks on every other machine, and the theme write permanently darkens `ftg_correct`. Neither `ruff check` nor the whole-suite gate would catch it, because the test still passes locally. Edit all three back out (never `git checkout` — that would discard the test file itself), then confirm:

**Do not use `git diff` for this check.** This file is created in Task 9 and is not `git add`ed until Step 10, so it is **untracked** at this point — and `git diff` on an untracked path prints nothing and exits 0 whether or not the capture edits are still there. That is an assertion that cannot fail, exactly what Task 2 Step 7 rejected a lookbehind regex for. Grep the file instead:

```bash
grep -n 'screenshot\|theme' tests/test_e2e_filltable_gate.py
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -v
```

Expected: the grep finds **nothing**, and all seven tests PASS. Neither `screenshot` nor `theme` occurs legitimately anywhere in this file, so either hit is a real leftover.

**Do not add a third alternative for the `_student` → `student` rebinding.** The obvious pattern `student, unit = _new_unit("ftg_correct")` is a *substring* of the correctly-reverted `_student, unit = …`, so grep matches it on a clean file and the check false-alarms every time — the same cannot-fail/always-fires trap in mirror image. A surviving rebinding on its own is inert anyway (it only renames a local); the two patterns above catch the leftovers that actually cause harm.

The same "remove the mutant by editing it back" rule every falsify step in this plan uses applies here.

**Pass criterion, checked per image rather than assumed.** Note what is *not* worth checking: "in the gated shot no part of the trailing element is legible" is trivially true in every build — the pre-hide CSS sets `display: none`, so the run is not merely illegible but absent — and test 21 already asserts it mechanically. Judging it by eye would be another cannot-fail criterion.

What the screenshots are actually for: **in the revealed shot, the trailing text and the locked green answer cells both remain readable against their background.** Secondarily, in the gated shot, check that the hidden run leaves no residual artefact — a stray gap, rule, or margin collapse where the content will appear — since `display: none` should reserve nothing. **Judge the dark pair on its own terms** — a light-mode pass carries no information about dark, and the green "correct" cell colour is the specific thing that has gone grey-on-grey in this repo before. If dark fails, that is a finding to raise, not a reason to alter the feature's CSS inside this task.

- [ ] **Step 10: Commit**

**Prove the mutants are out and the suite is green FIRST** — this is the re-run the Global
Constraint requires of every commit step that follows a falsify step, and Task 9 is named in
it. Step 8's copy of this proof is a forward pointer; **this** is the occurrence that gates
the commit, because Step 9 is skippable (an implementer who wants no screenshots has no
reason to enter it) and walking from the last mutant straight into `git add` would stage a
green-looking commit over a mutated `filltable.js`, `reveal.js` or `courses/models.py`. Step
10 stages only the test file, so nothing else would surface it until the branch gate:

```bash
docker compose -f docker-compose.test.yml up -d
git diff --quiet courses/static/courses/js/reveal.js \
                 courses/static/courses/js/filltable.js \
                 courses/models.py && echo "all three clean"
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -v
```

Expected: the echo fires and all seven tests PASS. Then:

```bash
# Step 9's capture edits must be GONE. grep, NOT git diff -- this file is still
# untracked until the `git add` below, and git diff is silent on untracked paths.
grep -n 'screenshot\|theme' tests/test_e2e_filltable_gate.py    # expect no hits
uv run ruff check --no-cache tests/test_e2e_filltable_gate.py
uv run ruff format --check tests/test_e2e_filltable_gate.py
git add tests/test_e2e_filltable_gate.py
git commit -m "test(filltable): e2e coverage for the reveal gate

Includes the chained pre-tick case (accepted, reload-healed) and the
ungated-no-cascade guard, whose fixture needs a second gating element or it
cannot fail."
```

**The lint gate is not boilerplate on this task.** The preamble's import block is sized for all seven tests, but `_gate` is used only by test 27 and `_seed_state` only by test 26. Stopping after test 25 — a plausible checkpoint — leaves two unused imports, and ruff selects `F`. Without these two commands that lands as a green commit whose failure only surfaces at the whole-repo lint gate several commits later.

---

### Task 10: Translation catalog

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`
- Modify: `locale/pl/LC_MESSAGES/django.mo` (binary, regenerated)
- Modify: `locale/en/LC_MESSAGES/django.po`
- Modify: `locale/en/LC_MESSAGES/django.mo` (binary, regenerated)

**Interfaces:** consumes the msgid introduced in Task 6.

**Both catalogs, not just Polish.** `locale/en/LC_MESSAGES/django.po` carries every msgid this repo emits — it already holds `Case-sensitive` from the very partial Task 6 edits — and the repo's history maintains the two in lockstep (`c0b8d555`, `2b4310c0`). A `-l pl`-only run ships a branch whose English catalog is missing the new msgid, and **nothing catches it**: `tests/test_i18n_po_health.py::test_pl_has_no_untranslated_msgid` is pl-only, and the `en` entries are deliberately blank so an empty `msgstr` there is not a defect. The omission surfaces later as unexplained churn in whoever next runs `makemessages -l en`.

**This task is last on purpose.** The `.mo` is a binary artifact; regenerating it early in a branch invites a merge conflict that has bitten this repo before.

- [ ] **Step 1: Extract messages — both locales**

```bash
uv run python manage.py makemessages -l pl
uv run python manage.py makemessages -l en
```

- [ ] **Step 2: Inspect the new entry for a fuzzy pre-fill**

Find `Reveal the rest of this section when all cells are correct` in `locale/pl/LC_MESSAGES/django.po`. This page already contains close neighbours ("Case-sensitive", and the three gate families' copy), which is the classic case for `makemessages` to pre-fill a **wrong** translation and mark it `#, fuzzy`.

If a `#, fuzzy` marker is present, clearing it takes **two** deletions — the marker line *and* the bogus `msgstr`:

```po
#: templates/courses/manage/editor/_edit_filltable.html:39
msgid "Reveal the rest of this section when all cells are correct"
msgstr "Odsłoń resztę tej sekcji, gdy wszystkie komórki są poprawne"
```

**The `msgstr` and Task 8 Step 2's bolded label must be the same string once the markdown line break is collapsed to a single space.** The help snippet wraps the label across a newline (`…tej sekcji, gdy wszystkie` / `komórki są poprawne**`) while the `.po` holds it on one line, so a literal byte comparison of the two sources always fails — compare the rendered label, not the raw text. The canonical form is the single-line one below. They currently agree only by transcription. If you revise the Polish wording *here*, go back and change Task 8 Step 2's snippet (and the already-edited `.pl.md` if Task 8 has run) to match; `tests/test_help.py` inspects no prose, so nothing catches the drift. This mirrors the ⚠️ warning in Task 6 Step 8, which covers the English side.

**Then check the churn before staging.** `makemessages` rewrites every `#:` source-reference comment in the catalog, so a one-msgid change lands as a diff spanning the whole file and a real regression hides easily in it:

```bash
git diff --stat locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po
git diff -U0 locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po | grep -E "^[+-](msgid|msgstr|#, )"
```

The second command must show **only** the new entry's `msgid`/`msgstr` (twice — once per catalog; the `en` `msgstr` is legitimately empty). Any other `msgstr` change, or any `#, fuzzy` appearing on an entry this branch did not touch, is unrelated churn to revert — not something to commit alongside the feature. Both catalogs rewrite their `#:` source-reference comments wholesale, so the `--stat` line count will be large in each; that part is expected.

- [ ] **Step 3: Compile — both locales**

```bash
uv run python manage.py compilemessages -l pl
uv run python manage.py compilemessages -l en
```

- [ ] **Step 4: Verify no fuzzy markers remain on this entry**

```bash
grep -B 6 'msgid "Reveal the rest of this section' locale/pl/LC_MESSAGES/django.po
# And the en catalog -- expect exactly 1. THIS is the command that fails on the
# failure mode this task's preamble exists to prevent: a pl-only makemessages
# run. Every other check in Task 10 reads only the Polish catalog, so if the
# `-l en` run is skipped, mistyped or silently no-ops, Steps 4 and 5 both still
# pass and the gap surfaces later as unexplained churn.
grep -c 'msgid "Reveal the rest of this section' locale/en/LC_MESSAGES/django.po
```

Keyed on the **msgid**, not the translation, and with a 6-line window: with `-B 3` on the `msgstr` the `#, fuzzy` line sits exactly at the edge of the window, so one extra `#:` reference line — or a msgid that gettext wraps once the label passes ~70 columns, which is precisely what Task 6 Step 8 contemplates — pushes the flag out of view and the check reports clean.

Expected: the `pl` entry **is found** *and* has no `#, fuzzy` line above it, **and the `en` count is `1`, not `0`**. Check all three halves — on empty output (which is what you get if the label was reworded in Task 6 Step 8 and this pattern was not updated with it) the "no fuzzy line" reading is trivially satisfied and tells you nothing. If the grep prints nothing, the msgid does not match: fix the pattern, not the catalog.

- [ ] **Step 5: Run the catalog health tests**

```bash
uv run pytest tests/test_i18n_po_health.py -v
```

Expected: all PASS. This file owns exactly these artifacts — `test_no_fuzzy_entries` and `test_no_obsolete_entries` cover **both** catalogs, and `test_pl_has_no_untranslated_msgid` covers `pl`. It is the only task-level check that a stray fuzzy or obsolete marker introduced *elsewhere* in either catalog by the two `makemessages` runs has not slipped in; without it that surfaces only at the whole-suite branch gate.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo \
        locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo
git commit -m "i18n(filltable): catalog entry for the reveal-gate checkbox

Both locales: the en catalog carries every msgid and is maintained in
lockstep, and no test would have caught a pl-only regeneration."
```

---

## Final branch gate

After Task 10, before opening the PR:

- [ ] **Whole-suite run** (a branch gate, never a per-task step):

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
```

Do not use doubled `-q` — it suppresses the summary line.

- [ ] **Lint gate:**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **Confirm the constraints held:** no new migration in `courses/migrations/`, `FORMAT_VERSION` still 11, `courses/state.py` unchanged, and `reveal.js`'s diff limited to the `focusTargetIn` branch.

```bash
git diff --stat origin/master...HEAD
# No new migration -- this constraint was the only one of the four with no
# command of its own, left to the eye over the whole-branch --stat above.
git diff --name-only origin/master...HEAD -- courses/migrations/
git diff origin/master...HEAD -- courses/state.py courses/transfer/schema.py
git diff origin/master...HEAD -- courses/static/courses/js/reveal.js
```

Expected: the migration command prints **nothing**; the `state.py`/`schema.py` command prints nothing (which is also what keeps `FORMAT_VERSION` at 11); the last shows only the `[data-filltablegate]` branch.
