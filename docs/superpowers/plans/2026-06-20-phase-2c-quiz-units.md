# Phase 2c — Quiz Units & Response Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `unit_type=quiz` live — students answer question elements per-question with immediate (withhold-gated) feedback, now persisted, attempt-capped and scored, then "Finish quiz" to lock and see their own results.

**Architecture:** Reuse the 2a/2b question/marking stack (`QuestionElement.mark()`, `build_answer()`, `render()`, the `fetch`+`X-CSRFToken` transport). Add three fields to the `QuestionElement` base (`marking_mode`, `max_attempts`, `max_marks`) and three persistence models (`QuizSubmission` → `QuestionResponse` → `Attempt`). Four new student-facing views (`quiz_unit`, `quiz_answer`, `quiz_finish`, `quiz_results`) mirror the existing `lesson_unit`/`check_answer` pair. Scoring math lives in a pure, unit-tested `courses/scoring.py`. The quiz-vs-lesson rendering difference is a `mode` flag threaded through `render_element` → `QuestionElement.render()`; per-type element templates are parameterized (form action URL + feedback partial) but otherwise unchanged.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, pytest + factory_boy, Playwright (e2e), bespoke CSS (no framework). Server-rendered; progressive-enhancement JS.

## Global Constraints

- **No new dependency.** Reuse Django, `courses.marking` (`MarkResult`, `mark()`), the `fetch`+`X-CSRFToken` transport, the `render_element` dispatch.
- **No-leak invariant:** accepted answers / `reveal` reach the client ONLY in a revealing feedback state. While a question has attempts remaining (wrong, not exhausted), neither the JS fragment nor the no-JS re-render nor a resume render may contain accepted-answer text or correct-answer data attributes.
- **Server-authoritative:** attempt caps, lock state, scoring, and the submitted-lock are enforced server-side. The client cannot exceed `max_attempts`, answer a locked/submitted question, or self-report a score.
- **IDOR/CSRF:** a student reads/writes only their own `QuizSubmission`/`QuestionResponse`; all four views scope by `request.user`; POSTs are CSRF-protected.
- **Persistence is gated on `is_enrolled`** (not the broader `can_access_course`): a non-enrolled accessor (author/staff preview) gets a read-only quiz with no `QuizSubmission` created — mirrors `courses.views.complete`.
- **No formative behavior change:** a question inside a *lesson* unit stays ephemeral, unlimited-retry, always-reveal; the three new fields are dormant there.
- **Decimal precision (verbatim):** marks-valued fields (`max_marks`, `earned_marks`, `QuizSubmission.score`/`max_score`) → `max_digits=7, decimal_places=2`. `fraction` fields (`QuestionResponse.fraction`, `Attempt.fraction`) → `max_digits=5, decimal_places=4`.
- **`MarkResult.fraction` stays a `float`** (upstream 2a/2b unchanged); it is converted to `Decimal` at the 2c scoring boundary only.
- **i18n:** every new user-facing string is wrapped (`{% trans %}` / `gettext`) and given a Polish translation, matching the 2b i18n pass.

**Predecessor facts (verified against the post-2b tree — do not re-discover):**
- `courses/marking.py`: `MarkResult(correct: bool, fraction: float, reveal=frozenset())`. Helpers `normalize_text`, `parse_number`.
- `QuestionElement` (abstract, `courses/models.py`): `stem`, `explanation` (sanitized on save); `REVEAL_TEMPLATE = None`; `mark(self, answer)` (abstract); `build_answer(self, post)` (per concrete type); `feedback_context(self, mark_result)`; `render(self, *, element=None, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)`.
- **`build_answer` return shapes:** `ChoiceQuestionElement` → `set[int]`; `ShortTextQuestionElement`/`ShortNumericQuestionElement` → `str` (`post.get("answer","")`); `FillBlankQuestionElement` → `list[str]` (`post.getlist("blank")`).
- `courses/models.py`: `Element` join-row has `unit` FK + `content_type`/`object_id` GFK; `ELEMENT_MODELS` allowlist; `UnitProgress(student, unit, seen_element_ids, completed, completed_at)` with a `save()` that stamps `completed_at` when `completed`.
- `ContentNode.UnitType` = `LESSON`/`QUIZ`; `Kind.UNIT`.
- `courses/access.py`: `is_enrolled(user, course)`; `can_access_course(user, course)`; `get_node_or_404(node_pk, slug, *, require_unit=False, require_lesson=False)`.
- `courses/views.py`: `_wants_fragment(request)` (`X-Requested-With == "fetch"`); `build_lesson_context(node, user)`; `check_answer`, `lesson_unit`, `complete`, `seen`. `lesson_unit` currently renders the quiz branch as an inert placeholder (`is_quiz=True`).
- `courses/templatetags/courses_extras.py`: `render_element(element, feedback_for_pk=None, selected_ids=frozenset(), submitted_values=None, mark_result=None)` dispatches to `obj.render(...)`.
- `courses/element_forms.py`: four question `ModelForm`s — `ChoiceQuestionElementForm` (`fields=["stem","explanation","multiple"]`), `ShortTextQuestionElementForm` (`+["accepted","case_sensitive"]`), `ShortNumericQuestionElementForm` (`+["value","tolerance"]`), `FillBlankQuestionElementForm` (`["stem","explanation"]`); `FORM_FOR_TYPE` dict.
- Tests live flat in `tests/` (`test_*.py`); factories in `tests/factories.py` (`UserFactory`, `CourseFactory`, `ContentNodeFactory` [`unit_type="lesson"` default], `EnrollmentFactory`, `add_element(unit, obj)`, `make_login(client, username)`); pytest with `@pytest.mark.django_db`.
- Per-type element templates (e.g. `templates/courses/elements/shorttextquestionelement.html`) render the input with `value="{% if element.pk == feedback_for_pk %}{{ submitted_values }}{% endif %}"`, hardcode `action="{% url 'courses:check_answer' ... %}"`, and `{% include "courses/elements/_question_feedback.html" %}`.

---

## Task 1: Scoring primitives (`courses/scoring.py`)

Pure, dependency-free functions for the fraction→marks conversion. The single home for §3.5 of the spec; everything else imports these.

**Files:**
- Create: `courses/scoring.py`
- Test: `tests/test_quiz_scoring.py`

**Interfaces:**
- Produces:
  - `to_stored_fraction(raw: float) -> Decimal` — `Decimal(str(raw))`, quantized to 4dp `ROUND_HALF_UP`, clamped to `[0, 1]`.
  - `earned_marks(fraction: Decimal, max_marks: Decimal) -> Decimal` — `(fraction * max_marks)` quantized to 2dp `ROUND_HALF_UP`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_scoring.py
from decimal import Decimal

from courses.scoring import earned_marks, to_stored_fraction


def test_to_stored_fraction_exact_endpoints():
    assert to_stored_fraction(1.0) == Decimal("1.0000")
    assert to_stored_fraction(0.0) == Decimal("0.0000")


def test_to_stored_fraction_thirds_quantized_4dp():
    # 2/3 float -> 0.6666666666666666 -> 4dp half-up
    assert to_stored_fraction(2 / 3) == Decimal("0.6667")


def test_to_stored_fraction_clamps_out_of_range():
    assert to_stored_fraction(1.5) == Decimal("1.0000")
    assert to_stored_fraction(-0.2) == Decimal("0.0000")


def test_earned_marks_partial_thirds():
    # stored 0.6667 * 3 marks -> 2.0001 -> 2dp -> 2.00
    assert earned_marks(Decimal("0.6667"), Decimal("3")) == Decimal("2.00")


