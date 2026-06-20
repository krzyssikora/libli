# tests/test_questions_2d_matchpair_mark.py
import pytest

from courses.models import MatchPair, MatchPairQuestionElement


def _q():
    q = MatchPairQuestionElement.objects.create(stem="<p>Match</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    MatchPair.objects.create(question=q, left="Spain", right="Madrid")
    return q


@pytest.mark.django_db
def test_matchpair_mark_and_reveal_carries_left():
    q = _q()
    res = q.mark(["Paris", "Rome"])
    assert res.fraction == 0.5 and res.correct is False
    assert res.reveal == (
        {"index": 0, "correct": True, "accepted": "Paris", "left": "France"},
        {"index": 1, "correct": False, "accepted": "Madrid", "left": "Spain"},
    )


@pytest.mark.django_db
def test_matchpair_left_label_never_matches():
    # "France" is a left label, not a pool token → choosing it is wrong.
    q = _q()
    assert q.mark(["France", "Madrid"]).fraction == 0.5
