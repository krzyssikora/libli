"""Render-tier tests for the collapsible course outline (spec T1-T5)."""

import pytest
from django.urls import reverse

from courses.models import Enrollment
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
    """T3. Mutant: move the link back inside the <summary>.

    Structural assertion. The motivation is that a <summary> is one button-role
    control whose accessible name concatenates its contents, and that a folded
    group hides everything except its summary — but this tier observes the
    structure, not those consequences.
    """
    course, part, chapter, unit = _three_level_course()
    html = _outline_html(client, course, "t3")

    _, _, rest = html.partition('<summary class="outline-node__head">')
    summary, _, _ = rest.partition("</summary>")
    assert "outline-node__chevron" in summary
    assert "outline-node__title" in summary
    assert "outline-node__reset" not in summary, "D9: the reset link is a sibling"
    assert "outline-node__reset" in html, "...but it is still rendered"
