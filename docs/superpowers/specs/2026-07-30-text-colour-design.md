# Text colour in rich text and table cells — design

**Date:** 2026-07-30
**Status:** approved (brainstorming), under spec review

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
| D7 | Parts `001_zbiory_liczbowe` and `002_elementy_logiki` are **excluded**, on both the source and DB sides | The user has made significant manual changes there. Those two parts hold only 29 of 697 spans (4%), so exclusion costs almost nothing. |
| D8 | `apply()` **refuses** a selection crossing a `\(…\)` / `\[…\]` boundary | Discovered during review: on the cell path the damage is permanent, not cosmetic (see "Maths overlap"). Refusing is the only option that cannot corrupt stored LaTeX. |

### Non-goals

- Background/highlight colour. Cheap to add later once `span` is allowed; doubles the
  contrast work, and no imported content uses it.
- Colouring *inside* a maths expression. That is `\color{}`'s job and the maths editor
  already offers it. See D8 for the enforced boundary.
- Restoring black, gray, magenta, purple, yellow or hex colours (109 spans, 16%). They
  drop to plain text. Explicitly accepted by the user: "the colours used in matematyka
  do not have to reflect the originals, some of them may be skipped".
- Any change to models, migrations, transfer schema or exporters.

### Rejected alternative: re-run the loader

`import_lal_content` already loads `out/**.json` idempotently, and `rebuild_unit_elements`
rebuilds a unit's elements from the same JSON. Once slice 1 teaches the sanitiser about
colour, re-running the loader over the 19 eligible parts would restore colour through an
already-tested path, with no new matcher.

It is rejected because **it would discard every edit made in an eligible part since the
import** — the loader rebuilds from source, so any post-import authoring is overwritten.
D6's property 3 (edited content is skipped) is the whole safety argument for slice 2, and
a rebuild inverts it. Recorded here so a plan-writer does not reopen the question, and so
the trade-off is on the record if the measured match rate (see "Acceptance gate") turns
out to be low.

## Palette

Four CSS custom properties — `--tc-red`, `--tc-blue`, `--tc-green`, `--tc-orange` —
defined in `core/static/core/css/tokens.css` in **both** the `:root` and
`[data-theme="dark"]` blocks. Utilities `.tc-red { color: var(--tc-red) }` etc. live in
`courses/static/courses/css/courses.css` next to `.ta-*` (currently 929-931).
`templates/courses/manage/editor/editor.html:6` already links `courses.css`, so the editor
surface and the student page share one definition.

**These four tokens are independent of `--danger`/`--success`/`--warning`.** Two dark
values (`--tc-green`, `--tc-orange`) happen to equal the corresponding semantic token
today. That is a coincidence of tuning, not aliasing: the light values differ, and the
semantic tokens are free to move for UI reasons without dragging the text palette with
them. Do not "simplify" by aliasing.

| slot | light | dark |
|---|---|---|
| `--tc-red` | `#C63E2F` | `#EA8A82` |
| `--tc-blue` | `#226DC3` | `#8FBCE8` |
| `--tc-green` | `#487A29` | `#9FBF7B` |
| `--tc-orange` | `#9C6016` | `#E8B761` |

Every value clears AA body text (4.5:1) against **every surface rich text can appear on**,
which is a larger set than the two page surfaces:

| surface | light worst | dark worst |
|---|---|---|
| `--surface-raised`, `--surface-base` | 4.51:1 | 5.65:1 |
| the four `.callout` backgrounds (`color-mix(accent 6%, --surface-raised)`, `courses.css:1414-1459`) | 4.51:1 | 5.12:1 |

`CalloutElement.body` is in `RICH_TEXT_FIELDS`, so the callout surfaces are reachable
authoring surfaces, not hypotheticals. The dark red is `#EA8A82` rather than the
semantic `--danger` dark `#E57373` precisely because the latter scores **4.26:1** on the
warning-callout background — below AA. The CSS test asserts against this full surface list.

Two consequences to accept knowingly:

- **Light orange is a dark amber** (`#9C6016`). Orange cannot reach 4.5:1 on a light
  background and still look orange. It stays clearly distinguishable from red, which is
  what colour-coding requires.
- **The palette does not match raw CSS `red`/`blue`/`green`/`orange`.** Measured against
  the tougher surface in each theme: CSS `orange` scores 1.75:1 on `--surface-base`, CSS
  `blue` 1.68:1 on dark `--surface-raised`. Divergence is deliberate; D4 is what keeps
  maths and prose consistent anyway.