def test_earned_marks_full_and_zero():
    assert earned_marks(Decimal("1.0000"), Decimal("2.5")) == Decimal("2.50")
    assert earned_marks(Decimal("0.0000"), Decimal("2.5")) == Decimal("0.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'courses.scoring'`

- [ ] **Step 3: Write the implementation**

```python
# courses/scoring.py
"""Pure scoring helpers for the quiz engine (Phase 2c, spec §3.5).

MarkResult.fraction is a float upstream; it is converted to Decimal HERE and
nowhere else. Storage is deterministic and quantized — exactness is impossible
for thirds, so we quantize rather than pretend to store an exact ratio.
"""

from decimal import ROUND_HALF_UP, Decimal

_FRACTION_Q = Decimal("0.0001")  # 4 dp — matches the fraction DecimalField
_MARKS_Q = Decimal("0.01")       # 2 dp — matches the marks DecimalFields
_ZERO = Decimal("0")
_ONE = Decimal("1")


def to_stored_fraction(raw):
    """float fraction -> Decimal, 4dp, clamped to [0, 1].

    `str()` first avoids binary-float artifacts (Decimal(str(2/3)) ==
    "0.6666666666666666", not the 55-digit Decimal(2/3)). The clamp guards the
    no-headroom field (max_digits=5) against a future buggy mark() returning >1.
    """
    f = Decimal(str(raw)).quantize(_FRACTION_Q, rounding=ROUND_HALF_UP)
    if f < _ZERO:
        return _ZERO.quantize(_FRACTION_Q)
    if f > _ONE:
        return _ONE.quantize(_FRACTION_Q)
    return f


def earned_marks(fraction, max_marks):
    """Stored 4dp fraction × max_marks, quantized to 2dp. The single source of
    truth used by BOTH the per-attempt cache and the Finish recompute."""
    return (fraction * max_marks).quantize(_MARKS_Q, rounding=ROUND_HALF_UP)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_scoring.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add courses/scoring.py tests/test_quiz_scoring.py
git commit -m "feat(2c): scoring primitives — to_stored_fraction + earned_marks"
```

---

## Task 2: `marks` display filter

A single template filter so per-question feedback, results, and the total all format marks identically (2dp internally, trailing zeros + trailing dot trimmed).

**Files:**
- Modify: `courses/templatetags/courses_extras.py` (add the filter; keep existing `render_element`)
- Test: `tests/test_quiz_scoring.py` (append — same display concern as Task 1)

**Interfaces:**
- Produces: a registered template filter `marks` — `{{ value|marks }}` → trimmed string. Importable for tests as `courses.templatetags.courses_extras.marks_filter`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_quiz_scoring.py`)

```python
from courses.templatetags.courses_extras import marks_filter


def test_marks_filter_trims_trailing_zeros():
    assert marks_filter(Decimal("2.00")) == "2"
    assert marks_filter(Decimal("1.50")) == "1.5"
    assert marks_filter(Decimal("0.67")) == "0.67"


def test_marks_filter_whole_tens_not_scientific():
    # regression: Decimal.normalize() would give "1E+1" — must be "10"
    assert marks_filter(Decimal("10.00")) == "10"


def test_marks_filter_none_is_dash():
    assert marks_filter(None) == "—"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_scoring.py -k marks_filter -v`
Expected: FAIL with `ImportError: cannot import name 'marks_filter'`

- [ ] **Step 3: Add the filter** (append to `courses/templatetags/courses_extras.py`; the file already has `register = template.Library()`)

```python
from decimal import Decimal


def marks_filter(value):
    """Format a marks Decimal for display: 2dp, trailing zeros + trailing '.' trimmed.

    NOT Decimal.normalize() — that yields scientific notation for whole tens
    (Decimal("10.00").normalize() == Decimal("1E+1")).
    """
    if value is None:
        return "—"
    s = f"{Decimal(value).quantize(Decimal('0.01')):f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


register.filter("marks", marks_filter)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_scoring.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add courses/templatetags/courses_extras.py tests/test_quiz_scoring.py
git commit -m "feat(2c): marks display template filter"
```

---

## Task 3: `QuestionElement` marking fields + per-type migrations

Add `marking_mode`, `max_attempts`, `max_marks` to the abstract base (inherited by all four concrete tables).

**Files:**
- Modify: `courses/models.py` (the `QuestionElement` abstract class body)
- Create: `courses/migrations/00NN_question_marking_fields.py` (generated)
- Test: `tests/test_quiz_models.py`

**Interfaces:**
- Produces: every concrete question model gains `marking_mode` (`"A"`/`"N"`/`"R"`, default `"A"`), `max_attempts` (`PositiveSmallIntegerField`, null=unlimited, default 1), `max_marks` (`Decimal`, default `1`). Helper constants `QuestionElement.MarkingMode.AUTO/NOT_MARKED/REVIEW`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quiz_models.py
from decimal import Decimal

import pytest

from courses.models import ShortTextQuestionElement


@pytest.mark.django_db
def test_question_marking_fields_defaults():
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    assert q.marking_mode == "A"
    assert q.max_attempts == 1
    assert q.max_marks == Decimal("1.00")


@pytest.mark.django_db
def test_question_max_attempts_nullable_for_unlimited():
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a", max_attempts=None)
    q.refresh_from_db()
    assert q.max_attempts is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quiz_models.py -v`
Expected: FAIL — `TypeError`/`FieldError` on unknown `marking_mode`/`max_attempts`.

- [ ] **Step 3: Add fields to `QuestionElement`** (in `courses/models.py`, inside the abstract `QuestionElement` class, near `stem`/`explanation`)

```python
    class MarkingMode(models.TextChoices):
        AUTO = "A", _("Auto-marked")
        NOT_MARKED = "N", _("Not marked")
        REVIEW = "R", _("Requires review")

    marking_mode = models.CharField(
        max_length=1, choices=MarkingMode.choices, default=MarkingMode.AUTO
    )
    # null = unlimited attempts; consumed only in quiz units (dormant in lessons).
    max_attempts = models.PositiveSmallIntegerField(null=True, blank=True, default=1)
    max_marks = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("1"),
        validators=[MinValueValidator(Decimal("0.01"))],
    )
```

Ensure imports at top of `courses/models.py` include `from decimal import Decimal` and `from django.core.validators import MinValueValidator` (MinValueValidator is already imported for `ShortNumericQuestionElement`; `Decimal` is imported in `marking.py` but confirm it is imported in `models.py` — add if missing).

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: a migration adding the three fields to `choicequestionelement`, `shorttextquestionelement`, `shortnumericquestionelement`, `fillblankquestionelement`. Rename the file to `..._question_marking_fields.py` if desired (optional).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations/
git commit -m "feat(2c): marking_mode/max_attempts/max_marks on QuestionElement base"
```

---

## Task 4: Persistence models + factories (`QuizSubmission`, `QuestionResponse`, `Attempt`)

The three models land together (mutual FKs → one migration). Factories added here for all later tasks.

**Files:**
- Modify: `courses/models.py` (append the three models)
- Create: `courses/migrations/00NN_quiz_persistence.py` (generated)
- Modify: `tests/factories.py` (add factories + a `make_quiz_unit` helper)
- Test: `tests/test_quiz_models.py` (append)

**Interfaces:**
- Produces:
  - `QuizSubmission(student, unit, status, submitted_at, score, max_score, created, updated)` — `status` in `{"in_progress","submitted"}`, default `"in_progress"`; unique `(student, unit)`; `save()` stamps `submitted_at` when `status == "submitted"`. Constants `QuizSubmission.Status.IN_PROGRESS/SUBMITTED`.
  - `QuestionResponse(submission, element, attempt_count, latest_answer, fraction, earned_marks, locked, last_attempt_at)` — unique `(submission, element)`.
  - `Attempt(response, n, answer, fraction, correct, created)` — unique `(response, n)`; `fraction`/`correct` nullable.
  - Factories `QuizSubmissionFactory`, `QuestionResponseFactory`, `AttemptFactory`; helper `make_quiz_unit(course=None, **kw) -> ContentNode` (a `unit_type="quiz"` unit).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_quiz_models.py`)

```python
from django.db import IntegrityError

from courses.models import Attempt, QuestionResponse, QuizSubmission
from tests.factories import (
    AttemptFactory,
    ContentNodeFactory,
    QuestionResponseFactory,
    QuizSubmissionFactory,
    UserFactory,
)


@pytest.mark.django_db
def test_quizsubmission_stamps_submitted_at():
    sub = QuizSubmissionFactory(status="submitted", submitted_at=None)
    assert sub.submitted_at is not None


@pytest.mark.django_db
def test_quizsubmission_unique_student_unit():
    student = UserFactory()
    unit = ContentNodeFactory(unit_type="quiz")
    QuizSubmissionFactory(student=student, unit=unit)
    with pytest.raises(IntegrityError):
        QuizSubmissionFactory(student=student, unit=unit)


@pytest.mark.django_db
def test_attempt_fraction_correct_nullable():
    a = AttemptFactory(fraction=None, correct=None)
    a.refresh_from_db()
    assert a.fraction is None and a.correct is None


@pytest.mark.django_db
def test_attempt_unique_response_n():
    resp = QuestionResponseFactory()
    AttemptFactory(response=resp, n=1)
    with pytest.raises(IntegrityError):
        AttemptFactory(response=resp, n=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_models.py -k "quizsubmission or attempt" -v`
Expected: FAIL with `ImportError` (models/factories not defined).

- [ ] **Step 3: Add the three models** (append to `courses/models.py`; uses `timezone` already imported for `UnitProgress`)

```python
class QuizSubmission(models.Model):
    """Per (student, quiz unit). The spine: status + submitted_at are the Phase 3
    deadline-snapshot hook; score/max_score are cached at Finish."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", _("In progress")
        SUBMITTED = "submitted", _("Submitted")

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="quiz_submissions",
    )
    unit = models.ForeignKey(
        ContentNode, on_delete=models.CASCADE,
        limit_choices_to={"kind": "unit"}, related_name="quiz_submissions",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.IN_PROGRESS
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["student", "unit"], name="uniq_quizsubmission_student_unit"
            )
        ]

    def save(self, *args, **kwargs):
        # Invariant: submitted => submitted_at set, on every write path.
        if self.status == self.Status.SUBMITTED and self.submitted_at is None:
            self.submitted_at = timezone.now()
        super().save(*args, **kwargs)


class QuestionResponse(models.Model):
    """Per (submission, question Element): the student's current state for one question."""

    submission = models.ForeignKey(
        QuizSubmission, on_delete=models.CASCADE, related_name="responses"
    )
    element = models.ForeignKey(
        Element, on_delete=models.CASCADE, related_name="responses"
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    latest_answer = models.JSONField(null=True, blank=True)
    fraction = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    earned_marks = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    locked = models.BooleanField(default=False)
    last_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "element"],
                name="uniq_response_submission_element",
            )
        ]


class Attempt(models.Model):
    """One row per submission of a question. fraction/correct null for [N]/[R]."""

    response = models.ForeignKey(
        QuestionResponse, on_delete=models.CASCADE, related_name="attempts"
    )
    n = models.PositiveSmallIntegerField()
    answer = models.JSONField()
    fraction = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    correct = models.BooleanField(null=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["n"]
        constraints = [
            models.UniqueConstraint(
                fields=["response", "n"], name="uniq_attempt_response_n"
            )
        ]
```

Confirm `settings` is imported in `models.py` (it is — `UnitProgress`/`MediaAsset` use `settings.AUTH_USER_MODEL`).

- [ ] **Step 4: Add factories** (append to `tests/factories.py`; add imports for the three models)

```python
from courses.models import Attempt, Element, QuestionResponse, QuizSubmission
from courses.models import ShortTextQuestionElement


def make_quiz_unit(course=None, **kw):
    """A quiz unit ContentNode (kind=unit, unit_type=quiz)."""
    kw.setdefault("kind", "unit")
    kw.setdefault("unit_type", "quiz")
    if course is not None:
        kw["course"] = course
    return ContentNodeFactory(**kw)


class QuizSubmissionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QuizSubmission

    student = factory.SubFactory(UserFactory)
    unit = factory.SubFactory(ContentNodeFactory, unit_type="quiz")


class QuestionResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QuestionResponse

    submission = factory.SubFactory(QuizSubmissionFactory)
    # An Element join-row pointing at a freshly created short-text question.
    element = factory.LazyAttribute(
        lambda o: Element.objects.create(
            unit=o.submission.unit,
            content_object=ShortTextQuestionElement.objects.create(stem="q", accepted="a"),
        )
    )


class AttemptFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attempt

    response = factory.SubFactory(QuestionResponseFactory)
    n = factory.Sequence(lambda n: n + 1)
    answer = factory.LazyFunction(lambda: ["a"])
    fraction = None
    correct = None
```

