# Text colour in rich text and table cells — design

**Date:** 2026-07-30
**Status:** approved (brainstorming), under spec review

## Problem

Authors cannot colour text. Two consequences:

1. **New content.** There is no way to colour-code terms — the default idiom in maths
   teaching (`x` red, `y` blue, the coefficient orange).
2. **Imported content already lost its colour.** The LAL parser output in
   `scripts/lal_import/out/**.json` carries **697 `<span style="color: …">` **colour-bearing elements** across
   106 files in 19 of 21 parts**. They are *not* all spans — measured by carrier tag:
   `span` 510, `strong` 161, `p` 8, `li` 6, `u` 6, `figcaption` 4, `i` 2. `sanitize_html` has never allowed `span`
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
| D1 | Fixed palette of **four** slots: red, blue, green, orange | Covers 588 of 697 imported colour-bearing elements (84%) and is exactly the set used for colour-coding algebra. Arbitrary colours would require allowing `style` through the sanitiser — a permanent security surface — and authors would pick values that vanish in dark mode. |
| D2 | Colour is a **class on an inline element**, never inline style | Mirrors the shipped `ta-*` alignment mechanism (`sanitize.py:43-45`); keeps the sanitiser a token-level allowlist. |
| D3 | The sanitiser stays **purely subtractive** | Translating `style="color:…"` → class requires parsing author HTML. Regex attribute surgery on author HTML is the trap that has already bitten this repo (see `richtext.py:79-95`). Translation happens only where a real parser exists: the browser (editor) and bs4 (backfill). |
| D4 | **KaTeX output is normalised** onto the same palette | Prose and maths colour appear in the same sentence in the imported content. Also makes maths colour theme-aware and AA-compliant, which it is not today. |
| D5 | Backfill via a **guarded management command**, run locally before the prod cutover | Colour then reaches prod through the sanctioned #68 export/import flow with no prod-side migration. |
| D6 | Backfill matches on **content, never node identity** | Many matematyka nodes have been renamed. Titles are not read or written at any point. |
| D7 | Parts `001_zbiory_liczbowe` and `002_elementy_logiki` are **excluded**, on both the source and DB sides | The user has made significant manual changes there. Those two parts hold only 29 of 697 colour-bearing elements (4%), so exclusion costs almost nothing. |
| D8 | `apply()` **refuses** any selection intersecting a `\(…\)` / `\[…\]` region, unless it strictly encloses whole regions containing no element boundary | On the cell path the damage is permanent, not cosmetic (see "Protected regions"). |
| D9 | Two distinct DOM passes: `mapColours()` and `tidyPastedSpans()` | They have opposite duties. Conflating them destroys rendered KaTeX (see "Two passes"). |
| D10 | The same refusal covers `{{…}}` author markers | Allowing `span` opens a **new** corruption path: markers are parsed *after* sanitisation, so a coloured marker becomes the stored answer. See "Protected regions". |

### Non-goals

- Background/highlight colour. Cheap to add later once `span` is allowed; doubles the
  contrast work, and no imported content uses it.
- Colouring *inside* a maths expression. That is `\color{}`'s job and the maths editor
  already offers it. D8 is the enforced boundary.
- Colouring *inside* a `{{…}}` blank/choice marker. D10 refuses it; the marker's interior is
  parsed data, not prose.
- Restoring black, gray, magenta, purple, yellow or hex colours (109 elements, 16%). The
  colouriser **unwraps** them to plain text — note that after slice 1 the sanitiser can no
  longer do this itself, so the unwrap is the colouriser's explicit duty. Explicitly accepted by the user: "the colours used in matematyka
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
| 7 | `.callout--example` bg (`courses.css:1414-1459`) | `#F2F6FC` | `#313132` |
| 8 | `.callout--note` bg | `#F5F5F6` | `#34322F` |
| 9 | `.callout--tip` bg | `#F2F8F5` | `#2F332C` |
| 10 | `.callout--warning` bg | `#FAF6F1` | `#373229` |

Deliberately **excluded**: `.table-editor__grid .is-range` (`editor.css:627-632`), which
paints a `--primary` tint over a selected cell. It is transient selection chrome in an
authoring tool, not a surface body text is read on.

Rows 7-10 are `color-mix(in srgb, <accent> 6%, --surface-raised)` computed with **per-channel
`round()` in sRGB**; the test must use that convention, because the light margin is thin.
The assertion is `>= 4.5` on a ratio computed to at least two decimals.

Measured worst case over all ten: **light 4.51:1** (red on `--danger-subtle`),
**dark 5.12:1** (red on the warning callout). Every slot clears AA on every surface.

