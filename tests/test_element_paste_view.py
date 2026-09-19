import re

import psycopg
import pytest
from django.db import OperationalError
from django.urls import reverse

from courses.builder import slot_key
from courses.models import CalloutElement
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.views_manage import copy_units_open_path
from courses.views_manage import copy_units_tree
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa
from tests.factories import make_quiz_unit

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


def _paste(client, course, unit, parent, tab, mode="move", token=None, *, element):
    """`element` is REQUIRED and passed by the caller -- never read from the
    session -- so a test's pre-assertion compares two independently sourced
    values. Pass element=None to post no `element` field at all."""
    data = {
        "ctx": "editor",
        "parent": "" if parent is None else parent.pk,
        "tab": tab,
        "mode": mode,
        "unit": unit.pk,
        "unit_token": token if token is not None else unit.updated.isoformat(),
    }
    if element is not None:
        data["element"] = element if isinstance(element, (int, str)) else element.pk
    return client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _paste_before(client, course, unit, anchor, mode="move", token=None, *, element):
    """The before-path posts NO parent/tab: the slot is derived from the anchor."""
    data = {
        "ctx": "editor",
        "mode": mode,
        "before": anchor if isinstance(anchor, int) else anchor.pk,
        "unit": unit.pk,
        "unit_token": token if token is not None else unit.updated.isoformat(),
    }
    if element is not None:
        data["element"] = element if isinstance(element, (int, str)) else element.pk
    return client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _assert_posts_the_mark(client, element):
    """Pre-assertion for every 409 test: the `element` ARGUMENT the caller hands the
    helper equals the session mark. It does not inspect the POST data -- that the
    helpers really transmit the field is pinned by
    test_a_paste_before_a_sibling_reorders_within_the_slot_and_clears_the_mark,
    which 409s instead of reordering if `element` is not posted."""
    assert client.session["element_clip"]["element"] == element.pk


def test_a_move_returns_both_fragments_and_relocates_the_element(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0], element=subject)

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
    _paste(client, course, unit, dest, slots[0], mode="copy", element=subject)
    assert "element_clip" in client.session  # one original can seed several slots

    unit.refresh_from_db()
    _paste(client, course, unit, dest, slots[1], mode="move", element=subject)
    assert "element_clip" not in client.session  # it is now where you put it


