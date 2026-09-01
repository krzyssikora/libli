"""Rewrite the legacy Open edX `jump_to_id` links left in mat-pp by the LAL import.

Each link is `<a href="/jump_to_id/<32-hex>">`, where the hex is an Open edX
`url_name`. The hex -> libli node mapping was recovered from the surviving
Studio outline (`py_scripts/toc_src.html` in the LAL corpus) and verified by
hand; it ships beside this command as `jump_to_id_map.json` so it is reviewable
as DATA in the diff rather than buried in code.

One-off, and deliberately so: these links exist only in the authoring database,
and the prod cutover copies content wholesale, so prod never sees them. This is
a command rather than a migration because a migration would re-run against a
database whose pks mean something else entirely.

The failure mode this guards is not a crash. It is a target pk that has MOVED
since the mapping was verified: the rewrite would then point a link at an
unrelated lesson, and nothing about the result would look wrong to a reader.
Hence the drift guard -- each target's title is recorded in the map and
re-checked before anything is written -- and hence "refuse the whole run",
never "rewrite what matches and skip the rest": a partial pass reads as success
and leaves dead links nobody comes back for.
"""

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from courses.models import ContentNode
from courses.models import Element
from courses.models import TextElement

DEFAULT_MAP = Path(__file__).with_name("jump_to_id_map.json")

# Both stored shapes: 31 of the 32 real links are relative and exactly one is
# absolute against the dev host. Anchoring at the leading slash would silently
# leave that one behind -- and it is the shape the problem was first reported
# as. The host part is optional, not a separate pattern, so the two can never
# drift apart.
LINK = re.compile(
    r'href="(?:https?://[^/"]+)?/jump_to_id/([0-9a-fA-F]{32})"',
    re.I,
)
# The scan is deliberately looser than LINK: it finds "jump_to_id" in ANY shape,
# so a link this command cannot rewrite is reported rather than passed over.
ANY_JUMP = re.compile(r"jump_to_id/([0-9a-zA-Z_-]+)")

# The one prose defect found alongside the links: unit 496's sentence reads
# "proporcjonalnosc PROSTA" while naming a target about "odwrotna", contradicting
# both the block before it and the two lessons after. Behind its own flag, off by
# default -- it is the author's copy, not a link.
PROSE_FIX = ("proporcjonalność prostą", "proporcjonalność odwrotną")


