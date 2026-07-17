import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Enrollment
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _login(client, course):
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student


def test_lesson_page_links_to_the_reset_interstitial(client):
    course, unit = make_course_with_unit()
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert (
        reverse("courses:progress_reset", args=[course.slug, unit.pk])
        in r.content.decode()
    )


def test_outline_links_to_the_course_level_reset(client):
    course, _unit = make_course_with_unit()
    _login(client, course)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert (
        reverse("courses:progress_reset_course", args=[course.slug])
        in r.content.decode()
    )


def test_outline_links_reset_per_grouping_node(client):
    course, _unit = make_course_with_unit()
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="u",
    )
    _login(client, course)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert (
        reverse("courses:progress_reset", args=[course.slug, ch.pk])
        in r.content.decode()
    )
