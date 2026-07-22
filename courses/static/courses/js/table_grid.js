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

  // Insert `td` into `tr` at LAYOUT column `layoutCol`.
  //
  // A ragged row's positional index diverges from its layout column, so
  // `tr.insertBefore(cell, cells(tr)[layoutCol])` is wrong: with a rowspan
  // anchored above, row 1's cells may start at layout column 1 or later.
  // Rule: before the first data cell whose layout column is >= layoutCol,
  // always before the trailing control cell; else last among the data cells.
  function insertCellAt(grid, sm, r, layoutCol) {
    var tr = grid.rows()[r];
    var cells = grid.cells(tr);
    var td = grid.makeCell();
    var ref = null;
    for (var k = 0; k < cells.length; k++) {
      var a = anchorOf(sm, cells[k]);
      if (a && a.r === r && a.c >= layoutCol) { ref = cells[k]; break; }
    }
    if (ref) tr.insertBefore(td, ref);
    else if (cells.length) cells[cells.length - 1].after(td);
    else tr.insertBefore(td, tr.firstChild); // before the control cell
    return td;
  }

  // A cell STRADDLES layoutCol iff it occupies both the slot before it and the
  // slot at it -- i.e. strict `c < layoutCol < c + colspan`. Used by INSERT.
  function straddlerAt(sm, r, layoutCol) {
    if (layoutCol <= 0 || layoutCol >= sm.width) return null;
    var before = sm.map[r][layoutCol - 1];
    var at = sm.map[r][layoutCol];
    return before && before === at ? before : null;
  }

  function insertColumn(grid, layoutCol) {
    var sm = slotMap(grid);
    var grown = [];
    for (var r = 0; r < sm.height; r++) {
      var straddler = straddlerAt(sm, r, layoutCol);
      if (straddler) {
        // Grow exactly ONCE, at the anchor -- a rowspan cell straddles in
        // every row it covers, and the covered rows gain no new cell.
        if (grown.indexOf(straddler) === -1) {
          setSpan(straddler, "colspan", colspanOf(straddler) + 1);
          grown.push(straddler);
        }
        continue;
      }
      insertCellAt(grid, sm, r, layoutCol);
    }
  }

  // Delete uses the COVERING predicate: any cell occupying the column, whether
  // or not it straddles. A cell anchored AT layoutCol must still decrement, or
  // it keeps claiming a column that no longer exists.
  function deleteColumn(grid, layoutCol) {
    var sm = slotMap(grid);
    if (layoutCol < 0 || layoutCol >= sm.width) return;
    var seen = [];
    for (var r = 0; r < sm.height; r++) {
      var cell = sm.map[r][layoutCol];
      if (!cell || seen.indexOf(cell) !== -1) continue;
      seen.push(cell);
      var next = colspanOf(cell) - 1;
      if (next <= 0) cell.remove();
      else setSpan(cell, "colspan", next);
    }
  }

  // Append a data cell to `tr`, before the trailing control cell.
  function appendDataCell(grid, tr, td) {
    var cells = grid.cells(tr);
    if (cells.length) cells[cells.length - 1].after(td);
    else tr.insertBefore(td, tr.firstChild);
    return td;
  }

  function insertRow(grid, layoutRow) {
    var sm = slotMap(grid);
    var rows = grid.rows();
    if (!rows.length) return null;
    // Bounds-check like every other entry point. Without this, layoutRow >
    // height makes sm.map[layoutRow - 1] undefined and the loop below throws.
    if (layoutRow < 0 || layoutRow > sm.height) return null;
    var tr = grid.makeRow();
    if (layoutRow >= sm.height) rows[rows.length - 1].after(tr);
    else rows[layoutRow].parentNode.insertBefore(tr, rows[layoutRow]);

    // Mirror of insertColumn: a cell STRADDLES the insertion row iff it
    // occupies both the slot above it and the slot at it. A cell anchored AT
    // layoutRow does not suppress a new cell.
    var grown = [];
    for (var c = 0; c < sm.width; c++) {
      var above = layoutRow > 0 ? sm.map[layoutRow - 1][c] : null;
      var at = layoutRow < sm.height ? sm.map[layoutRow][c] : null;
      if (above && above === at) {
        if (grown.indexOf(above) === -1) {
          setSpan(above, "rowspan", rowspanOf(above) + 1);
          grown.push(above);
        }
        continue;
      }
      appendDataCell(grid, tr, grid.makeCell());
    }
    return tr;
  }

  // Enforce the bounds invariant: r + rowspan <= height. Only the ROW axis is
  // falsifiable -- width is DEFINED as max(c + colspan), so its half is a
  // tautology. An overflowing rowspan shoves the injected control row sideways
  // and misaligns every handle, so it must be clamped after any op.
  function clampRowspans(grid) {
    var sm = slotMap(grid);
    var rows = grid.rows();
    for (var r = 0; r < rows.length; r++) {
      var cells = grid.cells(rows[r]);
      for (var k = 0; k < cells.length; k++) {
        if (r + rowspanOf(cells[k]) > sm.height) {
          setSpan(cells[k], "rowspan", Math.max(1, sm.height - r));
        }
      }
    }
  }

  function deleteRow(grid, layoutRow) {
    var sm = slotMap(grid);
    var rows = grid.rows();
    if (layoutRow < 0 || layoutRow >= rows.length) return;
    var tr = rows[layoutRow];
    var isLast = layoutRow === rows.length - 1;

    // (a) Cells merely STRADDLING the deleted row (anchored above it) just
    //     decrement; no node moves.
    var handled = [];
    for (var c = 0; c < sm.width; c++) {
      var cell = sm.map[layoutRow][c];
      if (!cell || handled.indexOf(cell) !== -1) continue;
      handled.push(cell);
      var a = anchorOf(sm, cell);
      if (a && a.r < layoutRow) setSpan(cell, "rowspan", rowspanOf(cell) - 1);
    }

    // (b) Cells ANCHORED in the deleted row with rowspan > 1 relocate into the
    //     next row they cover, at an index computed from THAT row's slot map.
    //     Terminal case: on the last row there is nothing to relocate into
    //     (only reachable via an overflowing stored rowspan), so the cell goes
    //     with its row.
    if (!isLast) {
      var target = rows[layoutRow + 1];
      var anchored = grid.cells(tr);
      for (var k = 0; k < anchored.length; k++) {
        var moving = anchored[k];
        if (rowspanOf(moving) <= 1) continue;
        var am = anchorOf(sm, moving);
        setSpan(moving, "rowspan", rowspanOf(moving) - 1);
        var tcells = grid.cells(target);
        var ref = null;
        for (var j = 0; j < tcells.length; j++) {
          var ta = anchorOf(sm, tcells[j]);
          if (ta && ta.c > am.c) { ref = tcells[j]; break; }
        }
        if (ref) target.insertBefore(moving, ref);
        else appendDataCell(grid, target, moving);
      }
    }

    tr.remove();
    clampRowspans(grid);
  }

  window.libliTableGrid = {
    slotMap: slotMap,
    layoutWidth: layoutWidth,
    anchorOf: anchorOf,
    isSpanning: isSpanning,
    colspanOf: colspanOf,
    rowspanOf: rowspanOf,
    setSpan: setSpan,
    insertColumn: insertColumn,
    deleteColumn: deleteColumn,
    insertCellAt: insertCellAt,
    insertRow: insertRow,
    deleteRow: deleteRow,
    clampRowspans: clampRowspans,
  };
})();
