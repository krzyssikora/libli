# Text colour in rich text and table cells — design

**Date:** 2026-07-30
**Status:** approved (brainstorming), ready for planning

## Problem

Authors cannot colour text. Two consequences:

1. **New content.** There is no way to colour-code terms — the default idiom in maths
   teaching (`x` red, `y` blue, the coefficient orange).
2. **Imported content already lost its colour.** The LAL parser output in
   `scripts/lal_import/out/**.json` carries **697 `<span style="color: …">` spans across
   106 files in 19 of 21 parts**. `sanitize_html` has never allowed `span`
   (`courses/sanitize.py:11-34`), so the loader stored the words and dropped the colour.
   Verified by running the real sanitiser on a real body:

   ```
   SOURCE : jeśli ( <span style="color: red;">założenie</span> ) to
            ( <span style="color: blue;">teza</span> )
   STORED : jeśli ( założenie ) to ( teza )
   ```

   In that content the colour is load-bearing, not decoration: red = hypothesis,
   blue = thesis. The maths half of the same sentence still renders coloured, because
   KaTeX handles `\color{red}` natively — so today the two halves disagree.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Fixed palette of **four** slots: red, blue, green, orange | Covers 588 of 697 imported spans (84%) and is exactly the set used for colour-coding algebra. Arbitrary colours would require allowing `style` through the sanitiser — a permanent security surface — and authors would pick values that vanish in dark mode. |
| D2 | Colour is a **class on an inline element**, never inline style | Mirrors the shipped `ta-*` alignment mechanism (`sanitize.py:43-45`); keeps the sanitiser a token-level allowlist. |
| D3 | The sanitiser stays **purely subtractive** | Translating `style="color:…"` → class requires parsing author HTML. Regex attribute surgery on author HTML is the trap that has already bitten this repo (see `richtext.py:79-95`). Translation happens only where a real parser exists: the browser (editor) and bs4 (backfill). |
| D4 | **KaTeX output is normalised** onto the same palette | Prose and maths colour appear in the same sentence in the imported content. Also makes maths colour theme-aware and AA-compliant, which it is not today. |
| D5 | Backfill via a **guarded management command**, run locally before the prod cutover | Colour then reaches prod through the sanctioned #68 export/import flow with no prod-side migration. |
| D6 | Backfill matches on **content, never node identity** | Many matematyka nodes have been renamed. Titles are not read or written at any point. |
| D7 | Parts `001_zbiory_liczbowe` and `002_elementy_logiki` are **excluded by node pk** | The user has made significant manual changes there. Those two parts hold only 29 of 697 spans (4%), so exclusion costs almost nothing. |

### Non-goals

- Background/highlight colour. Cheap to add later once `span` is allowed; doubles the
  contrast work, and no imported content uses it.
- Colouring *inside* a maths expression from the toolbar. That is `\color{}`'s job and
  the maths editor already offers it. **Defined behaviour:** a selection overlapping a
  `\(…\)` region is *not* prevented; the span splits the LaTeX and the maths stops
  rendering, which the author sees immediately and can undo. No data is corrupted — the
  sanitiser preserves the LaTeX text either way (measured: 0 contaminated maths spans
  across the corpus). Detecting and refusing such selections is deliberately out of scope.
- Restoring black, gray, magenta, purple, yellow or hex colours (109 spans, 16%). They
  drop to plain text. Explicitly accepted by the user: "the colours used in matematyka
  do not have to reflect the originals, some of them may be skipped".
- Any change to models, migrations, transfer schema or exporters.

## Palette

Tokens in `core/static/core/css/tokens.css`, in both the `:root` and
`[data-theme="dark"]` blocks, beside `--danger`/`--success`/`--warning`. Utilities
`.tc-*` in `courses/static/courses/css/courses.css` next to `.ta-*` (currently 929-931).
`manage/editor/editor.html:6` already links `courses.css`, so the editor surface and the
student page share one definition.

| slot | light | on light `--surface-base` | dark | on dark `--surface-raised` |
|---|---|---|---|---|
| `tc-red` | `#C63E2F` | 4.51:1 | `#E57373` | 4.85:1 |
| `tc-blue` | `#226DC3` | 4.60:1 | `#8FBCE8` | 7.25:1 |
| `tc-green` | `#487A29` | 4.55:1 | `#9FBF7B` | 7.04:1 |
| `tc-orange` | `#9C6016` | 4.54:1 | `#E8B761` | 7.84:1 |

