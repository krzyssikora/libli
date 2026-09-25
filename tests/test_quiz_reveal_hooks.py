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
        submission=sub,
        element=el,
        attempt_count=1,
        latest_answer="Paris",
        fraction=Decimal("1.0000"),
        locked=True,
    )
    q.accepted = "Lyon"
    q.save()
    stored = _stored_result(q, r)
    assert stored.correct is True  # stored fraction
    assert stored.fresh_correct is False  # the key as it is now


def test_revealed_at_is_a_nullable_datetime():
    field = QuestionResponse._meta.get_field("revealed_at")
    assert field.get_internal_type() == "DateTimeField"
    assert field.null is True
