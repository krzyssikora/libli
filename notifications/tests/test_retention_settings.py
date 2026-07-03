from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from institution.models import Institution
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_notifications_tab_renders_field_for_pa(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings") + "?tab=notifications")
    assert resp.status_code == 200
    assert resp.context["active_tab"] == "notifications"
    assert "notifications" in resp.context  # the RetentionForm
    assert "notification_retention_days" in resp.content.decode()


def test_save_persists_retention_window(client):
    make_pa(client, "pa")
    resp = client.post(
        reverse("institution:settings_notifications"),
        {"notification_retention_days": 45},
    )
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=notifications")
    assert Institution.load().notification_retention_days == 45


def test_save_rejects_over_ceiling_and_does_not_persist(client):
    # Covers the "form" half of the 0..MAX_RETENTION_DAYS invariant (the model
    # field's MaxValueValidator runs during ModelForm validation).
    make_pa(client, "pa")
    before = Institution.load().notification_retention_days
    resp = client.post(
        reverse("institution:settings_notifications"),
        {"notification_retention_days": 9999},  # > MAX_RETENTION_DAYS (3650)
    )
    assert resp.status_code == 200  # invalid -> re-render with errors, not a 302 save
    assert Institution.load().notification_retention_days == before


def test_purge_button_deletes_seeded_rows_and_flashes_counts(client):
    make_pa(client, "pa")
    inst = Institution.load()
    inst.notification_retention_days = 30
    inst.save()
    u = UserFactory()
    c = CourseFactory()
    # aged-read: backdated well beyond the 30-day window
    aged = Notification.objects.create(
        recipient=u,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=c.pk,
        read_at=timezone.now(),
        data={},
    )
    Notification.objects.filter(pk=aged.pk).update(
        created_at=timezone.now() - timedelta(days=60)
    )
    # orphaned: points at a deleted course
    dead = CourseFactory()
    dead_pk = dead.pk
    dead.delete()
    orphan = Notification.objects.create(
        recipient=u,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=dead_pk,
        read_at=None,
        data={},
    )
    resp = client.post(reverse("institution:settings_notifications_purge"), follow=True)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "read: 1" in body and "orphaned: 1" in body
    assert not Notification.objects.filter(pk__in=[aged.pk, orphan.pk]).exists()


def test_settings_views_are_pa_only(client):
    make_login(client, "plain")  # non-PA
    assert (
        client.post(
            reverse("institution:settings_notifications"),
            {"notification_retention_days": 45},
        ).status_code
        == 403
    )
    assert (
        client.post(reverse("institution:settings_notifications_purge")).status_code
        == 403
    )


def test_purge_get_redirects_to_tab(client):
    make_pa(client, "pa")
    resp = client.get(reverse("institution:settings_notifications_purge"))
    assert resp.status_code == 302
    assert resp["Location"].endswith("?tab=notifications")
