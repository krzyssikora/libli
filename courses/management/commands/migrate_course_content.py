"""Move a course's content between databases via the transfer engine.

Two phases with a bundle directory between them, because a Django process
binds one database: `export` runs against the source, `import` against the
target, and `verify` reconciles afterwards.

Content moves ONE TOP-LEVEL PART AT A TIME. That is not incidental --
import_course() would create a second course beside the prepared target, and
validate_document() caps each archive at TRANSFER_MAX_ELEMENTS/MEDIA_ENTRIES,
which a whole-course archive of a large course would breach outright.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from courses.models import ContentNode
from courses.models import Course
from courses.transfer.export import build_export
from courses.transfer.export import write_archive_from

SIDE_TABLE = "media-parts.json"

# Flags that belong to exactly one action. Anything used outside its action is
# rejected rather than silently ignored -- --allow-problems is a content-loss
# decision about EXPORT and must never double as an import override.
_ACTION_FLAGS = {
    "export": {"allow_problems"},
    "import": {"as_user", "dry_run", "force", "start_at"},
    "verify": set(),
}

# The "not supplied" value per flag, compared with `is` rather than `==`.
# `--start-at 0` is a LEGAL resume index, and `0 == False` in Python, so an
# equality check against a (None, False) tuple would silently let it through.
_FLAG_UNSET = {
    "allow_problems": False,
    "dry_run": False,
    "force": False,
    "as_user": None,
    "start_at": None,
}


class Command(BaseCommand):
    help = "Move course content between databases via the transfer engine."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("export", "import", "verify"))
        parser.add_argument("--source-slug")
        parser.add_argument("--target-slug")
        parser.add_argument("--bundle-dir", required=True)
        parser.add_argument("--allow-problems", action="store_true")
        parser.add_argument("--as-user")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--start-at", type=int)

    def handle(self, *args, **o):
        action = o["action"]
        self._reject_foreign_flags(action, o)
        if action == "export":
            self._export(o)
        else:  # pragma: no cover - later tasks
            raise CommandError(f"action not implemented yet: {action}")

    def _reject_foreign_flags(self, action, o):
        mine = _ACTION_FLAGS[action]
        for other, flags in _ACTION_FLAGS.items():
            if other == action:
                continue
            for flag in flags - mine:
                if o.get(flag) is not _FLAG_UNSET[flag]:
                    raise CommandError(
                        f"--{flag.replace('_', '-')} is not valid for the "
                        f"{action!r} action (it belongs to {other!r})."
                    )

    # --- export --------------------------------------------------------

    def _export(self, o):
        if not o.get("source_slug"):
            raise CommandError("export requires --source-slug")
        try:
            course = Course.objects.get(slug=o["source_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['source_slug']!r}") from exc

        bundle = Path(o["bundle_dir"])
        bundle.mkdir(parents=True, exist_ok=True)

        parts = list(
            ContentNode.objects.filter(course=course, parent__isnull=True).order_by(
                "order", "pk"
            )
        )
        if not parts:
            raise CommandError(f"course {course.slug!r} has no top-level nodes")

        # pk -> [part order, ...]. Accumulated across ALL parts and written
        # once, only on full success: a partial table would make `verify`
        # under-report cross-part sharing and turn a legitimate media delta
        # into an apparent fault.
        side = {}

        for part in parts:
            manifest, document, media_assets, problems = build_export(course, node=part)
            if problems and not o.get("allow_problems"):
                raise CommandError(
                    f"part {part.order} ({part.title!r}) exported with "
                    f"{len(problems)} problem(s): {problems}. "
                    f"Re-run with --allow-problems to accept them."
                )
            for _mid, asset, _is_placeholder in media_assets:
                side.setdefault(str(asset.pk), []).append(part.order)

            name = f"{part.order:02d}-{course.slug}.zip"
            with open(bundle / name, "wb") as fh:
                write_archive_from(manifest, document, media_assets, fh)
            self.stdout.write(f"exported part {part.order}: {name}")

        (bundle / SIDE_TABLE).write_text(
            json.dumps(side, ensure_ascii=False), encoding="utf-8"
        )
        self.stdout.write(f"wrote {SIDE_TABLE} ({len(side)} asset(s))")
