import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _tree(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, title="Algebra")
    chapter = ContentNodeFactory(
        course=course, kind="chapter", parent=part, title="Quadratics"
    )
    lesson = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="Vertex"
    )
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=chapter, title="Practice"
    )
    return course, part, chapter, lesson, quiz


def test_picker_lists_every_node_for_a_manager(client):
    course, part, chapter, lesson, quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    for node in (part, chapter, lesson, quiz):
        assert f'data-node="{node.pk}"' in html


def test_row_href_equals_reverse(client):
    # The route name is the single source of the URL shape for the JS path. A route
    # rename must fail here, not silently invalidate every future link.
    course, _part, _chapter, lesson, _quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    expected = reverse("courses:node_permalink", kwargs={"node_pk": lesson.pk})
    assert f'data-href="{expected}"' in html


def test_unit_rows_distinguish_lesson_from_quiz(client):
    # The permalink sends a lesson and a quiz to DIFFERENT pages, so an author
    # choosing a target must be able to tell them apart. Mirrors _tree_node.html.
    #
    # tree__badge--quiz/--lesson carry no CSS rule anywhere (editor.css nor
    # builder.css) -- the only distinction an author actually SEES is the L/Q letter.
    # A class-only assertion stays green even if both badges rendered the same
    # letter, so check the visible text too.
    from bs4 import BeautifulSoup

    course, _part, _chapter, lesson, quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    assert "tree__badge--lesson" in html
    assert "tree__badge--quiz" in html

    soup = BeautifulSoup(html, "html.parser")
    row = ".link-picker__row .tree__badge"
    lesson_badge = soup.select_one(f'[data-node="{lesson.pk}"] > {row}')
    quiz_badge = soup.select_one(f'[data-node="{quiz.pk}"] > {row}')
    assert lesson_badge.get_text(strip=True) == "L"
    assert quiz_badge.get_text(strip=True) == "Q"


def test_rows_are_treeitems_owning_their_children(client):
    # The <li> must BE the treeitem: with role="none" on the <li>, each role="group"
    # becomes a SIBLING of the item it belongs to, so no item owns any subtree and
    # the nesting is not conveyed at all.
    course, _part, _chapter, _lesson, _quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    # role="tree" lives on the dialog's mount div (which carries the aria-label);
    # this root <ol> is presentational so the <li> treeitems remain owned by the tree.
    assert 'role="none"' in html
    assert 'role="treeitem"' in html
    assert 'aria-level="1"' in html
    assert 'aria-level="2"' in html
    # ownership: the group must open INSIDE an item, i.e. after a treeitem <li> and
    # before its closing tag.
    item_start = html.index('role="treeitem"')
    group_start = html.index('role="group"')
    assert group_start > item_start


def test_parent_treeitems_expose_aria_expanded_true(client):
    # A treeitem owning a group should expose expanded state; the tree is permanently
    # expanded so aria-expanded="true" on rows that HAVE children is the whole fix.
    # Leaf rows (no group) must not claim an expanded/collapsed state they don't have.
    from bs4 import BeautifulSoup

    course, part, chapter, lesson, quiz = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    soup = BeautifulSoup(html, "html.parser")

    for node in (part, chapter):
        row = soup.select_one(f'[data-node="{node.pk}"]')
        assert row.get("aria-expanded") == "true", node.title

    for node in (lesson, quiz):
        row = soup.select_one(f'[data-node="{node.pk}"]')
        assert row.get("aria-expanded") is None, node.title


def test_response_is_a_bare_partial(client):
    course, *_ = _tree(client)
    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    assert "<html" not in html.lower()


def test_non_manager_gets_403(client):
    course = CourseFactory()
    make_login(client, "outsider")
    resp = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    )
    assert resp.status_code == 403


def test_unknown_slug_is_404(client):
    make_login(client, "someone")
    resp = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": "no-such-course"})
    )
    assert resp.status_code == 404


def test_query_count_is_flat_in_tree_size(client, django_assert_num_queries):
    # _children_map is ONE query and must stay one -- the point is that a regression
    # to one query per row goes red. assertNumQueries(1) would simply be wrong: the
    # view also runs auth/session lookups, resolves the course and checks the perm.
    course, *_ = _tree(client)
    for i in range(10):
        ContentNodeFactory(course=course, kind="part", parent=None, title=f"P{i}")
    url = reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    client.get(url)  # warm any session/auth caching
    with django_assert_num_queries(9) as captured:
        # Measured: session, user, allauth's EmailAddress read, the course lookup, the
        # permission/group reads behind can_manage_course, and one _children_map. The
        # exact total is incidental; the assertion below is the invariant that matters.
        client.get(url)
    # The invariant that actually matters: the tree costs ONE query regardless of size.
    node_queries = [
        q for q in captured.captured_queries if "courses_contentnode" in q["sql"]
    ]
    assert len(node_queries) == 1, node_queries
