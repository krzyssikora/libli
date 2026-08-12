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
  648px, *below* the 736px cap, so no cap can bind there and widths are already uniform.
- Changing the teacher review page or the quiz results page.
- Restructuring how the cap is applied. Two alternatives were considered and **explicitly rejected by
  the user**: (a) moving to an inner prose wrapper so element roots default to full width, and
  (b) leaving the allow-list intact and adding later `max-width: none` override rules.
- Narrowing anything tinted. An earlier option to cap *all* tinted blocks at 46rem was rejected: it
  would squeeze a table nested inside a callout — the regression the current exclusion prevents.
- **Slideshow/deck mode.** A unit with ≥1 slide-break paginates and `.slideshow-deck .slide` becomes
  an absolutely-positioned, separately padded scroller (`courses.css:382-390`). Per **S2** the
  invariant holds per containing block, which in deck mode is the slide's padding box. Out of scope.

## Current behaviour (verified against the worktree, not recalled)

Three rules interact. Line numbers are against `courses/static/courses/css/courses.css` at
`d197a4c7` unless stated.

1. `:291-292` — `.quiz, .lesson { max-width: 46rem; margin-inline: auto; }`. The standalone cap.
2. `:656-657` — `.unit-shell__main > .lesson, .unit-shell__main > .quiz { max-width: none;
   margin-inline: 0; padding: 1.25rem 1.5rem; }`. **Unconditional.** Inside the unit shell the
   article is never capped, in either TOC state.
3. `:1062-1086` — the "Prose cap" rationale comment (`:1062-1069`) and the rule block (`:1070-1086`),
   inside `@media screen and (min-width: 641px)`, every selector scoped
   `html.unit-tree-collapsed [data-unit-shell]`. Thirteen entries, each `max-width: 46rem`.

Capped elements are **left-aligned**, not centred — the block's comment notes the global
`* { margin: 0 }` leaves no auto margins to centre with. A capped element short of the column falls
short **on the right only**.

The block's comment states the design intent: it is an **allow-list, not cap-by-default**, because
"a missed opt-out BREAKS layout (a squeezed table) whereas a missed allow-list entry only leaves
prose wide."

### Derived geometry

**The binding constraint is `.app-main`, not `.unit-shell`.** `base.html` puts `{% block content %}`
inside `<main class="app-main">`, and `core/static/core/css/app.css:34` is
`.app-main { max-width: 960px; margin: 0 auto; padding: var(--space-8) var(--space-5); }` with
`--space-5: 20px` (`tokens.css:76`). Available width is **960 − 40 = 920px**, and `.unit-shell`'s
`max-width: 72rem` (`:654`) is **inert**: 72rem = 1152px never binds.

| State | Chain | Column |
|---|---|---|
| **Collapsed** | 920 available; `:1051` shifts the shell `-2.4rem` and the pin lane consumes `2.4rem`, so `.unit-shell__main` = 920; `.lesson` padding `3rem` | **872px** |
| **Expanded** | 920 − `.unit-tree` 14rem (224) = 696; `.lesson` padding `3rem` | **648px** |

Both confirmed in-repo: `tests/test_e2e_unit_nav.py:1311` ("that stays 872px either way"), `:1385`
("the EXPANDED quiz column at 1440 is 648px"), `tests/test_e2e_table_cell_images.py:27`, and
`docs/superpowers/plans/2026-08-04-image-size-presets.md:19-28`, which records this same correction
against a previous spec that had omitted `.app-main`.

**Because `.app-main` caps at 960px, 1280 and 1440 viewports produce identical geometry.**

**A card's inner box is not the column.** `.quiz .el--question` has `padding: var(--space-5)` and a
1px border (`:295-301`), so content inside measures ≈872 − 40 − 2 = **~830px**. `.callout`
(`:1834-1842`, `background` at `:1839`) has `padding: var(--space-4)`, a 1px border and a 3px
left border, so its body box is ≈872 − 32 − 4 = **~836px**.

**Which numbers may be asserted.** 46rem = **736px** and 22rem = **352px** are *design tokens* and may
be asserted; existing tests already assert 736 (`test_e2e_unit_nav.py:1379`, `:1398`,
`test_e2e_callout_container.py:148`). The **derived** figures (920 / 872 / 648 / ~830 / ~836) shift
whenever any of four-plus rules moves; **no test may assert those as constants.**

### Reading the column width (one recipe, used verbatim by tests 3 and 5)

`getBoundingClientRect()` returns the **border** box, and the article carries
`padding: 1.25rem 1.5rem`, so reading the article's box gives 920, not the 872 its children see. The
article is `.lesson` on a lesson page but `<article class="quiz">` on a quiz page
(`_quiz_article.html:2`), so the selector must cover both:

```js
() => { const a = document.querySelector('.quiz, .lesson'); const s = getComputedStyle(a);
        return a.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight); }
```

On a lesson page each element root is wrapped in
`<section class="lesson-block"><div class="lesson-block__body">` (`_lesson_article.html:38-39`);
a quiz uses a bare `<section data-element-id>`. Both templates additionally emit a third wrapper,
`<div class="slide">` (`_lesson_article.html:36`, `_quiz_article.html:27`), even for single-slide
units. **None of the three adds horizontal inset** — `.slide` is `display: contents`
(`courses.css:334`, becoming a bare `display: block` for a no-JS multi-slide unit at `:337`),
`.lesson-block__body` has no width rule, and the notes panel floats over the page margin rather than
insetting the block (`notes.css:90-101`) — so the recipe and pairwise comparisons are valid on both.
Note `.quiz-finish` and `[data-quiz-preview-notice]` sit *outside* `.slide`, while the cards sit
inside it.

