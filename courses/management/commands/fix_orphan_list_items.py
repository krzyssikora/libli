"""Repair the list structure the LAL import broke in a course's rich text.

The importer split a list around an image and wrapped each piece in <p> instead
of the list's own tag. html5ever re-parsed `<p><li>..</li></p>` as
`<p></p><li>..</li>`, so the stored bodies carry
  * ORPHAN <li> runs -- no <ul>/<ol> parent: the marker hangs outside the text
    column and the RTE's list buttons cannot toggle them;
  * EMPTY <p></p> -- invisible, but they trigger the block-spacing margin, which
    is the blank line that appears when the text after one is centred.
On top of that the import dropped every `<ol start>`, so a numbered list the
author continued after a figure restarts at 1.

normalize_body now repairs the first two on any save, but it cannot know the
source list, so it wraps a run in a bare <ul> -- and 26 of the 28 affected source
lists are numbered. This command looks each run up in the LAL source instead:
the run's FIRST item text is matched against every <li> in the source, which
gives its list tag and its number, so a run becomes `<ol start="2">` where the
source said so. It also restores `start` on stored <ol>s whose first item the
source numbers above 1. A run the source does not identify unambiguously falls
back to <ul> and is reported.

Run it BEFORE anyone edits an affected element: a save wraps the run in <ul>
first, and the command then no longer sees an orphan to look up.

One-off, like fix_space_before_punctuation, and with the same safety rails:
--dry-run, a mandatory --snapshot for a write run, --restore. Writes go through
QuerySet.update(), NOT .save(), and the owning units' `updated` is bumped by hand.
"""

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from courses.management.commands.fix_space_before_punctuation import FIELDS
from courses.management.commands.fix_space_before_punctuation import tighten
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.sanitize import tidy_structure

# Only the plain HTML fields: the JSON ones (table cells, switch-grid lines) are
# sanitised to a tag set that has no lists at all.
HTML_FIELDS = {
    model: [f for f, fixer in fields.items() if fixer is tighten]
    for model, fields in FIELDS.items()
}
_KEY_CHARS = 80
_MIN_KEY_CHARS = 12
_BARE_OL = re.compile(r"<ol>")


def _key(li):
    """An item's identity across source and DB: its text, whitespace removed.

    Both sides decode entities (`&lt;` in a stored maths span vs a literal `<`
    in the source), so get_text() agrees where the raw HTML does not."""
    return "".join(li.get_text().split())[:_KEY_CHARS]


def _number(li):
    lst = li.parent
    if lst.name != "ol":
        return 1
    try:
        start = max(1, int(lst.get("start", 1)))
    except (TypeError, ValueError):
        start = 1
    return start + lst.find_all("li", recursive=False).index(li)


def build_source_index(source_root):
    """{item key: {(list tag, number), ...}} over every <li> in the LAL source."""
    index = {}
    for path in sorted(Path(source_root).rglob("*.html")):
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        for li in soup.find_all("li"):
            if li.parent is None or li.parent.name not in ("ul", "ol"):
                continue
            key = _key(li)
            if key:
                index.setdefault(key, set()).add((li.parent.name, _number(li)))
    return index


def _first_item(html):
    return BeautifulSoup(html, "html.parser").find("li")


class _Repair:
    """Rewrites one value; records what it could and could not resolve."""

    def __init__(self, index):
        self.index = index
        self.unresolved = []

    def _lookup(self, li):
        key = _key(li) if li is not None else ""
        if len(key) < _MIN_KEY_CHARS:
            return None  # "tak", "a)": a unique match would be a coincidence
        hits = self.index.get(key)
        return next(iter(hits)) if hits and len(hits) == 1 else None

    def _list_for(self, run_html):
        li = _first_item(run_html)
        hit = self._lookup(li)
        if hit is None:
            self.unresolved.append(
                _key(li) if li is not None else run_html[:_KEY_CHARS]
            )
            return "ul", "<ul>"
        tag, number = hit
        if tag == "ol" and number > 1:
            return "ol", f'<ol start="{number}">'
        return tag, f"<{tag}>"

    def _restore_starts(self, html):
        out = []
        last = 0
        for m in _BARE_OL.finditer(html):
            hit = self._lookup(_first_item(html[m.end() :]))
            if hit and hit[0] == "ol" and hit[1] > 1:
                out.append(html[last : m.start()])
                out.append(f'<ol start="{hit[1]}">')
                last = m.end()
        out.append(html[last:])
        return "".join(out)

    def __call__(self, value):
        if not isinstance(value, str) or not value:
            return value
        return self._restore_starts(tidy_structure(value, list_for=self._list_for))


class Command(BaseCommand):
    help = "Repair orphan list items, empty paragraphs and lost list numbering."

    def add_arguments(self, parser):
        parser.add_argument("--course", help="slug of the course to fix.")
        parser.add_argument(
            "--source-root",
            help="the LAL html folder (the one holding 001_zbiory_liczbowe/ ...).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="print every planned change and write nothing.",
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
        root = o.get("source_root")
        if not root or not Path(root).is_dir():
            raise CommandError(f"--source-root must be the LAL html folder: {root!r}")
        course = Course.objects.filter(slug=o.get("course") or "").first()
        if course is None:
            raise CommandError(f"no course with slug {o.get('course')!r}")

        index = build_source_index(root)
        if not index:
            raise CommandError(f"no <li> found under {root!r} -- wrong folder?")
        planned, unresolved = self._plan(course, _Repair(index))
        units = sorted({p["unit_pk"] for p in planned})
        for p in planned:
            self.stdout.write(
                f"unit {p['unit_pk']} {p['model'].__name__} {p['pk']}.{p['field']}"
            )
            if o.get("dry_run"):
                self.stdout.write(f"    - {p['old']!r}")
                self.stdout.write(f"    + {p['new']!r}")
        for where, key in unresolved:
            self.stdout.write(f"UNRESOLVED (wrapped in <ul>) {where}: {key!r}")
        self.stdout.write(
            f"{len(planned)} field(s) across {len(units)} unit(s); "
            f"{len(unresolved)} run(s) not found in the source"
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

    def _plan(self, course, repair):
        planned = []
        unresolved = []
        for model, fields in HTML_FIELDS.items():
            if not fields:
                continue
            ct = ContentType.objects.get_for_model(model)
            unit_of = dict(
                Element.objects.filter(
                    unit__course=course, content_type=ct
                ).values_list("object_id", "unit_id")
            )
            objs = model.objects.filter(pk__in=unit_of).only("pk", *fields)
            for obj in objs.order_by("pk"):
                for field in fields:
                    old = getattr(obj, field)
                    before = len(repair.unresolved)
                    new = repair(old)
                    where = f"{model.__name__} {obj.pk}.{field}"
                    unresolved += [(where, k) for k in repair.unresolved[before:]]
                    if new != old:
                        planned.append(
                            {
                                "model": model,
                                "pk": obj.pk,
                                "field": field,
                                "old": old,
                                "new": new,
                                "unit_pk": unit_of[obj.pk],
                            }
                        )
        planned.sort(key=lambda p: (p["unit_pk"], p["model"].__name__, p["pk"]))
        return planned, unresolved

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
