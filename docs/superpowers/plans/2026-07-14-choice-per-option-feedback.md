# Per-choice feedback for ChoiceQuestionElement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let authors attach an optional feedback nudge to individual MCQ choices, shown when a student picks that distractor in a wrong answer.

**Architecture:** Enhance the existing `ChoiceQuestionElement` — no new element type. Add `Choice.feedback`; carry the pks-to-nudge on `MarkResult.nudged` (a `frozenset`, same type family as `reveal`, computed in `mark()`); the reveal template reads `c.feedback` for pks in `nudged` via a plain membership test. Marking is unchanged (exact set-equality). All three render paths (lesson fragment, quiz reload/no-JS, results) reconcile because they all route through `mark()`.

**Tech Stack:** Django 5.2, server-rendered templates, pytest, uv-run tooling, EN/PL i18n.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-14-choice-per-option-feedback-design.md`.
- Run tooling via **`uv run`** (ruff/pytest/python are not on PATH). DoD per task: `uv run ruff check --fix . && uv run ruff format .`, `uv run python manage.py makemigrations --check`, `uv run python manage.py check`, and the task's tests.
- `MarkResult` is a `@dataclass(frozen=True)` — the new field MUST be immutable/hashable (`frozenset`), never a `dict`.
- Marking semantics unchanged: exact set-equality; `nudged` is presentational only, never affects `correct`/`fraction`.
- Display rule: a choice nudges **iff** it was selected, is a distractor (`not is_correct`), AND the overall submission was wrong.
- No-leak: nudges ride `mark_result`; the reveal block is already gated to locked/marked in quiz. A pre-lock quiz fragment must contain no nudge.
- `Choice.feedback` = `CharField(max_length=500, blank=True, default="")` — `default=""` is required to keep `makemigrations` non-interactive.
- No new element type: do NOT touch `ELEMENT_MODELS`, `_add_menu.html`, `FORM_FOR_TYPE`, `save_element`, `NESTABLE_TYPE_KEYS`, `_ELEMENT_LABELS`, `element_summary`.
- i18n: both new strings (`"Feedback (optional)"` and `_("choice feedback")`) need a Polish `msgstr`.

---

### Task 1: Data foundations — `Choice.feedback` + `MarkResult.nudged` + migration

**Files:**
- Modify: `courses/models.py` (the `Choice` model)
- Modify: `courses/marking.py` (the `MarkResult` dataclass)
- Create: `courses/migrations/00XX_choice_feedback.py` (via makemigrations)
- Test: `tests/test_questions_models.py`

**Interfaces:**
- Produces: `Choice.feedback: str` (blank default `""`); `MarkResult.nudged: frozenset` (default empty). Later tasks consume both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_questions_models.py`:

```python
@pytest.mark.django_db
def test_choice_feedback_defaults_blank():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    c = Choice.objects.create(question=q, text="A", is_correct=True)
    assert c.feedback == ""  # default="" — no interactive migration prompt
    c.feedback = "Are you sure?"
    c.save()
    assert Choice.objects.get(pk=c.pk).feedback == "Are you sure?"


def test_markresult_nudged_defaults_empty_and_hashable():
    # nudged defaults to an empty frozenset and MarkResult stays hashable
    # (frozen=True + a frozenset field; a dict field would raise on hash()).
    r = MarkResult(correct=False, fraction=0.0, reveal=frozenset())
    assert r.nudged == frozenset()
    assert isinstance(hash(r), int)
    r2 = MarkResult(correct=False, fraction=0.0, reveal=frozenset(), nudged=frozenset({1, 2}))
    assert r2.nudged == frozenset({1, 2})
    assert isinstance(hash(r2), int)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_questions_models.py::test_choice_feedback_defaults_blank tests/test_questions_models.py::test_markresult_nudged_defaults_empty_and_hashable -v`
Expected: FAIL (`Choice` has no `feedback`; `MarkResult.__init__` got unexpected `nudged`).

- [ ] **Step 3: Add the `MarkResult.nudged` field + docstring**

In `courses/marking.py`, extend the dataclass (keep `frozen=True`):

