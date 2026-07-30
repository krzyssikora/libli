import pytest

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ShortTextQuestionElement
from courses.quiz import ephemeral_quiz_feedback
from courses.quiz import parse_attempt


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"attempt": "1"}, 1),
        ({"attempt": "3"}, 3),
        ({"attempt": "0"}, 1),
        ({"attempt": "-5"}, 1),
        ({"attempt": ""}, 1),
        ({"attempt": "abc"}, 1),
        ({}, 1),
    ],
)
def test_parse_attempt_floors_to_one(raw, expected):
    assert parse_attempt(raw) == expected


@pytest.mark.django_db
def test_empty_answer_is_validation_and_never_locks():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, result, validation = ephemeral_quiz_feedback(q, "", attempt=2)
    assert validation is True
    assert result is None
    # locked=False on the validation branch is load-bearing: quiz_feedback_context
    # copies .locked into the context BEFORE its `if validation: return ctx` exit,
    # so a locked stand-in would emit data-quiz-locked inside the validation panel.
    assert stand_in.locked is False
    assert stand_in.attempt_count == 1  # attempt - 1: an empty answer consumes none


@pytest.mark.django_db
def test_auto_wrong_with_attempts_left_does_not_lock():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, result, validation = ephemeral_quiz_feedback(q, "London", attempt=1)
    assert validation is False
    assert result is not None and result.correct is False
    assert stand_in.locked is False
    assert stand_in.attempt_count == 1


@pytest.mark.django_db
def test_auto_locks_when_correct():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, result, _ = ephemeral_quiz_feedback(q, "Paris", attempt=1)
    assert result.correct is True
    assert stand_in.locked is True


@pytest.mark.django_db
def test_auto_locks_at_max_attempts():
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    stand_in, _, _ = ephemeral_quiz_feedback(q, "London", attempt=3)
    assert stand_in.locked is True


@pytest.mark.django_db
def test_unlimited_attempts_never_locks_on_wrong_answer():
    """max_attempts=None means unlimited. Without the `is not None` guard this
    raises TypeError: '>=' not supported between 'int' and 'NoneType'."""
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=None
    )
    stand_in, _, _ = ephemeral_quiz_feedback(q, "London", attempt=99)
    assert stand_in.locked is False


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_lock_on_first_submit_without_marking(mode):
    q = ShortTextQuestionElement.objects.create(
        stem="Discuss", accepted="", marking_mode=mode
    )
    stand_in, result, validation = ephemeral_quiz_feedback(q, "anything", attempt=1)
    assert validation is False
    assert result is None  # never marked
    assert stand_in.locked is True


@pytest.mark.django_db
def test_latest_answer_is_normalised_via_answer_to_json():
    """rehydrate() is specified against a STORED latest_answer (answer_to_json
    output), not raw build_answer output. A choice question's raw `set` would
    survive set(...) by accident; this pins the normalisation explicitly."""
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=True)
    a = Choice.objects.create(question=q, text="A", is_correct=True)
    b = Choice.objects.create(question=q, text="B", is_correct=False)
    stand_in, _, _ = ephemeral_quiz_feedback(q, {b.pk, a.pk}, attempt=1)
    assert stand_in.latest_answer == sorted([a.pk, b.pk])
    assert isinstance(stand_in.latest_answer, list)