Ratios are WCAG 2.x against the **tougher** surface in each theme — `--surface-base`
(`#F4F1EA`) in light, `--surface-raised` (`#2C2925`) in dark. All four clear AA body text
(4.5:1) in both themes.

Two consequences to accept knowingly:

- **Light orange is a dark amber** (`#9C6016`). Orange cannot reach 4.5:1 on a light
  background and still look orange. It stays clearly distinguishable from red, which is
  what colour-coding requires.
- **The palette does not match raw CSS `red`/`blue`/`green`/`orange`.** Those score
  1.68:1 to 8.59:1 depending on hue and theme — orange 1.97:1 on light, blue 1.68:1 on
  dark. Divergence is deliberate; D4 is what keeps maths and prose consistent anyway.

## Architecture

### Storage contract

`courses/sanitize.py`:

- `ALLOWED_TAGS` gains `span`.
- `ALLOWED_CLASSES` gains the colour family. It is currently built as a comprehension
  over one family (`{tag: ALIGN_CLASS_VALUES for tag in ALIGN_CLASS_TAGS}`, line 45) and
  must be restructured to merge two families per tag.
- `CELL_TAGS` gains `span`, and `sanitize_cell`'s `nh3.clean` call starts passing
  `allowed_classes` — today it passes none, which is why no class survives a cell.
- `tc-*` is allowed on `span` **and** on `b`, `i`, `em`, `strong`, `u`.

That last allowance is defensive: `execCommand("foreColor")` may attach colour to an
existing inline wrapper rather than creating a fresh `span`, and if only `span` carried
the class the colour would silently vanish on save. **The plan must measure what Chrome
and Firefox actually emit** (see Unknowns).

`ALLOWED_ATTRIBUTES` is unchanged — in particular `a` still takes only `href`/`title`/
`rel`. Colouring a link puts the class on a wrapper, not the anchor; the internal-link
feature depends on the href prefix being the anchor's only marker hook.

Nothing else changes: colour rides inside strings that already round-trip through
transfer. Cell dicts keep their existing keys (`transfer/payloads.py:605` untouched), so
an export bundle carries colour with no schema change.

**Measured on the real corpus** (prototype colouriser + the real sanitisers, parts 001
and 002 excluded): 446 `tc-*` classes produced — 274 through `sanitize_html`
(body/stem/explanation) and 172 through `sanitize_cell` (table cell html) — with **zero**
maths spans contaminated by markup and **zero** outputs containing a literal escaped
`<span`. Two source spans were lost in cleaning. The `sanitize_cell` maths-stashing path
(`sanitize.py:83-99`), the one place where a nested span would corrupt LaTeX, is clean on
this content.

### One colour map, three consumers

```
COLOUR_MAP     accepted input              → slot
               #C63E2F, #E57373, red       → "red"
               #226DC3, #8FBCE8, blue      → "blue"
               #487A29, #9FBF7B, green     → "green"
               #9C6016, #E8B761, orange    → "orange"
               anything else               → no colour (span unwrapped)

consumers      text_toolbar.js / text_colour.js   applied + pasted colour → class
               libliRenderMath                    KaTeX inline colour     → class
               recolour_imported_content          imported style="color"  → class
```

Accepting the CSS colour names is what makes **paste from the old site** and the import
work through the same code path. The map is defined once in Python and mirrored in JS,
with a source-level drift test asserting the two literals agree — same guard style as
`test_richtext_drift.py` and `test_table_css.py`.

### Shared JS module

New `courses/static/courses/js/text_colour.js` exposing `window.libliColour`:

| export | contract |
|---|---|
| `MAP` | the four slots and their accepted input values |
| `apply(root, slot)` | colour the current selection, or clear it when `slot` is null |
| `normalise(root)` | rewrite inline colour to `tc-*` classes, in place |
| `activeSlot(root)` | the slot at the caret, or null — drives button state |

Three consumers: `text_toolbar.js`, `table_editor.js`, `filltable_editor.js`. The latter
two are the code-identical twins guarded by #169, so shared logic must not be duplicated
into both — this mirrors how `table_grid.js` already holds their shared algebra.

### Rich text editor

