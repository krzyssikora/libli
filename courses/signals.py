"""Signal receivers for the courses app (wired in CoursesConfig.ready)."""

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from courses.models import MediaAsset


@receiver(post_delete, sender=MediaAsset)
def _delete_mediaasset_file(sender, instance, **kwargs):
    """Remove the backing file from storage when a MediaAsset row is deleted.

    Django's FileField never deletes the underlying file on model deletion, so
    without this every deleted asset would orphan a file on disk. post_delete
    (not the model's delete()) is used deliberately: a cascade delete — e.g.
    deleting a Course, which cascade-removes its MediaAssets — bulk-deletes rows
    and fires post_delete per instance but never calls Model.delete(). Deferred
    to on_commit so a rolled-back delete can't strand a live row whose file is
    already gone; guarded so a blank or already-missing file is a no-op.
    """
    file = instance.file
    if not file:
        return
    name = file.name
    storage = file.storage

    def _remove():
        if name and storage.exists(name):
            storage.delete(name)

    transaction.on_commit(_remove)
