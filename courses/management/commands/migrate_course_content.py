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
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db.models import Count

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import MediaAsset
from courses.transfer.export import build_export
from courses.transfer.export import write_archive_from
from courses.transfer.importer import import_subtree
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import KIND_SUBTREE
from courses.transfer.schema import TransferError

# The bundle-level completion marker. Written ONCE by `export`, only after
# every part has exported successfully, so its mere presence means "this
# bundle is a complete, single-vintage export" -- never a partial or mixed one.
# It carries the SOURCE's own tallies, frozen at that moment (never re-derived
# from whatever files a bundle directory happens to hold later), plus the
# media cross-part-sharing table. `import` refuses to graft anything unless
# this manifest is present and its declared part_count matches the archives
# actually on disk; `verify` reconciles the target against these recorded
# tallies rather than against archives that may since have been edited,
# replaced, or partially deleted.
MANIFEST_NAME = "bundle-manifest.json"

# Written by `import`, once, at the TRUE start of a migration through this
# bundle -- i.e. the first invocation for which no such file yet exists.
# It freezes the target's pre-migration counts, so that:
#   - a later `--start-at K` resume validates its invariant against what the
#     target held BEFORE this migration touched it, not against 0 -- wrong
#     the moment `--force` put content there before part 0 ever committed;
#   - `verify` can tell this migration's own contribution apart from
#     anything the target already owned (also relevant after `--force`).
BASELINE_NAME = "import-baseline.json"

# Archive filenames are "<order>-<slug>.zip"; `order` is NOT zero-padded to a
# fixed width (`{order:02d}` is a MINIMUM width), so at >=100 parts a
# lexicographic sort of the names is wrong (e.g. "100-x.zip" < "20-x.zip" as
# text). Every site that needs an archive's part order parses this prefix as
# an integer and sorts on THAT.
_ARCHIVE_NAME_RE = re.compile(r"^(\d+)-")

# Flags that belong to exactly one action. Anything used outside its action is
# rejected rather than silently ignored -- --allow-problems is a content-loss
# decision about EXPORT and must never double as an import override.
#
# --source-slug, --target-slug and --bundle-dir are deliberately NOT in this
# matrix. They are not "belongs to exactly one action" toggles -- they are
# per-action REQUIRED values, already validated by an explicit
# `if not o.get(...)` at the top of each action method, and --target-slug is
# legitimately shared by both `import` and `verify`. The risk this matrix
# guards against is a CONTROL flag silently doing nothing in the wrong
# action (e.g. --force on export); a slug argument for the wrong course
# fails loudly on its own (Course.DoesNotExist), so folding it into this
# single-owner model would not add safety.
_ACTION_FLAGS = {
    "export": {"allow_problems", "clean"},
    "import": {"as_user", "dry_run", "force", "start_at"},
    "verify": set(),
}

# The "not supplied" value per flag, compared with `is` rather than `==`.
# `--start-at 0` is a LEGAL resume index, and `0 == False` in Python, so an
# equality check against a (None, False) tuple would silently let it through.
_FLAG_UNSET = {
    "allow_problems": False,
    "clean": False,
    "dry_run": False,
    "force": False,
    "as_user": None,
    "start_at": None,
}


