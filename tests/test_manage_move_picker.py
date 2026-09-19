from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa


def test_move_picker_position_defaults_to_empty_append(client, db):
    pa = make_pa(client, "pamp")
    course = CourseFactory(slug="mp", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="U"
    )
    url = f"/manage/courses/{course.slug}/build/node/move/?node={unit.pk}"
    html = client.get(url, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    import re

    m = re.search(r'<input[^>]*name="position"[^>]*>', html)
    assert m and 'value=""' in m.group(0), (
        "position must default to empty (append), not 0"
    )
    assert 'name="node_token"' in html
    # Ch is a legal destination for a unit (shallower kind), rendered with its
    # data-updated.
    assert f'value="{ch.pk}"' in html


def test_no_js_reparent_empty_position_appends(client, db):
    # The headline value="" change: an empty position must APPEND (not prepend to
    # index 0).
    pa = make_pa(client, "pamp2")
    course = CourseFactory(slug="mp2", owner=pa)
    ch = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="A"
    )
    ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=ch, title="B"
    )
    resp = client.post(
        f"/manage/courses/{course.slug}/build/node/move/",
        {
            "mode": "reparent",
            "node": str(a.pk),
            "new_parent": str(ch.pk),
            "position": "",
            "node_token": a.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    order = list(
        ContentNode.objects.filter(parent=ch)
        .order_by("order", "pk")
        .values_list("title", flat=True)
    )
    assert order == [
        "B",
        "A",
    ]  # A re-appended to the end of Ch (empty position -> append)


def _cancel_href(html):
    """The href of the picker's single Cancel link, entity-decoded."""
    import html as htmllib
    import re

    links = re.findall(r"<a\b[^>]*\bdata-move-cancel\b[^>]*>", html)
    assert len(links) == 1, f"expected exactly one Cancel link, found {links!r}"
    m = re.search(r'href="([^"]*)"', links[0])
    assert m, f"the Cancel link has no href: {links[0]!r}"
    return htmllib.unescape(m.group(1))


def test_move_picker_cancel_links_back_to_the_builder(client, db):
    """No-JS: Cancel is a plain link that navigates back to the builder."""
    from django.urls import reverse

    pa = make_pa(client, "pamp3")
    course = CourseFactory(slug="mp3", owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    url = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    html = client.get(url, {"node": unit.pk}).content.decode()
    assert _cancel_href(html) == reverse(
        "courses:manage_builder", kwargs={"slug": course.slug}
    )


def test_move_picker_cancel_keeps_the_filter(client, db):
    """A filtered author cancels back to the SAME filtered builder; `q` is
    url-encoded (the `&` would otherwise split it into a second parameter)."""
    from urllib.parse import parse_qs
    from urllib.parse import urlsplit

    from django.urls import reverse

    pa = make_pa(client, "pamp4")
    course = CourseFactory(slug="mp4", owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    url = reverse("courses:manage_node_move", kwargs={"slug": course.slug})
    html = client.get(url, {"node": unit.pk, "q": "a&b c"}).content.decode()
    parts = urlsplit(_cancel_href(html))
    assert parts.path == reverse("courses:manage_builder", kwargs={"slug": course.slug})
    assert parse_qs(parts.query) == {"q": ["a&b c"]}
