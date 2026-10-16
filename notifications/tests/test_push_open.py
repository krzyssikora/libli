"""§3 the tap target: marks the viewer's own notification read, never an oracle."""

import pytest
from django.urls import reverse

from notifications.models import Notification
from notifications.services import notification_url
from notifications.tests.push_helpers import logged_in_user
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enrolled(user, course=None, **data):
    course = course or CourseFactory()
    base = {"course_title": course.title, "course_slug": course.slug}
    base.update(data)
    return Notification.objects.create(
        recipient=user,
        kind="enrolled",
        target_type="course",
        target_id=course.pk,
        data=base,
    )


def _open(client, pk):
    return client.get(reverse("notifications:open", args=[pk]))


def test_marks_read_and_redirects_to_the_target(client):
    user = logged_in_user(client)
    n = _enrolled(user)
    r = _open(client, n.pk)
    assert r.status_code == 302 and r["Location"] == notification_url(n)
    n.refresh_from_db()
    assert n.read_at is not None


def test_idempotent_on_a_read_notification(client):
    user = logged_in_user(client)
    n = _enrolled(user)
    _open(client, n.pk)
    n.refresh_from_db()
    first = n.read_at
    _open(client, n.pk)
    n.refresh_from_db()
    assert n.read_at == first


def test_unreversible_target_falls_back_to_list(client):
    user = logged_in_user(client)
    n = _enrolled(user, course_slug="")
    assert _open(client, n.pk)["Location"] == reverse("notifications:list")


def test_foreign_and_missing_pk_look_identical_and_mark_nothing(client):
    logged_in_user(client)
    other = UserFactory()
    theirs = _enrolled(other)
    a, b = _open(client, theirs.pk), _open(client, 999999)
    assert (a.status_code, a["Location"]) == (b.status_code, b["Location"])
    assert a["Location"] == reverse("notifications:list")
    theirs.refresh_from_db()
    assert theirs.read_at is None


def test_anonymous_goes_to_login_with_next_and_marks_nothing(client):
    # mutant: login_required dropped
    n = _enrolled(UserFactory())
    r = _open(client, n.pk)
    assert r.status_code == 302
    assert reverse("account_login") in r["Location"]
    assert "next=" in r["Location"]
    n.refresh_from_db()
    assert n.read_at is None


def test_works_with_push_not_configured(client):
    user = logged_in_user(client)
    n = _enrolled(user)
    assert _open(client, n.pk).status_code == 302  # suite default: push not configured
    n.refresh_from_db()
    assert n.read_at is not None
