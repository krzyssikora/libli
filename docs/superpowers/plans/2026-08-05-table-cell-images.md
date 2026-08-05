# Table cell images (slice C2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a course author put a `MediaAsset` image inside a `TableElement` cell and choose one of four absolute size presets, and give the sibling `FillTableElement`'s existing image cells the same size scale.

**Architecture:** Cells gain a `kind:"image"` shape carrying `{media, alt, size}` — `kind` appears **only** on image cells so text cells keep byte-identical serialisation. Sizing is four **absolute square bounding boxes** (`min(100%, Npx)` × `Npx`), not percentages, because a table cell's containing block is content-negotiated. Image resolution (pk → `MediaAsset`) lives in one shared helper, `courses/tablecells.py`, parameterised by each model's fallback-cell shape. Both table editors' toolbars become permanently visible with cell-scoped controls `disabled` until a cell is focused, and `refreshToolbarState()` becomes the single owner of per-cell control painting.

**Tech Stack:** Django 5 + `JSONField`, server-rendered templates, vanilla ES5-style JS (no build step), plain CSS with design tokens, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-05-table-cell-images-design.md` — read the "Settled decisions" section before starting. It is the authority; this plan is its execution.

## Global Constraints

- **Test invocation is `uv run pytest`** — `pytest`/`python`/`ruff` are not on PATH.
- **`pyproject.toml` already sets `addopts = "-q -m 'not e2e'"`.** Do **not** add a second `-q` (it suppresses the summary); use `-v` to override. e2e tests need an explicit `-m e2e` or they silently deselect with exit code 5.
- **Scope every test run narrowly** to the files you touched. Whole-repo sweeps are a branch-level gate, not a per-task step.
- **A test counts only when shown RED first.** Each task names the mutant its test must catch.
- **`kind` appears only on image cells.** A text cell must never gain a `kind` key — it would break the byte-identity invariant across all 7,246 existing cells.
- **`size` is ALWAYS written on an image cell** by `normalize_data` (absent → `"full"`). Readers of *normalized* cells may subscript `cell["size"]`; `_ser_table`, which must not normalize, uses `.get` everywhere.
- **Cell image size tokens:** `small` / `medium` / `large` / `full`. Stored default `full`; editor-insert default `medium`.
- **Django `default` filters are written single-quoted:** `|default:'full'`, matching `_edit_table.html`'s existing `|default:''`.
- **`templates/courses/manage/editor/_rte_swatches.html` must NOT be edited.** It is included by six toolbars whose editors have no `disabled` mechanism.
- **Never `git add -A` / `git add .`** — always explicit paths.
- **Reformat every code block in this plan to the repo's lint rules before committing.**
  `pyproject.toml` sets `select = ["E", "F", "I", "UP", "B", "S"]` with only `S101`
  ignored — so **`E402` is live** — plus
  `[tool.ruff.lint.isort] force-single-line = true` and the default 88-column limit.
  Concretely: **one import per line** (this plan writes
  `from courses.models import FillTableElement, TableElement` for brevity — split it),
  and no line over 88 columns. Several snippets here exceed both.
- **Put new imports in each file's existing top-of-file import block**, never appended
  beside the test bodies — a module-level import after a function definition is `E402`.
- **Run `uv run ruff check <files you touched>` in every task's verification step**, not
  only at the final gate, or a lint error surfaces several tasks late.
- Every `python -c` in this plan means `uv run python -c`; `python` is not on PATH.
- Commit messages follow the repo convention: `feat(table-cell-images): …`, `test(...)`, `docs(...)`, `refactor(...)`.

## Test-module constants you must add

The tests appended by Tasks 4, 6, 7 and 8 reference module-level path constants.
**Three of them do not exist yet** — add them once, at the top of the named file,
before writing any test that uses them. Verified against the tree:

| file | already defined | **add** |
|---|---|---|
| `tests/test_table_editor_partial.py` | `ROOT`, `EDITOR_HTML`, `TABLE_JS` | `PARTIAL = ROOT / "templates/courses/manage/editor/_edit_table.html"`<br>`EDITOR_CSS = ROOT / "courses/static/courses/css/editor.css"` |
| `tests/test_filltable_editor_partial.py` | `ROOT`, `EDITOR_HTML`, `FILLTABLE_JS` | `PARTIAL = ROOT / "templates/courses/manage/editor/_edit_filltable.html"`<br>`FILL_JS = FILLTABLE_JS` (alias, so this plan's snippets read the same in both files) |
| `tests/test_table_css.py` | `ROOT`, `CSS`, `EDITOR_CSS`, `TABLE_JS` | `FILL_JS = ROOT / "courses/static/courses/js/filltable_editor.js"` |

Note the existing fill-table constant is spelled **`FILLTABLE_JS`**, not `FILL_JS`
— either alias it as above or substitute the real name at each use. Do not
introduce a second `Path(__file__)` root; reuse `ROOT`.

---

## File Structure

**New files**

| file | responsibility |
|---|---|
| `courses/tablecells.py` | the single `resolve_image_cells(cells, *, empty_cell, course=None)` helper; imports `MediaAsset` function-locally |
| `templates/courses/elements/_table_cell.html` | the plain table's shared cell body (image branch + text branch), included from all five `tableelement.html` branches |
| `tests/test_table_cell_images.py` | model-layer unit tests for the new cell shape, the resolver and the sanitiser |
| `tests/test_table_cell_image_form.py` | form-layer tests: course scoping, `resolved_grid_cells`, the builder `course=` threading |
| `tests/test_e2e_table_cell_images.py` | measured browser tests: preset geometry, neighbour-text stability, per-cell controls |

**Modified files**

| file | change |
|---|---|
| `courses/models.py` | `TableElement.CellImageSize` + two default constants; both models' `_cell` image branch and `_sanitized_data`; both models' delegating `resolve_image_cells`; `TableElement.resolved_cells`; `TableElement.render` |
| `courses/element_forms.py` | `TableElementForm` → `_CourseScopedMediaForm`; `clean_data` scoping; `resolved_grid_cells`; `cell_image_sizes` on both forms |
| `courses/builder.py` | add `"table"` to the `course=`-threading type-key tuple |
| `courses/transfer/schema.py` | `FORMAT_VERSION` 7 → 8 |
| `courses/transfer/payloads.py` | `_val_table` cell allowlist + per-field policy |
| `courses/transfer/export.py` | `_ser_table` rewrite; `_element_mids` `table` branch; `_ser_fill_table` gains `size` |
| `courses/transfer/importer.py` | `_build_table` remap-before-normalize |
| `templates/courses/elements/tableelement.html` | five branches include the new partial |
| `templates/courses/elements/_filltable_cell.html` | image `<img>` gains the shared `cell-img` classes |
| `templates/courses/manage/editor/_edit_table.html` | toolbar always visible + markup `disabled`; image button, alt input, size select, Remove image; image cell branch in the grid loop |
| `templates/courses/manage/editor/_edit_filltable.html` | toolbar always visible + markup `disabled`; size select; `data-size` + preview modifier on both image branches |
| `templates/courses/manage/editor/editor.html` | new `ed-image-remove` sprite symbol; stale imagezoom comment |
| `courses/static/courses/js/table_editor.js` | image-cell support end-to-end |
| `courses/static/courses/js/filltable_editor.js` | painting ownership, hoists, `size` in `serialize()` |
| `courses/static/courses/js/media_picker.js` | per-editor picker dispatch |
| `courses/static/courses/css/courses.css` | `.cell-img` + four presets + print block; delete `.filltable__img`; fill-table editor preview modifiers |
| `courses/static/courses/css/editor.css` | `.table-editor__img` + modifiers; `[data-image-remove][hidden]` / `[data-image-size][hidden]`; delete `.table-editor__toolbar[hidden]` |
| existing guard tests | `test_editor_twin_drift.py`, `test_cell_selector_guard.py`, `test_table_css.py`, `test_imagezoom_render.py`, `test_filltable_editor_partial.py`, five `FORMAT_VERSION` sites |
| `locale/{en,pl}/LC_MESSAGES/django.{po,mo}` | two new msgids |
| `docs/help/course-admin/{content-editors,interactive-elements}{,.pl}.md` | author manuals |

---

## Task 1: Size tokens and both models' image-cell shape

**Files:**
- Modify: `courses/models.py` (`TableElement`, `FillTableElement`)
- Test: `tests/test_table_cell_images.py` (create)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `TableElement.CellImageSize` (a `models.TextChoices` with `.values`, `.choices`), `TableElement.DEFAULT_CELL_IMAGE_SIZE == "full"`, `TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE == "medium"`. `TableElement.normalize_data(...)["cells"]` may now contain cells of shape `{kind:"image", media:int, alt:str, size:str, halign, valign}` plus optional `header`/`colspan`/`rowspan`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_cell_images.py`:

```python
"""Model-layer tests for TableElement/FillTableElement image cells (slice C2)."""

import pytest

from courses.models import FillTableElement, TableElement


def _data(cell):
    return {"header_row": False, "header_col": False, "border": "grid",
            "cells": [[cell]]}


def test_image_cell_normalizes_to_the_full_shape():
    nd = TableElement.normalize_data(_data(
        {"kind": "image", "media": 7, "alt": "a graph", "size": "medium",
         "halign": "center", "valign": "middle"}
    ))
    assert nd["cells"][0][0] == {
        "kind": "image", "media": 7, "alt": "a graph", "size": "medium",
        "halign": "center", "valign": "middle",
    }


def test_size_is_always_written_on_an_image_cell():
    """Absent size reads as the stored default, so every reader may subscript."""
    nd = TableElement.normalize_data(_data({"kind": "image", "media": 7}))
    assert nd["cells"][0][0]["size"] == "full"


def test_junk_size_coerces_to_full():
    for junk in ("enormous", "", None, 3, True):
        nd = TableElement.normalize_data(_data(
            {"kind": "image", "media": 7, "size": junk}
        ))
        assert nd["cells"][0][0]["size"] == "full", junk


@pytest.mark.parametrize("media", [None, "7", 7.0, True, False])
def test_invalid_media_degrades_to_a_kindless_text_cell(media):
    """Never raise, never render a broken <img>, and never leave a `kind` key."""
    nd = TableElement.normalize_data(_data(
        {"kind": "image", "media": media, "halign": "right"}
    ))
    cell = nd["cells"][0][0]
    assert cell == {"html": "", "halign": "right", "valign": "top"}
    assert "kind" not in cell


def test_alt_is_coerced_and_bounded_at_255():
    nd = TableElement.normalize_data(_data(
        {"kind": "image", "media": 7, "alt": "x" * 300}
    ))
    assert len(nd["cells"][0][0]["alt"]) == 255
    nd = TableElement.normalize_data(_data({"kind": "image", "media": 7, "alt": None}))
    assert nd["cells"][0][0]["alt"] == ""


def test_non_string_alt_never_becomes_the_literal_None():
    """str(alt) would store "None" — junk coerced into content."""
    nd = TableElement.normalize_data(_data({"kind": "image", "media": 7, "alt": {"a": 1}}))
    assert nd["cells"][0][0]["alt"] == ""


def test_image_cell_keeps_header_and_spans():
    nd = TableElement.normalize_data(_data(
        {"kind": "image", "media": 7, "header": True, "colspan": 2, "rowspan": 3}
    ))
    cell = nd["cells"][0][0]
    assert cell["header"] is True and cell["colspan"] == 2 and cell["rowspan"] == 3


def test_text_cells_gain_no_kind_key():
    """The byte-identity invariant: a text cell must serialize as it always did."""
    nd = TableElement.normalize_data(_data({"html": "<b>hi</b>"}))
    assert nd["cells"][0][0] == {"html": "<b>hi</b>", "halign": "left", "valign": "top"}


def test_sanitized_data_skips_image_cells_and_strips_alt():
    data = _data({"kind": "image", "media": 7, "alt": "  spaced  ", "size": "large"})
    out = TableElement._sanitized_data(TableElement.normalize_data(data))
    cell = out["cells"][0][0]
    assert cell["alt"] == "spaced"
    assert "html" not in cell
    assert cell["media"] == 7 and cell["size"] == "large"


def test_sanitized_data_survives_an_image_cell_with_no_alt_key():
    """_sanitized_data runs on RAW self.data from save(); a bare .strip() raises."""
    out = TableElement._sanitized_data(_data({"kind": "image", "media": 7}))
    assert out["cells"][0][0]["alt"] == ""


def test_filltable_image_cell_gains_size():
    nd = FillTableElement.normalize_data(
        {"prompt": "", "case_sensitive": False, "header_row": False,
         "header_col": False, "border": "grid",
         "cells": [[{"kind": "image", "media": 7, "size": "small"}]]}
    )
    assert nd["cells"][0][0]["size"] == "small"


def test_filltable_image_cell_size_defaults_and_coerces():
    base = {"prompt": "", "case_sensitive": False, "header_row": False,
            "header_col": False, "border": "grid"}
    nd = FillTableElement.normalize_data(
        {**base, "cells": [[{"kind": "image", "media": 7}]]}
    )
    assert nd["cells"][0][0]["size"] == "full"
    nd = FillTableElement.normalize_data(
        {**base, "cells": [[{"kind": "image", "media": 7, "size": "huge"}]]}
    )
    assert nd["cells"][0][0]["size"] == "full"


def test_size_tokens_and_defaults_are_named_once():
    assert TableElement.CellImageSize.values == ["small", "medium", "large", "full"]
    assert TableElement.DEFAULT_CELL_IMAGE_SIZE == "full"
    assert TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE == "medium"


def test_full_label_carries_the_image_size_gettext_context():
    """The spec's i18n pin, and the only part of the label story that can silently go
    wrong. The bare msgid "Full" is ALREADY taken by courses/forms.py's structure preset,
    whose Polish is "Pełna" (feminine); an image size is masculine ("Pełny"). Wrapping
    all four in pgettext_lazy would instead mint three brand-new msgids that ship
    untranslated, so the asymmetry is deliberate: bare _() for the first three, context
    only on Full.

    A source-level test because the rendered label is a lazy proxy - comparing str()
    under the default locale would pass either way.
    """
    import inspect
    import re

    src = inspect.getsource(TableElement.CellImageSize)
    assert re.search(r'FULL\s*=\s*"full",\s*pgettext_lazy\(\s*"image size",\s*"Full"\s*\)', src)
    for member in ("SMALL", "MEDIUM", "LARGE"):
        m = re.search(rf'{member}\s*=\s*"\w+",\s*(\S+)\(', src)
        assert m and m.group(1) == "_", member
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_cell_images.py -v`
Expected: FAIL — `AttributeError: type object 'TableElement' has no attribute 'CellImageSize'`, and the image-cell tests fail because `_cell` currently drops `kind`/`media`/`size` and emits `{"html": "", ...}`.

- [ ] **Step 3: Add the size tokens to `TableElement`**

In `courses/models.py`, inside `class TableElement(ElementBase):` immediately after the `MAX_COLS = 20` line:

```python
    class CellImageSize(models.TextChoices):
        """Absolute square bounding boxes for an image inside a table cell.

        Deliberately a SECOND enum duplicating ImageElement.Size rather than an
        alias: the tokens coincide today but the rules behind them do not
        (percentages of a containing block there, absolute caps here), so the two
        scales must be free to evolve apart. The four labels intentionally SHARE
        ImageElement.Size's msgids — that keeps one catalog entry each.
        """

        SMALL = "small", _("Small")
        MEDIUM = "medium", _("Medium")
        LARGE = "large", _("Large")
        # pgettext, not plain _: the bare msgid "Full" is ALREADY taken by the
        # structure-preset label in courses/forms.py, whose Polish is "Pełna"
        # (feminine). An image size is masculine ("Pełny"), so it needs a context.
        FULL = "full", pgettext_lazy("image size", "Full")

    # Stored default: a cell with no `size` reads as `full`, preserving today's
    # width exactly for the 31 existing fill-table cell images.
    DEFAULT_CELL_IMAGE_SIZE = "full"
    # Editor-insert default: a NEWLY authored cell must not land in the unstable
    # content-negotiated state this slice exists to fix.
    EDITOR_INSERT_CELL_IMAGE_SIZE = "medium"
```

Verify `pgettext_lazy` is already imported at the top of `courses/models.py` (it is — `ImageElement.Size.FULL` uses it). If not, add it to the existing `django.utils.translation` import.

- [ ] **Step 4: Add the image branch to `TableElement._cell`**

Replace the body of `TableElement._cell` (currently builds one `{"html", "halign", "valign"}` literal) with:

```python
    @staticmethod
    def _cell(raw):
        raw = raw if isinstance(raw, dict) else {}
        h = raw.get("halign")
        v = raw.get("valign")
        halign = h if h in TableElement.HALIGN else "left"
        valign = v if v in TableElement.VALIGN else "top"
        # Image branch BEFORE the text fallback, mirroring FillTableElement._cell.
        # `size` is ALWAYS written here (unlike kind/header/spans, which are
        # present-only-when-set), so every reader of normalized cells may
        # subscript cell["size"].
        if raw.get("kind") == "image":
            media = raw.get("media")
            if isinstance(media, int) and not isinstance(media, bool):
                alt = raw.get("alt")
                size = raw.get("size")
                cell = {
                    "kind": "image",
                    "media": media,
                    # isinstance-guarded: str(alt) would store the literal "None".
                    "alt": alt[:255] if isinstance(alt, str) else "",
                    "size": (
                        size
                        if size in TableElement.CellImageSize.values
                        else TableElement.DEFAULT_CELL_IMAGE_SIZE
                    ),
                    "halign": halign,
                    "valign": valign,
                }
            else:
                # Invalid/missing media -> an empty TEXT cell with NO `kind` key.
                # Never raise, never render a broken <img>.
                cell = {"html": "", "halign": halign, "valign": valign}
        else:
            cell = {"html": raw.get("html") or "", "halign": halign, "valign": valign}
        # Optional fields, present only when set (imported spanning tables), and
        # applied to BOTH branches: a header image cell and a spanning image cell
        # are both reachable.
        if raw.get("header"):
            cell["header"] = True
        for key in ("colspan", "rowspan"):
            span = TableElement._span(raw, key)
            if span is not None:
                cell[key] = span
        return cell
```

- [ ] **Step 5: Add the image skip to `TableElement._sanitized_data`**

In `TableElement._sanitized_data`, replace the inner cell loop:

```python
                for cell in row:
                    if not isinstance(cell, dict):
                        continue
                    if cell.get("kind") == "image":
                        alt = cell.get("alt")
                        # Defensive form, and the 255 bound must be enforced HERE
                        # too: save() calls only _sanitized_data, never
                        # normalize_data, so a bound in _cell alone does not make
                        # "truncated at save" true.
                        cell["alt"] = alt.strip()[:255] if isinstance(alt, str) else ""
                        # leave `media`/`size` untouched; write NO html key
                    else:
                        cell["html"] = sanitize_cell(cell.get("html", ""))
```

Update the docstring's first line from "Sanitise every cell's html in place" to "Sanitise text cells' html and trim image cells' alt, in place".

- [ ] **Step 6: Add `size` to `FillTableElement._cell`'s image branch**

In `FillTableElement._cell`'s `elif raw.get("kind") == "image":` branch, inside the valid-media arm, add `size` and bound `alt`:

```python
                alt = raw.get("alt")
                size = raw.get("size")
                cell = {
                    "kind": "image",
                    "media": media,
                    "alt": alt[:255] if isinstance(alt, str) else "",
                    "size": (
                        size
                        if size in TableElement.CellImageSize.values
                        else TableElement.DEFAULT_CELL_IMAGE_SIZE
                    ),
                    "halign": halign,
                    "valign": valign,
                }
```

- [ ] **Step 7: Bound `alt` in `FillTableElement._sanitized_data`**

Change its image branch's alt line to match the plain table's:

```python
                        cell["alt"] = alt.strip()[:255] if isinstance(alt, str) else ""
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_table_cell_images.py -v`
Run: `uv run ruff check courses/models.py tests/test_table_cell_images.py`
Expected: PASS.

- [ ] **Step 9: Falsify — delete the guard, require RED**

Temporarily change `_cell`'s alt line to `str(alt)[:255]` and re-run
`uv run pytest tests/test_table_cell_images.py::test_non_string_alt_never_becomes_the_literal_None -v`.
Expected: FAIL (stores `"{'a': 1}"`). Restore the guarded form.

Then temporarily remove the `size` key from `_cell`'s image branch and re-run
`uv run pytest tests/test_table_cell_images.py::test_size_is_always_written_on_an_image_cell -v`.
Expected: FAIL with `KeyError: 'size'`. Restore it.

- [ ] **Step 10: Run the neighbouring model suites**

Run: `uv run pytest tests/test_table_render.py tests/test_spanning_roundtrip.py tests/test_filltable_render.py -v`
Expected: PASS — text-cell normalisation is unchanged.

- [ ] **Step 11: Update the stale class docstring**

`TableElement`'s class docstring says "a JSON grid of **{html, halign, valign} cells**". Change to:

```python
    """Styled table: a JSON grid of cells plus header toggles and a border preset.
    A cell is either TEXT ({html, halign, valign}) or an IMAGE
    ({kind:"image", media, alt, size, halign, valign}); `kind` appears only on
    image cells, so text cells serialize byte-identically to before slice C2.
    Text html is sanitised and image alt trimmed at save()."""
```

- [ ] **Step 11b: Fix the `recolour` stale comment**

`courses/recolour/dbscan.py:126` reads "TableElement cells carry no `kind` at all, so the
guard is a no-op there" - false the moment this task ships, and the guard
(`if cell.get("kind") not in (None, "static"): continue`) becomes live for image cells.
No behavioural change is needed there; only the comment. Nothing reddens on it and the
branch gate cannot see a stale comment, so it needs its own step and its own `git add`.

- [ ] **Step 12: Commit**

```bash
git add courses/models.py courses/recolour/dbscan.py tests/test_table_cell_images.py
git commit -m "feat(table-cell-images): image cell shape and size tokens on both table models"
```

---

## Task 2: Shared image resolver, per-model delegators, and span preservation

**Files:**
- Create: `courses/tablecells.py`
- Modify: `courses/models.py` (`FillTableElement.resolve_image_cells`, `TableElement.resolve_image_cells`, `TableElement.resolved_cells`, `TableElement.render`)
- Modify: `tests/test_filltable_editor_partial.py` (invert + rename the span test)
- Test: `tests/test_table_cell_images.py` (append)

**Interfaces:**
- Consumes: Task 1's `TableElement.CellImageSize`, the `kind:"image"` cell shape.
- Produces: `courses.tablecells.resolve_image_cells(cells, *, empty_cell, course=None) -> list[list[dict]]`; `TableElement.resolve_image_cells(cells, course=None)` and `FillTableElement.resolve_image_cells(cells, course=None)` (both `@staticmethod`, both keeping that exact signature); `TableElement.resolved_cells` property.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_cell_images.py` (**move the import into the file's top import
block, not here** - a module-level import after a function definition is `E402`):

```python
from courses import tablecells


def test_resolver_preserves_header_and_spans_on_an_unresolvable_pk():
    """INVERTS the old fill-table behaviour: export already carried spans through
    both branches ("losing the image must not silently un-span the cell"), so
    render now agrees with export."""
    cells = [[{"kind": "image", "media": 999999, "alt": "", "size": "full",
               "halign": "center", "valign": "middle",
               "header": True, "colspan": 2, "rowspan": 3}]]
    out = TableElement.resolve_image_cells(cells)
    cell = out[0][0]
    assert cell == {"html": "", "halign": "center", "valign": "middle",
                    "header": True, "colspan": 2, "rowspan": 3}
    assert "kind" not in cell


def test_filltable_resolver_preserves_spans_with_its_own_fallback_shape():
    cells = [[{"kind": "image", "media": 999999, "alt": "", "size": "full",
               "halign": "left", "valign": "top", "colspan": 2}]]
    cell = FillTableElement.resolve_image_cells(cells)[0][0]
    assert cell == {"kind": "static", "html": "", "halign": "left",
                    "valign": "top", "colspan": 2}


def test_resolver_defaults_alignment_on_a_cell_missing_those_keys():
    cell = TableElement.resolve_image_cells(
        [[{"kind": "image", "media": 999999}]]
    )[0][0]
    assert cell == {"html": "", "halign": "left", "valign": "top"}


def test_resolver_survives_an_image_cell_with_no_media_and_a_non_dict_cell():
    """Both are unreachable through today's callers (all normalise first), but the
    resolver keeps _ser_table's defensive posture rather than asserting a property the
    code does not have: a bare c["media"] would KeyError and 500 a lesson render."""
    out = TableElement.resolve_image_cells(
        [[{"kind": "image"}, "not-a-dict", {"html": "x"}]]
    )
    assert out[0][0] == {"html": "", "halign": "left", "valign": "top"}
    assert out[0][1] == "not-a-dict"
    assert out[0][2] == {"html": "x"}