## Architecture

### Storage contract

`courses/sanitize.py`:

- `ALLOWED_TAGS` gains `span`.
- A new `TC_CLASS_VALUES = {"tc-red", "tc-blue", "tc-green", "tc-orange"}`.
- `TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}`.
- `CELL_TAGS` gains `span`, and a new `CELL_ALLOWED_CLASSES` — covering only `CELL_TAGS`,
  not the block-tag alignment family — is passed to `sanitize_cell`'s `nh3.clean`, which
  today passes no `allowed_classes` at all.

**`ALLOWED_CLASSES` must be rebuilt, not mutated.** It is currently
`{tag: ALIGN_CLASS_VALUES for tag in ALIGN_CLASS_TAGS}` (line 45), a comprehension that
binds **the same set object** to all seven keys. Any in-place merge
(`ALLOWED_CLASSES[tag].update(...)` or `|=`) mutates `ALIGN_CLASS_VALUES` itself and
silently widens the allowlist for every tag. Build fresh sets per tag
(`ALIGN_CLASS_VALUES | TC_CLASS_VALUES` where both families apply), and add a test
asserting `ALIGN_CLASS_VALUES` is unchanged after import, plus one asserting `tc-*` is
**not** accepted on a tag outside `TC_CLASS_TAGS`.

`tc-*` on `b/i/em/strong/u` is defensive: `execCommand("foreColor")` may attach colour to
an existing inline wrapper rather than creating a fresh `span`, and if only `span` carried
the class the colour would vanish on save.

**`a` is deliberately included.** A selection that exactly covers a link's text commonly
styles the `<a>` itself, and a per-tag allowlist would then strip the class, losing the
colour silently on save. This touches a recorded invariant — internal links carry no
marker class, and the `href` prefix is their only styling hook — so it is a widening of
exactly four class values on `a` and nothing else. `ALLOWED_ATTRIBUTES` is unchanged, and
`test_sanitiser_passes_internal_links_through_untouched` must stay green.

Nothing else changes: colour rides inside strings that already round-trip through
transfer. Cell dicts keep their existing keys (`transfer/payloads.py:605` untouched).

### The three sanitisers, and which fields use which

The spec's field coverage cannot be read off field names — there are **three** sanitisers,
and `RICH_TEXT_FIELDS` alone is not the right registry for the backfill:

| sanitiser | fields | in scope? |
|---|---|---|
| `sanitize_html` | `TextElement.body`, `SpoilerElement.body`, `CalloutElement.body`, `QuestionElement.stem`/`.explanation` on every concrete question type | yes |
| `sanitize_cell` | table cells (`models.py:962`), filltable cells (`:1134`), MCQ `options` (`:738`), choicegrid cycler options (`:805`), gallery `img["desc"]` (`:1278`), `element_forms.py:419,513` | table + filltable cells only; the rest are **out of scope** (no authoring surface for colour, and no imported colour measured in them) |
| `sanitize_stem_segments` (`courses/switchgrid.py:54`, used by `builders.py:205,215,278,290,314`) | `FillGateElement.stem`, `SwitchGateElement.stem`, `GuessNumberElement.stem`, `SwitchGridElement.lines[*].stem` | yes for the three that are in `RICH_TEXT_FIELDS`; `SwitchGridElement.lines[*].stem` is out of scope (deliberately absent from that registry) |

The trap this table exists to prevent: three of those stem fields **are** in
`RICH_TEXT_FIELDS`, so a backfill that builds every key with `sanitize_html` would produce
keys that never match for them. **The key generator must select the sanitiser per field**,
from an explicit table, not from the registry membership.

### Maths overlap (D8)

The earlier draft said a colour span overlapping maths merely stops the maths rendering
and "can be undone". That is wrong on the cell path, and the correction is why D8 exists.

`_MATH_SPAN` (`sanitize.py:65`) is non-greedy and `DOTALL`, so it stashes
`\(x + <span class="tc-red">y\)` **including the injected markup**; `_canon_math`
(`sanitize.py:73`) then escapes it, baking a literal escaped `<span …>` into the stored
LaTeX. Both sanitisers are idempotent, so re-saving never heals it — the damage survives
the undo window.

