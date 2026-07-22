# Spanning-Table Editor (Cell Merge / Split) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach both WYSIWYG table editors (`TableElement` and `FillTableElement`) about `colspan`/`rowspan` — stop the silent span-stripping on save, and add a Merge/Split/Header-cell UI with span-aware row/column operations.

**Architecture:** A new chrome-agnostic JS module `table_grid.js` holds all span-aware grid algebra (slot map, insert/delete, merge/split) and is driven by a caller-supplied `grid` descriptor, so both editors share one implementation without being merged. Server-side, `TableElementForm`'s ragged-rows rejection is relaxed for spanning grids, size caps move to layout terms (grandfathered), and a `grid_data` form property fixes the bound-invalid re-render. Work lands in five slices: round-trip fidelity → grid algebra → table editor UI → fill-table editor UI → help/i18n/verification.

**Tech Stack:** Django 5.2, vanilla ES5-style JS (no build step, no framework), Playwright for e2e, pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-spanning-table-editor-design.md` — read it before starting. It records *why* each rule is what it is; this plan records *how*.

## Global Constraints

- **Non-spanning tables must serialize byte-identically to today.** No `colspan`, `rowspan`, or `header` key may appear for a table with no merges and no header cells. Every task that touches `serialize()` or a template must preserve this.
- **Never rectangularise a spanning grid.** Rows stay ragged; merge removes absorbed cells, split re-inserts them.
- **Fill-table cell kinds are `static | answer | image`** and must survive every operation — an answer cell's string and an image cell's `media` pk are only ever discarded through the merge confirm.
- **Insert uses the strict straddle predicate** (`c < layoutCol < c + colspan`); **delete uses the covering predicate** (`c <= layoutCol < c + colspan`). Conflating them corrupts grids in opposite directions.
- **`width = max over cells of (c + colspan)`, `0` for an empty grid. `height = number of data rows.`** Identical in JS (`slotMap`) and Python (`layout_dims`) **for any grid the forms accept** — `layout_dims` routes spans through `_span`, which clamps, while JS's `spanOf` does not, so a hand-edited `colspan: 99` would give 20 vs 99. The forms reject that payload, so the divergence is unreachable in practice.
- **Student practice state is knowingly left behind.** `filltable_check` and `filltable.js` key answers by positional `(r, c)`, so a merge or split re-indexes cells and a saved answer can restore into the wrong one. The spec declares this an explicit non-goal (it is equally true of today's column insert/delete), so no task here re-keys it — but do not "discover" it mid-implementation and improvise a fix.
- **Caps gate growth, not absolute size.** `MAX_COLS = 20`, `MAX_ROWS = 50`; an existing over-cap grid (the 26-wide `130_kombinatoryka` table) stays saveable. Per-axis: reject iff `new_axis > cap and new_axis > stored_axis`.
- **Refuse, never silently clamp.** An out-of-range span is a `ValidationError`, not a truncation.
- **Test command:** `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e"`. Do **not** set `DJANGO_SETTINGS_MODULE` **on pytest invocations** (pyproject already pins `config.settings.test`; forcing `local` causes a false failure in `tests/test_auth_styles.py`). `manage.py` commands against `libli_mat` *do* need `DJANGO_SETTINGS_MODULE=config.settings.local` — see Task 18. Do **not** pipe pytest through `tail` — the harness then reports the pipe's exit code.
- **e2e command:** same, with `-m e2e`. Slice 2's grid-algebra loop uses `-m e2e -k table_grid`.
- **Lint:** `uv run ruff check .` and `uv run ruff format --check .` before every commit.
- **Every task is TDD:** write the failing test, *verify it fails for the stated reason*, implement, verify green, commit.

---

## File Structure

**Created:**
- `courses/static/courses/js/table_grid.js` — all span-aware grid algebra. Pure functions over a caller-supplied descriptor; no DOM chrome knowledge, no serialization, no toolbar.
- `tests/test_table_grid_algebra.py` — Playwright-hosted unit tests for the above (pure functions, run in a headless page because CI has no Node).
- `tests/test_spanning_roundtrip.py` — server-side round-trip + form tests.
- `tests/test_cell_selector_guard.py` — source-level guard that every data-cell selector also matches `th`.
- `tests/test_e2e_spanning_roundtrip.py` — the headline browser-driven data-loss test.
- `tests/test_e2e_spanning_merge.py` — real-gesture merge/split e2e for both editors.

**Modified:**
- `courses/models.py` — `TableElement._span` per-axis clamp; new `TableElement.layout_dims`.
- `courses/element_forms.py` — `_scan_spans` helper; `TableElementForm.clean_data` relaxation; `FillTableElementForm.clean_data` layout caps; `grid_data` property on both.
- `templates/courses/elements/tableelement.html`, `filltableelement.html` — spans on the `header_row`/`header_col` `<th>` branches.
- `templates/courses/manage/editor/_edit_table.html`, `_edit_filltable.html` — emit spans, `<th>` per kind branch, bind `d` from `form.grid_data`, new toolbar buttons + `data-msg-*`.
- `templates/courses/manage/editor/editor.html` — three new sprite symbols, `table_grid.js` script tag.
- `courses/static/courses/js/table_editor.js`, `filltable_editor.js` — selector widening, span serialization, selection state, toolbar wiring.
- `courses/static/courses/css/editor.css`, `courses.css` — `th` in cell selectors, range highlight.
- `docs/help/course-admin/content-editors.md` + `.pl.md`, `interactive-elements.md` + `.pl.md`.
- `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`.

---

# SLICE 1 — Round-trip fidelity

Goal: a spanning table opens correctly and saves **without losing its spans**, and the structural handles are disabled while they are still span-unaware. Nothing here adds merge/split UI.

---

### Task 1: `layout_dims` + per-axis `_span` clamp

**Files:**
- Modify: `courses/models.py:831-841` (`TableElement._span`), add `layout_dims` beside it
- Test: `tests/test_spanning_roundtrip.py` (create)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `TableElement.layout_dims(cells) -> tuple[int, int]` returning `(width, height)`; `TableElement._span(raw, key)` unchanged in signature, now clamping `rowspan` to `MAX_ROWS`

- [ ] **Step 1: Write the failing test**

Create `tests/test_spanning_roundtrip.py`:

```python
"""Server-side behaviour for spanning (colspan/rowspan) tables: layout
dimensions, form validation relaxation, caps grandfathering, and the
bound-invalid re-render seam."""

import re

import pytest

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
```

- [ ] **Step 2: Run the tests to verify they fail**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -v
```

Expected: `test_span_clamps_rowspan_against_max_rows_not_max_cols` FAILS (asserts 30, gets 20 — the column cap applied to a rowspan). All `layout_dims` tests FAIL with `AttributeError: type object 'TableElement' has no attribute 'layout_dims'`.

- [ ] **Step 3: Fix `_span` and add `layout_dims`**

In `courses/models.py`, replace the body of `TableElement._span` and add `layout_dims` directly after it:

```python
    @staticmethod
    def _span(raw, key):
        """A colspan/rowspan value: a positive int > 1, clamped to that axis's
        cap, else absent. Kept out of the cell dict when 1 so non-spanning
        tables and the WYSIWYG editor are unaffected.

        The clamp is per-axis: a rowspan clamped against MAX_COLS would
        silently truncate a legal 30-row span. It is defence-in-depth only —
        the forms REJECT an out-of-range span rather than relying on this
        (a silent clamp produces a layout-inconsistent grid)."""
        n = raw.get(key)
        if isinstance(n, bool) or not isinstance(n, int):
            return None
        cap = TableElement.MAX_ROWS if key == "rowspan" else TableElement.MAX_COLS
        return min(n, cap) if n > 1 else None

    @staticmethod
    def layout_dims(cells):
        """(width, height) of a grid in LAYOUT terms, i.e. accounting for
        colspan/rowspan rather than counting cells per row.

        width = max over cells of (anchor column + colspan), 0 for an empty
        grid; height = number of rows. Identical to table_grid.js's slotMap()
        so the server and the editor can never disagree about a grid's size.

        Degenerate input is coerced, never raised on (this runs on raw
        author-supplied JSON in TableElementForm): a non-dict cell counts as a
        1x1 occupant, a span value that fails _span's type test counts as 1,
        and a non-list row is skipped."""
        rows = cells if isinstance(cells, list) else []
        occupied = set()
        width = 0
        for r, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            c = 0
            for cell in row:
                raw = cell if isinstance(cell, dict) else {}
                while (r, c) in occupied:
                    c += 1
                colspan = TableElement._span(raw, "colspan") or 1
                rowspan = TableElement._span(raw, "rowspan") or 1
                for dr in range(rowspan):
                    for dc in range(colspan):
                        occupied.add((r + dr, c + dc))
                c += colspan
                width = max(width, c)
        return width, len(rows)
```

- [ ] **Step 4: Run the tests to verify they pass**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Run the full suite to check for regressions**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e" -q
```

Expected: no new failures. (`_span`'s rowspan behaviour changed, so watch `tests/test_table_*.py` and `tests/test_filltable_*.py`.)

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add courses/models.py tests/test_spanning_roundtrip.py
git commit -m "feat(tables): add layout_dims and fix _span's per-axis clamp"
```

---

### Task 2: `_scan_spans` + form relaxation and layout caps

**Files:**
- Modify: `courses/element_forms.py:1332-1400` (both `clean_data` methods), add `_scan_spans` above `TableElementForm`
- Test: `tests/test_spanning_roundtrip.py` (append)

**Interfaces:**
- Consumes: `TableElement.layout_dims(cells)`, `TableElement._span(raw, key)` from Task 1
- Produces: `courses.element_forms._scan_spans(cells) -> bool` (True when the grid is spanning; raises `ValidationError` on an out-of-range raw span). Both `clean_data` methods now accept ragged spanning grids.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spanning_roundtrip.py` — but put the two new imports in the file's
**existing top-of-file import block**, not above the appended tests. `pyproject.toml`
selects `E` and `I`, so a mid-file import is an immediate `E402` / isort failure at this
task's own lint gate. The same applies to every later append in this plan.

```python
# --- add to the imports at the TOP of the file ---
from courses.element_forms import FillTableElementForm
from courses.element_forms import TableElementForm

# --- append below the existing tests ---


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
    stored = TableElement.objects.create(data=TableElement.normalize_data({"cells": wide}))
    form = _table_form({"cells": wide}, instance=stored)
    assert form.is_valid(), form.errors


def test_grandfathered_grid_may_narrow_but_not_widen():
    wide = [[{} for _ in range(26)]]
    stored = TableElement.objects.create(data=TableElement.normalize_data({"cells": wide}))

    narrower = [[{} for _ in range(24)]]
    assert _table_form({"cells": narrower}, instance=stored).is_valid()

    wider = [[{} for _ in range(27)]]
    assert not _table_form({"cells": wider}, instance=stored).is_valid()


def test_grandfathering_is_per_axis():
    # Stored 26 wide x 1 tall. Narrowing columns does not license growing rows
    # past MAX_ROWS.
    wide = [[{} for _ in range(26)]]
    stored = TableElement.objects.create(data=TableElement.normalize_data({"cells": wide}))
    too_tall = [[{}, {}] for _ in range(51)]
    assert not _table_form({"cells": too_tall}, instance=stored).is_valid()
```

- [ ] **Step 2: Run the tests to verify they fail**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -v
```

Expected: `test_ragged_spanning_grid_is_accepted` FAILS with the "All table rows must have the same number of cells." error — this is the blocker the whole design rests on. Import of `_scan_spans` is not yet needed, but the caps/grandfathering tests FAIL because the cap is still computed from per-row cell counts.

- [ ] **Step 3: Add `_scan_spans`**

In `courses/element_forms.py`, immediately above `class TableElementForm`:

```python
def _scan_spans(cells):
    """Detect whether a raw, author-supplied grid is spanning, and reject an
    out-of-range span while we are here.

    Returns True iff any cell carries a real colspan/rowspan (> 1). Detection
    goes through TableElement._span so it cannot diverge from the branch
    normalize_data will actually take -- notably, _span does NOT coerce, so a
    string "3" is not a span.

    The RANGE check deliberately reads the RAW int instead: _span's return is
    already clamped to the cap and so can never look out of range. Values below
    2 are not spans at all and are ignored rather than rejected, matching both
    _span (None) and layout_dims (counts as 1).

    Coerces defensively at both levels, mirroring normalize_data: a non-list
    `cells` is empty, a non-list row is skipped, a non-dict cell is skipped.
    TableElementForm has its own guards ahead of this, but
    FillTableElementForm does not -- without this, a crafted {"cells": 5}
    would be `for r in 5` -> TypeError -> 500."""
    rows = cells if isinstance(cells, list) else []
    spanning = False
    for row in rows:
        if not isinstance(row, list):
            continue
        for cell in row:
            if not isinstance(cell, dict):
                continue
            for key, cap in (
                ("colspan", TableElement.MAX_COLS),
                ("rowspan", TableElement.MAX_ROWS),
            ):
                raw = cell.get(key)
                if isinstance(raw, bool) or not isinstance(raw, int) or raw < 2:
                    continue
                if raw > cap:
                    # Two msgids, not one interpolated with 20 or 50: a single
                    # nounless string ("more than 20.") cannot be translated
                    # correctly, and Polish needs the axis word to inflect.
                    raise forms.ValidationError(
                        _("A merged cell may not span more than %(n)d columns.")
                        % {"n": cap}
                        if key == "colspan"
                        else _("A merged cell may not span more than %(n)d rows.")
                        % {"n": cap}
                    )
            if (
                TableElement._span(cell, "colspan") is not None
                or TableElement._span(cell, "rowspan") is not None
            ):
                spanning = True
    return spanning


def _caps_ok(form, cells):
    """True iff the grid's LAYOUT dimensions are within the caps, or are no
    larger than what is already stored (grandfathering).

    The 26-column 130_kombinatoryka table already exceeds MAX_COLS, so an
    absolute cap would make an existing element permanently unsaveable. The
    caps therefore gate GROWTH, per axis, against the pre-save DB value.
    (0, 0) for an unsaved instance -- an explicit special case, because
    normalize_data({}) returns the default 2x2, not an empty grid."""
    model = form._meta.model
    # Read the caps off the FORM'S model, not TableElement: they are equal
    # today (FillTableElement aliases them), but hardcoding one model's caps
    # here while the error message interpolates the other's would silently
    # disagree the moment they diverge.
    max_cols, max_rows = model.MAX_COLS, model.MAX_ROWS
    width, height = TableElement.layout_dims(cells)
    if form.instance.pk is None:
        stored_w, stored_h = 0, 0
    else:
        stored = model.normalize_data(form.instance.data)["cells"]
        stored_w, stored_h = TableElement.layout_dims(stored)
    if width > max_cols and width > stored_w:
        return False
    if height > max_rows and height > stored_h:
        return False
    return True
```

- [ ] **Step 4: Relax `TableElementForm.clean_data`**

Replace the width/caps portion of `TableElementForm.clean_data` (currently `widths = {...}` through the `n_rows, n_cols` cap check). The two existing guards stay **first and unchanged**:

```python
        widths = {len(r) if isinstance(r, list) else -1 for r in rows}
        # Present-but-malformed grid IS an error (non-list row, or EVERY row
        # empty). Note this is not a per-row zero-width rejection: a single
        # empty row is legal, and is exactly what a full-width multi-row merge
        # produces.
        if -1 in widths or widths == {0}:
            raise forms.ValidationError(_("A table needs at least one cell."))
        # Only now decide which structural check applies. A spanning grid is
        # ragged by construction, so the uniform-width rule cannot hold for it.
        spanning = _scan_spans(rows)
        if not spanning and len(widths) != 1:
            raise forms.ValidationError(
                _("All table rows must have the same number of cells.")
            )
        if not _caps_ok(self, rows):
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": TableElement.MAX_ROWS, "c": TableElement.MAX_COLS}
            )
        # Coerce enums / fill cell defaults (does not resize a valid grid).
        return TableElement.normalize_data(data)
