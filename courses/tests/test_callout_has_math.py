import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.views import _element_has_math
from courses.views import build_lesson_context
from courses.views import build_quiz_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_element_has_math_true_for_math_body():
    el = CalloutElement(kind="note", body=r"see \(x^2\) here")
    assert _element_has_math(el) is True


def test_element_has_math_false_for_plain_body():
    el = CalloutElement(kind="note", body="plain prose")
    assert _element_has_math(el) is False


@pytest.fixture
def lesson_unit_node():
    _course, unit = make_course_with_unit()  # returns a LESSON unit
    return unit


@pytest.fixture
def student_user():
    return make_verified_user(username="callout_ctx")


def test_callout_only_lesson_unit_arms_has_math(lesson_unit_node, student_user):
    el = CalloutElement.objects.create(kind="note", body=r"Value \(x^2\)")
    Element.objects.create(unit=lesson_unit_node, content_object=el)
    ctx = build_lesson_context(lesson_unit_node, student_user)
    assert ctx["has_math"] is True


def test_callout_without_math_does_not_arm(lesson_unit_node, student_user):
    el = CalloutElement.objects.create(kind="note", body="<p>no math</p>")
    Element.objects.create(unit=lesson_unit_node, content_object=el)
    ctx = build_lesson_context(lesson_unit_node, student_user)
    assert ctx["has_math"] is False


def test_math_only_callout_in_questionless_quiz_arms_has_math(client, student_user):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    quiz = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    el = CalloutElement.objects.create(kind="note", body=r"Value \(x^2\)")
    Element.objects.create(unit=quiz, content_object=el)
    ctx = build_quiz_context(quiz, student_user)
    assert ctx["has_math"] is True
