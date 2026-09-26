# tests/test_questions_2d_quiz_noleak.py
import pytest

from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.reveal_pr2_kit import key


def _quiz(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return user, unit


@pytest.mark.django_db
def test_dragfill_quiz_withholds_reveal_then_reveals_on_last_attempt(client):
    user, unit = _quiz(client)
    q = DragFillBlankQuestionElement.objects.create(
        stem="Cap is ￿0￿", distractors="Rome", marking_mode="A", max_attempts=2
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"

    # Wrong, 1 attempt remaining → withhold: the reveal partial must NOT render.
    body1 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "Correct token:" not in body1
    assert "question__reveal" not in body1
    # PR 2 (spec 2026-09-25 §2.1, §7): replaces the two checks above, which target
    # list markers that no longer exist and so can never fail -- before the lock
    # only booleans reach the page: no key copy at all, and the wrong gap's
    # correct token is never shown selected.
    assert "data-answer-key" not in body1
    assert 'value="Paris" selected' not in body1

    # Wrong on the LAST attempt → reveal: the correct token is now shown.
    body2 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    # PR 2 (spec 2026-09-25 §2.2, §4): replaces `"Correct token:" in body2 and
    # "Paris" in body2` -- the locked question shows the key copy, not the list.
    assert "data-answer-key" in body2
    assert 'value="Paris" selected' in key(body2)


@pytest.mark.django_db
def test_matchpair_quiz_withholds_then_reveals(client):
    user, unit = _quiz(client)
    q = MatchPairQuestionElement.objects.create(
        stem="<p>m</p>", distractors="Rome", marking_mode="A", max_attempts=2
    )
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = add_element(unit, q)
    url = f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    body1 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "Correct match:" not in body1
    # PR 2 (spec 2026-09-25 §2.1, §7): replaces the check above, which targets a
    # list marker that no longer exists and so can never fail -- before the lock
    # only booleans reach the page: no key copy at all, and the wrong gap's
    # correct token is never shown selected.
    assert "data-answer-key" not in body1
    assert 'value="Paris" selected' not in body1
    body2 = client.post(
        url, {"slot": ["Rome"]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    # PR 2 (spec 2026-09-25 §2.2, §4): replaces `"Correct match:" in body2 and
    # "Paris" in body2` -- the locked question shows the key copy, not the list.
    assert "data-answer-key" in body2
    assert 'value="Paris" selected' in key(body2)
