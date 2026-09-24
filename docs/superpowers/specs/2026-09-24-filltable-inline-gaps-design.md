# Fill-in table: inline `{{answer}}` gaps in cell text — design

Date: 2026-09-24 · Branch: `feat/filltable-inline-gaps`

## Problem

The LAL importer turns a table cell holding ONE `table_input` into a bare answer
cell and discards every other thing in that cell (`scripts/lal_import/tables.py`,
the `len(inputs) == 1` branch of `fill_table_element`). Only cells with two or more
inputs keep their text (`_split_multi_input_cell`). A read-only scan of the LAL
source found **83 affected cells in 19 lessons**. Three kinds of loss:

- **the question itself** — `\(NWD(15, 16)=\)`, `\(3^5\cdot 3^4=3\)` (input is the
  exponent), `\(\log_{2}16=\)`, "Pole =" — the student sees an empty box with no
  question. **Limitation:** a `{{…}}` inside maths stays literal (§2), so a box can
  never sit IN a superscript. The author writes the box on the baseline after the
  maths — `\(3^5\cdot 3^4=3\)` then `{{9}}` renders as `3⁵·3⁴ = 3 ▢`, and the
  instruction text says "wpisz wykładnik" — which is how the LAL original already
  looked (the input sat on the baseline there too);
- **an expression around the box** — `\((x+2)^2+(y\)` ▢ `\()^2=16\)`;
- **a unit / suffix** — `\(\pi\)` (270/290_kolo_okrag, the trigger), `\(^{\circ}\)`,
  `\(\cdot\sqrt{6}\)`.

The course is already imported to libli.pl and the owner has hand-edited more than
half of it, so **re-importing is not an option**. Fixing the importer does not help
the live content.

## Owner decisions (verbatim intent — do not reverse in review)

| # | Decision | Rejected alternative |
|---|----------|----------------------|
| D1 | The fix must be something an **author applies themselves** in the editor. | Re-import; an importer-only fix; an operator-run repair script as THE fix. |
| D2 | **Approach A:** the author types `{{answer}}` into a normal cell's text; the box renders **inline** in that text. | Extra static π columns; a header note; `9|9π` answer alternatives; "text before/after" fields on an answer cell (cannot put a box inside a formula). |
| D3 | The editor shows the **raw `{{…}}` text** as typed, like the Fill-in-the-blank element. | Rendering the gap as a chip/box inside the editor. |
| D4 | **Storage option 1:** parse at save into a token-stem + a hidden answer list (the fill-blank pattern); the editor gets `{{…}}` back via the reverse conversion. | Storing raw `{{9}}` and stripping answers at every read site; a new segment-list cell kind. |
| D5 | Existing "Answer cell" cells keep working unchanged; gaps are an ADDITIONAL way to add boxes. | Replacing answer cells. |
| D6 | Out of scope: changing the LAL importer; any automatic repair of the live lessons. | — |

## Success criterion

The owner opens e.g. `270_kolo_okrag` on libli.pl, types `{{9}} \(\pi\)` into the
cell, saves; a student sees `▢ π`, types `9`, and the box turns green. Nothing else in
the course changes.

## Design

### 1. Stored shape

A static cell MAY carry an optional `gaps` key: a list with one entry per box, each
entry the list of that box's accepted alternatives (trimmed, non-empty strings). The
cell's `html` holds an opaque token `\uffff{n}\uffff` at box `n`'s position — the
same sentinel/token as `courses/fillblank.py` (`SENTINEL`, `_TOKEN`, `_TOKEN_RE`).

```json
{"kind": "static", "html": "\uffff0\uffff \\(\\pi\\)", "gaps": [["9"]], "halign": "left", "valign": "top"}
```

- A static cell with no boxes has **no `gaps` key** — its stored shape and every
  reader's behaviour are byte-identical to today.
- Answer cells (`kind: "answer"`) and image cells are untouched.
- Verified during design: `courses.sanitize.sanitize_cell` preserves U+FFFF, so a
  token survives the sanitise pass that `FillTableElement.save()` runs on every save.

### 2. One shared helper — `courses/filltable.py`

All parse / reverse / reconcile logic lives here, reused by the form, the model, the
render, the check view and the editor template, so they cannot disagree.

