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


def _save_callout(client, course, unit, element="new", **fields):
    """The FULL element_save shape. A missing `el_title` blanks the join title, and
    `unit_token` is the concurrency token, so the unit is re-read first: creating
    rows bumps `updated`."""
    unit.refresh_from_db()
    data = {
        "type": "callout",
        "element": str(element),
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "",
        "heading": "",
        "body": "<p>x</p>",
    }
    data.update(fields)
    return client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _edit_form_html(client, course, join):
    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": join.pk},
        ),
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="kind"' in html  # the callout form really rendered
    return html


def _saved(kind, numbered, unit):
    el = CalloutElement.objects.create(kind=kind, numbered=numbered, body="")
    return el, Element.objects.create(unit=unit, content_object=el)


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


def test_edit_form_offers_the_summary_kind(client):
    """T7. Fixture kind is NOT summary, or the option would carry `selected`."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("example", True, unit)
    html = _edit_form_html(client, course, join)
    assert '<option value="summary">Key facts</option>' in html


def test_save_round_trips_the_summary_kind(client):
    """T7. A ticked box on a NEW summary is ignored: save() forces False."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = _save_callout(
        client, course, unit, kind="summary", heading="Funkcja liniowa", numbered="on"
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit).content_object
    assert el.kind == "summary"
    assert el.heading == "Funkcja liniowa"
    assert el.numbered is False


def test_the_summary_edit_form_has_no_numbered_checkbox(client):
    """T7 / D5. Mutant: remove the {% if %} around the checkbox."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("summary", False, unit)
    assert 'name="numbered"' not in _edit_form_html(client, course, join)


def test_the_example_edit_form_keeps_the_numbered_checkbox(client):
    """T7, the present half. Mutant: invert the {% if %}."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("example", True, unit)
    assert 'name="numbered"' in _edit_form_html(client, course, join)


def test_switching_a_ticked_example_to_summary_unnumbers_it_and_hides_the_box(
    client,
):
    """Review Focus 1. No JS hides the box when the select changes, so the POST
    carries numbered=on for a summary. Mutant: remove the save() force -> True."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("example", True, unit)
    resp = _save_callout(
        client, course, unit, element=join.pk, kind="summary", numbered="on"
    )
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False
    assert 'name="numbered"' not in _edit_form_html(client, course, join)


def test_leaving_summary_for_example_restores_numbered(client):
    """T7b. The summary form rendered no checkbox, so the POST has no key.
    Mutant: remove the clean() restore -> False."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("summary", False, unit)
    resp = _save_callout(client, course, unit, element=join.pk, kind="example")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.kind == "example"
    assert el.numbered is True


def test_leaving_summary_for_note_restores_unnumbered(client):
    """T7b. Mutant: restore a flat True instead of KIND_DEFAULT_NUMBERED."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("summary", False, unit)
    resp = _save_callout(client, course, unit, element=join.pk, kind="note")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.kind == "note"
    assert el.numbered is False


def test_a_sent_numbered_value_is_not_overridden_when_leaving_summary(client):
    """T7b. CheckboxInput reads "false" as False. Mutant: drop the
    `not in self.data` check -> True."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("summary", False, unit)
    resp = _save_callout(
        client, course, unit, element=join.pk, kind="example", numbered="false"
    )
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.numbered is False


def test_an_unticked_example_stays_unnumbered(client):
    """T7b. The restore applies ONLY when leaving summary. Mutant: apply it
    unconditionally -> True."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el, join = _saved("example", True, unit)
    resp = _save_callout(client, course, unit, element=join.pk, kind="example")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.numbered is False


def test_a_422_after_asking_for_summary_still_shows_the_checkbox(client):
    """T7b. kind stays VALID and the heading is over max_length=120, so the form
    fails while construct_instance() still copies kind="summary" onto
    form.instance. Mutant: key the {% if %} on form.instance.kind -> hidden."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _el, join = _saved("example", True, unit)
    resp = _save_callout(
        client, course, unit, element=join.pk, kind="summary", heading="z" * 121
    )
    assert resp.status_code == 422
    assert 'name="numbered"' in resp.content.decode()


def test_a_new_callout_still_renders_and_saves_the_checkbox(client):
    """T7b, the create path (no instance): original_kind is the default
    "example", so the box renders ticked and a ticked POST saves True."""
    from django.template.loader import render_to_string

    from courses.element_forms import CalloutElementForm

    body = render_to_string(
        "courses/manage/editor/_edit_callout.html", {"form": CalloutElementForm()}
    )
    assert 'name="numbered" checked' in body

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = _save_callout(client, course, unit, kind="example", numbered="on")
    assert resp.status_code == 200
    assert Element.objects.get(unit=unit).content_object.numbered is True
