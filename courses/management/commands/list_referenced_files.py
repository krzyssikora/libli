"""Print every file the database references, as <volume>\\t<relative-path>.

Consumed by backup.sh (writes it to refs/<ts>.txt) and by restore.sh (fetches
exactly these paths rather than the whole mirror).

Fetching the whole mirror instead would resurrect every file deleted in the
last MIRROR_PRUNE_DAYS -- and Caddy serves /media/ straight off the volume, so
a resurrected file is reachable at its URL whether or not any row points at it.

SOURCES is a fixed list rather than a scan so the output is deterministic and
reviewable. tests/test_list_referenced_files.py asserts it is exhaustive.
"""

from django.apps import apps
from django.core.management.base import BaseCommand

# (model label, field name). The volume comes from VOLUME_BY_MODEL below and is
# emitted as the first column, so the shell consumer maps it straight to
# vol_path() with no translation table.
SOURCES = [
    ("courses.mediaasset", "file"),
    ("courses.mediaasset", "thumb"),
    ("courses.mediaasset", "web"),
    ("institution.institution", "logo"),
    ("institution.institution", "favicon"),
    ("support.issuereport", "screenshot"),
]

# Which volume each model's files live on. IssueReport.screenshot uses
# ScreenshotStorage (SUPPORT_SCREENSHOT_DIR); everything else is MEDIA_ROOT.
VOLUME_BY_MODEL = {
    "support.issuereport": "support_screenshots",
}


class Command(BaseCommand):
    help = "Print every file the database references, as <volume>\\t<path>."

    def handle(self, *args, **options):
        seen = set()
        for model_label, field_name in SOURCES:
            model = apps.get_model(model_label)
            volume = VOLUME_BY_MODEL.get(model_label, "media")
            for name in (
                model.objects.exclude(**{field_name: ""})
                .exclude(**{f"{field_name}__isnull": True})
                .values_list(field_name, flat=True)
                .iterator()
            ):
                if not name:
                    continue
                row = (volume, str(name).replace("\\", "/"))
                if row not in seen:
                    seen.add(row)
                    self.stdout.write(f"{row[0]}\t{row[1]}")
