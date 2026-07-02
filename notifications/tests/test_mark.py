import pytest
from django.urls import reverse

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_mark_read_owner_only(client):
    mine = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    n = Notification.objects.get(recipient=mine)
    resp = client.post(reverse("notifications:mark_read", kwargs={"pk": n.pk}))
    assert resp.status_code == 302
    n.refresh_from_db()
    assert n.read_at is not None


def test_mark_read_foreign_is_404_and_untouched(client):
    make_login(client, "owner")
    other = UserFactory()
    course = CourseFactory()
    services.notify_enrolled(other, course)
    foreign = Notification.objects.get(recipient=other)
    resp = client.post(reverse("notifications:mark_read", kwargs={"pk": foreign.pk}))
    assert resp.status_code == 404
    foreign.refresh_from_db()
    assert foreign.read_at is None


def test_mark_all_read(client):
    mine = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    services.notify_enrolled(mine, course)
    resp = client.post(reverse("notifications:mark_all_read") + "?page=2")
    assert resp.status_code == 302
    assert resp["Location"].endswith("?page=2")
    assert services.unread_count(mine) == 0


def test_mark_get_not_allowed(client):
    mine = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    n = Notification.objects.get(recipient=mine)
    resp = client.get(reverse("notifications:mark_read", kwargs={"pk": n.pk}))
    assert resp.status_code == 405
