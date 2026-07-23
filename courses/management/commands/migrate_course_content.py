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

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError

from courses.models import ContentNode
from courses.models import Course
from courses.transfer.export import build_export
from courses.transfer.export import write_archive_from
from courses.transfer.importer import import_subtree
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError

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
        elif action == "import":
            self._import(o)
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

    # --- import --------------------------------------------------------

    def _bundle_archives(self, bundle):
        """Archives in part order, taken from the zero-padded filename prefix.

        Deterministic naming means order is recoverable without opening every
        archive to read its manifest.
        """
        archives = sorted(bundle.glob("*.zip"))
        if not archives:
            raise CommandError(
                f"no archives in {bundle} -- an import that grafts nothing "
                f"would be indistinguishable from a completed migration"
            )
        return archives

    def _import(self, o):
        if not o.get("target_slug"):
            raise CommandError("import requires --target-slug")
        if not o.get("as_user"):
            raise CommandError(
                "import requires --as-user: it is stamped on every "
                "re-materialised MediaAsset.uploaded_by"
            )
        try:
            target = Course.objects.get(slug=o["target_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['target_slug']!r}") from exc
        try:
            user = get_user_model().objects.get(email=o["as_user"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"no user with email {o['as_user']!r}") from exc

        bundle = Path(o["bundle_dir"])
        archives = self._bundle_archives(bundle)

        existing = ContentNode.objects.filter(
            course=target, parent__isnull=True
        ).count()
        start_at = o.get("start_at")

        if start_at is None:
            # Double-run guard: grafting into a non-empty target would append a
            # SECOND copy of every part.
            if existing and not o.get("force"):
                raise CommandError(
                    f"target {target.slug!r} already has {existing} top-level "
                    f"node(s); pass --force to graft anyway, or --start-at to "
                    f"resume a partial run"
                )
            todo = archives
        else:
            # Resume: the operator supplies the intent, the command checks the
            # fact. A mistyped K would otherwise silently skip or duplicate a
            # part -- exactly what the double-run guard it bypasses prevents.
            if existing != start_at:
                raise CommandError(
                    f"--start-at {start_at} expects the target to hold exactly "
                    f"{start_at} top-level node(s), but it holds {existing}"
                )
            todo = [a for a in archives if int(a.name[:2]) >= start_at]

        committed = None
        for archive in todo:
            order = int(archive.name[:2])
            try:
                with open(archive, "rb") as fh:
                    with open_archive(fh, expected_kind=KIND_SUBTREE) as (
                        zf,
                        manifest,
                        document,
                        media_entries,
                    ):
                        validate_archive_document(
                            zf,
                            manifest,
                            document,
                            media_entries,
                            kind=KIND_SUBTREE,
                            target_course=target,
                        )
                        n_nodes = len(document["nodes"])
                        n_els = len(document["elements"])
                        n_media = len(document["media"])
                        if o.get("dry_run"):
                            self.stdout.write(
                                f"[dry-run] {archive.name}: {n_nodes} nodes, "
                                f"{n_els} elements, {n_media} media"
                            )
                            continue
                        # insertion_node=None -> top level. All positional.
                        import_subtree(
                            zf,
                            manifest,
                            document,
                            media_entries,
                            target,
                            None,
                            user,
                        )
            except TransferError as exc:
                # Recovery guidance belongs HERE, on the failure path -- a
                # trailing "no parts committed" line after the loop would be
                # unreachable, because this CommandError propagates out of it.
                if committed is None:
                    hint = "no parts committed; re-run import from the start"
                else:
                    hint = (
                        f"last part committed: {committed}; "
                        f"resume with --start-at {committed + 1}"
                    )
                raise CommandError(f"{archive.name}: {exc}\n{hint}") from exc
            committed = order
            self.stdout.write(f"grafted part {order} from {archive.name}")

        if o.get("dry_run"):
            self.stdout.write("[dry-run] validated; nothing written")
        else:
            self.stdout.write(f"last part committed: {committed}")
