# Phase 2a — Question foundations (formative MCQ in lessons) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `ChoiceQuestionElement` (single + multiple-choice MCQ) that authors add through the existing per-unit editor and students answer formatively inside lesson units, receiving server-marked feedback (correct/incorrect + revealed answers + explanation), with no response persistence.

**Architecture:** Questions are new Element types in the existing GFK join-row + concrete-model pattern. An abstract `QuestionElement(ElementBase)` defines the `mark(answer) -> MarkResult` contract; `ChoiceQuestionElement` is the first concrete type with related `Choice` rows. The student consumption path reuses `render_element` dispatch and a new `check_answer` endpoint (two transports: JS fragment-swap + no-JS full-page). Authoring reuses `FORM_FOR_TYPE`/`_render_open_form`/`builder.save_element`, extended for an inline `Choice` formset. **Nothing about a student's answer is persisted** — the server marks it and returns feedback in the same request.

**Tech Stack:** Django 5.2, server-rendered templates, vanilla JS (fetch + `X-CSRFToken`), pytest + Playwright, vendored KaTeX.

## Global Constraints

- **No new dependency.** Reuse Django, `courses.sanitize.sanitize_html`, vendored KaTeX, the `fetch`+`X-CSRFToken` transport.
- **No response persistence in 2a.** `check_answer` marks and returns feedback; it stores nothing. The `UnitProgress` completion contract is unchanged (answering is not required for completion).
- **Security invariant:** choice `is_correct` is never serialized to any render except the single element matching `feedback_for_pk`. The server is the sole marking authority.
- **Progressive enhancement:** every interactive path has a no-JS baseline. No `csrf_exempt`.
- **i18n:** every new user-facing string wrapped (`gettext` / `{% trans %}`) + Polish translation; never put literal `\(`/`\[` LaTeX delimiters inside `{% trans %}` strings (they break the PO gate — see `_edit_html.html`).
- **Manage predicate:** authoring access = `can_manage_course` (owner OR `courses.change_course`); never `is_staff`.
- **Optimistic concurrency unchanged:** element ops bump the parent unit's `updated`; token = `unit.updated.isoformat()` posted as `unit_token`; 409-before-422.
- **DoD gate (run before "done"):** default `pytest -q` (e2e excluded by `-m 'not e2e'`) green + the new e2e green; `ruff check .`; `ruff format --check .`; `makemigrations --check` (exactly one new migration); `uv run python manage.py check`; `collectstatic`; `compilemessages -l pl`.
- **Env:** Windows; run Python via `uv run python`; run pytest via `uv run pytest`.

---

### Task 1: Data model — `QuestionElement`, `MarkResult`, `ChoiceQuestionElement`, `Choice`, migration

**Files:**
- Create: `courses/marking.py`
- Modify: `courses/models.py` (add abstract base + two models; extend `ELEMENT_MODELS`)
- Create: `courses/migrations/0013_choicequestion.py` (generated)
- Test: `tests/test_questions_models.py`

**Interfaces:**
- Produces:
  - `courses.marking.MarkResult` — frozen dataclass: `correct: bool`, `fraction: float`, `reveal: frozenset[int]`.
  - `courses.models.QuestionElement` — abstract `ElementBase` subclass; fields `stem: TextField`, `explanation: TextField`; sanitizes both on `save()`; declares `mark(self, answer) -> MarkResult` (raises `NotImplementedError`).
  - `courses.models.ChoiceQuestionElement(QuestionElement)` — field `multiple: BooleanField(default=False)`; `choices` reverse relation; `GenericRelation(Element)`; concrete `mark()`.
  - `courses.models.Choice` — `question` FK (`related_name="choices"`, CASCADE), `text: CharField(500)`, `is_correct: BooleanField`, `order: OrderField(for_fields=["question"])`.
  - `ELEMENT_MODELS` includes `"choicequestionelement"`.

- [ ] **Step 1: Write the failing test for `MarkResult` and `mark()`**

Create `tests/test_questions_models.py`:

```python
import pytest

from courses.marking import MarkResult


@pytest.mark.django_db
def test_mark_single_choice_set_equality():
    from courses.models import ChoiceQuestionElement, Choice

    q = ChoiceQuestionElement.objects.create(stem="2+2?", multiple=False)
    a = Choice.objects.create(question=q, text="4", is_correct=True)
    b = Choice.objects.create(question=q, text="5", is_correct=False)

    correct = q.mark({a.pk})
    assert isinstance(correct, MarkResult)
    assert correct.correct is True and correct.fraction == 1.0
    assert correct.reveal == frozenset({a.pk})

    assert q.mark({b.pk}).correct is False
    # forged: two ids in single mode -> not equal to the singleton correct set
    assert q.mark({a.pk, b.pk}).correct is False
    # empty submission -> incorrect
    assert q.mark(set()).correct is False and q.mark(set()).fraction == 0.0


@pytest.mark.django_db
def test_mark_multiple_choice_all_or_nothing():
    from courses.models import ChoiceQuestionElement, Choice

    q = ChoiceQuestionElement.objects.create(stem="Primes?", multiple=True)
    c2 = Choice.objects.create(question=q, text="2", is_correct=True)
    c3 = Choice.objects.create(question=q, text="3", is_correct=True)
    c4 = Choice.objects.create(question=q, text="4", is_correct=False)

    assert q.mark({c2.pk, c3.pk}).correct is True
    assert q.mark({c2.pk}).correct is False          # partial -> wrong (all-or-nothing)
    assert q.mark({c2.pk, c3.pk, c4.pk}).correct is False
    assert q.mark(set()).correct is False


@pytest.mark.django_db
def test_stem_and_explanation_sanitised_on_save():
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(
        stem="<p>ok</p><script>alert(1)</script>",
        explanation="<p>why</p><script>bad()</script>",
    )
    assert "<script>" not in q.stem and "<p>ok</p>" in q.stem
    assert "<script>" not in q.explanation and "<p>why</p>" in q.explanation


@pytest.mark.django_db
def test_choice_order_autonumbers_and_survives_delete_then_add():
    from courses.models import ChoiceQuestionElement, Choice

    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    a = Choice.objects.create(question=q, text="a")
    b = Choice.objects.create(question=q, text="b")
    c = Choice.objects.create(question=q, text="c")
    assert [x.order for x in (a, b, c)] == [0, 1, 2]  # OrderField base is 0
    b.delete()  # leaves a gap at order 1
    d = Choice.objects.create(question=q, text="d")
    assert d.order == 3  # max(order)+1, not reusing the gap
    # effective display order is (order, pk): a(0), c(2), d(3)
    assert [x.text for x in q.choices.all()] == ["a", "c", "d"]


@pytest.mark.django_db
def test_choicequestionelement_in_element_models():
    from courses.models import ELEMENT_MODELS

    assert "choicequestionelement" in ELEMENT_MODELS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_questions_models.py -q`
Expected: FAIL — `ModuleNotFoundError: courses.marking` / `ImportError: cannot import name 'ChoiceQuestionElement'`.

- [ ] **Step 3: Create `courses/marking.py`**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkResult:
    """The normalized result every question type's mark() returns.

    `reveal` is a per-type, type-opaque presentation payload consumed by the
    feedback template. For ChoiceQuestionElement it is a frozenset[int] of the
    correct choice ids.
    """

    correct: bool
    fraction: float
    reveal: frozenset = frozenset()
```

- [ ] **Step 4: Add the models to `courses/models.py`**

Add `from courses.marking import MarkResult` to the imports at the top. Then add, after the `HtmlElement` class (the last `ElementBase` subclass, ~line 300):

```python
class QuestionElement(ElementBase):
    """Abstract base for all question element types (Phase 2).

    Owns the shared rich-text fields and declares the marking contract. Concrete
    subclasses implement mark(); the server is the sole marking authority.
    """

    stem = models.TextField(blank=True)  # the prompt; rich text, sanitised on save
    explanation = models.TextField(blank=True)  # shown in feedback; sanitised on save

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.stem = sanitize_html(self.stem)
        self.explanation = sanitize_html(self.explanation)
        super().save(*args, **kwargs)

    def mark(self, answer):
        raise NotImplementedError