- [ ] **Step 5: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: a migration creating `QuizSubmission`, `QuestionResponse`, `Attempt` with the three unique constraints.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_models.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/ tests/factories.py tests/test_quiz_models.py
git commit -m "feat(2c): QuizSubmission/QuestionResponse/Attempt models + factories"
```

---

## Task 5: `require_quiz` guard kwarg

Extend the existing node resolver so quiz views 404 a non-quiz node, mirroring `require_lesson`.

**Files:**
- Modify: `courses/access.py:30-43` (`get_node_or_404`)
- Test: `tests/test_quiz_views.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_node_or_404(node_pk, slug, *, require_unit=False, require_lesson=False, require_quiz=False)` — raises `Http404` when `require_quiz` and `unit_type != QUIZ`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quiz_views.py
import pytest
from django.http import Http404

from courses.access import get_node_or_404
from tests.factories import ContentNodeFactory, make_quiz_unit


@pytest.mark.django_db
def test_require_quiz_404s_lesson():
    lesson = ContentNodeFactory(unit_type="lesson")
    with pytest.raises(Http404):
        get_node_or_404(lesson.pk, lesson.course.slug, require_unit=True, require_quiz=True)


@pytest.mark.django_db
def test_require_quiz_passes_quiz():
    quiz = make_quiz_unit()
    node = get_node_or_404(quiz.pk, quiz.course.slug, require_unit=True, require_quiz=True)
    assert node.pk == quiz.pk
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quiz_views.py -k require_quiz -v`
Expected: FAIL — `TypeError: get_node_or_404() got an unexpected keyword argument 'require_quiz'`

- [ ] **Step 3: Add the kwarg** (`courses/access.py`)

```python
def get_node_or_404(
    node_pk, slug, *, require_unit=False, require_lesson=False, require_quiz=False
):
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if node.course.slug != slug:
        raise Http404("node does not belong to this course")
    if require_unit and node.kind != ContentNode.Kind.UNIT:
        raise Http404("not a unit")
    if require_lesson and node.unit_type != ContentNode.UnitType.LESSON:
        raise Http404("not a lesson unit")
    if require_quiz and node.unit_type != ContentNode.UnitType.QUIZ:
        raise Http404("not a quiz unit")
    return node
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_views.py -k require_quiz -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add courses/access.py tests/test_quiz_views.py
git commit -m "feat(2c): require_quiz kwarg on get_node_or_404"
```

---

## Task 6: Quiz answer/response helpers (`courses/quiz.py`)

Pure-ish helpers the views compose: empty-answer detection, JSON round-trip of `latest_answer`, and rehydration into `selected_ids`/`submitted_values`. Isolated here so the view stays thin and these are unit-tested without HTTP.

**Files:**
- Create: `courses/quiz.py`
- Test: `tests/test_quiz_helpers.py`

**Interfaces:**
- Produces:
  - `answer_is_empty(answer) -> bool` — True for an empty set, blank/whitespace str, or list whose entries are all blank.
  - `answer_to_json(answer) -> list | str` — JSON-safe form of a `build_answer` payload (`set` → sorted `list`; `str`/`list` unchanged).
  - `rehydrate(question, latest_answer) -> tuple[set, object]` — returns `(selected_ids, submitted_values)` for the shared templates: choice → `(set(latest_answer), None)`; text/numeric → `(set(), latest_answer)`; fill-blank → `(set(), latest_answer)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_helpers.py
import pytest

from courses.quiz import answer_is_empty, answer_to_json, rehydrate
from courses.models import (
    ChoiceQuestionElement,
    FillBlankQuestionElement,
    ShortTextQuestionElement,
)


def test_answer_is_empty_across_shapes():
    assert answer_is_empty(set())
    assert answer_is_empty("")
    assert answer_is_empty("   ")
    assert answer_is_empty(["", "  "])
    assert not answer_is_empty({1})
    assert not answer_is_empty("x")
    assert not answer_is_empty(["", "a"])


def test_answer_to_json_set_becomes_sorted_list():
    assert answer_to_json({3, 1, 2}) == [1, 2, 3]
    assert answer_to_json("hi") == "hi"
    assert answer_to_json(["a", ""]) == ["a", ""]


@pytest.mark.django_db
def test_rehydrate_choice_returns_selected_ids():
    q = ChoiceQuestionElement.objects.create(stem="s", multiple=True)
    selected, submitted = rehydrate(q, [5, 7])
    assert selected == {5, 7} and submitted is None


@pytest.mark.django_db
def test_rehydrate_text_returns_submitted_values():
    q = ShortTextQuestionElement.objects.create(stem="s", accepted="a")
    selected, submitted = rehydrate(q, "Paris")
    assert selected == set() and submitted == "Paris"


@pytest.mark.django_db
def test_rehydrate_fillblank_returns_list():
    q = FillBlankQuestionElement.objects.create(stem="s {{a}}")
    selected, submitted = rehydrate(q, ["x", "y"])
    assert selected == set() and submitted == ["x", "y"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.quiz'`

- [ ] **Step 3: Write the helpers**

```python
# courses/quiz.py
"""View-agnostic helpers for the quiz path (Phase 2c)."""

from courses.models import ChoiceQuestionElement


def answer_is_empty(answer):
    """True iff a build_answer() payload carries nothing markable."""
    if isinstance(answer, (set, frozenset)):
        return not answer
    if isinstance(answer, str):
        return not answer.strip()
    if isinstance(answer, (list, tuple)):
        return not any(str(v).strip() for v in answer)
    return not answer


def answer_to_json(answer):
    """JSON-safe form of a build_answer() payload for QuestionResponse.latest_answer."""
    if isinstance(answer, (set, frozenset)):
        return sorted(answer)
    if isinstance(answer, tuple):
        return list(answer)
    return answer


def rehydrate(question, latest_answer):
    """Reconstruct (selected_ids, submitted_values) for the shared element templates
    from a stored latest_answer. Choice types use selected_ids; the rest use
    submitted_values — exactly the no-JS context vars check_answer already passes."""
    if isinstance(question, ChoiceQuestionElement):
        return set(latest_answer or []), None
    return set(), latest_answer
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_helpers.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add courses/quiz.py tests/test_quiz_helpers.py
git commit -m "feat(2c): quiz answer helpers — empty/json/rehydrate"
```

---

## Task 7: Quiz-mode rendering — `render()` + `render_element` + per-type template params

Thread a `mode` and quiz state through the render pipeline without forking per-type templates. Lesson rendering must stay byte-identical.

**Files:**
- Modify: `courses/models.py` (`QuestionElement.render` signature + context)
- Modify: `courses/templatetags/courses_extras.py` (`render_element` passthrough)
- Modify: `templates/courses/elements/choicequestionelement.html`, `shorttextquestionelement.html`, `shortnumericquestionelement.html`, `fillblankquestionelement.html` (parameterize form `action` + feedback partial, with lesson defaults)
- Test: `tests/test_quiz_render.py`

**Interfaces:**
- Consumes: `marks` filter (Task 2), helpers (Task 6).
- Produces: `QuestionElement.render(..., mode="lesson", action_url=None, feedback_partial="courses/elements/_question_feedback.html", quiz_submitted=False, locked=False, attempts_left=None)`. When `mode="quiz"`, the per-type template posts to `action_url` and includes `feedback_partial`; inputs carry `disabled` when `quiz_submitted or locked`. `render_element` gains the same passthrough kwargs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quiz_render.py
import pytest

from courses.models import ShortTextQuestionElement
from tests.factories import add_element, make_quiz_unit


@pytest.mark.django_db
def test_quiz_render_posts_to_quiz_answer_and_can_lock():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)

    html = q.render(
        element=el, mode="quiz",
        action_url=f"/x/answer/{el.pk}/", locked=True, quiz_submitted=False,
    )
    assert f"/x/answer/{el.pk}/" in html      # form action redirected to quiz path
    assert "disabled" in html                  # locked input
    assert "courses:check_answer" not in html  # not the lesson action


@pytest.mark.django_db
def test_lesson_render_unchanged_defaults():
    unit = make_quiz_unit()  # any unit; lesson-mode render
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)
    html = q.render(element=el)  # mode defaults to lesson
    assert "check/" in html       # lesson form posts to check_answer URL
    assert "disabled" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quiz_render.py -v`
Expected: FAIL — `render()` rejects `mode`/`action_url`/`locked`.

- [ ] **Step 3: Extend `QuestionElement.render`** (replace the existing `render` method body in `courses/models.py`)

```python
    def render(
        self,
        *,
        element=None,
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
        mode="lesson",
        action_url=None,
        feedback_partial="courses/elements/_question_feedback.html",
        quiz_submitted=False,
        locked=False,
        attempts_left=None,
    ):
        name = self._meta.model_name
        unit = element.unit if element is not None else None
        # Lesson default: post to check_answer. Quiz: caller supplies action_url.
        if action_url is None and unit is not None:
            action_url = reverse(
                "courses:check_answer",
                kwargs={"slug": unit.course.slug, "node_pk": unit.pk,
                        "element_pk": element.pk},
            )
        return render_to_string(
            f"courses/elements/{name}.html",
            {
                "el": self,
                "element": element,
                "slug": unit.course.slug if unit is not None else "",
                "node_pk": unit.pk if unit is not None else "",
                "feedback_for_pk": feedback_for_pk,
                "selected_ids": set(selected_ids or ()),
                "submitted_values": submitted_values,
                "mark_result": mark_result,
                "reveal_template": self.REVEAL_TEMPLATE,
                "mode": mode,
                "action_url": action_url,
                "feedback_partial": feedback_partial,
                "quiz_submitted": quiz_submitted,
                "locked": locked,
                "attempts_left": attempts_left,
            },
        )