class Command(BaseCommand):
    help = "Rewrite legacy Open edX jump_to_id links to libli permalinks."

    def add_arguments(self, parser):
        parser.add_argument("--map", default=str(DEFAULT_MAP))
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="report every planned change and write nothing.",
        )
        parser.add_argument(
            "--snapshot",
            help="path to write the pre-change bodies to. REQUIRED for a write "
            "run: it is the only way back.",
        )
        parser.add_argument(
            "--restore",
            help="path of a snapshot to put back, byte-identical. Terminal: "
            "restores and returns, rewriting nothing.",
        )
        parser.add_argument("--report", help="path to write the verification list to.")
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:8000",
            help="only used to build clickable URLs in the report.",
        )
        parser.add_argument(
            "--fix-prose",
            action="store_true",
            help="also correct unit 496's 'proporcjonalność prostą' to "
            "'odwrotną'. Off by default: that is the author's copy.",
        )

    def handle(self, *args, **o):
        if o.get("restore"):
            return self._restore(o["restore"])
        if not o.get("dry_run") and not o.get("snapshot"):
            raise CommandError(
                "--snapshot <path> is required for a write run (or pass "
                "--dry-run). The snapshot is the only way back."
            )

        doc = self._read_map(o["map"])
        targets = doc["targets"]
        course_slug = doc["course_slug"]

        rows = list(
            TextElement.objects.filter(body__contains="jump_to_id").order_by("pk")
        )
        self._check_all_ids_are_mapped(rows, targets)
        nodes = self._check_targets(targets, course_slug)

        planned, snapshot = [], {}
        for te in rows:
            new_body, hits = self._rewrite(te.body, targets)
            if not hits:
                continue
            snapshot[str(te.pk)] = te.body
            planned.append((te, new_body, hits))

        if o.get("fix_prose"):
            planned = self._plan_prose(planned, snapshot)

        total = sum(len(h) for _t, _b, h in planned)
        self.stdout.write(
            f"{len(planned)} text block(s), {total} anchor(s), "
            f"{len(targets)} mapped target(s)"
        )
        if o.get("dry_run"):
            for te, _new, hits in planned:
                for h in hits:
                    self.stdout.write(f"  [dry-run] text {te.pk}: {h}")
            self.stdout.write("[dry-run] nothing written")
            return

        Path(o["snapshot"]).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        self.stdout.write(f"snapshot of {len(snapshot)} body(ies) -> {o['snapshot']}")

        with transaction.atomic():
            for te, new_body, _hits in planned:
                te.body = new_body
                # .save(), not .update(): TextElement.save() runs normalize_body,
                # and going around it would store a body the model would never
                # have produced. Verified no-op on all 30 real bodies, so it
                # changes nothing but this rewrite.
                te.save(update_fields=["body"])

        self._assert_clean(targets)
        report = self._build_report(planned, nodes, o["base_url"])
        if o.get("report"):
            Path(o["report"]).write_text(
                json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            self.stdout.write(f"verification list -> {o['report']}")
        for row in report["lessons"]:
            self.stdout.write(f"  {row['url']}  {row['unit']}")
            for a in row["anchors"]:
                self.stdout.write(
                    f"      {a['text']!r} -> {a['new_href']} ({a['target']})"
                )

    # --- guards ---------------------------------------------------------

    def _read_map(self, path):
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read the mapping at {path}: {exc}") from exc
        if "targets" not in doc or "course_slug" not in doc:
            raise CommandError(f"{path} is not a jump_to_id mapping")
        return doc

    def _check_all_ids_are_mapped(self, rows, targets):
        """An id in the database with no mapping aborts the run.

        Rewriting the known ones and skipping the rest reads as success and
        leaves dead links behind. Compared case-insensitively because the map is
        keyed on the lowercase form the corpus uses.
        """
        known = {k.lower() for k in targets}
        seen = {}
        for te in rows:
            for m in ANY_JUMP.finditer(te.body):
                seen.setdefault(m.group(1).lower(), []).append(te.pk)
        missing = sorted(set(seen) - known)
        if missing:
            where = ", ".join(f"{i[:8]} (text {seen[i][0]})" for i in missing)
            raise CommandError(
                f"{len(missing)} jump_to_id id(s) in the database are not in the "
                f"mapping: {where}. Refusing to rewrite only the mapped ones."
            )

    def _check_targets(self, targets, course_slug):
        """Existence, course scope, and TITLE DRIFT -- the last is the point.

        A pk that has moved since the mapping was verified repoints a link at an
        unrelated lesson, which no amount of reading the result would reveal.
        The recorded title is what makes that detectable, so a mismatch aborts.
        """
        nodes = {}
        problems = []
        for hexid, spec in sorted(targets.items()):
            node = (
                ContentNode.objects.filter(pk=spec["node_pk"])
                .select_related("course")
                .first()
            )
            if node is None:
                problems.append(f"{hexid[:8]}: node {spec['node_pk']} no longer exists")
                continue
            if node.course.slug != course_slug:
                problems.append(
                    f"{hexid[:8]}: node {node.pk} is in course {node.course.slug!r}, "
                    f"not {course_slug!r}"
                )
                continue
            if node.title != spec["title"]:
                problems.append(
                    f"{hexid[:8]}: node {node.pk} title drifted -- mapping recorded "
                    f"{spec['title']!r}, database holds {node.title!r}"
                )
                continue
            nodes[hexid.lower()] = node
        if problems:
            raise CommandError(
                "the mapping no longer describes this database:\n  "
                + "\n  ".join(problems)
                + "\nRefusing to write. Re-verify the mapping."
            )
        return nodes

    def _assert_clean(self, targets):
        """After the write: nothing left behind, and every new href resolves."""
        left = TextElement.objects.filter(body__contains="jump_to_id").count()
        if left:
            raise CommandError(
                f"{left} body(ies) still hold a jump_to_id link after the rewrite"
            )
        pks = {spec["node_pk"] for spec in targets.values()}
        live = set(ContentNode.objects.filter(pk__in=pks).values_list("pk", flat=True))
        if pks - live:
            raise CommandError(f"target node(s) vanished mid-run: {sorted(pks - live)}")

    # --- work -----------------------------------------------------------

    def _rewrite(self, body, targets):
        hits = []

        def sub(m):
            spec = targets[m.group(1).lower()]
            hits.append(f"{m.group(1)[:8]} -> /courses/n/{spec['node_pk']}/")
            return f'href="/courses/n/{spec["node_pk"]}/"'

        return LINK.sub(sub, body), hits

    def _plan_prose(self, planned, snapshot):
        old, new = PROSE_FIX
        out, done = [], False
        for te, body, hits in planned:
            if old in body:
                body = body.replace(old, new)
                hits = hits + [f"prose: {old!r} -> {new!r}"]
                done = True
            out.append((te, body, hits))
        if not done:
            raise CommandError(
                f"--fix-prose found no body containing {old!r}; it may already "
                f"have been corrected. Refusing to guess."
            )
        return out

    def _build_report(self, planned, nodes, base_url):
        by_unit = {}
        for te, new_body, _hits in planned:
            join = (
                Element.objects.filter(
                    content_type__model="textelement", object_id=te.pk
                )
                .select_related("unit")
                .first()
            )
            if join is None:  # pragma: no cover -- orphan content row
                continue
            unit = join.unit
            row = by_unit.setdefault(
                unit.pk,
                {
                    "unit_pk": unit.pk,
                    "unit": unit.title,
                    "url": f"{base_url}/courses/n/{unit.pk}/",
                    "published": unit.published,
                    "anchors": [],
                },
            )
            for m in re.finditer(
                r'<a href="(/courses/n/(\d+)/)">(.*?)</a>', new_body, re.S
            ):
                target = ContentNode.objects.filter(pk=int(m.group(2))).first()
                row["anchors"].append(
                    {
                        "text": re.sub(r"<[^>]+>", "", m.group(3)).strip(),
                        "new_href": m.group(1),
                        "target": target.title if target else "?",
                        "target_pk": int(m.group(2)),
                    }
                )
        return {"lessons": sorted(by_unit.values(), key=lambda r: r["unit_pk"])}

    def _restore(self, path):
        try:
            snap = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read the snapshot at {path}: {exc}") from exc
        with transaction.atomic():
            for pk, body in snap.items():
                # .update(), NOT .save(): restoring must be byte-identical, and
                # save() would run normalize_body over a body that is being put
                # back exactly as it was found.
                TextElement.objects.filter(pk=int(pk)).update(body=body)
        self.stdout.write(f"restored {len(snap)} body(ies) from {path}")
