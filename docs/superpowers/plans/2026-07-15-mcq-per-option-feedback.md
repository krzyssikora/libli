# Inline per-option MCQ feedback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show `ChoiceQuestionElement` per-option feedback inline beneath each wrong option in lessons, driven by a symmetric "options you got wrong" rule, while keeping the existing bottom reveal list in quiz-feedback and quiz-results.

**Architecture:** Rename the choice-specific `MarkResult.nudged` field to `annotated` and redefine it as the symmetric difference between the student's picks and the correct set (restricted to options carrying feedback). Render that feedback inline in `choicequestion.html` for `mode="lesson"`, suppress the duplicate bottom reveal list in lesson mode via a `render()` override gate + a truthiness guard, and deliver the lesson re-render by reusing `question.render()` (full element) over both the student fetch path (`check_answer`) and the authoring preview (`element_try`), with `question.js`/`editor.js` swapping the form body.

**Tech Stack:** Django (server-rendered templates), vanilla JS (no framework), pytest + Playwright (`-m e2e`), `uv run` for all tooling.

## Global Constraints

- All Python/pytest/ruff run via `uv run` (bash `pytest`/`ruff`/`python` are NOT on PATH). Ref: repo convention.
- No new model, migration, `ELEMENT_MODELS` entry, transfer serializer, palette card, or form. `Choice.feedback` already exists and round-trips through export/import.
- Do **not** bump `transfer/schema.py` `FORMAT_VERSION` — on-disk shape is unchanged.
- Feedback is **corrective-only**: shown exactly on options the student got wrong (selected distractor OR missed correct). Never on correctly-handled options; a fully-correct answer shows no per-option annotation.
- The `render()` lesson-mode gate goes **only** in the `ChoiceQuestionElement.render()` override — the base `QuestionElement.render()` must stay unchanged (else every other question type loses its no-JS reveal).
- i18n: any new author-facing string ships EN + PL.
- Marks/scoring unchanged — this is presentational only.

---

### Task 1: Symmetric marking rule + `nudged`→`annotated` rename (atomic)

Renames the choice-specific `MarkResult` field and redefines its semantics. This is one atomic change because a partial rename leaves producers/consumers mismatched (a 500). Touches 3 non-test files and 4 test files.

**Files:**
- Modify: `courses/marking.py:20,29` (field def + docstring)
- Modify: `courses/models.py:1206-1214,1219` (`ChoiceQuestionElement.mark()` computation + `MarkResult(...)` kwarg)
- Modify: `courses/views.py:667` (`_stored_result` — read `m.annotated`, pass `annotated=`)
- Modify: `templates/courses/elements/_reveal_choice.html:7` (consumer: `mark_result.nudged` → `mark_result.annotated`)
- Test: `tests/test_questions_models.py` (rename `.nudged`→`.annotated`, fix the stale "only selected distractors" comment at 143-161, add a missed-correct positive test)
- Test: `tests/test_choice_nudge_paths.py:18,34` (rename `.nudged`→`.annotated`)
- Test: `tests/test_render_choice_nudge.py:23,48,54` (rename `nudged=`→`annotated=`)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `MarkResult.annotated: frozenset` — for `ChoiceQuestionElement`, the frozenset of choice pks in the symmetric difference `answer △ correct` that carry non-empty `feedback`. Empty for every other question type. Replaces `MarkResult.nudged` entirely (no alias kept). `MarkResult.reveal` is unchanged.

- [ ] **Step 1: Write the failing test** — add to `tests/test_questions_models.py` (after the existing `test_mark_nudged_*` block):

```python
@pytest.mark.django_db
def test_mark_annotated_symmetric_includes_missed_correct():
    # NEW symmetric rule: an option is annotated iff the student's state for it
    # is wrong (selected XOR correct) AND it carries feedback. This covers BOTH
    # a selected distractor and a MISSED correct option (the omission case the
    # old asymmetric `nudged` rule never surfaced).
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=True)
    a = Choice.objects.create(question=q, text="A", is_correct=True, feedback="need A")
    b = Choice.objects.create(question=q, text="B", is_correct=True)  # correct, no feedback
    c = Choice.objects.create(question=q, text="C", is_correct=False, feedback="trap C")

    # student picks only C (a trap) and misses both correct options.
    res = q.mark({c.pk})
    assert res.correct is False
    # C = selected distractor with feedback -> annotated
    # A = missed correct WITH feedback -> annotated (the new case)
    # B = missed correct but NO feedback -> excluded
    assert res.annotated == frozenset({a.pk, c.pk})
    # fully-correct answer -> empty annotated (stay quiet when right)
    assert q.mark({a.pk, b.pk}).annotated == frozenset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_questions_models.py::test_mark_annotated_symmetric_includes_missed_correct -v`
