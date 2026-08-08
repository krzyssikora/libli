import pytest

from courses.models import BeforeAfterElement
from courses.models import Element


@pytest.fixture
def lesson_unit_node():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def student_user():
    from tests.factories import make_verified_user

    return make_verified_user(username="student_ba_math")


@pytest.mark.django_db
def test_has_math_finds_math_nested_in_a_panel(lesson_unit_node, student_user):
    """Mutant: make _before_after_has_math non-recursive -> KaTeX never loads and
    the lesson ships raw LaTeX.
    """
    from courses.models import MathElement
    from courses.views import build_lesson_context

    join = Element.objects.create(
        unit=lesson_unit_node, content_object=BeforeAfterElement.objects.create()
    )
    Element.objects.create(
        unit=lesson_unit_node,
        content_object=MathElement.objects.create(latex="x^2"),
        parent=join,
        tab_id=BeforeAfterElement.AFTER_SLOT_ID,
    )
    assert build_lesson_context(lesson_unit_node, student_user)["has_math"] is True