```python
@dataclass(frozen=True)
class MarkResult:
    """The normalized result every question type's mark() returns.

    `reveal` is a per-type, type-opaque presentation payload consumed by the
    feedback template. For ChoiceQuestionElement it is a frozenset[int] of the
    correct choice ids. `nudged` is a second per-type presentation payload: for
    ChoiceQuestionElement, the frozenset[int] of choice ids whose per-choice
    feedback should be shown (selected distractors on a wrong answer); empty for
    every other type.
    """

    correct: bool
    fraction: float
    reveal: frozenset = frozenset()
    nudged: frozenset = frozenset()
```

- [ ] **Step 4: Add the `Choice.feedback` field**

In `courses/models.py`, in the `Choice` model, add below `text`:

```python
    feedback = models.CharField(max_length=500, blank=True, default="")
```

- [ ] **Step 5: Make the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/00XX_choice_feedback.py` adding `feedback`, with NO interactive prompt (because `default=""`).

- [ ] **Step 6: Run tests + DoD**

Run: `uv run pytest tests/test_questions_models.py -v` → PASS
Run: `uv run python manage.py makemigrations --check` → clean
Run: `uv run ruff check --fix . && uv run ruff format .` → clean

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/marking.py courses/migrations/ tests/test_questions_models.py
git commit -m "feat(choice): add Choice.feedback + MarkResult.nudged foundations"
```

---

### Task 2: `mark()` computes `nudged`

**Files:**
- Modify: `courses/models.py` (`ChoiceQuestionElement.mark`)
- Test: `tests/test_questions_models.py`

**Interfaces:**
- Consumes: `Choice.feedback`, `MarkResult.nudged` (Task 1).
- Produces: `ChoiceQuestionElement.mark(answer).nudged` — frozenset of selected-distractor pks with feedback, on a wrong answer only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_questions_models.py`:

```python
@pytest.mark.django_db
def test_mark_nudged_selected_distractor_on_wrong():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True, feedback="")
    bad = Choice.objects.create(question=q, text="B", is_correct=False, feedback="Not quite")

    # wrong answer selecting the annotated distractor -> its pk is nudged
    assert q.mark({bad.pk}).nudged == frozenset({bad.pk})
    # correct answer -> nothing nudged
    assert q.mark({good.pk}).nudged == frozenset()


@pytest.mark.django_db
def test_mark_nudged_excludes_blank_and_unselected():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True)
    bad_blank = Choice.objects.create(question=q, text="B", is_correct=False, feedback="")
    bad_annot = Choice.objects.create(question=q, text="C", is_correct=False, feedback="hint")

    # selected a blank-feedback distractor -> nothing to nudge
    assert q.mark({bad_blank.pk}).nudged == frozenset()
    # an annotated distractor the student did NOT select -> not nudged
    assert bad_annot.pk not in q.mark({bad_blank.pk}).nudged


@pytest.mark.django_db
def test_mark_nudged_multi_excludes_selected_correct_pick():
    # multiple-choice: overall-wrong but the student selected an annotated CORRECT
    # choice -> that correct choice does NOT nudge (only selected distractors do).
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=True)
    c_ok = Choice.objects.create(question=q, text="A", is_correct=True, feedback="good one")
    c_ok2 = Choice.objects.create(question=q, text="B", is_correct=True)
    c_bad = Choice.objects.create(question=q, text="C", is_correct=False, feedback="nope")

    # selected one correct + one distractor -> overall wrong; only c_bad nudges
    res = q.mark({c_ok.pk, c_bad.pk})
    assert res.correct is False
    assert res.nudged == frozenset({c_bad.pk})  # c_ok excluded despite feedback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_questions_models.py -k nudged -v`
Expected: FAIL (`mark()` returns `nudged == frozenset()` always — the distractor case fails).

- [ ] **Step 3: Rewrite `mark()` to compute `nudged`**

In `courses/models.py`, replace `ChoiceQuestionElement.mark`:

```python
    def mark(self, answer):
        # `answer` is an already-validated set of this question's choice ids.
        # Single source of choices for both the correct-set and the nudge-set
        # (one query; choices are prefetched on the quiz/results builders).
        choices = list(self.choices.all())
        correct_set = frozenset(c.pk for c in choices if c.is_correct)
        is_correct = set(answer) == set(correct_set)
        # nudge = selected DISTRACTORS (not correct) carrying feedback, only on a
        # wrong answer. `not c.is_correct` is load-bearing for multiple-choice:
        # a selected annotated *correct* choice in an overall-wrong submission
        # must stay quiet (Display rule).
        nudged = (
            frozenset(
                c.pk
                for c in choices
                if c.pk in answer and c.feedback and not c.is_correct
            )
            if not is_correct
            else frozenset()
        )
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=correct_set,
            nudged=nudged,
        )
```