class ChoiceQuestionElement(QuestionElement):
    """Single- (multiple=False) or multiple-choice (multiple=True) MCQ."""

    multiple = models.BooleanField(default=False)
    elements = GenericRelation(Element)

    def correct_ids(self):
        return frozenset(
            self.choices.filter(is_correct=True).values_list("pk", flat=True)
        )

    def mark(self, answer):
        # `answer` is an already-validated set of this question's choice ids
        # (foreign/forged ids are dropped in check_answer before mark() is called).
        # Single and multi are one uniform rule: exact set equality.
        correct_set = self.correct_ids()
        is_correct = set(answer) == set(correct_set)
        return MarkResult(
            correct=is_correct,
            fraction=1.0 if is_correct else 0.0,
            reveal=correct_set,
        )


class Choice(models.Model):
    question = models.ForeignKey(
        ChoiceQuestionElement, on_delete=models.CASCADE, related_name="choices"
    )
    text = models.CharField(max_length=500)  # plain text + KaTeX delimiters; never sanitised
    is_correct = models.BooleanField(default=False)
    order = OrderField(for_fields=["question"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.text
```

Then extend `ELEMENT_MODELS` (currently at ~line 133):

```python
ELEMENT_MODELS = [
    "textelement",
    "imageelement",
    "videoelement",
    "iframeelement",
    "mathelement",
    "htmlelement",
    "choicequestionelement",
]
```

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0013_*.py` with `CreateModel` for `ChoiceQuestionElement` + `Choice` **and** an `AlterField` on `Element.content_type` (because `limit_choices_to` references `ELEMENT_MODELS` — validation-only, no DDL on `Element`, exactly as `0010` did).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_questions_models.py -q`
Expected: PASS (5 tests).

- [ ] **Step 7: Verify migration state is clean**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 8: Commit**

```bash
git add courses/marking.py courses/models.py courses/migrations/0013_*.py tests/test_questions_models.py
git commit -m "feat(2a): QuestionElement base + ChoiceQuestionElement/Choice + MarkResult"
```

---

### Task 2: Student consumption — render, mark, feedback (both transports)

**Files:**
- Modify: `courses/models.py` (add `ChoiceQuestionElement.render()` override)
- Modify: `courses/templatetags/courses_extras.py` (`render_element` gains kwargs, forwards to `QuestionElement.render`)
- Create: `templates/courses/elements/choicequestion.html`
- Create: `templates/courses/elements/_question_feedback.html`
- Modify: `courses/views.py` (`build_lesson_context` helper; refactor `lesson_unit`; add `check_answer`)
- Modify: `courses/urls.py` (add `check_answer` route)
- Modify: `templates/courses/lesson_unit.html` (pass feedback kwargs to `render_element`)
- Test: `tests/test_questions_consumption.py`

**Interfaces:**
- Consumes: `ChoiceQuestionElement`, `Choice`, `MarkResult` (Task 1); `get_node_or_404`, `can_access_course`, `is_enrolled`; `_wants_fragment` is *not* in `views.py` — define a local equivalent (see Step 7).
- Produces:
  - `ChoiceQuestionElement.render(self, *, element=None, feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)` → HTML string.
  - `render_element(element, feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)`.
  - `courses.views.build_lesson_context(node, user)` → dict.
  - `courses.views.check_answer(request, slug, node_pk, element_pk)`.
  - URL name `courses:check_answer`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_questions_consumption.py`:

```python
import pytest
from django.urls import reverse

from courses.models import ChoiceQuestionElement, Choice, Element, Enrollment
from tests.factories import ContentNodeFactory, CourseFactory
from tests.factories import make_login


def _login(client):
    # make_login force_logins (bypasses allauth's mandatory-verification middleware —
    # the gotcha documented in tests/factories.py). Do NOT use client.login here.
    return make_login(client, "stu")


def _question_in_lesson(course, *, multiple=False):
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    q = ChoiceQuestionElement.objects.create(stem="2+2?", multiple=multiple)
    right = Choice.objects.create(question=q, text="4", is_correct=True)
    wrong = Choice.objects.create(question=q, text="5", is_correct=False)
    el = Element.objects.create(unit=unit, content_object=q)
    return unit, el, q, right, wrong


@pytest.mark.django_db
def test_initial_render_has_no_correctness_signal(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    body = resp.content.decode()
    assert 'name="choice"' in body
    assert f'value="{right.pk}"' in body and f'value="{wrong.pk}"' in body
    # No correctness leaks to the initial page:
    assert "is_correct" not in body
    assert "data-correct" not in body
    assert "answer-correct" not in body  # the feedback CSS class (Task 5)


@pytest.mark.django_db
def test_check_answer_correct_fragment(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    # Assert on the locale-independent verdict CSS class, not the English word
    # (the verdict text is {% trans %}'d; "is-correct" is not a substring of
    # "is-incorrect" or "answer-correct", so it's a clean discriminator).
    assert b"is-correct" in resp.content


@pytest.mark.django_db
def test_check_answer_incorrect_and_reveals(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [wrong.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content


@pytest.mark.django_db
def test_check_answer_empty_submission_is_incorrect(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content


@pytest.mark.django_db
def test_check_answer_drops_foreign_choice_ids(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    other_q = ChoiceQuestionElement.objects.create(stem="x", multiple=False)
    foreign = Choice.objects.create(question=other_q, text="z", is_correct=True)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    # foreign id is dropped -> treated as empty -> incorrect (never errors)
    resp = client.post(url, {"choice": [foreign.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"is-incorrect" in resp.content


@pytest.mark.django_db
def test_check_answer_404s_on_quiz_unit(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(stem="q", multiple=False)
    Choice.objects.create(question=q, text="a", is_correct=True)
    el = Element.objects.create(unit=unit, content_object=q)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": []}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_check_answer_404s_for_element_in_other_unit(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    other_unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": other_unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_no_js_post_rerenders_whole_lesson_with_feedback(client):
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]})  # no X-Requested-With → full page
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "lesson-unit__title" in body  # whole lesson page, not just a fragment
    assert "is-correct" in body


@pytest.mark.django_db
def test_post_submit_page_reveals_only_the_answered_question(client):
    # Spec §4(b): on a post-submit page, reveal data appears for the answered
    # question ONLY — every other question stays clean.
    user = _login(client)
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit, el, q, right, wrong = _question_in_lesson(course)
    q2 = ChoiceQuestionElement.objects.create(stem="3+3?", multiple=False)
    Choice.objects.create(question=q2, text="6", is_correct=True)
    Choice.objects.create(question=q2, text="7", is_correct=False)
    Element.objects.create(unit=unit, content_object=q2)  # a SECOND, unanswered question
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    resp = client.post(url, {"choice": [right.pk]})  # no-JS full page
    body = resp.content.decode()
    # Exactly one reveal block (the answered single-choice question's one correct choice);
    # the second question renders no feedback / no correctness signal.
    assert body.count("answer-correct") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_questions_consumption.py -q`
Expected: FAIL — `NoReverseMatch: 'check_answer'` (and template/attr assertions).

- [ ] **Step 3: Add the `render()` override to `ChoiceQuestionElement` in `courses/models.py`**

Add this method to `ChoiceQuestionElement` (it overrides `ElementBase.render`, which would otherwise look for `choicequestionelement.html` and pass only `{"el": self}`):

```python
    def render(
        self,
        *,
        element=None,
        feedback_for_pk=None,
        selected_ids=frozenset(),
        mark_result=None,
    ):
        # `element` is the Element join-row (carries the unit + pk for the form action
        # and the per-element feedback gate). Mirrors HtmlElement.render's extra args.
        choices = list(self.choices.all())
        unit = element.unit if element is not None else None
        return render_to_string(
            "courses/elements/choicequestion.html",
            {
                "el": self,
                "element": element,
                "choices": choices,
                "slug": unit.course.slug if unit is not None else "",
                "node_pk": unit.pk if unit is not None else "",
                "feedback_for_pk": feedback_for_pk,
                "selected_ids": set(selected_ids or ()),
                "mark_result": mark_result,
            },
        )
```

- [ ] **Step 4: Update `render_element` in `courses/templatetags/courses_extras.py`**

```python
from django import template
from django.utils.safestring import mark_safe

from courses.models import HtmlElement
from courses.models import QuestionElement
from courses.sanitize import sanitize_html

register = template.Library()


@register.simple_tag
def render_element(element, feedback_for_pk=None, selected_ids=frozenset(), mark_result=None):
    """Render one Element's concrete payload. Empty string if the target was deleted.

    Question elements need per-render feedback context (the answered question's pk,
    the student's selection, and the MarkResult); these reach the template ONLY via
    the concrete render() override, so the tag forwards them (the HtmlElement
    forwarding precedent, which passes unit/course).
    """
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course))  # noqa: S308
    if isinstance(obj, QuestionElement):
        return mark_safe(  # noqa: S308 — template auto-escapes choice text; is_correct never leaks
            obj.render(
                element=element,
                feedback_for_pk=feedback_for_pk,
                selected_ids=selected_ids,
                mark_result=mark_result,
            )
        )
    return mark_safe(obj.render())  # noqa: S308 — each element template escapes its own fields
```

- [ ] **Step 5: Create `templates/courses/elements/choicequestion.html`**

```django
{% load i18n %}
<div class="el el--question" data-question>
  <div class="question__stem">{{ el.stem|safe }}</div>
  {% if element %}
  <form class="question__form" method="post"
        action="{% url 'courses:check_answer' slug=slug node_pk=node_pk element_pk=element.pk %}">
    {% csrf_token %}
    <ul class="question__choices">
      {% for c in choices %}
        <li class="question__choice">
          <label>
            <input type="{% if el.multiple %}checkbox{% else %}radio{% endif %}"
                   name="choice" value="{{ c.pk }}"
                   {% if element.pk == feedback_for_pk and c.pk in selected_ids %}checked{% endif %}>
            <span class="question__choice-text">{{ c.text }}</span>
          </label>
        </li>
      {% endfor %}
    </ul>
    <button type="submit" class="btn btn--small">{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_question_feedback.html" %}
      {% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

Notes:
- `el.stem` is stored already-sanitized (Task 1 `save()`), so `|safe` is correct here. Choice `text` is auto-escaped (no `|safe`).
- `el.multiple` is a **saved** model field here (reliable), unlike the editor partial where the form's `multiple` is bound/unbound-fragile (Task 4 uses an explicit `is_multiple`).
- The `{% if element %}` guard means a defensive `render(element=None)` degrades to a read-only stem+choices block instead of raising `NoReverseMatch` on the URL.
- The duplicate inner `data-element-id` is dropped — the lesson/preview `<section>` wrapper already carries it (it's what `progress.js` observes); `question.js` scopes on `[data-question]`.
- `selected_ids` repopulation is gated on `element.pk == feedback_for_pk` so only the answered question echoes its selection.

- [ ] **Step 6: Create `templates/courses/elements/_question_feedback.html`**

```django
{% load i18n %}
{% if mark_result %}
  <div class="question__verdict {% if mark_result.correct %}is-correct{% else %}is-incorrect{% endif %}">
    {% if mark_result.correct %}
      <span class="question__glyph" aria-hidden="true">✓</span>{% trans "Correct" %}
    {% else %}
      <span class="question__glyph" aria-hidden="true">✗</span>{% trans "Incorrect" %}
    {% endif %}
  </div>
  <ul class="question__reveal">
    {% for c in choices %}
      <li class="question__reveal-item {% if c.pk in mark_result.reveal %}answer-correct{% endif %}">
        <span>{{ c.text }}</span>
        {% if c.pk in mark_result.reveal %}<span class="question__tick" aria-hidden="true">✓</span>{% endif %}
      </li>
    {% endfor %}
  </ul>
  {% if el.explanation %}
    <div class="question__explanation">{{ el.explanation|safe }}</div>
  {% endif %}
{% endif %}
```

- [ ] **Step 7: Add `build_lesson_context`, refactor `lesson_unit`, add `check_answer` in `courses/views.py`**

Add imports at the top:

```python
from django.db.models import prefetch_related_objects
from django.http import Http404

from courses.htmlsandbox import has_math_delimiters
from courses.marking import MarkResult  # noqa: F401  (documents the return type)
from courses.models import ChoiceQuestionElement
from courses.models import QuestionElement
```

Add the helper and the discriminator, and refactor `lesson_unit` to use the helper (replace the body from the `elements = list(...)` line through the final `render(...)`):

```python
def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def build_lesson_context(node, user):
    """Shared element/has_*/progress context for a LESSON unit. Used by both
    lesson_unit (GET) and check_answer (POST re-render) so the two cannot drift.
    Performs the same UnitProgress.get_or_create + seen-count as a normal view."""
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    # Batch-load choices for any question elements so the math scan + feedback
    # render don't N+1 across questions.
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, ChoiceQuestionElement)
    ]
    if questions:
        prefetch_related_objects(questions, "choices")

    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    question_ct_ids = {ContentType.objects.get_for_model(ChoiceQuestionElement).id}

    def _question_has_math(q):
        if has_math_delimiters(q.stem):
            return True
        return any(has_math_delimiters(c.text) for c in q.choices.all())

    has_math = any(el.content_type_id == math_ct_id for el in elements) or any(
        isinstance(el.content_object, ChoiceQuestionElement)
        and _question_has_math(el.content_object)
        for el in elements
    )
    has_html = any(el.content_type_id == html_ct_id for el in elements)
    has_questions = any(el.content_type_id in question_ct_ids for el in elements)

    progress = None
    seen_ids = set()
    if is_enrolled(user, node.course):
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
    current_ids = [el.pk for el in elements]
    seen_count = len(seen_ids.intersection(current_ids))
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": False,
        "elements": elements,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": has_questions,
        "progress": progress,
        "element_count": len(current_ids),
        "seen_count": seen_count,
    }
