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
- The RTE B/I/U toolbar (`courses/static/courses/js/text_toolbar.js`) is `document.execCommand`-based,
  but its `applyCmd` helper is a **private IIFE function — not an exported global**. The table editor
  therefore does **not** import it; it implements its own thin B/I/U handlers, which are one-liners
  (`document.execCommand("bold"|"italic"|"underline")`) acting on the focused cell. Note that
  `execCommand("bold"/"italic")` emits **`<b>`/`<i>`** (not `<strong>`/`<em>`) in Chromium/Firefox —
  which is why the cell allowlist must include `b`/`i` (see §1). The MathLive inserter
  (`window.libliMathInput.open(cb)`) *is* a generic global and is reused directly.

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

**Sanitisation** happens in the form's `clean` / model `save`, not in the template: the stored `html`
is already restricted to the cell allowlist. A new helper in `courses/sanitize.py`:

```python
# Includes b/i as well as strong/em because document.execCommand("bold"/"italic")
# emits <b>/<i> in Chromium/Firefox — mirroring the existing ALLOWED_TAGS pairing.
CELL_TAGS = {"strong", "b", "em", "i", "u", "br"}

def sanitize_cell(value):
    return _sanitize_preserving_math(value or "", tags=CELL_TAGS)
```

`sanitize_html`'s existing signature and behaviour are preserved; `sanitize_cell` is additive with
**no** allowed attributes and **no** allowed URL schemes (cells carry no links/attrs). Spell out the
full `nh3.clean(value, tags=CELL_TAGS, attributes={}, url_schemes=set(), link_rel=None,
strip_comments=True)` call in the implementation rather than an ellipsis.

**Math must be protected from the HTML tokenizer (critical correctness point).** `nh3.clean` runs a
real HTML tokenizer, so raw LaTeX is **not** universally safe as text: `\(a<b\)` tokenizes `<b` as a
start tag and the sanitizer drops it — corrupting extremely common inequalities like `\(x<5\)`, and
MathLive emits a literal `<`. Therefore `_sanitize_preserving_math` must **extract each properly-closed `\(...\)` and
`\[...\]` span into a placeholder before `nh3.clean`, then restore them verbatim after**. Rules to
pin in the implementation:

- **Only balanced pairs are protected, matched non-greedily, no nesting:** a `\(` pairs with the next
  `\)` (and `\[` with the next `\]`). An **unmatched** opener or closer (a lone `\(`, or a stray `\)`
  first) is **not** protected — it is left as literal text and sanitized normally. A test covers a
  cell containing a single unmatched `\(`.
- **Placeholder tokens carry a per-invocation random nonce** (or use codepoints the sanitizer strips
  from ordinary text) so they cannot collide with a token the author literally typed as cell content,
  which would otherwise make the restore step wrongly replace author text with math.

This makes the "LaTeX survives" guarantee actually hold for `<`/`>` inside balanced math. Non-math
`<`/`>` typed as literal text outside math delimiters is still HTML-escaped/stripped by the sanitizer,
which is correct.

### 2. Render (student view) — `templates/courses/elements/tableelement.html`

Emits a real semantic `<table>` inside an `overflow-x:auto` wrapper (mobile horizontal scroll):

- `class="el el--table el--table--border-<border>"` on a wrapper; the preset drives borders in CSS.
- Row 0 cells become `<th scope="col">` when `header_row`; column 0 cells become `<th scope="row">`
  when `header_col`; the `header_row`×`header_col` corner is a `<th>` with **no `scope` attribute**
  (it heads neither a single row nor a single column — the standard, deterministic choice), asserted
  in the render test.
- Each cell gets alignment via classes (e.g. `ta-left va-middle`) — **not** inline styles, to keep
  CSP-friendliness and themeability.
- Cell `html` is emitted through the existing `|sanitize`-style path but using the **cell** allowlist
  (either a `sanitize_cell` template filter or pre-sanitised-at-save so the template can mark safe).
  Decision: sanitise **at save**, and the template emits the stored html with `|safe` — matching how
  the model already sanitises `TextElement.body` at save. (The template must never emit unsanitised
  author input.)