**The light margin is 0.01.** `--tc-red` and `--danger-subtle` are now coupled: neither may
move without re-running the full ten-surface measurement.

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
- `CELL_TAGS` gains `span`, and a new `CELL_ALLOWED_CLASSES = {tag: TC_CLASS_VALUES for tag in CELL_TAGS & TC_CLASS_TAGS}`
  — covering only cell tags, not the block-tag alignment family, and excluding `br`, which is
  in `CELL_TAGS` but not `TC_CLASS_TAGS` — is passed to `sanitize_cell`'s `nh3.clean`, which
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

| sanitiser | fields | in **backfill** scope? |
|---|---|---|
| `sanitize_html` | `TextElement.body`, `SpoilerElement.body`, `CalloutElement.body`, `GuessNumberElement.success_message` (`models.py:779`), `QuestionElement.stem`/`.explanation` on every concrete question type (`models.py:1604-1605`) | yes |
| `sanitize_cell` | table cells (`models.py:962`), filltable cells (`:1134`), MCQ `options` (`:738`), choicegrid cycler options (`:805`), gallery `img["desc"]` (`:1278`), `element_forms.py:419,513` | table + filltable cells only; the rest are **out of scope for the backfill** — and **measured** to carry zero palette colour: palette colour exists only under the JSON keys `body`, `html` and `stem` (see the appendix). The exclusion therefore costs nothing. |
| `sanitize_stem_segments` (`courses/switchgrid.py:54`, used by `builders.py:205,215,278,290,314`) | `FillGateElement.stem`, `SwitchGateElement.stem`, `GuessNumberElement.stem`, `SwitchGridElement.lines[*].stem` | yes for the three in `RICH_TEXT_FIELDS`. `SwitchGridElement.lines[*].stem` is out of **backfill** scope (2 palette occurrences) and is **not** an RTE surface — it is a bare textarea, so it gets no swatches and no D10 refusal; see "Protected regions" |

**Some fields are sanitised TWICE on the import path, and the key must reproduce the
composition.** `courses/lal_loader/builders.py:214` creates `FillBlankQuestionElement` with
`stem=sanitize_stem_segments(...)`, and `QuestionElement.save()` then re-applies
`sanitize_html` to `stem` and `explanation` (`models.py:1604-1605`). The stored value is
`sanitize_html(sanitize_stem_segments(x))`, which is materially different from
`sanitize_html(x)` — `sanitize_cell` strips block tags and `_canon_math` escapes the maths
spans. A key built with either sanitiser alone matches **nothing** for that field. There is **no** drag-fill-blank branch in the loader, so that model can hold no imported
colour. `builders.py:360/376/386` are `ChoiceQuestionElement`, `ShortNumericQuestionElement`
and `ShortTextQuestionElement`, each created with a bare `stem=el["stem"]` and **no**
builder-side sanitiser — their key is therefore `sanitize_html(x)` alone, applied by
`QuestionElement.save()`.

**The rule is therefore: reproduce the full import write path, in order, including any
`save()`-time sanitiser that runs after the builder's explicit one** — not "the sanitiser
that owns the field", which is ambiguous for exactly these fields.

**The three gate stems have two owning sanitisers depending on write path.**
`sanitize_stem_segments` is documented as used by the import builder, "which bypasses the
form's clean()-time sanitize" (`switchgrid.py:56-57`), while a form edit goes through
`sanitize_html` (`models.py:776-779`). They have different tag allowlists —
`sanitize_stem_segments` delegates to `sanitize_cell` (`CELL_TAGS`). Therefore:

- the backfill's key generator must reproduce the **import** path
  (`sanitize_stem_segments`), because that is what the loader stored;
- `tc-*` must be allowed under **both** `CELL_ALLOWED_CLASSES` and `ALLOWED_CLASSES`, so a
  later form edit of a backfilled stem does not strip the colour.

### Protected regions (D8, D10)

An earlier draft said an overlapping colour span merely stops the maths rendering and can
be undone. That is wrong on the cell path. `_MATH_SPAN` (`sanitize.py:65`) is non-greedy
and `DOTALL`; `_canon_math` (`sanitize.py:68`) escapes whatever it stashed. So
`\(<span class="tc-red">x</span> + y\)` — a selection **wholly inside** a region — is
still delimiter-balanced, gets stashed *with the span*, and is escaped into the stored
LaTeX permanently. Both sanitisers are idempotent, so re-saving never heals it.

The rule is therefore **not** "wholly inside is fine". `apply()` refuses whenever the
selection intersects a maths region, with one exception:

| selection vs. a `\(…\)` / `\[…\]` region | outcome |
|---|---|
| wholly outside every region | allowed |
| strictly encloses whole regions, **none of which contains an element boundary** | **allowed** — the span wraps the delimiters rather than splitting them, so the stashed LaTeX is untouched |
| strictly encloses a region that **does** contain an element boundary | **refused** — see below |
| wholly inside a region | **refused** |
| starts inside, ends outside (or vice versa) | **refused** |
| any region with an unbalanced or unclosed delimiter in the scan root | **refused** (fail closed) |

