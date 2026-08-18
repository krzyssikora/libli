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
