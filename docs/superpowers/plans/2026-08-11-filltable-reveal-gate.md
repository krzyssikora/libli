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
- **`reveal.js` gets exactly one change** — the `focusTargetIn` branch in Task 5. Do not touch `scopeOf`, `isGateWrapper`, `cascadeFrom`, or `restoreGates`.
- **An ungated fill-table must behave byte for byte as it does today.** Every change is conditional on `gate`.
- **Falsify every test before trusting it.** Introduce the named mutant, confirm RED, then remove the mutant *by editing it out* — never `git checkout`, which would discard the new test along with it.
- **Run tests narrowly.** Start the test-DB container first (`docker compose -f docker-compose.test.yml up -d`); a down container makes the suite look hung for ~4 minutes. Never background a pytest run.
- **Tooling is via `uv run`** — `pytest`, `ruff`, and `python` are not on PATH.
- **Lint before each commit:** `uv run ruff check --no-cache <changed files>` and `uv run ruff format --check <changed files>` (a separate CI gate). `--no-cache` matters: a `# noqa` warning is cached away and the second run falsely reports clean.
- **English source strings only** in Tasks 1–9; the Polish catalog and the binary `.mo` are Task 10, deliberately last.

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

Expected: 6 FAILED with `KeyError: 'gate'`.

- [ ] **Step 3: Implement the normalizer change**

In `courses/models.py`, inside `FillTableElement.normalize_data`, immediately after the `border`/`prompt` lines and before the `return`:

```python
        border = data.get("border")
        prompt = data.get("prompt")
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

The local import mirrors `canonical_cells`, which already does `from courses.filltable import split_alternatives` inside the method body.

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

Three separate mutants; the guard has three independent failure modes and a single combined check would let two of them hide:

1. Delete `"gate": gate,` from the returned dict → **all six** go RED with `KeyError` (every one of them reads `nd["gate"]`). This mutant proves the key exists; mutants 2 and 3 are the ones that discriminate between the two conjuncts.
2. Restore it, then change `gate = (...)` to `gate = bool(data.get("gate"))` → `test_normalize_data_gate_forced_off_without_answer_cells` **and** both blank-answer tests go RED.
3. Restore, then drop only the `not any(is_blank_answer(...))` conjunct → the two blank-answer tests go RED, the no-answer-cell test stays GREEN.

Remove each mutant by editing it back, never by `git checkout` — that would delete the new tests too.

- [ ] **Step 7: Lint and commit**

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
- Test: `tests/test_filltable_render.py`, and a new `courses/tests/test_filltable_gate_print.py`

**Interfaces:**
- Consumes: `data.gate` from Task 1.
- Produces: a gated table renders `data-reveal-gate data-filltablegate` on the **same node** that carries `data-state`. Tasks 5 and 9 depend on both attributes being on `.filltable` itself.

**Two things here look separable but are not.** The print rule only becomes wrong once the marker exists, so they ship together.

**The co-location invariant.** `reveal.js::storedOpen(btn)` reads `btn.dataset.state` off the node it found via `[data-reveal-gate]`. The template has a second plausible host — the inner `.el.el--filltable` div. Putting the marker there makes `storedOpen` read `undefined` → `false` → prefix-closure `break` → the revealed content is hidden **forever** for a student who already solved the table. The test asserts same-node, not mere presence, because a presence-only assertion stays green under exactly that mutation.

- [ ] **Step 1: Add the imports and the shared grid constant**

`tests/test_filltable_render.py` currently imports only `pytest`, `FillTableElement`, `make_course`, `make_image_asset`. Add:

```python
from bs4 import BeautifulSoup
from courses.models import CalloutElement
from courses.models import Element
from tests.factories import make_course_with_unit
```

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
    # The pre-hide CSS is `.callout__children > .callout__child:has(> [data-reveal-gate])`.
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


def _print_block(css):
    m = re.search(r"@media print\s*\{(.*?)\n\}", css, re.S)
    assert m, "no @media print block in app.css"
    return m.group(1)


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

Expected: FAIL — the block still holds the bare selector.

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

`courses/static/courses/css/courses.css:1995` cites this rule as house precedent: "…`[data-reveal-gate]` and `.unit-strip__edit` are both hidden in print". After the carve-out that is no longer universally true. Append to that comment:

```
(a fill-table gate is carved out — see the :not([data-filltablegate]) rule in app.css)
```

No CSS behaviour changes here; this is prose upkeep. Task 6 makes the same argument about `test_editor_twin_drift.py`'s reason string — a prose guard that quietly rots is worse than none, because it is still read as authoritative.

- [ ] **Step 11: Verify the scope-agreement guard is undisturbed**

```bash
uv run pytest courses/tests/test_filltable_gate_print.py courses/tests/test_reveal_scope_agreement.py -v
```

Expected: all PASS. `test_reveal_scope_agreement.py` must stay green **unmodified** — it asserts the five *scope* selectors appear in the print block, a different rule, and its `@media print\s*\{(.*?)\n\}` regex still captures the narrowed one because the terminating `}` is at column 0.

- [ ] **Step 12: Falsify both**

1. Restore the bare `[data-reveal-gate]` selector → the print test goes RED, `test_reveal_scope_agreement.py` stays GREEN (proving it was never guarding this).
2. Move `data-reveal-gate data-filltablegate` from the root `.filltable` div onto the inner `.el.el--filltable` div → `test_gate_marker_is_on_the_same_node_as_data_state` goes RED while `test_gated_table_marks_the_root_div` stays GREEN. That contrast is the whole point of the co-location test.
3. Drop the `{% if data.gate %}…{% endif %}` guard so the marker is emitted unconditionally → `test_ungated_table_has_no_gate_attributes` RED. It is green from the moment it is written, so without this it is never shown to be able to fail — and it is the only render-level guard on the "byte for byte" constraint.
4. Wrap the root `.filltable` div in an extra `<div>` in `filltableelement.html` → the direct-child pin RED while the co-location test stays GREEN. Two tests, two distinct failure modes: co-location survives an extra ancestor, the pre-hide CSS does not.

- [ ] **Step 13: Lint and commit**

```bash
uv run ruff check --no-cache tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py
uv run ruff format --check tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py
git add templates/courses/elements/filltableelement.html core/static/core/css/app.css tests/test_filltable_render.py courses/tests/test_filltable_gate_print.py
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
- **Hoist `normalize_data`.** The existing body calls it once per branch; adding a third call is wasteful and easy to get out of sync.

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
    Enrollment.objects.create(student=student, course=course)   # the POST needs an enrolled, logged-in user
    row, _obj = _seed_filltable(unit, student, _CELLS, None, gate=True)
    resp = client.post(
        reverse("courses:element_state_save", args=[unit.course.slug, unit.pk]),
        data=json.dumps({"element": row.pk, "state": {"done": True, "open": True}}),
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.content   # else UnitProgress.DoesNotExist masks the real cause
    stored = UnitProgress.objects.get(student=student, unit=unit).element_state
    assert stored[str(row.pk)] == {"done": True}, "`open` must not survive _val_done"
```

*Mutant for this one: add `open` to `_val_done`'s return in `courses/state.py`* — the test must go RED, proving it reads storage rather than the response. Restore `courses/state.py` immediately afterwards; it is a Global Constraint that the file ships unchanged.

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_restore.py -k "renders_open or does_not_render_open or mutate or stores_done_only" -v
```

Expected, all four named explicitly (a bare `-k gate` would also sweep in `test_saved_gated_state_stores_done_only` without accounting for it):
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
        nd = self.normalize_data(self.data)  # hoisted: both branches use it
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
uv run pytest tests/test_filltable_restore.py -v
```

Expected: all PASS, including the file's pre-existing tests.

- [ ] **Step 6: Falsify all three**

1. Remove the whole `if nd["gate"]:` block → `test_gated_done_renders_open_in_data_state` RED. **This is the highest-value mutant in the plan**: without this test, deleting the derivation is invisible to the entire suite and breaks restore for every gated table.
2. Restore, then change the condition to always-true (drop `if nd["gate"]:`) → `test_ungated_done_does_not_render_open` RED.
3. Restore, then change the copy to an in-place mutation:
   ```python
   ctx["mine"]["open"] = True
   ```
   → `test_render_does_not_mutate_the_callers_state_blob` RED.

- [ ] **Step 7: Commit**

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
- Modify: `templates/courses/lesson_unit.html:11`
- Test: extend `tests/test_filltable_context.py`; new `tests/test_filltable_gate_prepaint.py`; new `courses/tests/test_filltable_gate_query_shape.py`

**Interfaces:**
- Consumes: `data__gate` (Task 1).
- Produces: context keys `has_filltable_gate` (bool) and an updated `has_reveal_gate`. Task 9's e2e depends on both, because `reveal.js` loads only under `has_reveal_gate`.

**This is not cosmetic.** `reveal.js` is loaded only under `{% if has_reveal_gate %}` (`lesson_unit.html:89`). On a unit whose only gate is a fill-table, omitting this term means **the cascade engine never loads at all** and the gate silently does nothing.

**Use the CT-free query shape.** The obvious `FillTableElement.objects.filter(elements__unit=node, ...)` makes `GenericRelation.get_extra_restriction` call `ContentType.objects.get_for_model`, a DB SELECT on a cold cache. `views.py` rejects that pattern in two existing comments (:411-412 and :457-459), the second naming `tests/test_html_element.py`'s query-count assertion as the thing it breaks.

- [ ] **Step 1: Write the failing view-flag tests**

**Extend `tests/test_filltable_context.py`** — do not create a new file. It already carries exactly the fixtures these tests need: `unit_with_element(el)` (attaches an unsaved concrete element to a fresh unit) and `ctx_for(unit)` (mints a uniquely-named verified user and calls `build_lesson_context`). It also already holds `test_has_fill_table_flag`, `test_has_fill_table_flag_when_nested_in_tab` and `test_has_fill_table_flag_false_without_element`, so the new cases sit directly beside their `has_fill_table` counterparts.

```python
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]   # non-blank: Task 1's guard keeps `gate` on


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
    has_fill_table = node.elements.filter(
        content_type__model="filltableelement"
    ).exists()
    # CT-free by construction (see the has_html / has_stateful_elements comments
    # below): a reverse-GenericRelation filter would resolve FillTableElement's
    # ContentType and emit a cold-cache CT SELECT, breaking test_html_element's
    # query-count invariant. Short-circuited on has_fill_table so a unit with no
    # fill-table costs zero extra queries. NOT scoped to parent__isnull=True: a
    # gate nested in a tab or callout keeps its own `unit` FK.
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