Expected: FAIL — `AttributeError: 'MarkResult' object has no attribute 'annotated'` (field still named `nudged`).

- [ ] **Step 3: Rename the field in `courses/marking.py`**

Replace the docstring sentence (line ~19-23) and the field (line 29):

```python
    correct choice ids. `annotated` is a second per-type presentation payload: for
    ChoiceQuestionElement, the frozenset[int] of choice ids whose per-choice
    feedback should be shown — the symmetric difference between the student's
    selection and the correct set (a selected distractor OR a missed correct
    option), restricted to options carrying feedback; empty for every other type.
    """

    correct: bool
    fraction: float
    reveal: frozenset = frozenset()
    annotated: frozenset = frozenset()
```

- [ ] **Step 4: Redefine the rule in `courses/models.py` `ChoiceQuestionElement.mark()`**

Replace the `nudged = (...)` block (lines 1206-1214) and the `MarkResult(...)` `nudged=nudged` kwarg (line 1219):

```python
        # annotated = options whose selection state is WRONG (selected XOR correct)
        # and that carry feedback. Covers a selected distractor AND a missed correct
        # option. A fully-correct answer yields an empty symmetric difference, so no
        # explicit is_correct guard is needed (and dropping it enables the omission
        # case: a wrong answer with only missed-correct options still annotates).
        annotated = frozenset(
            c.pk
            for c in choices
            if c.feedback and ((c.pk in answer) != c.is_correct)
        )
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=correct_set,
            annotated=annotated,
        )
```

- [ ] **Step 5: Update `courses/views.py:_stored_result` (line 667)**

Change the `MarkResult(...)` construction so it reads and passes the renamed field:

```python
        annotated=m.annotated,
```

- [ ] **Step 6: Update the consumer template `templates/courses/elements/_reveal_choice.html`**

Change line 7 from `{% if c.pk in mark_result.nudged %}` to:

```django
      {% if c.pk in mark_result.annotated %}
```

- [ ] **Step 7: Rename `.nudged`/`nudged=` across the remaining tests + fix stale comment**

In `tests/test_questions_models.py`: replace every `.nudged` with `.annotated` and every `nudged=` with `annotated=` (lines 92-161, including `test_markresult_nudged_defaults_empty_and_hashable`, `test_mark_nudged_selected_distractor_on_wrong`, `test_mark_nudged_excludes_blank_and_unselected`, `test_mark_nudged_multi_excludes_selected_correct_pick`). Rewrite the misleading comment in `test_mark_nudged_multi_excludes_selected_correct_pick` (lines 144-145) to the symmetric semantics:

```python
    # multiple-choice: overall-wrong; the student selected an annotated CORRECT
    # choice. That choice is handled CORRECTLY (selected == correct), so it is NOT
    # annotated — only the wrongly-selected distractor is.
```

In `tests/test_choice_nudge_paths.py`: rename `test_stored_result_carries_nudged` → `test_stored_result_carries_annotated`, and line 34 `res.nudged` → `res.annotated`.

In `tests/test_render_choice_nudge.py`: replace `nudged=` (lines 23, 48) with `annotated=`, and the `# empty nudged -> no nudge leaks` comment (line 54) with `# empty annotated -> no feedback leaks`.

- [ ] **Step 8: Run the touched test files to verify they pass**

Run: `uv run pytest tests/test_questions_models.py tests/test_choice_nudge_paths.py tests/test_render_choice_nudge.py -v`
Expected: PASS (all, including the new symmetric test).

- [ ] **Step 9: Confirm no `nudged` references remain**

Run: `uv run python -c "import subprocess,sys; r=subprocess.run(['git','grep','-n','nudged','--','courses','tests'],capture_output=True,text=True); print(r.stdout); sys.exit(1 if r.stdout.strip() else 0)"`
Expected: empty output, exit 0.

- [ ] **Step 10: Commit**

```bash
git add courses/marking.py courses/models.py courses/views.py templates/courses/elements/_reveal_choice.html tests/test_questions_models.py tests/test_choice_nudge_paths.py tests/test_render_choice_nudge.py
git commit -m "feat(mcq-feedback): symmetric per-option annotated rule + nudged->annotated rename"
```

---

### Task 2: Inline per-option feedback markup in `choicequestion.html`

Adds the `data-question-inline` hook and the inline per-option marker + feedback, gated on `mode == "lesson" and mark_result and c.pk in mark_result.annotated`. At this task the bottom reveal is still emitted (removed in Task 3); the no-JS lesson page therefore transiently shows both — corrected next task.