- `parse_cell_gaps(html) -> (token_html, gaps)` — runs on SANITISED cell html with the
  sentinel stripped first (`fillblank.strip_sentinel`), exactly like fill-blank's
  author flow. Reuses `fillblank.mask_math` / `restore_math` so `{{` inside
  `\(…\)` / `\[…\]` stays literal, and fill-blank's marker rules (`_MARKER_RE`:
  single-line, `|` alternatives, `html.unescape` + strip each piece, empty pieces
  dropped). Raises `FillBlankError` on an empty marker (`{{}}`, `{{ | }}`) or an
  unterminated one (`{{9`). Unlike `fillblank.parse`, **zero markers is NOT an error**
  — it returns `(html, [])`.
  - **Markup inside a marker is stripped.** Static cells are rich contenteditable
    (B/I/U toolbar, `libliColour.mapColours`, stray `<br>`/`<span>`), so the marker
    interior may hold tags: `{{<b>9</b>}}`. The interior's tags are removed (text
    content only) BEFORE `html.unescape` + split, so the answer is `9`. An answer is
    always plain text. Only the INTERIOR is stripped: a marker straddling a tag
    (`<b>{{9</b>}}`, `{{<b>9}} rest</b>`) leaves an unbalanced tag in `token_html`
    (`<b>\uffff0\uffff`, an orphan `</b>`); that is acceptable because `FillTableElement.save()`
    re-sanitises the cell html, which rebalances it. A brace pair split by a tag
    (`{<b>{</b>9}}`) matches no marker and is stored as literal text — documented
    behaviour, not an error.
  - **Only `\(…\)` and `\[…\]` are protected.** `filltable.js` calls
    `renderMathInElement(root)` with KaTeX's default delimiters, which also typeset
    `$$…$$`, but `mask_math` does not mask `$$`. A `{{` inside `$$…$$` is therefore
    read as a marker. Accepted (the LAL corpus and the editor use `\(`/`\[`); the §10
    prod query flags `{{` inside `$$…$$` too, so any live instance is surfaced.
  - **Maths inside a marker is rejected.** `mask_math` runs before marker
    extraction, so `{{9\(\pi\)}}` would store the placeholder `9\uffffM0\uffff` as the answer —
    unmatchable. A marker whose interior contains a math placeholder raises
    `GapMathError`, a subclass of `FillBlankError` defined in `courses/filltable.py`
    (the form branches on the CLASS, never on the message string), surfaced by the
    form as (note: maths that STARTS inside a marker and ends outside it,
    `{{9\(x}}\)`, swallows the `}}` during masking, so it reports the
    empty/unclosed message instead — accepted, pinned by a test) *"Row R, column C: an
    answer box cannot contain maths — put the maths outside the braces, e.g.
    `{{9}} \(\pi\)`."* (Fill-blank shares the latent flaw; fixing it there is out of
    scope.)
- `author_cell_html(cell) -> str` — the inverse for the editor: tokens become
  `{{alt1|alt2}}`, alternatives html-escaped (`quote=False`), exactly as
  `fillblank.to_author_stem`. Identity for a cell without `gaps`.
- `reconcile_gaps(html, gaps) -> (html, gaps)` — the read-side repair (§4). Always
  returns a list for `gaps` (`[]` when no box survives), so its output is a valid
  input; `_cell` omits the `gaps` key when the returned list is empty.
- **Cap:** at most `MAX_GAPS_PER_CELL = 10` markers per cell (the LAL corpus peaks
  at 2). More → a form error *"Row R, column C: at most 10 answer boxes per cell."*
  Rows/columns are already capped, so this bounds the inputs, POST keys and
  check-view iterations per table; `reconcile_gaps` truncates to the cap on read.
- `answer_cells` is unchanged; a new `gap_cells(cells)` yields `(r, c, g, alts)` with
  `alts` the stored LIST of alternatives (no `|` join/re-split), so the "has at least
  one answer" rule and the check view can iterate answer cells and gaps together.

### 3. Saving

**Form** (`FillTableElementForm.clean_data`, `courses/element_forms.py`):

- **Order matters — parse BEFORE `normalize_data`.** Today `clean_data` calls
  `FillTableElement.normalize_data(data)` and returns that `nd`; `normalize_data`
  derives `gate` from the answers it can see. If the raw `{{…}}` were parsed only
  after normalising, a gated table whose answers are ALL gaps would be normalised
  with no visible answer → `gate: False` stored → `has_filltable_gate`
  (`views.py`, `data__gate=True`) never arms reveal.js; the author's tick silently
  lost. So: walk the RAW posted cells first; for every static cell, sanitise its
  `html`, `parse_cell_gaps`, write `token_html` back and set `gaps` (omit the key
  when empty); THEN `normalize_data`. "Static" means any cell whose `kind` is
  neither `answer` nor `image` (an unknown kind normalises to static). The raw walk
  never raises on malformed input: non-list rows and non-dict cells are skipped (left
  for `normalize_data` to coerce), a non-string `html` is treated as `""`.