def test_the_helper_actually_calls_the_injected_empty_cell():
    """One definition of the unresolved-asset behaviour, injected shape aside.

    Assert on the parsed AST, not a substring of the source: inspect.getsource includes
    the docstring, and the mandated docstring contains the literal `empty_cell(cell)` - so
    a substring check passes even if the body never calls the callable. Same trap as
    test_tablecells_has_no_module_level_imports guards against.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(tablecells.resolve_image_cells).lstrip())
    calls = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "empty_cell" in calls


def test_tablecells_has_no_module_level_imports():
    """A module-level MediaAsset import would be a circular import at app load.

    Assert on the parsed IMPORT NODES, not the bare identifier: the module docstring
    names MediaAsset twice, so `"MediaAsset" not in head` would fail against the
    CORRECT implementation. That is this repo's recorded "comments can fail tests"
    trap, and it has already bitten a source-scanning test here before.
    """
    import ast
    import pathlib

    src = pathlib.Path(tablecells.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))] == []


@pytest.mark.django_db
def test_resolved_cells_replaces_the_pk_with_the_asset(course_with_image):
    """Resolution only. The RENDER assertions belong to Task 4: at this point
    tableelement.html still emits {{ cell.html|safe }} on all five branches, and an
    image cell has no `html` key, so el.render() is empty and any
    `asset.file.url in html` assertion is impossible until _table_cell.html exists."""
    _course, asset = course_with_image
    el = TableElement.objects.create(data=TableElement.normalize_data(
        _data({"kind": "image", "media": asset.pk, "alt": "graph"})
    ))
    assert el.resolved_cells[0][0]["media"] == asset


@pytest.mark.django_db
def test_resolved_cells_can_be_merged_into_the_data_context(course_with_image):
    """The SHAPE render() must build: resolved cells INSIDE `data`, not replacing the
    context - the template reads data.border / data.header_row / data.cells, so a bare
    {**normalize_data(...), "cells": ...} as the whole context would leave data.border
    empty and drop the header attributes.

    This is a shape check on the dict, NOT a pin on render() itself: it does not call
    el.render(), so leaving render() passing normalize_data(self.data) straight through
    keeps it green. The behavioural falsifier for Step 6 is Task 4's
    test_image_cell_renders_the_asset_with_preset_class_and_zoom_hook, which cannot exist
    until _table_cell.html does.
    """
    _course, asset = course_with_image
    el = TableElement.objects.create(data=TableElement.normalize_data(
        _data({"kind": "image", "media": asset.pk, "alt": "graph"})
    ))
    data = el.normalize_data(el.data)
    ctx_cells = {**data, "cells": el.resolved_cells}
    assert ctx_cells["border"] == "grid"          # top-level keys survive
    assert ctx_cells["cells"][0][0]["media"] == asset
```

**Put this fixture in `tests/conftest.py`, not in the test module.** Tasks 3 and 4 both
need it, and a module-local fixture is invisible to them — `tests/test_table_render.py`
would error with `fixture 'course_with_image' not found`. Verified: it is not in any
existing `conftest.py`, so this slice adds it.

```python
# tests/conftest.py
@pytest.fixture
def course_with_image(db, tmp_path, settings):
    """A Course plus one real IMAGE MediaAsset with a readable file on disk.

    MEDIA_ROOT is redirected per test: make_image_asset writes a real file, and a
    render asserting on file.url needs it resolvable.
    """
    from tests.factories import make_course, make_image_asset

    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    return course, make_image_asset(course, filename="graph.png", size=(1586, 612))
```

`tests/factories.py` provides `make_course`, `make_image_asset(course, filename=…,
size=…, color=…)` and `MediaAssetFactory`. Use those throughout this plan — never
`Course.objects.create`, whose required fields a hand-written fixture will guess wrong.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_cell_images.py -v -k "resolver or resolved_cells or tablecells or empty_cell"`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.tablecells'`.

- [ ] **Step 3: Create the shared helper**

Create `courses/tablecells.py`:

```python
"""Shared image-cell resolution for TableElement and FillTableElement.

Both models replace an image cell's `media` int pk with its MediaAsset for
rendering, with the same unresolved-asset fallback. They differ ONLY in the shape
of the replacement cell, so that shape is injected via `empty_cell` and there is
exactly ONE definition of the behaviour. This is single-definition-BY-CONSTRUCTION
rather than by test: tests/test_editor_twin_drift.py guards the two JS editors and
has no visibility into Python, so nothing would catch a copy-paste divergence here.
"""


def resolve_image_cells(cells, *, empty_cell, course=None):
    """`cells` with each image cell's int `media` pk replaced by its MediaAsset.

    One `in_bulk` pass. An unresolved pk degrades to `empty_cell(cell)` with the
    cell's `header`/`colspan`/`rowspan` CARRIED THROUGH — a dangling asset must
    never 500 a lesson, and must never silently un-span a cell and shift the grid
    (which is what `_ser_fill_table` has always done on the export side).

    `empty_cell` is a callable taking the original cell and returning only the
    model-specific BASE shape; carrying the span keys is this function's job, not
    the caller's — otherwise each caller would reimplement it and diverge.

    `course` scopes the lookup to that course's IMAGE assets, matching what
    clean_data validates. The editor passes it (it resolves author-submitted pks
    on a rejected save); the student render does not (its data already passed
    clean_data). An out-of-scope pk simply fails to resolve and takes the same
    fallback — no second branch, no second shape.

    MediaAsset is imported INSIDE the function so this module stays importable from
    `courses/models.py` at MODULE scope. Today the two delegators import `tablecells`
    function-locally, so a module-level `from courses.models import MediaAsset` would in
    fact resolve - but the guard is what keeps that refactor safe, and it is the same
    function-local pattern `_ser_fill_table` uses for the identical symbol.
    """
    from courses.models import MediaAsset

    # .get, not subscripting, and the same isinstance shape _ser_table uses: a stored
    # {"kind": "image"} with no `media` is reachable by this spec's own defensive
    # argument, and a KeyError here would 500 a lesson render.
    ids = [
        c["media"]
        for row in cells
        for c in row
        if isinstance(c, dict)
        and c.get("kind") == "image"
        and isinstance(c.get("media"), int)
        and not isinstance(c.get("media"), bool)
    ]
    if not ids:
        assets = {}
    elif course is None:
        assets = MediaAsset.objects.in_bulk(ids)
    else:
        assets = MediaAsset.objects.filter(
            course=course, kind="image", pk__in=ids
        ).in_bulk()

    out = []
    for row in cells:
        out_row = []
        for c in row:
            if not isinstance(c, dict) or c.get("kind") != "image":
                out_row.append(c)
                continue
            asset = assets.get(c.get("media"))
            if asset is not None:
                out_row.append({**c, "media": asset})
                continue
            fallback = empty_cell(c)
            for key in ("header", "colspan", "rowspan"):
                if key in c:
                    fallback[key] = c[key]
            out_row.append(fallback)
        out.append(out_row)
    return out
```

- [ ] **Step 4: Replace `FillTableElement.resolve_image_cells` with a delegator**

Replace the whole existing method body with:

```python
    @staticmethod
    def resolve_image_cells(cells, course=None):
        """Delegates to the shared resolver, supplying this model's fallback shape.

        Signature kept EXACTLY as before — (cells, course=None), no `empty_cell` —
        because two live call sites depend on it: resolved_cells below and
        FillTableElementForm.resolved_grid_cells in element_forms.py.

        The unresolved-asset fallback now PRESERVES header/colspan/rowspan
        (slice C2), making render agree with _ser_fill_table's export, which has
        always carried them through both branches.
        """
        from courses import tablecells

        return tablecells.resolve_image_cells(
            cells,
            empty_cell=lambda c: {
                "kind": FillTableElement.STATIC,
                "html": "",
                "halign": c.get("halign", "left"),
                "valign": c.get("valign", "top"),
            },
            course=course,
        )
```

Import module-qualified (`from courses import tablecells`), not `from courses.tablecells import resolve_image_cells` — a bare same-named call inside a same-named staticmethod reads like accidental recursion.

- [ ] **Step 5: Add `TableElement.resolve_image_cells` and `resolved_cells`**

In `class TableElement`, after `normalized_data`:

```python
    @staticmethod
    def resolve_image_cells(cells, course=None):
        """Delegates to the shared resolver with the PLAIN table's fallback shape:
        an empty TEXT cell carrying NO `kind` key (the fill table's is
        kind:"static"). One delegator per model means one `empty_cell` per model —
        without it, resolved_cells and TableElementForm.resolved_grid_cells would
        each need their own lambda and could diverge with no Python-side guard."""
        from courses import tablecells

        return tablecells.resolve_image_cells(
            cells,
            empty_cell=lambda c: {
                "html": "",
                "halign": c.get("halign", "left"),
                "valign": c.get("valign", "top"),
            },
            course=course,
        )

    @property
    def resolved_cells(self):
        """The normalized grid with each image cell's `media` pk replaced by its
        MediaAsset. Resolution is a RENDER-time concern: `normalized_data` stays
        unresolved."""
        cells = self.normalize_data(self.data)["cells"]
        return self.resolve_image_cells(cells)
```

- [ ] **Step 6: Make `render()` use it**

`TableElement.render` currently passes `normalize_data(self.data)` straight through, so `cell.media` stays an int and the template would emit `src=""`. Change to:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        data = self.normalize_data(self.data)
        # The resolved cells go INSIDE the existing `data` key — the template reads
        # data.border / data.header_row / data.cells. Replacing the whole context
        # would leave data.border empty and drop the header attributes.
        return render_to_string(
            "courses/elements/tableelement.html",
            {"el": self, "data": {**data, "cells": self.resolved_cells}},
        )
```

This normalises twice per render (once here, once inside `resolved_cells`). Accepted: it mirrors the existing `FillTableElement.render` shape, and the editor render already pays the same double cost because `grid_data` is an uncached property.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_table_cell_images.py -v`
Expected: PASS.

- [ ] **Step 8: Invert and RENAME the span-drop test**

In `tests/test_filltable_editor_partial.py`, the test
`test_unresolvable_image_cell_drops_spans_in_both_render_and_editor` asserts the
behaviour this slice inverts, **and its name would lie**. Rename it to
`test_unresolvable_image_cell_keeps_spans_in_both_render_and_editor`, flip its
assertions to expect `colspan`/`rowspan`/`header` present, and replace its
docstring (which currently argues "a spanning gap left un-spanned would misshape
the grid") with:

```python
    """An unresolvable image cell keeps its header/colspan/rowspan (slice C2).

    Inverted from the original drop-spans behaviour: _ser_fill_table has always
    carried these through BOTH branches, with the comment "losing the image must
    not silently un-span the cell and shift the grid". Export and render
    disagreed; render now agrees with export. Neither layout was measured — this
    is decided on consistency with export plus the fact that 15 of 312 tables
    span, so the case is live.
    """
```

- [ ] **Step 9: Update the two stale docstrings**

The span-dropping rationale is asserted in prose in two more places, and no test
reads them:
- `FillTableElement.resolve_image_cells`'s docstring — already replaced in Step 4.
- `FillTableElementForm.resolved_grid_cells`'s docstring in `courses/element_forms.py`
  repeats "it drops any colspan/rowspan/header the cell carried, same as the
  model". Change that clause to "it PRESERVES any colspan/rowspan/header the cell
  carried, same as the model (slice C2)".

- [ ] **Step 10: Run the affected suites**

Run: `uv run pytest tests/test_filltable_editor_partial.py tests/test_filltable_render.py tests/test_table_render.py -v`
Expected: PASS.

- [ ] **Step 11: Falsify — require RED**

Temporarily delete the `for key in ("header", "colspan", "rowspan")` loop from
`courses/tablecells.py` and run
`uv run pytest tests/test_table_cell_images.py::test_resolver_preserves_header_and_spans_on_an_unresolvable_pk tests/test_filltable_editor_partial.py -v`.
Expected: FAIL in both. Restore the loop.

**Step 6 (`render()` using `resolved_cells`) has NO falsifier in this task**, and that is
stated rather than papered over: every test here operates on `resolved_cells` directly, and
a render-level assertion is impossible until `_table_cell.html` exists. Its falsifier is
Task 4's `test_image_cell_renders_the_asset_with_preset_class_and_zoom_hook` — revert
Step 6 there and that test goes RED (`src=""`, no `cell-img` class). Note it in Task 4's
falsification step as a fourth mutant.

- [ ] **Step 12: Commit**

```bash
git add courses/tablecells.py courses/models.py courses/element_forms.py \
        tests/conftest.py \
        tests/test_table_cell_images.py tests/test_filltable_editor_partial.py
git commit -m "feat(table-cell-images): shared image-cell resolver preserving spans"
```

---

## Task 3: Form course-scoping and the rejected-save re-render

**Files:**
- Modify: `courses/element_forms.py` (`TableElementForm`, `FillTableElementForm`)
- Modify: `courses/builder.py` (the `course=`-threading type-key tuple)
- Test: `tests/test_table_cell_image_form.py` (create)

**Interfaces:**
- Consumes: `TableElement.resolve_image_cells`, `TableElement.CellImageSize`.
- Produces: `TableElementForm(course=...)` accepted; `TableElementForm.resolved_grid_cells`; `form.cell_image_sizes` on both table forms (returns `TableElement.CellImageSize.choices`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_table_cell_image_form.py`:

```python
"""Form-layer tests for table cell images: course scoping and re-render."""

import json

import pytest

from courses.element_forms import TableElementForm
from courses.models import MediaAsset, TableElement


def _payload(media_pk, **cell):
    return {"data": json.dumps({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": media_pk,
                    "alt": "", "size": "medium", **cell}]],
    })}


@pytest.mark.django_db
def test_foreign_course_pk_is_rejected(course_with_image, other_course_image):
    course, _asset = course_with_image
    form = TableElementForm(data=_payload(other_course_image.pk), course=course)
    assert not form.is_valid()
    assert "not an image in this course" in str(form.errors)


@pytest.mark.django_db
def test_in_course_non_image_asset_is_rejected(course_with_image):
    course, _asset = course_with_image
    video = MediaAsset.objects.create(course=course, kind="video")
    form = TableElementForm(data=_payload(video.pk), course=course)
    assert not form.is_valid()


@pytest.mark.django_db
def test_in_course_image_is_accepted(course_with_image):
    course, asset = course_with_image
    form = TableElementForm(data=_payload(asset.pk), course=course)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["data"]["cells"][0][0]["media"] == asset.pk


@pytest.mark.django_db
def test_image_cell_with_no_media_never_500s(course_with_image):
    """clean_data must normalize BEFORE scoping.

    The fill table's `{c["media"] for ...}` expression is only safe because it runs over
    the NORMALIZED grid (FillTableElementForm.clean_data already binds nd first);
    copying it above the normalise, where TableElementForm still has raw `rows`, would
    KeyError on a crafted POST and 500 the save.
    """
    course, _asset = course_with_image
    payload = {"data": json.dumps({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image"}]],
    })}
    form = TableElementForm(data=payload, course=course)
    form.is_valid()  # must not raise


@pytest.mark.django_db
def test_resolved_grid_cells_resolves_a_rejected_save(course_with_image):
    course, asset = course_with_image
    # colspan 99 is out of range -> the form rejects, and the editor re-renders
    # the SUBMITTED grid through resolved_grid_cells.
    form = TableElementForm(data=_payload(asset.pk, colspan=99), course=course)
    assert not form.is_valid()
    cell = form.resolved_grid_cells[0][0]
    assert cell["media"] == asset


@pytest.mark.django_db
def test_resolved_grid_cells_scopes_by_course(course_with_image, other_course_image):
    """A foreign pk resolves to nothing and takes the fallback, NOT a foreign URL.

    Do NOT assert exact cell equality here, and do NOT invalidate via colspan: the
    span is what makes the form invalid, _grid_data then normalizes and CLAMPS it to
    MAX_COLS=20, and Task 2's resolver deliberately CARRIES spans onto the fallback —
    so the real cell is {..., "colspan": 20} and an exact match fails.
    """
    course, _asset = course_with_image
    form = TableElementForm(data=_payload(other_course_image.pk, colspan=99),
                            course=course)
    assert not form.is_valid()
    cell = form.resolved_grid_cells[0][0]
    assert cell["html"] == ""
    assert "kind" not in cell
    assert cell["colspan"] == 20          # clamped by normalize_data, carried by the resolver


def test_form_exposes_the_ordered_size_choices():
    assert TableElementForm().cell_image_sizes == TableElement.CellImageSize.choices


def test_builder_threads_course_for_table():
    """Without "table" in the tuple, self.course stays None on the SAVE path, the
    guard `if img_ids and self.course is not None` becomes a check that NEVER fires,
    and a crafted POST can attach a foreign course's asset with every test green."""
    from courses.builder import COURSE_SCOPED_TYPE_KEYS

    assert "table" in COURSE_SCOPED_TYPE_KEYS
    # filltable is deliberately absent from views_manage's two tuples; table
    # follows it, so this constant is the ONLY place "table" is added.
    assert "filltable" in COURSE_SCOPED_TYPE_KEYS
```

Add **only** `other_course_image` - `course_with_image` comes from `tests/conftest.py`
(added in Task 2). Re-declaring it module-locally would shadow the shared one, so this
module would silently use a different asset and a later edit to the conftest version would
not reach these tests.

```python
@pytest.fixture
def other_course_image(db, tmp_path, settings):
    """An image asset belonging to a DIFFERENT course — the crafted-POST case."""
    from tests.factories import make_course, make_image_asset

    settings.MEDIA_ROOT = str(tmp_path)
    return make_image_asset(make_course(), filename="foreign.png")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_cell_image_form.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'course'` (`TableElementForm` is a plain `ModelForm` today).

- [ ] **Step 3: Make `TableElementForm` course-scoped**

In `courses/element_forms.py`:

**Change only the base class and add `media_kind`. KEEP the existing `__init__`
verbatim** — it sets `self.fields["data"].required = False`, and its own comment
explains why: `JSONField(default=dict)` yields a `required=True` form field and
Django's `EMPTY_VALUES` includes `{}`, so the "add a table, Save without editing" flow
(whose hidden field is `""` because the JS does not serialize on init) would fail
"This field is required" **before `clean_data` runs**. Drop it and that flow breaks and
`clean_data`'s empty-grid branch becomes unreachable.

```python
class TableElementForm(_CourseScopedMediaForm):   # was: forms.ModelForm
    """Styled table. Image cells carry a `media` id that is course-scoped against
    the referenced image in clean_data (mirrors FillTableElementForm — the same
    author-submitted-pk risk)."""

    media_kind = "image"                          # NEW

    class Meta:
        model = TableElement
        fields = ["data"]

    def __init__(self, *args, **kwargs):
        # UNCHANGED — keep this method and its full comment exactly as it is today.
        super().__init__(*args, **kwargs)
        self.fields["data"].required = False
```

`_CourseScopedMediaForm.__init__` accepts `course=None` and gates its queryset
narrowing on `"media" in self.fields`, so a `fields = ["data"]` form subclasses
cleanly — and `super().__init__(*args, **kwargs)` above now routes through it, which is
what makes `self.course` exist.

- [ ] **Step 4: Add the scoping guard to `clean_data`**

`TableElementForm.clean_data` works on the **raw** submitted `rows` throughout and
normalises only in its `return`. Bind the normalised grid first, scope over it,
and return it — one normalise, not two:

```python
        # (existing structural checks stay exactly as they are, operating on `rows`)
        nd = TableElement.normalize_data(data)
        # Course-scope image cells (mirrors FillTableElementForm). Scoping over the
        # NORMALIZED cells is load-bearing: over raw rows, a crafted
        # {"kind": "image"} with no `media` would KeyError and 500 the save.
        cells = nd["cells"]
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

Leave the early `return TableElement.normalize_data({})` branch (empty/no-cells)
**untouched** — it must not be routed through the guard.

- [ ] **Step 5: Thread `course=` from the builder**

In `courses/builder.py`, find the hard-coded type-key tuple
`("image", "video", "gallery", "filltable")` that decides which element forms get
`course=course`. Extract it to a module-level constant so a test can read it, and
add `"table"`:

```python
# Type keys whose element form takes course= (it re-validates a submitted
# MediaAsset pk against the course). "table" joins in slice C2: without it,
# TableElementForm.self.course stays None on the SAVE path, the guard pattern
# `if img_ids and self.course is not None` becomes a check that NEVER fires, and a
# crafted POST can attach a foreign course's asset with every test still green.
COURSE_SCOPED_TYPE_KEYS = ("image", "video", "gallery", "filltable", "table")
```

Use the constant at the call site. Do **not** touch either of the two
`("image", "video", "dragtoimagequestion", "gallery")` tuples in
`courses/views_manage.py` — `filltable` is deliberately absent from those, and
`table` follows it. Consequence, matching existing fill-table behaviour: on the
`views_manage` GET render path `self.course` is `None`, so `resolved_grid_cells`
resolves **unscoped** against already-validated stored data. Acceptable — scoping
is a save-time guard.

- [ ] **Step 6: Add `resolved_grid_cells` and `cell_image_sizes`**

In `TableElementForm`:

```python
    @property
    def resolved_grid_cells(self):
        """grid_data's cells with image pks resolved to MediaAsset, so a rejected
        save re-renders the SUBMITTED grid with real image URLs.

        Sanitisation is INHERITED from _grid_data (which returns
        _sanitized_data(normalize_data(parsed)) on the bound-invalid branch) — do
        NOT add a second pass; that path is where a self-XSS was caught during the
        spanning-table work, so the test here is a regression pin on behaviour that
        already holds."""
        return TableElement.resolve_image_cells(
            self.grid_data["cells"], course=self.course
        )

    @property
    def cell_image_sizes(self):
        """Ordered (value, label) pairs for the size <select>. The forms otherwise
        expose only `data`, so the template needs this hook."""
        return TableElement.CellImageSize.choices
```

Add the same `cell_image_sizes` property to `FillTableElementForm`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_table_cell_image_form.py -v`
Run: `uv run ruff check courses/element_forms.py courses/builder.py tests/test_table_cell_image_form.py`
Expected: PASS.

- [ ] **Step 8: Falsify — require RED**

Remove `"table"` from `COURSE_SCOPED_TYPE_KEYS` and run
`uv run pytest tests/test_table_cell_image_form.py::test_builder_threads_course_for_table -v`.
Expected: FAIL. Restore it.

Then mutate the ordering as a **two-line edit** — change `cells = nd["cells"]` to
`cells = rows`, and move the `nd = TableElement.normalize_data(data)` assignment into
the `return` — and run
`uv run pytest tests/test_table_cell_image_form.py::test_image_cell_with_no_media_never_500s -v`.
Expected: FAIL with `KeyError: 'media'`. Moving only the `nd = …` line instead would
leave `cells = nd["cells"]` referencing an unbound name, raising
`UnboundLocalError` on *every* call and reddening all six tests in the module rather
than isolating the ordering invariant. Restore both lines.

- [ ] **Step 9: Run the neighbouring form suites**

Run: `uv run pytest tests/test_filltable_form.py tests/test_table_form.py tests/test_spanning_roundtrip.py -v`
(skip any that do not exist)
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add courses/element_forms.py courses/builder.py tests/test_table_cell_image_form.py
git commit -m "feat(table-cell-images): course-scope table image cells at save time"
```

---

## Task 4: Student cell partial and the CSS size scale

**Files:**
- Create: `templates/courses/elements/_table_cell.html`
- Modify: `templates/courses/elements/tableelement.html`
- Modify: `templates/courses/elements/_filltable_cell.html`
- Modify: `courses/static/courses/css/courses.css`
- Test: `tests/test_table_render.py` (append), `tests/test_table_css.py` (append)

**Interfaces:**
- Consumes: `TableElement.resolved_cells` (cells whose `media` is a `MediaAsset`).
- Produces: student markup `<img class="cell-img cell-img--<size>" … data-zoomable>` in both table families; CSS classes `.cell-img`, `.cell-img--small|medium|large|full`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_render.py`:

```python
def test_image_cell_renders_the_asset_with_preset_class_and_zoom_hook(
    course_with_image,
):
    from courses.models import TableElement

    course, asset = course_with_image
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "a graph",
                    "size": "medium"}]],
    }))
    html = el.render()
    assert 'class="cell-img cell-img--medium"' in html
    assert f'src="{asset.file.url}"' in html
    assert 'alt="a graph"' in html
    assert "data-zoomable" in html


def test_partial_defaults_size_when_the_key_is_absent(course_with_image):
    """|default:'full' — a bare {{ cell.size }} yields `cell-img--`, which matches no
    rule, and nothing else caps the image once max-width leaves the base.

    Rendered at the PARTIAL level with a context that has no `size` key at all. Going
    through el.render() cannot falsify the mutant: render() calls normalize_data,
    which materialises size:"full", so `cell.size` is always populated at the template
    and the output is `cell-img--full` with or without the filter. (This is the shape
    tests/test_imagezoom_render.py already uses for _filltable_cell.html.)
    """
    from django.template.loader import render_to_string

    _course, asset = course_with_image
    html = render_to_string(
        "courses/elements/_table_cell.html",
        {"cell": {"kind": "image", "media": asset, "alt": ""}},
    )
    assert "cell-img--full" in html
    assert "cell-img--\"" not in html
    assert "cell-img-- " not in html