```

Add `from django.urls import reverse` to `courses/models.py` imports if not present.

- [ ] **Step 4: Update `render_element`** (`courses/templatetags/courses_extras.py`) to accept and forward the new kwargs

```python
@register.simple_tag
def render_element(
    element,
    feedback_for_pk=None,
    selected_ids=frozenset(),
    submitted_values=None,
    mark_result=None,
    mode="lesson",
    action_url=None,
    feedback_partial="courses/elements/_question_feedback.html",
    quiz_submitted=False,
    locked=False,
    attempts_left=None,
):
    obj = element.content_object
    if obj is None:
        return ""
    if isinstance(obj, HtmlElement):
        return mark_safe(obj.render(unit=element.unit, course=element.unit.course))  # noqa: S308
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
            )
        )
    return mark_safe(obj.render())  # noqa: S308
```

(Keep the existing non-question branch exactly as it was; only the question branch and signature change.)

- [ ] **Step 5: Parameterize each per-type template.** In all four `templates/courses/elements/<type>.html`, replace the hardcoded action + feedback include + add the disabled attribute. Example for `shorttextquestionelement.html`:

```html
{% load i18n %}
<div class="el el--question" data-question>
  <div class="question__stem">{{ el.stem|safe }}</div>
  {% if element %}
  <form class="question__form" method="post"
        action="{{ action_url }}">
    {% csrf_token %}
    <input type="text" name="answer" class="question__text-input" autocomplete="off"
           value="{% if element.pk == feedback_for_pk %}{{ submitted_values }}{% endif %}"
           {% if quiz_submitted or locked %}disabled{% endif %}>
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    <div class="question__feedback" data-question-feedback>
      {% if element.pk == feedback_for_pk %}
        {% include feedback_partial %}
      {% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

Apply the equivalent change to `choicequestionelement.html` (each choice `<input>` gets `{% if quiz_submitted or locked %}disabled{% endif %}`), `shortnumericquestionelement.html`, and `fillblankquestionelement.html` (each blank `<input>` gets the disabled flag). The lesson defaults (`action_url` resolved to check_answer, `feedback_partial="..._question_feedback.html"`, `locked`/`quiz_submitted` False) keep lesson rendering identical.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_render.py tests/test_questions_consumption.py tests/test_questions_2b_consumption.py -v`
Expected: PASS — new quiz-render tests pass AND existing lesson consumption tests still pass (no regression).

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/templatetags/courses_extras.py templates/courses/elements/ tests/test_quiz_render.py
git commit -m "feat(2c): quiz-mode render passthrough (action_url, feedback_partial, locked)"
```

---

## Task 8: `build_quiz_context` + `quiz_unit` GET view + `quiz_unit.html`

The GET path: render a quiz unit, create the submission for enrolled students, redirect to results when submitted, read-only for previewers. Rehydration of prior responses is added in Task 11.

**Files:**
- Modify: `courses/views.py` (add `build_quiz_context`, `quiz_unit`)
- Modify: `courses/urls.py` (4 quiz routes — add all now; later tasks fill the views)
- Create: `templates/courses/quiz_unit.html`
- Test: `tests/test_quiz_views.py` (append)

**Interfaces:**
- Consumes: `get_node_or_404(..., require_quiz=True)`, `is_enrolled`, `can_access_course`, `render_element` quiz mode.
- Produces:
  - `build_quiz_context(node, user) -> dict` — `course`, `unit`, `elements`, `has_math`/`has_html`/`has_questions`, `submission` (or None), `quiz_submitted` (bool), plus per-element quiz render state keyed for the template.
  - `quiz_unit(request, slug, node_pk)` view; URL name `courses:quiz_unit` at `courses/<slug>/u/<node_pk>/quiz/`.
  - URL names `courses:quiz_answer`, `courses:quiz_finish`, `courses:quiz_results`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_quiz_views.py`)

```python
from courses.models import QuizSubmission
from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


def _quiz_with_question(client, enroll=True):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    if enroll:
        EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    el = add_element(unit, q)
    return user, unit, el


@pytest.mark.django_db
def test_quiz_unit_get_renders_and_creates_submission_for_enrolled(client):
    user, unit, el = _quiz_with_question(client)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"Finish quiz" in resp.content
    assert QuizSubmission.objects.filter(student=user, unit=unit).count() == 1


@pytest.mark.django_db
def test_quiz_unit_get_no_submission_for_unenrolled_preview(client):
    user, unit, el = _quiz_with_question(client, enroll=False)
    user.is_staff = True
    user.save()
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"
    resp = client.get(url)
    assert resp.status_code == 200
    assert not QuizSubmission.objects.filter(unit=unit).exists()


@pytest.mark.django_db
def test_quiz_unit_get_redirects_to_results_when_submitted(client):
    user, unit, el = _quiz_with_question(client)
    QuizSubmission.objects.create(student=user, unit=unit, status="submitted")
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/"
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url.endswith("/results/")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_views.py -k quiz_unit_get -v`
Expected: FAIL — 404 (no URL) / `AttributeError` (no view).

- [ ] **Step 3: Add the four URLs** (`courses/urls.py`, after the `check_answer` route)

```python
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/",
        views.quiz_unit,
        name="quiz_unit",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/q/<int:element_pk>/answer/",
        views.quiz_answer,
        name="quiz_answer",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/finish/",
        views.quiz_finish,
        name="quiz_finish",
    ),
    path(
        "courses/<slug:slug>/u/<int:node_pk>/quiz/results/",
        views.quiz_results,
        name="quiz_results",
    ),
```

- [ ] **Step 4: Add `build_quiz_context` + `quiz_unit`** (`courses/views.py`). Reuse the has_math/has_html/has_questions computation by factoring it, or recompute inline. For now recompute the booleans inline mirroring `build_lesson_context`:

```python
from courses.models import Attempt, QuestionResponse, QuizSubmission  # add to imports
from courses.quiz import answer_is_empty, answer_to_json, rehydrate    # add to imports


def build_quiz_context(node, user):
    """Element/render context for a QUIZ unit. Parallels build_lesson_context but
    threads per-question quiz state (responses, locked, attempts_left)."""
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    submission = None
    if is_enrolled(user, node.course):
        submission, _ = QuizSubmission.objects.get_or_create(student=user, unit=node)
    quiz_submitted = bool(submission and submission.status == QuizSubmission.Status.SUBMITTED)

    responses = {}
    if submission is not None:
        responses = {r.element_id: r for r in submission.responses.all()}

    # has_* flags: a quiz always loads the question JS; math/html as needed.
    has_math = any(
        isinstance(el.content_object, QuestionElement) for el in elements
    )  # KaTeX auto-render is harmless when absent; keep simple — load if any question.
    has_html = any(isinstance(el.content_object, HtmlElement) for el in elements)
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": True,
        "elements": elements,
        "responses": responses,
        "submission": submission,
        "quiz_submitted": quiz_submitted,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": True,
    }


@login_required
def quiz_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    ctx = build_quiz_context(node, request.user)
    sub = ctx["submission"]
    if sub is not None and sub.status == QuizSubmission.Status.SUBMITTED:
        return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)
    return render(request, "courses/quiz_unit.html", ctx)
```

- [ ] **Step 5: Create `templates/courses/quiz_unit.html`**

```html
{% extends "base.html" %}
{% load i18n static courses_extras %}
{% block head_title %}{{ unit.title }} — libli{% endblock %}
{% block extra_css %}
  <link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">
  {% if has_math %}<link rel="stylesheet" href="{% static 'courses/vendor/katex/katex.min.css' %}">{% endif %}
{% endblock %}
{% block content %}
<article class="quiz" lang="{{ course.language }}">
  <h1 class="lesson-unit__title">{{ unit.title }}</h1>
  {% for el in elements %}
    {% with resp=responses|dictkey:el.pk %}
    <section data-element-id="{{ el.pk }}">
      {% render_element el mode="quiz" quiz_submitted=quiz_submitted action_url=el|quiz_answer_url locked=resp.locked %}
    </section>
    {% endwith %}
  {% endfor %}

  {% if not quiz_submitted %}
  <form class="quiz-finish" method="post"
        action="{% url 'courses:quiz_finish' slug=course.slug node_pk=unit.pk %}"
        data-quiz-finish>
    {% csrf_token %}
    <button type="submit" class="btn btn--primary" data-finish-btn>{% trans "Finish quiz" %}</button>
  </form>
  {% endif %}
</article>
{% endblock %}
{% block extra_js %}
  {% if has_math %}
    <script src="{% static 'courses/vendor/katex/katex.min.js' %}" defer></script>
    <script src="{% static 'courses/vendor/katex/contrib/auto-render.min.js' %}" defer></script>
    <script src="{% static 'courses/js/math.js' %}" defer></script>
  {% endif %}
  {% if has_html %}<script src="{% static 'courses/js/html_element.js' %}" defer></script>{% endif %}
  <script src="{% static 'courses/js/quiz.js' %}" defer></script>
{% endblock %}
```

Add two helpers to `courses/templatetags/courses_extras.py` used above (a dict lookup filter and the per-element quiz-answer URL):

```python
@register.filter
def dictkey(d, key):
    """Look up d[key] in a template (responses keyed by element pk)."""
    return (d or {}).get(key)


@register.filter
def quiz_answer_url(element):
    return reverse(
        "courses:quiz_answer",
        kwargs={"slug": element.unit.course.slug, "node_pk": element.unit_id,
                "element_pk": element.pk},
    )
