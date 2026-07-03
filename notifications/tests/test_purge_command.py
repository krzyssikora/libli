from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from institution.models import MAX_RETENTION_DAYS
from institution.models import Institution
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _aged_read(user, course, days_old):
    n = Notification.objects.create(
        recipient=user,
        kind=Notification.Kind.ENROLLED,
        target_type="course",
        target_id=course.pk,
        read_at=timezone.now(),
        data={},
    )
    Notification.objects.filter(pk=n.pk).update(
        created_at=timezone.now() - timedelta(days=days_old)
    )
    return n


def test_plain_run_deletes_and_prints():
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    out = StringIO()
    call_command("purge_notifications", stdout=out)
    assert "Notifications purged" in out.getvalue()
    assert Notification.objects.count() == 0


def test_dry_run_prints_would_purge_and_deletes_nothing():
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    out = StringIO()
    call_command("purge_notifications", "--dry-run", stdout=out)
    assert "Would purge" in out.getvalue()
    assert Notification.objects.count() == 1


def test_days_overrides_setting():
    inst = Institution.load()
    inst.notification_retention_days = 0  # setting would skip age purge
    inst.save()
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    call_command("purge_notifications", "--days", "90")  # explicit override
    assert Notification.objects.count() == 0


def test_negative_and_over_max_raise_command_error():
    u = UserFactory()
    c = CourseFactory()
    _aged_read(u, c, 100)
    for bad in ("-1", str(MAX_RETENTION_DAYS + 1)):
        with pytest.raises(CommandError):
            call_command("purge_notifications", "--days", bad)
    assert Notification.objects.count() == 1  # nothing deleted
