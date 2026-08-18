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
    # No `numbered` key was posted: an unchecked checkbox transmits nothing, so
    # this is indistinguishable from a deliberate untick. Pin the deliberate
    # False, don't let it drift silently.
    assert el.content_object.numbered is False


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


def test_edit_form_offers_the_task_kind(client):
    # Fixture kind is deliberately NOT task: a task-kind callout would render
    # <option value="task" selected> and fail this exact-string assert.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el = CalloutElement.objects.create(kind="example", heading="", body="")
    join = Element.objects.create(unit=unit, content_object=el)
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": join.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    # Exact string: two separate `'value="task"' in html` / `'Task' in html`
    # asserts would both pass with the label wrong.
    assert '<option value="task">Task</option>' in resp.content.decode()


def test_save_round_trips_the_task_kind(client):
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
            "kind": "task",
            "heading": "",
            "body": "<p>x</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    # Status first: without the enum member the form rejects the POST, nothing is
    # saved, and the .get() below raises DoesNotExist instead of asserting.
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert el.content_object.kind == "task"
    # No `numbered` key was posted: an unchecked checkbox transmits nothing, so
    # this is indistinguishable from a deliberate untick. `task` is the
    # highest-volume kind (177 rows) and defaults to numbered -- the strongest
    # evidence in the repo that this outcome must be deliberate, not silent.
    assert el.content_object.numbered is False
