"""Support receivers: screenshot cleanup (here) and cache invalidation (Task 2)."""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from support.models import IssueReport


@receiver(post_delete, sender=IssueReport)
def delete_screenshot_file(sender, instance, **kwargs):
    """Django does not remove files on model delete. Orphaned screenshots of
    student data accumulating on disk is exactly the failure mode to avoid."""
    if instance.screenshot:
        instance.screenshot.delete(save=False)
