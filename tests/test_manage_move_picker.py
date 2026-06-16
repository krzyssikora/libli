import pytest
from tests.factories import ContentNodeFactory, CourseFactory, make_pa
from courses.models import ContentNode


def test_move_picker_position_defaults_to_empty_append(client, db):
    pa = make_pa(client, "pamp")
    course = CourseFactory(slug="mp", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="U")
    url = f"/manage/courses/{course.slug}/build/node/move/?node={unit.pk}"
    html = client.get(url, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    import re
    m = re.search(r'<input[^>]*name="position"[^>]*>', html)
    assert m and 'value=""' in m.group(0), "position must default to empty (append), not 0"
    assert 'name="node_token"' in html
    # Ch is a legal destination for a unit (shallower kind), rendered with its data-updated.
    assert f'value="{ch.pk}"' in html


def test_no_js_reparent_empty_position_appends(client, db):
    # The headline value="" change: an empty position must APPEND (not prepend to index 0).
    pa = make_pa(client, "pamp2")
    course = CourseFactory(slug="mp2", owner=pa)
    ch = ContentNodeFactory(course=course, kind="chapter", unit_type=None, parent=None, title="Ch")
    a = ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="A")
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=ch, title="B")
    resp = client.post(
        f"/manage/courses/{course.slug}/build/node/move/",
        {"mode": "reparent", "node": str(a.pk), "new_parent": str(ch.pk),
         "position": "", "node_token": a.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    order = list(ContentNode.objects.filter(parent=ch).order_by("order", "pk")
                 .values_list("title", flat=True))
    assert order == ["B", "A"]   # A re-appended to the end of Ch (empty position -> append)