The element-boundary carve-out is not pedantry. For `\(x + <b>y</b>\)`, `foreColor` emits
**one span per element boundary** — the same splitting behaviour the spec relies on
elsewhere — so `\(` and `\)` end up in *different* spans. `_MATH_SPAN` then matches across
the intervening tags and `_canon_math` escapes them permanently on the cell path: exactly
the damage D8 exists to prevent, produced by a case an earlier draft called safe.

**`{{…}}` markers are protected identically (D10), and this is a new hazard created by
this feature.** `fillblank.py`'s documented order is `sanitize_html(raw) → strip_sentinel →
parse()`, so markers are parsed **after** sanitisation. Before slice 1 a `<span>` inside a
marker was stripped; once `span` is allowed, `{{<span class="tc-red">a</span>|b}}` still
matches `_MARKER_RE` (`fillblank.py:28`) and `group(1)` becomes the accepted-answer list —
the stored answer is HTML markup that no student input can ever match. `fillblank.parse` is called from **three** forms, not one — `FillGateElementForm`
(`element_forms.py:259`), `FillBlankQuestionElementForm` (`:816`) and
`DragFillBlankQuestionElementForm` (`:856`) — and it raises only on an empty/unterminated
marker or no blanks, so a coloured marker is *accepted* and stored as the answer list by all
three. For switchgate/switchgrid/guessnumber the exact-literal `{{choice}}` / `{{42}}` match
fails instead and the **form rejects the save** (`element_forms.py:411-417` catches
`SwitchGateError` and calls `add_error("stem", …)`).

So the split is: **fill-blank, drag-fill-blank and fill-gate corrupt silently**;
switch-gate, switch-grid and guess-number are rejected. The three silent ones are what make
D10 load-bearing rather than merely tidy.

Marker regions get the **same four-case table** as maths regions, found in the **same**
offset pass, on every marker-bearing field that is an RTE surface: the fill-blank,
**drag-fill-blank**, fill-gate, switch-gate and guess-number stems, all edited through
`_rte_toolbar.html`.

**SwitchGrid line stems are excluded, because they are not an RTE surface.**
`_edit_switchgrid.html:14` renders each one as a bare
`<textarea name="line-N-stem" rows="1" data-stem>` — no `data-rte-source`, no toolbar, no
contenteditable, so there is no swatch to refuse from and no live-DOM pass to hang the test
on. An author can still type raw HTML into that textarea, and per D3 the sanitiser cannot
detect a marker collision. **Recorded as a knowing gap**, not an oversight: promoting that
textarea to a full RTE surface is a materially larger change and would need its own decision
row.

**Detection** is not a lookup. A DOM `Range` yields (node, offset) pairs, not indices into
`root.textContent`, so the plan must implement an explicit mapping step: a `TreeWalker`
accumulation over text nodes producing a global text offset for the range's start and end,
then an interval test against the delimiter regions found by scanning that same text. The
scan root is **the RTE surface** for rich text and **the individual cell** for table
editors. Delimiters may straddle element boundaries (`\(x + <b>y</b>\)`), which the
text-offset approach handles by construction and which has a dedicated unit test.

**Refusal is announced, not silent.** An author who selects across maths or a marker and
clicks a swatch must be told why. Reuse the `.op-error` bar pattern used for the
editor-conflict message (`text_toolbar.js:126-137`) — and note that pattern reads its text
from a **template attribute**, not a JS constant. So: `editor.html` emits
`data-msg-colour-region` on the `.editor` root beside the existing `data-msg-conflict`,
`text_colour.js` reads it, and degrades silently when the attribute is absent, exactly as
the conflict path does. **`text_colour.js` owns the bar in all three editors** — it prepends
the `.op-error` element itself, reading the attribute off the nearest `.editor`, so the DOM
and the e2e selector are identical everywhere. The table editors' own announcement path
(`msg()`/`say()` into `[data-range-status]`, `table_editor.js:226-233`) is deliberately
**not** used for this message. **One** message covers both region kinds. A silent no-op is the
data-loss-shaped failure this repo already rejects elsewhere.

The corpus measurement (0 contaminated maths spans across all 697 colour-bearing elements) says the
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

**Removing the inline colour is mandatory on the render path too.** An inline
`style="color:…"` always beats a class in the cascade, so adding `tc-red` while leaving
KaTeX's inline `red` in place would leave maths raw, theme-unaware and sub-AA — D4 would
achieve exactly nothing while a test that merely asserts "a colour is present" still
passed. The D4 e2e therefore asserts the computed colour **equals the `--tc-red` token
value**.

**Clear the `color` longhand, not the `style` attribute.** KaTeX packs `height`,
`vertical-align` and `margin-right` into the same attribute; removing it destroys the
layout. Set `el.style.color = ""`, then `removeAttribute("style")` **only if the attribute
is now empty**. The byte-identity test uses a KaTeX span whose style carries both `color`
and a `height`.

**`null` means "no slot", not "delete".** The caller decides the action, and the two
callers decide differently — this was a contradiction in an earlier draft:

| caller | unmapped colour |
|---|---|
| editor / author path (`apply`, `tidyPastedSpans`) | **dropped** — it cannot be stored anyway, since the sanitiser strips unknown classes and all inline style |
| render path (the KaTeX wrapper) | **left exactly as-is** — so existing `\color{purple}` content keeps rendering as it does today |

Why a canonical form is mandatory: both JS consumers read colour **back out of the DOM** —
`el.style.color` for the KaTeX pass, the result of `execCommand("foreColor")` for the
editor — and browsers serialise those as `rgb(178, 55, 42)`, never `#B2372A` or `red`. A
map keyed on source literals would match nothing on either JS path. The Python consumer reads bs4's view of the source attribute, a third vocabulary — and it
needs a **declaration-parsing step** the value-level contract does not cover: split the
`style` attribute on `;`, split each declaration on the **first** `:`, `strip().lower()` the
property name, and require it to equal exactly `color` before handing the value to
`normaliseColour`. A suffix match is a real trap: the corpus contains `background-color:`
declarations that an unanchored `color:` search matches, and `color:red` with no space (12
occurrences) plus values with trailing whitespace and semicolons. Unit cases:
`background-color: red` yields **no** slot; `color:red` yields red.

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
| `mapColours(root, {dropUnmapped})` | only elements carrying an **inline colour**. A **mapped** colour always gets the `tc-*` class added **and** its inline colour removed, on *both* paths. An **unmapped** colour is dropped when `dropUnmapped` (author path) and left untouched otherwise (render path) | any element without inline colour | the KaTeX wrapper; the editor after `apply()`; the editor on `input` |
| `tidyPastedSpans(root)` | (a) a pasted `.katex` subtree — **replaced by its `annotation[encoding="application/x-tex"]` text**, wrapped in `\[…\]` when the subtree is display maths (`.katex-display` on it or its parent) and `\(…\)` otherwise; (b) any other `span` whose class list holds no `tc-*`/`ta-*` token and which carries no attribute other than `class`/`style` — unwrapped | any element carrying semantics: `a`, `b`, `em`, …, or a span with a `tc-*`/`ta-*` class | the editor, on `input` with `inputType` `insertFromPaste` or `insertFromDrop` |