def test_a_paste_with_no_mark_is_a_409(client):
    """Reachable in ordinary use: a move clears the mark, so a back-button
    resubmit, a double POST or a second tab holding a stale render all post a
    paste against an empty clipboard."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)

    resp = _paste(client, course, unit, dest, slots[0], element=None)

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
    _assert_posts_the_mark(client, subject)

    resp = _paste(client, course, unit, dest, slots[0], element=subject)

    assert resp.status_code == 409
    assert client.session["element_clip"]["element"] == subject.pk  # kept


def test_a_mark_pointing_at_a_deleted_row_is_a_409(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    Element.objects.filter(pk=subject.pk).delete()
    unit.refresh_from_db()
    _assert_posts_the_mark(client, subject)

    resp = _paste(client, course, unit, dest, slots[0], element=subject)

    assert resp.status_code == 409
    assert "element_clip" not in client.session


def test_a_stale_token_is_a_409(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    _assert_posts_the_mark(client, subject)

    resp = _paste(
        client,
        course,
        unit,
        dest,
        slots[0],
        token="2020-01-01T00:00:00+00:00",
        element=subject,
    )

    assert resp.status_code == 409


def test_a_half_supplied_scope_is_a_400(client):
    course, unit = _seed(client)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "t1", element=subject)

    assert resp.status_code == 400


def test_an_unknown_mode_is_a_400(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(
        client, course, unit, dest, slots[0], mode="teleport", element=subject
    )

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

    resp = _paste(client, course, unit, inner, islots[0], element=root)

    assert resp.status_code == 422
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'id="editor-error"' in body
    # The MESSAGE, not just the marker: mapping into_own_subtree to any other
    # reason's string (e.g. unknown_slot's) would still satisfy an id-only check.
    assert "An element cannot be placed inside itself." in body
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
            "element": subject.pk,
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

    resp = _paste(client, course, unit, dest, slots[0], mode="copy", element=root)

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

    resp = _paste(client, course, unit, dest, slots[1], mode="move", element=subject)

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

    resp = _paste(client, course, unit, sp, SpoilerElement.SLOT_ID, element=subject)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (sp.pk, SpoilerElement.SLOT_ID)


def test_the_clip_context_keys_reach_both_render_paths(client):
    """The headline guarantee this task exists to deliver: BOTH context builders
    must carry the fourteen clip keys, or a fragment swap silently drops the
    feature the very next time the page renders -- exactly the trap
    `_clip_context`'s own docstring and the `max_nest_depth` precedent comment both
    warn about. Nothing else in this suite would catch their absence: Django
    templates ignore a missing context variable, so every status/body/DB
    assertion elsewhere would stay green with the keys gone from either builder.

    Mutant: delete the `**_clip_context(request, unit)` splat from EITHER
    _render_editor_fragments or _editor_page -> RED, independently, both ways.
    """
    course, unit = _seed(client)
    # Under a part, so copy_units_open has a real value to carry: a builder that
    # dropped the key would render every container collapsed after each swap
    # (undefined template variables are falsy) and nothing else would notice.
    part = _unit(course, "P", kind="part", unit_type="")
    unit.parent = part
    unit.save()
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    expected_key = slot_key(dest.pk, slots[0])

    # The fragment-POST path (_render_editor_fragments): the clip POST itself is
    # the cheapest way to reach it with a mark already pending.
    resp = _mark(client, course, unit, subject)
    assert resp.status_code == 200
    assert resp.context["clip_active"] is True
    assert resp.context["clip_element_pk"] == str(subject.pk)  # a STRING, not an int
    assert expected_key in resp.context["copy_slots"]
    assert resp.context["clip_mode"] == "move"
    assert resp.context["copy_units_open"] == {part.pk}

    # The full-page GET path (_editor_page).
    unit.refresh_from_db()
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert resp.context["clip_active"] is True
    assert resp.context["clip_element_pk"] == str(subject.pk)
    assert expected_key in resp.context["copy_slots"]
    assert resp.context["clip_mode"] == "move"
    assert resp.context["copy_units_open"] == {part.pk}


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
    # Guards against a vacuous pass: if the clip POST regressed to a 409, no mark
    # would be set, _clip_context would take its empty-return path, and this test
    # would pass with NO walk having happened at all.
    assert _mark(client, course, unit, subject).status_code == 200

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
    # Guards against a vacuous pass: if the clip POST regressed to a 409, no mark
    # would be set, _clip_context would take its empty-return path, and this test
    # would pass with element_depth never having had the chance to run.
    assert _mark(client, course, unit, subject).status_code == 200

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

    resp = _paste(client, course, unit, cols, third, element=subject)

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

    resp = _paste(
        client, course, unit, callout, CalloutElement.SLOT_ID, element=subject
    )

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

    resp = _paste(client, course, unit, dest, slots[0], element=subject)

    assert resp.status_code in (403, 404)
    subject.refresh_from_db()
    assert subject.parent_id is None


# ── paste BEFORE a chosen element, through the view ────────────────────────


def _order(unit, parent=None, tab=""):
    return list(
        Element.objects.filter(unit=unit, parent=parent, tab_id=tab)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )


def test_a_paste_before_a_sibling_reorders_within_the_slot_and_clears_the_mark(client):
    """The whole point, end to end: an element added at the BOTTOM reaches the top
    of a 4-element group in one request instead of three arrow round trips."""
    course, unit = _seed(client)
    first = _text(unit, body="<p>1</p>")
    second = _text(unit, body="<p>2</p>")
    subject = _text(unit, body="<p>s</p>")
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste_before(client, course, unit, first, element=subject)

    assert resp.status_code == 200
    assert _order(unit) == [subject.pk, first.pk, second.pk]
    assert "element_clip" not in client.session


def test_a_paste_before_derives_the_slot_from_the_anchor(client):
    """No parent/tab is posted at all, so a view that kept reading them would land
    the element at top level and leave this RED."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    anchor = _text(unit, parent=dest, tab=slots[1], body="<p>a</p>")
    subject = _text(unit, body="<p>s</p>")
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste_before(client, course, unit, anchor, element=subject)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (dest.pk, slots[1])
    assert _order(unit, dest, slots[1]) == [subject.pk, anchor.pk]


