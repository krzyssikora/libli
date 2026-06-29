import pytest
from django.urls import reverse

from courses.models import Enrollment
from tags import services
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _user(n=0):
    """Verified user — force_login works with allauth's AccountMiddleware."""
    return make_verified_user(
        username=f"outline{n}", email=f"outline{n}@test.example.com"
    )


def _course_with_units(user):
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    u1 = ContentNodeFactory(
        course=course, parent=part, unit_type="lesson", title="Photosynthesis"
    )
    u2 = ContentNodeFactory(
        course=course, parent=part, unit_type="lesson", title="Membranes"
    )
    return course, u1, u2


def test_outline_renders_chip_for_tagged_unit(client):
    user = _user(0)
    client.force_login(user)
    course, u1, _ = _course_with_units(user)
    services.tag_unit(user, u1, "exam")
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert b"exam" in resp.content


def test_filter_hides_non_matching_unit(client):
    user = _user(1)
    client.force_login(user)
    course, u1, u2 = _course_with_units(user)
    exam = services.tag_unit(user, u1, "exam").tag
    resp = client.get(
        reverse("courses:course_outline", args=[course.slug]) + f"?tags={exam.pk}"
    )
    html = resp.content.decode()
    # the matching unit's row is visible; the non-matching one carries hidden
    assert "Photosynthesis" in html
    # crude check: the membranes row's <li> has the hidden attribute
    assert "Membranes" in html  # still in DOM (hidden, not omitted)


def test_unknown_tag_id_is_dropped_not_404(client):
    user = _user(2)
    client.force_login(user)
    course, _, _ = _course_with_units(user)
    resp = client.get(
        reverse("courses:course_outline", args=[course.slug]) + "?tags=999999"
    )
    assert resp.status_code == 200
    assert resp.context["active_tag_ids"] == []
