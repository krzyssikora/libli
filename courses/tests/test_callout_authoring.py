import pytest
from django.urls import reverse

from courses import builder
from courses.models import CalloutElement
from courses.models import Element
from courses.models import TabsElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_form_renders_callout_edit_partial(client):
    # POST the add form for a callout — proves _edit_callout.html exists (else 500).
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "callout", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="kind"' in html
    assert 'name="heading"' in html
    assert 'name="body"' in html


def test_callout_is_nestable_via_resolve_scope():
    # Prove nesting is actually allowed through the real resolve_scope() path
    # (form key "callout"), mirroring test_reveal_gate_form_builder.py.
    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    parent_join, resolved_tab = builder.resolve_scope(
        unit, str(join.pk), tab_id, "callout"
    )
    assert parent_join == join
    assert resolved_tab == tab_id


def test_save_round_trips_kind_heading_body(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "callout",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "kind": "warning",
            "heading": "Careful",
            "body": "<p>x</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, CalloutElement)
    assert el.content_object.kind == "warning"
    assert el.content_object.heading == "Careful"


def test_edit_form_preselects_stored_kind(client):
    # Editing a saved WARNING callout must mark <option value="warning" ... selected>.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el = CalloutElement.objects.create(kind="warning", heading="", body="")
    join = Element.objects.create(unit=unit, content_object=el)
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": join.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    # the warning option must be the selected one, not example (the first option)
    assert 'value="warning" selected' in html
