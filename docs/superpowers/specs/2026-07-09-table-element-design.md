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

**Where sanitisation lives (pinned).** Cell-`html` sanitisation happens authoritatively in
**`TableElement.save()`** — exactly as `TextElement.body` is sanitised at save — so **every** write
path is covered without repetition: the form path, the transfer-import builder, and any future writer
all persist through `save()`, which runs `sanitize_cell` over every cell before storing. The
**form** (`TableElementForm.clean`) owns *validation* (shape, dimension cap rejection, enum coercion,
JSON-parse errors) — things that must raise `ValidationError` and cannot live in `save()`. So: `save()`
sanitises html (defense-in-depth for all paths); `clean` validates. The import builder therefore gets
html-sanitisation for free via `save()`, and only needs to handle the *validation-flavoured* concerns
`save()` does not (enum coercion, cap, `normalize_data`) — see §5.9. `save()`'s sanitise loop reads
each cell **defensively** (`cell.get("html", "")` with an `isinstance` guard, skipping non-dict cells /
non-list rows) so it cannot itself raise on the malformed legacy shapes `normalize_data` documents —
even though both real write paths (form `clean`, import builder) already normalize before `save()`.
The template never sanitises; it emits already-sanitised stored html. A new helper in
`courses/sanitize.py`:

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
MathLive emits a literal `<`. Therefore `_sanitize_preserving_math` must **extract each properly-closed `\(...\)` and `\[...\]` span
into a placeholder before `nh3.clean`, then, on restore, re-insert the span with its contents
CANONICALISED — HTML-unescape exactly once, then HTML-escape exactly once** (`html.unescape` then
`html.escape`), **never verbatim and never blind-escape**. Rules to pin in the implementation:

- **Restore canonicalises (unescape-once-then-escape-once) — this is load-bearing for BOTH input
  shapes.** The editor serialises each cell via `innerHTML`, so a typed `<` reaches the server
  **already** as the entity `&lt;` (input `\(a&lt;b\)`); the import path can carry a **literal** `<`
  (input `\(<img…>\)`). A single blind escape can't serve both — it would double-escape the editor
  path (`&lt;` → `&amp;lt;`, compounding on every re-edit) while correctly escaping the import path.
  Canonicalising converges them: editor `a&lt;b` → unescape → `a<b` → escape → `a&lt;b`; import
  `<img…>` → unescape (no-op) → escape → `&lt;img…&gt;` (inert). Both store a **single-escaped**,
  KaTeX-correct, XSS-safe value.
- **Why escaped at all (security + correctness).** Verbatim restore would (a) let a crafted
  properly-closed pair like `\(<img src=x onerror=alert(1)>\)` bypass the tag sanitizer entirely →
  stored XSS via the render template's `|safe`, and (b) mis-render even benign `\(a<b\)` because the
  browser HTML tokenizer consumes `<b…` as a tag *before* KaTeX runs. A single-escaped span is inert
  to the HTML parser, while KaTeX still gets the right input because it reads the element's **decoded**
  `textContent` (`\(a&lt;b\)` decodes to the text `a<b`).
- **Only balanced pairs are protected, matched non-greedily, no nesting:** a `\(` pairs with the next
  `\)` (and `\[` with the next `\]`). An **unmatched** opener or closer (a lone `\(`, or a stray `\)`
  first) is **not** protected — it is left as literal text and sanitized normally. A test covers a
  cell containing a single unmatched `\(`.
- **Placeholder tokens carry a per-invocation random nonce and must SURVIVE `nh3.clean` unchanged**
  (they are inserted before the clean and must still be present to be restored). Do **not** build them
  from codepoints the sanitizer strips — that would delete the placeholder and silently lose the math.
  The nonce prevents collision with a token the author literally typed as cell content. An invariant/
  test asserts the placeholder is present in `nh3.clean`'s output before restore.

Result: math survives the sanitizer, `<`/`>` inside balanced math both round-trips and typesets, and
no math span can smuggle live markup. Non-math `<`/`>` typed as literal text outside math delimiters
is HTML-escaped/stripped by the sanitizer, which is correct.

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
  **quiz** consumption context (~line 468). Content elements — including tables — can appear in quiz
  units, so **every consumption site that can contain a table must gain a `TableElement` branch**,
  reusing `has_math_delimiters()` against the concatenation of the table's cell htmls. **Results page
  (~line 682) — resolve, do not hedge:** the implementation MUST inspect the results-page context
  builder and decide definitively — if it renders any content element (and thus could contain a table),
  it MUST gain the `TableElement` `has_math` branch **and** a gating test there; if it renders no
  content elements, the plan records that exclusion explicitly with a one-line justification. No silent
  omission. Add a `has_math` gating test for the **quiz** path, not just the lesson path.
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
  `data` JSON that the form binds to. The controls strip and grid are **server-rendered from the
  normalized stored `data`**, so for an existing table the toggles/select reflect the persisted
  `header_row`/`header_col`/`border` (they must not render as defaults that would clobber saved
  settings on the first serialize). **The controls-strip inputs are name-less (not form-bound):** they
  are pure JS-driven UI whose state is mirrored into the hidden `data` JSON, which is the **sole
  authoritative field** for `header_row`/`header_col`/`border` (avoids extra/conflicting POST params).
