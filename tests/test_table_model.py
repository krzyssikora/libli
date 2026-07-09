import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _cell(html="", h="left", v="top"):
    return {"html": html, "halign": h, "valign": v}


def test_normalize_empty_gives_default_2x2():
    d = TableElement.normalize_data({})
    assert len(d["cells"]) == 2 and len(d["cells"][0]) == 2
    assert d["header_row"] is False and d["header_col"] is False
    assert d["border"] == "grid"


def test_normalize_degenerate_empty_rows_falls_back_to_2x2():
    d = TableElement.normalize_data({"cells": [[], []]})
    assert len(d["cells"]) == 2 and len(d["cells"][0]) == 2


def test_normalize_rectangularises_ragged_without_truncating():
    d = TableElement.normalize_data({"cells": [[_cell("a")], [_cell("b"), _cell("c")]]})
    assert [len(r) for r in d["cells"]] == [2, 2]
    assert d["cells"][0][0]["html"] == "a"  # kept
    assert d["cells"][0][1]["html"] == ""  # padded


def test_normalize_fills_missing_cell_keys():
    d = TableElement.normalize_data({"cells": [[{"html": "x"}]]})
    c = d["cells"][0][0]
    assert c["halign"] == "left" and c["valign"] == "top" and c["html"] == "x"


def test_save_sanitises_each_cell_html():
    el = TableElement(
        data={
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [[_cell("<script>x</script><b>y</b>")]],
        }
    )
    el.save()
    stored = el.data["cells"][0][0]["html"]
    assert "<script>" not in stored and "<b>y</b>" in stored


def test_save_does_not_raise_on_malformed_cells():
    el = TableElement(data={"cells": "nope"})  # legacy/garbage shape
    el.save()  # must not raise