Therefore `apply()` refuses a selection whose range crosses a `\(…\)` or `\[…\]`
delimiter boundary, on **both** surfaces (uniform rule; the cell consequence is what
forces it). Detection is on the surface's text content: locate the delimiter regions, and
refuse if the selection starts inside one and ends outside, or vice versa. A selection
wholly inside or wholly outside a region is allowed. The refusal is silent-but-visible: no
mutation, and the swatch does not take an active state.

The corpus measurement (0 contaminated maths spans across 697 imported spans) says the
*imported* content never has this shape. It says nothing about the editor, which is what
D8 governs.

### One colour map, three consumers

Colour reaches the map in three different vocabularies, so the map is keyed on a
**canonical `(r, g, b)` triple**, not on source-form literals:

```
normaliseColour(value) → (r, g, b) | null
  accepts  "#rgb", "#rrggbb", "rgb(r, g, b)", "rgba(r, g, b, a)",
           and the CSS keywords red / blue / green / orange

SLOTS   (198, 62, 47) → "red"      light --tc-red
        (234,138,130) → "red"      dark  --tc-red
        (255,  0,  0) → "red"      CSS keyword `red`
        …same three rows per slot for blue / green / orange
        anything else → null → element unwrapped, colour dropped
```

Why a canonical form is mandatory: both JS consumers read colour **back out of the DOM** —
`el.style.color` for the KaTeX pass, and the result of `execCommand("foreColor")` for the
editor — and browsers serialise those as `rgb(198, 62, 47)`, never as `#C63E2F` or `red`.
A map keyed on source literals would match nothing on either JS path. The Python consumer
reads bs4's view of the source attribute (`color: red;`), a third vocabulary. One
canonical form reconciles all three.

| consumer | input vocabulary |
|---|---|
| `text_colour.js` — applied and pasted colour | `rgb()` serialisation from the DOM |
| the KaTeX pass | `rgb()` serialisation from the DOM |
| `recolour_imported_content` | raw `style="color: …"` attribute text via bs4 |

`normaliseColour` and the slot table are implemented in both Python and JS. The drift test
compares the **canonical slot tables** — triple → slot — not the raw literals, because the
two languages legitimately accept different input forms over the same slots.

### Shared JS module

New `courses/static/courses/js/text_colour.js` exposing `window.libliColour`:

| export | contract |
|---|---|
| `MAP` | canonical triple → slot |
| `normaliseColour(value)` | any accepted form → canonical triple, or null |
| `apply(root, slot)` | colour the current selection, or clear it when `slot` is null; refuses per D8 |
| `normalise(root)` | rewrite inline colour to `tc-*` classes **in the live DOM**, in place |
| `activeSlot(root)` | the slot at the caret, or null |

`activeSlot` boundary behaviour, all three of which are reachable because several RTE
surfaces are live at once (`text_toolbar.js:146`):

- selection outside `root` → `null`
- selection spanning two different slots → `null`
- selection spanning coloured and uncoloured text → `null`

It is called from `refreshActive()` and the `selectionchange` listener
(`text_toolbar.js:212-258`), where every other active state is already computed.

**Nested-span collapse.** Recolouring the same text repeatedly yields
`<span class="tc-red"><span class="tc-blue">…`. `normalise()` collapses a `tc-*` span
whose only child is another `tc-*` span, **innermost wins** (it is the most recent
application). Without this, nesting grows unboundedly across a session while
`activeSlot()`'s nearest-ancestor read hides the growth. Idempotency of the pass is a
different property from convergence of the markup; both are required, and both are tested.

Three consumers: `text_toolbar.js`, `table_editor.js`, `filltable_editor.js`. The latter
two are the code-identical twins guarded by #169. **Acceptance rule:** all colour logic
lives in `text_colour.js`; the per-editor glue must be byte-identical in both files; the
#169 guard is re-run as part of slice 1's test list.

### Rich text editor

`apply()` uses `execCommand("foreColor")` with `styleWithCSS(true)` — it correctly splits
selections that straddle nested elements — then immediately calls `normalise(surface)` and
resets `styleWithCSS(false)`. That reset is mandatory: the flag is document-global and a
leaked `true` breaks bold/italic/underline (`text_toolbar.js:81-90`).