## The rule this change installs

> **In the TOC-collapsed state, tinted element-root blocks fill the column; prose caps at 46rem
> wherever it lives — including inside a tinted block.**

This replaces the rationale comment at `:1062-1069`; the comment rewrite is part of this change.

### Two scope limits, both deliberate

**S1 — the rule governs element *roots*, not sub-element tints.** Decoration *inside* a box —
`.question__feedback-panel` (`:165-190`, four tint variants), the `.markdone` row hover tint
(`:2053-2054`), `.unit-done__pill` (`:833-836`) — is internal to its container and tracks whatever
prose container holds it. **Out of scope.** Consequence to accept knowingly: a feedback panel renders
at ≤736px inside an 872px question card.

**S2 — the invariant holds *per containing block*.** `courses/builder.py` registers Callout, Spoiler,
TwoColumn, BeforeAfter and Tabs as containers, and questions are nestable inside them (PR #240).
`.quiz .el--question` is a *descendant* selector, so a nested question card is tinted too, but its
width is the callout's content box, not the column. Today both nested and top-level cards are capped
at 736 and happen to be equal; after this change they diverge. **Accepted**: a nested box cannot
exceed its parent. Nested tinted blocks are uniform *with their siblings in the same containing
block*, which is what a reader compares.

## Architecture

**Two CSS regions change:**

1. `courses.css:1062-1086` — the rationale comment and the cap rule. Five selectors out, four in.
2. `courses.css:315-318` — the rationale comment above `.quiz/.lesson input.question__text-input`
   (the rule itself is at `:319-320`). Its text — "the extended-response `textarea` (same class)
   keeps app.css's width:100% and fills the card column, resizable up to it" — becomes **false** once
   the textarea is capped, and must be amended. The amended text must reference
   `app.css:150 textarea { resize: vertical }`, not "resizable up to it".

**One comment-only template edit** (below); no other template changes, no JavaScript, no Python.

3. `templates/courses/elements/calloutelement.html:11-20` — the `{% comment %}` justifying the
   `.callout__children` wrapper gives three reasons for its existence, the third being "the subject of
   the `:has(> .callout__children)` predicate the prose-cap narrowing keys on". This change deletes the
   only `:has(> .callout__children)` predicate in the codebase, so that reason becomes false and a later
   reader finding two surviving reasons could conclude the wrapper is removable. Strike the third
   reason, leaving `scopeOf` and the `.callout__body + .callout__children` anchor. This is a comment
   edit only — no markup changes.

### Out — tinted element roots, which now fill the column

| Entry | Why it is tinted |
|---|---|
| `.callout:not(:has(> .callout__children))` | `:1839`, `background: color-mix(in srgb, var(--callout-accent) 6%, var(--surface-raised))` |
| `.el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill)` | `:295-301`, `background: var(--surface-raised)` |
| `[data-quiz-preview-notice]` | `_quiz_article.html:20` renders it `class="alert alert--info"`; `app.css:216`, `background: var(--primary-subtle)` |

Each entry is removed **in full, including its `:not()` chain**.

### Out — chrome that frames the cards

| Entry | Why it moves |
|---|---|
| `.quiz-finish` | `:322-326` is a `border-top: 1px solid` separator (declaration at `:325`) drawn *under the question cards*. Because capped elements are left-aligned, leaving it capped ends the rule **136px short of the cards' right edge**. |
| `.lesson-unit__head` | `:824-825`, the flex row holding the title, the `.unit-done` pill and — when `has_stateful_elements` — `.lesson-unit__reset` (`_lesson_article.html:28-33`). Left capped, the right-aligned pill sits 136px left of the card edges below it. |

Both are transparent — they move for **alignment**: chrome that frames the cards must share their
edges.

**Accepted side effect — re-derived for the three-item head.** `.lesson-unit__head` is
`display: flex; justify-content: space-between; gap: 1rem` with **three** children whenever
`has_stateful_elements` is true. `courses/views.py:467-470` sets that flag for any *stateful* element,
which includes question elements — so any fixture seeding a question card renders the reset link too.
`tests/test_e2e_unit_head_layout.py` already exists to guard this three-item row.

With head = 872 and `.lesson-unit__title { flex: 1; min-width: 0 }` (`:830-831`), the title's target
is `872 − 2×16 gap − pill(~110) − reset(~90)` ≈ **650px**, up from ≈514px today — so it **grows by
~136px but never reaches its own 736px cap**. The 736 figure applies only to a *two-item* head, and
even then only when pill + gap fit within 136px, which is locale-dependent (the Polish "Oznacz jako
ukończone" pill is materially wider than the English one). Either way a long title re-wraps, which is
visible and must appear in the screenshot checklist. **No test may assert the title at 736** — see
test 5.

This chrome decision is a judgement call slightly beyond the literal request. **Call it out in the PR
body** so the user can reverse it cheaply.

`.unit-crumbs` stays capped despite also being chrome: breadcrumbs are left-aligned text with no
right-edge affordance, so the alignment argument does not reach them.

### In — prose and answer controls inside a tinted block

| Entry | Covers |
|---|---|
| `.el--question .question__stem` | the question prose (R1 measured B0 — no `:not()` chain) |
| `.question__choices` | the options list (`choicequestion.html:12`) |
| `.question__feedback` | per-question feedback prose |
| `textarea.question__text-input` | the extended-response answer box |

Without these a question card would widen *and* stretch its contents to ~830px, contradicting the
rule for callouts and worsening the readability the cap protects.

**Why the `textarea` type selector is mandatory, not stylistic.** The textarea is a **nephew** of the
stem — `extendedresponsequestionelement.html` has `.question__stem` at `:3` and
`<form class="question__form">` at `:5`, with the textarea a child of that form (`:7-9`) — so no other
capped selector reaches it. It must be written `textarea.question__text-input`. Compare the **tails**
(the shared `html.unit-tree-collapsed [data-unit-shell] ` prefix contributes equally to both
candidates and only obscures the count): `textarea.question__text-input` is 1 class + 1 type, while a
bare `.question__text-input` is 1 class + 0 types. Either way the full selector out-specifies
`.quiz input.question__text-input` = (0,2,1) at `:319-320` on its class component — so writing the
class bare, an easy slip since every other new entry is bare, would silently jump the short-text and
short-numeric boxes from **352px to 736px**. Test 9 pins the 352px input for this reason.

**Accepted consequence of capping the textarea:** the extended-response box renders at 736px instead
of the card's inner ~830px in the collapsed state. It has **never** been horizontally draggable —
`app.css:150` is `textarea { resize: vertical; }`, and its comment at `:145-149` records that the
browser default `resize: both` was overridden precisely so "a full-width textarea (e.g. the
extended-response answer box)" could not be dragged past its column. Growth stays vertical-only.

**Why `.question__choices` and `.question__feedback` are safe to cap.** Both are prose containers,
and the identical content risk already exists, accepted, on `.el--text`, which has been capped at
736px since the allow-list was written. `courses/sanitize.py` permits `pre` and `code` but not
`table` or `img`, and explanations may carry display math — all of which can exceed 736px and
overflow. That is **pre-existing prose behaviour**, not introduced here: the same `<pre>` in a text
element overflows identically today. Accepted without a new measurement. (Contrast the fieldset stems
in R1, where the discriminator is not the content but the `<fieldset>` `min-inline-size: min-content`
quirk.)

The submit `<button>` needs no entry (a button does not stretch to its container).

`.callout__body` needs **no** entry: `calloutelement.html:8` renders it as
`<div class="el el--text callout__body">`, and `.el--text` remains on the list.

### Completeness obligation

Auditing *children* of `.el--question` proves nothing: there are only one or two, and in the two
fieldset types (`fillblankquestionelement.html:14-30`, `dragfillblankquestionelement.html:3-20`) the
`{% if element %}` branch gives `.el--question` a **single** child, `.question__form`, with the stem
being the fieldset *inside* it.

**Stopping rule:** a descendant of an already-capped container needs no entry of its own. This is what
bounds the enumeration — `.question__feedback` is the **barrier** behind which
`_question_feedback.html` (`.question__verdict`, `.question__explanation`),
`_quiz_question_feedback.html` (`.question__feedback-panel`) and the ten `_reveal_*.html` partials
(`.question__reveal`, `courses.css:194`) all render. Those files are therefore out of the
denominator by rule, not by oversight.

Within that bound, enumerate **every descendant of `.el--question` that establishes its own block
box, walking through `.question__form`**, and show each is either capped or deliberately wide:

- **Bare (unclassed) `<fieldset>` wrappers**, which are pass-throughs: `choicegrid:7`, `multigrid:7`,
  `matchpair:7`, `dragimage:7`.
- **Class-bearing stems handled by R1**, *not* bare wrappers: `fillblank:17`, `dragfill:6` — both
  `<fieldset class="question__stem">`.
- `.question__choices`, `.question__feedback` (the barrier), `.scroll-x` / `.dragimage__stage`, and
  both `input`/`textarea.question__text-input`.
- **`.dnd__pool` in dragimage (`:23`) and matchpair (`:14`)** — deliberately wide. Unlike drag-fill's,
  these pools sit inside the *bare* fieldset, which is a declared pass-through, so the stopping rule
  does not excuse them: they widen from the old 736px card to the ~830px card inner box. Harmless
  because `courses.css:475` is `flex-wrap: wrap`, so widening changes only chip row count, never
  overflow.

`.question__form` is an **intentional pass-through**: it neither caps nor constrains.

The denominator is **ten** templates under `templates/courses/elements/`:
`choicegridquestionelement`, `choicequestion`, `dragfillblankquestionelement`,
`dragtoimagequestionelement`, `extendedresponsequestionelement`, `fillblankquestionelement`,
`matchpairquestionelement`, `multigridquestionelement`, `shortnumericquestionelement`,
`shorttextquestionelement`. Record the enumeration in the plan.

### Entries that stay

`.el--text`; `.lesson-unit__title`; `.unit-crumbs` (`:849`); and the five gate wrappers `.markdone`,
`.fillgate` (`app.css:1031`), `.stepper`, `.switchgate` (`app.css:1103`), `.guessnumber`
(`app.css:1558`). **No root rule in any state — base or `--done` — sets a background.** There is no
`.markdone { … }` or `.stepper { … }` rule at all; the base rules that exist declare margin only; and
the state modifiers `.fillgate--done` (`app.css:1095`), `.switchgate--done` (`:1204`) and
`.guessnumber.guessnumber--done` (`:1653`) declare only `padding-left` plus a success `border-left`.
Per **S1** the `.markdone` row hover tint at `:2053-2054` stays with its container.

### Entry count and the branch matrix

13 before, 5 removed, 4 added → **12 after**. The prelude between the sentinels is **12 selectors in
every R1 branch** — B0/B1 change only the `:not()` chain *inside* the stem entry, and B2's remedy is a
separate rule outside the sentinels (see R1). So:

| Quantity | Value (RESOLVED by measurement) |
|---|---|
| Expected prelude list (R2 assertion) | **12** |
| Stem entry | **`.el--question .question__stem`** (B0 — no `:not()`) |
| `examined` in `test_consumption_css.py` | **16** (no type resolved to B2) |

`test_consumption_css.py:212` currently asserts `examined >= 17`; it becomes **`>= 16`**. Because the
operator is `>=`, it cannot catch B2's extra selector — R2's assertions are what pin the shape.

Both fieldset types were measured independently; **both landed in B0**, so no carve-out and no
`min-inline-size` rule are built.

## Implementation ordering — RESOLVED

**R1 has been measured (see MEASURED OUTCOME): both types are B0.** The ordering constraint below is
therefore already discharged, and the selector list and counts are fixed. It is retained so a reader
understands why the numbers are what they are.

R1's measurement had to precede the tests because its outcome changes the strings they hard-code:

- **B0** → the stem entry becomes `.el--question .question__stem` (**not** bare `.question__stem` —
  dropping the `:not()` leaves the `.el--question` prefix in place; the two differ as strings and in
  specificity).
- **B1** → the stem entry keeps/gains `:not()` per affected type.
- **B2** → a separate scoped `min-inline-size: 0` rule is added outside the sentinels.

Sequence: **measure R1 → record verdict and numbers → fix the selector list and counts → write the
R2 assertions and the tests.** Steps 1 and 2 are **done**; the outcome is B0/B0.

## Data flow

No runtime data flow; the flow is the cascade resolving a used width:

1. Is `html.unit-tree-collapsed` set? Set pre-paint by `base.html`. **Unchanged.**
2. Viewport ≥641px and medium `screen`? **Unchanged.**
3. Inside `[data-unit-shell]`? Keeps the rule off the teacher review page. **Unchanged.**
4. Does the element match an allow-list selector? **The only step this change touches.**

## Error handling

### R1 — fieldset stems: two shapes need measurement

Widget placement relative to `.question__stem`, across all ten templates. In every `{% if element %}`
branch the widget sits inside a bare `<fieldset>` inside `<form class="question__form">`, making it a
**nephew-once-removed** of the stem, never a sibling; only `dragimage`'s `{% else %}` branch (`:31`)
is a true sibling.

| Type | Wide widget | Position | Capping the stem |
|---|---|---|---|
| choicequestion | none (`.question__choices` is capped) | stem is a `<div>` (`:3`) | safe |
| choicegrid | `.scroll-x` (`:9,24`) | nephew (inside `.question__form > fieldset`) | safe |
| multigrid | `.scroll-x` (`:9,24`) | nephew | safe |
| dragimage | `.dragimage__stage` (`:8`, and `:31` in the no-form branch) | nephew (sibling only at `:31`) | safe |
| matchpair | pair widget | nephew | safe |
| shorttext / shortnumeric / extendedresponse | none | — | safe |
| **fillblank** | inline `<input>`s from `{% render_fill_blanks %}`, rendered directly into the stem | `<fieldset class="question__stem">` (`:17`) | **must be measured** |
| **dragfill** | inline-block `<select>`s from `{% render_drag_selects %}`, plus `.dnd__pool` | `<fieldset class="question__stem">` (`:6`); pool at `:13` | **must be measured** |

**Both fieldset stems are in scope.** Today the *card* is capped and the stem never has to shrink
itself; after this change the stem receives the cap directly for the first time. A `<fieldset>`
defaults to `min-inline-size: min-content`, which can refuse a `max-width` when a child has a large
min-content contribution — the trap in `fieldset-min-inline-size-defeats-scroll`. Neither inline
`style` sets `min-inline-size` (`fillblank:18`, `dragfill:7` set border/padding/margin only).

#### The overflow subject is the STEM, for both types

Not `.dnd__pool`. Two independent reasons, both verified:

- **The pool ships hidden and empty.** `_dnd_pool.html` is
  `<div class="dnd__pool" data-dnd-pool hidden></div>`, and `courses.css:476` is
  `.dnd__pool[hidden] { display: none; }`. `dnd.js:70` (`pool.hidden = false`) reveals and fills it,
  behind three guards: `:43` `data-dndReady` idempotence, `:46` early return when the block has no
  `select[name="slot"]`, and `:48` early return when the pool element is absent.
- **The pool wraps.** `courses.css:475` is
  `.dnd__pool { display: flex; flex-wrap: wrap; gap: var(--space-2); … }`. A wrapping flex container
  reflows into more rows instead of overflowing, so `scrollWidth > clientWidth` is false at any width
  unless a single chip exceeds the pool. The pool is a **row-count-only** signal, never an overflow
  signal.

The stem holds the inline-block `<select>`s (drag-fill) and inline `<input>`s (fill-blank) that
`courses.css:22-26` names, and under the default `overflow: visible` its `scrollWidth` reflects
overflowing inline content.

#### Which build the measurement runs against (load-bearing)

The B1/B2 criteria only mean anything with `max-width: 46rem` **already landing on the stem**.
Measured against the *unmodified* build they are meaningless: `courses.css:1073` excludes
`.el--dragfill` from the cap today, so its stem's `clientWidth` is the card's inner ~830px — over the
738 threshold — and it would be classified **B2 unconditionally**, while B1 could never be observed
at all. Fill-blank's stem sits inside a currently-capped 736px card, so its `scrollWidth`/
`clientWidth` comparison would answer a question about ~694px, not 736px.

**The measurement runs against a scratch build carrying the unconditional entry**
`html.unit-tree-collapsed [data-unit-shell] .el--question .question__stem { max-width: 46rem }`
(no `:not()` chain), with the five removals already applied. B0/B1/B2 are read off *that* build; only
then is the final selector string fixed.

#### Measurement procedure

Run in a **JS-enabled e2e context** at 1280×900, collapsed, on seeded drag-fill **and** fill-blank
questions.

Use **realistic** fill-blank content — the inline `<input>`s that `{% render_fill_blanks %}` emits.
Do **not** seed a long unbreakable token: one overflows a 736px box in *any* container, including
`.el--text` today, so it would force a permanent carve-out for a content risk this spec explicitly
accepts above. **B1 requires the widget's own layout — the inline inputs/selects — to overflow**,
matching the accepted `.el--text` baseline.

**Synchronise before reading.** For drag-fill, wait for `.el--dragfill [data-dnd-pool]:not([hidden])`
and a `.dnd__chip` count > 0.

**Invalidity rule:** a recorded pool `clientWidth` of 0, a pool still carrying `[hidden]`, or a
missing pool element (the `:48` guard) means **the measurement did not happen**. Re-run it. It must
never be recorded as B0 — that is the silent-zero path that would fabricate a "no harm" verdict.

Record, per type, in the plan:

- `.question__stem` `getBoundingClientRect().width`
- `.question__stem` `scrollWidth` and `clientWidth`
- drag-fill only: `.dnd__pool` rendered row count and `clientWidth` (the latter solely as the
  validity check)

#### Verdict

| Branch | Criterion | Remedy |
|---|---|---|
| **B2** — cap does not bind | stem width > 738 | add `min-inline-size: 0` to that stem, then re-measure |
| **B1** — content overflows | stem `scrollWidth > clientWidth + 1` | keep/add the `:not()` carve-out for that type |
| **B0** — healthy | neither | stem entry becomes `.el--question .question__stem` |

Row-count growth alone is **not** harm. B2's remedy is **not** a `:not()` exclusion — if the cap
already fails to bind, excluding the element from it changes nothing.

#### MEASURED OUTCOME — both types are B0 (2026-08-11)

Run per the procedure above: scratch build, JS-enabled e2e, 1280×900, collapsed, realistic
content. **Validity satisfied** — the pool was live (not `[hidden]`, `clientWidth` 736, chips
rendered across 2 rows), so this is a real measurement, not the silent-zero path.

| Subject | width | scrollWidth | clientWidth | verdict |
|---|---|---|---|---|
| column (Reading recipe) | 872 | — | — | confirms the derived geometry |
| dragfill card | 872 | 870 | 870 | uncapped, fills the column |
| **fillblank stem** | **736** | 736 | 736 | **B0** |
| **dragfill stem** | **736** | 736 | 736 | **B0** |
| dragfill `.dnd__pool` | 736 | 736 | 736 | 2 rows, no overflow |

Neither criterion fired: no stem exceeded 738 (so the `<fieldset>` `min-inline-size: min-content`
floor did **not** refuse the cap), and neither overflowed. **The B1 and B2 branches are dead.**
Consequences, now fixed rather than conditional:

- The stem entry is **`.el--question .question__stem`** — no `:not()` chain.
- **No `min-inline-size: 0` rule**, and therefore no `/* prose-cap-fieldset:begin|end */` pair and
  no second source assertion.
- The prelude is **12 selectors**; `examined` is **16**, so the floor becomes `>= 16` exactly.
- Architecture stays **two** CSS regions.

The B1/B2 analysis above is retained as the rationale for *why* this had to be measured — not as
work to be done. An implementer must not build the dead branches.

**Also measured on the same build** (the user-facing premise, confirmed before planning):

| Element | width |
|---|---|
| callout, prose-only | 872 |
| callout, with children | 872 — **equal; the reported defect is fixed** |
| card, shorttext | 872 |
| card, choicegrid | 872 — **equal** |
| `.callout__body` | 736 — prose stays capped inside the widened box |
| `.lesson-unit__head` | 872 |
| `.lesson-unit__title` | **643.6** |

The title figure confirms the three-item-head derivation: it lands well below its own 736px cap,
so **no test may assert 736 for the title** — assert directionally or `< 738`.



**B2 placement and its own pin.** The `min-inline-size: 0` declaration must be a **separate rule with
its own single-selector prelude**, never added to the cap rule's shared declaration block (which
would apply it to `.el--text`, `.lesson-unit__title`, `.unit-crumbs` and the five gate wrappers as
well). It is placed **outside** `/* prose-cap:begin|end */` but **inside the same
`@media screen and (min-width: 641px)` block** — with its own sentinels inside that `@media` too,
mirroring R2's rule for the `prose-cap` pair. The media scoping is load-bearing: outside it,
`min-inline-size: 0` would apply at **every** viewport including below 641px, where no cap exists,
letting the fieldset shrink below its min-content contribution on phones for a reason unrelated to
this change. That is a live boundary — `tests/test_e2e_scroll_affordance.py` already drives question
widgets at a 390px viewport. Under B2, Architecture's "two CSS regions" becomes three.

