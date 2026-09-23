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
  question;
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
cell's `html` holds an opaque token `￿{n}￿` at box `n`'s position — the
same sentinel/token as `courses/fillblank.py` (`SENTINEL`, `_TOKEN`, `_TOKEN_RE`).

```json
{"kind": "static", "html": "￿0￿ \\(\\pi\\)", "gaps": [["9"]], "halign": "left", "valign": "top"}
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
- `author_cell_html(cell) -> str` — the inverse for the editor: tokens become
  `{{alt1|alt2}}`, alternatives html-escaped (`quote=False`), exactly as
  `fillblank.to_author_stem`. Identity for a cell without `gaps`.
- `reconcile_gaps(html, gaps) -> (html, gaps)` — the read-side repair (§4).
- `answer_cells` is unchanged; a new `gap_cells(cells)` yields `(r, c, g, alts_string)`
  for every gap so the "has at least one answer" and "no blank answer" rules and the
  check view can iterate answer cells and gaps together.

### 3. Saving

**Form** (`FillTableElementForm.clean_data`, `courses/element_forms.py`): for every
static cell, sanitise then `parse_cell_gaps`; store `token_html` in `html` and set
`gaps` (omit the key when empty). A `FillBlankError` becomes a `ValidationError`
naming the cell: *"Row %(r)d, column %(c)d: an answer box `{{…}}` is empty or not
closed."* (1-based, translated).

The existing rules extend to gaps:
- "at least one answer" — satisfied by ≥1 answer cell OR ≥1 gap. Message becomes:
  *"Add at least one answer — mark an answer cell, or type `{{answer}}` in a cell."*
- "no blank answer" — gaps can never be blank (parse rejects empty markers), so the
  rule stays as-is for answer cells.

**Model** (`FillTableElement._cell` + `_sanitized_data`):
- `_cell` carries `gaps` through for a static cell when it is a list of lists of
  strings; anything else is dropped. Then `reconcile_gaps` (§4).
- `_sanitized_data` does NOT parse raw `{{…}}`. Only the form converts author
  markers. Other write paths (transfer import, course builder, LAL loader) store what
  they are given; a raw `{{9}}` arriving by those paths renders as literal text,
  which is today's behaviour. (YAGNI: no current producer emits markers.)
- `normalize_data`'s gate check counts gaps as answers (a gated table made only of
  inline boxes keeps its gate).

### 4. Token/answer consistency (read-side repair, never an error)

A stored cell's tokens and `gaps` can disagree only through a damaged archive or a
hand DB edit. `reconcile_gaps`, run in `_cell`:
- a token whose index has no entry in `gaps` → the token is removed from `html`;
- a `gaps` entry with no token in `html` → the entry is dropped;
- tokens are renumbered to `0..k-1` in document order and `gaps` reordered to match,
  so the check view's `g` index always equals the rendered box's index;
- a gap entry whose alternatives are all blank → token and entry both removed.

Never raises; a repaired cell simply shows fewer boxes.

### 5. Student render

`templates/courses/elements/_filltable_cell.html`, static branch: when the cell has
`gaps`, split `html` on `_TOKEN_RE` (the `fillblank.render_inputs` technique) and
safe-join the trusted sanitised text segments with server-built inputs:

```html
<input type="text" class="filltable__input filltable__input--inline"
       data-r="R" data-c="C" data-g="G" aria-label="Answer, row R+1, column C+1, box G+1">
