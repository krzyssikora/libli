"""Per-type reveal hooks for the five PR 2 types (spec 2026-09-25 §2.1, §2.2, §2.6)."""

from decimal import Decimal

import pytest

from courses.models import ChoiceGridQuestionElement
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import GridRow
from courses.models import MatchPairQuestionElement
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.quiz import answer_to_json
from courses.quiz import rehydrate
from courses.views import _stored_result
from tests.factories import MediaAssetFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_quiz_unit
from tests.reveal_pr2_kit import KINDS
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import post


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS)
def test_part_verdicts_one_bool_per_part(kind):
    kit = build(kind)
    q = kit.question
    answer = q.build_answer(post(kit.half))
    assert q.part_verdicts(q.mark(answer), answer) == [True, False]
    right = q.build_answer(post(kit.right))
    assert q.part_verdicts(q.mark(right), right) == [True, True]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS)
def test_key_answer_is_build_answer_of_the_right_post(kind):
    # Spec §2.2: the key is in EXACTLY build_answer()'s shape, so the same
    # render / rehydrate path draws both copies.
    kit = build(kind)
    q = kit.question
    assert q.key_answer() == kit.key
    assert q.build_answer(post(kit.right)) == kit.key
    assert rehydrate(q, answer_to_json(q.key_answer()))[1] == kit.key


@pytest.mark.django_db
def test_empty_keys_are_none():
    # P3: no parts at all -> no key copy, no switch.
    assert DragFillBlankQuestionElement.objects.create(stem="x").key_answer() is None
    assert MatchPairQuestionElement.objects.create(stem="x").key_answer() is None
    assert (
        DragToImageQuestionElement.objects.create(
            media=MediaAssetFactory()
        ).key_answer()
        is None
    )
    assert ChoiceGridQuestionElement.objects.create(stem="x").key_answer() is None
    mg = MultiGridQuestionElement.objects.create(stem="x")
    assert mg.key_answer() is None
    MultiGridRow.objects.create(question=mg, order=0, statement="s")
    assert mg.key_answer() is None  # a row, but nothing is correct anywhere


@pytest.mark.django_db
def test_multigrid_empty_row_inside_a_real_key_stays():
    # P3: a "tick nothing" row inside a non-empty key is a real answer.
    kit = build("multigrid")
    q = kit.question
    MultiGridRow.objects.create(question=q, order=2, statement="none apply")
    assert q.key_answer() == kit.key + [[]]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS)
def test_stored_path_verdicts_follow_the_current_key(kind):
    # Spec §2.6: colours come from a FRESH mark() of the stored answer.
    kit = build(kind)
    q = kit.question
    unit = make_quiz_unit()
    el = add_element(unit, q)
    sub = QuizSubmission.objects.create(student=UserFactory(), unit=unit)
    stored = answer_to_json(q.build_answer(post(kit.half)))
    r = QuestionResponse.objects.create(
        submission=sub,
        element=el,
        attempt_count=1,
        latest_answer=stored,
        fraction=Decimal("0.5000"),
    )
    assert q.part_verdicts(_stored_result(q, r), stored) == [True, False]


@pytest.mark.django_db
def test_grid_key_edit_repaints_on_the_stored_path():
    kit = build("choicegrid")
    q = kit.question
    unit = make_quiz_unit()
    el = add_element(unit, q)
    sub = QuizSubmission.objects.create(student=UserFactory(), unit=unit)
    stored = answer_to_json(q.build_answer(post(kit.half)))
    r = QuestionResponse.objects.create(
        submission=sub,
        element=el,
        attempt_count=1,
        latest_answer=stored,
        fraction=Decimal("0.5000"),
    )
    row2 = GridRow.objects.filter(question=q).order_by("order")[1]
    row2.correct_column = q.columns.order_by("order")[0]  # the student's pick
    row2.save()
    assert q.part_verdicts(_stored_result(q, r), stored) == [True, True]
