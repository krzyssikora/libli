# Table content element

## Purpose

Course creators need a way to insert a **styled table** into a lesson unit. Today the only route to
tabular content is the raw-HTML escape hatch (`HtmlElement`), which is unsafe to hand to
non-technical authors and renders in a sandboxed iframe. This feature adds a first-class `table`
content element with an author-friendly WYSIWYG editor and a clean student-facing render.

Scope of "basic styling", as agreed during brainstorming:

- **Structure** — a grid of rows × columns; add/remove rows and columns.
- **Header row** and **header column** (leftmost) — two independent toggles. Header cells get
  auto-emphasis (bold + subtle shading) and a divider separating them from the body.
- **Alignment** — per cell: horizontal (`left` / `center` / `right`) and vertical
  (`top` / `middle` / `bottom`).
- **Borders** — one table-level preset: `grid` (all cell borders) / `rows` (horizontal lines only) /
  `header` (only the header row/column dividers) / `none`. Header dividers always render when their
  toggle is on, regardless of the preset.
- **Text formatting inside cells** — **bold / italic / underline** on selected text, plus inline
  **LaTeX** math (`\(...\)` inline, `\[...\]` display) that renders on the student view.

This is **slice 1 of 3** new content elements (table → image gallery → tabs wrapper). The table is
self-contained; nothing here couples to the later slices.

### Out of scope (YAGNI)

Merged cells (colspan/rowspan), links inside cells, per-cell background colours, and any rich
content in cells beyond B/I/U + LaTeX. These can be revisited later if a real need appears.

### Deferred to the end

Functional/basic CSS is written during the build. The **polished** visual design of the four border
presets, header shading, and the editor toolbar is applied as a final step via the `frontend-design`
skill (an explicit user request), after the element works end-to-end.

## Background: how content elements work in this codebase

(Established by codebase exploration; captured here so the plan and reviewers share the model.)

- An **`Element`** row (`courses/models.py`) is a generic-FK join-row in a unit's ordered element
  list, pointing at one concrete per-type model. Each concrete type subclasses **`ElementBase`** and
  declares `elements = GenericRelation(Element)`.
- `ElementBase.render()` renders `courses/elements/<model_name>.html` by naming convention.
- There is **no single registry**. A new element type must be added to ~10 places in lockstep
  (enumerated under "Plumbing" below). Migration `courses/migrations/0032_slidebreakelement_*` is the
  template for the model-plus-`AlterField` migration shape.
- Two key key-styles: **`model_name`** = lowercased class name (`tableelement`), used for render
  templates and list labels; **`type_key`** = `model_name` minus the `element` suffix (`table`), used
  for editor forms/templates, the add-menu, and save/add dispatch. The transfer subsystem uses a
  third, snake_case key — here also `table`.
- Math is rendered **client-side** by KaTeX (`courses/static/courses/js/math.js`), gated on a
  server-computed `has_math` flag (`courses/views.py`) that scans element bodies via
  `has_math_delimiters()` (`courses/htmlsandbox.py`). Delimiters are `\(...\)` / `\[...\]`
  everywhere; `$...$` is **not** recognised and must not be introduced.
- Inline math already renders inside `.el--text` rich text via `renderMathInElement` with
  `INLINE_DELIMS`. Table cells reuse this exact mechanism.
- The B/I/U toolbar (`courses/static/courses/js/text_toolbar.js`) is `document.execCommand`-based and
  operates on whatever contenteditable holds the selection. The MathLive inserter
  (`window.libliMathInput.open(cb)`) is a generic global. Both are reused by the table editor.

## Architecture / components

### 1. Model — `TableElement` (`courses/models.py`)

```python
class TableElement(ElementBase):
    data = models.JSONField(default=dict)
    elements = GenericRelation(Element)
```

`data` shape (validated — see Error handling):

```json
{
  "header_row": false,
  "header_col": false,
  "border": "grid",
  "cells": [
    [ {"html": "", "halign": "left", "valign": "top"}, ... ],
    ...
  ]
}
```

- `cells` is a rectangular row-major 2-D array (every row the same length).
- `border` ∈ {`grid`, `rows`, `header`, `none`}.
- `halign` ∈ {`left`, `center`, `right`}; `valign` ∈ {`top`, `middle`, `bottom`}.
- `html` is the sanitised cell HTML (see below); LaTeX lives inside it as plain text.

Add `"tableelement"` to `ELEMENT_MODELS`. The model rides the **generic single-model save path**
(`builder.py` `FORM_FOR_TYPE[type_key]`) — no custom `save_element` branch (contrast with
choice/matchpair which have sub-tables).

