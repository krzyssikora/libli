# Lesson-mode Question Answer Restore — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist a student's lesson-mode question answer so it survives a page reload, restoring the filled answer plus a re-derived verdict, for the five simple question types.

**Architecture:** Persist-on-check + server-side restore. `check_answer` writes the parsed answer (JSON envelope) into `UnitProgress.element_state`; `render_element`'s question branch reads that per-element map on any full-page render and refills + re-marks the question by reusing the quiz-mode helpers. No new endpoint, model field, or migration; zero question-template edits.

**Tech Stack:** Django, Python, pytest, Playwright (e2e). Postgres (isolated test DB per worktree via `.env`).

## Global Constraints

- **In-scope types (persist AND restore):** `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `ExtendedResponseQuestionElement`, `ChoiceQuestionElement`, `FillBlankQuestionElement`. Gated by a single class attribute `RESTORABLE_IN_LESSON`.
- **Deferred types (must neither persist nor restore):** `DragFillBlankQuestionElement`, `MatchPairQuestionElement`, `DragToImageQuestionElement`, `ChoiceGridQuestionElement`, `MultiGridQuestionElement`.
- **Blob shape:** exactly `{"answer": answer_to_json(build_answer(POST))}` — a **dict envelope** (bare list/str is dropped by `build_lesson_context`'s non-dict read filter).
- **Key seam:** the DB row `UnitProgress.element_state` is **str-keyed** (`str(element.pk)`); the ambient context map is **int-keyed** (`{int(Element.pk): blob}`, views.py:371-378). Save writes the str key; restore looks up the int key.
- **No stored verdict** — re-mark on every load. **No new migration** (`makemigrations --check` must stay clean). **No question-template edits.**
- **Questions are non-nestable:** none of the five in-scope types are in `NESTABLE_TYPE_KEYS` (`courses/builder.py:34`), so they only ever render top-level via `_lesson_article.html` (which passes the feedback kwargs). There is no Tabs/TwoColumn nested-child render path to thread `feedback_for_pk`/`element_state` through — the restore seam in `render_element` sees every question at top level.
- **Falsification rule:** for every guard, the test must go RED when the guard is deleted. A passing test proves nothing until falsified.
- **Tooling:** run Python via `uv run` (pytest/ruff/manage.py are not on PATH). Test DB is isolated per worktree via `.env` `DATABASE_URL`.
- Commit messages end with the repo's required Co-Authored-By / Claude-Session trailers.

---

### Task 1: `RESTORABLE_IN_LESSON` scope contract

The single source of truth for which question types participate. Consumed by Task 3 (save) and Task 4 (restore).

**Files:**
- Modify: `courses/models.py` — `QuestionElement` (base, ~line 1333) and the five in-scope subclasses (`ChoiceQuestionElement` ~1432, `ShortTextQuestionElement` ~1565, `ExtendedResponseQuestionElement` ~1592, `ShortNumericQuestionElement` ~1622, `FillBlankQuestionElement` ~1646).
- Test: `courses/tests/test_question_restore.py` (new).

**Interfaces:**
- Produces: class attribute `RESTORABLE_IN_LESSON: bool` on `QuestionElement` and every subclass — `False` on base + all deferred subclasses (inherited), `True` on the five in-scope subclasses.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_question_restore.py`:

```python
import pytest

from courses.models import (
    ChoiceGridQuestionElement,
    ChoiceQuestionElement,
    DragFillBlankQuestionElement,
    DragToImageQuestionElement,
    ExtendedResponseQuestionElement,
    FillBlankQuestionElement,
    MatchPairQuestionElement,
    MultiGridQuestionElement,
    QuestionElement,
    ShortNumericQuestionElement,
    ShortTextQuestionElement,
)

IN_SCOPE = [
    ChoiceQuestionElement,
    ShortTextQuestionElement,
    ExtendedResponseQuestionElement,
    ShortNumericQuestionElement,
    FillBlankQuestionElement,
]
DEFERRED = [
    ChoiceGridQuestionElement,
    MultiGridQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    DragFillBlankQuestionElement,
]


def test_base_default_is_false():
    assert QuestionElement.RESTORABLE_IN_LESSON is False


@pytest.mark.parametrize("cls", IN_SCOPE)
def test_in_scope_types_are_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is True


@pytest.mark.parametrize("cls", DEFERRED)
def test_deferred_types_are_not_restorable(cls):
    assert cls.RESTORABLE_IN_LESSON is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_question_restore.py -q`