**Clearing colour** is `execCommand("foreColor")` applied with a sentinel value that
`normaliseColour` maps to `null`, followed by `normalise(surface)`, which unwraps any
element left carrying an unmapped colour. This reuses execCommand's selection-splitting
rather than hand-rolling `Range` surgery — the same reason it is used for applying. It
cannot be `removeFormat`, which would also strip bold and italic. Partial selections
follow from execCommand's own splitting: clearing colour on a subset of a coloured span
splits the span and leaves the untouched remainder coloured. That boundary case is tested
explicitly.

**Colour is converted to a class on the surface itself**, unlike alignment. Alignment
keeps inline styles on the surface (`text_toolbar.js:48-74`) because its active state
needs `queryCommandState("justifyCenter")`. Colour has no such need, and keeping inline
colour on the surface would show an author working in dark mode the *light-theme* hex.
Therefore:

- `classToStyle()` leaves `tc-*` untouched on load.
- **`normalise(surface)` runs on `paste` and `input`**, so the live DOM is authoritative.
  This is required, not decorative: `styleToClass()` is a **pure string** function
  (`text_toolbar.js:48-61`) that builds a detached `<div>` and returns HTML — it never
  touches the live surface. Relying on it alone would leave the textarea holding `tc-*`
  classes while the contenteditable still held inline colour, breaking both `activeSlot()`
  and the dark-mode rationale for exactly the pasted content.
- `styleToClass()` still runs on sync, as the belt-and-braces string-level pass.

**Paste of rendered maths.** Today, pasting a rendered KaTeX expression collapses to plain
text because every `span` is stripped. Once `span` is allowed, the whole `.katex` span
tree would survive as dozens of empty nested spans with the LaTeX source gone. The map's
rule settles it: **a `span` carrying no mapped colour is unwrapped**, in `normalise()` and
in the sanitiser's class allowlist alike. An e2e case covers pasting rendered maths.

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

**The obvious hook is the wrong one.** `window.libliRenderMath` is `renderMath`
(`math.js:12-19,42`), which visits only `[data-katex]` **display** elements. The inline
`\(…\)` prose maths this feature exists for is rendered by `window.renderMathInElement`,
called from ~20 sites across `math.js` (`renderInlineText`, itself not exported on
`window`), `question.js`, `quiz.js`, `choicegrid.js`, `dnd.js`, `filltable.js`,
`switchgate.js`, `switchgrid.js`, `editor.js` and `math_input.js`. Hooking
`libliRenderMath` alone would reach almost none of the affected content.

**Mechanism:** wrap `window.renderMathInElement` **once**, at load, in `text_colour.js` —
the wrapper calls through, then runs the colour normalisation over the same scope. Every
existing and future call site is covered without editing any of them. `libliRenderMath` is
additionally wrapped for the display path. The plan must enumerate and verify the call
sites against the wrapper, and confirm no site captures a reference to
`renderMathInElement` before the wrapper is installed — load order is the one way this
mechanism fails.

Two safety rules: a colour **not** in the map is left exactly as-is, so existing
`\color{purple}` content keeps rendering as it does today; and the pass is idempotent, so
re-renders and the `katexDone` guard are unaffected. Both are tested.

## Backfill command

```
manage.py recolour_imported_content --course <slug> \
    --exclude-part <dirname> --exclude-node <pk> [--apply]
```

`--course` takes a **slug** and resolves via `lal_loader.guards.resolve_course`, the same
helper `import_lal_content` uses. The intended target is the grafted `mat-pp` course.

Build, from the eligible `out/**.json` files, a map of `key → coloured value`, then walk
the course's content and rewrite a field **only when its stored value is byte-identical to
a key**.

### Key construction

The key is produced by **unwrapping** the colour spans — removing the `<span>` element and
keeping its children — *not* by dropping the `style` attribute. This is not a detail:
after slice 1 `span` is in `ALLOWED_TAGS`, so attribute-dropping would yield
`<span>założenie</span>`, which can never equal what the pre-change loader stored
(`założenie`, span fully removed). Only unwrapping produces a matchable key.

The key generator then applies **the sanitiser that owns that field** (see the
three-sanitiser table), so the key reproduces what the loader actually stored.

The unwrap is a bs4 pass, and this repo has a recorded trap there: `str(Tag)` re-escapes
entities while `str(NavigableString)` decodes them, so a body must be serialised with
`decode_contents()`. One entity difference in one span silently zeroes that key with no
error.

### Acceptance gate — measure the DB before writing anything

