"""Retention/purge for notifications: delete read-and-aged + orphaned rows.

A distinct concern from services.py (its own target-model map). The only entry
point is purge_notifications(); format_purge_result() is the shared message
formatter used by the management command and the PA "Purge now" button.
"""

import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.translation import gettext as _  # runtime strings → eager

from notifications.models import Notification

logger = logging.getLogger("notifications.retention")

PURGE_BATCH_SIZE = 1000


def _target_models():
    # Inverse of services._resolve_target's mapping. A target_type absent here is
    # skipped (never mass-deleted). test_target_models_covers_every_target_type
    # asserts full coverage so a future TargetType fails loudly instead of
    # silently leaving its orphans un-purged. Function-local import: avoids a
    # top-level notifications -> courses import.
    from courses.models import Course
    from courses.models import QuizSubmission

    return {
        Notification.TargetType.SUBMISSION: QuizSubmission,
        Notification.TargetType.COURSE: Course,
    }


def _resolve_window(days):
    """None -> Institution setting; validate 0..MAX_RETENTION_DAYS. Function-local
    institution import keeps a single source of truth with no top-level cycle."""
    from institution.models import MAX_RETENTION_DAYS
    from institution.models import Institution

    if days is None:
        days = Institution.load().notification_retention_days
    if days < 0 or days > MAX_RETENTION_DAYS:
        raise ValueError(
            f"retention window must be 0..{MAX_RETENTION_DAYS}, got {days}"
        )
    return days


def purge_notifications(*, days=None, dry_run=False) -> dict:
    days = _resolve_window(days)

    # Orphaned first (regardless of read state) — DB-side correlated subquery.
    orphaned_ids = set()
    for target_type, model in _target_models().items():
        qs = Notification.objects.filter(target_type=target_type).exclude(
            target_id__in=model.objects.values("pk")
        )
        orphaned_ids.update(qs.values_list("pk", flat=True))

    # Read + aged (strict <), disjoint from orphaned so counts don't double.
    read_aged_ids = set()
    if days > 0:
        cutoff = timezone.now() - timedelta(days=days)
        qs = Notification.objects.filter(read_at__isnull=False, created_at__lt=cutoff)
        read_aged_ids = set(qs.values_list("pk", flat=True)) - orphaned_ids

    counts = {"read_aged": len(read_aged_ids), "orphaned": len(orphaned_ids)}

    if not dry_run:
        all_ids = list(orphaned_ids | read_aged_ids)  # set is not sliceable
        for i in range(0, len(all_ids), PURGE_BATCH_SIZE):
            chunk = all_ids[i : i + PURGE_BATCH_SIZE]
            Notification.objects.filter(pk__in=chunk).delete()

    logger.info(
        "retention purge (dry_run=%s, days=%s): %s read, %s orphaned",
        dry_run,
        days,
        counts["read_aged"],
        counts["orphaned"],
    )
    return counts


def format_purge_result(counts, *, dry_run):
    """Canonical user-facing message for both the command and the PA button.
    Placeholder keys match the counts dict, so `template % counts` needs no
    remapping. label:number form (no plural agreement — Polish-safe)."""
    template = (
        _("Would purge — read: %(read_aged)d, orphaned: %(orphaned)d")
        if dry_run
        else _("Notifications purged — read: %(read_aged)d, orphaned: %(orphaned)d")
    )
    return template % counts
