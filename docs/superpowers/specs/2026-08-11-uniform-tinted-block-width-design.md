# Uniform width for background-bearing blocks on the student unit page

## Purpose

On a student unit page with the course tree (TOC) collapsed, two callouts render at two different
widths. A callout holding only text is capped at 46rem (736px); a callout that has child elements
runs the full column (872px — see Derived geometry). A student reading two worked examples sees one
box 136px wider than the other, with no meaning attached to the difference. The user's report:

> when callouts have child elements they are wider than when they have only text. This is confusing.
> Students see two examples, one wider, the other narrower.

The same split already affects question cards. `.el--question` carries a card background
(`courses.css:295-301`, `background: var(--surface-raised)`), and the five grid-ish question types
(`choicegrid`, `multigrid`, `dragimage`, `matchpair`, `dragfill`) are excluded from the cap while
plain question types are not — so a quiz already shows two card widths for the same reason.

The goal is the user's stated rule: **every element-root block that paints a background different
from the page background renders at one width.**

### Non-goals

- Changing anything in the TOC-**expanded** state. See Derived geometry: the expanded column is
  648px, *below* the 736px cap, so no cap can bind there and widths are already uniform. Pinned by
  test 6 — which for that reason must assert computed style, not width.
- Changing the teacher review page or the quiz results page.
- Restructuring how the cap is applied. Two alternatives were considered and **explicitly rejected by
  the user**: (a) moving to an inner prose wrapper so element roots default to full width, and
  (b) leaving the allow-list intact and adding later `max-width: none` override rules. Neither is to
  be reintroduced during implementation.
- Narrowing anything tinted. An earlier option to cap *all* tinted blocks at 46rem was considered and
  rejected, because it would squeeze a table nested inside a callout — the exact regression the
  current exclusion exists to prevent.
- **Slideshow/deck mode.** A unit with ≥1 slide-break paginates (`_lesson_article.html:4`,
  `_quiz_article.html:3`) and `.slideshow-deck .slide` becomes an absolutely-positioned, separately
  padded, fixed-height scroller (`courses.css:382-390`). Per **S2** the invariant holds per containing
  block, and in deck mode that block is the slide's padding box, not the column. Out of scope; no
  measurement required.

## Current behaviour (verified against the worktree, not recalled)

Three rules interact. Line numbers are against `courses/static/courses/css/courses.css` at
`d197a4c7` unless stated.

1. `:291-292` — `.quiz, .lesson { max-width: 46rem; margin-inline: auto; }`. The standalone
   (non-shell) cap.
2. `:656-657` — `.unit-shell__main > .lesson, .unit-shell__main > .quiz { max-width: none;
   margin-inline: 0; padding: 1.25rem 1.5rem; }`. **Unconditional.** Inside the unit shell the
   article is never capped, in either TOC state.
3. `:1063-1086` — the "Prose cap" rationale comment (`:1063-1069`) and the rule block (`:1070-1086`),
   inside `@media screen and (min-width: 641px)`, every selector scoped
   `html.unit-tree-collapsed [data-unit-shell]`. Thirteen entries, each `max-width: 46rem`.

Capped elements are **left-aligned**, not centred — the block's comment notes the global
`* { margin: 0 }` leaves no auto margins to centre with. So a capped element short of the column
falls short **on the right only**.

The block's comment states the design intent: it is an **allow-list, not cap-by-default**, because
"a missed opt-out BREAKS layout (a squeezed table) whereas a missed allow-list entry only leaves
prose wide."

### Derived geometry

**The binding constraint is `.app-main`, not `.unit-shell`.** `base.html` puts `{% block content %}`
inside `<main class="app-main">`, and `core/static/core/css/app.css:34` is
`.app-main { max-width: 960px; margin: 0 auto; padding: var(--space-8) var(--space-5); }` with
`--space-5: 20px` (`tokens.css:76`). So the available width is **960 − 40 = 920px**, and
`.unit-shell`'s `max-width: 72rem` (`:654`, quoted as written — there is no `min()` in the
stylesheet) is **inert**: 72rem = 1152px never binds.

| State | Chain | Column |
|---|---|---|
| **Collapsed** | 920 available; `:1051` shifts the shell `-2.4rem` and the pin lane consumes `2.4rem`, so `.unit-shell__main` = 920; `.lesson` padding `3rem` | **872px** |
| **Expanded** | 920 − `.unit-tree` 14rem (224) = 696; `.lesson` padding `3rem` | **648px** |