- **Default grid / empty-data normalization (server-side).** A brand-new `TableElement` has
  `data = {}`. Normalization to a default **2×2, no headers, `border="grid"`** happens **server-side**
  — the form/`_edit_table.html` renders the default grid from empty/`{}` data. The single source of
  truth is a pure **`TableElement.normalize_data(data) -> dict` static/class method**. Because Django
  templates cannot call a method **with an argument**, consumers reach it through **zero-arg seams**,
  never by calling `normalize_data(data)` in a template:
  - the student render path normalizes in Python — `TableElement.render()` / its `get_context` calls
    `normalize_data(self.data)` and passes the normalized dict to the template;
  - a zero-arg **`normalized_data` property** (`return TableElement.normalize_data(self.data)`) is
    available where a template needs it directly;
  - the editor view normalizes server-side and hands the normalized dict to `_edit_table.html`.

  All three funnel through the one static method, so form, editor, and render share one implementation.
  `table_editor.js` only *enhances* the already-rendered grid; it does not synthesize the initial grid.
  The same method guards the render path against legacy/empty data (§ Error handling).
- **`normalize_data` contract (pinned for the "well-formed" guarantee):** given arbitrary stored data
  (reachable via DB/admin/legacy edits) it returns a dict where: missing top-level keys get defaults
  (`header_row=False`, `header_col=False`, `border="grid"`); **ragged rows are rectangularised** (padded
  with empty cells to the widest row, never truncated — no author content is dropped); a **non-list
  row** is treated as empty, and a **non-dict cell** is replaced by the default cell
  `{html:"", halign:"left", valign:"top"}` (existing cells have only their *missing* keys filled with
  those defaults). **Degenerate-collapse guard (closes the ≥1×1 hole):** after rectangularisation, if
  the computed **height or width is 0** — i.e. `cells` is missing/`[]`, or a non-empty list of empty
  rows like `[[],[]]`, or otherwise collapses — it falls back to the default **2×2**. So the output is
  always a rectangular grid of at least 1×1 with fully-formed cells, which is what makes the render
  "always well-formed" guarantee hold for ragged/partial/degenerate inputs, not only empty ones. Tests
  cover `cells:[[],[]]`, a ragged grid, and a cell missing keys.
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
    server cap client-side (same dead-end avoided on the upper bound). Cells created by a row/column
    insert are initialised with `data-halign="left"`, `data-valign="top"`, and empty content —
    matching `normalize_data`'s per-cell defaults, so the toolbar active-state (which reads
    `data-halign`/`data-valign`) and serialization stay consistent.
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
3. `courses/element_forms.py` — define `TableElementForm(ModelForm)` (validates `data`; html
   sanitisation is at `save()` per §1) **and** add the `FORM_FOR_TYPE["table"]` entry: the
   `FORM_FOR_TYPE` dict is defined at `element_forms.py:594` (both the class and its mapping entry live
   in this file). `builder.py` / `views_manage.py` only *import and consume* `FORM_FOR_TYPE`; §1's
   "`builder.py` `FORM_FOR_TYPE[type_key]`" refers to that consumption site, not where the dict is
   defined.
4. `templates/courses/manage/editor/_edit_table.html` — editor partial.
5. `templates/courses/elements/tableelement.html` — render partial.
6. `courses/views_manage.py` — `"table"` in `_EDITOR_TYPE_LABELS`, the `element_add` allowed-tuple,
   and the `element_save` allowed-tuple.
7. `templates/courses/manage/editor/_add_menu.html` — `data-add-type="table"` card, plus a
   `<symbol id="el-table">` icon in `templates/courses/manage/_icon_sprite.html`.
8. `courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS["tableelement"] = "Table"` and
   an `element_summary` branch (e.g. `"3×4 table"`). **All new user-facing strings** — this label, the
   summary, the add-menu card, and the editor's toolbar/affordance tooltips — use **`gettext_lazy`**
   (module-level labels must be lazy — eager `gettext` has previously frozen labels to English here)
   and ship **EN + PL** catalog entries, consistent with the rest of the authoring UI.
