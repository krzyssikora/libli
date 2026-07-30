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
| D8 | `apply()` **refuses** any selection intersecting a `\(…\)` / `\[…\]` region, unless it strictly encloses whole regions | On the cell path the damage is permanent, not cosmetic (see "Maths overlap"). |
| D9 | Two distinct DOM passes: `mapColours()` and `tidyPastedSpans()` | They have opposite duties. Conflating them destroys rendered KaTeX (see "Two passes"). |

### Non-goals

- Background/highlight colour. Cheap to add later once `span` is allowed; doubles the
  contrast work, and no imported content uses it.
- Colouring *inside* a maths expression. That is `\color{}`'s job and the maths editor
  already offers it. D8 is the enforced boundary.
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
the trade-off is on the record if the measured match rate falls below the acceptance gate.

## Palette

Four CSS custom properties — `--tc-red`, `--tc-blue`, `--tc-green`, `--tc-orange` —
defined in `core/static/core/css/tokens.css` in **both** the `:root` and
`[data-theme="dark"]` blocks. Utilities `.tc-red { color: var(--tc-red) }` etc. live in
`courses/static/courses/css/courses.css` next to `.ta-*` (currently 929-931).
`templates/courses/manage/editor/editor.html:6` already links `courses.css`, so the editor
surface and the student page share one definition.

**These four tokens are independent of `--danger`/`--success`/`--warning`.** Some dark
values coincide with a semantic token today; that is tuning coincidence, not aliasing. The
semantic tokens are free to move for UI reasons without dragging the text palette with
them. Do not "simplify" by aliasing.

| slot | light | dark |
|---|---|---|
| `--tc-red` | `#B2372A` | `#EA8A82` |
| `--tc-blue` | `#1F61AD` | `#8FBCE8` |
| `--tc-green` | `#3F6B24` | `#9FBF7B` |
| `--tc-orange` | `#8A5514` | `#E8B761` |

### The surface list is the specification

Rich text renders on far more than the two page surfaces, and the palette must clear AA
body text (4.5:1) on **all** of them. This list is normative — the CSS test asserts
against exactly it:

| # | surface | light | dark |
|---|---|---|---|
| 1 | `--surface-raised` | `#FFFFFF` | `#2C2925` |
| 2 | `--surface-base` | `#F4F1EA` | `#1A1816` |
| 3 | `--surface-sunken` — `.question__feedback-panel` base and its neutral/validation variants (`courses.css:59,78-79`) | `#FAF8F3` | `#15130F` |
| 4 | `--danger-subtle` — `.question__feedback-panel--incorrect` (`_quiz_question_feedback.html:27`) | `#F2D9D5` | `#3A1E1A` |
| 5 | `--success-subtle` — `.question__feedback-panel--correct` (`:37`) | `#E3ECD7` | `#2A3620` |
| 6 | `--warning-subtle` | `#F4E8CD` | `#3A2F18` |
| 7-10 | the four `.callout` backgrounds, `color-mix(accent 6%, --surface-raised)` (`courses.css:1414-1459`) | mixes | mixes |

Measured worst case over all ten: **light 4.51:1** (red on `--danger-subtle`),
**dark 5.12:1** (red on the warning callout). Every slot clears AA on every surface.

Surfaces 3-6 are why the light values are darker than an earlier draft's. `CalloutElement.body`
and `QuestionElement.explanation` are both `RICH_TEXT_FIELDS` fields, and the explanation
renders inside the quiz feedback panels — where the previous light palette measured
**3.79:1**, below AA, while a CSS test restricted to surfaces 1-2 would have passed. The
dark red is `#EA8A82` rather than the semantic `--danger` dark `#E57373` for the same
reason: `#E57373` measures 4.26:1 on the warning callout.

Two consequences to accept knowingly:

- **Light orange is a dark amber** (`#8A5514`). Orange cannot reach 4.5:1 on light
  backgrounds and still look orange. It stays clearly distinguishable from red, which is
  what colour-coding requires.
- **The palette does not match raw CSS `red`/`blue`/`green`/`orange`.** Measured against
  the tougher of surfaces 1-2 in each theme: CSS `orange` scores 1.75:1 on
  `--surface-base`, CSS `blue` 1.68:1 on dark `--surface-raised`. Divergence is
  deliberate; D4 is what keeps maths and prose consistent anyway.

