(function () {
  "use strict";

  // ---- Span-aware grid algebra, shared by table_editor.js and
  // filltable_editor.js. -------------------------------------------------
  //
  // Deliberately knows NOTHING about cell kinds, toolbars, serialization, the
  // hidden field, or the editors' injected chrome. Every entry point takes a
  // `grid` descriptor supplied by the caller:
  //
  //   { rows:  () => [<tr>, ...],  // data rows only (control row excluded)
  //     cells: (tr) => [...],      // that row's data cells (control excluded)
  //     makeCell: () => <td>,      // caller's default empty cell
  //     makeRow:  () => <tr>,      // empty <tr> WITH the caller's row chrome
  //     maxCols: 20, maxRows: 50 } // caps, so this module holds no policy
  //
  // WHO ENFORCES THE CAPS: only canMerge, which refuses an over-sized range
  // (never clamps it). insertColumn/insertRow deliberately do NOT consult the
  // caps -- the callers gate those on refreshControlState, which also owns the
  // grandfathering rule the module has no way to know about.
  //
  // BOUNDS: deleteColumn, insertRow and deleteRow return without mutating on an
  // out-of-range index. insertColumn deliberately does NOT -- an index below 0
  // prepends and one past the width appends, which is what makes
  // insertColumn(grid, width) the documented "append at the right edge" form.
  //
  // `rows` is a FUNCTION, symmetrical with `cells`: insertRow/deleteRow change
  // the row list, and a materialized array would be stale exactly when the
  // bounds clamp needs the new height. The module cannot recompute the list
  // itself without knowing about tr[data-control-row], which the
  // chrome-agnostic contract forbids.

  function spanOf(cell, attr) {
    var n = parseInt(cell.getAttribute(attr), 10);
    return n > 1 ? n : 1;
  }

  function colspanOf(cell) { return spanOf(cell, "colspan"); }
  function rowspanOf(cell) { return spanOf(cell, "rowspan"); }

  // Write a span only when > 1, mirroring the model's rule that a span key is
  // absent at 1 -- so a fully-split grid serializes byte-identically to a
  // table that never had a merge.
  function setSpan(cell, attr, n) {
    if (n > 1) cell.setAttribute(attr, String(n));
    else cell.removeAttribute(attr);
  }

  // Standard HTML table cell-mapping.
  //   width  = max over cells of (anchor column + colspan), 0 for an empty grid
  //   height = number of data rows (an overflowing rowspan is CLIPPED for
  //            mapping, never counted as extra height)
  // Degenerate input is tolerated rather than repaired: last-writer-wins on a
  // slot collision, unreached slots stay null and count as unoccupied.
  function slotMap(grid) {
    var rows = grid.rows();
    var height = rows.length;
    var map = [];
    var r, c;
    for (r = 0; r < height; r++) map.push([]);
    var width = 0;
    for (r = 0; r < height; r++) {
      var cells = grid.cells(rows[r]);
      c = 0;
      for (var k = 0; k < cells.length; k++) {
        var cell = cells[k];
        while (map[r][c]) c++;
        var cs = colspanOf(cell);
        var rs = rowspanOf(cell);
        for (var dr = 0; dr < rs && r + dr < height; dr++) {
          for (var dc = 0; dc < cs; dc++) map[r + dr][c + dc] = cell;
        }
        c += cs;
        if (c > width) width = c;
      }
    }
    for (r = 0; r < height; r++) {
      for (c = 0; c < width; c++) if (!map[r][c]) map[r][c] = null;
    }
    return { map: map, width: width, height: height };
  }

  function layoutWidth(grid) { return slotMap(grid).width; }

  // The (r, c) a cell is anchored at, or null if it is not in the map.
  function anchorOf(sm, cell) {
    for (var r = 0; r < sm.height; r++) {
      for (var c = 0; c < sm.width; c++) {
        if (sm.map[r][c] === cell) return { r: r, c: c };
      }
    }
    return null;
  }

  function isSpanning(grid) {
    var rows = grid.rows();
    for (var r = 0; r < rows.length; r++) {
      var cells = grid.cells(rows[r]);
      for (var k = 0; k < cells.length; k++) {
        if (colspanOf(cells[k]) > 1 || rowspanOf(cells[k]) > 1) return true;
      }
    }
    return false;
  }

  window.libliTableGrid = {
    slotMap: slotMap,
    layoutWidth: layoutWidth,
    anchorOf: anchorOf,
    isSpanning: isSpanning,
    colspanOf: colspanOf,
    rowspanOf: rowspanOf,
    setSpan: setSpan,
  };
})();