Note: `correct_ids()` is left in place (still used elsewhere); `mark()` now derives the correct set inline to avoid a second `self.choices` query.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_questions_models.py -v` → PASS (existing set-equality tests still green — `reveal` unchanged).

- [ ] **Step 5: DoD + Commit**

Run: `uv run ruff check --fix . && uv run ruff format .` → clean

```bash
git add courses/models.py tests/test_questions_models.py
git commit -m "feat(choice): mark() computes nudged selected-distractor pks"
```

---

### Task 3: Reveal template renders the nudge + `.question__nudge` styling

**Files:**
- Modify: `templates/courses/elements/_reveal_choice.html`
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_render_choice_nudge.py` (create)

**Interfaces:**
- Consumes: `mark_result.nudged` (Task 2), `choices` in template context, `c.feedback`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_choice_nudge.py`:

```python
import pytest
from django.template.loader import render_to_string

from courses.marking import MarkResult


@pytest.mark.django_db
def test_reveal_choice_shows_nudge_for_nudged_choice_only():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True)
    bad = Choice.objects.create(question=q, text="B", is_correct=False, feedback="Re-read step 2")

    choices = list(q.choices.all())
    mark_result = MarkResult(
        correct=False, fraction=0.0, reveal=frozenset({good.pk}), nudged=frozenset({bad.pk})
    )
    html = render_to_string(
        "courses/elements/_reveal_choice.html",
        {"choices": choices, "mark_result": mark_result},
    )
    assert "Re-read step 2" in html          # nudge shown for the mis-picked distractor
    assert "question__nudge" in html          # rendered in the dedicated element
    # correct-tick behaviour unchanged: the correct choice still gets its marker
    assert "answer-correct" in html


@pytest.mark.django_db
def test_reveal_choice_no_nudge_when_none():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False, feedback="hidden hint")

    choices = list(q.choices.all())
    mark_result = MarkResult(
        correct=True, fraction=1.0, reveal=frozenset({good.pk}), nudged=frozenset()
    )
    html = render_to_string(
        "courses/elements/_reveal_choice.html",
        {"choices": choices, "mark_result": mark_result},
    )
    assert "hidden hint" not in html          # empty nudged -> no nudge leaks
    assert "question__nudge" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_choice_nudge.py -v`
Expected: FAIL (`Re-read step 2` / `question__nudge` not in output).

- [ ] **Step 3: Edit the reveal template**

Replace `templates/courses/elements/_reveal_choice.html` with:

```django
{% load i18n %}
<ul class="question__reveal">
  {% for c in choices %}
    <li class="question__reveal-item {% if c.pk in mark_result.reveal %}answer-correct{% endif %}">
      <span>{{ c.text }}</span>
      {% if c.pk in mark_result.reveal %}<span class="question__tick" aria-hidden="true">✓</span>{% endif %}
      {% if c.pk in mark_result.nudged %}
        <p class="question__nudge">{{ c.feedback }}</p>
      {% endif %}
    </li>
  {% endfor %}