## Architecture

### Storage contract

`courses/sanitize.py`:

- `ALLOWED_TAGS` gains `span`.
- `TC_CLASS_VALUES = {"tc-red", "tc-blue", "tc-green", "tc-orange"}`.
- `TC_CLASS_TAGS = {"span", "b", "i", "em", "strong", "u", "a"}`.
- `CELL_TAGS` gains `span`, and a new `CELL_ALLOWED_CLASSES` — covering only `CELL_TAGS`,
  not the block-tag alignment family — is passed to `sanitize_cell`'s `nh3.clean`, which
  today passes no `allowed_classes` at all.

**`ALLOWED_CLASSES` must be rebuilt, not mutated.** It is currently
`{tag: ALIGN_CLASS_VALUES for tag in ALIGN_CLASS_TAGS}` (line 45), a comprehension that
binds **the same set object** to all seven keys. Any in-place merge
(`ALLOWED_CLASSES[tag].update(...)` or `|=`) mutates `ALIGN_CLASS_VALUES` itself and
silently widens the allowlist for every tag. `ALIGN_CLASS_TAGS` and `TC_CLASS_TAGS` are
**disjoint**, so the result is a merge of two independent dicts, each built with fresh
sets — no tag needs a union today. Add a test asserting `ALIGN_CLASS_VALUES` is unchanged
after import, and one asserting `tc-*` is not accepted on a tag outside `TC_CLASS_TAGS`.

`tc-*` on `b/i/em/strong/u` is defensive: `execCommand("foreColor")` may attach colour to
an existing inline wrapper rather than creating a fresh `span`.

**`a` is deliberately included.** A selection that exactly covers a link's text commonly
styles the `<a>` itself, and a per-tag allowlist would strip the class, losing the colour
silently on save. This touches a recorded invariant — internal links carry no marker
class, the `href` prefix is their only styling hook — so it widens exactly four class
values on `a` and nothing else. `ALLOWED_ATTRIBUTES` is unchanged, and
`test_sanitiser_passes_internal_links_through_untouched` must stay green.

**What the sanitiser cannot do.** Measured against the installed nh3: with `span` in
`tags` and `allowed_classes={"span": {"tc-red"}}`,

```
in  : <span class="katex"><span class="mord">x</span></span>
out : <span class=""><span class="">x</span></span>
```

nh3's `allowed_classes` filters class *tokens*; it has **no unwrap-on-disallowed-class
capability** (`clean_content_tags` deletes content, which is worse). So:

- the sanitiser **strips the class and keeps the element**;
- unwrapping a meaningless span is a **JS/bs4 responsibility**, never the sanitiser's —
  which is also what D3 requires;
- on the **no-JS path** (raw textarea submission), pasted rendered KaTeX is therefore
  stored as nested `<span class="">`. This is accepted: it is inert, invisible, and the
  no-JS path is already the degraded one. The unit test asserts nh3's **actual** output,
  not an unwrap that cannot happen.

Nothing else changes: colour rides inside strings that already round-trip through
transfer. Cell dicts keep their existing keys (`transfer/payloads.py:605` untouched).

### The three sanitisers, and which fields use which

Field coverage cannot be read off field names — there are **three** sanitisers, and
`RICH_TEXT_FIELDS` alone is not the right registry for the backfill:

| sanitiser | fields | in scope? |
|---|---|---|
| `sanitize_html` | `TextElement.body`, `SpoilerElement.body`, `CalloutElement.body`, `QuestionElement.stem`/`.explanation` on every concrete question type | yes |
| `sanitize_cell` | table cells (`models.py:962`), filltable cells (`:1134`), MCQ `options` (`:738`), choicegrid cycler options (`:805`), gallery `img["desc"]` (`:1278`), `element_forms.py:419,513` | table + filltable cells only; the rest are **out of scope** (no authoring surface for colour, no imported colour measured in them) |
| `sanitize_stem_segments` (`courses/switchgrid.py:54`, used by `builders.py:205,215,278,290,314`) | `FillGateElement.stem`, `SwitchGateElement.stem`, `GuessNumberElement.stem`, `SwitchGridElement.lines[*].stem` | yes for the three in `RICH_TEXT_FIELDS`; `SwitchGridElement.lines[*].stem` is out of scope |