Rule (a) is not optional and the earlier "unwraps classless spans" predicate could never
have satisfied it: KaTeX spans always carry `class`, and usually inline `style` and
`aria-hidden`, so **none** of them is classless. Worse, a `.katex` subtree contains a
`.katex-mathml` branch holding `<annotation>x^2</annotation>` plus the flattened glyph
text; `nh3.clean` strips disallowed *tags* but keeps their text, so a naive paste stores
the LaTeX source **and** the glyph text as visibly duplicated prose. Replacing the subtree
with its `annotation` text restores the author's original `\(x^2\)` and re-renders.

A test asserts rendered KaTeX survives the **wrapper** byte-for-byte apart from colour
attributes (the wrapper must never call `tidyPastedSpans`), and a separate test asserts a
pasted `.katex` subtree becomes `\(x^2\)` text — not merely that no empty spans remain — and
a display-maths paste becomes `\[…\]`, since `[data-katex]` renders with
`displayMode: true` (`math.js:6`) and rewrapping it inline is a silent visual downgrade.

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

**The active ring is an RTE-only affordance.** `table_editor.js` has no `refreshActive` and
no `selectionchange` listener — its toolbar handler (`:523-540`) only dispatches commands —
so the two table editors' swatches are **stateless**: they apply colour and never show an
active state. Stating this is what keeps the "byte-identical glue in both twins" rule
achievable; adding selection-tracking to the table editors is explicitly out of scope.

**Never leave `tc-*` on the root itself.** This is worse than the block-tag case:
`sync()` serialises `surface.innerHTML` (`text_toolbar.js:196`) and `serialize()` reads
`td.innerHTML` (`table_editor.js:174`), so anything `foreColor` puts on the `.rte-surface`
div or the contenteditable `<td>` is **never serialised at all** — the colour vanishes with
no sanitiser involved and no feedback. If the styled element is `root`, `mapColours` wraps
`root`'s children in a `span` carrying the class and clears the root's inline colour. Unit
case: `root` carrying `style="color:…"`.

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
shapes that are semantically identical. Innermost wins (most recent application). **A single element carrying two
slots** (`class="tc-red tc-blue"`, reachable via the HTML source view — measured: nh3 keeps
both) is normalised to **one** `tc-*` token, last wins, so the outcome never depends on
declaration order in `courses.css`.
Idempotency of the pass and convergence of the markup are different properties; both are
required and both are tested.

