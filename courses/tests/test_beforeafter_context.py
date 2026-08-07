import pytest

from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TabsElement
from courses.views import build_lesson_context


# Copied from test_fillgate_context.py:21-35 -- these are file-local everywhere.
@pytest.fixture
def lesson_unit_node():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def student_user():
    from tests.factories import make_verified_user

    return make_verified_user(username="student_ba_ctx")


@pytest.fixture
def quiz_unit_node():
    """tests/factories.py:235 already provides make_quiz_unit; the precedent is
    test_callout_has_math.py:58-62."""
    from tests.factories import CourseFactory
    from tests.factories import make_quiz_unit

    return make_quiz_unit(course=CourseFactory())


@pytest.mark.django_db
def test_flag_is_set_for_a_top_level_instance(lesson_unit_node, student_user):
    unit = lesson_unit_node
    Element.objects.create(
        unit=unit, content_object=BeforeAfterElement.objects.create()
    )
    assert build_lesson_context(unit, student_user)["has_before_after"] is True


@pytest.mark.django_db
def test_flag_is_set_for_a_NESTED_instance(lesson_unit_node, student_user):
    """The query must be FLAT -- children keep their own `unit` FK.

    Mutant: scope it to parent__isnull=True -> a before/after inside a tab is
    undetected, no pre-hide is emitted, and the answer flashes on every load.
    """
    unit = lesson_unit_node
    tabs = Element.objects.create(
        unit=unit,
        content_object=TabsElement.objects.create(data=TabsElement.default_data()),
    )
    tab_id = tabs.content_object.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=BeforeAfterElement.objects.create(),
        parent=tabs,
        tab_id=tab_id,
    )
    assert build_lesson_context(unit, student_user)["has_before_after"] is True


@pytest.mark.django_db
def test_flag_is_false_without_the_element(lesson_unit_node, student_user):
    # Positional: the signature is build_lesson_context(node, user) -- views.py:314.
    # `unit=` raises TypeError, failing for the wrong reason both before and after
    # the implementation lands.
    ctx = build_lesson_context(lesson_unit_node, student_user)
    assert ctx["has_before_after"] is False


@pytest.mark.django_db
def test_flag_is_set_for_a_quiz_unit(quiz_unit_node, student_user):
    """Mutant: omit it from build_quiz_context -> the answer side is permanently
    visible in every quiz unit.
    """
    from courses.views import build_quiz_context

    Element.objects.create(
        unit=quiz_unit_node, content_object=BeforeAfterElement.objects.create()
    )
    assert build_quiz_context(quiz_unit_node, student_user)["has_before_after"] is True


@pytest.mark.django_db
def test_flag_is_set_for_a_NESTED_instance_in_a_quiz_unit(quiz_unit_node, student_user):
    """The quiz query must be FLAT too -- children keep their own `unit` FK.

    Mutant: scope it to parent__isnull=True -> a before/after inside a tab in a
    quiz unit is undetected, no pre-hide is emitted, and the answer is exposed
    on every load.
    """
    from courses.views import build_quiz_context

    unit = quiz_unit_node
    tabs = Element.objects.create(
        unit=unit,
        content_object=TabsElement.objects.create(data=TabsElement.default_data()),
    )
    tab_id = tabs.content_object.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=BeforeAfterElement.objects.create(),
        parent=tabs,
        tab_id=tab_id,
    )
    assert build_quiz_context(unit, student_user)["has_before_after"] is True