**The three gate stems have two owning sanitisers depending on write path.**
`sanitize_stem_segments` is documented as used by the import builder, "which bypasses the
form's clean()-time sanitize" (`switchgrid.py:56-57`), while a form edit goes through
`sanitize_html` (`models.py:776-779`). They have different tag allowlists —
`sanitize_stem_segments` delegates to `sanitize_cell` (`CELL_TAGS`). Therefore:

- the backfill's key generator must reproduce the **import** path
  (`sanitize_stem_segments`), because that is what the loader stored;
- `tc-*` must be allowed under **both** `CELL_ALLOWED_CLASSES` and `ALLOWED_CLASSES`, so a
  later form edit of a backfilled stem does not strip the colour.

### Maths overlap (D8)

An earlier draft said an overlapping colour span merely stops the maths rendering and can
be undone. That is wrong on the cell path. `_MATH_SPAN` (`sanitize.py:65`) is non-greedy
and `DOTALL`; `_canon_math` (`sanitize.py:73`) escapes whatever it stashed. So
`\(<span class="tc-red">x</span> + y\)` — a selection **wholly inside** a region — is
still delimiter-balanced, gets stashed *with the span*, and is escaped into the stored
LaTeX permanently. Both sanitisers are idempotent, so re-saving never heals it.

The rule is therefore **not** "wholly inside is fine". `apply()` refuses whenever the
selection intersects a maths region, with one exception:

| selection vs. a `\(…\)` / `\[…\]` region | outcome |
|---|---|
| wholly outside every region | allowed |
| strictly encloses one or more whole regions | **allowed** — the span wraps the delimiters rather than splitting them, so the stashed LaTeX is untouched |
| wholly inside a region | **refused** |
| starts inside, ends outside (or vice versa) | **refused** |
| any region with an unbalanced or unclosed delimiter in the scan root | **refused** (fail closed) |

**Detection** is not a lookup. A DOM `Range` yields (node, offset) pairs, not indices into
`root.textContent`, so the plan must implement an explicit mapping step: a `TreeWalker`
accumulation over text nodes producing a global text offset for the range's start and end,
then an interval test against the delimiter regions found by scanning that same text. The
scan root is **the RTE surface** for rich text and **the individual cell** for table
editors. Delimiters may straddle element boundaries (`\(x + <b>y</b>\)`), which the
text-offset approach handles by construction and which has a dedicated unit test.

**Refusal is announced, not silent.** An author who selects across maths and clicks a
swatch must be told why. Reuse the `.op-error` bar pattern already used for the
editor-conflict message (`text_toolbar.js:126-137`) with a translated string. A silent
no-op is the data-loss-shaped failure this repo already rejects elsewhere.

The corpus measurement (0 contaminated maths spans across 697 imported spans) says the
*imported* content never has this shape. It says nothing about the editor, which is what
D8 governs.

### One colour map, three consumers

Colour arrives in three vocabularies, so the map is keyed on a canonical `(r, g, b)`
triple, not on source-form literals:

```
normaliseColour(value) → (r, g, b) | null
  accepts  "#rgb", "#rrggbb", "rgb(r, g, b)", "rgba(r, g, b, a)",
           and the CSS keywords red / blue / green / orange

SLOTS   (178, 55, 42) → "red"      light --tc-red
        (234,138,130) → "red"      dark  --tc-red
        (255,  0,  0) → "red"      CSS keyword `red`
        …same three rows per slot for blue / green / orange
```

**`null` means "no slot", not "delete".** The caller decides the action, and the two
callers decide differently — this was a contradiction in an earlier draft:

| caller | unmapped colour |
|---|---|
| editor / author path (`apply`, `tidyPastedSpans`) | **dropped** — it cannot be stored anyway, since the sanitiser strips unknown classes and all inline style |
| render path (the KaTeX wrapper) | **left exactly as-is** — so existing `\color{purple}` content keeps rendering as it does today |