def test_a_paste_before_a_vanished_anchor_is_a_422_with_a_visible_reason(client):
    """A co-author deleting the anchor between the mark and the click is the race
    this path creates. Assert the BODY: a bare status leaves the author staring at
    an unchanged pane with no idea why."""
    course, unit = _seed(client)
    subject = _text(unit)
    doomed = _text(unit)
    doomed_pk = doomed.pk
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    Element.objects.filter(pk=doomed_pk).delete()
    unit.refresh_from_db()

    resp = _paste_before(client, course, unit, doomed_pk, element=subject)

    assert resp.status_code == 422
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert "removed while you were working" in body


def test_a_paste_before_with_a_stale_token_is_a_409(client):
    course, unit = _seed(client)
    anchor = _text(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    _assert_posts_the_mark(client, subject)

    resp = _paste_before(
        client,
        course,
        unit,
        anchor,
        token="2020-01-01T00:00:00+00:00",
        element=subject,
    )

    assert resp.status_code == 409
    assert _order(unit) == [anchor.pk, subject.pk]


def test_a_paste_before_itself_is_a_400(client):
    """No UI produces it -- the marked row renders no button -- so it is a shape
    error, not a refusal the author needs explained."""
    course, unit = _seed(client)
    _text(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste_before(client, course, unit, subject, element=subject)

    assert resp.status_code == 400


def _unit(course, title, unit_type="lesson", parent=None, kind="unit"):
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title
    )


def _editor_get(client, course, unit):
    unit.refresh_from_db()
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )


def test_copy_units_tree_keeps_units_at_any_depth_and_drops_empty_containers():
    course = CourseFactory()
    root_unit = _unit(course, "RootUnit")
    part = _unit(course, "Part", kind="part", unit_type="")
    chapter = _unit(course, "Chapter", kind="chapter", unit_type="", parent=part)
    section = _unit(course, "Section", kind="section", unit_type="", parent=chapter)
    deep = _unit(course, "Deep", parent=section)
    empty_section = _unit(
        course, "EmptySection", kind="section", unit_type="", parent=chapter
    )

    pruned, top, available = copy_units_tree(course)

    assert top == [root_unit, part] or top == [part, root_unit]
    assert pruned[chapter.pk] == [section]  # the unit-less section is dropped
    assert empty_section not in pruned.get(chapter.pk, [])
    assert pruned[section.pk] == [deep]
    assert available is True


def test_copy_units_tree_reports_a_one_unit_course_as_unavailable():
    course = CourseFactory()
    _unit(course, "Only")

    _pruned, _top, available = copy_units_tree(course)

    assert available is False


def test_copy_units_tree_reports_two_units_as_available():
    course = CourseFactory()
    _unit(course, "One")
    _unit(course, "Two")

    assert copy_units_tree(course)[2] is True