The rule is invisible to R2's prelude assertion — so under B2 it gets **its own sentinel pair** `/* prose-cap-fieldset:begin */` …
`/* prose-cap-fieldset:end */`. That pair wraps the whole B2 region and may contain **one
single-selector rule per affected type**, each scoped `html.unit-tree-collapsed [data-unit-shell]`
and naming only that type's stem, with **one source assertion per rule**. Without that second pin the
B2 remedy would be covered by nothing.

**Correct carve-out selector.** If a type must be excluded, the working form is
`html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--dragfill) .question__stem`.
`.el--dragfill` sits on the element **root** (`dragfillblankquestionelement.html:2`), never on the
stem, so `.question__stem:not(.el--dragfill)` would match **every** stem including drag-fill's — a
silent no-op that would look like the risk had been addressed.

### R2 — the change is invisible in the expanded state

**The existing guard does not cover this.** `tests/test_consumption_css.py:191-206` iterates selectors
and `continue`s on any lacking `html.unit-tree-collapsed` — a lifted rule is **skipped, not caught**.
Only the `examined` floor catches a lift, incidentally, and being `>=` it tolerates a lift paired with
two additions.

**Required:** a positive assertion that the sliced prelude contains **exactly** the 12 expected
selectors, each containing both `html.unit-tree-collapsed` and `[data-unit-shell]`. Compare
`sorted(s.strip() for s in prelude.split(","))` against a sorted literal **and** assert the unsorted
list's length is 12, so a duplicated selector still reddens while a harmless reorder does not.

