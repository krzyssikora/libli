from datetime import timedelta
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from institution.models import MAX_RETENTION_DAYS
from institution.models import Institution
from notifications.models import Notification
from notifications.retention import format_purge_result
from notifications.retention import purge_notifications
from tests.factories import CourseFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_retention_field_default_is_90():
    assert Institution.load().notification_retention_days == 90


def test_retention_field_rejects_over_ceiling():
    inst = Institution.load()
    inst.notification_retention_days = MAX_RETENTION_DAYS + 1
    with pytest.raises(ValidationError):
        inst.full_clean()


def test_retention_field_accepts_zero_and_ceiling():
    inst = Institution.load()
    for v in (0, MAX_RETENTION_DAYS):
        inst.notification_retention_days = v
        inst.full_clean()  # no raise


def _notif(user, *, ttype, tid, read, days_old=None, kind=Notification.Kind.ENROLLED):
    n = Notification.objects.create(
        recipient=user,
        kind=kind,
        target_type=ttype,
        target_id=tid,
        read_at=timezone.now() if read else None,
        data={},
    )
    if days_old is not None:
        Notification.objects.filter(pk=n.pk).update(
            created_at=timezone.now() - timedelta(days=days_old)
        )
    return n


def test_read_aged_deleted_recent_and_unread_kept():
    u = UserFactory()
    c = CourseFactory()
    aged = _notif(u, ttype="course", tid=c.pk, read=True, days_old=100)
    recent = _notif(u, ttype="course", tid=c.pk, read=True, days_old=10)
    unread_aged = _notif(u, ttype="course", tid=c.pk, read=False, days_old=100)
    counts = purge_notifications(days=90)
    assert counts["read_aged"] == 1
    assert not Notification.objects.filter(pk=aged.pk).exists()
    assert Notification.objects.filter(pk=recent.pk).exists()
    assert Notification.objects.filter(pk=unread_aged.pk).exists()


def test_orphaned_deleted_including_unread_alive_kept():
    u = UserFactory()
    alive = CourseFactory()
    dead = CourseFactory()
    dead_pk = dead.pk
    dead.delete()
    orphan_unread = _notif(u, ttype="course", tid=dead_pk, read=False, days_old=1)
    alive_row = _notif(u, ttype="course", tid=alive.pk, read=False, days_old=1)
    counts = purge_notifications(days=90)
    assert counts["orphaned"] == 1
    assert not Notification.objects.filter(pk=orphan_unread.pk).exists()
    assert Notification.objects.filter(pk=alive_row.pk).exists()


def test_row_both_aged_and_orphaned_counted_once():
    u = UserFactory()
    c = CourseFactory()
    c_pk = c.pk
    c.delete()  # orphaned
    both = _notif(u, ttype="course", tid=c_pk, read=True, days_old=100)  # also aged
    counts = purge_notifications(days=90)
    assert counts == {"read_aged": 0, "orphaned": 1}  # counted once, as orphaned
    assert not Notification.objects.filter(pk=both.pk).exists()


def test_days_zero_skips_age_but_orphans_purged():
    u = UserFactory()
    alive = CourseFactory()  # aged row points here so it is NOT orphaned
    dead = CourseFactory()
    dead_pk = dead.pk
    aged = _notif(u, ttype="course", tid=alive.pk, read=True, days_old=100)
    dead.delete()
    orphan = _notif(u, ttype="course", tid=dead_pk, read=False, days_old=1)
    counts = purge_notifications(days=0)
    assert counts == {"read_aged": 0, "orphaned": 1}
    assert Notification.objects.filter(pk=aged.pk).exists()  # age skipped
    assert not Notification.objects.filter(pk=orphan.pk).exists()


def test_days_none_uses_institution_setting():
    inst = Institution.load()
    inst.notification_retention_days = 30
    inst.save()
    u = UserFactory()
    c = CourseFactory()
    aged = _notif(u, ttype="course", tid=c.pk, read=True, days_old=40)
    kept = _notif(u, ttype="course", tid=c.pk, read=True, days_old=20)
    counts = purge_notifications(days=None)
    assert counts["read_aged"] == 1
    assert not Notification.objects.filter(pk=aged.pk).exists()
    assert Notification.objects.filter(pk=kept.pk).exists()


def test_out_of_range_window_raises_and_deletes_nothing():
    u = UserFactory()
    c = CourseFactory()
    _notif(u, ttype="course", tid=c.pk, read=True, days_old=100)
    before = Notification.objects.count()
    for bad in (-1, MAX_RETENTION_DAYS + 1):
        with pytest.raises(ValueError):
            purge_notifications(days=bad)
    assert Notification.objects.count() == before


def test_boundary_exact_is_kept_one_second_older_deleted():
    u = UserFactory()
    c = CourseFactory()
    frozen = timezone.now()
    with mock.patch("notifications.retention.timezone.now", return_value=frozen):
        exact = _notif(u, ttype="course", tid=c.pk, read=True)
        Notification.objects.filter(pk=exact.pk).update(
            created_at=frozen - timedelta(days=30)
        )
        older = _notif(u, ttype="course", tid=c.pk, read=True)
        Notification.objects.filter(pk=older.pk).update(
            created_at=frozen - timedelta(days=30, seconds=1)
        )
        purge_notifications(days=30)
    assert Notification.objects.filter(pk=exact.pk).exists()  # exactly 30d → kept
    assert not Notification.objects.filter(pk=older.pk).exists()  # older → deleted


def test_target_models_covers_every_target_type():
    from notifications.retention import _target_models

    assert set(_target_models()) == set(Notification.TargetType)


def test_dry_run_counts_without_deleting():
    u = UserFactory()
    c = CourseFactory()
    _notif(u, ttype="course", tid=c.pk, read=True, days_old=100)
    before = Notification.objects.count()
    counts = purge_notifications(days=90, dry_run=True)
    assert counts["read_aged"] == 1
    assert Notification.objects.count() == before  # nothing deleted


def test_batching_deletes_more_than_one_batch():
    from notifications.retention import PURGE_BATCH_SIZE

    u = UserFactory()
    c = CourseFactory()
    rows = [
        Notification(
            recipient=u,
            kind=Notification.Kind.ENROLLED,
            target_type="course",
            target_id=c.pk,
            read_at=timezone.now(),
            data={},
        )
        for _ in range(PURGE_BATCH_SIZE + 5)
    ]
    Notification.objects.bulk_create(rows)
    Notification.objects.filter(recipient=u).update(
        created_at=timezone.now() - timedelta(days=100)
    )
    counts = purge_notifications(days=90)
    assert counts["read_aged"] == PURGE_BATCH_SIZE + 5
    assert Notification.objects.filter(recipient=u).count() == 0


def test_unmapped_target_type_ignored_by_orphan_pass():
    u = UserFactory()
    # A target_type not in _target_models() must never be touched by the orphan
    # pass. .create() does not enforce the field's choices, so we can store a
    # bogus type; unread so the age pass ignores it too.
    row = Notification.objects.create(
        recipient=u,
        kind=Notification.Kind.ENROLLED,
        target_type="bogus_unmapped",
        target_id=1,
        read_at=None,
        data={},
    )
    purge_notifications(days=90)
    assert Notification.objects.filter(pk=row.pk).exists()


def test_format_purge_result_real_and_dry():
    counts = {"read_aged": 142, "orphaned": 7}
    assert "read: 142" in format_purge_result(counts, dry_run=False)
    assert "orphaned: 7" in format_purge_result(counts, dry_run=False)
    assert format_purge_result(counts, dry_run=True).startswith("Would purge")