Expected: FAIL with `AttributeError: type object 'QuestionElement' has no attribute 'RESTORABLE_IN_LESSON'`.

- [ ] **Step 3: Add the attribute (base = False)**

In `courses/models.py`, inside `class QuestionElement(ElementBase):`, add after the docstring (before the `MarkingMode` inner class):

```python
    # Practice-state (slice 3): does a lesson-mode answer to this type persist and
    # restore across reload? Base default off; the five simple, server-refillable
    # types opt in. Single source of truth for BOTH the save (check_answer) and the
    # restore (render_element) sides.
    RESTORABLE_IN_LESSON = False
```

- [ ] **Step 4: Opt in the five in-scope subclasses**

In each of the five classes, add `RESTORABLE_IN_LESSON = True` immediately after the class docstring (next to `REVEAL_TEMPLATE` where present). For example, in `ShortTextQuestionElement`:

```python
class ShortTextQuestionElement(QuestionElement):
    """Free-text answer marked by normalized comparison against >=1 accepted lines."""

    RESTORABLE_IN_LESSON = True

    REVEAL_TEMPLATE = "courses/elements/_reveal_shorttext.html"
```

Do the same in `ChoiceQuestionElement`, `ExtendedResponseQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_question_restore.py -q`
Expected: PASS (all parametrized cases).

- [ ] **Step 6: Confirm no migration is produced**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (a plain class attribute is not a model field).

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/tests/test_question_restore.py
git commit -m "feat(question-restore): RESTORABLE_IN_LESSON scope contract on the 5 simple types"
```

---

### Task 2: `save_element_state` helper + `element_state_save` refactor

Extract the atomic write so `check_answer` and `element_state_save` share one path, and fix the delete path so it never spawns a `UnitProgress` row for a passive previewer.

**Files:**
- Modify: `courses/views.py` — add module-level `save_element_state(...)`; refactor `element_state_save`'s atomic block (currently ~lines 727-738) to call it.
- Test: `courses/tests/test_question_restore.py` (append), plus the existing `courses/tests/test_element_state_endpoint.py` must still pass unchanged.

**Interfaces:**
- Produces: `save_element_state(user, unit, element_pk, blob)` in `courses/views.py`. `blob` is a dict to store (upserts the row) or `None` to delete the key (operates only on an existing row; never creates one). Returns `None`.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_question_restore.py`:

```python
from courses.models import Enrollment, UnitProgress
from courses.views import save_element_state
from tests.factories import make_course_with_unit, make_verified_user

pytestmark = pytest.mark.django_db  # ensure module has DB access for the tests below


def test_save_helper_stores_and_deletes():
    course, unit = make_course_with_unit()
    user = make_verified_user()
    Enrollment.objects.create(student=user, course=course)

    save_element_state(user, unit, 7, {"answer": "x"})
    up = UnitProgress.objects.get(student=user, unit=unit)
    assert up.element_state == {"7": {"answer": "x"}}

    save_element_state(user, unit, 7, None)
    up.refresh_from_db()
    assert "7" not in up.element_state


def test_save_helper_delete_does_not_spawn_a_row():
    course, unit = make_course_with_unit()
    user = make_verified_user()
    Enrollment.objects.create(student=user, course=course)

    # No UnitProgress row exists yet; deleting a key must NOT create one.
    save_element_state(user, unit, 7, None)
    assert not UnitProgress.objects.filter(student=user, unit=unit).exists()
```

> Note: the module already declares `pytestmark = pytest.mark.django_db` at the top from Task 1; the duplicate assignment here is harmless but you may omit it if the top-level one is in scope.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k save_helper`
Expected: FAIL with `ImportError: cannot import name 'save_element_state'`.

- [ ] **Step 3: Add the helper**

In `courses/views.py`, add a module-level function near `element_state_save` (reuses the existing `transaction` and `UnitProgress` imports):

```python
def save_element_state(user, unit, element_pk, blob):
    """Atomic per-student practice-state write, shared by check_answer and
    element_state_save. `blob` is a dict to STORE (upserts the row), or None to
    DELETE the key. On delete, operate only on an EXISTING row — never spawn a row
    just to pop a missing key (a passive previewer clicking Check on a blank
    question must not create a spurious empty-state row)."""
    with transaction.atomic():
        if blob is None:
            progress = (
                UnitProgress.objects.select_for_update()
                .filter(student=user, unit=unit)
                .first()
            )
            if progress is None:
                return  # nothing to delete; do not spawn a row
            progress.element_state.pop(str(element_pk), None)
        else:
            UnitProgress.objects.get_or_create(student=user, unit=unit)
            progress = UnitProgress.objects.select_for_update().get(
                student=user, unit=unit
            )
            progress.element_state[str(element_pk)] = blob
        progress.save()
