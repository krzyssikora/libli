import pytest

from courses.models import Element
from courses.models import SpoilerElement
from courses.views import build_lesson_context


@pytest.fixture
def lesson_unit_node():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def student_user():
    from tests.factories import make_verified_user

    return make_verified_user(username="spoiler_ctx")


@pytest.mark.django_db
def test_spoiler_only_unit_arms_has_math(lesson_unit_node, student_user):
    unit = lesson_unit_node
    el = SpoilerElement.objects.create(label="Show", body="Value \\(x^2\\)")
    Element.objects.create(unit=unit, content_object=el)
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


@pytest.mark.django_db
def test_spoiler_without_math_does_not_arm(lesson_unit_node, student_user):
    unit = lesson_unit_node
    el = SpoilerElement.objects.create(label="Show", body="<p>no math here</p>")
    Element.objects.create(unit=unit, content_object=el)
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is False