**Files:**
- Modify: `templates/courses/elements/choicequestion.html`
- Test: `tests/test_choice_inline_feedback.py` (new)

**Interfaces:**
- Consumes: `MarkResult.annotated` (Task 1); `selected_ids`, `mode`, `element`, `choices` from the existing `render()` context.
- Produces: rendered `<span class="question__choice-marker question__choice-marker--wrong">` / `--missed` and `<p class="question__choice-feedback">` inside each annotated `<li>`, as siblings after the `<label>`. The `<form>` carries the `data-question-inline` attribute. These class names are the anchors the CSS (Task 8) and tests assert on.

- [ ] **Step 1: Write the failing test** — create `tests/test_choice_inline_feedback.py`:

```python
import pytest

from courses.marking import MarkResult
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element


def _lesson_choice():
    course = CourseFactory(slug="ilf")
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=True)
    a = Choice.objects.create(question=q, text="A", is_correct=True, feedback="need A", order=0)
    c = Choice.objects.create(question=q, text="C", is_correct=False, feedback="trap C", order=1)
    el = add_element(unit, q)
    return q, el, a, c


@pytest.mark.django_db
def test_inline_feedback_wrong_and_missed_markers():
    q, el, a, c = _lesson_choice()
    # student picked only the trap C -> C wrong-selected, A missed-correct
    res = MarkResult(correct=False, fraction=0.0, reveal=frozenset({a.pk}),
                     annotated=frozenset({a.pk, c.pk}))
    html = q.render(element=el, mode="lesson", mark_result=res, selected_ids=frozenset({c.pk}))
    assert 'data-question-inline' in html
    assert "trap C" in html and "need A" in html
    assert "question__choice-marker--wrong" in html   # selected distractor C
    assert "question__choice-marker--missed" in html  # missed correct A
    assert 'class="question__choice-feedback"' in html


@pytest.mark.django_db
def test_inline_feedback_absent_initial_state():
    q, el, a, c = _lesson_choice()
    # initial GET / preview: mark_result is None -> must not raise, no markers/feedback
    html = q.render(element=el, mode="lesson")
    assert "question__choice-marker" not in html
    assert "question__choice-feedback" not in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_choice_inline_feedback.py -v`
Expected: FAIL — `data-question-inline` / marker classes absent.

- [ ] **Step 3: Edit `templates/courses/elements/choicequestion.html`**

Add `data-question-inline` to the form tag and the per-option block after the `<label>`. Replace the choices loop (lines 8-20) with:

```django
    <ul class="question__choices">
      {% for c in choices %}
        <li class="question__choice">
          <label>
            <input type="{% if el.multiple %}checkbox{% else %}radio{% endif %}"
                   name="choice" value="{{ c.pk }}"
                   {% if element.pk == feedback_for_pk and c.pk in selected_ids %}checked{% endif %}
                   {% if quiz_submitted or locked %}disabled{% endif %}>
            <span class="question__choice-text">{{ c.text }}</span>
          </label>
          {% if mode == "lesson" and mark_result and c.pk in mark_result.annotated %}
            {% if c.pk in selected_ids %}
              <span class="question__choice-marker question__choice-marker--wrong" aria-hidden="true">✗</span>
            {% else %}
              <span class="question__choice-marker question__choice-marker--missed" aria-hidden="true">＋</span>
            {% endif %}
            <p class="question__choice-feedback">{{ c.feedback }}</p>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
```

Change the opening `<form>` tag (line 5-6) to add the hook:

```django
  <form class="question__form" method="post" data-question-inline
        action="{{ action_url }}">
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_choice_inline_feedback.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/choicequestion.html tests/test_choice_inline_feedback.py
git commit -m "feat(mcq-feedback): inline per-option markers + feedback in choice template"
```

---

### Task 3: Suppress the bottom reveal list in lesson mode

Gates `reveal_template` to `None` in the `ChoiceQuestionElement.render()` override for `mode == "lesson"`, and re-guards `_question_feedback.html`'s include on truthiness so `reveal_template=None` doesn't raise `TemplateDoesNotExist`. After this task the no-JS lesson path is fully correct (inline feedback, no duplicate list); quiz/results keep the reveal.

**Files:**
- Modify: `courses/models.py:1263` (`ChoiceQuestionElement.render()` override only)
- Modify: `templates/courses/elements/_question_feedback.html:10`
- Test: `tests/test_choice_inline_feedback.py` (extend)