```

Add `from django.urls import reverse` to `courses_extras.py` imports.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_views.py -k quiz_unit_get -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Commit**

```bash
git add courses/views.py courses/urls.py courses/templatetags/courses_extras.py templates/courses/quiz_unit.html tests/test_quiz_views.py
git commit -m "feat(2c): quiz_unit GET view + template + build_quiz_context"
```

---

## Task 9: `quiz_answer` — `[A]` submission, withhold state machine, locks, no-leak

The core. Per-question submit: lock the submission + response rows, enforce caps, mark, persist, return the reveal-gated feedback. Includes the empty-answer guard and concurrency locks.

**Files:**
- Modify: `courses/views.py` (add `quiz_answer`, a `_quiz_feedback_context` builder)
- Create: `templates/courses/elements/_quiz_question_feedback.html`
- Create: `courses/static/courses/js/quiz.js`
- Test: `tests/test_quiz_answer.py`, `tests/test_quiz_noleak.py`

**Interfaces:**
- Consumes: `scoring.to_stored_fraction`/`earned_marks`, `quiz.answer_is_empty`/`answer_to_json`, the models.
- Produces:
  - `quiz_answer(request, slug, node_pk, element_pk)` — `@require_POST @login_required`.
  - `_quiz_feedback_context(question, response, *, result=None, validation=False) -> dict` — builds the **reveal-gated** context: includes `reveal_template` + `mark_result` ONLY when revealing (correct, or wrong-on-last-attempt); otherwise passes `attempts_left` and no reveal.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_answer.py
import pytest

from courses.models import Attempt, QuestionResponse, QuizSubmission
from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


def _setup(client, max_attempts=1, accepted="Paris"):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted=accepted, explanation="It's Paris.", max_attempts=max_attempts
    )
    el = add_element(unit, q)
    return user, unit, el


def _answer_url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


@pytest.mark.django_db
def test_correct_answer_reveals_locks_and_persists(client):
    user, unit, el = _setup(client, max_attempts=3)
    resp = client.post(_answer_url(unit, el), {"answer": "Paris"},
                       HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"Correct" in resp.content
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.attempt_count == 1
    assert r.fraction == 1 and r.earned_marks == 1
    assert Attempt.objects.filter(response=r).count() == 1


@pytest.mark.django_db
def test_wrong_with_attempts_left_withholds(client):
    user, unit, el = _setup(client, max_attempts=3)
    resp = client.post(_answer_url(unit, el), {"answer": "London"},
                       HTTP_X_REQUESTED_WITH="fetch")
    body = resp.content.decode()
    assert "Paris" not in body            # NO leak while attempts remain
    assert "It's Paris." not in body      # explanation withheld too
    assert "2" in body                    # attempts-left shown
    r = QuestionResponse.objects.get(element=el)
    assert not r.locked and r.attempt_count == 1


@pytest.mark.django_db
def test_wrong_on_last_attempt_reveals_and_locks(client):
    user, unit, el = _setup(client, max_attempts=1)
    resp = client.post(_answer_url(unit, el), {"answer": "London"},
                       HTTP_X_REQUESTED_WITH="fetch")
    body = resp.content.decode()
    assert "Paris" in body                # reveal on exhaustion
    r = QuestionResponse.objects.get(element=el)
    assert r.locked


@pytest.mark.django_db
def test_attempt_cap_rejects_after_exhaustion(client):
    user, unit, el = _setup(client, max_attempts=1)
    client.post(_answer_url(unit, el), {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.post(_answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409
    assert QuestionResponse.objects.get(element=el).attempt_count == 1


@pytest.mark.django_db
def test_empty_answer_does_not_burn_attempt(client):
    user, unit, el = _setup(client, max_attempts=2)
    resp = client.post(_answer_url(unit, el), {"answer": "   "}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"Enter an answer" in resp.content
    assert QuestionResponse.objects.filter(element=el).first() is None \
        or QuestionResponse.objects.get(element=el).attempt_count == 0


@pytest.mark.django_db
def test_answer_after_submitted_is_rejected(client):
    user, unit, el = _setup(client)
    QuizSubmission.objects.filter(student=user, unit=unit).update(status="submitted")
    resp = client.post(_answer_url(unit, el), {"answer": "Paris"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_answer.py -v`
Expected: FAIL — no `quiz_answer` view.

- [ ] **Step 3: Implement `quiz_answer` + `_quiz_feedback_context`** (`courses/views.py`)

```python
from django.db import transaction
from django.http import HttpResponse

from courses.scoring import earned_marks, to_stored_fraction


def _quiz_feedback_context(question, response, *, result=None, validation=False):
    """Reveal-gated feedback context. Reveal (reveal_template + mark_result) is
    included ONLY when the question is locked AND was marked — i.e. correct, or
    wrong-on-last-attempt. While attempts remain, only `attempts_left` passes."""
    ctx = {"el": question, "validation": validation, "mode": "quiz"}
    if validation:
        return ctx
    revealing = response.locked and result is not None
    if revealing:
        # Reuse the per-type feedback_context (choices, reveal_template) for the reveal.
        ctx.update(question.feedback_context(result))
    else:
        # Withhold: no reveal_template, no mark_result payload.
        ctx["mark_result"] = result  # correct=False only; template shows no reveal
        ctx["reveal_template"] = None
    ctx["locked"] = response.locked
    if question.max_attempts is not None and not response.locked:
        ctx["attempts_left"] = max(0, question.max_attempts - response.attempt_count)
    else:
        ctx["attempts_left"] = None
    return ctx


@require_POST
@login_required
def quiz_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied  # previewers cannot persist

    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    with transaction.atomic():
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=request.user, unit=node
        )
        if submission.status == QuizSubmission.Status.SUBMITTED:
            return _quiz_locked_response(request, slug, node_pk)

        response, _ = (
            QuestionResponse.objects.select_for_update()
            .get_or_create(submission=submission, element=element)
        )
        if response.locked or (
            question.max_attempts is not None
            and response.attempt_count >= question.max_attempts
        ):
            return _quiz_locked_response(request, slug, node_pk)

        answer = question.build_answer(request.POST)
        if answer_is_empty(answer):
            return _quiz_render_feedback(
                request, node, element, question, response, validation=True
            )

        is_auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
        result = None
        if is_auto:
            result = question.mark(answer)
            f = to_stored_fraction(result.fraction)
            response.fraction = f
            response.earned_marks = earned_marks(f, question.max_marks)
            attempt_fraction = f
            attempt_correct = result.correct
        else:
            attempt_fraction = None
            attempt_correct = None

        response.attempt_count += 1
        response.latest_answer = answer_to_json(answer)
        response.last_attempt_at = timezone.now()
        if is_auto:
            response.locked = bool(result.correct) or (
                question.max_attempts is not None
                and response.attempt_count >= question.max_attempts
            )
        else:
            response.locked = True  # [N]/[R]: single submission
        response.save()
        Attempt.objects.create(
            response=response, n=response.attempt_count,
            answer=response.latest_answer,
            fraction=attempt_fraction, correct=attempt_correct,
        )

    return _quiz_render_feedback(
        request, node, element, question, response, result=result
    )


def _quiz_locked_response(request, slug, node_pk):
    if _wants_fragment(request):
        return HttpResponse(_("This quiz has already been submitted."), status=409)
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


def _quiz_render_feedback(request, node, element, question, response,
                          *, result=None, validation=False):
    if _wants_fragment(request):
        ctx = _quiz_feedback_context(question, response, result=result, validation=validation)
        return render(request, "courses/elements/_quiz_question_feedback.html", ctx)
    # No-JS: full quiz_unit re-render with this question's feedback inline.
    ctx = build_quiz_context(node, request.user)
    ctx["feedback_for_pk"] = element.pk
    ctx["feedback_response"] = response
    ctx["feedback_result"] = result
    ctx["feedback_validation"] = validation
    return render(request, "courses/quiz_unit.html", ctx)
```

Add `from django.utils.translation import gettext as _` to `views.py` imports if not present.

- [ ] **Step 4: Create `templates/courses/elements/_quiz_question_feedback.html`**

```html
{% load i18n %}
{% if validation %}
  <div class="question__verdict is-validation">{% trans "Enter an answer" %}</div>
{% elif mark_result %}
  {% if mark_result.correct %}
    <div class="question__verdict is-correct">
      <span class="question__glyph" aria-hidden="true">✓</span>{% trans "Correct" %}
    </div>
    {% if reveal_template %}{% include reveal_template %}{% endif %}
    {% if el.explanation %}<div class="question__explanation">{{ el.explanation|safe }}</div>{% endif %}
  {% else %}
    <div class="question__verdict is-incorrect">
      <span class="question__glyph" aria-hidden="true">✗</span>{% trans "Incorrect" %}
      {% if attempts_left %} — {% blocktrans count n=attempts_left %}{{ n }} attempt left{% plural %}{{ n }} attempts left{% endblocktrans %}{% endif %}
    </div>
    {% comment %}Reveal block renders ONLY when locked (wrong-on-last-attempt): reveal_template is None while attempts remain.{% endcomment %}
    {% if reveal_template %}{% include reveal_template %}{% endif %}
    {% if locked and el.explanation %}<div class="question__explanation">{{ el.explanation|safe }}</div>{% endif %}
  {% endif %}
{% endif %}
```

- [ ] **Step 5: Create `courses/static/courses/js/quiz.js`** (progressive enhancement: intercept each question form, POST with `X-Requested-With: fetch`, swap the feedback partial; intercept Finish to confirm)

```javascript
// Quiz interactions: per-question submit (swap feedback) + Finish confirmation.
(function () {
  function csrf() {
    const m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  document.querySelectorAll("form.question__form").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const res = await fetch(form.action, {
        method: "POST",
        headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
        body: new FormData(form),
      });
      const box = form.querySelector("[data-question-feedback]");
      if (res.status === 409) {
        window.location.reload();
        return;
      }
      box.innerHTML = await res.text();
      if (box.querySelector(".is-correct, .question__explanation")) {
        form.querySelectorAll("input, button").forEach((n) => (n.disabled = true));
      }
      if (window.renderMathInElement) {
        window.renderMathInElement(box);
      }
    });
  });

  const finish = document.querySelector("[data-quiz-finish]");
  if (finish) {
    finish.addEventListener("submit", (e) => {
      if (!window.confirm("Finish the quiz? You can't change your answers afterwards.")) {
        e.preventDefault();
      }
    });
  }
})();
```

