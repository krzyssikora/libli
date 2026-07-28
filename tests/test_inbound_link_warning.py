import pytest
from django.urls import reverse

from courses.models import TextElement
from courses.richtext import count_inbound_links
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login


def _text(body):
    """A saved TextElement -- there is no TextElementFactory in this repo."""
    obj = TextElement(body=body)
    obj.save()
    return obj


pytestmark = pytest.mark.django_db


def _scene(client=None):
    owner = make_login(client, "owner") if client else None
    course = CourseFactory(owner=owner) if owner else CourseFactory()
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=None, title="Ch"
    )
    inner = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="Inner"
    )
    outside = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Outside"
    )
    return course, chapter, inner, outside


def test_zero_with_no_links():
    _course, chapter, _inner, _outside = _scene()
    assert count_inbound_links(chapter.course, chapter) == 0


def test_counts_a_link_from_outside_the_subtree():
    course, chapter, _inner, outside = _scene()
    add_element(outside, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    assert count_inbound_links(course, chapter) == 1


def test_counts_links_to_a_descendant_not_just_the_node():
    course, chapter, inner, outside = _scene()
    add_element(outside, _text(f'<a href="/courses/n/{inner.pk}/">i</a>'))
    assert count_inbound_links(course, chapter) == 1


def test_counts_elements_not_anchors():
    # Two anchors in ONE body pointing at two doomed nodes count once: the author's
    # unit of repair is "this element needs editing".
    course, chapter, inner, outside = _scene()
    body = (
        f'<a href="/courses/n/{chapter.pk}/">c</a> '
        f'<a href="/courses/n/{inner.pk}/">i</a>'
    )
    add_element(outside, _text(body=body))
    assert count_inbound_links(course, chapter) == 1


def test_ignores_links_originating_inside_the_doomed_subtree():
    # A link inside the subtree dies with its target. Counting those would report a
    # large number for a self-contained part whose lessons cross-link each other --
    # the opposite of the warning's purpose.
    course, chapter, inner, _outside = _scene()
    add_element(inner, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    assert count_inbound_links(course, chapter) == 0


def test_ignores_links_from_another_course():
    course, chapter, _inner, _outside = _scene()
    other = CourseFactory()
    other_unit = ContentNodeFactory(
        course=other, kind="unit", unit_type="lesson", parent=None, title="X"
    )
    add_element(other_unit, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    assert count_inbound_links(course, chapter) == 0


def test_confirm_page_shows_the_sentence_only_when_non_zero(client):
    course, chapter, _inner, outside = _scene(client)
    url = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    html = client.get(url, {"node": chapter.pk}).content.decode()
    assert "links here" not in html.lower()

    add_element(outside, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    html = client.get(url, {"node": chapter.pk}).content.decode()
    assert "links here" in html.lower() or "link here" in html.lower()


def test_the_scan_is_one_query_per_model_with_a_constant_predicate(
    client, django_assert_num_queries
):
    # The fixture must hold at least TWO link-bearing elements of the SAME model
    # OUTSIDE the doomed subtree -- among the rows the scan actually reads. Putting
    # them inside would make this vacuous: the scan excludes the subtree, so those rows
    # are never queried per-model and could not distinguish per-model from per-element.
    course, chapter, _inner, outside = _scene(client)
    for _ in range(2):
        add_element(outside, _text(f'<a href="/courses/n/{chapter.pk}/">c</a>'))
    url = reverse("courses:manage_node_delete", kwargs={"slug": course.slug})
    client.get(url, {"node": chapter.pk})  # warm caches

    # MEASURED on this repo: 32. Shape: 16 registry-model queries + 2 from
    # ContentNode._subtree_node_ids (one per descendant depth level PLUS one for the
    # terminating empty frontier) + the pre-existing per-node _descendant_count and
    # _element_count walks + the view's fixed queries (session, user, course+perm,
    # get_node_or_404) + the FIVE custom context processors registered in
    # config/settings/base.py:66-75. Re-derive rather than record if it drifts.
    with django_assert_num_queries(32) as captured:
        client.get(url, {"node": chapter.pk})

    # The COMPLEXITY invariant, which a bare count cannot see: a per-pk-OR
    # implementation would still issue exactly 16 queries. Each scan query must carry a
    # CONSTANT predicate -- no node pk in the SQL.
    scan = [q for q in captured.captured_queries if "/courses/n/" in q["sql"]]
    assert scan, "no scan query used the constant substring"
    for q in scan:
        assert f"/courses/n/{chapter.pk}/" not in q["sql"], q["sql"]