9. Transfer — `SERIALIZERS` (`courses/transfer/export.py`), `VALIDATORS`
   (`courses/transfer/payloads.py`), `BUILDERS` (`courses/transfer/importer.py`), all keyed `"table"`.
   **The import BUILDER does not go through `TableElementForm`.** Cell-`html` sanitisation is still
   guaranteed because the builder persists via `TableElement.save()` (which runs `sanitize_cell` — §1).
   The builder must additionally handle the *validation-flavoured* concerns `save()` does not: coerce
   the enums (`border`/`halign`/`valign`), **reject over-cap payloads (>50×20) consistently with the
   form** (over-cap is a validation failure, checked in `VALIDATORS`, not silently clamped), and
   `normalize_data`. See the security note in Error handling.

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
  - Cell `html` sanitisation is **not** performed here in `clean` — it is guaranteed at **`save()`**
    via `sanitize_cell` (invoked on every persist, including form submit; §1). The net effect is that
    anything outside `CELL_TAGS` (`<strong>/<b>/<em>/<i>/<u>/<br>`) is stripped and malicious/rich
    markup can never reach the DB or the render template. (Do **not** add a second `sanitize_cell` call
    in `clean`; this list must stay in sync with `CELL_TAGS` in §1 — all six tags, including `b`/`i`.)
  - Reject (form error) rather than silently truncate on structurally invalid payloads (e.g. `cells`
    not a list); coerce on merely out-of-range enum values.
- **Rendering is defensive:** `TableElement.render()`/`get_context` normalizes via
  `normalize_data(self.data)` before the template runs, promoting missing keys and an empty/`cells:[]`
  grid to the default 2×2. So the template always renders a well-formed `<table>` (never a "renders
  nothing" branch — normalize guarantees ≥1×1) and never `500`s on legacy/odd data.
- **Transfer import is a security boundary.** Because the render template emits stored cell `html`
  with `|safe`, any path that writes `data.cells[*].html` must have sanitised it. This is guaranteed
  because **all write paths persist through `TableElement.save()`, which sanitises** (§1) — the import
  builder included, even though it bypasses `TableElementForm`. Without the save-level sanitiser a
  crafted imported zip could land `<script>`/`onclick=` in a cell → stored XSS; with it, such markup
  is stripped (or, inside a math span, escaped inert). Over-cap imported payloads are **rejected** by
  `VALIDATORS` (consistent with the form's reject semantics, not silently clamped); a malformed payload
  fails validation cleanly (never a crash). **Tests:** an imported payload with a disallowed
  tag/attribute is stripped on import; an over-cap imported payload is rejected.
- **Math:** `renderMathInElement` uses `throwOnError: false` (existing behaviour), so bad LaTeX in a
  cell renders as-is rather than breaking the page.

## Testing

Follow the repo's TDD conventions; `uv run` for `ruff`/`pytest`/`python`; run **both** `ruff check`
and `ruff format --check`. Use `tests.factories.TEST_PASSWORD` — never hardcode passwords. If any
translatable strings are removed during the build, run the i18n catalog tests in the DoD.

Test coverage to write:

- **Model / sanitisation:** `sanitize_cell` strips disallowed tags, **keeps `strong/b/em/i/u/br`** (so
  `execCommand`-produced `<b>`/`<i>` survive), and preserves math by **canonicalising** its contents
  (unescape-once-then-escape-once) to a single-escaped form. Both input shapes converge to the same
  stored value `\(a&lt;b\)`: the **editor** input `\(a&lt;b\)` (already-entity from `innerHTML`) and a
  **literal** `\(a<b\)`. A crafted `\(<img src=x onerror=alert(1)>\)` stores inert as
  `\(&lt;img…&gt;\)` (XSS-via-import regression test). **Idempotency test:** running a stored value
  back through `sanitize_cell` (simulating re-edit) does **not** add another escape layer.
  `TableElement.render()` produces a `<table>` with correct `<th>` placement for each header-toggle
  combination (including the both-off `border="header"` no-op) and correct alignment/border classes.
- **Editor-path serialization test (drive the real UI, not a synthetic literal):** a test/e2e that
  builds a cell as a real text node `\(a<b\)`, serialises via `innerHTML` (→ `\(a&lt;b\)`), saves, and
  asserts the stored value is single-escaped `\(a&lt;b\)` — guarding the double-escape trap that a
  synthetic literal-`<` unit test would mask (per this repo's e2e-must-drive-real-UI lesson).
- **Math consumption/render:** a consumption test asserts a cell containing `\(a<b\)` actually
  **typesets** (KaTeX reads the decoded `textContent` `a<b`), confirming canonicalisation does not
  break real math — not just that the stored string is escaped.
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