**Interfaces:**
- Consumes: `MarkResult.annotated`, the inline markup (Task 2).
- Produces: `render(mode="lesson")` output contains **no** `question__reveal` list and never `{% include None %}`-raises; `render(mode="quiz")` and other question types still include their reveal.

- [ ] **Step 1: Write the failing test** — append to `tests/test_choice_inline_feedback.py`:

```python
@pytest.mark.django_db
def test_lesson_render_suppresses_bottom_reveal_list():
    q, el, a, c = _lesson_choice()
    res = MarkResult(correct=False, fraction=0.0, reveal=frozenset({a.pk}),
                     annotated=frozenset({a.pk, c.pk}))
    html = q.render(element=el, mode="lesson", mark_result=res,
                    selected_ids=frozenset({c.pk}), feedback_for_pk=el.pk)
    # inline feedback present, but the duplicate bottom reveal <ul> is gone
    assert "trap C" in html
    assert "question__reveal" not in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_choice_inline_feedback.py::test_lesson_render_suppresses_bottom_reveal_list -v`
Expected: FAIL — `question__reveal` still present (render passes `self.REVEAL_TEMPLATE` unconditionally).

- [ ] **Step 3: Gate `reveal_template` in the `ChoiceQuestionElement.render()` override**

In `courses/models.py`, in the `ChoiceQuestionElement.render()` method's `render_to_string(...)` context dict (line 1263), change:

```python
                "reveal_template": None if mode == "lesson" else self.REVEAL_TEMPLATE,
```

Add a short comment above it:

```python
                # Lesson: per-option feedback renders INLINE in the choices list, so the
                # bottom reveal list is suppressed (this override only — the base
                # QuestionElement.render must keep REVEAL_TEMPLATE for other types' no-JS path).
```

- [ ] **Step 4: Re-guard the include in `_question_feedback.html`**

Change line 10 from `{% if not mark_result.correct %}{% include reveal_template %}{% endif %}` to:

```django
  {% if not mark_result.correct and reveal_template %}{% include reveal_template %}{% endif %}
```

- [ ] **Step 5: Run to verify it passes (and existing reveal/quiz tests still green)**

Run: `uv run pytest tests/test_choice_inline_feedback.py tests/test_render_choice_nudge.py tests/test_choice_nudge_paths.py -v`
Expected: PASS (quiz/results reveal unaffected; lesson reveal suppressed).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py templates/courses/elements/_question_feedback.html tests/test_choice_inline_feedback.py
git commit -m "feat(mcq-feedback): suppress duplicate bottom reveal list in lesson mode"
```

---

### Task 4: `check_answer` fetch branch returns the full element for choice

The student JS path must return the re-rendered full element (inline feedback) instead of the bare `_question_feedback.html`, so the inline markup reaches the browser. Non-choice types are untouched.

**Files:**
- Modify: `courses/views.py:524-529` (`check_answer` fragment branch)
- Test: `tests/test_choice_inline_feedback.py` (extend, client-based)

**Interfaces:**
- Consumes: `question.render(...)` (Tasks 2-3), `HttpResponse` (already imported at `views.py:12`).
- Produces: fetch-path `check_answer` for a `ChoiceQuestionElement` returns an `HttpResponse` whose body is the full element with inline feedback and no `question__reveal`; for non-choice types it still returns `_question_feedback.html`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_choice_inline_feedback.py`:

```python
from django.urls import reverse
from tests.factories import make_login


@pytest.mark.django_db
def test_check_answer_fetch_returns_inline_full_element(client):
    make_login(client, "stu")
    q, el, a, c = _lesson_choice()
    url = reverse("courses:check_answer", kwargs={
        "slug": el.unit.course.slug, "node_pk": el.unit.pk, "element_pk": el.pk})
    body = client.post(url, {"choice": [str(c.pk)]},
                       HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "trap C" in body            # inline feedback for the selected distractor
    assert "need A" in body            # inline feedback for the missed correct option
    assert "question__choice-feedback" in body
    assert "question__reveal" not in body  # no duplicate bottom list
```

