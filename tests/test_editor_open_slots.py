import pytest
from django.urls import reverse

from courses.builder import ancestor_slots
from courses.builder import slot_key
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_slot_key_uses_an_explicit_none_test():
    """`parent_pk or ''` would collapse a pk of 0 onto the top-level key."""
    assert slot_key(None, "") == ":"
    assert slot_key(0, "t1") == "0:t1"
    assert slot_key(12, "t1") == "12:t1"


def test_ancestor_slots_names_every_container_above_a_join():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=tabs_join,
        tab_id=t2,
    )

    assert ancestor_slots(child) == {slot_key(tabs_join.pk, t2)}
    assert ancestor_slots(tabs_join) == set()


def test_duplicating_inside_tab_two_renders_that_tab_open(client):
    """Without the open-set the response shows only tab 1, so the author's new
    copy is born invisible."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=tabs_join,
        tab_id=t2,
    )

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    marker = f'data-tab-id="{t2}"'
    at = body.index(marker)
    tag = body[at : at + 200]
    assert " open" in tag
    assert "data-force-open" in tag


def test_a_column_nested_in_a_tab_opens_its_whole_ancestor_chain(client):
    """The `:132` edit uses `column.id`, not `tab.id`. Copying the tabs line
    verbatim there fails SILENTLY -- nested inside a tabs element, `tab` is still
    in scope (the recursive include at :86 passes no `only`), so the key names
    the enclosing TAB and matches nothing. Without this test that ships green,
    and it also gives ancestor_slots its only two-hop exercise."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    cols = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols_join = Element.objects.create(
        unit=unit, content_object=cols, parent=tabs_join, tab_id=t2
    )
    _c1, c2 = [c["id"] for c in cols.data["columns"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>deep</p>"),
        parent=cols_join,
        tab_id=c2,
    )

    # Two hops: the column slot AND the tab slot above it.
    assert ancestor_slots(child) == {
        slot_key(cols_join.pk, c2),
        slot_key(tabs_join.pk, t2),
    }

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    for marker in (f'data-column-id="{c2}"', f'data-tab-id="{t2}"'):
        tag = body[body.index(marker) : body.index(marker) + 200]
        assert "data-force-open" in tag, marker
        assert " open" in tag, marker


# --- Authoring inside a non-first column (the "the column collapses under me" bug) ---
#
# Every editor op answers with a full re-render of the element pane, so the
# <details> open-state is decided fresh by the server on each one. Without an
# open-set the author's own column snaps shut the instant they click Edit in it,
# and the form they just opened is inside the part that just collapsed.


def _unit_with_a_child_in_column_two(client, username="pa"):
    """A unit holding a two-column element whose SECOND column has one Text child."""
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    cols = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols_join = Element.objects.create(unit=unit, content_object=cols)
    c1, c2 = [c["id"] for c in cols.data["columns"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>x</p>"),
        parent=cols_join,
        tab_id=c2,
    )
    return course, unit, cols_join, c1, c2, child


def _slot_tag(body, marker):
    """The opening <details ...> tag carrying `marker`. Slicing forward from the
    attribute (rather than parsing) matches the sibling tests above and keeps the
    assertion on the TAG, not on anything nested inside the section."""
    at = body.index(marker)
    return body[at : at + 200]


def test_editing_an_element_in_column_two_renders_that_column_open(client):
    """THE REPORTED BUG. element_form re-renders the whole editor pane; with no
    open-set the columns fall back to the template default and the row whose form
    was just opened is sitting inside a collapsed <details>."""
    course, _unit, _join, _c1, c2, child = _unit_with_a_child_in_column_two(client)

    resp = client.get(
        reverse(
            "courses:manage_element_form",
            kwargs={"slug": course.slug, "pk": child.pk},
        )
    )

    assert resp.status_code == 200
    tag = _slot_tag(resp.content.decode(), f'data-column-id="{c2}"')
    assert " open" in tag
    assert "data-force-open" in tag


def test_saving_an_element_in_column_two_keeps_that_column_open(client):
    """The save path re-renders through the same builder. Fixing only the
    edit-open path would reopen the column on the click and collapse it again on
    the very next Save."""
    course, unit, _join, _c1, c2, child = _unit_with_a_child_in_column_two(client)

    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "text",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "body": "<p>edited</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    tag = _slot_tag(resp.content.decode(), f'data-column-id="{c2}"')
    assert " open" in tag
    assert "data-force-open" in tag


def test_adding_into_column_two_renders_that_column_open(client):
    """Same defect on the create half: element_add answers with the pane plus an
    empty form, and the new element is born inside a collapsed column."""
    course, unit, join, _c1, c2, _child = _unit_with_a_child_in_column_two(client)

    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "parent": join.pk, "tab": c2},
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    tag = _slot_tag(resp.content.decode(), f'data-column-id="{c2}"')
    assert " open" in tag
    assert "data-force-open" in tag


def test_a_new_element_saved_into_column_two_lands_in_an_open_column(client):
    """The create path THROUGH SAVE: element_add round-trips parent/tab as hidden
    fields, so element_save must derive the open-set from those rather than from a
    join row that did not exist when the request arrived."""
    course, unit, join, _c1, c2, _child = _unit_with_a_child_in_column_two(client)

    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "text",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "parent": join.pk,
            "tab": c2,
            "body": "<p>fresh</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    tag = _slot_tag(resp.content.decode(), f'data-column-id="{c2}"')
    assert " open" in tag
    assert "data-force-open" in tag


def test_columns_are_collapsed_by_default_so_neither_is_privileged(client):
    """A plain editor load names no open slot: EVERY column renders shut. The old
    `forloop.first` default made column 1 permanently expanded and every other
    column permanently shut, which is the asymmetry the author reported -- and it
    is what makes the force-open above observable rather than a no-op on column 1."""
    course, unit, _join, c1, c2, _child = _unit_with_a_child_in_column_two(client)

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    for cid in (c1, c2):
        tag = _slot_tag(body, f'data-column-id="{cid}"')
        assert " open" not in tag, cid
