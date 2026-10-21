"""Every quiz reader enforces the RESOLVED limit (spec §4, §5.5, D13)."""

from types import SimpleNamespace

import pytest

from courses.models import Course
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.quiz import quiz_feedback_context
from courses.views_analytics import _quiz_answer_rows
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

LOCKED = b"data-quiz-locked"


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _setup(client, *, course_kw=None, unit_kw=None):
    user = make_login(client, "stu")
    course = CourseFactory(**(course_kw or {}))
    unit = make_quiz_unit(course=course, **(unit_kw or {}))
    EnrollmentFactory(student=user, course=course)
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    return user, unit, add_element(unit, q)  # q inherits


def _wrong(client, unit, el):
    return client.post(
        _url(unit, el), {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch"
    )


def test_untouched_question_still_gets_one_attempt(client):
    _user, unit, el = _setup(client)
    assert LOCKED in _wrong(client, unit, el).content


def test_inherited_quiz_limit_two(client):
    _user, unit, el = _setup(
        client, unit_kw={"attempts_mode": "limited", "attempts_limit": 2}
    )
    assert LOCKED not in _wrong(client, unit, el).content
    assert LOCKED in _wrong(client, unit, el).content
    assert _wrong(client, unit, el).status_code == 409  # 3rd refused


def test_inherited_unlimited_never_locks(client):
    _user, unit, el = _setup(
        client, course_kw={"attempts_mode": "unlimited", "attempts_limit": None}
    )
    for _ in range(5):
        assert LOCKED not in _wrong(client, unit, el).content


@pytest.mark.parametrize("level", ["course", "unit", "question"])
def test_raising_a_limit_does_not_unlock(client, level):
    """D13, at every level (spec §7.3)."""
    _user, unit, el = _setup(client)
    _wrong(client, unit, el)  # locks at the default 1
    if level == "course":
        Course.objects.filter(pk=unit.course.pk).update(attempts_limit=3)
    elif level == "unit":
        type(unit).objects.filter(pk=unit.pk).update(
            attempts_mode="limited", attempts_limit=3
        )
    else:
        type(el.content_object).objects.filter(pk=el.object_id).update(
            attempts_mode="limited", attempts_limit=3
        )
    assert _wrong(client, unit, el).status_code == 409
    assert QuestionResponse.objects.get(element=el).locked is True


def test_lowered_then_raised_limit_reopens(client):
    """§5.5: blocked only by a LOWERED limit = locked False, key never shown."""
    _user, unit, el = _setup(
        client, course_kw={"attempts_mode": "limited", "attempts_limit": 3}
    )
    _wrong(client, unit, el)
    _wrong(client, unit, el)
    Course.objects.filter(pk=unit.course.pk).update(attempts_limit=1)
    assert _wrong(client, unit, el).status_code == 409  # gate refuses
    r = QuestionResponse.objects.get(element=el)
    assert (r.locked, r.attempt_count) == (False, 2)
    page = client.get(f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/")
    assert b"Paris" not in page.content  # the key was not revealed
    assert b'name="reveal"' in page.content
    Course.objects.filter(pk=unit.course.pk).update(attempts_limit=3)
    assert LOCKED in _wrong(client, unit, el).content  # 3rd attempt, now the last
    assert QuestionResponse.objects.get(element=el).attempt_count == 3


def test_attempts_left_uses_the_resolved_limit():
    unit = make_quiz_unit(attempts_mode="limited", attempts_limit=3)
    q = ShortTextQuestionElement(stem="x", accepted="a", max_marks=1)
    stand_in = SimpleNamespace(locked=False, attempt_count=1, revealed_at=None)
    ctx = quiz_feedback_context(q, stand_in, unit=unit, result=None)
    assert ctx["attempts_left"] == 2


def test_analytics_attempt_max_is_resolved(client):
    user, unit, el = _setup(
        client, unit_kw={"attempts_mode": "limited", "attempts_limit": 4}
    )
    _wrong(client, unit, el)
    _wrong(client, unit, el)
    sub = QuizSubmission.objects.get(student=user, unit=unit)
    (row,) = _quiz_answer_rows(unit, sub)
    assert (row["attempt_count"], row["attempt_max"]) == (2, 4)
