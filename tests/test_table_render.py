import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _grid(rows, cols, **top):
    cells = [
        [{"html": f"r{r}c{c}", "halign": "left", "valign": "top"} for c in range(cols)]
        for r in range(rows)
    ]
    return {
        "header_row": False,
        "header_col": False,
        "border": "grid",
        "cells": cells,
        **top,
    }


def test_renders_table_with_overflow_wrapper():
    html = TableElement(data=_grid(2, 2)).render()
    assert "el--table" in html and "<table" in html
    assert "el--table--border-grid" in html


def test_header_row_makes_first_row_th_scope_col():
    html = TableElement(data=_grid(2, 2, header_row=True)).render()
    assert 'scope="col"' in html


def test_header_col_makes_first_col_th_scope_row():
    html = TableElement(data=_grid(2, 2, header_col=True)).render()
    assert 'scope="row"' in html


def test_corner_th_has_no_scope():
    html = TableElement(data=_grid(2, 2, header_row=True, header_col=True)).render()
    # In a 2x2 with both headers: exactly one scope="col" (the top-right header
    # cell) and one scope="row" (the bottom-left) — the (0,0) corner <th> gets
    # NO scope. Counting the scopes proves the corner is scope-less without
    # depending on class-attribute whitespace.
    assert html.count('scope="col"') == 1
    assert html.count('scope="row"') == 1


def test_alignment_classes_emitted():
    d = _grid(1, 1)
    d["cells"][0][0].update(halign="center", valign="middle")
    html = TableElement(data=d).render()
    assert "ta-center" in html and "va-middle" in html


def test_border_header_both_toggles_off_is_noop_not_error():
    html = TableElement(data=_grid(2, 2, border="header")).render()
    assert "el--table--border-header" in html  # renders, no exception


def test_math_left_as_raw_text_for_client_typeset():
    d = _grid(1, 1)
    d["cells"][0][0]["html"] = r"\(x\)"
    html = TableElement(data=d).render()
    assert r"\(x\)" in html
