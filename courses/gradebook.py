from django.utils.translation import gettext as _

from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix


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