```

- Same `filltable__input` class → verdict colours, `lock()`, the confirm handler and
  the reveal gate all apply unchanged. `--inline`: `display:inline-block; width:8ch;`
  plus the (0,2,0) `.el--filltable` prefix the verdict rules need (see the specificity
  note at `courses.css` "`.el--filltable` IS THE POINT") — a fixed width, never sized
  to the answer.
- aria-label omits "box N" when the cell has exactly one gap. Translated.
- **Done state** (`mine.done`, `canonical_cells`): each gap input renders
  `value=<first alternative>`, `readonly`, `filltable__input--correct` — mirroring the
  answer-cell done branch. `canonical_cells` returns a `gaps_display` (first
  alternatives) alongside, never mutating `self.data`.
- The answer list is NEVER emitted into the page. The render builds from `html`
  tokens only; `gaps` is read only in the done state (answers already earned).
- Implementation note: this is best done in Python (a template filter or a
  precomputed `cell.parts` list), not template string-splitting.

### 6. Checking

`filltable_check` (`courses/views.py`) iterates answer cells (POST key `r{r}c{c}`,
unchanged) AND gaps (POST key `r{r}c{c}g{g}`), each through the existing
`blank_matches(got, alts, case_sensitive=…)`. Response cells gain an optional `g`:
`{"r":1,"c":2,"g":0,"correct":true}`. `all_correct` requires every answer cell and
every gap correct; zero of both → the existing empty response.

`filltable.js`: `submit` appends `g` to the key when `data-g` is present; `paint`
selects `[data-r][data-c][data-g]` when the reply carries `g`, else
`[data-r][data-c]:not([data-g])`. The `:not([data-g])` is required — a cell's gaps
share its `r`/`c`, so a bare `[data-r][data-c]` selector would paint a gap with an
answer cell's verdict.

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
- ⚠️ The table and fill-table editors are drift-guarded twins. This change touches
  only the fill-table side; teach the drift guard the difference, never weaken it.

### 8. Transfer (export / import / duplicate)

- `_ser_fill_table` carries `gaps` on a static cell when present.
- `FORMAT_VERSION` 15 → 16 (`courses/transfer/schema.py`), so an older instance
  refuses a v16 archive (`importer.py:194`) instead of rendering raw `￿` tokens.
  A v15 archive imports unchanged (no `gaps` anywhere).
- `_val_fill_table`: if a static cell has `gaps`, it must be a list of lists of
  strings, else reject (gross corruption, matching that validator's lenient policy).
  Index mismatches are left to `reconcile_gaps`.
- Duplicate-unit and cross-unit element copy run through export/import → covered.

### 9. Other readers of fill-table cells

- `courses_manage_extras` builder summary: *"N answer(s)"* counts answer cells + gaps.
- `courses/recolour/*` and `fix_space_before_punctuation`: operate on cell `html`
  only. The plan must verify each leaves a `￿{n}￿` token intact (a
  space-fixer rule adjacent to a token must not merge or split it).
- `views.py:155` math-delimiter detection reads static `html` — tokens contain no
  delimiters; unaffected.

## Tests

Unit (no browser):
- `parse_cell_gaps` / `author_cell_html` round-trip is identity on: one gap, several
  gaps, gap between two maths spans, `{{` inside `\(…\)` (stays literal), alternatives
  with `|`, `<` in an answer, no gaps.
- Form: empty and unterminated markers rejected with the right row/column; a table
  with only gaps saves; a table with neither answers nor gaps is rejected with the new
  message.
- `reconcile_gaps`: each of the four repair cases.
- Check view: per-gap verdicts with `g`; answer cells unchanged; `all_correct` needs
  both kinds; case sensitivity honoured for gaps.
- **Leak test:** the rendered student page for a table with gaps contains none of the
  answers (distinctive answer strings, asserted absent).
- Done state renders first alternatives, readonly, correct; gate stays on for a
  gaps-only gated table.
- Transfer: export → import round-trip keeps gaps; a v15 archive still imports; a
  malformed `gaps` is rejected.
- Builder summary count.

e2e (one, driving the real editor): author types `{{9}} \(\pi\)` into a cell, saves;
the student page shows an inline box beside a rendered π; typing `9` + Check turns it
green; typing `8` turns it red and leaves an answer cell in the same table correctly
painted (the `:not([data-g])` selector).

Falsify: the leak test, the `:not([data-g])` paint selector, and the gate-counts-gaps
rule each get a deliberate mutant that must turn a test RED.

## Out of scope

- LAL importer emitting gaps instead of dropping text (possible small follow-up).
- Any automated repair of the 83 cells on libli.pl — the owner fixes them in the editor.
- Rendering gaps as chips in the editor (D3).
- Raw `{{…}}` parsing on non-form write paths (§3).
