"""Move a course's content between databases via the transfer engine.

Two phases with a bundle directory between them, because a Django process
binds one database: `export` runs against the source, `import` against the
target, and `verify` reconciles afterwards.

Content moves ONE TOP-LEVEL PART AT A TIME. That is not incidental, for two
independent reasons:

  - import_course() would create a SECOND course beside the prepared target,
    rather than grafting into it. This reason is structural and permanent.
  - A whole-course archive of a large course breaches the transfer caps. Since
    the caps were re-scaled the COUNT caps no longer bind (the largest real
    course measures 20,608 elements against a 100,000 limit and 1,191 media
    against 5,000), but the BYTE caps still do, and decisively: that same course
    carries 3.66 GB of media against a 1 GiB archive limit. Per-part archives
    are each far under it -- the largest measures 575 MB.

Do not read the second reason as "raise the byte cap and export the course in
one piece". The byte caps are sized to what the host's staging, upload-spill and
media volumes can each hold at once; this command exists so that ceiling never
has to move. See docs/deployment-course-transfer.md.
"""

import json
import os
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import DatabaseError
from django.db import transaction
from django.db.models import Count

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import MediaAsset
from courses.richtext import find_link_targets
from courses.richtext import iter_rich_text
from courses.richtext import rewrite_instance
from courses.richtext import rewrite_links
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

# Written by `import`, accumulated one entry per part, and read by the deferred
# link rewrite. It is the ONLY record of export_id -> new_pk: export ids exist
# nowhere else once an archive has been grafted, so losing this file loses the
# ability to rewrite anything. Lifecycle mirrors BASELINE_NAME -- never unlinked
# by `export --clean`, overwritten fresh when `start_at is None`.
LINK_STATE_NAME = "import-link-state.json"
LINK_STATE_VERSION = 1


def _write_state(bundle, state):
    """Serialise to <name>.tmp then os.replace onto the real name.

    NEVER truncate-in-place. Path.write_text opens mode="w", which truncates
    before writing a byte; this file is rewritten once per part (21 times for
    mat-pp) inside an open transaction, so a crash or ENOSPC in any of those
    windows would leave truncated JSON -- and a torn state file discards every
    committed part's export_id -> new_pk map, which is unrecoverable.
    """
    tmp = bundle / (LINK_STATE_NAME + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, bundle / LINK_STATE_NAME)


def _read_state(bundle, *, validate):
    """`validate=False` is for the one branch that discards the file wholesale
    (`start_at is None`, no --resolve-rewrite). Validating there could only turn
    a torn file into a permanent dead end: `export --clean` deliberately does not
    unlink this file, so the operator's only remedy would be a manual rm."""
    path = bundle / LINK_STATE_NAME
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        if not validate:
            return None
        raise CommandError(
            f"{LINK_STATE_NAME} in {bundle} is not valid JSON: {exc}"
        ) from exc
    if not validate:
        return state
    if state.get("version") != LINK_STATE_VERSION:
        raise CommandError(
            f"{LINK_STATE_NAME} in {bundle} has version "
            f"{state.get('version')!r}; this command writes and reads version "
            f"{LINK_STATE_VERSION}"
        )
    return state


def _fresh_state(target):
    return {
        "version": LINK_STATE_VERSION,
        "status": "collecting",
        "target_slug": target.slug,
        "target_pk": target.pk,
        "parts": [],
    }


def _invert_node_index(node_index, order):
    """{export_id: source_pk} for one part order.

    int(pk) is REQUIRED: node_index keys are decimal STRINGS and the `src` guard
    is a fatal equality test, so a missing int() makes it False on every part of
    every run and blocks the feature behind a spurious re-export error. This is
    THE shared helper -- called at the graft-time write and at the guard, never
    inlined at either.
    """
    return {
        eid: int(pk)
        for pk, (o, eid) in ((k, tuple(v)) for k, v in node_index.items())
        if int(o) == int(order)
    }


def _live_pks(entries, target):
    """Recorded pks of `entries`, filtered to rows that actually exist in
    `target`. Callers differ only in which entries they pass: the rewrite scope
    passes PENDING entries, the mapping's liveness filter and `verify` pass ALL
    of them."""
    recorded = {pk for e in entries for pk in e["node_map"].values()}
    return set(
        ContentNode.objects.filter(pk__in=recorded, course=target).values_list(
            "pk", flat=True
        )
    )


def _is_fail_closed(instance):
    """True iff part 2 declines to touch a body that demonstrably holds link
    targets.

    Part 2's return types carry no fail-closed flag and part 3 does not widen
    them, so this is a decidable probe rather than an observation. `not changed`
    is NOT a substitute: a body with no internal links returns exactly the same
    signal, so that rule would record most of the 20,054 elements and make
    verify's reconciliation permanently vacuous.

    Under an empty map with on_missing="unwrap" every target in a well-formed
    body is flattened; a body that holds targets and still comes back
    byte-identical with flattened == 0 is exactly part 2's fail-closed path.
    """
    for _field, value in iter_rich_text(instance):
        if not find_link_targets(value):
            continue
        probed, flattened = rewrite_links(value, {}, on_missing="unwrap")
        if probed == value and flattened == 0:
            return True
    return False