</ul>
```

Only a membership test (`c.pk in mark_result.nudged`) and attribute access (`c.feedback`) are used — no custom filter.

- [ ] **Step 4: Add `.question__nudge` CSS**

In `courses/static/courses/css/courses.css`, near the existing `.question__reveal` rules, add a muted, indented aside distinct from the ✓ reveal. Use the repo's existing muted-text token **`--text-tertiary`** (already used throughout `courses.css`, e.g. `.rollup`) — NOT a hardcoded colour or a `var(..., #666)` fallback (a fallback would silently mask a wrong token name):

```css
.question__nudge {
  margin: 0.25rem 0 0 1.25rem;
  font-size: 0.9em;
  color: var(--text-tertiary);
  font-style: italic;
}
```

- [ ] **Step 5: Run test + DoD**

Run: `uv run pytest tests/test_render_choice_nudge.py -v` → PASS
Run: `uv run ruff check --fix . && uv run ruff format .` → clean

- [ ] **Step 6: Visual check (manual, before shipping)**

Note for the reviewer/controller: screenshot the nudge on a lesson choice question in light + dark and confirm it reads as a subordinate aside (per spec §3). Not an automated gate; record the observation.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/elements/_reveal_choice.html courses/static/courses/css/courses.css tests/test_render_choice_nudge.py
git commit -m "feat(choice): render per-choice feedback nudge in reveal + style"
```

---

### Task 4: Quiz reload / results carry — `_stored_result` threads `nudged`

**Files:**
- Modify: `courses/views.py` (`_stored_result`)
- Test: `tests/test_choice_nudge_paths.py` (create)

**Interfaces:**
- Consumes: `MarkResult.nudged` (Task 2), the reveal template (Task 3).
- Produces: `_stored_result(question, response).nudged` populated from the live `mark()` call.

- [ ] **Step 1: Write the failing test**

Create `tests/test_choice_nudge_paths.py` with a `_stored_result` unit test. `_stored_result` covers the quiz **reload / no-JS re-render**; the **results page** independently re-derives `nudged` via `_results_row` → `mark()` (Step 5 pins that path separately):

```python
import pytest
from decimal import Decimal


@pytest.mark.django_db
def test_stored_result_carries_nudged():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.views import _stored_result

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    good = Choice.objects.create(question=q, text="A", is_correct=True)
    bad = Choice.objects.create(question=q, text="B", is_correct=False, feedback="hint B")

    # a minimal stand-in for QuestionResponse: latest_answer is what the student
    # submitted (the distractor), fraction is the frozen wrong score.
    class _Resp:
        latest_answer = [bad.pk]      # answer_from_json for choice -> set of pks
        fraction = Decimal("0.0000")

    res = _stored_result(q, _Resp())
    assert res.nudged == frozenset({bad.pk})   # nudge survives the rebuild
    assert res.correct is False
```

If `answer_from_json` for choice expects a different shape than `[bad.pk]`, mirror the exact shape used by the existing `test_stored_result`-adjacent tests (grep `answer_from_json` in `courses/`); adjust `latest_answer` accordingly. The assertion on `.nudged` is the point.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_choice_nudge_paths.py -v`
Expected: FAIL (`res.nudged == frozenset()` — `_stored_result` drops it).

- [ ] **Step 3: Thread `nudged` through `_stored_result`**

In `courses/views.py`, replace `_stored_result`:

```python
def _stored_result(question, response):
    # MarkResult + answer_from_json imported at views.py top.
    m = question.mark(answer_from_json(question, response.latest_answer))
    return MarkResult(
        correct=(response.fraction == Decimal("1.0000")),
        fraction=float(response.fraction or 0),
        reveal=m.reveal,
        nudged=m.nudged,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_choice_nudge_paths.py -v` → PASS

- [ ] **Step 5: Add the no-leak + results integration assertions**

Append to `tests/test_choice_nudge_paths.py`. Choice has **no** non-e2e withhold test yet, so adapt the dragfill pattern in `tests/test_questions_2d_quiz_noleak.py` (enrolled student + `make_quiz_unit` + `/quiz/q/<el>/answer/` POST). Ensure these imports are present at the top of the file:

```python
from decimal import Decimal

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit
```

**No-leak test** (the load-bearing safety property — the nudge must NOT appear before lock):

```python
@pytest.mark.django_db
def test_choice_nudge_withheld_prelock_then_revealed(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", multiple=False, marking_mode="A", max_attempts=2
    )
    Choice.objects.create(question=q, text="A", is_correct=True)
    bad = Choice.objects.create(question=q, text="B", is_correct=False, feedback="NUDGE-B")
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"

    # Wrong, 1 attempt remaining -> withhold: the nudge must NOT render.
    body1 = client.post(
        url, {"choice": [str(bad.pk)]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "NUDGE-B" not in body1
    assert "question__reveal" not in body1

    # Wrong on the LAST attempt -> reveal: the nudge is now shown.
    body2 = client.post(
        url, {"choice": [str(bad.pk)]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "NUDGE-B" in body2
```

**Results-page test** (the third render path, `_results_row` → `_reveal_choice.html`; build the persisted wrong response directly, mirroring `tests/test_quiz_results_render.py`):

```python
@pytest.mark.django_db
def test_choice_nudge_on_results_page(client):
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_login(client, "stu")
    course = CourseFactory(slug="rc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="NUDGE-B", order=1
    )
    el = Element.objects.create(unit=unit, content_object=q)
    sub = QuizSubmission.objects.create(
        student=user, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    # a wrong, locked response selecting the annotated distractor
    QuestionResponse.objects.create(
        submission=sub, element=el, attempt_count=1,
        latest_answer=[bad.pk], fraction=Decimal("0.0000"), locked=True,
    )
    url = reverse("courses:quiz_results", kwargs={"slug": course.slug, "node_pk": unit.pk})
    body = client.get(url).content.decode()
    assert "NUDGE-B" in body   # nudge rendered on the results reveal
```

If the `/answer/` URL shape or `make_quiz_unit` differ, verify against `tests/test_questions_2d_quiz_noleak.py` (same fixtures) and adjust only the literal URL.

- [ ] **Step 6: Run all + DoD**

Run: `uv run pytest tests/test_choice_nudge_paths.py -v` → PASS
Run: `uv run ruff check --fix . && uv run ruff format .` → clean

- [ ] **Step 7: Commit**

```bash
git add courses/views.py tests/test_choice_nudge_paths.py
git commit -m "feat(choice): carry nudged through quiz reload/results via _stored_result"
```

---

### Task 5: Editor — feedback input on each choice row

**Files:**
- Modify: `courses/element_forms.py` (`ChoiceFormSet` / `inlineformset_factory`)
- Modify: `templates/courses/manage/editor/_edit_choicequestion.html`
- Test: `tests/test_questions_authoring.py`

**Interfaces:**
- Consumes: `Choice.feedback` (Task 1).
- Produces: the editor persists `Choice.feedback` from `choices-<i>-feedback` POST fields.

- [ ] **Step 1: Write the failing test**

In `tests/test_questions_authoring.py`, extend `_save_payload` to accept optional feedback and add a round-trip test. Change the helper signature and loop:

```python
def _save_payload(unit, *, multiple, rows, element="new"):
    """rows: list of (text, correct_bool) OR (text, correct_bool, feedback)."""
    data = {
        "ctx": "editor",
        "type": "choicequestion",
        "element": element,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "stem": "<p>Pick</p>",
        "explanation": "",
        "multiple": "True" if multiple else "False",
        "choices-TOTAL_FORMS": str(len(rows)),
        "choices-INITIAL_FORMS": "0",
        "choices-MIN_NUM_FORMS": "0",
        "choices-MAX_NUM_FORMS": "1000",
    }
    for i, row in enumerate(rows):
        text, correct = row[0], row[1]
        feedback = row[2] if len(row) > 2 else ""
        data[f"choices-{i}-text"] = text
        data[f"choices-{i}-feedback"] = feedback
        if correct:
            data[f"choices-{i}-is_correct"] = "on"
    return data
```

Add the test:

```python
@pytest.mark.django_db
def test_save_persists_choice_feedback(client):
    from tests.factories import make_pa
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _save_payload(
            unit, multiple=False,
            rows=[("4", True), ("5", False, "Check your arithmetic")],
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ChoiceQuestionElement.objects.get()
    distractor = q.choices.get(text="5")
    assert distractor.feedback == "Check your arithmetic"
    assert q.choices.get(text="4").feedback == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_authoring.py::test_save_persists_choice_feedback -v`
Expected: FAIL (feedback not saved — field absent from the formset).

- [ ] **Step 3: Add `feedback` to the choice formset with a Textarea widget**

In `courses/element_forms.py`, update the `inlineformset_factory` call for choices:

```python
ChoiceFormSet = inlineformset_factory(
    ChoiceQuestionElement,
    Choice,
    formset=BaseChoiceFormSet,
    fields=["text", "is_correct", "feedback"],
    widgets={"feedback": forms.Textarea(attrs={"rows": 2, "maxlength": 500})},
    extra=2,
    can_delete=True,
)
```

(`forms` is already imported at the top of `element_forms.py`.) `Textarea` does not emit `maxlength` on its own, so the explicit attr mirrors the server cap client-side.

- [ ] **Step 4: Add the feedback input to the editor row**

In `templates/courses/manage/editor/_edit_choicequestion.html`, inside the `<li class="choice-row" ...>` loop, after the `choice-row__text` span, add:

```django
        <label class="choice-row__feedback">
          <span class="el-editor__hint">{% trans "Feedback (optional)" %}</span>
          {{ f.feedback }}
        </label>
```

Render via the auto widget `{{ f.feedback }}` (emits `id_choices-N-feedback`), NOT a hand-built input like `is_correct` — the auto id is what the "Add option" clone regex renumbers and what a `<label>` associates with. (Here the `<label>` wraps the field, so no `for=` is needed; if a non-wrapping label is used instead, it must be `for="{{ f.feedback.id_for_label }}"`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_questions_authoring.py -v` → PASS (existing authoring tests still green — the added `choices-<i>-feedback` blank fields are harmless).

- [ ] **Step 6: Assert the widget id renders (clone-safety)**

Add a lightweight render assertion so the clone-renumber contract is pinned without JS:

```python
@pytest.mark.django_db
def test_editor_renders_feedback_widget_with_id(client):
    from tests.factories import make_pa
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "choice-single", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    # auto widget emits id_choices-<n>-feedback, the anchor editor.js renumbers
    assert b"choices-0-feedback" in resp.content
```

Run: `uv run pytest tests/test_questions_authoring.py::test_editor_renders_feedback_widget_with_id -v` → PASS

- [ ] **Step 7: DoD + Commit**

Run: `uv run ruff check --fix . && uv run ruff format .` → clean

```bash
git add courses/element_forms.py templates/courses/manage/editor/_edit_choicequestion.html tests/test_questions_authoring.py
git commit -m "feat(choice): per-choice feedback input in the editor"
```

---

### Task 6: Transfer — export/validate/import + FORMAT_VERSION bump

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_choice`)
- Modify: `courses/transfer/payloads.py` (`_val_choice`)
- Modify: `courses/transfer/importer.py` (`_build_choice`)
- Modify: `courses/transfer/schema.py` (`FORMAT_VERSION`)
- Modify (fix pinned assertions): `tests/test_tabs_transfer.py`, `tests/test_transfer_schema.py`, `tests/test_transfer_export.py`
- Test: `tests/test_transfer_choice_feedback.py` (create)

**Interfaces:**
- Consumes: `Choice.feedback` (Task 1).
- Produces: choice transfer payloads carry `feedback`; `FORMAT_VERSION == 4`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transfer_choice_feedback.py`:

```python
import pytest

from courses.transfer.export import _ser_choice
from courses.transfer.payloads import _val_choice
from courses.transfer.schema import TransferError


@pytest.mark.django_db
def test_export_includes_feedback():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False, feedback="nope")

    data = _ser_choice(q, {})
    assert data["choices"] == [
        {"text": "A", "is_correct": True, "feedback": ""},
        {"text": "B", "is_correct": False, "feedback": "nope"},
    ]


