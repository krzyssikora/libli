"""Support receivers: screenshot cleanup and support-config cache invalidation."""

from django.db.models.signals import m2m_changed
from django.db.models.signals import post_delete
from django.db.models.signals import post_save
from django.dispatch import receiver

from support.models import IssueReport
from support.models import SupportSettings
from support.policy import invalidate_support_config


@receiver(post_delete, sender=IssueReport)
def delete_screenshot_file(sender, instance, **kwargs):
    """Django does not remove files on model delete. Orphaned screenshots of
    student data accumulating on disk is exactly the failure mode to avoid."""
    if instance.screenshot:
        instance.screenshot.delete(save=False)


post_save.connect(invalidate_support_config, sender=SupportSettings)
# The m2m receiver is the easy one to omit, and omitting it means a newly-granted
# teacher cannot report until the cache TTL expires — a bug that looks like
# "the setting didn't save".
m2m_changed.connect(
    invalidate_support_config, sender=SupportSettings.extra_reporters.through
)