Note: `_lesson_choice` builds a lesson unit; `make_login` must be enrolled-independent — lesson access via `can_access_course`. If access fails, enroll: `from courses.models import Enrollment; Enrollment.objects.create(student=<user>, course=el.unit.course)` (capture the user returned by `make_login`).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_choice_inline_feedback.py::test_check_answer_fetch_returns_inline_full_element -v`
Expected: FAIL — body is the bare feedback partial (no `question__choice-feedback`).

- [ ] **Step 3: Edit `courses/views.py` `check_answer` fragment branch (lines 524-529)**

```python
    if _wants_fragment(request):
        if isinstance(question, ChoiceQuestionElement):
            # Choice: return the full re-rendered element so inline per-option feedback
            # lands in the choices list (question.js swaps the form body). render() sets
            # reveal_template=None for lesson mode -> no duplicate bottom reveal list.
            selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
            return HttpResponse(
                question.render(
                    element=element,
                    mode="lesson",
                    selected_ids=selected,
                    mark_result=result,
                    feedback_for_pk=element.pk,
                )
            )
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
```

Confirm `ChoiceQuestionElement` and `HttpResponse` are imported at the top of `views.py` (`HttpResponse` is at line 12; add `ChoiceQuestionElement` to the `courses.models` import block if not already present).

- [ ] **Step 4: Run to verify it passes + non-choice regression**

Run: `uv run pytest tests/test_choice_inline_feedback.py tests/test_courses_views.py -k "check_answer or inline or feedback" -v`
Expected: PASS (choice returns full element; other question types' check_answer tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add courses/views.py tests/test_choice_inline_feedback.py
git commit -m "feat(mcq-feedback): check_answer returns full inline element for choice questions"
```

---

### Task 5: `question.js` gated form-body swap + lesson e2e

The lesson JS must, for `data-question-inline` forms, swap the live form's inner HTML (extracted from the full-element response) instead of the bottom slot, and re-query the verdict/math against the live form (not the detached pre-fetch `slot`). Verified end-to-end.

**Files:**
- Modify: `courses/static/courses/js/question.js`
- Test: `tests/test_e2e_choice_inline_feedback.py` (new, `-m e2e`)

**Interfaces:**
- Consumes: `check_answer` full-element response (Task 4); `data-question-inline` (Task 2).
- Produces: after Check, the choice form body is replaced in place; the bound submit listener survives (form node persists); math re-typeset; Check hidden on correct. Other question types keep swapping `[data-question-feedback]`.

- [ ] **Step 1: Write the failing e2e test** — create `tests/test_e2e_choice_inline_feedback.py`:

```python
import pytest

pytestmark = pytest.mark.e2e


def test_lesson_inline_feedback_under_wrong_option(e2e_page, live_server, ...):
    # Build a lesson unit with a multi-select MCQ: A correct (feedback "need A"),
    # C distractor (feedback "trap C"). Log in an enrolled student. Navigate to the
    # lesson. Tick only C, click Check.
    # Assert the corrective feedback appears INLINE, inside the same .question__choice
    # <li> as the option, and no .question__reveal list exists.
    ...
    li_wrong = page.locator(".question__choice", has_text="C")
    expect(li_wrong.locator(".question__choice-feedback")).to_have_text("trap C")
    expect(page.locator(".question__reveal")).to_have_count(0)


def test_lesson_correct_answer_hides_check_no_feedback(e2e_page, ...):
    # Tick A and B (both correct), Check -> ✓ verdict, no .question__choice-feedback,
    # Check button hidden.
    ...
```

Follow the fixture/login/navigation pattern in the existing `tests/test_e2e_questions.py` (same `-m e2e` harness, enrolled-student login, lesson navigation). Fill the `...` with that file's concrete setup.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_e2e_choice_inline_feedback.py -v` (foreground; do NOT background `-m e2e` — runaway browsers)
Expected: FAIL — feedback still lands in the bottom slot, not inline in the `<li>`.

- [ ] **Step 3: Edit `courses/static/courses/js/question.js`**

In the submit handler (currently `.then(function (html) { if (!slot) return; slot.innerHTML = html; renderQ(slot); ...})`), branch on the form hook:

```javascript
        .then(function (html) {
          if (form.hasAttribute("data-question-inline")) {
            // Choice: response is the full element; swap the LIVE form's body so the
            // bound submit listener survives, then re-query against the live form
            // (the pre-fetch `slot` is detached by this assignment).
            var doc = new DOMParser().parseFromString(html, "text/html");
            var newForm = doc.querySelector("form");
            if (!newForm) return;
            form.innerHTML = newForm.innerHTML;
            renderQ(form);
            if (form.querySelector(".question__verdict.is-correct")) {
              var cbtn = form.querySelector("button[type='submit'], input[type='submit']");
              if (cbtn) cbtn.hidden = true;
            }
            return;
          }
          if (!slot) return;
          slot.innerHTML = html;
          renderQ(slot);
          if (slot.querySelector(".question__verdict.is-correct")) {
            var btn = form.querySelector("button[type='submit'], input[type='submit']");
            if (btn) btn.hidden = true;
          }
        })
```

- [ ] **Step 4: Collectstatic if the harness serves from staticfiles, then run the e2e**