**Caret and undo.** Mutating the live DOM under a contenteditable collapses the selection
and cannot be reversed by `execCommand`-driven undo. Two requirements: `mapColours` saves and restores the `Range` **only when it actually
mutates and the current selection is inside `root`**, and it is a **no-op when nothing needs
rewriting**, so ordinary typing never mutates the DOM. The scoping is load-bearing because
`mapColours` also runs from the render wrappers: `editor.js` re-renders the preview after
every fragment swap (`:94,:242,:251`, plus the initial pass near `:493`; `editor.js:12` uses
a bare `renderMathInElement` global, which is what makes the wrapper cover the preview) while the author's caret may sit in a live
`.rte-surface`, and an unscoped `removeAllRanges()`/`addRange()` there would move a
selection belonging to a different subtree. An e2e case covers apply-then-undo.

Three consumers: `text_toolbar.js`, `table_editor.js`, `filltable_editor.js`. The latter
two are the code-identical twins guarded by #169. **Acceptance rule:** all colour logic in `text_colour.js`; **the inner colour-branch body
and the `mapColours`/`tidyPastedSpans` call expressions** byte-identical in both files; the
#169 guard re-run as part of slice 1's test list. The rule is deliberately *not* extended to
the enclosing guards and listener bodies, which already diverge and stay so —
`table_editor.js:529` guards `if (cmdBtn && focusCell)` while `filltable_editor.js:729` adds
`&& focusCell.hasAttribute("contenteditable")`, and their `input` listeners differ
(`:461-464` vs `:651-655`). One consequence worth recording: `filltable_editor.js:379-381`
disables every `[data-cmd]` button on answer/image cells, so the swatches inherit that
disabled state for free in filltable and **do not** in table.

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

**Inside the surface, colour is represented as a class** (alignment is represented as
inline style) — note "inside": never on the contenteditable host itself, per the root rule
above. Alignment keeps inline
styles on the surface (`text_toolbar.js:48-74`) because its active state needs
`queryCommandState("justifyCenter")`. Colour has no such need, and inline colour on the
surface would show an author in dark mode the *light-theme* hex. Therefore:

- `classToStyle()` leaves `tc-*` untouched on load.
- **`input` is the only hook**, not `paste`. The `paste` event fires *before* the default
  insertion, so a handler on it sees the pre-paste DOM and normalises nothing; `input`
  fires afterwards with `inputType: "insertFromPaste"`. Both passes run from that single
  listener, and they are gated differently: `mapColours` runs on **every** `input` (it is a
  no-op when nothing carries inline colour), while `tidyPastedSpans` runs **only** when
  `inputType` is `insertFromPaste` or `insertFromDrop` — running it on ordinary typing
  would unwrap spans as the author works.
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
active swatch is indicated by a ring, not by colour alone — and it must **not** reuse
`.rte-btn.is-on`, which is already `background: var(--primary); color: var(--text-inverse)`
(`editor.css:230`) and would repaint the active swatch brand-teal, hiding the very colour it
represents. Use a distinct `.rte-swatch` class whose `.is-on` state is a `box-shadow` ring.
Specificity is a tie, so declaration order decides: `.rte-btn.is-on` and `.rte-swatch.is-on`
are both (0,2,0), so `.rte-swatch.is-on` **must be declared after `editor.css:230`** — or the
swatch must not carry `rte-btn` at all and `.rte-swatch` restates the sizing it needs. Pick
one and pin it with a test asserting the active swatch's computed background is not
`--primary`. The frontend-design pass judges the
active state in a screenshot, since a test asserting "the class is present" would pass
either way. The "no colour" control is a
bordered square with a CSS diagonal — no new sprite entry.

**There are four RTE toolbar markup sites, not one**, and the primary authoring surface is
among the three that are easy to miss: `_rte_toolbar.html` is the shared partial used by the
question/gate editors, but `_edit_text.html`, `_edit_callout.html` and `_edit_spoiler.html`
each carry a **fully duplicated inline toolbar** with a different control set (three align
buttons, no `∑`). `TextElement.body` alone holds **390 of the 588** palette-coloured
elements (66%), so a change that touched only the shared partial would ship the feature with
no swatches on the surface that needs it most.

The swatch group is therefore extracted into its own partial, `_rte_swatches.html`, included
by all four — which extends the "byte-identical" discipline to the markup instead of relying
on four hand-copies staying in step. It is **inserted after the bold/italic/underline group,
before the first `.rte-sep`** (not appended — the end of the toolbar is where `∑` sits).