def _resume_hint(committed):
    """The recovery line every mid-loop failure in `_import`'s per-part graft
    needs -- OSError, DatabaseError and TransferError all reach this same
    decision, and it was duplicated at each site until this fix."""
    if committed is None:
        return "no parts committed; re-run import from the start"
    return f"last part committed: {committed}; resume with --start-at {committed + 1}"


def _dangling_examples(dangling, target_pks, cap=10):
    """(unit_id, element pk, href) triples for elements in `target_pks`,
    capped at `cap` regardless of how many sites cite the same target pk.

    The cap must be enforced INSIDE the inner per-site loop -- a hub node
    referenced from hundreds of elements would otherwise append every one of
    its sites before the outer per-pk loop ever re-checks the bound.
    """
    examples = []
    for pk, sites in sorted(dangling.items()):
        for unit_id, epk in sites:
            if epk in target_pks:
                examples.append((unit_id, epk, f"/courses/n/{pk}/"))
                if len(examples) >= cap:
                    return examples
    return examples


def _build_mapping(state, node_index, target):
    """(mapping, scope_pks, order_by_new_pk, scanned_orders).

    TWO pk sets, never one. Conflating them drops every node in an
    already-rewritten order from the mapping, so a link from a re-grafted part
    into an earlier one is unmapped and unwrap flattens it -- and the drop is a
    bare `continue`, so all three counters report 0 and the fatal gate below
    never fires.
    """
    pending_entries = [e for e in state["parts"] if not e["rewritten"]]
    scanned_orders = {int(e["order"]) for e in pending_entries}

    # LIVENESS for the MAPPING: every recorded order.
    live = _live_pks(state["parts"], target)
    all_recorded = {pk for e in state["parts"] for pk in e["node_map"].values()}
    skipped_dead = sorted(all_recorded - live)
    # SCOPE of the rewrite: pending orders only. _live_pks already filters, and
    # pending is a subset of all, so no further intersection is needed.
    scope_pks = _live_pks(pending_entries, target)

    by_order = {int(e["order"]): e["node_map"] for e in state["parts"]}
    order_by_new_pk = {pk: o for o, nm in by_order.items() for pk in nm.values()}

    skipped_parts, skipped_ids, mapping = [], [], {}
    for old_pk_str, pair in node_index.items():
        order, export_id = tuple(pair)
        part = by_order.get(int(order))
        if part is None:
            skipped_parts.append(int(order))
            continue
        new_pk = part.get(export_id)
        if new_pk is None:
            skipped_ids.append((int(order), export_id))
            continue
        if new_pk not in live:  # already counted in skipped_dead
            continue
        mapping[int(old_pk_str)] = new_pk

    if skipped_parts or skipped_ids or skipped_dead:
        # FATAL, before the transaction and before status flips to in_progress.
        # None of the three is reachable on a healthy migration, and each one
        # means hrefs would be unwrap-flattened irreversibly. Counted in full so
        # the message can name every offender rather than failing on the first.
        raise CommandError(
            f"refusing to run the deferred link rewrite: the bundle and "
            f"{LINK_STATE_NAME} disagree. "
            f"skipped_parts={sorted(set(skipped_parts))} "
            f"skipped_ids={sorted(set(skipped_ids))} "
            f"skipped_dead={skipped_dead}. Every one of these would flatten "
            f"links irreversibly; nothing has been changed."
        )
    return mapping, scope_pks, order_by_new_pk, scanned_orders