```

- [ ] **Step 4: Refactor `element_state_save` to use the helper**

In `element_state_save`, replace the existing atomic write block:

```python
    with transaction.atomic():
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        if result is state_svc.EMPTY:
            progress.element_state.pop(str(element.pk), None)
            blob = {}
        else:
            progress.element_state[str(element.pk)] = result
            blob = result
        progress.save()
    return _resp(blob)
```

with a call to the helper that keeps computing the echo blob for `_resp`:

```python
    if result is state_svc.EMPTY:
        save_element_state(request.user, node, element.pk, None)
        blob = {}
    else:
        save_element_state(request.user, node, element.pk, result)
        blob = result
    return _resp(blob)
```

The REJECT branch above this block, the `_stored()`/`_resp()` helpers, and all previewer/echo semantics are unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_question_restore.py courses/tests/test_element_state_endpoint.py -q`
Expected: PASS — the new helper tests AND every existing endpoint test (echo, EMPTY-drops-key, REJECT) still green.

- [ ] **Step 6: Falsify the no-spawn guard**

Temporarily change the helper's delete path to `UnitProgress.objects.get_or_create(...)` then pop. Re-run `-k delete_does_not_spawn` → it must FAIL (a row appears). Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/views.py courses/tests/test_question_restore.py
git commit -m "refactor(state): extract save_element_state; delete path no longer spawns a row"
```

---

### Task 3: Persist the answer on check (`check_answer`)

**Files:**
- Modify: `courses/views.py` — `check_answer` (~lines 744-789), insert the save after `result = question.mark(answer)`.
- Test: `courses/tests/test_question_restore.py` (append).

**Interfaces:**
- Consumes: `save_element_state` (Task 2); `RESTORABLE_IN_LESSON` (Task 1); `answer_is_empty`, `answer_to_json` (already imported in views.py, lines 70-71).
- Produces: after any lesson check of an in-scope question, `UnitProgress.element_state[str(element.pk)] == {"answer": answer_to_json(build_answer(POST))}`, or the key is absent when the answer is empty.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_question_restore.py`:

```python
from django.urls import reverse

from courses.models import Choice, Element, MatchPairQuestionElement
from tests.factories import make_student


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _add(unit, obj):
    return Element.objects.create(unit=unit, content_object=obj)


def _enrolled(client):
    student = make_student(client, "qr_save")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    return student, course, unit


def test_check_persists_shorttext_envelope_fragment_path(client):
    # JS-fragment path (X-Requested-With: fetch) — exercises the branch the lesson UI
    # actually uses, pinning that the save runs before the _wants_fragment split.
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "paris"}, HTTP_X_REQUESTED_WITH="fetch")
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": "paris"}}


def test_check_persists_fillblank_list_envelope(client):
    from courses.models import Blank

    student, course, unit = _enrolled(client)
    obj = FillBlankQuestionElement.objects.create(stem="Cap is {{paris}}.")
    Blank.objects.create(question=obj, order=1, accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"blank": ["paris"]})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": ["paris"]}}


def test_check_persists_shortnumeric_envelope(client):
    student, course, unit = _enrolled(client)
    obj = ShortNumericQuestionElement.objects.create(stem="Q", value=42, tolerance=0)
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "42"})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": "42"}}


def test_check_persists_choice_sorted_pk_list(client):
    student, course, unit = _enrolled(client)
    obj = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    c1 = Choice.objects.create(question=obj, text="a", is_correct=True)
    c2 = Choice.objects.create(question=obj, text="b", is_correct=True)
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"choice": [str(c2.pk), str(c1.pk)]})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": sorted([c1.pk, c2.pk])}}


def test_empty_answer_deletes_key(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"answer": "paris"}}
    )
    client.post(_check_url(unit, row.pk), {"answer": "   "})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(row.pk) not in up.element_state


def test_deferred_type_persists_nothing(client):
    student, course, unit = _enrolled(client)
    obj = MatchPairQuestionElement.objects.create(stem="Q")
    row = _add(unit, obj)
    # POST a NON-empty answer for the deferred type: MatchPair.build_answer is
    # post.getlist("slot") (models.py:1761), so {"slot": ["x"]} yields ["x"], not
    # empty. This matters for falsification — with the scope gate deleted, an empty
    # answer would still hit the delete branch and store nothing (false GREEN); a
    # non-empty one takes the store branch and a row appears (true RED).
    resp = client.post(_check_url(unit, row.pk), {"slot": ["x"]})
    assert resp.status_code == 200  # isolate the scope-gate signal from any mark() error
    assert not UnitProgress.objects.filter(student=student, unit=unit).exists()


def test_nojs_path_also_persists(client):
    # No X-Requested-With header -> the no-JS full-page re-render path.
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "paris"})  # no fetch header
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"answer": "paris"}}
```