Plus the two table toolbars: `_edit_table.html` (near 41-43) and `_edit_filltable.html`
(near 50-52). In the table editors the group rides the existing toolbar `mousedown`
preventDefault that preserves `focusCell` (`table_editor.js:523`), and `mapColours()` must
run on the cell **before** `innerHTML` is harvested into the JSON payload
(`table_editor.js:174`) or the colour is dropped at save.

**Both passes are wired in the table editors too, and "the editor" in D9 means all three.**
`table_editor.js` has one `input` listener (`:461`) and no paste handler, so without this a
paste into a cell would store nested `<span class="">` plus duplicated MathML/glyph prose
(`span` is newly in `CELL_TAGS`), and a paste of inline-coloured HTML would silently lose
its colour. Wire both from that existing `grid` `input` listener, scoped to
`e.target.closest("[contenteditable]")` — the cell actually edited — with `tidyPastedSpans`
gated on `inputType` as in the RTE. `mapColours` additionally runs over **every** cell
inside `serialize()`, because a paste can land in a cell that is never focused again.

The colour branch in **both**
table editors must set `styleWithCSS(true)` before `foreColor` and reset it to `false`
afterwards — those files currently force it `false` for bold/italic/underline
(`table_editor.js:534-537`), and the reset discipline documented in the RTE section applies
identically here.

### KaTeX normalisation

**The obvious hook is the wrong one.** `window.libliRenderMath` is `renderMath`
(`math.js:12-19,42`), which visits only `[data-katex]` **display** elements. The inline
`\(…\)` prose maths this feature exists for is rendered by `window.renderMathInElement`,
called from ~20 sites across `math.js` (`renderInlineText`, itself not exported),
`question.js`, `quiz.js`, `choicegrid.js`, `dnd.js`, `filltable.js`, `switchgate.js`,
`switchgrid.js`, `editor.js` and `math_input.js`.

**Mechanism:** wrap `window.renderMathInElement` once, at load, in `text_colour.js`; the
wrapper calls through and then runs `mapColours(scope, {dropUnmapped: false})`. Every
existing and future call site is covered without editing any. This works *only* because
`math.js:30-33` resolves `window.renderMathInElement` at **call** time, not at load time.

**The display path needs a different hook — `window.libliRenderMath` cannot work.**
`math.js` assigns `window.libliRenderMath = renderMath` during its own evaluation (line 42),
so at the required insertion point the symbol does not yet exist, and the assignment would
clobber any earlier wrapper. Worse, line 43 calls the **local** `renderMath(document)` for
the initial pass, which no `window` wrapper can ever intercept — the dominant case. Wrap
**`window.katex.render`** instead: `renderOne` resolves bare `katex.render(...)` at call
time (`math.js:6`), and `katex.min.js` defines it before the insertion point, so the initial
display pass *is* covered. The wrapper runs `mapColours` on the element KaTeX just rendered
into.

**Load order is the failure mode, and it is not about captured references.** All scripts
are `defer`, so they execute in document order, and `math.js` calls `renderMath(document)`
and `renderInlineText(document)` **at module evaluation**. A `text_colour.js` placed after
`math.js` therefore misses the entire initial page render — the dominant case. The wrapper
also cannot be installed before `auto-render.min.js` defines `window.renderMathInElement`.

**Insertion point: immediately after `auto-render.min.js`, and before *any* script that
calls `renderMathInElement`** — which is `math.js` on three pages and `question.js` on the
other two. Stating it as "before `math.js`" would leave the two results pages unprotected,
since they never load `math.js` at all:

| template | note |
|---|---|
| `courses/lesson_unit.html` | lines 61-63 are katex → auto-render → math.js |
| `courses/quiz_unit.html` | |
| `courses/manage/editor/editor.html` | |
| `courses/quiz_results.html` | loads katex + auto-render but **not** `math.js`; the anchor is `question.js` (`:65`), which resolves `renderMathInElement` as a bare global and runs its own initial pass. Renders `el.explanation`. |
| `courses/manage/review_submission.html` | same shape as quiz_results |

Gating differs by template: the four student/results pages wrap the scripts in
`{% if has_math %}`, but `editor.html:135-137` loads KaTeX **unconditionally** and must
continue to — `window.libliColour` has to exist for the toolbars even in a unit with no
maths, so on the editor page `text_colour.js` is ungated.

Defensive requirement: if `window.renderMathInElement` (or `window.katex`) is undefined at
wrap time, install a lazy accessor rather than silently no-op.

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

The key is produced by **unwrapping every `<span>`** — removing the element and keeping its
children — *not* by dropping the `style` attribute, and *not* only for colour-bearing spans.

Two distinct reasons, both measured:

- Attribute-dropping would yield `<span>założenie</span>`, which can never equal what the
  pre-change loader stored (`założenie`), because `span` is allowed after slice 1.
