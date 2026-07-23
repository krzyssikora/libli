import pytest

from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import SpoilerElement
from courses.models import TextElement
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


@pytest.mark.django_db
def test_has_questions_true_for_spoiler_nested_fillblank(
    lesson_unit_node, student_user
):
    # a unit whose ONLY question is a FillBlankQuestionElement nested as a spoiler
    # child -- must be detected unit-wide so question.js/dnd.js get armed.
    from courses.fillblank import SENTINEL

    unit = lesson_unit_node
    sp = SpoilerElement.objects.create(label="Hint")
    join = Element.objects.create(unit=unit, content_object=sp)
    fb = FillBlankQuestionElement.objects.create(stem=f"x = {SENTINEL}0{SENTINEL}")
    Blank.objects.create(question=fb, accepted="0", order=0)
    Element.objects.create(
        unit=unit,
        content_object=fb,
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
        order=0,
    )
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_questions"] is True


@pytest.mark.django_db
def test_has_questions_false_when_no_questions(lesson_unit_node, student_user):
    unit = lesson_unit_node
    el = TextElement.objects.create(body="<p>just text, no questions here</p>")
    Element.objects.create(unit=unit, content_object=el)
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_questions"] is False