**(b)** `FillTableElement` is **already imported** at `views.py:52`. Do not add a second import — `ruff` will flag it.

**(c)** Add to the return dict (:502-529), next to `has_fill_table`:

```python
        "has_filltable_gate": has_filltable_gate,
```

- [ ] **Step 5: Add the watchdog term to the template**

`templates/courses/lesson_unit.html:11`:

```
      if (!window.__revealBooted{% if has_fill_gate %} || !window.__fillGateBooted{% endif %}{% if has_switch_gate %} || !window.__switchGateBooted{% endif %}{% if has_filltable_gate %} || !window.__fillTableBooted{% endif %}) {
```

No change to the script-loading block: `filltable.js` already loads under `has_fill_table`, and `reveal.js` now loads because `has_reveal_gate` includes gating tables.

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py tests/test_html_element.py -v
```

Expected: all PASS. `tests/test_html_element.py` must stay green **unmodified**.

- [ ] **Step 7: Write the query-shape source assertion**

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
```

- [ ] **Step 8: Falsify everything in this task**

1. Drop `or has_filltable_gate` from `has_reveal_gate` → `test_has_filltable_gate_flag`, `test_has_filltable_gate_flag_when_nested_in_a_callout` **and** the prepaint A/B go RED — the whole prepaint block sits inside `{% if has_reveal_gate %}` (`lesson_unit.html:5-17`), so both `__fillTableBooted` and `reveal-armed` vanish from the gated render too.
2. Restore, then omit `"has_filltable_gate": has_filltable_gate,` from the return dict → **all four** new tests go RED: the three context tests raise `KeyError` reading `ctx["has_filltable_gate"]`, and the prepaint A/B fails on the missing term. The A/B still earns its place — it is the only one that proves the *template* term is driven by the flag rather than by the mere presence of a fill-table, which no context-dict assertion can show.
3. Restore, then scope the inner query to `parent__isnull=True` → the callout test goes RED, the top-level test stays GREEN.
4. Restore, then rewrite the query as `FillTableElement.objects.filter(elements__unit=node, data__gate=True)` → **both** source assertions go RED (the rewrite drops `pk__in` and `object_id` as well as adding `elements__unit=`), while **every runtime test stays GREEN**. That second half is the contrast that matters, and exactly why this guard has to be a source assertion.

- [ ] **Step 9: Commit**

```bash
uv run ruff check --no-cache courses/views.py tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py courses/tests/test_filltable_gate_query_shape.py
uv run ruff format --check courses/views.py tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py courses/tests/test_filltable_gate_query_shape.py
git add courses/views.py templates/courses/lesson_unit.html tests/test_filltable_context.py tests/test_filltable_gate_prepaint.py courses/tests/test_filltable_gate_query_shape.py
git commit -m "feat(filltable): detect a gating table at the page level

reveal.js loads only under has_reveal_gate, so without this term the cascade
engine never loads on a unit whose only gate is a fill-table. CT-free query
shape, guarded by a source assertion -- a runtime query-count A/B provably
cannot falsify it."
```

---

### Task 5: Call the cascade, and resolve the focus target

**Files:**
- Modify: `courses/static/courses/js/filltable.js` — top of the IIFE, and `submit`'s all-correct branch (~:57-60)
- Modify: `courses/static/courses/js/reveal.js` — `focusTargetIn` (~:106-119)
- Test: `courses/tests/test_reveal_refactor_static.py` (extend), new `courses/tests/test_filltable_gate_static.py`