```

Replace the `lesson_unit` tail (after the quiz early-return) so it delegates:

```python
@login_required
def lesson_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if node.unit_type == ContentNode.UnitType.QUIZ:
        return render(
            request,
            "courses/lesson_unit.html",
            {"course": course, "unit": node, "is_quiz": True},
        )
    ctx = build_lesson_context(node, request.user)
    ctx.update(feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)
    return render(request, "courses/lesson_unit.html", ctx)
```

Add `check_answer` at the end of the file:

```python
@require_POST
@login_required
def check_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    valid_ids = set(question.choices.values_list("pk", flat=True))
    submitted = set()
    for raw in request.POST.getlist("choice"):
        try:
            submitted.add(int(raw))
        except (TypeError, ValueError):
            continue
    answer = submitted & valid_ids  # drop foreign/forged ids; never error-leak
    result = question.mark(answer)  # NOTHING is persisted

    if _wants_fragment(request):
        return render(
            request,
            "courses/elements/_question_feedback.html",
            {"el": question, "mark_result": result, "choices": list(question.choices.all())},
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    ctx = build_lesson_context(node, request.user)
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=frozenset(answer),
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)
```

Also add `from courses.models import Element` to the imports if not present (it is not in the current `views.py` import block — add it).

- [ ] **Step 8: Add the `check_answer` route to `courses/urls.py`**

Add after the `complete` route:

```python
    path(
        "courses/<slug:slug>/u/<int:node_pk>/q/<int:element_pk>/check/",
        views.check_answer,
        name="check_answer",
    ),