- **A posted `gaps` key is discarded.** The form deletes any client-supplied `gaps`
  on every cell before parsing; only what it parses from the `html` is stored.
- A `FillBlankError` becomes a `ValidationError` naming the cell (1-based,
  translated): *"Row %(r)d, column %(c)d: an answer box `{{…}}` is empty or not
  closed."*, or the maths message from §2. R and C are the RAW list indices + 1; in a
  spanning (merged-cell) table C is the cell's position within its row list and may
  differ from the visual column. Accepted.

The existing rules extend to gaps:
- "at least one answer" — satisfied by ≥1 answer cell OR ≥1 gap. Message becomes:
  *"Add at least one answer — mark an answer cell, or type `{{answer}}` in a cell."*
  The same new text goes in all three places that hold the old one: the server
  `ValidationError`, the `data-msg-no-answer` attribute in `_edit_filltable.html`,
  and the hard-coded fallback in `filltable_editor.js` `onSubmit`; plus BOTH `.po`
  catalogs (`locale/pl/…/django.po` and `locale/en/…/django.po`, which also holds the
  old msgid) and the recompiled `.mo`. `tests/test_filltable_editor_partial.py`
  references the old string and is updated with it.
- "no blank answer" — gaps can never be blank (parse rejects empty markers), so the
  rule stays as-is for answer cells.

**Model** (`FillTableElement._cell` + `_sanitized_data`):
- `_cell` carries `gaps` through for a static cell, then `reconcile_gaps` (§4). A
  non-list `gaps` drops the whole key; within a list, a bad entry is handled PER
  ENTRY as §4 defines. `reconcile_gaps` runs ONLY when the raw cell has a `gaps`
  key; a cell without one is passed through untouched (even if its html happens to
  contain `\uffffn\uffff` text), which is what keeps §1's "byte-identical" promise. Likewise
  the render split (§5) applies only to cells with `gaps`.
- `_sanitized_data` does NOT parse raw `{{…}}`. Only the form converts author
  markers. Other write paths (transfer import, course builder, LAL loader) store what
  they are given; a raw `{{9}}` arriving by those paths renders as literal text,
  which is today's behaviour. (YAGNI: no current producer emits markers.)
- `normalize_data`'s gate check counts gaps as answers (a gated table made only of
  inline boxes keeps its gate).

### 4. Token/answer consistency (read-side repair, never an error)

A stored cell's tokens and `gaps` can disagree only through a damaged archive or a
hand DB edit. `reconcile_gaps`, run in `_cell`:
1. **Entry cleaning** (per entry): an entry that is not a list → treated as empty.
   Non-string alternatives are dropped; string alternatives are trimmed; blank ones
   are dropped. An entry left with no alternatives is EMPTY.
2. **Duplicate tokens:** if the same index appears more than once in `html`, the
   FIRST occurrence is kept and every later occurrence is removed.
3. a token whose index has no entry, or whose entry is EMPTY → the token is removed;
4. a `gaps` entry with no token in `html` → the entry is dropped;
5. surviving tokens are renumbered to `0..k-1` in document order and `gaps`
   reordered to match, so the check view's `g` always equals the rendered box's
   index and every rendered `g` is unique;
6. only the first `MAX_GAPS_PER_CELL` surviving tokens are kept (later ones
   removed with their entries);
7. `k == 0` → returns `[]`, and `_cell` omits the `gaps` key.

Never raises; a repaired cell simply shows fewer boxes. Idempotent:
`reconcile_gaps(*reconcile_gaps(h, g)) == reconcile_gaps(h, g)`.

### 5. Student render

`templates/courses/elements/_filltable_cell.html`, static branch: when the cell has
`gaps`, split `html` on `_TOKEN_RE` (the `fillblank.render_inputs` technique) and
safe-join the trusted sanitised text segments with server-built inputs:

```html
<input type="text" class="filltable__input filltable__input--inline"
       data-r="R" data-c="C" data-g="G" aria-label="Answer, row R+1, column C+1, box G+1">
```

