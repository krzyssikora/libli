import pytest
from django.urls import reverse

from notifications import services
from tests.factories import CourseFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_badge_count_in_context_for_authenticated(client):
    user = make_login(client, "owner")
    course = CourseFactory()
    services.notify_enrolled(user, course)
    services.notify_enrolled(user, course)
    resp = client.get(reverse("courses:my_courses"))
    assert resp.context["notifications_unread"] == 2


def test_badge_absent_for_anonymous(client):
    resp = client.get(reverse("account_login"))
    assert "notifications_unread" not in resp.context or not resp.context.get(
        "notifications_unread"
    )
