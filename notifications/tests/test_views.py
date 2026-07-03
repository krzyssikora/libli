import pytest
from django.urls import reverse
from django.utils import timezone

from notifications import services
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def test_url_reversal_per_kind():
    course = CourseFactory(slug="c1")
    sub = QuizSubmissionFactory(unit=make_quiz_unit(course=course))
    needs_review = Notification(
        kind=Notification.Kind.QUIZ_NEEDS_REVIEW,
        target_type="submission",
        target_id=sub.pk,
        data={"course_slug": "c1", "node_pk": sub.unit_id},
    )
    assert services.notification_url(needs_review) == reverse(
        "courses:manage_review_submission",
        kwargs={"slug": "c1", "submission_pk": sub.pk},
    )
    graded = Notification(
        kind=Notification.Kind.QUIZ_GRADED,
        target_type="submission",
        target_id=sub.pk,
        data={"course_slug": "c1", "node_pk": sub.unit_id},
    )
    assert services.notification_url(graded) == reverse(
        "courses:quiz_results", kwargs={"slug": "c1", "node_pk": sub.unit_id}
    )
    enrolled = Notification(
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=course.pk,
        data={"course_slug": "c1"},
    )
    assert services.notification_url(enrolled) == reverse(
        "courses:course_outline", kwargs={"slug": "c1"}
    )


def test_url_none_when_slug_missing():
    n = Notification(
        kind=Notification.Kind.ENROLLED, target_type="course", target_id=1, data={}
    )
    assert services.notification_url(n) is None


def test_list_requires_login(client):
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code in (302, 301)  # redirect to login


def test_list_shows_only_own(client):
    mine = make_login(client, "owner")
    other = UserFactory()
    course = CourseFactory()
    services.notify_enrolled(mine, course)
    services.notify_enrolled(other, course)
    resp = client.get(reverse("notifications:list"))
    assert resp.status_code == 200
    rows = resp.context["page"].object_list
    assert all(n.recipient_id == mine.pk for n in rows)
    assert len(rows) == 1


def test_list_mark_all_read_gated_on_unread(client):
    # The list header's "Mark all read" appears only while unread rows exist —
    # same rule as the bell dropdown. The `?page=` suffix is unique to the list
    # header form action, so this targets it (not the bell's mark-all form).
    user = make_login(client, "owner")
    header_action = reverse("notifications:mark_all_read") + "?page="

    def _list_html():
        return client.get(reverse("notifications:list")).content.decode()

    assert header_action not in _list_html()  # empty state: hidden
    services.notify_enrolled(user, CourseFactory())
    assert header_action in _list_html()  # unread present: shown
    Notification.objects.filter(recipient=user).update(read_at=timezone.now())
    assert header_action not in _list_html()  # all read: hidden
