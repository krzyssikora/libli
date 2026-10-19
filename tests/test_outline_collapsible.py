"""Render-tier tests for the collapsible course outline (spec T1-T5)."""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import Enrollment
from courses.models import UnitProgress
from courses.rollups import build_outline
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _three_level_course():
    """part > chapter > unit. Every container holds a visible unit, or
    build_outline's pruning drops it before the template ever sees it."""
    course = CourseFactory()
    part = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chapter = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=part
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chapter, title="U1"
    )
    return course, part, chapter, unit


def test_build_outline_sets_depth(django_user_model):
    course, part, chapter, unit = _three_level_course()
    user = django_user_model.objects.create_user(username="d1", password="x")
    tree = build_outline(course, user)

    assert tree[0]["depth"] == 0, "a root container is depth 0"
    assert tree[0]["children"][0]["depth"] == 1
    assert tree[0]["children"][0]["children"][0]["depth"] == 2


def _outline_html(client, course, username):
    user = make_login(client, username)
    Enrollment.objects.create(student=user, course=course)
    return client.get(
        reverse("courses:course_outline", kwargs={"slug": course.slug})
    ).content.decode()


def test_depth0_open_deeper_closed(client):
    """T1. Mutant: emit `open` unconditionally."""
    course, part, chapter, unit = _three_level_course()
    html = _outline_html(client, course, "t1")

    assert f'data-node="{part.pk}"' in html
    assert 'data-depth="0"' in html
    assert 'data-depth="1"' in html

    part_tag = html.split(f'data-node="{part.pk}"')[1].split(">")[0]
    chapter_tag = html.split(f'data-node="{chapter.pk}"')[1].split(">")[0]
    assert "open" in part_tag, "a depth-0 container ships open (D1)"
    assert "open" not in chapter_tag, "a depth-1 container ships folded (D1)"


def test_reset_link_is_a_sibling_of_details_not_inside_the_summary(client):
    """T3. Mutant: move the menu back inside the <summary>.

    Structural assertion. The motivation is that a <summary> is one button-role
    control whose accessible name concatenates its contents, and that a folded
    group hides everything except its summary — but this tier observes the
    structure, not those consequences.
    """
    course, part, chapter, unit = _three_level_course()
    # The link renders only above saved work, so seed some before the request.
    user = make_login(client, "t3")
    Enrollment.objects.create(student=user, course=course)
    UnitProgress.objects.create(student=user, unit=unit, element_state={"1": {}})
    html = client.get(
        reverse("courses:course_outline", kwargs={"slug": course.slug})
    ).content.decode()

    summary = BeautifulSoup(html, "html.parser").select_one(
        "summary.outline-node__head"
    )
    assert summary.select_one(".outline-node__chevron") is not None
    assert summary.select_one(".outline-node__title") is not None
    assert summary.select_one(".outline-node__reset") is None, (
        "D9: the reset link is not inside the summary"
    )
    menu = summary.parent.find_next_sibling()
    assert menu.name == "details" and "outline-menu" in menu["class"], (
        "the menu holding the reset link is the <details>' next sibling"
    )
    assert menu.select_one("a.outline-node__reset") is not None


def test_filter_opens_the_ancestors_of_a_match(client):
    """T5 / D8. The tag filter is NOT JS-only: _tags_filter_bar.html renders real
    <a href="?tags=N"> links and outline_with_tags sets tag_hidden server-side.
    Without the second `open` arm, a no-JS student clicking a filter chip sees an
    outline of nothing — a regression on a currently-working path.

    Mutant: drop the `or active_tag_ids and not item.tag_hidden` arm.
    """
    from tags.models import Tag
    from tags.models import UnitTag

    course = CourseFactory()
    root_a = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    root_b = ContentNodeFactory(course=course, kind="part", unit_type=None, parent=None)
    chap_a = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=root_a
    )
    chap_b = ContentNodeFactory(
        course=course, kind="chapter", unit_type=None, parent=root_b
    )
    hit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=chap_a
    )
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=chap_b)

    user = make_login(client, "t5")
    Enrollment.objects.create(student=user, course=course)
    # The tag MUST be authored by the student issuing the GET: course_outline
    # filters active_tag_ids down to tags_for_outline(request.user, course), which
    # is tag__author-scoped. A tag owned by anyone else leaves active_tag_ids
    # empty, the D8 arm never fires, and this test fails on a CORRECT build.
    tag = Tag.objects.create(author=user, name="exam")
    UnitTag.objects.create(tag=tag, unit=hit)

    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    html = client.get(f"{url}?tags={tag.pk}").content.decode()

    chap_a_tag = html.split(f'data-node="{chap_a.pk}"')[1].split(">")[0]
    chap_b_tag = html.split(f'data-node="{chap_b.pk}"')[1].split(">")[0]
    assert "open" in chap_a_tag, "the match's depth-1 ancestor is opened"
    # Negative side must target depth >= 1: depth-0 containers render open
    # unconditionally under D1's arm, so a depth-0 negative fails on a correct build.
    assert "open" not in chap_b_tag, "a depth-1 container with no match stays folded"


def test_header_button_and_nav_attributes(client):
    """T4. Mutant: drop data-course-slug from the nav — without it the storage key
    becomes `libli_outline_open:undefined`, i.e. one fold state shared across every
    course, which nothing else would notice."""
    course, part, chapter, unit = _three_level_course()
    html = _outline_html(client, course, "t4")

    assert f'data-course-slug="{course.slug}"' in html
    assert "outline-tree--booting" in html, (
        "server-rendered: a JS-added class arrives after the first paint, which is "
        "the very paint it exists to cover"
    )
    button = html.split("data-outline-toggle-all")[0].rsplit("<button", 1)[1]
    assert "hidden" in button, "ships hidden; JS reveals it (dead control with JS off)"
    assert 'data-label-expand="Expand all"' in html
    assert 'data-label-collapse="Collapse all"' in html
    # Spec §4.5: outline_tree.js must register its libli:tagfilter listener
    # before tags.js runs its initial applyFilter(). Both are `defer`, so
    # document order IS execution order — and nothing else in the suite notices
    # a swap. Same shape as
    # test_title_math_assets.py::test_js_partial_keeps_the_load_bearing_script_order.
    # Mutant: swap the two <script> lines.
    assert html.index("outline_tree.js") < html.index("tags/js/tags.js")