**Locating the block — both sentinels are pinned INSIDE the `@media` block.**
`/* prose-cap:begin */` goes immediately **before the rule's first selector** (i.e. just after
`@media screen and (min-width: 641px) {`), and `/* prose-cap:end */` immediately **after the rule's
closing brace**, still inside the `@media`. The slice is then exactly
`prelude { max-width: 46rem; }` — no at-rule, no comment. Both placements are load-bearing:

- **The rationale comment must stay outside.** The new rationale must explain why callouts left the
  cap, so the literal `.callout` will appear in its prose, and test 1 scans the slice for exactly
  that token — an inside-the-sentinels comment would redden test 1 on correct code. The comment also
  contains literal braces (`* { margin: 0 }`), which would desynchronise a brace split.
- **The `@media` prelude must stay outside.** With the begin sentinel before `@media … {`, splitting
  the slice on the closing brace fuses the at-rule prelude onto the first selector, yielding
  `@media screen and (min-width: 641px) { html.unit-tree-collapsed … .el--text` as "selector 1".
  That is the exact trap `tests/test_consumption_css.py:184-190` documents. The sorted comparison
  could never match, and the "contains `[data-unit-shell]`" check would pass vacuously on the fused
  string.

**Extraction is a four-step sequence, not a choice:** (1) read the file **un-stripped** — the
sentinels are comments; (2) slice between them; (3) strip comments from the slice; (4) take
`slice.rsplit("{", 1)[0]` as the prelude, then split it on `,`. Steps 1 and 3 are both mandatory.