def test_text_cell_bytes_are_unchanged_by_the_partial_factoring(db):
    """The mutant: a trailing newline or a leading indent in _table_cell.html.
    {% spaceless %} strips whitespace only BETWEEN tags, so whitespace adjacent to
    TEXT survives and changes rendered bytes for all 7,246 existing cells.
    The cell MUST be non-empty: with html:"" the include emits only its newline and
    `<td>\\n</td>` collapses to `<td></td>`, so an empty fixture cannot falsify."""
    from courses.models import TableElement

    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"html": "cell text", "halign": "center", "valign": "top"}]],
    }))
    assert '<td class="ta-center va-top">cell text</td>' in el.render()


def test_header_cell_bytes_are_unchanged_too(db):
    """Four of the five branches are <th>; a rule phrased only for <td> leaves a
    header-row table's bytes unpinned."""
    from courses.models import TableElement

    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": True, "header_col": False, "border": "grid",
        "cells": [[{"html": "head text", "halign": "left", "valign": "top"}]],
    }))
    assert '<th scope="col" class="ta-left va-top">head text</th>' in el.render()


def test_table_cell_partial_has_no_trailing_newline():
    """Byte-level: an editor will silently re-add one."""
    import pathlib

    from django.conf import settings

    p = pathlib.Path(settings.BASE_DIR) / "templates/courses/elements/_table_cell.html"
    assert p.read_bytes()[-1:] not in (b"\n", b"\r")
```

Append to `tests/test_table_css.py`:

```python
def test_courses_css_defines_the_cell_image_scale():
    # Comments STRIPPED first, same as the sibling test below: the explanatory comment
    # this slice adds names `.cell-img--medium` (to record the equal-specificity trap),
    # so an unstripped boundary-anchored search is satisfied by the comment and the
    # medium entry cannot fail even with its rule deleted. Medium is the one preset with
    # e2e coverage, i.e. the entry least likely to be caught elsewhere.
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS.read_text(encoding="utf-8"))
    # Naming: every class is present, boundary-anchored on BOTH sides so
    # `.cell-img` is not satisfied by `.cell-img--small`.
    for cls in ["cell-img", "cell-img--small", "cell-img--medium",
                "cell-img--large", "cell-img--full"]:
        assert re.search(rf"(?<![\w-])\.{re.escape(cls)}(?![\w-])", css), cls
    # Existence: the BASE RULE itself, not just the name. `.ta-center > .cell-img`
    # satisfies the naming check with the base rule entirely absent.
    assert re.search(r"^\.cell-img\s*\{", css, re.M)


def test_filltable_img_rule_is_deleted_not_merely_reduced():
    """The decision is deletion — a no-op stub invites re-adding max-width and
    re-opens the equal-specificity trap. The CLASS stays on the element."""
    # Comments are STRIPPED first: the explanatory comment this slice adds names
    # `.filltable__img` to record why it went, and a boundary-anchored regex would
    # match inside it, failing against the exact CSS this plan mandates.
    css = re.sub(r"/\*[\s\S]*?\*/", "", CSS.read_text(encoding="utf-8"))
    assert not re.search(r"(?<![\w-])\.filltable__img(?![\w-])", css)


def test_print_block_follows_the_preset_block():
    """@media print adds no specificity, so ordering is what makes it win.

    Anchor on the NEW rule. `170mm` already appears twice in courses.css — a comment
    near line 96 and C1's `.el--image--full img` block near line 107 — both roughly a
    thousand lines BEFORE the region this block lands in, so a bare
    `css.index("170mm")` is false wherever the new block sits.
    """
    css = CSS.read_text(encoding="utf-8")
    m = re.search(r"@media print\s*\{[^}]*\.cell-img--full[^}]*170mm", css, re.S)
    assert m, "no @media print block bounding .cell-img--full at 170mm"
    assert css.index(".cell-img--full") < m.start()
```

Ensure `import re` is present at the top of `tests/test_table_css.py`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_render.py tests/test_table_css.py -v`
Expected: FAIL — the partial does not exist; `.cell-img` is not in `courses.css`.

- [ ] **Step 3: Create the shared cell partial**

Create `templates/courses/elements/_table_cell.html` with **exactly one line and
no terminating newline** (see Step 4 for why):

```
{% if cell.kind == "image" %}<img class="cell-img cell-img--{{ cell.size|default:'full' }}" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}" data-zoomable>{% else %}{{ cell.html|safe }}{% endif %}
```

Two branches only — do **not** copy `_filltable_cell.html`'s three-way shape (it
also handles `kind == "answer"`, which a plain table has no equivalent of). The
`{% else %}` body is exactly `{{ cell.html|safe }}`: no wrapper, no whitespace, no
filter. That is what keeps text-cell bytes identical to the five inline sites it
replaces.

Write it with a tool that does not append a trailing newline, then verify:

```bash
python -c "import pathlib; p=pathlib.Path('templates/courses/elements/_table_cell.html'); print(repr(p.read_bytes()[-30:]))"
```

Expected: ends with `{% endif %}` and **no** `\n` / `\r`.

- [ ] **Step 4: Include it from all five branches of `tableelement.html`**

In `templates/courses/elements/tableelement.html`, replace `{{ cell.html|safe }}`
with `{% include "courses/elements/_table_cell.html" %}` on **all five** branches
(one `<td>`, four `<th>`). The include must sit immediately between `>` and the
closing `</td>` / `</th>` with no whitespace either side.

Add this comment above the `{% for cell in row %}` loop:

```
{% comment %}The cell body is factored into _table_cell.html so the five branches
cannot drift and an image in a header row is handled once. That partial MUST stay
one line with no leading whitespace and no terminating newline, and the include
must sit flush between `>` and `</td>`/`</th>`: {% spaceless %} strips whitespace
only BETWEEN tags, so whitespace adjacent to TEXT survives and would change
rendered bytes for every existing cell. Do NOT take _filltable_cell.html as the
byte-safety precedent — it ends with \r\n, which is harmless there only because
filltableelement.html has no {% spaceless %} at all.{% endcomment %}
```

- [ ] **Step 5: Give the fill-table partial the shared classes**

In `templates/courses/elements/_filltable_cell.html`, change the image branch's
`<img>` to carry the shared carrier alongside its existing class:

```
<img class="filltable__img cell-img cell-img--{{ cell.size|default:'full' }}" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}" data-zoomable>
```

The `filltable__img` **class stays on the element** — `tests/test_filltable_render.py`
asserts its presence (and its absence on the degraded path), and
`tests/test_e2e_imagezoom.py::test_filltable_image_cell_opens_the_overlay` drives
`page.locator(".filltable__img")`. Only the CSS *rule* goes (Step 6).

- [ ] **Step 6: Write the CSS**

In `courses/static/courses/css/courses.css`, **delete** the line
`.filltable__img { max-width: 100%; height: auto; display: block; }` and replace it
with the shared scale. Place this block **after** any rule that could tie with a
single-class modifier:

```css
/* --- Table cell images (slice C2). The scale is FOUR ABSOLUTE SQUARE bounding
   boxes, not percentages: a cell's containing block is content-negotiated, so a
   percentage compounds the instability (MEASURED 5.2x spread across real table
   shapes versus 1.4x for the absolute cap). The `min(100%, Npx)` arm keeps the
   cell a hard ceiling — measured across 32 shape x treatment combinations,
   including phone at 296px, with no horizontal scroll anywhere.

   The BASE RULE DECLARES NO max-width. `.filltable__img` used to declare
   `max-width: 100%`, which ties with a single-class `.cell-img--medium` and would
   silently win by source order, degrading every preset to Full. That rule is
   DELETED rather than reduced — keeping a no-op invites re-adding max-width and
   re-opens the trap. Chromium/Firefox/WebKit agree to within 1px on these rules
   (measured on five shapes); do not re-derive. --- */
.cell-img { height: auto; display: block; }
.cell-img--small  { max-width: min(100%, 80px);  max-height: 80px; }
.cell-img--medium { max-width: min(100%, 160px); max-height: 160px; }
.cell-img--large  { max-width: min(100%, 240px); max-height: 240px; }
.cell-img--full   { max-width: 100%;             max-height: 60dvh; }

/* halign is `text-align` on the <td>, which has NO effect on a display:block
   child. With absolute caps of 80/160/240px inside a 648px column the image is
   almost always narrower than its cell, so it would sit flush left whatever the
   author picks — while the align buttons stay enabled and serialize() faithfully
   writes halign. Margin-driven alignment from the cell's existing class fixes it.
   (`ta-left` is the margin-inline:0 default and needs no rule.) */
.ta-center > .cell-img { margin-inline: auto; }
.ta-right  > .cell-img { margin-inline: auto 0; }

/* dvh not vh, per C1: vh resolves against the toolbar-collapsed viewport, so a vh
   cap can still fall below the fold on a phone. AGGREGATE height is accepted: the
   60dvh bound is per image, so a five-row table of tall `full` images is still
   ~300dvh of scrolling — strictly better than today's unbounded 1287px per cell,
   and the editor-insert default of `medium` keeps new content well clear. */

/* @media print adds NO specificity, so this must come AFTER the preset block.
   Without it a `full` cell image prints at a viewport-relative dvh height.
   Small/Medium/Large are already absolute and need no print counterpart. */
@media print {
  .cell-img--full { max-height: 170mm; }
}

```

**The fill-table EDITOR preview rules are deliberately NOT in this task — they move to
Task 8.** Deleting `.filltable-editor__img { max-width: 120px }` here while its replacement
modifier is only emitted in Task 8 (template Step 3, `setImageCell` Step 5) would leave
**four intermediate commits** in which nothing caps the fill-table editor preview:
`setImageCell` still writes only `img.className = "filltable-editor__img"`, and `reset.css`'s
`img { max-width: 100% }` is a type selector against an auto-layout cell - the very non-bound
this slice exists to retire. Existing e2e cannot catch it (`make_image_asset` defaults to
`size=(1, 1)`), and Task 8 is explicitly designed to be gate-able on its own, so rejecting
Task 8 would ship the regression. **Leave `.filltable-editor__img { max-width: 120px; height:
auto; display: block; }` exactly as it is in this task.**

**Delete the existing `.filltable-editor__img { max-width: 120px; height: auto; display:
block; }` rule outright** (it is one line in `courses.css`, just after `.filltable__img`).
The new base rule above replaces it - stripping only `max-width` from the old rule while
also adding the new one leaves a duplicate no-op rule that nothing catches.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_table_render.py tests/test_table_css.py tests/test_filltable_render.py -v`
Expected: PASS.

- [ ] **Step 8: Falsify — require RED (three mutants)**

1. Append a newline to `_table_cell.html`; run
   `uv run pytest tests/test_table_render.py -k "bytes_are_unchanged or trailing_newline" -v`.
   Expected: FAIL. Remove it.
2. Change the partial's class to `cell-img--{{ cell.size }}` (drop the filter); run
   `uv run pytest tests/test_table_render.py::test_partial_defaults_size_when_the_key_is_absent -v`.
   Expected: FAIL. Restore the filter.
3. Delete the `.cell-img { height: auto; display: block; }` line but keep the four
   modifiers; run `uv run pytest tests/test_table_css.py::test_courses_css_defines_the_cell_image_scale -v`.
   Expected: FAIL on the `re.M` base-rule assertion (the naming assertion alone
   would still pass, via `.ta-center > .cell-img`). Restore it.
4. **Deferred from Task 2**, which has no render-level falsifier: revert
   `TableElement.render` to passing `normalize_data(self.data)` straight through (drop the
   `"cells": self.resolved_cells` merge) and run
   `uv run pytest tests/test_table_render.py::test_image_cell_renders_the_asset_with_preset_class_and_zoom_hook -v`.
   Expected: FAIL - `cell.media` stays an int, so the template emits `src=""` and no
   asset URL appears. Restore the merge.

- [ ] **Step 9: Run the math-reflow and zoom suites**

Run: `uv run pytest tests/test_e2e_math_reflow_dom.py tests/test_imagezoom_render.py -v`
Expected: PASS. Note `test_e2e_math_reflow_dom.py` builds its fixture from a
hand-authored innerHTML string and never renders `tableelement.html`, so it is
**not** the byte guard — the render-level tests in Step 1 are.

- [ ] **Step 10: Commit**

```bash
git add templates/courses/elements/_table_cell.html \
        templates/courses/elements/tableelement.html \
        templates/courses/elements/_filltable_cell.html \
        courses/static/courses/css/courses.css \
        tests/test_table_render.py tests/test_table_css.py
git commit -m "feat(table-cell-images): shared cell partial and absolute size scale"
```

---

## Task 5: Transfer — five sites and the FORMAT_VERSION bump

**Files:**
- Modify: `courses/transfer/schema.py`, `payloads.py`, `export.py`, `importer.py`
- Modify: `tests/test_link_transfer.py`, `tests/test_tabs_transfer.py`, `tests/test_transfer_schema.py`, `courses/tests/test_image_size_transfer.py`, `tests/test_transfer_export.py`, `tests/test_table_transfer.py`
- Test: `tests/test_table_transfer.py` (append)

**Interfaces:**
- Consumes: the `kind:"image"` cell shape, `TableElement.CellImageSize`.
- Produces: `FORMAT_VERSION == 8`; archives whose table cells may carry `kind`/`media`/`alt`/`size`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_transfer.py` (it already imports `SERIALIZERS`, `VALIDATORS`,
`BUILDERS`, `TransferError` and the factories, and sets
`pytestmark = pytest.mark.django_db`). **Move the four imports below into that file's
existing top import block, one per line** - appended module-level imports after a function
definition are `E402`, and `from tests.factories import make_course, make_image_asset`
violates `force-single-line`:

```python
from courses.transfer.export import MediaIdMap
from courses.transfer.export import _element_mids
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import make_course, make_image_asset


# SERIALIZERS values are (model, fn) TUPLES - `SERIALIZERS["table"](...)` raises
# TypeError: 'tuple' object is not callable. Unpack the callable once, exactly as
# tests/test_filltable_transfer.py does (`SERIALIZERS["fill_table"][1](src, ids)`).
_ser_table_fn = SERIALIZERS["table"][1]
_ser_fill_table_fn = SERIALIZERS["fill_table"][1]


def _tbl(cells, **top):
    return {"header_row": False, "header_col": False, "border": "grid",
            "cells": cells, **top}


def _img(media, **kw):
    return {"kind": "image", "media": media, "alt": "", "size": "full",
            "halign": "left", "valign": "top", **kw}


def test_format_version_is_bumped_for_cell_images():
    assert FORMAT_VERSION == 8


def test_ser_table_registers_the_asset_and_emits_a_string_local_id(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk, size="medium")]]))
    )
    out = _ser_table_fn(el, MediaIdMap())
    cell = out["cells"][0][0]
    assert cell["media"] == "m1"          # local STRING id, not the int pk
    assert cell["size"] == "medium"       # the preset survives export
    assert cell["kind"] == "image"


def test_ser_table_does_not_mutate_el_data(tmp_path, settings):
    """dict(el.data) is a SHALLOW copy: assigning cell["media"] in place would
    replace real pks on the in-memory element, and duplicate-unit persists that."""
    settings.MEDIA_ROOT = str(tmp_path)
    asset = make_image_asset(make_course())
    el = TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk)]]))
    )
    _ser_table_fn(el, MediaIdMap())
    assert el.data["cells"][0][0]["media"] == asset.pk


def test_ser_table_survives_ragged_rows_and_non_dict_cells():
    """EXPORT-ONLY fixture: _ser_table must not raise and must not alter these
    bytes. The resulting archive is legitimately NOT importable (_val_table's
    _exact_keys and its non-dict-cell check reject it) — do NOT extend into a
    round-trip, or you will "fix" the validator and widen the import surface."""
    stored = {"cells": [[_cell("a"), "not-a-dict"], "not-a-row", [_cell("b")]]}
    out = _ser_table_fn(TableElement(data=stored), MediaIdMap())
    assert out["cells"][1] == "not-a-row"
    assert out["cells"][0][1] == "not-a-dict"
    assert out["cells"][0][0] == _cell("a")


def test_ser_table_degrades_an_unresolvable_pk_keeping_spans():
    """A cell's media is a bare int in a JSONField with NO FK protection, so a
    dangling pk is reachable and ids.register(assets[pk]) would KeyError, 500ing
    both export and duplicate-unit."""
    el = TableElement(data=_tbl([[_img(999999, colspan=2, header=True)]]))
    cell = _ser_table_fn(el, MediaIdMap())["cells"][0][0]
    assert cell == {"html": "", "halign": "left", "valign": "top",
                    "colspan": 2, "header": True}
    assert "kind" not in cell


def test_ser_table_materialises_size_full_when_absent(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    asset = make_image_asset(make_course())
    el = TableElement(data=_tbl([[{"kind": "image", "media": asset.pk,
                                   "halign": "left", "valign": "top"}]]))
    assert _ser_table_fn(el, MediaIdMap())["cells"][0][0]["size"] == "full"


def test_ser_table_handles_an_image_cell_with_no_media_key():
    """By this spec's own defensive argument, a stored {"kind": "image"} with no
    media is reachable — and subscripting would 500 export AND duplicate-unit."""
    el = TableElement(data=_tbl([[{"kind": "image", "halign": "left"}]]))
    cell = _ser_table_fn(el, MediaIdMap())["cells"][0][0]
    assert cell == {"html": "", "halign": "left", "valign": "top"}


def test_legacy_non_normalized_table_export_bytes_are_unchanged():
    """_ser_table must NOT call normalize_data: save() calls only _sanitized_data,
    so nothing guarantees a stored row is rectangular. Normalizing at export would
    rectangularise and inject defaults, silently altering archive bytes."""
    stored = {"cells": [[{"html": "a"}], [{"html": "b"}, {"html": "c"}]]}
    out = _ser_table_fn(TableElement(data=stored), MediaIdMap())
    assert out == stored            # ragged rows kept, no halign/valign injected
    assert "header_row" not in out  # absent top-level keys NOT invented


def test_element_mids_table_yields_image_local_ids():
    """Mirrors test_element_mids_fill_table_yields_image_local_ids. NOTE the branch
    tests isinstance(..., str): _element_mids runs on ALREADY SERIALIZED data, where
    media is a local string id. An isinstance(..., int) test — the natural guess,
    since the STORED value is a pk — returns [].

    What a missing branch costs is DIAGNOSTICS, not data: document["media"] and the
    zip entries come from media_ids.items(), the registry _ser_table writes via
    ids.register(). This mid list feeds only mid_refs / missing-image reporting."""
    assert list(_element_mids("table", _tbl([[_img("m3"), _cell("x")]]))) == ["m3"]


def test_val_table_accepts_an_image_cell_and_coerces_out_of_enum_size():
    """Coerce, not reject — matching _val_image, for a cosmetic field with a
    lossless default: `full` IS the pre-feature rendering. Scoped to IMAGE cells,
    unlike _val_image's unconditional setdefault (which would write size onto TEXT
    cells). Note this DOES materialise the key on image cells; that is intended."""
    data = _tbl([[_img("m1", size="enormous")]])
    VALIDATORS["table"](data, "el-1", {"m1": "image"})
    assert data["cells"][0][0]["size"] == "full"


def test_val_table_rejects_an_unknown_cell_kind():
    data = _tbl([[{**_img("m1"), "kind": "video"}]])
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "el-1", {"m1": "image"})


def test_val_table_rejects_an_unregistered_or_wrong_kind_media_ref():
    with pytest.raises(TransferError):
        VALIDATORS["table"](_tbl([[_img("m9")]]), "el-1", {"m1": "image"})
    with pytest.raises(TransferError):
        VALIDATORS["table"](_tbl([[_img("m1")]]), "el-1", {"m1": "video"})


def test_a_plain_all_text_table_archive_still_imports():
    """The alt check MUST carry an `is not None` guard: check_str rejects None, and
    the flat allowlist means _val_table walks TEXT cells too, which carry no alt.
    An unconditional check_str fails EVERY pre-feature archive."""
    VALIDATORS["table"](_tbl([[_cell("a"), _cell("b")]]), "el-1", {})


def test_val_table_rejects_an_over_long_alt():
    data = _tbl([[_img("m1", alt="x" * 256)]])
    with pytest.raises(TransferError):
        VALIDATORS["table"](data, "el-1", {"m1": "image"})


def test_build_table_remaps_before_normalizing(tmp_path, settings):
    """ORDERING IS LOAD-BEARING: reversed, the string local id has already failed
    _cell's isinstance(media, int) test and degraded the cell to an empty text cell —
    a silent, total loss of every imported cell image with no error."""
    settings.MEDIA_ROOT = str(tmp_path)
    asset = make_image_asset(make_course())
    el, _children = BUILDERS["table"](_tbl([[_img("m1", size="large")]]),
                                      {"m1": asset})
    cell = el.data["cells"][0][0]
    assert cell["media"] == asset.pk
    assert cell["size"] == "large"


def test_table_image_cell_round_trips_end_to_end(tmp_path, settings):
    """export -> validate -> import preserves the asset AND the preset."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk, size="small")]]))
    )
    payload = _ser_table_fn(el, MediaIdMap())
    VALIDATORS["table"](payload, "el-1", {"m1": "image"})
    rebuilt, _children = BUILDERS["table"](payload, {"m1": asset})
    cell = rebuilt.data["cells"][0][0]
    assert cell["kind"] == "image" and cell["media"] == asset.pk
    assert cell["size"] == "small"


def test_filltable_image_cell_round_trips_size(tmp_path, settings):
    """_ser_fill_table builds an explicit out_cell literal WITHOUT `size`, so
    without this change every fill-table export — and therefore duplicate-unit,
    duplicate-ELEMENT (builder.duplicate_element -> _copy_below runs export
    in-process) and clipboard paste — silently reverts every image cell to `full`."""
    from courses.models import FillTableElement

    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = FillTableElement.objects.create(data=FillTableElement.normalize_data({
        "prompt": "", "case_sensitive": False, "header_row": False,
        "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "size": "large"}]],
    }))
    payload = _ser_fill_table_fn(el, MediaIdMap())
    assert payload["cells"][0][0]["size"] == "large"


def test_out_of_enum_size_is_tolerated_by_val_fill_table():
    """_val_fill_table stays lenient and gains no symmetric rejection — its
    docstring commits it to being "intentionally more lenient than _val_table",
    leaving value-enum drift for normalize_data to repair. The strictness asymmetry
    between the two validators is intentional and pre-existing; do NOT "fix" it."""
    data = {"prompt": "", "case_sensitive": False, "header_row": False,
            "header_col": False, "border": "grid",
            "cells": [[{"kind": "image", "media": "m1", "alt": "",
                        "size": "enormous", "halign": "left", "valign": "top"}]]}
    VALIDATORS["fill_table"](data, "el-1", {"m1": "image"})  # must not raise


def test_a_300_char_alt_survives_the_round_trip(tmp_path, settings):
    """Truncated at save — by _sanitized_data, which is what save() actually calls,
    since save() never normalizes — and never rejected at import."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course)
    el = TableElement(data=_tbl([[{**_img(asset.pk), "alt": "x" * 300}]]))
    el.save()
    assert len(el.data["cells"][0][0]["alt"]) == 255
    payload = _ser_table_fn(el, MediaIdMap())
    VALIDATORS["table"](payload, "el-1", {"m1": "image"})  # must not raise
```

`_cell(html, h, v)` is the helper already defined at the top of this file. Check the
exact keyword names `VALIDATORS["table"]` expects (`data, elid, media_kinds`) against
the neighbouring fill-table tests before running.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_transfer.py -v`
Expected: FAIL — `assert 7 == 8`, and the table image cell is rejected by
`_val_table`'s exact allowlist.

- [ ] **Step 3: Bump `FORMAT_VERSION`**

`courses/transfer/schema.py`: `FORMAT_VERSION = 8`.

- [ ] **Step 4: Widen `_val_table` and add the per-field policy**

In `courses/transfer/payloads.py::_val_table`:

```python
    allowed = {"html", "halign", "valign", "header", "colspan", "rowspan",
               "kind", "media", "alt", "size"}
```

Keep the allowlist **flat** (not partitioned by kind): an archive text cell may
legally carry `media`/`alt`/`size`. That is harmless — `_cell`'s text branch drops
them, and `_element_mids`/`_build_table` key on `kind == "image"`.

Then inside the per-cell loop, after the existing `html` check:

```python
            kind = cell.get("kind")
            if kind is not None and kind != "image":
                _err(_("Element '%(el)s': unknown table cell kind."), el=elid)
            if kind == "image":
                refs |= _require_media(cell.get("media"), elid, media_kinds, "image")
                # Coerce, don't reject: a cosmetic field with a lossless default
                # must never fail an import (_val_image's stated rule). Scoped to
                # IMAGE cells only — _val_image's unconditional setdefault would
                # write `size` onto TEXT cells, which never carry it. Note this
                # DOES materialise the key on image cells (get() returns None on
                # absence, which is not in `values`); that is intended.
                if cell.get("size") not in TableElement.CellImageSize.values:
                    cell["size"] = "full"
            alt = cell.get("alt")
            if alt is not None:
                # `is not None` is mandatory: check_str rejects None, and the flat
                # allowlist means this loop walks TEXT cells too, which carry no
                # alt — an unconditional call fails EVERY pre-feature archive.
                # Bounded at 255 to match the model, which now truncates at both
                # _cell and _sanitized_data, so an authorable table always re-imports.
                check_str(alt, "alt", max_length=255)
