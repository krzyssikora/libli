from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def _course_with_section(client, username):
    # make_pa creates AND logs in a Platform Admin (holds courses.change_course, so it can
    # manage any course regardless of owner). Create data after, owned by that user.
    pa = make_pa(client, username)
    course = CourseFactory(slug=f"aff-{username}", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch1")
    sec = ContentNodeFactory(course=course, kind="section", unit_type=None, parent=ch, title="SecA")
    return course, ch, sec


def test_affordance_shows_only_legal_kinds_per_scope(client, db):
    course, ch, sec = _course_with_section(client, "pa")
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    assert "+ Chapter" in html                     # top scope primary chip
    assert f'data-add-scope="{ch.pk}"' in html      # chapter scope has an affordance
    assert f'data-add-scope="{sec.pk}"' in html     # section scope has an affordance (+ Unit only)


def test_empty_chapter_still_shows_its_add_affordance(client, db):
    pa = make_pa(client, "pa2")
    course = CourseFactory(slug="empty", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    assert f'data-add-scope="{ch.pk}"' in html       # empty chapter still exposes its + chips


def test_reorder_buttons_disabled_at_boundaries(client, db):
    pa = make_pa(client, "pab")
    course = CourseFactory(slug="bnd", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="A")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="B")
    html = client.get(f"/manage/courses/{course.slug}/build/").content.decode()
    # First child A: up disabled; last child B: down disabled. Regex tolerant of other
    # attributes between value and disabled (robust against attribute reordering).
    import re
    assert re.search(r'value="up"[^>]*\bdisabled', html), "first child should disable up"
    assert re.search(r'value="down"[^>]*\bdisabled', html), "last child should disable down"


def test_no_js_add_via_kind_button_creates_node(client, db):
    course, ch, sec = _course_with_section(client, "pa3")
    resp = client.post(
        f"/manage/courses/{course.slug}/build/node/add/",
        {"parent": str(sec.pk), "kind": "unit", "title": "L1",
         "unit_type": "lesson", "parent_token": sec.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert ContentNode.objects.filter(course=course, parent=sec, title="L1", kind="unit").exists()