### R3 — a widened tinted box with short content

A text-only callout now paints tint across 872px while its body text stops at 736px, leaving **136px**
of empty tint on the right (right only — capped elements are left-aligned). **Accepted, not a
defect** — the user chose it explicitly over letting text fill the box.

## Testing

**Every new or changed assertion must be falsified against a named mutant**
(`css-confirmation-needs-an-ab-not-a-measurement`, `falsify-tests-not-run-them`).

**Viewports.** New tests run at **1280×900**. The existing `test_e2e_unit_nav.py` tests **stay at
1440×900** — not because the geometry differs (it is identical) but to keep the diff to the
assertions being changed.

**Constant discipline.** Assertions carry their weight on the **736 / 352 tokens**
(`abs(w - 736) < 2`) and on **directional** comparisons. Threshold constants with tens of pixels of
slack (`- 100`, `+ 50`) are banned as primary assertions: at the real geometry they leave 36-44px of
headroom and flip red on correct code if `.app-main` or any padding ever narrows.

**State discipline.** Expanded, the column is 648px and *every* capped element also measures 648, so
equality-only and `<= 738`-only assertions pass in the wrong TOC state. **Tests 3, 5, 6, 8, 9 and 10
must each assert `document.documentElement.classList.contains('unit-tree-collapsed')` explicitly**,
and test 7 must assert the class is **absent**. This is not width-derived and therefore cannot be
satisfied by the wrong state.