- Same `filltable__input` class → verdict colours, `lock()`, the confirm handler and
  the reveal gate all apply unchanged.
- **`--inline` box model.** app.css's (0,1,1) `input[type=text]` rule owns this
  control's box (`width:100%`, border-box, ~`var(--space-3)` padding — see the
  courses.css notes around the existing `.el--filltable .filltable__input`
  `min-width`). A bare `width:8ch` would leave ~4ch of content, and the full padding
  breaks line rhythm inside running text. So, at (0,2,0) with the `.el--filltable`
  prefix — and placed AFTER the existing `.el--filltable .filltable__input
  { min-width: calc(4ch + …) }` floor block in courses.css, which has the same
  (0,2,0) specificity, so `min-width: 0` wins on source order: `display:inline-block;
  width: calc(6ch + 2 * var(--space-1) + 2px); min-width: 0;
  padding-block: 0; padding-inline: var(--space-1); vertical-align: baseline;` —
  a fixed width, never sized to the answer. The exact values are tuned against a
  screenshot; the constraint is: ~6ch of CONTENT, text baseline aligned with the
  surrounding text and KaTeX, line height not visibly increased.
- **Visual check (required):** light AND dark screenshots of a cell with a box
  between two maths spans (`\((x+2)^2+(y\) {{-1}} \()^2=16\)`) and of `{{9}} \(\pi\)`,
  each judged separately.
- aria-label omits "box N" when the cell has exactly one gap. Translated.
- **Done state** (`mine.done`, `canonical_cells`): each gap input renders
  `value=<first alternative>`, `readonly`, `filltable__input--correct` and a `size`
  that fits the value — mirroring `fillblank.render_inputs(locked=True)`, so a long
  first alternative is not clipped by the fixed inline width (the width rule must
  yield to `size` in this state: `.el--filltable .filltable__input--inline[readonly]
  { width:auto }`, (0,3,0), so it beats the (0,2,0) fixed width regardless of source
  order). **`[readonly]`, NEVER `:read-only`:** on a successful LIVE Check,
  `filltable.js` `lock()` sets `disabled` (not `readonly`) on every input, and a
  disabled input MATCHES `:read-only`; live-locked inline inputs carry no `size`, so
  `width:auto` would fall back to the browser default `size=20` and every box in the
  running text would jump from ~6ch to ~20ch at the moment of success. The
  `[readonly]` attribute is set only by the server-rendered done state. The
  done-state test/screenshot includes a long first alternative, AND an e2e check
  asserts an inline box keeps its width after a successful live Check.
- `canonical_cells` keeps its return type (one grid). On a static cell with `gaps`
  it returns `{**cell, "gaps_display": [first alternative of each gap]}` — a per-cell
  key; `gaps` itself stays on the cell in the done branch (answers already earned).
  Never mutates `self.data`.
- **Escaping.** Every server-built gap `<input>` is built with `format_html`, so
  `value`, `aria-label` and `size` are escaped. Stored alternatives are DECODED plain
  text (§2), so `a<b` or `"x" onfocus=…` is raw data; the inputs are safe-joined with
  the trusted text segments (the `fillblank.render_inputs` technique), which bypasses
  template autoescaping — `format_html` is the only thing escaping them.
- The answer list is NEVER emitted into the page. The render builds from `html`
  tokens only; `gaps` is read only in the done state (answers already earned).
  Structurally enforced: in the non-done branch, `render()` passes cells with the
  `gaps` key REMOVED (only the precomputed parts reach the template), so a future
  `{{ cell }}` or `json_script` in the template cannot leak answers.
- **Where the inputs are built:** `render()` precomputes `cell["parts"]` (a list of
  trusted-html / server-built-input pieces) for every static cell with `gaps`, in
  BOTH the done and non-done branches; the template only outputs the parts. No
  template filter. `r`/`c` are the RAW list indices — the same ones `answer_cells`,
  `gap_cells`, the POST key and the existing `_filltable_cell.html`
  (`forloop.parentloop.counter0` / `forloop.counter0`) use — so `data-r`/`data-c`,
  the POST key and the aria-label numbers agree for answer cells and gaps alike.

### 6. Checking