A new CSS file (or a section in the elements stylesheet) styles the four presets + header emphasis.
Basic during build; polished via `frontend-design` at the end.

**Edge combination:** `border="header"` with **both** `header_row` and `header_col` off renders no
borders at all — this is an accepted, intentional no-op (the author asked for header dividers but
declared no headers), not an error state. Tests assert this combination renders a borderless table
without erroring.

### 3. Math typesetting

- **Student view:** extend `math.js` so the inline `renderMathInElement` pass (`renderInlineText`)
  also covers table cells — add `.el--table` alongside `.el--text` (same `INLINE_DELIMS`). All slides
  of a slideshow unit are present in the DOM at page load (paging is CSS-only), so the single
  load-time `renderInlineText(document)` pass typesets tables on any slide; no per-swap inline
  re-typeset is required. Add a test for a table containing `\(...\)` on a **non-first** slide.
- **has_math gating — multiple sites, not one.** `courses/views.py` computes `has_math` in more than
  one place: at minimum the **lesson** consumption context (`build_lesson_context`, ~line 140) and the
  **quiz** consumption context (~line 468); the results page (~line 682) if it renders elements.
  Content elements — including tables — can appear in quiz units, so **every consumption site that can
  contain a table must gain a `TableElement` branch**, reusing `has_math_delimiters()` against the
  concatenation of the table's cell htmls. The plan must enumerate the exact sites and add a gating
  test for the quiz path, not just the lesson path.
- **Editable cells are NEVER typeset in place (critical).** KaTeX/`renderMathInElement` replaces raw
  `\(...\)` source with rendered markup *in the element it runs over*. If it ran over the editable
  grid cells, the subsequent `innerHTML` serialization would capture KaTeX span-soup, which
  `sanitize_cell` then strips — destroying the author's LaTeX on save. So the contenteditable cells
  keep LaTeX as **raw text** for the entire editing session, and serialization always reads that
  pre-typeset source (see §4).
