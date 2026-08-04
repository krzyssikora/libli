import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
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


def test_callout_body_math_is_detected():
    co = CalloutElement.objects.create(kind="example", body=r"<p>\(x^2\)</p>")
    assert _element_has_math(co) is True


def test_transient_callout_with_body_math_is_detected():
    """No join row yet. The `join_row() is None` guard must sit on the CHILDREN walk
    only -- _twocolumn_has_math's top-of-function guard is correct there because a
    two-column element has no text of its own, but a callout does."""
    co = CalloutElement.objects.create(kind="example", body=r"<p>\(a\)</p>")
    assert co.join_row() is None
    assert _element_has_math(co) is True


def test_callout_stored_heading_math_is_detected():
    co = CalloutElement.objects.create(kind="example", heading=r"Wzór \(a^2\)")
    assert _element_has_math(co) is True


def test_math_in_a_table_inside_a_callout_is_detected():
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": r"\(x^2\)"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    assert _element_has_math(co) is True


def test_math_TWO_containers_deep_inside_a_callout_is_detected():
    """callout > tabs > table. Kills a non-recursive walk that special-cases tables."""
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=join, tab_id=CalloutElement.SLOT_ID
    )
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": r"\(y^3\)"}]]}
        ),
        parent=tabs_join,
        tab_id="t000001",
    )
    assert _element_has_math(co) is True


def test_spoiler_with_body_math_AND_children_is_detected():
    """The regression D1 INTRODUCES: before this slice a bodied spoiler with children
    could not render its body, so nothing covered this."""
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s", body=r"<p>\(z^2\)</p>")
    join = add_element(unit, sp)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>no math here</p>"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    assert _element_has_math(sp) is True