**Sanitisation** happens in the form's `clean` / model `save`, not in the template: the stored
`html` is already restricted to `<strong>/<em>/<u>/<br>`. A new helper in `courses/sanitize.py`:

```python
CELL_TAGS = {"strong", "em", "u", "br"}
def sanitize_cell(value):
    return nh3.clean(value or "", tags=CELL_TAGS, attributes={}, ...)
```

`sanitize_html`'s existing signature is preserved; `sanitize_cell` is additive. LaTeX `\(...\)`
survives because it is text, not tags.

### 2. Render (student view) — `templates/courses/elements/tableelement.html`

Emits a real semantic `<table>` inside an `overflow-x:auto` wrapper (mobile horizontal scroll):

- `class="el el--table el--table--border-<border>"` on a wrapper; the preset drives borders in CSS.
- Row 0 cells become `<th scope="col">` when `header_row`; column 0 cells become `<th scope="row">`
  when `header_col`; the `header_row`×`header_col` corner is a `<th>`.
- Each cell gets alignment via classes (e.g. `ta-left va-middle`) — **not** inline styles, to keep
  CSP-friendliness and themeability.
- Cell `html` is emitted through the existing `|sanitize`-style path but using the **cell** allowlist
  (either a `sanitize_cell` template filter or pre-sanitised-at-save so the template can mark safe).
  Decision: sanitise **at save**, and the template emits the stored html with `|safe` — matching how
  the model already sanitises `TextElement.body` at save. (The template must never emit unsanitised
  author input.)

A new CSS file (or a section in the elements stylesheet) styles the four presets + header emphasis.
Basic during build; polished via `frontend-design` at the end.

### 3. Math typesetting

- **Student view:** extend `math.js` so the inline `renderMathInElement` pass also covers table cells
  — add `.el--table` (or a `.el--table td`/`th` selector) alongside `.el--text` in `renderInlineText`
  (same `INLINE_DELIMS`).
- **has_math gating:** extend the `has_math` computation in `courses/views.py` so a `TableElement`
  whose any cell `html` contains `\(` or `\[` sets `has_math` (so KaTeX assets load). Reuse
  `has_math_delimiters()` against the concatenation of cell htmls.
- **Editor preview:** after an editor fragment swap, re-typeset like `editor.js:applyFragments` does
  (call `renderMathInElement` over the preview subtree).

### 4. Editor — `_edit_table.html` + `courses/static/courses/js/table_editor.js`

- `templates/courses/manage/editor/_edit_table.html` is auto-included by `_host_form.html` via
  `type_key`. It renders: a **controls strip** (header-row toggle, header-column toggle, border-preset
  `<select>`), the **grid** of `contenteditable` cells, and a hidden field carrying the serialised
  `data` JSON that the form binds to.
- `table_editor.js` progressively enhances the grid:
  - **Pinned per-cell toolbar** shown/updated on cell focus: B / I / U (reuse `applyCmd` +
    `[data-cmd]` delegation from `text_toolbar.js`, treating the focused cell as the active surface),
    horizontal-align buttons, vertical-align buttons, and an **insert-math** button that calls
    `window.libliMathInput.open(cb)` and inserts a `\(latex\)` text node at the caret (copy the RTE
    `math` command pattern).
  - **Row/column controls:** hover the top edge of a column / left edge of a row → insert (＋) /
    delete (✕) handles; append affordances at the far right / bottom edges.
  - On every mutation (typing, formatting, structural change, alignment, toggles, preset) it
    re-serialises the grid to the hidden JSON field so a normal form submit persists it. Cell html is
    read from each cell's `innerHTML`; final authoritative sanitisation is server-side.
- The editor's B/I/U and math reuse existing globals; no new toolbar engine.

### 5. Plumbing (all updated in lockstep)

1. `courses/models.py` — `TableElement` + `"tableelement"` in `ELEMENT_MODELS`.
2. Migration — `CreateModel(TableElement)` **and** `AlterField` on `Element.content_type` to refresh
   `limit_choices_to` (template: migration `0032`).
3. `courses/element_forms.py` — `TableElementForm(ModelForm)` (validates/sanitises `data`) + entry in
   `FORM_FOR_TYPE` keyed `"table"`.
4. `templates/courses/manage/editor/_edit_table.html` — editor partial.
5. `templates/courses/elements/tableelement.html` — render partial.
6. `courses/views_manage.py` — `"table"` in `_EDITOR_TYPE_LABELS`, the `element_add` allowed-tuple,
   and the `element_save` allowed-tuple.