Why a canonical form is mandatory: both JS consumers read colour **back out of the DOM** —
`el.style.color` for the KaTeX pass, the result of `execCommand("foreColor")` for the
editor — and browsers serialise those as `rgb(178, 55, 42)`, never `#B2372A` or `red`. A
map keyed on source literals would match nothing on either JS path. The Python consumer
reads bs4's view of the source attribute (`color: red;`), a third vocabulary.

The drift test compares the **canonical slot tables** (triple → slot), not raw literals,
because the two languages legitimately accept different input forms. Follow the
`tests/test_richtext_drift.py` pattern; the JS table must be a single literal the test can
extract, so refactoring it into computed form reddens the suite.

### Two passes, not one (D9)

Conflating these destroys rendered maths: KaTeX output is overwhelmingly spans carrying no
colour at all (`<span class="mord mathnormal">`, `<span class="base">`, struts,
delimiters), so a pass that unwraps colourless spans would flatten every rendered
expression.

| pass | touches | never touches | run by |
|---|---|---|---|
| `mapColours(root)` | only elements carrying an **inline colour**: maps it to a `tc-*` class and clears the style (author path), or maps it and leaves unmapped values alone (render path) | any element without inline colour | the KaTeX wrapper; the editor after `apply()`; the editor on `input` |
| `tidyPastedSpans(root)` | only `span` elements with **no allowed class, no inline colour and no other attribute** — unwraps them | any element carrying semantics: `a`, `b`, `em`, …, or a span with a `tc-*`/`ta-*` class | the editor, on paste only |

A test asserts rendered KaTeX survives the wrapper byte-for-byte apart from colour
attributes.

### Shared JS module

New `courses/static/courses/js/text_colour.js` exposing `window.libliColour`:

| export | contract |
|---|---|
| `MAP` | canonical triple → slot |
| `normaliseColour(value)` | any accepted form → canonical triple, or null |
| `apply(root, slot)` | colour the selection, or clear it when `slot` is null; refuses per D8 |
| `mapColours(root, {dropUnmapped})` | see D9 |
| `tidyPastedSpans(root)` | see D9 |
| `activeSlot(root)` | the slot at the caret, or null |

`activeSlot` boundary behaviour — all three reachable, because several RTE surfaces are
live at once (`text_toolbar.js:146`):

- selection outside `root` → `null`
- selection spanning two different slots → `null`
- selection spanning coloured and uncoloured text → `null`

Called from `refreshActive()` and the `selectionchange` listener (`text_toolbar.js:212-258`).

**Never leave `tc-*` on a tag outside `TC_CLASS_TAGS`.** Selecting a whole paragraph is an
ordinary gesture, and Unknown #2 concedes it is not yet known which element `foreColor`
styles. If it styles the block, a naive pass produces `p.tc-red`, the sanitiser strips it,
and the colour vanishes on save with no feedback — the exact failure the `a` widening
exists to prevent. `mapColours` must move the class onto a wrapping/inner `span` instead.
Unit test on `<p style="color:…">`; e2e on select-whole-paragraph → colour → save → reload.

**Nested-span collapse.** Recolouring the same text yields
`<span class="tc-red"><span class="tc-blue">…`. `mapColours` collapses a `tc-*` span whose
only **rendered** content is another `tc-*` span — whitespace-only text nodes are ignored,
because `execCommand` routinely emits them and an "only child" predicate would fail on
shapes that are semantically identical. Innermost wins (most recent application).
Idempotency of the pass and convergence of the markup are different properties; both are
required and both are tested.

**Caret and undo.** Mutating the live DOM under a contenteditable collapses the selection
and cannot be reversed by `execCommand`-driven undo. Two requirements: `mapColours` saves
and restores the `Range` across any mutation, and it is a **no-op when nothing needs
rewriting**, so ordinary typing never mutates the DOM. An e2e case covers apply-then-undo.

Three consumers: `text_toolbar.js`, `table_editor.js`, `filltable_editor.js`. The latter
two are the code-identical twins guarded by #169. **Acceptance rule:** all colour logic in
`text_colour.js`; per-editor glue byte-identical in both files; the #169 guard re-run as
part of slice 1's test list.

### Rich text editor

`apply()` uses `execCommand("foreColor")` with `styleWithCSS(true)` — it correctly splits
selections straddling nested elements — then calls `mapColours(surface, {dropUnmapped:
true})` and resets `styleWithCSS(false)`. That reset is mandatory: the flag is
document-global and a leaked `true` breaks bold/italic/underline (`text_toolbar.js:81-90`).