Every number in this spec is **source-side** (parser JSON → prototype → sanitiser).
Nothing has been measured against the `mat-pp` database, and slice 2 rests entirely on
byte-identity against stored values.

The plan's first slice-2 task is therefore: build the key map, run the lookup against the
local `mat-pp` DB **in dry-run**, and record matches per part. That number is the
acceptance gate. If it lands far below the source-side upper bound, the cause is almost
certainly key construction (wrong sanitiser per field, or the bs4 entity trap) — diagnose
before writing, and if it cannot be resolved, the rejected re-import alternative goes back
on the table for the parts with no post-import edits.

### Matching contract — two field shapes

**HTML fields** (`sanitize_html` and `sanitize_stem_segments` fields): the stored string is
compared to the key whole. Rewrite replaces the field.

**JSON cell fields** (`TableElement.data`, `FillTableElement.data`): the stored value is a
structure (`{"cells": [[{"html": …, "halign": …, "colspan": …}]]}`,
`transfer/payloads.py:605-625`), never byte-identical to an HTML key. So:

- the key is **one cell's `html`**, matched per cell;
- a table with 3 of 5 cells matching is rewritten **partially** — matching cells are
  recoloured, non-matching cells are left exactly as they are, and the row counts as one
  changed field;
- the write is `update_fields=["data"]`, which re-triggers `save()`'s `sanitize_cell` pass
  over every cell. That pass must be idempotent on the newly-coloured html — asserted by a
  test, because a non-idempotent pass would corrupt on write rather than on read.

### Safety properties

1. **Node names are untouchable.** `ContentNode.title` is never read and never written —
   it is not part of the key, the lookup, or the write. A test asserts every title is
   unchanged after a run.
2. **Renames, reorders, insertions and deletions are irrelevant**, for the same reason.
3. **Edited content is skipped.** Anything changed since import no longer equals a key.
4. **A key with two different colourings is refused**, reported, and skipped.

Measured on the corpus: **257** distinct colour-bearing stripped forms, matched by **306**
occurrences across the parser output, and **every repeated form is coloured identically —
0 conflicts**. The 306 counts occurrences in *all* parts, including excluded ones, so it is
an upper bound, not a prediction. The conflict guard is inert today but must exist: it is
the one shape that could colour something wrong, and a future re-parse could introduce it.

### Exclusion (D7) — both sides, two flags

Each side blocks a different failure, and each needs its **own** input, because a node pk
cannot be resolved to a source directory without reading titles (which D6 forbids):

- **Source side, `--exclude-part <dirname>`** — the named `out/` directories are not read,
  so their colourings never enter the map.
- **DB side, `--exclude-node <pk>`** — candidate rows are filtered out via
  `.exclude(elements__unit_id__in=subtree)`. Note the join: the content models in
  `RICH_TEXT_FIELDS` have no `unit` field and reach a unit through the `Element` join, as
  `richtext.py:262` already does. That exclusion is only correct because a content row has
  exactly one owning `Element` — the caveat recorded on `count_inbound_links` — so the
  command must fail closed if it ever encounters a content row reachable from more than
  one `Element`.

The command validates that the two lists have the same length, and that every
`--exclude-node` pk exists and belongs to `--course`.

Dry-run is the default. `--apply` writes in a transaction with `update_fields`. Output
reports per-part rewritten/skipped counts and the reason for each skip. Re-running after an
apply changes nothing, because stored values no longer equal the stripped keys — which
makes idempotency directly testable.

**Sequencing: run locally, before the mat-pp → prod export.** Colour then ships inside the
export bundle.

## Testing

**Unit — sanitiser.** Keeps `span.tc-*`; strips foreign classes, inline `style`, and `tc-*`
on tags outside `TC_CLASS_TAGS`; keeps `tc-*` on the inline emphasis tags and on `a`;
unwraps a `span` with no mapped colour; idempotent on both paths; preserves maths spans in
cells. `ALIGN_CLASS_VALUES` is unchanged after import (the aliasing guard). The existing
`test_sanitize_align.py:34` (no class on `<b class="ta-center">`) and
`test_sanitiser_passes_internal_links_through_untouched` must both stay green.

**CSS.** All four tokens defined in both themes, and every value clears 4.5:1 against the
full surface list — the two page surfaces **and** the four callout backgrounds.

**Drift.** The JS and Python canonical slot tables agree.