def _choice_payload(choices):
    return {
        "stem": "q", "explanation": "", "marking_mode": "A",
        "max_attempts": 1, "max_marks": "1.00",
        "multiple": False, "choices": choices,
    }


def test_val_choice_accepts_legacy_without_feedback():
    # v<=3 archives have no feedback key; the setdefault shim adds "" so exact-keys passes.
    # NOTE: >=2 choices with exactly one correct — _val_choice runs `len(choices) < 2`
    # and correct-count guards BEFORE the per-choice shim loop, so a single-choice
    # payload would raise there and never exercise the shim.
    data = _choice_payload(
        [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}]
    )
    _val_choice(data, "el1", {})  # must not raise
    assert data["choices"][0]["feedback"] == ""
    assert data["choices"][1]["feedback"] == ""


def test_val_choice_rejects_overlong_feedback():
    # >=2 valid choices so the raise originates from the feedback length check, NOT the
    # `len(choices) < 2` guard (which would make the test pass for the wrong reason).
    data = _choice_payload(
        [
            {"text": "A", "is_correct": True},
            {"text": "B", "is_correct": False, "feedback": "x" * 501},
        ]
    )
    with pytest.raises(TransferError):
        _val_choice(data, "el1", {})
```

Confirm the exact `Q_KEYS` field names/values (`marking_mode`, `max_attempts`, `max_marks`) against an existing passing choice payload in `tests/test_transfer_validation.py` and copy them verbatim if they differ.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_choice_feedback.py -v`
Expected: FAIL (export lacks `feedback`; `_val_choice` rejects the extra key / lacks the shim).

