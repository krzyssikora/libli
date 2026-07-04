from decimal import ROUND_HALF_UP
from decimal import Decimal

from django.utils.translation import gettext as _

from courses.models import QuizSubmission
from courses.rollups import _quiz_review_maps
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from courses.rollups import quiz_gradeable_max
from courses.rollups import quiz_units_in_order
from courses.rollups import submission_is_counted

_CENT = Decimal("0.01")


def _avg(total, count):
    """Participants-only mean, quantized to 2dp; None when no participants."""
    if count == 0:
        return None
    return (total / count).quantize(_CENT, rounding=ROUND_HALF_UP)


def build_matrix_table(course, students, mode, expanded):
    """Reshape the analytics matrix into the neutral Table (spec §3.1). Pure
    re-shaping — no new aggregation. Reads ["percent"] out of the matrix's _cell
    dicts; a neutral cell (None) passes through unchanged. title/subtitle left ""."""
    builder = build_results_matrix if mode == "results" else build_progress_matrix
    matrix = builder(course, students, expanded)

    columns = [
        {"label": c["title"], "max": None, "kind": "percent"} for c in matrix["columns"]
    ]
    rows = [
        {
            "name": r["student"].display_name or r["student"].username,
            "username": r["student"].username,
            "cells": [cell["percent"] for cell in r["cells"]],
            "total": r["overall"]["percent"],
        }
        for r in matrix["rows"]
    ]
    footer = [
        {
            "label": _("Average"),
            "values": [a["percent"] for a in matrix["averages"]],
            "total": matrix["overall_average"]["percent"],
        }
    ]
    return {
        "title": "",
        "subtitle": "",
        "columns": columns,
        "total_kind": "percent",
        "total_label": _("Overall"),
        "meta_row": None,
        "rows": rows,
        "footer": footer,
    }


def build_quiz_gradebook(course, students, numbers_only):
    """Per-quiz raw-marks register (spec §3.2). One column per quiz leaf unit;
    cells are raw counted sub.score or a —/…/R marker; a dedicated Max row; a
    per-student Total and a participants-only class Average. title/subtitle "" ."""
    students = list(students)
    units = quiz_units_in_order(course)
    maxes = quiz_gradeable_max(units)

    columns = [
        {"label": f"{i}. {u.title}", "max": maxes[u.pk], "kind": "score"}
        for i, u in enumerate(units, start=1)
    ]
    meta_total = sum((c["max"] for c in columns), Decimal("0"))
    meta_row = {
        "label": _("Max"),
        "values": [c["max"] for c in columns],
        "total": meta_total,
    }

    subs = {
        (s.student_id, s.unit_id): s
        for s in QuizSubmission.objects.filter(unit__in=units, student__in=students)
    }
    _has_auto, total_review, reviewed_counts = _quiz_review_maps(
        [u.pk for u in units], subs.values()
    )

    col_sums = [Decimal("0")] * len(columns)
    col_counts = [0] * len(columns)
    total_sum = Decimal("0")
    total_count = 0

    rows = []
    for s in students:
        cells = []
        row_total = Decimal("0")
        row_has_counted = False
        for idx, u in enumerate(units):
            if columns[idx]["max"] == 0:  # non-gradeable column
                cells.append(None)
                continue
            sub = subs.get((s.id, u.pk))
            if sub is None:
                cells.append(None if numbers_only else "—")
            elif sub.status == QuizSubmission.Status.IN_PROGRESS:
                cells.append(None if numbers_only else "…")
            elif submission_is_counted(sub, total_review, reviewed_counts):
                score = sub.score or Decimal("0")
                cells.append(score)
                row_total += score
                row_has_counted = True
                col_sums[idx] += score
                col_counts[idx] += 1
            else:  # SUBMITTED but pending [R]
                cells.append(None if numbers_only else "R")
        total = row_total if row_has_counted else None
        if total is not None:
            total_sum += total
            total_count += 1
        rows.append(
            {
                "name": s.display_name or s.username,
                "username": s.username,
                "cells": cells,
                "total": total,
            }
        )

    footer = [
        {
            "label": _("Average"),
            "values": [_avg(col_sums[i], col_counts[i]) for i in range(len(columns))],
            "total": _avg(total_sum, total_count),
        }
    ]
    return {
        "title": "",
        "subtitle": "",
        "columns": columns,
        "total_kind": "score",
        "total_label": _("Total"),
        "meta_row": meta_row,
        "rows": rows,
        "footer": footer,
    }
