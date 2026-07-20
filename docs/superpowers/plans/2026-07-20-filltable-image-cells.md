# FillTable Image Cells Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class, editor-authorable `image` cell kind to `FillTableElement` so images used as visual prompts in fill-table grid cells (the largest remaining LAL image-loss bucket: 31 imgs / 7 files) render instead of being stripped at save.

**Architecture:** A third cell kind `{kind:"image", media:<int pk>, alt}` stored in the element's `data` JSON, following the proven `GalleryElement` media-in-JSON precedent (`resolved_images()` → new `resolved_cells` property, `MediaAsset.objects.in_bulk`). Touches model, render template, parser, loader, transfer round-trip (export/import/validate/ref-router), the grid editor (media picker + per-cell alt), and form course-scoping. No migration (`FillTableElement.data` is already a `JSONField`).

**Tech Stack:** Django, PostgreSQL, BeautifulSoup4 (parser), vanilla JS (grid editor + media picker), Playwright (e2e), pytest. Run tooling with `uv run` (bash `ruff`/`pytest`/`python` are NOT on PATH). Test DB: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat`.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-20-filltable-image-cells-design.md` (6 spec-review rounds, clean). Read it before starting.
- **No migration** — `FillTableElement.data` is `JSONField(default=dict)`.
- **Two `media` representations, kept distinct:** model/editor JSON layer → `media` is an **int** pk (`_cell` validates `isinstance(int)` and rejects `bool`); transfer payload layer → `media` is a **string** bundle-local id (`ids.register(asset)` → `"m1"`, `"m2"`…). Never mix them.
- **Never mutate `self.data` / `el.data` in place** for a derived view — build fresh structures (the repo's recurring FillTable render lesson).
- **Never 500 a lesson on a dangling media pk** — an image cell whose pk does not resolve degrades to an empty static cell for rendering (Gallery's `resolved_images` skip-unresolved rule).
- **Test tooling:** `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest <path> -v`. pytest verdict lines don't survive the Bash pipe — rely on the exit code + grep for `FAILED`/`PASSED`. e2e tests are `-m e2e` (excluded by default; run focused + FOREGROUND).
- **Falsify every test** — after writing a test, confirm it FAILS for the right reason before implementing (the repo's "Falsify tests, don't run them" lesson: a passing-from-the-start test proves nothing).
- **Commit after each task** (each task ends green).

## File map

- `courses/models.py` — `FillTableElement._cell`, `_sanitized_data`, new `resolved_cells` property, `canonical_cells`, `render()` (Tasks 1–3).
- `templates/courses/elements/_filltable_cell.html` — taking-view image branch (Task 3); `courses/static/courses/css/…` — `.filltable__img` rule (Task 3).
- `scripts/lal_import/tables.py` — parser pure-image cell (Task 4).
- `courses/lal_loader/builders.py` — loader `fill_table` image resolution (Task 5).
- `courses/transfer/export.py` (`_ser_fill_table`, `_element_mids`), `courses/transfer/importer.py` (`_build_fill_table`), `courses/transfer/payloads.py` (`_val_fill_table`) — transfer round-trip (Tasks 6–7).
- `courses/element_forms.py` (`FillTableElementForm`), `courses/views_manage.py` — form course-scoping (Task 8).
- `templates/courses/manage/editor/_edit_filltable.html` — editor deserialize + toggle/alt UI (Tasks 9–10).
- `courses/static/courses/js/filltable_editor.js`, `media_picker.js` — grid editor + picker hook (Task 10).

---

### Task 1: Model — `image` cell kind in `_cell` and `_sanitized_data`

**Files:**
- Modify: `courses/models.py` (`FillTableElement._cell` ~917-937, `_sanitized_data` ~989-1009)
- Test: `tests/test_filltable_model.py`

**Interfaces:**
- Produces: `FillTableElement._cell(raw)` now returns `{kind:"image", media:<int>, alt:<str>, halign, valign}` for a valid image cell, or degrades an invalid one to `{kind:"static", html:"", …}`. `_sanitized_data` leaves image cells' `media` untouched, trims `alt`, writes no `html` key.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_model.py`:

```python
def test_cell_image_kind_valid_media_preserved():
    nd = FillTableElement.normalize_data(
        {"cells": [[{"kind": "image", "media": 7, "alt": "graph", "halign": "center"}]]}
    )
    c = nd["cells"][0][0]
    assert c == {"kind": "image", "media": 7, "alt": "graph",
                 "halign": "center", "valign": "top"}


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
    nd = FillTableElement.normalize_data({"cells": [[{"kind": "image", "media": 3, "alt": 9}]]})
    assert nd["cells"][0][0]["alt"] == ""


def test_sanitized_data_image_cell_keeps_media_trims_alt_no_html():
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": 5, "alt": "  a graph  "}]]}
    )
    el.save()
    cell = el.data["cells"][0][0]
    assert cell["kind"] == "image" and cell["media"] == 5
    assert cell["alt"] == "a graph"
    assert "html" not in cell  # the else-branch's sanitize_cell must NOT run on image cells
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/test_filltable_model.py -v -k image`
Expected: FAIL (image kind falls through to static today; `_sanitized_data` writes an `html` key onto the image cell).

- [ ] **Step 3: Add the image branch to `_cell`**

In `FillTableElement._cell`, after computing `halign`/`valign` and before the `ANSWER` branch (or between ANSWER and the static fallback), add:

```python
        if raw.get("kind") == "image":
            media = raw.get("media")
            if isinstance(media, int) and not isinstance(media, bool):
                alt = raw.get("alt")
                return {
                    "kind": "image",
                    "media": media,
                    "alt": alt if isinstance(alt, str) else "",
                    "halign": halign,
                    "valign": valign,
                }
            # invalid/missing media -> safe empty static (never a broken <img>)
            return {
                "kind": FillTableElement.STATIC,
                "html": "",
                "halign": halign,
                "valign": valign,
            }
```

- [ ] **Step 4: Add the image branch to `_sanitized_data`**

In `FillTableElement._sanitized_data`, the per-cell loop currently is `if kind == ANSWER: … else: cell["html"] = sanitize_cell(…)`. Insert an explicit image branch **before** the `else`:

```python
                    if cell.get("kind") == FillTableElement.ANSWER:
                        a = cell.get("answer")
                        cell["answer"] = a.strip() if isinstance(a, str) else ""
                    elif cell.get("kind") == "image":
                        alt = cell.get("alt")
                        cell["alt"] = alt.strip() if isinstance(alt, str) else ""
                        # leave `media` untouched; write NO html key
                    else:
                        cell["html"] = sanitize_cell(cell.get("html", ""))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/test_filltable_model.py -v`
Expected: PASS (new image tests + all existing static/answer tests).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py tests/test_filltable_model.py
git commit -m "feat(filltable): image cell kind in _cell + _sanitized_data"
```

---

### Task 2: Model — `resolved_cells` property

**Files:**
- Modify: `courses/models.py` (`FillTableElement`, add `resolved_cells` property near `canonical_cells`)
- Test: `tests/test_filltable_model.py`

**Interfaces:**
- Consumes: `_cell` image kind (Task 1).
- Produces: `FillTableElement.resolved_cells` — a **property** (no parens) returning the normalized grid with every image cell's `media` int pk replaced by its `MediaAsset`; unresolved pks degrade to `{kind:"static", html:"", …}`. Static/answer cells pass through. Consumed by Task 3 (render) and Task 9 (editor deserialize).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_model.py`:

```python
from tests.factories import make_image_asset, make_course


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
    el = FillTableElement(data={"cells": [[{"kind": "image", "media": 999999, "alt": "x"}]]})
    el.save()
    cell = el.resolved_cells[0][0]
    assert cell["kind"] == "static" and cell["html"] == ""


def test_resolved_cells_static_and_answer_pass_through():
    el = FillTableElement(
        data={"cells": [[{"kind": "static", "html": "s"},
                         {"kind": "answer", "answer": "1"}]]}
    )
    el.save()
    grid = el.resolved_cells
    assert grid[0][0]["kind"] == "static" and grid[0][0]["html"] == "s"
    assert grid[0][1]["kind"] == "answer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `… uv run pytest tests/test_filltable_model.py -v -k resolved_cells`
Expected: FAIL with `AttributeError: 'FillTableElement' object has no attribute 'resolved_cells'`.

- [ ] **Step 3: Implement the property**

Add to `FillTableElement` (near `canonical_cells`):

```python
    @property
    def resolved_cells(self):
        """The normalized grid with each image cell's `media` int pk replaced by its
        MediaAsset (one in_bulk pass). Unresolved pks degrade to an empty static cell
        so a dangling asset never 500s a lesson. Static/answer cells pass through.
        A property (parallel to normalized_data) so the editor template can read it."""
        cells = self.normalize_data(self.data)["cells"]
        ids = [c["media"] for row in cells for c in row if c.get("kind") == "image"]
        assets = MediaAsset.objects.in_bulk(ids)
        out = []
        for row in cells:
            out_row = []
            for c in row:
                if c.get("kind") == "image":
                    asset = assets.get(c["media"])
                    if asset is not None:
                        out_row.append({**c, "media": asset})
                    else:
                        out_row.append({"kind": self.STATIC, "html": "",
                                        "halign": c["halign"], "valign": c["valign"]})
                else:
                    out_row.append(c)
            out.append(out_row)
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `… uv run pytest tests/test_filltable_model.py -v -k resolved_cells`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/models.py tests/test_filltable_model.py
git commit -m "feat(filltable): resolved_cells property (image pk -> MediaAsset)"
```

---

### Task 3: Render — template image branch, CSS, and done/not-done composition

**Files:**
- Modify: `courses/models.py` (`FillTableElement.canonical_cells`, `render()`)
- Modify: `templates/courses/elements/_filltable_cell.html`
- Modify: CSS (find the filltable rules file, see Step 3) — add `.filltable__img`
- Test: `tests/test_filltable_render.py`

**Interfaces:**
- Consumes: `resolved_cells` (Task 2).
- Produces: `render()` emits image cells as `<img>` in BOTH `mine.done` and not-done states; `canonical_cells` now builds from `resolved_cells` so image cells carry a resolved `MediaAsset` on the done path.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_render.py`:

```python
from tests.factories import make_image_asset, make_course


def test_image_cell_renders_img_with_url_and_alt():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": asset.pk, "alt": "graph"},
                         {"kind": "answer", "answer": "1"}]]}
    )
    el.save()
    html = el.render()
    assert asset.file.url in html
    assert 'alt="graph"' in html
    assert "filltable__img" in html


def test_image_cell_unresolved_renders_no_broken_img():
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": 999999, "alt": "x"},
                         {"kind": "answer", "answer": "1"}]]}
    )
    el.save()
    html = el.render()
    assert "filltable__img" not in html  # degraded to empty static, no <img>


def test_done_render_keeps_image_and_canonicalises_answer():
    # mine.done path must resolve image cells too (uses canonical_cells)
    course = make_course()
    asset = make_image_asset(course, "g.png")
    el = FillTableElement(
        data={"cells": [[{"kind": "image", "media": asset.pk, "alt": "g"},
                         {"kind": "answer", "answer": "4 | four"}]]}
    )
    el.save()
    # canonical_cells is the done-path grid; assert the image cell is resolved there
    done_cells = el.canonical_cells
    assert done_cells[0][0]["kind"] == "image"
    assert done_cells[0][0]["media"].pk == asset.pk  # resolved, not an int
    assert done_cells[0][1]["answer"] == "4"  # first alternative
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `… uv run pytest tests/test_filltable_render.py -v -k image`
Expected: FAIL (template has no image branch → no `<img>`; `canonical_cells` returns an int `media`, not a MediaAsset).

- [ ] **Step 3: Add the template image branch + CSS**

In `templates/courses/elements/_filltable_cell.html`, the current body is `{% if cell.kind == "answer" %}…{% else %}{{ cell.html|safe }}{% endif %}`. Insert an `elif` before the `else`:

```django
{% elif cell.kind == "image" %}<img class="filltable__img" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
```

Find the filltable CSS (grep for `el--filltable` under `courses/static/courses/css/`) and add near those rules:

```css
.filltable__img { max-width: 100%; height: auto; display: block; }
```

Run `grep -rl "el--filltable" courses/static/courses/css/` to locate the exact file; add the rule there.

- [ ] **Step 4: Refactor `canonical_cells` to build from `resolved_cells`, and `render()` to use `resolved_cells` on the not-done path**

In `canonical_cells`, change the source line from `cells = self.normalize_data(self.data)["cells"]` to:

```python
        cells = self.resolved_cells  # resolve image pks -> MediaAsset, then swap answers
```

The rest of `canonical_cells` (answer → first-alternative swap; static/other pass-through) is unchanged — image cells fall into the `else` pass-through, already resolved.

In `render()`, the not-done branch currently does `ctx["data"] = self.normalize_data(self.data)`. Change it so cells are resolved:

```python
        else:
            ctx["data"] = {
                **self.normalize_data(self.data),
                "cells": self.resolved_cells,
            }
```

(The done branch already does `{**self.normalize_data(self.data), "cells": self.canonical_cells}` — now `canonical_cells` resolves images, so it needs no further change.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `… uv run pytest tests/test_filltable_render.py tests/test_filltable_model.py tests/test_filltable_restore.py -v`
Expected: PASS (new image render tests + all existing render/model/restore tests — the `canonical_cells` refactor must not regress the answer-swap tests).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py templates/courses/elements/_filltable_cell.html courses/static/courses/css
git add tests/test_filltable_render.py
git commit -m "feat(filltable): render image cells in both done and not-done states"
```

---

### Task 4: Parser — pure-image cell → `{kind:"image", media_src, alt}`

**Files:**
- Modify: `scripts/lal_import/tables.py` (`fill_table_element`, cell loop ~57-66)
- Test: `tests/lal_import/test_tables.py`

**Interfaces:**
- Produces: a fill-table cell whose only significant content is a single `<img>` emits `{kind:"image", media_src:<src>, alt:<alt>}`; the loader (Task 5) resolves `media_src`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/lal_import/test_tables.py`. Note the module imports `table_element`; also import `fill_table_element`:

```python
from scripts.lal_import.tables import fill_table_element


def _fill_table(html):
    return BeautifulSoup(html, "html.parser").find("table")


def test_pure_image_cell_becomes_image_kind():
    # one input cell (so it routes to fill_table) + one pure-<img> cell
    t = _fill_table(
        '<table>'
        '<tr><td><img src="static/g.png" alt="graph"></td>'
        '<td><input class="table_input"></td></tr>'
        '</table>'
    )
    inp = t.find("input", class_="table_input")
    result, _flags = fill_table_element(t, {id(inp): "5"})
    cells = result["data"]["cells"]
    assert cells[0][0] == {"kind": "image", "media_src": "static/g.png", "alt": "graph"}
    assert cells[0][1]["kind"] == "answer"


def test_image_cell_with_only_stray_br_still_image():
    t = _fill_table(
        '<table><tr>'
        '<td><img src="static/v.png"><br></td>'
        '<td><input class="table_input"></td>'
        '</tr></table>'
    )
    inp = t.find("input", class_="table_input")
    result, _ = fill_table_element(t, {id(inp): "1"})
    assert result["data"]["cells"][0][0]["kind"] == "image"


def test_mixed_text_and_image_cell_stays_static():
    # meaningful text alongside the image -> falls through to static (image dropped,
    # documenting the deliberate non-split; no such cell exists in the corpus)
    t = _fill_table(
        '<table><tr>'
        '<td>Look: <img src="static/g.png"></td>'
        '<td><input class="table_input"></td>'
        '</tr></table>'
    )
    inp = t.find("input", class_="table_input")
    result, _ = fill_table_element(t, {id(inp): "1"})
    assert result["data"]["cells"][0][0]["kind"] == "static"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/lal_import/test_tables.py -v -k image`
Expected: FAIL (the pure-image cell currently becomes `{kind:"static", html:"<img …>"}`).

- [ ] **Step 3: Add the pure-image detection in the cell loop**

In `fill_table_element`, the cell loop is:

```python
        for c in r:
            inp = c.find(class_="table_input")
            if inp is not None:
                raw = answer_by_input.get(id(inp), "")
                row.append({"kind": "answer", "answer": _answer_alternatives(raw)})
            else:
                row.append({"kind": "static", "html": c.decode_contents().strip()})
```

Insert a pure-image branch between the `answer` and `static` cases:

```python
        for c in r:
            inp = c.find(class_="table_input")
            if inp is not None:
                raw = answer_by_input.get(id(inp), "")
                row.append({"kind": "answer", "answer": _answer_alternatives(raw)})
            elif not c.get_text(strip=True) and len(c.find_all("img")) == 1:
                # a pure image cell (only an <img>, maybe a stray <br>): keep the
                # image as an image cell; the loader resolves media_src -> MediaAsset.
                img = c.find("img")
                row.append({"kind": "image",
                            "media_src": img.get("src", ""),
                            "alt": img.get("alt", "")})
            else:
                row.append({"kind": "static", "html": c.decode_contents().strip()})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `… uv run pytest tests/lal_import/test_tables.py -v`
Expected: PASS (new image tests + existing table tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lal_import/tables.py tests/lal_import/test_tables.py
git commit -m "feat(lal-parser): fill-table pure-image cell -> image kind"
```

---

### Task 5: Loader — resolve fill-table image-cell media

**Files:**
- Modify: `courses/lal_loader/builders.py` (`fill_table` branch ~190-198)
- Test: `tests/test_lal_loader_units.py`

**Interfaces:**
- Consumes: parser image cells `{kind:"image", media_src, alt}` (Task 4); `resolve_source`/`get_or_create_asset` (`courses/lal_loader/media.py`).
- Produces: a loaded `FillTableElement` whose image cells store `{kind:"image", media:<asset.pk>, alt}`; assets deduped by content hash; reload idempotent.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_lal_loader_units.py` (a helper writes a real PNG at `source_root/source_dir/media_src`):

```python
def _write_png(path):
    from io import BytesIO
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    Image.new("RGB", (1, 1)).save(buf, "PNG")
    path.write_bytes(buf.getvalue())


def test_build_fill_table_resolves_image_cell_media(tmp_path):
    from courses.models import FillTableElement, MediaAsset
    course = CourseFactory()
    unit = _unit(course)
    _write_png(tmp_path / "x" / "static" / "g.png")
    el = {
        "type": "fill_table",
        "data": {"cells": [[
            {"kind": "image", "media_src": "static/g.png", "alt": "graph"},
            {"kind": "answer", "answer": "1"},
        ]]},
    }
    obj = build_element(course, unit, el, source_root=tmp_path, source_dir="x",
                        allow_html=False)
    assert isinstance(obj, FillTableElement)
    cell = obj.data["cells"][0][0]
    assert cell["kind"] == "image"
    asset = MediaAsset.objects.get(pk=cell["media"])
    assert asset.course == course and asset.kind == "image"
    assert cell["alt"] == "graph"


def test_build_fill_table_image_dedups_on_reload(tmp_path):
    from courses.models import MediaAsset
    course = CourseFactory()
    unit = _unit(course)
    _write_png(tmp_path / "x" / "static" / "g.png")
    el = {"type": "fill_table", "data": {"cells": [[
        {"kind": "image", "media_src": "static/g.png", "alt": ""},
        {"kind": "answer", "answer": "1"},
    ]]}}
    build_element(course, unit, el, source_root=tmp_path, source_dir="x", allow_html=False)
    build_element(course, unit, el, source_root=tmp_path, source_dir="x", allow_html=False)
    assert MediaAsset.objects.filter(course=course, kind="image").count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `… uv run pytest tests/test_lal_loader_units.py -v -k fill_table_image` (adjust `-k` to match the two names)
Expected: FAIL — the loader stores `media_src` verbatim (no asset), so `MediaAsset.objects.get(pk=cell["media"])` raises (`media` is the string `"static/g.png"`).

- [ ] **Step 3: Implement image resolution in the `fill_table` builder**

The current branch is:

```python
    if etype == "fill_table":
        return _attach(
            unit,
            FillTableElement.objects.create(
                data=FillTableElement.normalize_data(el["data"])
            ),
        )
```

Replace the body with a cell-walk that resolves image cells before `normalize_data`:

```python
    if etype == "fill_table":
        data = el["data"]
        rows = data.get("cells") if isinstance(data.get("cells"), list) else []
        resolved_rows = []
        for row in rows:
            resolved_row = []
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, dict) and cell.get("kind") == "image":
                    path = resolve_source(source_root, source_dir, cell["media_src"])
                    asset = get_or_create_asset(course, "image", path)
                    resolved_row.append({
                        "kind": "image",
                        "media": asset.pk,
                        "alt": cell.get("alt", ""),
                        **{k: cell[k] for k in ("halign", "valign") if k in cell},
                    })
                else:
                    resolved_row.append(cell)
            resolved_rows.append(resolved_row)
        resolved_data = {**data, "cells": resolved_rows}
        return _attach(
            unit,
            FillTableElement.objects.create(
                data=FillTableElement.normalize_data(resolved_data)
            ),
        )
```

Confirm `resolve_source` and `get_or_create_asset` are already imported at the top of `builders.py` (they are — used by the `image`/`video` branches).

- [ ] **Step 4: Run tests to verify they pass**

Run: `… uv run pytest tests/test_lal_loader_units.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/lal_loader/builders.py tests/test_lal_loader_units.py
git commit -m "feat(lal-loader): resolve fill-table image-cell media to assets"
```

---

### Task 6: Transfer — serialize / import / validate round-trip

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_fill_table` ~170)
- Modify: `courses/transfer/importer.py` (`_build_fill_table` ~589)
- Modify: `courses/transfer/payloads.py` (`_val_fill_table` ~618)
- Test: `tests/test_filltable_transfer.py`

**Interfaces:**
- Consumes: `MediaIdMap` (`export.py`), `_require_media` (`payloads.py`), `resolved_cells` (Task 2) is NOT used here — export resolves via `in_bulk` directly (see below).
- Produces: an image cell round-trips as `media` = string bundle-local id (export) → real asset pk (import); the validator returns the media-ref set for image cells.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_transfer.py`:

```python
from courses.transfer.export import MediaIdMap
from courses.transfer.schema import TransferError
from tests.factories import make_image_asset, make_course


def test_image_cell_round_trip_preserves_asset_and_alt():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    src = FillTableElement(data={"cells": [[
        {"kind": "image", "media": asset.pk, "alt": "graph"},
        {"kind": "answer", "answer": "1"},
    ]]})
    src.save()

    ids = MediaIdMap()
    payload = SERIALIZERS["fill_table"][1](src, ids)
    # export must register the asset and emit a STRING local id, not the int pk
    local_id = payload["cells"][0][0]["media"]
    assert isinstance(local_id, str)
    assert payload["cells"][0][0]["alt"] == "graph"
    assert ids.items() == [(local_id, asset)]

    # validate: media_kinds maps local id -> kind; validator must not raise and must
    # return a ref set containing the local id
    media_kinds = {local_id: "image"}
    refs = VALIDATORS["fill_table"](payload, "e1", media_kinds)
    assert local_id in refs

    # import: assets maps local id -> a (possibly new) MediaAsset
    new_course = make_course()
    dest_asset = make_image_asset(new_course, "g2.png")
    obj, _children = BUILDERS["fill_table"](payload, {local_id: dest_asset})
    cell = obj.data["cells"][0][0]
    assert cell["kind"] == "image" and cell["media"] == dest_asset.pk
    assert cell["alt"] == "graph"


def test_export_does_not_mutate_source_data():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    src = FillTableElement(data={"cells": [[{"kind": "image", "media": asset.pk, "alt": "g"}]]})
    src.save()
    SERIALIZERS["fill_table"][1](src, MediaIdMap())
    assert src.data["cells"][0][0]["media"] == asset.pk  # still the int pk, un-clobbered


def test_validator_image_cell_missing_media_key_raises_clean():
    payload = {"cells": [[{"kind": "image", "alt": "x"}]]}  # no media key
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](payload, "e1", {})


def test_validator_image_cell_unregistered_media_raises():
    payload = {"cells": [[{"kind": "image", "media": "m9", "alt": "x"}]]}
    with pytest.raises(TransferError):
        VALIDATORS["fill_table"](payload, "e1", {})  # m9 not in media_kinds
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `… uv run pytest tests/test_filltable_transfer.py -v -k image`
Expected: FAIL (`_ser_fill_table` returns raw `dict(el.data)` → `media` is still the int pk; `_val_fill_table` returns `set()` and never checks image cells; `_build_fill_table` never remaps).

- [ ] **Step 3: Rewrite `_ser_fill_table` to rebuild fresh + register image media**

Replace `_ser_fill_table` (`export.py`):

```python
def _ser_fill_table(el, ids):
    # Build a FRESH data structure — never mutate el.data (export runs in-process,
    # e.g. duplicate-unit). Register each image cell's asset (skipping unresolved
    # pks, degrading them to empty static, like _gallery_assets), so the bundle
    # references it; carry alt/halign/valign through.
    from courses.models import MediaAsset

    data = el.normalize_data(el.data)
    rows = data["cells"]
    img_pks = [c["media"] for row in rows for c in row if c.get("kind") == "image"]
    assets = MediaAsset.objects.in_bulk(img_pks)
    out_rows = []
    for row in rows:
        out_row = []
        for c in row:
            if c.get("kind") == "image":
                asset = assets.get(c["media"])
                if asset is not None:
                    out_row.append({"kind": "image", "media": ids.register(asset),
                                    "alt": c.get("alt", ""),
                                    "halign": c["halign"], "valign": c["valign"]})
                else:
                    out_row.append({"kind": "static", "html": "",
                                    "halign": c["halign"], "valign": c["valign"]})
            else:
                out_row.append(dict(c))
        out_rows.append(out_row)
    return {"header_row": data["header_row"], "header_col": data["header_col"],
            "case_sensitive": data["case_sensitive"], "border": data["border"],
            "prompt": data["prompt"], "cells": out_rows}
```

- [ ] **Step 4: Extend `_build_fill_table` to remap image media**

Replace `_build_fill_table` (`importer.py`):

```python
def _build_fill_table(data, assets):
    # Remap each image cell's STRING local id -> the real asset pk (mirrors
    # _build_gallery). normalize_data + save() then sanitise/rectangularise.
    if isinstance(data, dict) and isinstance(data.get("cells"), list):
        rows = []
        for row in data["cells"]:
            out = []
            for cell in row if isinstance(row, list) else []:
                if isinstance(cell, dict) and cell.get("kind") == "image":
                    out.append({**cell, "media": assets[cell["media"]].pk})
                else:
                    out.append(cell)
            rows.append(out)
        data = {**data, "cells": rows}
    return (
        _clean_save(FillTableElement(data=FillTableElement.normalize_data(data))),
        (),
    )
```

- [ ] **Step 5: Extend `_val_fill_table` to require + return image media refs**

In `_val_fill_table` (`payloads.py`), keep the existing gross-corruption leniency, and while walking cells accumulate a ref set. For each cell that is a dict with `kind == "image"`, call `_require_media(cell.get("media"), elid, media_kinds, "image")` and union its return into the ref set; **return the ref set** instead of `set()`. Sketch:

```python
def _val_fill_table(data, elid, media_kinds):
    if not isinstance(data, dict):
        _err(...)  # existing message
    cells = data.get("cells")
    if not isinstance(cells, list):
        _err(...)
    refs = set()
    for row in cells:
        if not isinstance(row, list):
            _err(...)
        for cell in row:
            if not isinstance(cell, dict):
                _err(...)
            if cell.get("kind") == "image":
                refs |= _require_media(cell.get("media"), elid, media_kinds, "image")
    return refs
```

Match the EXACT existing `_err` messages/structure already in `_val_fill_table` — only add the `refs` accumulation, the image branch, and the `return refs`. Confirm `_require_media` returns `{local_id}` (used with `|=`) by reading its definition (~97-102).

- [ ] **Step 6: Run tests to verify they pass**

Run: `… uv run pytest tests/test_filltable_transfer.py -v`
Expected: PASS (new image round-trip tests + all existing fill_table transfer tests, incl. `test_validator_accepts_tolerable_drift` and `test_validator_rejects_gross_corruption`).

- [ ] **Step 7: Commit**

```bash
git add courses/transfer/export.py courses/transfer/importer.py courses/transfer/payloads.py tests/test_filltable_transfer.py
git commit -m "feat(transfer): round-trip fill-table image cells (register/remap/validate)"
```

---

### Task 7: Transfer — `_element_mids` fill_table branch (tolerant-export attribution)

**Files:**
- Modify: `courses/transfer/export.py` (`_element_mids` ~366)
- Test: `tests/test_transfer_export.py` (or `tests/test_filltable_transfer.py`)

**Interfaces:**
- Consumes: the export payload shape from Task 6 (`data["cells"]` with image cells carrying a string `media` local id).
- Produces: `_element_mids("fill_table", data)` yields each image cell's string `media` local id, so `mid_refs` attributes a missing image to its unit in a tolerant export.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_transfer_export.py`:

```python
def test_element_mids_fill_table_yields_image_local_ids():
    from courses.transfer.export import _element_mids
    data = {"cells": [[
        {"kind": "image", "media": "m3", "alt": "g"},
        {"kind": "answer", "answer": "1"},
        {"kind": "static", "html": "s"},
    ]]}
    assert list(_element_mids("fill_table", data)) == ["m3"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `… uv run pytest tests/test_transfer_export.py -v -k element_mids_fill_table`
Expected: FAIL — `_element_mids` has no `fill_table` branch, so it hits the scalar default `data.get("media")` (None) and yields `[]`.

- [ ] **Step 3: Add the `fill_table` branch to `_element_mids`**

In `_element_mids`, before the scalar default (`m = data.get("media")`), add (mirroring the `gallery` branch's `isinstance(..., str)` guard):

```python
    if type_key == "fill_table":
        return [
            c["media"]
            for row in (data.get("cells") or [])
            for c in (row or [])
            if isinstance(c, dict) and c.get("kind") == "image"
            and isinstance(c.get("media"), str)
        ]
```

(Match the exact return style of the existing `gallery` branch — list comprehension vs generator — read ~366-377 first and mirror it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `… uv run pytest tests/test_transfer_export.py -v -k element_mids`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/export.py tests/test_transfer_export.py
git commit -m "feat(transfer): _element_mids fill_table branch for image attribution"
```

---

### Task 8: Form — course-scope image-cell media in `FillTableElementForm`

**Files:**
- Modify: `courses/element_forms.py` (`FillTableElementForm`)
- Modify: `courses/views_manage.py` (~842 add-path tuple; the edit-path form construction ~1115-1123)
- Test: `tests/test_filltable_form.py`

**Interfaces:**
- Consumes: `_CourseScopedMediaForm` (provides `self.course` + `course=` kwarg), `MediaAsset`.
- Produces: `FillTableElementForm(course=…)` rejects an image cell whose `media` is not an image in `self.course`; a course-scoped image cell validates.

> **Spec gap being closed:** the spec's form section covered invalid-media degrade but not cross-course scoping. `GalleryElementForm` course-scopes its media ids; image cells introduce the same author-submitted pks, so `FillTableElementForm` gets the same guard (Gallery precedent).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_form.py`:

```python
import json
import pytest
from courses.element_forms import FillTableElementForm
from tests.factories import make_image_asset, make_course

pytestmark = pytest.mark.django_db


def _form(data_dict, course):
    return FillTableElementForm(data={"data": json.dumps(data_dict)}, course=course)


def test_form_accepts_course_scoped_image_cell():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    form = _form({"cells": [[
        {"kind": "image", "media": asset.pk, "alt": "g"},
        {"kind": "answer", "answer": "1"},
    ]]}, course)
    assert form.is_valid(), form.errors


def test_form_rejects_cross_course_image_cell():
    course = make_course()
    other = make_course()
    foreign = make_image_asset(other, "g.png")
    form = _form({"cells": [[
        {"kind": "image", "media": foreign.pk, "alt": "g"},
        {"kind": "answer", "answer": "1"},
    ]]}, course)
    assert not form.is_valid()
    assert "data" in form.errors
```

Also confirm the existing `_form` helper in this file (which builds `FillTableElementForm(data=…)` WITHOUT `course`) still works — `course=None` must be accepted (it is: `_CourseScopedMediaForm.__init__(course=None)`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `… uv run pytest tests/test_filltable_form.py -v -k image`
Expected: FAIL — `FillTableElementForm` doesn't accept `course=` (raises `TypeError`) and doesn't scope image cells.

- [ ] **Step 3: Make `FillTableElementForm` course-scoped**

Change the base class and add image-cell scoping in `clean_data`:

```python
class FillTableElementForm(_CourseScopedMediaForm):
    media_kind = "image"

    class Meta:
        model = FillTableElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["data"].required = False

    def clean_data(self):
        from courses.filltable import answer_cells, is_blank_answer

        data = self.cleaned_data.get("data")
        nd = FillTableElement.normalize_data(data if isinstance(data, dict) else {})
        cells = nd["cells"]
        n_rows, n_cols = len(cells), len(cells[0])
        if n_rows > FillTableElement.MAX_ROWS or n_cols > FillTableElement.MAX_COLS:
            raise forms.ValidationError(
                _("Tables are limited to %(r)d rows by %(c)d columns.")
                % {"r": FillTableElement.MAX_ROWS, "c": FillTableElement.MAX_COLS}
            )
        answers = list(answer_cells(cells))
        if not answers:
            raise forms.ValidationError(
                _("Mark at least one answer cell (use the “Answer cell” button).")
            )
        if any(is_blank_answer(ans) for _r, _c, ans in answers):
            raise forms.ValidationError(
                _("An answer cell is blank — type its accepted answer, "
                  "or make it a normal cell.")
            )
        # Course-scope image cells (mirrors GalleryElementForm): every image cell's
        # media must be an image in this course.
        img_ids = {c["media"] for row in cells for c in row if c.get("kind") == "image"}
        if img_ids and self.course is not None:
            allowed = set(
                MediaAsset.objects.filter(
                    course=self.course, kind="image", pk__in=img_ids
                ).values_list("pk", flat=True)
            )
            if img_ids - allowed:
                raise forms.ValidationError(
                    _("A table image is not an image in this course.")
                )
        return nd
```

(`_CourseScopedMediaForm.__init__` guards `if "media" in self.fields` — FillTable has no `media` field, so it's a no-op; `self.course` is still set. `MediaAsset` is already imported in `element_forms.py`.)

- [ ] **Step 4: Thread `course` in the editor views**

In `courses/views_manage.py`, add `"filltable"` to the add-path tuple (~842):

```python
        extra = (
            {"course": unit.course}
            if type_key in ("image", "video", "dragtoimagequestion", "gallery", "filltable")
            else {}
        )
```

Find the EDIT-path form construction (~1115-1123, `form = FORM_FOR_TYPE[type_key](instance=el.content_object, **extra)`) and ensure its `extra` likewise includes `{"course": course}` for `"filltable"`. Read that block and mirror whatever conditional the add-path uses (the two must agree). If the edit path builds `extra` separately, add `"filltable"` there too.

- [ ] **Step 5: Run tests to verify they pass**

Run: `… uv run pytest tests/test_filltable_form.py tests/test_filltable_manage_plumbing.py -v`
Expected: PASS (new scoping tests + existing form + manage-plumbing tests — the latter exercises the add/edit view wiring; confirm passing `course` didn't break an unscoped call site).

- [ ] **Step 6: Commit**

```bash
git add courses/element_forms.py courses/views_manage.py tests/test_filltable_form.py
git commit -m "feat(filltable): course-scope image-cell media in the editor form"
```

---

### Task 9: Editor deserialize — render existing image cells in `_edit_filltable.html`

**Files:**
- Modify: `templates/courses/manage/editor/_edit_filltable.html`
- Test: `tests/test_filltable_editor_partial.py`

**Interfaces:**
- Consumes: `resolved_cells` (Task 2) for the thumbnail URL + `cell.media.pk` for the hidden id.
- Produces: an existing image cell renders as `td[data-image]` with a thumbnail `<img>`, a hidden media id (`cell.media.pk`), and an alt input — so `filltable_editor.js` (Task 10) round-trips it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_filltable_editor_partial.py`:

```python
from tests.factories import make_image_asset, make_course


def test_editor_renders_existing_image_cell():
    course = make_course()
    asset = make_image_asset(course, "g.png")
    el = FillTableElement(data={"cells": [[
        {"kind": "image", "media": asset.pk, "alt": "graph"},
        {"kind": "answer", "answer": "1"},
    ]]})
    el.save()
    html = _render(el)
    assert "data-image" in html
    assert asset.file.url in html          # thumbnail
    assert f'data-media="{asset.pk}"' in html   # hidden pk (NOT the asset __str__)
    assert 'value="graph"' in html          # per-cell alt


def test_editor_toolbar_has_image_toggle_and_alt_input():
    html = _render(FillTableElement())
    assert "data-image-toggle" in html
    assert "data-image-alt" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `… uv run pytest tests/test_filltable_editor_partial.py -v -k image`
Expected: FAIL (grid iterates `normalized_data` with unresolved int `media`; no image branch; no toggle/alt controls).

- [ ] **Step 3: Iterate `resolved_cells` for the grid + add the image cell branch**

In `_edit_filltable.html`, the grid loop is `{% for row in d.cells %}` where `d = form.instance.normalized_data`. Keep `d` for header/border/prompt, but iterate the RESOLVED grid for rows. Change the grid `<table>` loop to iterate `form.instance.resolved_cells`:

```django
  <div class="table-editor__grid filltable-editor__grid" data-table-grid>
    <table>
      {% for row in form.instance.resolved_cells %}
      <tr>
        {% for cell in row %}
        {% if cell.kind == "answer" %}
        <td data-answer class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}">
          <input type="text" class="filltable-editor__answer" value="{{ cell.answer }}"
                 placeholder="{% trans 'Accepted answer' %}">
        </td>
        {% elif cell.kind == "image" %}
        <td data-image data-media="{{ cell.media.pk }}" data-alt="{{ cell.alt }}"
            class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}">
          <img class="filltable-editor__img" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
        </td>
        {% else %}
        <td contenteditable="true" class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}">{{ cell.html|safe }}</td>
        {% endif %}
        {% endfor %}
      </tr>
      {% endfor %}
    </table>
  </div>
```

Note: `{{ cell.alt }}` reused for both the hidden `data-alt` and the `<input value>` (Task 10 wires the toolbar alt input to this per-cell `data-alt`). Keep the `{% with d=... %}` wrapper for the controls strip.

- [ ] **Step 4: Add the "Image cell" toggle + alt input to the toolbar**

In the `data-table-toolbar`, after the `data-answer-toggle` button, add:

```django
    <button type="button" class="rte-btn" data-image-toggle
            title="{% trans 'Image cell' %}" aria-label="{% trans 'Image cell' %}"
            data-pick-media="image" data-pick-mode="cell"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-answer"/></svg></button>
    <input type="text" class="filltable-editor__alt input" data-image-alt hidden
           placeholder="{% trans 'Image description (alt)' %}">
```

(Reuse an existing sprite `#ed-answer` for now, or add an image sprite if one exists — grep `courses/static` for available `#ed-*` symbols. The exact icon is cosmetic; the `data-image-toggle` hook is what matters.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `… uv run pytest tests/test_filltable_editor_partial.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_edit_filltable.html tests/test_filltable_editor_partial.py
git commit -m "feat(filltable-editor): deserialize image cells + image-cell toolbar controls"
```

---

### Task 10: Editor JS — image cell kind, picker hook, per-cell alt, serialize

**Files:**
- Modify: `courses/static/courses/js/filltable_editor.js`
- Modify: `courses/static/courses/js/media_picker.js`
- Test: `tests/test_e2e_filltable.py` (new e2e), and a JS-free serialize assertion via the partial if feasible

**Interfaces:**
- Consumes: the `td[data-image]` DOM + `data-image-toggle`/`data-image-alt` controls (Task 9); the media picker's `[data-pick-media]` open path + `data-asset-id` string.
- Produces: an authored image cell serialises to `{kind:"image", media:<int>, alt:<per-cell>, halign, valign}` in the hidden `data` field; multi-image grids keep distinct alts.

- [ ] **Step 1: Write the failing e2e test**

Add to `tests/test_e2e_filltable.py` a test that (mirroring the file's login/seed harness) opens the editor for a unit, adds a FillTable, converts two cells to image cells via the picker, sets DISTINCT alts on each, saves, reopens, and asserts both alts survive. Skeleton (adapt seed/login helpers already in the file):

```python
def test_author_two_image_cells_with_distinct_alts(page, live_server):
    # ... login as an owner, open the editor for a lesson unit, add a FillTable ...
    editor = page.locator("[data-filltable-editor]")
    grid = editor.locator("[data-table-grid]")

    def make_image_cell(cell, alt, asset_name):
        cell.click()
        editor.locator("[data-image-toggle]").click()          # opens the media picker
        page.locator(".picker .asset-pick", has_text=asset_name).first.click()
        editor.locator("[data-image-alt]").fill(alt)

    cells = grid.locator("td")
    make_image_cell(cells.nth(0), "first graph", "seedA")
    make_image_cell(cells.nth(1), "second graph", "seedB")
    # ... ensure at least one answer cell exists so the form validates ...
    page.locator("button[type='submit']").click()

    # reopen the editor and assert BOTH alts round-tripped (distinct, not shared)
    # ... navigate back to the same element's editor ...
    imgs = page.locator("[data-table-grid] td[data-image]")
    assert imgs.nth(0).get_attribute("data-alt") == "first graph"
    assert imgs.nth(1).get_attribute("data-alt") == "second graph"
```

The seed must create two course image assets named so the picker grid shows them (`make_image_asset(course, ...)` + set `original_filename` to `seedA`/`seedB`). Use the file's existing `_seed_*`/`_login` helpers; if the editor add-flow is heavy to drive, seed the FillTable element via ORM with two static cells and only drive the toggle→pick→alt→save→reload path (still a REAL gesture, per the repo's e2e lesson — no `page.evaluate` shortcut into serialize()).

- [ ] **Step 2: Run the e2e to verify it fails**

Run: `DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local uv run pytest tests/test_e2e_filltable.py -v -m e2e -k image` (FOREGROUND)
Expected: FAIL — the toggle does nothing (no JS wiring), the picker doesn't target the cell, alts aren't stored/serialised.

- [ ] **Step 3: Add the cell-target hook to `media_picker.js`**

In `wireEditorPicker`, (a) in the `[data-pick-media]` click handler, detect the cell mode and register the fill-table cell target; (b) in `selectAsset`, route to a fill-table callback before the gallery/select branches. Add a parallel hook (do NOT overload `libliGalleryAdd`):

```javascript
// in selectAsset(id, name, url), near the top (before targetSelect handling):
if (fillTargetCb) {
  var cb = fillTargetCb; fillTargetCb = null;
  closeModal();
  cb(id, name, url);   // id is a STRING (data-asset-id)
  return;
}
```

```javascript
// in the [data-pick-media] click handler, when data-pick-mode === "cell":
if (pick.getAttribute("data-pick-mode") === "cell" && window.libliFillTablePickImage) {
  fillTargetCb = window.libliFillTablePickImage(pick);  // editor returns a callback
}
```

Declare `var fillTargetCb = null;` alongside `appendTarget`. `window.libliFillTablePickImage(pickButton)` is implemented in `filltable_editor.js` (Step 4): it returns a callback that fills the focused cell. Keep the existing kind-based fetch/openModal flow (the `url = root.dataset.pickerUrl + "?kind=image"` path is unchanged).

- [ ] **Step 4: Wire the image cell kind in `filltable_editor.js`**

Extend `filltable_editor.js`:
1. `dataCells(tr)` — currently `tr.querySelectorAll("td:not([data-control])")`, which already includes `td[data-image]`; confirm image columns are counted on resize (they are, by that selector — no change, but verify).
2. Expose the picker hook. In `wire(editor)`, define:

```javascript
    window.libliFillTablePickImage = function () {
      var target = focusedCell;          // the cell the toggle was clicked on
      return function (id, _name, url) { // picker callback: id is a STRING
        setImageCell(target, parseInt(id, 10), url, "");
        serialize();
      };
    };
```

3. `setImageCell(td, mediaInt, url, alt)` converts a cell to an image cell: stash the prior kind's content (reuse `stashFor`), set `td.setAttribute("data-image","")`, `td.dataset.media = String(mediaInt)`, `td.dataset.alt = alt`, replace innerHTML with `<img class="filltable-editor__img" src="url">`, remove `contenteditable`/`data-answer`.
4. Toolbar handler: `data-image-toggle` click → if `focusedCell`, the picker opens via `media_picker.js` (the button has `data-pick-media="image" data-pick-mode="cell"`, so `media_picker.js` handles the open; `filltable_editor.js` only supplies the callback via `libliFillTablePickImage`). Ensure clicking the toggle does not also fire the answer-toggle path.
5. Alt input: on `focusin` of a `td[data-image]`, show `[data-image-alt]` and set its value to `td.dataset.alt`; on `input` of `[data-image-alt]`, write `focusedCell.dataset.alt` (only if it's an image cell) and `serialize()`. Hide the alt input when the focused cell is not an image cell.
6. `serialize()` — in the per-cell loop, add an image branch BEFORE the answer/static branches:

```javascript
          if (td.hasAttribute("data-image")) {
            row.push({
              kind: "image",
              media: parseInt(td.dataset.media, 10),
              alt: td.dataset.alt || "",
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            });
          } else if (td.hasAttribute("data-answer")) { ... } else { ... }
```

`media` MUST be a JS number (`parseInt`), matching `_cell`'s int check.
7. Submit guard (`onSubmit`): image cells are not answer cells, so the existing "≥1 answer cell / no blank answers" checks (which query `td[data-answer]`) already ignore them — confirm, no change.
8. `toggleAnswerCell`/stash: extend the stash so a cell round-tripping image→static→answer does not lose content; an image cell being toggled to static should clear `data-image`/`data-media`/`data-alt` and restore the stashed html.

- [ ] **Step 5: Run the e2e to verify it passes**

Run: `… uv run pytest tests/test_e2e_filltable.py -v -m e2e` (FOREGROUND; run the whole file to catch regressions in the existing fill/check e2e)
Expected: PASS (new multi-image-alt test + the existing correct/incorrect fill tests).

- [ ] **Step 6: Run the full filltable + transfer + loader + parser suite (regression gate)**

Run: `… uv run pytest tests/test_filltable_model.py tests/test_filltable_render.py tests/test_filltable_form.py tests/test_filltable_context.py tests/test_filltable_check.py tests/test_filltable_restore.py tests/test_filltable_transfer.py tests/test_filltable_editor_partial.py tests/test_filltable_manage_plumbing.py tests/test_transfer_export.py tests/test_transfer_schema.py tests/test_lal_loader_units.py tests/lal_import/test_tables.py -v`
Expected: PASS (whole feature, no regressions).

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/filltable_editor.js courses/static/courses/js/media_picker.js tests/test_e2e_filltable.py
git commit -m "feat(filltable-editor): author image cells via media picker + per-cell alt"
```

---

## End-to-end verification (after all tasks)

Not a task — the SDD driver runs this after Task 10 and reports URLs to the user.

1. Reseed the 7 affected parts with `--force` and reload into `libli_mat`:
   ```bash
   for p in 010_funkcja_liniowa 030_kwadratowa 070_geometria 100_geometria_2 \
            104_geometria_3_czworokaty 110_przeksztalcanie_wykresow_funkcji; do
     DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
       uv run python -m scripts.lal_import.parser $p --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --force
     DATABASE_URL=postgres://libli:libli@localhost:5432/libli_mat DJANGO_SETTINGS_MODULE=config.settings.local \
       uv run python manage.py import_lal_content --course matematyka --part $p \
       --source-root "C:/Users/krzys/Documents/teaching/LAL/html" --json-dir scripts/lal_import/out --allow-html
   done
   ```
2. Re-run the recursion-aware measure (from the current scratchpad): the **fill_table_cell bucket drops 31 → 0**; total lost 76 → ~45 (sub-spec B tail remains).
3. Run the DEBUG server (per the memory's How-to-resume) and hand the user URLs for the `f_lin_023` and `wykresy_20` units so they can confirm images render above/beside the inputs and the self-check still works, plus an editor URL to confirm an image cell is authorable.

## Self-review notes

- **Spec coverage:** model image kind (T1) ✓, resolved_cells (T2) ✓, render + template + done/not-done composition (T3) ✓, parser pure-image (T4) ✓, loader resolve+dedup (T5) ✓, transfer register/remap/validate + no-mutation (T6) ✓, `_element_mids` attribution (T7) ✓, editor deserialize (T9) ✓, editor JS + picker + per-cell alt + parseInt + submit guard (T10) ✓, has_math (no code change; covered by T1's no-`html`-key on image cells) ✓. Course-scoping (T8) is an ADDITION beyond the spec (flagged).
- **Type consistency:** `media` is a JS/JSON number and a Python int at the model/editor layer everywhere (`parseInt` in JS, `isinstance(int)` in `_cell`); a string local id everywhere at the transfer layer (`ids.register`, `_require_media`, `_element_mids`, `_build_fill_table` remap). `resolved_cells` is a property (no parens) at every call site.
- **Ordering:** model (T1–3) → parser (T4) → loader (T5) → transfer (T6–7) → form (T8) → editor (T9–10). Each task is green and committable on its own.
