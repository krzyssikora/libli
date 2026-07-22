"""Server-side behaviour for spanning (colspan/rowspan) tables: layout
dimensions, form validation relaxation, caps grandfathering, and the
bound-invalid re-render seam."""

import re

import pytest

from courses.element_forms import FillTableElementForm
from courses.element_forms import TableElementForm
from courses.models import FillTableElement
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


def _table_form(data, instance=None):
    import json

    return TableElementForm(
        data={"data": json.dumps(data)}, instance=instance or TableElement()
    )


def _fill_form(data, instance=None):
    import json

    return FillTableElementForm(
        data={"data": json.dumps(data)}, instance=instance or FillTableElement()
    )


def test_ragged_spanning_grid_is_accepted():
    # The shape the editor produces for a merge: row 0 is one full-width cell.
    form = _table_form({"cells": [[{"colspan": 3, "html": "x"}], [{}, {}, {}]]})
    assert form.is_valid(), form.errors


def test_ragged_grid_without_spans_is_still_rejected():
    # The relaxation must NOT disable raggedness validation generally.
    form = _table_form({"cells": [[{}], [{}, {}, {}]]})
    assert not form.is_valid()
    assert "same number of cells" in str(form.errors)


def test_colspan_of_one_does_not_count_as_spanning():
    # A too-broad predicate ("has a colspan key") would accept this.
    form = _table_form({"cells": [[{"colspan": 1}], [{}, {}, {}]]})
    assert not form.is_valid()
    assert "same number of cells" in str(form.errors)


def test_string_span_is_not_a_span_and_ragged_rows_still_rejected():
    # _span does not coerce, so "3" is not a span -> grid is non-spanning ->
    # the ragged rejection fires. Crucially: no 500.
    form = _table_form({"cells": [[{"colspan": "3"}], [{}, {}, {}]]})
    assert not form.is_valid()
    assert "same number of cells" in str(form.errors)


def test_non_dict_cell_does_not_raise():
    form = _table_form({"cells": [["junk", {}], [{}, {}]]})
    form.is_valid()  # must not raise AttributeError


def test_fill_table_non_list_cells_does_not_raise():
    # FillTableElementForm has no pre-existing non-list guards, so _scan_spans
    # must coerce defensively or `for r in 5` is a 500.
    form = _fill_form({"cells": 5})
    form.is_valid()


def test_fill_table_non_list_row_does_not_raise():
    form = _fill_form({"cells": [5]})
    form.is_valid()


def test_out_of_range_colspan_is_rejected_not_clamped():
    # 26 must be REFUSED. Asserting on cleaned_data would prove nothing --
    # Django drops "data" from cleaned_data when clean_data raises, so any
    # `"20" not in cleaned_data` check passes whether the code rejects or
    # clamps. The meaningful contrast is that the SAME grid at the cap IS
    # valid, so the difference is the rejection rather than the value.
    assert not _table_form({"cells": [[{"colspan": 26}]]}).is_valid()
    assert _table_form({"cells": [[{"colspan": 20}]]}).is_valid()


def test_span_below_two_is_ignored_not_rejected():
    # colspan 0 / -3 are not spans; they must not raise, and the grid is then
    # non-spanning (so a rectangular one validates normally).
    form = _table_form({"cells": [[{"colspan": 0}, {}], [{}, {}]]})
    assert form.is_valid(), form.errors


def test_spanning_grid_with_one_empty_row_saves():
    # A full-width 2-row merge leaves row 1 with no cells at all.
    form = _table_form({"cells": [[{"colspan": 2, "rowspan": 2}], []]})
    assert form.is_valid(), form.errors


def test_new_table_over_cap_is_rejected():
    row = [{} for _ in range(21)]
    form = _table_form({"cells": [row]})
    assert not form.is_valid()


def test_over_cap_grid_is_grandfathered_when_unchanged():
    # A stored 26-wide grid stays saveable at 26.
    wide = [[{} for _ in range(26)]]
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": wide})
    )
    form = _table_form({"cells": wide}, instance=stored)
    assert form.is_valid(), form.errors


def test_grandfathered_grid_may_narrow_but_not_widen():
    wide = [[{} for _ in range(26)]]
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": wide})
    )

    narrower = [[{} for _ in range(24)]]
    assert _table_form({"cells": narrower}, instance=stored).is_valid()

    wider = [[{} for _ in range(27)]]
    assert not _table_form({"cells": wider}, instance=stored).is_valid()


def test_grandfathering_is_per_axis():
    # Stored 26 wide x 1 tall. Narrowing columns does not license growing rows
    # past MAX_ROWS.
    wide = [[{} for _ in range(26)]]
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": wide})
    )
    too_tall = [[{}, {}] for _ in range(51)]
    assert not _table_form({"cells": too_tall}, instance=stored).is_valid()


