# Transfer Spanning Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make native colspan/rowspan spanning tables round-trip through the course transfer engine so the matematyka → `mat-pp` migration (and any spanning-table export/import) succeeds without data loss.

**Architecture:** The transfer *validator* `_val_table` is the only real blocker — export already serializes tables verbatim and import's `_build_table`→`normalize_data` already preserves spans. Rework `_val_table` into a shared prefix + a unified per-cell shape check (applied to both branches) + a two-way branch that differs only in geometry (uniform-width for non-spanning, span-aware `layout_dims` for spanning), reusing the model's own `_span`/`layout_dims` as the single source of truth. Also carry span keys through `_ser_fill_table`'s image-cell rebuild, and bump `FORMAT_VERSION` 4→5.

**Tech Stack:** Python 3.13, Django, pytest, `uv` for tooling.

## Global Constraints

- **Validator mirrors the model (lenient):** reject only genuine structural corruption (non-dict cell, unknown cell key, present-non-null non-str `html`, present-non-null out-of-enum alignment) and enforce `MAX_ROWS`/`MAX_COLS`. Never reject a value the model would coerce (bogus/absent/`null` optional or core fields). Read every cell field by value via `.get(...)` with an explicit `is not None` guard — never by key presence.
- **Single source of truth:** use `TableElement._span` and `TableElement.layout_dims` (already imported region uses `TableElement` in `payloads.py`) for span detection and geometry, so validator and model can never disagree.
- **No regression:** the unified cell check must never *newly reject* a cell that validates today; it only additionally allows optional keys and tolerates absent/null fields.
- **FORMAT_VERSION = 5** after this work (was 4).
- **Running tests (do this exactly):** from the worktree, run
  `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" <paths>`.
  The worktree-unique DB name avoids the cross-worktree `test_libli` contention. Do **NOT** set
  `DJANGO_SETTINGS_MODULE` (pyproject already pins `config.settings.test`; forcing `local` breaks an
  unrelated template test). `pytest`/`ruff`/`python` are not on PATH — always `uv run`. Also run
  `uv run ruff format --check` and `uv run ruff check` on touched files before committing.

---

### Task 1: Bump FORMAT_VERSION 4 → 5

**Files:**
- Modify: `courses/transfer/schema.py:14`
- Test: `tests/test_transfer_schema.py:57`, `tests/test_tabs_transfer.py:57-58`, `tests/test_transfer_export.py:220`