- [ ] **Step 3: Export the field**

In `courses/transfer/export.py`, `_ser_choice`:

```python
def _ser_choice(el, ids):
    return {
        **_question_fields(el),
        "multiple": el.multiple,
        "choices": [
            {"text": c.text, "is_correct": c.is_correct, "feedback": c.feedback}
            for c in el.choices.all()
        ],
    }
```

- [ ] **Step 4: Validate with the legacy shim**

In `courses/transfer/payloads.py`, `_val_choice`, inside the `for c in choices:` loop, immediately before the per-choice `_exact_keys`:

```python
    for c in choices:
        if isinstance(c, dict):
            c.setdefault("feedback", "")  # v<=3 archives gain the key -> exact-keys passes
        _exact_keys(c, ["text", "is_correct", "feedback"], _("choice"))
        check_str(c["text"], _("choice text"), max_length=500, required=True)
        check_str(c["feedback"], _("choice feedback"), max_length=500)  # required=False default
        check_bool(c["is_correct"], "is_correct")
        n_correct += c["is_correct"]
```

- [ ] **Step 5: Import the field**

In `courses/transfer/importer.py`, `_build_choice`:

```python
    rows = [
        Choice(
            question=q,
            text=c["text"],
            is_correct=c["is_correct"],
            feedback=c["feedback"],
        )
        for c in data["choices"]
    ]
```