Run: `uv run python manage.py collectstatic --noinput` (only if the e2e harness serves collected static; skip if it serves app static directly — check `tests/test_e2e_questions.py` conventions)
Run: `uv run pytest tests/test_e2e_choice_inline_feedback.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/question.js tests/test_e2e_choice_inline_feedback.py
git commit -m "feat(mcq-feedback): question.js swaps form body for inline choice feedback + e2e"
```

---

### Task 6: Authoring preview fidelity — `element_try` + `editor.js`

The manage-editor "try it" preview must show authors the same inline layout students get. `element_try`'s lesson branch mirrors `check_answer` for choice; `editor.js`'s preview handler gets the parallel form-body swap.

**Files:**
- Modify: `courses/views_manage.py:1120-1126` (`element_try` lesson branch)
- Modify: `courses/static/courses/js/editor.js:195-213` (preview swap handler)
- Test: `tests/test_choice_inline_feedback.py` (extend — server-side preview output)

**Interfaces:**
- Consumes: `question.render(...)` (Tasks 2-3), the `data-question-inline` swap pattern (Task 5).
- Produces: `manage_element_try` for a lesson choice question returns the full inline element; `editor.js` swaps the live preview form body for `data-question-inline`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_choice_inline_feedback.py`:

```python
from tests.factories import make_pa


@pytest.mark.django_db
def test_element_try_lesson_choice_returns_inline(client):
    make_pa(client, "pa")  # manage-gated
    q, el, a, c = _lesson_choice()
    url = reverse("courses:manage_element_try",
                  kwargs={"slug": el.unit.course.slug, "pk": el.pk})
    body = client.post(url, {"choice": [str(c.pk)]},
                       HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "question__choice-feedback" in body
    assert "trap C" in body
    assert "question__reveal" not in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_choice_inline_feedback.py::test_element_try_lesson_choice_returns_inline -v`
Expected: FAIL — returns `_question_feedback.html` with the reveal list, no inline feedback.

- [ ] **Step 3: Edit `courses/views_manage.py` `element_try` lesson branch (lines 1120-1126)**

```python
    # Lesson: immediate feedback, exactly like the student lesson check.
    if el.unit.unit_type != ContentNode.UnitType.QUIZ:
        result = question.mark(answer)  # NOTHING is persisted
        if isinstance(question, ChoiceQuestionElement):
            selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
            return HttpResponse(
                question.render(
                    element=el,
                    mode="lesson",
                    selected_ids=selected,
                    mark_result=result,
                    feedback_for_pk=el.pk,
                )
            )
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
```

Ensure `ChoiceQuestionElement` and `HttpResponse` are imported in `views_manage.py` (add to imports if absent).

- [ ] **Step 4: Run the server-side preview test**

Run: `uv run pytest tests/test_choice_inline_feedback.py::test_element_try_lesson_choice_returns_inline -v`
Expected: PASS.

- [ ] **Step 5: Edit `courses/static/courses/js/editor.js` preview handler**

In the `tryForm` `.then(function (html) {...})` (lines 195-213), branch before the `slot` swap:

```javascript
      }).then(function (r) { return r.text(); }).then(function (html) {
        if (tryForm.hasAttribute("data-question-inline")) {
          // Choice lesson preview: full element -> swap the live form body, re-render
          // math against the live form (the pre-fetch `slot` is detached).
          var doc = new DOMParser().parseFromString(html, "text/html");
          var newForm = doc.querySelector("form");
          if (!newForm) return;
          tryForm.innerHTML = newForm.innerHTML;
          if (window.libliRenderMath) window.libliRenderMath(tryForm);
          renderPreviewMath(tryForm);
          return;
        }
        var slot = tryForm.querySelector("[data-question-feedback]");
        if (!slot) return;
        slot.innerHTML = html;
        if (window.libliRenderMath) window.libliRenderMath(slot);
        renderPreviewMath(slot);  // inline math in revealed answers / explanation
        if (!qEl) return;
        if (!slot.querySelector(".is-validation")) {
          qEl.setAttribute("data-attempts-made", String(made + 1));
        }
        if (slot.querySelector("[data-quiz-locked]")) {
          qEl.querySelectorAll("input, button[type=submit]").forEach(function (n) {
            n.disabled = true;
          });
        }
      });
