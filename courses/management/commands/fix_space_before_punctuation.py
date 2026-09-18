"""Remove the space the LAL import left before punctuation in a course.

The LAL source HTML was pretty-printed and the importer copied its whitespace
verbatim, so `<strong>naturalne</strong>.` was stored as

    <strong>
        naturalne
    </strong>
    .

and renders as "naturalne ." -- the whitespace INSIDE the closing tag renders
too, so both runs go. Same shape after inline maths (`\\(3\\) ,`) and after a
gate's slot sentinel.

One-off, like fix_jump_to_id_links: a command rather than a migration because
it is scoped to one course by slug, and prod is the only database that matters.

Deliberately conservative -- a missed space is cosmetic, a wrong edit is not:
  * only `. , ; : ! ? )` -- never quotes or an opening bracket, where the space
    belongs;
  * never inside maths (KaTeX ignores the space, and `\\\\ ,` -> `\\\\,` would
    turn a line break into a spacing command) or inside a tag's attributes;
  * never after an ellipsis, before a decimal digit, or in a one-line `6 : 2`
    (a division sign);
  * never a mark that opens a line or follows a block tag;
  * only display fields: answer keys (Blank.accepted, FillTableElement.data,
    options, cyclers) and MathElement.latex are not in FIELDS at all.

Writes go through QuerySet.update(), NOT .save(): several save() methods
re-sanitise, and this must change whitespace and nothing else. The owning units'
`updated` is bumped by hand for the same reason builder.py bumps it.
"""

import json
import re
from pathlib import Path

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from courses.models import CalloutElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import FillGateElement
from courses.models import GuessNumberElement
from courses.models import ImageElement
from courses.models import QuestionElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TextElement

WS = "[ \t\r\n]"
INLINE = "strong|b|em|i|u|span|a|small|sup|sub|emph|mark|s|code"
CANDIDATE = re.compile(
    rf"(?P<ws>{WS}*)(?P<tags>(?:</(?:{INLINE})>{WS}*)*)(?P<mark>[.,;:!?)])"
)
PROTECTED = re.compile(
    r"\$\$.*?\$\$"
    r"|\\\(.*?\\\)"
    r"|\\\[.*?\\\]"
    r"|\\begin\{(\w+\*?)\}.*?\\end\{\1\}"
    r"|<[^>]*>",
    re.S,
)


def _fixes(text):
    """[(start, end, replacement)] for every space-before-mark worth removing."""
    spans = [(m.start(), m.end()) for m in PROTECTED.finditer(text)]

    def inside(i):
        return any(s < i < e for s, e in spans)

    out = []
    for m in CANDIDATE.finditer(text):
        ws, tags, mark = m.group("ws"), m.group("tags"), m.group("mark")
        if not re.search(WS, ws + tags):
            continue
        start, mark_at = m.start(), m.start("mark")
        before = text[start - 1] if start else ""
        after = text[m.end() : m.end() + 1]
        if not before or before.isspace() or before in ">.,;:!?":
            # opens a line, follows a tag, follows an ellipsis, or follows another
            # mark: `spośród: !, @` lists the symbol, `? ;)` is an emoticon
            continue
        if inside(start) or any(s <= mark_at < e for s, e in spans):
            continue  # maths or a tag's attributes
        if mark in ".," and (after == "." or after.isdigit()):
            continue  # an ellipsis or a decimal
        if mark == ":" and not tags and "\n" not in ws and after in (" ", "\t"):
            continue  # `6 : 2` -- a division sign
        if mark in "?!" and re.match(rf"{WS}+[a-ząćęłńóśźż]", text[m.end() :]):
            continue  # `oraz ? możemy` -- the symbol, mid-sentence
        if mark == ")":
            opening = text.rfind("(", 0, start)
            if opening != -1 and text[opening + 1 : opening + 2].isspace():
                continue  # `( teza )` -- spaced on both sides on purpose
        out.append((start, m.end(), re.sub(WS, "", tags) + mark))
    return out


def tighten(text):
    """(text with every fix applied, number of fixes)."""
    fixes = _fixes(text)
    for start, end, rep in reversed(fixes):
        text = text[:start] + rep + text[end:]
    return text, len(fixes)


def _fix_lines(lines):
    n = 0
    out = []
    for line in lines or []:
        if isinstance(line, dict) and isinstance(line.get("stem"), str):
            stem, k = tighten(line["stem"])
            line = {**line, "stem": stem}
            n += k
        out.append(line)
    return out, n


def _fix_cells(data):
    if not isinstance(data, dict) or not isinstance(data.get("cells"), list):
        return data, 0
    n = 0
    rows = []
    for row in data["cells"]:
        if not isinstance(row, list):
            rows.append(row)
            continue
        new_row = []
        for cell in row:
            if isinstance(cell, dict) and isinstance(cell.get("html"), str):
                html, k = tighten(cell["html"])
                cell = {**cell, "html": html}
                n += k
            new_row.append(cell)
        rows.append(new_row)
    return {**data, "cells": rows}, n


