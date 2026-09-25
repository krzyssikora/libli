# Quiz answer reveal — PR 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the shared "Show answer" + Your/Correct switch machinery and convert fill in the blanks, short text and number to it — in quizzes (live, resume, no-JS, previewer, editor try-it, results page) and, for short text and number, in lessons (D13).

**Architecture:** Everything is server-rendered. Two per-type hooks (`part_verdicts`, `key_answer`) plus one flag (`SUPPORTS_REVEAL`) drive it; one helper (`courses.quiz.quiz_render_state`) computes every quiz render key from a (question, response, result) triple so the four quiz render paths cannot drift; the correct-answer copy is the type's own controls include rendered a second time and neutralised by one BeautifulSoup pass (`courses.keycopy`). A new nullable `QuestionResponse.revealed_at` records a reveal.

**Tech Stack:** Django 5 templates, Python 3.13, PostgreSQL, vanilla JS (quiz.js, editor.js, question.js), BeautifulSoup4, pytest + pytest-django + Playwright.

**Spec:** `docs/superpowers/specs/2026-09-25-quiz-answer-reveal-design.md` (owner decisions D1–D13 are VERBATIM intent — never reverse one). This plan is **PR 1 of 3** (spec §8). PR 2 (drag, match, grids, drag onto image) and PR 3 (multiple choice, extended response) get their own plans after this merges.

## Global Constraints

- Owner decisions D1–D13 in the spec are verbatim; a task that seems to need reversing one STOPS and asks.
- `SUPPORTS_REVEAL` is set in PR 1 on **exactly** `FillBlankQuestionElement`, `ShortTextQuestionElement`, `ShortNumericQuestionElement`. Every other type must behave exactly as today **except the result line** (spec §2.1).
- Lessons never render the key copy, the switch, or the Show answer button (D11).
- Before the lock, only per-part **booleans** reach the page — never accepted-answer text (spec §2.1, §7 "no leak").
- The key copy: every control `disabled`, no `name`, every `id` suffixed `-key`; rendered **only** when `key_view(...)` returns non-None (spec §2.2).
- Check is the **first** submit button in every question form (spec §3.1).
- Migration dependency = the graph head at the time of writing (today `0066_blank_answers_unescape`).
- Colour is never the only cue: a painted part carries `aria-invalid="true"` when wrong and `.sr-only` "correct"/"incorrect" text (spec §2.1). Use the global `.sr-only` class (`core/static/core/css/reset.css`), NOT `.visually-hidden` (redefined in notes/tags CSS).
- Tests: run with `uv run pytest …` after `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. e2e needs `-m e2e`. Never pass `-q`. Scope runs to the files named in each task; the whole-repo sweep is Task 12 only.
- Template comments: `{# #}` is single-line only; multi-line comments use `{% comment %}…{% endcomment %}`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Double reveal / reveal racing a Check** — a second reveal POST on an already-revealed question must get the locked response (409 on fetch), leave `attempt_count` untouched and not crash. Test in Task 8 (`test_second_reveal_is_refused`).
2. **Author adds a blank after a student answered** — the stored answer has fewer entries than the stem has blanks; resume and results must render without error, painting the extra blank as wrong (mark pads with ""). Test in Task 8 (`test_resume_after_blank_added`).
3. **`max_attempts=1` wrong answer** — locks immediately; no Show answer button ever appears, but the key copy and switch do. Test in Task 8 (`test_single_attempt_wrong_locks_with_key_no_button`).
4. **Key text with HTML/LaTeX specials** (accepted answer `a<b` or `\(x\)`) — shown escaped in the key copy's `value`, never as markup. Test in Task 4 (`test_key_copy_escapes_value`) and Task 7.
5. **Unlimited attempts, partial answer** — result line has no "attempts left" segment, Show answer is offered. Test in Task 5 (`test_unlimited_attempts_line_omits_count`) and Task 8 (`test_unlimited_attempts_partial_offers_reveal`).

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/marking.py` | `MarkResult.fresh_correct` (new optional field) |
| `courses/models.py` | `SUPPORTS_REVEAL`, `CONTROLS_TEMPLATE`, `part_verdicts`, `key_answer`, `render_key_copy`; `render()` new kwargs; `QuestionResponse.revealed_at`; per-type hooks |
| `courses/migrations/0067_questionresponse_revealed_at.py` | new column |
| `courses/scoring.py` | `outcome(earned, max_marks)` |
| `courses/quiz.py` | `can_reveal`, `key_view`, `quiz_render_state`; `ephemeral_quiz_feedback(reveal=)`; stand-in `revealed_at`; `quiz_feedback_context` result-line keys |
| `courses/keycopy.py` (new) | `neutralise_key_copy(html)` — the one bs4 post-pass |
| `courses/fillblank.py` | `render_inputs` adds `.sr-only` verdict text |
| `courses/templatetags/courses_extras.py` | `render_element` forwards new keys; `render_fill_blanks(verdicts=)` |
| `courses/views.py` | `_stored_result` fresh_correct; `build_quiz_context`, `_quiz_render_feedback`, `quiz_answer` reveal branch, `_quiz_reveal_refused`, `_results_row` (outcome helper + `revealed` key), results render helper |
| `courses/views_manage.py` | `element_try` quiz branch: reveal + whole element |
| `templates/courses/elements/_answer_switch.html` (new) | the switch |
| `templates/courses/elements/_reveal_button.html` (new) | the Show answer button |
| `templates/courses/elements/_results_question_feedback.html` (new) | results-mode feedback box |
| `templates/courses/elements/_fillblankquestionelement_controls.html` (new) | fill-blank controls include |
| `templates/courses/elements/_shorttextquestionelement_controls.html` (new) | short-text controls include |
| `templates/courses/elements/_shortnumericquestionelement_controls.html` (new) | number controls include |
| `templates/courses/elements/{fillblank,shorttext,shortnumeric}questionelement.html` | results branch, key copy, switch, button, `data-answer-scope` |
| `templates/courses/elements/_quiz_question_feedback.html` | partial / marks / answer shown |
| `templates/courses/_quiz_article.html` | forward new `st.*` keys |
| `templates/courses/quiz_results.html` | converted rows render the element |
| `templates/courses/manage/analytics_student_quiz.html` | "answer shown" tag |
| `courses/static/courses/css/courses.css` | switch, key copy visibility, text-input verdict colours, partial verdict |
| `courses/static/courses/js/quiz.js`, `editor.js` | submitter + fallback, confirm, counter, freeze exclusion |
| `docs/help/course-admin/quiz-editors.md` + `.pl.md` | help |
| `locale/pl/LC_MESSAGES/django.po/.mo` | strings |

---

### Task 1: Per-type hooks and `MarkResult.fresh_correct`

**Files:**
- Modify: `courses/marking.py` (class `MarkResult`)
- Modify: `courses/models.py` (class `QuestionElement`, `ShortTextQuestionElement`, `ShortNumericQuestionElement`, `FillBlankQuestionElement`; new module helper `_single_part_verdict`)
- Modify: `courses/views.py` (`_stored_result`)
- Test: `tests/test_quiz_reveal_hooks.py` (new)

**Interfaces:**
- Produces: `MarkResult.fresh_correct: bool | None = None`; `QuestionElement.SUPPORTS_REVEAL: bool = False`; `QuestionElement.CONTROLS_TEMPLATE: str | None = None`; `QuestionElement.part_verdicts(mark_result, answer) -> list[bool | None] | None`; `QuestionElement.key_answer() -> object | None`; `views._stored_result(question, response) -> MarkResult` now sets `fresh_correct`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_hooks.py
"""Per-type reveal hooks (spec 2026-09-25 §2.1, §2.2, §2.6)."""

from decimal import Decimal

import pytest

from courses.fillblank import parse
from courses.marking import MarkResult
from courses.models import Blank
from courses.models import ChoiceQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.views import _stored_result
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit


def _fillblank(accepted):
    token_stem, _ = parse(" ".join("{{%s}}" % (a or "x") for a in accepted))
    q = FillBlankQuestionElement.objects.create(stem=token_stem)
    for i, acc in enumerate(accepted):
        Blank.objects.create(question=q, order=i, accepted=acc)
    return q


@pytest.mark.django_db
def test_fillblank_part_verdicts_one_bool_per_blank():
    q = _fillblank(["11", "9", "2"])
    result = q.mark(["11", "", "5"])
    assert q.part_verdicts(result, ["11", "", "5"]) == [True, False, False]


@pytest.mark.django_db
def test_shorttext_part_verdicts_live_uses_correct():
    q = ShortTextQuestionElement.objects.create(stem="?", accepted="Paris")
    assert q.part_verdicts(q.mark("Paris"), "Paris") == [True]
    assert q.part_verdicts(q.mark("Rome"), "Rome") == [False]


def test_single_part_verdict_prefers_fresh_correct():
    q = ShortTextQuestionElement(accepted="Paris")
    stored = MarkResult(correct=True, fraction=1.0, fresh_correct=False)
    assert q.part_verdicts(stored, "Paris") == [False]


def test_numeric_part_verdicts():
    q = ShortNumericQuestionElement(value="3.14", tolerance="0.01")
    assert q.part_verdicts(q.mark("3.15"), "3.15") == [True]
    assert q.part_verdicts(q.mark("4"), "4") == [False]


@pytest.mark.django_db
def test_key_answers():
    assert ShortTextQuestionElement(accepted="Paris\nparis").key_answer() == "Paris"
    assert ShortTextQuestionElement(accepted="").key_answer() is None
    assert ShortNumericQuestionElement(value="3.14").key_answer() == "3.14"
    assert _fillblank(["11", "9"]).key_answer() == ["11", "9"]


@pytest.mark.django_db
def test_fillblank_key_answer_partial_empty_kept_whole_empty_none():
    assert _fillblank(["11", ""]).key_answer() == ["11", ""]
    assert _fillblank(["", ""]).key_answer() is None


def test_unconverted_type_hooks_are_none():
    q = ChoiceQuestionElement()
    assert q.SUPPORTS_REVEAL is False
    assert q.part_verdicts(MarkResult(correct=False, fraction=0.0), set()) is None
    assert q.key_answer() is None


@pytest.mark.django_db
def test_stored_result_carries_fresh_correct_after_key_edit():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="?", accepted="Paris")
    el = add_element(unit, q)
    sub = QuizSubmission.objects.create(student=UserFactory(), unit=unit)
    r = QuestionResponse.objects.create(
        submission=sub, element=el, attempt_count=1, latest_answer="Paris",
        fraction=Decimal("1.0000"), locked=True,
    )
    q.accepted = "Lyon"
    q.save()
    stored = _stored_result(q, r)
    assert stored.correct is True  # stored fraction
    assert stored.fresh_correct is False  # the key as it is now
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_hooks.py -p no:randomly`
Expected: FAIL — `AttributeError: ... has no attribute 'part_verdicts'` / `TypeError: MarkResult.__init__() got an unexpected keyword argument 'fresh_correct'`.

- [ ] **Step 3: Implement**

In `courses/marking.py`, add the field as the last field of `MarkResult` (after `annotated`):

```python
    # Stored paths only (views._stored_result): the FRESH mark().correct, which can
    # differ from `correct` (the stored fraction) once an author edits the key. A
    # live mark() leaves it None; single-part part_verdicts fall back to `correct`.
    fresh_correct: bool | None = None
```

In `courses/models.py`, inside `class QuestionElement`, directly after `INLINE_LESSON_FEEDBACK = False`:

```python
    # Quiz answer reveal (spec 2026-09-25 §2.1): may a student press Show answer, do
    # quiz Checks answer with the whole element, and does the results page render
    # the question itself? Set per type, PR by PR; base off.
    SUPPORTS_REVEAL = False

    # The type's answer-controls include, rendered once for "Your answer" and once
    # (via render_key_copy) for the correct answer. Set by each converted type.
    CONTROLS_TEMPLATE = None
```

and after `def feedback_context(...)` (before `def mark`):

```python
    def part_verdicts(self, mark_result, answer):
        """Right/wrong per answer part in draw order: True / False, None = paint
        nothing. Returns None when the type paints no parts (spec §2.1)."""
        return None

    def key_answer(self):
        """The correct answer in exactly build_answer()'s shape, or None when there
        is no key to show (spec §2.2)."""
        return None
```

Add a module-level helper directly above `class ShortTextQuestionElement`:

```python
def _single_part_verdict(mark_result):
    """One-part types: a stored path's fresh correctness wins over the stored one
    (spec §2.6); a live mark() leaves fresh_correct None."""
    fresh = mark_result.fresh_correct
    return bool(mark_result.correct if fresh is None else fresh)
```

In `ShortTextQuestionElement`, after `mark()`:

```python
    def part_verdicts(self, mark_result, answer):
        return [_single_part_verdict(mark_result)]

    def key_answer(self):
        lines = _accepted_lines(self.accepted)
        return lines[0] if lines else None
```

In `ShortNumericQuestionElement`, after `mark()`:

```python
    def part_verdicts(self, mark_result, answer):
        return [_single_part_verdict(mark_result)]

    def key_answer(self):
        # A plain string: build_answer's shape (post.get("answer", "")).
        return self.value or None
```

In `FillBlankQuestionElement`, after `mark()`:

```python
    def part_verdicts(self, mark_result, answer):
        return [bool(item["correct"]) for item in mark_result.reveal]

    def key_answer(self):
        firsts = [(_accepted_lines(b.accepted) or [""])[0] for b in self.blanks.all()]
        # A blank with no accepted line stays an (empty) part; only a wholly empty
        # key hides the copy (spec §2.2 "empty keys").
        return firsts if any(firsts) else None
```

In `courses/views.py`, `_stored_result`, add `fresh_correct=m.correct,` to the `MarkResult(...)` call.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_quiz_reveal_hooks.py -p no:randomly`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add courses/marking.py courses/models.py courses/views.py tests/test_quiz_reveal_hooks.py
git commit -m "feat(quiz-reveal): per-type part_verdicts / key_answer hooks + MarkResult.fresh_correct"
```

---

### Task 2: `QuestionResponse.revealed_at` + migration

**Files:**
- Modify: `courses/models.py` (class `QuestionResponse`)
- Create: `courses/migrations/0067_questionresponse_revealed_at.py` (generated)
- Test: `tests/test_quiz_reveal_hooks.py` (append)

**Interfaces:**
- Produces: `QuestionResponse.revealed_at: DateTimeField(null=True, blank=True)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_quiz_reveal_hooks.py`)

```python
def test_revealed_at_is_a_nullable_datetime():
    field = QuestionResponse._meta.get_field("revealed_at")
    assert field.get_internal_type() == "DateTimeField"
    assert field.null is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_quiz_reveal_hooks.py::test_revealed_at_is_a_nullable_datetime -p no:randomly`
Expected: FAIL — `FieldDoesNotExist`.

- [ ] **Step 3: Implement**

In `class QuestionResponse`, after `last_attempt_at`:

```python
    # Set when the student pressed Show answer (spec 2026-09-25 §3). Null = never.
    revealed_at = models.DateTimeField(null=True, blank=True)
```

Generate the migration and check its dependency is the current graph head:

```bash
ls courses/migrations | grep -E "^0[0-9]+" | sort | tail -1   # the head BEFORE generating
uv run python manage.py makemigrations courses -n questionresponse_revealed_at
grep -n "dependencies" -A3 courses/migrations/0067_questionresponse_revealed_at.py
```
Expected: the file depends on the head the `ls` printed (today `("courses", "0066_blank_answers_unescape")`). If another 0067 already exists on master, rebase first and regenerate — never hand-renumber.

- [ ] **Step 4: Run to verify it passes, and the migration is complete**

Run: `uv run pytest tests/test_quiz_reveal_hooks.py -p no:randomly` → PASS.
Run: `uv run python manage.py makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 5: Commit**

```bash
git add courses/models.py courses/migrations/0067_questionresponse_revealed_at.py tests/test_quiz_reveal_hooks.py
git commit -m "feat(quiz-reveal): QuestionResponse.revealed_at"
```

---

### Task 3: Quiz helpers — `outcome`, `can_reveal`, `key_view`, ephemeral reveal, `quiz_render_state`

**Files:**
- Modify: `courses/scoring.py` (new `outcome`)
- Modify: `courses/quiz.py`
- Modify: `courses/views.py` (`_results_row` uses `outcome`)
- Test: `tests/test_quiz_reveal_helpers.py` (new)

**Interfaces:**
- Consumes: Task 1 hooks, Task 2 field.
- Produces:
  - `courses.scoring.outcome(earned: Decimal, max_marks: Decimal) -> str` ∈ `{"correct","partial","incorrect"}`
  - `courses.quiz.can_reveal(question, *, attempts_made: int, locked: bool) -> bool`
  - `courses.quiz.key_view(question, *, mode: str, locked: bool, fully_correct: bool) -> object | None`
  - `courses.quiz.ephemeral_quiz_feedback(question, answer, attempt, *, reveal=False)` — stand-in gains `.revealed_at` on every branch
  - `courses.quiz.quiz_render_state(question, response, result) -> dict` with keys `locked, selected_ids, submitted_values, mark_result, verdicts, key_values, can_reveal, reveal_earned, revealed`
  - `courses.quiz.BLANK_QUIZ_STATE: dict` (the same keys, empty values)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_helpers.py
"""Reveal helpers (spec 2026-09-25 §2.2, §2.5, §3.3, §3.5)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from courses.fillblank import parse
from courses.models import Blank
from courses.models import ChoiceQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import ShortTextQuestionElement
from courses.quiz import BLANK_QUIZ_STATE
from courses.quiz import can_reveal
from courses.quiz import ephemeral_quiz_feedback
from courses.quiz import key_view
from courses.quiz import quiz_render_state
from courses.scoring import outcome

A = QuestionElement.MarkingMode.AUTO
N = QuestionElement.MarkingMode.NOT_MARKED
R = QuestionElement.MarkingMode.REVIEW


def test_outcome_by_earned_marks():
    assert outcome(Decimal("1.00"), Decimal("1")) == "correct"
    assert outcome(Decimal("0.25"), Decimal("1")) == "partial"
    assert outcome(Decimal("0.00"), Decimal("1")) == "incorrect"


@pytest.fixture
def converted(monkeypatch):
    monkeypatch.setattr(ShortTextQuestionElement, "SUPPORTS_REVEAL", True)
    return ShortTextQuestionElement(accepted="Paris", marking_mode=A)


def test_can_reveal_matrix(converted):
    assert can_reveal(converted, attempts_made=1, locked=False) is True
    assert can_reveal(converted, attempts_made=0, locked=False) is False
    assert can_reveal(converted, attempts_made=1, locked=True) is False
    converted.marking_mode = N
    assert can_reveal(converted, attempts_made=1, locked=False) is False
    converted.marking_mode = R
    assert can_reveal(converted, attempts_made=1, locked=False) is False


def test_can_reveal_refuses_unconverted_type():
    q = ChoiceQuestionElement(marking_mode=A)
    assert can_reveal(q, attempts_made=3, locked=False) is False


def test_key_view_matrix():
    q = ShortTextQuestionElement(accepted="Paris", marking_mode=A)
    kw = dict(locked=True, fully_correct=False)
    assert key_view(q, mode="quiz", **kw) == "Paris"
    assert key_view(q, mode="results", **kw) == "Paris"
    assert key_view(q, mode="lesson", **kw) is None
    assert key_view(q, mode="quiz", locked=False, fully_correct=False) is None
    assert key_view(q, mode="quiz", locked=True, fully_correct=True) is None
    for m in (N, R):
        q.marking_mode = m
        assert key_view(q, mode="quiz", **kw) is None  # N/R never show a key


def test_ephemeral_stand_in_always_has_revealed_at():
    q = ShortTextQuestionElement(accepted="Paris", marking_mode=A, max_attempts=3)
    for answer in ("", "Rome"):
        stand_in, _r, _v = ephemeral_quiz_feedback(q, answer, 1)
        assert stand_in.revealed_at is None


def test_ephemeral_reveal_locks_marks_form_and_skips_validation():
    q = ShortTextQuestionElement(accepted="Paris", marking_mode=A, max_attempts=3)
    stand_in, result, validation = ephemeral_quiz_feedback(q, "", 1, reveal=True)
    assert validation is False
    assert stand_in.locked is True and stand_in.revealed_at is not None
    assert result.correct is False and result.fraction == 0.0
    assert stand_in.attempt_count == 1  # the reveal consumes no attempt


@pytest.mark.django_db
def test_quiz_render_state_unlocked_partial_paints_without_key(monkeypatch):
    monkeypatch.setattr(FillBlankQuestionElement, "SUPPORTS_REVEAL", True)
    token_stem, _ = parse("{{11}} {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=3)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    resp = SimpleNamespace(
        locked=False, attempt_count=1, latest_answer=["11", "5"], revealed_at=None
    )
    st = quiz_render_state(q, resp, q.mark(["11", "5"]))
    assert st["verdicts"] == [True, False]
    assert st["key_values"] is None and st["mark_result"] is None
    assert st["can_reveal"] is True
    assert st["reveal_earned"] == Decimal("0.50")
    assert st["submitted_values"] == ["11", "5"]


@pytest.mark.django_db
def test_quiz_render_state_locked_partial_has_key_and_result():
    token_stem, _ = parse("{{11}} {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=1)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    resp = SimpleNamespace(
        locked=True, attempt_count=1, latest_answer=["11", "5"], revealed_at=None
    )
    result = q.mark(["11", "5"])
    st = quiz_render_state(q, resp, result)
    assert st["key_values"] == ["11", "9"]
    assert st["mark_result"] is result
    assert st["can_reveal"] is False


@pytest.mark.django_db
def test_quiz_render_state_stored_correct_paints_all_green():
    # §2.6 reverse case: stored fully correct, key edited since -> all True.
    from courses.marking import MarkResult

    token_stem, _ = parse("{{11}} {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="7")  # edited after answering
    fresh = q.mark(["11", "9"])
    stored = MarkResult(correct=True, fraction=1.0, reveal=fresh.reveal,
                        fresh_correct=fresh.correct)
    resp = SimpleNamespace(
        locked=True, attempt_count=1, latest_answer=["11", "9"], revealed_at=None
    )
    st = quiz_render_state(q, resp, stored)
    assert st["verdicts"] == [True, True]
    assert st["key_values"] is None  # fully correct: no copy, no switch


def test_blank_state_has_every_key():
    assert set(BLANK_QUIZ_STATE) == {
        "locked", "selected_ids", "submitted_values", "mark_result", "verdicts",
        "key_values", "can_reveal", "reveal_earned", "revealed",
    }
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_helpers.py -p no:randomly`
Expected: FAIL — `ImportError: cannot import name 'outcome'` (and the others).