`filltable_check` (`courses/views.py`) iterates answer cells (POST key `r{r}c{c}`,
unchanged) AND gaps (POST key `r{r}c{c}g{g}`), each through the existing
`blank_matches(got, alts, case_sensitive=…)`. Response cells gain an optional `g`:
`{"r":1,"c":2,"g":0,"correct":true}`. `all_correct` requires every answer cell and
every gap correct; zero of both → the existing empty response.

`filltable.js`: `submit` appends `g` to the key when `data-g` is present; `paint`
selects `[data-r][data-c][data-g="G"]` when the reply carries `g`, else
`[data-r][data-c]:not([data-g])`.

- **The real risk is the `g` part.** A cell's gaps share its `r`/`c`; if `paint`
  drops or mis-builds the `data-g` term, `querySelector` returns the cell's FIRST
  gap for every gap reply, so in a two-gap cell box 1 wears box 2's verdict and
  box 2 is never painted.
- `:not([data-g])` is defensive only: a cell is either an answer cell or a static
  cell, never both, so an answer-cell reply's `(r,c)` cannot match a gap today. It
  carries no RED-mutant requirement.

### 7. Editor

- `_edit_filltable.html`: static cells render `author_cell_html(cell)` instead of
  `cell.html` — the author sees and edits `{{9|9,0}} \(\pi\)`.
- A rejected save re-renders the SUBMITTED grid (`grid_data` re-reads POST, which
  still holds raw `{{…}}`), so nothing typed is lost. `author_cell_html` is the
  identity on a cell without `gaps`.
- `filltable_editor.js` `onSubmit`: the "no answer" client guard passes when any
  static cell's text contains `{{`. It does not validate markers — the server does.
- One hint line under the grid (translated): *"Type `{{answer}}` in a cell to put an
  answer box inside its text; separate accepted alternatives with `|`."*
- Help: `docs/help/course-admin/interactive-elements.md` and `.pl.md`, Fill-in table
  entry, one short paragraph with the π example.
- ⚠️ The table and fill-table editors are drift-guarded twins
  (`tests/test_editor_twin_drift.py`). `onSubmit` has no twin, so no TWINS entry
  changes. Two concrete constraints instead:
  - The guard finds function bodies by counting `{`/`}` per line and assumes no
    brace-bearing string or regex literal in either editor. Write the marker check
    WITHOUT literal braces — e.g. `text.indexOf("\x7b\x7b")` — with a comment citing
    the drift guard. A literal `"{{"` or `/\{\{/` silently extends `onSubmit`'s body
    to end-of-file.
  - If a new named function is added to `filltable_editor.js`, update
    `EXPECTED_COUNTS[FILL_JS]` (currently 37). Never loosen the guard.

### 8. Transfer (export / import / duplicate)

- `_ser_fill_table` needs NO change: its static branch already copies the cell
  whole (`dict(c)`), so once `_cell` keeps `gaps` the export carries it for free.
  The export → import round-trip test is the guard.
- `FORMAT_VERSION` 15 → 16 (`courses/transfer/schema.py`), so an older instance
  refuses a v16 archive (`importer.py:194`) instead of rendering raw `\uffff` tokens.
  A v15 archive imports unchanged (no `gaps` anywhere). `gaps` is honoured
  whatever the archive's version: a hand-made older archive carrying `gaps` is
  repaired by `reconcile_gaps` like any other, and the author owns their archive —
  no version-gated drop.
  - Seven tests pin `assert FORMAT_VERSION == 15` and must move to 16:
    `courses/tests/test_beforeafter_transfer.py`, `test_caption_transfer.py`,
    `test_image_size_transfer.py`, `tests/test_link_transfer.py`,
    `tests/test_table_transfer.py`, `tests/test_tabs_transfer.py`,
    `tests/test_transfer_schema.py`.
  - Two branches making the same 15 → 16 bump merge with NO conflict. Before
    merge, check no other open branch/PR also bumps `FORMAT_VERSION`.
- `_val_fill_table`: if a static cell (kind neither `answer` nor `image`) has
  `gaps`, it must be a list, else reject — gross structural corruption only, matching
  that validator's stated lenient policy. Entry-level problems (non-list entry,
  non-string alternative) and index mismatches are left to `reconcile_gaps`, which
  repairs them per entry.
- Duplicate-unit and cross-unit element copy run through export/import → covered.

### 9. Other readers of fill-table cells