Both are confirmed in-repo: `tests/test_e2e_unit_nav.py:1311` ("that stays 872px either way"),
`:1385` ("the EXPANDED quiz column at 1440 is 648px"), `tests/test_e2e_table_cell_images.py:27`
("a 648px content [column]"), and `docs/superpowers/plans/2026-08-04-image-size-presets.md:19-28`,
which records this same correction against a previous spec that had omitted `.app-main`.

**Because `.app-main` caps at 960px, 1280 and 1440 viewports produce identical geometry** (872
collapsed, 648 expanded).

**Which numbers may be asserted.** 46rem = **736px** is a *design token* — the single value this
feature caps at; existing tests already assert it (`test_e2e_unit_nav.py:1380`,
`test_e2e_callout_container.py:148`) and new tests may. The **derived** figures (920 / 872 / 648, and
any card/callout inner width) are computed from four or more separate rules and shift when any moves;
**no test may assert those as constants.** Where a test needs the column, it must read it (see
"Reading the column width") or compare two elements.

### Reading the column width (one recipe, used verbatim by tests 3, 4, 6)

`getBoundingClientRect()` returns the **border** box, and the article carries
`padding: 1.25rem 1.5rem`, so reading the article's box gives 920, not the 872 its children see. The
article is `.lesson` on a lesson page but `<article class="quiz">` on a quiz page
(`_quiz_article.html:2`), so the selector must cover both:

```js
() => { const a = document.querySelector('.quiz, .lesson'); const s = getComputedStyle(a);
        return a.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight); }
```

## The rule this change installs

> **In the TOC-collapsed state, tinted element-root blocks fill the column; prose caps at 46rem
> wherever it lives — including inside a tinted block.**

This replaces the rationale comment at `:1063-1069`; the comment rewrite is part of this change, not
incidental to it. The value is as much that a future author can apply one sentence as that two boxes
line up: the present list cannot be extended correctly without guessing, which is how the callout and
question splits arose.

### Two scope limits, both deliberate

**S1 — the rule governs element *roots*, not sub-element tints.** A student perceives "an example",
"a question", "a note" as boxes; the rule makes those agree. Decoration *inside* such a box —
`.question__feedback-panel` (`:165-190`, four tint variants), the `.markdone` row hover tint
(`:2053-2054`), `.unit-done__pill` (`:833-836`) — is internal to its container and tracks whatever
prose container holds it. **Out of scope**; an implementer must not widen these to "fix" them.
Consequence to accept knowingly: a feedback panel renders at ≤736px inside an 872px question card.