def test_a_mark_in_another_unit_of_the_course_offers_copy_only(client):
    """The cross-unit branch. Mutant: fill move_slots in the cross-unit branch
    (e.g. `move_slots = set(copy_slots)`) -> RED."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    box, slots = _tabs(y)
    _mark(client, course, x, subject)

    resp = _editor_get(client, course, y)

    ctx = resp.context
    assert ctx["clip_active"] is True
    assert ctx["clip_mode"] == "copy"
    assert ctx["clip_source_unit"] == x
    assert ctx["clip_element_pk"] == str(subject.pk)
    assert ctx["move_slots"] == set()
    assert slot_key(box.pk, slots[0]) in ctx["copy_slots"]
    assert ctx["before_slots"] == ctx["copy_slots"]
    assert ctx["clip_noop_pk"] == ""
    assert ctx["clip_nothing_fits"] is False
    assert ctx["copy_units_available"] is True


def test_the_source_unit_keeps_move_mode_and_no_source_link(client):
    course, x = _seed(client)
    _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    ctx = _editor_get(client, course, x).context

    assert ctx["clip_mode"] == "move"
    assert ctx["clip_source_unit"] is None


def test_a_mark_from_another_course_is_ignored_and_kept(client):
    """D8. Mutant: pop the session mark on the foreign-course path -> RED."""
    course, unit = _seed(client)
    other_course = CourseFactory(owner=course.owner)
    foreign_unit = _unit(other_course, "F")
    foreign = _text(foreign_unit)
    _mark(client, other_course, foreign_unit, foreign)
    assert client.session["element_clip"]["element"] == foreign.pk

    ctx = _editor_get(client, course, unit).context

    assert ctx["clip_active"] is False
    assert client.session["element_clip"]["element"] == foreign.pk


def test_a_mark_whose_source_unit_was_deleted_is_cleared(client):
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)
    x.delete()

    ctx = _editor_get(client, course, y).context

    assert ctx["clip_active"] is False
    assert "element_clip" not in client.session


def test_a_non_numeric_session_unit_is_cleared(client):
    course, unit = _seed(client)
    session = client.session
    session["element_clip"] = {"unit": "abc", "element": 1}
    session.save()

    ctx = _editor_get(client, course, unit).context

    assert ctx["clip_active"] is False
    assert "element_clip" not in client.session


def test_a_partial_session_mark_is_cleared_as_dead(client):
    """`none` is exactly `not clip`; {"unit": X} takes lookup step 1 and misses."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    session = client.session
    session["element_clip"] = {"unit": x.pk}
    session.save()

    ctx = _editor_get(client, course, y).context

    assert ctx["clip_active"] is False
    assert "element_clip" not in client.session


