# Lesson-mode Restore for the Deferred Widget Question Types — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the five deferred interactive question types (`ChoiceGridQuestionElement`, `MultiGridQuestionElement`, `MatchPairQuestionElement`, `DragToImageQuestionElement`, `DragFillBlankQuestionElement`) to lesson-mode practice-state parity with the five simple types — a student's answer persists on Check and restores (refilled + re-marked) on reload.

**Architecture:** This is a **verify-first flag flip**, not new mechanism. Slice 3 already built the entire type-agnostic substrate: `check_answer` persists `{"answer": answer_to_json(build_answer(POST))}`, `render_element`'s question branch rehydrates + re-marks + renders filled on any full-page render, and `question.js` hides Check on a restored-correct question. The **only** thing gating these five out is the class flag `RESTORABLE_IN_LESSON = False` they inherit from `QuestionElement`. The premise — "the flag flip alone is sufficient" — is treated as a hypothesis to **falsify per type** (RED with the flag off, GREEN after the flip) before it is trusted, and every drag widget's actual JS re-arm is proven in a real browser (a Django test client cannot observe the overlay/inline widget).

**Tech Stack:** Django, Python, pytest, pytest-django (`client`, `live_server`), Playwright (`page`, e2e). Postgres — **isolated test DB per worktree via `.env` `DATABASE_URL`**.

## Global Constraints

