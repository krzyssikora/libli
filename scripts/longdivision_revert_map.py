"""Reconstruct the long-division revert map from an ALREADY-APPLIED conversion.

    uv run python scripts/longdivision_revert_map.py \
        --source-dir C:/Users/krzys/Documents/teaching/LAL/html/045_wielomiany \
        --part-id 408 --course mat-pp \
        --out docs/superpowers/plans/\
2026-08-26-wielomiany-long-division-arrays-revert-map.md

READ-ONLY. It opens no transaction and writes nothing to the database.

Why it exists: `convert_long_division --apply` overwrote `Element.object_id`
without ever printing the pk it overwrote, so the plan's `## Rollback` snippet
had no `<original table pk>` to put in. The command now prints that mapping
(see its `--apply` loop), but the mat-pp run predates the fix. The old pks are
still recoverable because the conversion orphans the `TableElement` row instead
of deleting it, so the mapping can be rebuilt from content alone:

* an ORPHAN is a `TableElement` no `Element` join points at;
* `db_text_key(orphan.data["cells"])` is the same key the matcher used;
* a CONVERTED join is an `Element` in the part's subtree pointing at a
  `MathElement` whose latex is a `\\begin{array}`;
* orphan O is a candidate original for join J iff J's latex is one of the LaTeX
  strings the source tables under O's text key produce.

That is the inverse of exactly what the conversion did, so it cannot invent a
pairing the run could not have made. It CAN leave a group undecided: stored
tables with identical cell text share one text key and therefore one candidate
set, so their orphans are interchangeable. MEASURED on mat-pp: two groups of
three (units 423/425/426 and 424/425/426), and in both the orphans' stored
`data` is byte-identical, so restoring any member into any of the group's joins
gives the same content. The script checks that byte-identity rather than
assuming it, and prints the groups instead of hiding them.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import django

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from django.contrib.contenttypes.models import ContentType  # noqa: E402

from courses.longdivision.convert import db_text_key  # noqa: E402
from courses.longdivision.match import index_by_key  # noqa: E402
from courses.longdivision.source import scan  # noqa: E402
from courses.management.commands.convert_long_division import _subtree_ids  # noqa: E402
from courses.models import ContentNode  # noqa: E402
from courses.models import Course  # noqa: E402
from courses.models import Element  # noqa: E402
from courses.models import MathElement  # noqa: E402
from courses.models import TableElement  # noqa: E402

ARRAY_PREFIX = "\\begin{array}"


def pair(joins, orphans, index):
    """(rows, groups) -- one row per join, plus the undecided candidate groups.

    `joins` is [(element_pk, unit_pk, math_pk, latex)], `orphans` is
    [(table_pk, text_key)], `index` is `index_by_key(scan(...))`. Pure: no DB,
    no filesystem, so the pairing rule is testable on literals.

    A join whose candidate set has exactly one orphan is settled. Any larger set
    is reported whole and assigned by lowest pk, so the output is deterministic
    and every member of the group carries the same flag.
    """
    latex_by_key = {key: {c.latex for c in cands} for key, cands in index.items()}
    cands_for = {}
    for el_pk, _unit_pk, _math_pk, latex in joins:
        cands_for[el_pk] = sorted(
            table_pk for table_pk, key in orphans if latex in latex_by_key.get(key, ())
        )

    groups = sorted({tuple(v) for v in cands_for.values() if len(v) != 1})
    taken, rows = set(), []
    for el_pk, unit_pk, math_pk, _latex in joins:
        cands = cands_for[el_pk]
        free = [pk for pk in cands if pk not in taken]
        chosen = free[0] if free else None
        if chosen is not None:
            taken.add(chosen)
        rows.append(
            {
                "element_pk": el_pk,
                "unit_pk": unit_pk,
                "orphan_table_pk": chosen,
                "math_pk": math_pk,
                "candidates": cands,
                "ambiguous": len(cands) != 1,
            }
        )
    return rows, groups


def collect(course_slug, part_id, source_dir):
    table_ct = ContentType.objects.get_for_model(TableElement)
    math_ct = ContentType.objects.get_for_model(MathElement)

    referenced = set(
        Element.objects.filter(content_type=table_ct).values_list(
            "object_id", flat=True
        )
    )
    orphans, data_by_pk = [], {}
    for t in TableElement.objects.exclude(pk__in=referenced).order_by("pk"):
        orphans.append((t.pk, db_text_key(t.data.get("cells") or [])))
        data_by_pk[t.pk] = json.dumps(t.data, sort_keys=True, ensure_ascii=False)

    course = Course.objects.get(slug=course_slug)
    part = ContentNode.objects.get(pk=part_id, course=course)
    joins = []
    for join in Element.objects.filter(
        unit_id__in=_subtree_ids(part), content_type=math_ct
    ).order_by("pk"):
        latex = MathElement.objects.get(pk=join.object_id).latex
        if latex.startswith(ARRAY_PREFIX):
            joins.append((join.pk, join.unit_id, join.object_id, latex))

    return joins, orphans, index_by_key(scan(source_dir)), data_by_pk


HEADER = """# Wielomiany long-division: revert map

