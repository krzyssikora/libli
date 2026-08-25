"""Where the editor draws the PENDING "new element" row, and which element a save
reports back.

Two defects these cover, both on the CREATE path:

1. ``_editor_scope.html`` used to append the pending row at the end of the TOP-LEVEL
   list whatever slot the author picked. ``element_add`` resolves the scope correctly
   and the host form round-trips it, so the element landed in the right slot on save --
   but the author was thrown to the bottom of the unit to fill the form in, and a
   validation error (422) re-rendered it there again.

2. The save response named nothing, so ``editor.js`` -- which anchors its post-save
   scroll on ``form.closest(".el-row[data-element]")`` -- had no anchor at all for a
   row that did not exist yet, and left the author wherever the form had been.

Sibling concern: ``test_editor_open_slots.py`` covers whether the container renders
OPEN. That is orthogonal -- an open <details> containing no pending row is still the
bug, and both are needed for the author to see the form they just opened.
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _callout(unit, *, with_child=True, tail=3):
    """A callout at the top of `unit`, optionally holding one child, followed by a
    tail of top-level elements -- the shape from the bug report ("a callout followed
    by a number of other elements")."""
    callout = CalloutElement.objects.create(body="<p>callout</p>")
    join = Element.objects.create(unit=unit, content_object=callout, order=0)
    if with_child:
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body="<p>inside</p>"),
            parent=join,
            tab_id=CalloutElement.SLOT_ID,
            order=0,
        )
    for i in range(1, tail + 1):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>tail {i}</p>"),
            order=i,
        )
    return join


def _add(client, course, unit, type_key="text", parent=None, tab=None):
    payload = {"type": type_key, "unit": unit.pk}
    if parent is not None:
        payload["parent"] = parent.pk
        payload["tab"] = tab
    return client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        payload,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _pending_row(html):
    """The <li> holding the blank create form, and the soup it came from.

    Keyed on the FORM, not on `.el-row--editing`: an open edit form for an existing
    element carries that class too, so a class lookup would answer with the wrong row
    the moment a test opens both."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.select_one('form[data-op="element-save"]')
    assert form is not None, "no open element form in the fragment"
    assert form.select_one('input[name="element"]')["value"] == "new", (
        "expected the CREATE form (element=new)"
    )
    return soup, form.find_parent("li")


def _callout_slot(soup, callout):
    """The callout's child list -- the <ol> the pending row has to land in."""
    return soup.select_one(
        f'li.el-row[data-element="{callout.pk}"] '
        f".el-row__callout ol.element-list--nested"
    )


def test_add_into_a_callout_draws_the_pending_row_inside_that_callout(client):
    """The author picked the callout's own add-menu; the form has to appear there."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit)

    resp = _add(client, course, unit, parent=callout, tab=CalloutElement.SLOT_ID)

    assert resp.status_code == 200
    soup, row = _pending_row(resp.content.decode())
    nested = _callout_slot(soup, callout)
    assert nested is not None
    assert row.parent is nested, (
        "pending row is not in the callout's child list -- it rendered at "
        f"<{row.parent.name} class={row.parent.get('class')}>"
    )


def test_add_into_a_callout_keeps_the_pending_row_out_of_the_root_list(client):
    """The other half of the same swap: drawing it in the slot is only a fix if it
    STOPS being drawn at the bottom. A template that renders it in both places
    satisfies the test above and still shows the author two forms."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit)

    resp = _add(client, course, unit, parent=callout, tab=CalloutElement.SLOT_ID)

    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    assert len(soup.select('form[data-op="element-save"]')) == 1
    root_list = soup.select_one(".pane-body > ol.element-list")
    top_rows = [li for li in root_list.find_all("li", recursive=False)]
    assert not any("el-row--editing" in (li.get("class") or []) for li in top_rows)


def test_add_into_an_empty_callout_replaces_its_empty_state(client):
    """`{% empty %}` fires on the child queryset, which the pending row is not part
    of -- so without a guard the author reads "This callout is empty." directly above
    the form they just opened inside it."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit, with_child=False)

    resp = _add(client, course, unit, parent=callout, tab=CalloutElement.SLOT_ID)

    soup, row = _pending_row(resp.content.decode())
    slot = _callout_slot(soup, callout)
    assert row.parent is slot
    assert slot.select_one("li.empty-state") is None


def test_add_into_tab_two_draws_the_pending_row_in_tab_two_only(client):
    """The slot key is (parent, tab), not parent alone: a container with more than one
    slot must not sprout the form in every one of them."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=0)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]

    resp = _add(client, course, unit, parent=tabs_join, tab=t2)

    soup, row = _pending_row(resp.content.decode())
    second = soup.select_one(f'details.tabs-rows[data-tab-id="{t2}"] ol.element-list')
    first = soup.select_one(f'details.tabs-rows[data-tab-id="{t1}"] ol.element-list')
    assert row.parent is second
    assert first.select_one('form[data-op="element-save"]') is None


def test_a_top_level_add_still_draws_the_pending_row_in_the_root_list(client):
    """Regression guard: the un-nested add is the common case and must not move."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    _callout(unit)

    resp = _add(client, course, unit)

    soup, row = _pending_row(resp.content.decode())
    assert row.parent is soup.select_one(".pane-body > ol.element-list")
    assert row.parent.find_all("li", recursive=False)[-1] is row


def test_a_nested_creates_validation_error_re_renders_in_the_slot(client):
    """The 422 goes back through the same renderer, carrying parent/tab forward so the
    corrected resubmit keeps its scope. The row it re-renders must keep its scope too,
    or the author is bounced to the bottom to read the error."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit)

    # VideoElement.clean() requires exactly one of url/media; neither is a 422.
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "type": "video",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "parent": callout.pk,
            "tab": CalloutElement.SLOT_ID,
            "el_title": "",
            "url": "",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 422
    soup, row = _pending_row(resp.content.decode())
    assert row.parent is _callout_slot(soup, callout)


def test_a_create_names_the_row_it_made_on_the_editor_pane(client):
    """editor.js anchors its post-save scroll on the op's row. A create has no row to
    read the pk off -- the pending <li> carries no data-element -- so the response has
    to name it, or nothing scrolls and the author is left where the form was."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit)

    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "type": "text",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "parent": callout.pk,
            "tab": CalloutElement.SLOT_ID,
            "el_title": "",
            "body": "<p>new child</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    created = Element.objects.filter(
        parent=callout, tab_id=CalloutElement.SLOT_ID
    ).latest("pk")
    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    pane = soup.select_one('[data-scope="editor"]')
    assert pane.get("data-saved-element") == str(created.pk)


def test_an_update_names_the_row_it_saved(client):
    """Same key on the update path, so editor.js reads ONE attribute rather than
    branching on create-vs-update -- and an update that starts naming nothing would
    silently fall back to the old anchor."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit)
    child = Element.objects.get(parent=callout)

    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "type": "text",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "el_title": "",
            "body": "<p>edited</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    assert soup.select_one('[data-scope="editor"]').get("data-saved-element") == str(
        child.pk
    )


def test_an_op_that_saves_nothing_names_nothing(client):
    """A move/delete/duplicate re-render must leave the attribute blank: a stale pk
    there would make editor.js scroll to whatever the LAST save touched instead of
    falling back to the row the op acted on."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    callout = _callout(unit)
    child = Element.objects.get(parent=callout)

    resp = client.post(
        reverse("courses:manage_element_delete", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    soup = BeautifulSoup(resp.content.decode(), "html.parser")
    assert not soup.select_one('[data-scope="editor"]').get("data-saved-element")