# model -> {field: fixer}. A field missing here is never touched.
FIELDS = {
    TextElement: {"body": tighten},
    SpoilerElement: {"body": tighten},
    CalloutElement: {"heading": tighten, "body": tighten},
    ImageElement: {"figcaption": tighten},
    FillGateElement: {"stem": tighten},
    SwitchGateElement: {"stem": tighten},
    GuessNumberElement: {"stem": tighten, "success_message": tighten},
    SwitchGridElement: {"prompt": tighten, "lines": _fix_lines},
    TableElement: {"data": _fix_cells},
}
for _q in QuestionElement.__subclasses__():
    FIELDS[_q] = {"stem": tighten, "explanation": tighten}


def _context(text, width=40):
    """One printable before -> after line per fix in `text`."""
    for start, end, rep in _fixes(text):
        head = text[max(0, start - width) : start]
        tail = text[end : end + 10]
        yield (
            f"{(head + text[start:end] + tail)!r}\n        -> {(head + rep + tail)!r}"
        )


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


class Command(BaseCommand):
    help = "Remove the space the LAL import left before punctuation in a course."

    def add_arguments(self, parser):
        parser.add_argument("--course", help="slug of the course to fix.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="print every planned fix and write nothing.",
        )
        parser.add_argument(
            "--snapshot",
            help="path to write the pre-change values to. REQUIRED for a write "
            "run: it is the only way back.",
        )
        parser.add_argument(
            "--restore",
            help="path of a snapshot to put back, byte-identical. Terminal.",
        )

    def handle(self, *args, **o):
        if o.get("restore"):
            return self._restore(o["restore"])
        if not o.get("dry_run") and not o.get("snapshot"):
            raise CommandError(
                "--snapshot <path> is required for a write run (or pass "
                "--dry-run). The snapshot is the only way back."
            )
        course = Course.objects.filter(slug=o.get("course") or "").first()
        if course is None:
            raise CommandError(f"no course with slug {o.get('course')!r}")

        planned = self._plan(course)
        total = sum(p["count"] for p in planned)
        units = sorted({p["unit_pk"] for p in planned})
        for p in planned:
            self.stdout.write(
                f"unit {p['unit_pk']} {p['model'].__name__} {p['pk']}.{p['field']}: "
                f"{p['count']}"
            )
            if o.get("dry_run"):
                # Only strings the fixer changed: a JSON field also holds answer
                # keys (cycler options) that _fixes would happily report.
                changed = zip(_strings(p["old"]), _strings(p["new"]), strict=True)
                for s in (old for old, new in changed if old != new):
                    for line in _context(s):
                        self.stdout.write(f"    {line}")
        self.stdout.write(
            f"{total} fix(es) in {len(planned)} field(s) across {len(units)} unit(s)"
        )
        if o.get("dry_run"):
            self.stdout.write("[dry-run] nothing written")
            return

        snapshot = [
            {
                "model": p["model"]._meta.label_lower,
                "pk": p["pk"],
                "field": p["field"],
                "value": p["old"],
            }
            for p in planned
        ]
        Path(o["snapshot"]).write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        self.stdout.write(f"snapshot of {len(snapshot)} field(s) -> {o['snapshot']}")

        with transaction.atomic():
            for p in planned:
                p["model"].objects.filter(pk=p["pk"]).update(**{p["field"]: p["new"]})
            ContentNode.objects.filter(pk__in=units).update(updated=timezone.now())
        self.stdout.write(f"wrote {len(planned)} field(s)")

    def _plan(self, course):
        planned = []
        for model, fields in FIELDS.items():
            ct = ContentType.objects.get_for_model(model)
            unit_of = dict(
                Element.objects.filter(
                    unit__course=course, content_type=ct
                ).values_list("object_id", "unit_id")
            )
            for obj in model.objects.filter(pk__in=unit_of).order_by("pk"):
                for field, fixer in fields.items():
                    old = getattr(obj, field)
                    new, count = fixer(old)
                    if count:
                        planned.append(
                            {
                                "model": model,
                                "pk": obj.pk,
                                "field": field,
                                "old": old,
                                "new": new,
                                "count": count,
                                "unit_pk": unit_of[obj.pk],
                            }
                        )
        planned.sort(key=lambda p: (p["unit_pk"], p["model"].__name__, p["pk"]))
        return planned

    def _restore(self, path):
        try:
            snap = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"cannot read the snapshot at {path}: {exc}") from exc
        with transaction.atomic():
            for row in snap:
                model = apps.get_model(row["model"])
                model.objects.filter(pk=row["pk"]).update(
                    **{row["field"]: row["value"]}
                )
        self.stdout.write(f"restored {len(snap)} field(s) from {path}")