- [ ] **Step 6: Bump `FORMAT_VERSION` and fix the pinned assertions**

In `courses/transfer/schema.py`: `FORMAT_VERSION = 4`.

Then update the currently-green assertions that pin `3`:
- `tests/test_tabs_transfer.py`: `test_format_version_is_3` → rename to `test_format_version_is_4` and assert `FORMAT_VERSION == 4`.
- `tests/test_transfer_schema.py`: the `FORMAT_VERSION == 3` assertion → `== 4`.
- `tests/test_transfer_export.py`: the `manifest["format_version"] == 3` assertion → `== 4`; AND `test_choice_question` (~line 115) exact-equality on choice dicts → add `"feedback": ""` to each expected dict.

(Grep `== 3` and `format_version` in `tests/` to be sure none are missed.)

- [ ] **Step 7: Round-trip test (exercises `_build_choice` import)**

The existing full-course round-trip tests in `tests/test_transfer_import.py` already create a `ChoiceQuestionElement` with two choices (~line 171) and import via `_import_zip(buf, user)` (line 55, wrapping `import_course`). Extend that path to prove `feedback` survives export→import:

- In the fixture/builder that creates that `choice_q` (~line 171), add feedback to choice "B": `Choice.objects.create(question=choice_q, text="B", is_correct=False, feedback="keep me")`.
- In `test_full_course_round_trip_graph_equality` (line 274) — or a new sibling test using the same `_import_zip(buf, importer)` helper — after import, fetch the re-imported distractor and assert `imported_choice.feedback == "keep me"`.

If wiring into the shared fixture is awkward, inline a self-contained round-trip in `tests/test_transfer_choice_feedback.py` using `courses.transfer.importer.import_course` + `_import_zip` (import them from `tests.test_transfer_import`), building a one-unit course whose single choice question has a distractor with `feedback="keep me"`, and assert it survives. The point is one assertion that `_build_choice` restored `feedback`.

- [ ] **Step 8: Run everything + DoD**

Run: `uv run pytest tests/test_transfer_choice_feedback.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py -v` → PASS
Run: `uv run ruff check --fix . && uv run ruff format .` → clean

- [ ] **Step 9: Commit**

```bash
git add courses/transfer/ tests/test_transfer_choice_feedback.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py
git commit -m "feat(choice): transfer feedback field + FORMAT_VERSION 4"
```

---

### Task 7: `has_math` scan + i18n

**Files:**
- Modify: `courses/views.py` (`_question_has_math`)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Modify: `tests/test_i18n_questions.py` (add the two msgids to `REQUIRED_MSGIDS`)
- Test: `tests/test_choice_feedback_has_math.py` (create)