**Interfaces:**
- Consumes: the marker (Task 2).
- Produces: `window.__fillTableBooted` (read by Task 4's watchdog term) and the live cascade behaviour Task 9's e2e asserts.

**The `saveFlag` line does not change.** Writing `{done: true, open: true}` here would be dead code — `_val_done` strips `open` before it is stored. Leave it exactly as it is.

- [ ] **Step 1: Write the failing static tests**

Create `courses/tests/test_filltable_gate_static.py`:

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


def test_cascade_call_is_guarded_by_the_gate_attribute():
    # Without the attribute guard an UNGATED table also cascades, moving focus
    # and scrolling on every correct answer.
    assert 'hasAttribute("data-reveal-gate")' in SRC
    assert "window.libliRevealCascade" in SRC


def test_save_flag_stays_done_only():
    # _val_done strips anything else; writing `open` here would be dead code.
    assert "saveFlag(root, { done: true })" in SRC
```

Add to `courses/tests/test_reveal_refactor_static.py`, next to its existing `test_focus_targets_fill_gate_input`:

```python
def test_focus_targets_fill_table_input():
    # Focus resolution must special-case a fill-table gate (its <div> is not
    # focusable), and must skip a DISABLED input -- lock() disables every input
    # on the live success path, and focus() on a disabled node silently drops
    # focus to <body> instead of falling through to the wrapper fallback.
    assert "data-filltablegate" in SRC
    assert ".filltable__input:not([disabled])" in SRC
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py -v
```

Expected: **three** FAIL. `test_save_flag_stays_done_only` is GREEN already — `filltable.js:59` reads `window.libliState.saveFlag(root, { done: true });` today, and this task does not change that line. It is a **pin against future drift**, not a TDD test; its mutant is "change the payload to `{ done: true, open: true }`", which belongs in Step 7.

- [ ] **Step 3: Add the boot flag**

At the top of `filltable.js`'s IIFE, immediately after `"use strict";`:

```js
(function () {
  "use strict";

  // Parse-time boot flag, mirroring fillgate.js / switchgate.js: lesson_unit.html's
  // prepaint watchdog disarms the pre-hide at DOMContentLoaded if this is still
  // falsy, so a dead filltable.js cannot trap content permanently hidden.
  window.__fillTableBooted = true;
```

- [ ] **Step 4: Add the cascade call**

In `submit`, replace the all-correct branch (~:57-60):

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

- [ ] **Step 5: Add the focus branch**

In `reveal.js::focusTargetIn`, after the `[data-fillgate]` branch and before the `[data-switchgate]` one:

```js
    if (gate.matches("[data-filltablegate]")) {
      // :not([disabled]) is load-bearing -- filltable.js::lock() disables every
      // input on the live success path, and focus() on a disabled node is a silent
      // no-op that drops focus to <body> instead of falling through to
      // cascadeFrom's `target || makeFocusable(firstNew)` fallback. The
      // server-rendered restore path uses readonly, which IS focusable.
      return gate.querySelector(".filltable__input:not([disabled])");
    }
```

This is the **only** `reveal.js` change. Leave `scopeOf`, `isGateWrapper`, `cascadeFrom` and `restoreGates` alone — in particular `cascadeFrom`'s `break` at an already-open downstream gate, whose consequence is a documented, accepted limitation (spec Error handling, pinned by e2e test 26 in Task 9).

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py -v
```

Expected: all PASS.

- [ ] **Step 7: Falsify**

1. Delete `window.__fillTableBooted = true;` → `test_boot_flag_is_assigned` RED.
2. Restore, then delete the `hasAttribute("data-reveal-gate") &&` clause → `test_cascade_call_is_guarded_by_the_gate_attribute` RED. (The behavioural counterpart is e2e test 27 in Task 9.)
3. Restore, then delete the `[data-filltablegate]` branch from `focusTargetIn` → `test_focus_targets_fill_table_input` RED.
4. Restore, then drop `:not([disabled])` from that selector → the same test RED.
5. Restore, then change `filltable.js`'s save line to `saveFlag(root, { done: true, open: true })` → `test_save_flag_stays_done_only` RED. This is the drift pin promised in Step 2; without this mutant it is the one test in the task trusted without ever being shown to fail.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --no-cache courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py
uv run ruff format --check courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py
git add courses/static/courses/js/filltable.js courses/static/courses/js/reveal.js courses/tests/test_filltable_gate_static.py courses/tests/test_reveal_refactor_static.py
git commit -m "feat(filltable): cascade on a fully-correct gated check

Adds the boot flag, the attribute-guarded libliRevealCascade call, and
reveal.js's focus branch. The saveFlag payload is deliberately unchanged --
_val_done strips anything but `done`."
```

---

### Task 6: Editor checkbox, and the rejected-save fix

**Files:**
- Modify: `templates/courses/manage/editor/_edit_filltable.html:38`
- Modify: `courses/static/courses/js/filltable_editor.js` (:174, :250, :937)
- Modify: `courses/element_forms.py` — add `FillTableElementForm.grid_data`
- Modify: `tests/test_editor_twin_drift.py:179-181` (reason string only)
- Test: `tests/test_filltable_editor_partial.py`, `tests/test_filltable_form.py`

**Interfaces:**
- Consumes: `normalize_data`'s `gate` (Task 1).
- Produces: authors can set the flag. Nothing later depends on this.

**Why `grid_data` needs an override.** `_grid_data` (shared with `TableElementForm`) returns `model._sanitized_data(model.normalize_data(parsed))` on the bound-invalid path, deliberately re-rendering the *submitted* grid. But Task 1's suppression forces `gate` to `False` on a subset of the conditions that make `clean_data` raise — the no-answer-cell and blank-answer-cell rules are both a rejection reason *and* a suppression trigger. So an author who ticks the box and forgets one answer gets "An answer cell is blank" **and a silently unticked checkbox**, and their next Save posts `gate: false` from the DOM. The overlap is one-way: `clean_data` also raises via `_scan_spans` (an out-of-range span, checked first), `_caps_ok`, and the course-scope image check, and for those three `normalize_data` leaves `gate` at `True`. Write the override **unconditionally** so it is a no-op on those and correct on all five.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_editor_partial.py`. **That file's helper is `_render(instance)`** (line 22) — it builds `FORM_FOR_TYPE["filltable"](instance=instance)` and renders the partial. `test_partial_has_case_sensitive_checkbox` in the same file is the exact precedent for both the call and the assertion shape:

```python
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]   # non-blank: the guard keeps `gate` on


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

Add to `tests/test_filltable_form.py` (check its existing imports first — it needs `json` and `FillTableElementForm`; add whichever is missing):

```python
def test_rejected_save_keeps_the_gate_ticked():
    # normalize_data suppresses `gate` for exactly the grid that makes clean_data
    # raise here, so without the grid_data override the author's tick is silently
    # lost and their next Save posts gate: false from the DOM.
    payload = {
        "gate": True,
        "cells": [[{"kind": "answer", "answer": ""}]],  # blank -> rejected
    }
    form = FillTableElementForm(data={"data": json.dumps(payload)})
    assert not form.is_valid()
    assert form.grid_data["gate"] is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_filltable_editor_partial.py tests/test_filltable_form.py -k gate -v
```

Expected: FAIL — no `data-gate` attribute, and `grid_data["gate"]` is `False`.

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

In `courses/element_forms.py`, replace `FillTableElementForm`'s existing `grid_data` property:

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

- [ ] **Step 8: Falsify**

1. Drop `{% if d.gate %}checked{% endif %}` → `test_partial_gate_checkbox_is_checked_for_a_gated_element` RED.
2. Restore, then hardcode `checked` on the new `<input data-gate>` (drop the `{% if %}` but keep the attribute) → `test_partial_has_gate_checkbox_unchecked_by_default` RED, and the checked-state test stays GREEN. Mutant 1 leaves this test green, so it needs its own.
3. Restore, then delete the `grid_data` override → `test_rejected_save_keeps_the_gate_ticked` RED.
4. Restore, then drop `gate: !!(gate && gate.checked),` from `serialize` → `test_editor_js_serializes_the_gate_flag` RED.
5. Restore, then delete `var gate = editor.querySelector("[data-gate]");` → the same test RED on its *first* assertion.
6. Restore, then delete the `gate.addEventListener("change", serialize);` line → the same test RED on its *third* assertion.

Mutants 4-6 are separate for the reason Task 1 Step 6 gives: that test makes three independent assertions, and one combined mutant would let two of them hide. Likewise, removing the `data-gate` attribute from the partial altogether reddens the presence clause of `test_partial_has_gate_checkbox_unchecked_by_default`, which mutant 2 leaves untouched.

That third mutant is guarded by `test_editor_js_serializes_the_gate_flag`, written in Step 1.

- [ ] **Step 9: Commit**

```bash
uv run ruff check --no-cache courses/element_forms.py tests/test_filltable_form.py tests/test_filltable_editor_partial.py
uv run ruff format --check courses/element_forms.py tests/test_filltable_form.py tests/test_filltable_editor_partial.py
git add templates/courses/manage/editor/_edit_filltable.html courses/static/courses/js/filltable_editor.js courses/element_forms.py tests/test_editor_twin_drift.py tests/test_filltable_editor_partial.py tests/test_filltable_form.py
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

The importer needs nothing: `_build_fill_table` ends with `FillTableElement(data=FillTableElement.normalize_data(data))`, and the normalizer supplies `gate` — `False` for a legacy bundle lacking the key, and forced off for a bundle whose grid cannot satisfy it. `_val_fill_table` needs nothing either: it checks only gross structural corruption and does no exact-keys check, which is also why an **older** libli can import a newer bundle — it ignores the unknown key and degrades to an ungated table.

- [ ] **Step 1: Write the failing tests**

**Use the file's own idiom.** `tests/test_filltable_transfer.py` imports `SERIALIZERS`, `BUILDERS`, `VALIDATORS` and `MediaIdMap`, and calls them through the registries — the module-private `_ser_fill_table` / `_build_fill_table` are never imported. Builders return a `(obj, children)` pair. The routing-invariant test additionally needs `json` and `FillTableElementForm`, neither of which the file imports yet; add both.

```python
_GATE_CELLS = [[{"kind": "answer", "answer": "1"}]]   # non-blank: the guard keeps `gate` on


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
    # path routes through normalize_data. Pin it: the form and the importer are
    # the only two production construction sites.
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
uv run pytest tests/test_filltable_transfer.py -k gate -v
```

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
2. Restore, then narrow the mutation to the coercion **only** — `bool(data.get("gate"))` → `data.get("gate")`, keeping both conjuncts — and run just this file (`uv run pytest tests/test_filltable_transfer.py -v`).

   **A truthy payload will NOT falsify it.** `and` returns its last operand, so `"yes" and bool(answers) and not any(...)` evaluates to `True` — a real bool — and both existing assertions stay green. The mutant is only visible on a **falsy non-`False`** payload, where the expression returns `""` rather than `False`. So extend the test with that case first:

   ```python
       # An empty string is falsy but is NOT False -- this is the only payload that
       # distinguishes bool(data.get("gate")) from data.get("gate"), because `and`
       # returns its last operand and a truthy value would coerce to True anyway.
       assert FillTableElement.normalize_data(
           {"gate": "", "cells": _GATE_CELLS}
       )["gate"] is False
   ```

   With that line present the coercion mutant goes RED; without it the plan's only falsification for this test does not falsify anything.

- [ ] **Step 6: Commit**

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

The English section currently ends "Records no marks and reveals nothing." — which this change falsifies. The Polish twin ends "Nie przyznaje punktów i niczego nie odsłania." Both must change, and both should describe the scope confinement the way the three existing gate-family sections do.

- [ ] **Step 1: Update the English page**

Replace the final sentence of the `{el:filltable}` section:

```markdown
is one-way. Records no marks. Tick **Reveal the rest of this section when all
cells are correct** to turn the table into a reveal gate: everything after it
stays hidden until a student fills every answer cell correctly, then appears in
one go. Like the other gates (**Show more**, **Fill in & confirm**, **Choose & confirm**),
the reveal stops at the edge of whatever contains the table — inside a callout it
reveals the rest of that callout and nothing beyond it. Two gated tables in a row
chain: the first reveals the second, the second reveals what follows.
```

- [ ] **Step 2: Update the Polish page**

Replace the final sentence of the `{el:filltable}` section:

```markdown
jednokierunkowe. Nie przyznaje punktów. Zaznacz **Odsłoń resztę tej sekcji, gdy
wszystkie komórki są poprawne**, aby zamienić tabelę w bramkę odsłaniającą:
wszystko, co znajduje się po niej, pozostaje ukryte, dopóki uczeń nie wypełni
poprawnie każdej komórki z odpowiedzią, a potem pojawia się naraz. Podobnie jak
w pozostałych bramkach (**Pokaż więcej**, **Uzupełnij i potwierdź**,
**Wybierz i potwierdź**) odsłanianie zatrzymuje się na granicy elementu zawierającego tabelę — wewnątrz
ramki odsłoni resztę tej ramki i nic poza nią. Dwie kolejne bramkowane tabele
tworzą łańcuch: pierwsza odsłania drugą, druga odsłania to, co następuje po niej.
```

**Why the snippets above use plain bolded names rather than links:** that page contains no intra-page links at all (grep for `](interactive-elements` returns zero hits), so a cross-link would both invent a convention and link the page to itself. The bolded form matches the existing prose style.

Note also that none of the three gate sections states the scope confinement: `{el:revealgate}` (:16-22) says only "hides the elements that follow it in the outline", and the other two are similar. So there is no sibling wording to mirror — state the confinement in one sentence of the fill-table section, and accept that it is the first section on the page to say it.

- [ ] **Step 3: Verify the help pages still render**

```bash
uv run pytest tests/test_help.py -v
```

Expected: PASS. If the repo has a help-page link checker or an `{el:...}` anchor test, it runs here.

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


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Copied from
    # tests/test_e2e_filltable.py:40-45 -- a local fixture, not importable.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield
```

Every test carries `@pytest.mark.django_db(transaction=True)`. Steps 1-7 show only the body; this is the full shape they all follow:

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
- **All fixtures must be TOP-LEVEL (slide-scope), not callout children.** `data-element-id` is emitted only by `_lesson_article.html:38` for top-level elements; `calloutelement.html:23` renders children as bare `<div class="callout__child">{% render_element child %}</div>` — no `data-element-id`, no `.lesson-block`. A locator keyed on `.lesson-block[data-element-id=…]` therefore returns `null` for a callout child. Top-level scope also exercises the `.slide` pre-hide selector, and the callout-child *rendering* path is already pinned by Task 2's direct-child unit test, so nothing is lost.
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
    Returns (join_row, concrete_obj) pairs -- test 25 needs the concrete object to
    flip its `gate` mid-test, which a join row alone cannot reach."""
    out = []
    for obj in objs:
        obj.save()
        out.append((add_element(unit, obj), obj))   # tests.factories.add_element
    return out


def _block(join_pk):
    return f".lesson-block[data-element-id='{join_pk}']"


def _visible(page, join_pk):
    return page.evaluate(f'document.querySelector("{_block(join_pk)}").checkVisibility()')
```

The seven fixtures are then: **21/22** `_seed(unit, _filltable(gate=True), _text("trailing"))`; **23** `_seed(unit, _filltable(gate=True), _filltable(gate=True), _text("trailing"))` — adjacent, nothing between the two tables; **24** as 21/22; **25** deliberately **`_seed(unit, _filltable(gate=False), _text("trailing"))`** — seeded UNGATED, then flipped mid-test. Seeding it gated would make the flip a no-op, write the blob while already gated, and silently collapse test 25 into a duplicate of test 24 — losing the "ordering, not storage" distinction that is its whole reason to exist. On the first load `has_reveal_gate` is false, so there is no prepaint and the trailing element is visible; that is expected, since the assertion only runs after the flip and reload; **26** as 23, with `_seed_state(student, unit, {str(table2_row.pk): {"done": True}})` before the first load (note `_seed_state` keys by **str** — `UnitProgress.element_state` is str-keyed); **27** `_seed(unit, _filltable(gate=False), _text("ungated-trailing"), _gate("Show more"), _text("gated-trailing"))` — the trailing `_gate` is what makes `has_reveal_gate` true so `reveal.js` loads at all (see Step 7).

Run with:
```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -v
```
`-m e2e` is mandatory — without it the whole file is silently deselected and pytest exits 5, which reads as success at a glance.

- [ ] **Step 1: Test 21 — a wrong answer keeps the content hidden**

Fixture: `(table_row, _t), (trailing_row, _tr) = _seed(unit, _filltable(gate=True), _text("trailing"))`.

```python
inp = page.locator(".filltable__input").first
inp.fill("nope")
_confirm(page).click()
expect(inp).to_have_class(_INCORRECT)      # <- synchronise BEFORE reading the DOM
assert _visible(page, trailing_row.pk) is False
```

*Mutant: cascade unconditionally, ignoring `all_correct`.*

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
```

*Mutant: remove the `libliRevealCascade` call.*

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

*Mutant: delete `isGateWrapper`'s `break`* — table 1 would reveal everything at once.

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
(table_row, table_obj), (trailing_row, _tr) = _seed(
    unit, _filltable(gate=False), _text("trailing")     # seeded UNGATED -- see the fixture note
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
(table_row, _t), (ungated_trailing_row, _ut), (gate_row, _g), (gated_trailing_row, _gt) = _seed(
    unit, _filltable(gate=False), _text("ungated-trailing"),
    _gate("Show more"), _text("gated-trailing"),
)   # the trailing _gate is what makes has_reveal_gate true so reveal.js LOADS
_login(page, live_server, "ftg_ungated")
page.goto(_unit_url(live_server, unit))

inp = page.locator(f"{_block(table_row.pk)} .filltable__input").first
inp.fill(_ANSWER)                       # fill() itself scrolls the input into view...
scroll_before = page.evaluate("window.scrollY")   # ...so capture AFTER it
page.locator(f"{_block(table_row.pk)} .filltable__confirm").click()
expect(page.locator(f"{_block(table_row.pk)} .filltable__summary")).to_have_class(_SUCCESS)

assert page.evaluate(
    f'document.querySelector("{_block(ungated_trailing_row.pk)}").classList.contains("reveal-shown")'
) is False
# activeElement is <body> here -- lock() hid the Check button. Assert the negative
# that actually distinguishes the mutant:
assert page.evaluate(
    f'!document.querySelector("{_block(ungated_trailing_row.pk)}").contains(document.activeElement)'
) is True
assert page.evaluate("window.scrollY") == scroll_before
```

*Mutant: delete the `hasAttribute("data-reveal-gate")` guard in `filltable.js`.* This is the only test defending the "an ungated fill-table behaves byte for byte" guarantee; every other test in this file uses a gated fixture.

- [ ] **Step 8: Run the suite and falsify per item**

```bash
uv run pytest tests/test_e2e_filltable_gate.py -m e2e -v
```

**There is no single group mutant for this block, and assuming one wastes a debugging session.** Reverting Task 5's `libliRevealCascade` call reddens only tests 22 and 23 — **not** 21, 24, 25, 26 or 27 — because `reveal.js::restoreGates` calls `cascadeFrom` **directly** off `data-state` (line 249) — it never goes through `filltable.js`. The `saveFlag({done: true})` line is unchanged and Task 3 derives `open`, so every reload-based path still works. Under that mutant:

| Test | Under the `libliRevealCascade` mutant | Falsified instead by |
|---|---|---|
| 21 (wrong answer stays hidden) | **GREEN** — a negative assertion; a mutant that reveals nothing passes it trivially | cascading unconditionally, ignoring `all_correct` |
| 22 (correct reveals) | **RED** | — |
| 23 (chain, adjacent) | **RED** | — |
| 24 (reload restores) | **GREEN** — restore path intact | removing Task 3's `open` derivation |
| 25 (pre-tick, single) | **GREEN** — same reason | removing Task 3's `open` derivation |
| 26 (pre-tick, chained) | **GREEN** — same reason | removing Task 3's `open` derivation |
| 27 (ungated no cascade) | **GREEN** — also a negative assertion; nothing cascading is what it wants | deleting the `hasAttribute("data-reveal-gate")` guard (Step 7) |

So: apply each per-item mutant named above and confirm the matching test goes red alone. Do **not** treat a green test under the `libliRevealCascade` mutant as a broken test — for 21, 24, 25, 26 and 27 that is the correct outcome.

- [ ] **Step 9: Screenshots**

Capture the gated and revealed states in **light and dark**. Judge the dark result on its own terms — do not assume the light one carries over. Follow the repo's existing capture scripts in `tests/capture_*.py` for the harness; note that a dark-mode e2e needs `user.theme` set, not just the cookie.

- [ ] **Step 10: Commit**

```bash
git add tests/test_e2e_filltable_gate.py
git commit -m "test(filltable): e2e coverage for the reveal gate

Includes the chained pre-tick case (accepted, reload-healed) and the
ungated-no-cascade guard, whose fixture needs a second gating element or it
cannot fail."
```

---

### Task 10: Translation catalog

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`
- Modify: `locale/pl/LC_MESSAGES/django.mo` (binary, regenerated)

**Interfaces:** consumes the msgid introduced in Task 6.

**This task is last on purpose.** The `.mo` is a binary artifact; regenerating it early in a branch invites a merge conflict that has bitten this repo before.

- [ ] **Step 1: Extract messages**

```bash
uv run python manage.py makemessages -l pl
```

- [ ] **Step 2: Inspect the new entry for a fuzzy pre-fill**

Find `Reveal the rest of this section when all cells are correct` in `locale/pl/LC_MESSAGES/django.po`. This page already contains close neighbours ("Case-sensitive", and the three gate families' copy), which is the classic case for `makemessages` to pre-fill a **wrong** translation and mark it `#, fuzzy`.

If a `#, fuzzy` marker is present, clearing it takes **two** deletions — the marker line *and* the bogus `msgstr`:

```po
#: templates/courses/manage/editor/_edit_filltable.html:39
msgid "Reveal the rest of this section when all cells are correct"
msgstr "Odsłoń resztę tej sekcji, gdy wszystkie komórki są poprawne"
```

- [ ] **Step 3: Compile**

```bash
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 4: Verify no fuzzy markers remain on this entry**

```bash
grep -B 3 "Odsłoń resztę tej sekcji" locale/pl/LC_MESSAGES/django.po
```

Expected: no `#, fuzzy` line in the output.

- [ ] **Step 5: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(filltable): Polish string for the reveal-gate checkbox"
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
git diff origin/master...HEAD -- courses/state.py courses/transfer/schema.py
git diff origin/master...HEAD -- courses/static/courses/js/reveal.js
```

Expected: the middle command prints nothing; the last shows only the `[data-filltablegate]` branch.