- `courses_manage_extras` builder summary: *"N answer(s)"* counts answer cells + gaps.
- `courses/recolour/*` (`dbscan.py` `CELL_FIELDS`, `replay.py`) rewrites fill-table
  cell `html`; the plan must verify it leaves a `\uffff{n}\uffff` token intact.
  `fix_space_before_punctuation` never reads `FillTableElement.data` (its docstring
  excludes answer keys from FIELDS), so it needs no check.
- `views.py:155` math-delimiter detection reads static `html` — tokens contain no
  delimiters; unaffected.

### 10. Existing live data with a literal `{{`

After deploy, the form parses every static cell on every save. An EXISTING cell
holding `{{…}}` outside maths would silently become an answer box the next time
anything in its table is saved, and a stray unclosed `{{` would make the whole table
unsaveable with an error on a cell the author never touched.

**Required before merge:** query prod (read-only, or a fresh prod dump) for
fill-table static cells whose `html`, with `\(…\)`/`\[…\]` spans masked, contains
`{{` or `}}` — counting `{{` inside `$$…$$` as a hit too (§2: `$$` is not
protected); record the count and the element ids in the PR. Zero hits → nothing more to
do. Any hits → stop and bring them to the owner before merging (options: hand-edit
those cells, or add an escape); do not decide silently.

## Tests

Unit (no browser):
- `parse_cell_gaps` / `author_cell_html` are **idempotent**, not identity (spaces
  around alternatives are trimmed, entities normalised): parse → author → parse gives
  the same stored `(html, gaps)`. Cases: one gap, several gaps, gap between two
  maths spans, `{{` inside `\(…\)` (stays literal), alternatives with `|`, `<` in an
  answer, `{{ 9 | 9,0 }}`, no gaps.
- Markup in a marker: `{{<b>9</b>}}` and a colour-mapped `{{<span …>9</span>}}` both
  store the answer `9`.
- Maths in a marker: `{{9\(\pi\)}}` is rejected with the maths message (raised as
  `GapMathError`); an empty marker gets the empty/unclosed message, not the maths one;
  `{{9\(x}}\)` (maths overlapping the marker's end) gets the empty/unclosed message.
- Cap: 11 markers in a cell → form error; 10 → saves.
- Straddling tag: `<b>{{9</b>}}` stores the answer `9`, and after `save()` the cell
  html is balanced; `{<b>{</b>9}}` stays literal text with no gap.
- Escaping: a done-state first alternative containing `<` and `"` renders escaped in
  `value` (no raw `<` or attribute break-out).
- Form: empty and unterminated markers rejected with the right row/column; a table
  with only gaps saves; a table with neither answers nor gaps is rejected with the new
  message; a posted `gaps` key is ignored.
- **Gate through the FORM:** a POST whose only answers are `{{9}}` with `gate: true`
  stores `gate: True` (a model-level test would not catch the ordering bug in §3).
- `reconcile_gaps`: each rule in §4 (non-list entry, mixed blank/non-blank
  alternatives, untrimmed alternatives, duplicate token, orphan token, orphan entry,
  renumbering, all-removed → no `gaps` key), plus idempotence.
- Check view: per-gap verdicts with `g`; answer cells unchanged; `all_correct` needs
  both kinds; case sensitivity honoured for gaps.
- **Leak test:** the rendered student page for a table with gaps contains none of the
  answers (distinctive answer strings, asserted absent).
- Done state renders first alternatives, readonly, correct; gate stays on for a
  gaps-only gated table.
- Transfer: export → import round-trip keeps gaps; a v15 archive still imports; a
  malformed `gaps` is rejected.
- Builder summary count.

e2e (one, driving the real editor): author types `{{9}} \(\pi\)` into one cell and
`\((x+2)^2+(y\) {{-1}} \()^2=\) {{16}}` (TWO gaps) into another, saves; the student
page shows inline boxes beside rendered maths; the student answers the first gap of
the two-gap cell WRONG and the second RIGHT, + Check → each box gets its OWN
verdict (first red, second green); correcting it turns both green.

Falsify: the leak test, the `data-g` term of the paint selector (drop it → the
two-gap e2e must go RED), and the gate-counts-gaps rule through the form (parse
after `normalize_data` → the form gate test must go RED) each get a deliberate
mutant.

## Out of scope

- LAL importer emitting gaps instead of dropping text (possible small follow-up).
- Any automated repair of the 83 cells on libli.pl — the owner fixes them in the editor.
- Rendering gaps as chips in the editor (D3).
- Raw `{{…}}` parsing on non-form write paths (§3).