(The confirm copy is replaced with an i18n-driven `data-` attribute in Task 12; a literal here is acceptable for this task's tests, which don't exercise JS.)

- [ ] **Step 6: Write the no-leak test** (`tests/test_quiz_noleak.py`)

```python
import pytest

from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


@pytest.mark.django_db
def test_no_leak_fragment_pre_reveal(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris", max_attempts=3)
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"Paris" not in resp.content
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_answer.py tests/test_quiz_noleak.py -v`
Expected: PASS (all)

- [ ] **Step 8: Commit**

```bash
git add courses/views.py templates/courses/elements/_quiz_question_feedback.html courses/static/courses/js/quiz.js tests/test_quiz_answer.py tests/test_quiz_noleak.py
git commit -m "feat(2c): quiz_answer [A] path — withhold state machine, locks, no-leak"
```

---

## Task 10: `quiz_answer` — `[N]` / `[R]` branch

The mode branch is already coded in Task 9 (`is_auto` else-branch). This task adds the tests + the neutral feedback rendering, confirming `[N]`/`[R]` persist without marking.

**Files:**
- Modify: `templates/courses/elements/_quiz_question_feedback.html` (neutral states)
- Test: `tests/test_quiz_answer.py` (append)

**Interfaces:**
- Consumes: the Task 9 view (no view change). The feedback context for `[N]`/`[R]` carries `mark_result=None`, `reveal_template=None`, and a `mode_label` for the neutral message.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_quiz_answer.py`)

```python
@pytest.mark.django_db
def test_not_marked_records_without_score_and_locks(client):
    user = make_login(client, "stu2")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Reflect", accepted="", marking_mode="N", max_attempts=3
    )
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    resp = client.post(url, {"answer": "my thoughts"}, HTTP_X_REQUESTED_WITH="fetch")
    assert b"Answer recorded" in resp.content
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.fraction is None and r.earned_marks is None
    assert r.attempt_count == 1
    a = Attempt.objects.get(response=r)
    assert a.fraction is None and a.correct is None


@pytest.mark.django_db
def test_not_marked_second_submit_rejected_despite_high_cap(client):
    user = make_login(client, "stu3")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Reflect", accepted="", marking_mode="N", max_attempts=5)
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    client.post(url, {"answer": "first"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.post(url, {"answer": "second"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409  # locked after first, cap irrelevant
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_answer.py -k "not_marked" -v`
Expected: FAIL — feedback lacks "Answer recorded".

- [ ] **Step 3: Add the neutral state** to `_quiz_question_feedback.html`. Update the top of the template so a non-validation, non-`mark_result` response (i.e. `[N]`/`[R]`) shows the neutral message:

```html
{% load i18n %}
{% if validation %}
  <div class="question__verdict is-validation">{% trans "Enter an answer" %}</div>
{% elif neutral %}
  <div class="question__verdict is-recorded">
    {% if neutral == "review" %}{% trans "Submitted for review" %}{% else %}{% trans "Answer recorded" %}{% endif %}
  </div>
{% elif mark_result %}
  ... (unchanged [A] block from Task 9) ...
{% endif %}
```

And set `neutral` in `_quiz_feedback_context` (Task 9) — extend it:

```python
    if not validation and result is None and response.locked:
        # [N]/[R]: recorded, no marking.
        ctx["neutral"] = (
            "review" if question.marking_mode == QuestionElement.MarkingMode.REVIEW
            else "recorded"
        )
```

(Place this branch before the `revealing` computation; when `neutral` is set, skip reveal logic.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_answer.py -v`
Expected: PASS (all, including Task 9 tests)

- [ ] **Step 5: Commit**

```bash
git add courses/views.py templates/courses/elements/_quiz_question_feedback.html tests/test_quiz_answer.py
git commit -m "feat(2c): quiz_answer [N]/[R] branch — recorded, no score, locked"
```

---

## Task 11: `quiz_finish` + scoring + `UnitProgress` + `quiz_results`

Finish: serialize on the submission, lock all responses, recompute scores from current `max_marks`/`marking_mode`, freeze, set `UnitProgress.completed`, redirect to the read-only results view.

**Files:**
- Modify: `courses/views.py` (`quiz_finish`, `quiz_results`, a `_score_submission` helper)
- Create: `templates/courses/quiz_results.html`
- Test: `tests/test_quiz_finish.py`

**Interfaces:**
- Consumes: `scoring.earned_marks`, the models, `UnitProgress`.
- Produces:
  - `quiz_finish(request, slug, node_pk)` — `@require_POST @login_required`; idempotent.
  - `quiz_results(request, slug, node_pk)` — GET; redirects to `quiz_unit` if submission absent/in_progress.
  - `_score_submission(node, submission) -> None` — recomputes `score`/`max_score`, locks all responses, sets status+submitted_at.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_finish.py
from decimal import Decimal

import pytest

from courses.models import QuestionResponse, QuizSubmission, UnitProgress
from tests.factories import (
    EnrollmentFactory, FillBlankQuestionElement, ShortTextQuestionElement,
    add_element, make_login, make_quiz_unit,
)


def _enrolled(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return user, unit


@pytest.mark.django_db
def test_finish_scores_partial_credit_and_unanswered_zero(client):
    user, unit = _enrolled(client)
    q1 = ShortTextQuestionElement.objects.create(stem="A?", accepted="x", max_marks=Decimal("2"))
    el1 = add_element(unit, q1)
    q2 = ShortTextQuestionElement.objects.create(stem="B?", accepted="y", max_marks=Decimal("3"))
    add_element(unit, q2)  # left unanswered

    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el1.pk}/answer/", {"answer": "x"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.post(f"{base}/finish/")
    assert resp.status_code == 302 and resp.url.endswith("/results/")

    sub = QuizSubmission.objects.get(student=user, unit=unit)
    assert sub.status == "submitted" and sub.submitted_at is not None
    assert sub.score == Decimal("2.00")        # q1 full, q2 unanswered=0
    assert sub.max_score == Decimal("5.00")    # 2 + 3
    assert UnitProgress.objects.get(student=user, unit=unit).completed


@pytest.mark.django_db
def test_finish_locks_all_responses(client):
    user, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="A?", accepted="x", max_attempts=None)
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "wrong"}, HTTP_X_REQUESTED_WITH="fetch")
    assert not QuestionResponse.objects.get(element=el).locked  # unlimited, not locked yet
    client.post(f"{base}/finish/")
    assert QuestionResponse.objects.get(element=el).locked       # Finish locked it


@pytest.mark.django_db
def test_finish_idempotent_freezes_score(client):
    user, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="A?", accepted="x", max_marks=Decimal("2"))
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "x"}, HTTP_X_REQUESTED_WITH="fetch")
    client.post(f"{base}/finish/")
    q.max_marks = Decimal("99")  # author edits after submit
    q.save()
    client.post(f"{base}/finish/")  # second finish = no-op
    assert QuizSubmission.objects.get(student=user, unit=unit).max_score == Decimal("2.00")


@pytest.mark.django_db
def test_results_redirects_when_in_progress(client):
    user, unit = _enrolled(client)
    resp = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/results/")
    assert resp.status_code == 302 and resp.url.endswith("/quiz/")


@pytest.mark.django_db
def test_zero_auto_quiz_no_div_by_zero(client):
    user, unit = _enrolled(client)
    q = ShortTextQuestionElement.objects.create(stem="R", accepted="", marking_mode="N")
    add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/finish/")
    sub = QuizSubmission.objects.get(student=user, unit=unit)
    assert sub.max_score == Decimal("0.00") and sub.score == Decimal("0.00")
    resp = client.get(f"{base}/results/")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_finish.py -v`
Expected: FAIL — no `quiz_finish`/`quiz_results`.

- [ ] **Step 3: Implement `_score_submission`, `quiz_finish`, `quiz_results`** (`courses/views.py`)

```python
def _score_submission(node, submission):
    """Recompute score/max_score from CURRENT max_marks/marking_mode, lock all
    responses, mark submitted. Caller holds select_for_update on the submission."""
    responses = {r.element_id: r for r in submission.responses.select_related()}
    total = Decimal("0.00")
    possible = Decimal("0.00")
    for el in node.elements.all().prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode != QuestionElement.MarkingMode.AUTO:
            continue
        possible += q.max_marks
        r = responses.get(el.pk)
        if r is not None and r.fraction is not None:
            total += earned_marks(r.fraction, q.max_marks)
    submission.responses.update(locked=True)
    submission.score = total
    submission.max_score = possible
    submission.status = QuizSubmission.Status.SUBMITTED
    submission.save()  # stamps submitted_at


from decimal import Decimal  # ensure imported at top of views.py


@require_POST
@login_required
def quiz_finish(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied
    with transaction.atomic():
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=request.user, unit=node
        )
        if submission.status != QuizSubmission.Status.SUBMITTED:
            _score_submission(node, submission)
            progress, _ = UnitProgress.objects.get_or_create(
                student=request.user, unit=node
            )
            if not progress.completed:
                progress.completed = True
                progress.save()
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