`apply()` uses `execCommand("foreColor")` with `styleWithCSS(true)` — it correctly splits
selections that straddle nested elements, which manual `Range` surgery does not — then
immediately calls `normalise(surface)` and resets `styleWithCSS(false)`. That reset is
mandatory: the flag is document-global and a leaked `true` breaks bold/italic/underline
(`text_toolbar.js:81-90`).

**Colour is converted to a class on the surface itself**, unlike alignment. Alignment
deliberately keeps inline styles on the surface (`styleToClass`/`classToStyle`,
`text_toolbar.js:48-74`) because its active state needs
`queryCommandState("justifyCenter")`. Colour has no such need — `activeSlot()` reads the
caret's ancestor class — and keeping inline colour on the surface would show an author
working in dark mode the *light-theme* hex while typing. Therefore:

- `classToStyle()` leaves `tc-*` untouched on load.
- `styleToClass()` additionally catches stray inline colour on sync, which is what makes
  **pasting** old-site HTML normalise itself.
- The "no colour" control unwraps `tc-*` within the selection. It cannot be
  `removeFormat`, which would also strip bold and italic.

### Toolbar

Inline swatches, no popover. A popover means new focus management and re-fighting the
selection-loss problem the link dialog already fights (`text_toolbar.js:108-112`); five
18px squares cost roughly the width of two icon buttons.

```
[B][I][U] [red][blue][green][orange][none] │ [H2][H3][H4] │ [ul][ol][link][quote][code] │ [∑]
```

The same group is appended to `_rte_toolbar.html`, `_edit_table.html` (near 41-43) and
`_edit_filltable.html` (near 50-52). In the table editors it rides the existing toolbar
`mousedown` preventDefault that preserves `focusCell` (`table_editor.js:523`), and
`normalise()` must run on the cell **before** `innerHTML` is harvested into the JSON
payload (`table_editor.js:174`) or the colour is dropped at save.

Each swatch carries a translated `title` and `aria-label` — colour alone cannot name a
control — and the active swatch is indicated by a ring, not by colour alone. The "no
colour" control is a bordered square with a CSS diagonal, so no new sprite entry.

### KaTeX normalisation

Inside `libliRenderMath`, after KaTeX renders, walk the rendered subtree, read each
element's inline colour, map it through `MAP`, set the class and clear the inline style.
`\color{red}{x^2}` and a prose `tc-red` word then resolve to the same token in both
themes.

Two safety rules: a colour **not** in the map is left exactly as-is, so existing
`\color{purple}` content keeps rendering as it does today; and the pass is idempotent, so
re-renders and the `katexDone` guard are unaffected.

## Backfill command

```
manage.py recolour_imported_content --course mat-pp \
    --exclude-node <pk> --exclude-node <pk> [--apply]
```

Build, from the eligible `out/**.json` files, a map of
`sanitised(colour-stripped source)` → `sanitised(coloured source)`. Then walk the
course's content and rewrite a field **only when its stored value is byte-identical to a
key**.

Properties, in order of importance:

1. **Node names are untouchable.** `ContentNode.title` is never read and never written —
   it is not part of the key, the lookup, or the write. A test asserts every title is
   unchanged after a run.
2. **Renames, reorders, insertions and deletions are irrelevant**, for the same reason.
3. **Edited content is skipped.** Anything changed since import no longer equals a key.
4. **A key with two different colourings is refused**, reported, and skipped.

Measured on the corpus: **257** distinct colour-bearing stripped forms, matched by **306**
occurrences across the parser output, and **every repeated form is coloured identically —
0 conflicts**. Note the 306 counts occurrences in *all* parts, including the excluded
ones, so it is an upper bound on what will be rewritten, not a prediction. The conflict
guard is therefore inert today, but must exist: it is the one shape that could colour
something wrong, and a future re-parse could introduce it.

Exclusion (D7) applies on **both** sides and must, because each side blocks a different
failure:

- **Source side** — the two part directories are not read, so their colourings never
  enter the map.
- **DB side** — candidate rows are filtered by node pk (`exclude(unit__in=subtree)`), so
  a value that appears in both an excluded and an eligible part cannot leak across, and a
  renamed part is still correctly excluded.