**Clearing colour** applies `foreColor` with a sentinel, then `mapColours`. The sentinel is
`rgb(1, 2, 3)`, chosen against three constraints: it must be a colour the browser accepts
(`inherit`/`unset` are rejected or inconsistent across engines), it must not collide with
any of the twelve mapped triples, and it must be one no author would plausibly type. A
unit assertion pins `normaliseColour(SENTINEL) === null` and the sentinel's absence from
`MAP`.

**Clearing is tag-dependent, and this is load-bearing.** `TC_CLASS_TAGS` exists because
`foreColor` may colour an existing `<a>` or `<b>`. If clearing *unwrapped* that element it
would delete the link and its `href`, or delete the bold — inverting the very reason `a`
was included:

| element carrying the cleared colour | action |
|---|---|
| bare `<span>` with no other allowed class or attribute | unwrap |
| any other tag (`a`, `b`, `em`, `strong`, `i`, `u`), or a span with another class/attribute | remove the `tc-*` class and the inline colour **only**; keep the element |

An e2e case colours a link, clears it, and asserts the link survives with its `href`.

Partial selections follow from execCommand's own splitting: clearing on a subset of a
coloured span splits it and leaves the remainder coloured. Tested explicitly.

**Colour is a class on the surface itself**, unlike alignment. Alignment keeps inline
styles on the surface (`text_toolbar.js:48-74`) because its active state needs
`queryCommandState("justifyCenter")`. Colour has no such need, and inline colour on the
surface would show an author in dark mode the *light-theme* hex. Therefore:

- `classToStyle()` leaves `tc-*` untouched on load.
- **`input` is the hook**, not `paste`. The `paste` event fires *before* the default
  insertion, so a handler on it sees the pre-paste DOM and normalises nothing; `input`
  fires afterwards with `inputType: "insertFromPaste"`. If `paste` is wired at all it must
  defer (`queueMicrotask`) — but `input` alone is sufficient and is what the plan specifies.
- **`mapColours` and `tidyPastedSpans` must run *before* `sync`.** Listener order is
  registration order, and `sync` is already wired at `text_toolbar.js:197`. Registering the
  colour glue afterwards means the textarea is written from the *un-normalised* surface,
  and any save path that does not go through the form's `submit` handler — the editor's
  fragment saves — stores inline colour, which the sanitiser then strips. Silent colour
  loss on exactly the pasted content the mechanism exists for. Either register ahead of
  `sync` inside `wireRte`, or have the colour pass call `sync()` itself. The paste e2e
  asserts the **textarea value** carries `tc-*` immediately after the paste.
- `styleToClass()` is **not** part of this mechanism. It only rewrites `el.style.textAlign`
  (`text_toolbar.js:48-61`) and does nothing with colour. An earlier draft called it a
  belt-and-braces string-level fallback; that was vacuous. The live-DOM pass is the sole
  mechanism, and because it runs before `sync`, the textarea receives classes through the
  ordinary sync path.

**Paste of rendered maths** is handled by `tidyPastedSpans` (D9), which unwraps the
classless, colourless `.katex` spans. An e2e case covers it.

### Toolbar

Inline swatches, no popover. A popover means new focus management and re-fighting the
selection-loss problem the link dialog already fights (`text_toolbar.js:108-112`); five
18px squares cost roughly the width of two icon buttons.

```
[B][I][U] [red][blue][green][orange][none] │ [H2][H3][H4] │ [ul][ol][link][quote][code] │ [∑]
```

All three toolbars dispatch on `[data-cmd]` (`text_toolbar.js:204`, `table_editor.js:527`),
so the five controls have a **stated contract** the twins can be byte-identical to:
`data-cmd="colour-red"`, `colour-blue`, `colour-green`, `colour-orange`, `colour-none`,
each with a translated `title` and `aria-label` (colour alone cannot name a control). The
active swatch is indicated by a ring, not by colour alone. The "no colour" control is a
bordered square with a CSS diagonal — no new sprite entry.

