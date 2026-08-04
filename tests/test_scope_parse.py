import pytest
from django.urls import reverse

from courses import builder
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_parent_and_tab_come_together_or_not_at_all():
    _course, unit = make_course_with_unit()

    assert builder._parse_scope_ref(unit, "", "") == (None, "")
    with pytest.raises(builder.NestingError):
        builder._parse_scope_ref(unit, "5", "")
    with pytest.raises(builder.NestingError):
        builder._parse_scope_ref(unit, "", "t1")


def test_a_non_numeric_parent_ref_is_a_shape_error():
    _course, unit = make_course_with_unit()

    with pytest.raises(builder.NestingError) as exc:
        builder._parse_scope_ref(unit, "abc", "t1")
    assert not isinstance(exc.value, builder.ParentGoneError)


def test_a_vanished_parent_is_parent_gone_not_a_bare_shape_error():
    """ "The destination container was deleted by another author between the render
    and the click" is the concurrent-edit case this design creates; it must reach
    the author as a visible 422, not the invisible 400 a shape error gets."""
    _course, unit = make_course_with_unit()

    with pytest.raises(builder.ParentGoneError):
        builder._parse_scope_ref(unit, "9999999", "t1")


def test_parent_gone_is_a_nesting_error_subclass():
    """element_add and element_save catch NestingError and nothing else. A sibling
    class would turn their 400 into an uncaught 500 the day a parent pk vanishes."""
    assert issubclass(builder.ParentGoneError, builder.NestingError)


def test_resolve_scope_still_reports_a_vanished_parent_through_the_same_path():
    _course, unit = make_course_with_unit()

    with pytest.raises(builder.NestingError):
        builder.resolve_scope(unit, "9999999", "t1", "text")


def test_element_add_still_answers_400_for_a_vanished_parent(client):
    """The regression the subclassing exists to prevent, driven through the real
    endpoint rather than asserted on the class."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )

    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "unit": unit.pk,
            "type": "text",
            "parent": "9999999",
            "tab": "t1",
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 400


def test_a_resolvable_parent_comes_back_as_a_join():
    _course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]

    parent, slot = builder._parse_scope_ref(unit, str(join.pk), tab)

    assert (parent, slot) == (join, tab)


def test_a_parent_in_another_unit_is_parent_gone():
    """The lookup is unit-scoped, which is what makes same-unit -- and
    transitively same-course -- hold."""
    _course, unit = make_course_with_unit()
    _course2, other_unit = make_course_with_unit()
    foreign = Element.objects.create(
        unit=other_unit, content_object=TextElement.objects.create(body="x")
    )

    with pytest.raises(builder.ParentGoneError):
        builder._parse_scope_ref(unit, str(foreign.pk), "t1")