- **Editor whole-element preview:** the editor's existing separate preview pane (the `editor.js`
  fragment-swap flow) renders the *saved* element via the normal render template and re-typesets it
  using the existing `editor.js:applyFragments` math path (`libliRenderMath` for `[data-katex]` blocks
  plus the editor page's inline auto-render helper) — the **same** path the Text element's preview
  already uses. The table adds nothing new here and does not introduce a new `renderMathInElement`
  call on the manage page; it relies only on what `applyFragments` already invokes. This preview node
  is distinct from the editable grid, so typesetting it never touches the serialized cell source.

### 4. Editor — `_edit_table.html` + `courses/static/courses/js/table_editor.js`

- **JS-required.** The table editor is a JS-enhanced widget; with JS disabled there is no way to build
  or edit the grid. This is consistent with the rest of the authoring UI (adding/saving any element
  already runs through `editor.js`). We explicitly declare the table editor JS-required — there is no
  no-JS grid fallback. The add-menu and save endpoints still degrade sanely on the server side; only
  the in-browser grid authoring needs JS.
- `templates/courses/manage/editor/_edit_table.html` is auto-included by `_host_form.html` via
  `type_key`. It renders: a **controls strip** (header-row toggle, header-column toggle, border-preset
  `<select>`), the **grid** of `contenteditable` cells, and a hidden field carrying the serialised
  `data` JSON that the form binds to.
- **Default grid / empty-data normalization (server-side).** A brand-new `TableElement` has
  `data = {}`. Normalization to a default **2×2, no headers, `border="grid"`** happens **server-side**
  — the form/`_edit_table.html` renders the default grid from empty/`{}` data. Normalization lives in
  **one place both paths can reach: a `TableElement.normalize_data(data) -> dict` static/class method**
  (not on the form — the render template must call it too). The form/editor partial and the student
  render template both call `TableElement.normalize_data(...)`, so form, editor, and render share one
  implementation. `table_editor.js` only *enhances* the already-rendered grid; it does not synthesize
  the initial grid. The same method guards the render template against legacy/empty data
  (§ Error handling).
- `table_editor.js` progressively enhances the grid:
  - **Pinned per-cell toolbar** shown/updated on cell focus: B / I / U (own thin
    `document.execCommand` handlers acting on the focused cell — the private `applyCmd` in
    `text_toolbar.js` is **not** importable, so it is not reused; see Background), horizontal-align
    buttons, vertical-align buttons, and an **insert-math** button that calls
    `window.libliMathInput.open(cb)` and inserts a `\(latex\)` **text node** at the caret (copy the RTE
    `math` command pattern). The inserted math stays as raw `\(...\)` text and is never typeset inside
    the cell. **The button inserts inline `\(...\)` only.** Display math `\[...\]` renders correctly on
    the student view (the inline pass's `INLINE_DELIMS` includes the `display:true` `\[...\]` entry)
    but has **no dedicated button in v1** — it is reachable by an author hand-typing the `\[...\]`
    delimiters. A test asserts a hand-typed `\[...\]` cell typesets as display math on consumption.
  - **Selection/caret preservation (contenteditable footgun):** clicking a toolbar button would
    otherwise blur the cell and drop the selection before the handler runs, so `execCommand` would
    no-op and "insert at the caret" would have no caret. Toolbar buttons therefore call
    `preventDefault()` on **`mousedown`** to keep focus and selection in the cell. The insert-math flow
    additionally **captures the cell's `Range` before opening `window.libliMathInput`** and restores
    it in the async callback before inserting the `\(latex\)` text node. Before applying B/I/U,
    `table_editor.js` calls `document.execCommand("styleWithCSS", false, false)` once so bold/italic/
    underline emit tag markup (`<b>`/`<i>`/`<u>`) — never `<span style>`, which the attribute-free
    `sanitize_cell` would strip.
  - **Enter-key handling:** pressing Enter inside a cell inserts a `<br>` (the only intra-cell block
    separator in the allowlist) rather than the browser default `<div>`/`<p>` wrapper (which
    sanitisation would strip, silently losing the line break). `table_editor.js` intercepts Enter to
    insert `<br>`.
  - **Row/column controls:** hover the top edge of a column / left edge of a row → insert (＋) /
    delete (✕) handles; append affordances at the far right / bottom edges. The delete handle is
    disabled/hidden when only one row (or one column) remains, so the editor cannot drop below the
    enforced **1×1** minimum client-side (matching the server floor) — no confusing reject-on-save
    dead-end. Symmetrically, the insert-row/insert-column and far-edge append affordances are
    disabled/hidden once the grid reaches the **50×20** ceiling, so the editor also cannot exceed the
    server cap client-side (same dead-end avoided on the upper bound).
  - **Single alignment representation shared by editor and render:** each editable cell carries
    `data-halign` / `data-valign` attributes; the align buttons set these attributes on the focused
    cell (and reflect them in the toolbar's active state). Serialization reads `halign`/`valign` back
    from those attributes. The render template maps the same values to `ta-*` / `va-*` classes. One
    vocabulary (`left|center|right`, `top|middle|bottom`) flows editor-attr → JSON → render-class.
  - On every mutation (typing, formatting, structural change, alignment, toggles, preset) it
    re-serialises the grid to the hidden JSON field so a normal form submit persists it. Each cell's
    `html` is read from `innerHTML` — always the **raw pre-typeset source** because cells are never
    typeset in place (§3) — and its `halign`/`valign` from the `data-*` attributes above. Final
    authoritative sanitisation (allowlist + math-protection) is server-side.
- The editor reuses only the MathLive global (`window.libliMathInput`); B/I/U is a small local
  `execCommand` layer, not a shared toolbar engine.

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
   **The import BUILDER does not go through `TableElementForm`, so it must itself apply the same
   defenses before persisting:** run `sanitize_cell` on every cell `html`, coerce the enums
   (`border`/`halign`/`valign`), enforce the 50×20 cap, and `normalize_data`. `VALIDATORS` only checks
   *shape* — sanitisation is a separate, mandatory step in the builder (see the security note in
   Error handling).

## Data flow

**Authoring:** creator clicks the "Table" card in the add-menu → `_edit_table.html` renders the
server-normalized default grid (2×2, no headers, `grid` border — from empty `data={}` via
`normalize_data()`) → author types into cells, formats text, toggles headers,
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
  - The hidden field carries a JSON **string**; an unparseable string yields a clean form error (not
    a `500`) — Django's `JSONField` form parsing surfaces it, and the "reject on structurally invalid"
    test covers it alongside the shape checks below.
  - `data` must be a dict with `cells` a non-empty rectangular 2-D list; each row equal length;
    at least 1×1 and at most a sane cap of **50 rows × 20 columns** (guards against crafted/imported
    payloads bloating storage and render; a payload exceeding the cap is rejected with a form error).
  - `border` coerced to the allowed set (default `grid` on invalid); `halign`/`valign` coerced to
    allowed sets (default `left`/`top`); `header_row`/`header_col` coerced to bool.
  - Each cell `html` passed through `sanitize_cell` — anything outside `CELL_TAGS`
    (`<strong>/<b>/<em>/<i>/<u>/<br>`) is stripped. Malicious/rich markup can never reach the DB or
    the render template. (This list must stay in sync with `CELL_TAGS` in §1 — all six tags, including
    `b`/`i`.)
  - Reject (form error) rather than silently truncate on structurally invalid payloads (e.g. `cells`
    not a list); coerce on merely out-of-range enum values.
- **Rendering is defensive:** the render template calls `TableElement.normalize_data(data)` first,
  which promotes missing keys and an empty/`cells:[]` grid to the default 2×2. So the template always
  renders a well-formed `<table>` (never a "renders nothing" branch — normalize guarantees ≥1×1) and
  never `500`s on legacy/odd data.
- **Transfer import is a security boundary (must sanitise, not just validate).** Because the render
  template emits stored cell `html` with `|safe`, any path that writes `data.cells[*].html` must have
  sanitised it. The importer rebuilds a `TableElement` **without** `TableElementForm`, and `VALIDATORS`
  checks only *shape* — so the import BUILDER must itself run `sanitize_cell` on every cell, coerce the
  enums, enforce the 50×20 cap, and `normalize_data`, before persisting. Without this, a crafted
  imported zip could land `<script>`/`onclick=` in a cell → stored XSS. A malformed imported payload
  still fails validation cleanly (never a crash). **Test:** an imported table payload containing a
  disallowed tag/attribute is stripped on import.
- **Math:** `renderMathInElement` uses `throwOnError: false` (existing behaviour), so bad LaTeX in a
  cell renders as-is rather than breaking the page.

## Testing

Follow the repo's TDD conventions; `uv run` for `ruff`/`pytest`/`python`; run **both** `ruff check`
and `ruff format --check`. Use `tests.factories.TEST_PASSWORD` — never hardcode passwords. If any
translatable strings are removed during the build, run the i18n catalog tests in the DoD.

Test coverage to write:

- **Model / sanitisation:** `sanitize_cell` strips disallowed tags, **keeps `strong/b/em/i/u/br`** (so
  `execCommand`-produced `<b>`/`<i>` survive), and — critically — preserves LaTeX intact including
  `<`/`>` inside math: **`\(x<5\)` and `\(a<b\)` round-trip unchanged** through the math-protection
  placeholdering. `TableElement.render()` produces a `<table>` with correct `<th>` placement for each
  header-toggle combination (including the both-off `border="header"` no-op) and correct
  alignment/border classes.
- **Form validation:** valid payload saves; ragged/empty/non-list `cells` rejected; over-cap
  (>50 rows or >20 cols) rejected; out-of-range `border`/`halign`/`valign` coerced to defaults;
  empty `data={}` normalizes to the default 2×2; cell html sanitised on save; an intra-cell `<br>`
  survives while block wrappers are stripped.
- **has_math gating (multiple sites):** a **lesson** unit whose table cell contains `\(x\)` sets
  `has_math` (KaTeX loads) and one without delimiters does not; **the same for a table in a quiz
  unit** — cover the quiz consumption path, not only the lesson path.
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