def _merge_rewrite(prior, per_order, fail_closed, all_orders):
    """A pass scans only the pending orders, so it REPLACES their rows and
    CARRIES the rest forward. Overwriting the whole object would discard the
    fail_closed_elements of orders it did not scan, and verify would then read
    a previously-recorded fail-closed element as an ordinary dangling one and
    raise with no remedy reachable."""
    # Capture emptiness BEFORE the pop: a {"resolved_by_operator": True} object
    # is NOT a first pass, and popping first would make it look like one.
    first_pass = not prior
    prior = dict(prior or {})
    prior.pop("resolved_by_operator", None)
    rows = {int(r["order"]): r for r in prior.get("parts", [])}
    for order, counts in per_order.items():
        rows[order] = {"order": order, **counts}
    for order in all_orders:
        rows.setdefault(
            order, {"order": order, "elements_touched": None, "flattened": None}
        )
    parts = [rows[o] for o in sorted(rows)]

    merged = {"parts": parts}
    if all(r["elements_touched"] is not None for r in parts):
        merged["elements_touched"] = sum(r["elements_touched"] for r in parts)
        merged["flattened"] = sum(r["flattened"] for r in parts)
    else:
        merged["elements_touched"] = None
        merged["flattened"] = None
    # Unioned ONLY when the prior object actually had the key; OMITTED entirely
    # when it did not. An incomplete list is worse than an absent one, because
    # verify recomputes live on absence but TRUSTS a present list -- so emitting
    # this pass's findings alone after a --resolve-rewrite applied (which writes
    # no such key) would drop a previously-recorded element and make verify raise
    # with status == "applied" and no remedy reachable.
    #
    # `first_pass` is the genuinely-first pass: nothing has been recorded yet, so
    # this pass's findings ARE complete and the key is safe to write.
    if "fail_closed_elements" in prior:
        union = set(prior["fail_closed_elements"]) | set(fail_closed)
    elif first_pass:
        union = set(fail_closed)
    else:
        return merged  # key stays ABSENT -> verify recomputes
    # Drop entries whose Element rows no longer exist, or a delete-and-re-graft
    # cycle accumulates dead pks in this list forever (spec Counts).
    merged["fail_closed_elements"] = sorted(
        Element.objects.filter(pk__in=union).values_list("pk", flat=True)
    )
    return merged


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
    "import": {"as_user", "dry_run", "force", "start_at", "resolve_rewrite"},
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
    "resolve_rewrite": None,
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
        parser.add_argument(
            "--resolve-rewrite",
            choices=("applied", "not-applied"),
            help="import only: break the in_progress deadlock left by a crash "
            "during the deferred link rewrite. 'applied' records that the "
            "rewrite committed; 'not-applied' runs it now. The command prints "
            "a probe reading to inform the choice; it never guesses.",
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

    def _check_identity(self, state, target):
        """Which target database these pks belong to. Without it a resume
        against the wrong course is not refused -- the pass's course=target
        liveness filter simply finds nothing live, and (but for the fatal skip
        rule) that is a whole-scope flatten. target_pk is authoritative;
        target_slug only names the course in messages, so a rename is a note."""
        if "target_pk" not in state:
            raise CommandError(
                f"{LINK_STATE_NAME} in this bundle has no 'target_pk': it was "
                f"written by a pre-feature import. Re-run `import` from the "
                f"start against a clean target."
            )
        if state["target_pk"] != target.pk:
            raise CommandError(
                f"{LINK_STATE_NAME} records target pk {state['target_pk']} "
                f"({state.get('target_slug')!r}), but --target-slug resolved to "
                f"{target.slug!r} (pk {target.pk}). Refusing to mix targets."
            )
        if state.get("target_slug") != target.slug:
            self.stdout.write(
                f"note: this course was renamed from "
                f"{state.get('target_slug')!r} to {target.slug!r} since the "
                f"import began; continuing on the recorded pk"
            )

    def _check_src_drift(self, state, node_index):
        """Runs BEFORE anything is grafted, not inside the pass. Inside the
        pass it is a post-mortem: the remaining parts are all committed from
        the NEW archives first, and only then does it raise.

        Compares SOURCE PKS, not export-id sets. Export ids are positional and
        _create_nodes keys node_map by every document node, so both sides are
        always exactly {n1..nK} for a part of K nodes -- a set comparison
        returns True no matter what those ids now denote, and a sibling reorder
        re-labels both nodes while preserving the set.
        """
        for entry in state["parts"]:
            order = int(entry["order"])
            expected = _invert_node_index(node_index, order)
            recorded = {eid: int(pk) for eid, pk in entry.get("src", {}).items()}
            if recorded != expected:
                raise CommandError(
                    f"{LINK_STATE_NAME} disagrees with {MANIFEST_NAME} about "
                    f"part {order}: the bundle was re-exported from a changed "
                    f"source after that part was grafted, so the recorded "
                    f"export-id map no longer describes it. Re-run `import` "
                    f"from the start against a clean target."
                )

    def _scan_links(self, state, target):
        """(dangling, dangling_elements, total_elements) over ALL recorded
        orders. Composed from part 2's read-only exports -- none of them returns
        an href, so a reported href is RECONSTRUCTED as /courses/n/<pk>/ from
        the dangling pk, not captured."""
        qs = (
            Element.objects.filter(unit_id__in=_live_pks(state["parts"], target))
            .order_by("pk")
            .prefetch_related("content_object")
        )
        referenced = {}
        total_elements = 0
        for join in qs.iterator(chunk_size=500):
            total_elements += 1
            obj = join.content_object
            if obj is None:
                continue
            for _field, value in iter_rich_text(obj):
                for pk in find_link_targets(value):
                    referenced.setdefault(pk, []).append((join.unit_id, join.pk))

        live_targets = set(  # NOT `live`: a different set
            ContentNode.objects.filter(course=target, pk__in=referenced).values_list(
                "pk", flat=True
            )
        )
        dangling = {
            pk: sites for pk, sites in referenced.items() if pk not in live_targets
        }
        dangling_elements = {epk for sites in dangling.values() for _u, epk in sites}
        return dangling, dangling_elements, total_elements

    def _in_progress_message(self, bundle, state, target):
        """The discriminator. After a committed pass no in-scope element holds
        a dangling internal href; before it, essentially every one does. The
        command reports and refuses -- an automatic guess that lands wrong
        produces exactly the silent mis-point this design exists to prevent.

        Both numbers are over the PENDING scope, because only pending orders
        would be rewritten. Over all entries, one re-grafted part of ~1,000
        elements inside a 20,054-element scope reads as ~5% -- neither near zero
        nor near total -- and 5% pushes the operator toward `applied`, stranding
        the re-grafted part's hrefs on source pks.
        """
        pending = [e for e in state["parts"] if not e["rewritten"]]
        probe = dict(state)
        probe["parts"] = pending
        _dangling, dangling_elements, total = self._scan_links(probe, target)
        fail_closed = {
            join.pk
            for join in Element.objects.filter(
                pk__in=dangling_elements
            ).prefetch_related("content_object")
            if join.content_object is not None and _is_fail_closed(join.content_object)
        }
        # Context only: how big the pending scope is relative to the whole
        # migration. Without it, "N of M in scope" on a repair resume hides that
        # M is one part of twenty-one -- the ~5%-vs-~100% misreading the spec
        # warns about.
        migration_total = Element.objects.filter(
            unit_id__in=_live_pks(state["parts"], target)
        ).count()
        header = (
            f"{LINK_STATE_NAME} in {bundle} is in_progress: a crash left the "
            f"deferred link rewrite in an unknown state.\n"
        )
        if total == 0:
            # DEGENERATE: total == 0 does NOT mean "every part is rewritten"
            # -- it also arises from pending parts that hold zero elements, or
            # whose in-scope units no longer exist (all-dead nodes). Derive
            # the explanation from the ACTUAL condition (`not pending`) rather
            # than asserting the common case unconditionally. This is not
            # hypothetical -- a status hand-flipped to in_progress on an
            # otherwise-fully-applied state file reaches the `not pending`
            # shape, and so would a partially corrupted one, since _read_state
            # does not cross-check status against the per-part rewritten
            # flags.
            # The two threshold lines below both read "near 0" when total is
            # 0, which would hand the operator two OPPOSITE instructions for
            # the one decision this message exists to disambiguate -- an
            # ambiguous reading is worse than none, so report unavailability
            # explicitly instead of rendering a broken threshold.
            if not pending:
                reason = "every recorded part's 'rewritten' flag already reads true"
            else:
                reason = (
                    f"{len(pending)} part(s) are pending but hold no elements in scope"
                )
            return (
                header + f"  probe: 0 element(s) recorded in the pending scope -- "
                f"there is nothing to check for a dangling internal link "
                f"({reason}; the whole migration holds {migration_total}).\n"
                f"  the reading is UNAVAILABLE here, not a signal: inspect "
                f"{LINK_STATE_NAME} by hand to determine whether the "
                f"deferred link rewrite actually committed, then re-run with "
                f"--resolve-rewrite applied or --resolve-rewrite not-applied "
                f"accordingly.\n"
                f"The command will not guess: a wrong answer silently "
                f"re-points correct links at unrelated nodes."
            )
        return (
            header
            + f"  probe: {len(dangling_elements - fail_closed)} element(s) hold a "
            f"dangling internal link, of {total} in the pending scope "
            f"({len(fail_closed)} more are malformed and were never "
            f"rewritable; the whole migration holds {migration_total}).\n"
            f"  near {total} means the rewrite did NOT run  -> re-run with "
            f"--resolve-rewrite not-applied\n"
            f"  near 0 means it DID commit                  -> re-run with "
            f"--resolve-rewrite applied\n"
            f"The command will not guess: a wrong answer silently re-points "
            f"correct links at unrelated nodes."
        )

    def _resolve_rewrite(self, o, bundle, state, node_index, target):
        """Terminal: mutates only the state file, grafts nothing, returns.

        Handled before the baseline capture and the :401 double-run guard --
        an in_progress file only exists after a complete or nearly-complete
        import, so the natural invocation would otherwise hit :401 and the
        operator would never reach the state file. Following that error's advice
        and adding --force is worse: it re-grafts every part.
        """
        answer = o["resolve_rewrite"]
        for flag, label in (
            ("start_at", "--start-at"),
            ("force", "--force"),
            ("dry_run", "--dry-run"),
        ):
            if o.get(flag) is not _FLAG_UNSET[flag]:
                raise CommandError(
                    f"--resolve-rewrite cannot be combined with {label}: it is "
                    f"a terminal action that grafts nothing, so {label} would "
                    f"be silently ignored."
                )

        recorded = {int(e["order"]) for e in state["parts"]}
        on_disk = {self._archive_order(p.name) for p in self._bundle_archives(bundle)}
        status = state["status"]
        if answer == "applied":
            if status != "in_progress":
                raise CommandError(
                    f"--resolve-rewrite applied is only meaningful on an "
                    f"in_progress {LINK_STATE_NAME}; this one is {status!r}."
                )
            for entry in state["parts"]:
                entry["rewritten"] = True
            state["status"] = "applied"
            rewrite = dict(state.get("rewrite") or {})
            rewrite["resolved_by_operator"] = True
            state["rewrite"] = rewrite
            _write_state(bundle, state)
            self.stdout.write(
                "recorded the deferred link rewrite as applied on the "
                "operator's word; counts for the resolved parts are unknown"
            )
            return

        if not (
            status == "in_progress" or (status == "collecting" and recorded == on_disk)
        ):
            raise CommandError(
                f"--resolve-rewrite not-applied needs an in_progress "
                f"{LINK_STATE_NAME}, or a collecting one whose recorded parts "
                f"match the archives on disk; this one is {status!r} with "
                f"recorded={sorted(recorded)} on_disk={sorted(on_disk)}."
            )
        # The `collecting` flip is NOT persisted first: the pass's own gates
        # raise before it writes in_progress, and a persisted `collecting` would
        # leave --resolve-rewrite refused ever after. Leaving the file as-is
        # until the pass succeeds keeps this action re-runnable.
        for entry in state["parts"]:
            entry["rewritten"] = False
        state["status"] = "collecting"
        self._run_link_pass(bundle, state, node_index, target)

    def _should_run_pass(self, state, ordered, *, todo=None):
        """`todo` is passed ONLY at site 1. Site 2 must not carry it: `todo` is
        a list the graft loop iterates but never empties, so `not todo` is False
        after any run that grafted anything -- and the `start_at is None` branch
        has no other trigger site, which would make the whole feature inert on
        the primary invocation.

        At site 1 the conjunct is required for the opposite reason: without it
        the pass fires while parts are still ungrafted (the stale-entry window
        at the last part), aborting on skipped_dead and stalling the migration.
        """
        if todo is not None and todo:
            return False
        recorded = {int(e["order"]) for e in state["parts"]}
        on_disk = {order for order, _p in ordered}
        pending_orders = {int(e["order"]) for e in state["parts"] if not e["rewritten"]}
        return (
            recorded == on_disk
            and state["status"] == "collecting"
            and bool(pending_orders)
        )

    def _run_link_pass(self, bundle, state, node_index, target):
        self._check_src_drift(state, node_index)  # redundant assertion here
        mapping, scope_pks, order_by_new_pk, scanned_orders = _build_mapping(
            state, node_index, target
        )
        per_order = {o: {"elements_touched": 0, "flattened": 0} for o in scanned_orders}
        fail_closed = []

        # Marker BEFORE the transaction: a crash between the DB commit and the
        # file write would otherwise leave fully rewritten content with no
        # marker, and the trigger would re-apply an old-source-pk map over hrefs
        # that now hold target pks -- the silent mis-point nothing can detect.
        state["status"] = "in_progress"
        _write_state(bundle, state)

        with transaction.atomic():
            qs = (
                Element.objects.filter(unit_id__in=scope_pks)
                .order_by("pk")
                .prefetch_related("content_object")
            )
            # chunk_size is MANDATORY after prefetch_related on Django 5.2:
            # iterator() raises ValueError without it. The value is a tuning
            # constant; passing one at all is not.
            for join in qs.iterator(chunk_size=500):
                obj = join.content_object
                if obj is None:  # dangling GFK
                    continue
                if _is_fail_closed(obj):
                    # Record, AND STILL REWRITE: the probe is per-instance, and
                    # the instance's other fields may hold mappable hrefs. Part 2
                    # returns the fail-closed field byte-identical on its own.
                    fail_closed.append(join.pk)
                changed, flattened = rewrite_instance(obj, mapping, on_missing="unwrap")
                if changed:
                    obj.save(update_fields=changed)
                order = order_by_new_pk[join.unit_id]
                if changed:
                    per_order[order]["elements_touched"] += 1
                per_order[order]["flattened"] += flattened

        for entry in state["parts"]:
            entry["rewritten"] = True
        state["status"] = "applied"
        state["rewrite"] = _merge_rewrite(
            state.get("rewrite"),
            per_order,
            fail_closed,
            {int(e["order"]) for e in state["parts"]},
        )
        _write_state(bundle, state)

        for row in state["rewrite"]["parts"]:
            # Carried-forward rows hold None; render them the same way the
            # summary line does rather than printing "None element(s)".
            et = row["elements_touched"]
            fl = row["flattened"]
            self.stdout.write(
                f"part {row['order']}: "
                f"{et if et is not None else 'unknown'} element(s) rewritten, "
                f"{fl if fl is not None else 'unknown'} link(s) flattened"
            )
        # BOTH lookups must tolerate absence: _merge_rewrite omits
        # fail_closed_elements when the prior object lacked it, and nulls the
        # totals when any carried-forward row has unknown counts. Reached by the
        # resolve-applied-then-repair-resume path.
        rw = state["rewrite"]
        fc = rw.get("fail_closed_elements")
        et = rw["elements_touched"]
        fl = rw["flattened"]
        self.stdout.write(
            f"deferred link rewrite applied: "
            f"{et if et is not None else 'unknown'} element(s) touched, "
            f"{fl if fl is not None else 'unknown'} link(s) flattened, "
            f"{len(fc) if fc is not None else 'unknown'} body(ies) left "
            f"untouched by the scanner"
        )

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
        # source pk -> [part order, export id], same lifecycle as `side`. Covers
        # EVERY node in the course, because every node descends from some
        # top-level part -- unlike document["link_nodes"], which holds only
        # targets referenced from inside one part, so a node linked to ONLY from
        # another part would appear in no archive's map at all.
        node_index = {}
        total_nodes = 0
        total_elements = 0
        node_kind_counts = {}
        written = set()
        over_cap = []

        for part in parts:
            report = {}
            manifest, document, media_assets, problems = build_export(
                course, node=part, report=report
            )
            if problems and not o.get("allow_problems"):
                raise CommandError(
                    f"part {part.order} ({part.title!r}) exported with "
                    f"{len(problems)} problem(s): {problems}. "
                    f"Re-run with --allow-problems to accept them."
                )
            for pk, nid in report["node_ids"].items():
                node_index[str(pk)] = [part.order, nid]
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
            counts = ", ".join(f"{m['key']}={m['value']}" for m in report["limits"])
            self.stdout.write(f"exported part {part.order}: {name} ({counts})")
            # ADVISORY, never fatal -- unlike `problems` above, which aborts the
            # whole bundle unless --allow-problems. An over-cap part must not
            # abort: the per-part bundle is exactly the path a course too big
            # for one archive travels, so refusing to build it would refuse the
            # remedy for the condition being reported. And the caps that decide
            # belong to the TARGET deployment, which this process cannot see.
            for m in report["limits"]:
                if not m["over"]:
                    continue
                over_cap.append(part.order)
                self.stdout.write(
                    f"  note: part {part.order} {m['key']}={m['value']} exceeds "
                    f"this instance's limit of {m['cap']}; the importing "
                    f"instance must allow more (raise {m['env']} there)"
                )

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
            "node_index": node_index,
        }
        (bundle / MANIFEST_NAME).write_text(
            json.dumps(bundle_manifest, ensure_ascii=False), encoding="utf-8"
        )
        self.stdout.write(
            f"wrote {MANIFEST_NAME} ({total_nodes} nodes, {total_elements} "
            f"elements, {len(side)} distinct media asset(s), "
            f"{len(node_index)} node(s) indexed for internal links)"
        )
        if over_cap:
            self.stdout.write(
                f"note: {len(set(over_cap))} part(s) exceed a limit on THIS "
                f"instance: {sorted(set(over_cap))}. The bundle is complete and "
                f"was written in full; check the target instance's limits "
                f"before importing."
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
        # NOT `manifest`: the graft loop binds that name below via
        # `with open_archive(...) as (zf, manifest, ...)`, and a `with ... as`
        # target binds in the ENCLOSING FUNCTION SCOPE and survives the block.
        # After the loop `manifest` is the LAST ARCHIVE's manifest, so the
        # post-loop trigger would read the wrong dict and raise KeyError.
        bundle_manifest = self._read_bundle_manifest(
            bundle, archives
        )  # completeness gate
        if "node_index" not in bundle_manifest:
            raise CommandError(
                f"{MANIFEST_NAME} in {bundle} has no 'node_index': this bundle "
                f"predates internal-link support. Re-export it -- importing it "
                f"as-is would flatten every internal link in the course."
            )
        node_index = bundle_manifest["node_index"]
        ordered = [(self._archive_order(p.name), p) for p in archives]

        start_at = o.get("start_at")
        resolve = o.get("resolve_rewrite")  # Task 9 adds the flag
        baseline_path = bundle / BASELINE_NAME

        # STEP 1. Validate unless this invocation discards the file wholesale.
        # --start-at is fatal alongside --resolve-rewrite, so `start_at is
        # None` is ALWAYS true on a resolve invocation -- a naive exemption
        # would skip validation on every one of them, and step 2 returns
        # before step 3 ever discards anything.
        state = _read_state(bundle, validate=not (start_at is None and resolve is None))

        # STEP 2. --resolve-rewrite is terminal. Identity FIRST, so a wrong
        # --target-slug cannot flip the file and destroy the only record of
        # whether the real target's rewrite ran. (Task 9 implements the
        # terminal action itself; this task only wires the guard.)
        if resolve is not None:
            if state is None:
                raise CommandError(
                    f"{LINK_STATE_NAME} is missing from {bundle}; there is no "
                    f"rewrite state to resolve"
                )
            self._check_identity(state, target)
            return self._resolve_rewrite(o, bundle, state, node_index, target)

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
                # STEP 3. Behind the :401-equivalent guard above AND behind
                # the dry-run gate. Before that guard, a plain re-run after a
                # crash would wipe `parts` to [] and THEN raise "target
                # already has N top-level node(s)" -- consuming an
                # unrecoverable map on an invocation that does nothing else.
                # No status check applies on this path: a leftover
                # `in_progress`/`applied` file from an earlier migration
                # through this bundle must not block a legitimate fresh
                # re-import.
                state = _fresh_state(target)
                _write_state(bundle, state)
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

            # STEP 4. All five gates, in this order, AFTER the invariant
            # above and BEFORE `todo` is computed.
            if state is None or not state.get("parts"):
                if start_at == 0:
                    state = _fresh_state(target)
                    if not o.get("dry_run"):
                        _write_state(bundle, state)
                else:
                    where = (
                        f"is missing from {bundle}"
                        if state is None
                        else f"in {bundle} records no committed parts"
                    )
                    raise CommandError(
                        f"{LINK_STATE_NAME} {where}, but "
                        f"--start-at {start_at} says {start_at} part(s) are "
                        f"already committed. That import began before "
                        f"internal-link support, so its export_id -> new_pk "
                        f"map cannot be reconstructed -- export ids exist "
                        f"nowhere else. Re-run `import` from the start "
                        f"against a clean target."
                    )
            else:
                self._check_identity(state, target)  # 1. identity
                if state["status"] == "in_progress":  # 2. in_progress refusal
                    raise CommandError(self._in_progress_message(bundle, state, target))
                recorded = {int(e["order"]) for e in state["parts"]}
                on_disk = {order for order, _p in ordered}
                missing = {  # 3. resume subset guard
                    x for x in on_disk if x < start_at
                } - recorded
                if missing:
                    raise CommandError(
                        f"--start-at {start_at} expects part(s) "
                        f"{sorted(missing)} to be committed, but "
                        f"{LINK_STATE_NAME} does not record them. Proceeding "
                        f"would flatten every link into them."
                    )
                extra = recorded - on_disk  # 4. recorded - on_disk refusal
                if extra:
                    raise CommandError(
                        f"{LINK_STATE_NAME} records part(s) {sorted(extra)} "
                        f"as grafted, but {bundle} no longer holds their "
                        f"archive(s). The bundle was re-exported with parts "
                        f"removed; re-run `import` from the start."
                    )
                self._check_src_drift(state, node_index)  # 5. src drift

            todo = [(order, path) for order, path in ordered if order >= start_at]
            if not o.get("dry_run") and not baseline_path.exists():
                baseline_path.write_text(
                    json.dumps(baseline, ensure_ascii=False), encoding="utf-8"
                )
            fired_here = False
            if not o.get("dry_run") and self._should_run_pass(
                state, ordered, todo=todo
            ):
                self.stdout.write(
                    "no parts left to graft; applying the deferred link rewrite"
                )
                self._run_link_pass(bundle, state, node_index, target)
                fired_here = True
            if not todo:
                if not fired_here:
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
                        # on_missing="defer" (below) means import_subtree never
                        # calls _rewrite_links here, so `report["flattened_links"]`
                        # is unconditionally 0 for every part (importer.py sets it
                        # via `report.setdefault("flattened_links", 0)` only,
                        # never increments it under `defer`) -- this call site
                        # surfaces NO flattening. Internal links are left exactly
                        # as exported, recorded pending in the state file below,
                        # and resolved (or reported flattened) only by the final
                        # deferred rewrite pass over the WHOLE bundle.
                        #
                        # OUTER atomic, opened here and NOT around the archive
                        # open: _run_import's own atomic becomes a savepoint, so
                        # the real commit happens when THIS block exits -- after
                        # the state write below. That inverts the crash window
                        # from a MISSING entry (unrecoverable: export ids exist
                        # nowhere else) to a STALE one (detectable, and replaced
                        # by the re-graft).
                        try:
                            with transaction.atomic():
                                report = {}
                                import_subtree(
                                    zf,
                                    manifest,
                                    document,
                                    media_entries,
                                    target,
                                    None,
                                    user,
                                    on_missing="defer",
                                    report=report,
                                )
                                state["parts"] = [
                                    e
                                    for e in state["parts"]
                                    if int(e["order"]) != order
                                ]
                                state["parts"].append(
                                    {
                                        "order": order,
                                        "node_map": report["node_map"],
                                        "src": _invert_node_index(node_index, order),
                                        "rewritten": False,
                                    }
                                )
                                # A RE-graft after "applied" must re-arm the pass.
                                state["status"] = "collecting"
                                _write_state(bundle, state)
                        except OSError as exc:
                            # NOT `except Exception`: import_subtree runs inside
                            # this block and TransferError is a plain Exception
                            # subclass, so a broad catch would report an
                            # IntegrityError as a state-file failure and leave
                            # this method's TransferError handler reachable
                            # only for open_archive failures.
                            hint = _resume_hint(committed)
                            raise CommandError(
                                f"could not write {LINK_STATE_NAME} while "
                                f"grafting part {order}: {exc}. Part {order}'s "
                                f"media files may be orphaned on disk.\n{hint}"
                            ) from exc
                        except DatabaseError as exc:
                            # The outer atomic's own COMMIT (or SAVEPOINT
                            # COMMIT, under a test's outer transaction) can
                            # fail AFTER `_write_state` above has already
                            # returned successfully -- e.g. the connection
                            # drops between the file write and COMMIT. Neither
                            # `except OSError` above nor `except TransferError`
                            # below matches DatabaseError (verified against
                            # django/db/utils.py: a failed commit is wrapped by
                            # DatabaseErrorWrapper into one of DataError /
                            # OperationalError / IntegrityError / InternalError
                            # / ProgrammingError / NotSupportedError /
                            # DatabaseError -- every one a DatabaseError
                            # subclass), so without this clause the operator
                            # loses the --start-at recovery hint exactly when
                            # the state file and the DB may have diverged.
                            hint = _resume_hint(committed)
                            raise CommandError(
                                f"database error while committing part "
                                f"{order}: {exc}. {LINK_STATE_NAME} may "
                                f"already reflect this part even though the "
                                f"database transaction did not confirm "
                                f"committing it.\n{hint}"
                            ) from exc
            except TransferError as exc:
                # Recovery guidance belongs HERE, on the failure path -- a
                # trailing "no parts committed" line after the loop would be
                # unreachable, because this CommandError propagates out of it.
                hint = _resume_hint(committed)
                raise CommandError(f"{archive.name}: {exc}\n{hint}") from exc
            committed = order
            self.stdout.write(f"grafted part {order} from {archive.name}")

        if not o.get("dry_run") and self._should_run_pass(state, ordered):
            self._run_link_pass(bundle, state, node_index, target)
        elif not o.get("dry_run") and state["status"] != "applied":
            # Backstop: never end `import` silently without the pass having run.
            self.stdout.write(
                f"note: the deferred link rewrite did not run "
                f"(status={state['status']!r}); run `verify` to see why"
            )

        if o.get("dry_run"):
            self.stdout.write("[dry-run] validated; nothing written")
        else:
            self.stdout.write(
                f"last part committed: {committed}; run `verify` to confirm "
                f"internal links are consistent"
            )

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

        state = _read_state(bundle, validate=True)
        if state is None:
            raise CommandError(
                f"{LINK_STATE_NAME} is missing from {bundle}; run `import` "
                f"before `verify` so the link rewrite is on record"
            )
        self._check_identity(state, target)
        # A stale entry REPORTS here rather than raising -- unlike in the pass,
        # because `verify` never mutates.
        stale = {
            pk for e in state["parts"] for pk in e["node_map"].values()
        } - _live_pks(state["parts"], target)
        if stale:
            orders = sorted(
                int(e["order"])
                for e in state["parts"]
                if set(e["node_map"].values()) & stale
            )
            self.stdout.write(
                f"note: {LINK_STATE_NAME} records {len(stale)} node(s) in "
                f"part(s) {orders} that no longer exist in {target.slug!r}"
            )
        if state["status"] == "in_progress":
            # The SAME probe reading `import` gives. The spec makes the reading
            # the decisive discriminator, and an operator who reaches the
            # deadlock through `verify` needs it just as much.
            raise CommandError(self._in_progress_message(bundle, state, target))
        if state["status"] != "applied":
            raise CommandError(
                f"{LINK_STATE_NAME} in {bundle} is {state['status']!r}: the "
                f"deferred link rewrite never ran, so internal links still "
                f"hold source pks. Re-run `import`."
            )

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

        rewrite = state.get("rewrite") or {}
        if rewrite.get("resolved_by_operator"):
            self.stdout.write(
                "link rewrite: marked applied by the operator; counts unavailable"
            )
        for row in rewrite.get("parts", []):
            et = row["elements_touched"]
            fl = row["flattened"]
            self.stdout.write(
                f"  part {row['order']}: "
                f"{et if et is not None else 'unknown'} rewritten, "
                f"{fl if fl is not None else 'unknown'} flattened"
            )

        dangling, dangling_elements, total_elements = self._scan_links(state, target)
        if "fail_closed_elements" in rewrite:
            fail_closed = set(rewrite["fail_closed_elements"])
        else:
            # Absent, NOT empty. The resolved_by_operator shape has no such key
            # by construction, and treating it as empty would read every
            # fail-closed body as an ordinary dangling element -- with status
            # already applied and --resolve-rewrite refusing a non-in_progress
            # file, verify would then fail forever with no remedy.
            fail_closed = {
                join.pk
                for join in Element.objects.filter(
                    pk__in=dangling_elements
                ).prefetch_related("content_object")
                if join.content_object is not None
                and _is_fail_closed(join.content_object)
            }
        real = dangling_elements - fail_closed
        reported = dangling_elements & fail_closed

        if reported:
            # Non-fatal, but the count alone gives no way to FIND the
            # elements among (potentially) 20,054 -- the same (unit_id,
            # element pk, href) triples the fatal branch below reports,
            # capped identically.
            reported_examples = _dangling_examples(dangling, reported)
            self.stdout.write(
                f"note: {len(reported)} element(s) hold links the scanner "
                f"declines to touch (malformed anchor markup); they keep their "
                f"source pks and need a manual fix. First "
                f"{len(reported_examples)}: {reported_examples}"
            )
        if real:
            real_examples = _dangling_examples(dangling, real)
            raise CommandError(
                f"{len(real)} migrated element(s) hold a dangling internal "
                f"link (of {total_elements} in scope). First "
                f"{len(real_examples)}: {real_examples}"
            )
        self.stdout.write(
            f"internal links OK: {total_elements} element(s) in scope, none dangling"
        )

        shared = {k: v for k, v in table.items() if len(v) > 1}
        self.stdout.write(
            f"OK: {actual_nodes} nodes, {actual_elements} elements, "
            f"{actual_media} media ({len(shared)} asset(s) shared across "
            f"parts)"
        )