Appended to `_rte_toolbar.html`, `_edit_table.html` (near 41-43) and `_edit_filltable.html`
(near 50-52). In the table editors the group rides the existing toolbar `mousedown`
preventDefault that preserves `focusCell` (`table_editor.js:523`), and `mapColours()` must
run on the cell **before** `innerHTML` is harvested into the JSON payload
(`table_editor.js:174`) or the colour is dropped at save.

### KaTeX normalisation

**The obvious hook is the wrong one.** `window.libliRenderMath` is `renderMath`
(`math.js:12-19,42`), which visits only `[data-katex]` **display** elements. The inline
`\(…\)` prose maths this feature exists for is rendered by `window.renderMathInElement`,
called from ~20 sites across `math.js` (`renderInlineText`, itself not exported),
`question.js`, `quiz.js`, `choicegrid.js`, `dnd.js`, `filltable.js`, `switchgate.js`,
`switchgrid.js`, `editor.js` and `math_input.js`.

**Mechanism:** wrap `window.renderMathInElement` once, at load, in `text_colour.js`; the
wrapper calls through and then runs `mapColours(scope, {dropUnmapped: false})`. Every
existing and future call site is covered without editing any. `libliRenderMath` is wrapped
too, for the display path.

**Load order is the failure mode, and it is not about captured references.** All scripts
are `defer`, so they execute in document order, and `math.js` calls `renderMath(document)`
and `renderInlineText(document)` **at module evaluation**. A `text_colour.js` placed after
`math.js` therefore misses the entire initial page render — the dominant case. The wrapper
also cannot be installed before `auto-render.min.js` defines `window.renderMathInElement`.

**Insertion point: after `auto-render.min.js`, before `math.js`**, inside the same
`{% if has_math %}` gate, in each of the five templates that load KaTeX:

| template | note |
|---|---|
| `courses/lesson_unit.html` | lines 61-63 are katex → auto-render → math.js |
| `courses/quiz_unit.html` | |
| `courses/manage/editor/editor.html` | |
| `courses/quiz_results.html` | loads katex + auto-render but **not** `math.js`; renders `el.explanation` |
| `courses/manage/review_submission.html` | same shape as quiz_results |

Defensive requirement: if `window.renderMathInElement` is undefined at wrap time, install a
lazy accessor rather than silently no-op.

## Backfill command

```
manage.py recolour_imported_content --course <slug> \
    --exclude <dirname>=<pk> [--exclude <dirname>=<pk> …] [--apply]
```

`--course` takes a **slug** and resolves via `lal_loader.guards.resolve_course`, the same
helper `import_lal_content` uses. The intended target is the grafted `mat-pp` course.

Build, from the eligible `out/**.json` files, a map of `key → coloured value`, then walk
the course's content and rewrite a field **only when its stored value is byte-identical to
a key**.

### Key construction

The key is produced by **unwrapping** the colour spans — removing the `<span>` and keeping
its children — *not* by dropping the `style` attribute. After slice 1, `span` is allowed,
so attribute-dropping would yield `<span>założenie</span>`, which can never equal what the
pre-change loader stored (`założenie`). Only unwrapping produces a matchable key.

The generator then applies **the sanitiser that owns that field on the import path** (see
the three-sanitiser table — for gate stems that is `sanitize_stem_segments`, not
`sanitize_html`), so the key reproduces what the loader actually stored.

The unwrap is a bs4 pass, and this repo has a recorded trap there: `str(Tag)` re-escapes
entities while `str(NavigableString)` decodes them, so a body must be serialised with
`decode_contents()`. One entity difference in one span silently zeroes that key with no
error.

### Acceptance gate — measure the DB before writing anything

Every number in this spec is **source-side** (parser JSON → prototype → sanitiser). Nothing
has been measured against the `mat-pp` database, and slice 2 rests entirely on byte-identity
against stored values.

The first slice-2 task is therefore to build the key map, run the lookup against the local
`mat-pp` DB **in dry-run**, and record matches per part. The gate has a numeric pass
condition, fixed before the measurement is taken:

- **≥ 70%** of the eligible-part occurrences match, **and**
- **no eligible part matches zero.**

