# tests/test_questions_2d_quiz_routing.py
import pytest

from courses import quiz
from courses.models import DragFillBlankQuestionElement
from courses.models import MatchPairQuestionElement


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model", [DragFillBlankQuestionElement, MatchPairQuestionElement]
)
def test_round_trip_keeps_token_list_on_default_branch(model):
    q = model.objects.create(stem="x", distractors="")
    stored = ["Paris", "", "Madrid"]
    # write path: list passes through unchanged
    assert quiz.answer_to_json(stored) == stored
    # read paths: token-text list returns untouched, not a choice set
    selected, submitted = quiz.rehydrate(q, stored)
    assert selected == set() and submitted == stored
    assert quiz.answer_from_json(q, stored) == stored
