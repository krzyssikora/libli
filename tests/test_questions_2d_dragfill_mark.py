# tests/test_questions_2d_dragfill_mark.py
import pytest
from django.http import QueryDict

from courses.models import DragBlank, DragFillBlankQuestionElement


def _q():
    q = DragFillBlankQuestionElement.objects.create(stem="￿0￿ ￿1￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    return q


@pytest.mark.django_db
def test_build_answer_returns_raw_slot_list():
    q = _q()
    post = QueryDict(mutable=True)
    post.setlist("slot", ["Paris", "Madrid"])
    assert q.build_answer(post) == ["Paris", "Madrid"]


@pytest.mark.django_db
def test_mark_full_partial_and_reveal():
    q = _q()
    full = q.mark(["Paris", "Madrid"])
    assert full.correct is True and full.fraction == 1.0
    partial = q.mark(["Paris", "Rome"])
    assert partial.correct is False and partial.fraction == 0.5
    assert partial.reveal == (
        {"index": 0, "correct": True, "accepted": "Paris"},
        {"index": 1, "correct": False, "accepted": "Madrid"},
    )


@pytest.mark.django_db
def test_mark_empty_answer_scores_zero():
    q = _q()
    assert q.mark(q.build_answer(QueryDict())).fraction == 0.0