**Interfaces:**
- Consumes: nothing.
- Produces: `FORMAT_VERSION == 5` (read by `export.py` when writing a bundle manifest and by `importer.py`'s version gate). No signature changes.

- [ ] **Step 1: Update the version-assertion tests to expect 5 (make them fail)**

In `tests/test_transfer_schema.py` line 57, change `assert FORMAT_VERSION == 4` to `assert FORMAT_VERSION == 5`.

In `tests/test_transfer_export.py` line 220, change `assert manifest["format_version"] == 4` to `assert manifest["format_version"] == 5`.

In `tests/test_tabs_transfer.py`, rename and update:

```python
def test_format_version_is_5():
    assert FORMAT_VERSION == 5
```

(Leave the `format_version=99` / `format_version=0` rejection tests in `tests/test_transfer_archive.py` unchanged — they test the gate, not the constant.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_transfer_schema.py tests/test_tabs_transfer.py::test_format_version_is_5 tests/test_transfer_export.py::test_build_export_full_course_document -q`
Expected: FAIL — `FORMAT_VERSION` is still 4, so all three version assertions fail: `test_tabs_transfer.py::test_format_version_is_5`, the `assert FORMAT_VERSION == 5` at `tests/test_transfer_schema.py:57` (which lives inside the broader test `test_transfer_error_carries_message`, not a dedicated node), and `manifest["format_version"] == 5` inside `test_build_export_full_course_document`. Run whole files / real node ids — do not invent `format_version`-named nodes (only `test_tabs_transfer.py` has one).

- [ ] **Step 3: Bump the constant**

In `courses/transfer/schema.py` line 14, change:

```python
FORMAT_VERSION = 4
```
to
```python
FORMAT_VERSION = 5
```

- [ ] **Step 4: Run the version tests + the whole transfer suite to verify green**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_transfer_schema.py tests/test_tabs_transfer.py tests/test_transfer_export.py tests/test_transfer_archive.py tests/test_transfer_import.py -q`
Expected: PASS (all). The `format_version=99`/`0` rejection tests still pass (gate unchanged).

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/schema.py tests/test_transfer_schema.py tests/test_tabs_transfer.py tests/test_transfer_export.py
git commit -m "feat(transfer): bump FORMAT_VERSION to 5 for spanning-table support"
```

---

### Task 2: Make `_val_table` spanning-aware

**Files:**
- Modify: `courses/transfer/payloads.py:574-615` (the whole `_val_table` function)
- Test: `tests/test_table_transfer.py` (add new tests), `tests/test_transfer_validation.py` (optional home for the pure-validator cases — put them in `test_table_transfer.py` for locality)

**Interfaces:**
- Consumes: `TableElement._span(raw, key)` → `int|None`; `TableElement.layout_dims(cells)` → `(width, height)`; `TableElement.HALIGN`, `VALIGN`, `MAX_ROWS`, `MAX_COLS` (all already referenced in `payloads.py`). `_err` is the **module-local** helper at `payloads.py:31` (not imported from schema); `check_bool`, `check_list`, `_exact_keys` are imported from `courses.transfer.schema`.
- Produces: `_val_table(data, elid, media_kinds) -> set()` — unchanged signature and return; now accepts spanning tables.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_table_transfer.py` (the module already imports `TableElement`, `SERIALIZERS`, `BUILDERS`, `VALIDATORS`, `write_archive`, `open_archive`, `validate_archive_document`, `import_course`, `TransferError`, `ContentNodeFactory`, `CourseFactory`, `add_element`, `make_login`, and defines `_cell(html, h, v)`):

```python
def _span_cell(html="", h="left", v="top", **extra):
    return {"html": html, "halign": h, "valign": v, **extra}


def test_val_table_accepts_spanning_ragged_table():
    # Ragged rows + colspan/rowspan/header: rejected today, must be accepted.
    data = TableElement.normalize_data(
        {
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [
                [_span_cell("A", colspan=2, header=True)],          # 1 cell, width 2
                [_span_cell("B"), _span_cell("C", rowspan=2)],      # 2 cells
                [_span_cell("D")],                                  # 1 cell (C spans down)
            ],
        }
    )
    assert VALIDATORS["table"](data, "e1", {}) == set()


def test_val_table_rectangular_header_no_spans_accepted():
    # C1 regression: a non-spanning, uniform table whose only optional key is
    # per-cell header:True must validate (today's _exact_keys rejects "header").
    data = TableElement.normalize_data(
        {
            "header_row": False,
            "header_col": False,
            "border": "grid",
            "cells": [
                [_span_cell("H1", header=True), _span_cell("H2", header=True)],
                [_span_cell("a"), _span_cell("b")],
            ],
        }
    )
    assert VALIDATORS["table"](data, "e1", {}) == set()


def test_val_table_spanning_over_max_cols_rejected():
    row = [_span_cell("x", colspan=TableElement.MAX_COLS)] + [_span_cell("y")]
    data = {"header_row": False, "header_col": False, "border": "grid", "cells": [row]}
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_non_dict_cell_rejected_no_raw_exception():
    # Guard: a non-dict cell is rejected as TransferError, never a raw
    # AttributeError from _span (falsified in Step 4b by removing BOTH isinstance
    # guards). Passes before AND after the fix (today via _exact_keys' isinstance).
    data = {"header_row": False, "header_col": False, "border": "grid", "cells": [["oops"]]}
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_unknown_cell_key_rejected():
    data = {
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[_span_cell("x", bogus=1)]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_non_str_html_rejected():
    data = {
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"html": 123, "halign": "left", "valign": "top"}]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_out_of_enum_alignment_rejected():
    data = {
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"html": "", "halign": "sideways", "valign": "top"}]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_val_table_tolerates_bogus_optional_and_absent_core():
    # Mirror-the-model leniency: bogus optional span + a cell missing core keys
    # are accepted (the model coerces them). colspan:0 makes NO cell span, so
    # this is a rectangular 1x2 grid.
    data = {
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"colspan": 0}, {}]],
    }
    assert VALIDATORS["table"](data, "e1", {}) == set()


def test_val_table_non_spanning_ragged_still_rejected():
    data = {
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[_span_cell("a"), _span_cell("b")], [_span_cell("c")]],
    }
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "e1", {})


def test_spanning_table_round_trip_preserves_data(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    unit = ContentNodeFactory(course=src, kind="unit", unit_type="lesson")
    original = TableElement.normalize_data(
        {
            "header_row": True,
            "header_col": False,
            "border": "grid",
            "cells": [
                [_span_cell("Title", h="center", colspan=2, header=True)],
                [_span_cell("L", rowspan=2), _span_cell("r1")],
                [_span_cell("r2")],
            ],
        }
    )
    saved = TableElement.objects.create(data=original)
    add_element(unit, saved)

    buf = io.BytesIO()  # `io` is imported at the module top
    write_archive(src, None, buf)
    buf.seek(0)
    owner = make_login(client, "span-importer")
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course", target_course=None)
        dest = import_course(zf, mani, doc, media, owner)

    tables = [
        join.content_object
        for node in dest.nodes.all()
        for join in node.elements.all()
        if isinstance(join.content_object, TableElement)
    ]
    assert len(tables) == 1
    # Byte-identity against the SAVED source (import applies normalize+sanitize;
    # the saved source is already normalized+sanitized, so they must be equal).
    assert tables[0].data == saved.data


def test_spanning_table_imports_from_legacy_v4_declared_bundle(client, settings, tmp_path):
    # Spec test #8: a bundle DECLARING format_version=4 but carrying a spanning
    # table imports through the full gate (4 <= FORMAT_VERSION=5) AND the spanning
    # branch — proving span handling keys on span-key presence, not the version.
    # Build a real archive via write_archive (emits v5), then downgrade the
    # manifest's declared version to 4 and re-drive it through the importer.
    import json
    import zipfile

    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    unit = ContentNodeFactory(course=src, kind="unit", unit_type="lesson")
    data = TableElement.normalize_data(
        {
            "header_row": False, "header_col": False, "border": "grid",
            "cells": [[_span_cell("x", colspan=2)], [_span_cell("a"), _span_cell("b")]],
        }
    )
    add_element(unit, TableElement.objects.create(data=data))

    import io
    src_buf = io.BytesIO()
    write_archive(src, None, src_buf)
    src_buf.seek(0)

    out = io.BytesIO()
    with zipfile.ZipFile(src_buf) as zin, zipfile.ZipFile(out, "w") as zout:
        for name in zin.namelist():
            raw = zin.read(name)
            if name == "manifest.json":
                m = json.loads(raw)
                m["format_version"] = 4
                raw = json.dumps(m).encode()
            zout.writestr(name, raw)
    out.seek(0)

    owner = make_login(client, "v4-importer")
    with open_archive(out, expected_kind="course") as (zf, mani, doc, media):
        assert mani["format_version"] == 4
        validate_archive_document(zf, mani, doc, media, kind="course", target_course=None)
        dest = import_course(zf, mani, doc, media, owner)

    tables = [
        join.content_object
        for node in dest.nodes.all()
        for join in node.elements.all()
        if isinstance(join.content_object, TableElement)
    ]
    assert len(tables) == 1  # v4 bundle with spans imported via the spanning branch
```

(This test uses a local `import io` / `import json` / `import zipfile`; `io` is also at module top, so the local `import io` is harmless — keep it self-contained. The single-column non-spanning tests already import nothing extra.)

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_table_transfer.py -q`
Expected: the genuinely RED-first tests FAIL today — `test_val_table_accepts_spanning_ragged_table`, `test_val_table_rectangular_header_no_spans_accepted`, `test_val_table_tolerates_bogus_optional_and_absent_core`, `test_spanning_table_round_trip_preserves_data`, and `test_spanning_table_imports_from_legacy_v4_declared_bundle` (today's `_val_table` rejects them: `_exact_keys` rejects the `header`/`colspan`/`rowspan` keys and any absent core key; `len(widths) != 1` rejects ragged rows).

**These tests are NOT red-first** — they pass before AND after (today they raise `TransferError` via `_exact_keys`/`check_str`; after the fix, via the new checks): `test_val_table_spanning_over_max_cols_rejected` (today the `colspan` key trips `_exact_keys`' unknown-key rejection), `test_val_table_non_dict_cell_rejected_no_raw_exception`, `test_val_table_unknown_cell_key_rejected`, `test_val_table_non_str_html_rejected`, `test_val_table_out_of_enum_alignment_rejected`, and `test_val_table_non_spanning_ragged_still_rejected`. Merely running them proves nothing about whether the NEW guards are wired — so Step 4b falsifies each. (Note: the current `_val_table` never calls `_span`; a non-dict cell is rejected by `_exact_keys`' `isinstance` guard, **not** by any `AttributeError`.)

- [ ] **Step 3: Rewrite `_val_table`**

Replace the entire body of `_val_table` (`courses/transfer/payloads.py`, currently lines 574-615) with:

```python
def _val_table(data, elid, media_kinds):
    # `data` is the table dict DIRECTLY (header_row/header_col/border/cells),
    # matching _ser_table's un-wrapped return and _build_table's call shape.
    _exact_keys(data, ["header_row", "header_col", "border", "cells"], _("table data"))
    check_bool(data["header_row"], "header_row")
    check_bool(data["header_col"], "header_col")
    if data["border"] not in TableElement.BORDERS:
        _err(_("Element '%(el)s': unknown table border style."), el=elid)
    rows = check_list(data["cells"], "cells")
    if len(rows) > TableElement.MAX_ROWS:
        _err(
            _("Element '%(el)s': a table may have at most %(n)d rows."),
            el=elid,
            n=TableElement.MAX_ROWS,
        )
    # Per-row list check + width gather. The per-row check_list MUST run before
    # spanning detection / the cell check iterate a row, so a non-list row is
    # rejected (not silently walked as keys/chars). widths feeds the emptiness
    # guard and the non-spanning uniform-width check.
    widths = set()
    for row in rows:
        cells = check_list(row, "cells row")
        widths.add(len(cells))
    if not rows or widths == {0}:
        _err(_("Element '%(el)s': a table needs at least one cell."), el=elid)

    # Unified per-cell shape check (BOTH branches), mirroring the model's
    # leniency: reject only genuine corruption; tolerate whatever the model
    # coerces (absent/null fields; bogus optional header/colspan/rowspan). Every
    # field is read by value via .get with an explicit `is not None` guard, so a
    # missing key and an explicit null are treated identically (both tolerated).
    allowed = {"html", "halign", "valign", "header", "colspan", "rowspan"}
    for row in rows:
        for cell in row:
            if not isinstance(cell, dict):
                _err(_("Element '%(el)s': a table cell must be an object."), el=elid)
            if set(cell) - allowed:
                _err(
                    _("Element '%(el)s': a table cell has an unknown key."),
                    el=elid,
                )
            html = cell.get("html")
            if html is not None and not isinstance(html, str):
                # Crash-guard (not model-mirroring): a truthy non-str html
                # survives normalize_data's `get("html") or ""` and TypeErrors in
                # sanitize_cell's re.sub. Rejecting all present non-null non-str
                # matches today's check_str.
                _err(_("Element '%(el)s': a table cell's html must be text."), el=elid)
            halign = cell.get("halign")
            if halign is not None and halign not in TableElement.HALIGN:
                _err(_("Element '%(el)s': unknown cell horizontal alignment."), el=elid)
            valign = cell.get("valign")
            if valign is not None and valign not in TableElement.VALIGN:
                _err(_("Element '%(el)s': unknown cell vertical alignment."), el=elid)
            # header/colspan/rowspan: optional, NOT value-checked (model coerces).

    # Geometry: the only branch difference. Detection is byte-equivalent to the
    # model's normalize_data spanning predicate; the isinstance guard is
    # mandatory (all cells are dicts here — the check above errored otherwise —
    # but keep it to mirror the model exactly and never call _span on a non-dict).
    spanning = any(
        TableElement._span(c, "colspan") is not None
        or TableElement._span(c, "rowspan") is not None
        for row in rows
        for c in row
        if isinstance(c, dict)
    )
    if spanning:
        width, _height = TableElement.layout_dims(rows)
        if width > TableElement.MAX_COLS:
            _err(
                _("Element '%(el)s': a table may have at most %(n)d columns."),
                el=elid,
                n=TableElement.MAX_COLS,
            )
    else:
        if len(widths) != 1:
            _err(
                _("Element '%(el)s': all table rows must have the same number of cells."),
                el=elid,
            )
        n_cols = next(iter(widths))
        if n_cols > TableElement.MAX_COLS:
            _err(
                _("Element '%(el)s': a table may have at most %(n)d columns."),
                el=elid,
                n=TableElement.MAX_COLS,
            )
    return set()
```

- [ ] **Step 4: Run the table tests + full transfer suite to verify green**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_table_transfer.py tests/test_transfer_validation.py tests/test_transfer_import.py tests/test_transfer_export.py -q`
Expected: PASS (all new tests green; existing non-spanning/round-trip/over-cap tests still green).

- [ ] **Step 4b: Falsify each new guard (break → confirm RED for the stated reason → restore)**

The tests listed as "NOT red-first" above pass by construction; this step proves each new guard is actually wired by breaking it and confirming the matching test goes RED. For **each** row: make the temporary edit to `courses/transfer/payloads.py::_val_table`, run the named test, confirm it FAILS for the stated reason, then **revert the edit** before the next row.

Run each with: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_table_transfer.py::<test> -q`

| Break | Test that must go RED | Why |
|---|---|---|
| Delete the spanning `if width > TableElement.MAX_COLS:` block | `test_val_table_spanning_over_max_cols_rejected` | over-cap span layout no longer rejected → no `TransferError` |
| Delete the `if html is not None and not isinstance(html, str):` block | `test_val_table_non_str_html_rejected` | non-str `html` passes validation → no `TransferError` |
| Delete the `if halign is not None and halign not in TableElement.HALIGN:` block | `test_val_table_out_of_enum_alignment_rejected` | out-of-enum `halign` passes → no `TransferError` |
| Delete the `if set(cell) - allowed:` block | `test_val_table_unknown_cell_key_rejected` | unknown cell key passes → no `TransferError` |
| Delete BOTH the per-cell `if not isinstance(cell, dict):` line AND the `if isinstance(c, dict)` filter in the spanning-detection generator | `test_val_table_non_dict_cell_rejected_no_raw_exception` | a non-dict cell reaches `TableElement._span("oops", ...)` → raw `AttributeError` (not `TransferError`) → `pytest.raises(TransferError)` errors out |

Expected each time: the named test FAILS; after reverting, the full `tests/test_table_transfer.py` is green again. Confirm the revert with a final `uv run pytest -m "not e2e" tests/test_table_transfer.py -q` → PASS before committing.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format courses/transfer/payloads.py tests/test_table_transfer.py
uv run ruff check courses/transfer/payloads.py tests/test_table_transfer.py
git add courses/transfer/payloads.py tests/test_table_transfer.py
git commit -m "feat(transfer): accept spanning tables in _val_table"
```

---

### Task 3: Carry span keys through `_ser_fill_table` image cells

**Files:**
- Modify: `courses/transfer/export.py:170-216` (`_ser_fill_table`, the image-cell branches)
- Test: `tests/test_filltable_transfer.py` (add new tests)

**Interfaces:**
- Consumes: `FillTableElement.normalize_data` (already emits `header`/`colspan`/`rowspan` on spanning cells via `FillTableElement._cell`), `MediaIdMap`, `MediaAsset.objects.in_bulk`.
- Produces: `_ser_fill_table(el, ids)` — unchanged signature; image cells (both the resolved-`image` and the unresolved-`static` degradation) now carry `header`/`colspan`/`rowspan` when present.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_transfer.py` (it already imports `FillTableElement`, `SERIALIZERS`, `MediaIdMap`, `make_course`, `make_image_asset`):

```python
def test_ser_fill_table_carries_span_on_resolved_image_cell():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    src = FillTableElement(
        data={
            "case_sensitive": False,
            "prompt": "",
            "cells": [[
                {"kind": "image", "media": asset.pk, "colspan": 2, "header": True},
                {"kind": "static", "html": "x"},
            ]],
        }
    )
    src.save()  # normalize_data keeps colspan>1 + header
    payload = SERIALIZERS["fill_table"][1](src, MediaIdMap())
    img = payload["cells"][0][0]
    assert img["kind"] == "image"
    assert img["colspan"] == 2
    assert img["header"] is True


def test_ser_fill_table_carries_span_on_unresolved_image_cell():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    src = FillTableElement(
        data={
            "case_sensitive": False,
            "prompt": "",
            "cells": [[
                {"kind": "image", "media": asset.pk, "colspan": 2, "header": True},
            ]],
        }
    )
    src.save()
    asset.delete()  # now unresolvable -> degrade-to-static branch
    payload = SERIALIZERS["fill_table"][1](src, MediaIdMap())
    cell = payload["cells"][0][0]
    assert cell["kind"] == "static"
    assert cell["colspan"] == 2   # geometry preserved even though the image is gone
    assert cell["header"] is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_filltable_transfer.py -k span -q`
Expected: FAIL — the current image-cell rebuild emits only `kind/media/alt/halign/valign` (resolved) or `kind/html/halign/valign` (unresolved), dropping `colspan`/`header`.

- [ ] **Step 3: Carry the span keys through both image branches**

In `courses/transfer/export.py`, in `_ser_fill_table`, the loop currently builds the resolved-image and unresolved-static cells. Replace the `if c.get("kind") == "image":` block's two branches so each appends span keys. The new block:

```python
        for c in row:
            if c.get("kind") == "image":
                asset = assets.get(c["media"])
                if asset is not None:
                    out_cell = {
                        "kind": "image",
                        "media": ids.register(asset),
                        "alt": c.get("alt", ""),
                        "halign": c["halign"],
                        "valign": c["valign"],
                    }
                else:
                    out_cell = {
                        "kind": "static",
                        "html": "",
                        "halign": c["halign"],
                        "valign": c["valign"],
                    }
                # Carry span/header through BOTH branches: losing the image
                # must not silently un-span the cell and shift the grid.
                for k in ("header", "colspan", "rowspan"):
                    if k in c:
                        out_cell[k] = c[k]
                out_row.append(out_cell)
            else:
                out_row.append(dict(c))
```

(The `else: out_row.append(dict(c))` for static/answer cells is unchanged — it already preserves span keys.)

- [ ] **Step 4: Run to verify green**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" tests/test_filltable_transfer.py -q`
Expected: PASS (new span tests + all existing fill-table transfer tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_filltable_transfer.py
uv run ruff check courses/transfer/export.py tests/test_filltable_transfer.py
git add courses/transfer/export.py tests/test_filltable_transfer.py
git commit -m "feat(transfer): preserve span keys on fill-table image cells in export"
```

---

## Final verification (after all tasks)

Run the full non-e2e transfer + table + fill-table suites together to confirm no regression:

```bash
DATABASE_URL=postgres://libli:libli@localhost:5432/libli_spanning uv run pytest -m "not e2e" \
  tests/ -k "transfer or table or filltable" -q
```
Expected: all pass. This proves the round-trip, per-guard falsification, version bump, and fill-table span carry-through together.

**Out of automated scope (manual, post-merge):** re-run the real migration dry-run
(`migrate_course_content export` against `libli_mat` → `import --dry-run` against `mat-pp`) and confirm
all 21 parts validate — this needs the two local databases and the worktree media.