**S2 — the invariant holds *per containing block*.** `courses/builder.py` registers Callout, Spoiler,
TwoColumn, BeforeAfter and Tabs as containers, and questions are nestable inside them (PR #240).
`.quiz .el--question` is a *descendant* selector, so a question card nested inside a callout is tinted
too, but its available width is the callout's content box, not the column. Today both nested and
top-level cards are capped at 736 and so happen to be equal; after this change they diverge. This is
**accepted**: a nested box cannot exceed its parent, and a rule promising otherwise would be
unimplementable. Nested tinted blocks are uniform *with their siblings in the same containing block*,
which is what a reader actually compares. Deck-mode slides (see Non-goals) are the same case.

## Architecture

One CSS region changes: `courses.css:1063-1086` (rationale comment + rule block). Five selectors out,
four in. No template changes, no JavaScript, no Python.

### Out — tinted element roots, which now fill the column

| Entry | Why it is tinted |
|---|---|
| `.callout:not(:has(> .callout__children))` | `:1834-1839`, `background: color-mix(in srgb, var(--callout-accent) 6%, var(--surface-raised))` |
| `.el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill)` | `:295-301`, `background: var(--surface-raised)` |
| `[data-quiz-preview-notice]` | `_quiz_article.html:20` renders it `class="alert alert--info"`; `app.css:216`, `background: var(--primary-subtle)` |

Each entry is removed **in full, including its `:not()` chain**.

### Out — chrome that frames the cards

| Entry | Why it moves |
|---|---|
| `.quiz-finish` | `:322` is a `border-top: 1px solid` separator drawn *under the question cards*. Because capped elements are left-aligned, leaving it capped ends the rule **136px short of the cards' right edge** — a visibly broken separator. |
| `.lesson-unit__head` | `:824`, the flex row holding the title, the `.unit-done` pill and — when `has_stateful_elements` — `.lesson-unit__reset` (`_lesson_article.html:29`). Left capped, the right-aligned pill sits 136px left of the card edges below it. |

Both are transparent, so neither is tinted — they move for **alignment**: chrome that frames the
cards must share the cards' edges.

**Accepted side effect (I6):** `.lesson-unit__head .lesson-unit__title { flex: 1; min-width: 0 }`
(`:829-830`), so widening the head raises the title's flex target from ~610px to ~746px, where its
own 736px cap clamps it. The lesson title's measure therefore **grows by ~126px and a long title
re-wraps**. This is accepted because the new measure is exactly the 736px prose token — the value the
whole design treats as readable — but it is a visible change and must appear in the screenshot
checklist.

This chrome decision is a judgement call slightly beyond the literal request ("blocks with a
background"), taken because leaving it out ships a visibly misaligned separator as a direct
consequence of the change. **Call it out in the PR body** so the user can reverse it cheaply.

`.unit-crumbs` stays capped despite also being chrome: breadcrumbs are left-aligned text with no
right-edge affordance, so the alignment argument does not reach them.

### In — prose and answer controls inside a tinted block

| Entry | Covers |
|---|---|
| `.el--question:not(.el--dragfill) .question__stem` | the question prose (see R1 for the `:not()`) |
| `.question__choices` | the options list (`choicequestion.html:12`) |
| `.question__feedback` | per-question feedback prose |
| `textarea.question__text-input` | the extended-response answer box |

Without these a question card would widen *and* stretch its contents to 872px, contradicting the rule
for callouts and worsening the readability the cap protects.

`textarea.question__text-input` is a separate entry because the textarea is **not** a descendant of
any other capped selector: `extendedresponsequestionelement.html:7-9` makes it a direct child of
`.question__form`, a sibling of the stem. `:317-318` caps only `input.question__text-input` (22rem)
and its comment says the textarea "keeps app.css's `width:100%` and fills the card column" — which
after this change is ~830px, a ~105-character answer box. **Accepted consequence:** the same comment
records the textarea as "resizable up to" the card column, so a student can no longer drag it past
736px. That is consistent with the cap's purpose (protecting line length), not a regression.

The submit `<button>` needs no entry (a button does not stretch to its container).

`.callout__body` needs **no** entry: `calloutelement.html:7` renders it as
`<div class="el el--text callout__body">`, and `.el--text` remains on the list. Adding a
`.callout__body` selector would be a no-op — `courses/tests/test_callout_nesting_css.py:25` already
records this in a comment.

### Completeness obligation

`.el--question` has only two children in every template (`.question__stem` and `.question__form`, or
a no-form `{% else %}` branch), so auditing *children* proves nothing. The implementation must
enumerate **every descendant of `.el--question` that establishes its own block box, walking through
`.question__form`** — the bare `<fieldset>` wrappers (`choicegrid:7`, `multigrid`, `matchpair:33`,
`dragfill:6`), `.question__choices`, `.question__feedback`, `.scroll-x` / `.dragimage__stage`, and
both `input`/`textarea.question__text-input` — and show each is either capped or deliberately wide.
`.question__form` is an **intentional pass-through**: it neither caps nor constrains.

The denominator is **ten** templates, all under `templates/courses/elements/`:
`choicegridquestionelement`, `choicequestion`, `dragfillblankquestionelement`,
`dragtoimagequestionelement`, `extendedresponsequestionelement`, `fillblankquestionelement`,
`matchpairquestionelement`, `multigridquestionelement`, `shortnumericquestionelement`,
`shorttextquestionelement`. Record the enumeration in the plan.

### Entries that stay

`.el--text`; `.lesson-unit__title`; `.unit-crumbs` (`:849`); and the five gate wrappers `.markdone`,
`.fillgate` (`app.css:1031`), `.stepper`, `.switchgate` (`app.css:1103`), `.guessnumber`
(`app.css:1558`). Each gate wrapper either **declares margin only or has no root rule at all** —
there is no `.markdone { … }` or `.stepper { … }` rule in either stylesheet. The conclusion holds
(none paints a background at the root); the reason differs per selector. Per **S1** the `.markdone`
row hover tint at `:2053-2054` is a sub-element tint and stays with its container.

### Entry count

13 before, 5 removed, 4 added → **12 after**. `tests/test_consumption_css.py:212` asserts
`examined >= 17` (4 structural + one per allow-list entry); the correct value becomes **4 + 12 = 16**,
so it **must be re-derived to `>= 16`**. Its comment already anticipates this ("re-derive this number
only on a removal"). If R1's measurement changes the selector shape, re-derive again.

## Data flow

No runtime data flow; the flow is the cascade resolving a used width:

1. Is `html.unit-tree-collapsed` set? Set pre-paint by `base.html` from a global localStorage key.
   **Unchanged.**
2. Viewport ≥641px and medium `screen`? **Unchanged.**
3. Inside `[data-unit-shell]`? This scoping keeps the rule off the teacher review page, which reuses
   `.unit-shell` but is not the student shell. **Unchanged.**
4. Does the element match an allow-list selector? **The only step this change touches.** After:
   tinted element roots and card chrome do not match (fill the column); prose and answer controls do
   (736px), including prose nested inside a tinted block.

Prose containers are matched by **descendant** selectors, so `.el--text` or `.question__stem` nested
at any depth still caps — which makes "prose caps wherever it lives" true without per-container
entries.

## Error handling

CSS has no error path; the failure modes are silent mis-rendering.

### R1 — fieldset stems: two shapes need measurement

Widget placement relative to `.question__stem`, across all ten templates:

| Type | Wide widget | Position | Capping the stem |
|---|---|---|---|
| choicequestion | none (`.question__choices` is capped) | stem is a `<div>` (`:3`), sibling of `.question__form` | safe |
| choicegrid | `.scroll-x` (`:9,24`) | inside a bare `<fieldset>` (`:7`) inside `.question__form` — a **nephew** of the stem, not a sibling | safe |
| multigrid | `.scroll-x` (`:9,24`) | same nephew shape | safe |
| dragimage | `.dragimage__stage` (`:8,31`) | sibling of stem (`:3`) | safe |
| matchpair | pair widget | sibling of stem (`:3`) | safe |
| shorttext / shortnumeric / extendedresponse | none | — | safe |
| **fillblank** | inline `<input>`s in prose | `<fieldset class="question__stem">` (`:17`) | **must be measured** |
| **dragfill** | **`.dnd__pool`** | inside the stem — `:13` (fieldset branch), `:22` (no-form branch) | **must be measured** |

**Both fieldset stems are in scope.** Today the *card* is capped and the stem never has to shrink
itself; after this change the stem receives the cap directly for the first time. A `<fieldset>`
defaults to `min-inline-size: min-content`, which can refuse a `max-width` when a child has a large
min-content contribution — the trap recorded in `fieldset-min-inline-size-defeats-scroll`. Drag-fill
has `.dnd__pool` inside; fill-blank can have display math or a long unbreakable token. Neither inline
`style` sets `min-inline-size` (`fillblank:18`, `dragfill:7` set border/padding/margin only).

Two failure modes, **each with a different remedy** — which is why this is measured, not guessed:

| Branch | Symptom | Remedy |
|---|---|---|
| **B1** — widget squeezed | stem caps at 736, but the widget overflows horizontally | keep `:not(.el--dragfill)` (and add `:not(.el--fillblank)` if it applies) |
| **B2** — cap does not bind | the `min-inline-size: min-content` floor wins; stem stays 872 | add `min-inline-size: 0` to the stem, then re-measure |
| **B0** — neither | stem caps at 736, widget reflows without overflow | drop the `:not()`; no change needed |

B2's remedy is **not** a `:not()` exclusion — if the cap already fails to bind, excluding the element
from it changes nothing.

**Correct carve-out selector.** If a type must be excluded, the working form is
`html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--dragfill) .question__stem`.
`.el--dragfill` sits on the element **root** (`dragfillblankquestionelement.html:2`), never on the
stem, so `.question__stem:not(.el--dragfill)` would match **every** stem including drag-fill's — a
silent no-op that would look like the risk had been addressed. The spec's default is to ship the
`:not(.el--dragfill)` form and remove it only if B0 is measured.

**Mechanical definition of harm** (so two implementers reach the same verdict). At 1280×900
collapsed, on seeded drag-fill **and** fill-blank questions, record and put in the plan:

- `.question__stem` `getBoundingClientRect().width`
- for drag-fill, `.dnd__pool` `scrollWidth` and `clientWidth`, and the pool's rendered row count

**Harm** is exactly: (a) stem width > 738 → **B2**; or (b) `scrollWidth > clientWidth` → **B1**.
Row-count growth alone is **not** harm.

### R2 — the change is invisible in the expanded state

Every selector edited lives under `html.unit-tree-collapsed`, so an implementation that lifted a rule
out of that block would change the expanded state.

**The existing guard does not cover this.** `tests/test_consumption_css.py:184-206` iterates selectors
and `continue`s on any lacking `html.unit-tree-collapsed` — a lifted rule is **skipped, not caught**.
Only the `examined >= 17` floor catches a lift, incidentally, via the count dropping; and being `>=`,
lifting one selector while adding two scoped ones still passes.

**Required:** a positive assertion that the cap block's prelude contains **exactly** the expected 12
selectors, each containing both `html.unit-tree-collapsed` and `[data-unit-shell]`.

**Locating the block.** `courses.css` has many `@media screen and (min-width: 641px)` blocks and many
rules containing `html.unit-tree-collapsed`, and the line numbers cited here shift the moment the
block is edited. The implementation must **add sentinel comments** `/* prose-cap:begin */` and
`/* prose-cap:end */` around the rule and extract between them. Naming the anchor in the source is
what makes the assertion reproducible rather than two implementers writing two fragile extractors.
Note the extractor must run on the **un-stripped** source to see the sentinels, or strip comments only
after slicing.

### R3 — a widened tinted box with short content

A text-only callout now paints tint across 872px while its body text stops at 736px, leaving **136px**
of empty tint on the right (right only — capped elements are left-aligned). **Accepted, not a
defect** — the user chose it explicitly over letting text fill the box. Recorded so a later reviewer
does not "fix" it.

## Testing

**Every new or changed assertion must be falsified against a named mutant**, and a CSS claim needs an
**A/B** — a measurement taken with the rule present proves nothing
(`css-confirmation-needs-an-ab-not-a-measurement`).

**Viewports.** Tests 1-8 run at **1280×900**, matching `test_e2e_callout_container.py` (whose
docstring explains why 641px is too narrow: the collapsed box there is ~555px, below the cap, so it
never binds). The existing `test_e2e_unit_nav.py` tests **stay at 1440×900** — not because the
geometry differs (it is identical; `.app-main` caps both at 960) but to keep the diff to the
assertions being changed. A shared width helper is therefore safe across both.

### Tests that must change

1. **`courses/tests/test_callout_nesting_css.py:22`**. Its first assertion — that
   `.callout:not(:has(> .callout__children))` **exists** — inverts: the extracted cap block must
   contain **no `.callout` selector in any form**. Its second assertion (`:30`) is
   `re.search(r"unit-tree-collapsed[^{]*\]\s+\.callout\s*,")`, which requires a **trailing comma** —
   a `.callout` re-added as the *last* selector in the prelude is followed by `{` and escapes it.
   Fold it into the inverted first assertion, or widen its terminator to `[,{]`. Rename the test.

2. **`tests/test_e2e_callout_container.py:147-150`**. Currently asserts a prose-only callout is 736px.
   Rewrite to assert the two callout widths are **equal AND both exceed 736px**. Equality alone passes
   when *both* are capped — the squeezed-table regression this test exists to prevent.

3. **`tests/test_e2e_unit_nav.py:1376-1398`**, `test_quiz_chrome_is_capped_across_both_page_states`.
   Four assertions go red: both loops assert `w <= 736 + 2`, and `.el--question`,
   `[data-quiz-preview-notice]` and `.quiz-finish` all leave the cap. Rewrite so
   `.lesson-unit__title` still asserts `<= 738` while the other three equal the column (via the
   Reading recipe). **Preserve the test's stated purpose** — proving those selectors exist at all, so
   their deletion cannot ship green. Keep the `locator(...).count()` assertions untouched.

4. **`tests/test_consumption_css.py`** changes in exactly three ways: the `>= 17` floor becomes
   `>= 16`; the positive 12-selector assertion of R2 is added; and the docstring at `:157-167` is
   re-derived — it currently says "the **thirteen** capped selectors" and "four of the **thirteen**
   entries", and after this change the count is twelve with three of those four behaviourally-covered
   entries leaving the cap. Nothing else in it may be weakened.

### Tests to add

5. **Card-width agreement (e2e):** on one seeded unit, a plain question card, a `choicegrid` card, a
   text-only callout and a container callout all have equal width; and on the quiz page,
   `[data-quiz-preview-notice]` equals the question-card width (needs the owner-not-enrolled load —
   see `test_quiz_chrome_is_capped_across_both_page_states`'s docstring). Compare pairwise, or against
   the Reading recipe — never a derived constant.

6. **Prose-inside-a-box (e2e):** `.callout__body` and `.question__stem` measure 736px inside their
   widened boxes. **Mandate `abs(width - 736) < 2`.** Do *not* use `prose_width < box_width - 100` as
   the primary assertion: at the real geometry the correct build gives 736 inside 872, only 36px of
   slack, so any future narrowing of `.app-main` or the padding flips it red on correct code. A
   difference form may be added as a supplementary check only. Do **not** assert merely "narrower than
   its own box" — `.callout` and `.el--question` both have padding, so a child is *always* narrower,
   cap or no cap, and the assertion cannot fail.

7. **Expanded state (e2e):** the expanded column is 648px, **below** the 736px cap, so a lifted rule
   changes no measured width and a width-based test would pass on its own mutant. Assert
   **computed style** instead: in the expanded state,
   `getComputedStyle(el).maxWidth === 'none'` for the callout and both question cards. That is what
   the mutant reddens.

8. **Grid-type stems narrow (e2e):** the five grid types are excluded from the cap today, so their
   stems fill the column; adding `.question__stem` narrows them to 736px. Intended under S1 + the
   user's "prose stays readable" choice, but a behaviour change to types the Purpose section does not
   mention, so pin it. Assert `abs(stem_width - 736) < 2` **and** `scroll_x_width > stem_width + 50`.
   Do not describe `.scroll-x` as a sibling (it is a nephew) and do not expect it to equal the column
   — it sits inside the card, so its width is the card's inner box. The fixture **must set a
   non-empty `stem`**: `choicegridquestionelement.html:3` is `{% if el.stem %}`, so a stemless fixture
   renders no `.question__stem` and the locator silently resolves elsewhere. Scope it
   `.el--choicegrid .question__stem`.

9. **Fieldset stems (e2e), per R1:** pin whichever branch measurement selects, for **both** drag-fill
   and fill-blank, and record the measured numbers in the plan.

### Falsification

Each test shown RED against a named mutant, **run**, not merely cited (`falsify-tests-not-run-them`):

| Test | Mutant |
|---|---|
| 1 | re-add `.callout:not(:has(> .callout__children))` |
| 2 | re-add the callout entry (boxes diverge); and separately cap *both* callouts, to prove the `> 736` half fails too |
| 3 | re-add `[data-quiz-preview-notice]` and `.quiz-finish` |
| 4 | remove one selector from the block (count assertion); unscope one selector (positive assertion) |
| 5 | re-add the `:not(.el--choicegrid)` exclusion |
| 6 | delete the `.question__stem` entry (prose stretches to fill) |
| 7 | write the new rule without the `html.unit-tree-collapsed` prefix |
| 8 | delete the `.question__stem` entry |
| 9 (B1) | remove the `:not()` carve-out — widget overflows |
| 9 (B2) | remove `min-inline-size: 0` — stem stays wide despite the cap |

Note the trap from this file's own history: an assertion pinned to a bare class name can be satisfied
by `lesson_unit.html`'s inline pre-hide `<style>`, which emits `.callout__children` as a literal in
the page `<head>`. Source-scan assertions must be pinned to the attribute form
(`'class="callout__children"'`), and CSS-block assertions must **extract the block before scanning**
(now via the R2 sentinels).

### Regression scope

- Non-e2e suite plus the e2e files touching callouts, questions, the unit shell, and consumption CSS.
- The teacher review page and quiz results page render none of these capped selectors inside
  `[data-unit-shell]`; confirm no e2e covering them changes.

### Visual verification

Screenshot the collapsed student unit page in **light and dark**, judged separately
(`verify-ui-with-screenshots`), showing a text-only callout, a container callout, a plain question
card and a grid question card together; a quiz page showing the `.quiz-finish` separator against the
card edges; and **a long lesson title**, to see the I6 re-wrap. Dark mode is what catches a tinted box
whose widened area reads as a different surface.

### Test-run mechanics

Start the test-DB container **before** any pytest run, or the suite looks hung for ~4m21s. Tooling is
behind `uv run` (`ruff`, `pytest`, `python` are not on PATH); e2e needs `-m e2e` or it silently
deselects (exit 5, which is **not** a pass); use `--verbosity=0`, never a second `-q`. Run narrowly
scoped; a whole-repo sweep is a branch gate, not a task step. Two other pipeline worktrees exist on
this machine — never run two pytest sessions at once, they contend for the same test database. A
worktree has no `.env`, so database settings must be passed explicitly.
