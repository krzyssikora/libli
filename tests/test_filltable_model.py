import pytest

from courses.models import FillTableElement

pytestmark = pytest.mark.django_db


def _cells(nd):
    return nd["cells"]


def test_normalize_defaults_and_degenerate_collapse():
    nd = FillTableElement.normalize_data({})
    assert len(nd["cells"]) == 2 and len(nd["cells"][0]) == 2  # default 2x2
    assert nd["border"] == "grid"
    assert nd["header_row"] is False and nd["header_col"] is False
    assert nd["case_sensitive"] is False
    assert nd["prompt"] == ""
    # every cell has a valid kind
    assert all(c["kind"] in ("static", "answer") for row in nd["cells"] for c in row)


def test_normalize_ragged_rows_padded_not_truncated():
    nd = FillTableElement.normalize_data(
        {
            "cells": [
                [{"kind": "static", "html": "a"}],
                [{"kind": "static", "html": "b"}, {"kind": "answer", "answer": "x"}],
            ]
        }
    )
    assert len(nd["cells"][0]) == 2 and len(nd["cells"][1]) == 2


def test_normalize_unknown_kind_becomes_static():
    nd = FillTableElement.normalize_data({"cells": [[{"kind": "weird", "html": "h"}]]})
    assert nd["cells"][0][0]["kind"] == "static"


def test_normalize_scalar_coercion_never_faults_on_tampered_types():
    nd = FillTableElement.normalize_data(
        {
            "prompt": 123,
            "case_sensitive": "yes",
            "header_row": 1,
            "border": "dashed",
            "cells": [[{"kind": "answer", "answer": 5}]],
        }
    )
    assert nd["prompt"] == ""  # non-string prompt -> ""
    assert nd["case_sensitive"] is True  # coerced via bool()
    assert nd["header_row"] is True
    assert nd["border"] == "grid"  # out-of-enum -> default
    assert nd["cells"][0][0]["answer"] == ""  # non-string answer -> ""


def test_save_sanitizes_static_html_and_trims_answer():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "<script>x</script><b>ok</b>"},
                    {"kind": "answer", "answer": "  0,5 | 0.5  "},
                ]
            ]
        }
    )
    el.save()
    static, answer = el.data["cells"][0][0], el.data["cells"][0][1]
    assert "<script>" not in static["html"] and "<b>ok</b>" in static["html"]
    assert answer["answer"] == "0,5 | 0.5"  # trimmed, not HTML-sanitized


def test_save_preserves_math_in_static_cell():
    el = FillTableElement(data={"cells": [[{"kind": "static", "html": r"\(x<5\)"}]]})
    el.save()
    # sanitize_cell's _canon_math canonicalises the math span's "<" to "&lt;"
    # (so it survives the HTML tokenizer intact); the \( \) delimiters and the
    # comparison operator are preserved, just single-escaped. Same behaviour
    # as TableElement's static cells (shared sanitize_cell, unmodified here).
    assert r"\(x&lt;5\)" in el.data["cells"][0][0]["html"]
