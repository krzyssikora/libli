"""The four context sites and the render barrier. There is no single choke point
that covers all four (spec R1), so each gets its own test."""

import pytest
from django.urls import reverse

from courses.models import SINGLE_SLOT_ID
from courses.models import CalloutElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import TabsElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

NUMBER_SPAN = '<span class="callout__number">2</span>'


def _numbered_callout(unit, kind="example", parent=None, tab_id="", order=0):
    el = CalloutElement.objects.create(kind=kind, numbered=True, body="")
    return Element.objects.create(
        unit=unit, content_object=el, parent=parent, tab_id=tab_id, order=order
    )


def _unit_with_a_nested_callout(unit):
    """Top-level callout (number 1) + a callout inside tabs (number 2). The NESTED
    one is what proves the map crossed the render barrier."""
    _numbered_callout(unit, order=0)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000000", "label": "One"}]}
    )
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=1)
    return _numbered_callout(unit, "task", parent=tabs_join, tab_id="t000000")


@pytest.fixture
def student_user():
    """Both context builders REQUIRE a real user; neither tolerates None.
    build_lesson_context reaches `elif user.is_authenticated` (courses/views.py:513)
    whenever the viewer is not enrolled -- and is_enrolled(None, course) is a plain
    .filter(student=None).exists(), so that branch always runs and None.is_authenticated
    raises. build_quiz_context crashes further down instead, via
    unit_edit_context -> can_manage_course -> `course.owner_id == user.id`
    (courses/access.py:41). Matches the fixture in
    courses/tests/test_callout_has_math.py.
    """
    from tests.factories import make_verified_user

    return make_verified_user(username="callout_numbering_ctx")


def test_lesson_context_carries_the_map(student_user):
    from courses.views import build_lesson_context

    _course, unit = make_course_with_unit()
    _unit_with_a_nested_callout(unit)
    ctx = build_lesson_context(unit, student_user)
    assert len(ctx["callout_numbers"]) == 2


def test_quiz_context_carries_the_map(student_user):
    from courses.views import build_quiz_context

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type=ContentNode.UnitType.QUIZ
    )
    _unit_with_a_nested_callout(unit)
    ctx = build_quiz_context(unit, student_user)
    assert len(ctx["callout_numbers"]) == 2


def test_the_student_lesson_page_numbers_a_NESTED_callout(client):
    """The barrier end-to-end. Mutant: drop `**(page or {})` from TabsElement.render
    -> the top-level callout keeps its number and this one loses it."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_a_nested_callout(unit)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert resp.status_code == 200
    assert NUMBER_SPAN in resp.content.decode()


def test_the_editor_full_page_load_numbers_a_nested_callout(client):
    """_editor_page. Mutant: wire only _render_editor_fragments -> the first load
    shows no numbers while every later swap does."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_a_nested_callout(unit)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert NUMBER_SPAN in resp.content.decode()


def test_an_editor_fragment_swap_numbers_a_nested_callout(client):
    """_render_editor_fragments. Mutant: wire only _editor_page -> the first load
    looks perfect and every add/save/move/paste silently drops the numbers."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_a_nested_callout(unit)
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert NUMBER_SPAN in resp.content.decode()


def test_a_callout_nested_in_a_callout_is_numbered_on_the_page(client):
    """The map must survive TWO barrier crossings."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    outer = _numbered_callout(unit, order=0)
    _numbered_callout(unit, "task", parent=outer, tab_id=SINGLE_SLOT_ID)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert NUMBER_SPAN in resp.content.decode()