```

- [ ] **Step 5: Give `FillTableElementForm.clean_data` the same caps**

`FillTableElementForm.clean_data` currently derives `n_cols = len(cells[0])`, which is meaningless once row 0 is one merged cell. Its span work must run on the **raw** payload before `normalize_data` (afterwards every span has already been clamped, so a range check is impossible). Replace its opening:

```python
    def clean_data(self):
        from courses.filltable import answer_cells
        from courses.filltable import is_blank_answer

        data = self.cleaned_data.get("data")
        raw_cells = data.get("cells") if isinstance(data, dict) else None
        # Raw scan FIRST: rejects an out-of-range span before normalize_data
        # clamps it out of sight. Coerces malformed input rather than raising.
        _scan_spans(raw_cells)
        nd = FillTableElement.normalize_data(data if isinstance(data, dict) else {})
        cells = nd["cells"]
        if not _caps_ok(self, cells):
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": FillTableElement.MAX_ROWS, "c": FillTableElement.MAX_COLS}
            )
```

(Delete the old `n_rows, n_cols = len(cells), len(cells[0])` block and its cap check; the rest of the method — answer-cell guards, media scoping — is unchanged.)

- [ ] **Step 6: Run the tests to verify they pass**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -v
```

Expected: all pass.

- [ ] **Step 7: Run the full suite**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e" -q
```

Expected: no new failures. Watch `tests/test_filltable_form.py` and `tests/test_table_*` — the caps message and validation order both moved.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add courses/element_forms.py tests/test_spanning_roundtrip.py
git commit -m "feat(tables): accept ragged spanning grids and move caps to layout terms"
```

---

### Task 3: `grid_data` — bound-invalid re-render seam

**Files:**
- Modify: `courses/element_forms.py` (add `grid_data` to both form classes)
- Modify: `templates/courses/manage/editor/_edit_table.html:6`, `_edit_filltable.html:8`
- Test: `tests/test_spanning_roundtrip.py` (append)

**Interfaces:**
- Consumes: `_scan_spans`, `_caps_ok` from Task 2
- Produces: `form.grid_data` — a normalised data dict, used by both editor templates in place of `form.instance.normalized_data`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spanning_roundtrip.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -k grid_data -v
```

Expected: FAIL with `AttributeError: 'TableElementForm' object has no attribute 'grid_data'`.

- [ ] **Step 3: Add the property to both forms**

Add `import json` at the top of `courses/element_forms.py` if absent, then add this identical property to **both** `TableElementForm` and `FillTableElementForm`:

```python
    @property
    def grid_data(self):
        """Normalised grid the editor template renders from.

        On a bound-INVALID form this is the SUBMITTED payload, not the stored
        one. The hidden name="data" field always carries the submission, and
        serialize() skips its init pass when that field is non-empty -- so
        rendering the stored grid after a rejected save shows the author their
        pre-edit table while the field still holds the edit, and their next
        Save silently re-posts the rejected shape.

        The templates cannot do this themselves: the submission exists only as
        an unparsed JSON string and Django templates have no json.loads.

        Falls back to the stored value when unbound, valid, absent,
        unparseable, or not a dict (which also covers the add path)."""
        if self.is_bound and not self.is_valid():
            raw = self.data.get("data")
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    return self._meta.model.normalize_data(parsed)
        return self.instance.normalized_data
```

- [ ] **Step 4: Point both editor templates at it**

`templates/courses/manage/editor/_edit_table.html` line 6:

```
{% with d=form.grid_data %}
```

`templates/courses/manage/editor/_edit_filltable.html` line 8: same change.

The fill-table template also iterates `form.instance.resolved_cells` for its grid (line
63). Leave that for now — Task 5 replaces it with `form.resolved_grid_cells`, which is
where the image-pk resolution has to live. **Note it in the commit message**, because
until then the fill-table renders its *controls* from the submitted payload and its *grid*
from the stored instance — a deliberately temporary halfway state, and the plain
"re-render the submitted grid" subject would be false for that editor:

```bash
git commit -m "fix(editor): re-render the submitted grid after a rejected save

The fill-table's grid still renders from the stored instance until Task 5
adds resolved_grid_cells; its controls already honour the submission."
```

- [ ] **Step 5: Run to verify pass**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -v
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_table_editor_partial.py tests/test_filltable_editor_partial.py -v
```