7. `templates/courses/manage/editor/_add_menu.html` — `data-add-type="table"` card, plus a
   `<symbol id="el-table">` icon in `templates/courses/manage/_icon_sprite.html`.
8. `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS["tableelement"] = "Table"` and
   an `element_summary` branch (e.g. `"3×4 table"`).
9. Transfer — `SERIALIZERS` (`courses/transfer/export.py`), `VALIDATORS`
   (`courses/transfer/payloads.py`), `BUILDERS` (`courses/transfer/importer.py`), all keyed `"table"`.

## Data flow

**Authoring:** creator clicks the "Table" card in the add-menu → `_edit_table.html` loads a default
grid (e.g. 2×2, no headers, `grid` border) → author types into cells, formats text, toggles headers,
picks a border, adds/removes rows/cols → `table_editor.js` keeps the hidden `data` JSON in sync →
form submit → `TableElementForm` validates + sanitises each cell → `TableElement.data` saved →
`Element` join-row created/updated. The generic `FORM_FOR_TYPE["table"]` path handles save.

**Consumption:** student opens the unit → `_lesson_article.html` loops elements →
`{% render_element el %}` → `TableElement.render()` → `tableelement.html` emits the `<table>` →
if any cell has math delimiters `has_math` was set server-side so KaTeX loaded → `math.js` runs
`renderMathInElement` over `.el--table` cells → math typesets.

**Transfer:** export serialises `data` verbatim; import validates the payload shape then rebuilds a
`TableElement`. Round-trips through the same JSON.

## Error handling

- **Server-side validation (`TableElementForm`)** is authoritative:
  - `data` must be a dict with `cells` a non-empty rectangular 2-D list; each row equal length;
    at least 1×1.
  - `border` coerced to the allowed set (default `grid` on invalid); `halign`/`valign` coerced to
    allowed sets (default `left`/`top`); `header_row`/`header_col` coerced to bool.
  - Each cell `html` passed through `sanitize_cell` — anything outside `<strong>/<em>/<u>/<br>` is
    stripped. Malicious/rich markup can never reach the DB or the render template.
  - Reject (form error) rather than silently truncate on structurally invalid payloads (e.g. `cells`
    not a list); coerce on merely out-of-range enum values.
- **Rendering is defensive:** the template tolerates a legacy/empty `data` (missing keys → sensible
  defaults, empty grid → renders nothing or an empty table without erroring). No `500` on odd data.
- **Transfer import** re-validates with the same rules before building; a malformed imported payload
  fails the import validation cleanly (consistent with other element validators), never a crash.
- **Math:** `renderMathInElement` uses `throwOnError: false` (existing behaviour), so bad LaTeX in a
  cell renders as-is rather than breaking the page.

## Testing

Follow the repo's TDD conventions; `uv run` for `ruff`/`pytest`/`python`; run **both** `ruff check`
and `ruff format --check`. Use `tests.factories.TEST_PASSWORD` — never hardcode passwords. If any
translatable strings are removed during the build, run the i18n catalog tests in the DoD.

Test coverage to write:

- **Model / sanitisation:** `sanitize_cell` strips disallowed tags, keeps `strong/em/u/br`, preserves
  `\(...\)` text. `TableElement.render()` produces a `<table>` with correct `<th>` placement for each
  header-toggle combination and correct alignment/border classes.
- **Form validation:** valid payload saves; ragged/empty/non-list `cells` rejected; out-of-range
  `border`/`halign`/`valign` coerced to defaults; cell html sanitised on save.
- **has_math gating:** a unit whose table cell contains `\(x\)` sets `has_math` (KaTeX loads); a
  table with no delimiters does not.
- **Editor plumbing:** the add-menu exposes the Table card; `element_add`/`element_save` accept
  `type=table`; `_edit_table.html` renders for a new and an existing table; `element_summary` and the
  list label show sensibly.
- **Transfer round-trip:** export → import of a course containing a table reproduces an equivalent
  `TableElement` (headers, border, alignments, cell html all preserved).
- **JS (per repo convention):** if there is an existing JS test harness, cover the serialise
  round-trip and B/I/U/align/structural mutations; otherwise rely on an e2e/Playwright path that
  drives the real editor (add a table, format a cell, toggle a header, save, reload, consume). Drive
  the real gesture — do not shortcut via `page.evaluate`.
- **Consumption render test / screenshot** for the four border presets × header combinations
  (feeds the final `frontend-design` pass).