On failure the run **halts** — no `--apply`. A zero-matching part almost always means key
construction is wrong for a field type (wrong sanitiser, or the bs4 entity trap); a broad
shortfall means edits are more widespread than assumed. If it cannot be resolved, the
rejected re-import alternative returns to the table for parts with no post-import edits.

### Matching contract — two field shapes

**HTML fields** (`sanitize_html` and `sanitize_stem_segments` fields): the stored string is
compared to the key whole; the rewrite replaces the field.

**JSON cell fields** (`TableElement.data`, `FillTableElement.data`): the stored value is a
structure (`{"cells": [[{"html": …, "halign": …}]]}`, `transfer/payloads.py:605-625`),
never byte-identical to an HTML key. So:

- the key is **one cell's `html`**, matched per cell;
- a table with 3 of 5 cells matching is rewritten **partially** — matching cells recoloured,
  the rest untouched, counting as one changed field;
- the write is `update_fields=["data"]`, which re-triggers `save()`'s `sanitize_cell` pass
  over every cell; that pass must be idempotent on the newly-coloured html.

**Whether `save()` re-sanitises differs by field shape**, so the safety net is not uniform:

| field shape | save-time sanitisation |
|---|---|
| `sanitize_html` fields | yes — `save()` re-sanitises |
| JSON cell fields | yes — `save()` re-sanitises every cell |
| the three gate stems | **no** — `save()` explicitly declines to touch `stem` (`models.py:776-779`) |

Because the gate stems have no net, the backfill must **read back every rewritten field and
assert it equals what was written** (byte-identity after round-trip), not merely assert that
the cell sanitiser is idempotent.

### Safety properties

1. **Node names are untouchable.** `ContentNode.title` is never read and never written. A
   test asserts every title is unchanged after a run.
2. **Renames, reorders, insertions and deletions are irrelevant**, for the same reason.
3. **Edited content is skipped.** Anything changed since import no longer equals a key.
4. **A key with two different colourings is refused**, reported, and skipped.

Measured on the corpus: **257** distinct colour-bearing stripped forms, matched by **306**
occurrences across the parser output, and **every repeated form is coloured identically —
0 conflicts**. The 306 counts occurrences in *all* parts, so it is an upper bound. The
conflict guard is inert today but must exist: it is the one shape that could colour
something wrong.

### Exclusion (D7) — paired, not two parallel lists

**The DB-side failure being blocked:** a key built from an eligible part can match text that
is byte-identical inside an *excluded* part, and would then recolour content the user has
hand-edited. Source-side exclusion alone cannot prevent that.

An earlier draft used two independent flags validated only for equal length — which two
correct-length but mismatched lists would pass. Instead each `--exclude` takes an explicit
**`<dirname>=<pk>` pair**, so the correspondence is stated by the operator, not inferred:

- the named `out/` directory is not read, so its colourings never enter the map;
- the paired node's subtree is filtered out of the candidate rows.

Validation and edge cases:

- every pk must exist and belong to `--course`;
- a dirname that does not exist under `out/` is an error (guards against typos silently
  disabling the exclusion);
- **a part whose node was deleted** from the DB: the pair may name the dirname with an empty
  pk (`<dirname>=`), excluding source-side only, and the command reports it;
- **one source part mapping to several nodes** after manual restructuring: the flag is
  repeatable with the same dirname and different pks, and all named subtrees are excluded.

Candidate rows are filtered with `.filter(elements__unit__course=course)` as the base
queryset (mirroring `richtext.py:246`) and `.exclude(elements__unit_id__in=subtree)`, where
`subtree = set(node._subtree_node_ids())` — the same private helper `richtext.py:253` uses,
and the descendant walk is the whole correctness of the exclusion. The base filter is not
optional: `.exclude()` on a reverse relation keeps rows with **no** `Element` at all, so an
orphaned content row would otherwise survive both filters. That exclusion is also only
correct because a content row has exactly one owning `Element` — the caveat recorded on
`count_inbound_links` — so the command **fails closed** if it encounters a content row
reachable from more than one `Element`.

Dry-run is the default. `--apply` writes in a transaction with `update_fields`. Because a
transaction protects against a partial write but not against a *wrong* one, take a
`dumpdata` of the affected models before `--apply` — the run is local and the cost is
trivial. Output reports per-part rewritten/skipped counts and the reason for each skip.
Re-running after an apply changes nothing, because stored values no longer equal the keys.