Expected: all pass.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add courses/element_forms.py templates/courses/manage/editor/_edit_table.html templates/courses/manage/editor/_edit_filltable.html tests/test_spanning_roundtrip.py
git commit -m "fix(editor): re-render the submitted grid after a rejected save"
```

---

### Task 4: render templates — spans on the `header_row`/`header_col` `<th>` branches

**Files:**
- Modify: `templates/courses/elements/tableelement.html:18-24`, `templates/courses/elements/filltableelement.html:26-30`
- Test: `tests/test_spanning_roundtrip.py` (append)

**Interfaces:**
- Consumes: nothing new
- Produces: student-facing renders that keep `colspan`/`rowspan` on every `<th>` branch

- [ ] **Step 1: Write the failing test**

```python
def test_header_row_th_keeps_its_span_in_the_student_render():
    # 250_pole_trojkata has header_row=True, so a merge in row 0 goes through
    # the header_row <th> branch -- which drops the span today.
    el = TableElement(
        data=TableElement.normalize_data(
            {"header_row": True, "cells": [[{"colspan": 3, "html": "hi"}], [{}, {}, {}]]}
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
                "cells": [[{"rowspan": 2, "html": "m"}, {"html": "b"}], [{"html": "c"}]],
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
```

- [ ] **Step 2: Verify failure**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py -k th_keeps -v
```

Expected: 3 FAIL — the rendered `<th>` has no `colspan`/`rowspan` attribute.

> `test_merging_away_a_header_col_rows_first_cell_promotes_the_next_one` is deliberately
> **not** in that `-k` filter. It is a **regression pin** for behaviour that already
> works, not a RED-first test, so it passes the moment it is written — the one exemption
> from this plan's TDD rule, stated so it does not look like an oversight. To convince
> yourself it is not vacuous, temporarily move the `{% elif forloop.first and
> data.header_col %}` branch below the plain `<td>` branch and confirm it goes red.

- [ ] **Step 3: Add the attributes**

Define the span fragment once at the top of `templates/courses/elements/tableelement.html` (after the opening comment) so the four branches stay readable:

```django
{% comment %}Spans must appear on EVERY branch that can emit a cell, not just the
per-cell `header` and plain `<td>` ones: a merge inside a header_row/header_col
table goes through those <th> branches, and dropping the span there silently
breaks the layout the editor saved.{% endcomment %}
```

Then add `{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}` to each of the three `<th>` branches that lack it — the `<th>` tags are on **lines 19, 21 and 23** of `tableelement.html` (18/20/22 are their `{% elif %}` conditions) — exactly as the `cell.header` branch already has it. For example:

```django
          {% elif forloop.parentloop.first and data.header_row and forloop.first and data.header_col %}
            <th class="ta-{{ cell.halign }} va-{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>{{ cell.html|safe }}</th>
```

Do the same for the single combined `<th>` branch in `filltableelement.html` (the `<th>`
tag itself is on lines 28-29).

- [ ] **Step 4: Verify pass + no regression**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_spanning_roundtrip.py tests/test_table_css.py tests/test_filltable_render.py -v
```

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/tableelement.html templates/courses/elements/filltableelement.html tests/test_spanning_roundtrip.py
git commit -m "fix(tables): keep colspan/rowspan on header-row/col th branches"
```

---

### Task 5: editor templates emit spans + `<th>`; both `serialize()` read them back; widen every `td`-scoped selector

**Files:**
- Modify: `templates/courses/manage/editor/_edit_table.html:45-56`, `_edit_filltable.html:61-86`
- Modify: `courses/element_forms.py` (add `FillTableElementForm.resolved_grid_cells`)
- Modify: `courses/static/courses/js/table_editor.js` (lines 24-26, 169-188, 219-242)
- Modify: `courses/static/courses/js/filltable_editor.js` (lines 31-33, 193-233, 386-420, 595-597)
- Modify: `courses/static/courses/css/editor.css:595,600`; `courses/static/courses/css/courses.css:902,904`
- Test: `tests/test_table_editor_partial.py`, `tests/test_filltable_editor_partial.py` (append), new `tests/test_cell_selector_guard.py`

**Interfaces:**
- Consumes: `form.grid_data` from Task 3
- Produces: `FillTableElementForm.resolved_grid_cells`; editor grids that carry `colspan`/`rowspan`/`<th>`; `serialize()` emitting `colspan`/`rowspan` only when > 1 and `header: true` only for `TH`

- [ ] **Step 1: Write the failing partial-render tests**

Append to `tests/test_table_editor_partial.py`:

```python
def test_editor_grid_emits_spans_for_a_spanning_table():
    el = TableElement(
        data=TableElement.normalize_data(
            {"cells": [[{"colspan": 3, "rowspan": 2, "html": "m"}], [{}, {}]]}
        )
    )
    html = _render(el)
    assert 'colspan="3"' in html
    assert 'rowspan="2"' in html


def test_editor_grid_emits_th_for_a_header_cell():
    el = TableElement(
        data=TableElement.normalize_data({"cells": [[{"header": True, "html": "h"}, {}]]})
    )
    html = _render(el)
    assert "<th" in html
    # a header cell in the plain table is still editable
    assert re.search(r"<th[^>]*contenteditable", html)


def test_editor_grid_of_a_plain_table_has_no_span_attributes():
    html = _render(TableElement())
    assert "colspan" not in html
    assert "rowspan" not in html
    assert "<th" not in html


def test_editor_grid_does_not_promote_header_row_or_col_cells_to_th():
    """The riskiest byte-identity case, and the one the default 2x2 misses.

    If the EDITOR promoted header_row/header_col cells to <th>, serialize()
    would start writing header:true for cells that never carried it -- breaking
    byte-identity for every existing header-row table in the corpus. Only a
    cell's OWN header flag may produce a <th> here."""
    el = TableElement(
        data=TableElement.normalize_data(
            {"header_row": True, "header_col": True, "cells": [[{}, {}], [{}, {}]]}
        )
    )
    html = _render(el)
    # "<th" carries the whole signal. Do NOT also assert `"header" not in html`:
    # the border preset renders <option value="header"> unconditionally, so that
    # substring is present in every render, before and after this change.
    assert "<th" not in html
```

Append to `tests/test_filltable_editor_partial.py` (mirroring its existing `_render`
helper). Add `import re` to that file's top-of-file import block if it is not already
there — mid-file imports fail `E402`:

```python
def test_filltable_editor_answer_header_cell_is_th_without_contenteditable():
    el = FillTableElement(
        data=FillTableElement.normalize_data(
            {
                "cells": [
                    [{"kind": "answer", "answer": "a", "header": True},
                     {"kind": "static", "html": ""}]
                ]
            }
        )
    )
    html = _render(el)
    assert "<th" in html and "data-answer" in html
    # An answer cell is an <input>; making its TH contenteditable would let the
    # static-content handlers fire on it.
    assert not re.search(r"<th[^>]*data-answer[^>]*contenteditable", html)
```

- [ ] **Step 2: Verify failure**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_table_editor_partial.py tests/test_filltable_editor_partial.py -v
```

Expected: the span/`<th>` tests FAIL (no attributes emitted, always `<td>`).

- [ ] **Step 3: Emit spans and `<th>` in `_edit_table.html`**

Replace the grid loop (lines 45-56):

```django
  {% comment %}Cells carry their spans so the browser lays the EDITING grid out
  with the same geometry the student sees, and serialize() can read them back.
  A cell's own `header` flag wins over the header_row/header_col toggles --
  mirroring the render templates, where the cell.header branch comes first. The
  toggles themselves deliberately do NOT promote cells to <th> here: if they
  did, serialize() would start writing header:true for cells that never had it
  and break byte-identity for every existing header-row table.{% endcomment %}
  <div class="table-editor__grid" data-table-grid>
    <table>
      {% for row in d.cells %}
      <tr>
        {% for cell in row %}
        {% if cell.header %}
        <th contenteditable="true" class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>{{ cell.html|safe }}</th>
        {% else %}
        <td contenteditable="true" class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>{{ cell.html|safe }}</td>
        {% endif %}
        {% endfor %}
      </tr>
      {% endfor %}
    </table>
  </div>
```

- [ ] **Step 4: Same for `_edit_filltable.html`, per kind branch**

Its grid currently iterates `form.instance.resolved_cells`, which reads the *stored* instance and would defeat Task 3. Add a `resolved_grid_cells` property to `FillTableElementForm` that resolves image pks against `grid_data` instead:

```python
    @property
    def resolved_grid_cells(self):
        """grid_data's cells with image pks resolved to MediaAsset, mirroring
        FillTableElement.resolved_cells but sourced from grid_data so a
        rejected save re-renders the SUBMITTED grid (see grid_data)."""
        from courses.models import MediaAsset

        cells = self.grid_data["cells"]
        ids = [
            c.get("media")
            for row in cells
            for c in row
            if c.get("kind") == "image" and isinstance(c.get("media"), int)
        ]
        assets = MediaAsset.objects.in_bulk(ids) if ids else {}
        out = []
        for row in cells:
            out_row = []
            for c in row:
                if c.get("kind") == "image":
                    asset = assets.get(c.get("media"))
                    out_row.append(
                        {**c, "media": asset}
                        if asset
                        else {**c, "kind": "static", "html": ""}
                    )
                else:
                    out_row.append(c)
            out.append(out_row)
        return out
```

Then change `{% for row in form.instance.resolved_cells %}` to
`{% for row in form.resolved_grid_cells %}` and give each of the three kind branches a
`<th>` twin. All three are written out — this is the most intricate template edit in the
plan, and the branches differ in more than their tag name:

```django
        {% comment %}Each kind gets a <th> twin differing ONLY in tag name. Note
        which branches carry contenteditable: static cells do, answer and image
        cells do NOT (an answer cell is an <input>, and making its container
        editable would let the static-content keydown/input handlers -- now
        widened to accept th -- fire on it).{% endcomment %}
        {% if cell.kind == "answer" %}
          {% if cell.header %}
          <th data-answer class="ta-{{ cell.halign }} va-{{ cell.valign }}"
              data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>
            <input type="text" class="filltable-editor__answer" value="{{ cell.answer }}"
                   placeholder="{% trans 'Accepted answer' %}">
          </th>
          {% else %}
          <td data-answer class="ta-{{ cell.halign }} va-{{ cell.valign }}"
              data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>
            <input type="text" class="filltable-editor__answer" value="{{ cell.answer }}"
                   placeholder="{% trans 'Accepted answer' %}">
          </td>
          {% endif %}
        {% elif cell.kind == "image" %}
          {% if cell.header %}
          <th data-image data-media="{{ cell.media.pk }}" data-alt="{{ cell.alt }}" tabindex="0"
              class="ta-{{ cell.halign }} va-{{ cell.valign }}"
              data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>
            <img class="filltable-editor__img" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
          </th>
          {% else %}
          <td data-image data-media="{{ cell.media.pk }}" data-alt="{{ cell.alt }}" tabindex="0"
              class="ta-{{ cell.halign }} va-{{ cell.valign }}"
              data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>
            <img class="filltable-editor__img" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
          </td>
          {% endif %}
        {% else %}
          {% if cell.header %}
          <th contenteditable="true" class="ta-{{ cell.halign }} va-{{ cell.valign }}"
              data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>{{ cell.html|safe }}</th>
          {% else %}
          <td contenteditable="true" class="ta-{{ cell.halign }} va-{{ cell.valign }}"
              data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>{{ cell.html|safe }}</td>
          {% endif %}
        {% endif %}
```

The rule to hold: **`contenteditable="true"` appears on a `<th>` only where the corresponding `<td>` would carry it** — every cell in the plain table, static cells only in the fill-table.

- [ ] **Step 5: Read spans back in both `serialize()`s**

**Append these three lines to each existing per-cell object — do not replace the object.**
`table_editor.js` builds one shape (`{html, halign, valign}`); `filltable_editor.js` builds
three different ones (`kind: "answer"` + `answer`, `kind: "image"` + `media`/`alt`,
`kind: "static"` + `html`), and pasting a plain-table literal over them would wipe
`kind`/`answer`/`media`. So: keep each `row.push({...})` as it is, capture it in a local,
and add the three lines before pushing — in **all four** places (one in `table_editor.js`,
three in `filltable_editor.js`):

```js
          // Emit spans ONLY when > 1 and header ONLY for TH, so a table with
          // no merges and no header cells serializes byte-identically to
          // before this feature existed.
          if (td.colSpan > 1) cell.colspan = td.colSpan;
          if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
          if (td.tagName === "TH") cell.header = true;
          row.push(cell);
```

e.g. the fill-table's answer branch becomes:

```js
          } else if (td.hasAttribute("data-answer")) {
            var input = td.querySelector(".filltable-editor__answer");
            var cell = {
              kind: "answer",
              answer: input ? input.value : "",
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
            if (td.colSpan > 1) cell.colspan = td.colSpan;
            if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
            if (td.tagName === "TH") cell.header = true;
            row.push(cell);
```

- [ ] **Step 6: Widen every `td`-scoped selector**

Apply the full inventory from the spec. In `table_editor.js`:

```js
  function dataCells(tr) {
    // A "data cell" is any non-chrome cell, TD or TH. A <th> that only half
    // the selectors match would be un-focusable, un-alignable and invisible to
    // serialization.
    return tr.querySelectorAll("td:not([data-control]), th:not([data-control])");
  }
```

and change all three `closest("td[contenteditable]")` occurrences (focusin, keydown, input handlers) to `closest("td[contenteditable], th[contenteditable]")`.

In `filltable_editor.js`: `dataCells` → `"td:not([data-control]), th:not([data-control])"`; the `focusin` selector gains the three `th` variants; the two `closest("td[contenteditable]")` gain `th[contenteditable]`; the submit guard becomes
`querySelectorAll("td[data-answer] .filltable-editor__answer, th[data-answer] .filltable-editor__answer")`.

In `editor.css`, widen the **two data-cell selectors at 595 and 600** to include `th`.
Line 607 is `.table-editor__grid td[data-control]` and stays `td`-only — a control cell is
chrome and is never a `<th>`:

```css
.table-editor__grid td, .table-editor__grid th {
  min-width: 4rem; padding: var(--space-2);
  border: 1px solid var(--border-default);
  vertical-align: top;
}
.table-editor__grid td:focus, .table-editor__grid th:focus { outline: 2px solid var(--primary); outline-offset: -2px; }
```

In `courses.css` line 902/904:

```css
.el-editor--filltable .table-editor__grid td,
.el-editor--filltable .table-editor__grid th { border-color: var(--border-strong); }

.filltable-editor__grid td[data-answer],
.filltable-editor__grid th[data-answer] { background: var(--surface-sunken); }
```

- [ ] **Step 7: Add the source-level guard test**

Create `tests/test_cell_selector_guard.py`:

```python
"""Guard: every selector that can match a DATA cell must also match `th`.

A <th> matched by only half the editors' selectors is un-focusable,
un-alignable and invisible to serialization -- and all 48 `header: true`
cells in the imported corpus live in spanning tables, so this is not a corner
case. Two exemptions, named rather than blanket: chrome selectors scoped by
[data-control], and element construction (createElement("td")).

This test must go RED if any single row of the spec's selector inventory is
reverted."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The spec's selector inventory, as an EXPLICIT list rather than a broad regex.
# A general "any bare `td`" scan is unusable here: it matches the JS variable
# `td` (td.dataset, td.className, td.colSpan), unrelated components
# (.choicegrid td), and even `td.tagName === "TH"` -- 113 false positives
# across these four files. Enumerating the sites keeps the guard honest AND
# keeps it falsifiable, which a whitelist-everything regex would not be.
# Needles are chosen to survive the widening edit itself: `.table-editor__grid
# td` (no trailing brace) still matches after the rule becomes
# `.table-editor__grid td, .table-editor__grid th {`.
INVENTORY = [
    # (file, substring identifying the site, what must appear in its WINDOW)
    ("courses/static/courses/js/table_editor.js", 'querySelectorAll("td', "th"),
    ("courses/static/courses/js/table_editor.js", 'closest("td[contenteditable]', "th"),
    ("courses/static/courses/js/filltable_editor.js", 'querySelectorAll("td', "th"),
    ("courses/static/courses/js/filltable_editor.js", 'closest("td[contenteditable]', "th"),
    ("courses/static/courses/js/filltable_editor.js", "td[data-answer] .filltable-editor__answer", "th"),
    ("courses/static/courses/css/editor.css", ".table-editor__grid td", "th"),
    ("courses/static/courses/css/editor.css", ".table-editor__grid td:focus", "th"),
    ("courses/static/courses/css/courses.css", ".el-editor--filltable .table-editor__grid td", "th"),
    ("courses/static/courses/css/courses.css", ".filltable-editor__grid td[data-answer]", "th"),
]

# Exempt by design: CONTROL-CELL chrome selectors (a control cell is never a
# <th>) and element construction. Scoped to `td[data-control]` specifically --
# a bare `data-control` test would also swallow
# `querySelectorAll("td:not([data-control]), th:not([data-control])")`, i.e.
# the correctly-widened dataCells line this guard exists to check.
EXEMPT = re.compile(r"td\[data-control\]|createElement")

# CSS selector lists may be split across lines, so a needle's `th` twin can sit
# on the NEXT line. Check a small window rather than the single matched line.
WINDOW = 2

# `th` as a WHOLE token. A bare substring test is vacuous over a 2-line window:
# editor.css:595 is followed by `min-width: 4rem;` -- which contains "th" -- so
# that row would pass whether or not the selector was ever widened. ("this",
# "them", "path" do the same elsewhere.)
TH_TOKEN = re.compile(r"(?<![a-z])th(?![a-z])")


def test_every_inventoried_data_cell_selector_also_matches_th():
    """Any selector that can match a DATA cell must also match `th`.

    A <th> matched by only half the editors' selectors is un-focusable,
    un-alignable and invisible to serialization -- and all 48 `header: true`
    cells in the imported corpus live in spanning tables, so this is not a
    corner case. Must go RED if any single inventory row is reverted."""
    problems = []
    for rel, needle, required in INVENTORY:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        hits = [
            i for i, ln in enumerate(lines) if needle in ln and not EXEMPT.search(ln)
        ]
        if not hits:
            problems.append(f"{rel}: inventory line vanished: {needle!r}")
            continue
        for i in hits:
            window = " ".join(lines[i : i + WINDOW]).lower()
            if not TH_TOKEN.search(window):
                problems.append(
                    f"{rel}:{i + 1}: {lines[i].strip()!r} does not also match th"
                )
    assert not problems, "\n".join(problems)
```

- [ ] **Step 8: Falsify the guard**

Falsify **one JS row and one CSS row** — the CSS half has its own failure mode (split
selector lists, incidental `th` substrings) that a JS-only falsification never exercises:

1. Change `dataCells` in `table_editor.js` back to `td:not([data-control])`.
2. Change `editor.css:595` back to `.table-editor__grid td {`.

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_cell_selector_guard.py -v
```

Expected: FAIL naming **both** `table_editor.js` and `editor.css`. Restore both and re-run:
PASS. A guard that cannot go red is not a test.

- [ ] **Step 9: Full suite**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e" -q
```

- [ ] **Step 10: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add -A
git commit -m "feat(editor): round-trip colspan/rowspan and header cells in both grids"
```

---

### Task 6: `table_grid.js` read-only half — slot map, layout width, aligned column strip, spanning handle-disable

**Files:**
- Create: `courses/static/courses/js/table_grid.js`
- Modify: `templates/courses/manage/editor/editor.html:127` (script tag)
- Modify: `courses/static/courses/js/table_editor.js` (`colCount`, `rebuildColControls`, `refreshControlState`, `wire`)
- Modify: `courses/static/courses/js/filltable_editor.js` (same four)
- Test: `tests/test_table_grid_algebra.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks (JS-only)
- Produces: `window.libliTableGrid.slotMap(grid) -> {map, width, height}`, `.layoutWidth(grid) -> int`, `.isSpanning(grid) -> bool`, `.anchorOf(sm, cell) -> {r, c}|null`, plus `colspanOf`/`rowspanOf`/`setSpan`. The `grid` descriptor is `{rows(), cells(tr), makeCell(), makeRow(), maxCols, maxRows}`. Later tasks add mutating functions to the same module.

> **Why this half lands in slice 1.** Disabling the structural handles closes the *corruption* window, but `rebuildColControls` would still emit `colCount()` button pairs — row 0's **cell** count — which for any table with a row-0 colspan is fewer than the layout width, leaving every handle under the wrong column. Slice 1's own acceptance goal is that u/432's strip lines up.

- [ ] **Step 1: Write the failing test harness + tests**

Create `tests/test_table_grid_algebra.py`:

```python
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
            makeCell: function () { var td = document.createElement('td');
                                    td.setAttribute('contenteditable','true'); return td; },
            makeRow: function () { var tr = document.createElement('tr');
                                   var ctl = document.createElement('td');
                                   ctl.setAttribute('data-control',''); tr.appendChild(ctl);
                                   return tr; },
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
        """
    )
    return page


ROW_3 = "<tr><td></td><td></td><td></td><td data-control></td></tr>"
ROW_SPAN3 = "<tr><td colspan='3'></td><td data-control></td></tr>"


def test_layout_width_ignores_the_trailing_control_cell(grid_page):
    assert grid_page.evaluate("() => libliTableGrid.layoutWidth(mk(`%s`))" % ROW_3) == 3


def test_layout_width_counts_a_colspan_not_the_cell_count(grid_page):
    assert (
        grid_page.evaluate("() => libliTableGrid.layoutWidth(mk(`%s`))" % ROW_SPAN3) == 3
    )


def test_slot_map_projects_a_rowspan_into_later_rows(grid_page):
    html = (
        "<tr><td id='a' rowspan='2'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    assert (
        grid_page.evaluate(
            """() => {
                 var sm = libliTableGrid.slotMap(mk(`%s`));
                 return sm.map[1][0] === document.getElementById('a');
               }"""
            % html
        )
        is True
    )


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
    assert (
        grid_page.evaluate("() => libliTableGrid.isSpanning(mk(`%s`))" % ROW_3) is False
    )


def test_is_spanning_is_true_when_any_cell_spans(grid_page):
    assert (
        grid_page.evaluate("() => libliTableGrid.isSpanning(mk(`%s`))" % ROW_SPAN3)
        is True
    )


# The server (TableElement.layout_dims) and the editor (slotMap) must never
# disagree about a grid's size: if they did, the caps could reject a grid the
# editor believes is legal -- an author-facing dead end with no way out.
SHARED_FIXTURES = [
    ([[{"colspan": 3}], [{}, {}, {}]], "<tr><td colspan='3'></td><td data-control></td></tr>"
     "<tr><td></td><td></td><td></td><td data-control></td></tr>"),
    ([[{"rowspan": 2}, {}, {}], [{}, {}]],
     "<tr><td rowspan='2'></td><td></td><td></td><td data-control></td></tr>"
     "<tr><td></td><td></td><td data-control></td></tr>"),
]


@pytest.mark.parametrize("cells,html", SHARED_FIXTURES)
def test_layout_dims_and_slot_map_agree(grid_page, cells, html):
    from courses.models import TableElement

    js_dims = grid_page.evaluate(
        """() => {
             var sm = libliTableGrid.slotMap(mk(`%s`));
             return [sm.width, sm.height];
           }"""
        % html
    )
    assert tuple(js_dims) == TableElement.layout_dims(cells)
```

- [ ] **Step 2: Verify failure**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v
```

Expected: **9 ERRORS** (7 plain tests + `test_layout_dims_and_slot_map_agree` parametrized
over 2 fixtures). They are *errors*, not failures: `add_script_tag(path=...)` raises inside
the `grid_page` fixture because `table_grid.js` does not exist yet.

- [ ] **Step 3: Create the module (read-only half)**

Create `courses/static/courses/js/table_grid.js`:

```js
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
  // grandfathering rule the module has no way to know about. Every function
  // bounds-checks its own index arguments and returns without mutating on an
  // out-of-range one.
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
```

- [ ] **Step 4: Load it before both editors**

In `templates/courses/manage/editor/editor.html`, immediately above the `table_editor.js` tag:

```django
  {% comment %}Shared span-aware grid algebra. MUST be a defer script like the two
  editors below it: source order only guarantees execution order among defer
  scripts.{% endcomment %}
  <script src="{% static 'courses/js/table_grid.js' %}" defer></script>
```

- [ ] **Step 5: Verify the module tests pass**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v
```

Expected: 9 passed.

- [ ] **Step 6: Drive both editors' column strips from layout width**

In **both** `table_editor.js` and `filltable_editor.js`, build the descriptor once per editor inside `wire()`. Add it right after `grid` is resolved:

```js
    // Descriptor handed to table_grid.js. `rows`/`cells` are this editor's own
    // helpers, so there is exactly one definition of "data cell" per editor and
    // the module inherits it.
    var desc = {
      rows: function () { return dataRows(grid); },
      cells: function (tr) { return Array.prototype.slice.call(dataCells(tr)); },
      makeCell: newCell,
      makeRow: function () {
        var tr = document.createElement("tr");
        tr.appendChild(rowCtl(grid));
        return tr;
      },
      maxCols: MAX_COLS,
      maxRows: MAX_ROWS,
    };
```

Replace `colCount` outright — **no `legacyColCount` fallback**. `table_grid.js` is a
hard dependency (a `defer` script in the same template), and a half-applied fallback is
worse than none: `refreshControlState` and `spanLocked` below call `libliTableGrid`
unguarded, so a guard on `colCount` alone would protect nothing while implying safety.

```js
  // Layout column count. The old body read row 0's CELL count, which is wrong
  // the moment a span exists: a row-0 colspan makes the control strip too short
  // and every handle lands under the wrong column.
  function colCount(desc) {
    return window.libliTableGrid.layoutWidth(desc);
  }
```

⚠️ **`colCount` has FIVE call sites, three of them outside the control strip.** Passing
the *grid* where a *descriptor* is now expected throws `grid.rows is not a function` — on
a **plain** table, where nothing is span-locked and the handles are live, so this is an
immediate regression of existing behaviour, not a spanning-only edge. All of them, by
line:

| File | Lines | Site |
|---|---|---|
| `table_editor.js` | 108, 123 | inside `rebuildColControls` / `refreshControlState` |
| `table_editor.js` | 250 | `buildRow(grid, colCount(grid))` in the row-insert handler |
| `table_editor.js` | 268 | `if (colCount(grid) < MAX_COLS)` in the **col-insert** handler |
| `table_editor.js` | 278 | `if (colCount(grid) > 1)` in the **col-delete** handler |
| `filltable_editor.js` | 116, 129, 430, 450, 461 | the same five |

Every one becomes `colCount(desc)`. (Task 11 later deletes `buildRow` entirely in favour
of `libliTableGrid.insertRow`.)

Thread `desc` through `rebuildColControls(grid, desc)` (its loop bound becomes
`colCount(desc)`) and rewrite `refreshControlState`:

```js
  function refreshControlState(grid, desc) {
    var sm = window.libliTableGrid.slotMap(desc);
    var rows = sm.height;
    var cols = sm.width;
    var locked = spanLocked(desc);
    // Insert is capped; delete keeps today's FLOOR guard, restated in layout
    // terms -- "one layout column left" is not "one cell left in row 0".
    Array.prototype.forEach.call(grid.querySelectorAll("[data-row-delete]"), function (b) {
      b.disabled = rows <= 1 || locked;
    });
    Array.prototype.forEach.call(grid.querySelectorAll("[data-row-insert]"), function (b) {
      b.disabled = rows >= MAX_ROWS || locked;
    });
    Array.prototype.forEach.call(grid.querySelectorAll("[data-col-delete]"), function (b) {
      b.disabled = cols <= 1 || locked;
    });
    Array.prototype.forEach.call(grid.querySelectorAll("[data-col-insert]"), function (b) {
      b.disabled = cols >= MAX_COLS || locked;
    });
  }

  // SLICE 1 ONLY -- deleted in slice 2 once the handlers are span-aware.
  // The handles still use cell-index insertion, which would corrupt a spanning
  // grid that (before slice 1) could not be saved at all.
  function spanLocked(desc) {
    return window.libliTableGrid.isSpanning(desc);
  }
```

Update **every** call site to pass `desc` — enumerated, because "the four call sites" is
wrong for either function. In `table_editor.js`: `rebuildColControls` at **191, 270, 281**;
`refreshControlState` at **192, 252, 261, 271, 282** (282, *not* 281 — line 281 is the
`rebuildColControls` call in that same col-delete branch); `colCount` at **108, 123, 250,
268, 278** per the table above. `filltable_editor.js` has the same set, offset by its extra
code (search each name rather than trusting line numbers there).

After editing, grep both files for the stale single-argument form —
`grep -nE "(refreshControlState|rebuildColControls|colCount)\(grid\)" courses/static/courses/js/*table*editor.js`
— and confirm it returns nothing. One surviving site throws `grid.rows is not a function`
on a **plain** table.

- [ ] **Step 7: Verify plain tables are unaffected**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k "table_editor or filltable" -v
```

Expected: the existing editor e2e tests still pass — a plain table is non-spanning, so
`spanLocked` is false and nothing changes for it. Slice 1's *spanning*-grid acceptance
goal (the control strip lining up) is pinned in **Task 7**, which is where
`tests/test_e2e_spanning_roundtrip.py` and its helpers are created — still inside slice 1,
and before slice 2 deletes the lock.

- [ ] **Step 8: Commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add -A
git commit -m "feat(editor): layout-aware column strip; lock handles on spanning grids"
```

---

### Task 7: the headline data-loss e2e (slice-1 acceptance gate)

**Files:**
- Create: `tests/test_e2e_spanning_roundtrip.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6
- Produces: the acceptance gate for slice 1

> **This test must be browser-driven.** On the edit path the hidden field renders empty and `serialize()` fills it from the live DOM on init, so a Python test that POSTs the stored JSON never exercises the code under test and would pass today — a textbook vacuous test.
>
> **And its assertion must be two-part.** A rejected save writes nothing, so "stored == stored" is trivially true. Assert the save *succeeded* first, then compare **structure** (per-cell `colspan`/`rowspan`/`header`/`kind` plus row lengths) — not whole-grid equality, because cell `html` round-trips through `contenteditable`'s `innerHTML` and the sanitiser and can legitimately differ. Fixtures therefore use plain-text cells.

- [ ] **Step 1: Write the test**

Create `tests/test_e2e_spanning_roundtrip.py`:

```python
"""The headline slice-1 gate: opening a SPANNING table and saving it with zero
edits must not change its structure.

Before this slice, saving a spanning table -- even untouched -- stripped every
span and header flag, because the editor templates never emitted them and
neither serialize() read them back. The two fixtures go RED for DIFFERENT
reasons, which is expected rather than a harness fault:

  * `table`      -> fails the SUCCESS assertion (TableElementForm rejected the
                    ragged grid with "All table rows must have the same number
                    of cells")
  * `fill_table` -> passes SUCCESS, fails the STRUCTURE assertion (saved
                    "successfully" having silently dropped the spans)
"""

import os

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _structure(cells):
    """The signal this test guards: geometry and kind, never cell html."""
    return [
        [
            (
                c.get("colspan", 1),
                c.get("rowspan", 1),
                bool(c.get("header")),
                c.get("kind"),
            )
            for c in row
        ]
        for row in cells
    ]


# Plain-text cells only: html round-trips through contenteditable and the
# sanitiser, so markup would make this flap for a reason unrelated to spans.
TABLE_CELLS = [
    [{"html": "top", "colspan": 3, "header": True}],
    [{"html": "a", "rowspan": 2}, {"html": "b"}, {"html": "c"}],
    [{"html": "d"}, {"html": "e"}],
]

# TWO non-blank answer cells deliberately: FillTableElementForm rejects a grid
# with no answer cells or any blank one, so a static-only fixture would fail
# the SUCCESS assertion for a third, misleading reason.
FILL_CELLS = [
    [{"kind": "static", "html": "top", "colspan": 3, "header": True}],
    [
        {"kind": "static", "html": "a", "rowspan": 2},
        {"kind": "static", "html": "b"},
        {"kind": "answer", "answer": "42"},
    ],
    [{"kind": "static", "html": "d"}, {"kind": "answer", "answer": "7"}],
]


def _seed(unit, model, cells, **extra):
    from django.contrib.contenttypes.models import ContentType

    from courses.models import Element

    concrete = model.objects.create(
        data=model.normalize_data({"cells": cells, **extra})
    )
    return Element.objects.create(
        unit=unit,
        order=0,
        content_type=ContentType.objects.get_for_model(model),
        object_id=concrete.pk,
    )


# ---- editor helpers -------------------------------------------------------
#
# test_e2e_table_editor.py's _reopen/_save CANNOT be reused here, for two
# reasons, and both would show up as a bare 30s Playwright timeout:
#
#  1. They wait on "[data-edit-slot] [data-table-editor]". The fill-table
#     editor's root is [data-filltable-editor] -- data-table-editor never
#     appears in a fill-table edit slot -- so every fill-table case would hang.
#  2. _save waits for the editor to DETACH. On a REJECTED save the form
#     re-renders inside the slot and never detaches, so the helper times out
#     before the test can assert anything. This suite's whole point is to
#     distinguish "saved" from "rejected", so it needs a save that survives
#     both outcomes.

TABLE_ROOT = "[data-edit-slot] [data-table-editor]"
FILL_ROOT = "[data-edit-slot] [data-filltable-editor]"


def _reopen(page, live_server, unit, element, root):
    from tests.test_e2e_table_editor import _editor_url

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator(f"[data-element='{element.pk}'] .el-act-edit").click()
    page.wait_for_selector(root)


def _save_and_report(page, root):
    """Click Save and return True iff the POST was accepted.

    Reads the HTTP STATUS, because that is the only reliable signal here:
    `element_save` answers a rejected save with 422 and editor.js swaps the
    re-rendered form back into the slot, and NEITHER editor partial renders
    any error markup (there is no `.field-error` node anywhere in
    _edit_table.html / _edit_filltable.html / _host_form.html). Waiting on
    error markup -- or on the editor detaching -- would hang for the full
    Playwright timeout on exactly the rejected path this helper exists to
    detect."""
    with page.expect_response(
        lambda r: "/build/element/save/" in r.url and r.request.method == "POST"
    ) as info:
        page.locator(
            "[data-edit-slot] .editor-form__actions button[type='submit']"
        ).click()
    if info.value.status != 200:
        return False
    page.wait_for_selector(root, state="detached")
    return True


@pytest.mark.django_db(transaction=True)
def test_spanning_table_survives_a_zero_edit_save(page, live_server):
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_tbl")
    _login(page, live_server, "span_tbl")
    unit = _unit("span_tbl", "span-tbl")
    element = _seed(unit, TableElement, TABLE_CELLS, header_row=True)
    before = _structure(
        TableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    saved = _save_and_report(page, TABLE_ROOT)

    # (1) the save actually succeeded -- without this, the comparison below is
    # satisfied vacuously by a rejected POST that wrote nothing.
    assert saved, "save was rejected"

    after = _structure(
        TableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )
    assert after == before


@pytest.mark.django_db(transaction=True)
def test_spanning_fill_table_survives_a_zero_edit_save(page, live_server):
    from courses.models import FillTableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_fill")
    _login(page, live_server, "span_fill")
    unit = _unit("span_fill", "span-fill")
    element = _seed(unit, FillTableElement, FILL_CELLS, header_row=True)
    before = _structure(
        FillTableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )

    _reopen(page, live_server, unit, element, FILL_ROOT)
    saved = _save_and_report(page, FILL_ROOT)

    assert saved, "save was rejected"

    after = _structure(
        FillTableElement.objects.get(pk=element.object_id).normalized_data["cells"]
    )
    assert after == before
```

Finally, the slice-1 acceptance pin — the control strip lining up on a *spanning* grid,
which no plain-table test can catch:

```python
@pytest.mark.django_db(transaction=True)
def test_spanning_grid_gets_a_layout_width_control_strip(page, live_server):
    """Row 0 is one colspan=3 cell, so the OLD colCount() (row 0's CELL count)
    would emit ONE handle pair for a 3-column layout, leaving every handle
    under the wrong column. Also pins slice 1's temporary handle-lock."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("strip")
    _login(page, live_server, "strip")
    unit = _unit("strip", "strip")
    element = _seed(unit, TableElement, [[{"colspan": 3, "html": "t"}], [{}, {}, {}]])

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    assert page.locator(f"{TABLE_ROOT} [data-col-insert]").count() == 3
    # Slice 1 only: span-aware handlers arrive in slice 2, so they are locked.
    assert page.locator(f"{TABLE_ROOT} [data-col-insert]").first.is_disabled()
```

> Task 11 deletes the `is_disabled` assertion when it lifts the lock.

> **Later e2e files reuse these helpers**, importing them explicitly:
> `from tests.test_e2e_spanning_roundtrip import FILL_ROOT, TABLE_ROOT, _reopen, _save_and_report, _seed`.
> Never `tests.test_e2e_table_editor`'s `_reopen`/`_save` — they hard-code the plain-table root and assume detachment.

- [ ] **Step 2: Falsify it**

The production code already exists, so prove **both** tests can fail — the fill-table half
guards the more fragile three-branch serializer, and a table-only falsification never
exercises it. Temporarily comment out the three span/header lines Task 5 appended in
`table_editor.js`'s `serialize()` **and** in each of `filltable_editor.js`'s three
branches, then:

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k spanning_roundtrip -v
```

Expected, and the two differ:

- `test_spanning_table_survives_a_zero_edit_save` FAILS on
  `assert saved, "save was rejected"` — **not** on the structure comparison. Without the
  span lines, `serialize()` posts row 0 with one cell and row 1 with three and no spans:
  a ragged *non-spanning* grid, which `TableElementForm` rejects. (This also exercises
  `_save_and_report`'s 422 detection — a hang here means that helper is wrong.)
- `test_spanning_fill_table_survives_a_zero_edit_save` FAILS on the **structure**
  comparison: `FillTableElementForm` has no raggedness check, so it saves "successfully"
  with every span silently stripped.

Restore all four sets of lines.

- [ ] **Step 3: Verify green**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k spanning_roundtrip -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_spanning_roundtrip.py
git commit -m "test(editor): prove a spanning table survives a zero-edit save"
```

**Slice 1 complete.** A spanning table opens with an aligned column strip and saves without losing its spans; its structural handles are disabled pending slice 2.

---

# SLICE 2 — Span-aware grid algebra

Goal: `table_grid.js` gains its mutating half, both editors' handlers are rewired to it, and slice 1's blanket handle-disable is lifted. No new UI yet.

**TDD loop for this whole slice:** `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v`

---

### Task 8: `insertColumn` / `deleteColumn`

**Files:**
- Modify: `courses/static/courses/js/table_grid.js`
- Test: `tests/test_table_grid_algebra.py` (append)

**Interfaces:**
- Consumes: `slotMap`, `anchorOf`, `colspanOf`, `rowspanOf`, `setSpan` from Task 6
- Produces: `libliTableGrid.insertColumn(grid, layoutCol)`, `.deleteColumn(grid, layoutCol)`

> **The two predicates differ, deliberately.** Insert skips a row only when a cell **straddles** the insertion point (strict `c < layoutCol < c + colspan`). Delete decrements every cell **covering** the column (`c <= layoutCol < c + colspan`). Conflating them corrupts grids in opposite directions — see the two ⚠️ callouts in the spec.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_grid_algebra.py`:

```python
def _run(page, rows_html, js):
    return page.evaluate("() => { var g = mk(`%s`); %s; return shape(g); }" % (rows_html, js))


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
    idx = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.insertColumn(g, 2);
             var row1 = g.cells(g.rows()[1]);
             return row1.indexOf(document.getElementById('mark'));
           }"""
        % rows
    )
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
    gone = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.deleteColumn(g, 1);
             return document.getElementById('doomed') === null;
           }"""
        % rows
    )
    assert gone is True
```

- [ ] **Step 2: Verify failure**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v
```

Expected: the 10 new tests FAIL with `libliTableGrid.insertColumn is not a function`.

- [ ] **Step 3: Implement both ops**

Add to `table_grid.js`, before the `window.libliTableGrid = {...}` export:

```js
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
```

Export `insertColumn` and `deleteColumn` (and `insertCellAt`, which Tasks 9 and 10 reuse).

- [ ] **Step 4: Verify green, then commit**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v
git add -A && git commit -m "feat(table-grid): span-aware column insert and delete"
```

---

### Task 9: `insertRow` / `deleteRow` (with anchor relocation and the bounds clamp)

**Files:**
- Modify: `courses/static/courses/js/table_grid.js`
- Test: `tests/test_table_grid_algebra.py` (append)

**Interfaces:**
- Consumes: Task 8's helpers
- Produces: `libliTableGrid.insertRow(grid, layoutRow)`, `.deleteRow(grid, layoutRow)`

> **`deleteRow` is not a transpose of `deleteColumn`.** Deleting a column never moves a node between rows; deleting the anchor row of a `rowspan > 1` cell must physically relocate that cell into the next row it covers, at an index computed from *that* row's slot map.

- [ ] **Step 1: Write the failing tests**

```python
def test_insert_row_grows_a_straddling_rowspan(grid_page):
    rows = (
        "<tr><td rowspan='2'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertRow(g, 1)") == [
        "1x3,1x1",
        "1x1",
        "1x1",
    ]


def test_insert_row_at_a_rowspans_anchor_does_not_grow_it(grid_page):
    rows = (
        "<tr><td rowspan='2'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.insertRow(g, 0)") == [
        "1x1,1x1",
        "1x2,1x1",
        "1x1",
    ]


def test_insert_row_appends_at_the_bottom(grid_page):
    assert _run(grid_page, ROW_3, "libliTableGrid.insertRow(g, 1)") == [
        "1x1,1x1,1x1",
        "1x1,1x1,1x1",
    ]


def test_inserted_row_carries_its_control_chrome(grid_page):
    # makeRow supplies the caller's row handles; without it the new row would
    # silently have no insert/delete buttons.
    has_ctl = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.insertRow(g, 1);
             return !!g.rows()[1].querySelector('td[data-control]');
           }"""
        % ROW_3
    )
    assert has_ctl is True


def test_delete_row_shrinks_a_rowspan_anchored_above(grid_page):
    rows = (
        "<tr><td rowspan='3'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.deleteRow(g, 1)") == ["1x2,1x1", "1x1"]


def test_delete_row_relocates_a_cell_anchored_in_it(grid_page):
    # The hard case: a rowspan=3 cell mid-way along a wide row. Its node must
    # move into the next row, decremented, at the right sibling index.
    rows = (
        "<tr><td></td><td id='rs' rowspan='3'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td id='after'></td><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>"
    )
    result = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.deleteRow(g, 0);
             var rs = document.getElementById('rs');
             var row0 = g.cells(g.rows()[0]);
             return [shape(g), row0.indexOf(rs), rs.rowSpan];
           }"""
        % rows
    )
    shape, index, rowspan = result
    assert rowspan == 2
    # It lands at layout column 1, i.e. sibling index 1 -- before 'after'.
    assert index == 1
    assert shape == ["1x1,1x2,1x1", "1x1,1x1"]


def test_delete_last_row_removes_an_overflowing_rowspan_cell(grid_page):
    # Terminal case: no row idx+1 to relocate into. Reachable from hand-edited
    # JSON; must degrade rather than throw.
    rows = "<tr><td rowspan='9'></td><td></td><td data-control></td></tr>"
    assert _run(grid_page, rows, "libliTableGrid.deleteRow(g, 0)") == []


def test_delete_row_clamps_a_rowspan_that_would_overflow(grid_page):
    # After removing the last row, a rowspan=2 anchored in row 0 would reach
    # past the grid and shove the control strip sideways.
    rows = (
        "<tr><td rowspan='2'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td data-control></td></tr>"
    )
    assert _run(grid_page, rows, "libliTableGrid.deleteRow(g, 1)") == ["1x1,1x1"]
```

- [ ] **Step 2: Verify failure, then implement**

```js
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
```

Export `insertRow`, `deleteRow`, `clampRowspans`.

- [ ] **Step 3: Verify green and commit**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v
git add -A && git commit -m "feat(table-grid): span-aware row insert and delete with anchor relocation"
```

---

### Task 10: `rangeCells` / `canMerge` / `merge` / `split`

**Files:**
- Modify: `courses/static/courses/js/table_grid.js`
- Test: `tests/test_table_grid_algebra.py` (append)

**Interfaces:**
- Consumes: Tasks 8–9
- Produces: `libliTableGrid.rangeCells(grid, a, b) -> {cells, anchor, r0, c0, r1, c1}|null`, `.canMerge(grid, a, b) -> bool`, `.merge(grid, a, b) -> cell|null`, `.split(grid, cell)`

> `a` and `b` may each be a **cell node** or a **layout `{r, c}` coordinate** — `rangeEnd` is a coordinate, because "one slot right" is undefined against a multi-slot node. Normalisation runs to a **fixpoint**: expanding to swallow one clipped merged cell can newly clip another on a different edge, and merging an illegal rectangle would remove cells that still project outside it.

- [ ] **Step 1: Write the failing tests**

```python
def test_range_expands_to_contain_a_clipped_merged_cell(grid_page):
    rows = (
        "<tr><td id='a'></td><td colspan='2'></td><td data-control></td></tr>"
        "<tr><td></td><td id='b'></td><td></td><td data-control></td></tr>"
    )
    dims = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             var rg = libliTableGrid.rangeCells(
               g, document.getElementById('a'), document.getElementById('b'));
             return [rg.r0, rg.c0, rg.r1, rg.c1];
           }"""
        % rows
    )
    # Selecting (0,0)..(1,1) clips the colspan=2 at (0,1), so c1 expands to 2.
    assert dims == [0, 0, 1, 2]


def test_range_normalisation_runs_to_a_fixpoint(grid_page):
    """Expanding for one merged cell must newly clip a SECOND one, forcing a
    second pass. A single-pass implementation returns an illegal rectangle, and
    merge() on an illegal rectangle removes cells that still project outside it.

    Layout (4 wide, 3 tall), traced by hand against slotMap:
        row0:  a(0,0)   M1 = colspan2 (0,1)-(0,2)   D(0,3)
        row1:  E(1,0)   f(1,1)   M2 = rowspan2 (1,2)-(2,2)   H(1,3)
        row2:  I(2,0)   J(2,1)   [covered by M2]   L(2,3)

    Selecting f..a starts at r0=0,c0=0,r1=1,c1=1.
      pass 1: M1 at (0,1) reaches column 2  -> c1 = 2
      pass 2: that pulls in M2 at (1,2), which reaches row 2 -> r1 = 2
      pass 3: nothing changes -> fixpoint at [0, 0, 2, 2]
    """
    rows = (
        "<tr><td id='a'></td><td colspan='2'></td><td></td>"
        "<td data-control></td></tr>"
        "<tr><td></td><td id='f'></td><td rowspan='2'></td><td></td>"
        "<td data-control></td></tr>"
        "<tr><td></td><td></td><td></td><td data-control></td></tr>"
    )
    dims = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             var rg = libliTableGrid.rangeCells(
               g, document.getElementById('f'), document.getElementById('a'));
             return [rg.r0, rg.c0, rg.r1, rg.c1];
           }"""
        % rows
    )
    assert dims == [0, 0, 2, 2]


def test_can_merge_is_false_for_a_single_cell(grid_page):
    assert (
        grid_page.evaluate(
            """() => {
                 var g = mk(`%s`);
                 var c = g.cells(g.rows()[0])[0];
                 return libliTableGrid.canMerge(g, c, c);
               }"""
            % ROW_3
        )
        is False
    )


def test_can_merge_is_false_when_the_range_exceeds_max_cols(grid_page):
    # 26 columns against maxCols 20: refused, never clamped.
    cells = "".join("<td></td>" for _ in range(26))
    rows = "<tr>%s<td data-control></td></tr>" % cells
    assert (
        grid_page.evaluate(
            """() => {
                 var g = mk(`%s`);
                 var cs = g.cells(g.rows()[0]);
                 return libliTableGrid.canMerge(g, cs[0], cs[25]);
               }"""
            % rows
        )
        is False
    )


def test_merge_gives_the_anchor_the_covering_spans_and_removes_the_rest(grid_page):
    rows = (
        "<tr><td id='a'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td id='b'></td><td data-control></td></tr>"
    )
    result = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.merge(g, document.getElementById('a'),
                                     document.getElementById('b'));
             return shape(g);
           }"""
        % rows
    )
    assert result == ["2x2", ""]


def test_merge_leaves_a_legal_empty_row(grid_page):
    # A full-width 2-row merge empties row 1 entirely -- legal, and the row
    # keeps its control cell so it can still be deleted.
    rows = (
        "<tr><td id='a'></td><td></td><td data-control></td></tr>"
        "<tr><td></td><td id='b'></td><td data-control></td></tr>"
    )
    kept = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.merge(g, document.getElementById('a'),
                                     document.getElementById('b'));
             return [g.rows().length,
                     !!g.rows()[1].querySelector('td[data-control]')];
           }"""
        % rows
    )
    assert kept == [2, True]


def test_split_restores_cells_at_the_right_sibling_indexes(grid_page):
    # colspan=3 rowspan=2 anchored mid-row in a ragged grid: 2 slots free to
    # its right in row 0, 3 in row 1.
    rows = (
        "<tr><td></td><td id='m' colspan='3' rowspan='2'></td><td></td>"
        "<td data-control></td></tr>"
        "<tr><td></td><td id='tail'></td><td data-control></td></tr>"
    )
    result = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             libliTableGrid.split(g, document.getElementById('m'));
             return [shape(g),
                     g.cells(g.rows()[1]).indexOf(document.getElementById('tail'))];
           }"""
        % rows
    )
    shape, tail_index = result
    assert shape == ["1x1,1x1,1x1,1x1,1x1", "1x1,1x1,1x1,1x1,1x1"]
    # 'tail' sat at layout column 4, so three new cells went in before it.
    assert tail_index == 4


def test_merge_is_a_no_op_when_the_anchor_slot_is_null(grid_page):
    # A degenerate grid whose top-left slot is unoccupied: merge must not
    # remove the absorbed cells with no survivor.
    rows = (
        "<tr><td data-control></td></tr>"
        "<tr><td></td><td></td><td data-control></td></tr>"
    )
    ok = grid_page.evaluate(
        """() => {
             var g = mk(`%s`);
             var cs = g.cells(g.rows()[1]);
             var before = shape(g).join('|');
             libliTableGrid.merge(g, {r: 0, c: 0}, cs[1]);
             return shape(g).join('|') === before;
           }"""
        % rows
    )
    assert ok is True
```

- [ ] **Step 2: Verify failure, then implement**

```js
  // `x` is a cell node or a layout {r, c} coordinate. rangeEnd is a coordinate
  // because "one slot right" is undefined against a multi-slot node.
  function slotOf(sm, x) {
    if (!x) return null;
    if (x.nodeType === 1) return anchorOf(sm, x);
    if (x.r == null || x.c == null) return null;
    if (x.r < 0 || x.r >= sm.height || x.c < 0 || x.c >= sm.width) return null;
    return { r: x.r, c: x.c };
  }

  function rangeCells(grid, a, b) {
    var sm = slotMap(grid);
    var pa = slotOf(sm, a);
    var pb = slotOf(sm, b);
    if (!pa || !pb) return null;
    var r0 = Math.min(pa.r, pb.r), r1 = Math.max(pa.r, pb.r);
    var c0 = Math.min(pa.c, pb.c), c1 = Math.max(pa.c, pb.c);

    // Expand to a FIXPOINT: swallowing one clipped merged cell can newly clip
    // a different one on another edge. Terminates because the rectangle only
    // grows and is bounded by the grid.
    var changed = true;
    while (changed) {
      changed = false;
      for (var r = r0; r <= r1; r++) {
        for (var c = c0; c <= c1; c++) {
          var cell = sm.map[r] && sm.map[r][c];
          if (!cell) continue;
          var an = anchorOf(sm, cell);
          if (!an) continue;
          var er = an.r + rowspanOf(cell) - 1;
          var ec = an.c + colspanOf(cell) - 1;
          if (an.r < r0) { r0 = an.r; changed = true; }
          if (an.c < c0) { c0 = an.c; changed = true; }
          if (er > r1) { r1 = er; changed = true; }
          if (ec > c1) { c1 = ec; changed = true; }
        }
      }
    }

    var cells = [];
    for (var rr = r0; rr <= r1; rr++) {
      for (var cc = c0; cc <= c1; cc++) {
        var x = sm.map[rr] && sm.map[rr][cc];
        if (x && cells.indexOf(x) === -1) cells.push(x);
      }
    }
    return {
      cells: cells,
      // The cell at (r0, c0) AFTER normalisation -- fixpoint expansion can
      // make this a different cell from the one the author first clicked.
      anchor: (sm.map[r0] && sm.map[r0][c0]) || null,
      r0: r0, c0: c0, r1: r1, c1: c1,
    };
  }

  function canMerge(grid, a, b) {
    var rg = rangeCells(grid, a, b);
    if (!rg || !rg.anchor) return false;          // null anchor -> refuse
    if (rg.cells.length < 2) return false;
    if (rg.c1 - rg.c0 + 1 > grid.maxCols) return false;  // refuse, never clamp
    if (rg.r1 - rg.r0 + 1 > grid.maxRows) return false;
    return true;
  }

  function merge(grid, a, b) {
    if (!canMerge(grid, a, b)) return null;
    var rg = rangeCells(grid, a, b);
    var keep = rg.anchor;
    for (var i = 0; i < rg.cells.length; i++) {
      if (rg.cells[i] !== keep) rg.cells[i].remove();
    }
    setSpan(keep, "colspan", rg.c1 - rg.c0 + 1);
    setSpan(keep, "rowspan", rg.r1 - rg.r0 + 1);
    return keep;
  }

  function split(grid, cell) {
    var sm = slotMap(grid);
    var a = anchorOf(sm, cell);
    if (!a) return;
    var cs = colspanOf(cell);
    var rs = rowspanOf(cell);
    if (cs <= 1 && rs <= 1) return;
    setSpan(cell, "colspan", 1);
    setSpan(cell, "rowspan", 1);
    // Re-slot after each insertion: the grid is at most 50x20, so the repeated
    // slotMap is cheap and far easier to reason about than an incremental map.
    for (var dr = 0; dr < rs; dr++) {
      for (var dc = 0; dc < cs; dc++) {
        if (dr === 0 && dc === 0) continue;
        var r = a.r + dr;
        var live = slotMap(grid);
        if (r >= live.height) continue;
        insertCellAt(grid, live, r, a.c + dc);
      }
    }
  }
```

Export all four.

- [ ] **Step 3: Verify green and commit**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k table_grid -v
git add -A && git commit -m "feat(table-grid): range normalisation, merge and split"
```

---

### Task 11: rewire both editors' handlers, then lift the slice-1 lock

**Files:**
- Modify: `courses/static/courses/js/table_editor.js` (the delegated click handler; delete `insertColumnAfter`, `deleteColumnAt`, `buildRow`, `spanLocked`)
- Modify: `courses/static/courses/js/filltable_editor.js` (same)
- Test: `tests/test_e2e_spanning_merge.py` (create — structural half only; merge UI arrives in slice 3)

**Interfaces:**
- Consumes: all of `libliTableGrid`
- Produces: row/column handles that operate correctly on a spanning grid

> **Order matters.** Rewire first, lift `spanLocked` last. Lifting it before the handlers are span-aware re-opens the corruption window slice 1 closed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_e2e_spanning_merge.py`. Written out in full — every later test in this
file follows this shape (module header, marks, seed, reopen, real gesture, save, assert
against the DB), so subsequent cases may be written more tersely.

```python
"""Real-gesture e2e for span-aware structural editing and the merge/split UI.

Drives actual clicks and keystrokes throughout -- no page.evaluate shortcuts.
Helpers come from test_e2e_spanning_roundtrip (NOT test_e2e_table_editor, whose
_reopen/_save hard-code the plain-table root and assume the editor detaches on
save, which is false for a rejected one)."""

import os

import pytest

from tests.test_e2e_spanning_roundtrip import FILL_ROOT
from tests.test_e2e_spanning_roundtrip import TABLE_ROOT
from tests.test_e2e_spanning_roundtrip import _reopen
from tests.test_e2e_spanning_roundtrip import _save_and_report
from tests.test_e2e_spanning_roundtrip import _seed

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _cells(model, element):
    return model.objects.get(pk=element.object_id).normalized_data["cells"]


@pytest.mark.django_db(transaction=True)
def test_column_insert_through_a_colspan_widens_it(page, live_server):
    """Press the real column-insert handle on a spanning table: the straddled
    colspan must GROW rather than the row gaining a stray cell. Also proves
    slice 1's blanket handle-lock has been lifted."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_ins")
    _login(page, live_server, "span_ins")
    unit = _unit("span_ins", "span-ins")
    element = _seed(
        unit,
        TableElement,
        [[{"colspan": 3, "html": "top"}], [{"html": "a"}, {"html": "b"}, {"html": "c"}]],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    # "Insert column right" of layout column 0 -> insertColumn(desc, 1), which
    # is strictly inside the colspan=3 and must widen it to 4.
    page.locator(f"{TABLE_ROOT} [data-col-insert][data-col-index='0']").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 4
    assert len(cells[0]) == 1          # the merged cell grew; no stray cell
    assert len(cells[1]) == 4          # the plain row gained one


@pytest.mark.django_db(transaction=True)
def test_column_delete_inside_a_colspan_shrinks_it(page, live_server):
    """The covering predicate: deleting a column the span covers decrements it."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("span_del")
    _login(page, live_server, "span_del")
    unit = _unit("span_del", "span-del")
    element = _seed(
        unit,
        TableElement,
        [[{"colspan": 3, "html": "top"}], [{"html": "a"}, {"html": "b"}, {"html": "c"}]],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    page.locator(f"{TABLE_ROOT} [data-col-delete][data-col-index='1']").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 2
    assert len(cells[1]) == 2
```

- [ ] **Step 2: Verify it fails**

Expected RED is a **Playwright actionability timeout**, not a clean assertion failure:
`.click()` waits for `[data-col-insert]` to become enabled and slice 1 locked it. Assert
the lock first so the red is fast and legible:
`expect(page.locator(f"{TABLE_ROOT} [data-col-insert]").first).to_be_disabled()`.

- [ ] **Step 3: Rewire the four handlers in both editors**

```js
      var colInsert = e.target.closest("[data-col-insert]");
      if (colInsert) {
        // "Insert column right" of layout column i is an insert AT i + 1.
        // insertColumn(grid, width) appends. Consequence worth knowing: on a
        // colspan's LAST covered slot this yields layoutCol == c + s, so the
        // span does not grow -- a new cell appears after it.
        var i = parseInt(colInsert.dataset.colIndex, 10);
        if (colCount(desc) < MAX_COLS) {   // colCount is the layoutWidth wrapper
                                           // Task 6 introduced -- keep ONE spelling
          libliTableGrid.insertColumn(desc, i + 1);
          afterStructuralEdit();
        }
        return;
      }
```

and the matching `deleteColumn(desc, i)`.

⚠️ **The row handles have no index attribute.** `colCtl()` sets `dataset.colIndex` on both
its buttons, but `rowCtl()` (`table_editor.js:70-77`, `filltable_editor.js:78-85`) creates
the row buttons with **no** index — today's handlers work purely off
`rowInsert.closest("tr")`. So there is no `i` in scope for the row branches; derive it
from the DOM position rather than inventing an attribute (which would then need keeping in
sync on every structural edit):

```js
      var rowInsert = e.target.closest("[data-row-insert]");
      if (rowInsert) {
        // rowCtl() carries no index, so read the row's position from desc.
        var ri = desc.rows().indexOf(rowInsert.closest("tr"));
        if (ri >= 0 && libliTableGrid.slotMap(desc).height < MAX_ROWS) {
          libliTableGrid.insertRow(desc, ri + 1);   // "insert below" == at ri+1
          afterStructuralEdit();
        }
        return;
      }
```

`[data-row-delete]` mirrors it with `deleteRow(desc, ri)`. Factor the shared tail into one
function, since slices 3 and 4 extend it:

```js
    // Every structural edit ends the same way. Slices 3-4 add range clearing
    // and toolbar refresh here.
    function afterStructuralEdit() {
      if (typeof cellStash !== "undefined") cellStash.clear(); // fill-table only
      rebuildColControls(grid, desc);
      refreshControlState(grid, desc);
      serialize();
    }
```

Delete `insertColumnAfter`, `deleteColumnAt` and `buildRow` — `libliTableGrid` now owns all four operations.

- [ ] **Step 4: Lift the lock**

Delete `spanLocked` and the four `|| locked` clauses in `refreshControlState`.

- [ ] **Step 5: Verify green + no regression**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k "table_grid or spanning or table_editor or filltable" -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(editor): drive row/column handles through the span-aware grid module"
```

**Slice 2 complete.** Structural editing is correct on spanning grids; no merge UI yet.

---

# SLICE 3 — Merge / Split / Header UI in `table_editor.js`

---

### Task 12: sprite symbols, toolbar markup, range-highlight CSS

**Files:**
- Modify: `templates/courses/manage/editor/editor.html` (three `<symbol>`s beside `ed-answer`/`ed-image`)
- Modify: `templates/courses/manage/editor/_edit_table.html` (toolbar buttons, `data-msg-*`, live region)
- Modify: `courses/static/courses/css/editor.css` (`.is-range`)
- Test: `tests/test_table_editor_partial.py` (append)

**Interfaces:**
- Consumes: nothing
- Produces: `[data-merge]`, `[data-split]`, `[data-header-toggle]` buttons; `[data-range-status]` live region; `data-msg-merge-confirm` / `-merge-too-big` / `-header-locked` / `-range-selected` / `-range-cleared` on the editor root

- [ ] **Step 1: Write the failing test**

```python
def test_table_editor_exposes_merge_split_and_header_controls():
    html = _render(TableElement())
    for attr in ("data-merge", "data-split", "data-header-toggle"):
        assert attr in html
    # Client-built markup cannot call {% trans %}, so every string rides on a
    # data-msg-* attribute (the established convention in this editor).
    for msg in ("data-msg-merge-confirm", "data-msg-merge-too-big",
                "data-msg-header-locked", "data-msg-range-selected"):
        assert msg in html
    assert 'aria-live="polite"' in html
```

- [ ] **Step 2: Add three monochrome `currentColor` symbols to `editor.html`**

Match the existing `ed-answer`/`ed-image` line style (16×16 viewBox, `fill="none" stroke="currentColor" stroke-width="1.3"`):

```django
    {% comment %}Merge: two cells collapsing into one (arrows pointing inward at a
    shared seam). Split: the inverse. Header: a table outline with a filled top
    band. All three are single-colour line icons per the project's icon
    convention -- never multicolour glyphs.{% endcomment %}
    <symbol id="ed-merge" viewBox="0 0 16 16"><rect x="2.5" y="3.5" width="11" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 4.5v7" stroke="currentColor" stroke-width="1.3" stroke-dasharray="1.5 1.5"/><path d="M5 8h1.8M11 8H9.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></symbol>
    <symbol id="ed-split" viewBox="0 0 16 16"><rect x="2.5" y="3.5" width="11" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M8 4.5v7" stroke="currentColor" stroke-width="1.3"/><path d="M4.6 8h2M11.4 8h-2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></symbol>
    <symbol id="ed-header" viewBox="0 0 16 16"><rect x="2.5" y="3.5" width="11" height="9" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M2.5 6.8h11" stroke="currentColor" stroke-width="1.3"/><path d="M3.6 5.2h8.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" opacity=".55"/></symbol>
```

- [ ] **Step 3: Add the toolbar controls and messages to `_edit_table.html`**

On the editor root, alongside the existing `data-msg-*`:

```django
     data-msg-merge="{% trans 'Merge cells' %}"
     data-msg-header="{% trans 'Header cell' %}"
     data-msg-merge-confirm="{% trans 'Merging will discard the content of the other selected cells.' %}"
     data-msg-merge-too-big="{% trans 'The selection is larger than a table may be.' %}"
     data-msg-header-locked="{% trans 'Unavailable while the row or column header option covers this cell.' %}"
     data-msg-range-selected="{% trans 'Range selected' %}"
     data-msg-range-cleared="{% trans 'Range cleared' %}"
```

> The confirm and live-region strings are deliberately **count-free**. A count needs `ngettext`, and Polish has three plural forms a single `data-msg-*` filled by `{% trans %}` cannot carry.

After the alignment groups in the toolbar:

```django
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn" data-merge disabled
            title="{% trans 'Merge cells' %}" aria-label="{% trans 'Merge cells' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-merge"/></svg></button>
    <button type="button" class="rte-btn" data-split disabled
            title="{% trans 'Split cell' %}" aria-label="{% trans 'Split cell' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-split"/></svg></button>
    <button type="button" class="rte-btn" data-header-toggle aria-pressed="false"
            title="{% trans 'Header cell' %}" aria-label="{% trans 'Header cell' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-header"/></svg></button>
```

And, after the grid div, the announcement region:

```django
  {% comment %}Range membership is announced here rather than with aria-selected,
  which is only meaningful on gridcell/option/row roles and is ignored (and
  axe-flagged) on a bare <td>. Giving the editing table role="grid" would mean
  owning full grid keyboard semantics -- out of scope.{% endcomment %}
  <p class="visually-hidden" data-range-status aria-live="polite"></p>
```

- [ ] **Step 4: Style the range highlight in `editor.css`, light and dark**

```css
/* Selected merge range. Outline + tint rather than a background swap, so a
   cell's own alignment/border styling still reads through. The dark variant
   keys off [data-theme="dark"] -- this app themes with a root ATTRIBUTE
   (core/static/core/css/tokens.css), not prefers-color-scheme. A media query
   here would tint wrongly whenever the OS is dark but the app is light, and
   miss the case where the author toggles the app dark on a light OS. */
.table-editor__grid .is-range {
  outline: 2px solid var(--primary);
  outline-offset: -2px;
  background: color-mix(in srgb, var(--primary) 12%, transparent);
}
[data-theme="dark"] .table-editor__grid .is-range {
  background: color-mix(in srgb, var(--primary) 22%, transparent);
}
```

- [ ] **Step 5: Run `makemessages` — the msgids are introduced HERE**

Every new string in slice 3 (`Merge cells`, `Split cell`, `Header cell`, plus the five
`data-msg-*` texts) appears in this task's template edit, not in Tasks 13–15. Running the
catalogue update here keeps Tasks 12–14 from each committing against a stale `.po`:

```bash
uv run python manage.py makemessages -l en -l pl
```

Check for fuzzy flags on the new msgids. (Task 15 re-runs it for anything the chord probe
changes; Task 17 does the final sweep and the Polish translations.)

- [ ] **Step 6: Verify green and commit**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest tests/test_table_editor_partial.py -v
git add -A && git commit -m "feat(editor): merge/split/header toolbar controls and range styling"
```

---

### Task 13: selection state + Merge/Split wiring in `table_editor.js`

**Files:**
- Modify: `courses/static/courses/js/table_editor.js`
- Test: `tests/test_e2e_spanning_merge.py` (append)

**Interfaces:**
- Consumes: `libliTableGrid.rangeCells/canMerge/merge/split`; the Task 12 buttons
- Produces: `focusCell` / `rangeAnchor` / `rangeEnd` state, `refreshToolbarState()` in `table_editor.js`, working Merge and Split

- [ ] **Step 1: Write the failing e2e**

⚠️ **Two of these are written out in full** (`test_shift_click_range_then_merge_persists_the_span`
and `test_merge_then_split_all_returns_the_original_rectangle`). The others are
**specifications, not paste-ready code** — their bodies are comments, which is an
`IndentationError` if pasted verbatim. Expand each following the full examples' shape:
imports inside the function, `_make_pa_user`/`_login`/`_unit`, `_seed`, `_reopen`, real
gestures, `_save_and_report`, then assert against `_cells(...)`. The same applies to every
sketched test in Tasks 14, 15 and 16.

```python
def _cell(page, root, row, col):
    """The (row, col)-th DATA cell of the editor grid, by sibling position."""
    return page.locator(f"{root} [data-table-grid] tr").nth(row).locator(
        "td:not([data-control]), th:not([data-control])"
    ).nth(col)


@pytest.mark.django_db(transaction=True)
def test_shift_click_range_then_merge_persists_the_span(page, live_server):
    """Real gestures only: click a cell, Shift+click another, press Merge,
    Save -- the span must reach the database."""
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("merge_ok")
    _login(page, live_server, "merge_ok")
    unit = _unit("merge_ok", "merge-ok")
    element = _seed(
        unit,
        TableElement,
        [[{"html": ""} for _ in range(3)] for _ in range(3)],
    )

    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    _cell(page, TABLE_ROOT, 1, 1).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()
    assert _save_and_report(page, TABLE_ROOT), "save was rejected"

    cells = _cells(TableElement, element)
    assert cells[0][0]["colspan"] == 2
    assert cells[0][0]["rowspan"] == 2
    assert len(cells[0]) == 2          # 3 cells -> merged one + the survivor
    assert len(cells[1]) == 1          # row 1 lost the absorbed cell
    assert len(cells[2]) == 3          # untouched


@pytest.mark.django_db(transaction=True)
def test_split_returns_the_freed_cells(page, live_server):
    # seed [[{"colspan": 2, "rowspan": 2}], []], click the merged cell, press
    # [data-split], save, assert a rectangular 2x2 with NO span keys at all.


@pytest.mark.django_db(transaction=True)
def test_merge_then_split_all_returns_the_original_rectangle(page, live_server):
    """The normalize_data BRANCH FLIP, pinned end to end.

    normalize_data picks its branch from "does any cell carry a span", so
    splitting the last merge flips a grid from keep-ragged-verbatim to
    rectangularising (pad-to-max-width, plus the 2x2 collapse guard). That is
    only safe because the editor never posts a layout-inconsistent grid.
    """
    from courses.models import TableElement
    from tests.test_e2e_table_editor import _login
    from tests.test_e2e_table_editor import _make_pa_user
    from tests.test_e2e_table_editor import _unit

    _make_pa_user("flip")
    _login(page, live_server, "flip")
    unit = _unit("flip", "flip")
    element = _seed(
        unit,
        TableElement,
        [[{"html": f"{r}{c}"} for c in range(3)] for r in range(3)],
    )
    before = _cells(TableElement, element)

    # merge (0,0)..(1,1)
    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    _cell(page, TABLE_ROOT, 1, 1).click(modifiers=["Shift"])
    page.locator(f"{TABLE_ROOT} [data-merge]").click()
    assert _save_and_report(page, TABLE_ROOT), "merge save was rejected"
    assert _cells(TableElement, element)[0][0]["colspan"] == 2

    # split it again -- the grid flips back to the rectangularising branch
    _reopen(page, live_server, unit, element, TABLE_ROOT)
    _cell(page, TABLE_ROOT, 0, 0).click()
    page.locator(f"{TABLE_ROOT} [data-split]").click()
    assert _save_and_report(page, TABLE_ROOT), "split save was rejected"

    after = _cells(TableElement, element)
    assert [len(r) for r in after] == [3, 3, 3]
    for row in after:
        for c in row:
            assert "colspan" not in c
            assert "rowspan" not in c
            assert "header" not in c
    # The surviving anchor keeps its content; the re-created cells are empty.
    assert after[0][0]["html"] == before[0][0]["html"]


@pytest.mark.django_db(transaction=True)
def test_merge_over_content_asks_before_discarding(page, live_server):
    # seed cells with text in the second one; register a dialog handler that
    # DISMISSES; merge; assert the grid is unchanged. Then accept and assert it
    # merged.


@pytest.mark.django_db(transaction=True)
def test_merge_while_focus_sits_on_an_absorbed_cell_refocuses_the_survivor(page, live_server):
    # Click cell B, shift-click A so the range covers both but focusCell is B
    # (an absorbed cell). Merge. The kept cell must hold DOM focus -- assert
    # `page.locator(TABLE_ROOT + " td:focus")` is the merged cell.
    #
    # NOTE: the keyboard consequence of getting this wrong (Alt+Shift+Arrow
    # silently dying, because its listener is on the grid) is asserted in
    # Task 15, where the chord exists. Do not reference the chord here.
```

- [ ] **Step 2: Verify failure** (`[data-merge]` is inert).

- [ ] **Step 3: Implement the selection state**

Rename the existing `focusedCell` **declaration and all 13 of its references**
(`table_editor.js` lines 201, 204, 208, 214, 222, 296, 298, 310, 330, 332-334, 340,
342-343) to `focusCell`, and reuse that declaration — do **not** re-declare it. A
whole-file find-and-replace of the identifier is the safe move here. Only the two range
variables are new:

```js
    // focusCell (the existing declaration, renamed) is the SINGLE authority for
    // what the toolbar acts on. It is set on plain click/focusin and
    // deliberately NOT moved by Shift+click: suppressing the Shift mousedown
    // also suppresses focus movement, so document.activeElement is unusable.
    var rangeAnchor = null;   // a cell node
    var rangeEnd = null;      // a LAYOUT {r, c} coordinate, not a node

    function clearRange(announce) {
      rangeEnd = null;
      Array.prototype.forEach.call(
        grid.querySelectorAll(".is-range"),
        function (c) { c.classList.remove("is-range"); }
      );
      if (announce) say("range-cleared");
      refreshToolbarState();
    }

    // Every client-built string rides on a data-msg-* attribute, because this
    // markup is created in JS where {% trans %} is unavailable.
    function msg(key) {
      return editor.getAttribute("data-msg-" + key) || "";
    }

    function say(key) {
      var region = editor.querySelector("[data-range-status]");
      if (region) region.textContent = msg(key);
    }

    // A range that is legal in SHAPE but larger than a table may be -- e.g.
    // all 26 columns of the grandfathered table. canMerge already refuses it;
    // this is only so the button can say WHY instead of greying out silently.
    function tooBig() {
      if (!rangeAnchor || !rangeEnd) return false;
      var rg = libliTableGrid.rangeCells(desc, rangeAnchor, rangeEnd);
      if (!rg) return false;
      return (rg.c1 - rg.c0 + 1) > desc.maxCols ||
             (rg.r1 - rg.r0 + 1) > desc.maxRows;
    }

    function paintRange() {
      Array.prototype.forEach.call(
        grid.querySelectorAll(".is-range"),
        function (c) { c.classList.remove("is-range"); }
      );
      if (!rangeAnchor || !rangeEnd) return;
      var rg = libliTableGrid.rangeCells(desc, rangeAnchor, rangeEnd);
      if (!rg) return;
      rg.cells.forEach(function (c) { c.classList.add("is-range"); });
      say("range-selected");
      refreshToolbarState();
    }
```

**Update the existing `focusin` handler** (`table_editor.js:219`) — three changes, all
load-bearing, and without them the merge/split tests cannot pass:

```js
    grid.addEventListener("focusin", function (e) {
      var td = e.target.closest("td[contenteditable], th[contenteditable]");
      if (!td) return;
      focusCell = td;
      rangeAnchor = td;   // a plain click ALWAYS re-seats the anchor, so a
                          // stale anchor from an earlier merge can never
                          // silently re-appear in the next range
      clearRange(false);  // ... and drops any live range
      if (toolbar) toolbar.hidden = false;
      refreshToolbarState();   // replaces the bare refreshAlignButtons() call:
                               // Split and Header enablement both read
                               // focusCell, so the toolbar must recompute
                               // whenever focus moves
    });
```

Shift+click, scoped away from form controls:

```js
    // Chrome and genuine multi-line controls are excluded, but the fill-table's
    // ANSWER INPUT is not: it is styled full-cell, so it covers essentially the
    // whole answer cell. Excluding it would leave an author with no way to make
    // an answer cell a range endpoint at all -- which Task 16's first test
    // requires. Shift+click text-selection inside a one-line input is the
    // (marginal) thing traded away; the caret still lands there on a plain click.
    var SHIFT_EXEMPT = "textarea, select, button, [data-control]";

    grid.addEventListener("mousedown", function (e) {
      if (!e.shiftKey) return;
      if (e.target.closest(SHIFT_EXEMPT)) return;
      e.preventDefault();   // stop contenteditable starting a text selection
    });

    grid.addEventListener("click", function (e) {
      if (!e.shiftKey) return;
      if (e.target.closest(SHIFT_EXEMPT)) return;
      var td = e.target.closest("td, th");
      if (!td || td.hasAttribute("data-control")) return;
      // First gesture in a fresh editor: no focusin has fired, so there is no
      // anchor yet. Behave exactly like a plain click -- never reach
      // rangeCells with a null anchor.
      if (!rangeAnchor) {
        rangeAnchor = td;
        focusCell = td;
        // Focus explicitly: the mousedown above already preventDefault'ed, so
        // nothing in the grid has DOM focus and the grid-scoped keyboard chord
        // would stay unreachable until the author clicked again.
        td.focus();
        refreshToolbarState();
        return;
      }
      var sm = libliTableGrid.slotMap(desc);
      rangeEnd = libliTableGrid.anchorOf(sm, td);
      paintRange();
    });
```

Toolbar state, running **before** any null-focus early return:

```js
    function refreshToolbarState() {
      if (!toolbar) return;
      var mergeBtn = toolbar.querySelector("[data-merge]");
      var splitBtn = toolbar.querySelector("[data-split]");
      var headerBtn = toolbar.querySelector("[data-header-toggle]");
      // These three must be settled even when focusCell is null -- a delete
      // that nulls it would otherwise leave Merge enabled. "Toolbar hidden" is
      // a different mechanism and does not substitute.
      if (mergeBtn) {
        var ok = rangeAnchor && rangeEnd &&
                 libliTableGrid.canMerge(desc, rangeAnchor, rangeEnd);
        mergeBtn.disabled = !ok;
        mergeBtn.title = tooBig() ? msg("merge-too-big") : msg("merge");
      }
      if (splitBtn) {
        splitBtn.disabled = !(focusCell &&
          (libliTableGrid.colspanOf(focusCell) > 1 ||
           libliTableGrid.rowspanOf(focusCell) > 1));
      }
      // Task 12 already renders [data-header-toggle], so headerBtn is non-null
      // throughout Task 13 -- but refreshHeaderButton only exists from Task 14.
      // Ship the stub below in THIS task so refreshToolbarState cannot throw a
      // ReferenceError (which would take paintRange, clearRange and the whole
      // merge/split enablement down with it); Task 14 replaces its body.
      if (headerBtn) refreshHeaderButton(headerBtn);
      refreshAlignButtons();
    }

    // Replaced wholesale in Task 14.
    function refreshHeaderButton(btn) {
      btn.disabled = true;
    }
```

Merge and Split handlers. **Both go in the TOOLBAR `click` listener** (the one already
handling `[data-cmd]` / `[data-halign]`, `table_editor.js:294`) — **not** the grid-level
delegated `click` at line 245, which serves the row/column handles. The toolbar listener
is also the one whose `mousedown` `preventDefault`s, which is exactly why the merge tail
has to restore focus explicitly.

```js
      var mergeBtn = e.target.closest("[data-merge]");
      if (mergeBtn && !mergeBtn.disabled) {
        var rg = libliTableGrid.rangeCells(desc, rangeAnchor, rangeEnd);
        if (rg && absorbedNonEmpty(rg)) {
          if (!window.confirm(msg("merge-confirm"))) return;   // cancel: no change
        }
        var kept = libliTableGrid.merge(desc, rangeAnchor, rangeEnd);
        if (kept) {
          focusCell = kept;
          rangeAnchor = kept;
          kept.focus();     // not decoration -- see the note below
        }
        afterStructuralEdit();   // owns range clearing; do not clear here too
        return;
      }

      var splitBtn = e.target.closest("[data-split]");
      if (splitBtn && !splitBtn.disabled && focusCell) {
        var anchor = focusCell;
        libliTableGrid.split(desc, anchor);
        // The anchor survives a split, so focus simply stays on it.
        focusCell = anchor;
        rangeAnchor = anchor;
        anchor.focus();
        afterStructuralEdit();
        return;
      }
```

```js
    // Non-empty means: static html that is not blank, OR any answer cell, OR
    // any image cell -- so a merge can never silently lose an accepted answer
    // or an image's media pk. (table_editor.js has no kinds; the kind clauses
    // live in filltable_editor.js's override.)
    function absorbedNonEmpty(rg) {
      for (var i = 0; i < rg.cells.length; i++) {
        var c = rg.cells[i];
        if (c === rg.anchor) continue;
        if (cellIsNonEmpty(c)) return true;
      }
      return false;
    }

    function cellIsNonEmpty(c) {
      return c.textContent.trim() !== "" || c.querySelector("img") !== null;
    }
```

Extend `afterStructuralEdit` from Task 11 with the range/toolbar steps:

```js
    function afterStructuralEdit() {
      clearRange(false);
      rebuildColControls(grid, desc);
      refreshControlState(grid, desc);
      refreshToolbarState();
      serialize();
    }
```

> **The focus step is not decoration.** The toolbar's `mousedown` handler `preventDefault`s so the button never takes focus; when `focusCell` was an *absorbed* cell, merge detaches the focused node and DOM focus falls to `<body>`. Since the `Alt+Shift+Arrow` listener is registered **on the grid**, keyboard range selection would silently stop working after every such merge until the author clicked a cell again.

- [ ] **Step 4: Verify green and commit**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k spanning_merge -v
git add -A && git commit -m "feat(editor): shift-click range selection with merge and split"
```

---

### Task 14: the Header-cell toggle (node replacement)

**Files:**
- Modify: `courses/static/courses/js/table_editor.js`
- Test: `tests/test_e2e_spanning_merge.py` (append)

**Interfaces:**
- Consumes: Task 13's `focusCell` / `refreshToolbarState`
- Produces: `toggleHeaderCell(td)`, `refreshHeaderButton(btn)`

> `td` ↔ `th` needs a **new element**, and several live references point at the old node.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db(transaction=True)
def test_header_toggle_round_trips_a_header_cell(page, live_server):
    # click a cell, press [data-header-toggle], save; stored cell has
    # header: True. Toggle again, save; the key is GONE (not header: False).


@pytest.mark.django_db(transaction=True)
def test_header_toggle_is_disabled_for_a_cell_the_header_row_option_covers(page, live_server):
    # focus a row-0 cell, tick [data-th-row], and assert the button becomes
    # disabled WITHOUT a re-click -- enablement must be live.
```

- [ ] **Step 2: Implement**

```js
    // td <-> th is a NEW element, so every live reference to the old node must
    // be re-pointed or it silently dangles.
    function toggleHeaderCell(td) {
      if (!td) return;
      var tag = td.tagName === "TH" ? "td" : "th";
      var next = document.createElement(tag);
      var i;
      for (i = 0; i < td.attributes.length; i++) {
        next.setAttribute(td.attributes[i].name, td.attributes[i].value);
      }
      // MOVE the children rather than re-serializing: a live
      // .filltable-editor__answer input must keep its typed value and its
      // event bindings.
      while (td.firstChild) next.appendChild(td.firstChild);
      td.replaceWith(next);
      if (typeof cellStash !== "undefined" && cellStash.has(td)) {
        cellStash.set(next, cellStash.get(td));   // fill-table only
        cellStash.delete(td);
      }
      if (focusCell === td) focusCell = next;
      if (rangeAnchor === td) rangeAnchor = next;   // rangeEnd is a coordinate
      next.focus();
      refreshToolbarState();
      serialize();
    }

    // "Already promoted" must mean exactly what the RENDER templates mean, or
    // the editor and the renderer disagree about which cells are covered:
    //   header_row -> row 0
    //   header_col -> each row's POSITIONALLY FIRST cell (forloop.first), NOT
    //                 layout column 0 -- on a ragged grid these diverge.
    function headerLocked(td) {
      var tr = td.parentNode;
      var rows = desc.rows();
      if (thRow && thRow.checked && rows.indexOf(tr) === 0) return true;
      if (thCol && thCol.checked && desc.cells(tr)[0] === td) return true;
      return false;
    }

    function refreshHeaderButton(btn) {
      var locked = focusCell ? headerLocked(focusCell) : true;
      btn.disabled = !focusCell || locked;
      btn.setAttribute(
        "aria-pressed", String(!!focusCell && focusCell.tagName === "TH")
      );
      btn.classList.toggle("is-on", !!focusCell && focusCell.tagName === "TH");
      btn.title = locked ? msg("header-locked") : msg("header");
    }
```

Replace Task 13's `refreshHeaderButton` stub with the real one above, and add the click
branch to the **TOOLBAR** click listener, beside merge/split (not the grid-level listener
— the toolbar's `mousedown` `preventDefault` is what keeps the caret in the cell):

```js
      var hdrBtn = e.target.closest("[data-header-toggle]");
      if (hdrBtn && !hdrBtn.disabled && focusCell) {
        toggleHeaderCell(focusCell);
        return;
      }
```

Then make enablement **live** — the author can tick Header row while the same cell stays focused:

```js
    if (thRow) thRow.addEventListener("change", function () { serialize(); refreshToolbarState(); });
    if (thCol) thCol.addEventListener("change", function () { serialize(); refreshToolbarState(); });
```

- [ ] **Step 3: Verify green and commit**

```bash
git add -A && git commit -m "feat(editor): per-cell header toggle with live enablement"
```

---

### Task 15: `Alt+Shift+Arrow` + the chord probe

**Files:**
- Modify: `courses/static/courses/js/table_editor.js`
- Test: `tests/test_e2e_spanning_merge.py` (append)

**Interfaces:**
- Consumes: Task 13's `rangeEnd` coordinate + `paintRange`
- Produces: keyboard range selection

- [ ] **Step 1: Probe the chord FIRST, before writing anything**

The probe has to come first: the chord is baked into this task's tests *and* its
implementation *and* Tasks 16–17's help text and msgids. Probing afterwards would mean
rewriting all of them.

Run the app (`uv run python manage.py runserver 127.0.0.1:8000`; the worktree `.env`
supplies DEBUG + `libli_mat`), open any table element, focus a cell and press each
candidate:

| Candidate | Known conflict to watch for |
|---|---|
| `Alt+Shift+Arrow` | the Windows keyboard-layout-switch chord — directly relevant on a PL/EN machine |
| `Ctrl+Alt+Arrow` | Intel graphics screen rotation on some Windows setups |
| `Ctrl+Shift+Alt+Arrow` | the fallback of last resort; verify, don't assume |

Also confirm plain `Alt+Arrow` browser history navigation is not triggered.

**Record the winner and use it everywhere below.** The rest of this task, plus Tasks 16
and 17, use the confirmed chord — the plan writes `Alt+Shift+Arrow` throughout on the
assumption it passes.

- [ ] **Step 2: Write the failing tests**

```python
@pytest.mark.django_db(transaction=True)
def test_alt_shift_arrow_extends_and_then_shrinks_the_range(page, live_server):
    # click (0,0); Alt+Shift+ArrowRight selects TWO slots on the FIRST press
    # (seed AND move in one keystroke -- seeding alone would be a keystroke
    # with no visible effect). ArrowLeft then shrinks it back to one.


@pytest.mark.django_db(transaction=True)
def test_alt_shift_arrow_is_a_no_op_with_nothing_focused(page, live_server):
    # No click first: the keystroke must not throw and must not select.
```

- [ ] **Step 3: Implement, listener scoped to the grid**

```js
    // Registered on the GRID, not the document, so it is scoped to the editor
    // that owns it (a page can hold more than one).
    grid.addEventListener("keydown", function (e) {
      if (!e.altKey || !e.shiftKey) return;
      var delta = { ArrowRight: [0, 1], ArrowLeft: [0, -1],
                    ArrowDown: [1, 0], ArrowUp: [-1, 0] }[e.key];
      if (!delta) return;
      e.preventDefault();
      if (!focusCell) return;                   // no-op, never a throw
      var sm = libliTableGrid.slotMap(desc);
      if (!rangeEnd) {
        // Seed from focusCell's ANCHOR slot AND apply the move in the same
        // keystroke, so one press already selects two slots.
        rangeEnd = libliTableGrid.anchorOf(sm, focusCell);
        if (!rangeEnd) return;
        rangeAnchor = focusCell;
      }
      var r = Math.min(Math.max(rangeEnd.r + delta[0], 0), sm.height - 1);
      var c = Math.min(Math.max(rangeEnd.c + delta[1], 0), sm.width - 1);
      rangeEnd = { r: r, c: c };                // clamped; edge press is a no-op
      paintRange();                             // re-normalises every keystroke
    });

    grid.addEventListener("keydown", function (e) {
      // Only act -- and only swallow the event -- when a range is actually
      // live, so a stray Escape still reaches the media-picker and math-input
      // modals that share this page.
      if (e.key !== "Escape" || !rangeEnd) return;
      e.stopPropagation();
      clearRange(true);        // rangeAnchor stays at focusCell
    });
```

- [ ] **Step 4: Re-verify the chord end to end**

Step 1 probed the chord in isolation; now confirm it still behaves with the handler
actually bound (a `preventDefault`ed keydown can mask an OS chord in one direction but
not the other). Same server, same gesture, plus one range built entirely by keyboard.

- [ ] **Step 5: Re-run `makemessages` if the chord probe changed anything**

Task 12 already registered slice 3's msgids. Re-run only if Step 1 selected a fallback
chord that appears in a user-visible string:

```bash
uv run python manage.py makemessages -l en -l pl
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(editor): keyboard range selection via Alt+Shift+Arrow"
```

---

# SLICE 4 — the same UI in `filltable_editor.js`

---

### Task 16: fill-table selection, toolbar, kind preservation

**Files:**
- Modify: `courses/static/courses/js/filltable_editor.js`
- Modify: `templates/courses/manage/editor/_edit_filltable.html` (same buttons, messages, live region as Task 12)
- Test: `tests/test_e2e_spanning_merge.py` (append), `tests/test_filltable_editor_partial.py` (append)

**Interfaces:**
- Consumes: everything from slices 2–3
- Produces: merge/split/header in the fill-table editor, with kinds preserved

**What to copy, and where.** `filltable_editor.js` already has its own `wire()` with the
same shape as `table_editor.js`'s, so the transplant is mechanical — but it is ~200 lines
and the insertion points matter:

| From Task | Copy into `filltable_editor.js` | Insertion point |
|---|---|---|
| 6 | the `desc` descriptor literal | inside `wire()`, after `grid` is resolved (it was already added there in Task 6 — reuse it, do not build a second one) |
| 13 | `rangeAnchor` / `rangeEnd` declarations | beside the existing `focusedCell` (rename it to `focusCell` here too) |
| 13 | `msg`, `say`, `tooBig`, `clearRange`, `paintRange`, `SHIFT_EXEMPT` | after the existing `answerPlaceholder()` helper |
| 13 | the `focusin` rewrite | replace the existing handler at `filltable_editor.js:386`, keeping its image-alt reveal and `refreshToolbarState()` call |
| 13 | the `mousedown` + `click` Shift handlers | beside the existing delegated grid `click` |
| 13 | the merge / split branches | into the existing **toolbar** `click` listener (`filltable_editor.js:478`), beside `[data-answer-toggle]` |
| 14 | `toggleHeaderCell`, `headerLocked`, `refreshHeaderButton`, the `[data-header-toggle]` branch | same toolbar listener |
| 15 | the `Alt+Shift+Arrow` and `Escape` keydown handlers | beside the existing grid `keydown` |
| 13 | the two lines Task 13 added to `afterStructuralEdit` (`clearRange(false)`, `refreshToolbarState()`) | the `afterStructuralEdit` this file gained in Task 11 — Task 13 extended only the plain-table copy, so without this a fill-table merge leaves the `.is-range` highlight painted and Merge enabled against removed nodes |

Non-obvious specifics, each of which differs from the plain-table version:

- **`refreshToolbarState` already exists here** (`filltable_editor.js:271`) and owns the
  answer/image kind-button state. **Extend** it — add the Merge/Split/Header block
  *before* its early return (which reads `if (!toolbar || !focusCell) return;` once the
  `focusedCell` → `focusCell` rename above has been applied to this file too) — rather
  than replacing it, or the kind buttons stop updating.
- **`kept.focus()` is a no-op on an answer cell here.** A fill-table answer cell is
  `<td data-answer>` with no `contenteditable` and no `tabindex` (only image cells get
  `tabindex="0"`), so `.focus()` does nothing, DOM focus stays on `<body>`, and the
  grid-scoped keyboard chord becomes unreachable — precisely the failure the merge tail's
  focus step exists to prevent. In this file, focus the cell's
  `.filltable-editor__answer` input when present, falling back to the cell:
  `(kept.querySelector(".filltable-editor__answer") || kept).focus();`. Assert it: after
  `test_fill_table_merge_keeps_the_anchors_answer`, a subsequent chord press must still
  extend a range.
- **`SHIFT_EXEMPT` must not list `input`.** The answer cell's `.filltable-editor__answer`
  is styled full-cell, so exempting inputs would make an answer cell unselectable — and
  this task's first test merges an answer anchor.
- **`toggleHeaderCell`'s attribute copy** carries `data-answer` / `data-image` /
  `data-media` / `data-alt` / `tabindex` for free (it loops `td.attributes`), but its
  `cellStash` re-point is live here where it was inert in `table_editor.js`.
- **`headerLocked`** reads *this* editor's `thRow` / `thCol` (already resolved in `wire()`).

Three behavioural differences from the plain table:

1. **`cellIsNonEmpty` also treats kind as content**, so an answer or image cell always triggers the confirm:

```js
    // A merge must not silently lose an accepted answer or an image's media
    // pk, so ANY answer or image cell counts as non-empty regardless of what
    // it displays.
    function cellIsNonEmpty(c) {
      if (c.hasAttribute("data-answer") || c.hasAttribute("data-image")) return true;
      return c.textContent.trim() !== "";
    }
```

2. **The merged cell keeps the top-left's kind** — which needs no code, because `libliTableGrid.merge` mutates the anchor node in place and never touches its attributes. Pin it with a test rather than trusting it.

3. **`cellStash` is cleared on merge and split** (already handled by `afterStructuralEdit`).

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db(transaction=True)
def test_fill_table_merge_keeps_the_anchors_answer(page, live_server):
    # Anchor is an ANSWER cell; merge it with a static neighbour; the stored
    # cell must still be kind "answer" with its accepted answer intact.


@pytest.mark.django_db(transaction=True)
def test_fill_table_merge_over_an_image_cell_asks_first(page, live_server):
    # Dismiss the dialog -> the image cell's media pk survives untouched.


@pytest.mark.django_db(transaction=True)
def test_header_toggle_on_an_answer_cell_preserves_the_typed_answer(page, live_server):
    # Type into an answer cell, toggle header, and assert the input still holds
    # the typed text -- childNodes were MOVED, not re-serialized. Then toggle
    # the cell back to static and assert the stash restored the right html.
```

Plus the fill-table twin of Task 12's markup assertion, appended to
`tests/test_filltable_editor_partial.py` — the cheap render-level check that this
editor's new toolbar actually shipped:

```python
def test_filltable_editor_exposes_merge_split_and_header_controls():
    html = _render(FillTableElement())
    for attr in ("data-merge", "data-split", "data-header-toggle"):
        assert attr in html
    for msg in ("data-msg-merge-confirm", "data-msg-merge-too-big",
                "data-msg-header-locked", "data-msg-range-selected"):
        assert msg in html
    assert 'aria-live="polite"' in html
```

- [ ] **Step 2: Verify failure, transplant the wiring, verify green**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -k "spanning_merge or filltable" -v
```

- [ ] **Step 3: `makemessages` and commit**

```bash
uv run python manage.py makemessages -l en -l pl
git add -A && git commit -m "feat(filltable-editor): merge/split/header with kind preservation"
```

---

# SLICE 5 — help, i18n, verification, visual pass

---

### Task 17: help pages ×4, the caps message, and the i18n sweep

**Files:**
- Modify: `docs/help/course-admin/content-editors.md` + `.pl.md` (the `{el:table}` paragraph)
- Modify: `docs/help/course-admin/interactive-elements.md` + `.pl.md` (the `{el:filltable}` section)
- Modify: `courses/element_forms.py` (caps message wording)
- Modify: `tests/test_filltable_form.py:69` (asserts the old "limited to" wording)
- Modify: `locale/{en,pl}/LC_MESSAGES/django.po`

- [ ] **Step 1: Extend each of the four help passages**

Cover, in prose: Shift+click to select a range; the chord Task 15 **confirmed**; the Merge / Split / Header cell buttons; that merging keeps only the top-left cell's content; and — the one thing authors will otherwise file a bug about — **why Header cell is greyed out** when "Header row"/"Header column" is ticked, worded to match the button's own `title` so help and UI agree.

Also note the accepted `header_col` interaction: merging away a row's first cell promotes the next one to a header in the student view.

- [ ] **Step 2: Reword the caps message**

Under grandfathering, *"Tables are limited to %(r)d rows by %(c)d columns."* is misleading — a 26-wide table **is** saveable. It gates *growth*:

```python
                _("A table cannot be made larger than %(r)d rows by %(c)d columns.")
```

Say the same in the help text, and **do not** promise that a narrowed over-cap table can be widened again — the client gate is deliberately the stricter absolute cap, so narrowing a grandfathered table is one-way.

⚠️ **An existing test asserts the old wording.** `tests/test_filltable_form.py:69` does
`assert any("limited to" in str(e).lower() for e in f.errors["data"])`. Update it in this
task, and grep for other assertions on the message —
`grep -rn "limited to" tests/` — so the reword does not surface as a mystery failure in
Task 18's full-suite run.

- [ ] **Step 3: Sweep and translate**

```bash
uv run python manage.py makemessages -l en -l pl
```

Supply Polish for every new msgid (the three button labels, `header-locked`, `merge-too-big`, the two live-region strings, the merge confirm, the reworded caps message). Check for fuzzy flags. Per project convention, **delete** removed msgids from both `.po` files rather than leaving them as `#~` obsolete entries — the catalogue tests assert on that.

```bash
uv run python manage.py compilemessages
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e" -k "i18n or catalog or help" -v
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "docs(help): document cell merge/split; reword the table size limit"
```

---

### Task 18: live verification on `libli_mat`, then the visual pass

**Files:** none (verification), then whatever the frontend-design pass changes in `editor.css` / the sprite.

> **Read-mostly.** Prove u/432 opens and edits, leave its stored data unchanged, and do destructive experiments on a throwaway element you create and delete. **No reseed, no reload, no course rebuild** — the user is concurrently renaming nodes.

- [ ] **Step 1: Pre-flight — has anything already been damaged?**

Before trusting any live check, find out whether a spanning element was opened and saved through the *old* editor, which would have stripped its spans in the DB already:

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
  uv run python manage.py shell -c "
from courses.models import TableElement, FillTableElement
for m in (TableElement, FillTableElement):
    for el in m.objects.all():
        cells = (el.data or {}).get('cells') or []
        spans = [c for r in cells if isinstance(r, list)
                 for c in r if isinstance(c, dict)
                 and (c.get('colspan') or c.get('rowspan'))]
        if not spans: continue
        # Report max rowspan too: Task 1 changed _span's rowspan clamp from
        # MAX_COLS (20) to MAX_ROWS (50), so any STORED rowspan in 21..50 was
        # previously normalised down to 20 on every read and now resolves to
        # its true value -- a geometry change on already-imported tables that a
        # truthiness count cannot reveal. Inspect any element this flags.
        mx = max(c.get('rowspan') or 1 for c in spans)
        print(m.__name__, el.pk, len(spans), 'max_rowspan=', mx,
              '<== RE-CHECK' if mx > 20 else '')
"
```

Compare the count against the 24 spanning tables in `scripts/lal_import/out/**/*.json`. **Report any shortfall to the user** — recovering it means reloading that part, which needs their go-ahead. Do not reload anything unilaterally.

- [ ] **Step 2: Verify u/432 in a real browser**

Start the server (`uv run python manage.py runserver 127.0.0.1:8000`; the worktree `.env` supplies `DJANGO_DEBUG=True` + `libli_mat`), sign in as the local pilot account, and open the "Pola trójkątów podobnych" fill-table's editor.

Confirm: the two `colspan=3` explanation rows render aligned; the column strip has one button pair per **layout** column; Merge, Split and Alt+Shift+Arrow all work; a span-crossing column insert widens the span rather than adding a stray cell. Screenshot **light and dark**.

Then **leave the stored element unchanged** — either save an identical shape or navigate away.

- [ ] **Step 3: Probe browser undo once**

Merge two cells, press Ctrl+Z, and confirm the result is *visibly* wrong rather than silently corrupt (the accepted-risk note in the spec). `serialize()` re-reads the live DOM, so the damage is bounded to the table the author is looking at.

- [ ] **Step 4: Run the frontend-design skill**

Invoke `frontend-design` over the three new toolbar buttons, the sprite icons and the range highlight. Screenshot light **and** dark, self-critique, and iterate — per the project's standing rule that styling is verified with screenshots, never asserted.

- [ ] **Step 5: Full suite, then commit**

```
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m "not e2e" -q
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat uv run pytest -m e2e -q
uv run ruff check . && uv run ruff format --check .
```

```bash
git add -A && git commit -m "style(editor): visual pass over merge/split controls"
```

---

## Done when

- A spanning table opens with an aligned column strip, saves untouched without losing a single span or header flag, and can be merged, split, and restructured.
- A plain table's stored JSON is byte-identical to before this work.
- `/courses/matematyka/u/432/`'s fill-table — the acceptance criterion — is editable in `libli_mat`, with its stored data unchanged by the verification.
- Help pages in both languages describe the feature, including why Header cell greys out.