class Command(BaseCommand):
    help = "Move course content between databases via the transfer engine."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=("export", "import", "verify"),
            help=(
                "export: read the source course (this process's database) and "
                "write a bundle to --bundle-dir. import: graft a bundle into "
                "an existing --target-slug course (this process's database). "
                "verify: reconcile the target against the bundle's own "
                "recorded tallies, after an import."
            ),
        )
        parser.add_argument(
            "--source-slug",
            help="export only (required): slug of the course to read from.",
        )
        parser.add_argument(
            "--target-slug",
            help="import/verify only (required): slug of the existing course "
            "to graft into, or check.",
        )
        parser.add_argument(
            "--bundle-dir",
            required=True,
            help="directory holding the archive bundle -- written by export, "
            "read by import and verify.",
        )
        parser.add_argument(
            "--allow-problems",
            action="store_true",
            help="export only: proceed even though build_export reported "
            "problems (missing media placeholdered, dropped videos, broken "
            "elements) for some part. Without this flag any problem aborts "
            "the export for that part.",
        )
        parser.add_argument(
            "--clean",
            action="store_true",
            help="export only: remove any archives/manifest already present "
            "in --bundle-dir before writing. Without this flag, exporting "
            "into a non-empty bundle directory is refused -- a bundle is "
            "never silently merged into.",
        )
        parser.add_argument(
            "--as-user",
            help="import only (required): email of the user resolved and "
            "stamped as MediaAsset.uploaded_by on every re-materialised asset.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="import only: open and validate every archive and report "
            "counts, writing nothing to the target database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="import only: graft into a target that already has "
            "top-level content nodes. Without this flag, a non-empty target "
            "aborts (the double-run guard).",
        )
        parser.add_argument(
            "--start-at",
            type=int,
            help="import only: resume a partially-committed import at part "
            "order K (graft archives with order >= K). Before grafting, the "
            "command verifies the target holds exactly "
            "(pre-migration top-level nodes + K) top-level nodes -- an "
            "operator-supplied index that is CHECKED against that recorded "
            "baseline, never trusted outright.",
        )

    def handle(self, *args, **o):
        action = o["action"]
        self._reject_foreign_flags(action, o)
        if action == "export":
            self._export(o)
        elif action == "import":
            self._import(o)
        else:
            self._verify(o)

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

    # --- shared bundle helpers ------------------------------------------

    def _bundle_archives(self, bundle):
        """Archives sorted by the INTEGER part order parsed from their
        filename prefix -- never by filename text, which breaks at >=100
        parts (see _ARCHIVE_NAME_RE)."""
        found = sorted(bundle.glob("*.zip"))
        if not found:
            raise CommandError(
                f"no archives in {bundle} -- an import that grafts nothing "
                f"would be indistinguishable from a completed migration"
            )
        bad = [p.name for p in found if not _ARCHIVE_NAME_RE.match(p.name)]
        if bad:
            raise CommandError(
                f"{bundle} contains archive(s) not named "
                f"'<order>-<slug>.zip': {bad} -- refusing to guess their "
                f"part order"
            )
        return sorted(found, key=lambda p: self._archive_order(p.name))

    def _archive_order(self, name):
        return int(_ARCHIVE_NAME_RE.match(name).group(1))

    def _read_bundle_manifest(self, bundle, archives):
        """The completeness gate shared by `import` and `verify`: refuse a
        bundle whose export never completed, or whose archives on disk no
        longer match what the manifest declares -- BEFORE anything else runs,
        so a Frankenstein bundle (part of one export, part of another) is
        caught before any destructive step, not after."""
        path = bundle / MANIFEST_NAME
        if not path.exists():
            raise CommandError(
                f"{MANIFEST_NAME} is missing from {bundle}; the export that "
                f"produced this bundle did not complete (or the bundle "
                f"predates --clean support), so it cannot be trusted"
            )
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"{MANIFEST_NAME} in {bundle} is not valid JSON: {exc}"
            ) from exc
        declared = manifest.get("part_count")
        if len(archives) != declared:
            raise CommandError(
                f"{MANIFEST_NAME} declares {declared} part(s), but {bundle} "
                f"holds {len(archives)} archive(s) -- the bundle is "
                f"incomplete or mixes archives from more than one export"
            )
        return manifest

    def _capture_baseline(self, target):
        """The target's own state, captured before this migration touches it.
        Both the `--start-at` invariant and `verify` compare against this
        rather than assuming the target started empty -- true for the
        standard prepared-empty-target workflow, false the moment `--force`
        is used."""
        nodes = ContentNode.objects.filter(course=target)
        kind_counts = {
            row["kind"]: row["n"]
            for row in nodes.values("kind").annotate(n=Count("pk"))
        }
        return {
            "top_nodes": nodes.filter(parent__isnull=True).count(),
            "all_nodes": nodes.count(),
            "kind_counts": kind_counts,
            "elements": Element.objects.filter(unit__course=target).count(),
            "media": MediaAsset.objects.filter(course=target).count(),
        }

    # --- export ----------------------------------------------------------

    def _export(self, o):
        if not o.get("source_slug"):
            raise CommandError("export requires --source-slug")
        try:
            course = Course.objects.get(slug=o["source_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['source_slug']!r}") from exc

        bundle = Path(o["bundle_dir"])
        bundle.mkdir(parents=True, exist_ok=True)

        stale_zips = list(bundle.glob("*.zip"))
        stale_manifest = bundle / MANIFEST_NAME
        if (stale_zips or stale_manifest.exists()) and not o.get("clean"):
            raise CommandError(
                f"{bundle} already holds {len(stale_zips)} archive(s) from "
                f"an earlier export; pass --clean to remove them first, or "
                f"point --bundle-dir at an empty directory. A bundle is "
                f"never merged into -- a re-export that stops partway "
                f"through would otherwise leave old and new parts side by "
                f"side, indistinguishable."
            )
        if o.get("clean"):
            for z in stale_zips:
                z.unlink()
            if stale_manifest.exists():
                stale_manifest.unlink()

        parts = list(
            ContentNode.objects.filter(course=course, parent__isnull=True).order_by(
                "order", "pk"
            )
        )
        if not parts:
            raise CommandError(f"course {course.slug!r} has no top-level nodes")

        # pk -> [part order, ...]. Accumulated across ALL parts and folded
        # into the manifest once, only on full success -- see MANIFEST_NAME.
        side = {}
        total_nodes = 0
        total_elements = 0
        node_kind_counts = {}
        written = set()

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
            total_nodes += len(document["nodes"])
            total_elements += len(document["elements"])
            for nd in document["nodes"]:
                node_kind_counts[nd["kind"]] = node_kind_counts.get(nd["kind"], 0) + 1

            name = f"{part.order:02d}-{course.slug}.zip"
            if name in written:
                # OrderField.pre_save's docstring states order is NOT
                # database-unique. Two top-level nodes sharing an order would
                # otherwise silently clobber one archive with the other and
                # the loop would print success for both.
                raise CommandError(
                    f"part {part.order} ({part.title!r}) would overwrite the "
                    f"archive {name!r} already written for another part in "
                    f"this export -- two top-level nodes share order="
                    f"{part.order} (ContentNode.order is not guaranteed "
                    f"unique); refusing to silently drop one"
                )
            written.add(name)
            with open(bundle / name, "wb") as fh:
                write_archive_from(manifest, document, media_assets, fh)
            self.stdout.write(f"exported part {part.order}: {name}")

        if len(written) != len(parts):  # pragma: no cover -- guarded above
            raise CommandError(
                f"exported {len(written)} archive(s) for {len(parts)} part(s)"
            )

        bundle_manifest = {
            "source_slug": course.slug,
            "part_count": len(parts),
            "tallies": {
                "total_nodes": total_nodes,
                "node_kind_counts": node_kind_counts,
                "total_elements": total_elements,
                "media_count": len(side),
            },
            "media_parts": side,
        }
        (bundle / MANIFEST_NAME).write_text(
            json.dumps(bundle_manifest, ensure_ascii=False), encoding="utf-8"
        )
        self.stdout.write(
            f"wrote {MANIFEST_NAME} ({total_nodes} nodes, {total_elements} "
            f"elements, {len(side)} distinct media asset(s))"
        )

    # --- import ------------------------------------------------------------

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
        self._read_bundle_manifest(bundle, archives)  # completeness gate
        ordered = [(self._archive_order(p.name), p) for p in archives]

        start_at = o.get("start_at")
        baseline_path = bundle / BASELINE_NAME

        if start_at is None:
            # A fresh start -- always re-captures the baseline now,
            # overwriting any left over from an earlier migration through
            # this bundle/target pair.
            baseline = self._capture_baseline(target)
            existing = baseline["top_nodes"]
            # Double-run guard: grafting into a non-empty target would
            # append a SECOND copy of every part.
            if existing and not o.get("force"):
                raise CommandError(
                    f"target {target.slug!r} already has {existing} "
                    f"top-level node(s); pass --force to graft anyway, or "
                    f"--start-at to resume a partial run"
                )
            todo = ordered
            if not o.get("dry_run"):
                baseline_path.write_text(
                    json.dumps(baseline, ensure_ascii=False), encoding="utf-8"
                )
        else:
            # A resume, including the degenerate K=0 case. Reuse the
            # baseline the run that began this migration recorded, if any;
            # a target that has never had this bundle grafted into it has no
            # such record yet, so capture it fresh (this is the same value
            # `start_at is None` would have captured, and only start_at == 0
            # can possibly satisfy the invariant against it).
            if baseline_path.exists():
                try:
                    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise CommandError(
                        f"{BASELINE_NAME} in {bundle} is not valid JSON: {exc}"
                    ) from exc
            else:
                baseline = self._capture_baseline(target)

            existing = ContentNode.objects.filter(
                course=target, parent__isnull=True
            ).count()
            expected_existing = baseline["top_nodes"] + start_at
            if existing != expected_existing:
                raise CommandError(
                    f"--start-at {start_at} expects the target to hold "
                    f"exactly {expected_existing} top-level node(s) "
                    f"({baseline['top_nodes']} pre-existing + {start_at} "
                    f"committed part(s)), but it holds {existing}"
                )
            todo = [(order, path) for order, path in ordered if order >= start_at]
            if not o.get("dry_run") and not baseline_path.exists():
                baseline_path.write_text(
                    json.dumps(baseline, ensure_ascii=False), encoding="utf-8"
                )
            if not todo:
                self.stdout.write(
                    f"nothing to do: --start-at {start_at} is at or beyond "
                    f"the bundle's {len(archives)} part(s); this migration "
                    f"is already complete"
                )
                return

        committed = None
        for order, archive in todo:
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

    # --- verify --------------------------------------------------------

    def _verify(self, o):
        if not o.get("target_slug"):
            raise CommandError("verify requires --target-slug")
        try:
            target = Course.objects.get(slug=o["target_slug"])
        except Course.DoesNotExist as exc:
            raise CommandError(f"no course with slug {o['target_slug']!r}") from exc

        bundle = Path(o["bundle_dir"])
        archives = self._bundle_archives(bundle)
        bundle_manifest = self._read_bundle_manifest(bundle, archives)

        baseline_path = bundle / BASELINE_NAME
        if not baseline_path.exists():
            raise CommandError(
                f"{BASELINE_NAME} is missing from {bundle}; run `import` "
                f"before `verify` so the pre-migration baseline is on record"
            )
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"{BASELINE_NAME} in {bundle} is not valid JSON: {exc}"
            ) from exc

        # Cross-check the archives themselves still agree with what the
        # manifest recorded -- corruption or a hand-edited bundle after
        # export would otherwise slip past a manifest-only check. Any
        # TransferError from a damaged archive must surface as a
        # CommandError, never a raw traceback.
        declared_nodes = 0
        for archive in archives:
            with open(archive, "rb") as fh:
                try:
                    with open_archive(fh, expected_kind=KIND_SUBTREE) as (
                        _zf,
                        _manifest,
                        document,
                        _entries,
                    ):
                        declared_nodes += len(document["nodes"])
                except TransferError as exc:
                    raise CommandError(f"{archive.name}: {exc}") from exc

        tallies = bundle_manifest["tallies"]
        if declared_nodes != tallies["total_nodes"]:
            raise CommandError(
                f"bundle inconsistency: the archives in {bundle} declare "
                f"{declared_nodes} node(s) total, but {MANIFEST_NAME} "
                f"recorded {tallies['total_nodes']} -- the bundle was "
                f"modified after export"
            )

        expected_nodes = baseline["all_nodes"] + tallies["total_nodes"]
        actual_nodes = ContentNode.objects.filter(course=target).count()
        if actual_nodes != expected_nodes:
            raise CommandError(
                f"node count mismatch: expected {expected_nodes} "
                f"({baseline['all_nodes']} pre-existing + "
                f"{tallies['total_nodes']} from the bundle), target "
                f"{target.slug!r} holds {actual_nodes}"
            )

        for kind, n in tallies["node_kind_counts"].items():
            expected_kind = baseline["kind_counts"].get(kind, 0) + n
            actual_kind = ContentNode.objects.filter(course=target, kind=kind).count()
            if actual_kind != expected_kind:
                raise CommandError(
                    f"node count mismatch for kind {kind!r}: expected "
                    f"{expected_kind}, target {target.slug!r} holds "
                    f"{actual_kind}"
                )

        expected_elements = baseline["elements"] + tallies["total_elements"]
        actual_elements = Element.objects.filter(unit__course=target).count()
        if actual_elements != expected_elements:
            raise CommandError(
                f"element count mismatch: expected {expected_elements}, "
                f"target {target.slug!r} holds {actual_elements}"
            )

        # Media is an EXACT count, not a floor: _create_media materialises
        # one MediaAsset row per document["media"] entry, from the same list
        # the side table is built from, so the total is fully determined --
        # an asset referenced from N parts is re-materialised exactly N
        # times, never more, never fewer.
        table = bundle_manifest["media_parts"]
        bundle_media = sum(len(parts) for parts in table.values())
        expected_media = baseline["media"] + bundle_media
        actual_media = MediaAsset.objects.filter(course=target).count()
        if actual_media != expected_media:
            raise CommandError(
                f"media count mismatch: expected {expected_media} "
                f"({baseline['media']} pre-existing + {bundle_media} from "
                f"the bundle, accounting for cross-part sharing), target "
                f"{target.slug!r} holds {actual_media}"
            )

        shared = {k: v for k, v in table.items() if len(v) > 1}
        self.stdout.write(
            f"OK: {actual_nodes} nodes, {actual_elements} elements, "
            f"{actual_media} media ({len(shared)} asset(s) shared across "
            f"parts)"
        )