Field coverage reuses `courses/richtext.py`'s `RICH_TEXT_FIELDS` — the existing single
source of truth for "where rich text lives", already drift-guarded — plus a small sibling
registry for the JSON cell-bearing fields (`TableElement.data`, `FillTableElement.data`),
declared next to it.

Dry-run is the default. `--apply` writes in a transaction with `update_fields`. Output
reports per-part rewritten/skipped counts and the reason for each skip. Re-running after
an apply changes nothing, because stored values no longer equal the stripped keys — which
makes idempotency directly testable.

**Sequencing: run locally, before the mat-pp → prod export.** Colour then ships inside the
export bundle.

## Testing

**Unit.** Sanitiser keeps `span.tc-*`; strips foreign classes, inline `style`, and `tc-*`
on disallowed tags; keeps `tc-*` on the inline emphasis tags; is idempotent on both paths;
preserves maths spans in cells. The existing guard `test_sanitize_align.py:34` (no class
on `<b class="ta-center">`) must still pass — nh3's allowlist is per-tag.

**CSS.** All four slots defined in both themes (precedent: `test_table_css.py`).

**Drift.** The JS map literal and the Python map literal agree.

**e2e (chromium).** Colour applied in the RTE survives save and reload; colour applied in
a table cell reaches the saved JSON; pasted inline-coloured HTML normalises to classes;
`\color{red}` and a prose `tc-red` resolve to the same computed colour; both themes
screenshotted and judged separately.

**Backfill.** Rewrites an untouched element; skips an edited one; leaves every node title
unchanged; honours `--exclude-node`; writes nothing on a dry run; is a no-op on second
run; refuses a conflicting key.

**Falsification.** Every test above is falsified — delete the thing it guards and require
RED — per this repo's standing rule that a passing test proves nothing on its own.

**After implementation:** a `frontend-design` pass on all three toolbars, **explicitly at
mobile widths (~360px)**. That is where the risk sits: the swatch group adds five controls
to table toolbars already carrying bold/italic/underline, three h-align, three v-align,
merge, split and header-toggle. If the group cannot wrap gracefully, the fallback is
collapsing the swatches into a single popover button on narrow viewports only.

## Delivery

Two slices, because they carry different risk and the second is the only one that touches
existing content:

1. **Feature** — palette tokens, sanitiser, `text_colour.js`, three toolbars, KaTeX pass,
   tests, i18n (five new labels in `pl`, with the `.mo` regenerated after merging master;
   a long-lived branch touching `locale/` has produced a silent binary conflict here
   before).
2. **Backfill** — `recolour_imported_content`, its tests, and the local run.

Slice 2 must land before the mat-pp → prod export. A single plan document may cover both,
but they ship as separate PRs.

## Unknowns to measure during implementation

These are stated as claims to test, not as facts:

1. **What KaTeX serialises.** Source-level, `katex.min.js` concatenates `color: ` + the
   raw token into an inline `style`. Whether `el.style.color` then reads back as `"red"`
   or `rgb(255, 0, 0)`, and whether the colour lands on the wrapper or on descendants,
   must be checked in a real browser before the map is written.
2. **What `execCommand("foreColor")` emits** with `styleWithCSS` true and false, in Chrome
   and Firefox — a fresh `span`, or a style/attribute on an existing inline element. This
   decides whether the `tc-*`-on-emphasis-tags allowance is load-bearing or belt-and-braces.
3. **Whether the swatch group fits** the two table toolbars at 360px.

## Appendix — measured corpus data

Colour spans in `scripts/lal_import/out/**.json`, 697 total across 106 files:

| colour | spans | | part | spans |
|---|---|---|---|---|
| red | 222 | | `130_kombinatoryka` | 358 (51%) |
| blue | 174 | | `104_geometria_3_czworokaty` | 58 |
| green | 129 | | `040_funkcje_podstawy` | 39 |
| orange | 63 | | `045_wielomiany` | 36 |
| black | 37 | | `140_geometria_analityczna_2` | 32 |
| gray | 35 | | `002_elementy_logiki` | 25 *(excluded)* |
| magenta | 12 | | … 12 further parts | 145 |
| purple | 6 | | `001_zbiory_liczbowe` | 4 *(excluded)* |
| yellow | 5 | | `150_f_wykladnicza`, `120_wartosc_bezwzgledna` | 0 |
| hex/other | ~14 | | | |

Palette (D1) covers the first four rows: 588 spans, 84%.