Reconstructed by `scripts/longdivision_revert_map.py` AFTER the conversion ran,
because the applying run never printed the pks it overwrote. Read-only: nothing
in the database was changed to produce this.

Each row names one converted element. `orphan_table_pk` is the `TableElement`
row the join pointed at BEFORE the conversion -- the `<original table pk>` the
plan's `## Rollback` snippet asks for:

```python
from django.contrib.contenttypes.models import ContentType
from courses.models import Element, TableElement
join = Element.objects.get(pk=<element_pk>)
join.content_type = ContentType.objects.get_for_model(TableElement)
join.object_id = <orphan_table_pk>
join.save(update_fields=["content_type", "object_id"])
```

The `MathElement` row named by `math_pk` is left behind by that repoint, exactly
as the `TableElement` rows are left behind by the conversion. Delete it only if
you are sure no other join points at it.

Rows flagged `ambiguous` share a candidate set with other rows: their stored
tables have identical cell text, so content alone cannot say which orphan came
from which join. The group listing below reports whether the group's orphans are
byte-identical; where it says YES, restoring any candidate into any of the
group's joins gives the same content and the choice does not matter. The flag is
there so nobody mistakes the assignment for a measurement.
"""


def render(rows, groups, joins, orphans, data_by_pk):
    out = [HEADER, ""]
    out.append(
        f"Converted elements: {len(joins)}.  "
        f"Orphaned `TableElement` rows: {len(orphans)}.  "
        f"Undecided groups: {len(groups)}."
    )
    out.append("")
    if groups:
        out.append("Undecided candidate groups (interchangeable orphans):")
        out.append("")
        for g in groups:
            members = [r["element_pk"] for r in rows if tuple(r["candidates"]) == g]
            same = len({data_by_pk[p] for p in g}) == 1
            verdict = "YES" if same else "NO (the assignment MATTERS -- check by hand)"
            els = ", ".join(str(p) for p in members)
            orph = ", ".join(str(p) for p in g)
            out.append(
                f"* elements {els} <- orphans {orph} -- stored `data` "
                f"byte-identical across the group: {verdict}"
            )
        out.append("")
    out.append("| element_pk | unit_pk | orphan_table_pk | math_pk | ambiguous |")
    out.append("| ---: | ---: | ---: | ---: | :--- |")
    for r in rows:
        orphan = "?" if r["orphan_table_pk"] is None else r["orphan_table_pk"]
        flag = ""
        if r["ambiguous"]:
            flag = "yes ({})".format(", ".join(str(p) for p in r["candidates"]))
        out.append(
            f"| {r['element_pk']} | {r['unit_pk']} | {orphan} | {r['math_pk']} "
            f"| {flag} |"
        )
    out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", default="mat-pp")
    ap.add_argument("--part-id", type=int, default=408)
    ap.add_argument("--source-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    joins, orphans, index, data_by_pk = collect(
        args.course, args.part_id, args.source_dir
    )
    rows, groups = pair(joins, orphans, index)
    Path(args.out).write_text(
        render(rows, groups, joins, orphans, data_by_pk), encoding="utf-8"
    )

    unresolved = [r for r in rows if r["orphan_table_pk"] is None]
    print(
        f"joins {len(joins)}  orphans {len(orphans)}  groups {len(groups)}  "
        f"unassigned {len(unresolved)}"
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