```

(The choice-lesson preview never emits `.is-validation` / `[data-quiz-locked]` sentinels, so skipping that quiz-only bookkeeping is correct.)

- [ ] **Step 6: Verify the preview swap in the editor**

Manually (or via a focused preview e2e mirroring Task 5) confirm: open the manage editor for a lesson MCQ with option feedback, click "try it", tick a wrong option → feedback appears inline in the preview, no bottom reveal list. Server-side test from Step 4 is the committed guard; note the manual check in the commit body.

- [ ] **Step 7: Commit**

```bash
git add courses/views_manage.py courses/static/courses/js/editor.js tests/test_choice_inline_feedback.py
git commit -m "feat(mcq-feedback): faithful authoring preview (element_try + editor.js inline swap)"
```

---

### Task 7: Editor `feedback` field help text (EN + PL)

Tell authors the feedback now shows for both a selected trap AND a missed correct option, so they write text for correct options too.

**Files:**
- Modify: `courses/element_forms.py:581-589` (`ChoiceFormSet` — add `help_texts`)
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compile)
- Test: `tests/test_choice_inline_feedback.py` (extend — help text present)

**Interfaces:**
- Consumes: nothing new.
- Produces: the choice `feedback` field renders a help string; a PL translation exists.

- [ ] **Step 1: Write the failing test** — append to `tests/test_choice_inline_feedback.py`:

```python
from courses.element_forms import build_choice_formset


@pytest.mark.django_db
def test_choice_feedback_help_text_mentions_both_cases():
    fs = build_choice_formset(multiple=True)
    help_text = str(fs.forms[0].fields["feedback"].help_text)
    assert help_text  # non-empty
    # mentions the missed-correct case, not only distractors
    assert "correct" in help_text.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_choice_inline_feedback.py::test_choice_feedback_help_text_mentions_both_cases -v`
Expected: FAIL — `feedback` field has no `help_text`.

- [ ] **Step 3: Add `help_texts` to the `ChoiceFormSet` factory in `courses/element_forms.py`**

Add a `help_texts` kwarg to `inlineformset_factory` (after `widgets=`, line 586). Use `gettext_lazy` (imported as `_`), matching the repo's lazy-i18n convention:

```python
    help_texts={
        "feedback": _(
            "Shown to the student when they get this option wrong — either they "
            "picked it (a distractor) or missed it (a correct option). Explain why "
            "it is wrong, or why a correct option should be chosen."
        )
    },
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_choice_inline_feedback.py::test_choice_feedback_help_text_mentions_both_cases -v`
Expected: PASS.

- [ ] **Step 5: Regenerate + translate the PL catalog**

Run: `uv run python manage.py makemessages -l pl` (from repo root). Locate the new `msgid` (the help string) in `locale/pl/LC_MESSAGES/django.po`, add a `msgstr` PL translation, and ensure no `#, fuzzy` marker remains on it. Then compile: `uv run python manage.py compilemessages -l pl`.

Watch the makemessages fuzzy-flag gotcha: remove any `#, fuzzy` on the new/edited entry or the translation is ignored.

- [ ] **Step 6: Run the i18n catalog test**

