"""Unit tests for table_grid.js's PURE functions.

They run inside a headless Playwright page because CI has no Node -- these are
NOT UI tests and are not a substitute for the real-gesture e2e in
test_e2e_spanning_merge.py. They feed a DOM table in and assert the shape that
comes out.

Run this slice's loop with:
  DATABASE_URL=... uv run pytest -m e2e -k table_grid
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

MODULE = (
    Path(__file__).resolve().parent.parent / "courses/static/courses/js/table_grid.js"
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture
def grid_page(page):
    """A blank page with table_grid.js loaded and a `mk(html)` helper building a
    descriptor over a <table>. Chrome (a trailing td[data-control] per row and a
    tr[data-control-row]) is present in every fixture so the descriptor's
    exclusion of it is genuinely exercised."""
    page.set_content("<body><div id='host'></div></body>")
    page.add_script_tag(path=str(MODULE))
    page.evaluate(
        """
        (function () {
        window.mk = function (rowsHtml) {
          var host = document.getElementById('host');
          host.innerHTML = '<table>' + rowsHtml +
            '<tr data-control-row><td data-control></td></tr></table>';
          var table = host.querySelector('table');
          function rows() {
            return Array.prototype.filter.call(
              table.querySelectorAll('tr'),
              function (tr) { return !tr.hasAttribute('data-control-row'); });
          }
          function cells(tr) {
            return Array.prototype.slice.call(
              tr.querySelectorAll('td:not([data-control]), th:not([data-control])'));
          }
          return {
            rows: rows,
            cells: cells,
            makeCell: function () {
              var td = document.createElement('td');
              td.setAttribute('contenteditable','true');
              return td;
            },
            makeRow: function () {
              var tr = document.createElement('tr');
              var ctl = document.createElement('td');
              ctl.setAttribute('data-control','');
              tr.appendChild(ctl);
              return tr;
            },
            maxCols: 20, maxRows: 50
          };
        };
        // Compact readback: one string per row, each cell as "colspanxrowspan".
        window.shape = function (g) {
          return g.rows().map(function (tr) {
            return g.cells(tr).map(function (c) {
              return (c.colSpan || 1) + 'x' + (c.rowSpan || 1);
            }).join(',');
          });
        };
        })();
        """
    )
    return page


ROW_3 = "<tr><td></td><td></td><td></td><td data-control></td></tr>"
ROW_SPAN3 = "<tr><td colspan='3'></td><td data-control></td></tr>"


def test_layout_width_ignores_the_trailing_control_cell(grid_page):
    js = "() => libliTableGrid.layoutWidth(mk(`%s`))" % ROW_3  # noqa: UP031
    assert grid_page.evaluate(js) == 3


def test_layout_width_counts_a_colspan_not_the_cell_count(grid_page):
    js = "() => libliTableGrid.layoutWidth(mk(`%s`))" % ROW_SPAN3  # noqa: UP031
    assert grid_page.evaluate(js) == 3


def test_slot_map_projects_a_rowspan_into_later_rows(grid_page):
    html = (
        "<tr><td id='a' rowspan='2'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    template = """() => {
             var sm = libliTableGrid.slotMap(mk(`%s`));
             return sm.map[1][0] === document.getElementById('a');
           }"""
    js = template % html  # noqa: UP031
    assert grid_page.evaluate(js) is True


def test_slot_map_of_an_empty_grid_has_zero_width(grid_page):
    assert grid_page.evaluate(
        """() => {
             var sm = libliTableGrid.slotMap(mk("<tr><td data-control></td></tr>"));
             return [sm.width, sm.height];
           }"""
    ) == [0, 1]


def test_slot_map_clips_a_rowspan_that_overflows_the_grid(grid_page):
    # Reachable from hand-edited JSON. Height stays the row count.
    assert grid_page.evaluate(
        """() => {
             var sm = libliTableGrid.slotMap(
               mk("<tr><td rowspan='9'></td><td data-control></td></tr>"));
             return [sm.width, sm.height];
           }"""
    ) == [1, 1]


def test_is_spanning_is_false_for_a_plain_grid(grid_page):
    js = "() => libliTableGrid.isSpanning(mk(`%s`))" % ROW_3  # noqa: UP031
    assert grid_page.evaluate(js) is False


def test_is_spanning_is_true_when_any_cell_spans(grid_page):
    js = "() => libliTableGrid.isSpanning(mk(`%s`))" % ROW_SPAN3  # noqa: UP031
    assert grid_page.evaluate(js) is True


# The server (TableElement.layout_dims) and the editor (slotMap) must never
# disagree about a grid's size: if they did, the caps could reject a grid the
# editor believes is legal -- an author-facing dead end with no way out.
SHARED_FIXTURES = [
    (
        [[{"colspan": 3}], [{}, {}, {}]],
        "<tr><td colspan='3'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td></td><td data-control></td></tr>",
    ),
    (
        [[{"rowspan": 2}, {}, {}], [{}, {}]],
        "<tr><td rowspan='2'></td><td></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>",
    ),
]


@pytest.mark.parametrize("cells,html", SHARED_FIXTURES)
def test_layout_dims_and_slot_map_agree(grid_page, cells, html):
    from courses.models import TableElement

    template = """() => {
             var sm = libliTableGrid.slotMap(mk(`%s`));
             return [sm.width, sm.height];
           }"""
    js = template % html  # noqa: UP031
    js_dims = grid_page.evaluate(js)
    assert tuple(js_dims) == TableElement.layout_dims(cells)


def _run(page, rows_html, js):
    template = "() => { var g = mk(`%s`); %s; return shape(g); }"
    return page.evaluate(template % (rows_html, js))  # noqa: UP031


def test_insert_column_grows_a_straddling_colspan(grid_page):
    # colspan=3 anchored at 0 covers 0,1,2. Inserting at 1 is strictly inside.
    rows = (
        "<tr><td colspan='3'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertColumn(g, 1)") == [
        "4x1",
        "1x1,1x1,1x1,1x1",
    ]


def test_insert_column_at_a_spans_anchor_does_not_grow_it(grid_page):
    # layoutCol == c is NOT straddling: a fresh cell goes in before the span.
    rows = (
        "<tr><td colspan='3'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertColumn(g, 0)") == [
        "1x1,3x1",
        "1x1,1x1,1x1,1x1",
    ]


def test_insert_column_at_the_far_edge_of_a_span_does_not_grow_it(grid_page):
    # layoutCol == c + s falls outside the span entirely.
    rows = (
        "<tr><td colspan='2'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertColumn(g, 2)") == [
        "2x1,1x1",
        "1x1,1x1,1x1",
    ]


def test_insert_column_appends_at_the_right_edge(grid_page):
    assert _run(grid_page, ROW_3, "libliTableGrid.insertColumn(g, 3)") == [
        "1x1,1x1,1x1,1x1"
    ]


def test_insert_column_through_rowspan_covered_rows_grows_the_span_once(grid_page):
    # A colspan=2 rowspan=3 cell straddling column 1: it grows ONCE, at its
    # anchor, and the covered rows gain nothing. "Insert into every row" would
    # produce a layout-inconsistent grid here.
    rows = (
        "<tr><td colspan='2' rowspan='3'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertColumn(g, 1)") == [
        "3x3,1x1",
        "1x1",
        "1x1",
    ]


def test_insert_column_at_the_anchor_of_a_rowspan_gives_every_row_a_cell(grid_page):
    # The layoutCol == c edge for a rowspan=3 colspan=1 cell: all three rows
    # gain a cell and the layout stays consistent.
    rows = (
        "<tr><td></td><td></td><td rowspan='3'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertColumn(g, 2)") == [
        "1x1,1x1,1x1,1x3",
        "1x1,1x1,1x1",
        "1x1,1x1,1x1",
    ]


def test_insert_column_position_follows_layout_not_sibling_index(grid_page):
    # (0,0) has rowspan=2, so row 1's data cells sit at layout columns 1,2,3.
    # Inserting at layout column 2 must land at SIBLING index 1 in row 1.
    rows = (
        "<tr><td id='rs' rowspan='2'></td><td></td><td></td><td></td>"
        "<td data-control></td></tr>"
        "<tr><td></td><td id='mark'></td><td></td><td data-control></td></tr>"
    )
    template = """() => {
             var g = mk(`%s`);
             libliTableGrid.insertColumn(g, 2);
             var row1 = g.cells(g.rows()[1]);
             return row1.indexOf(document.getElementById('mark'));
           }"""
    idx = grid_page.evaluate(template % rows)  # noqa: UP031
    # 'mark' was at sibling index 1 and the new cell went in before it.
    assert idx == 2


def test_delete_column_shrinks_a_covering_colspan(grid_page):
    rows = (
        "<tr><td colspan='3'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.deleteColumn(g, 1)") == [
        "2x1",
        "1x1,1x1",
    ]


def test_delete_column_at_a_spans_anchor_still_decrements_it(grid_page):
    # The COVERING predicate, not the strict straddle one. Under the straddle
    # test this cell would keep colspan=3 in a 2-wide grid -- inconsistent.
    rows = (
        "<tr><td colspan='3'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.deleteColumn(g, 0)") == [
        "2x1",
        "1x1,1x1",
    ]


def test_delete_column_removes_a_cell_whose_last_column_goes(grid_page):
    rows = (
        "<tr><td></td><td id='doomed'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>"
    )
    template = """() => {
             var g = mk(`%s`);
             libliTableGrid.deleteColumn(g, 1);
             return document.getElementById('doomed') === null;
           }"""
    gone = grid_page.evaluate(template % rows)  # noqa: UP031
    assert gone is True