- **The five in-scope types (this slice):** `ChoiceGridQuestionElement`, `MultiGridQuestionElement`, `MatchPairQuestionElement`, `DragToImageQuestionElement`, `DragFillBlankQuestionElement` — all in `courses/models.py`, all currently inheriting `RESTORABLE_IN_LESSON = False` from the base (`courses/models.py:1344`). Class defs: `DragFillBlankQuestionElement:1710`, `MatchPairQuestionElement:1762`, `ChoiceGridQuestionElement:1813`, `MultiGridQuestionElement:1892`, `DragToImageQuestionElement:1980`.
- **The ONLY production edit permitted is the flag flip** (`RESTORABLE_IN_LESSON = True` on the five classes). No new client-rehydrate/`data-state` machinery, no endpoint, no model field, no migration, no translatable string, no question-template edit, no change to the five simple types / quiz mode / the save-restore substrate / `dnd.py` / the grid render tags / `choicegrid.js` / `multigrid.js`. If a type cannot round-trip from the flag flip alone, it is **carved to the Fallback** (reverted to `False`), never forced with new code.
- **`RESTORABLE_IN_LESSON` is the sole gate on BOTH sides.** `check_answer` (`courses/views.py:779`) persists only when it is truthy; `render_element` (`courses/templatetags/courses_extras.py:57`) restores only when it is truthy. Flipping it flips save and restore together — a type can never be enabled on one side only.
- **Blob shape:** exactly `{"answer": answer_to_json(build_answer(POST))}` — a **dict envelope**. `build_lesson_context` (`courses/views.py:373-379`) drops any non-dict value, so a bare list/str is silently ignored.
- **Blob payload per family** (all JSON-native, lossless through `answer_to_json`):
  - `ChoiceGridQuestionElement` → a **positional list**, one entry per row, each an int column-pk or `""` (`build_answer`, models.py:1821).
  - `MultiGridQuestionElement` → a **list-of-lists**, one inner sorted list of int column-pks per row (models.py:1901).
  - `DragFillBlankQuestionElement` / `MatchPairQuestionElement` / `DragToImageQuestionElement` → a **positional list of `slot` strings** (`post.getlist("slot")`; models.py:1727/1777/1999). An unfilled slot posts `""` (the native `<select>`'s blank placeholder), so the list stays positionally aligned.
- **Key seam:** the DB row `UnitProgress.element_state` is **str-keyed** (`str(element.pk)`). The ambient render context map (`context["element_state"]`) is **int-keyed** (`build_lesson_context` re-keys `state[int(k)] = blob`, views.py:377). Save writes the str key; restore looks up `element.pk` (int).
- **rehydrate/answer_from_json are type-blind for these five.** Both branch only on `isinstance(question, ChoiceQuestionElement)` (`courses/quiz.py:89,98`); none of the five is a `ChoiceQuestionElement` subclass, so all take the pass-through `else` branch — the grid positional list / drag slot list arrives verbatim as `submitted_values`, which the grid render tags and `dnd._render_select` consume to emit `checked` / `<option selected>`.
- **No stored verdict** — re-marked on every load (an author fixing a wrong key re-marks a restored answer correctly). No attempt history, no analytics/gradebook coupling, no quiz-mode change.
- **Verify-first / falsification rule** (`[[falsify-tests-not-run-them]]`): every restore/save assertion must be shown able to go RED — either by capturing RED before the flag flip (Task 1's C1 proof) or, for tests written after the flip, by a falsification step that reverts the guard (flag → `False`, or delete the render bounds guard) and observes RED. A passing test proves nothing until falsified. Never leave a parametrized test iterating an empty set (it passes vacuously).
- **Import style (ruff isort):** `pyproject.toml` sets `[tool.ruff.lint.isort] force-single-line = true` and `select` includes `"I"`. **Every** added import — module-level **and** function-local (the e2e seed helpers) — must be **one `import X` / `from m import X` per line**, sorted; a grouped/parenthesized or comma-joined import fails `ruff check` (I001), which `ruff format` does **not** fix. The Definition of Done's `ruff check` gate is unforgiving here, so write imports single-line from the start.
- **Tooling** (`[[uv-run-tooling]]`): run Python via `uv run` (pytest/ruff/manage.py are not on PATH). Default `uv run pytest` excludes e2e (`-m 'not e2e'`, pyproject.toml:48); run e2e with `-m e2e`. Run focused e2e files **foreground**, never the whole `-m e2e` suite in the background (runaway browsers — `[[gallery-carousel-status]]`).
- **Test-DB isolation** (`[[test-db-contention-across-worktrees]]`): this worktree has **no `.env`**, so it would fall back to the default `DATABASE_URL` (`test_libli`) and collide with the main checkout. **Execution prerequisite (do once, before any test):** copy the main repo's `.env` into this worktree and change only the `DATABASE_URL` database name to a unique per-worktree value, e.g. `…/libli_dwqr` (yielding test DB `test_libli_dwqr`). `.env` is gitignored — this produces no commit.
- Commit messages end with the repo's required `Co-Authored-By:` / `Claude-Session:` trailers.

---

### Task 1: Flip the flag + C1 view-level restore proof (red→green) + reconcile the suite

The gating premise-proof and the one production edit. Writes a view-level restore test for each of the five (RED on the current all-deferred tree), flips `RESTORABLE_IN_LESSON = True` on all five, re-runs (GREEN), and reconciles every existing test the flip breaks so the suite is green at the commit. The RED/GREEN outputs are pasted into the commit message as the discoverable falsification artifact.

**Files:**
- Modify: `courses/models.py` — add `RESTORABLE_IN_LESSON = True` to the five classes (`:1710, :1762, :1813, :1892, :1980`).
- Modify: `courses/tests/test_question_restore.py` — add five restore tests; move the five from `DEFERRED` to `IN_SCOPE` (`:29-42`); delete `test_deferred_types_are_not_restorable` (`:54-56`, now vacuous); retarget `test_deferred_type_persists_nothing` (`:158-177`) and `test_deferred_hand_forged_blob_does_not_restore` (`:276-286`).

**Interfaces:**
- Consumes: existing helpers in `courses/tests/test_question_restore.py` — `_enrolled(client)` (`:94`), `_add(unit, obj)` (`:90`), `_seed(unit, student, obj, blob)` (`:211`), `_lesson_url(unit)` (`:205`), `_check_url(unit, element_pk)` (`:83`); factories `make_course_with_unit`, `make_student` from `tests.factories`; models `Element`, `Enrollment`, `UnitProgress`.
- Produces: `RESTORABLE_IN_LESSON = True` on the five classes (single source of truth read by Task 2's save tests and Task 3's restore tests); the five listed in `IN_SCOPE`.

- [ ] **Step 1: Add the five restore view-tests (RED on the current tree)**

Append to `courses/tests/test_question_restore.py`. These seed a str-keyed `element_state` blob, GET the lesson view (so `build_lesson_context` re-keys str→int — never `obj.render` with a str key), and assert the answered state renders: grids → `checked` on the chosen cell (by exact `value="<pk>" checked`); drag types → `<option value="<token>" selected>` on the chosen slot (asserting the **specific** chosen option, since a native `<select>` always has *some* option selected).

```python
# Add these to the EXISTING top-of-file import block, ONE `from courses.models import X`
# per line (ruff isort `force-single-line = true` — a grouped/parenthesized import fails
# `ruff check` I001). Only these eight names are new: the file already imports
# ChoiceGridQuestionElement, MultiGridQuestionElement, MatchPairQuestionElement,
# DragToImageQuestionElement, DragFillBlankQuestionElement, Element, Enrollment, UnitProgress —
# do NOT re-import those (F811 redefinition).
from courses.models import DragBlank
from courses.models import DragZone
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPair
from courses.models import MediaAsset
from courses.models import MultiGridColumn
from courses.models import MultiGridRow


def _image(course):
    return MediaAsset.objects.create(
        course=course, kind="image", file="courses/media/x.png", original_filename="x.png"
    )


def _seed_choicegrid(unit, student, *, chosen="B"):
    """One 1-row matrix: columns A,B; row correct=A. Seed the student's chosen column
    (default 'B' → wrong, so the restore signal is the `checked` cell, not a verdict)."""
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    col_b = GridColumn.objects.create(question=q, label="B")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    picked = col_a if chosen == "A" else col_b
    row = _seed(unit, student, q, {"answer": [picked.pk]})
    return q, row, col_a, col_b


def _seed_multigrid(unit, student):
    """One 1-row multi-select grid: columns A,B; row correct={A}. Seed chosen={A}."""
    q = MultiGridQuestionElement.objects.create(stem="Q")
    col_a = MultiGridColumn.objects.create(question=q, label="A")
    col_b = MultiGridColumn.objects.create(question=q, label="B")
    r = MultiGridRow.objects.create(question=q, statement="r1")
    r.correct_columns.add(col_a)
    row = _seed(unit, student, q, {"answer": [[col_a.pk]]})
    return q, row, col_a, col_b


# The drag/matchpair restore tests seed a WRONG-but-in-pool answer (a distractor / a
# swapped token), NOT the correct one. A distractor still renders `<option value="X"
# selected>`, so the restore signal is decoupled from any correct-verdict rendering path —
# only `_seed_choicegrid` needs the same care (it already seeds "B", the wrong column).
def _seed_matchpair(unit, student, *, chosen="renal"):  # "renal" is a distractor (in pool, wrong)
    q = MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")
    MatchPair.objects.create(question=q, left="Heart", right="cardiac")
    row = _seed(unit, student, q, {"answer": [chosen]})
    return q, row


def _seed_dragfill(unit, student, *, chosen="Rome"):  # "Rome" is a distractor (in pool, wrong)
    q = DragFillBlankQuestionElement.objects.create(stem="Cap is ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    row = _seed(unit, student, q, {"answer": [chosen]})
    return q, row


def _seed_dragimage(unit, student, *, answer=("Lung", "Heart")):  # swapped → both wrong, both in pool
    course = unit.course
    q = DragToImageQuestionElement.objects.create(media=_image(course), alt="Diagram", distractors="Liver")
    DragZone.objects.create(question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    DragZone.objects.create(question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1)
    row = _seed(unit, student, q, {"answer": list(answer)})
    return q, row


def test_restore_choicegrid_checks_chosen_cell(client):
    student, course, unit = _enrolled(client)
    _q, _row, _col_a, col_b = _seed_choicegrid(unit, student, chosen="B")
    body = client.get(_lesson_url(unit)).content.decode()
    assert f'value="{col_b.pk}" checked' in body  # the student's chosen column is checked


def test_restore_multigrid_checks_chosen_cell(client):
    student, course, unit = _enrolled(client)
    _q, _row, col_a, _col_b = _seed_multigrid(unit, student)
    body = client.get(_lesson_url(unit)).content.decode()
    assert f'value="{col_a.pk}" checked' in body


def test_restore_matchpair_selects_chosen_option(client):
    student, course, unit = _enrolled(client)
    _seed_matchpair(unit, student, chosen="renal")  # wrong-but-in-pool distractor
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="renal" selected' in body


def test_restore_dragfill_selects_chosen_option(client):
    student, course, unit = _enrolled(client)
    _seed_dragfill(unit, student, chosen="Rome")  # wrong-but-in-pool distractor
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="Rome" selected' in body


def test_restore_dragimage_selects_both_slots(client):
    student, course, unit = _enrolled(client)
    _seed_dragimage(unit, student, answer=("Lung", "Heart"))  # swapped → both wrong, both in pool
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="Lung" selected' in body
    assert 'value="Heart" selected' in body
```

> Field names verified against `courses/models.py`: `GridColumn(question, label)` / `GridRow(question, statement, correct_column FK)` via `columns`/`rows`; `MultiGridColumn` + `MultiGridRow(correct_columns M2M)`; `MatchPair(question, left, right)`; `DragBlank(question, correct_token)` with the stem carrying a `￿0￿` token marker; `DragZone(question, correct_label, x, y, w, h, order)`; `DragToImageQuestionElement.media` is a required FK to an image `MediaAsset`. `_seed`/`_enrolled`/`_lesson_url` already exist in this file.
>
> **U+FFFF sentinel warning (DragFillBlank stem):** the `￿` in `stem="Cap is ￿0￿"` is a single **U+FFFF** character (the `SENTINEL` in `courses/fillblank.py`; `render_selects` splits on `_TOKEN_RE = ￿(\d+)￿`). It is invisible and easily stripped/mangled by an editor or encoding round-trip during copy-paste. If it is lost, `render_selects` produces **zero** `<select>` gaps and the DragFillBlank restore test fails RED **after** the flip — which the carve logic would misread as "DragFillBlank cannot restore" and spuriously carve a working type. **Preserve it byte-for-byte**, or seed via `tests.factories.DragFillBlankQuestionElementFactory` (its `stem` already carries the sentinel) instead of a hand-typed literal. If a dragfill test fails only because no `<select>` rendered, suspect a lost sentinel before suspecting the restore path.

- [ ] **Step 2: Run the five restore tests — capture RED (flag OFF, current tree)**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k "restore_choicegrid or restore_multigrid or restore_matchpair or restore_dragfill or restore_dragimage"`
Expected: **all five FAIL** — the `checked` / `selected` assertions miss because `render_element`'s restore branch is gated behind `RESTORABLE_IN_LESSON`, still `False` for these types (renders un-restored: grids emit no `checked`; drag selects leave the blank placeholder as the default option). **Confirm each failure is the missing `checked`/`selected` assertion, NOT a `TypeError`/`NoReverseMatch`/collection error** (which would mean a seed identifier is wrong, not that the gate is being exercised). **Save this console output** — it is the RED half of the falsification artifact for the commit message.

- [ ] **Step 3: Flip the flag on the five models**

In `courses/models.py`, add `RESTORABLE_IN_LESSON = True` immediately after the class docstring in each of the five classes. For example, `DragFillBlankQuestionElement` (`:1710`):

```python
class DragFillBlankQuestionElement(QuestionElement):
    """Drag tokens into ordered gaps. Marking is per-gap, like fill-blank, but the
    student picks a discrete chip instead of typing. `stem` stores the token-stem
    from fillblank.parse(); each gap's correct token is a DragBlank row."""

    RESTORABLE_IN_LESSON = True

    REVEAL_TEMPLATE = "courses/elements/_reveal_dragfill.html"
```

Do the same in `MatchPairQuestionElement` (`:1762`), `ChoiceGridQuestionElement` (`:1813`), `MultiGridQuestionElement` (`:1892`), and `DragToImageQuestionElement` (`:1980`) — each gets a `RESTORABLE_IN_LESSON = True` line after its docstring.

- [ ] **Step 4: Reconcile the existing suite for the flip**

The flip immediately breaks three existing tests; fix all three so the file is green at this task's commit.

> **Sequencing note (carve-aware):** parts (a)–(b) below assume the all-green outcome (all five enabled). If Step 5's go/no-go carves any type, do **not** fully empty `DEFERRED` or delete the sentinel test — instead leave each carved type in `DEFERRED`, keep `test_deferred_types_are_not_restorable` parametrized over the still-deferred set, and move only the surviving types into `IN_SCOPE`. Practically: reach Step 5's run first, then finalize this membership edit to match the surviving set, so you never delete-then-un-delete the sentinel test across one step.

(a) In `courses/tests/test_question_restore.py`, move the five deferred classes from `DEFERRED` into `IN_SCOPE` and **empty `DEFERRED`** (all-green case):

```python
IN_SCOPE = [
    ChoiceQuestionElement,
    ShortTextQuestionElement,
    ExtendedResponseQuestionElement,
    ShortNumericQuestionElement,
    FillBlankQuestionElement,
    ChoiceGridQuestionElement,
    MultiGridQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    DragFillBlankQuestionElement,
]
DEFERRED = []  # all widget types enabled this slice; kept for the base-invariant note below
```

(b) **Delete** `test_deferred_types_are_not_restorable` (`:54-56`) — **only in the all-green case**, where `DEFERRED` is empty and the test would iterate nothing and pass vacuously (`[[falsify-tests-not-run-them]]`). Its base-invariant intent is already carried by `test_base_default_is_false` (`:45-46`) — keep that. Add a one-line comment where the deleted test was, noting the base default still guards future subclasses. **If any type is carved** (per the sequencing note above), do **not** delete it — keep it parametrized over the non-empty still-deferred set.

(c) Retarget `test_deferred_type_persists_nothing` (`:158-177`) — it asserted a MatchPair check persists nothing; MatchPair now persists. Rename and invert to assert persistence:

```python
def test_matchpair_check_persists_slot_list(client):
    # MatchPair is now in-scope: a non-empty check persists the slot list envelope.
    student, course, unit = _enrolled(client)
    q = MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")
    MatchPair.objects.create(question=q, left="Heart", right="cardiac")
    row = _add(unit, q)
    resp = client.post(_check_url(unit, row.pk), {"slot": ["cardiac"]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": ["cardiac"]}}
```

(d) Retarget `test_deferred_hand_forged_blob_does_not_restore` (`:276-286`) — it seeded a malformed `{"answer": [[0, 1]]}` MatchPair blob and asserted no restore via the (then-active) scope gate. That gate is gone; the same malformed blob is now caught by the fail-open `try/except` in `render_element` (`courses_extras.py:68-84`). Rename to assert the fail-open path:

```python
def test_matchpair_malformed_blob_is_fail_open(client):
    # A structurally-wrong blob (list-of-lists, not slot strings) must not 500 and must
    # not emit a verdict — the render_element try/except logs and falls through.
    student, course, unit = _enrolled(client)
    obj = MatchPairQuestionElement.objects.create(stem="Q")
    MatchPair.objects.create(question=obj, left="Heart", right="cardiac")
    _seed(unit, student, obj, {"answer": [[0, 1]]})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert "question__verdict" not in resp.content.decode()
```

- [ ] **Step 5: Run the whole file — capture GREEN (flag ON)**

Run: `uv run pytest courses/tests/test_question_restore.py -q`
Expected: **the entire file passes** — the five new restore tests are GREEN, the retargeted tests pass, `test_in_scope_types_are_restorable` now covers all ten types, `test_base_default_is_false` still holds. **Save this console output** — the GREEN half of the falsification artifact.

**Go/no-go carve check.** Every one of the five must individually go red→green. If any type's restore test stays RED after the flip, the flag-flip premise is false for that type: **revert its `RESTORABLE_IN_LESSON` to `False`, move it back to `DEFERRED`, keep a `DEFERRED`-sentinel `test_deferred_types_are_not_restorable` parametrized over only the still-deferred set, and document the carve** (see Fallback). Source analysis indicates all five should pass (both grid bounds guards and the drag blank placeholder already exist), but this is a check to run, not an assumption. Minimum to ship: **at least one grid** red→green (see Fallback → Ship criteria).

- [ ] **Step 6: Confirm no migration is produced**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (a plain class attribute is not a model field).

- [ ] **Step 6b: Confirm the flip's full blast radius is green**

The flag flip is a global production change; verify no test **outside** this file encoded the old deferred behavior before committing it.
Run: `uv run pytest -n auto -m "not e2e"`
Expected: exit 0, 0 failures. (Source analysis found no other non-e2e test asserting these flags and the widget reload e2es are quiz-mode, so the risk is low — but confirm it at the commit that introduces the flip, not only at the Definition of Done.) Also run `uv run ruff check .` here to catch the import-style rule (Global Constraints → Import style) on the new test code before it is committed.

- [ ] **Step 7: Commit (with the RED/GREEN evidence in the message)**

Paste the Step-2 (flag off) and Step-5 (flag on) run outputs into the commit body so red-then-green is a discoverable artifact, annotated with the per-type carve outcome (all five enabled, or the carved set).

```bash
git add courses/models.py courses/tests/test_question_restore.py
git commit
# Subject: feat(widget-restore): enable lesson restore for the 5 deferred widget types (flag flip)
# Body: the RED (flag off) + GREEN (flag on) run outputs from Steps 2 and 5, per-type carve outcome.
```

---

### Task 2: Save-path persistence per type + drag save-side positional alignment

Prove `check_answer` persists the correct envelope for each enabled type on both the JS-fragment and no-JS paths, that an empty answer deletes the key, and — the one save-leg invariant that can silently misfill drag restores — that a **partially**-answered drag question stores a **positionally-aligned** list (a placeholder `""` retained for each empty slot), not a compacted short list.

**Files:**
- Modify: `courses/tests/test_question_restore.py` (append).

**Interfaces:**
- Consumes: `RESTORABLE_IN_LESSON = True` (Task 1); the seed helpers `_seed_choicegrid`, `_seed_multigrid`, `_seed_dragimage` (Task 1) for element construction; `_check_url`, `_enrolled`, `_add`; `answer_to_json`/`answer_is_empty` (already exercised by `check_answer`).
- Produces: no production change — verification only.

- [ ] **Step 1: Write the save-path tests**

Append to `courses/tests/test_question_restore.py`. Post through the real `check_answer` view and assert the stored `element_state`.

```python
def test_check_persists_choicegrid_positional_list(client):
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridColumn.objects.create(question=q, label="B")
    row_obj = GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    el = _add(unit, q)
    client.post(_check_url(unit, el.pk), {f"row_{row_obj.pk}": str(col_a.pk)}, HTTP_X_REQUESTED_WITH="fetch")
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(el.pk): {"answer": [col_a.pk]}}


def test_check_persists_multigrid_list_of_lists(client):
    student, course, unit = _enrolled(client)
    q = MultiGridQuestionElement.objects.create(stem="Q")
    col_a = MultiGridColumn.objects.create(question=q, label="A")
    col_b = MultiGridColumn.objects.create(question=q, label="B")
    r = MultiGridRow.objects.create(question=q, statement="r1")
    r.correct_columns.add(col_a)
    el = _add(unit, q)
    client.post(_check_url(unit, el.pk), {f"row_{r.pk}": [str(col_a.pk), str(col_b.pk)]})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(el.pk): {"answer": [sorted([col_a.pk, col_b.pk])]}}


def test_check_persists_dragfill_slot_list_fragment_path(client):
    # JS-fragment path (X-Requested-With: fetch) — the save runs BEFORE the
    # _wants_fragment split, so it must persist here too. Its no-JS sibling below
    # covers the other leg; keep the fetch header here so the pair covers both.
    student, course, unit = _enrolled(client)
    q = DragFillBlankQuestionElement.objects.create(stem="Cap is ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = _add(unit, q)
    client.post(_check_url(unit, el.pk), {"slot": ["Paris"]}, HTTP_X_REQUESTED_WITH="fetch")
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(el.pk): {"answer": ["Paris"]}}


def test_check_empty_grid_deletes_key(client):
    # An all-"" grid answer reads empty (answer_is_empty recurses) → the prior key is dropped.
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    GridColumn.objects.create(question=q, label="A")
    row_obj = GridRow.objects.create(question=q, statement="r1", correct_column=q.columns.first())
    el = _add(unit, q)
    UnitProgress.objects.create(student=student, unit=unit, element_state={str(el.pk): {"answer": [q.columns.first().pk]}})
    client.post(_check_url(unit, el.pk), {})  # no row_<pk> posted → build_answer → [""]
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(el.pk) not in up.element_state


def test_check_nojs_path_also_persists_dragfill(client):
    # No X-Requested-With header → the no-JS full-page re-render path still saves.
    student, course, unit = _enrolled(client)
    q = DragFillBlankQuestionElement.objects.create(stem="Cap is ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = _add(unit, q)
    client.post(_check_url(unit, el.pk), {"slot": ["Paris"]})  # no fetch header
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(el.pk): {"answer": ["Paris"]}}


def test_check_dragimage_partial_answer_keeps_placeholder_alignment(client):
    # THE save-leg invariant: a partial drag answer (only slot 2 filled) must store a
    # POSITIONALLY-ALIGNED list ["", "Lung"] — a placeholder kept for the empty slot 1 —
    # NOT a compacted ["Lung"] that would shift slot 2's answer onto slot 1 on restore.
    student, course, unit = _enrolled(client)
    course = unit.course
    q = DragToImageQuestionElement.objects.create(media=_image(course), alt="D", distractors="Liver")
    DragZone.objects.create(question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    DragZone.objects.create(question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1)
    el = _add(unit, q)
    # The native selects post one value each; slot 1 left at the blank placeholder ("").
    client.post(_check_url(unit, el.pk), {"slot": ["", "Lung"]})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(el.pk): {"answer": ["", "Lung"]}}
```

- [ ] **Step 2: Run the save-path tests**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k "persists or deletes_key or nojs_path or partial_answer_keeps"`
Expected: **PASS** — `check_answer` already persists for these types now that Task 1 flipped the flag.

- [ ] **Step 3: Falsify the scope gate and the alignment invariant**

- Temporarily revert `RESTORABLE_IN_LESSON` to `False` on `ChoiceGridQuestionElement` only; re-run `-k persists_choicegrid` → must FAIL (no blob written). Restore the flag.
- Confirm the partial-alignment guard would catch a regression: temporarily change the test's expected value to `{"answer": ["Lung"]}` and re-run `-k partial_answer_keeps` → must FAIL (the stored list is `["", "Lung"]`, length 2). Revert the expected value. (This proves the test actually pins the placeholder-retained shape and would go RED if `build_answer`/`answer_to_json` ever dropped the empty slot.)

- [ ] **Step 4: Commit**

```bash
git add courses/tests/test_question_restore.py
git commit -m "test(widget-restore): save-path envelope per type + drag positional-alignment"
```

---

### Task 3: Restore robustness — degradation, partial alignment, empty, preview, reset

Pin the acceptable-degradation floor: a stored blob referencing since-edited structure must render **200, no 500** (the render-time bounds/placeholder guards run **outside** the fail-open `try/except`), and a partial drag answer must restore **positionally** (the restore-leg counterpart to Task 2's save-leg test). Also cover empty/preview/reset for the widget types.

**Files:**
- Modify: `courses/tests/test_question_restore.py` (append).

**Interfaces:**
- Consumes: Task 1 seed helpers; the grid render bounds guards (`courses_extras.py:164` `sv[i] if i < len(sv) else ""`, `:220` `else []`); `dnd._render_select` blank-placeholder behavior (`dnd.py:70-83`); `progress_reset` (`courses/views.py:489`); the `manage_editor` preview route.
- Produces: no production change — verification only.

- [ ] **Step 1: Write the degradation + alignment + empty/preview/reset tests**

Append to `courses/tests/test_question_restore.py`.

```python
def test_restore_grid_stale_column_pk_renders_unfilled(client):
    # A stored column-pk whose column was deleted fails to match on re-mark; the cell
    # renders unfilled — no `checked`, 200, no 500.
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    row = _seed(unit, student, q, {"answer": [999999]})  # non-existent column pk
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert f'value="{col_a.pk}" checked' not in resp.content.decode()  # cell unfilled


def test_restore_grid_fewer_stored_entries_than_rows_is_bounded(client):
    # A row ADDED after save (stored list shorter than current rows) must NOT IndexError:
    # render_choice_grid guards `sv[i] if i < len(sv) else ""`. obj.render() runs OUTSIDE
    # the fail-open try/except, so an unguarded index here would be a real 500.
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    GridRow.objects.create(question=q, statement="r2", correct_column=col_a)  # 2 rows
    _seed(unit, student, q, {"answer": [col_a.pk]})  # only 1 stored entry
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200


def test_restore_grid_more_stored_entries_than_rows_is_bounded(client):
    # A row DELETED after save (stored list longer than current rows): render iterates
    # rows and ignores the extra entry — 200, no crash (a later cell MAY show a
    # neighbour's answer; that bounded misfill is accepted, verdict re-derived on load).
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)  # 1 row
    _seed(unit, student, q, {"answer": [col_a.pk, col_a.pk, col_a.pk]})  # 3 stored entries
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200


def test_restore_drag_stale_slot_list_is_bounded(client):
    # A stored slot list longer than the current zone count (a zone removed after save):
    # render iterates zones, extra entries ignored — 200, no 500.
    student, course, unit = _enrolled(client)
    course = unit.course
    q = DragToImageQuestionElement.objects.create(media=_image(course), alt="D", distractors="Liver")
    DragZone.objects.create(question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    _seed(unit, student, q, {"answer": ["Heart", "Lung", "Liver"]})  # 3 stored, 1 zone
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200


# Position-scoping helper (module-level). Every drag/match slot renders its OWN
# `<select name="slot">` holding the FULL pool, so a global `"value=X selected" in body`
# only proves X is selected SOMEWHERE — it cannot tell slot 0 from slot 1 and so cannot
# detect a positional shift/compaction. These helpers isolate each slot's own <select>
# markup (in document = slot order) so the alignment assertions actually pin position.
def _slot_options(body):
    # One chunk per <select name="slot">, in slot order, truncated at that select's close.
    chunks = body.split('<select name="slot"')[1:]  # [0] is the pre-first-select prefix
    return [c.split("</select>")[0] for c in chunks]


def test_restore_dragimage_partial_answer_aligns_positionally(client):
    # Restore-leg alignment: an aligned partial blob ["", "Lung"] must pre-select Lung on
    # slot 2 and leave slot 1 on the blank placeholder — NOT shift Lung onto slot 1.
    student, course, unit = _enrolled(client)
    course = unit.course
    q = DragToImageQuestionElement.objects.create(media=_image(course), alt="D", distractors="Liver")
    DragZone.objects.create(question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    DragZone.objects.create(question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1)
    _seed(unit, student, q, {"answer": ["", "Lung"]})
    slots = _slot_options(client.get(_lesson_url(unit)).content.decode())
    assert len(slots) == 2
    assert "selected" not in slots[0]              # slot 1 stays on the blank placeholder
    assert 'value="Lung" selected' in slots[1]     # slot 2 restored to Lung, in its OWN select


def test_restore_matchpair_partial_answer_aligns_positionally(client):
    student, course, unit = _enrolled(client)
    q = MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")
    MatchPair.objects.create(question=q, left="Heart", right="cardiac")
    MatchPair.objects.create(question=q, left="Kidney", right="renal")
    _seed(unit, student, q, {"answer": ["", "renal"]})
    slots = _slot_options(client.get(_lesson_url(unit)).content.decode())
    assert len(slots) == 2
    assert "selected" not in slots[0]              # row 1 stays on the placeholder
    assert 'value="renal" selected' in slots[1]    # row 2 restored, in its OWN select


def test_restore_dragfill_partial_answer_aligns_positionally(client):
    q_stem = "￿0￿ and ￿1￿"  # two U+FFFF gap markers — preserve byte-for-byte
    student, course, unit = _enrolled(client)
    q = DragFillBlankQuestionElement.objects.create(stem=q_stem, distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    _seed(unit, student, q, {"answer": ["", "Madrid"]})
    slots = _slot_options(client.get(_lesson_url(unit)).content.decode())
    assert len(slots) == 2
    assert "selected" not in slots[0]              # gap 1 stays on the placeholder
    assert 'value="Madrid" selected' in slots[1]   # gap 2 restored, in its OWN select


def test_restore_grid_empty_blob_renders_blank(client):
    # An all-"" grid blob reads empty; nothing restores (no checked cell), 200.
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    _seed(unit, student, q, {"answer": [""]})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert f'value="{col_a.pk}" checked' not in resp.content.decode()  # nothing restored


def test_editor_preview_does_not_restore_widget(client):
    # The editor preview renders mode="lesson" with NO element_state → nothing restores,
    # even when another student has a stored answer.
    author = make_student(client, "wr_author")
    course, unit = make_course_with_unit(owner=author)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    row = Element.objects.create(unit=unit, content_object=q)
    other = make_verified_user()
    UnitProgress.objects.create(student=other, unit=unit, element_state={str(row.pk): {"answer": [col_a.pk]}})
    preview_url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    body = client.get(preview_url).content.decode()
    # Scope the negative to the restore-specific string — the authoring page chrome
    # (toolbars, author correct-column markers, aria-checked) may contain bare "checked".
    assert f'value="{col_a.pk}" checked' not in body


def test_start_fresh_clears_widget_blob(client):
    student, course, unit = _enrolled(client)
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    row = _seed(unit, student, q, {"answer": [col_a.pk]})
    client.post(reverse("courses:progress_reset", kwargs={"slug": course.slug, "node_pk": unit.pk}))
    up = UnitProgress.objects.filter(student=student, unit=unit).first()
    assert not (up and up.element_state.get(str(row.pk)))
```

> `make_course_with_unit(owner=...)`, `make_student`, `make_verified_user`, and the `manage_editor` route (kwarg `pk`) follow the sibling slice-3 tests in this same file (`test_editor_preview_does_not_restore`). If `progress_reset` requires a confirmation POST field, mirror whatever the existing `test_start_fresh_clears_question_blob` sends (same file). If the `manage_editor` preview requires build access beyond `make_student`, reuse the login the existing editor-preview test uses.

- [ ] **Step 2: Run the robustness tests**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k "stale or bounded or aligns_positionally or empty_blob or editor_preview_does_not_restore_widget or start_fresh_clears_widget"`
Expected: **PASS**.

- [ ] **Step 3: Falsify the render bounds guard and the alignment**

- Temporarily edit `courses/templatetags/courses_extras.py:164` from `sv[i] if i < len(sv) else ""` to `sv[i]` and re-run `-k fewer_stored_entries` → must **500/IndexError** (proving the guard is load-bearing and that `obj.render()` is outside the try/except). Revert.
- **Prove each partial-alignment test actually pins position** (all three — dragimage, matchpair, dragfill): temporarily swap that test's seed from `["", "<token>"]` to the mis-aligned `["<token>", ""]` (token on slot 0) and re-run it → `assert "selected" not in slots[0]` must FAIL (the token is now selected in slot 0's own `<select>`), confirming the per-slot scoping detects a positional shift. Revert each. (A global-substring version of these assertions would stay GREEN under this swap — that is the vacuous form the `_slot_options` helper exists to avoid.)

- [ ] **Step 4: Commit**

```bash
git add courses/tests/test_question_restore.py
git commit -m "test(widget-restore): degradation bounds, positional alignment, empty/preview/reset"
```

---

### Task 4: e2e — DragToImage overlay widget re-arms after reload (mandatory crux)

A Django test client sees the server-rendered `<select>` but **cannot** observe whether `dnd.js` painted the absolute-positioned overlay. This is the riskiest re-arm path and the whole reason the type was deferred, so it must be proven in a real browser: answer via the real drag gesture, reload, assert the **visible overlay targets** show the restored answer. Cover correct **and** incorrect (still editable by a real gesture).

**Files:**
- Create: `tests/test_e2e_widget_restore.py` (top-level `tests/`, matching the repo's `tests/test_e2e_*.py` convention — the spec's illustrative `courses/tests/test_question_restore_e2e.py` does not match where e2e tests actually live).
- Test: the file itself.

**Interfaces:**
- Consumes: `RESTORABLE_IN_LESSON = True` on `DragToImageQuestionElement` (Task 1); the drag-to-image e2e harness in `tests/test_e2e_questions_2dii.py` (`_size_stage`, `_PNG_DATA_URI`, `.dragimage__target`, `select[name="slot"]`, `.dnd__chip[data-token]`); the login + factory pattern in `tests/test_e2e_question_restore.py`.
- Produces: browser proof that the overlay re-arms from server-rendered selects.

- [ ] **Step 1: Write the overlay restore e2e**

Create `tests/test_e2e_widget_restore.py`. Model the harness on `tests/test_e2e_questions_2dii.py` (the `_size_stage`/`_PNG_DATA_URI`/overlay locators) and `tests/test_e2e_question_restore.py` (the `_login`, `expect_response(lambda r: "/check/" in r.url)`, reload pattern). Drive the **real drag gesture** — never `page.evaluate` to fake the answer (`[[e2e-must-drive-real-ui]]`).

```python
"""Playwright e2e: the deferred WIDGET question types re-arm their JS widget from a
server-side practice-state restore after reload.

The Django test client (courses/tests/test_question_restore.py) proves the server
renders the correct <select> values, but cannot observe whether dnd.js painted the
overlay / inline slots. These e2es drive the REAL gesture, reload, and assert the
VISIBLE widget shows the restored answer -- the actual falsification of "the JS widget
cannot be re-armed from server-rendered selects". Marked e2e (run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _size_stage(page, w=400, h=300):
    page.wait_for_selector("[data-dragimage-stage]")
    page.evaluate(
        """([w, h, src]) => {
            const stage = document.querySelector('[data-dragimage-stage]');
            stage.style.width = w + 'px'; stage.style.height = h + 'px';
            stage.style.position = 'relative'; stage.style.display = 'block';
            const img = stage.querySelector('img');
            if (img) { img.src = src; img.style.width = w + 'px'; img.style.height = h + 'px'; }
        }""",
        [w, h, _PNG_DATA_URI],
    )
    page.wait_for_function(
        """() => { const t = document.querySelector('.dragimage__target');
            if (!t) return false; const r = t.getBoundingClientRect();
            return r.width > 4 && r.height > 4; }"""
    )


def _seed_dragimage_lesson(username, slug):
    # One import per line (ruff force-single-line); keep sorted.
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import DragToImageQuestionElement
    from courses.models import DragZone
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MediaAsset

    user = make_verified_user(username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD)
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(course=course, kind="unit", unit_type="lesson", title="U")
    media = MediaAsset.objects.create(course=course, kind="image", file="courses/media/x.png", original_filename="x.png")
    q = DragToImageQuestionElement.objects.create(media=media, alt="Diagram", distractors="Liver")
    DragZone.objects.create(question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0)
    DragZone.objects.create(question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1)
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


def _lesson_url(live_server, course, unit):
    return f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"


@pytest.mark.django_db(transaction=True)
def test_dragimage_overlay_restores_correct_after_reload(live_server, page):
    course, unit, el = _seed_dragimage_lesson("wr_di_ok", "wr-di-ok")
    _login(page, live_server, "wr_di_ok")
    page.goto(_lesson_url(live_server, course, unit))
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    page.locator('.dnd__chip[data-token="Heart"]').drag_to(targets.nth(0))
    page.locator('.dnd__chip[data-token="Lung"]').drag_to(targets.nth(1))
    with page.expect_response(lambda r: "/check/" in r.url):
        page.locator('.question__form button[type="submit"]').click()

    page.reload()
    _size_stage(page)
    # The overlay targets (VISIBLE widget) must show the restored answer on load.
    targets = page.locator(".dragimage__target")
    expect(targets.nth(0)).to_have_text("Heart")
    expect(targets.nth(1)).to_have_text("Lung")
    # And the native selects (source of truth the overlay paints from) are pre-selected.
    assert page.locator('select[name="slot"]').nth(0).input_value() == "Heart"
    assert page.locator('select[name="slot"]').nth(1).input_value() == "Lung"


@pytest.mark.django_db(transaction=True)
def test_dragimage_overlay_restores_incorrect_and_stays_editable(live_server, page):
    course, unit, el = _seed_dragimage_lesson("wr_di_bad", "wr-di-bad")
    _login(page, live_server, "wr_di_bad")
    page.goto(_lesson_url(live_server, course, unit))
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    page.locator('.dnd__chip[data-token="Liver"]').drag_to(targets.nth(0))  # wrong
    page.locator('.dnd__chip[data-token="Lung"]').drag_to(targets.nth(1))
    with page.expect_response(lambda r: "/check/" in r.url):
        page.locator('.question__form button[type="submit"]').click()

    page.reload()
    _size_stage(page)
    targets = page.locator(".dragimage__target")
    expect(targets.nth(0)).to_have_text("Liver")  # the WRONG answer still painted
    # Editability BY GESTURE (not by attribute): re-drag a different chip onto slot 0.
    page.locator('.dnd__chip[data-token="Heart"]').drag_to(targets.nth(0))
    expect(page.locator(".dragimage__target").nth(0)).to_have_text("Heart")
    assert page.locator('select[name="slot"]').nth(0).input_value() == "Heart"
```

> `_size_stage` must be re-run **after** `page.reload()` — the factory image is not served, so the stage collapses to 0px on every load and the overlay targets need geometry restored (same reason `tests/test_e2e_questions_2dii.py` calls it after each navigation). The overlay `paint()` reads `sel.value` on boot (dnd.js), so the target text equals the restored select value. Do **not** assert Check-hidden / verdict-shown here: `question.js` only hides Check when the lesson template already renders `.question__verdict.is-correct`, which is contingent per type — assert those **only if** observed, never fail on their absence (would spuriously carve a correctly-restored type).

- [ ] **Step 2: Run the overlay e2e (foreground, focused)**

Run: `uv run pytest tests/test_e2e_widget_restore.py -q -m e2e`
Expected: **PASS** (both cases). Run focused/foreground — never the whole `-m e2e` suite in the background (`[[gallery-carousel-status]]`).

- [ ] **Step 3: Falsify the restore**

Temporarily revert `RESTORABLE_IN_LESSON = False` on `DragToImageQuestionElement` and re-run → after reload the overlay targets are empty (no restore), so `to_have_text("Heart")` FAILS. Revert the flag.

> **Carve rule:** if this overlay e2e cannot be made to pass (the widget genuinely does not re-arm from server selects), `DragToImageQuestionElement` routes to the Fallback: revert its flag to `False`, move it back to `DEFERRED`, remove/deferred-convert its tests, and document the carve. The grids + inline drag can still ship.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_widget_restore.py
git commit -m "test(widget-restore): e2e DragToImage overlay re-arms after reload"
```

---

### Task 5: e2e — inline drag widget (DragFillBlank) re-arms after reload (mandatory)

The inline widgets (`DragFillBlank`, `MatchPair`) re-arm through `buildInlineSlots` — a **distinct** dnd.js code path from the overlay's `paint()` that a view test cannot observe. At least one inline e2e is mandatory; it vouches for the shared `buildInlineSlots` path for **both** inline types only if that function has no per-type branch and both inline templates present the same slot DOM shape.

**Files:**
- Modify: `tests/test_e2e_widget_restore.py` (append).

**Interfaces:**
- Consumes: `RESTORABLE_IN_LESSON = True` on `DragFillBlankQuestionElement` (Task 1); the dragfill e2e harness in `tests/test_e2e_questions_2d.py` (`.dnd__chip[data-token]`, `.dnd__slot`, `select[name="slot"]`, stem `"…￿0￿…"` + `DragBlank`); `buildInlineSlots` (`courses/static/courses/js/dnd.js:180`, reads `sel.value` at `:186`).
- Produces: browser proof that the inline slot re-arms from server-rendered selects.

- [ ] **Step 1: Confirm the shared-path vouch precondition**

Read `courses/static/courses/js/dnd.js` `buildInlineSlots` (around `:180-214`). **Source-confirm** it has **no per-inline-type branch** (it keys generically on `sel.value` / `.dnd__slot`, identical for dragfill and matchpair). Both inline templates render `<select name="slot">` inside `.dnd__rows`/inline markup that `buildInlineSlots` enhances into `.dnd__slot`. If confirmed, one inline e2e (DragFillBlank) vouches for MatchPair too, and MatchPair's distinct **server render** (`render_match_rows`) is already covered by its Task 1 view test. If the confirm **fails** (a per-type branch, or differing slot DOM), add a second inline e2e for MatchPair instead of relying on the vouch. Record the confirmation outcome in the commit message.

> **MatchPair fallback e2e shape (only if the vouch fails):** mirror `test_dragfill_inline_slot_restores_after_reload` (Step 2), swapping the seed for a `_seed_matchpair_lesson` that builds a `MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")` + `MatchPair.objects.create(question=q, left="Heart", right="cardiac")` on a lesson `ContentNode` (same login/enroll pattern), and drive the same locators — `render_match_rows` also emits `<ol class="dnd__rows"><li class="dnd__row">…<select name="slot"></li>` which `buildInlineSlots` enhances into `.dnd__slot`, so the gesture (`.dnd__chip[data-token="cardiac"].drag_to(.dnd__slot.first)`), the reload, and the `expect(.dnd__slot.first).to_have_text("cardiac")` assertion are identical to the dragfill case. No new locator concept is needed.

- [ ] **Step 2: Write the inline restore e2e**

Append to `tests/test_e2e_widget_restore.py`:

```python
def _seed_dragfill_lesson(username, slug):
    # One import per line (ruff force-single-line); keep sorted.
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement
    from courses.models import Element
    from courses.models import Enrollment

    user = make_verified_user(username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD)
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(course=course, kind="unit", unit_type="lesson", title="U")
    q = DragFillBlankQuestionElement.objects.create(stem="Cap is ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_dragfill_inline_slot_restores_after_reload(live_server, page):
    course, unit, el = _seed_dragfill_lesson("wr_df", "wr-df")
    _login(page, live_server, "wr_df")
    page.goto(_lesson_url(live_server, course, unit))

    # Real drag: chip 'Paris' onto the inline drop-slot.
    page.locator('.dnd__chip[data-token="Paris"]').drag_to(page.locator(".dnd__slot").first)
    assert page.locator('select[name="slot"]').input_value() == "Paris"
    with page.expect_response(lambda r: "/check/" in r.url):
        page.locator('.question__form button[type="submit"]').click()

    page.reload()
    page.wait_for_selector(".dnd__slot")
    # The VISIBLE inline slot (built by buildInlineSlots from sel.value on boot) shows the token.
    expect(page.locator(".dnd__slot").first).to_have_text("Paris")
    assert page.locator('select[name="slot"]').input_value() == "Paris"
```

> `buildInlineSlots` seeds `slot.textContent = sel.value` on boot (dnd.js:186), so a server-restored select makes the visible `.dnd__slot` show the token after reload. Assert the visible slot text, not just the hidden select. Same Check/verdict caveat as Task 4 (assert only if observed).

- [ ] **Step 3: Run the inline e2e (foreground, focused)**

Run: `uv run pytest tests/test_e2e_widget_restore.py -q -m e2e -k dragfill_inline`
Expected: **PASS**.

- [ ] **Step 4: Falsify the restore**

Temporarily revert `RESTORABLE_IN_LESSON = False` on `DragFillBlankQuestionElement` and re-run → after reload the `.dnd__slot` is empty (`…`), so `to_have_text("Paris")` FAILS. Revert.

> **Carve rule:** a failed inline e2e disproves the shared-`buildInlineSlots` vouch — so MatchPair may **not** ship on the vouch. Carve DragFillBlank (revert flag, deferred-convert its tests), and either give MatchPair its own passing inline e2e or carve it too.

- [ ] **Step 5: Run the full inline+overlay e2e file once**

Run: `uv run pytest tests/test_e2e_widget_restore.py -q -m e2e`
Expected: all cases PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_widget_restore.py
git commit -m "test(widget-restore): e2e DragFillBlank inline slot re-arms after reload"
```

---

## Fallback / carve decisions

Every carve is driven by an **observed RED or failed precondition**, never schedule pressure. Source analysis says all five should pass, but the executor must act on what the tests actually show:

- **A type's C1 view test stays RED after the flip** → revert its `RESTORABLE_IN_LESSON` to `False`, move it back to `DEFERRED`, keep a `DEFERRED`-parametrized `test_deferred_types_are_not_restorable` over the still-deferred set, document the carve, and remove/deferred-convert that type's save/restore/e2e tests so the committed suite is green.
- **A drag type's C4 e2e fails** (widget cannot re-arm) → carve that drag type the same way. A failed **inline** e2e also voids the `buildInlineSlots` vouch, so the sibling inline type must get its own e2e or be carved too.
- **The drag save-side alignment test (Task 2) goes RED** because `dnd.py` drops empty slots → that is a **shared** defect and fixing it is a production edit this flag-flip slice excludes: carve **all three** drag types, ship the two grids, and spin the placeholder fix into its own follow-up spec. (Source shows placeholders ARE retained — the native `<select>` posts `""` and `getlist` keeps it — so this is not expected to fire.)
- **A grid render bounds-guard test (Task 3) 500s** because the `sv[i] if i < len(sv)` guard is absent → adding it is a production edit this slice excludes: carve the grids, spin the guard fix into its own follow-up, ship the passing drag types. (Source shows both guards ARE present.)
- **Ship criteria:** at least **one grid** red→green is the floor to ship anything (the two grids are independent, per-type carveable). If **neither** grid restores, the premise is falsified and **nothing ships** (the deferral was right) — document and abandon. A drag type ships only if it clears its C1 view test, its C4 e2e (or the inline vouch), and the save-side alignment precondition.

## Definition of Done

- [ ] Task 1 commit contains the RED (flag off) + GREEN (flag on) run outputs and the per-type carve outcome.
- [ ] Full non-e2e suite green: `uv run pytest -n auto -m "not e2e"` (exit 0, 0 failures) — run at every red-window boundary, not only here.
- [ ] Focused e2e green (foreground): `uv run pytest tests/test_e2e_widget_restore.py -q -m e2e` (overlay + inline), plus a smoke of `tests/test_e2e_question_restore.py`.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`.
- [ ] `uv run python manage.py check` clean.
- [ ] Every falsification step performed (guard/flag reverted → RED → restored) at least once during development.
- [ ] The only production diff is `RESTORABLE_IN_LESSON = True` on the shipping subset of the five models (carved types remain `False`); no template, endpoint, migration, `dnd.py`, or render-tag change.
