import pytest

from courses.models import QuizSubmission
from courses.rollups import build_outline
from courses.rollups import build_resume
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


def _tree(course, user):
    return build_outline(course, user, drafts="hide")


def _resume(course, user):
    return build_resume(course, user, _tree(course, user))


def _course_with_units(n, **kw):
    """A course with n published lesson units at root level, in order."""
    course = CourseFactory(**kw)
    units = [
        ContentNodeFactory(course=course, kind="unit", unit_type="lesson", order=i)
        for i in range(n)
    ]
    return course, units


@pytest.mark.django_db
def test_no_visible_units_returns_none():
    course = CourseFactory()
    user = make_verified_user(username="s1", email="s1@test.example.com")
    EnrollmentFactory(student=user, course=course)
    assert _resume(course, user) is None


@pytest.mark.django_db
def test_no_rows_at_all_starts_the_course():
    course, units = _course_with_units(3)
    user = make_verified_user(username="s2", email="s2@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert r["state"] == "start"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_history_only_on_an_unpublished_unit_is_next_not_start():
    """Step 5. The student HAS history, so `start` would be a lie -- but every row
    sits on a unit that is no longer visible, so sources A-D see nothing.

    Unpublishing is the ONLY mechanism that reaches step 5: the unit FKs are
    CASCADE, so DELETING a unit destroys its rows and correctly lands on step 6.
    """
    course, units = _course_with_units(3)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", order=9, published=False
    )
    user = make_verified_user(username="s3", email="s3@test.example.com")
    EnrollmentFactory(student=user, course=course)
    UnitProgressFactory(student=user, unit=ghost)
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_history_only_on_an_unpublished_quiz_also_reaches_step_5():
    """Source E's SECOND probe. A student whose only artefact is a QuizSubmission
    must not be told to start the course."""
    course, units = _course_with_units(3)
    ghost = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", order=9, published=False
    )
    user = make_verified_user(username="s4", email="s4@test.example.com")
    EnrollmentFactory(student=user, course=course)
    QuizSubmissionFactory(
        student=user, unit=ghost, status=QuizSubmission.Status.IN_PROGRESS
    )
    r = _resume(course, user)
    assert r["state"] == "next"
    assert r["node"].pk == units[0].pk


@pytest.mark.django_db
def test_returned_node_is_a_contentnode_not_a_leaf_dict():
    """A leaf dict would blow up at {% url %} with NoReverseMatch (<int:node_pk>),
    after quietly rendering no kind chip and sending every link to lesson_unit."""
    from courses.models import ContentNode

    course, units = _course_with_units(2)
    user = make_verified_user(username="s5", email="s5@test.example.com")
    EnrollmentFactory(student=user, course=course)
    r = _resume(course, user)
    assert isinstance(r["node"], ContentNode)