- [ ] **Step 3: Implement**

Append to `courses/scoring.py`:

```python
def outcome(earned, max_marks):
    """'correct' / 'partial' / 'incorrect' from EARNED marks (spec 2026-09-25 §2.5):
    the one classifier the live result line and the results page share, so a tiny
    fraction that rounds to 0.00 reads "incorrect" in both places."""
    if earned == max_marks:
        return "correct"
    if earned > 0:
        return "partial"
    return "incorrect"
```

In `courses/views.py` `_results_row`, replace the three-way `if earned == …/elif earned > 0/else` block with:

```python
            row["outcome"] = outcome(earned, question.max_marks)
```
and add `from courses.scoring import outcome` next to the existing `earned_marks` import.

In `courses/quiz.py`:
- change the scoring import to `from courses.scoring import earned_marks` + `from courses.scoring import to_stored_fraction`, and add `from django.utils import timezone`;
- in `parse_attempt`'s docstring, change the reserved-names sentence to: "`attempt`, `reveal` and `answer_view_<pk>` are RESERVED answer-POST field names (spec 2026-09-25 §2.3): NO QuestionElement.build_answer implementation may read them -- all ten read only choice / answer / blank / slot / row_<pk>.";
- update `ephemeral_quiz_feedback`'s docstring: the stand-in now has FOUR attributes (`locked`, `attempt_count`, `latest_answer`, `revealed_at`) on every branch, and there is a third branch — `reveal=True` skips the empty-answer validation, marks the form as-is, locks, and consumes no attempt;
- add `revealed_at=None` to BOTH existing `SimpleNamespace(...)` calls in `ephemeral_quiz_feedback`, give it a keyword-only `reveal=False` parameter, and insert this branch **directly after `latest = answer_to_json(answer)`** and before `if answer_is_empty(answer):` (it uses `latest`):

```python
    if reveal:
        # Show answer on the stateless path (spec §3.3): bypasses the empty-answer
        # validation, marks whatever the form holds, locks, consumes no attempt.
        # The caller has already checked can_reveal().
        return (
            SimpleNamespace(
                locked=True,
                attempt_count=attempt,
                latest_answer=latest,
                revealed_at=timezone.now(),
            ),
            question.mark(answer),
            False,
        )
```

- append the new helpers (after `locked_after`):

```python
def can_reveal(question, *, attempts_made, locked):
    """May Show answer be offered / accepted (spec §3.5)? THE single home of the
    SUPPORTS_REVEAL check: the button's render condition, the enrolled branch and
    both ephemeral paths all call this. SUBMITTED is checked by quiz_answer's gate."""
    return bool(
        type(question).SUPPORTS_REVEAL
        and question.marking_mode == QuestionElement.MarkingMode.AUTO
        and attempts_made >= 1
        and not locked
    )


def key_view(question, *, mode, locked, fully_correct):
    """The key-copy values, or None (spec §2.2). One decision, made here, passed to
    render() as `key_values`; the template draws the copy + switch iff non-None.
    The AUTO conjunct is load-bearing: N/R questions lock on first submission and
    are never fully correct, so without it they would show the key."""
    if mode not in ("quiz", "results"):
        return None
    if question.marking_mode != QuestionElement.MarkingMode.AUTO:
        return None
    if not locked or fully_correct:
        return None
    return question.key_answer()


BLANK_QUIZ_STATE = {
    "locked": False,
    "selected_ids": frozenset(),
    "submitted_values": None,
    "mark_result": None,
    "verdicts": None,
    "key_values": None,
    "can_reveal": False,
    "reveal_earned": None,
    "revealed": False,
}


def quiz_render_state(question, response, result):
    """Every quiz-mode render key for one answered question (spec §2.4): the fetch
    response, resume, the no-JS re-render and the editor try-it all build the
    element from this, so they cannot drift. `response` is a QuestionResponse or
    the ephemeral stand-in (needs .locked, .attempt_count, .latest_answer,
    .revealed_at). `result` is None for N/R."""
    locked = bool(response.locked)
    selected, submitted = rehydrate(question, response.latest_answer)
    verdicts = None
    if result is not None:
        verdicts = question.part_verdicts(
            result, answer_from_json(question, response.latest_answer)
        )
        if verdicts is not None and result.correct:
            # §2.6 reverse case: a stored fully-correct answer paints all correct
            # even if a later key edit makes the fresh mark disagree.
            verdicts = [None if v is None else True for v in verdicts]
    return {
        "locked": locked,
        "selected_ids": selected,
        "submitted_values": submitted,
        # Key material: only once locked (the withhold window is over).
        "mark_result": result if locked else None,
        "verdicts": verdicts,
        "key_values": key_view(
            question,
            mode="quiz",
            locked=locked,
            fully_correct=bool(result is not None and result.correct),
        ),
        "can_reveal": can_reveal(
            question, attempts_made=response.attempt_count, locked=locked
        ),
        "reveal_earned": (
            earned_marks(to_stored_fraction(result.fraction), question.max_marks)
            if result is not None
            else None
        ),
        "revealed": bool(getattr(response, "revealed_at", None)),
    }
```

`rehydrate` and `answer_from_json` are defined later in the same module; that is fine at call time.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_quiz_reveal_helpers.py tests/test_quiz_lock_rule_parity.py tests/test_ephemeral_quiz_feedback.py tests/test_quiz_finish.py -p no:randomly`
Expected: PASS (the three existing files guard the lock rule, the stand-in and `_results_row`'s outcome refactor).

- [ ] **Step 5: Commit**

```bash
git add courses/scoring.py courses/quiz.py courses/views.py tests/test_quiz_reveal_helpers.py
git commit -m "feat(quiz-reveal): can_reveal, key_view, quiz_render_state, ephemeral reveal, outcome helper"
```

---

### Task 4: The key-copy post-pass (`courses/keycopy.py`)

**Files:**
- Create: `courses/keycopy.py`
- Test: `tests/test_quiz_reveal_keycopy.py` (new)

**Interfaces:**
- Produces: `courses.keycopy.neutralise_key_copy(html: str) -> str`; `courses.keycopy.KEY_SUFFIX = "-key"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_keycopy.py
"""The key copy's one BeautifulSoup pass (spec 2026-09-25 §2.2)."""

from courses.keycopy import neutralise_key_copy


def test_names_stripped_controls_disabled():
    out = neutralise_key_copy(
        '<input type="text" name="blank" value="9">'
        '<select name="slot"><option>a</option></select>'
        '<input type="radio" name="row_5" value="3" checked>'
        '<textarea name="answer"></textarea>'
    )
    assert "name=" not in out
    assert out.count("disabled") == 4
    assert 'data-slot=""' in out  # dnd.js reads the slot select without a name


def test_ids_suffixed_internal_refs_rewritten_external_untouched():
    out = neutralise_key_copy(
        '<label for="b0">x</label><input id="b0" name="blank">'
        '<span aria-describedby="b0 hint-outside"></span>'
    )
    assert 'id="b0-key"' in out
    assert 'for="b0-key"' in out
    assert 'aria-describedby="b0-key hint-outside"' in out


def test_embeds_removed():
    out = neutralise_key_copy('<p>x</p><iframe src="https://g"></iframe><embed><object></object>')
    assert "<iframe" not in out and "<embed" not in out and "<object" not in out
    assert "<p>x</p>" in out


def test_latex_and_entities_round_trip():
    src = '<p>\\(a&lt;b\\) &amp; c</p><input name="blank" value="x">'
    out = neutralise_key_copy(src)
    assert "<p>\\(a&lt;b\\) &amp; c</p>" in out


def test_key_copy_escapes_value():
    out = neutralise_key_copy('<input name="answer" value="a&lt;b">')
    assert 'value="a&lt;b"' in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_keycopy.py -p no:randomly`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.keycopy'`.

- [ ] **Step 3: Implement**

```python
# courses/keycopy.py
"""The correct-answer copy's HTML post-pass (spec 2026-09-25 §2.2).

The answer controls are built in Python with hard-coded names (fillblank
render_inputs -> name="blank", dnd -> name="slot", grids -> name="row_<pk>"), so no
builder changes: this ONE pass neutralises the second render instead. It runs on
the rendered controls include only -- never on the form, buttons or feedback box.

html.parser + decode_contents(): a NavigableString decodes entities and a Tag
re-escapes them, so serialising the soup's CONTENTS round-trips author LaTeX such
as \\(a&lt;b\\) unchanged (the known bs4 trap).
"""

from bs4 import BeautifulSoup

KEY_SUFFIX = "-key"
_REF_ATTRS = ("for", "aria-labelledby", "aria-describedby", "aria-controls")
_EMBEDS = ("iframe", "embed", "object")
_CONTROLS = ("input", "select", "textarea")


def neutralise_key_copy(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_EMBEDS):
        tag.decompose()  # a second GeoGebra applet is heavy and pointless
    ids = set()
    for tag in soup.find_all(id=True):
        ids.add(tag["id"])
        tag["id"] = tag["id"] + KEY_SUFFIX
    for attr in _REF_ATTRS:
        for tag in soup.find_all(attrs={attr: True}):
            # Rewrite a reference only when its target is inside this copy; one
            # pointing outside (e.g. a stem hint) stays as it is.
            tag[attr] = " ".join(
                ref + KEY_SUFFIX if ref in ids else ref
                for ref in str(tag[attr]).split()
            )
    for tag in soup.find_all(_CONTROLS):
        name = tag.attrs.pop("name", None)
        if tag.name == "select" and name == "slot":
            tag["data-slot"] = ""
        tag["disabled"] = ""
    return soup.decode_contents()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_quiz_reveal_keycopy.py -p no:randomly`
Expected: PASS (5 passed). If `test_latex_and_entities_round_trip` fails, do NOT switch parsers — print `out` and compare; the fix is always in how the soup is serialised.

- [ ] **Step 5: Commit**

```bash
git add courses/keycopy.py tests/test_quiz_reveal_keycopy.py
git commit -m "feat(quiz-reveal): key-copy post-pass (names, disabled, ids, embeds)"
```

---

### Task 5: The result line — partly correct, marks, answer shown (every quiz type)

**Files:**
- Modify: `courses/quiz.py` (`quiz_feedback_context`)
- Modify: `templates/courses/elements/_quiz_question_feedback.html`
- Modify: `courses/static/courses/css/courses.css` (partial verdict colour, next to `.question__verdict.is-incorrect` at ~line 302)
- Test: `tests/test_quiz_reveal_result_line.py` (new); existing tests updated per Step 4

**Interfaces:**
- Consumes: `courses.scoring.outcome`, `earned_marks`, `to_stored_fraction`.
- Produces: `quiz_feedback_context` ctx keys `outcome` (`"correct"|"partial"|"incorrect"|None`), `earned` (Decimal|None), `possible` (Decimal), `revealed` (bool). `reveal_template` is None for `SUPPORTS_REVEAL` types too.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_result_line.py
"""Result line (spec 2026-09-25 §1, §2.5): real outcome + marks, every quiz type."""

from decimal import Decimal

