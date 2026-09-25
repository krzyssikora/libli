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
    stored = MarkResult(
        correct=True, fraction=1.0, reveal=fresh.reveal, fresh_correct=fresh.correct
    )
    resp = SimpleNamespace(
        locked=True, attempt_count=1, latest_answer=["11", "9"], revealed_at=None
    )
    st = quiz_render_state(q, resp, stored)
    assert st["verdicts"] == [True, True]
    assert st["key_values"] is None  # fully correct: no copy, no switch


def test_blank_state_has_every_key():
    assert set(BLANK_QUIZ_STATE) == {
        "locked",
        "selected_ids",
        "submitted_values",
        "mark_result",
        "verdicts",
        "key_values",
        "can_reveal",
        "reveal_earned",
        "revealed",
    }