> `Choice`'s FK to the question is `question` (related_name `choices`), verified against `courses/models.py:1542`. The assertion shape (`{"answer": sorted pks}`) is what matters.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k "persists or deletes or deferred or nojs"`
Expected: FAIL because **no `element_state` is written** (assertion on `up.element_state` / `UnitProgress` fails) — `check_answer` persists nothing today. Confirm the failure is that assertion, NOT a `TypeError`/`NoReverseMatch`/collection error (which would mean a fixture identifier is wrong, not that the guard is being exercised) before implementing.

- [ ] **Step 3: Insert the save into `check_answer`**

In `courses/views.py`, in `check_answer`, immediately after:

```python
    answer = question.build_answer(request.POST)
    result = question.mark(answer)  # NOTHING is persisted
```

add:

```python
    if getattr(question, "RESTORABLE_IN_LESSON", False):
        # Practice-state (slice 3): persist the answer only — never the verdict; it
        # is re-marked on restore. Empty answer clears any prior stored answer.
        if answer_is_empty(answer):
            save_element_state(request.user, node, element.pk, None)
        else:
            save_element_state(
                request.user, node, element.pk, {"answer": answer_to_json(answer)}
            )
```

(Remove the now-stale `# NOTHING is persisted` comment.) This sits before the `_wants_fragment` branch, so it runs for BOTH the JS-fragment and no-JS response paths.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_question_restore.py -q`
Expected: PASS.

- [ ] **Step 5: Add + verify the reset-clears test**

`progress_reset` already wipes `element_state` wholesale; pin it. Append:

```python
def test_start_fresh_clears_question_blob(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = _add(unit, obj)
    client.post(_check_url(unit, row.pk), {"answer": "paris"})
    assert UnitProgress.objects.get(student=student, unit=unit).element_state
    client.post(reverse("courses:progress_reset", kwargs={"slug": course.slug, "node_pk": unit.pk}))
    up = UnitProgress.objects.filter(student=student, unit=unit).first()
    assert not (up and up.element_state.get(str(row.pk)))
```

> Verify the `progress_reset` URL name + args against `courses/urls.py` and adjust kwargs if needed (there is a unit-level reset route). If reset requires a confirmation POST field, include it.

Run: `uv run pytest courses/tests/test_question_restore.py -q -k start_fresh` → PASS.

- [ ] **Step 6: Falsify the scope gate**

Temporarily delete the `if getattr(question, "RESTORABLE_IN_LESSON", False):` wrapper (persist unconditionally). Re-run `-k deferred` → `test_deferred_type_persists_nothing` must FAIL. Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/views.py courses/tests/test_question_restore.py
git commit -m "feat(question-restore): persist answer envelope on lesson check (both paths)"
```

---

### Task 4: Restore seam in `render_element`

**Files:**
- Modify: `courses/templatetags/courses_extras.py` — the `isinstance(obj, QuestionElement)` branch of `render_element` (~lines 47-63).
- Test: `courses/tests/test_question_restore.py` (append).

**Interfaces:**
- Consumes: `RESTORABLE_IN_LESSON` (Task 1); the int-keyed `element_state` context map (`build_lesson_context`); `rehydrate`, `answer_from_json` (from `courses.quiz`, imported lazily inside the branch).
- Produces: on a lesson full-page render, an in-scope question with a stored `{"answer": …}` blob renders refilled + re-marked (as if `feedback_for_pk == element.pk`), unless it is the live-checked element.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_question_restore.py` (note the `import re` at the top — the restore-choice test uses it):

```python
import re


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _seed(unit, student, obj, blob):
    row = Element.objects.create(unit=unit, content_object=obj)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): blob}
    )
    return row


