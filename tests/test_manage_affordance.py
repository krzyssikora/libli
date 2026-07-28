from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa
from tests.helpers_builder import open_all_param


def _course_with_section(client, username):
    # make_pa creates AND logs in a Platform Admin (holds courses.change_course,
    # so it can manage any course regardless of owner). Create data after, owned by
    # that user.
    pa = make_pa(client, username)
    course = CourseFactory(slug=f"aff-{username}", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch1"
    )
    sec = ContentNodeFactory(
        course=course, kind="section", unit_type=None, parent=ch, title="SecA"
    )
    return course, ch, sec


def test_affordance_shows_only_legal_kinds_per_scope(client, db):
    # This fixture is well under SIZE_THRESHOLD, so it would arrive fully open
    # even without the param -- pass open=all explicitly so the assertion
    # actually documents "an open scope shows its affordance" rather than
    # relying on the below-threshold auto-expand as an accident of size.
    course, ch, sec = _course_with_section(client, "pa")
    html = client.get(
        f"/manage/courses/{course.slug}/build/" + open_all_param()
    ).content.decode()
    assert "+ Chapter" in html  # top scope primary chip
    assert f'data-add-scope="{ch.pk}"' in html  # chapter scope has an affordance
    assert (
        f'data-add-scope="{sec.pk}"' in html
    )  # section scope has an affordance (+ Unit only)


def test_empty_chapter_still_shows_its_add_affordance(client, db):
    pa = make_pa(client, "pa2")
    course = CourseFactory(slug="empty", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    html = client.get(
        f"/manage/courses/{course.slug}/build/" + open_all_param()
    ).content.decode()
    assert (
        f'data-add-scope="{ch.pk}"' in html
    )  # empty chapter still exposes its + chips


def test_collapsed_scope_hides_its_add_affordance(client, db):
    # Behaviour change (not a fixture artifact): a container's own
    # add-affordance lives inside `_scope.html`, which `_tree_node.html` only
    # includes when the container's pk is in open_ids (templates/courses/
    # manage/_tree_node.html). Collapsing a scope therefore hides the "+"
    # chips for adding children to it, along with the rest of that scope's
    # markup. Force full collapse with an explicit empty `open=` -- an empty
    # string is still "present", so it does not fall through to the
    # below-threshold auto-expand (courses/builder_open.py `_raw_open`/
    # `open_ids` step 2 vs step 4).
    course, ch, sec = _course_with_section(client, "pa4")
    html = client.get(f"/manage/courses/{course.slug}/build/?open=").content.decode()
    assert "+ Chapter" in html  # the root scope always renders (builder.html
    # includes it directly, never gated behind open_ids)
    assert f'data-node="{ch.pk}"' in html  # ch's own row still renders...
    assert f'data-add-scope="{ch.pk}"' not in html  # ...but its scope is closed
    # sec is INSIDE ch's collapsed scope, so its row -- and its affordance --
    # aren't in the response at all.
    assert f'data-node="{sec.pk}"' not in html
    assert f'data-add-scope="{sec.pk}"' not in html


def test_opening_a_scope_reveals_its_add_affordance(client, db):
    # Complement to the collapsed case above: opening exactly `ch` (and only
    # `ch`) shows ch's own affordance and sec's row, but sec's OWN scope stays
    # closed since sec's pk isn't in the requested open set.
    course, ch, sec = _course_with_section(client, "pa5")
    html = client.get(
        f"/manage/courses/{course.slug}/build/?open={ch.pk}"
    ).content.decode()
    assert f'data-add-scope="{ch.pk}"' in html  # ch is open -> its chips render
    assert f'data-node="{sec.pk}"' in html  # sec's row is visible (child of ch)
    assert f'data-add-scope="{sec.pk}"' not in html  # but sec's own scope is shut

    # Opening both makes sec's affordance appear too.
    html_both = client.get(
        f"/manage/courses/{course.slug}/build/?open={ch.pk},{sec.pk}"
    ).content.decode()
    assert f'data-add-scope="{ch.pk}"' in html_both
    assert f'data-add-scope="{sec.pk}"' in html_both


def test_reorder_buttons_disabled_at_boundaries(client, db):
    pa = make_pa(client, "pab")
    course = CourseFactory(slug="bnd", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="A"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="B"
    )
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    # First child A: up disabled; last child B: down disabled. Regex tolerant of other
    # attributes between value and disabled (robust against attribute reordering).
    import re

    assert re.search(r'value="up"[^>]*\bdisabled', html), (
        "first child should disable up"
    )
    assert re.search(r'value="down"[^>]*\bdisabled', html), (
        "last child should disable down"
    )


def test_no_js_add_via_kind_button_creates_node(client, db):
    course, ch, sec = _course_with_section(client, "pa3")
    resp = client.post(
        f"/manage/courses/{course.slug}/build/node/add/",
        {
            "parent": str(sec.pk),
            "kind": "unit",
            "title": "L1",
            "unit_type": "lesson",
            "parent_token": sec.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(
        course=course, parent=sec, title="L1", kind="unit"
    ).exists()
