import pytest

from courses.models import FillTableElement
from tests.factories import make_course
from tests.factories import make_image_asset

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


def test_normalize_spanning_fill_table_keeps_ragged_and_span():
    nd = FillTableElement.normalize_data(
        {
            "cells": [
                [{"kind": "static", "html": "h", "colspan": 2, "header": True}],
                [{"kind": "static", "html": "x"}, {"kind": "answer", "answer": "5"}],
            ]
        }
    )
    assert [len(r) for r in nd["cells"]] == [1, 2]  # ragged preserved, not padded
    assert nd["cells"][0][0]["colspan"] == 2 and nd["cells"][0][0]["header"] is True
    assert nd["cells"][1][1]["kind"] == "answer" and nd["cells"][1][1]["answer"] == "5"
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


def test_canonical_cells_uses_first_alternative_per_answer_cell():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "x"},
                    {"kind": "answer", "answer": "4 | four | IV"},
                ]
            ]
        }
    )
    out = el.canonical_cells
    assert out[0][0] == {
        "kind": "static",
        "html": "x",
        "halign": "left",
        "valign": "top",
    }
    assert out[0][1]["kind"] == "answer"
    assert out[0][1]["answer"] == "4"


def test_canonical_cells_no_alternatives_renders_empty_string():
    el = FillTableElement(data={"cells": [[{"kind": "answer", "answer": ""}]]})
    assert el.canonical_cells[0][0]["answer"] == ""
    el2 = FillTableElement(data={"cells": [[{"kind": "answer", "answer": "|  |"}]]})
    assert el2.canonical_cells[0][0]["answer"] == ""  # pipe-only -> zero alternatives


def test_canonical_cells_shape_matches_normalize_data():
    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "answer", "answer": "1"}],
                [{"kind": "static", "html": "b"}],
            ]
        }
    )
    normalized = FillTableElement.normalize_data(el.data)
    assert len(el.canonical_cells) == len(normalized["cells"])
    assert [len(r) for r in el.canonical_cells] == [len(r) for r in normalized["cells"]]


def test_cell_image_kind_valid_media_preserved():
    nd = FillTableElement.normalize_data(
        {"cells": [[{"kind": "image", "media": 7, "alt": "graph", "halign": "center"}]]}
    )
    c = nd["cells"][0][0]
    assert c == {
        "kind": "image",
        "media": 7,
        "alt": "graph",
        "halign": "center",
        "valign": "top",
    }


@pytest.mark.parametrize("bad_media", [None, "7", 7.0, True, {"x": 1}])
def test_cell_image_invalid_media_degrades_to_empty_static(bad_media):
    # missing/non-int/bool media -> a safe empty static cell, never a broken image
    nd = FillTableElement.normalize_data(
        {"cells": [[{"kind": "image", "media": bad_media, "alt": "x"}]]}
    )
    c = nd["cells"][0][0]
    assert c["kind"] == "static" and c["html"] == ""


def test_cell_image_missing_media_key_degrades():
    nd = FillTableElement.normalize_data({"cells": [[{"kind": "image", "alt": "x"}]]})
    assert nd["cells"][0][0]["kind"] == "static"


def test_cell_image_non_string_alt_coerced():
    nd = FillTableElement.normalize_data(
        {"cells": [[{"kind": "image", "media": 3, "alt": 9}]]}
    )
    assert nd["cells"][0][0]["alt"] == ""


def test_sanitized_data_image_cell_keeps_media_trims_alt_no_html():
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": 5, "alt": "  a graph  "}]]}
    )
    el.save()
    cell = el.data["cells"][0][0]
    assert cell["kind"] == "image" and cell["media"] == 5
    assert cell["alt"] == "a graph"
    assert (
        "html" not in cell
    )  # the else-branch's sanitize_cell must NOT run on image cells


def test_image_only_fill_table_has_no_math():
    # spec's has_math confirming test: _fill_table_has_math scans non-answer cells'
    # html; an image cell has no html key, so it contributes no math.
    from courses.views import _fill_table_has_math

    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "image", "media": 5, "alt": "x"},
                    {"kind": "answer", "answer": "1"},
                ]
            ]
        }
    )
    el.save()
    assert _fill_table_has_math(el) is False


def test_resolved_cells_replaces_pk_with_asset():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": asset.pk, "alt": "graph"}]]}
    )
    el.save()
    cell = el.resolved_cells[0][0]
    assert cell["kind"] == "image"
    assert cell["media"].pk == asset.pk  # a MediaAsset instance, not the int pk
    assert cell["alt"] == "graph"


def test_resolved_cells_unresolved_pk_degrades_to_static():
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": 999999, "alt": "x"}]]}
    )
    el.save()
    cell = el.resolved_cells[0][0]
    assert cell["kind"] == "static" and cell["html"] == ""


def test_resolved_cells_static_and_answer_pass_through():
    el = FillTableElement(
        data={
            "cells": [
                [{"kind": "static", "html": "s"}, {"kind": "answer", "answer": "1"}]
            ]
        }
    )
    el.save()
    grid = el.resolved_cells
    assert grid[0][0]["kind"] == "static" and grid[0][0]["html"] == "s"
    assert grid[0][1]["kind"] == "answer"
