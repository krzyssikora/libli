import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _text(unit, parent=None, tab="", body="<p>x</p>"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _mark(client, course, unit, element):
    return client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": element.pk, "unit": unit.pk, "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _paste(client, course, unit, parent, tab, mode="move", token=None):
    return client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": "" if parent is None else parent.pk,
            "tab": tab,
            "mode": mode,
            "unit": unit.pk,
            "unit_token": token if token is not None else unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_a_move_returns_both_fragments_and_relocates_the_element(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'data-scope="preview"' in body
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (dest.pk, slots[0])


def test_a_move_clears_the_mark_and_a_copy_keeps_it(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()

    _mark(client, course, unit, subject)
    unit.refresh_from_db()
    _paste(client, course, unit, dest, slots[0], mode="copy")
    assert "element_clip" in client.session  # one original can seed several slots

    unit.refresh_from_db()
    _paste(client, course, unit, dest, slots[1], mode="move")
    assert "element_clip" not in client.session  # it is now where you put it


def test_a_paste_with_no_mark_is_a_409(client):
    """Reachable in ordinary use: a move clears the mark, so a back-button
    resubmit, a double POST or a second tab holding a stale render all post a
    paste against an empty clipboard."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 409


def test_a_mark_naming_another_unit_is_a_409(client):
    course, unit = _seed(client)
    other_unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    subject = _text(other_unit)
    dest, slots = _tabs(unit)
    other_unit.refresh_from_db()
    _mark(client, course, other_unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 409


def test_a_mark_pointing_at_a_deleted_row_is_a_409(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    Element.objects.filter(pk=subject.pk).delete()
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 409


def test_a_stale_token_is_a_409(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)

    resp = _paste(
        client, course, unit, dest, slots[0], token="2020-01-01T00:00:00+00:00"
    )

    assert resp.status_code == 409


def test_a_half_supplied_scope_is_a_400(client):
    course, unit = _seed(client)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "t1")

    assert resp.status_code == 400


def test_an_unknown_mode_is_a_400(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0], mode="teleport")

    assert resp.status_code == 400


def test_a_refused_placement_is_a_422_with_a_VISIBLE_reason(client):
    """Assert the BODY, not only the status. A 422 whose body is a bare op-error
    div passes a status-only assertion and is still invisible to the author --
    exactly how this error path was got wrong once already."""
    course, unit = _seed(client)
    root, rslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=root, tab=rslots[0])
    unit.refresh_from_db()
    _mark(client, course, unit, root)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, inner, islots[0])

    assert resp.status_code == 422
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'id="editor-error"' in body
    # The mark survives a refusal, or the retry the message invites is impossible.
    assert "element_clip" in client.session


def test_a_vanished_destination_is_a_422_not_a_400(client):
    """ "The destination container was deleted by another author between the render
    and the click" is the concurrent-edit case this design creates; a silent 400 is
    the outcome the error section exists to rule out."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    dest_pk, slot = dest.pk, slots[0]
    Element.objects.filter(pk=dest_pk).delete()
    unit.refresh_from_db()

    resp = client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": dest_pk,
            "tab": slot,
            "mode": "move",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 422
    assert 'id="editor-error"' in resp.content.decode()


def test_a_copy_of_a_damaged_subtree_is_a_422(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    root, rslots = _tabs(unit)
    child = _text(unit, parent=root, tab=rslots[0])
    Element.objects.filter(pk=child.pk).update(object_id=9_999_999)
    unit.refresh_from_db()
    _mark(client, course, unit, root)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0], mode="copy")

    assert resp.status_code == 422
    assert 'id="editor-error"' in resp.content.decode()


def test_the_pasted_elements_ancestors_render_open(client):
    """A move CLEARS the mark, so the very re-render that shows the result has no
    mark pending -- without the ancestor chain every <details> would snap back to
    first-tab-only and the author would watch the row vanish."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[1], mode="move")

    body = resp.content.decode()
    marker = f'data-tab-id="{slots[1]}"'
    tag = body[body.index(marker) : body.index(marker) + 200]
    assert " open" in tag
    assert "data-force-open" in tag


def test_a_move_into_a_spoiler_works_end_to_end(client):
    course, unit = _seed(client)
    sp = Element.objects.create(
        unit=unit, content_object=SpoilerElement.objects.create(body="<p>s</p>")
    )
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, sp, SpoilerElement.SLOT_ID)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (sp.pk, SpoilerElement.SLOT_ID)


def test_an_unmarked_render_never_walks_the_unit(client, monkeypatch):
    """The cost guarantee the whole design rests on: the enumerator runs on EVERY
    editor response while a mark is pending, so `_clip_context` MUST return before
    calling it when nothing is marked. Nothing else pins this -- the enumerator's
    own query-count test measures it in isolation, so a refactor that hoists
    `enumerate_slots(unit)` above the empty return ships green and silently doubles
    the query cost of every add, save, move and delete.

    Mutant: move the `enumerate_slots` call above `_clip_context`'s empty return ->
    RED with the RuntimeError below.
    """
    from courses import builder as builder_mod

    course, unit = _seed(client)
    _tabs(unit)
    _text(unit)

    def _boom(_unit):
        raise RuntimeError("enumerate_slots must not run on an unmarked render")

    monkeypatch.setattr(builder_mod, "enumerate_slots", _boom)

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )

    assert resp.status_code == 200


def test_a_marked_render_does_not_walk_parents_per_slot(
    client, django_assert_max_num_queries
):
    """An order-of-magnitude tripwire on the marked render, and nothing more.

    MEASURED BASELINE: this exact fixture costs 27 queries on master with no
    clipboard feature at all. A correct marked render adds _clip_context's cost --
    the `marked` lookup, enumerate_slots (1 for the joins plus 1 per distinct
    content type) and one GFK for _slot_cap(marked) -- landing around 32. The
    ceiling is set well above that so unrelated query churn elsewhere in the
    editor render does not red it.

    HONEST LIMITATION: dropping `dest_depth=` is NOT detectable here. `pairs`
    hands the same join instances to every call and Django caches a resolved FK on
    the instance, so the element_depth fallback costs about three queries in total
    for this tree -- 32 vs 35, which no sane ceiling separates. That guarantee is
    pinned by the next test instead, which fails outright if the fallback is taken.
    """
    course, unit = _seed(client)
    outer, oslots = _tabs(unit)
    mid, mslots = _tabs(unit, parent=outer, tab=oslots[0])
    _tabs(unit, parent=mid, tab=mslots[0])
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)

    # max, not exact: this catches an order-of-magnitude regression, and an exact
    # count would break on any unrelated query added elsewhere in the editor render.
    with django_assert_max_num_queries(45):
        client.get(
            reverse(
                "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
            )
        )


def test_a_marked_render_never_falls_back_to_walking_parents(client, monkeypatch):
    """The real guard on `dest_depth=`. A query-count bound cannot separate the
    fallback's handful of extra queries from noise, so forbid the call outright:
    _clip_context passes dest_depth for every slot, therefore element_depth must
    never run during a marked render.

    Mutant: drop `dest_depth=dest_depth` from _clip_context's paste_allowed call
    -> RED with the RuntimeError below.
    """
    from courses import builder as builder_mod

    course, unit = _seed(client)
    outer, oslots = _tabs(unit)
    _tabs(unit, parent=outer, tab=oslots[0])
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)

    def _boom(_join):
        raise RuntimeError("paste_allowed must receive dest_depth from the render")

    monkeypatch.setattr(builder_mod, "element_depth", _boom)

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )

    assert resp.status_code == 200


def test_a_paste_into_a_column_works_end_to_end(client):
    """The view-level column case. `column.id` is a different template expression
    from `tab.id`, and the columns branch is the one where a copied condition fails
    silently -- so the endpoint needs its own column row, not just the template
    tests."""
    from courses.models import TwoColumnElement

    course, unit = _seed(client)
    cols_obj = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]}
    )
    cols = Element.objects.create(unit=unit, content_object=cols_obj)
    cols_obj.refresh_from_db()
    third = cols_obj.data["columns"][2]["id"]
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, cols, third)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (cols.pk, third)


def test_a_paste_into_a_callout_works_end_to_end(client):
    """The view-level callout case, mirroring the spoiler one. #214 made this a
    legal destination; nothing else at this level drives it.
    """
    from courses.models import CalloutElement

    course, unit = _seed(client)
    callout = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, callout, CalloutElement.SLOT_ID)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (callout.pk, CalloutElement.SLOT_ID)


def test_a_user_who_cannot_manage_the_course_is_refused(client):
    from tests.factories import make_teacher

    course, unit = _seed(client, username="owner")
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()
    client.logout()
    make_teacher(client, "teacher")

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code in (403, 404)
    subject.refresh_from_db()
    assert subject.parent_id is None