**Interfaces:**
- Consumes: `Choice.feedback` (Task 1).

- [ ] **Step 1: Write the failing test**

Create `tests/test_choice_feedback_has_math.py`:

```python
import pytest

from courses.views import _element_has_math


@pytest.mark.django_db
def test_element_has_math_true_for_math_only_in_feedback():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="plain stem", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)  # plain
    Choice.objects.create(question=q, text="B", is_correct=False, feedback=r"try \(x^2\)")
    assert _element_has_math(q) is True


@pytest.mark.django_db
def test_element_has_math_false_when_no_math_anywhere():
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="plain", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True, feedback="plain hint")
    Choice.objects.create(question=q, text="B", is_correct=False)
    assert _element_has_math(q) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_choice_feedback_has_math.py -v`
Expected: FAIL on the first test (feedback not scanned).

- [ ] **Step 3: Scan feedback in `_question_has_math`**

In `courses/views.py`, update the `ChoiceQuestionElement` clause of `_question_has_math`:

```python
    if isinstance(q, ChoiceQuestionElement):
        return any(
            has_math_delimiters(c.text) or has_math_delimiters(c.feedback)
            for c in q.choices.all()
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_choice_feedback_has_math.py -v` → PASS

- [ ] **Step 5: Extract + translate i18n strings**

Run: `uv run python manage.py makemessages -l pl` (from repo root; watch the fuzzy-flag gotcha — do not leave `#, fuzzy` on the new entries).

Provide Polish `msgstr` for both new msgids in `locale/pl/LC_MESSAGES/django.po`:
- `"Feedback (optional)"` → `"Informacja zwrotna (opcjonalnie)"`
- `"choice feedback"` → `"informacja zwrotna odpowiedzi"`

Then compile: `uv run python manage.py compilemessages`.

- [ ] **Step 6: Gate the two new PL strings (write the failing assertion first)**

The catalog-clean test only greps for `#, fuzzy` / obsolete `#~` — it does NOT catch a new msgid left with an empty `msgstr`. The repo convention is a runtime `gettext(msgid) != msgid` gate. Add both new msgids to `REQUIRED_MSGIDS` in `tests/test_i18n_questions.py`:

```python
REQUIRED_MSGIDS = [
    # ... existing entries ...
    "Feedback (optional)",
    "choice feedback",
]
```

The existing `test_question_strings_have_polish_translations` iterates that list under `translation.override("pl")` and asserts each `gettext(msgid) != msgid`, so it now fails if either PL translation is missing/empty/fuzzy. (Add the entries BEFORE Step 5's compile to see it fail, then pass after compile.)

- [ ] **Step 7: Run the i18n gates + DoD**

Run: `uv run pytest tests/test_i18n_questions.py -v` → PASS (both new strings resolve to Polish)
Run: `uv run pytest tests/ -k "po_catalog or catalog" -v` → PASS (no obsolete `#~`, no fuzzy)
Run: `uv run ruff check --fix . && uv run ruff format .` → clean

- [ ] **Step 8: Commit**

```bash
git add courses/views.py locale/ tests/test_choice_feedback_has_math.py tests/test_i18n_questions.py
git commit -m "feat(choice): has_math scans feedback + PL translations"
```

---

### Task 8: Full-suite Definition of Done

**Files:** none (verification only).

- [ ] **Step 1: Full non-e2e suite**

Run: `uv run pytest -m "not e2e"` → all green (watch for any other test asserting the old choice-dict shape or `FORMAT_VERSION == 3`; fix in the owning task if found).

- [ ] **Step 2: Migrations + system checks**

Run: `uv run python manage.py makemigrations --check` → clean
Run: `uv run python manage.py check` → clean

- [ ] **Step 3: Lint/format**

Run: `uv run ruff check . && uv run ruff format --check .` → clean

- [ ] **Step 4: Targeted e2e (choice authoring + consumption)**

Run the existing choice/quiz e2e in the foreground only (per repo practice — avoid backgrounded `-m e2e` runaway browsers): `uv run pytest tests/test_e2e_questions.py -v`. Confirm no regression on choice authoring/consumption.

- [ ] **Step 5: Commit (if any DoD fixes were needed)**

```bash
git add -A
git commit -m "chore(choice): DoD fixes for per-choice feedback"
```
