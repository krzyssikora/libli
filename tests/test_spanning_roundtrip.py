"""Server-side behaviour for spanning (colspan/rowspan) tables: layout
dimensions, form validation relaxation, caps grandfathering, and the
bound-invalid re-render seam."""

import pytest

from courses.models import TableElement

pytestmark = pytest.mark.django_db


def test_span_clamps_rowspan_against_max_rows_not_max_cols():
    # MAX_COLS is 20, MAX_ROWS is 50. A rowspan of 30 is legal and must not
    # be truncated to 20 by the column cap.
    assert TableElement._span({"rowspan": 30}, "rowspan") == 30
    # Above the ROW cap it clamps to MAX_ROWS, not MAX_COLS.
    assert TableElement._span({"rowspan": 99}, "rowspan") == TableElement.MAX_ROWS
    # colspan still clamps against the column cap.
    assert TableElement._span({"colspan": 99}, "colspan") == TableElement.MAX_COLS


def test_layout_dims_counts_spans_not_cell_counts():
    # Row 0: one cell spanning 3 columns. Row 1: three 1x1 cells.
    cells = [
        [{"colspan": 3}],
        [{}, {}, {}],
    ]
    assert TableElement.layout_dims(cells) == (3, 2)


def test_layout_dims_accounts_for_rowspan_offsetting_later_rows():
    # (0,0) has rowspan 2, so row 1's first cell starts at layout column 1.
    cells = [
        [{"rowspan": 2}, {}, {}],
        [{}, {}],
    ]
    assert TableElement.layout_dims(cells) == (3, 2)


def test_layout_dims_empty_grid_is_zero_by_zero():
    assert TableElement.layout_dims([]) == (0, 0)


def test_layout_dims_treats_malformed_cells_as_one_by_one():
    # A non-dict cell counts as a 1x1 occupant; a non-int span counts as 1.
    cells = [["not a dict", {"colspan": "3"}, {}]]
    assert TableElement.layout_dims(cells) == (3, 1)


def test_layout_dims_skips_a_non_list_row_but_still_counts_its_height():
    # The junk row contributes no width, but height is len(rows) -- pinned
    # explicitly, because "skips" alone would imply height 1.
    assert TableElement.layout_dims([[{}, {}], "junk"]) == (2, 2)