@login_required
def quiz_results(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    submission = QuizSubmission.objects.filter(
        student=request.user, unit=node, status=QuizSubmission.Status.SUBMITTED
    ).first()
    if submission is None:
        return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
    responses = {r.element_id: r for r in submission.responses.all()}
    rows = []
    for el in node.elements.order_by("order", "pk").prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        rows.append(_results_row(q, r))
    return render(request, "courses/quiz_results.html", {
        "course": course, "unit": node, "submission": submission, "rows": rows,
    })


def _results_row(question, response):
    """Outcome classification keyed on CURRENT marking_mode (stale fraction ignored
    for [N]). Returns a dict the results template renders."""
    mode = question.marking_mode
    row = {"question": question, "response": response, "outcome": None,
           "earned": None, "possible": question.max_marks}
    if mode == QuestionElement.MarkingMode.NOT_MARKED:
        row["outcome"] = "recorded" if response else "not_answered"
    elif mode == QuestionElement.MarkingMode.REVIEW:
        row["outcome"] = "review"
    else:  # [A]
        if response is None or response.fraction is None:
            row["outcome"] = "not_answered"
            row["earned"] = Decimal("0.00")
        else:
            earned = earned_marks(response.fraction, question.max_marks)
            row["earned"] = earned
            if earned == question.max_marks:
                row["outcome"] = "correct"
            elif earned > 0:
                row["outcome"] = "partial"
            else:
                row["outcome"] = "incorrect"
    return row
```

- [ ] **Step 4: Create `templates/courses/quiz_results.html`**

```html
{% extends "base.html" %}
{% load i18n static courses_extras %}
{% block head_title %}{{ unit.title }} — {% trans "Results" %} — libli{% endblock %}
{% block extra_css %}<link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">{% endblock %}
{% block content %}
<article class="quiz-results" lang="{{ course.language }}">
  <h1 class="lesson-unit__title">{{ unit.title }} — {% trans "Results" %}</h1>
  {% if submission.max_score %}
    <p class="quiz-results__total">{% trans "Score" %}: {{ submission.score|marks }} / {{ submission.max_score|marks }}</p>
  {% else %}
    <p class="quiz-results__total">{% trans "Score" %}: —</p>
  {% endif %}
  <ol class="quiz-results__list">
    {% for row in rows %}
    <li class="quiz-results__item is-{{ row.outcome }}">
      <div class="question__stem">{{ row.question.stem|safe }}</div>
      {% if row.outcome == "correct" %}<span class="badge">{% trans "Correct" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
      {% elif row.outcome == "partial" %}<span class="badge">{% trans "Partial" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
      {% elif row.outcome == "incorrect" %}<span class="badge">{% trans "Incorrect" %} (0/{{ row.possible|marks }})</span>
      {% elif row.outcome == "not_answered" %}<span class="badge">{% trans "Not answered" %}</span>
      {% elif row.outcome == "recorded" %}<span class="badge">{% trans "Answer recorded" %}</span>
      {% elif row.outcome == "review" %}<span class="badge">{% trans "Awaiting review" %}</span>{% endif %}
      {% if row.response and row.response.locked and row.question.REVEAL_TEMPLATE and row.outcome != "recorded" and row.outcome != "review" %}
        {% include row.question.REVEAL_TEMPLATE with el=row.question %}
      {% endif %}
      {% if row.question.explanation and row.outcome != "recorded" and row.outcome != "review" %}
        <div class="question__explanation">{{ row.question.explanation|safe }}</div>
      {% endif %}
    </li>
    {% endfor %}
  </ol>
  <a class="btn" href="{% url 'courses:course_outline' slug=course.slug %}">{% trans "Back to course" %}</a>
</article>
{% endblock %}
```

Note: the reveal includes (`_reveal_choice.html` etc.) read `el` and (for choice) `choices`/`mark_result`. For results, fill-blank/short-text/numeric reveals render from `el` alone; choice reveal needs `choices` + the correct set. If a choice reveal needs more context than `el`, render the choice outcome inline instead (list choices with `is_correct`). For this task, gate the `{% include REVEAL_TEMPLATE %}` to non-choice types and render a simple correct-answer line for choice; verify against the actual `_reveal_*.html` contents during implementation and adjust to whatever context each reveal partial requires.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_finish.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add courses/views.py templates/courses/quiz_results.html tests/test_quiz_finish.py
git commit -m "feat(2c): quiz_finish scoring + UnitProgress + quiz_results view"
```

---

## Task 12: Resume / rehydration + resume no-leak

`quiz_unit` GET reconstructs prior answers (pre-filled inputs, locked state, withhold-gated feedback). The no-JS `quiz_answer` re-render and the GET both go through `build_quiz_context`, so rehydration lives there.

**Files:**
- Modify: `courses/views.py` (`build_quiz_context` — populate per-element rehydration + feedback) and `templates/courses/quiz_unit.html`
- Test: `tests/test_quiz_resume.py`, `tests/test_quiz_noleak.py` (append resume assertion)

**Interfaces:**
- Consumes: `quiz.rehydrate`, `_quiz_feedback_context`.
- Produces: `build_quiz_context` now yields, per element, a small render-state object (`selected_ids`, `submitted_values`, `locked`, `attempts_left`, and a pre-rendered feedback fragment for answered questions). `quiz_unit.html` consumes it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_resume.py
import pytest

from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


def _enrolled_q(client, max_attempts=3):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", explanation="It's Paris.", max_attempts=max_attempts
    )
    el = add_element(unit, q)
    return user, unit, el


@pytest.mark.django_db
def test_resume_prefills_last_answer(client):
    user, unit, el = _enrolled_q(client)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.get(f"{base}/")
    assert b'value="London"' in resp.content


@pytest.mark.django_db
def test_resume_does_not_leak_for_unrevealed_question(client):
    user, unit, el = _enrolled_q(client)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.get(f"{base}/")          # reload
    assert b"Paris" not in resp.content    # withhold survives reload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_quiz_resume.py -v`
Expected: FAIL — resume renders blank inputs (no rehydration yet).

- [ ] **Step 3: Populate rehydration in `build_quiz_context`.** Replace the simple `responses` dict usage with a per-element render-state map, and have the template consume it. Update `build_quiz_context` to add:

```python
    from courses.views import _quiz_feedback_context  # same module; or define above

    render_states = {}
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        state = {
            "selected_ids": frozenset(),
            "submitted_values": None,
            "locked": bool(r.locked) if r else False,
            "feedback_html": "",
        }
        if r is not None and r.attempt_count > 0:
            selected, submitted = rehydrate(q, r.latest_answer)
            state["selected_ids"] = selected
            state["submitted_values"] = submitted
            # Re-render the withhold-gated feedback for this answered question.
            result = None
            if r.fraction is not None and r.locked:
                # Reveal only when locked & marked: reconstruct a MarkResult-like view
                result = q.mark(_answer_from_response(q, r))  # re-mark to get reveal payload
            ctx_fb = _quiz_feedback_context(q, r, result=result)
            state["feedback_html"] = render_to_string(
                "courses/elements/_quiz_question_feedback.html", ctx_fb
            )
        render_states[el.pk] = state
    ctx_extra = {"render_states": render_states}
```

Add a small helper `_answer_from_response(question, response)` that reconstructs the `mark()` input from `latest_answer` (inverse of `answer_to_json`): choice → `set(latest_answer)`; text/numeric → `latest_answer` (str); fill-blank → `list(latest_answer)`. Place it in `courses/quiz.py` and import it.

```python
# courses/quiz.py — append
def answer_from_json(question, latest_answer):
    """Inverse of answer_to_json for re-marking on resume."""
    if isinstance(question, ChoiceQuestionElement):
        return set(latest_answer or [])
    return latest_answer
```

Use `answer_from_json` (not a view-local helper) in `build_quiz_context`. Merge `render_states` into the returned context dict.

- [ ] **Step 4: Consume `render_states` in `quiz_unit.html`.** Replace the `{% render_element %}` line:

```html
    {% with st=render_states|dictkey:el.pk %}
    <section data-element-id="{{ el.pk }}">
      {% render_element el mode="quiz" quiz_submitted=quiz_submitted action_url=el|quiz_answer_url locked=st.locked selected_ids=st.selected_ids submitted_values=st.submitted_values %}
      {% if st.feedback_html %}<div class="question__feedback" data-question-feedback>{{ st.feedback_html|safe }}</div>{% endif %}
    </section>
    {% endwith %}
```

(The per-type template already renders its own `data-question-feedback` box when `feedback_for_pk` matches; on resume we instead inject the pre-rendered fragment. Ensure no double feedback box: pass `feedback_for_pk=None` on resume so the in-template box stays empty and only `st.feedback_html` shows. Since `render_element` is not passed `feedback_for_pk` here, it defaults to None — correct.)

- [ ] **Step 5: Append the resume no-leak assertion** to `tests/test_quiz_noleak.py`

```python
@pytest.mark.django_db
def test_no_leak_on_resume_render(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris", max_attempts=3)
    el = add_element(unit, q)
    base = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz"
    client.post(f"{base}/q/{el.pk}/answer/", {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    resp = client.get(f"{base}/")
    assert b"Paris" not in resp.content
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_resume.py tests/test_quiz_noleak.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add courses/views.py courses/quiz.py templates/courses/quiz_unit.html tests/test_quiz_resume.py tests/test_quiz_noleak.py
git commit -m "feat(2c): quiz resume/rehydration with withhold-gated no-leak"
```

---

## Task 13: Authoring — `marking_mode`/`max_attempts`/`max_marks` in the four question forms

Surface the three fields in the per-unit editor, only when the owning unit is a quiz; hide marks/attempts for `[N]`/`[R]`.

**Files:**
- Modify: `courses/element_forms.py` (add fields to the four question `ModelForm`s; a shared mixin)
- Modify: the editor view that builds the form (pass `unit_type`) and the editor template (conditionally render the fields)
- Test: `tests/test_quiz_authoring.py`

**Interfaces:**
- Consumes: the model fields (Task 3).
- Produces: each question form includes `marking_mode`/`max_attempts`/`max_marks` in `fields`; a form kwarg/attribute `is_quiz` controls whether they are required/shown.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_quiz_authoring.py
import pytest

from courses.element_forms import ShortTextQuestionElementForm


@pytest.mark.django_db
def test_quiz_question_form_accepts_marking_fields():
    form = ShortTextQuestionElementForm(data={
        "stem": "Q", "explanation": "", "accepted": "a", "case_sensitive": False,
        "marking_mode": "A", "max_attempts": 2, "max_marks": "3",
    })
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    assert obj.max_attempts == 2 and str(obj.max_marks) == "3"


@pytest.mark.django_db
def test_quiz_question_form_rejects_zero_max_marks():
    form = ShortTextQuestionElementForm(data={
        "stem": "Q", "explanation": "", "accepted": "a", "case_sensitive": False,
        "marking_mode": "A", "max_attempts": 1, "max_marks": "0",
    })
    assert not form.is_valid()
    assert "max_marks" in form.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_quiz_authoring.py -v`
Expected: FAIL — the form drops `marking_mode`/`max_attempts`/`max_marks` (not in `fields`).

- [ ] **Step 3: Add the fields to the four forms.** Append `"marking_mode", "max_attempts", "max_marks"` to each question form's `Meta.fields`. Example for `ShortTextQuestionElementForm`:

```python
class ShortTextQuestionElementForm(forms.ModelForm):
    class Meta:
        model = ShortTextQuestionElement
        fields = ["stem", "explanation", "accepted", "case_sensitive",
                  "marking_mode", "max_attempts", "max_marks"]
```

Apply the same three-field append to `ChoiceQuestionElementForm`, `ShortNumericQuestionElementForm`, and `FillBlankQuestionElementForm`. The model-level `MinValueValidator(Decimal("0.01"))` on `max_marks` (Task 3) drives the zero-rejection test; ModelForm runs model validators on the field, so no extra form validation is needed for that case.

- [ ] **Step 4: Conditionally render in the editor.** In the editor template that renders each question form (locate via `grep -rl "element_form\|editor" templates/courses/manage* templates/courses/elements/_editor*`), wrap the three new fields in `{% if is_quiz %}...{% endif %}`, and pass `is_quiz=(unit.unit_type == "quiz")` from the editor/element_form view (`courses/views_manage.py`) into the form-render context. Within that block, wrap `max_attempts`/`max_marks` in a `data-marks-fields` container that JS hides when `marking_mode` is `N`/`R` (progressive enhancement; server still accepts them and ignores per §2.1). For this task's automated test the form-level acceptance is what's asserted; the conditional rendering is verified in the e2e task.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_quiz_authoring.py tests/test_questions_2b_forms.py -v`
Expected: PASS — new authoring tests pass and existing 2b form tests still pass.

- [ ] **Step 6: Commit**

```bash
git add courses/element_forms.py courses/views_manage.py templates/courses/ tests/test_quiz_authoring.py
git commit -m "feat(2c): quiz marking fields in question authoring forms"
```

---

## Task 14: i18n — Polish strings

Wrap any remaining literals and add Polish translations for all new quiz strings.

**Files:**
- Modify: `courses/static/courses/js/quiz.js` (move the confirm copy to a `data-` attribute set from a `{% trans %}` string in `quiz_unit.html`)
- Modify: `locale/pl/LC_MESSAGES/django.po` (translations)
- Test: `tests/test_i18n_quiz.py`

**Interfaces:**
- Consumes: the templates' `{% trans %}`/`{% blocktrans %}` strings.
- Produces: a `pl` translation for each new msgid; the Finish-confirm copy sourced from a translated `data-confirm` attribute.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_i18n_quiz.py
import pytest
from django.utils import translation

from tests.factories import (
    EnrollmentFactory, ShortTextQuestionElement, add_element, make_login, make_quiz_unit,
)


@pytest.mark.django_db
def test_quiz_finish_label_translated_pl(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="a")
    add_element(unit, q)
    with translation.override("pl"):
        resp = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/",
                          HTTP_ACCEPT_LANGUAGE="pl")
    # The PL translation of "Finish quiz" (set in Step 3) must appear.
    assert "Zakończ quiz".encode() in resp.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_i18n_quiz.py -v`
Expected: FAIL — untranslated English "Finish quiz" rendered.

- [ ] **Step 3: Extract and translate.** Move the JS confirm literal into the template:

In `quiz_unit.html`, set the confirm copy as a data attribute:
```html
  <form class="quiz-finish" method="post" data-quiz-finish
        data-confirm="{% trans 'Finish the quiz? You can’t change your answers afterwards.' %}"
        action="{% url 'courses:quiz_finish' slug=course.slug node_pk=unit.pk %}">
```
and in `quiz.js` read `finish.dataset.confirm` instead of the literal.

Run extraction and add translations:
```bash
uv run python manage.py makemessages -l pl -i ".venv"
```
Then edit `locale/pl/LC_MESSAGES/django.po`, filling in msgstr for the new msgids, including:
- `"Finish quiz"` → `"Zakończ quiz"`
- `"Answer recorded"` → `"Odpowiedź zapisana"`
- `"Submitted for review"` → `"Przesłano do oceny"`
- `"Enter an answer"` → `"Wpisz odpowiedź"`
- `"Correct"` / `"Incorrect"` / `"Partial"` / `"Not answered"` / `"Awaiting review"` / `"Results"` / `"Score"` / `"Back to course"` — Polish equivalents
- the `{% blocktrans count %}` "N attempts left" plural forms

Then compile:
```bash
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_i18n_quiz.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/quiz.js templates/courses/ locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_quiz.py
git commit -m "i18n(2c): Polish strings for quiz units"
```

---

## Task 15: e2e — Playwright (JS + no-JS)

End-to-end: author a quiz, answer across types, exhaust attempts, finish, see results; assert no leak before reveal and lock-after-finish.

**Files:**
- Create: `tests/test_e2e_quiz.py`

**Interfaces:**
- Consumes: the full stack. Mirror the structure of `tests/test_e2e_questions_2b.py` (the established Playwright pattern in this repo — fixtures, live-server, page helpers).

- [ ] **Step 1: Write the e2e tests** (model after `tests/test_e2e_questions_2b.py`; concrete flow below)

```python
# tests/test_e2e_quiz.py
import pytest

# Reuse the repo's existing Playwright fixtures/conventions from test_e2e_questions_2b.py
# (live_server, page, a logged-in enrolled student, a quiz unit with questions).

pytestmark = pytest.mark.e2e


def test_quiz_answer_finish_results_js(live_server, page, quiz_with_questions, login_student):
    course, unit, els = quiz_with_questions  # short-text(correct=Paris, max_attempts=2)
    login_student(page)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")

    # Wrong answer: withhold (no "Paris", shows attempts-left)
    q = page.locator("[data-element-id]").first
    q.locator("input[name=answer]").fill("London")
    q.locator("button[type=submit]").click()
    page.wait_for_selector("[data-question-feedback] .is-incorrect")
    assert "Paris" not in page.content()

    # Correct on second attempt: reveal + lock
    q.locator("input[name=answer]").fill("Paris")
    q.locator("button[type=submit]").click()
    page.wait_for_selector("[data-question-feedback] .is-correct")
    assert q.locator("input[name=answer]").is_disabled()

    # Finish (accept confirm) -> results
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/")
    assert "/results/" in page.url


def test_quiz_no_js_full_flow(live_server, client, quiz_with_questions, enrolled_student):
    # Drive via the Django test client (no JS) to assert no-JS parity:
    course, unit, els = quiz_with_questions
    base = f"/courses/{course.slug}/u/{unit.pk}/quiz"
    r = client.post(f"{base}/q/{els[0].pk}/answer/", {"answer": "London"})  # no X-Requested-With
    assert r.status_code == 200 and b"Paris" not in r.content   # full re-render, withheld
    r = client.post(f"{base}/finish/")
    assert r.status_code == 302 and r.url.endswith("/results/")
```

- [ ] **Step 2: Run the e2e tests**

Run: `uv run pytest tests/test_e2e_quiz.py -v`
Expected: PASS. (If the repo gates e2e behind a marker/browser install, follow the same invocation as `tests/test_e2e_questions_2b.py`.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_quiz.py
git commit -m "test(2c): Playwright e2e — quiz answer/finish/results (JS + no-JS)"
```

---

## Task 16: Full suite + lint gate

Confirm the whole slice is green and lint-clean before review.

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all pass (no regressions in 2a/2b lesson tests; new quiz tests green).

- [ ] **Step 2: Run the linter/formatter**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean. Fix any findings, re-run.

- [ ] **Step 3: Apply migrations on a fresh DB to confirm they're consistent**

Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected" (all model changes captured in committed migrations).

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore(2c): lint + migration-consistency gate"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- §2.1 marking fields → Task 3. §2.2–2.4 models → Task 4. §3.5/§3.6 scoring + display → Tasks 1–2. §3.1 submission/branch/concurrency → Tasks 9–10. §3.2 withhold state machine → Task 9. §3.3 [N]/[R] → Task 10. §3.4 Finish/scoring/results → Task 11. §4.1 views (require_quiz, is_enrolled, quiz_results redirect) → Tasks 5, 8, 11. §4.2 templates → Tasks 8, 9, 11. §4.3 quiz-mode render → Task 7. §4.4 resume + resume no-leak → Task 12. §5.1 no-leak (both transports + resume) → Tasks 9, 12. §5.2 edge cases (cap, zero-[A], unanswered, idempotent) → Tasks 9, 11. §5.3 i18n → Task 14. §5.4 tests → woven through. §5.5 authoring → Task 13.
- Concurrency (`select_for_update`, `UniqueConstraint(response, n)`) → constraint in Task 4, locks in Tasks 9 & 11.

**Type consistency:** `to_stored_fraction`/`earned_marks` (Task 1) used verbatim in Tasks 9 & 11. `_quiz_feedback_context` (Task 9) reused in Tasks 10 & 12. `rehydrate`/`answer_to_json`/`answer_from_json` (Tasks 6, 12) used in Tasks 9 & 12. `render_element`/`render` kwargs (Task 7) consumed by templates in Tasks 8 & 12. `QuizSubmission.Status`/`QuestionElement.MarkingMode` enums used consistently.

**Known implementation check (flagged for the implementer):** Task 11's results template includes per-type `REVEAL_TEMPLATE` partials — verify each `_reveal_*.html`'s required context (choice reveal needs `choices`/correct set) and adapt the include accordingly; this is the one spot where the per-type reveal context must be confirmed against the actual partials during implementation.
