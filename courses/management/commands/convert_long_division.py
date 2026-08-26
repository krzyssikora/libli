"""Convert legacy long-division tables to KaTeX math elements.

Dry-run by default. Run this LOCALLY against the mat-pp database; there is no
prod-side counterpart.

The stored TableElement rows are NEVER deleted -- the Element join is repointed
and the old row is left orphaned, which is the whole revert path (repoint back).
Element deletion in libli is a hard delete with no backups.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction

from courses.longdivision.convert import db_text_key
from courses.longdivision.match import index_by_key
from courses.longdivision.match import plan_unit
from courses.longdivision.source import scan
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import MathElement
from courses.models import TableElement


def _subtree_ids(root):
    ids, frontier = {root.pk}, [root.pk]
    while frontier:
        kids = [
            pk
            for pk in ContentNode.objects.filter(parent_id__in=frontier).values_list(
                "pk", flat=True
            )
            if pk not in ids
        ]
        ids.update(kids)
        frontier = kids
    return ids


class Command(BaseCommand):
    help = "Convert long-division tables to math elements (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--course", required=True)
        parser.add_argument("--part-id", type=int, required=True)
        parser.add_argument("--source-dir", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--list-matches", action="store_true")

    def handle(self, *args, **opts):
        try:
            course = Course.objects.get(slug=opts["course"])
        except Course.DoesNotExist as exc:
            raise CommandError("no course with slug %r" % opts["course"]) from exc  # noqa: UP031 - clearer than nested braces here
        try:
            part = ContentNode.objects.get(pk=opts["part_id"], course=course)
        except ContentNode.DoesNotExist as exc:
            raise CommandError(
                "node %s is not in course %s" % (opts["part_id"], opts["course"])  # noqa: UP031 - clearer than nested braces here
            ) from exc

        sources = scan(opts["source_dir"])
        if not sources:
            raise CommandError("no convertible tables under %s" % opts["source_dir"])  # noqa: UP031 - clearer than nested braces here
        index = index_by_key(sources)
        self.stdout.write("source tables selected: %d" % len(sources))  # noqa: UP031 - clearer than nested braces here

        table_ct = ContentType.objects.get_for_model(TableElement)
        joins = list(
            Element.objects.filter(
                unit_id__in=_subtree_ids(part), content_type=table_ct
            ).select_related("unit")
        )

        by_unit = {}
        for join in joins:
            by_unit.setdefault(join.unit_id, []).append(join)

        matched, ambiguous, unmatched = [], [], []
        for unit_id, unit_joins in sorted(by_unit.items()):  # noqa: B007 - unit_id orders the iteration, not read in the body
            rows = [
                (j.pk, db_text_key(j.content_object.data.get("cells") or []))
                for j in unit_joins
            ]
            m, a, u = plan_unit(rows, index)
            by_pk = {j.pk: j for j in unit_joins}
            matched.extend((by_pk[pk], src) for pk, src in m)
            ambiguous.extend(by_pk[pk] for pk in a)
            unmatched.extend(by_pk[pk] for pk in u)

        self.stdout.write(
            "stored tables in the subtree: %d  (convertible %d, unresolved %d, "  # noqa: UP031 - clearer than nested braces here
            "not a long division %d)"
            % (len(joins), len(matched), len(ambiguous), len(unmatched))
        )

        if opts["list_matches"]:
            for join, src in matched:
                self.stdout.write(
                    "  el=%-6s unit=%-6s <- %s" % (join.pk, join.unit_id, src.ident)  # noqa: UP031 - clearer than nested braces here
                )

        for join in ambiguous:
            self.stderr.write(
                "UNRESOLVED el=%s unit=%s: several source tables, none preferred"  # noqa: UP031 - clearer than nested braces here
                % (join.pk, join.unit_id)
            )

        # Absence is judged on LATEX, not on ident. `resolve` legitimately returns
        # the first of several byte-identical plain candidates, so the others stay
        # unclaimed by ident while their content is fully converted -- 150#0 and
        # 155#0 are the same 204 characters, and 150#1/155#1 the same 307. Keying
        # this on ident would report two tables as lost content that are not lost
        # at all. MEASURED against the real corpus: ident-keyed reports 4 absent,
        # latex-keyed reports the 2 that genuinely have no stored counterpart.
        converted = {src.latex for _, src in matched}
        for src in sources:
            if src.latex not in converted:
                self.stdout.write(
                    "  %s: no stored counterpart (skipped)" % src.ident  # noqa: UP031 - clearer than nested braces here
                )

        if ambiguous:
            raise CommandError(
                "%d table(s) could not be resolved; nothing written" % len(ambiguous)  # noqa: UP031 - clearer than nested braces here
            )
        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("dry run -- pass --apply to write"))
            return

        math_ct = ContentType.objects.get_for_model(MathElement)
        with transaction.atomic():
            for join, src in matched:
                math = MathElement.objects.create(latex=src.latex)
                join.content_type = math_ct
                join.object_id = math.pk
                join.save(update_fields=["content_type", "object_id"])
        self.stdout.write(self.style.SUCCESS("converted %d" % len(matched)))  # noqa: UP031 - clearer than nested braces here