**Sequencing: run locally, before the mat-pp → prod export.** Colour then ships inside the
export bundle.

## Testing

**Unit — sanitiser.** Keeps `span.tc-*`; strips foreign classes, inline `style`, and `tc-*`
on tags outside `TC_CLASS_TAGS`; keeps `tc-*` on the inline emphasis tags and on `a`;
**asserts nh3's actual output for a disallowed class — `<span class="">`, element kept, not
unwrapped**; idempotent on both paths; preserves maths spans in cells. `ALIGN_CLASS_VALUES`
unchanged after import. `test_sanitize_align.py:34` and
`test_sanitiser_passes_internal_links_through_untouched` stay green.

**CSS.** All four tokens defined in both themes, and every value clears 4.5:1 against **all
ten surfaces** in the normative surface list.

**Drift.** The JS and Python canonical slot tables agree, following `test_richtext_drift.py`.

**Unit — JS.** `normaliseColour` accepts all four input forms and returns null for the
sentinel; `mapColours` moves a class off a block tag onto a span; nested `tc-*` spans
collapse innermost-wins **including the whitespace-text-node shape**; `mapColours` is a
no-op on second call and when nothing needs rewriting; `tidyPastedSpans` unwraps a bare
span but never one carrying `tc-*`/`ta-*` or another attribute; `classToStyle()` passes
`tc-*` through untouched; D8's Range→offset mapping refuses a region whose delimiters
straddle an element boundary and fails closed on an unclosed delimiter.

**e2e (chromium).** Colour survives save and reload in the RTE and in a table cell; pasted
inline-coloured HTML normalises in the live surface **and the textarea value carries `tc-*`
immediately after paste**; pasting rendered KaTeX leaves no empty spans; rendered KaTeX
survives the wrapper apart from colour attributes; `\color{purple}` is left untouched;
colouring a whole paragraph survives save; colouring a link then clearing leaves the link
and its `href` intact; clearing on a subset of a coloured span leaves the remainder
coloured; apply-then-undo leaves consistent markup; D8 refuses a selection wholly inside
`\(x+y\)` **on the cell path** and shows the translated message; both themes screenshotted
and judged separately.

**e2e — D4 on the student side.** `\color{red}` and a prose `tc-red` resolve to the same
computed colour, pinned to `lesson_unit.html` (where the load-order constraint is real),
plus a second instance on `quiz_results.html`, which loads auto-render **without** `math.js`.

**Transfer round-trip.** Export a course carrying `tc-*` in a body **and** a table cell,
import into a fresh course, assert byte-identity of both fields. This is the load-bearing
claim for how the work reaches production (D5).

**Backfill.** Rewrites an untouched element; skips an edited one; leaves every node title
unchanged; honours the `<dirname>=<pk>` exclusions and rejects a bad dirname, a pk from
another course, and an empty-pk pair used without report; rewrites a partially-matching
table; reads back every rewritten field and asserts byte-identity; writes nothing on a dry
run; no-ops on second run; refuses a conflicting key; fails closed on a content row with
more than one owning `Element`; halts when the acceptance gate is not met.

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
   wrapper across five templates, tests, i18n (**six** new labels: four colours, "no
   colour", and the D8 refusal message; run `makemessages -l pl -l en --no-obsolete` so
   both catalogues stay current, and regenerate the `.mo` after merging master — a
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
   and Firefox — a fresh `span`, a style on an existing inline element (including an `<a>`),
   or a style on the block. This decides whether the `TC_CLASS_TAGS` widening and the
   move-off-block rule are load-bearing or belt-and-braces.
3. **Whether wrapping `renderMathInElement` before `math.js` is sufficient** in all five
   templates.
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

That 446 does not reconcile to 588-minus-excluded, and the gap is scope, not loss: the
prototype walked only the JSON keys `body`, `html`, `stem` and `explanation`, and counted
only the four palette colours. Spans in fields it did not walk — gallery `desc`, MCQ
`options`, switchgrid line stems, `latex` — are excluded from the 446 and are also, per the
three-sanitiser table, out of scope for the backfill. The remaining difference is expected;
the DB-side acceptance gate is what turns any of these figures into a real prediction.
