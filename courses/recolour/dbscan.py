"""Find the stored fields whose bytes equal a key, and rewrite them.

The registry is built from what the LAL loader actually writes, not from
courses.richtext.RICH_TEXT_FIELDS: that registry exists for internal links, includes
CalloutElement (which no builder branch creates) and excludes the two JSON cell
fields, which the backfill must cover.
"""

from typing import NamedTuple

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GuessNumberElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SpoilerElement
from courses.models import SwitchGateElement
from courses.models import TableElement
from courses.models import TextElement


class MultiOwnerError(RuntimeError):
    """A content row is reachable from more than one Element -- fail closed."""


class ReadBackError(RuntimeError):
    """A rewritten field did not read back byte-identical to what was written."""


HTML_FIELDS = [
    (TextElement, "body"),
    (SpoilerElement, "body"),
    (ChoiceQuestionElement, "stem"),
    (ShortNumericQuestionElement, "stem"),
    (ShortTextQuestionElement, "stem"),
    (FillBlankQuestionElement, "stem"),
    (FillGateElement, "stem"),
    (SwitchGateElement, "stem"),
    (GuessNumberElement, "stem"),
    (GuessNumberElement, "success_message"),
]
CELL_FIELDS = [(TableElement, "data"), (FillTableElement, "data")]


class Match(NamedTuple):
    model: type
    pk: int
    field: str
    cell: tuple  # (row, col) for a JSON cell field; None for an HTML field
    key: str
    value: str


def excluded_node_ids(course, pks):
    """Every node id in the named subtrees. The DESCENDANT walk is the whole
    correctness of the exclusion: a key built from an eligible part can match text
    that is byte-identical inside an excluded part, and source-side exclusion alone
    cannot prevent that."""
    ids = set()
    for pk in pks:
        node = ContentNode.objects.filter(course=course, pk=pk).first()
        if node is not None:
            ids |= set(node._subtree_node_ids())
    return ids


def _candidates(model, course, excluded):
    qs = model.objects.filter(elements__unit__course=course)
    if excluded:
        qs = qs.exclude(elements__unit_id__in=excluded)
    return qs.distinct()


def _assert_single_owner(model, pks):
    if not pks:
        return
    ct = ContentType.objects.get_for_model(model)
    dupes = (
        Element.objects.filter(content_type=ct, object_id__in=list(pks))
        .values("object_id")
        .annotate(n=Count("pk"))
        .filter(n__gt=1)
        .values_list("object_id", flat=True)
    )
    bad = list(dupes[:5])
    if bad:
        raise MultiOwnerError(
            f"{model.__name__} rows {bad} are owned by more than one Element; "
            "the subtree exclusion cannot be trusted for them"
        )


def find_matches(course, entries, excluded):
    """Every stored field whose bytes equal a key. Never reads ContentNode.title."""
    matches = []
    for model, field in HTML_FIELDS:
        rows = list(_candidates(model, course, excluded).values_list("pk", field))
        _assert_single_owner(model, [pk for pk, _v in rows])
        for pk, stored in rows:
            if stored and stored in entries:
                matches.append(Match(model, pk, field, None, stored, entries[stored]))
    for model, field in CELL_FIELDS:
        rows = list(_candidates(model, course, excluded).values_list("pk", field))
        _assert_single_owner(model, [pk for pk, _v in rows])
        for pk, data in rows:
            if not isinstance(data, dict):
                continue
            for r, row in enumerate(data.get("cells") or []):
                if not isinstance(row, list):
                    continue
                for c, cell in enumerate(row):
                    if not isinstance(cell, dict):
                        continue
                    # FillTableElement._sanitized_data sanitises cell["html"] ONLY for
                    # cells whose kind is neither `answer` nor `image` -- those two keep
                    # their media/answer payload and are never re-sanitised. A match
                    # landing on one would be written UNSANITISED while the read-back
                    # still passed, because the read-back compares against what we
                    # wrote. TableElement image cells now carry `kind: "image"` too
                    # (slice C2), so this guard is live for them as well, not just a
                    # FillTableElement concern. The real corpus produces zero
                    # fill-table matches, which is exactly why this branch must be
                    # closed rather than left to ship unexecuted.
                    if cell.get("kind") not in (None, "static"):
                        continue
                    stored = cell.get("html")
                    if stored and stored in entries:
                        matches.append(
                            Match(model, pk, field, (r, c), stored, entries[stored])
                        )
    return matches


def apply_matches(matches):
    """Write every match and read it back. Returns the number of CHANGED FIELDS.

    A table with 3 of 5 cells matching is rewritten partially and counts as ONE
    changed field. The read-back is not optional: the three gate stems have no
    save()-time sanitiser (models.py:776-779), so nothing else would notice a
    value the write path altered under us.
    """
    by_row = {}
    for m in matches:
        by_row.setdefault((m.model, m.pk, m.field), []).append(m)

    for (model, pk, field), group in by_row.items():
        row = model.objects.get(pk=pk)
        if group[0].cell is None:
            setattr(row, field, group[0].value)
        else:
            data = getattr(row, field)
            for m in group:
                data["cells"][m.cell[0]][m.cell[1]]["html"] = m.value
            setattr(row, field, data)
        row.save(update_fields=[field])

        fresh = model.objects.get(pk=pk)
        for m in group:
            if m.cell is None:
                got = getattr(fresh, field)
            else:
                got = getattr(fresh, field)["cells"][m.cell[0]][m.cell[1]]["html"]
            if got != m.value:
                raise ReadBackError(
                    f"{model.__name__}(pk={pk}).{field}"
                    f"{'' if m.cell is None else list(m.cell)} read back as "
                    f"{got[:120]!r}, expected {m.value[:120]!r}"
                )
    return len(by_row)