def test_restore_shorttext_fills_value_and_verdict(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    _seed(unit, student, obj, {"answer": "paris"})
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="paris"' in body
    assert "question__verdict is-correct" in body


def test_restore_choice_checks_inputs(client):
    student, course, unit = _enrolled(client)
    obj = ChoiceQuestionElement.objects.create(stem="Q", multiple=False)
    c1 = Choice.objects.create(question=obj, text="a", is_correct=True)
    Choice.objects.create(question=obj, text="b", is_correct=False)
    _seed(unit, student, obj, {"answer": [c1.pk]})
    body = client.get(_lesson_url(unit)).content.decode()
    # the correct choice's radio is checked
    assert re.search(rf'value="{c1.pk}"[^>]*checked', body) or re.search(
        rf'checked[^>]*value="{c1.pk}"', body
    )


def test_restore_extendedresponse_incorrect_shows_guide_not_keywords(client):
    student, course, unit = _enrolled(client)
    obj = ExtendedResponseQuestionElement.objects.create(
        stem="Q", required_keywords="mitochondria"
    )
    _seed(unit, student, obj, {"answer": "totally unrelated text"})
    body = client.get(_lesson_url(unit)).content.decode()
    assert "totally unrelated text" in body  # textarea refilled
    assert "question__reveal-guide" in body  # no-JS neutral guide
    assert "question__reveal-keywords" not in body  # NOT the per-keyword list


def test_corrupt_blob_is_fail_open(client):
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    _seed(unit, student, obj, {"answer": {"unexpected": "dict-not-a-str"}})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    assert 'value="paris"' not in resp.content.decode()  # rendered un-restored


def test_deferred_hand_forged_blob_does_not_restore(client):
    student, course, unit = _enrolled(client)
    obj = MatchPairQuestionElement.objects.create(stem="Q")
    _seed(unit, student, obj, {"answer": [[0, 1]]})
    resp = client.get(_lesson_url(unit))
    assert resp.status_code == 200
    # Un-restored: the feedback partial is included only when element.pk ==
    # feedback_for_pk (matchpairquestionelement.html:19). A restored deferred blob
    # would emit a verdict; assert none — this is what goes RED if the restore-side
    # scope gate is deleted.
    assert "question__verdict" not in resp.content.decode()


def test_restore_shortnumeric_fills_value(client):
    student, course, unit = _enrolled(client)
    obj = ShortNumericQuestionElement.objects.create(stem="Q", value=42, tolerance=0)
    _seed(unit, student, obj, {"answer": "42"})
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="42"' in body
    assert "question__verdict is-correct" in body


def test_restore_fillblank_fills_each_blank(client):
    # One blank accepting "paris"; the {{...}} token in the stem marks the gap
    # (Blank.accepted is parsed from {{a|b}}, courses/models.py:1679).
    from courses.models import Blank

    student, course, unit = _enrolled(client)
    obj = FillBlankQuestionElement.objects.create(stem="The capital is {{paris}}.")
    Blank.objects.create(question=obj, order=1, accepted="paris")
    _seed(unit, student, obj, {"answer": ["paris"]})
    body = client.get(_lesson_url(unit)).content.decode()
    assert 'value="paris"' in body  # the blank input is refilled with the stored value
    assert "question__verdict is-correct" in body


def test_editor_preview_does_not_restore(client):
    # Guard 4 (absent element_state) is the SOLE exclusion for the editor preview,
    # which renders in mode="lesson". Render the author's preview of a unit that has
    # a stored answer FOR ANOTHER STUDENT; the preview context carries no
    # element_state, so nothing restores.
    author = make_student(client, "qr_author")
    course, unit = make_course_with_unit(owner=author)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = Element.objects.create(unit=unit, content_object=obj)
    other = make_verified_user()
    UnitProgress.objects.create(
        student=other, unit=unit, element_state={str(row.pk): {"answer": "paris"}}
    )
    # The editor｜preview page (courses/urls.py:207); its kwarg is `pk`, not node_pk.
    preview_url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    body = client.get(preview_url).content.decode()
    assert 'value="paris"' not in body  # author preview never restores another user's answer
```

> `Blank` (FK `question`, related_name `blanks`) and the `manage_editor` route (kwarg `pk`) are verified against `courses/models.py:1679` and `courses/urls.py:207`. If `render_fill_blanks` needs the gap token in a specific form, confirm the `{{paris}}` stem emits an `<input name="blank">` (courses/fillblank.py); keep the asserted behavior (refilled `value="paris"` / no restore in preview). The editor page may require the author to be logged in with build access — reuse whatever login the existing editor tests use if `make_student` is insufficient.

> Adjust `required_keywords` / `Choice` field names to the real schema if they differ; keep the asserted markers (`question__reveal-guide`, `value="paris"`, `checked`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k restore`
Expected: FAIL because **inputs render blank / verdict absent** (the body assertions fail) — the question branch ignores `element_state` today. Confirm each failure is the missing-value assertion, NOT a `TypeError`/`NoReverseMatch`/import error, before implementing.

- [ ] **Step 3: Add the restore block**

In `courses/templatetags/courses_extras.py`, replace the `QuestionElement` branch:

```python
    if isinstance(obj, QuestionElement):
        return mark_safe(  # noqa: S308 — templates escape user text; correctness never leaks
            obj.render(
                element=element,
                feedback_for_pk=feedback_for_pk,
                selected_ids=selected_ids,
                submitted_values=submitted_values,
                mark_result=mark_result,
                mode=mode,
                action_url=action_url,
                feedback_partial=feedback_partial,
                quiz_submitted=quiz_submitted,
                locked=locked,
                attempts_left=attempts_left,
                feedback_html=feedback_html,
            )
        )
```

with:

```python
    if isinstance(obj, QuestionElement):
        # Practice-state restore (lesson full-page render only): if this in-scope
        # question has a stored answer and is NOT the element being checked live,
        # refill + re-mark it server-side. The live-checked element (feedback_for_pk)
        # keeps its live answer. The context element_state map is INT-keyed.
        if (
            mode == "lesson"
            and getattr(obj, "RESTORABLE_IN_LESSON", False)
            and element.pk != feedback_for_pk
        ):
            blob = (context.get("element_state") or {}).get(element.pk)
            if isinstance(blob, dict) and "answer" in blob:
                try:
                    from courses.quiz import answer_from_json, rehydrate

                    stored = blob["answer"]
                    r_selected, r_submitted = rehydrate(obj, stored)
                    r_result = obj.mark(answer_from_json(obj, stored))
                except Exception:
                    pass  # fail-open: fall through to the un-restored render
                else:
                    selected_ids = r_selected
                    submitted_values = r_submitted
                    mark_result = r_result
                    feedback_for_pk = element.pk
        return mark_safe(  # noqa: S308 — templates escape user text; correctness never leaks
            obj.render(
                element=element,
                feedback_for_pk=feedback_for_pk,
                selected_ids=selected_ids,
                submitted_values=submitted_values,
                mark_result=mark_result,
                mode=mode,
                action_url=action_url,
                feedback_partial=feedback_partial,
                quiz_submitted=quiz_submitted,
                locked=locked,
                attempts_left=attempts_left,
                feedback_html=feedback_html,
            )
        )
```

The `try` wraps only the data-prep; `obj.render(...)` is the single existing call after it. Overrides are committed only in the `else` (full success), so a mid-prep exception leaves every kwarg at its default (fully un-restored).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_question_restore.py -q -k restore`
Expected: PASS (all restore cases, including fail-open and deferred-no-restore).

- [ ] **Step 5: Add the live-wins-over-stale-blob test**

Append and run:

```python
def test_live_check_wins_over_stale_blob_nojs(client):
    # No-JS check re-render: the just-checked element uses the LIVE answer, other
    # answered elements restore from their blob.
    student, course, unit = _enrolled(client)
    obj = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    row = Element.objects.create(unit=unit, content_object=obj)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"answer": "STALE"}}
    )
    body = client.post(_check_url(unit, row.pk), {"answer": "paris"}).content.decode()
    assert 'value="paris"' in body and "STALE" not in body