def test_a_question_callout_marked_for_a_quiz_fits_nowhere(client):
    """Mutant: never set clip_nothing_fits (always False) -> RED."""
    course, x = _seed(client)
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    box = Element.objects.create(
        unit=x, content_object=CalloutElement.objects.create(kind="example")
    )
    Element.objects.create(
        unit=x,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    _mark(client, course, x, box)

    ctx = _editor_get(client, course, quiz).context

    assert ctx["copy_slots"] == set()
    assert ctx["clip_nothing_fits"] is True


def test_the_copy_list_is_built_only_while_a_mark_is_active(client, monkeypatch):
    """0 calls unmarked, EXACTLY 1 marked (so a never-built tree also goes red).

    Mutant: build copy_units_tree unconditionally in _clip_context -> RED (1 call
    on the unmarked render)."""
    from courses import views_manage

    course, unit = _seed(client)
    _unit(course, "Y")
    subject = _text(unit)
    calls = []
    real = views_manage._children_map

    def _counting(c):
        calls.append(c)
        return real(c)

    monkeypatch.setattr(views_manage, "_children_map", _counting)

    _editor_get(client, course, unit)
    assert calls == []

    _mark(client, course, unit, subject)
    calls.clear()
    _editor_get(client, course, unit)
    assert len(calls) == 1


def test_a_cross_unit_marked_render_stays_within_its_query_ceiling(
    client, django_assert_max_num_queries
):
    """An order-of-magnitude tripwire on the CROSS-UNIT marked render.

    MEASURED BASELINE: 44 queries. To re-measure, set the ceiling to 1
    temporarily and read the real count from the failure message; the ceiling is
    that count + 5. At
    least 10 slots in Y and 2 descendants under the marked element, so a per-slot
    re-walk of the source clears the margin.

    Mutant: drop `facts=facts` from the cross-unit paste_allowed loop -> RED.
    NOT caught (stated, not claimed): dropping select_related("unit") -- a single
    query, which no sane ceiling separates (see the same-unit sibling test)."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    for _ in range(5):
        _tabs(y)  # 2 slots each -> 10 container slots
    root, rslots = _tabs(x)
    _text(x, parent=root, tab=rslots[0])
    _text(x, parent=root, tab=rslots[1])
    assert _mark(client, course, x, root).status_code == 200

    with django_assert_max_num_queries(49):  # tightened to measured + 5 in Step 5b
        _editor_get(client, course, y)


def test_a_cross_unit_marked_render_never_falls_back_to_walking_parents(
    client, monkeypatch
):
    """Mutant: drop `dest_depth=dest_depth` from the cross-unit loop -> RED."""
    from courses import builder as builder_mod

    course, x = _seed(client)
    y = _unit(course, "Y")
    outer, oslots = _tabs(y)
    _tabs(y, parent=outer, tab=oslots[0])
    subject = _text(x)
    assert _mark(client, course, x, subject).status_code == 200

    def _boom(_join):
        raise RuntimeError("paste_allowed must receive dest_depth from the render")

    monkeypatch.setattr(builder_mod, "element_depth", _boom)

    assert _editor_get(client, course, y).status_code == 200


def test_a_cross_unit_copy_returns_the_destinations_fragments_and_keeps_the_mark(
    client,
):
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x, body="<p>COPYMARK</p>")
    _mark(client, course, x, subject)
    y.refresh_from_db()

    resp = _paste(client, course, y, None, "", mode="copy", element=subject)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert f'data-unit="{y.pk}"' in body  # Y's pane, not X's
    assert Element.objects.filter(unit=y).count() == 1
    assert client.session["element_clip"]["element"] == subject.pk


def test_a_paste_form_with_a_mismatched_element_is_a_409(client):
    """Mutant: delete the stale-form check -> RED (the copy is made, 200)."""
    course, unit = _seed(client)
    subject = _text(unit)
    other = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=other)

    assert resp.status_code == 409
    assert Element.objects.filter(unit=unit).count() == 2  # nothing copied


def test_a_paste_form_with_no_element_is_a_409(client):
    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=None)

    assert resp.status_code == 409


def test_a_paste_form_with_the_matching_element_succeeds(client):
    """Mutant: compare clip["element"] to the POSTed string without str() -> RED
    (an int never equals a str, so every paste would 409)."""
    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=subject)

    assert resp.status_code == 200


def test_a_mark_from_another_course_is_a_409_on_paste(client):
    """mode=copy on purpose: a default move would be stopped earlier by the
    move-reload rule and never reach the service's course filter."""
    course, unit = _seed(client)
    other_course = CourseFactory(owner=course.owner)
    foreign_unit = _unit(other_course, "F")
    foreign = _text(foreign_unit)
    _mark(client, other_course, foreign_unit, foreign)
    _assert_posts_the_mark(client, foreign)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=foreign)

    assert resp.status_code == 409


def test_a_non_numeric_session_element_is_a_409_on_paste(client):
    """Posts the EXACT session value, so the stale-form check passes and the
    service's step-1 guard is what answers."""
    course, unit = _seed(client)
    y = _unit(course, "Y")
    session = client.session
    session["element_clip"] = {"unit": unit.pk, "element": "abc"}
    session.save()
    y.refresh_from_db()

    resp = _paste(client, course, y, None, "", mode="copy", element="abc")

    assert resp.status_code == 409


def test_a_cross_unit_move_reloads_instead_of_refusing(client):
    """Only a stale tab can post it. Mutant: drop the move-reload rule -> RED
    (the service answers 422 wrong_unit instead)."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)
    _assert_posts_the_mark(client, subject)
    y.refresh_from_db()

    resp = _paste(client, course, y, None, "", mode="move", element=subject)

    assert resp.status_code == 409
    assert client.session["element_clip"]["element"] == subject.pk


def _deadlock():
    try:
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    except psycopg.errors.DeadlockDetected as inner:
        raise OperationalError("deadlock detected") from inner


def test_cancel_works_from_a_destination_unit(client):
    """The destination banner's cancel posts ITS unit with ANOTHER unit's element.
    It works because element_clip's cancel branch pops the session before any
    element check -- pinned here so a later "validate first" change cannot break
    cancel in every destination unit silently."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    resp = client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": subject.pk, "unit": y.pk, "action": "cancel"},
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    assert "element_clip" not in client.session