```

- [ ] **Step 9: Pass feedback kwargs to `render_element` in `templates/courses/lesson_unit.html`**

Change the element loop's render call (line 16) from `{% render_element el %}` to:

```django
      <section data-element-id="{{ el.pk }}">{% render_element el feedback_for_pk=feedback_for_pk selected_ids=selected_ids mark_result=mark_result %}</section>
```

(The preview call site in `_preview.html` keeps the bare `{% render_element el %}` — kwargs default to `None`/empty.)

**Design note (exactly one question answered per request):** `check_answer` marks a single element, so there is ever only one `mark_result` / one `feedback_for_pk` per request. The lesson template forwards that single page-level trio to *every* `render_element` call; only the question whose `element.pk == feedback_for_pk` renders feedback (the template gate). This coupling is intentional and correct for the per-question round-trip.

**Sequencing note:** `build_lesson_context` produces `has_questions` now, but the `{% if has_questions %}<script question.js>` include + the question CSS link are intentionally deferred to **Task 5** (the JS/CSS task). Don't wire them here — the consumption tests in this task don't depend on the browser script.

- [ ] **Step 10: Run the consumption tests**

Run: `uv run pytest tests/test_questions_consumption.py -q`
Expected: PASS (9 tests).

- [ ] **Step 11: Run the full courses suite to confirm no regression**

Run: `uv run pytest tests/test_courses_views.py tests/test_courses_progress.py tests/test_courses_elements.py -q`
Expected: PASS (the `lesson_unit` refactor preserves existing behavior).

- [ ] **Step 12: Commit**

```bash
git add courses/models.py courses/templatetags/courses_extras.py courses/views.py courses/urls.py templates/courses/elements/choicequestion.html templates/courses/elements/_question_feedback.html templates/courses/lesson_unit.html tests/test_questions_consumption.py
git commit -m "feat(2a): student consumption — render + check_answer marking + feedback"
```

---

### Task 3: Authoring forms — `ChoiceQuestionElementForm` + `Choice` formset + `FORM_FOR_TYPE`

**Files:**
- Modify: `courses/element_forms.py`
- Test: `tests/test_questions_forms.py`

**Interfaces:**
- Consumes: `ChoiceQuestionElement`, `Choice` (Task 1).
- Produces:
  - `ChoiceQuestionElementForm` — ModelForm (`stem`, `explanation`, `multiple`); `multiple` removed from fields when editing an existing instance.
  - `ChoiceFormSet = inlineformset_factory(...)` and a `build_choice_formset(data=None, instance=None)` helper returning a bound/unbound formset with the custom-clean rules.
  - `FORM_FOR_TYPE["choicequestion"] = ChoiceQuestionElementForm`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_questions_forms.py`:

```python
import pytest

from courses.element_forms import ChoiceQuestionElementForm, build_choice_formset
from courses.element_forms import FORM_FOR_TYPE


def _formset_data(rows, *, prefix="choices"):
    """rows: list of (text, is_correct_bool). Builds management-form + row POST data."""
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": "0",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for i, (text, correct) in enumerate(rows):
        data[f"{prefix}-{i}-text"] = text
        if correct:
            data[f"{prefix}-{i}-is_correct"] = "on"
    return data


@pytest.mark.django_db
def test_form_in_registry_and_has_multiple_on_create():
    assert FORM_FOR_TYPE["choicequestion"] is ChoiceQuestionElementForm
    form = ChoiceQuestionElementForm(initial={"multiple": True})
    assert "multiple" in form.fields


@pytest.mark.django_db
def test_form_drops_multiple_field_on_edit():
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="x", multiple=True)
    form = ChoiceQuestionElementForm(instance=q)
    assert "multiple" not in form.fields  # pinned: a bound POST cannot flip it


@pytest.mark.django_db
def test_formset_requires_two_choices():
    fs = build_choice_formset(data=_formset_data([("only one", True)]))
    assert not fs.is_valid()


@pytest.mark.django_db
def test_formset_requires_at_least_one_correct():
    fs = build_choice_formset(data=_formset_data([("a", False), ("b", False)]))
    assert not fs.is_valid()


@pytest.mark.django_db
def test_single_choice_requires_exactly_one_correct():
    # multiple=False context: two correct is invalid
    fs = build_choice_formset(
        data=_formset_data([("a", True), ("b", True)]), multiple=False
    )
    assert not fs.is_valid()


@pytest.mark.django_db
def test_multiple_choice_allows_two_correct():
    fs = build_choice_formset(
        data=_formset_data([("a", True), ("b", True)]), multiple=True
    )
    assert fs.is_valid(), fs.non_form_errors()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_questions_forms.py -q`
Expected: FAIL — `ImportError: cannot import name 'ChoiceQuestionElementForm'`.

- [ ] **Step 3: Implement the form + formset in `courses/element_forms.py`**

Add imports at the top:

```python
from django.forms import inlineformset_factory

from courses.models import Choice
from courses.models import ChoiceQuestionElement
```

Add the form, the base formset class (custom `clean()`), the factory, and a builder helper:

```python
class ChoiceQuestionElementForm(forms.ModelForm):
    class Meta:
        model = ChoiceQuestionElement
        fields = ["stem", "explanation", "multiple"]
        widgets = {
            "stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""}),
            "explanation": forms.Textarea(attrs={"rows": 2, "data-rte-source": ""}),
            "multiple": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `multiple` is fixed at creation by the add-card and pinned on edit: drop it
        # from an edit form so a tampered hidden POST value cannot flip single<->multi.
        if self.instance.pk is not None:
            self.fields.pop("multiple", None)


class BaseChoiceFormSet(forms.BaseInlineFormSet):
    """Single source of truth for the choice-count rules (counts only non-deleted,
    non-empty rows; min_num/validate_min are NOT used — they miscount DELETE/empty
    extra rows). `self.multiple` is injected by build_choice_formset."""

    multiple = False

    def clean(self):
        super().clean()
        if any(self.errors):
            return  # intentional: a per-row field error already blocks the save, so the
                    # count/correctness rules below are skipped until rows are individually valid
        kept = [
            f
            for f in self.forms
            if f.cleaned_data
            and not f.cleaned_data.get("DELETE")
            and f.cleaned_data.get("text")
        ]
        if len(kept) < 2:
            raise forms.ValidationError(_("Add at least two choices."))
        correct = [f for f in kept if f.cleaned_data.get("is_correct")]
        if not correct:
            raise forms.ValidationError(_("Mark at least one choice correct."))
        if not self.multiple and len(correct) != 1:
            raise forms.ValidationError(
                _("A single-choice question needs exactly one correct choice.")
            )


ChoiceFormSet = inlineformset_factory(
    ChoiceQuestionElement,
    Choice,
    formset=BaseChoiceFormSet,
    fields=["text", "is_correct"],
    extra=2,
    can_delete=True,
)


def build_choice_formset(*, data=None, files=None, instance=None, multiple=None, prefix="choices"):
    """Construct the Choice inline formset with the multiple-aware clean() rule.
    Shared by the render-only and save paths so validation cannot drift. When
    `multiple` is not passed, derive it from a saved instance (the edit path uses the
    stored value); a brand-new/unsaved instance defaults to single (False)."""
    if multiple is None:
        multiple = bool(instance.multiple) if (instance is not None and instance.pk) else False
    fs = ChoiceFormSet(data=data, files=files, instance=instance, prefix=prefix)
    fs.multiple = multiple
    return fs
```

Add `from django.utils.translation import gettext_lazy as _` to the imports if not present. (This is the single, final definition — callers either pass `multiple=` explicitly or rely on the instance-derivation.)

Register the type key (extend the existing `FORM_FOR_TYPE` dict):

