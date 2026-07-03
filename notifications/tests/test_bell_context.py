import pytest
from django.urls import reverse

from core.context_processors import BELL_RECENT_LIMIT
from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_recent_exposed_and_capped(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    for _ in range(BELL_RECENT_LIMIT + 3):
        services.notify_enrolled(user, course)
    resp = client.get(reverse("courses:my_courses"))
    recent = resp.context["notifications_recent"]
    assert len(recent) == BELL_RECENT_LIMIT
    assert all(hasattr(n, "url") for n in recent)
    assert resp.context["notifications_unread"] == BELL_RECENT_LIMIT + 3


def test_recent_url_none_when_unresolvable(client):
    user = make_login(client, "owner")
    # Empty data → notification_url can't resolve a slug → None.
    Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=1,
        data={},
    )
    resp = client.get(reverse("courses:my_courses"))
    assert resp.context["notifications_recent"][0].url is None


def test_anonymous_gets_neither(client):
    resp = client.get(reverse("account_login"))
    assert not resp.context.get("notifications_recent")
    assert not resp.context.get("notifications_unread")


def test_one_added_query_no_n_plus_one(rf, django_assert_num_queries):
    user = make_verified_user(username="q", email="q@test.example.com")
    course = CourseFactory()
    for _ in range(5):
        services.notify_enrolled(user, course)
    from core.context_processors import notifications_badge

    request = rf.get("/")
    request.user = user
    # Exactly two queries: unread_count() + recent_for(); notification_url is
    # pure Python (reverse()) and adds none regardless of row count.
    with django_assert_num_queries(2):
        ctx = notifications_badge(request)
    assert len(ctx["notifications_recent"]) == 5