```

Run: `uv run pytest courses/tests/test_question_restore.py -q -k live_check_wins` → PASS.

- [ ] **Step 6: Falsify C1 (int-key) and the live-wins guard**

- Change `.get(element.pk)` to `.get(str(element.pk))`; re-run `-k restore_shorttext` → FAIL (misses the int-keyed map). Revert.
- Delete the `element.pk != feedback_for_pk` condition; re-run `-k live_check_wins` → FAIL (STALE overrides the live answer). Revert.
- Delete the `getattr(obj, "RESTORABLE_IN_LESSON", False)` condition; re-run `-k deferred_hand_forged` → FAIL (the forged deferred blob restores and emits `question__verdict`). Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_extras.py courses/tests/test_question_restore.py
git commit -m "feat(question-restore): server-side restore in render_element (int-key, fail-open)"
```

---

### Task 5: Check-button consistency + real-UI e2e

**Files:**
- Modify: `courses/static/courses/js/question.js` — add a boot pass hiding the Check button on already-correct questions, scoped to forms.
- Test: an e2e under the project's Playwright e2e suite (mirror an existing lesson e2e file; `courses/tests/e2e/` or wherever `-m e2e` tests live).

**Interfaces:**
- Consumes: the restore render from Task 4 (a restored-correct question shows `.question__verdict.is-correct` on load).
- Produces: on load, any question with a live form AND a `.question__verdict.is-correct` has its submit button hidden; form-less blocks (results/review pages) are untouched.