def test_a_deadlock_abort_of_the_copy_is_a_409(client, monkeypatch):
    """Mutant: delete the OperationalError handler -> RED (the error propagates)."""
    from courses import builder as builder_mod

    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    _assert_posts_the_mark(client, subject)
    unit.refresh_from_db()
    calls = []

    def _boom(*args, **kwargs):
        calls.append(1)
        _deadlock()

    monkeypatch.setattr(builder_mod, "paste_element", _boom)

    resp = _paste(client, course, unit, None, "", mode="copy", element=subject)

    assert calls == [1]  # the 409 provably came from the handler
    assert resp.status_code == 409
    assert client.session["element_clip"]["element"] == subject.pk


def test_any_other_operational_error_propagates(client, monkeypatch):
    """Mutant: drop the sqlstate check (map every OperationalError) -> RED."""
    from courses import builder as builder_mod

    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    def _boom(*args, **kwargs):
        try:
            raise psycopg.errors.SerializationFailure("could not serialize")
        except psycopg.errors.SerializationFailure as inner:
            raise OperationalError("could not serialize") from inner

    monkeypatch.setattr(builder_mod, "paste_element", _boom)

    with pytest.raises(OperationalError):
        _paste(client, course, unit, None, "", mode="copy", element=subject)


def test_every_rendered_paste_form_carries_the_marked_element(client):
    """Both inclusion tags see ONLY the dict they return.

    Mutant: drop clip_element_pk from paste_before_button's dict -> RED."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    # The extra X row comes FIRST: a row directly below the mark is clip_noop_pk
    # and renders no before-button, so it must sit above the subject.
    _text(x)  # a row in X that offers move-before
    subject = _text(x)
    _tabs(y)
    _text(y)  # a row in Y that offers copy-before
    _mark(client, course, x, subject)

    for u in (x, y):
        body = _editor_get(client, course, u).content.decode()
        assert 'data-op="element-paste-before"' in body, u.title
        forms = re.findall(
            r'<form[^>]*data-op="element-paste(?:-before)?"[^>]*>.*?</form>',
            body,
            flags=re.S,
        )
        assert forms, u.title
        for form in forms:
            assert f'name="element" value="{subject.pk}"' in form


# ── D13: the unit list loads each level on expand ──────────────────────────


def test_copy_units_open_path_is_every_container_above_the_unit():
    course = CourseFactory()
    part = _unit(course, "P", kind="part", unit_type="")
    chapter = _unit(course, "C", kind="chapter", unit_type="", parent=part)
    deep = _unit(course, "Deep", parent=chapter)
    _unit(course, "Other")

    units_map, _top, _available = copy_units_tree(course)

    assert copy_units_open_path(units_map, deep) == {part.pk, chapter.pk}


def test_copy_units_open_path_is_empty_for_a_root_level_unit():
    course = CourseFactory()
    root = _unit(course, "Root")
    part = _unit(course, "P", kind="part", unit_type="")
    _unit(course, "Under", parent=part)

    units_map, _top, _available = copy_units_tree(course)

    assert copy_units_open_path(units_map, root) == set()


def test_copy_units_open_path_is_empty_for_a_unit_not_in_the_map():
    course = CourseFactory()
    _unit(course, "A")
    _unit(course, "B")
    stranger = _unit(CourseFactory(), "Elsewhere")

    units_map, _top, _available = copy_units_tree(course)

    assert copy_units_open_path(units_map, stranger) == set()


def _level(client, course, parent=None, current=None):
    params = {}
    if parent is not None:
        params["parent"] = parent if isinstance(parent, (int, str)) else parent.pk
    if current is not None:
        params["current"] = current.pk
    return client.get(
        reverse("courses:manage_copy_units", kwargs={"slug": course.slug}), params
    )


def _other_course_with_a_part(course):
    other = CourseFactory(owner=course.owner)
    part = _unit(other, "ForeignPart", kind="part", unit_type="")
    _unit(other, "ForeignUnit", parent=part)
    return other, part


def test_a_level_lists_its_units_as_links_and_its_containers_collapsed(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    leaf = _unit(course, "LeafUnit", parent=part)
    chapter = _unit(course, "ChapterC", kind="chapter", unit_type="", parent=part)
    _unit(course, "GrandchildUnit", parent=chapter)

    resp = _level(client, course, part)

    assert resp.status_code == 200
    body = resp.content.decode()
    leaf_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": leaf.pk}
    )
    assert f'href="{leaf_url}"' in body
    assert "ChapterC" in body
    assert 'class="clip-banner__group"' in body
    assert "data-units-url=" in body
    assert "GrandchildUnit" not in body  # collapsed: no grandchild rows


def test_a_level_marks_the_current_unit_and_does_not_link_it(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    here = _unit(course, "HereUnit", parent=part)
    _unit(course, "ThereUnit", parent=part)

    body = _level(client, course, part, current=here).content.decode()

    here_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": here.pk}
    )
    assert 'aria-current="page"' in body
    assert f'href="{here_url}"' not in body


def test_a_level_of_a_unitless_container_is_a_404(client):
    """Mutant: serve the UNPRUNED _children_map instead of the pruned map -> RED."""
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)
    empty = _unit(course, "EmptyChapter", kind="chapter", unit_type="", parent=part)
    # A unit-less CHILD container (a section is deeper than a chapter, so the tree is
    # valid), so `empty` IS a key of the unpruned _children_map (which only keys
    # parents that have children) -- without it the mutant below would 404 anyway
    # and stay green.
    _unit(course, "EmptySection", kind="section", unit_type="", parent=empty)

    assert _level(client, course, empty).status_code == 404


def test_a_level_of_a_unit_or_a_foreign_or_bad_node_is_a_404(client):
    course, x = _seed(client)
    _other, foreign_part = _other_course_with_a_part(course)

    assert _level(client, course, x).status_code == 404  # a unit
    assert _level(client, course, foreign_part).status_code == 404
    assert _level(client, course, "abc").status_code == 404
    assert _level(client, course).status_code == 404  # no parent at all


def test_a_level_is_refused_to_a_user_who_cannot_manage_the_course(client):
    """Mutant: drop the can_manage_course check -> RED."""
    from tests.factories import make_teacher

    course, _x = _seed(client, username="owner")
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)
    # The construction test_a_user_who_cannot_manage_the_course_is_refused uses.
    client.logout()
    make_teacher(client, "teacher")

    assert _level(client, course, part).status_code == 403


def test_a_level_needs_a_login(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)
    client.logout()

    assert _level(client, course, part).status_code == 302


def test_a_level_refuses_post(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)

    resp = client.post(
        reverse("courses:manage_copy_units", kwargs={"slug": course.slug}),
        {"parent": part.pk},
    )

    assert resp.status_code == 405


def test_a_levels_query_count_does_not_grow_with_its_size(client):
    """Mutant: a per-row query in the row partial, e.g. {{ n.parent.title }} added to
    each unit row -> RED. (NOT n.course.slug: nodes from course.nodes.all() already
    carry .course via the reverse-FK manager's known-related-objects cache, so that
    mutant costs no query and would stay green.)"""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course, _x = _seed(client)
    small = _unit(course, "Small", kind="part", unit_type="")
    _unit(course, "S1", parent=small)
    big = _unit(course, "Big", kind="part", unit_type="")
    for i in range(30):
        _unit(course, f"B{i}", parent=big)
    _level(client, course, small)  # warm the session/auth path

    with CaptureQueriesContext(connection) as small_q:
        _level(client, course, small)
    with CaptureQueriesContext(connection) as big_q:
        _level(client, course, big)

    assert len(big_q) == len(small_q)