```python
FORM_FOR_TYPE = {
    "text": TextElementForm,
    "image": ImageElementForm,
    "video": VideoElementForm,
    "iframe": IframeElementForm,
    "math": MathElementForm,
    "html": HtmlElementForm,
    "choicequestion": ChoiceQuestionElementForm,
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_questions_forms.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py tests/test_questions_forms.py
git commit -m "feat(2a): ChoiceQuestionElementForm + Choice inline formset + registry"
```

---

### Task 4: Authoring wiring + editor template

**Files:**
- Modify: `courses/builder.py` (`ElementFormInvalid.__init__`; `save_element` formset sequence)
- Modify: `courses/views_manage.py` (`_render_open_form` gains `initial`/`formset`; `element_add`/`element_save` allowlist + add-key translation; `element_form` formset; the 422 branch threads the formset)
- Create: `templates/courses/manage/editor/_rte_toolbar.html` (shared toolbar partial)
- Create: `templates/courses/manage/editor/_edit_choicequestion.html`
- Modify: `templates/courses/manage/editor/_add_menu.html` (two cards)
- Modify (only if it binds a single source): `courses/static/courses/js/text_toolbar.js` (iterate all `[data-rte-source]` — see Step 8)
- Test: `tests/test_questions_authoring.py`

(`_host_form.html` needs no change — it already includes `_edit_<type_key>.html` and passes the shared render context, which now carries `formset`/`is_multiple`.)