def test_grid_data_falls_back_to_stored_when_unbound():
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{"html": "kept"}, {}], [{}, {}]]})
    )
    form = TableElementForm(instance=stored)
    assert form.grid_data["cells"][0][0]["html"] == "kept"


def test_grid_data_reflects_submitted_json_on_a_rejected_save():
    # A rejected save must re-render what the author submitted, not the stored
    # value -- otherwise the visible grid and the hidden field disagree and the
    # next Save silently re-posts the rejected shape.
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{"html": "old"}, {}], [{}, {}]]})
    )
    # Ragged + non-spanning => rejected.
    form = _table_form({"cells": [[{"html": "new"}], [{}, {}, {}]]}, instance=stored)
    assert not form.is_valid()
    assert form.grid_data["cells"][0][0]["html"] == "new"


def test_grid_data_carries_the_whole_binding_not_just_cells():
    # header_row/border are read back by serialize() too, so a rejected save
    # must re-render those from the submission as well.
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{}], [{}]], "header_row": False})
    )
    form = _table_form(
        {"cells": [[{}], [{}, {}]], "header_row": True, "border": "rows"},
        instance=stored,
    )
    assert not form.is_valid()
    assert form.grid_data["header_row"] is True
    assert form.grid_data["border"] == "rows"


def test_grid_data_falls_back_when_payload_is_unparseable():
    stored = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{"html": "old"}, {}], [{}, {}]]})
    )
    form = TableElementForm(data={"data": "{not json"}, instance=stored)
    assert not form.is_valid()
    assert form.grid_data["cells"][0][0]["html"] == "old"


def test_header_row_th_keeps_its_span_in_the_student_render():
    # 250_pole_trojkata has header_row=True, so a merge in row 0 goes through
    # the header_row <th> branch -- which drops the span today.
    el = TableElement(
        data=TableElement.normalize_data(
            {
                "header_row": True,
                "cells": [[{"colspan": 3, "html": "hi"}], [{}, {}, {}]],
            }
        )
    )
    html = el.render()
    assert 'colspan="3"' in html


def test_header_col_th_keeps_its_span_in_the_student_render():
    el = TableElement(
        data=TableElement.normalize_data(
            {"header_col": True, "cells": [[{"rowspan": 2, "html": "hi"}, {}], [{}]]}
        )
    )
    assert 'rowspan="2"' in el.render()


def test_combined_header_row_and_col_th_keeps_its_span():
    # The FOURTH <th> branch: cell (0,0) when BOTH toggles are on hits the
    # combined `header_row and header_col` condition, which is a different
    # branch from the header_row-only and header_col-only ones tested above.
    el = TableElement(
        data=TableElement.normalize_data(
            {
                "header_row": True,
                "header_col": True,
                "cells": [[{"colspan": 2, "html": "hi"}], [{}, {}]],
            }
        )
    )
    html = el.render()
    assert re.search(r'<th[^>]*colspan="2"', html)


def test_merging_away_a_header_col_rows_first_cell_promotes_the_next_one():
    # ACCEPTED behaviour, pinned so it cannot change silently: header_col
    # promotes each row's POSITIONALLY FIRST cell, so a merge that removes
    # row 1's first cell makes the next one a <th> in the student view --
    # invisible to the author, since the editor does not render header_col
    # cells as <th>. The help text mentions this.
    el = TableElement(
        data=TableElement.normalize_data(
            {
                "header_col": True,
                # (0,0) now spans both rows, so row 1 begins with what used to
                # be its SECOND cell.
                "cells": [
                    [{"rowspan": 2, "html": "m"}, {"html": "b"}],
                    [{"html": "c"}],
                ],
            }
        )
    )
    html = el.render()
    # Assert on the SPECIFIC cell: "<th" alone is true before the merge too
    # (row 0's first cell is already a header), and a bare `"c" in html` matches
    # class names and attributes. Row 1's only cell must be a <th>, not a <td>.
    assert re.search(r"<th[^>]*>\s*c\s*</th>", html)
    assert not re.search(r"<td[^>]*>\s*c\s*</td>", html)


def test_fill_table_header_row_th_keeps_its_span():
    el = FillTableElement(
        data=FillTableElement.normalize_data(
            {
                "header_row": True,
                "cells": [
                    [{"kind": "static", "colspan": 2, "html": "hi"}],
                    [{"kind": "answer", "answer": "a"}, {"kind": "static", "html": ""}],
                ],
            }
        )
    )
    assert 'colspan="2"' in el.render()