```

**Write the `refs` plumbing out in full — a missed `return refs` makes every
table-image archive un-importable, and no test in this task would notice.**
`_val_table` currently ends `return set()`. `courses/transfer/schema.py:326` does
`refs = validate_element_data(el, media_kinds); referenced_media |= refs`, and line 339
then hard-rejects with "Media entry '%(v)s' is not referenced by any element." So a table
whose only media reference is a cell image would fail validation with a confusing error
about an unreferenced media entry. Concretely:

1. `refs = set()` immediately before the per-cell loop (copying the snippet's
   `refs |= …` without this is a bare `NameError`);
2. `refs |= _require_media(cell.get("media"), elid, media_kinds, "image")` inside the
   `kind == "image"` branch, as shown;
3. replace the trailing `return set()` with `return refs`.

**And add an archive-level test**, because every other test in this task calls
`VALIDATORS["table"](...)` directly and so bypasses the caller that consumes the return:

```python
def test_a_table_with_a_cell_image_passes_whole_archive_validation(tmp_path, settings):
    """The `refs` return is observable ONLY from validate_archive_document: it is what
    stops schema.py rejecting the bundled asset as "not referenced by any element".

    Every other test in this task calls VALIDATORS["table"](...) directly and so bypasses
    the caller that consumes the return - which is exactly why a missed `return refs` would
    otherwise ship green.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit")
    asset = make_image_asset(course)
    add_element(unit, TableElement.objects.create(
        data=TableElement.normalize_data(_tbl([[_img(asset.pk, size="medium")]]))
    ))

    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        # Real signature: (zf, manifest, document, media_entries, *, kind,
        # target_course=None) - importer.py:389. A two-arg call TypeErrors, so
        # "must NOT raise" would fail on a correct build.
        validate_archive_document(zf, mani, doc, media, kind="course", target_course=None)
```

Check `write_archive`'s argument list and `ContentNodeFactory`'s `kind`/`unit_type`
defaults against the whole-archive test already in this file (around lines 56-80). `io`, `CourseFactory`, `ContentNodeFactory`, `add_element`,
`write_archive`, `open_archive` and `validate_archive_document` are all already imported
at the top of this module.

Leave `_val_fill_table` untouched — its docstring commits it to being
"intentionally more lenient than `_val_table`", and that asymmetry is pre-existing.

Update `_val_table`'s in-body comment, which now lies: "Unified per-cell shape
check (BOTH branches) … tolerate whatever the model coerces" — the allowlist is now
kind-aware in its *values*.

- [ ] **Step 5: Rewrite `_ser_table`**

Replace `return dict(el.data)` with a defensive walk:

```python
def _ser_table(el, ids):
    # Return the table dict DIRECTLY (not {"data": ...}) — see the original note.
    #
    # Two traps, both specific to this function:
    #  * Do NOT call normalize_data. _ser_fill_table opens with it, but copying
    #    that here would change exported bytes: save() calls only _sanitized_data,
    #    so nothing at the model layer guarantees a stored row is rectangular or
    #    that its cells carry halign/valign/html. Normalizing would rectangularise
    #    and inject defaults, colliding with the byte-identity invariant. (No
    #    SHIPPED path produces such a row today — LAL, seed, import and the form
    #    all normalize — so these guards are defence-in-depth against the missing
    #    model-layer guarantee, not a response to a live producer.)
    #  * dict(el.data) is a SHALLOW copy: row lists and cell dicts are shared with
    #    the live instance, so assigning cell["media"] in place would replace real
    #    pks on the in-memory element and duplicate-unit would persist that.
    #
    # Because the walk sees RAW stored shapes, every key is read with .get and the
    # same defaults the render-side fallback uses.
    from courses.models import MediaAsset

    stored = el.data if isinstance(el.data, dict) else {}
    rows = stored.get("cells")
    if not isinstance(rows, list):
        return dict(stored)

    img_pks = [
        c.get("media")
        for row in rows
        if isinstance(row, list)
        for c in row
        if isinstance(c, dict)
        and c.get("kind") == "image"
        and isinstance(c.get("media"), int)
        and not isinstance(c.get("media"), bool)
    ]
    assets = MediaAsset.objects.in_bulk(img_pks)

    out_rows = []
    for row in rows:
        if not isinstance(row, list):
            out_rows.append(row)
            continue
        out_row = []
        for c in row:
            if not isinstance(c, dict):
                out_row.append(c)
                continue
            if c.get("kind") != "image":
                out_row.append(dict(c))
                continue
            asset = assets.get(c.get("media"))
            if asset is not None:
                out_cell = {
                    "kind": "image",
                    "media": ids.register(asset),
                    "alt": (c.get("alt") or "")[:255],
                    "size": c.get("size") or "full",
                    "halign": c.get("halign", "left"),
                    "valign": c.get("valign", "top"),
                }
            else:
                # Unresolved pk, or a kind:"image" cell whose media is missing or
                # not an int: the table's empty-cell shape, no `kind`.
                out_cell = {
                    "html": "",
                    "halign": c.get("halign", "left"),
                    "valign": c.get("valign", "top"),
                }
            for k in ("header", "colspan", "rowspan"):
                if k in c:
                    out_cell[k] = c[k]
            out_row.append(out_cell)
        out_rows.append(out_row)

    # Reassemble by SHALLOW copy, replacing `cells` only. An explicit five-key
    # literal (as _ser_fill_table uses) would inject header_row/header_col/border
    # defaults into a legacy row that lacks them; an unconditional
    # {**stored, "cells": rows} would append a `cells` key to data that has none.
    out = dict(stored)
    out["cells"] = out_rows
    return out
```

- [ ] **Step 6: Add the `table` branch to `_element_mids`**

In `courses/transfer/export.py::_element_mids`, add before the scalar fallback:

```python
    if type_key == "table":
        return [
            c["media"]
            for row in (data.get("cells") or [])
            for c in (row or [])
            if isinstance(c, dict)
            and c.get("kind") == "image"
            and isinstance(c.get("media"), str)
        ]
```

`isinstance(..., str)` **not `int`**: this runs on the already-serialized data,
after `_ser_table` has replaced pks with local ids.

Update the function's docstring, which says "a fill_table walks its `cells` grid …
**every other** media-bearing type reads the scalar `media`" — `table` now walks
its grid too.

**Consequence, stated so nobody mis-pins it:** a missing branch here does **not**
omit the asset from the zip. `document["media"]` and the zip entries come from
`media_ids.items()` — the registry `_ser_table` writes via `ids.register()` — while
`_element_mids` feeds only `mid_refs`, which drives missing-image reporting. What
breaks without it is the operator warning for a table whose image file is missing
on disk.

- [ ] **Step 7: Add `size` to `_ser_fill_table`'s `out_cell`**

In the resolved-asset arm of `_ser_fill_table`, add `"size": c.get("size") or "full",`
to the `out_cell` literal. Without it every fill-table export — and therefore
duplicate-unit, duplicate-**element** (`builder.duplicate_element` → `_copy_below`
calls `build_element_export` in-process) and **clipboard paste** — silently reverts
every image cell to `full`.

- [ ] **Step 8: Fix `_build_table`'s ordering**

```python
def _build_table(data, assets):
    # ORDERING IS LOAD-BEARING: remap the RAW archive dict FIRST, then normalize.
    # Reversed, the string local id has already failed _cell's isinstance(media,
    # int) test and degraded the cell to an empty text cell — a silent, total loss
    # of every imported cell image with no error.
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
    return _clean_save(TableElement(data=TableElement.normalize_data(data))), ()
```

- [ ] **Step 9: Update the five red `FORMAT_VERSION` assertions and rename two**

An implementer running only `test_table_transfer.py` sees none of these:

- `tests/test_link_transfer.py` — `assert FORMAT_VERSION == 8`, and **rename**
  `test_format_version_is_7` → `test_format_version_is_current`.
- `tests/test_tabs_transfer.py` — same assertion and the same **rename**.
- `tests/test_transfer_schema.py` — `assert FORMAT_VERSION == 8`.
- `courses/tests/test_image_size_transfer.py` — `assert FORMAT_VERSION == 8`
  (its function is already version-agnostic: `test_format_version_is_bumped`).
- `tests/test_transfer_export.py` — `manifest["format_version"] == 8`.
- `tests/test_table_transfer.py` — a **comment**, not an assertion, so nothing
  reddens: "table imports through the full gate (4 <= FORMAT_VERSION=7) …". Update
  it to `=8`.

- [ ] **Step 10: Run the tests to verify they pass**

Run: `uv run pytest tests/test_table_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py tests/test_link_transfer.py tests/test_tabs_transfer.py courses/tests/test_image_size_transfer.py -v`
Run: `uv run ruff check courses/transfer/ tests/test_table_transfer.py`
Expected: PASS.

- [ ] **Step 11: Falsify — require RED (three mutants)**

1. Swap `isinstance(c.get("media"), str)` for `int` in the `_element_mids` `table`
   branch; run `uv run pytest tests/test_table_transfer.py::test_element_mids_table_yields_image_local_ids -v`.
   Expected: FAIL. Restore.
2. Move `TableElement.normalize_data(data)` **before** the remap loop in
   `_build_table`; run the round-trip test. Expected: FAIL (image lost). Restore.
3. Remove `"size"` from `_ser_fill_table`'s `out_cell`; run
   `uv run pytest tests/test_table_transfer.py::test_filltable_image_cell_round_trips_size -v`.
   Expected: FAIL. Restore.
4. **The `refs` return** - the one defect in this task with no other falsifier. Revert
   `_val_table`'s `return refs` to `return set()` and run
   `uv run pytest tests/test_table_transfer.py::test_a_table_with_a_cell_image_passes_whole_archive_validation -v`.
   Expected: FAIL with "Media entry ... is not referenced by any element". Restore.

- [ ] **Step 12: Commit**

```bash
git add courses/transfer/ tests/test_table_transfer.py tests/test_transfer_schema.py \
        tests/test_transfer_export.py tests/test_link_transfer.py \
        tests/test_tabs_transfer.py courses/tests/test_image_size_transfer.py
git commit -m "feat(table-cell-images): transfer image cells, FORMAT_VERSION 8"
```

---

## Task 6: Always-visible toolbar and single-owner control painting

**Files:**
- Modify: `templates/courses/manage/editor/_edit_table.html`, `_edit_filltable.html`
- Modify: `courses/static/courses/js/table_editor.js`, `filltable_editor.js`
- Modify: `courses/static/courses/css/editor.css`
- Modify: `tests/test_editor_twin_drift.py`
- Test: `tests/test_table_editor_partial.py`, `tests/test_filltable_editor_partial.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks (pure editor refactor).
- Produces: `refreshToolbarState()` as the single owner of per-cell control painting in both editors, with two-way visibility **and** value population; every toolbar control carrying an explicit `disabled` predicate; `focusCell` nulled when its node disconnects.

**Why this is its own task:** it is a shared refactor of both editors that Tasks 7
and 8 both build on, and a reviewer could accept it while rejecting either of them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_editor_partial.py`:

```python
def test_toolbar_is_not_hidden():
    """Discoverability: an author opening a table saw a bare grid and no controls,
    with nothing signalling that clicking a cell reveals eighteen of them."""
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-table-toolbar hidden" not in src
    assert "data-table-toolbar" in src


def test_cell_scoped_buttons_carry_disabled_in_markup():
    """Between page load and wire(), and permanently if JS never runs, these would
    otherwise render ENABLED with nothing focused. The e2e assertion cannot see
    this window because wire() has already run by the time Playwright looks."""
    src = PARTIAL.read_text(encoding="utf-8")
    # NOTE: `data-image-toggle` is deliberately ABSENT from this list. _edit_table.html
    # has no image button until Task 7 creates it, so including it here would raise
    # ValueError: substring not found and make this task's PASS unreachable. Task 7
    # asserts it. (This partial's count at the end of Task 6 is therefore TEN
    # cell-scoped buttons: 4 [data-cmd] + 3 halign + 3 valign.)
    for needle in ['data-cmd="bold"', 'data-cmd="italic"', 'data-cmd="underline"',
                   'data-cmd="math"',
                   'data-halign="left"', 'data-halign="center"',
                   'data-halign="right"', 'data-valign="top"',
                   'data-valign="middle"', 'data-valign="bottom"']:
        i = src.index(needle)
        tag = src[src.rindex("<button", 0, i):src.index(">", i)]
        assert "disabled" in tag, needle


def test_rte_swatches_partial_is_untouched():
    """It is included by SIX toolbars whose editors have no disabled mechanism;
    adding `disabled` there would permanently disable colour authoring in the
    text, callout, spoiler and generic RTE editors."""
    import pathlib

    from django.conf import settings

    p = (pathlib.Path(settings.BASE_DIR)
         / "templates/courses/manage/editor/_rte_swatches.html")
    assert "disabled" not in p.read_text(encoding="utf-8")


def test_editor_css_drops_the_dead_toolbar_hidden_rule():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert ".table-editor__toolbar[hidden]" not in css
```

**And mirror the first two into `tests/test_filltable_editor_partial.py`** — otherwise
nothing pins the fill table's half of this task, and a half-done edit ships green. I
verified no existing test asserts either fact for that partial. Same bodies, with
`PARTIAL` pointing at `_edit_filltable.html` and the needle list extended to its
**twelve** cell-scoped buttons — the four `[data-cmd]`, `[data-image-toggle]`,
`[data-answer-toggle]`, and all six align buttons:

```python
def test_filltable_toolbar_is_not_hidden():
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-table-toolbar hidden" not in src
    assert "data-table-toolbar" in src


def test_filltable_cell_scoped_buttons_carry_disabled_in_markup():
    """Twelve here, versus ten in _edit_table.html at this task: this partial already has
    both [data-image-toggle] and [data-answer-toggle]. Both were explicit decisions in the
    spec's predicate table, so both are asserted."""
    src = PARTIAL.read_text(encoding="utf-8")
    for needle in ['data-cmd="bold"', 'data-cmd="italic"', 'data-cmd="underline"',
                   'data-cmd="math"', "data-image-toggle", "data-answer-toggle",
                   'data-halign="left"', 'data-halign="center"',
                   'data-halign="right"', 'data-valign="top"',
                   'data-valign="middle"', 'data-valign="bottom"']:
        i = src.index(needle)
        tag = src[src.rindex("<button", 0, i):src.index(">", i)]
        assert "disabled" in tag, needle
```

Append to `tests/test_editor_twin_drift.py` nothing yet — Step 9 updates it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_editor_partial.py tests/test_filltable_editor_partial.py -v -k "toolbar or disabled or swatches"`
Expected: FAIL in BOTH modules - each partial still renders `data-table-toolbar hidden`,
and neither has `disabled` on its cell-scoped buttons. Running only the plain-table module
would leave the mirrored fill-table tests never shown RED.

- [ ] **Step 3: Make both toolbars always visible, with markup `disabled`**

In **both** `_edit_table.html` and `_edit_filltable.html`:
1. Remove the `hidden` attribute from `<div class="table-editor__toolbar" data-table-toolbar hidden>`.
2. Add `disabled` to the four `[data-cmd]` buttons authored in the file (bold,
   italic, underline, math) and to all six `[data-halign]`/`[data-valign]` buttons.
   In `_edit_filltable.html` **only**, also add it to `[data-image-toggle]` and
   `[data-answer-toggle]`. Merge/split/header already carry it.

**Counts at the end of THIS task:** **twelve** in `_edit_filltable.html`
(4 + image + answer + 3 + 3) and **ten** in `_edit_table.html` (4 + 3 + 3) — the plain
table has no image button and no answer toggle yet. Task 7 adds its
`[data-image-toggle]` **already carrying `disabled`**, taking it to eleven, and asserts
that there.

Do **not** edit `_rte_swatches.html`. The five swatches keep their pre-`wire()`
enabled window — accepted, because that partial is shared with four editors that
have no `disabled` mechanism at all and `.rte-swatch:disabled` styling exists but
nothing would ever re-enable them.

- [ ] **Step 4: Delete the two dead things**

1. In `courses/static/courses/css/editor.css`, delete
   `.table-editor__toolbar[hidden] { display: none; }`.
   This cuts against a repo convention (`.btn[hidden]`, `.view-toggle[hidden]`,
   `.outline-node[hidden]` all keep such a guard because an author `display` beats
   the UA `[hidden]` rule). Accepted deliberately: the toolbar is now permanently
   visible by design, so a future author reaching for `hidden` there would be
   reversing this decision and should meet a dead rule rather than a working one.
2. In **each** editor's `focusin` handler, delete the whole line
   `if (toolbar) toolbar.hidden = false;` - not just the assignment, which would leave a
   dangling `if (toolbar)`.

- [ ] **Step 5: Rewrite `filltable_editor.js`'s `refreshToolbarState`**

Four things move **above** the `if (!focusCell) return;` gate, and then the gate
itself is **deleted**:

```javascript
    function refreshToolbarState() {
      if (!toolbar) return;              // unrelated guard; STAYS
      var mergeBtn = toolbar.querySelector("[data-merge]");
      var splitBtn = toolbar.querySelector("[data-split]");
      var headerBtn = toolbar.querySelector("[data-header-toggle]");
      var answerBtn = toolbar.querySelector("[data-answer-toggle]");
      var imgBtn = toolbar.querySelector("[data-image-toggle]");
      // Derived ONCE, null-safe, at the top: every predicate below uses these
      // names, and `var` hoisting would otherwise make them `undefined` here.
      var isAnswer = !!focusCell && focusCell.hasAttribute("data-answer");
      var isImage = !!focusCell && focusCell.hasAttribute("data-image");

      if (mergeBtn) { /* existing body unchanged */ }
      if (splitBtn) { /* existing body unchanged */ }
      if (headerBtn) refreshHeaderButton(headerBtn);

      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-cmd]"), function (btn) {
        btn.disabled = !focusCell || isAnswer || isImage;
      });
      // The image button keeps its OWN predicate: it must stay ENABLED on an image
      // cell, because that is the re-pick path. Folding it into the loop above
      // would make re-pick unreachable.
      if (imgBtn) imgBtn.disabled = !focusCell;
      if (answerBtn) {
        answerBtn.disabled = !focusCell;
        answerBtn.classList.toggle("is-on", isAnswer);
      }
      Array.prototype.forEach.call(
        toolbar.querySelectorAll("[data-halign], [data-valign]"),
        function (btn) { btn.disabled = !focusCell; }
      );
      // `answerBtn.disabled` above is pinned from BOTH sides: Task 6's mirrored
      // test_filltable_cell_scoped_buttons_carry_disabled_in_markup covers the
      // no-focus state, and Task 9's fill-table e2e asserts
      // `[data-answer-toggle]` is_enabled() WITH a cell focused. Together those
      // bracket the predicate. The plain table's
      // test_cell_scoped_buttons_are_disabled_before_any_focus deliberately omits
      // that selector - the plain table has no answer toggle.

      // Per-cell controls: TWO-WAY visibility AND value population. The old line
      // was `if (imageAlt && !isImage) imageAlt.hidden = true;` — a ONE-WAY hide
      // that never sets hidden=false. Reveal lived only in focusin and in
      // setImageCell's two-liner, both of which are deleted, so relocating the
      // one-way line would leave every control permanently hidden and would redden
      // test_e2e_filltable.py's make_image_cell (it fill()s the alt input right
      // after the picker click, and Playwright's fill() requires visibility).
      var showCellCtl = isImage;
      if (imageAlt) {
        imageAlt.hidden = !showCellCtl;
        if (showCellCtl) imageAlt.value = focusCell.dataset.alt || "";
      }
      if (sizeSel) {
        sizeSel.hidden = !showCellCtl;
        if (showCellCtl) sizeSel.value = focusCell.dataset.size || CELL_IMAGE_DEFAULT;
      }
      if (removeBtn) removeBtn.hidden = !showCellCtl;

      refreshAlignButtons();
    }
```

Acquire `sizeSel` **beside the existing `var imageAlt`** at the top of `wire()`,
and **declare `removeBtn` there too** even though its query returns `null` in this
editor (`[data-image-remove]` is `_edit_table.html` only) — the block above is the
same in both editors, so an undeclared name would throw `ReferenceError` inside
`wire()`:

```javascript
    var sizeSel = editor.querySelector("[data-image-size]");
    var removeBtn = editor.querySelector("[data-image-remove]");
```

**Three bespoke reveal/hide sites must be deleted**, or per-cell painting has more than
one owner and the task's "Produces" is false:

1. `focusin`'s trailing
   `if (td.hasAttribute("data-image") && imageAlt) { imageAlt.hidden = false; imageAlt.value = …; }`
   block (it sits immediately *after* that handler's existing `refreshToolbarState()` call).
2. **`setImageCell`'s trailing
   `if (imageAlt) { imageAlt.hidden = false; imageAlt.value = td.dataset.alt || ""; }`
   two-liner** — the one Step 5c's `refreshToolbarState()` call replaces. Miss this and
   Task 8 Step 7 has you rewrite a comment describing behaviour that is still present.
3. `toggleAnswerCell`'s `if (imageAlt) imageAlt.hidden = true;` line, which paints only
   `imageAlt` and not the new size select — so leaving it makes the sole-owner invariant
   false specifically on the **revert** path. Its branch already ends with
   `refreshToolbarState()`, which repaints all of them correctly once the visibility
   lines are two-way.

- [ ] **Step 5b: Rewrite `table_editor.js`'s `refreshToolbarState` — the mirror image**

Step 5 covers the fill table. The plain table needs the **same final shape reached from
the opposite starting point**: its `refreshToolbarState` today touches merge/split/header
and then calls `refreshAlignButtons`, and the file has **zero** occurrences of
`imageAlt`/`isImage`. So it *acquires* what the fill table *relocates*. Without this
step nothing mandates the plain table's disable loops or per-cell painting at all, and
Task 9's `test_cell_scoped_buttons_are_disabled_before_any_focus` and
`test_clicking_an_image_cell_reveals_and_populates_the_controls` would depend
on code no step writes.

First, acquire the handles **beside `var toolbar = editor.querySelector("[data-table-toolbar]")`**
near the top of `wire()` — **above** the init-time call added in Step 8. The natural site
(beside the new listeners at the *bottom* of `wire()`) is below it, where all three are
hoisted-but-`undefined`, every `if (…)` is falsy, and the init-time hide never runs:

```javascript
    var imageAlt = editor.querySelector("[data-image-alt]");
    var sizeSel = editor.querySelector("[data-image-size]");
    var removeBtn = editor.querySelector("[data-image-remove]");
```

Then the body — identical to the fill table's from `var isImage` onward, minus
`isAnswer`/`answerBtn`:

```javascript
    function refreshToolbarState() {
      if (!toolbar) return;
      var mergeBtn = toolbar.querySelector("[data-merge]");
      var splitBtn = toolbar.querySelector("[data-split]");
      var headerBtn = toolbar.querySelector("[data-header-toggle]");
      var imgBtn = toolbar.querySelector("[data-image-toggle]");
      // Derived ONCE at the top, null-safe, and used by BOTH the [data-cmd] loop and
      // the showCellCtl block below. `var` hoisting would otherwise leave it
      // `undefined` at the loop, making the predicate `!focusCell || undefined` ->
      // falsy -> [data-cmd] ENABLED on a focused image cell.
      var isImage = !!focusCell && focusCell.hasAttribute("data-image");

      if (mergeBtn) { /* existing body unchanged */ }
      if (splitBtn) { /* existing body unchanged */ }
      if (headerBtn) refreshHeaderButton(headerBtn);

      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-cmd]"), function (btn) {
        btn.disabled = !focusCell || isImage;
      });
      // Its OWN predicate: it must stay ENABLED on an image cell, because that is the
      // re-pick path. Folding it into the loop above makes re-pick unreachable.
      if (imgBtn) imgBtn.disabled = !focusCell;
      Array.prototype.forEach.call(
        toolbar.querySelectorAll("[data-halign], [data-valign]"),
        function (btn) { btn.disabled = !focusCell; }
      );

      var showCellCtl = isImage;
      if (imageAlt) {
        imageAlt.hidden = !showCellCtl;
        if (showCellCtl) imageAlt.value = focusCell.dataset.alt || "";
      }
      if (sizeSel) {
        sizeSel.hidden = !showCellCtl;
        if (showCellCtl) sizeSel.value = focusCell.dataset.size || CELL_IMAGE_DEFAULT;
      }
      if (removeBtn) removeBtn.hidden = !showCellCtl;

      refreshAlignButtons();
    }
```

**Declare BOTH constants at module level in BOTH editor files in this step** (beside each
file's `var MAX_ROWS = 50;`), so every body written here compiles immediately:

```javascript
  var CELL_IMAGE_DEFAULT = "full";
  var CELL_IMAGE_INSERT = "medium";
```

Step 5's fill-table body also references `CELL_IMAGE_DEFAULT`, so declaring it only in
`table_editor.js` would leave `filltable_editor.js` naming an undeclared identifier. It is
inert at this task (the fill table has no `[data-image-size]` yet, so `if (sizeSel)` is
falsy), but that is luck, not design - and it becomes a live `ReferenceError` the moment
Tasks 7/8 are reordered or the select is added early. Task 7 then adds only
`CELL_IMG_CLASS` to `table_editor.js`, and Task 8 only `CELL_IMG_CLASS` to
`filltable_editor.js`. At this task `[data-image-alt]`,
`[data-image-size]` and `[data-image-remove]` do not exist in `_edit_table.html` yet, so
all three handles are `null` and every `if (…)` simply never fires — intended, and the
same reason the fill table must *declare* `removeBtn` even though its query returns
`null`.

- [ ] **Step 5c: Make the fill table's picker callback repaint**

`window.libliFillTablePickImage`'s inner callback does
`setImageCell(...); focusCell = target; serialize();` and **never calls
`refreshToolbarState()`**. Once Step 5 makes that function the sole owner of the reveal,
the alt input (and the new size select) stay **hidden** after a picker conversion — and
`tests/test_e2e_filltable.py::make_image_cell` does
`editor.locator("[data-image-alt]").fill(alt)` immediately after the asset click, which
fails Playwright's visibility requirement. `setImageCell` also does
`td.removeAttribute("contenteditable")`, which **blurs** the cell, so no `focusin` fires
to save it.

Insert the call between the two existing lines, and add the null guard the spec requires
in **both** callbacks (it tests the **captured** `target`, not `focusCell`, because
`target` is what the argument list dereferences):

```javascript
      return function (id, _name, url) {
        if (!target) return;                       // NEW — guards the captured node
        setImageCell(target, parseInt(id, 10), url, target.dataset.alt || "");
        focusCell = target;
        refreshToolbarState();                     // NEW — nothing else repaints
        serialize();
      };
```

- [ ] **Step 6: Fix `refreshAlignButtons` (a `TWIN` — byte-identical in both files)**

Its body opens `if (!toolbar || !focusCell) return;` and both loops dereference
`focusCell.dataset`. Simply deleting `|| !focusCell` makes it **throw** on every
null-focus call — including the newly mandated init-time one, inside `wire()`,
which would abort wiring so nothing serializes. Required **whole-function** shape, **character-for-character
identical in `table_editor.js` and `filltable_editor.js`**:

```javascript
    function refreshAlignButtons() {
      if (!toolbar) return;
      var h = focusCell ? (focusCell.dataset.halign || "left") : null;
      var v = focusCell ? (focusCell.dataset.valign || "top") : null;
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-halign]"), function (btn) {
        btn.classList.toggle("is-on", btn.getAttribute("data-halign") === h);
      });
      Array.prototype.forEach.call(toolbar.querySelectorAll("[data-valign]"), function (btn) {
        btn.classList.toggle("is-on", btn.getAttribute("data-valign") === v);
      });
    }
```

`null` matches no button, so all `is-on` clear — which is the stale-paint fix.

- [ ] **Step 7: Fix `refreshHeaderButton` (also a `TWIN`)**

With the toolbar permanently visible, hovering Header with nothing focused shows
"Unavailable while the row or column header option covers this cell." — a false
explanation previously unreachable. Change the fallback, byte-identically in both files:

```javascript
      var locked = focusCell ? headerLocked(focusCell) : false;   // was: : true
```

**This is a ONE-LINE diff, not a function body.** Change only the `locked` initialiser's
`: true` to `: false` and leave the other four statements untouched. The live function has
**five** statements, and the two not shown here —
`btn.setAttribute("aria-pressed", …)` and `btn.classList.toggle("is-on", …)` — sit
*between* `btn.disabled` and `btn.title`. Presenting the three interesting lines as a
contiguous "required shape" (the phrasing this plan uses elsewhere for whole-function
replacements) would have an implementer delete the header button's pressed state and
`is-on` paint in **both** editors, with no test covering either.

The flip is safe because `btn.disabled` already ORs `!focusCell`, so nothing becomes
clickable; only the tooltip stops claiming "Unavailable while the row or column header
option covers this cell." when nothing is focused.

- [ ] **Step 8: Add the init-time refresh and the disconnect clearing**

In **both** editors, call `refreshToolbarState()` once at init, placed **after** the
`focusCell`/`rangeAnchor` declarations. (The natural-looking site beside
`refreshControlState(grid, desc)` sits *above* `var focusCell = null`, where it
works only by `var` hoisting and breaks the moment either becomes `let`/`const`.)

In **both** editors' `afterStructuralEdit()`, add the disconnect clearing as
**statement two** — immediately after `cellStash.clear()`, **before**
`clearRange(false)`:

```javascript
      // focusCell is never re-nulled by any delete/merge path, so deleting the row
      // holding the focused image cell leaves it pointing at a DETACHED <td>: the
      // per-cell controls stay visible and populated, and edits write to a node no
      // longer in the grid — silently lost at the next serialize(). Position
      // matters as much as the bytes: placed after this function's
      // refreshToolbarState()/serialize() calls, the toolbar would be repainted
      // from the still-detached node.
      if (focusCell && !focusCell.isConnected) { focusCell = null; rangeAnchor = null; }
```

The `focusCell &&` half is mandatory: `focusCell` is `null` until the first
`focusin`, and the row/column insert-delete handles are hover-revealed grid chrome
reachable **from page load**. All four of those handlers call
`afterStructuralEdit()`, so a bare `!focusCell.isConnected` raises
`TypeError: Cannot read properties of null`, aborting the handler and leaving the
grid half-edited and **unserialized**.

`table_editor.js` has no `cellStash` yet — Task 7 adds it. For this task, add the
disconnect block as the **first** statement of the plain table's
`afterStructuralEdit()`, and Task 7 will insert `cellStash.clear()` above it.

- [ ] **Step 9: Update `tests/test_editor_twin_drift.py`**

It asserts `EXPECTED_COUNTS = {TABLE_JS: 28, FILL_JS: 36}` and requires every
function name common to both files to be classified in exactly one of
`TWINS` / `DIVERGENT`. Re-derive both counts from the files as they now stand.

Classify only **named `function` declarations** this slice adds to both files —
`_DEF` is `^\s*function (\w+)\s*\(`, so function *expressions* (the picker hook,
the `change`/`input` listeners) are invisible to this guard and must **not** be
given entries; `test_no_stale_classification` asserts every classified name IS a
function in both files, so inventing a key turns a green test RED.

Five `DIVERGENT` reason strings go stale (no test compares them, so nothing reddens):

| entry | replacement reason |
|---|---|
| `serialize` | "fill-table emits three cell kinds (static/answer/image) where the plain table emits **two** (text/image), AND its payload carries two extra document-level fields, case_sensitive and prompt" |
| `refreshToolbarState` | the plain table now has a kind-specific refresh; the fill table's `if (!focusCell) return` gate is **gone** |
| `toggleHeaderCell` | keep the existing focus-fallback clause, which is still the real differentiator (`(next.querySelector(".filltable-editor__answer") \|\| next).focus()` vs a bare `next.focus()`, because `.focus()` is a no-op on a `<td data-answer>`), and add "both now re-key `cellStash`". Replacing the reason with the stash note alone would drop the only true divergence |
| `cellIsNonEmpty` | the plain table now checks **both** a nested `<img>` and `data-image` |
| `afterStructuralEdit` | entry **removed** in Task 7 (it moves to `TWINS`, and a `TWINS` member has no reason string - rewording and keeping the `DIVERGENT` entry fails `test_classifications_are_disjoint`) |

**Do NOT move `afterStructuralEdit` to `TWINS` in this task, and do NOT add a
`stashFor` entry.** Step 8 deliberately leaves the plain table's
`afterStructuralEdit` **without** `cellStash.clear()` (Task 7 inserts it), so at the end
of this task the two bodies still differ by one line and a `TWINS` entry would redden
`test_twins_are_identical`. And `stashFor` does not exist in `table_editor.js` until
Task 7 Step 7, so classifying it now reddens `test_no_stale_classification`, which
asserts every classified name **is** a function in both files.

**In this task:** re-derive `EXPECTED_COUNTS`, and fix only **`refreshToolbarState`**'s
reason - the single one Task 6's own edits invalidate. **Leave `serialize`,
`toggleHeaderCell` and `cellIsNonEmpty` alone until Task 7 Step 8 item 10.** Task 6 does
not touch `serialize` at all (the plain table's image branch lands in Task 7 Step 8
item 1), so at the end of this task the existing reason "the plain table emits one" is
still TRUE and the replacement would be false. Likewise:
`table_editor.js` has no `cellStash` and no `data-image` clause until then, so their
replacement reasons would be false at the end of this task. That is the same
"encode a later task's classification early" pattern already corrected two rows above for
`afterStructuralEdit`/`stashFor`.

**Deferred to Task 7 Step 8 item 10** (once the plain table has `cellStash`): move
`afterStructuralEdit` to `TWINS`, add `stashFor` to `TWINS`, update the module
docstring's counts to **22** twins / **11 file-scope + 11 nested**, "a 21st unguarded
twin" to "a **23rd**", and the "163 lines" figure **re-derived** from the twin bodies
rather than guessed (two implementers would otherwise write two different numbers), update
the `TWINS` inline comment, and delete the fill table's now-false `// fill-table only`
trailing comment. For that move to hold, `test_twins_are_identical` compares
comment-stripped, indent-stripped token lines — so the plain table's map must be named
exactly `cellStash`, `cellStash.clear()` must be its first statement, and the disconnect
block must be byte-identical.

- [ ] **Step 10: Run the tests**

Run: `uv run pytest tests/test_table_editor_partial.py tests/test_filltable_editor_partial.py tests/test_editor_twin_drift.py tests/test_colour_glue_drift.py tests/test_cell_selector_guard.py -v`
Expected: PASS.

**And run BOTH editors' e2e — all five files above are source-scanners.** This task rewrites
five functions in `table_editor.js` (`refreshToolbarState`, `refreshAlignButtons`,
`refreshHeaderButton`, `afterStructuralEdit`, plus the init-time call and the `focusin`
deletion) and nothing so far executes the plain-table editor at all, so a null-deref there
would ship to Task 7 undetected:

Run: `uv run pytest -m e2e tests/test_e2e_table_editor.py tests/test_e2e_filltable.py tests/test_e2e_spanning_merge.py tests/test_e2e_spanning_roundtrip.py -v`
Expected: PASS. The first two drive click-a-cell, `[data-cmd='bold']`, `[data-halign='center']`
and `[data-row-insert]`. **The two spanning modules matter specifically because they reach
`afterStructuralEdit()` with NO cell ever clicked** (`[data-col-insert]` / `[data-col-delete]`
straight after `_reopen`), which is the only place Step 8's new disconnect block runs with
`focusCell === null`.

- [ ] **Step 11: Falsify — require RED**

**Mutant 1 — the align-button null deref.** After Step 6 the function no longer contains
`|| !focusCell` (its guard is `if (!toolbar) return;` plus two ternaries), so phrase the
mutant against the *new* shape: replace the two ternaries with the original bare
`focusCell.dataset.halign` / `.valign` reads, keeping `if (!toolbar) return;`. Do it in
**both** files (it is a byte-identical `TWIN`) and run
`uv run pytest -m e2e tests/test_e2e_table_editor.py tests/test_e2e_filltable.py -v`.
Expected: FAIL — the init-time `refreshToolbarState()` throws inside `wire()`, wiring
aborts, nothing serializes. Restore the ternaries.

**Mutant 2 — the picker repaint (Step 5c).** Remove the `refreshToolbarState();` line
from `libliFillTablePickImage`'s inner callback and run
`uv run pytest -m e2e tests/test_e2e_filltable.py -v`.
Expected: FAIL — `make_image_cell` does `[data-image-alt]`.`fill()` right after the asset
click, and Playwright's `fill()` requires a visible element. Restore it. This existing,
currently-green test is the falsifier for the whole two-way rewrite.

**Mutant 3 - the disconnect predicate. It IS falsifiable here** (an earlier draft claimed
otherwise, reasoning only from `tests/test_e2e_table_editor.py`, whose two scenarios both
click and type into a cell first). `tests/test_e2e_spanning_merge.py::test_column_insert_through_a_colspan_widens_it`
and `test_column_delete_inside_a_colspan_shrinks_it` do `_reopen(...)` and then click
`[data-col-insert]` / `[data-col-delete]` with **no cell click at all**, so they reach
`afterStructuralEdit()` with `focusCell === null` - exactly the window Step 8's new block
first executes in. Change the predicate to the bare `!focusCell.isConnected` and run
`uv run pytest -m e2e tests/test_e2e_spanning_merge.py -v`. Expected: FAIL. Restore.

That also means a genuine (non-mutant) error in the new block would abort those handlers
and skip `serialize()`, which is why those modules join Step 10's run list. Task 9's
`test_a_row_insert_before_any_focus_does_not_throw` remains the direct, dedicated pin.

- [ ] **Step 12: Commit**

```bash
git add templates/courses/manage/editor/_edit_table.html \
        templates/courses/manage/editor/_edit_filltable.html \
        courses/static/courses/js/table_editor.js \
        courses/static/courses/js/filltable_editor.js \
        courses/static/courses/css/editor.css \
        tests/test_editor_twin_drift.py tests/test_table_editor_partial.py \
        tests/test_filltable_editor_partial.py
git commit -m "refactor(table-cell-images): always-visible toolbar, single-owner control painting"
```

---

## Task 7: Plain-table image cells end-to-end in the editor

**Files:**
- Modify: `templates/courses/manage/editor/_edit_table.html`, `editor.html`
- Modify: `courses/static/courses/js/table_editor.js`, `media_picker.js`
- Modify: `courses/static/courses/css/editor.css`
- Modify: `tests/test_table_css.py`, `tests/test_imagezoom_render.py`, `tests/test_cell_selector_guard.py`
- Test: `tests/test_table_editor_partial.py` (append)

**Interfaces:**
- Consumes: Task 3's `form.resolved_grid_cells` and `form.cell_image_sizes`; Task 6's `refreshToolbarState` contract and handle names (`imageAlt`, `sizeSel`, `removeBtn`, `isImage`).
- Produces: `window.libliTablePickImage(pick)` returning `function (id, _name, url)`; `td[data-image]` cells in the plain table's grid; serialized image cells `{kind, media, alt, size, halign, valign}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_table_editor_partial.py`:

```python
def test_image_button_carries_both_pick_attributes():
    """data-pick-mode alone NEVER opens the picker: media_picker.js gates on
    closest("[data-pick-media]") and reads the asset kind from that attribute."""
    src = PARTIAL.read_text(encoding="utf-8")
    i = src.index("data-image-toggle")
    tag = src[src.rindex("<button", 0, i):src.index(">", i)]
    assert 'data-pick-media="image"' in tag
    assert 'data-pick-mode="cell"' in tag
    # Task 6 deliberately left this needle out of its own markup-disabled test (the
    # button did not exist yet) and promised it would be asserted HERE.
    assert "disabled" in tag


def test_per_cell_controls_are_hidden_named_and_unnamed():
    """`hidden` in MARKUP, not merely painted by JS — otherwise three cell-scoped
    controls render visible on every editor load until wire() runs. No `name`: the
    hidden data field is the sole authoritative input, and a badly chosen name can
    shadow a form property (the recorded form.action incident). aria-label because
    an icon-only .rte-btn and a bare <select> ship nameless to screen readers."""
    src = PARTIAL.read_text(encoding="utf-8")
    for attr in ("data-image-alt", "data-image-size", "data-image-remove"):
        i = src.index(attr)
        tag = src[src.rindex("<", 0, i):src.index(">", i)]
        assert "hidden" in tag, attr
        assert "name=" not in tag, attr
        assert "aria-label" in tag, attr


def test_size_select_iterates_the_model_choices_not_per_option_trans():
    """A bare {% trans "Full" %} resolves to the msgid owned by courses/forms.py
    (feminine "Pełna"), so the shipped select would render the wrong gender while a
    source-level test on the model constant still passed."""
    src = PARTIAL.read_text(encoding="utf-8")
    assert "form.cell_image_sizes" in src
    # Scope to the <option> REGION only. A window starting at `data-image-size` would
    # include the select's own title/aria-label {% trans %} calls, which
    # test_per_cell_controls_are_hidden_named_and_unnamed REQUIRES - the two assertions
    # would be mutually unsatisfiable.
    i = src.index("form.cell_image_sizes")
    # Search FORWARD from i: _edit_table.html already has a <select data-border> in the
    # controls strip ABOVE the toolbar, so a bare src.index("</select>") returns that
    # earlier closer, the slice runs backwards, and the assertion passes on "".
    seg = src[i:src.index("</select>", i)]
    assert "{% trans" not in seg


def test_grid_loop_reads_resolved_cells():
    """form.grid_data leaves cell.media an int, so the preview would emit src=""."""
    src = PARTIAL.read_text(encoding="utf-8")
    assert "form.resolved_grid_cells" in src
    assert "{% with d=form.grid_data %}" in src  # controls strip still needs `d`


def test_image_cell_branch_is_a_th_td_pair_with_full_attributes():
    src = PARTIAL.read_text(encoding="utf-8")
    for tag in ("<th data-image", "<td data-image"):
        i = src.index(tag)
        el = src[i:src.index(">", i)]
        assert 'data-media="{{ cell.media.pk }}"' in el, tag
        assert 'data-alt="{{ cell.alt }}"' in el, tag
        assert "data-size=\"{{ cell.size|default:'full' }}\"" in el, tag
        assert 'tabindex="0"' in el, tag
        assert "contenteditable" not in el, tag
        assert "data-halign=" in el and "data-valign=" in el, tag


def test_editor_preview_image_has_no_zoom_hook():
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-zoomable" not in src


def test_table_editor_js_registers_its_own_picker_hook():
    js = TABLE_JS.read_text(encoding="utf-8")
    assert "window.libliTablePickImage" in js
    # Both editor scripts load on every editor page, so a shared global means
    # whichever runs last wins and one editor's picker drives the other's callback.
    assert "libliFillTablePickImage" not in js
```

Append to `tests/test_imagezoom_render.py`: add
`"courses/manage/editor/_edit_table.html"` to `NEVER_ARMED`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_editor_partial.py tests/test_imagezoom_render.py -v`
Expected: FAIL — no image button, no per-cell controls, no image branch.

- [ ] **Step 3: Add the toolbar controls to `_edit_table.html`**

After both align groups and the following `rte-sep`, mirroring `_edit_filltable.html`,
where the image controls sit after `[data-valign]` and the separator (not before the align
groups - an earlier draft said both, which cannot hold):

```html
    <button type="button" class="rte-btn" data-image-toggle disabled
            title="{% trans 'Image cell' %}" aria-label="{% trans 'Image cell' %}"
            data-pick-media="image" data-pick-mode="cell"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-image"/></svg></button>
    <input type="text" class="table-editor__alt input" data-image-alt hidden
           maxlength="255" aria-label="{% trans 'Image description (alt)' %}"
           placeholder="{% trans 'Image description (alt)' %}">
    <select class="input" data-image-size hidden
            title="{% trans 'Image size' %}" aria-label="{% trans 'Image size' %}">
      {% for value, label in form.cell_image_sizes %}
      <option value="{{ value }}">{{ label }}</option>
      {% endfor %}
    </select>
    <button type="button" class="rte-btn" data-image-remove hidden
            title="{% trans 'Remove image' %}" aria-label="{% trans 'Remove image' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-image-remove"/></svg></button>
```

Neither the select nor the alt input carries a `name`. The select's labels come
from `form.cell_image_sizes` (the model's ordered `TextChoices`), never a
per-option `{% trans %}`.

Add `maxlength="255"` to `_edit_filltable.html`'s existing `[data-image-alt]` input
and an `aria-label` matching its placeholder, so the twins agree.

- [ ] **Step 4: Add the sprite symbol**

The sprite defines no trash/remove glyph (`ed-minus` means "delete row/column").
Add a new monochrome `currentColor` line symbol `ed-image-remove` to the sprite in
`templates/courses/manage/editor/editor.html`. Covered by
`tests/test_table_editor_partial.py::test_toolbar_icons_resolve_to_sprite_symbols`
and its fill-table twin, which assert `refs <= _sprite_symbols()`.

While in that file, fix the now-incomplete imagezoom comment ("renders the student
**image/gallery/fill-table** templates, whose images carry `data-zoomable`") — the
plain-table student template carries it too now, via `_table_cell.html`.

- [ ] **Step 5: Add the image branch to the grid loop**

Switch the row iteration to `form.resolved_grid_cells` (keeping
`{% with d=form.grid_data %}` for the controls strip, which reads `d.header_row` /
`d.header_col` / `d.border`), and add a `<th>`/`<td>` **pair** before the existing
text pair:

```html
        {% if cell.kind == "image" %}
        {% if cell.header %}
        <th data-image data-media="{{ cell.media.pk }}" data-alt="{{ cell.alt }}"
            data-size="{{ cell.size|default:'full' }}" tabindex="0"
            class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>
          <img class="table-editor__img table-editor__img--{{ cell.size|default:'full' }}" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
        </th>
        {% else %}
        <td data-image data-media="{{ cell.media.pk }}" data-alt="{{ cell.alt }}"
            data-size="{{ cell.size|default:'full' }}" tabindex="0"
            class="ta-{{ cell.halign }} va-{{ cell.valign }}"
            data-halign="{{ cell.halign }}" data-valign="{{ cell.valign }}"{% if cell.colspan %} colspan="{{ cell.colspan }}"{% endif %}{% if cell.rowspan %} rowspan="{{ cell.rowspan }}"{% endif %}>
          <img class="table-editor__img table-editor__img--{{ cell.size|default:'full' }}" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
        </td>
        {% endif %}
        {% elif cell.header %}
        … existing text <th> …
```

`data-media` must be `{{ cell.media.pk }}`, **not** `{{ cell.media }}`: at this
point `cell.media` is a resolved `MediaAsset`, so the latter renders
`MediaAsset object (5)`, `parseInt` yields `NaN`, `JSON.stringify` writes
`media: null`, and `_cell` degrades the cell to empty text — **the image is lost on
the author's next save with no error**.

It must be a `<th>`/`<td>` pair: `toggleHeaderCell` makes `<th data-image>`
reachable and `serialize()` writes `header: true` for it, so a `<td>`-only branch
silently demotes every header image cell on reload.

- [ ] **Step 6: Per-editor picker dispatch in `media_picker.js`**

Replace the single hard-coded hook with a dispatch keyed off the button's owning
editor root:

```javascript
      fillTargetCb = null;
      if (pick.getAttribute("data-pick-mode") === "cell") {
        // Dispatch by OWNING EDITOR ROOT. Both editor scripts load on every editor
        // page, so a shared global means whichever runs last wins and one editor's
        // picker silently drives the other's callback.
        if (pick.closest("[data-table-editor]") && window.libliTablePickImage) {
          fillTargetCb = window.libliTablePickImage(pick);
        } else if (window.libliFillTablePickImage) {
          fillTargetCb = window.libliFillTablePickImage(pick);
        }
      }
```

- [ ] **Step 7: Add the picker registry and `setImageCell` to `table_editor.js`**

A `closest()` call alone does not fix last-wins, because the fill table's hook is
assigned *inside* `wire(editor)` and closes over that editor's `focusCell` and
`setImageCell`. Use an explicit registry:

```javascript
  // Module-level, keyed by editor root: wire() publishes its per-editor handle
  // here, and ONE module-scope hook looks it up. A per-editor closure re-assigned
  // to one global would still be last-wins regardless of what it inspects.
  var PICK_HANDLES = new WeakMap();

  window.libliTablePickImage = function (pick) {
    var root = pick.closest("[data-table-editor]");
    var handle = root && PICK_HANDLES.get(root);
    if (!handle) return null;   // media_picker.js already tests for truthiness
    return handle(pick);
  };
```

Inside `wire(editor)`, publish the handle and define `setImageCell`:

```javascript
    PICK_HANDLES.set(editor, function (_pick) {
      var target = focusCell;          // captured when the picker OPENS
      return function (id, _name, url) {
        // Guard on the CAPTURED target, not focusCell: it is `target` the argument
        // list dereferences, so the early return must precede argument evaluation.
        // Defence-in-depth — unreachable through the UI while [data-image-toggle]
        // is disabled with no focused cell.
        if (!target) return;
        // id is a STRING (media_picker.js passes the raw data-asset-id).
        setImageCell(target, parseInt(id, 10), url, target.dataset.alt || "");
        focusCell = target;
        refreshToolbarState();   // see below: nothing else paints the new controls
        serialize();
      };
    });

    function setImageCell(td, mediaInt, url, alt) {
      // Stash ONLY on a genuine text->image conversion. On a RE-PICK the cell
      // already carries data-image, and an unconditional stash write would
      // overwrite s.html with the preview <img> markup — Remove image would then
      // restore an <img> into a contenteditable cell, sanitize_cell would strip it
      // to "", and the author's original text would be permanently lost.
      if (!td.hasAttribute("data-image")) {
        stashFor(td).html = td.innerHTML;
      }
      td.setAttribute("data-image", "");
      td.dataset.media = String(mediaInt);
      td.dataset.alt = alt || "";
      // `|| CELL_IMAGE_INSERT` serves conversion AND re-pick from ONE call site: a
      // literal "medium" would demote an author's `full` cell on every re-pick,
      // while a literal "preserve" would leave a converted cell with no size.
      td.dataset.size = td.dataset.size || CELL_IMAGE_INSERT;
      var size = td.dataset.size;      // read AFTER the assignment
      td.setAttribute("tabindex", "0");
      // NOT cosmetic: without this the runtime guard
      // `if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable"))`
      // passes on an image cell, and the Enter/input handlers (deliberately left
      // [contenteditable]-only) start firing on it.
      td.removeAttribute("contenteditable");
      td.innerHTML = "";
      // DOM property assignment, not innerHTML concat, so a `"` or `<` in a
      // free-typed alt cannot break out of the markup.
      var img = document.createElement("img");
      img.className = "table-editor__img";        // lone assignment: the guard regex
      img.classList.add(CELL_IMG_CLASS[size]);    // literal map, not concatenation
      img.src = url;
      img.alt = alt || "";
      td.appendChild(img);
    }
```

Add the `CELL_IMG_CLASS` map beside the existing `var MAX_ROWS = 50;`.
**`CELL_IMAGE_DEFAULT` and `CELL_IMAGE_INSERT` already exist** — Task 6 Step 5b declared
both in **both** editor files. Do not re-declare them here; duplicate `var` is legal JS
and `test_js_size_defaults_match_python_and_are_used` uses `in src`, so nothing would
catch the duplication.

```javascript
  // Whole-literal class names: `classList.add("table-editor__img--" + size)` would
  // leave only a stem literal in the source, making test_table_css.py's assertion
  // pass with three of four modifiers unstyled.
  var CELL_IMG_CLASS = {
    small: "table-editor__img--small",
    medium: "table-editor__img--medium",
    large: "table-editor__img--large",
    full: "table-editor__img--full",
  };
```

Add `cellStash` and `stashFor`, copied **byte-identically** from
`filltable_editor.js` — verified there as `new Map()`, **not** a `WeakMap` (a
`WeakMap` has no `.clear()`, which `afterStructuralEdit` calls). `stashFor` becomes a
`TWIN`, so the plain table keeps the unused `answer: null` slot verbatim even though
it has no answer cells: a one-word dead key costs less than a `DIVERGENT` entry whose
reason would need maintaining.

```javascript
    // Declared at the same relative position as the fill table's (above the
    // focusCell/rangeAnchor declarations): afterStructuralEdit, setImageCell and the
    // Remove-image listener all dereference it, and the init-time refreshToolbarState
    // runs after those declarations.
    var cellStash = new Map();

    function stashFor(td) {
      var s = cellStash.get(td);
      if (!s) {
        s = { html: null, answer: null };
        cellStash.set(td, s);
      }
      return s;
    }
```



- [ ] **Step 8: Wire the rest of `table_editor.js`**

1. **`serialize()`** — derive `isImage` as the callback's first statement, guard
   `mapColours` on a **separate enclosing line** so the needle line stays
   byte-identical (`tests/test_colour_glue_drift.py` compares that whole line
   between the two files), branch on kind, and keep **one** `row.push(cell)` after
   the shared span/header suffix with **no `return`** anywhere in the callback:

```javascript
        Array.prototype.forEach.call(dataCells(tr), function (td) {
          var isImage = td.hasAttribute("data-image");
          if (!isImage) {
            if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });
          }
          var cell;
          if (isImage) {
            cell = {
              kind: "image",
              media: parseInt(td.dataset.media, 10),   // dataset is a STRING
              alt: td.dataset.alt || "",
              size: td.dataset.size || CELL_IMAGE_DEFAULT,
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
          } else {
            cell = {
              html: td.innerHTML,
              halign: td.dataset.halign || "left",
              valign: td.dataset.valign || "top",
            };
          }
          if (td.colSpan > 1) cell.colspan = td.colSpan;
          if (td.rowSpan > 1) cell.rowspan = td.rowSpan;
          if (td.tagName === "TH") cell.header = true;
          row.push(cell);
        });
```

2. **`focusin`** — widen the selector to
   `"td[contenteditable], th[contenteditable], td[data-image], th[data-image]"`.
   **Only this selector widens.** `table_editor.js` has three
   `closest("td[contenteditable], th[contenteditable]")` sites plus one bare
   `closest("[contenteditable]")` (inside the `input` handler, which is not a td/th pair
   and to which "widen the selector" does not apply at all); the
   Enter `keydown` and the `input` handler stay `[contenteditable]`-only (an image
   cell has no caret), matching what the fill table did. There is **no**
   "post-merge/delete focus fallback" selector — merge/split call
   `kept.focus()` / `anchor.focus()` on a *node*.
3. **Toolbar click handler** — add the twin's clause:
   `if (cmdBtn && focusCell && focusCell.hasAttribute("contenteditable"))`.
   Defence-in-depth/twin-parity, deliberately **unpinned**: after `setImageCell`
   calls `refreshToolbarState()` the button is already `disabled`, so a UI-level
   "convert then click math" test is unfalsifiable (Playwright's `.click()` waits
   for enabled and times out; `force=True` dispatches no event).
4. **Alt input listener** — the plain table has **zero** occurrences of `imageAlt`
   today, so this is created from scratch (a `DIVERGENT` behaviour, not a twin — it
   queries `.table-editor__img` where the fill table queries
   `.filltable-editor__img`; and being an anonymous callback it is **outside**
   `test_editor_twin_drift.py`'s contract):

```javascript
      if (imageAlt) {
        imageAlt.addEventListener("input", function () {
          if (!focusCell || !focusCell.hasAttribute("data-image")) return;
          focusCell.dataset.alt = imageAlt.value;
          var img = focusCell.querySelector(".table-editor__img");
          if (img) img.setAttribute("alt", imageAlt.value);
          serialize();
        });
      }
```

5. **Size select listener** — remove all four modifiers before adding one:

```javascript
      if (sizeSel) {
        sizeSel.addEventListener("change", function () {
          if (!focusCell || !focusCell.hasAttribute("data-image")) return;
          focusCell.dataset.size = sizeSel.value;
          var img = focusCell.querySelector(".table-editor__img");
          if (img) {
            // REMOVE all four first: classList.add alone accumulates, and the four
            // modifiers are single-class selectors of identical specificity, so the
            // winner would then be decided by stylesheet source order rather than
            // the author's pick.
            Object.keys(CELL_IMG_CLASS).forEach(function (k) {
              img.classList.remove(CELL_IMG_CLASS[k]);
            });
            img.classList.add(CELL_IMG_CLASS[sizeSel.value]);
          }
          serialize();
        });
      }
```

6. **Remove image** — the plain table has no Answer-cell toggle to get this free:

```javascript
      if (removeBtn) {
        removeBtn.addEventListener("click", function () {
          if (!focusCell || !focusCell.hasAttribute("data-image")) return;   // no-op
          var stashed = cellStash.get(focusCell);
          // The NO-STASH case is the DOMINANT one, not an edge case: the stash is
          // populated only by an in-session conversion, so any author who saves,
          // reloads and then removes a server-rendered image cell hits it. A bare
          // `stashed.html` would write the string "undefined".
          focusCell.innerHTML = (stashed && stashed.html != null) ? stashed.html : "";
          focusCell.removeAttribute("data-image");
          delete focusCell.dataset.media;
          delete focusCell.dataset.alt;
          delete focusCell.dataset.size;
          focusCell.removeAttribute("tabindex");
          focusCell.setAttribute("contenteditable", "true");
          refreshToolbarState();
          serialize();
        });
      }
```

7. **Structural operations that need NO work** — stated so nobody invents any:
   **Split** leaves the image in the anchor cell and builds the new cells from the
   existing `makeCell()` helper as ordinary text cells; the **`header_row`/`header_col`
   toggles** may promote an image cell to `<th>`, which the shared `_table_cell.html`
   already handles; **row/column delete** gets no new warning, matching text cells
   today. **Merge** is the one that acts: an absorbed image cell triggers the
   *existing* merge-discard confirmation and, on confirm, is discarded — it does
   **not** block (`absorbedNonEmpty`'s only consumer is
   `if (rg && absorbedNonEmpty(rg)) { if (!window.confirm(msg("merge-confirm"))) return; }`).
8. **`cellIsNonEmpty`** — add a `data-image` clause as **defence-in-depth /
   twin-parity**, not a fix for a reachable state (every producer of
   `td[data-image]` also produces the child `<img>` synchronously, so
   `querySelector("img")` already covers every live case). **It is therefore deliberately
   UNPINNED** — the same treatment the `contenteditable` clause and both picker-callback
   guards get. Do **not** write a test that synthesises the state by deleting the `<img>`:
   it would assert a property of a state no code path produces.

```javascript
      return c.textContent.trim() !== ""
        || c.querySelector("img") !== null
        || c.hasAttribute("data-image");
```

   Delete the now-false comment above `absorbedNonEmpty`
   ("table_editor.js has no kinds; the kind clauses live in filltable_editor.js's
   override.").
9. **`toggleHeaderCell`** — it builds a **new** element and calls
   `td.replaceWith(next)`; attributes are copied but a `WeakMap`/`Map` stash key is
   not, so header-toggling an image cell would orphan its stash and Remove image
   would restore nothing. Re-point the stash from the old node to the replacement,
   mirroring the fill table. Delete its now-false comment ("there is no such map in
   this file's scope"), and update **`filltable_editor.js`**'s reciprocal comment
   too ("cellStash is LIVE here (unlike table_editor.js's no-op guard)") — the
   diff does not route anyone to that line.
10. **`afterStructuralEdit`** — add `cellStash.clear()` as its **first** statement
   (above Task 6's disconnect block), making the two bodies identical. **Now** do the
   twin-drift bookkeeping Task 6 deferred:
   - **remove** `afterStructuralEdit`'s `DIVERGENT` entry and add it to `TWINS`;
   - add `stashFor` to `TWINS`;
   - **add a `DIVERGENT["setImageCell"]` entry** — this task makes it a function common
     to both files (`filltable_editor.js:408` already has
     `function setImageCell(td, mediaInt, url, alt)`, which `_DEF` matches), so without
     an entry `test_every_common_function_is_classified` goes RED at Step 11. Reason:
     *"preview class name differs (`table-editor__img` vs `filltable-editor__img`); the
     fill table also stashes and clears `data-answer`, and its stash write has two
     branches where the plain table's has one."*
   - **update `serialize`'s reason** to "fill-table emits three cell kinds
     (static/answer/image) where the plain table emits **two** (text/image), AND its
     payload carries two extra document-level fields, `case_sensitive` and `prompt`";
   - **update `cellIsNonEmpty`'s reason** - the live one contrasts "the plain table
     queries for a nested `<img>`, fill-table checks the `data-image` attribute", and
     item 8 makes the plain table check **both**;
   - **update `toggleHeaderCell`'s reason** - the live one names "fill-table re-keys the
     live `cellStash` Map old->new" as the differentiator, and item 9 makes the plain
     table re-key too. Keep the focus-fallback clause, which remains the real divergence
     (`(next.querySelector(".filltable-editor__answer") || next).focus()` vs a bare
     `next.focus()`, because `.focus()` is a no-op on a `<td data-answer>`);
   - re-derive `EXPECTED_COUNTS` again, update the module docstring's counts to **22**
     twins (**11 file-scope + 11 nested** — `afterStructuralEdit` and `stashFor` are both
     nested in `wire()`) and re-derive the `DIVERGENT` count too;
   - update the `TWINS` inline comment, and delete the fill table's now-false
     `// fill-table only` trailing comment on `cellStash.clear()`.

- [ ] **Step 9: Editor CSS**

In `courses/static/courses/css/editor.css`:

```css
/* Plain-table editor preview. `.table-editor__img` does NOT exist today — this is
   authored new, not "stripped". No max-width on the base, for the same
   equal-specificity reason as the student rules. The scale is proportional, not
   pixel-exact (the editor grid is not the 648px student column), but every entry
   is bounded ABSOLUTELY in both axes: `max-width: 100%` is NOT a bound here,
   because the editing grid is an auto-layout <table> too — a 1586x612 asset with
   only a 200px height cap would render ~518px wide and drag the grid. */
.table-editor__img { height: auto; display: block; }
.table-editor__img--small  { max-width: 40px;             max-height: 40px; }
.table-editor__img--medium { max-width: 80px;             max-height: 80px; }
.table-editor__img--large  { max-width: 120px;            max-height: 120px; }
.table-editor__img--full   { max-width: min(100%, 200px); max-height: 200px; }
.ta-center > .table-editor__img { margin-inline: auto; }
.ta-right  > .table-editor__img { margin-inline: auto 0; }

/* The BUTTON needs this: `.rte-btn` declares display:inline-flex, and an author display
   beats the UA [hidden]{display:none} rule REGARDLESS of specificity - the same trap this
   file already documents at .view-toggle[hidden]. Without it a `hidden` Remove-image
   button stays permanently visible, on text cells too.

   The SELECT does not strictly need it today (`.input` declares no `display`, and there is
   no .table-editor__alt / .filltable-editor__alt rule), so its rule is defence-in-depth
   against a future `display` landing on `.input`. Stated accurately rather than claiming
   both are broken without it. */
[data-image-remove][hidden] { display: none; }
[data-image-size][hidden] { display: none; }
```

Extend `tests/test_table_css.py`'s emission guard: replace its pattern with
`re.findall(r'"(table-editor__[\w-]+)"', js)` — a strict **superset** of the
existing `className = "…"` pattern that also catches the `CELL_IMG_CLASS` map's
literals. Assert per-file and boundary-anchored on both sides
(`(?<![\w-])\.{cls}(?![\w-])`), `table-editor__*` against `editor.css` **only**,
never concatenated with `courses.css` — `.table-editor__img--small` is a substring
of `.filltable-editor__img--small`. Add a line-anchored
`re.search(r"^\.table-editor__img\s*\{", editor_css, re.M)` for the base rule
(**`re.M` is mandatory**; without it `^` anchors at string start and matches
nothing, failing a correct build).

Append to **`tests/test_table_css.py`** (which already defines `TABLE_JS`, and to which the
constants table tells you to add `FILL_JS`) a source-level test asserting the JS literals
equal the Python constants **and are used**:

```python
def test_js_size_defaults_match_python_and_are_used():
    from courses.models import TableElement

    # TABLE_JS ONLY in this task: filltable_editor.js does not declare these constants
    # until Task 8 Step 4, and does not USE `|| CELL_IMAGE_INSERT` until Task 8 Step 5.
    # Task 8 Step 8 widens this loop to both files.
    src = TABLE_JS.read_text(encoding="utf-8")
    assert f'var CELL_IMAGE_DEFAULT = "{TableElement.DEFAULT_CELL_IMAGE_SIZE}"' in src
    assert f'var CELL_IMAGE_INSERT = "{TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE}"' in src
    # Declared-but-unused would leave the pin guarding nothing.
    assert "|| CELL_IMAGE_DEFAULT" in src
    assert "|| CELL_IMAGE_INSERT" in src
```

- [ ] **Step 10: Update `tests/test_cell_selector_guard.py`**

Its `INVENTORY` carries `("…/table_editor.js", 'closest("td[contenteditable]', "th")`,
and its own comment documents the hazard: **if** the selector is line-wrapped, the
needle no longer lands on the `focusin` site and is instead satisfied by unrelated
single-line `keydown`/`input` calls, leaving the widened site **unguarded with the
test still green**. Add the plain table's bespoke full-literal entry
unconditionally, mirroring the fill table's. **The guard matches line by line
(`needle in ln`), so the widened `closest(...)` argument literal must itself stay on ONE
source line** — that is precisely why the fill table's entry works
(`filltable_editor.js:546` holds the whole literal on one line). Wrapping *inside* the
literal makes the entry report "inventory line vanished" on a correct build. The exact
needle is `"td[contenteditable], th[contenteditable], td[data-image], th[data-image]"`.
The entry is correct whether or not the widened
selector happens to wrap. A Definition-of-Done item on **this** task, alongside
`test_editor_twin_drift.py`'s `EXPECTED_COUNTS`, `test_colour_glue_drift.py` and
`NEVER_ARMED`.

- [ ] **Step 11: Run the tests**

Run: `uv run pytest tests/test_table_editor_partial.py tests/test_table_css.py tests/test_imagezoom_render.py tests/test_cell_selector_guard.py tests/test_editor_twin_drift.py tests/test_colour_glue_drift.py -v`
Expected: PASS.

- [ ] **Step 12: Falsify — what CAN be falsified here, and what is deferred**

**Falsifiable now** (Step 1's source-level tests):

1. Emit the modifier by concatenation (`classList.add("table-editor__img--" + size)`)
   instead of the `CELL_IMG_CLASS` map; run
   `uv run pytest tests/test_table_css.py -v`. Expected: FAIL — only the stem is a
   literal, so three of four modifiers go unguarded. Restore the map.
2. Change the template's `data-media` to `{{ cell.media }}`; run
   `uv run pytest tests/test_table_editor_partial.py::test_image_cell_branch_is_a_th_td_pair_with_full_attributes -v`.
   Expected: FAIL. Restore `.pk`.
3. Assign `window.libliFillTablePickImage` in `table_editor.js` instead of its own hook;
   run `uv run pytest tests/test_table_editor_partial.py::test_table_editor_js_registers_its_own_picker_hook -v`.
   Expected: FAIL. Restore.

**Deferred to Task 9 Step 4** — these three need a browser, and their tests are created
there, so do **not** attempt them at this task (an earlier draft named tests that exist
nowhere, and a `pytest` "not found" error reads deceptively like a caught mutant):

- `serialize()`'s `media:` → bare `td.dataset.media`, falsified by
  `test_an_image_cell_survives_a_save_and_reopen`;
- the template's `data-media` → `{{ cell.media }}`, falsified by the same test
  behaviourally (Step 12 item 2 above catches it at source level only);
- removing the `if (!td.hasAttribute("data-image"))` stash guard, falsified by
  `test_convert_repick_then_remove_restores_the_original_text`.

- [ ] **Step 13: Commit**

```bash
git add templates/courses/manage/editor/_edit_table.html \
        templates/courses/manage/editor/_edit_filltable.html \
        templates/courses/manage/editor/editor.html \
        courses/static/courses/js/table_editor.js \
        courses/static/courses/js/filltable_editor.js \
        courses/static/courses/js/media_picker.js \
        courses/static/courses/css/editor.css \
        tests/test_table_editor_partial.py tests/test_table_css.py \
        tests/test_imagezoom_render.py tests/test_cell_selector_guard.py \
        tests/test_editor_twin_drift.py
git commit -m "feat(table-cell-images): plain-table image cells in the editor"
```

---

## Task 8: Fill-table size select and preview modifiers

**Files:**
- Modify: `templates/courses/manage/editor/_edit_filltable.html`
- Modify: `courses/static/courses/js/filltable_editor.js`
- Test: `tests/test_filltable_editor_partial.py` (append), `tests/test_table_css.py`
  (Steps 7b and 7c both edit it)

**Interfaces:**
- Consumes: Task 3's `form.cell_image_sizes`; Task 6's handle names and painting contract; Task 7's `CELL_IMG_CLASS` pattern (the fill table gets its own map).
- Produces: fill-table image cells that round-trip `size` through an editor save.

**Why separate:** two sites carry `size` in the fill table, and missing either
reverts **every** image cell to `full` on **every** save — the same defect class as
the `_ser_fill_table` omission but on the far more frequent path. A reviewer should
be able to gate it independently.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_filltable_editor_partial.py`:

```python
def test_image_branches_carry_data_size_and_the_preview_modifier():
    src = PARTIAL.read_text(encoding="utf-8")
    assert src.count("data-size=\"{{ cell.size|default:'full' }}\"") == 2  # th + td
    assert src.count("filltable-editor__img--{{ cell.size|default:'full' }}") == 2


def test_size_select_is_present_beside_the_alt_input():
    src = PARTIAL.read_text(encoding="utf-8")
    assert "data-image-size" in src
    assert "form.cell_image_sizes" in src


def test_filltable_per_cell_controls_are_hidden_named_and_unnamed():
    """Mirrors the plain table's test_per_cell_controls_are_hidden_named_and_unnamed. A
    presence check alone is not enough: a select without markup `hidden` renders visible
    on every fill-table editor load until wire() runs, and Task 9's fill-table e2e asserts
    visibility only AFTER the image cell is clicked, so it would stay green."""
    src = PARTIAL.read_text(encoding="utf-8")
    for attr in ("data-image-alt", "data-image-size"):
        i = src.index(attr)
        tag = src[src.rindex("<", 0, i):src.index(">", i)]
        assert "hidden" in tag, attr
        assert "name=" not in tag, attr
        assert "aria-label" in tag, attr
    # maxlength is half of the spec's "255 at both ends" decision, which is what keeps an
    # authorable table re-importable. Task 7 Step 3 adds it here; nothing else pins it.
    i = src.index("data-image-alt")
    assert 'maxlength="255"' in src[src.rindex("<", 0, i):src.index(">", i)]


def test_serialize_image_branch_emits_size():
    js = FILL_JS.read_text(encoding="utf-8")
    seg = js[js.index('kind: "image"'):js.index('kind: "image"') + 400]
    assert "size:" in seg


def test_toggle_answer_cell_clears_data_size():
    """A stale data-size would linger on the static cell and be inherited by a
    later reconversion."""
    js = FILL_JS.read_text(encoding="utf-8")
    seg = js[js.index("function toggleAnswerCell"):]
    seg = seg[:seg.index("\n    }")]
    assert "data-size" in seg or "dataset.size" in seg
```

Plus the behavioural test — an **untouched** image cell must round-trip its `size`
through an editor save. This is the defect class that matters most: it fires on the
*most frequent* path, and every server-side test that constructs data directly
would stay green through it.

```python
@pytest.mark.django_db
def test_form_and_model_preserve_a_submitted_size(tmp_path, settings):
    """Pins the FORM + MODEL path only: a payload carrying `size` survives clean_data,
    normalize_data and save().

    It hand-builds its JSON and posts it, so it never runs JS - it is green with or
    without `size:` in serialize() and with or without `data-size` in the template. Those
    two JS sites are pinned by the source-level tests above and, behaviourally, by Task 9's
    fill-table e2e. Do not point a serialize() mutant at this test.
    """
    import json

    from courses.element_forms import FillTableElementForm
    from tests.factories import make_course, make_image_asset

    settings.MEDIA_ROOT = str(tmp_path)
    course = make_course()
    asset = make_image_asset(course, filename="a.png")
    payload = {"data": json.dumps({
        "prompt": "", "case_sensitive": False, "header_row": False,
        "header_col": False, "border": "grid",
        # An ANSWER CELL IS MANDATORY: FillTableElementForm.clean_data raises
        # "Mark at least one answer cell (use the "Answer cell" button)." when
        # answer_cells(cells) is empty, so an image-only payload can NEVER validate
        # and this test — the pin for the slice's highest-frequency defect — could
        # never pass.
        "cells": [[
            {"kind": "image", "media": asset.pk, "alt": "",
             "size": "large", "halign": "left", "valign": "top"},
            {"kind": "answer", "answer": "x", "halign": "left", "valign": "top"},
        ]],
    })}
    form = FillTableElementForm(data=payload, course=course)
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.data["cells"][0][0]["size"] == "large"
```

Confirm `FillTableElementForm`'s `Meta.fields` against `tests/test_filltable_form.py`
before running — that file already builds valid payloads for this form and is the
reference for any other required key.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_filltable_editor_partial.py -v -k "size"`
Expected: FAIL.

- [ ] **Step 2b: Fill-table editor preview CSS (deferred from Task 4)**

Do this **before** Step 3, so the base rule and its modifiers land in the same commit as
the template and JS that emit them - no window in which the preview is uncapped. In
`courses/static/courses/css/courses.css`, replace the single existing
`.filltable-editor__img { max-width: 120px; height: auto; display: block; }` line with:

```css
/* Fill-table editor preview. max-width leaves the BASE for the same equal-specificity
   reason as the student rules, so every size lives on a modifier. Bounded ABSOLUTELY in
   both axes: `max-width: 100%` is not a bound in an auto-layout editor grid. */
.filltable-editor__img { height: auto; display: block; }
.filltable-editor__img--small  { max-width: 40px;             max-height: 40px; }
.filltable-editor__img--medium { max-width: 80px;             max-height: 80px; }
.filltable-editor__img--large  { max-width: 120px;            max-height: 120px; }
.filltable-editor__img--full   { max-width: min(100%, 200px); max-height: 200px; }
.ta-center > .filltable-editor__img { margin-inline: auto; }
.ta-right  > .filltable-editor__img { margin-inline: auto 0; }
```

Add `courses/static/courses/css/courses.css` to this task's Files list and Step 10's
`git add`.

- [ ] **Step 3: Template — `data-size` and the preview modifier on both branches**

In `_edit_filltable.html`, add `data-size="{{ cell.size|default:'full' }}"` to
**both** the `<th data-image …>` and `<td data-image …>` branches, and change both
`<img class="filltable-editor__img">` tags to:

```html
<img class="filltable-editor__img filltable-editor__img--{{ cell.size|default:'full' }}" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}">
```

The `|default:'full'` filter is required on **both** editors' sites, not just the
plain table's: a missing key renders `filltable-editor__img--`, which matches no
rule, and since `max-width: 120px` is stripped from the base, nothing then caps the
preview — a p50 1192px asset renders at intrinsic width and drags the editing grid.

Add the size select beside the existing `[data-image-alt]` input, identical in
shape to the plain table's (Task 7 Step 3) — `hidden`, no `name`, `title` +
`aria-label`, options from `form.cell_image_sizes`.

- [ ] **Step 4: JS — `size` in `serialize()`**

Add `size: td.dataset.size || CELL_IMAGE_DEFAULT,` to the image branch's cell literal,
and add a `CELL_IMG_CLASS` map for `filltable-editor__img--*` (same shape as Task 7's).
**The two constants already exist** from Task 6 Step 5b — do not re-declare them.

**And rewrite the `forEach` callback's opening, which Task 7 did only for the plain table.**
`filltable_editor.js`'s callback still calls `mapColours` unconditionally as its first
statement and branches inline on `td.hasAttribute(...)`. The spec requires **both** files to
derive the locals and guard the call, and **nothing reddens if this is skipped** — because
`test_colour_glue_drift.py::_line` strips indentation, the shared needle line compares equal
either way, so the asymmetric result the spec calls "honest rather than a coincidence" would
silently not land:

```javascript
        Array.prototype.forEach.call(dataCells(tr), function (td) {
          var isAnswer = td.hasAttribute("data-answer");
          var isImage  = td.hasAttribute("data-image");
          if (!isAnswer && !isImage) {
            if (window.libliColour) window.libliColour.mapColours(td, { dropUnmapped: true });
          }
          …
```

The `mapColours` line itself stays **byte-identical** to the plain table's — that is what
keeps `test_colour_glue_drift.py` green untouched — and the three existing branch conditions
are re-expressed as `if (isImage) … else if (isAnswer) … else …`, so the attribute is read
once per cell and the guard cannot drift from the branch it mirrors.

- [ ] **Step 5: JS — `setImageCell` emits the modifier**

It rebuilds the preview with `img.className = "filltable-editor__img"` — base only.
Once `max-width` is stripped from that base, an in-session conversion or re-pick
would render the asset at its intrinsic width and drag the editing grid — a
regression to an already-shipped feature. Add, after the lone `className` line:

```javascript
      var size = td.dataset.size;
      img.classList.add(CELL_IMG_CLASS[size]);
```

**`td.dataset.size` must be SET here first — the fill table's `setImageCell` never
writes it.** It writes `data-media`, `data-alt` and `tabindex` only. Without the
assignment, `td.dataset.size` is `undefined` on a conversion, `CELL_IMG_CLASS[undefined]`
is `undefined`, and `classList.add(undefined)` adds the literal token `"undefined"` — so
the preview gets **no bounding modifier** and drags the editing grid, exactly the
regression this step exists to prevent. `serialize()` would then also write `size: "full"`,
contradicting the mandated editor-insert default of `medium`. So the full addition is:

```javascript
      td.dataset.size = td.dataset.size || CELL_IMAGE_INSERT;  // NEW - before the read
      var size = td.dataset.size;
      img.classList.add(CELL_IMG_CLASS[size]);
```

`|| CELL_IMAGE_INSERT` (not a literal `"medium"`) serves conversion **and** re-pick from
this one call site: a literal would demote an author's `full` cell on every re-pick.

**The stash guard, written out for THIS function** — "exactly as in Task 7" does not
transfer, because the plain table's is the single line `stashFor(td).html = td.innerHTML;`
while this one opens `var s = stashFor(td);` and has a two-branch answer/static write.
Wrap the whole thing, `var s = …` included:

```javascript
      // Stash ONLY on a genuine conversion. On a RE-PICK the cell already carries
      // data-image, and an unconditional write would overwrite s.html with the preview
      // <img> markup — Remove image / the answer toggle would then restore an <img>
      // into a contenteditable cell, sanitize_cell would strip it to "", and the
      // author's original text would be permanently lost.
      if (!td.hasAttribute("data-image")) {
        var s = stashFor(td);
        if (td.hasAttribute("data-answer")) {
          var input = td.querySelector(".filltable-editor__answer");
          s.answer = input ? input.value : "";
        } else {
          s.html = td.innerHTML;
        }
      }
```

- [ ] **Step 6: JS — size-select listener and `toggleAnswerCell`**

Add the `change` listener (querying `.filltable-editor__img`), removing all four
modifiers before adding one. Add `data-size` to the attributes removed by
`toggleAnswerCell`'s image→static branch, which today drops
`data-media`/`data-alt`/`tabindex`.

- [ ] **Step 7: Update the stale `setImageCell` header comment**

It reads "Stashes the prior kind's content … and **immediately reveals + populates
the alt input** — a later focusin is **NOT** relied upon". Both clauses are now
false: the stash write is conditional, and the reveal is `refreshToolbarState()`'s
job. Rewrite it.

- [ ] **Step 7b: Widen the JS-constant pin to both editor files**

Task 7 Step 9 scoped `test_js_size_defaults_match_python_and_are_used` to `TABLE_JS`
because `filltable_editor.js` had neither constant yet. Steps 4–5 have now added both
**and** the `|| CELL_IMAGE_INSERT` use, so restore the loop the spec requires
("symmetrically for both"):

```python
    for js in (TABLE_JS, FILL_JS):
        src = js.read_text(encoding="utf-8")
        assert f'var CELL_IMAGE_DEFAULT = "{TableElement.DEFAULT_CELL_IMAGE_SIZE}"' in src
        assert f'var CELL_IMAGE_INSERT = "{TableElement.EDITOR_INSERT_CELL_IMAGE_SIZE}"' in src
        assert "|| CELL_IMAGE_DEFAULT" in src
        assert "|| CELL_IMAGE_INSERT" in src
```

This is what gives `FILL_JS` in `tests/test_table_css.py` a consumer.

- [ ] **Step 7c: Guard the fill-table preview modifier classes**

The four `.filltable-editor__img--*` rules land in `courses.css` (Task 4), the template
modifier in Step 3, and the `CELL_IMG_CLASS` map in Step 4 — three sides with **nothing
pinning them together**. Task 7's emission guard is scoped to `table-editor__*` against
`editor.css` only, so a typo in either the JS map or a CSS rule silently leaves previews
unbounded, which is the exact regression Step 5 exists to prevent. Add the mirror half to
`tests/test_table_css.py`, per-file and boundary-anchored on both sides:

```python
def test_filltable_editor_classes_the_js_names_are_styled():
    js = FILL_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")          # courses.css ONLY, never concatenated
    emitted = set(re.findall(r'"(filltable-editor__[\w-]+)"', js))
    assert emitted, "expected filltable_editor.js to name filltable-editor__* classes"
    for cls in sorted(emitted):
        assert re.search(rf"(?<![\w-])\.{re.escape(cls)}(?![\w-])", css), cls
    # And the base rule itself exists, not merely the name (`.ta-center >
    # .filltable-editor__img` satisfies the name check on its own). re.M is mandatory.
    assert re.search(r"^\.filltable-editor__img\s*\{", css, re.M)
```

- [ ] **Step 8: Run the tests**

Placed AFTER Steps 7b and 7c, which both edit `tests/test_table_css.py` - an earlier draft
ran this before them, so neither the widened constant pin nor the new fill-table CSS guard
was ever executed before the commit.

Run: `uv run pytest tests/test_filltable_editor_partial.py tests/test_editor_twin_drift.py tests/test_table_css.py -v`
Run: `uv run ruff check courses/static/courses/js/filltable_editor.js tests/test_table_css.py tests/test_filltable_editor_partial.py`
Expected: PASS.

- [ ] **Step 9: Falsify**

Remove `size:` from the fill table's `serialize()` image branch and run
`uv run pytest tests/test_filltable_editor_partial.py::test_serialize_image_branch_emits_size -v`.
Expected: FAIL. Restore.

**Do NOT point this mutant at `test_untouched_image_cell_round_trips_size_through_an_editor_save`.**
That test hand-builds its JSON payload and posts it to the form — it never runs JS, so it
is green with or without `size:` in `serialize()` and with or without `data-size` in the
template. It re-proves Task 1's `normalize_data`, nothing more. Delete the false claim
from its docstring ("If either site … is missing, the payload carries no size") and
retitle it to what it actually pins: that the **form and model** preserve a submitted
`size`. The JS sites are pinned by the source-level tests above and, behaviourally, by
Task 9's `test_filltable_size_select_reveals_populates_and_swaps_the_preview` - added
specifically because Task 9's conversion-path test drives the PLAIN table
(`[data-table-editor]`, `table-editor__img`) and nothing else here touches the fill
table's select at all.

- [ ] **Step 10: Commit**

```bash
git add templates/courses/manage/editor/_edit_filltable.html \
        courses/static/courses/js/filltable_editor.js \
        tests/test_filltable_editor_partial.py tests/test_table_css.py
git commit -m "feat(table-cell-images): size select for fill-table image cells"
```

---

## Task 9: Measured e2e — preset geometry and neighbour-text stability

**Files:**
- Create: `tests/test_e2e_table_cell_images.py`

**Interfaces:**
- Consumes: everything above, through a real browser.
- Produces: nothing consumed by later tasks.

**The sizing claims are only real if measured in a browser.** C1's harness traps
transfer verbatim — read them before writing a line:

- **Caps only shrink**, so a bounding-box assertion needs
  `min(hcap, wcap/ratio, naturalHeight)` — without the intrinsic clamp the
  *correct* build fails.
- **`getComputedStyle().width` is the border box** (`reset.css` sets
  `box-sizing: border-box` globally). Measure the wrapper, never a padded container.
- **`_isolated_media` is mandatory, not hygiene** — `live_server`'s
  `_MediaFilesHandler` reads `MEDIA_ROOT` per request, so it is what makes
  `/media/<path>` resolve at all. Pair it with an await-decoded step: an undecoded
  `<img>` legitimately reports `naturalWidth` 0.
- **A request recorder must filter on the URL path**, never the Django URL *name*.
- **`_seed_unit` mints a fresh Course**, and `MediaAsset` is course-scoped.
- The **editor and preview panes are siblings**, so mutating the preview pane is a
  no-op mutant; mutate the editor pane.

- [ ] **Step 1: Copy the harness — five named helpers, not "the harness"**

`tests/test_e2e_image_size.py` (C1, student side) and `tests/test_e2e_table_editor.py`
(editor side) between them already contain everything this task needs. Copy these
**by name** into `tests/test_e2e_table_cell_images.py`:

| helper | source | why it is mandatory |
|---|---|---|
| `_allow_sync_orm_under_playwright` | either file (line ~19/49) | session-scoped autouse fixture setting `DJANGO_ALLOW_ASYNC_UNSAFE`. **Module-local in every `tests/test_e2e_*.py` — it is NOT in any `conftest.py`.** Without it the first ORM call inside a Playwright test raises `SynchronousOnlyOperation` |
| `_isolated_media` | `test_e2e_image_size.py` | `live_server`'s `_MediaFilesHandler` reads `MEDIA_ROOT` **per request**, so this is what makes `/media/<path>` resolve at all — not hygiene |
| `_make_pa_user` + `_login` | either file | a lesson page and an editor page both require an authenticated platform admin; nothing renders anonymously |
| `_lesson_url(live_server, unit)` | `test_e2e_image_size.py:106` | `reverse("courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk})`. **`TableElement` has no `get_absolute_url`** — `courses/models.py` has zero occurrences, so any `el.get_absolute_url()` raises `AttributeError` before the browser is touched |
| `_goto_editor`, `_open_edit` | `test_e2e_filltable.py` (~368, ~398) | the FILL-table opener. `_open_edit(page, element_pk)` locates `.el-act-edit[data-element-id="<pk>"]` and waits for the fill-table root; it needs a prior `_goto_editor`. The plain table's `_reopen` cannot substitute - its wait selector is `[data-table-editor]` |
| `_unit`, `_editor_url`, `_add_table`, `_save`, `_reopen` | `test_e2e_table_editor.py` | the editor-side path. **All five are used:** `_reopen` opens the element edit form (a bare `goto(_editor_url)` lands on the unit BUILDER, where `[data-table-editor]` does not exist), and `_save` + `_reopen` together drive the save/reopen round-trip that pins the two silent image-loss modes |

Also import `add_element` from `tests.factories`: a bare `TableElement.objects.create(...)`
row is **not reachable from any page** — the `Element` join row is what puts it in a unit.

```python
"""Measured browser tests for table cell image sizing (slice C2).

The sizing claims in the spec are only real if measured in a browser. Every trap below
is inherited from C1's harness; read the preamble in this task before changing anything.
"""

import os

import pytest

from courses.models import Element
from courses.models import TableElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

# BOTH markers, module-wide. transaction=True is mandatory, not hygiene: without it the
# live_server thread uses a different connection and cannot see rows created in the test's
# transaction, so every seeded unit/element/asset is simply absent. Every test in
# tests/test_e2e_table_editor.py and tests/test_e2e_image_size.py carries it, and it
# applies to the student-side tests here just as much as the editor-side ones.
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PA_USERNAME = "pa-cellimg"

# The MEASURED reference geometry (spec: "Why sizing is not optional"): a 648px content
# column, five columns, one image cell plus four text cells.
MEDIUM_CAP = 160.0


def _seed_table(unit, *, size, neighbour_text):
    """Attach a 5-column table (image + four text cells) to `unit`.

    This SHAPE is load-bearing. A merely "bounded preset" is not enough — the spec's own
    measurement table shows min(100%, 160px) rendering 112.4px in the 5-col all-images
    shape, still column-bound, and such a shape would fail on the CORRECT build. This is
    the shape where the cap provably binds in BOTH variants.

    add_element() is what makes the element reachable from the lesson page; the asset
    must belong to unit.course, because MediaAsset is course-scoped.
    """
    asset = make_image_asset(unit.course, filename="graph.png", size=(1586, 612))
    row = [{"kind": "image", "media": asset.pk, "alt": "graph", "size": size,
            "halign": "left", "valign": "top"}]
    row += [{"html": neighbour_text, "halign": "left", "valign": "top"}
            for _ in range(4)]
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid", "cells": [row],
    }))
    add_element(unit, el)
    return el, asset


def _rendered_box(page, selector=".cell-img"):
    """The image's rendered box.

    getComputedStyle().width is the BORDER box (reset.css sets box-sizing: border-box
    globally), so measure the <img> itself, never a padded container. Await decode
    first: an undecoded <img> legitimately reports naturalWidth 0.
    """
    page.wait_for_selector(selector)
    return page.evaluate(
        """async (sel) => {
             const img = document.querySelector(sel);
             if (!img.complete) await img.decode();
             const r = img.getBoundingClientRect();
             return {w: r.width, h: r.height,
                     nw: img.naturalWidth, nh: img.naturalHeight};
           }""",
        selector,
    )


def test_medium_preset_is_stable_against_neighbouring_text(
    page, live_server, _isolated_media
):
    """THE one genuinely new assertion: lengthening text in a NEIGHBOURING cell must no
    longer change the image's rendered width. Nothing below the browser layer can
    observe this — it is the whole reason the slice exists."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)

    unit_a = _unit(PA_USERNAME, "c2-short")
    _seed_table(unit_a, size="medium", neighbour_text="ok")
    page.goto(_lesson_url(live_server, unit_a))
    w_short = _rendered_box(page)["w"]

    unit_b = _unit(PA_USERNAME, "c2-long")
    _seed_table(unit_b, size="medium", neighbour_text="a much longer neighbour " * 8)
    page.goto(_lesson_url(live_server, unit_b))
    w_long = _rendered_box(page)["w"]

    assert w_short == pytest.approx(MEDIUM_CAP, abs=1.0)
    assert w_long == pytest.approx(MEDIUM_CAP, abs=1.0)
    assert w_short == pytest.approx(w_long, abs=1.0)


def test_full_is_the_control_and_still_moves(page, live_server, _isolated_media):
    """Asserts the defect is REAL: the same shape at `full` is content-negotiated, so
    lengthening a neighbour SHRINKS the image. Without this control, a broken build that
    pinned every width to a constant would pass the test above.

    DIRECTION only, deliberately no absolute pixel pins. The spec's 426.2/285.7 figures
    were measured on a page, asset and text this fixture does not reproduce, and a +-2px
    assertion on a deliberately content-negotiated width is the one number here that
    cannot be predicted from the CSS.
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)

    unit_a = _unit(PA_USERNAME, "c2-full-short")
    _seed_table(unit_a, size="full", neighbour_text="ok")
    page.goto(_lesson_url(live_server, unit_a))
    w_short = _rendered_box(page)["w"]

    unit_b = _unit(PA_USERNAME, "c2-full-long")
    _seed_table(unit_b, size="full", neighbour_text="a much longer neighbour " * 8)
    page.goto(_lesson_url(live_server, unit_b))
    w_long = _rendered_box(page)["w"]

    assert w_short > MEDIUM_CAP + 50          # `full` is NOT cap-bound
    assert w_long < w_short - 50              # and it MOVES with neighbour text


@pytest.mark.parametrize("natural", [(1586, 612), (494, 1492)])
def test_medium_is_a_square_box_not_a_width(
    page, live_server, _isolated_media, natural
):
    """One preset, comparable visual weight, any aspect ratio: at Medium a 1586x612
    image lands ~160x62 and a 494x1492 one ~53x160."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, f"c2-ratio-{natural[0]}")
    asset = make_image_asset(unit.course, filename="a.png", size=natural)
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "", "size": "medium",
                    "halign": "left", "valign": "top"},
                   {"html": "x", "halign": "left", "valign": "top"}]],
    }))
    add_element(unit, el)
    page.goto(_lesson_url(live_server, unit))
    box = _rendered_box(page)
    # CAPS ONLY SHRINK, so compute the expectation from the same formula the CSS
    # implements, clamped by the intrinsic size. A hard-coded pixel pair would fail on
    # the CORRECT build for any asset smaller than the cap.
    ratio = box["nw"] / box["nh"]
    exp_w = min(MEDIUM_CAP, MEDIUM_CAP * ratio, box["nw"])
    exp_h = min(MEDIUM_CAP, MEDIUM_CAP / ratio, box["nh"])
    assert box["w"] == pytest.approx(exp_w, abs=2.0)
    assert box["h"] == pytest.approx(exp_h, abs=2.0)


def test_a_ta_center_image_cell_centres_its_bounded_image(
    page, live_server, _isolated_media
):
    """halign is text-align on the <td>, which has NO effect on a display:block child.
    With an 80/160/240px cap inside a 648px column the image is almost always narrower
    than its cell, so without the margin rules it would sit flush left whatever the
    author picks — while the align buttons stay enabled and serialize() faithfully writes
    halign. This is the C1 precedent, where centring fit-content figures was exactly this
    class of bug."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-centre")
    asset = make_image_asset(unit.course, filename="a.png", size=(1586, 612))
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "", "size": "medium",
                    "halign": "center", "valign": "top"}]],
    }))
    add_element(unit, el)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".cell-img")
    offsets = page.evaluate(
        """() => {
             const img = document.querySelector('.cell-img');
             const td = img.closest('td');
             const i = img.getBoundingClientRect(), c = td.getBoundingClientRect();
             return {left: i.left - c.left, right: c.right - i.right};
           }"""
    )
    assert offsets["left"] == pytest.approx(offsets["right"], abs=2.0)
    assert offsets["left"] > 2.0        # genuinely inset, not flush left


def test_no_shape_produces_horizontal_scroll(page, live_server, _isolated_media):
    """The min(100%, Npx) arm keeps the CELL a hard ceiling. MEASURED across 32
    shape x treatment combinations, including phone at 296px, with no horizontal scroll
    anywhere."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-scroll")
    _seed_table(unit, size="medium", neighbour_text="a much longer neighbour " * 8)
    for width in (1280, 296):
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(_lesson_url(live_server, unit))
        page.wait_for_selector(".cell-img")
        # Measure the SCROLLER, not the document. tableelement.html wraps the table in
        # `.el--table__scroll`, which courses.css declares `overflow-x: auto` - so no cell
        # image width, not even an unbounded 1586px, can produce document-level overflow.
        # A document-level assertion holds identically on every mutant.
        overflow = page.evaluate(
            """() => {
                 const s = document.querySelector('.el--table__scroll');
                 return s.scrollWidth - s.clientWidth;
               }"""
        )
        assert overflow <= 1, width
```

- [ ] **Step 2: Write the editor-side helpers CONCRETELY, then the editor tests**

Two helpers, both written out — no stubs. `_add_table` produces an **empty 2x2**, so the
four tests that need a saved image cell need a second helper:

```python
def _open_editor_with_empty_table(page, live_server, slug):
    """Seed a unit, log in, add an empty 2x2 table, and return (unit, element, editor)."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, slug)
    element = _add_table(page, live_server, unit)
    return unit, element, page.locator("[data-table-editor]").first


def _open_editor_with_image_cell(page, live_server, slug):
    """Same, but the table is SAVED with one image cell already in it — so the editor
    renders td[data-image] from the server, which is the path the reload-side tests need
    (the stash is empty there, which is the dominant Remove-image case).

    Uses _reopen, NOT a bare goto(_editor_url): `_editor_url` is the unit-BUILDER page,
    and the element's edit form is opened on demand. _reopen does the three things that
    actually make [data-table-editor] exist — waits for [data-scope="editor"], clicks
    [data-element='<pk>'] .el-act-edit, then waits for
    [data-edit-slot] [data-table-editor].
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, slug)
    asset = make_image_asset(unit.course, filename="a.png", size=(1586, 612))
    el = TableElement.objects.create(data=TableElement.normalize_data({
        "header_row": False, "header_col": False, "border": "grid",
        # TWO rows: table_editor.js sets `b.disabled = rows <= 1` on every
        # [data-row-delete], so a one-row table makes the row-delete test time out
        # waiting for an enabled button - a failure on the CORRECT build.
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "seeded alt",
                    "size": "medium", "halign": "left", "valign": "top"},
                   {"html": "text", "halign": "left", "valign": "top"}],
                  [{"html": "r2c1", "halign": "left", "valign": "top"},
                   {"html": "r2c2", "halign": "left", "valign": "top"}]],
    }))
    # add_element RETURNS the Element join row, and _reopen's locator is
    # [data-element='<Element.pk>'] - passing the TableElement's pk makes it miss and the
    # click time out, failing six editor tests on a CORRECT build.
    element = add_element(unit, el)
    _reopen(page, live_server, unit, element)
    return unit, element, page.locator("[data-edit-slot] [data-table-editor]").first
```

**`_reopen` takes the `Element` JOIN ROW, not the concrete element.** Its locator is
`[data-element='<Element.pk>'] .el-act-edit`, and `tests/factories.py`'s
`add_element(unit, obj)` returns exactly that `Element` - so capture it. **`_add_table`
returns `None`** (it ends at `wait_for_selector`) and could not return an element anyway:
the add path is create-on-first-save, so the row appears only after `_save`. Where a test
needs the element after an add, use `Element.objects.get(unit=unit)` post-save, exactly as
`tests/test_e2e_table_editor.py` does.

The `transaction=True` requirement is handled once by the module-level `pytestmark` list
in Step 1, so it applies to **all** fourteen tests here - student-side and editor-side
alike, since every one of them seeds rows and then hits `live_server`.

```python
def test_the_toolbar_is_visible_with_nothing_focused(page, live_server):
    """The discoverability fix: an author opening a table saw a bare grid and no
    controls, with nothing signalling that clicking a cell reveals eighteen of them."""
    _unit_, _el, editor = _open_editor_with_empty_table(page, live_server, "c2-vis")
    assert editor.locator("[data-table-toolbar]").is_visible()


def test_cell_scoped_buttons_are_disabled_before_any_focus(page, live_server):
    """Exhaustive over the predicate table. The five colour swatches are NOT in scope:
    they come from _rte_swatches.html, shared by six toolbars whose editors have no
    `disabled` mechanism, and keep their pre-wire() enabled window by design."""
    _unit_, _el, editor = _open_editor_with_empty_table(page, live_server, "c2-dis")
    for sel in ['[data-cmd="bold"]', '[data-cmd="italic"]', '[data-cmd="underline"]',
                '[data-cmd="math"]', "[data-image-toggle]",
                '[data-halign="left"]', '[data-halign="center"]',
                '[data-halign="right"]', '[data-valign="top"]',
                '[data-valign="middle"]', '[data-valign="bottom"]']:
        assert editor.locator(sel).is_disabled(), sel


def test_clicking_an_image_cell_reveals_and_populates_the_controls(
    page, live_server, _isolated_media
):
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-reveal")
    editor.locator("td[data-image]").first.click()
    assert editor.locator("[data-image-alt]").is_visible()
    assert editor.locator("[data-image-size]").is_visible()
    assert editor.locator("[data-image-remove]").is_visible()
    # POPULATED, not merely shown — a toolbar-level control otherwise displays a stale
    # value from the previously focused image cell.
    assert editor.locator("[data-image-size]").input_value() == "medium"
    assert editor.locator("[data-image-alt]").input_value() == "seeded alt"
    # THE spec-mandated pin, which exists in no other test: "focus an image cell, assert a
    # [data-cmd] button is disabled". Its mutant is writing the isImage derivation BELOW
    # the [data-cmd] loop in refreshToolbarState - `var` hoisting then makes the predicate
    # `!focusCell || undefined` -> falsy -> B/I/U, math and the swatches stay ENABLED on a
    # focused image cell, where clicking math appends a text node that serialize()'s image
    # branch silently discards. Invisible to every source-level test the plan writes.
    assert editor.locator('[data-cmd="bold"]').is_disabled()
    assert editor.locator('[data-cmd="math"]').is_disabled()
    # And the image button must stay ENABLED - it is the re-pick path.
    assert editor.locator("[data-image-toggle]").is_enabled()


def test_conversion_path_populates_without_a_refocus(
    page, live_server, _isolated_media
):
    """THE regression that proves the two-way rewrite landed. The picker path runs
    neither focusin nor (pre-slice) refreshToolbarState, and
    removeAttribute("contenteditable") BLURS the cell rather than re-focusing it — so a
    test that re-focuses cannot see the defect. Never re-focus here."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-convert")
    make_image_asset(unit.course, filename="pickable.png", size=(1586, 612))
    _element = _add_table(page, live_server, unit)
    editor = page.locator("[data-table-editor]").first
    editor.locator("td[contenteditable]").first.click()
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").first.click()
    # NO re-focus, no second click on the cell.
    assert editor.locator("[data-image-size]").is_visible()
    assert editor.locator("[data-image-size]").input_value() == "medium"
    assert editor.locator("[data-image-remove]").is_visible()


def test_changing_size_twice_leaves_exactly_one_modifier_class(
    page, live_server, _isolated_media
):
    """classList.add alone accumulates, and the four modifiers are single-class selectors
    of identical specificity — so the winner would be decided by stylesheet source order
    rather than the author's pick."""
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-twice")
    editor.locator("td[data-image]").first.click()
    for value in ("large", "small"):
        editor.locator("[data-image-size]").select_option(value)
    classes = editor.locator("td[data-image] img").first.get_attribute("class")
    mods = [c for c in classes.split() if c.startswith("table-editor__img--")]
    assert mods == ["table-editor__img--small"]


def test_remove_image_on_a_reloaded_editor_yields_an_empty_cell(
    page, live_server, _isolated_media
):
    """The NO-STASH case is the DOMINANT one, not an edge case: the stash is populated
    only by an in-session conversion, so any author who saves, reloads and then removes a
    server-rendered image cell hits it. A bare `stash.html` would write the string
    "undefined"."""
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-remove")
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-remove]").click()
    cell = editor.locator("td").first
    assert cell.inner_html().strip() == ""
    assert cell.get_attribute("data-image") is None
    assert cell.get_attribute("contenteditable") == "true"


def test_convert_repick_then_remove_restores_the_original_text(
    page, live_server, _isolated_media
):
    """The re-pick data-loss path: setImageCell stashes UNCONDITIONALLY today, so on a
    re-pick s.html is overwritten with the preview <img> markup. Remove image then
    restores an <img> into a contenteditable cell, sanitize_cell strips it to "" at save,
    and the author's original text is permanently and silently lost. Needs TWO assets."""
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-repick")
    make_image_asset(unit.course, filename="one.png", size=(800, 600))
    make_image_asset(unit.course, filename="two.png", size=(800, 600))
    _element = _add_table(page, live_server, unit)
    editor = page.locator("[data-table-editor]").first
    cell = editor.locator("td[contenteditable]").first
    cell.click()
    cell.type("original words")
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").nth(0).click()
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-toggle]").click()          # RE-PICK
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").nth(1).click()
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-remove]").click()
    assert "original words" in editor.locator("td").first.inner_html()


def test_deleting_the_row_holding_the_focused_image_cell_hides_the_controls(
    page, live_server, _isolated_media
):
    """focusCell is never re-nulled by any delete path, so it would keep pointing at a
    DETACHED <td>: the controls stay visible AND populated, and edits write to a node no
    longer in the grid — silently lost at the next serialize()."""
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-del")
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-row-delete]").first.click()
    assert editor.locator("[data-image-size]").is_hidden()
    assert editor.locator("[data-image-remove]").is_hidden()


def test_filltable_size_select_reveals_populates_and_swaps_the_preview(
    page, live_server, _isolated_media
):
    """The ONLY executed coverage for the half of the slice Task 8 exists to ship.

    Task 8's other tests are all source-scanners (`"size:" in seg`), and its form/model
    round-trip never runs JS. Nothing else in this module touches the FILL table — the
    conversion-path test above drives [data-table-editor] and asserts
    `table-editor__img`, i.e. the plain table. Without this test, the "reverts every image
    cell to `full` on every save" defect class Task 8 names has no behavioural pin.

    Seed a fill table with an image cell AND an answer cell (FillTableElementForm requires
    at least one answer cell, so an image-only grid cannot be saved), then use
    tests/test_e2e_filltable.py's _goto_editor + _open_edit(page, element_pk) - NOT the
    plain table's _reopen, whose wait selector is [data-table-editor].
    """
    from courses.models import FillTableElement

    # NO explicit _login here: _goto_editor calls _login itself (unlike the plain
    # table's _reopen). A second login navigates to /accounts/login/ while already
    # authenticated, allauth redirects to LOGIN_REDIRECT_URL, the login form never
    # appears, and the fill() times out - on a fully correct build.
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-fill-size")
    asset = make_image_asset(unit.course, filename="f.png", size=(1586, 612))
    el = FillTableElement.objects.create(data=FillTableElement.normalize_data({
        "prompt": "", "case_sensitive": False, "header_row": False,
        "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": asset.pk, "alt": "",
                    "size": "medium", "halign": "left", "valign": "top"},
                   {"kind": "answer", "answer": "x",
                    "halign": "left", "valign": "top"}]],
    }))
    element = add_element(unit, el)
    # NOT _reopen: it ends `wait_for_selector("[data-edit-slot] [data-table-editor]")`,
    # hard-wired to the PLAIN table root. _edit_filltable.html renders
    # `data-filltable-editor` and never `data-table-editor` (the two roots are disjoint -
    # which is also what makes Task 7's pick.closest("[data-table-editor]") dispatch
    # correct), so _reopen would time out here on a fully correct build.
    _goto_editor(page, live_server, PA_USERNAME, unit)
    _open_edit(page, element.pk)
    editor = page.locator("[data-edit-slot] [data-filltable-editor]").first

    editor.locator("td[data-image]").first.click()
    assert editor.locator("[data-image-size]").is_visible()
    assert editor.locator("[data-image-size]").input_value() == "medium"

    # Same spec-mandated pin for the FILL table, whose predicate additionally ORs
    # isAnswer - and whose derivations Task 6 Step 5 hoists above the deleted early
    # return. Both files need it; neither had it.
    assert editor.locator('[data-cmd="bold"]').is_disabled()
    assert editor.locator("[data-answer-toggle]").is_enabled()   # focus exists

    editor.locator("[data-image-size]").select_option("small")
    classes = editor.locator("td[data-image] img").first.get_attribute("class")
    mods = [c for c in classes.split() if c.startswith("filltable-editor__img--")]
    assert mods == ["filltable-editor__img--small"]


def test_typing_in_the_alt_input_updates_the_cell_and_the_preview(
    page, live_server, _isolated_media
):
    """The plain table's alt-input listener is created FROM SCRATCH in Task 7 Step 8 item 4
    (`table_editor.js` has zero occurrences of `imageAlt` today), and nothing else in the
    plan exercises it - the reveal test pins refreshToolbarState's POPULATION, not the
    listener. The fill table's twin is already covered by
    tests/test_e2e_filltable.py::test_author_two_image_cells_with_distinct_alts, so the
    plain table was the only unguarded side.

    The preview assertion is the load-bearing half: it catches an implementer copying the
    fill table's `.filltable-editor__img` lookup verbatim, which is exactly the divergence
    the plan flags.
    """
    _unit_, _el, editor = _open_editor_with_image_cell(page, live_server, "c2-alt")
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-image-alt]").fill("a new description")
    td = editor.locator("td[data-image]").first
    assert td.get_attribute("data-alt") == "a new description"
    assert td.locator("img").get_attribute("alt") == "a new description"


def test_header_toggle_then_remove_image_restores_the_stashed_text(
    page, live_server, _isolated_media
):
    """toggleHeaderCell builds a NEW element and calls td.replaceWith(next); attributes are
    copied but a Map stash key is not, so without Task 7 Step 8 item 9's re-keying the stash
    is orphaned and Remove image restores "" instead of the author's text. Silent data loss
    on a reachable path - [data-header-toggle] is enabled whenever a non-locked cell is
    focused - and test_editor_twin_drift.py cannot see it (toggleHeaderCell stays DIVERGENT).
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-hdr")
    make_image_asset(unit.course, filename="h.png", size=(800, 600))
    _add_table(page, live_server, unit)
    editor = page.locator("[data-edit-slot] [data-table-editor]").first
    cell = editor.locator("td[contenteditable]").first
    cell.click()
    cell.type("stashed words")
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").first.click()
    editor.locator("td[data-image]").first.click()
    editor.locator("[data-header-toggle]").click()
    editor.locator("th[data-image]").first.click()
    editor.locator("[data-image-remove]").click()
    assert "stashed words" in editor.locator("th").first.inner_html()


def test_an_image_cell_survives_a_save_and_reopen(page, live_server, _isolated_media):
    """THE pin for the slice's two silent data-loss modes, neither of which had a
    behavioural test before:

      * serialize() reading a bare `td.dataset.media` (a STRING) instead of
        parseInt(..., 10) - _cell requires isinstance(media, int), so the cell degrades
        to empty text on save;
      * the template emitting data-media="{{ cell.media }}" instead of `.pk` - which
        renders "MediaAsset object (5)", parseInt yields NaN, JSON.stringify writes null.

    Both pass every server-side test that constructs data directly. Only a real
    convert -> save -> reopen cycle catches them.
    """
    _make_pa_user(PA_USERNAME)
    _login(page, live_server, PA_USERNAME)
    unit = _unit(PA_USERNAME, "c2-roundtrip")
    asset = make_image_asset(unit.course, filename="rt.png", size=(1586, 612))
    # _add_table returns None and CANNOT return an element: the add path is
    # create-on-first-save, so no Element row exists until _save(page).
    _add_table(page, live_server, unit)
    editor = page.locator("[data-edit-slot] [data-table-editor]").first
    editor.locator("td[contenteditable]").first.click()
    editor.locator("[data-image-toggle]").click()
    page.wait_for_selector(".picker-overlay")
    page.locator(".picker-overlay .asset-pick").first.click()
    _save(page)

    # Stored shape: a real int pk, not None and not a degraded text cell.
    element = Element.objects.get(unit=unit)     # needs `from courses.models import Element`
    cell = element.content_object.data["cells"][0][0]
    assert cell["kind"] == "image"
    assert cell["media"] == asset.pk
    assert cell["size"] == "medium"          # the editor-insert default

    # And it comes back as an image cell in the editor, with data-media as the pk.
    _reopen(page, live_server, unit, element)
    reopened = page.locator("[data-edit-slot] [data-table-editor]").first
    td = reopened.locator("td[data-image]").first
    assert td.get_attribute("data-media") == str(asset.pk)
    assert td.get_attribute("data-size") == "medium"


def test_a_row_insert_before_any_focus_does_not_throw(page, live_server):
    """The bare !focusCell.isConnected mutant, and the ONLY test that can catch it:
    focusCell is null until the first focusin, and the row handles are hover-revealed
    chrome reachable from page load. A TypeError there aborts the handler and leaves the
    grid half-edited and UNSERIALIZED. Note tests/test_e2e_table_editor.py cannot catch
    this — both its scenarios click and type into a cell before inserting a row."""
    # Arm the listener AFTER setup: _open_editor_with_empty_table performs the allauth
    # login and two navigations, and an unrelated JS error on either page would fail this
    # test with a message pointing at the disconnect predicate.
    _unit_, _el, editor = _open_editor_with_empty_table(page, live_server, "c2-insert")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    editor.locator("[data-row-insert]").first.click()
    assert errors == []
```

Confirm the `[data-row-insert]` / `[data-row-delete]` selectors and `.picker-overlay
.asset-pick` against `tests/test_e2e_table_editor.py` and
`tests/test_e2e_filltable.py::make_image_cell` before the first run — those two files
already drive both.

- [ ] **Step 3: Run and confirm the measurements**

Run: `uv run pytest -m e2e tests/test_e2e_table_cell_images.py -v`
Expected: PASS. If a Medium width is off by more than 1px, **do not widen the
tolerance** — re-measure and correct the spec's table. (The `full` control asserts
direction only, so it has no number to drift.)

Also run: `uv run ruff check tests/test_e2e_table_cell_images.py`

- [ ] **Step 4: Falsify — six mutants, all required RED**

Three are deferred here from Tasks 6 and 7, whose own tasks have no browser-level
falsifier for them:

1. **CSS.** Change `.cell-img--medium`'s `max-width` to `50%` and re-run
   `test_medium_preset_is_stable_against_neighbouring_text`.
   Expected: FAIL (the width moves with neighbour text). Restore.
1b. **`serialize()`'s media read** (deferred from Task 7). Change `media:` to the bare
   `td.dataset.media` and run `test_an_image_cell_survives_a_save_and_reopen`.
   Expected: FAIL — `_cell` requires an `int`, so the cell degrades to empty text and the
   stored `kind` is gone. Restore `parseInt(td.dataset.media, 10)`.
1c. **The template's `data-media`** (deferred from Task 7). Change it to
   `{{ cell.media }}` and run the same test.
   Expected: FAIL — `parseInt("MediaAsset object (5)")` is `NaN` → `media: null`. Restore `.pk`.
1d. **The stash guard** (deferred from Task 7). Remove
   `if (!td.hasAttribute("data-image"))` from `setImageCell` in **both** editors and run
   `test_convert_repick_then_remove_restores_the_original_text`.
   Expected: FAIL — Remove image restores the preview `<img>` markup instead of the
   author's text. Restore.
2. **The disconnect predicate** (deferred here from Task 6, which has no falsifier for
   it). Change `focusCell && !focusCell.isConnected` to the bare
   `!focusCell.isConnected` in **both** editors and run
   `test_a_row_insert_before_any_focus_does_not_throw`.
   Expected: FAIL with a `TypeError` captured by the `pageerror` listener. Restore.
3. **The alignment rules.** Delete `.ta-center > .cell-img { margin-inline: auto; }` and
   run `test_a_ta_center_image_cell_centres_its_bounded_image`.
   Expected: FAIL (`offsets["left"]` collapses to ~0). Restore.
4. **The modifier-removal loop** (Task 7 Step 8 item 5). Delete the
   `Object.keys(CELL_IMG_CLASS).forEach(... classList.remove ...)` loop, keeping the
   `add`, and run `test_changing_size_twice_leaves_exactly_one_modifier_class`.
   Expected: FAIL - two modifiers accumulate. Restore. (That loop was written with a
   "REMOVE all four first" comment precisely because it is easy to omit.)
5. **The plain table's picker repaint** (Task 7 Step 7). Remove `refreshToolbarState();`
   from the plain table's registry callback and run
   `test_conversion_path_populates_without_a_refocus`.
   Expected: FAIL - the controls stay hidden. Restore. (Task 6's Mutant 2 covers only
   `libliFillTablePickImage`, so the plain table's callback was unpinned.)
6. **The `[data-cmd]` derivation position** (Task 6 Steps 5/5b). Move the `var isImage`
   derivation BELOW the `[data-cmd]` loop in one editor's `refreshToolbarState` and run
   `test_clicking_an_image_cell_reveals_and_populates_the_controls` (plain) or
   `test_filltable_size_select_reveals_populates_and_swaps_the_preview` (fill).
   Expected: FAIL - `var` hoisting leaves the predicate falsy, so `[data-cmd="bold"]`
   stays enabled on a focused image cell. Restore.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_table_cell_images.py
git commit -m "test(table-cell-images): measured preset geometry and stability"
```

---

## Task 10: Release deliverables — screenshots, i18n catalog, author manuals

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`, and both tracked `.mo`
- Modify: `docs/help/course-admin/content-editors.md`, `content-editors.pl.md`, `interactive-elements.md`, `interactive-elements.pl.md`

**Interfaces:** consumes the shipped UI; produces nothing code-facing.

**This task must be LAST.** All three deliverables touch files once, at the end:
regenerating the catalog early produces a binary `.mo` conflict that cannot be
merged by hand, and the manuals must describe the shipped behaviour rather than an
intermediate state. The precedent is one commit doing all of it — `356c956e`
carried `content-editors.{md,pl.md}` *and*
`locale/{en,pl}/LC_MESSAGES/django.{po,mo}` together.

- [ ] **Step 1: Light + dark screenshots**

Capture and **judge dark mode separately** (that deferral is how the fill table
shipped its dark-mode contrast bug). An editor page must link **both**
`courses.css` and `editor.css` to render faithfully. Required shots:
1. Student table with Small/Medium/Large/Full image cells, light and dark.
2. Plain-table editor with an image cell focused (per-cell controls visible).
3. **An existing fill-table with an image cell, reopened** — its preview jumps from
   a uniform 120px thumbnail to up to 200×200, so the editing grid visibly reflows
   for content nobody edited. Accepted consequence; see it rather than discover it.

- [ ] **Step 2: Regenerate the i18n catalog**

Exactly **two** brand-new msgids (verified absent from `locale/pl/…/django.po`):
`Image size` and `Remove image`.

```bash
uv run python manage.py makemessages -l en -l pl
```

Then, in both `.po` files: supply natively-checked Polish for the two strings, and
**clear any `#, fuzzy` flag** — `makemessages` pre-fills a wrong translation from a
near neighbour, and clearing it is **two** deletions (the flag line *and* the bogus
`msgstr`).

```bash
uv run python manage.py compilemessages
```

Confirm both **tracked** `.mo` files changed. `aa87f643` is a cautionary
counter-example: it carried the manuals and both `.po` files but **no `.mo`**, so
its new string shipped uncompiled.

Everything else deliberately **reuses existing msgids**, so no other entry should
change: the four `CellImageSize` labels share `ImageElement.Size`'s entries
(`Small`/`Medium`/`Large` bare, plus `msgctxt "image size"` + `Full`), and the alt
input's `aria-label` reuses `Image description (alt)`. If `makemessages` wants to
change anything else, investigate before accepting it.

- [ ] **Step 3: Verify the msgid reuse held**

```bash
uv run pytest tests/test_table_cell_images.py::test_full_label_carries_the_image_size_gettext_context -v
grep -c 'msgctxt "image size"' locale/pl/LC_MESSAGES/django.po
```

Expected: the test PASSES and the `"image size"` context appears **once** (shared with
`ImageElement.Size`), not twice. That test is written in Task 1; an earlier draft pointed
this step at `tests/test_table_css.py -k "gettext or image_size"`, which matches nothing
there and exits 5 - "no tests ran", read as a pass.

- [ ] **Step 4: `content-editors.md` + `.pl.md`**

Add the Table's image cells and the Size scale (C1 added its Size paragraph to
exactly this file). **And reword the now-false framing** — line 73 reads
"a WYSIWYG grid editor: **click a cell to edit** its rich text", and `.pl.md`
line 77 "kliknij komórkę, aby edytować jej". The toolbar is no longer
focus-revealed; it is always visible with cell-scoped controls disabled until a
cell is focused. That change *is* the discoverability fix, so leaving this entry
describing the old behaviour would document the bug rather than the feature.

- [ ] **Step 5: `interactive-elements.md` + `.pl.md`**

Add **only** the fill-in table's new Size select. This entry needs **no** toolbar
rewording: its Fill-in table section opens by *delegating* the shared controls to
the Table page ("the same grid, header-row/column, border, and cell merge/split
controls as [Table](content-editors)") and contains no "click a cell" wording in
either language. Do **not** invent a paragraph in order to reword it.

- [ ] **Step 6: Commit**

```bash
git add locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo \
        locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo \
        docs/help/course-admin/content-editors.md \
        docs/help/course-admin/content-editors.pl.md \
        docs/help/course-admin/interactive-elements.md \
        docs/help/course-admin/interactive-elements.pl.md
git commit -m "docs(table-cell-images): author manuals and translation catalogs"
```

- [ ] **Step 7: Branch gate — full suite**

Only now, as a branch-level gate rather than a per-task step:

```bash
uv run pytest -v
uv run pytest -m e2e -v
uv run ruff check .
```

Expected: PASS. Note the e2e teardown deadlock: on `SQLSTATE 40P01` retry rather
than treating it as a failure, and never run two pytest invocations concurrently
across worktrees.

---

## Cross-task reference: stale artifacts

Every entry is a Definition-of-Done item on the named task. Only three live inside
test files and **none** of them reddens a test, which is exactly why they need
enumerating rather than trusting to a red suite.

| artifact | task |
|---|---|
| `TableElement` class docstring — "{html, halign, valign} cells" | 1 |
| `TableElement._sanitized_data` docstring — "Sanitise every cell's html" | 1 |
| `FillTableElement.resolve_image_cells` docstring — span-dropping rationale | 2 |
| `FillTableElementForm.resolved_grid_cells` docstring — same rationale | 2 |
| `test_unresolvable_image_cell_drops_spans_…` — **name** and docstring | 2 |
| `_element_mids` docstring — "every other media-bearing type reads the scalar `media`" | 5 |
| `_val_table` in-body comment — "Unified per-cell shape check (BOTH branches)" | 5 |
| `test_table_transfer.py` comment — "(4 <= FORMAT_VERSION=7)" (inert) | 5 |
| `courses/recolour/dbscan.py` comment - "TableElement cells carry no `kind` at all, so the guard is a no-op there" | 1 |
| `test_editor_twin_drift.py` docstring counts + `TWINS` inline comment | 6 |
| five `DIVERGENT` reason strings | 6 (`refreshToolbarState` only), 7 (the other four) |
| `filltable_editor.js` `// fill-table only` on `cellStash.clear()` | 6 |
| `table_editor.js` comment above `absorbedNonEmpty` — "has no kinds" | 7 |
| `toggleHeaderCell` comment — "no such map in this file's scope" | 7 |
| `filltable_editor.js` `toggleHeaderCell` — "cellStash is LIVE here (unlike table_editor.js's no-op guard)" | 7 |
| `editor.html` imagezoom comment — "image/gallery/fill-table templates" | 7 |
| `filltable_editor.js` `setImageCell` header comment | 8 |

`courses/recolour/` needs **no behavioural change**: `source.py` emits
`cell.get("html")` and `dbscan.py` guards with
`if cell.get("kind") not in (None, "static"): continue`, which correctly skips an
image cell. Only that comment goes stale. `_table_has_math` reads
`cell.get("html", "")`, so an image cell with no `html` key cannot raise there —
verified, no change needed.

## Non-goals (do not implement)

- Elements nested inside a table cell. A cell is not an element slot.
- Image **and** text in the same cell. A cell is a slot; mixed content
  reintroduces the content-negotiated width instability the presets remove.
- Widening `CELL_TAGS` to allow a raw `<img>`.
- Any data migration or parser change. `TableElement.data` is already a `JSONField`.
- Bringing cell images into media usage tracking. `_MEDIA_REF_MODELS` lists only
  FK-bearing models, so a JSON-referenced cell image reports **0 uses** and
  `delete_asset` will delete an asset a table is displaying. This is pre-existing
  and identical for gallery and fill-table cell images; the render fallback is the
  accepted mitigation. Do **not** "fix" it inside this slice.
- Making the presets meaningful on a phone. At 296px a 5-column table renders
  ~42px images whatever preset is chosen — geometry, not a bug; tap-to-enlarge
  already covers it.