**Interfaces:**
- Consumes: `ChoiceQuestionElementForm`, `build_choice_formset`, `FORM_FOR_TYPE` (Task 3); `save_element`, `ElementFormInvalid`, `_locked_unit`, `_locked_element_in_unit` (existing builder); `_render_open_form`, `_wants_fragment` (existing views_manage).
- Produces: authoring a `ChoiceQuestionElement` end-to-end (add → save creates question + choices atomically; edit; 422 re-render with bound pair; delete via `builder.delete_element`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_questions_authoring.py`:

```python
import pytest
from django.urls import reverse

from courses.models import ChoiceQuestionElement, Choice, Element
from tests.factories import ContentNodeFactory, CourseFactory, make_pa


def _unit(course):
    return ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")


def _save_payload(unit, *, multiple, rows, element="new"):
    """rows: list of (text, correct_bool)."""
    data = {
        "ctx": "editor",
        "type": "choicequestion",
        "element": element,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "stem": "<p>Pick</p>",
        "explanation": "",
        "multiple": "on" if multiple else "",
        "choices-TOTAL_FORMS": str(len(rows)),
        "choices-INITIAL_FORMS": "0",
        "choices-MIN_NUM_FORMS": "0",
        "choices-MAX_NUM_FORMS": "1000",
    }
    for i, (text, correct) in enumerate(rows):
        data[f"choices-{i}-text"] = text
        if correct:
            data[f"choices-{i}-is_correct"] = "on"
    return data


@pytest.mark.django_db
def test_add_choicequestion_is_render_only(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "choice-single", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b"choices-TOTAL_FORMS" in resp.content  # the formset's management form rendered
    assert Element.objects.filter(unit=unit).count() == 0  # nothing persisted


@pytest.mark.django_db
def test_save_creates_question_and_choices_atomically(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _save_payload(unit, multiple=False, rows=[("4", True), ("5", False)]),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    q = ChoiceQuestionElement.objects.get()
    assert q.multiple is False
    assert q.choices.count() == 2
    assert Element.objects.filter(unit=unit, object_id=q.pk).count() == 1


@pytest.mark.django_db
def test_save_invalid_formset_returns_422_and_persists_nothing(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _save_payload(unit, multiple=False, rows=[("only one", True)]),  # < 2 choices
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert ChoiceQuestionElement.objects.count() == 0  # atomic rollback
    assert Choice.objects.count() == 0


@pytest.mark.django_db
def test_edit_cannot_flip_multiple_via_tampered_post(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    q = ChoiceQuestionElement.objects.create(stem="<p>q</p>", multiple=False)
    a = Choice.objects.create(question=q, text="a", is_correct=True)
    b = Choice.objects.create(question=q, text="b", is_correct=False)
    el = Element.objects.create(unit=unit, content_object=q)
    unit.refresh_from_db()
    payload = _save_payload(
        unit, multiple=True, rows=[("a", True), ("b", True)], element=str(el.pk)
    )
    payload["choices-INITIAL_FORMS"] = "2"
    payload["choices-0-id"] = a.pk
    payload["choices-1-id"] = b.pk
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        payload,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    # multiple is pinned server-side → still single → "two correct" is invalid → 422
    assert resp.status_code == 422
    q.refresh_from_db()
    assert q.multiple is False
    # atomic rollback: the stored choices are untouched by the rejected edit
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.is_correct is True and b.is_correct is False
    assert q.choices.count() == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_questions_authoring.py -q`
Expected: FAIL — `element_add` returns 400 for `choice-single` (`bad type`).

- [ ] **Step 3: Change `ElementFormInvalid` in `courses/builder.py`**

```python
class ElementFormInvalid(Exception):
    """Carries the bound, invalid per-type form (with its instance) — and, for question
    types, the bound Choice formset — so the view re-renders the SAME bound pair at 422."""

    def __init__(self, form, formset=None):
        self.form = form
        self.formset = formset
        super().__init__("element form invalid")
```

- [ ] **Step 4: Extend `save_element` in `courses/builder.py` for the formset**

In `save_element`, replace the **exact span** from `extra = {"course": course} if type_key in ("image", "video") else {}` (currently line ~216) through the final `return unit` (line ~233) with the block below. Everything above that span — `unit = _locked_unit(...)`, `_check_token(...)`, and the `if element_ref == "new": join, instance = None, None` / `else: join = _locked_element_in_unit(...); instance = join.content_object` block — is **UNCHANGED**:

```python
    if type_key == "choicequestion":
        from courses.element_forms import ChoiceQuestionElementForm, build_choice_formset

        is_create = join is None
        # multiple authority: from POST on create; pinned to the stored value on edit.
        multiple = bool(post_data.get("multiple")) if is_create else instance.multiple
        form = ChoiceQuestionElementForm(data=post_data, instance=instance)
        formset = build_choice_formset(
            data=post_data, files=files, instance=instance, multiple=multiple
        )
        if not form.is_valid() or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save(commit=False)
        obj.multiple = multiple  # enforce the pinned value (field absent on the edit form)
        obj.save()
        formset.instance = obj
        formset.save()
    else:
        extra = {"course": course} if type_key in ("image", "video") else {}
        form = FORM_FOR_TYPE[type_key](
            data=post_data, files=files, instance=instance, **extra
        )
        if not form.is_valid():
            raise ElementFormInvalid(form)
        obj = form.save()  # concrete row saved (TextElement.save sanitises)
    title = (post_data.get("el_title") or "").strip()
    if join is None:
        Element.objects.create(unit=unit, content_object=obj, title=title)
    elif join.title != title:
        join.title = title
        join.save(update_fields=["title"])
    unit.save(update_fields=["updated"])
    return unit
```

The `else` branch is the original non-question logic verbatim; only the shared tail (`title`/join-row/`unit.save`) — which already existed — and the new `choicequestion` branch are introduced.

- [ ] **Step 5: Extend `_render_open_form` in `courses/views_manage.py`**

Change its signature and form/formset construction:

```python
def _render_open_form(
    request, unit, type_key, element_pk="new", form=None, formset=None,
    initial=None, status=200,
):
    """Render the host <form> wrapping a per-type editor partial, then the full editor
    scope with that form embedded in the form host."""
    from courses.element_forms import FORM_FOR_TYPE, build_choice_formset

    if form is None:
        extra = {"course": unit.course} if type_key in ("image", "video") else {}
        form = FORM_FOR_TYPE[type_key](initial=initial or {}, **extra)
    # Compute a SINGLE authoritative is_multiple for the template (radio vs checkbox),
    # rather than letting the template derive it from bound/unbound form attrs (fragile).
    is_multiple = False
    if type_key == "choicequestion":
        if form.instance.pk:
            is_multiple = form.instance.multiple          # edit: the stored value
        elif initial:
            is_multiple = bool(initial.get("multiple"))    # fresh add: the card's seed
        elif form.is_bound:
            is_multiple = bool(form.data.get("multiple"))  # 422 re-render of a create
        if formset is None:
            instance = form.instance if form.instance.pk else None
            formset = build_choice_formset(instance=instance)
    # current author label for an existing element (blank for a new one)
    el_title = ""
    if element_pk != "new":
        el_title = (
            Element.objects.filter(pk=element_pk, unit=unit)
            .values_list("title", flat=True)
            .first()
            or ""
        )
    unit.refresh_from_db(fields=["updated"])
    form_html = render(
        request,
        "courses/manage/editor/_host_form.html",
        {
            "course": unit.course,
            "unit": unit,
            "type_key": type_key,
            "element_pk": element_pk,
            "form": form,
            "formset": formset,
            "is_multiple": is_multiple,
            "el_title": el_title,
        },
    ).content.decode()
    return _render_editor_fragments(
        request, unit, status=status, open_form=form_html,
        open_form_pk=str(element_pk), refresh=False,
    )
```

- [ ] **Step 6: Update `element_add`, `element_save`, `element_form` in `courses/views_manage.py`**

`element_add` (add-key translation + allowlist + `initial` seed):

```python
@login_required
def element_add(request, slug):
    course = _require_manage(request, slug)
    raw = request.POST.get("type")
    initial = None
    if raw in ("choice-single", "choice-multi"):
        initial = {"multiple": raw == "choice-multi"}
        type_key = "choicequestion"
    else:
        type_key = raw
    if type_key not in ("text", "image", "video", "iframe", "math", "html", "choicequestion"):
        return HttpResponseBadRequest("bad type")
    unit = get_object_or_404(
        ContentNode, pk=request.POST.get("unit"), course=course, kind=ContentNode.Kind.UNIT
    )
    return _render_open_form(request, unit, type_key, element_pk="new", initial=initial)
```

`element_save` (allowlist + thread `e.formset` on 422):

```python
@login_required
def element_save(request, slug):
    course = _require_manage(request, slug)
    type_key = request.POST.get("type")
    if type_key not in ("text", "image", "video", "iframe", "math", "html", "choicequestion"):
        return HttpResponseBadRequest("bad type")
    element_ref = request.POST.get("element", "new")
    unit_pk = request.POST.get("unit")
    try:
        unit = builder_svc.save_element(
            course, unit_pk, type_key, element_ref, request.POST, request.FILES
        )
    except builder_svc.ConflictError:
        unit = ContentNode.objects.filter(
            pk=unit_pk, course=course, kind=ContentNode.Kind.UNIT
        ).first()
        if unit is None:
            return _render_tree(request, course, status=409)
        if not _wants_fragment(request):
            return redirect(f"{_editor_path(course, unit)}?changed=1")
        return _render_editor_fragments(request, unit, status=409)
    except builder_svc.ElementFormInvalid as e:
        unit = ContentNode.objects.filter(
            pk=unit_pk, course=course, kind=ContentNode.Kind.UNIT
        ).first()
        if unit is None:
            return _render_tree(request, course, status=409)
        return _render_open_form(
            request, unit, type_key, element_pk=element_ref,
            form=e.form, formset=e.formset, status=422,
        )
    if not _wants_fragment(request):
        return redirect(_editor_path(course, unit))
    return _render_editor_fragments(request, unit)
```

`element_form` (build the instance-bound formset for editing):

```python
@login_required
def element_form(request, slug, pk):
    course = _require_manage(request, slug)
    el = get_object_or_404(Element, pk=pk, unit__course=course)
    type_key = el.content_object.__class__.__name__.lower().replace("element", "")
    from courses.element_forms import FORM_FOR_TYPE, build_choice_formset

    extra = {"course": course} if type_key in ("image", "video") else {}
    form = FORM_FOR_TYPE[type_key](instance=el.content_object, **extra)
    formset = None
    if type_key == "choicequestion":
        formset = build_choice_formset(instance=el.content_object)
    return _render_open_form(
        request, el.unit, type_key, element_pk=pk, form=form, formset=formset
    )
```

- [ ] **Step 7: Create the RTE toolbar partial + the question editor partial**

First create `templates/courses/manage/editor/_rte_toolbar.html` — the toolbar button set copied verbatim from the `<div class="rte-toolbar" data-rte-toolbar>…</div>` block in `_edit_text.html`. Extracting it lets the question editor reuse the exact toolbar for two RTE surfaces:

```django
{% load i18n %}
<div class="rte-toolbar" data-rte-toolbar>
  <button type="button" class="rte-btn" data-cmd="bold" title="{% trans 'Bold' %}" aria-label="{% trans 'Bold' %}"><svg class="ic"><use href="#ed-bold"/></svg></button>
  <button type="button" class="rte-btn" data-cmd="italic" title="{% trans 'Italic' %}" aria-label="{% trans 'Italic' %}"><svg class="ic"><use href="#ed-italic"/></svg></button>
  <button type="button" class="rte-btn" data-cmd="underline" title="{% trans 'Underline' %}" aria-label="{% trans 'Underline' %}"><svg class="ic"><use href="#ed-underline"/></svg></button>
  <span class="rte-sep"></span>
  <button type="button" class="rte-btn rte-btn--text" data-cmd="h2" title="{% trans 'Heading 2' %}">H2</button>
  <button type="button" class="rte-btn rte-btn--text" data-cmd="h3" title="{% trans 'Heading 3' %}">H3</button>
  <button type="button" class="rte-btn rte-btn--text" data-cmd="h4" title="{% trans 'Heading 4' %}">H4</button>
  <span class="rte-sep"></span>
  <button type="button" class="rte-btn" data-cmd="ul" title="{% trans 'Bullet list' %}" aria-label="{% trans 'Bullet list' %}"><svg class="ic"><use href="#ed-ul"/></svg></button>
  <button type="button" class="rte-btn" data-cmd="ol" title="{% trans 'Numbered list' %}" aria-label="{% trans 'Numbered list' %}"><svg class="ic"><use href="#ed-ol"/></svg></button>
  <button type="button" class="rte-btn" data-cmd="link" title="{% trans 'Link' %}" aria-label="{% trans 'Link' %}"><svg class="ic"><use href="#ed-link"/></svg></button>
  <button type="button" class="rte-btn" data-cmd="blockquote" title="{% trans 'Quote' %}" aria-label="{% trans 'Quote' %}"><svg class="ic"><use href="#ed-quote"/></svg></button>
  <button type="button" class="rte-btn" data-cmd="code" title="{% trans 'Code' %}" aria-label="{% trans 'Code' %}"><svg class="ic"><use href="#ed-code"/></svg></button>
</div>
```

(Optionally refactor `_edit_text.html` to `{% include %}` this same partial — not required for 2a.)

Then create `templates/courses/manage/editor/_edit_choicequestion.html`. **Each rich-text field is wrapped in its OWN `.el-editor--text` container** so the existing `text_toolbar.js` `wireRte` — which resolves a source's toolbar via `closest(".el-editor--text")` — binds each surface to its own toolbar (stem and explanation never share one):

```django
{% load i18n %}
<div class="el-editor el-editor--question">
  {% if form.multiple %}{{ form.multiple }}{% endif %}{# hidden multiple seed; field absent on edit #}

  <label class="el-editor__label">{% trans "Question" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="stem" class="rte-source" data-rte-source rows="3">{{ form.stem.value|default:"" }}</textarea>
  </div>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Choices" %}</label>
  {{ formset.management_form }}
  <ul class="choice-rows" data-choice-rows>
    {% for f in formset %}
      <li class="choice-row">
        {{ f.id }}
        <input type="{% if is_multiple %}checkbox{% else %}radio{% endif %}"
               name="{{ f.is_correct.html_name }}" {% if f.is_correct.value %}checked{% endif %}
               aria-label="{% trans 'Correct' %}">
        {{ f.text }}
        {% if formset.can_delete %}
          <label class="choice-row__del">{{ f.DELETE }} {% trans "Remove" %}</label>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
  {% for e in formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <label class="el-editor__label">{% trans "Explanation (optional)" %}</label>
  <div class="el-editor--text">
    {% include "courses/manage/editor/_rte_toolbar.html" %}
    <textarea name="explanation" class="rte-source" data-rte-source rows="2">{{ form.explanation.value|default:"" }}</textarea>
  </div>
</div>
```

Notes:
- `is_multiple` is the single authoritative value computed in `_render_open_form` (Step 5); the template never derives radio/checkbox from bound/unbound form state.
- For **single**-choice the per-row correct markers render as `radio` sharing the formset's `is_correct` html names; the browser enforces one selection and the server's formset `clean()` is the validation authority regardless.

- [ ] **Step 8: Confirm the formset reaches the partial and `text_toolbar.js` binds every RTE surface**

`_host_form.html`: no change needed — `_edit_choicequestion.html` reads `formset`/`is_multiple` from the shared render context that `_render_open_form` (Step 5) now passes.

`courses/static/courses/js/text_toolbar.js`: read the file. Each rich-text field in the question editor sits in its own `.el-editor--text` wrapper (Step 7), so a source resolves its own toolbar via `closest(".el-editor--text")`. Confirm `wireRte` runs for **every** `[data-rte-source]` on the page — i.e. the entry point iterates `document.querySelectorAll("[data-rte-source]")` (not a single `querySelector`). If it currently binds only the first match, change the entry point to:

```javascript
document.querySelectorAll("[data-rte-source]").forEach(wireRte);
```

No change is needed if it already iterates all sources. (The earlier-suspected toolbar-sharing bug is avoided structurally by the per-field `.el-editor--text` wrappers — `closest()` resolves each source to its own toolbar.)

- [ ] **Step 9: Add the two add-menu cards in `templates/courses/manage/editor/_add_menu.html`**

Add after the HTML card (line 10):

```django
    <button type="button" class="typecard" data-add-type="choice-single"><span class="ic">◉</span>{% trans "Single choice" %}</button>
    <button type="button" class="typecard" data-add-type="choice-multi"><span class="ic">☑</span>{% trans "Multiple choice" %}</button>
```

- [ ] **Step 10: Run the authoring tests**

Run: `uv run pytest tests/test_questions_authoring.py -q`
Expected: PASS (4 tests).

- [ ] **Step 11: Run the broader authoring suite for regressions**

Run: `uv run pytest tests/test_element_add_save.py tests/test_element_editor_ops.py tests/test_manage_element_ops.py -q`
Expected: PASS (the `ElementFormInvalid(form, formset=None)` default and the `else` branch keep the six existing types unchanged).

- [ ] **Step 12: Commit**

```bash
git add courses/builder.py courses/views_manage.py templates/courses/manage/editor/_rte_toolbar.html templates/courses/manage/editor/_edit_choicequestion.html templates/courses/manage/editor/_add_menu.html tests/test_questions_authoring.py
# include text_toolbar.js in the add only if Step 8 required a change
git commit -m "feat(2a): author choice questions via the editor (formset wiring + add cards)"
```

---

### Task 5: `question.js` (submit + inline math) + styles

**Files:**
- Create: `courses/static/courses/js/question.js`
- Modify: `courses/static/courses/css/courses.css` (question + feedback styles)
- Modify: `templates/courses/lesson_unit.html` (load `auto-render.min.js` under `has_math`; load `question.js` under `has_questions`)
- Test: covered by the Task 7 Playwright e2e (JS behavior + math rendering are browser-tested).

**Interfaces:**
- Consumes: the `[data-question] form` markup + `[data-question-feedback]` slot (Task 2); `check_answer` endpoint (Task 2); the vendored `courses/static/courses/vendor/katex/contrib/auto-render.min.js` (already in the repo — the same file `htmlsandbox` loads).
- Produces: PE submit interception that swaps `_question_feedback.html` in, plus inline KaTeX rendering of question stems/choices/feedback.

**Why math needs handling here:** `math.js`'s `window.libliRenderMath` renders only `[data-katex]` blocks in *display* mode (the 1a MathElement). Question stems/choices carry **inline** `\(…\)` math mixed with text, which needs KaTeX's `renderMathInElement` (auto-render) — a different entry point. `build_lesson_context`'s scan sets `has_math` when a question has delimiters (Task 2), so `auto-render.min.js` loads; `question.js` then renders the inline math (guarded — a no-op if auto-render isn't present).

- [ ] **Step 1: Create `courses/static/courses/js/question.js`**

```javascript
(function () {
  "use strict";
  var Q_DELIMS = [
    { left: "\\(", right: "\\)", display: false },
    { left: "\\[", right: "\\]", display: true },
  ];
  function renderQ(root) {
    // Inline math for a question subtree (stem/choices) or a swapped feedback slot.
    // No-op if auto-render.min.js wasn't loaded (question without math).
    if (typeof renderMathInElement !== "function" || !root) return;
    try {
      renderMathInElement(root, { delimiters: Q_DELIMS, throwOnError: false });
    } catch (e) { /* leave raw LaTeX on error */ }
  }
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }
  var questions = document.querySelectorAll("[data-question]");
  questions.forEach(renderQ);  // initial inline-math pass over stems/choices
  questions.forEach(function (q) {
    var form = q.querySelector("form");
    if (!form) return;  // a join-row-less render has no form (Task 2 guard)
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var slot = q.querySelector("[data-question-feedback]");
      fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
        body: new FormData(form),
      })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          if (!slot) return;
          slot.innerHTML = html;
          renderQ(slot);  // typeset revealed-choice / explanation math
        })
        .catch(function () { /* leave the form intact on network error */ });
    });
  });
})();
```

- [ ] **Step 2: Add question + feedback styles to `courses/static/courses/css/courses.css`**

Append token-driven styles (match the existing `.el`/`.btn` vocabulary):

```css
.el--question .question__stem { margin-bottom: var(--space-3); }
.el--question .question__choices { list-style: none; padding: 0; margin: 0 0 var(--space-3); }
.el--question .question__choice { margin: var(--space-1) 0; }
.el--question .question__feedback:empty { display: none; }
.el--question .question__verdict.is-correct { color: var(--color-success, #1a7f4b); }
.el--question .question__verdict.is-incorrect { color: var(--color-danger, #b3261e); }
.el--question .question__reveal { list-style: none; padding: 0; margin: var(--space-2) 0; }
.el--question .question__reveal-item.answer-correct { font-weight: 600; }
```

- [ ] **Step 3: Load auto-render + question.js in `templates/courses/lesson_unit.html`**

The `{% block extra_js %}` `has_math` block currently loads `katex.min.js` + `math.js`. Insert `auto-render.min.js` **between** them (so `renderMathInElement` exists), and add the `question.js` include after the `has_html` line:

```django
  {% if has_math %}
    <script src="{% static 'courses/vendor/katex/katex.min.js' %}" defer></script>
    <script src="{% static 'courses/vendor/katex/contrib/auto-render.min.js' %}" defer></script>
    <script src="{% static 'courses/js/math.js' %}" defer></script>
  {% endif %}
  {% if has_html %}<script src="{% static 'courses/js/html_element.js' %}" defer></script>{% endif %}
  {% if has_questions %}<script src="{% static 'courses/js/question.js' %}" defer></script>{% endif %}
```

Order matters: `katex.min.js` → `auto-render.min.js` → `math.js`; all `defer` scripts run in document order, and `question.js` (after the `has_math` block) sees `renderMathInElement` already defined. **Editor-preview parity (note):** question math in the editor's live preview will render the same way once the editor page also loads `auto-render.min.js` + `question.js`; that small wiring is a follow-up — the 2a DoD asserts the **lesson** page (the student-facing spec requirement).

- [ ] **Step 4: Verify collectstatic picks up the new file**

Run: `uv run python manage.py collectstatic --noinput`
Expected: includes `courses/js/question.js` (no manifest error).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/question.js courses/static/courses/css/courses.css templates/courses/lesson_unit.html
git commit -m "feat(2a): question.js fragment-swap + inline question math + styles"
```

---

### Task 6: i18n — Polish strings + per-msgid gate

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)
- Test: `tests/test_i18n_questions.py`

**Interfaces:**
- Consumes: every `{% trans %}`/`gettext` string added in Tasks 2–5.

- [ ] **Step 1: Write the failing gate test**

Create `tests/test_i18n_questions.py`:

```python
from django.utils import translation


REQUIRED_MSGIDS = [
    "Check",
    "Correct",
    "Incorrect",
    "Single choice",
    "Multiple choice",
    "Question",
    "Choices",
    "Explanation (optional)",
    "Remove",
    "Add at least two choices.",
    "Mark at least one choice correct.",
    "A single-choice question needs exactly one correct choice.",
]


def test_question_strings_have_polish_translations():
    # Robust against fuzzy flags / multiline msgids: gettext at runtime ignores fuzzy
    # entries (returns the msgid) and uses the COMPILED catalog, so this asserts a real,
    # non-fuzzy Polish translation exists for each string. Requires compilemessages (Step 5).
    with translation.override("pl"):
        for msgid in REQUIRED_MSGIDS:
            translated = translation.gettext(msgid)
            assert translated != msgid, f"missing/fuzzy Polish translation for: {msgid}"
```

Note: this test reads the **compiled** `.mo`, so it only passes after Step 5's `compilemessages`. Run order matters — Step 2 (fail) is before extraction; Step 5 compiles then re-runs.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_i18n_questions.py -q`
Expected: FAIL (msgids not yet extracted/translated).

- [ ] **Step 3: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
Expected: new `msgid` entries appear in `locale/pl/LC_MESSAGES/django.po` with empty `msgstr ""`.

- [ ] **Step 4: Fill in the Polish translations**

Edit `locale/pl/LC_MESSAGES/django.po`, setting each new `msgstr`:

```
msgid "Check"            -> msgstr "Sprawdź"
msgid "Correct"          -> msgstr "Poprawnie"
msgid "Incorrect"        -> msgstr "Niepoprawnie"
msgid "Single choice"    -> msgstr "Jednokrotny wybór"
msgid "Multiple choice"  -> msgstr "Wielokrotny wybór"
msgid "Question"         -> msgstr "Pytanie"
msgid "Choices"          -> msgstr "Odpowiedzi"
msgid "Explanation (optional)" -> msgstr "Wyjaśnienie (opcjonalne)"
msgid "Add at least two choices." -> msgstr "Dodaj co najmniej dwie odpowiedzi."
msgid "Mark at least one choice correct." -> msgstr "Zaznacz co najmniej jedną poprawną odpowiedź."
msgid "A single-choice question needs exactly one correct choice." -> msgstr "Pytanie jednokrotnego wyboru wymaga dokładnie jednej poprawnej odpowiedzi."
```

(Also translate any other new strings `makemessages` surfaces — `remove`, `Correct` aria-label, etc.)

- [ ] **Step 5: Compile and run the gate**

```bash
uv run python manage.py compilemessages -l pl
uv run pytest tests/test_i18n_questions.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_questions.py
git commit -m "i18n(2a): Polish strings for choice questions"
```

---

### Task 7: Playwright e2e + DoD gate

**Files:**
- Create: `tests/test_e2e_questions.py`

**Interfaces:**
- Consumes: the full stack (Tasks 1–6). Follows the established e2e pattern (`tests/test_e2e_html_element.py`, `tests/test_e2e_editor.py`): `live_server`, `pytest.mark.e2e`, the session-scoped `DJANGO_ALLOW_ASYNC_UNSAFE` autouse fixture inside the e2e module.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_questions.py` following the exact harness of `tests/test_e2e_html_element.py` (copy its imports, markers, and the `DJANGO_ALLOW_ASYNC_UNSAFE` autouse fixture). Cover:

```python
# Pseudocode of the scenarios to implement against the real harness:
#
# test_author_and_answer_single_choice_js:
#   - make_pa, create a course + lesson unit (use the seed/factory helpers the other
#     e2e tests use, or author via the builder UI).
#   - As PA in the editor: open the add-menu, click "Single choice", fill stem,
#     two choices (mark one correct), Save. Assert the element appears in the preview.
#   - As an enrolled student: open the lesson, select the WRONG choice, click "Check".
#     Assert (JS path, no reload) the feedback slot shows "Incorrect", reveals the
#     correct choice, and shows the explanation if set.
#   - Select the correct choice, Check again → "Correct".
#
# test_question_inline_math_renders (C2 verification):
#   - Author a single-choice question whose stem or a choice contains inline math,
#     e.g. "What is \\(x^2\\)?" / a choice "\\(x^2\\)".
#   - As a student, open the lesson and assert KaTeX rendered: the question container
#     has a `.katex` node (page.locator("[data-question] .katex").count() > 0).
#     This proves auto-render + question.js inline rendering work end-to-end.
#
# test_answer_multiple_choice_no_js:
#   - With JS disabled in the browser context (context = browser.new_context(java_script_enabled=False)),
#     submit the form → full page reload → the answered question shows "Correct"/"Incorrect"
#     inline and OTHER questions on the page show no correctness signal.
```

Implement the two tests concretely using the page-object/locator style already in `tests/test_e2e_editor.py` (scope submit buttons past the shell header per the recurring gotcha).

- [ ] **Step 2: Run the e2e tests**

Run: `uv run pytest tests/test_e2e_questions.py -m e2e -q`
Expected: PASS (2 tests, Chromium).

- [ ] **Step 3: Run the full DoD gate**

```bash
uv run pytest -q                                  # default suite (e2e excluded)
uv run pytest -m e2e -q                            # all e2e
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py collectstatic --noinput
uv run python manage.py compilemessages -l pl
```
Expected: all green; `makemigrations --check` reports no changes; exactly one new migration (`0013`) in the tree.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_questions.py
git commit -m "test(2a): Playwright e2e — author + answer choice questions (JS + no-JS)"
```

---

## Self-Review notes (author)

- **Spec coverage:** §2.1–2.3 → Task 1; §3.4/§3.5 render + check_answer → Task 2; §3.6 has_questions/KaTeX/progress → Task 2 (`build_lesson_context`); §3.1 forms → Task 3; §3.2 authoring seam (allowlist, add-key, formset sites, multiple authority, ElementFormInvalid, 422 threading, templates) → Tasks 3+4; §3.4 no-leak + §4 security → Tasks 1/2 tests; §5 tests → distributed; e2e + DoD → Task 7. All sections map to a task.
- **Deviation flagged:** the spec sketched `render(self, *, feedback_for_pk=..., selected_ids=..., mark_result=...)`; the plan adds an `element=` kwarg (the join-row) because the concrete object needs the unit + join-row pk for the form `action` URL and the per-element feedback gate (the spec's render signature was explicitly "the plan finalizes"). The tag forwards it, mirroring `HtmlElement.render(unit, course)`.
- **Deviation flagged:** `_question_feedback.html` is feedback-only (verdict + reveal + explanation); the retry form lives in `choicequestion.html`. The JS path swaps the feedback partial into `[data-question-feedback]`; the no-JS path `{% include %}`s the same partial into that slot — one partial, both transports, per §3.5.
- **RTE multi-instance:** the question editor has two `data-rte-source` textareas (stem + explanation); Task 4 Step 8 verifies/extends `text_toolbar.js` to bind per-instance rather than the first match.