import pytest

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _enrolled_quiz(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _fb(unit, accepted, **kw):
    token_stem, _ = parse(" ".join("{{%s}}" % a for a in accepted))
    q = FillBlankQuestionElement.objects.create(stem=token_stem, **kw)
    for i, a in enumerate(accepted):
        Blank.objects.create(question=q, order=i, accepted=a)
    return Element.objects.create(unit=unit, content_object=q)


def _post(client, unit, el, data):
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    return client.post(url, data, HTTP_X_REQUESTED_WITH="fetch").content.decode()


@pytest.mark.django_db
def test_partial_reads_partly_correct_with_marks_and_attempts(client):
    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9", "2", "22"], max_attempts=3)
    body = _post(client, unit, el, {"blank": ["11", "", "", ""]})
    assert "Partly correct" in body
    assert "0.25 / 1" in body
    assert "2 attempts left" in body
    assert "Incorrect" not in body


@pytest.mark.django_db
def test_unlimited_attempts_line_omits_count(client):
    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9"], max_attempts=None)
    body = _post(client, unit, el, {"blank": ["11", "5"]})
    assert "Partly correct" in body
    assert "attempts left" not in body and "attempt left" not in body


@pytest.mark.django_db
def test_rounding_to_full_marks_while_unlocked_reads_partial(client):
    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9"], max_attempts=3, max_marks=Decimal("0.01"))
    body = _post(client, unit, el, {"blank": ["11", "5"]})  # 0.5 * 0.01 -> 0.01
    assert "Partly correct" in body
    assert "is-correct" not in body.split("question__verdict")[1][:40]


@pytest.mark.django_db
def test_resume_survives_auto_answer_switched_to_not_marked(client):
    # An AUTO attempt with attempts left, then the author switches the question to
    # N: resume reaches quiz_feedback_context with result=None and locked=False.
    from django.urls import reverse

    from courses.models import QuestionElement

    unit = _enrolled_quiz(client)
    el = _fb(unit, ["11", "9"], max_attempts=3)
    _post(client, unit, el, {"blank": ["11", "5"]})
    q = el.content_object
    q.marking_mode = QuestionElement.MarkingMode.NOT_MARKED
    q.save()
    page = client.get(reverse("courses:quiz_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk}))
    assert page.status_code == 200


@pytest.mark.django_db
def test_incorrect_unconverted_type_gets_new_line_too(client):
    # Choice stays unconverted through PR 1-2 -- the line is ungated (spec §2.1).
    from courses.models import Choice, ChoiceQuestionElement

    unit = _enrolled_quiz(client)
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    Choice.objects.create(question=q, text="A", is_correct=True)
    wrong = Choice.objects.create(question=q, text="B", is_correct=False)
    el = add_element(unit, q)
    body = _post(client, unit, el, {"choice": [str(wrong.pk)]})
    assert "Incorrect" in body and "0 / 1" in body
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_result_line.py -p no:randomly`
Expected: FAIL — "Partly correct" / "0.25 / 1" not in body.

- [ ] **Step 3: Implement**

In `courses/quiz.py`, add `from courses.scoring import outcome`, then in `quiz_feedback_context`:

1. extend the initial `ctx` dict with:

```python
        "revealed": bool(getattr(response, "revealed_at", None)),
        "outcome": None,
        "earned": None,
        "possible": question.max_marks,
```

2. directly before the `# [A]:` comment's `revealing = …` line, insert:

```python
    # The result line (spec §2.5): classified by EARNED marks via the shared helper.
    # Guarded: an AUTO answer whose question was since switched to N/R reaches here
    # with result=None and an UNLOCKED response (the early return needs locked);
    # today's code survives that, so the new line must too (outcome stays None).
    if result is not None:
        earned = earned_marks(to_stored_fraction(result.fraction), question.max_marks)
        ctx["earned"] = earned
        ctx["outcome"] = outcome(earned, question.max_marks)
        if ctx["outcome"] == "correct" and not result.correct and not response.locked:
            # An unlocked question never reads "Correct" (§1): rounding (e.g. 0.5 of
            # 0.01 marks -> 0.01) can reach full marks while result.correct is False.
            # LOCKED, the same rounding reads "Correct" while the switch still shows
            # (fully_correct follows result.correct): accepted by spec §2.6 ("the line
            # follows the helper, the switch follows the predicate") -- do not "fix".
            ctx["outcome"] = "partial"
```

3. change `if question.INLINE_QUIZ_REVEAL:` (inside `if revealing:`) to `if question.INLINE_QUIZ_REVEAL or question.SUPPORTS_REVEAL:` and extend its comment with: "Converted types (SUPPORTS_REVEAL) show the key as a second copy of their own controls behind the Your/Correct switch (spec §2.2), so the list goes for them too."

Replace the `{% elif mark_result %} … {% endif %}` block of `_quiz_question_feedback.html` (everything after the neutral branch up to the final `{% endif %}`) with:

```django
{% elif outcome %}
  {% if outcome == "correct" %}
    <div class="question__feedback-panel question__feedback-panel--correct">
      <div class="question__verdict is-correct">
        <span class="question__glyph" aria-hidden="true">✓</span>{% trans "Correct" %}
        <span class="question__marks"> · {{ earned|marks }} / {{ possible|marks }}</span>{% if revealed %} · {% trans "answer shown" %}{% endif %}
      </div>
      {% if locked and el.explanation %}<div class="question__explanation">{{ el.explanation|safe }}</div>{% endif %}
    </div>
  {% else %}
    <div class="question__feedback-panel question__feedback-panel--incorrect">
      <div class="question__verdict {% if outcome == 'partial' %}is-partial{% else %}is-incorrect{% endif %}">
        {% if outcome == "partial" %}<span class="question__glyph" aria-hidden="true">◐</span>{% trans "Partly correct" %}{% else %}<span class="question__glyph" aria-hidden="true">✗</span>{% trans "Incorrect" %}{% endif %}
        <span class="question__marks"> · {{ earned|marks }} / {{ possible|marks }}</span>{% if attempts_left %} · {% blocktrans count n=attempts_left %}{{ n }} attempt left{% plural %}{{ n }} attempts left{% endblocktrans %}{% endif %}{% if revealed %} · {% trans "answer shown" %}{% endif %}
      </div>
      {% comment %}The list renders ONLY for unconverted types once locked: reveal_template
      is None while attempts remain, and always None for SUPPORTS_REVEAL / inline types.{% endcomment %}
      {% if reveal_template %}{% include reveal_template %}{% endif %}
      {% if locked and el.explanation %}<div class="question__explanation">{{ el.explanation|safe }}</div>{% endif %}
    </div>
  {% endif %}
{% endif %}
```

Add `courses_extras` to the template's `{% load %}` line (for `|marks`): `{% load i18n courses_extras %}`.

In `courses.css`, after `.question__verdict.is-incorrect { … }`:

```css
/* --warning on the page background is ~3.2:1 -- below AA for text. The words stay
   in the body colour; only the (aria-hidden) glyph carries the warning hue. */
.question__verdict.is-partial { color: var(--text-primary); }
.question__verdict.is-partial .question__glyph { color: var(--warning); }
```

- [ ] **Step 4: Run the new tests, then the quiz suites; update tests that pin the OLD line**

Run: `uv run pytest tests/test_quiz_reveal_result_line.py -p no:randomly` → PASS.

Then run the quiz suites that render this template:
`uv run pytest tests/test_quiz_answer.py tests/test_quiz_noleak.py tests/test_questions_2d_quiz_noleak.py tests/test_quiz_resume.py tests/test_quiz_previewer_answer.py tests/test_quiz_choice_inline_marking.py tests/test_element_try.py tests/test_ux_roster_and_feedback.py tests/test_questions_2b_consumption.py tests/test_questions_consumption.py tests/test_questions_2diii_quiz.py tests/test_choice_inline_feedback.py tests/test_review_wording_pl.py -p no:randomly`

and list any other non-e2e quiz test that pins the old line: `grep -rlE "is-incorrect|attempts? left|Incorrect" tests courses/tests --include=test_*.py | grep -v e2e | xargs grep -l -i quiz` — run the hits too. The e2e side of this change is run in Task 9 Step 5.

Expected failures are ONLY of these two shapes; fix each by rewriting the assertion and adding a one-line comment naming the old assertion it replaces:
- the attempts separator changed from `" — N attempts left"` to `" · N attempts left"`;
- a partly-right answer now reads "Partly correct" (class `is-partial`) instead of "Incorrect" (class `is-incorrect`).

Any other failure is a real regression — stop and investigate. NEVER loosen a no-leak assertion (a check that key text is absent).

- [ ] **Step 5: Commit**

```bash
git add courses/quiz.py templates/courses/elements/_quiz_question_feedback.html courses/static/courses/css/courses.css tests/
git commit -m "feat(quiz-reveal): result line states partial + marks + answer shown"
```

---

### Task 6: Render plumbing + fill in the blanks (quiz + results + lesson)

**Files:**
- Modify: `courses/models.py` (`QuestionElement.render`, new `render_key_copy`; `ChoiceQuestionElement.render` override accepts the new kwargs; `FillBlankQuestionElement` flags)
- Modify: `courses/fillblank.py` (`render_inputs` sr-only verdict text)
- Modify: `courses/templatetags/courses_extras.py` (`render_element`, `render_fill_blanks`)
- Modify: `templates/courses/_quiz_article.html`
- Create: `templates/courses/elements/_answer_switch.html`, `_reveal_button.html`, `_fillblankquestionelement_controls.html`
- Modify: `templates/courses/elements/fillblankquestionelement.html`
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_quiz_reveal_fillblank_render.py` (new)

**Interfaces:**
- Consumes: Task 1 hooks, Task 4 `neutralise_key_copy`.
- Produces: `QuestionElement.render(..., verdicts=None, key_values=None, can_reveal=False, reveal_earned=None, revealed=False)` (plus existing kwargs); `mode` may now be `"results"`; `QuestionElement.render_key_copy(key_values) -> SafeString`; `render_element` tag accepts the same five kwargs; template context keys `verdicts`, `key_copy_html`, `can_reveal`, `reveal_earned`, `revealed`; `render_fill_blanks(el, submitted_values=None, locked=False, verdicts=None, sr_verdict=False)` — its old `mark_result=` parameter is REMOVED (its only caller was the fill-blank question template, rewritten here; fill gates never passed it; lesson verdicts now come from `render()`); `fillblank.render_inputs(..., verdicts=None, *, sr_verdict=False)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_fillblank_render.py
"""Fill in the blanks through the new render path (spec 2026-09-25 §2.2–§2.4, §4)."""

import re

import pytest

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from tests.factories import make_quiz_unit

_INPUT = re.compile(r"<input[^>]*>")


@pytest.fixture
def fb(db):
    unit = make_quiz_unit()
    token_stem, _ = parse("log {{11}} = {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=3)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    return q, Element.objects.create(unit=unit, content_object=q)


def _render(q, el, **kw):
    kw.setdefault("mode", "quiz")
    kw.setdefault("action_url", "/x/")
    return q.render(element=el, feedback_for_pk=el.pk, **kw)


def test_unlocked_paints_and_offers_reveal_no_key(fb):
    q, el = fb
    html = _render(q, el, submitted_values=["11", "5"], verdicts=[True, False],
                   can_reveal=True, reveal_earned="0.50")
    right, wrong = _INPUT.findall(html)[:2]
    assert "is-correct" in right and "is-incorrect" in wrong
    assert 'aria-invalid="true"' in wrong and "aria-invalid" not in right
    # Colour is never the only cue (spec §2.1): each painted blank is followed by
    # its .sr-only verdict.
    assert re.search(r'value="5"[^>]*>\s*<span class="sr-only">incorrect</span>', html)
    assert re.search(r'value="11"[^>]*>\s*<span class="sr-only">correct</span>', html)
    assert "data-reveal-btn" in html and 'name="reveal"' in html
    assert "data-answer-key" not in html and "data-answer-switch" not in html
    assert html.count("data-question-feedback") == 1


def test_check_is_the_first_submit_button(fb):
    q, el = fb
    html = _render(q, el, submitted_values=["11", "5"], can_reveal=True)
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', html)
    assert 'name="reveal"' not in buttons[0] and 'name="reveal"' in buttons[1]


def test_no_reveal_button_when_quiz_submitted(fb):
    q, el = fb
    html = _render(q, el, submitted_values=["11", "5"], can_reveal=True,
                   quiz_submitted=True)
    assert 'name="reveal"' not in html


def test_locked_key_copy_is_nameless_disabled_unique_ids(fb):
    q, el = fb
    html = _render(q, el, submitted_values=["11", "5"], verdicts=[True, False],
                   key_values=["11", "9"], locked=True)
    key = html.split("data-answer-key")[1].split("data-answer-switch")[0]
    assert 'value="9"' in key
    assert "name=" not in key
    assert key.count("disabled") >= 2
    assert "data-answer-switch" in html
    # With the copy drawn: still ONE feedback box, ONE Check, no Show answer (locked).
    assert html.count("data-question-feedback") == 1
    assert len(re.findall(r'<button[^>]*type="submit"(?![^>]*name="reveal")[^>]*>', html)) == 1
    assert 'name="reveal"' not in html
    yours_radio = re.search(r'<input[^>]*value="yours"[^>]*>', html).group(0)
    assert "checked" in yours_radio
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_switch_is_outside_every_fieldset(fb):
    q, el = fb
    html = _render(q, el, submitted_values=["11", "5"], key_values=["11", "9"],
                   locked=True)
    before_switch = html.split("data-answer-switch")[0]
    assert before_switch.count("<fieldset") == before_switch.count("</fieldset>")


def test_results_mode_has_no_form_or_buttons(fb):
    q, el = fb
    html = _render(q, el, mode="results", submitted_values=["11", "5"],
                   verdicts=[True, False], key_values=["11", "9"], locked=True,
                   feedback_html="<p>line</p>")
    assert "<form" not in html and "<button" not in html
    assert "data-answer-scope" in html and "<p>line</p>" in html
    # The results fieldset is `data-answer-yours disabled` (attribute order pinned
    # so this split sees the fieldset's own `disabled`).
    yours = html.split("data-answer-yours")[1].split("data-answer-key")[0]
    assert "disabled" in yours


def test_lesson_mode_paints_with_sr_text(fb):
    q, el = fb
    html = _render(q, el, mode="lesson", action_url=None, submitted_values=["11", "5"],
                   mark_result=q.mark(["11", "5"]))
    assert re.search(r'value="5"[^>]*aria-invalid="true"[^>]*>\s*<span class="sr-only">incorrect</span>', html)
    right = re.search(r'<input[^>]*value="11"[^>]*>', html).group(0)
    assert "aria-invalid" not in right
    assert re.search(r'value="11"[^>]*>\s*<span class="sr-only">correct</span>', html)


def test_fill_gate_render_is_unchanged():
    from courses.fillblank import parse, render_inputs

    token_stem, _ = parse("{{a}}")
    assert "sr-only" not in render_inputs(token_stem, ["a"], locked=True)


@pytest.mark.django_db
def test_quiz_page_with_a_choice_question_still_renders(client):
    # _quiz_article.html forwards the new keys for EVERY question; choice overrides
    # render(), so its signature must accept them (a TypeError here 500s the page).
    from django.urls import reverse

    from courses.models import Choice, ChoiceQuestionElement
    from tests.factories import EnrollmentFactory, add_element, make_login

    user = make_login(client, "stu_ch")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    Choice.objects.create(question=q, text="A", is_correct=True)
    add_element(unit, q)
    resp = client.get(reverse("courses:quiz_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk}))
    assert resp.status_code == 200


def test_lesson_mode_never_draws_key_or_button(fb):
    q, el = fb
    html = _render(q, el, mode="lesson", action_url=None, submitted_values=["11", "5"],
                   key_values=["11", "9"], can_reveal=True, locked=True)
    assert "data-answer-key" not in html and 'name="reveal"' not in html
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_fillblank_render.py -p no:randomly`
Expected: FAIL — `TypeError: render() got an unexpected keyword argument 'verdicts'` — EXCEPT the two regression guards `test_fill_gate_render_is_unchanged` and `test_quiz_page_with_a_choice_question_still_renders`, which pass no new kwarg and are expected to PASS already, and `test_lesson_mode_paints_with_sr_text`, which passes no new kwarg either and fails with an AssertionError (no `.sr-only` span yet).

- [ ] **Step 3: Implement the plumbing**

`QuestionElement.render` — add the kwargs after `feedback_html=""`:

```python
        verdicts=None,
        key_values=None,
        can_reveal=False,
        reveal_earned=None,
        revealed=False,
```

and before `return render_to_string(...)`:

```python
        # An unresolvable template variable (a quiz row with no st.verdicts) arrives
        # as ''. Normalise so templates only ever see None or a real value.
        verdicts = verdicts or None
        if key_values == "":
            key_values = None
        if (
            verdicts is None
            and mode == "lesson"
            and self.INLINE_LESSON_FEEDBACK
            and mark_result is not None
            and element is not None
            and element.pk == feedback_for_pk
        ):
            # Lesson verdicts are computed HERE (spec §5a) so every lesson path --
            # fetch, no-JS, restore, editor try-it, nested in a container -- paints
            # without new plumbing. The feedback_for_pk guard is load-bearing: the
            # no-JS lesson re-render hands ONE page-level mark_result to every
            # question on the unit.
            answer = (
                submitted_values
                if submitted_values is not None
                else set(selected_ids or ())
            )
            verdicts = self.part_verdicts(mark_result, answer)
        key_copy_html = ""
        if key_values is not None and mode in ("quiz", "results"):
            key_copy_html = self.render_key_copy(key_values)
```

and add to the context dict:

```python
                "verdicts": verdicts,
                "key_copy_html": key_copy_html,
                "can_reveal": can_reveal,
                "reveal_earned": reveal_earned,
                "revealed": revealed,
```

Add the method to `QuestionElement` (after `render`):

```python
    def render_key_copy(self, key_values):
        """The correct-answer copy: this type's own controls include rendered from
        key_values, then neutralised (names stripped, disabled, ids suffixed,
        embeds dropped) by the one bs4 pass (spec §2.2)."""
        from courses.keycopy import neutralise_key_copy

        html = render_to_string(
            self.CONTROLS_TEMPLATE,
            {
                "el": self,
                "values": key_values,
                "verdicts": None,
                "copy": "key",
                "locked": True,
            },
        )
        return mark_safe(neutralise_key_copy(html))  # noqa: S308 — escaped by the include
```

(`mark_safe` — add `from django.utils.safestring import mark_safe` to models.py imports if absent.)

**`ChoiceQuestionElement.render` overrides `render()`** (the ONLY question type that does — `awk '/^class .*QuestionElement\)/{c=$2} /    def render\(/ && c != "" {print NR": "c}' courses/models.py` prints exactly one line, `ChoiceQuestionElement(QuestionElement):`). Its keyword-only signature ends at `feedback_html=""`, and from this task on `_quiz_article.html` passes the five new keys for EVERY question, while Task 8 splats `**state` into choice renders (it is `INLINE_QUIZ_REVEAL`). Add the same five kwargs to its signature, after `feedback_html=""`, accepted and unused in PR 1 (choice is unconverted until PR 3):

```python
        verdicts=None,
        key_values=None,
        can_reveal=False,
        reveal_earned=None,
        revealed=False,
```

and extend its signature comment: "`verdicts` / `key_values` / `can_reveal` / `reveal_earned` / `revealed` are accepted for signature uniformity with QuestionElement.render (quiz answer reveal PR 1); choice consumes them in PR 3."

`FillBlankQuestionElement` — add:

```python
    SUPPORTS_REVEAL = True
    CONTROLS_TEMPLATE = "courses/elements/_fillblankquestionelement_controls.html"
```

`courses/fillblank.py` `render_inputs` — in the non-locked branch, after building the input string, append a screen-reader verdict when `verdict is not None`:

```python
                if verdict is not None:
                    out.append(
                        str(
                            format_html(
                                '<span class="sr-only">{}</span>',
                                pgettext("answer part verdict", "correct")
                                if verdict
                                else pgettext("answer part verdict", "incorrect"),
                            )
                        )
                    )
```

(import `from django.utils.translation import pgettext`.) Give `render_inputs` a keyword-only `sr_verdict=False` parameter. When it is True, also append the same `<span class="sr-only">` + `pgettext("answer part verdict", "correct")` after each input in the **locked** branch (the solved / key-copy look), so a locked green blank is not colour-only either. It defaults to False because the locked branch is ALSO reached from `fillgateelement.html` (`{% render_fill_blanks el el.canonical_answers locked=True %}`) — a fill gate is not a question and must not change (Global Constraints). Only the question controls include turns it on (below). The non-locked branch's sr-only span is keyed on `verdict is not None`, which fill gates never pass, so it needs no flag. Extend the docstring: "A painted blank is followed by a `.sr-only` "correct"/"incorrect" — colour is never the only cue (spec 2026-09-25 §2.1)."

`courses_extras.py`:
- `render_fill_blanks` becomes:

```python
@register.simple_tag
def render_fill_blanks(el, submitted_values=None, locked=False, verdicts=None, sr_verdict=False):
    """Render a fill-blank stem: text segments (sanitized HTML) interleaved with
    server-built <input name="blank"> elements (escaped values). `locked=True`
    renders the read-only answered state; `verdicts` (one bool / None per blank,
    from QuestionElement.render) paints each blank in place; `sr_verdict` adds the
    screen-reader "correct" to a LOCKED blank (questions only -- never fill gates).
    See courses.fillblank."""
    from courses import fillblank

    return fillblank.render_inputs(
        el.stem,
        submitted_values,
        locked=locked,
        verdicts=verdicts or None,
        sr_verdict=sr_verdict,
    )
```

- `render_element`: add `verdicts=None, key_values=None, can_reveal=False, reveal_earned=None, revealed=False,` to the signature (after `feedback_html=""`) and pass all five through in the `obj.render(...)` call of the `QuestionElement` branch. They are NOT added to the container `page` dict (quiz questions are never nested; lesson verdicts are computed inside `render`).

`_quiz_article.html` — extend the `{% render_element … %}` call with:
` verdicts=st.verdicts key_values=st.key_values can_reveal=st.can_reveal reveal_earned=st.reveal_earned revealed=st.revealed`

- [ ] **Step 4: Implement the shared partials, the controls include and the template**

`templates/courses/elements/_answer_switch.html`:

```django
{% load i18n %}
{% comment %}The Your / Correct answer switch (spec 2026-09-25 §2.3). A direct child of
the answer scope, OUTSIDE every fieldset (a disabled fieldset would kill it) and
skipped by both freeze scripts. autocomplete="off": reload must never reopen on
"Correct answer" (D3). No JS: the CSS :has() rule in courses.css does the showing.{% endcomment %}
<div class="answer-switch" data-answer-switch role="radiogroup" aria-label="{% trans 'Answer view' %}">
  <label class="answer-switch__opt"><input type="radio" name="answer_view_{{ element.pk }}" value="yours" data-answer-view="yours" autocomplete="off" checked> {% trans "Your answer" %}</label>
  <label class="answer-switch__opt"><input type="radio" name="answer_view_{{ element.pk }}" value="key" data-answer-view="key" autocomplete="off"> {% trans "Correct answer" %}</label>
</div>
```

`templates/courses/elements/_reveal_button.html`:

```django
{% load i18n courses_extras %}
{% comment %}Show answer (spec §1.3, §3). Always AFTER Check in tree order: implicit
submission (Enter) uses the first submit button. can_reveal already includes the
SUPPORTS_REVEAL / AUTO / attempt / lock rules; quiz_submitted is defence in depth.{% endcomment %}
{% if mode == "quiz" and can_reveal and not quiz_submitted %}
<button type="submit" name="reveal" value="1" class="btn btn--small btn--ghost" data-reveal-btn
        data-confirm="{% blocktrans with earned=reveal_earned|marks max=el.max_marks|marks %}Show the answer? This ends the question: you won't be able to try again, and you keep the marks you have now ({{ earned }} of {{ max }}).{% endblocktrans %}">{% trans "Show answer" %}</button>
{% endif %}
```

`templates/courses/elements/_fillblankquestionelement_controls.html`:

```django
{% load courses_extras %}{% render_fill_blanks el values locked=locked verdicts=verdicts sr_verdict=True %}
```

Rewrite `fillblankquestionelement.html`, keeping its existing `{% comment %}` header but REWRITING the three sentences this change makes false — "mark_result is None in quiz mode (_quiz_article.html passes feedback_html instead)" (a LOCKED quiz question now gets mark_result, and every quiz question gets `verdicts`), "mark_result=... paints it green/red" (the paint now comes from `verdicts`), and "Lesson only: a quiz answer is still the bare feedback fragment" (`data-question-inline` is unconditional; quiz Checks return the whole element from Task 8) — and adding one paragraph ("PR 1 of the quiz answer reveal: `data-answer-scope` on the form (quiz/lesson) or the results `<div>`; the student's controls sit in `[data-answer-yours]`, the key copy in `[data-answer-key]`, the switch outside the fieldset."):

```django
<div class="el el--question el--fillblank" data-question>
  {% if mode == "results" %}
  <div class="question__form" data-answer-scope>
    <fieldset class="question__stem" data-answer-yours disabled style="border:0;padding:0;margin:0 0 var(--space-3);">
      {% include "courses/elements/_fillblankquestionelement_controls.html" with values=submitted_values locked=False %}
    </fieldset>
    {% if key_copy_html %}<div class="question__stem answer-key" data-answer-key>{{ key_copy_html }}</div>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <div class="question__feedback" data-question-feedback>{{ feedback_html|safe }}</div>
  </div>
  {% elif element %}
  <form class="question__form" method="post" action="{{ action_url }}" data-lock-on-correct data-question-inline data-answer-scope>
    {% csrf_token %}
    <fieldset class="question__stem" {% if quiz_submitted or locked %}disabled{% endif %} data-answer-yours
              style="border:0;padding:0;margin:0 0 var(--space-3);">
      {% if element.pk == feedback_for_pk %}
        {% include "courses/elements/_fillblankquestionelement_controls.html" with values=submitted_values locked=mark_result.correct %}
      {% else %}
        {% include "courses/elements/_fillblankquestionelement_controls.html" with values=None locked=False verdicts=None %}
      {% endif %}
    </fieldset>
    {% if key_copy_html %}<div class="question__stem answer-key" data-answer-key>{{ key_copy_html }}</div>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% elif element.pk == feedback_for_pk and mark_result.correct %}disabled{% endif %}>{% trans "Check" %}</button>
    {% include "courses/elements/_reveal_button.html" %}
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% else %}
    <div class="question__stem">{% render_fill_blanks el %}</div>
  {% endif %}
</div>
```

**Expected interim state (do not "fix" it here):** from this commit until Task 8, a LOCKED-WRONG fill-blank quiz question shows neither the old list (Task 5 drops `reveal_template` for `SUPPORTS_REVEAL` types) nor the key copy (views pass `key_values` only from Task 8). Quiz tests asserting a fill-blank quiz reveal are expected RED until Task 8 and are rewritten there.

`data-question-inline` is now unconditional on the form: lesson mode needed it since #346, and quiz mode needs it because `SUPPORTS_REVEAL` is set. Until Task 8 lands, a quiz Check still returns the bare fragment; quiz.js already falls through to the feedback-box swap when the response has no `<form>`.

CSS — append to `courses.css` next to the fill-blank verdict rules:

```css
/* Quiz answer reveal (spec 2026-09-25 §2.3): the key copy is hidden by default and
   shown only by :has(), so a browser without :has() degrades to "Your answer" (D3). */
[data-answer-key] { display: none; }
[data-answer-scope]:has([data-answer-view="key"]:checked) [data-answer-key] { display: block; }
[data-answer-scope]:has([data-answer-view="key"]:checked) [data-answer-yours] { display: none; }
.answer-switch {
  display: inline-flex;
  margin: 0 0 var(--space-2);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  overflow: hidden;
  font-size: .9rem;
}
.answer-switch__opt { position: relative; padding: var(--space-1) var(--space-3); cursor: pointer; }
.answer-switch__opt input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
.answer-switch__opt:has(input:checked) { background: var(--accent); color: var(--text-inverse); }
.answer-switch__opt:has(input:focus-visible) { outline: 2px solid var(--primary); outline-offset: 2px; }
```

Every token above is defined in `core/static/core/css/tokens.css` (`--accent`, `--text-inverse`, `--primary`, `--border-strong`, `--radius-sm`, `--space-1..3`, `--success(-subtle)`, `--danger(-subtle)`, `--warning`); there is no font-size token, so `.9rem` follows courses.css's own convention, and the focus ring copies app.css's `outline: 2px solid var(--primary); outline-offset: 2px`. Verify with `grep -n -- "--accent:\|--text-inverse\|--primary:\|--border-strong\|--radius-sm" core/static/core/css/tokens.css` — do not invent tokens. Judge the switch's contrast in the Task 12 screenshots (light AND dark).

- [ ] **Step 5: Run to verify the new tests pass and nothing regressed**

Run: `uv run pytest tests/test_quiz_reveal_fillblank_render.py courses/tests/test_fillblank_inline_verdicts.py courses/tests/test_fillblank_lock_on_correct.py tests/test_questions_2b_fillblank_parse.py tests/test_quiz_render.py courses/tests/test_fillblank_locked.py courses/tests/test_fillgate_template.py courses/tests/test_question_restore.py -p no:randomly` and `uv run pytest tests/test_e2e_fillgate.py -m e2e -p no:randomly` (fill gates must be byte-for-byte unchanged: no `sr-only` in any fill-gate render).
Expected: PASS, EXCEPT `courses/tests/test_fillblank_inline_verdicts.py::test_quiz_fillblank_still_lists_the_correct_answers`, an expected interim RED (setting `SUPPORTS_REVEAL` drops the quiz list via Task 5; the key copy arrives in Task 8, which rewrites it). `test_questions_2b_fillblank_parse.py` and `courses/tests/test_fillblank_inline_verdicts.py` pin `render_inputs` / the painted blanks; if one fails only because a painted input is now followed by a `.sr-only` span (e.g. a regex that assumed the input tag ends the match, or a count of `<span`), update that assertion and say so in a comment.

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/fillblank.py courses/templatetags/courses_extras.py templates/courses courses/static/courses/css/courses.css tests/test_quiz_reveal_fillblank_render.py
git commit -m "feat(quiz-reveal): render plumbing, key copy, switch, Show answer button; fill in the blanks converted"
```

---

### Task 7: Short text and number — quiz render + lessons (D13)

**Files:**
- Create: `templates/courses/elements/_shorttextquestionelement_controls.html`, `_shortnumericquestionelement_controls.html`
- Modify: `templates/courses/elements/shorttextquestionelement.html`, `shortnumericquestionelement.html`
- Modify: `courses/models.py` (flags on both types)
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_quiz_reveal_single_part.py` (new)

**Interfaces:**
- Consumes: Task 6 plumbing.
- Produces: `ShortTextQuestionElement` / `ShortNumericQuestionElement` with `SUPPORTS_REVEAL = True`, `INLINE_LESSON_FEEDBACK = True`, `CONTROLS_TEMPLATE` set.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_single_part.py
"""Short text + number: quiz reveal and lesson in-place feedback (spec §2.2, §5a)."""

import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_quiz_unit
from tests.factories import make_student

_INPUT = re.compile(r'<input[^>]*name="answer"[^>]*>')


@pytest.fixture
def st_quiz(db):
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris", max_attempts=3)
    return q, Element.objects.create(unit=unit, content_object=q)


def test_quiz_locked_wrong_shows_key_copy(st_quiz):
    q, el = st_quiz
    html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                    submitted_values="Rome", verdicts=[False], key_values="Paris",
                    locked=True)
    key = html.split("data-answer-key")[1]
    assert 'value="Paris"' in key and "name=" not in key.split("data-answer-switch")[0]
    assert 'aria-label="Correct answer"' in key
    (yours,) = _INPUT.findall(html)
    assert "is-incorrect" in yours and 'aria-invalid="true"' in yours


@pytest.mark.parametrize("model", [ShortTextQuestionElement, ShortNumericQuestionElement])
def test_check_is_the_first_submit_button_single_part(db, model):
    unit = make_quiz_unit()
    q = model.objects.create(stem="?", **({"accepted": "a"} if model is ShortTextQuestionElement else {"value": "1"}))
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                    submitted_values="x", can_reveal=True)
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', html)
    assert 'name="reveal"' not in buttons[0] and 'name="reveal"' in buttons[1]


@pytest.mark.parametrize("model", [ShortTextQuestionElement, ShortNumericQuestionElement])
@pytest.mark.parametrize("verdict", [True, False])
def test_quiz_part_cues_per_single_part_type(db, model, verdict):
    unit = make_quiz_unit()
    q = model.objects.create(stem="?", **({"accepted": "a"} if model is ShortTextQuestionElement else {"value": "1"}))
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                    submitted_values="x", verdicts=[verdict])
    (inp,) = _INPUT.findall(html)
    if verdict:
        assert "is-correct" in inp and "aria-invalid" not in inp
        assert '<span class="sr-only">correct</span>' in html
        assert '<span class="sr-only">incorrect</span>' not in html
    else:
        assert "is-incorrect" in inp and 'aria-invalid="true"' in inp
        assert '<span class="sr-only">incorrect</span>' in html


def test_numeric_key_copy_prints_tolerance_unfiltered(db):
    unit = make_quiz_unit()
    q = ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14", tolerance="0.01")
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                    submitted_values="4", key_values="3.14", locked=True)
    key = html.split("data-answer-key")[1]
    assert 'value="3.14"' in key and "± 0.01" in key


def _lesson(client, q):
    student = make_student(client, "st_lesson")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    el = Element.objects.create(unit=unit, content_object=q)
    url = reverse("courses:check_answer",
                  kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk})
    return student, unit, el, url


def _make(kind):
    if kind == "text":
        return ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris"), "Rome", "Paris"
    return ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14"), "9", "3.14"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["text", "number"])
def test_lesson_check_paints_input_no_list(client, kind):
    q, wrong, key = _make(kind)
    _s, _u, _el, url = _lesson(client, q)
    body = client.post(url, {"answer": wrong}, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "data-question-inline" in body
    (inp,) = _INPUT.findall(body)
    assert "is-incorrect" in inp and 'aria-invalid="true"' in inp
    assert "Correct answer:" not in body and "Expected:" not in body and key not in body
    assert "data-answer-key" not in body and 'name="reveal"' not in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["text", "number"])
def test_lesson_nojs_restore_and_try_paint_both_types(client, kind):
    from tests.factories import ContentNodeFactory, CourseFactory, make_pa

    q, wrong, _key = _make(kind)
    student, unit, el, url = _lesson(client, q)
    def _no_list(html):
        assert "question__reveal" not in html
        assert "Correct answer:" not in html and "Expected:" not in html

    body = client.post(url, {"answer": wrong}).content.decode()  # no-JS
    assert "is-incorrect" in _INPUT.findall(body)[0]
    _no_list(body)
    page = client.get(reverse("courses:lesson_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk}))
    assert "is-incorrect" in _INPUT.findall(page.content.decode())[0]  # restore
    _no_list(page.content.decode())
    pa = make_pa(client, f"pa_{kind}")
    course = CourseFactory(owner=pa)
    lu = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    q2, wrong2, _k = _make(kind)
    el2 = Element.objects.create(unit=lu, content_object=q2)
    try_url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el2.pk})
    tbody = client.post(try_url, {"answer": wrong2}, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "is-incorrect" in _INPUT.findall(tbody)[0]
    _no_list(tbody)


@pytest.mark.django_db
def test_lesson_nojs_and_restore_paint(client):
    q = ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14")
    student, unit, el, url = _lesson(client, q)
    body = client.post(url, {"answer": "3.14"}).content.decode()
    assert "is-correct" in _INPUT.findall(body)[0]
    UnitProgress.objects.filter(student=student, unit=unit).update(
        element_state={str(el.pk): {"answer": "9"}}
    )
    page = client.get(reverse("courses:lesson_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk}))
    assert "is-incorrect" in _INPUT.findall(page.content.decode())[0]


@pytest.mark.django_db
@pytest.mark.parametrize("model,right_answer,wrong_answer", [
    (ShortTextQuestionElement, "Paris", "Rome"),
    (ShortNumericQuestionElement, "3.14", "9"),
])
def test_lesson_sr_text_on_both_aria_invalid_only_on_wrong(client, model, right_answer, wrong_answer):
    kw = {"accepted": "Paris"} if model is ShortTextQuestionElement else {"value": "3.14"}
    q = model.objects.create(stem="?", **kw)
    _s, _u, _el, url = _lesson(client, q)
    wrong = client.post(url, {"answer": wrong_answer}).content.decode()
    assert re.search(r'aria-invalid="true"[^>]*>\s*<span class="sr-only">incorrect</span>', wrong)
    right = client.post(url, {"answer": right_answer}).content.decode()
    assert '<span class="sr-only">correct</span>' in right
    assert "aria-invalid" not in _INPUT.findall(right)[0]


@pytest.mark.django_db
def test_lesson_nested_in_callout_paints_on_nojs_and_restore(client):
    from courses.models import CalloutElement
    from tests.factories import add_element

    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    student = make_student(client, "st_nested")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    callout_row = add_element(unit, CalloutElement.objects.create(kind="example"))
    nested = Element.objects.create(unit=unit, content_object=q, parent=callout_row,
                                    tab_id=CalloutElement.SLOT_ID)
    url = reverse("courses:check_answer",
                  kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": nested.pk})
    body = client.post(url, {"answer": "Rome"}).content.decode()  # no-JS
    assert "is-incorrect" in _INPUT.findall(body)[0]
    page = client.get(reverse("courses:lesson_unit",
                              kwargs={"slug": course.slug, "node_pk": unit.pk})).content.decode()
    assert "is-incorrect" in _INPUT.findall(page)[0]  # restore


@pytest.mark.django_db
def test_nojs_lesson_check_leaves_sibling_unpainted(client):
    from courses.fillblank import parse
    from courses.models import Blank, FillBlankQuestionElement

    token_stem, _ = parse("{{11}}")
    fbq = FillBlankQuestionElement.objects.create(stem=token_stem)
    Blank.objects.create(question=fbq, order=0, accepted="11")
    student, unit, fb_el, url = _lesson(client, fbq)
    st = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    Element.objects.create(unit=unit, content_object=st)
    body = client.post(url, {"blank": ["5"]})  # no-JS re-render of the whole unit
    assert body.status_code == 200
    (sibling,) = _INPUT.findall(body.content.decode())
    assert "is-correct" not in sibling and "is-incorrect" not in sibling


@pytest.mark.django_db
def test_nojs_short_text_check_beside_fillblank_sibling_is_safe(client):
    # The feedback_for_pk guard's real job: without it a fill-blank sibling would run
    # part_verdicts on a SHORT-TEXT result, whose reveal is a string -> item["correct"]
    # on characters -> 500.
    from courses.fillblank import parse
    from courses.models import Blank, FillBlankQuestionElement

    st = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    _s, unit, _el, url = _lesson(client, st)
    token_stem, _ = parse("{{11}}")
    fbq = FillBlankQuestionElement.objects.create(stem=token_stem)
    Blank.objects.create(question=fbq, order=0, accepted="11")
    Element.objects.create(unit=unit, content_object=fbq)
    resp = client.post(url, {"answer": "Rome"})  # no-JS: whole unit re-rendered
    assert resp.status_code == 200
    blank = re.search(r'<input[^>]*name="blank"[^>]*>', resp.content.decode()).group(0)
    assert "is-correct" not in blank and "is-incorrect" not in blank


@pytest.mark.django_db
def test_editor_try_lesson_paints_single_part(client):
    from tests.factories import ContentNodeFactory, CourseFactory, make_pa

    pa = make_pa(client, "pa_try")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    q = ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14")
    el = Element.objects.create(unit=unit, content_object=q)
    url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk})
    body = client.post(url, {"answer": "4"}, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "is-incorrect" in _INPUT.findall(body)[0]
    assert "Expected:" not in body


def test_key_copy_escapes_a_raw_key(st_quiz):
    q, el = st_quiz
    q.accepted = "a<b"
    html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                    submitted_values="x", key_values="a<b", locked=True)
    key = html.split("data-answer-key")[1].split("data-answer-switch")[0]
    assert 'value="a&lt;b"' in key and "<b" not in key.replace("&lt;b", "")


@pytest.mark.django_db
def test_fillblank_key_copy_keeps_latex_backslashes(db):
    from courses.fillblank import parse
    from courses.models import Blank, FillBlankQuestionElement

    unit = make_quiz_unit()
    q = FillBlankQuestionElement.objects.create(stem=parse("{{x}}")[0])
    Blank.objects.create(question=q, order=0, accepted="\\(x\\)")
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                    submitted_values=["y"], key_values=["\\(x\\)"], locked=True)
    assert 'value="\\(x\\)"' in html.split("data-answer-key")[1]


@pytest.mark.django_db
def test_numeric_key_copy_tolerance_matches_old_reveal_in_pl(db):
    from django.template.loader import render_to_string
    from django.utils import translation

    from courses.marking import MarkResult

    unit = make_quiz_unit()
    q = ShortNumericQuestionElement.objects.create(stem="x?", value="3.5", tolerance="0.25")
    el = Element.objects.create(unit=unit, content_object=q)
    with translation.override("pl"):
        html = q.render(element=el, mode="quiz", action_url="/x/", feedback_for_pk=el.pk,
                        submitted_values="4", key_values="3.5", locked=True)
        old = render_to_string("courses/elements/_reveal_shortnumeric.html", {
            "mark_result": MarkResult(correct=False, fraction=0.0,
                                      reveal={"value": "3.5", "tolerance": "0.25"})})
    key = html.split("data-answer-key")[1].split("data-answer-switch")[0]
    assert 'value="3.5"' in key
    # Same tolerance text in both renders (no localisation drift, e.g. 0,25).
    old_tol = re.search(r"± (\S+?)\s*</p>", old).group(1)
    new_tol = re.search(r"± (\S+?)(\s|<|$)", key).group(1)
    assert old_tol == new_tol == "0.25"


@pytest.mark.django_db
def test_lesson_correct_keeps_input_editable(client):
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    _s, _u, _el, url = _lesson(client, q)
    body = client.post(url, {"answer": "Paris"}).content.decode()
    (inp,) = _INPUT.findall(body)
    assert "is-correct" in inp and "disabled" not in inp and "readonly" not in inp
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_single_part.py -p no:randomly`
Expected: FAIL — no `data-answer-key`, lesson body still contains "Correct answer:". Expected to PASS already (regression guards): `test_nojs_short_text_check_beside_fillblank_sibling_is_safe` (falsified by Task 12's `feedback_for_pk` mutant — a 500) and `test_nojs_lesson_check_leaves_sibling_unpainted` (defence in depth: two layers guard it — the `render()` guard and the short-text `{% else %}` include's `verdicts=None` — so only Task 12's COMBINED mutant, removing both, falsifies it).

- [ ] **Step 3: Implement**

Flags, on BOTH `ShortTextQuestionElement` and `ShortNumericQuestionElement`:

```python
    SUPPORTS_REVEAL = True
    # Lesson (spec §5a, D13): the box turns green/red in place; the list is gone.
    INLINE_LESSON_FEEDBACK = True
    CONTROLS_TEMPLATE = "courses/elements/_shorttextquestionelement_controls.html"
```
(number: `_shortnumericquestionelement_controls.html`.)

`_shorttextquestionelement_controls.html`:

```django
{% load i18n %}<input type="text" name="answer" class="question__text-input{% if copy == 'key' or verdicts.0 is True %} is-correct{% elif verdicts.0 is False %} is-incorrect{% endif %}" autocomplete="off" value="{% if copy == 'key' or element.pk == feedback_for_pk %}{{ values|default_if_none:'' }}{% endif %}"{% if copy != 'key' and quiz_submitted or copy != 'key' and locked %} disabled{% endif %}{% if verdicts.0 is False %} aria-invalid="true"{% endif %}{% if copy == 'key' %} aria-label="{% trans 'Correct answer' %}"{% endif %}>{% if verdicts.0 is True %}<span class="sr-only">{% trans "correct" context "answer part verdict" %}</span>{% elif verdicts.0 is False %}<span class="sr-only">{% trans "incorrect" context "answer part verdict" %}</span>{% endif %}
```

`_shortnumericquestionelement_controls.html` — identical, with `inputmode="text"` added to the input, and after the sr-only span:

```django
{% if copy == 'key' and el.tolerance %} ± {{ el.tolerance }}{% endif %}
```

(Unfiltered, exactly as `_reveal_shortnumeric.html` prints the tolerance.)

`shorttextquestionelement.html` (and the number template — identical but for the include path and `el--shortnumeric`):

```django
{% load i18n %}
<div class="el el--question el--shorttext" data-question>
  {% if el.stem %}<div class="question__stem">{{ el.stem|safe }}</div>{% endif %}
  {% if mode == "results" %}
  <div class="question__form" data-answer-scope>
    <span data-answer-yours>{% include "courses/elements/_shorttextquestionelement_controls.html" with values=submitted_values copy="yours" %}</span>
    {% if key_copy_html %}<span class="answer-key" data-answer-key>{{ key_copy_html }}</span>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <div class="question__feedback" data-question-feedback>{{ feedback_html|safe }}</div>
  </div>
  {% elif element %}
  <form class="question__form" method="post" action="{{ action_url }}" data-question-inline data-answer-scope>
    {% csrf_token %}
    <span data-answer-yours>{% if element.pk == feedback_for_pk %}{% include "courses/elements/_shorttextquestionelement_controls.html" with values=submitted_values copy="yours" %}{% else %}{% include "courses/elements/_shorttextquestionelement_controls.html" with values=None verdicts=None copy="yours" %}{% endif %}</span>
    {% if key_copy_html %}<span class="answer-key" data-answer-key>{{ key_copy_html }}</span>{% include "courses/elements/_answer_switch.html" %}{% endif %}
    <button type="submit" class="btn btn--small"
            {% if quiz_submitted or locked %}disabled{% endif %}>{% trans "Check" %}</button>
    {% include "courses/elements/_reveal_button.html" %}
    <div class="question__feedback" data-question-feedback>
      {% if mode == "quiz" %}{{ feedback_html|safe }}{% elif element.pk == feedback_for_pk %}{% include feedback_partial %}{% endif %}
    </div>
  </form>
  {% endif %}
</div>
```

The results render passes `locked=True` (Task 10), which the include turns into `disabled` on the student input — the same mechanism the quiz uses (spec §4).

**Expected interim state (do not "fix" it here):** until Task 8, a locked-wrong short-text / number QUIZ question shows neither the old list nor the key copy; quiz tests asserting that reveal (e.g. `tests/test_ux_roster_and_feedback.py::test_incorrect_feedback_keeps_reveal_in_a_panel`) are expected RED until Task 8 and are rewritten there.

CSS, next to the fill-blank verdict rules (specificity (0,3,0) beats app.css's `input[type=text]` (0,1,1)):

```css
.el--question .question__text-input.is-correct { border-color: var(--success); background: var(--success-subtle); }
.el--question .question__text-input.is-incorrect { border-color: var(--danger); background: var(--danger-subtle); }
[data-answer-scope]:has([data-answer-view="key"]:checked) span[data-answer-key] { display: inline; }
```

- [ ] **Step 4: Run to verify they pass, plus the suites that pin the old lesson list**

Run: `uv run pytest tests/test_quiz_reveal_single_part.py tests/test_questions_2b_consumption.py tests/test_questions_consumption.py tests/test_element_try.py tests/test_i18n_questions_2b.py courses/tests/test_nested_question_nojs_feedback.py courses/tests/test_question_restore.py -p no:randomly` (the nested suite's docstrings rely on short text / number sharing a "byte-identical wrapper `<div class="el el--question" data-question>`" — the wrapper now carries `el--shorttext` / `el--shortnumeric`; update that comment, and any assertion that depended on it, to the new classes)
Expected: new tests PASS. Allowed rewrites, each with a comment naming the replaced assertion: (a) a short-text / number LESSON Check or lesson editor try-it now answers with the whole element (`<form`, `data-question-inline`), not the `_question_feedback.html` fragment; (b) existing lesson tests that assert "Correct answer:" / "Expected:" — or count `question__reveal-text` (e.g. `tests/test_questions_2b_consumption.py::test_post_submit_reveals_only_answered_across_types`, whose substance is "only the answered question is marked, and the OTHER question's key never appears": rewrite to "exactly one `name="answer"` input carries `is-incorrect`, and `secret` is absent") — for a WRONG short-text / number LESSON Check are now wrong by design (D13): rewrite each to assert the painted input (`is-incorrect`, `aria-invalid`) and add a comment `# D13 (spec 2026-09-25 §5a): replaces the old "Correct answer:" lesson list assertion`. Quiz-side assertions of "Correct answer:" for these types change in Task 8, not here.

- [ ] **Step 5: Commit**

```bash
git add courses/models.py templates/courses/elements courses/static/courses/css/courses.css tests/
git commit -m "feat(quiz-reveal): short text + number converted; lesson in-place feedback (D13)"
```

---

### Task 8: Views — whole-element responses, resume, no-JS, Show answer (enrolled, previewer, editor)

**Files:**
- Modify: `courses/views.py` (`build_quiz_context`, `_quiz_render_feedback`, `quiz_answer`, new `_quiz_reveal_refused`)
- Modify: `courses/views_manage.py` (`element_try` quiz branch)
- Modify: `tests/test_quiz_lock_rule_parity.py` (reveal parity)
- Test: `tests/test_quiz_reveal_flow.py` (new)

**Interfaces:**
- Consumes: `quiz_render_state`, `BLANK_QUIZ_STATE`, `can_reveal`, `ephemeral_quiz_feedback(reveal=)`, `_stored_result`.
- Produces: fetch Check / Show answer for converted types (and choice) → whole element; `quiz_answer` accepts `reveal=1`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_flow.py
"""Show answer + whole-element quiz responses end to end (spec 2026-09-25 §2.4, §3)."""

import re

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Attempt
from courses.models import Blank
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

_BLANK = re.compile(r'<input[^>]*name="blank"[^>]*>')


def _quiz(client, enrolled=True):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    if enrolled:
        EnrollmentFactory(student=user, course=unit.course)
    return user, unit


def _fb(unit, accepted=("11", "9"), **kw):
    kw.setdefault("max_attempts", 3)
    token_stem, _ = parse(" ".join("{{%s}}" % a for a in accepted))
    q = FillBlankQuestionElement.objects.create(stem=token_stem, **kw)
    for i, a in enumerate(accepted):
        Blank.objects.create(question=q, order=i, accepted=a)
    return Element.objects.create(unit=unit, content_object=q)


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _fetch(client, unit, el, data):
    return client.post(_url(unit, el), data, HTTP_X_REQUESTED_WITH="fetch")


@pytest.mark.django_db
def test_check_returns_whole_element_painted_no_key(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    body = _fetch(client, unit, el, {"blank": ["11", "5"]}).content.decode()
    assert "data-question-inline" in body and "<form" in body
    right, wrong = _BLANK.findall(body)
    assert "is-correct" in right and "is-incorrect" in wrong
    assert "data-answer-key" not in body
    assert 'value="9"' not in body  # the key never leaves before the lock
    assert 'name="reveal"' in body


@pytest.mark.django_db
def test_reveal_locks_at_current_marks_without_an_attempt(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    body = _fetch(client, unit, el, {"blank": ["", ""], "reveal": "1"}).content.decode()
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.revealed_at is not None
    assert r.attempt_count == 1 and Attempt.objects.filter(response=r).count() == 1
    assert "answer shown" in body and "Partly correct" in body
    assert "Answer recorded" not in body
    assert "data-answer-key" in body and 'value="9"' in body
    right, wrong = _BLANK.findall(body)[:2]  # stored answer, not the emptied form
    assert 'value="11"' in right and "is-correct" in right


@pytest.mark.django_db
def test_second_reveal_is_refused(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    _fetch(client, unit, el, {"reveal": "1"})
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 409
    assert QuestionResponse.objects.get(element=el).attempt_count == 1


@pytest.mark.django_db
def test_reveal_before_any_attempt_is_refused(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 409
    resp = client.post(_url(unit, el), {"reveal": "1"})
    assert resp.status_code == 302
    assert resp.url == reverse("courses:quiz_unit",
                               kwargs={"slug": unit.course.slug, "node_pk": unit.pk})


@pytest.mark.django_db
def test_reveal_refused_for_not_marked_and_unconverted(client):
    _u, unit = _quiz(client)
    nm = _fb(unit, marking_mode=QuestionElement.MarkingMode.NOT_MARKED)
    _fetch(client, unit, nm, {"blank": ["1", "2"]})  # locks on first submit
    assert _fetch(client, unit, nm, {"reveal": "1"}).status_code == 409
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    ch = add_element(unit, q)
    QuestionResponse.objects.create(
        submission=QuestionResponse.objects.get(element=nm).submission,
        element=ch, attempt_count=1, latest_answer=[],
    )
    assert _fetch(client, unit, ch, {"reveal": "1"}).status_code == 409


@pytest.mark.django_db
def test_exhausted_but_unlocked_can_still_reveal(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=3)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    _fetch(client, unit, el, {"blank": ["11", "6"]})
    q = el.content_object
    q.max_attempts = 1  # author lowered the limit below the student's count
    q.save()
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 200
    assert QuestionResponse.objects.get(element=el).locked


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
def test_locked_wrong_has_key_copy_and_no_old_list(client, kind):
    # Spec §2.1: a converted type's locked question shows the key copy and NEVER the
    # old _reveal_* list beside it -- in the fetch response and on resume.
    from courses.models import ShortNumericQuestionElement

    _u, unit = _quiz(client)
    if kind == "fillblank":
        el, data = _fb(unit, max_attempts=1), {"blank": ["11", "5"]}
    elif kind == "text":
        el = add_element(unit, ShortTextQuestionElement.objects.create(
            stem="?", accepted="Paris", max_attempts=1))
        data = {"answer": "Rome"}
    else:
        el = add_element(unit, ShortNumericQuestionElement.objects.create(
            stem="?", value="3.14", tolerance="0.01", max_attempts=1))
        data = {"answer": "9"}
    body = _fetch(client, unit, el, data).content.decode()
    page = client.get(reverse("courses:quiz_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk})).content.decode()
    for html in (body, page):
        assert "data-answer-key" in html
        assert "question__reveal" not in html
        assert "Correct answer:" not in html and "Expected:" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_never_show_the_key(client, kind, mode):
    # Spec §2.2: N/R lock on first submission, are never "fully correct", and have a
    # non-None key_answer() -- only key_view's AUTO conjunct keeps the key hidden.
    from courses.models import ShortNumericQuestionElement

    _u, unit = _quiz(client)
    if kind == "fillblank":
        el, data = _fb(unit, marking_mode=mode), {"blank": ["11", "5"]}
    elif kind == "text":
        el = add_element(unit, ShortTextQuestionElement.objects.create(
            stem="?", accepted="Paris", marking_mode=mode))
        data = {"answer": "Rome"}
    else:
        el = add_element(unit, ShortNumericQuestionElement.objects.create(
            stem="?", value="3.14", marking_mode=mode))
        data = {"answer": "9"}
    body = _fetch(client, unit, el, data).content.decode()
    page = client.get(reverse("courses:quiz_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk})).content.decode()
    for html in (body, page):
        assert "data-answer-key" not in html and "data-answer-switch" not in html


@pytest.mark.django_db
def test_nojs_enrolled_validation_keeps_prior_answer_painted(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    client.post(_url(unit, el), {"blank": ["11", "5"]})
    page = client.post(_url(unit, el), {"blank": ["", ""]}).content.decode()
    assert "is-validation" in page
    right, wrong = _BLANK.findall(page)[:2]
    assert 'value="11"' in right and "is-correct" in right
    assert 'value="5"' in wrong and "is-incorrect" in wrong
    assert "data-answer-key" not in page


@pytest.mark.django_db
def test_unlimited_attempts_partial_offers_reveal(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=None)
    body = _fetch(client, unit, el, {"blank": ["11", "5"]}).content.decode()
    assert 'name="reveal"' in body and "attempts left" not in body


@pytest.mark.django_db
def test_single_attempt_wrong_locks_with_key_no_button(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=1)
    body = _fetch(client, unit, el, {"blank": ["11", "5"]}).content.decode()
    assert "data-answer-key" in body and "data-answer-switch" in body
    assert 'name="reveal"' not in body


@pytest.mark.django_db
def test_validation_stays_a_fragment_for_converted_and_choice(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    body = _fetch(client, unit, el, {"blank": ["", ""]}).content.decode()
    assert "<form" not in body and "is-validation" in body
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    ch = add_element(unit, q)
    body = _fetch(client, unit, ch, {}).content.decode()
    assert "<form" not in body and "is-validation" in body


@pytest.mark.django_db
def test_resume_paints_and_offers_reveal_then_shows_key(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    page_url = reverse("courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    page = client.get(page_url).content.decode()
    right, wrong = _BLANK.findall(page)[:2]
    assert "is-correct" in right and "is-incorrect" in wrong
    assert 'name="reveal"' in page and "data-answer-key" not in page
    _fetch(client, unit, el, {"reveal": "1"})
    page = client.get(page_url).content.decode()
    assert "data-answer-key" in page and "answer shown" in page


@pytest.mark.django_db
def test_resume_after_blank_added(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=1)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    q = el.content_object
    Blank.objects.create(question=q, order=2, accepted="7")
    q.stem = parse("{{11}} {{9}} {{7}}")[0]
    q.save()
    page = client.get(reverse("courses:quiz_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk}))
    assert page.status_code == 200
    blanks = _BLANK.findall(page.content.decode())
    assert len(blanks) == 3
    assert "is-incorrect" in blanks[2]  # mark() pads the short stored answer with ""


@pytest.mark.django_db
def test_nojs_reveal_rerenders_quiz_with_key(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    client.post(_url(unit, el), {"blank": ["11", "5"]})
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert "data-answer-key" in page and "answer shown" in page


@pytest.mark.django_db
def test_previewer_reveal_divergences(client):
    user = make_login(client, "author")
    user.is_staff = True  # staff + not enrolled = the previewer path
    user.save()
    unit = make_quiz_unit()
    el = _fb(unit)
    # Empty form on reveal: marked as-is, locked, 0 marks, switch shown.
    body = _fetch(client, unit, el, {"blank": ["", ""], "reveal": "1", "attempt": "1"}).content.decode()
    assert "answer shown" in body and "0 / 1" in body and "data-answer-switch" in body
    # Form edited after the last Check: the confirm text shows the Check's marks, the
    # lock marks the edited form -- they differ, accepted on this path (spec §3.3).
    body = _fetch(client, unit, el, {"blank": ["11", "5"], "attempt": "1"}).content.decode()
    assert "(0.5 of 1)" in body
    body = _fetch(client, unit, el, {"blank": ["", "5"], "reveal": "1", "attempt": "1"}).content.decode()
    assert "answer shown" in body and "0 / 1" in body
    # Fully correct form on reveal: Correct, no switch.
    body = _fetch(client, unit, el, {"blank": ["11", "9"], "reveal": "1", "attempt": "1"}).content.decode()
    assert "Correct" in body and "answer shown" in body and "data-answer-switch" not in body


def _staff_previewer(client):
    user = make_login(client, "prev_staff")
    user.is_staff = True  # staff + not enrolled = the previewer path
    user.save()
    return make_quiz_unit()


@pytest.mark.django_db
def test_nojs_previewer_check_paints_and_offers_reveal(client):
    # The previewer has no stored responses, so the no-JS re-render only shows
    # the colours / button through _quiz_render_feedback's st.update(state).
    unit = _staff_previewer(client)
    el = _fb(unit)
    page = client.post(_url(unit, el), {"blank": ["11", "5"], "attempt": "1"}).content.decode()
    right, wrong = _BLANK.findall(page)[:2]
    assert "is-correct" in right and "is-incorrect" in wrong
    assert 'name="reveal"' in page


@pytest.mark.django_db
def test_nojs_previewer_reveal_works(client):
    # No `attempt` is posted without JS: parse_attempt floors it at 1 (spec §3.3), so
    # the previewer's Show answer still reveals.
    unit = _staff_previewer(client)
    el = _fb(unit)
    page = client.post(_url(unit, el), {"blank": ["11", "5"], "reveal": "1"}).content.decode()
    assert "answer shown" in page and "data-answer-key" in page


@pytest.mark.django_db
def test_nojs_previewer_validation_keeps_empty_form(client):
    unit = _staff_previewer(client)
    el = _fb(unit)
    page = client.post(_url(unit, el), {"blank": ["", ""], "attempt": "1"}).content.decode()
    assert "is-validation" in page
    assert all("is-correct" not in t and "is-incorrect" not in t for t in _BLANK.findall(page))


@pytest.mark.django_db
def test_ephemeral_fetch_validation_is_a_fragment(client):
    unit = _staff_previewer(client)
    el = _fb(unit)
    body = _fetch(client, unit, el, {"blank": ["", ""], "attempt": "1"}).content.decode()
    assert "<form" not in body and "is-validation" in body
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    ch = add_element(unit, q)
    body = _fetch(client, unit, ch, {"attempt": "1"}).content.decode()
    assert "<form" not in body and "is-validation" in body


@pytest.mark.django_db
def test_key_edit_then_reveal_keeps_stored_marks(client):
    _u, unit = _quiz(client)
    el = _fb(unit, ["11", "9", "2", "22"])
    _fetch(client, unit, el, {"blank": ["11", "", "", ""]})  # stored 0.25
    Blank.objects.filter(question=el.content_object, order=1).update(accepted="")
    body = _fetch(client, unit, el, {"reveal": "1"}).content.decode()
    assert "0.25 / 1" in body


@pytest.mark.django_db
def test_confirm_marks_match_line_marks(client):
    _u, unit = _quiz(client)
    el = _fb(unit, ["11", "9", "2", "22"])
    body = _fetch(client, unit, el, {"blank": ["11", "", "", ""]}).content.decode()
    assert "(0.25 of 1)" in body and "0.25 / 1" in body


@pytest.mark.django_db
def test_key_edit_after_stored_correct_paints_all_green(client):
    # NOTE: on resume a stored-correct fill-blank renders render_inputs(locked=True),
    # which is all is-correct regardless of verdicts -- this guards resume only.
    # The override in quiz_render_state is pinned by the RESULTS-page test in
    # Task 10 (test_results_stored_correct_key_edited_all_green).
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "9"]})
    Blank.objects.filter(question=el.content_object, order=1).update(accepted="7")
    page = client.get(reverse("courses:quiz_unit",
                              kwargs={"slug": unit.course.slug, "node_pk": unit.pk})).content.decode()
    assert all("is-correct" in t for t in _BLANK.findall(page)[:2])


@pytest.mark.django_db
def test_locked_choice_still_whole_element_with_marks(client):
    _u, unit = _quiz(client)
    from courses.models import Choice

    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=1)
    Choice.objects.create(question=q, text="A", is_correct=True)
    b = Choice.objects.create(question=q, text="B", is_correct=False)
    el = add_element(unit, q)
    body = _fetch(client, unit, el, {"choice": str(b.pk)}).content.decode()  # WRONG, locks
    assert "<form" in body and "question__choice-marker" in body
    # Spec §2.2: a wrong locked choice keeps its inline marks -- no switch, no copy.
    assert "data-answer-switch" not in body and "data-answer-key" not in body


@pytest.mark.django_db
def test_editor_try_quiz_reveal(client):
    from tests.factories import CourseFactory, ContentNodeFactory, make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    el = _fb(unit)
    url = reverse("courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk})
    body = client.post(url, {"blank": ["11", "5"], "attempt": "1"},
                       HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert 'name="reveal"' in body and "is-incorrect" in body
    body = client.post(url, {"blank": ["11", "5"], "reveal": "1", "attempt": "1"},
                       HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "data-answer-key" in body and "answer shown" in body
    assert body.count("data-question-feedback") == 1
    assert body.count('name="reveal"') == 0  # locked: no second Show answer
    assert QuestionResponse.objects.count() == 0
```

Append to `tests/test_quiz_lock_rule_parity.py` (one case per `can_reveal` condition, both paths):

Add to the file's TOP import block (it already imports `pytest`, `make_login`, `EnrollmentFactory`, `add_element`, `make_quiz_unit`; `_url` is already defined), one import per line, no aliases:

```python
from courses.fillblank import parse
from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionResponse
```

then append:

```python


def _reveal_setup(client, *, enrolled, kind, marking_mode="A", attempts=1):
    user = make_login(client, "rv_" + ("e" if enrolled else "p"))
    if not enrolled:
        user.is_staff = True
        user.save()
    unit = make_quiz_unit()
    if enrolled:
        EnrollmentFactory(student=user, course=unit.course)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(stem=parse("{{11}}")[0], marking_mode=marking_mode, max_attempts=3)
        Blank.objects.create(question=q, order=0, accepted="11")
        data = {"blank": ["5"]}
    else:
        q = ChoiceQuestionElement.objects.create(stem="?", marking_mode=marking_mode, max_attempts=3)
        Choice.objects.create(question=q, text="A", is_correct=True)
        wrong = Choice.objects.create(question=q, text="B", is_correct=False)
        data = {"choice": [str(wrong.pk)]}  # a real (wrong) attempt
    el = add_element(unit, q)
    for n in range(attempts):
        client.post(_url(unit, el), {**data, "attempt": str(n + 1)},
                    HTTP_X_REQUESTED_WITH="fetch")
    return unit, el, data


def _reveal(client, unit, el, data, made):
    return client.post(_url(unit, el), {**data, "reveal": "1", "attempt": str(made)},
                       HTTP_X_REQUESTED_WITH="fetch")


@pytest.mark.django_db
@pytest.mark.parametrize("kind,marking_mode,accepted", [
    ("fillblank", "A", True),
    ("fillblank", "N", False),
    ("choice", "A", False),  # unconverted type
])
def test_reveal_rule_parity(client, kind, marking_mode, accepted):
    unit, el, data = _reveal_setup(client, enrolled=True, kind=kind, marking_mode=marking_mode)
    enrolled = _reveal(client, unit, el, data, 1)
    client.logout()
    unit2, el2, data2 = _reveal_setup(client, enrolled=False, kind=kind, marking_mode=marking_mode)
    ephemeral = _reveal(client, unit2, el2, data2, 1)
    if accepted:
        assert enrolled.status_code == 200 and b"answer shown" in enrolled.content
        assert b"answer shown" in ephemeral.content
    else:
        # Enrolled: refused (409, or the locked response for N which locked on its
        # first submit). Ephemeral: the reveal is ignored -> a normal Check.
        assert enrolled.status_code == 409
        assert b"answer shown" not in ephemeral.content


@pytest.mark.django_db
def test_reveal_parity_no_attempt_yet(client):
    unit, el, data = _reveal_setup(client, enrolled=True, kind="fillblank", attempts=0)
    assert _reveal(client, unit, el, data, 0).status_code == 409
    assert QuestionResponse.objects.filter(element=el, revealed_at__isnull=False).count() == 0
    # The EPHEMERAL twin is deliberately not asserted: spec §3.3 floors the client
    # attempt count at 1 there, so its check is advisory (a pre-Check reveal passes).
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_flow.py -p no:randomly`
Expected: FAIL — fragment returned, `reveal` ignored (attempt consumed). Expected to PASS already (regression guards on today's behaviour): `test_locked_choice_still_whole_element_with_marks` (choice already takes the whole-element path), `test_nojs_previewer_validation_keeps_empty_form`, `test_key_edit_after_stored_correct_paints_all_green` (resume's locked `mark_result.correct` already renders every blank is-correct — it guards resume only), and in the parity file `test_reveal_rule_parity[fillblank-N-False]` (N already locks → 409; the ephemeral reveal already runs as a plain Check). The parity file is only partly RED here (the fillblank-A and choice cases).

- [ ] **Step 3: Implement**

`courses/views.py` imports: add `BLANK_QUIZ_STATE`, `can_reveal`, `quiz_render_state` to the `courses.quiz` imports.

`build_quiz_context` — replace the `state = {...}` literal and the `if r is not None and r.attempt_count > 0:` body with:

```python
        state = {"qnum": qnum, **BLANK_QUIZ_STATE, "attempts_left": None, "feedback_html": ""}
        state["locked"] = bool(r.locked) if r else False
        if r is not None and r.attempt_count > 0:
            result = (
                _stored_result(q, r)
                if q.marking_mode == QuestionElement.MarkingMode.AUTO
                else None  # [N]/[R] -> neutral branch in quiz_feedback_context
            )
            # One helper for every quiz render path (spec §2.4): verdicts on both
            # branches, mark_result / key copy only once locked.
            state.update(quiz_render_state(q, r, result))
            fb_ctx = quiz_feedback_context(q, r, result=result)
            state["attempts_left"] = fb_ctx.get("attempts_left")
            state["feedback_html"] = render_to_string(
                "courses/elements/_quiz_question_feedback.html", fb_ctx
            )
```

`_quiz_render_feedback` — replace the fetch branch and the no-JS `st[...]` patch:

```python
    fb_ctx = quiz_feedback_context(
        question, response, result=result, validation=validation
    )
    # Validation keeps the bare fragment for every type (spec §2.4): the student's
    # (empty) inputs stay as they are. A change for choice, which used to re-render.
    state = None if validation else quiz_render_state(question, response, result)
    if _wants_fragment(request):
        if state is not None and (
            question.SUPPORTS_REVEAL or question.INLINE_QUIZ_REVEAL
        ):
            # Verdicts / key copy / switch / Show answer live on the controls, outside
            # the feedback box: return the whole element; quiz.js swaps the form body.
            return HttpResponse(
                question.render(
                    element=element,
                    mode="quiz",
                    feedback_for_pk=element.pk,
                    action_url=reverse(
                        "courses:quiz_answer",
                        kwargs={
                            "slug": node.course.slug,
                            "node_pk": node.pk,
                            "element_pk": element.pk,
                        },
                    ),
                    attempts_left=fb_ctx.get("attempts_left"),
                    feedback_html=render_to_string(
                        "courses/elements/_quiz_question_feedback.html", fb_ctx
                    ),
                    **state,
                )
            )
        return render(request, "courses/elements/_quiz_question_feedback.html", fb_ctx)
```

and in the no-JS branch, replace the body of `if st is not None:` with:

```python
        st["feedback_html"] = fragment
        if state is not None:
            # Every new render key, set by hand: a PREVIEWER has responses == {}, so
            # build_quiz_context derived nothing for this question (spec §2.4).
            st.update(state)
        else:
            # Validation: keep the prior stored answer (student) or the empty form
            # (previewer), exactly as before.
            st["locked"] = response.locked
            selected, submitted = rehydrate(question, response.latest_answer)
            st["selected_ids"] = selected
            st["submitted_values"] = submitted
```

Add, next to `_quiz_locked_response`:

```python
def _quiz_reveal_refused(request, slug, node_pk):
    # Show answer on an ineligible question (no attempt yet / N-R / not converted):
    # fetch -> 409 (quiz.js reloads); no-JS -> back to the quiz page (spec §3.2).
    if _wants_fragment(request):
        return HttpResponse(
            _("Show answer is not available for this question."), status=409
        )
    return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
```

`quiz_answer`:
- previewer branch: replace the `ephemeral_quiz_feedback(...)` call with

```python
        attempt = parse_attempt(request.POST)
        # An ineligible reveal is ignored and processed as a normal Check (spec §3.3).
        # Spec §3.3: attempts_made = parse_attempt(POST), floored at 1 -- the
        # server-side check is ADVISORY on this stateless path (the client never
        # offers the button before a Check; a no-JS previewer posts no `attempt`
        # and still reveals).
        reveal = bool(request.POST.get("reveal")) and can_reveal(
            question, attempts_made=attempt, locked=False
        )
        stand_in, result, validation = ephemeral_quiz_feedback(
            question, question.build_answer(request.POST), attempt, reveal=reveal
        )
```

- enrolled branch: directly after the `response, _ = QuestionResponse.objects.select_for_update().get_or_create(...)` line and BEFORE the locked-or-exhausted gate, insert:

```python
        if request.POST.get("reveal"):
            # Show answer (spec §3.2). Runs BEFORE the exhausted gate (an author
            # may lower max_attempts below the student's count -- Show answer is the
            # way out) and before build_answer / validation (an emptied form must
            # not block it). Ignores the posted answer: the stored latest attempt is
            # what is marked and shown. Consumes no attempt, writes no Attempt row.
            if response.locked:
                return _quiz_locked_response(request, slug, node_pk)
            if not can_reveal(
                question, attempts_made=response.attempt_count, locked=False
            ):
                return _quiz_reveal_refused(request, slug, node_pk)
            response.locked = True
            response.revealed_at = timezone.now()
            response.save(update_fields=["locked", "revealed_at"])
            revealed_result = _stored_result(question, response)
        else:
            revealed_result = None
```

  then wrap everything from the existing locked-or-exhausted gate down to `Attempt.objects.create(...)` in `if revealed_result is None:` (indent it one level), and change the final call to:

```python
    return _quiz_render_feedback(
        request,
        node,
        element,
        question,
        response,
        result=revealed_result if revealed_result is not None else result,
    )
```

  (initialise `result = None` above the `with` block so the name always exists).

`courses/views_manage.py` `element_try` quiz branch — replace from `attempt = parse_attempt(request.POST)` to the end of the branch with:

```python
    from courses.quiz import can_reveal
    from courses.quiz import quiz_render_state

    attempt = parse_attempt(request.POST)
    # Spec §3.3: parse_attempt's floor-at-1 count; advisory on this path.
    reveal = bool(request.POST.get("reveal")) and can_reveal(
        question, attempts_made=attempt, locked=False
    )
    stand_in, result, validation = ephemeral_quiz_feedback(
        question, answer, attempt, reveal=reveal
    )
    ctx = quiz_feedback_context(
        question, stand_in, result=result, validation=validation
    )
    if not validation and (question.SUPPORTS_REVEAL or question.INLINE_QUIZ_REVEAL):
        # Same whole-element contract as the student path (views._quiz_render_feedback);
        # editor.js swaps the live form's body.
        return HttpResponse(
            question.render(
                element=el,
                mode="quiz",
                feedback_for_pk=el.pk,
                action_url=request.path,
                attempts_left=ctx.get("attempts_left"),
                feedback_html=render_to_string(
                    "courses/elements/_quiz_question_feedback.html", ctx
                ),
                **quiz_render_state(question, stand_in, result),
            )
        )
    return render(request, "courses/elements/_quiz_question_feedback.html", ctx)
```

- [ ] **Step 4: Run to verify, then run the quiz suites and rewrite quiz-reveal assertions for the three converted types**

Run: `uv run pytest tests/test_quiz_reveal_flow.py tests/test_quiz_lock_rule_parity.py tests/test_quiz_reveal_helpers.py tests/test_quiz_reveal_result_line.py tests/test_quiz_reveal_fillblank_render.py tests/test_quiz_reveal_single_part.py -p no:randomly` → PASS (the last four guard code this task rewrites: build_quiz_context, _quiz_render_feedback, choice's whole-element path).

Then: `uv run pytest tests/test_quiz_answer.py tests/test_quiz_noleak.py tests/test_quiz_resume.py tests/test_quiz_previewer_answer.py tests/test_quiz_choice_inline_marking.py tests/test_element_try.py tests/test_ux_roster_and_feedback.py tests/test_questions_2b_consumption.py tests/test_questions_consumption.py tests/test_quiz_render.py tests/test_ephemeral_quiz_feedback.py courses/tests/test_fillblank_inline_verdicts.py tests/test_questions_2d_quiz_noleak.py tests/test_questions_2diii_quiz.py tests/test_quiz_previewer_render.py tests/test_quiz_views.py tests/test_choice_nudge_paths.py -p no:randomly`

`courses/tests/test_fillblank_inline_verdicts.py::test_quiz_fillblank_still_lists_the_correct_answers` (RED since Task 6) is rewritten here: keep its substance "the quiz reveals the answer where the lesson does not" — assert the locked-wrong quiz response contains `data-answer-key` with the accepted value and NO "Correct answer:" list, and rename it `test_quiz_fillblank_reveals_the_answer_via_key_copy`.

Allowed rewrites (each with a comment naming the replaced assertion):
- a locked wrong fill-blank / short-text / number quiz response no longer contains "Correct answer:" / "Expected:" — assert the key copy instead (`data-answer-key` + `value="<key>"`);
- a converted type's Check response is now the whole element (`<form`), not the fragment;
- choice's VALIDATION response is now the fragment (spec §2.4 calls this change out).

Forbidden: removing or weakening any assertion that key text is ABSENT before the lock. If a no-leak test now fails because key text appears before the lock, that is a real leak — fix the code.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py courses/views_manage.py tests/
git commit -m "feat(quiz-reveal): whole-element quiz responses, resume/no-JS verdicts, Show answer (enrolled, previewer, editor)"
```

---

### Task 9: quiz.js and editor.js — submitter, confirm, counter, freeze

**Files:**
- Modify: `courses/static/courses/js/quiz.js`
- Modify: `courses/static/courses/js/editor.js` (the try-it branch of the delegated `submit` listener, ~lines 406–473)
- Test: `tests/test_e2e_quiz_reveal.py` (new, `-m e2e`)

**Interfaces:**
- Consumes: the `data-reveal-btn` button (`name="reveal"`, `data-confirm`), `[data-answer-switch]`, `[data-answer-view]`.

- [ ] **Step 1: Write the failing e2e tests**

```python
# tests/test_e2e_quiz_reveal.py
"""Playwright: Show answer + switch in the live quiz and the editor (spec §2.3, §3.1)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _student(username):
    return make_verified_user(username=username, email=f"{username}@t.example.com",
                              password=TEST_PASSWORD)


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_quiz(username, slug, max_attempts=3):
    from django.contrib.auth import get_user_model

    from courses.fillblank import parse
    from courses.models import Blank, Element, Enrollment, FillBlankQuestionElement
    from tests.factories import ContentNodeFactory, CourseFactory

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None, title="Q")
    q = FillBlankQuestionElement.objects.create(
        stem=parse("log {{11}} = {{9}} · {{2}} = {{22}}")[0], max_attempts=max_attempts)
    for i, a in enumerate(["11", "9", "2", "22"]):
        Blank.objects.create(question=q, order=i, accepted=a)
    Element.objects.create(unit=unit, content_object=q)
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_show_answer_flow_and_switch(browser, live_server):
    _student("rev_stu")
    course, unit = _seed_quiz("rev_stu", "e2e-reveal")
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_stu")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    blanks = q.locator("[data-answer-yours] input[name='blank']")
    blanks.nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator(".question__verdict.is-partial").wait_for(timeout=6000)
    assert "is-incorrect" in blanks.nth(1).get_attribute("class")
    # Measured, not just classed: app.css's input[type=text] (0,1,1) must not win.
    paint = "el => getComputedStyle(el).borderTopColor"
    assert blanks.nth(0).evaluate(paint) != blanks.nth(1).evaluate(paint)
    # Colours persist until the next Check (spec §1.2): editing a green part keeps it.
    blanks.nth(0).fill("12")
    assert "is-correct" in blanks.nth(0).get_attribute("class")
    blanks.nth(0).fill("11")
    # Confirm must be ACCEPTED explicitly: Playwright auto-dismisses dialogs.
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    yours = q.locator("[data-answer-view='yours']")
    assert yours.is_checked() and yours.is_enabled()  # not frozen
    key = q.locator("[data-answer-key]")
    assert not key.is_visible()
    q.locator("label:has([data-answer-view='key'])").click()
    assert key.is_visible() and key.locator("input").nth(1).input_value() == "9"
    # Reload with "Correct answer" SELECTED must still reopen on "Your answer"
    # (autocomplete="off" defeats form-state restoration, D3).
    page.reload()
    q = page.locator("[data-question]").first
    assert q.locator("[data-answer-view='yours']").is_checked()
    assert not q.locator("[data-answer-view='key']").is_checked()


@pytest.mark.django_db(transaction=True)
def test_short_text_verdict_colours_are_computed(browser, live_server):
    # Short text's .question__text-input.is-* rules sit on the app.css
    # input[type=text] collision: measure, don't trust the specificity argument.
    from django.contrib.auth import get_user_model

    from courses.models import Element, Enrollment, ShortTextQuestionElement
    from tests.factories import ContentNodeFactory, CourseFactory

    _student("rev_st")
    user = get_user_model().objects.get(username="rev_st")
    course = CourseFactory(slug="e2e-reveal-st")
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None, title="Q")
    for accepted in ("Paris", "Oslo"):
        Element.objects.create(unit=unit, content_object=ShortTextQuestionElement.objects.create(
            stem="?", accepted=accepted, max_attempts=3))
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_st")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    qs = page.locator("[data-question]")
    paint = "el => getComputedStyle(el).borderTopColor"
    plain = qs.nth(1).locator("input[name='answer']").evaluate(paint)
    qs.nth(0).locator("input[name='answer']").fill("Rome")
    qs.nth(0).locator("button[type='submit']:not([name='reveal'])").click()
    qs.nth(0).locator("input.is-incorrect").wait_for(timeout=6000)
    wrong = qs.nth(0).locator("input[name='answer']").evaluate(paint)
    assert wrong != plain


@pytest.mark.django_db(transaction=True)
def test_enter_in_a_blank_checks_not_reveals(browser, live_server):
    _student("rev_enter")
    course, unit = _seed_quiz("rev_enter", "e2e-reveal-enter")
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_enter")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)  # button now exists
    # NOW Enter: implicit submission uses the FIRST submit button -- which must be
    # Check. Show answer would lock and draw the switch.
    q.locator("input[name='blank']").nth(1).fill("5")
    # Sync on the Enter POST itself -- the partial verdict is ALREADY on screen from
    # the first Check, so waiting for it would pass before the response lands.
    with page.expect_request(lambda r: r.method == "POST" and "/answer/" in r.url) as req:
        q.locator("input[name='blank']").nth(1).press("Enter")
    assert "reveal" not in (req.value.post_data or "")
    q.get_by_text("1 attempt left").wait_for(timeout=6000)  # only the Enter response says 1
    assert q.locator("[data-answer-switch]").count() == 0
    assert q.locator("[data-reveal-btn]").count() == 1


@pytest.mark.django_db(transaction=True)
def test_previewer_reveal_keeps_client_counter(browser, live_server):
    # The client counter only matters on the stateless previewer path.
    from django.contrib.auth import get_user_model

    _student("rev_prev")
    course, unit = _seed_quiz("rev_prev", "e2e-reveal-prev")
    user = get_user_model().objects.get(username="rev_prev")
    from courses.models import Enrollment

    Enrollment.objects.filter(student=user).delete()  # not enrolled ...
    user.is_staff = True  # ... but staff -> previewer
    user.save()
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_prev")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)
    assert q.get_attribute("data-attempts-made") == "1"
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    assert q.get_attribute("data-attempts-made") == "1"


@pytest.mark.django_db(transaction=True)
def test_reveal_sent_when_submitter_is_missing(browser, live_server):
    # Old engines (Safari < 15.4) have no SubmitEvent.submitter: the click fallback
    # must still send reveal=1.
    _student("rev_old")
    course, unit = _seed_quiz("rev_old", "e2e-reveal-old")
    ctx = browser.new_context()
    ctx.add_init_script(
        "Object.defineProperty(SubmitEvent.prototype, 'submitter', {get() { return undefined; }});"
    )
    page = ctx.new_page()
    _login(page, live_server, "rev_old")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
```

Add the editor try-it test (a PA author, a QUIZ unit, the live preview):

```python
@pytest.mark.django_db(transaction=True)
def test_editor_try_it_reveal_switch_survives_freeze(browser, live_server):
    from courses.fillblank import parse
    from courses.models import Blank, Element, FillBlankQuestionElement
    from tests.factories import ContentNodeFactory, CourseFactory
    from tests.test_e2e_questions import _editor_url, _make_pa_user

    owner = _make_pa_user("rev_author")
    course = CourseFactory(slug="e2e-reveal-editor", owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz", parent=None, title="Q")
    q = FillBlankQuestionElement.objects.create(stem=parse("{{11}} {{9}}")[0], max_attempts=3)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    Element.objects.create(unit=unit, content_object=q)

    page = browser.new_context().new_page()
    _login(page, live_server, "rev_author")
    page.goto(_editor_url(live_server, unit))
    q_el = page.locator('[data-scope="preview"] [data-question]').first
    q_el.locator("input[name='blank']").nth(0).fill("11")
    q_el.locator("button[type='submit']:not([name='reveal'])").click()
    q_el.locator("[data-reveal-btn]").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())
    q_el.locator("[data-reveal-btn]").click()
    q_el.locator("[data-answer-switch]").wait_for(timeout=6000)
    assert q_el.locator("[data-answer-view='key']").is_enabled()  # editor freeze skipped it
    q_el.locator("label:has([data-answer-view='key'])").click()
    assert q_el.locator("[data-answer-key]").is_visible()
    # The reveal consumed no attempt: the client counter stayed at 1 (spec §3.1).
    assert q_el.get_attribute("data-attempts-made") == "1"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_e2e_quiz_reveal.py -m e2e -p no:randomly`
Expected: FAIL — reveal click posts a plain Check (no `[data-answer-switch]` appears; the attempt counter moves). `test_enter_in_a_blank_checks_not_reveals` and `test_short_text_verdict_colours_are_computed` (needs only the Task 7 CSS + Task 8 responses) are regression guards expected to PASS already. The Enter guard's falsification belongs in Step 5 (it cannot go RED before quiz.js sends the submitter).

- [ ] **Step 3: Implement quiz.js**

At the top of the IIFE (before the `document.querySelectorAll("form.question__form").forEach` block):

```js
  // Engines without SubmitEvent.submitter (Safari < 15.4): remember which submit
  // button was clicked; the submit handler reads it once, then clears it. Implicit
  // submission (Enter) fires a click on the default button, so Check is recorded too.
  document.addEventListener(
    "click",
    (e) => {
      const b = e.target.closest && e.target.closest('button[type="submit"]');
      if (b && b.form) b.form._libliSubmitter = b;
    },
    true,
  );
```

In the submit handler, right after `e.preventDefault();`:

```js
      const submitter = e.submitter || form._libliSubmitter || null;
      form._libliSubmitter = null;
      const isReveal = !!(submitter && submitter.name === "reveal");
      // Show answer ends the question: confirm first (text + marks from the server).
      if (isReveal && !window.confirm(submitter.dataset.confirm || "")) return;
```

Replace `const body = new FormData(form); body.append("attempt", String(made + 1));` with:

```js
      const body = new FormData(form);
      // NOT new FormData(form, submitter): older engines ignore the 2nd argument.
      if (submitter && submitter.name) body.append(submitter.name, submitter.value);
      // A reveal consumes no attempt: send the current count, not the next one.
      body.append("attempt", String(isReveal ? made : made + 1));
```

Change the counter guard to `if (qEl && !isReveal && !box.querySelector(".is-validation")) {`.

Change the freeze to skip the switch:

```js
        form
          .querySelectorAll("input, button, select, textarea, fieldset")
          .forEach((n) => {
            // The Your/Correct switch stays usable after the lock (spec §2.3).
            if (!n.closest("[data-answer-switch]")) n.disabled = true;
          });
```

- [ ] **Step 4: Implement editor.js (try-it branch)**

Inside `root.addEventListener("submit", …)`'s try-it branch, right after `e.preventDefault();`:

```js
      var submitter = e.submitter || tryForm._libliSubmitter || null;
      tryForm._libliSubmitter = null;
      var isReveal = !!(submitter && submitter.name === "reveal");
      if (isReveal && !window.confirm(submitter.getAttribute("data-confirm") || "")) return;
```

Replace `if (e.submitter && e.submitter.name) body.append(e.submitter.name, e.submitter.value);` and the following `body.append("attempt", String(made + 1));` with:

```js
      if (submitter && submitter.name) body.append(submitter.name, submitter.value);
      body.append("attempt", String(isReveal ? made : made + 1));  // reveal: no attempt
```

Change `if (!slot.querySelector(".is-validation")) {` to `if (!isReveal && !slot.querySelector(".is-validation")) {`.

Change the freeze `.forEach(function (n) { n.disabled = true; })` to:

```js
            .forEach(function (n) {
              if (!n.closest("[data-answer-switch]")) n.disabled = true;
            });
```

Add the submitter-fallback click listener next to the other `root.addEventListener` calls:

```js
  // SubmitEvent.submitter fallback for old engines -- see quiz.js.
  root.addEventListener(
    "click",
    function (e) {
      var b = e.target.closest && e.target.closest('[data-scope="preview"] button[type="submit"]');
      if (b && b.form) b.form._libliSubmitter = b;
    },
    true
  );
```

- [ ] **Step 5: Run to verify, then the existing JS-driven quiz / editor e2e**

Run: `uv run pytest tests/test_e2e_quiz_reveal.py tests/test_e2e_quiz.py tests/test_e2e_quiz_previewer.py tests/test_e2e_quiz_choice_marking.py tests/test_e2e_fillblank_lock.py tests/test_e2e_fillblank_inline_verdicts.py tests/test_e2e_choice_editor_feedback.py -m e2e -p no:randomly`
Also run `tests/test_e2e_uniform_block_width.py tests/test_e2e_blank_input_width.py tests/test_e2e_unit_nav.py tests/test_e2e_slideshow.py tests/test_e2e_question_restore.py tests/test_e2e_questions_2b.py tests/test_e2e_questions_2d.py tests/test_e2e_questions_2dii.py tests/test_e2e_questions_2diii.py tests/test_e2e_switchgrid.py tests/test_e2e_quiz_finish.py tests/test_e2e_quiz_math.py -m e2e` (Finish now meets two-button forms and whole-element swaps; math must re-typeset after the swap).

Enter-guard falsification (only now, with the submitter sent): move `{% include "courses/elements/_reveal_button.html" %}` ABOVE the Check button in `fillblankquestionelement.html` → `test_enter_in_a_blank_checks_not_reveals` must go RED — as an `expect_request` timeout (Enter picks Show answer, quiz.js calls `confirm()`, Playwright auto-dismisses it, no POST is sent); restore by hand.

Expected: PASS. Allowed e2e rewrites (comment naming the replaced assertion):
- a partly-right answer's verdict locator `.is-incorrect` becomes `.is-partial` (Task 5) — this hits unconverted types too (e.g. extended response with a missing keyword);
- a converted type's Check now swaps the whole form, so a locator held across a Check must be re-queried;
- a strict `button[type='submit']` Locator on a converted QUIZ question that now also matches Show answer (a strict-mode violation after the first Check — e.g. `tests/test_e2e_quiz.py` ~line 134) becomes `button[type='submit']:not([name='reveal'])`; legacy non-strict `page.click(...)` calls need no change;
- QUIZ: an assertion that `.question__reveal-text` shows the answer for a locked short-text / number / fill-blank question (e.g. `tests/test_e2e_quiz_previewer.py` ~108–117) becomes: click `label:has([data-answer-view='key'])`, then read `[data-answer-key] input` `input_value()`;
- LESSON (D13): an assertion on a number/short-text lesson `.question__reveal-text` (e.g. `tests/test_e2e_questions_2b.py::test_reveal_shows_the_fraction_and_hides_a_zero_tolerance`) moves to the QUIZ key copy — keep its substance: the key copy shows the value as authored (e.g. `1/3`), and prints no "±" when the tolerance is zero. Never simply delete such an assertion. Mutant check (required): comment out the `if (submitter && submitter.name) body.append(...)` line in quiz.js → `test_show_answer_flow_and_switch` must go RED; restore it by hand (never `git checkout`).

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/quiz.js courses/static/courses/js/editor.js tests/test_e2e_quiz_reveal.py
git commit -m "feat(quiz-reveal): quiz.js/editor.js send the submitter, confirm, keep the switch live"
```

---

### Task 10: Results page and analytics tag

**Files:**
- Modify: `courses/views.py` (`quiz_results`, new `_results_question_html`, `_results_row` adds `revealed`)
- Create: `templates/courses/elements/_results_question_feedback.html`
- Modify: `templates/courses/quiz_results.html`
- Modify: `templates/courses/manage/analytics_student_quiz.html`
- Test: `tests/test_quiz_reveal_results.py` (new)

**Interfaces:**
- Consumes: `quiz_render_state`, `key_view`, `_stored_result`, `render(mode="results")`.
- Produces: `row["rendered"]` (SafeString or `""`) and `row["revealed"]` (bool) on results rows; every existing `_results_row` key keeps its semantics.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quiz_reveal_results.py
"""Results page renders converted questions as they ended (spec §4) + analytics tag (§5)."""

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _setup(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    token_stem, _ = parse("{{11}} {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=3)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    fb = Element.objects.create(unit=unit, content_object=q)
    unanswered = add_element(unit, ShortTextQuestionElement.objects.create(stem="U?", accepted="Paris"))
    nm = add_element(unit, ShortTextQuestionElement.objects.create(
        stem="N?", accepted="Oslo", marking_mode=QuestionElement.MarkingMode.NOT_MARKED))
    return user, unit, fb, unanswered, nm


def _answer(client, unit, el, data):
    return client.post(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/",
                       data, HTTP_X_REQUESTED_WITH="fetch")


def _finish_and_get_results(client, unit):
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    return client.get(reverse("courses:quiz_results", kwargs=kw)).content.decode()


@pytest.mark.django_db
def test_results_render_questions_as_they_ended(client):
    _u, unit, fb, unanswered, nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})
    _answer(client, unit, fb, {"reveal": "1"})
    _answer(client, unit, nm, {"answer": "Bergen"})
    body = _finish_and_get_results(client, unit)
    assert "<form" not in body.split("quiz-results__list")[1]
    assert body.count("data-answer-switch") == 2  # fb (partial) + unanswered short text
    assert "answer shown" in body
    assert 'value="Paris"' in body  # unanswered key visible
    assert "Not answered (0/1)" in body  # spec §4: auto-marked unanswered shows 0 / 1
    assert "Oslo" not in body  # N question never shows a key
    assert "Correct answer:" not in body and "Expected:" not in body
    assert f'name="answer_view_{fb.pk}"' in body


@pytest.mark.django_db
def test_results_stored_correct_key_edited_all_green(client):
    # The results branch renders the student's copy with locked=False, so THIS is
    # where quiz_render_state's all-correct override is visible (spec §2.6).
    import re

    _u, unit, fb, _un, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "9"]})
    Blank.objects.filter(question=fb.content_object, order=1).update(accepted="7")
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    blanks = re.findall(r'<input[^>]*name="blank"[^>]*>', row)
    assert blanks and all("is-correct" in b for b in blanks)
    assert "data-answer-switch" not in row


@pytest.mark.django_db
def test_results_mirror_case_partial_line_over_green_parts(client):
    import re

    _u, unit, fb, _un, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})  # stored 0.5
    Blank.objects.filter(question=fb.content_object, order=1).update(accepted="5")
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    blanks = re.findall(r'<input[^>]*name="blank"[^>]*>', row)
    assert all("is-correct" in b for b in blanks[:2])
    assert "Partial" in row and "data-answer-switch" in row  # accepted as-is (§2.6)


@pytest.mark.django_db
@pytest.mark.parametrize("mode,answer,badge,switch,key_shown", [
    ("A", "Paris", "Correct (1/1)", False, False),
    ("A", "Rome", "Incorrect (0/1)", True, True),
    ("A", None, "Not answered (0/1)", True, True),
    ("N", "Rome", "Answer recorded", False, False),
    ("N", None, "Not answered", False, False),
    ("R", "Rome", "Awaiting review", False, False),
    ("R", None, "Awaiting review", False, False),
])
def test_results_row_matrix(client, mode, answer, badge, switch, key_shown):
    user = make_login(client, "stu_m")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", marking_mode=mode, max_attempts=1,
        explanation="<p>Because.</p>")
    el = add_element(unit, q)
    if answer is not None:
        _answer(client, unit, el, {"answer": answer})
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    assert badge in row
    assert ("data-answer-switch" in row) is switch
    assert ("data-answer-key" in row) is key_shown  # N/R never show a key
    # Explanation: hidden for recorded / review / reviewed outcomes, as today (an
    # unanswered R row's outcome is "review", so it is hidden there too).
    assert ("Because." in row) is (mode == "A" or (mode == "N" and answer is None))


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "number"])
@pytest.mark.parametrize("mode", ["N", "R"])
@pytest.mark.parametrize("answered", [True, False])
def test_results_nr_rows_never_show_the_key(client, kind, mode, answered):
    from courses.models import ShortNumericQuestionElement

    user = make_login(client, "stu_nr")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(
            stem=parse("{{11}}")[0], marking_mode=mode, max_attempts=1)
        Blank.objects.create(question=q, order=0, accepted="11")
        data = {"blank": ["5"]}
    else:
        q = ShortNumericQuestionElement.objects.create(
            stem="?", value="3.14", marking_mode=mode, max_attempts=1)
        data = {"answer": "9"}
    el = add_element(unit, q)
    if answered:
        _answer(client, unit, el, data)
    row = _finish_and_get_results(client, unit).split("quiz-results__item")[1]
    assert "data-answer-key" not in row and "data-answer-switch" not in row


@pytest.mark.django_db
def test_results_reviewed_row_shows_teacher_marks(client):
    from django.utils import timezone

    from courses.models import QuestionResponse

    user = make_login(client, "stu_r")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Essay?", accepted="Paris", marking_mode="R", max_attempts=1)
    el = add_element(unit, q)
    _answer(client, unit, el, {"answer": "Rome"})
    body_url_kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=body_url_kw))
    QuestionResponse.objects.filter(element=el).update(
        reviewed_at=timezone.now(), earned_marks="0.50", review_feedback="Half right.")
    body = client.get(reverse("courses:quiz_results", kwargs=body_url_kw)).content.decode()
    row = body.split("quiz-results__item")[1]
    assert "Reviewed (0.5/1)" in row and "Half right." in row
    assert "data-answer-switch" not in row and 'value="Paris"' not in row


@pytest.mark.django_db
def test_results_short_text_row_every_input_disabled(client):
    # Short text / number have no fieldset: freezing on the results page relies on
    # locked=True reaching the controls include (spec §4).
    import re

    user = make_login(client, "stu_dis")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(stem="?", accepted="Paris", max_attempts=1)
    el = add_element(unit, q)
    _answer(client, unit, el, {"answer": "Rome"})
    row = _finish_and_get_results(client, unit).split("quiz-results__item")[1]
    inputs = re.findall(r'<input[^>]*type="text"[^>]*>', row)
    assert len(inputs) == 2  # yours + key copy
    assert all("disabled" in t for t in inputs)
    assert 'name="answer"' in inputs[0]


@pytest.mark.django_db
def test_results_controls_are_all_disabled(client):
    _u, unit, fb, _un, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    yours = row.split("data-answer-yours")[1].split("data-answer-key")[0]
    assert "disabled" in yours  # fieldset is `data-answer-yours disabled` (Task 6)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
@pytest.mark.parametrize("answered", [True, False])
def test_analytics_expected_answer_per_type(client, kind, answered):
    # Spec §5: _results_row's keys feed analytics; every converted type, answered
    # (wrong) and unanswered, must still show its expected answer there.
    from courses.models import ShortNumericQuestionElement
    from tests.factories import make_pa

    user = make_login(client, "stu_an")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(stem=parse("{{zetakey}}")[0], max_attempts=1)
        Blank.objects.create(question=q, order=0, accepted="zetakey")
        data, key = {"blank": ["no"]}, "zetakey"
    elif kind == "text":
        q = ShortTextQuestionElement.objects.create(stem="?", accepted="Parisxyz", max_attempts=1)
        data, key = {"answer": "no"}, "Parisxyz"
    else:
        q = ShortNumericQuestionElement.objects.create(stem="?", value="3.14159", max_attempts=1)
        data, key = {"answer": "1"}, "3.14159"
    el = add_element(unit, q)
    if answered:
        _answer(client, unit, el, data)
    _finish_and_get_results(client, unit)
    client.logout()
    make_pa(client, "pa_an")
    url = reverse("courses:manage_analytics_student_quiz",
                  kwargs={"slug": unit.course.slug, "student_pk": user.pk, "node_pk": unit.pk})
    assert key in client.get(url).content.decode()


@pytest.mark.django_db
def test_analytics_keeps_expected_answers_and_tags_reveal(client):
    from tests.factories import make_pa

    user, unit, fb, unanswered, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})
    _answer(client, unit, fb, {"reveal": "1"})
    _finish_and_get_results(client, unit)
    make_pa(client, "teacher_pa")
    from courses.models import QuizSubmission

    sub = QuizSubmission.objects.get(student=user, unit=unit)
    assert sub.status == QuizSubmission.Status.SUBMITTED
    url = reverse("courses:manage_analytics_student_quiz",
                  kwargs={"slug": unit.course.slug, "student_pk": sub.student_id,
                          "node_pk": unit.pk})
    body = client.get(url).content.decode()
    assert "answer shown" in body
    assert "Paris" in body  # the unanswered row still shows its expected answer
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_quiz_reveal_results.py -p no:randomly`
Expected: FAIL — the results page still prints the old list rows. Expected to PASS already (regression guards — a RED here is a real problem): all six `test_analytics_expected_answer_per_type` cases (analytics unchanged by design), `test_results_reviewed_row_shows_teacher_marks`, and the `test_results_row_matrix` N / R cases (badge text and explanation rules unchanged; no switch / key before or after).

- [ ] **Step 3: Implement**

`_results_row` — add one key to the initial `row` dict (no other change):

```python
        "revealed": bool(response is not None and response.revealed_at),
```

New helper in `courses/views.py` (after `_results_row`):

```python
def _results_question_html(element, question, response, row):
    """A converted question rendered read-only as it ended (spec §4), via
    render(mode="results"). Separate from _results_row on purpose: analytics
    consumes _results_row's keys and must not change (spec §5)."""
    answered = row["answered"]
    auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
    if answered and auto and response.fraction is not None:
        result = _stored_result(question, response)
        state = quiz_render_state(question, response, result)
        fully_correct = bool(result.correct)
    elif answered:
        state = quiz_render_state(question, response, None)  # N/R: no verdicts
        fully_correct = False
    else:
        # Unanswered: neutral controls, mark() NOT called (spec §4).
        state = dict(BLANK_QUIZ_STATE)
        fully_correct = False
    # Every results row is locked (finalize_submission locks every response).
    key_values = key_view(
        question, mode="results", locked=True, fully_correct=fully_correct
    )
    feedback_html = render_to_string(
        "courses/elements/_results_question_feedback.html", {"row": row}
    )
    return mark_safe(  # noqa: S308 — the element template escapes its own fields
        question.render(
            element=element,
            mode="results",
            feedback_for_pk=element.pk,
            selected_ids=state["selected_ids"],
            submitted_values=state["submitted_values"],
            verdicts=state["verdicts"],
            key_values=key_values,
            locked=True,
            feedback_html=feedback_html,
        )
    )
```

(Imports: `key_view` from `courses.quiz`; `mark_safe` is already imported in views.py — verify with grep; add if not.)

`quiz_results` loop — replace `rows.append(_results_row(q, r))` with:

```python
        row = _results_row(q, r)
        row["rendered"] = (
            _results_question_html(el, q, r, row) if q.SUPPORTS_REVEAL else ""
        )
        rows.append(row)
```

`_results_question_feedback.html` (the converted rows' feedback box, built from the existing row markup):

```django
{% load i18n courses_extras %}
<div class="question__feedback-panel question__feedback-panel--{{ row.outcome }}">{# Badges: same markup as quiz_results.html's list rows and analytics_student_quiz.html, EXCEPT Not answered carries (0/N) here for auto-marked (spec §4). #}
{% if row.outcome == "correct" %}<span class="badge badge--correct">{% trans "Correct" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
{% elif row.outcome == "partial" %}<span class="badge badge--partial">{% trans "Partial" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
{% elif row.outcome == "incorrect" %}<span class="badge badge--incorrect">{% trans "Incorrect" %} (0/{{ row.possible|marks }})</span>
{% elif row.outcome == "not_answered" %}<span class="badge badge--muted">{% trans "Not answered" %}{% if row.question.marking_mode == "A" %} (0/{{ row.possible|marks }}){% endif %}</span>
{% elif row.outcome == "recorded" %}<span class="badge">{% trans "Answer recorded" %}</span>
{% elif row.outcome == "reviewed" %}<span class="badge">{% trans "Reviewed" %} ({{ row.earned|marks }}/{{ row.possible|marks }})</span>
{% elif row.outcome == "review" %}<span class="badge badge--review">{% trans "Awaiting review" %} ({% if row.possible == 1 %}{% trans "up to 1 mark" %}{% else %}{% blocktrans with m=row.possible|marks %}up to {{ m }} marks{% endblocktrans %}{% endif %})</span>{% endif %}
{% if row.revealed %}<span class="badge badge--muted">{% trans "answer shown" %}</span>{% endif %}
{% if row.review_feedback %}<div class="question__feedback question__feedback--review"><p>{{ row.review_feedback }}</p></div>{% endif %}
{% if row.question.explanation and row.outcome != "recorded" and row.outcome != "review" and row.outcome != "reviewed" %}<div class="question__explanation">{{ row.question.explanation|safe }}</div>{% endif %}
</div>
```

Note: `question__feedback-panel--{{ row.outcome }}` yields `--recorded` / `--review` / `--reviewed` for N/R rows, which have no CSS — exactly as today's `quiz_results.html` rows already do (same markup); parity, not a new gap. Include an N and an R row in the Task 12 screenshots to confirm they look as today.

`quiz_results.html` — inside `{% for row in rows %}`, make the existing `<li …>…</li>` the `{% else %}` branch of:

```django
    {% if row.rendered %}
    <li class="quiz-results__item is-{{ row.outcome }}">{{ row.rendered }}</li>
    {% else %}
    …existing <li> unchanged…
    {% endif %}
```

and update the existing `{# Badges: … change both. #}` comment in the old branch to `{# Badges: shared with analytics_student_quiz.html and _results_question_feedback.html, EXCEPT the converted rows' Not answered badge carries (0/N) for auto-marked (spec §4). #}`.

`analytics_student_quiz.html` — update its "A deliberate copy of quiz_results.html's badge markup" comment (~line 54) to name all three copies (`quiz_results.html`, `_results_question_feedback.html`, this file) and the one intended difference (converted rows' Not answered badge carries (0/N) for auto-marked, spec §4); then, directly after the badge `{% if … %}…{% endif %}` chain (line ~62):

```django
        {% if row.revealed %}<span class="badge badge--muted">{% trans "answer shown" %}</span>{% endif %}
```

- [ ] **Step 4: Run to verify, plus the results / analytics suites**

Run: `uv run pytest tests/test_quiz_reveal_results.py tests/test_quiz_results_render.py tests/test_quiz_finish.py tests/test_quiz_results_choice_reveal.py tests/test_analytics_student_quiz.py tests/test_questions_2d_results.py tests/test_questions_2diii_results.py -p no:randomly`
Then the results / analytics e2e: `uv run pytest tests/test_e2e_results.py tests/test_e2e_analytics_student_pages.py tests/test_e2e_analytics.py -m e2e -p no:randomly`.

Expected: PASS, except (a) a locator scoped to the OLD converted-row markup (`li.quiz-results__item > .question__feedback-panel …`) — converted rows now nest the panel inside `.el--question [data-answer-scope] .question__feedback`; re-scope the locator, keep the assertion; and (b) results-page assertions of "Correct answer:" / "Expected:" / per-blank reveal lists for the THREE converted types — rewrite those to the rendered element (switch + key copy) with a comment naming the replaced assertion. Choice and the PR 2 types keep their old rows untouched; any failure there is a regression. A lost badge surface, contrast or outcome border colour on a CONVERTED row (e.g. `test_e2e_analytics_student_pages.py::test_t33b_badge_has_its_own_opaque_surface_on_both_pages`) is a CSS regression to fix — never loosen that assertion.

- [ ] **Step 5: Commit**

```bash
git add courses/views.py templates/courses tests/test_quiz_reveal_results.py tests/
git commit -m "feat(quiz-reveal): results page renders converted questions as they ended; analytics 'answer shown' tag"
```

---

### Task 11: Translations and author help

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`, `django.mo`
- Modify: `docs/help/course-admin/quiz-editors.md`, `docs/help/course-admin/quiz-editors.pl.md`
- Test: `tests/test_i18n_quiz_reveal.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_i18n_quiz_reveal.py
from django.utils import translation
from django.utils.translation import gettext
from django.utils.translation import pgettext


def test_quiz_reveal_strings_translated_to_polish():
    with translation.override("pl"):
        for s in ("Show answer", "Correct answer", "Answer view", "Partly correct",
                  "answer shown", "Your answer"):
            assert gettext(s) != s, s
        assert pgettext("answer part verdict", "incorrect") != "incorrect"
        assert pgettext("answer part verdict", "correct") != "correct"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_i18n_quiz_reveal.py -p no:randomly`
Expected: FAIL on "Show answer".

- [ ] **Step 3: Extract, translate, compile**

```bash
uv run python manage.py makemessages -l pl --no-obsolete
```

Fill in each new msgstr (clear any `#, fuzzy` flag AND its pre-filled msgstr on these entries — makemessages pre-fills wrong translations):

| msgid | msgstr |
|---|---|
| Show answer | Pokaż odpowiedź |
| Correct answer | Poprawna odpowiedź |
| Answer view | Widok odpowiedzi |
| Partly correct | Częściowo poprawnie |
| answer shown | pokazano odpowiedź |
| correct (ctx "answer part verdict") | poprawnie |
| incorrect (ctx "answer part verdict") | niepoprawnie |
| Show answer is not available for this question. | Pokazanie odpowiedzi nie jest dostępne dla tego pytania. |
| Show the answer? This ends the question: you won't be able to try again, and you keep the marks you have now (%(earned)s of %(max)s). | Pokazać odpowiedź? To kończy pytanie: nie będzie można spróbować ponownie, a zachowasz obecne punkty (%(earned)s z %(max)s). |

Check nothing new is left fuzzy or empty: `grep -n -B1 -A2 "Show answer\|Answer view\|answer shown\|Partly correct" locale/pl/LC_MESSAGES/django.po | tr -d '\r'`.

```bash
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 4: Help text**

In `docs/help/course-admin/quiz-editors.md`, in the `## {el:fillblank} Fill in the blanks` section's lesson paragraph, DELETE its last sentence ("In a **quiz**, the correct answers are revealed once the question locks." — the switch model replaces it; the `.pl.md` twin: "W **quizie** poprawne odpowiedzi są pokazywane, gdy pytanie zostanie zablokowane."), then, in BOTH files, add a **type-agnostic** quiz paragraph (spec §8: PR 2 relies on it needing no change) directly BEFORE the first `## {el:` question section heading (`grep -n "^## {el:" docs/help/course-admin/quiz-editors*.md | head -1`), with no list of types:

EN:

```markdown
In a **quiz**, an auto-marked question colours each part green or red after every
Check, and a **Show answer** button appears after the first Check. Pressing it (after
a confirmation) ends the question at the marks the student has, and the student can
then switch between **Your answer** and **Correct answer** on the question itself.
The same switch appears when a question locks on its last attempt, and on the results
page after the quiz is finished.
```

PL:

```markdown
W **quizie** pytanie oceniane automatycznie po każdym sprawdzeniu koloruje każdą część
na zielono lub czerwono, a po pierwszym sprawdzeniu pojawia się przycisk **Pokaż
odpowiedź**. Jego naciśnięcie (po potwierdzeniu) kończy pytanie z punktami, które uczeń
ma w tej chwili, a uczeń może wtedy przełączać się między **Twoją odpowiedzią** i
**Poprawną odpowiedzią** w samym pytaniu. Ten sam przełącznik pojawia się, gdy pytanie
zostanie zablokowane po ostatniej próbie, oraz na stronie wyników po zakończeniu quizu.
```

In the `## {el:shorttext} …` and `## {el:shortnumeric} …` sections of both files (EN "Short text" / "Short numeric"-style titles; PL `## {el:shorttext} Krótki tekst` and `## {el:shortnumeric} Liczba` — locate with `grep -n "^## {el:short" docs/help/course-admin/quiz-editors*.md`), add one sentence each:
- EN: "In a **lesson**, a wrong answer turns the box red instead of showing the correct answer; in a **quiz** the answer is available through **Show answer**."
- PL: "Na **lekcji** błędna odpowiedź zmienia kolor pola na czerwony zamiast pokazywać poprawną odpowiedź; w **quizie** odpowiedź jest dostępna przez **Pokaż odpowiedź**."

Flag both Polish texts (UI strings + help paragraphs) for the owner's review in the PR description.

- [ ] **Step 5: Run to verify, plus the help-page and i18n suites**

Run: `uv run pytest tests/test_i18n_quiz_reveal.py tests/test_i18n_questions_2b.py tests/test_help.py tests/test_help_capture_isolation.py -p no:randomly`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale docs/help tests/test_i18n_quiz_reveal.py
git commit -m "i18n+docs(quiz-reveal): Polish strings and author help"
```

---

### Task 12: Branch gate — mutants, screenshots, full sweep

**Files:** none new (fixes only, if the gate finds something).

- [ ] **Step 1: Mutants (each must turn a test RED; revert every mutant BY HAND, never `git checkout`)**

| Mutant | Must fail |
|---|---|
| `key_view`: drop the `marking_mode != AUTO` return | `test_key_view_matrix`, `test_results_render_questions_as_they_ended` (Oslo) |
| `quiz_render_state`: `"key_values": question.key_answer() if locked else None` (bypass `key_view`) | `test_not_marked_and_review_never_show_the_key` |
| `quiz_feedback_context`: drop `or question.SUPPORTS_REVEAL` (old list comes back beside the key copy) | `test_locked_wrong_has_key_copy_and_no_old_list` |
| `key_view`: drop the `not locked` condition (copy before the lock) | `test_key_view_matrix`, `test_check_returns_whole_element_painted_no_key` |
| `neutralise_key_copy`: skip `tag["disabled"] = ""` | `test_names_stripped_controls_disabled`, `test_locked_key_copy_is_nameless_disabled_unique_ids` |
| `quiz_render_state`: `"mark_result": result` (not locked-gated) | `test_quiz_render_state_unlocked_partial_paints_without_key` (asserts `mark_result is None` unlocked) |
| `neutralise_key_copy`: skip `attrs.pop("name")` | `test_names_stripped_controls_disabled`, `test_locked_key_copy_is_nameless_disabled_unique_ids` |
| quiz.js: freeze without the `[data-answer-switch]` skip | `test_show_answer_flow_and_switch` |
| fill-blank template: `_reveal_button.html` include moved above Check | `test_enter_in_a_blank_checks_not_reveals` (as an `expect_request` timeout) |
| COMBINED (defence in depth — two layers guard it): drop `render()`'s `element.pk == feedback_for_pk` guard AND the short-text `{% else %}` include's `verdicts=None` | `test_nojs_lesson_check_leaves_sibling_unpainted` (either change alone is masked by the other) |
| editor.js: freeze without the `[data-answer-switch]` skip | `test_editor_try_it_reveal_switch_survives_freeze` |
| quiz.js: counter guard without `!isReveal` | `test_previewer_reveal_keeps_client_counter` |
| `quiz_answer` reveal branch: `response.attempt_count += 1` AND add `"attempt_count"` to its `update_fields` (otherwise the increment never persists and the mutant is vacuous) | `test_reveal_locks_at_current_marks_without_an_attempt` |
| `_results_question_html`: drop `locked=True` from its `question.render(...)` call | `test_results_short_text_row_every_input_disabled` |
| `render()`: drop the `element.pk == feedback_for_pk` guard | `test_nojs_short_text_check_beside_fillblank_sibling_is_safe` (Task 7) |

Record each mutant's RED test name in the PR description.

- [ ] **Step 2: Screenshots**

Write a throwaway e2e in `tests/test_e2e_zz_shot_tmp.py` (set `DJANGO_ALLOW_ASYNC_UNSAFE`; set `user.theme` to `"light"`/`"dark"` — the cookie is not enough) capturing: a partial Check, the locked state on "Your answer", the locked state on "Correct answer", a short-text key copy, and the results page. Read each PNG; judge dark mode separately. Delete the file.

- [ ] **Step 3: Full sweep (the branch gate)**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run ruff check --no-cache . && uv run ruff format --check --no-cache .
uv run python manage.py makemigrations --check --dry-run
```
Run the non-e2e suite in ~4 chunks (one run at a time — never two concurrent runs), then the e2e suite in chunks with `-m e2e`. Grep each run's summary line; do not trust the exit code alone.

- [ ] **Step 4: Re-sync with master before pushing**

```bash
git fetch origin && git rebase origin/master
ls courses/migrations | grep -E "^0[0-9]+" | sort | tail -2   # 0067 must be the LAST, depending on the one before it
grep -n "dependencies" -A3 courses/migrations/0067_questionresponse_revealed_at.py
uv run python manage.py makemessages -l pl --no-obsolete && uv run python manage.py compilemessages -l pl
```
If master gained its own 0067, regenerate this migration (delete ours, `makemigrations` again) — never hand-edit numbers. Regenerate the `.mo` rather than resolving a binary conflict. Re-run the Task 8 and Task 10 test files after the rebase.

- [ ] **Step 5: Commit any gate fixes, push, open the PR**

PR description: summary, the owner-decision table reference (D1–D13), mutant table, screenshots note, and "Please check the Polish wording" with the table from Task 11.

---

## Self-review notes (for the executor)

- **Spec coverage (PR 1 scope):** §1 → Tasks 5, 6, 7, 8, 9; §2.1 → 1, 6, 7; §2.2 → 1, 4, 6, 7; §2.3 → 6, 9; §2.4 → 6, 8; §2.5 → 3, 5; §2.6 → 1, 3, 8; §3.1 → 6, 9; §3.2 → 8; §3.3 → 3, 8; §3.4 → 6, 8; §3.5 → 3, 8; §3.6 → 2; §4 → 10; §5 → 10; §5a (short text, number) → 7; §8 PR 1 i18n + help → 11. PR 2 / PR 3 items (dnd roots, dnd.js inert UI, grids, choice verdicts, extended response, template deletion) are deliberately absent.
- `data-slot` in the key-copy pass (Task 4) is pinned now so PR 2 inherits it; nothing in PR 1 consumes it.
- If any task's code snippet disagrees with the file as it is at execution time (line drift, a renamed helper), the SPEC wins over the snippet; stop and report if they conflict on behaviour.