- The pre-change sanitiser unwrapped **all** spans, not just coloured ones, and the corpus
  is full of others: of **1197** spans, only 697 carry colour — the rest are 299
  `<span class="myequation">`, 129 bare `<span>`, 96 `<span style="display:inline-block…">`
  and similar. **10 of the 301 colour-bearing field occurrences (3%) also carry a
  non-colour span.** A key that unwraps only colour spans replays to `<span class="">…`
  while the DB holds the fully-unwrapped value — a silent zero-match with no diagnostic,
  the exact failure class the acceptance gate detects but cannot attribute.

**The value the colouriser writes must unwrap them too.** Non-palette and non-colour spans
must not survive into the DB: once `span` is allowed, nh3 no longer removes them, so
writing them back would ship `<span class="">` litter into content that is currently clean.

**The colouriser is not span-only** — this is where a naive implementation delivers nothing
for a fifth of the corpus. 142 of the 588 palette-coloured elements (24%) sit on a tag other
than `span`, and 61 of the 288 palette-bearing field occurrences (21%) include such a
carrier. The value rule is per carrier class:

| carrier | count | value rule |
|---|---|---|
| `span` | 446 | replace `style="color:…"` with `class="tc-*"` |
| in `TC_CLASS_TAGS` — `strong` 117, `u` 6, `i` 2 | 125 | put `class="tc-*"` on **the element itself**; drop the inline colour |
| outside `TC_CLASS_TAGS` — `p` 7, `li` 6, `figcaption` 4 | 17 | wrap the element's **children** in a `tc-*` span; drop the inline colour. `p`/`li` cannot carry `tc-*`, and `figcaption` is not in `ALLOWED_TAGS` at all |

This mirrors the editor's "never leave `tc-*` on a tag outside `TC_CLASS_TAGS`" rule — the
backfill needs it too. A span-only colouriser leaves `<strong style="color:red">` untouched,
the sanitiser strips `style`, and the written value is **byte-identical to the key**: a
silent no-op the gate would score as success without the `value != key` precondition.

The generator then replays **the full import write path for that field, in order** (see the
three-sanitiser table) — for gate stems `sanitize_stem_segments`; for
`FillBlankQuestionElement.stem` the composition `sanitize_html(sanitize_stem_segments(x))`,
because `save()` re-sanitises after the builder. Applying a single sanitiser where the real
path composes two produces keys that match nothing, and it fails silently.

**The colouriser must apply D8/D10's region test to the source value, too.** The editor is
forbidden from producing a colour span that intersects a maths region or a `{{…}}` marker,
but the backfill writes colour into exactly the marker- and sentinel-token-bearing stems
(`FillGateElement.stem`, `SwitchGateElement.stem`, `GuessNumberElement.stem`,
`FillBlankQuestionElement.stem`). If a source span straddles or sits inside such a region,
the backfill would store precisely the corruption D10 exists to prevent, and the next form
edit would surface it. So: run the same intersection test over each source value, and
**refuse and report** any occurrence that intersects a maths or marker region. The corpus
measurement behind D8 (0 contaminated maths spans) covers only maths — the equivalent
marker measurement must be taken during implementation and reported beside it.

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

- **≥ 70%** of *eligible occurrences* match, **and**
- **no eligible part that produces at least one key matches zero.**

**Both sides are defined as computable expressions, because three different corpus counts
appear in this spec and 70% of each gives a different verdict.** Neither 588 (spans) nor 446
(emitted classes) nor 306 (occurrences of stripped forms) nor 257 (distinct forms) is the
right number, so the gate does not cite any of them:

- **denominator** = the number of source-side `(json_file, field_path)` occurrences that
  produce a key after source-side exclusion;
- **numerator** = the subset of those whose key matched at least one DB field **and whose
  coloured value differs from the key** (`value != key`).

The `value != key` precondition is load-bearing: without it the non-span-carrier failure
mode scores as a success. A span-only colouriser yields `value == key` for every non-span
carrier, the key still matches, and the run reports ~100% while delivering zero colour for
21% of occurrences — and the read-back byte-identity check passes trivially too. The dry run
also emits a **`tc-*` classes emitted** count, expected value derived from the source scan,
and reports *matched-but-unchanged* as its own named skip reason.

Both are emitted by the dry run itself and re-derived from the code, not quoted from this
spec. (Per-cell counting belongs to the rewrite contract below, not to the gate.) The two
parts holding zero colour spans
(`150_f_wykladnicza`, `120_wartosc_bezwzgledna`) contribute to neither numerator nor
denominator; without that exclusion the second condition would halt every run by
construction.

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
   The converse is not guaranteed: author-written content that happens to be byte-identical
   to a key (a short stem such as "założenie" typed by hand in a new unit) **will** be
   recoloured, because matching is content-based by design (D6). The dry-run report is where
   an operator spots it.
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
queryset (mirroring `richtext.py:261`) and `.exclude(elements__unit_id__in=subtree)`, where
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