**Unit — JS.** `normaliseColour` accepts all four input forms; nested `tc-*` spans collapse
innermost-wins, so red→blue→red on one selection yields **one** span; `normalise()` is a
no-op on second call; `classToStyle()` passes `tc-*` through untouched.

**e2e (chromium).** Colour applied in the RTE survives save and reload; colour applied in a
table cell reaches the saved JSON; pasted inline-coloured HTML normalises to classes **in
the live surface**, not only in the textarea; pasting rendered KaTeX does not leave empty
spans; `\color{red}` and a prose `tc-red` resolve to the same computed colour; `\color{purple}`
is left untouched; a selection crossing a maths delimiter is refused (D8) in both a body
and a table cell; clearing colour on a subset of a coloured span leaves the remainder
coloured; both themes screenshotted and judged separately.

**Transfer round-trip.** Export a course carrying `tc-*` in a body **and** in a table cell,
import into a fresh course, assert byte-identity of both fields. This is the load-bearing
claim for how the work reaches production (D5) and was previously untested.

**Backfill.** Rewrites an untouched element; skips an edited one; leaves every node title
unchanged; honours `--exclude-part` and `--exclude-node`; rejects mismatched exclusion list
lengths and a pk from another course; rewrites a partially-matching table correctly; writes
nothing on a dry run; is a no-op on second run; refuses a conflicting key; fails closed on a
content row with more than one owning `Element`.

**Falsification.** Every test above is falsified — delete the thing it guards and require
RED — per this repo's standing rule that a passing test proves nothing on its own.

**After implementation:** a `frontend-design` pass on all three toolbars, **explicitly at
mobile widths (~360px)**. That is where the risk sits: the swatch group adds five controls
to table toolbars already carrying bold/italic/underline, three h-align, three v-align,
merge, split and header-toggle. If the group cannot wrap gracefully, the fallback is
collapsing the swatches into a single popover button on narrow viewports only.

## Delivery

Two slices, because they carry different risk and only the second touches existing content:

1. **Feature** — palette tokens, sanitiser, `text_colour.js`, three toolbars, the KaTeX
   wrapper, tests, i18n (five new labels; run `makemessages -l pl -l en --no-obsolete` so
   **both** catalogues stay current, and regenerate the `.mo` after merging master — a
   long-lived branch touching `locale/` has produced a silent binary conflict here before).
2. **Backfill** — `recolour_imported_content`, its tests, the DB-side acceptance
   measurement, and the local run.

Slice 2 must land before the mat-pp → prod export. A single plan document may cover both,
but they ship as separate PRs.

## Unknowns to measure during implementation

Stated as claims to test, not as facts:

1. **What KaTeX serialises.** Source-level, `katex.min.js` concatenates `color: ` + the raw
   token into an inline `style`. Whether `el.style.color` reads back as `"red"` or
   `rgb(255, 0, 0)`, and whether the colour lands on the wrapper or on descendants, must be
   checked in a real browser before the slot table is written.
2. **What `execCommand("foreColor")` emits** with `styleWithCSS` true and false, in Chrome
   and Firefox — a fresh `span`, or a style on an existing inline element (including an
   `<a>`). This decides whether the `TC_CLASS_TAGS` widening is load-bearing or
   belt-and-braces.
3. **Whether wrapping `renderMathInElement` is sufficient** — i.e. no call site captures a
   reference before the wrapper is installed.
4. **Whether the swatch group fits** the two table toolbars at 360px.

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

### Prototype run — scope and reconciliation

A prototype colouriser plus the **real** sanitisers, over parts excluding `001_`/`002_`,
produced **446** `tc-*` classes — 274 through `sanitize_html` and 172 through
`sanitize_cell` — with **zero** maths spans contaminated by markup and **zero** outputs
containing a literal escaped `<span`. Two source spans were lost in cleaning.

That 446 does **not** reconcile to 588-minus-excluded, and the gap is scope, not loss: the
prototype walked only the JSON keys `body`, `html`, `stem` and `explanation`, and counted
only the four palette colours. Spans in fields it did not walk — gallery `desc`, MCQ
`options`, switchgrid line stems, `latex` — are excluded from the 446 and are also, per the
three-sanitiser table, out of scope for the backfill. The remaining difference is
therefore expected; the DB-side acceptance gate is what turns any of these figures into a
real prediction.