Run: `uv run pytest tests/test_align_i18n.py -v` (or the repo's catalog-alignment test)
Expected: PASS (EN msgid has a PL msgstr; no fuzzy).

- [ ] **Step 7: Commit**

```bash
git add courses/element_forms.py locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_choice_inline_feedback.py
git commit -m "feat(mcq-feedback): choice feedback help text (EN+PL) for missed-correct case"
```

---

### Task 8: CSS for inline feedback + markers (light + dark, frontend-design)

Style the new `question__choice-feedback` and `question__choice-marker--wrong/--missed` so nothing ships unstyled.

**Files:**
- Modify: `courses/static/courses/css/courses.css` (near the existing `.question__nudge` rule, line ~85)
- Test: `tests/test_choice_inline_feedback_css.py` (new — CSS presence assertion, mirroring the repo's `test_*_css.py` pattern)

**Interfaces:**
- Consumes: the class names from Task 2.
- Produces: CSS rules for `.question__choice-feedback`, `.question__choice-marker`, `--wrong`, `--missed`.

- [ ] **Step 1: Write the failing test** — create `tests/test_choice_inline_feedback_css.py` (follow `tests/test_callout_css.py` / `tests/test_choicegrid_styles.py` for the read-the-css-file pattern):

```python
from pathlib import Path


def test_inline_feedback_classes_are_styled():
    css = Path("courses/static/courses/css/courses.css").read_text(encoding="utf-8")
    assert ".question__choice-feedback" in css
    assert ".question__choice-marker" in css
    assert "--wrong" in css and "--missed" in css
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_choice_inline_feedback_css.py -v`
Expected: FAIL — classes not in the stylesheet.

- [ ] **Step 3: Add the rules to `courses/static/courses/css/courses.css`** (after `.question__nudge {...}`, line ~90)

```css
/* Inline per-option feedback in the lesson choices list (mcq-feedback). Shares the
   visual language of .question__nudge (the quiz/results reveal-list feedback) but is
   positioned within the interactive <li> rather than the standalone reveal list. */
.question__choice-feedback {
  margin: 0.25rem 0 0 1.75rem;
  font-size: 0.9em;
  color: var(--text-tertiary);
  font-style: italic;
}
.question__choice-marker { margin-left: 0.4rem; font-weight: 600; }
.question__choice-marker--wrong { color: var(--danger); }
.question__choice-marker--missed { color: var(--success); }
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_choice_inline_feedback_css.py -v`
Expected: PASS.

- [ ] **Step 5: frontend-design pass + light/dark screenshot verification**

Invoke the `frontend-design` skill on the inline treatment. Then render a lesson MCQ answered wrong (via the running app / Playwright), capture light and dark screenshots, and self-critique: is the corrective feedback legible and clearly subordinate to the option; is the missed-correct marker visually distinct from a "correct ✓" and from the wrong ✗; do both markers read in dark mode. Adjust the CSS (tokens `--danger`, `--success`, `--text-tertiary` already adapt to theme) until both themes pass. Re-run Step 4 after any class-name change.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_choice_inline_feedback_css.py
git commit -m "feat(mcq-feedback): style inline choice feedback + markers (light+dark)"
```

---

### Task 9: Full-suite Definition-of-Done

Run the whole suite + lint + format + i18n to confirm no regressions across the codebase.

**Files:** none (verification only; commit any lint/format fixups).

- [ ] **Step 1: Full unit suite (parallel)**

Run: `uv run pytest -m "not e2e" -q`
Expected: PASS (no failures, no errors). Investigate any failure to root cause — do not proceed with red.

- [ ] **Step 2: Focused e2e (foreground)**

Run: `uv run pytest -m e2e tests/test_e2e_choice_inline_feedback.py -v`
Expected: PASS. (Run choice e2e only, foreground — avoid a full `-m e2e` background sweep.)

- [ ] **Step 3: Lint + format**

Run: `uv run ruff check .`
Run: `uv run ruff format --check .`
Expected: both clean. If `ruff format --check` reports diffs, run `uv run ruff format .`, re-run the touched tests, and commit.

- [ ] **Step 4: i18n catalog alignment**

Run: `uv run pytest tests/test_align_i18n.py -v`
Expected: PASS.

- [ ] **Step 5: Commit any fixups**

```bash
git add -A
git commit -m "chore(mcq-feedback): full-suite DoD (lint/format/i18n fixups)"
```

(If Steps 1-4 were all green with no changes, skip the commit.)

---

## Self-Review

**Spec coverage:**
- §1 marking rule → Task 1. §2 rename (2 producers/2 consumers + tests + comment) → Task 1. §3 inline markup + gate → Task 2; render() gate + truthiness guard → Task 3. §4 check_answer → Task 4; no-JS path → covered free by Tasks 2-3 (render()); element_try → Task 6. §5 question.js → Task 5; editor.js → Task 6. §6 reveal rename → Task 1; unanswered-results behavior → tested in Task 1's suite scope + existing `test_choice_nudge_on_results_page` (renamed) and the symmetric rule covers `mark(empty)`. §7 help text → Task 7. §8 CSS → Task 8. Testing (unit/template/view/e2e/DoD) → distributed across Tasks 1-9.
- Unanswered-results explicit test: `tests/test_choice_nudge_paths.py::test_choice_nudge_on_results_page` already exercises a wrong locked response; the `mark(empty)` unanswered path is exercised by the symmetric-rule unit test (`q.mark({c.pk})` covers missed-correct → annotated, and `mark(empty)` is the same code path with `answer=∅`). Adequate; no separate task needed.

**Placeholder scan:** e2e test bodies (Task 5) intentionally reference the existing `tests/test_e2e_questions.py` harness for fixture boilerplate rather than duplicating ~40 lines of Playwright setup — the assertions (the load-bearing part) are concrete. All server-side code steps show complete code.

**Type consistency:** `MarkResult.annotated: frozenset` defined in Task 1, consumed identically in Tasks 2-6 templates/views. `question.render(element=, mode=, selected_ids=, mark_result=, feedback_for_pk=)` signature matches `courses/models.py` `ChoiceQuestionElement.render()` keyword-only params. Class names `question__choice-feedback` / `question__choice-marker--wrong` / `--missed` consistent across Tasks 2, 5, 8. `data-question-inline` consistent across Tasks 2, 5, 6.