### Tests that must change

1. **`courses/tests/test_callout_nesting_css.py`** — `:22` is the test *name* to rename; **`:23-27` is
   a docstring that goes stale** ("A table nested in a callout must not inherit the 46rem prose cap… the
   load-bearing edit is narrowing `.callout`") — after this change the load-bearing edit is *removing*
   the `.callout` entry, and "must not inherit the cap" applies to every callout, not just one with
   children; `:29` is the first assertion, `:30` the second. The `:29` assertion inverts: the sliced, comment-stripped cap
   block must contain no `.callout` selector. Assert with a **token-boundary regex** —
   `re.search(r"\.callout(?![\w-])", block) is None` — so `.callout__body` / `.callout__children` /
   `.callout__heading` do not false-positive. The `:30` assertion requires a **trailing comma**
   (`\.callout\s*,`), so a `.callout` re-added as the *last* prelude selector escapes it; fold it into
   the inverted assertion or widen its terminator to `[,{]`.

2. **`tests/test_e2e_callout_container.py:146-156`** — the `prose_box` arm at `:147-151` *and* the
   `wide_box` arm at `:152-155`; the old anchor covered only half the edit. Rewrite to assert the two
   callout widths are **equal AND both exceed 736px** — equality alone passes when *both* are capped,
   the squeezed-table regression this test prevents. Its **docstring at `:117-120` must also be
   corrected**: it states the column as "min(viewport, 72rem) - 2.4rem - 3rem", the pre-`.app-main`
   formula this spec supersedes, which yields 1065.6px at the 1280px viewport the test uses.

3. **`tests/test_e2e_unit_nav.py:1376-1398`**, `test_quiz_chrome_is_capped_across_both_page_states`.
   Four assertions go red (`:1379` and `:1398` loops assert `w <= 736 + 2`). Rewrite so
   `.lesson-unit__title` still asserts `<= 738` while `.el--question`, `[data-quiz-preview-notice]`
   and `.quiz-finish` equal the column. Apply the State discipline rule above; re-derive the
   inline comment at `:1384-1388`. Keep the `locator(...).count()` existence assertions untouched.

4. **`tests/test_consumption_css.py`** — **five** sites carry the old counts, plus the new assertion:
   the floor at `:212` (`>= 17` → `>= 16`); its message at `:213-214` ("expected >= 17"); the
   derivation comment at `:208-211` ("one per allow-list entry (13) = 17" → `4 + 12 = 16`); the
   comment at `:190` ("the entire thirteen-selector list"); and the docstring at `:157-166`
   ("the **thirteen** capped selectors", "four of the **thirteen** entries" — after this change the
   count is twelve and three of those four leave the cap). Then add the R2 exact-list assertion.
   Nothing else may be weakened. Per `comments-can-fail-tests` this repo treats such prose as
   load-bearing, so leaving any of the five stale is a defect, not a cosmetic miss.

### Tests to add

5. **Card-width agreement (e2e):** on one seeded lesson unit, a plain question card, a `choicegrid`
   card, a text-only callout and a container callout all have equal width, **and at least one of them
   equals the Reading recipe's column reading** (peer-equality alone is state-blind). Also assert
   `.lesson-unit__head` equals the column — but assert its title **directionally** (title width
   greater than in a capped control, or simply `< 738`), **never** `abs(title - 736) < 2`: with the
   three-item head the title lands at ~650px and a 736 assertion fails on correct code. On the quiz
   page, `[data-quiz-preview-notice]` equals the question-card width (needs the owner-not-enrolled
   load — see `test_quiz_chrome_is_capped_across_both_page_states`'s docstring). The
   `.lesson-unit__head` arm must live here, not in test 3: `_quiz_article.html` has no
   `.lesson-unit__head` at all, so test 3 can never cover it — and it is the one removed entry the
   spec flags as a judgement call.

6. **Prose-inside-a-box (e2e):** `.callout__body`, `.question__stem`, `.question__choices`,
   `.question__feedback` and `textarea.question__text-input` each measure 736px inside their widened
   boxes. **Assert `abs(width - 736) < 2`.** Do not assert merely "narrower than its own box" — the
   containers have padding, so a child is *always* narrower, cap or no cap. The container callout
   fixture must carry a **non-empty `body`**: `calloutelement.html:7` renders `.callout__body` under
   `{% if el.body %}`, so a children-only callout has no body element and the locator resolves to
   nothing.

   **`.question__feedback` needs a fixture too, and a different read.** On a plain seeded lesson load
   its contents are `{% if mode == "quiz" %}…{% elif element.pk == feedback_for_pk %}…{% endif %}`,
   which renders nothing — leaving a whitespace-only block of height 0, and `courses.css:158` is
   `.el--question .question__feedback:empty { display: none; }`, one whitespace change from removing the
   box entirely. Make feedback actually render (submit an answer so `element.pk == feedback_for_pk`, or
   load in quiz mode with `feedback_html`), and read this arm with
   `getBoundingClientRect().width` via `page.evaluate` rather than `bounding_box()`, which is
   unreliable on a zero-height element. Scope each locator to its own card/callout.

7. **Expanded state (e2e):** the expanded column is 648px, **below** the cap, so a lifted rule changes
   no measured width and a width-based test passes on its own mutant. Assert **computed style**:
   `getComputedStyle(el).maxWidth === 'none'` for the callout and both question cards, with the
   `unit-tree-collapsed` class asserted **absent**.

8. **Grid-type stems narrow (e2e):** the five grid types are excluded today, so their stems fill the
   **card's inner box** (~830px, *not* the 872px column); adding `.question__stem` narrows them to
   736px. Assert `abs(stem_width - 736) < 2` — that half carries the weight — plus the directional
   `scroll_x_width > stem_width + 2`. `.scroll-x` is the **edge-shading wrapper**, not the scroller
   (`app.css:1668-1675` documents that it "does NOT scroll"; the scroller is the inner
   `.choicegrid-scroll` / `.multigrid-scroll`), and its width is **not** pinned to ~830 because the
   bare `<fieldset>` at `choicegrid:7` has no `min-inline-size: 0` and may refuse to shrink — which is
   why only the directional half is asserted. The fixture **must set a non-empty `stem`**
   (`choicegridquestionelement.html:3` is `{% if el.stem %}`); scope the locator
   `.el--choicegrid .question__stem`.

9. **Short-answer input unchanged (e2e):** `input.question__text-input` still measures **352px**
   (22rem) in the collapsed state, pinning the specificity hazard described under "In". The
   collapsed-state assertion is mandatory here: the `:319-320` cap is unscoped, so the input measures
   352px in *both* states and the mutant only diverges collapsed.

10. **Fieldset stems (e2e) — B0 confirmed:** assert `abs(stem_width - 736) < 2` **and**
    `scrollWidth <= clientWidth + 1` for **both** drag-fill and fill-blank. This is the pin that the
    `<fieldset>` `min-inline-size` floor does not refuse the cap and that neither widget overflows.
    Must sync on the pool being live before reading (see the invalidity rule).

### Falsification

| Test | Mutant |
|---|---|
| 1 | re-add `.callout:not(:has(> .callout__children))`; **separately** add `.callout__body` to confirm the token boundary does *not* redden |
| 2 | re-add the callout entry (boxes diverge); **and separately** cap *both* callouts, to prove the `> 736` half fails too |
| 3 | re-add `[data-quiz-preview-notice]` and `.quiz-finish`; **and separately** drop the collapsed-state guard and run expanded, to prove the state check still bites |
| 4 | remove one selector from the block (length + list assertion); duplicate one selector (length assertion); unscope one selector (positive assertion) |
| 5 | re-add the **whole** old `.el--question:not(.el--choicegrid):not(…)` entry — this caps the plain card at 736 while the choicegrid card stays at the column, reddening the plain-vs-choicegrid and plain-vs-callout comparisons (it does **not** redden callout-vs-callout); **separately** re-add `.lesson-unit__head` to the cap for that arm |
| 6 | one mutant **per capped container**, each deleting only that entry: `.question__stem`; `.el--text` (which carries `.callout__body`, so this is the body half); `.question__choices`; `.question__feedback`; `textarea.question__text-input`. Every arm must be shown red independently |
| 7 | re-add a **deleted** entry — e.g. `.callout:not(:has(> .callout__children))` — **without** the `html.unit-tree-collapsed` prefix, so the expanded state regains a `max-width: 46rem`. (The obvious mutant "unscope one of the *new* rules" does **not** work: the new rules are `.question__stem` / `.question__choices` / `.question__feedback` / `textarea…`, none of which is a subject of test 7.) |
| 8 | delete the `.question__stem` entry |
| 9 | write the new textarea entry with a bare class (`.question__text-input`), which out-specifies `:319-320` and jumps the input to 736 |
| 10 | add a `:not(.el--dragfill)` carve-out to the stem entry, which returns the drag-fill stem to the card's inner box (~830) and reddens `abs(w - 736) < 2` |

Note the trap from this file's own history: an assertion pinned to a bare class name can be satisfied
by `lesson_unit.html`'s inline pre-hide `<style>`, which emits `.callout__children` as a literal in
the page `<head>`. Source-scan assertions must be pinned to the attribute form, and CSS-block
assertions must extract the block first (via the R2 sentinels and its four-step sequence).

### Regression scope

- Non-e2e suite plus the e2e files touching callouts, questions, the unit shell, and consumption CSS.
- `tests/test_e2e_unit_head_layout.py` guards the three-item head row and must stay green.
- The teacher review page and quiz results page render none of these capped selectors inside
  `[data-unit-shell]` (only `_unit_shell.html` carries that attribute); confirm no e2e covering them
  changes.

### Visual verification

Screenshot the collapsed student unit page in **light and dark**, judged separately
(`verify-ui-with-screenshots`), showing a text-only callout, a container callout, a plain question
card and a grid question card together; a quiz page showing the `.quiz-finish` separator against the
card edges; and **a long lesson title on a unit with a stateful element** (so the three-item head
renders), to see the re-wrap. Dark mode is what catches a tinted box whose widened area reads as a
different surface.

### Test-run mechanics

Start the test-DB container **before** any pytest run, or the suite looks hung for ~4m21s. Tooling is
behind `uv run` (`ruff`, `pytest`, `python` are not on PATH); e2e needs `-m e2e` or it silently
deselects (exit 5, which is **not** a pass); use `--verbosity=0`, never a second `-q`. Run narrowly
scoped. Two other pipeline worktrees exist on this machine — never run two pytest sessions at once,
they contend for the same test database. A worktree has no `.env`, so database settings must be
passed explicitly.