- [ ] **Step 1: Add the boot pass**

In `courses/static/courses/js/question.js`, inside the IIFE, after the existing `questions.forEach(function (q) { ... })` submit-wiring loop, add:

```javascript
  // Boot pass: a restored (or server-rendered) correct answer already shows its
  // verdict; hide its Check/Submit button so it matches the post-fetch behavior.
  // Scoped to questions that HAVE a form (results/review pages render form-less
  // [data-question] blocks and must be untouched).
  questions.forEach(function (q) {
    var form = q.querySelector("form");
    if (!form) return;
    if (form.querySelector(".question__verdict.is-correct")) {
      var btn = form.querySelector("button[type='submit'], input[type='submit']");
      if (btn) btn.hidden = true;
    }
  });
```

- [ ] **Step 2: Write the e2e (real UI: answer → reload → assert)**

Create an e2e (model it on an existing lesson e2e for setup/login/URL helpers). Drive the ACTUAL gesture — never `page.evaluate` to fake the answer:

```python
# Pseudocode outline — adapt to the repo's e2e harness (LiveServer + Playwright).
# 1. Build a lesson unit with one ShortTextQuestionElement (accepted="paris").
# 2. Log in as an enrolled student; navigate to the lesson unit page.
# 3. Fill the answer input with "paris" and click the real Check button.
#    await page.expect_response(<check_answer url>) so the fire-and-forget save
#    lands before reload.
# 4. Reload the page.
# 5. Assert: the input value is "paris", the verdict shows is-correct, AND the
#    Check button is hidden (not visible).
# 6. Second case: answer "wrong", check, reload -> answer shown, verdict
#    is-incorrect, Check button STILL visible.
```

- [ ] **Step 3: Run the e2e**

Run the focused e2e file only (foreground), e.g.:
`uv run pytest courses/tests/e2e/test_question_restore_e2e.py -q`
Expected: PASS. (Run focused, not the whole `-m e2e` suite, to avoid runaway browsers.)

- [ ] **Step 4: Falsify the boot pass**

Comment out the boot-pass block; re-run the e2e → the "Check hidden after reload" assertion must FAIL. Restore.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/question.js courses/tests/e2e/test_question_restore_e2e.py
git commit -m "feat(question-restore): hide Check on restored-correct questions; real-UI e2e"
```

---

## Definition of Done

- [ ] Full non-e2e suite green: `uv run pytest -n auto -m "not e2e"` (exit 0, 0 failures). Run at every red-window boundary, not just here.
- [ ] Focused e2e green (foreground): the new question-restore e2e, plus a smoke of `test_element_state_endpoint.py` and any existing question/quiz e2e touched.
- [ ] `uv run ruff check .` and `uv run ruff format --check .` clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`.
- [ ] `uv run python manage.py check` clean.
- [ ] Every falsification step above performed (guard deleted → RED → restored) at least once during development.