**Unit — key construction.** For one field of each shape, assert the generated key equals the
value the loader actually stored. Measured, the only coloured stems in the corpus are
`fill_gate/stem` (2), `choice/stem` (2) and `switch_grid/stem` (2), so use
**`FillGateElement.stem`** as the real `sanitize_stem_segments` fixture and
**`ChoiceQuestionElement.stem`** as the real bare-`sanitize_html` one. The composed-path case
(`FillBlankQuestionElement.stem`) has **zero** corpus occurrences and uses a synthesised
fixture — the composition is real even though the imported data is not. This is the test that
would have caught the composed-path defect.

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
`\(x+y\)` **on the cell path** and shows the translated message; D8 refuses a selection
enclosing `\(x + <b>y</b>\)` (element boundary inside the region); D10 refuses colouring
inside `{{a|b}}` in a fill-blank stem, and the stored accepted answers are unchanged;
**D8 ALLOWS a selection strictly enclosing `\(x+y\)` with no interior tags** — it stores
`<span class="tc-red">\(x+y\)</span>` and the maths still renders after reload, with a
cell-path variant since `sanitize_cell` stashes the region before `nh3.clean`; both themes screenshotted
and judged separately.

**e2e — D4 on the student side.** `\color{red}` and a prose `tc-red` resolve to the same
computed colour — asserted as **equal to the `--tc-red` token value**, not merely "a colour
is present" — pinned to `lesson_unit.html` (where the load-order constraint is real), plus a
second instance on `quiz_results.html`, which loads auto-render **without** `math.js`. A
third case covers **display** maths (`[data-katex]`) on the initial page render, which is
the path the `window.katex.render` wrapper exists for.

**Transfer round-trip.** Export a course carrying `tc-*` in a body **and** a table cell,
import into a fresh course, assert byte-identity of both fields. This is the load-bearing
claim for how the work reaches production (D5).

**Backfill — carriers.** A `<strong style="color:red">` occurrence is rewritten to
`<strong class="tc-red">`, not left byte-identical to its key; a `<p style="color:red">`
occurrence has its children wrapped in a `tc-red` span; a `<figcaption>` carrier degrades
without error. Each asserts `value != key`.

**Backfill.** Rewrites an untouched element; skips an edited one; leaves every node title
unchanged; honours the `<dirname>=<pk>` exclusions; rejects a dirname absent from `out/` and a pk
belonging to another course; **accepts `<dirname>=` and emits the source-side-only report
line**; rewrites a partially-matching
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
   colour", and the one D8/D10 refusal message emitted as `data-msg-colour-region`; run `makemessages -l pl -l en --no-obsolete` so
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
3. **Whether the two wrappers together cover every render, and how much they overlap.**
   `auto-render.min.js` resolves `katex` as a property of the same `window.katex` object, so
   wrapping `window.katex.render` probably also fires once per inline span — on a *detached*
   node, before it is appended. `mapColours` is safe on a detached root (it reads only
   inline `style.color`), but the cost is N+1 passes per scope. Measure the overlap on the
   largest mat-pp unit and add a re-entrancy guard if it is material.
4. **Whether the swatch group fits** the two table toolbars at 360px.

## Appendix — measured corpus data

Colour-bearing **elements** in `scripts/lal_import/out/**.json`, 697 total across 106
files (carriers: `span` 510, `strong` 161, `p` 8, `li` 6, `u` 6, `figcaption` 4, `i` 2):

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

**An earlier draft explained the 588→446 gap as field scope. That was wrong, and measuring
it is what surfaced the non-span carrier problem.** Palette colour exists under exactly three
JSON keys — `body` 390, `html` 192, `stem` 6 — and **zero** under `desc`, `options`, `latex`
or any other key the prototype did not walk. The real decomposition:

| | palette elements |
|---|---|
| on a `span` — what the prototype emitted | **446** = `body`-span 268 + `stem`-span 6 (→ 274 via `sanitize_html`) + `html`-span 172 (via `sanitize_cell`) |
| on a non-span carrier — silently dropped by the prototype | **142** (`strong` 117, `p` 7, `li` 6, `u` 6, `figcaption` 4, `i` 2) |
| total | **588** |

So 446 is exactly the palette-coloured **span** count, and the gap is the carriers the
prototype ignored — which the colouriser's per-carrier value rule now handles. Correcting
the related claim: the out-of-scope `sanitize_cell` fields (`options`, `desc`, cycler
options) carry **zero** palette colour, not "roughly 100"; the only out-of-scope palette
colour anywhere is the 2 occurrences in `SwitchGridElement.lines[*].stem`. The DB-side
acceptance gate is what turns any of these figures into a real prediction.
