# Uniform width for background-bearing blocks on the student unit page

## Purpose

On a student unit page with the course tree (TOC) collapsed, two callouts render at two different
widths. A callout holding only text is capped at 46rem (736px); a callout that has child elements
runs the full column (~1066px at a 1280px viewport). A student reading two worked examples sees one
box noticeably wider than the other, with no meaning attached to the difference. The user's report:

> when callouts have child elements they are wider than when they have only text. This is confusing.
> Students see two examples, one wider, the other narrower.

The same split already affects question cards. `.el--question` carries a card background
(`courses.css:295-301`, `background: var(--surface-raised)`), and the five grid-ish question types
(`choicegrid`, `multigrid`, `dragimage`, `matchpair`, `dragfill`) are excluded from the cap while
plain question types are not — so a quiz already shows two card widths for the same reason.

The goal is the user's stated rule: **every element-root block that paints a background different
from the page background renders at one width.**

### Non-goals

- Changing anything in the TOC-**expanded** state. Nothing is capped there today (see Architecture),
  so widths are already uniform and must stay byte-identical. This is pinned by test 6, not merely
  asserted.
- Changing the teacher review page or the quiz results page.
- Restructuring how the cap is applied. Two alternatives were considered and **explicitly rejected by
  the user**: (a) moving to an inner prose wrapper so element roots default to full width, and
  (b) leaving the allow-list intact and adding later `max-width: none` override rules. Neither is to
  be reintroduced during implementation.
- Narrowing anything tinted. An earlier option to cap *all* tinted blocks at 46rem was considered and
  rejected, because it would squeeze a table nested inside a callout — the exact regression the
  current exclusion exists to prevent.

## Current behaviour (verified against the worktree, not recalled)

Three rules interact. All line numbers are against `courses/static/courses/css/courses.css` at
`d197a4c7` unless stated.

1. `:291-292` — `.quiz, .lesson { max-width: 46rem; margin-inline: auto; }`. This is the standalone
   (non-shell) cap.
2. `:656-657` — `.unit-shell__main > .lesson, .unit-shell__main > .quiz { max-width: none;
   margin-inline: 0; padding: 1.25rem 1.5rem; }`. **Unconditional.** Inside the unit shell the
   article is never capped, in either TOC state.
3. `:1063-1086` — the "Prose cap" rationale comment (`:1063-1069`) and the rule block itself
   (`:1070-1086`), inside `@media screen and (min-width: 641px)`, every selector scoped
   `html.unit-tree-collapsed [data-unit-shell]`. Thirteen entries, each capped at `max-width: 46rem`.

Consequences, which the implementation must preserve:

- **TOC expanded:** rule 2 removes the cap and rule 3 does not match (no `html.unit-tree-collapsed`).
  *Nothing on the page is capped*, so every element is already the same width. This state must not
  change.
- **TOC collapsed:** rule 3 matches, and only the thirteen listed selectors are capped. Everything
  else fills the column. That is where the two widths come from.

The block's own comment states the design intent: it is an **allow-list, not cap-by-default**,
because "a missed opt-out BREAKS layout (a squeezed table) whereas a missed allow-list entry only
leaves prose wide."

### Derived geometry (orientation only)

At a 1280×900 viewport in the collapsed state: `.unit-shell` is `min(1280px, 72rem) = 1152px`
(`:654`); `:1051` shifts it by `-2.4rem` at ≥1040px and the pin lane consumes `2.4rem`, leaving
`.unit-shell__main` at 1113.6px; `.lesson`'s `1.25rem 1.5rem` padding leaves a content box of
**1065.6px**.

**Which numbers may be asserted.** 46rem = **736px** is a *design token* — it is the single value
this feature caps at, existing tests already assert it (`test_e2e_unit_nav.py:1380`,
`test_e2e_callout_container.py:148`), and new tests may assert it. The **shell-derived** numbers
(1152 / 1113.6 / 1065.6) are computed from four separate rules and shift whenever any of them moves;
**no test may assert those as constants.** Where a test needs the column width, it must read it from
the page (e.g. the `.lesson` content box) or compare two elements to each other.

## The rule this change installs

> **In the TOC-collapsed state, tinted element-root blocks fill the column; prose caps at 46rem
> wherever it lives — including inside a tinted block.**

This replaces the allow-list's rationale comment at `:1063-1069`; the comment rewrite is part of this
change, not incidental to it. The value of the change is as much that a future author can apply one
sentence as that two boxes line up: the present list cannot be extended correctly without guessing,
which is how the callout and question splits arose in the first place.

### Two scope limits, both deliberate

**S1 — the rule governs element *roots*, not sub-element tints.** A student perceives "an example",
"a question", "a note" as boxes; the rule makes those agree. Decoration *inside* such a box —
`.question__feedback-panel` (`:165-190`, four tint variants), the `.markdone` row hover tint
(`:2053-2054`), `.unit-done__pill` (`:833-836`) — is internal to its container and tracks whatever
prose container holds it. It is **out of scope**, and an implementer must not widen these to "fix"
them. Consequence to accept knowingly: a feedback panel renders at ≤736px inside a ~1066px question
card.

**S2 — the invariant holds *per nesting level*.** `courses/builder.py` registers Callout, Spoiler,
TwoColumn, BeforeAfter and Tabs as containers, and questions are nestable inside them (PR #240).
`.quiz .el--question` is a *descendant* selector, so a question card nested inside a callout is
tinted too, but its available width is the callout's content box, not the column. Today both nested
and top-level cards are capped at 736px and so happen to be equal; after this change they diverge.
This is **accepted**: a nested box cannot exceed its parent, and a rule promising otherwise would be
unimplementable. Nested tinted blocks (question-in-callout, callout-in-callout, anything inside a
`.twocolumn__column`, whose min is 9-12rem at `:1797-1798`) are uniform *with their siblings at the
same level*, which is what a reader actually compares.

## Architecture

One CSS region changes: `courses.css:1063-1086` (rationale comment + rule block). Five selectors out,
four in. No template changes, no JavaScript, no Python.

### Out — tinted element roots, which now fill the column

| Entry | Why it is tinted |
|---|---|
| `.callout:not(:has(> .callout__children))` | `:1834-1839`, `background: color-mix(in srgb, var(--callout-accent) 6%, var(--surface-raised))` |
| `.el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill)` | `:295-301`, `background: var(--surface-raised)` |
| `[data-quiz-preview-notice]` | `templates/courses/_quiz_article.html:20` renders it `class="alert alert--info"`; `core/static/core/css/app.css:216`, `background: var(--primary-subtle)` |

Each entry is removed **in full, including its `:not()` chain**. Removing the five `:not()` exclusions
from the question entry is what makes all seven question types one width; removing
`:not(:has(> .callout__children))` from the callout entry is what makes both callout shapes one width.

### Out — chrome that frames the cards

| Entry | Why it moves |
|---|---|
| `.quiz-finish` | `:322` is a `border-top: 1px solid` separator drawn *under the question cards*. Left capped, the rule stops ~330px short of the card edges it is meant to bound — a visibly broken separator. |
| `.lesson-unit__head` | `:824`, the flex row holding the title and the right-aligned `.unit-done__pill`. Left capped, the pill no longer lines up with the right edge of the cards below it. |

Both are transparent, so neither is tinted — they move for **alignment**: chrome that frames the
cards must share the cards' edges. `.lesson-unit__title` **stays capped**, so the heading text itself
keeps its readable measure while its container widens.

This is a judgement call slightly beyond the literal request ("blocks with a background"), taken
because leaving it out ships a visibly misaligned separator as a direct consequence of the change.
It must be called out in the PR body so the user can reverse it cheaply if unwanted.

### In — prose and answer controls inside a tinted block

| Entry | Covers |
|---|---|
| `.el--question:not(.el--dragfill) .question__stem` | the question prose (see R1 for the `:not()`) |
| `.question__choices` | the options list (`choicequestion.html:12`) |
| `.question__feedback` | per-question feedback prose |
| `textarea.question__text-input` | the extended-response answer box |

These exist because the user chose "the box widens, the prose inside does not." Without them a
question card would widen *and* stretch its contents to ~1066px, contradicting the rule for callouts
and worsening the readability the cap exists to protect.

`textarea.question__text-input` is a separate entry because the textarea is **not** a descendant of
any of the other three: `extendedresponsequestionelement.html:7-9` makes it a direct child of
`.question__form`, a sibling of the stem. `:317-318` caps only `input.question__text-input` (22rem)
and its comment says the textarea "keeps app.css's `width:100%` and fills the card column" — which
after this change would be ~1066px, a ~128-character answer box. The submit `<button>` needs no entry
(a button does not stretch to its container).

`.callout__body` needs **no** entry: `templates/courses/elements/calloutelement.html:7` renders it as
`<div class="el el--text callout__body">`, and `.el--text` remains on the list. Adding a
`.callout__body` selector would be a no-op — a fact `courses/tests/test_callout_nesting_css.py:25`
already records in a comment.

### Completeness obligation

The implementation must **enumerate every child of `.el--question`** across all seven question
templates and show each is either (a) a descendant of one of the four capped selectors, or (b)
deliberately wide (a grid, stage, or scroll container). The table in R1 does this for wide *widgets*;
it does not by itself establish that nothing else stretches. Record the enumeration in the plan.

### Entries that stay

`.el--text`; `.lesson-unit__title`; `.unit-crumbs` (`:849`); and the five gate wrappers `.markdone`,
`.fillgate` (`app.css:1031`), `.stepper`, `.switchgate` (`app.css:1103`), `.guessnumber`
(`app.css:1558`). Each of the gate wrappers either **declares margin only or has no root rule at
all** — there is no `.markdone { … }` or `.stepper { … }` rule in either stylesheet. The conclusion
holds (none paints a background at the root); the reason differs per selector. Per **S1** the
`.markdone` row hover tint at `:2053-2054` is a sub-element tint and stays with its container.

### Entry count

13 before, 5 removed, 4 added → **12 after**. `tests/test_consumption_css.py:212` asserts
`examined >= 17` (4 structural selectors + one per allow-list entry); after this change the correct
value is **4 + 12 = 16**, so that assertion **must be re-derived to `>= 16`** and its comment updated.
Its comment already anticipates this: "re-derive this number only on a removal." If R1's measurement
changes the selector shape further, re-derive again.

## Data flow

There is no runtime data flow; the flow is the CSS cascade resolving a used width. For a given
element on the student unit page:

1. Is `html.unit-tree-collapsed` set? Set pre-paint by `base.html` from a global localStorage key.
   If not → no cap, element fills the column. **Unchanged by this work.**
2. Is the viewport ≥641px and the medium `screen`? If not → no cap. **Unchanged.**
3. Is the element inside `[data-unit-shell]`? Scoping that keeps the rule off the teacher review page,
   which reuses the `.unit-shell` class but is not the student shell. **Unchanged.**
4. Does the element match one of the allow-list selectors? **This is the only step this change
   touches.** After the change: tinted element roots and card chrome do not match (fill the column);
   prose and answer controls do match (46rem), including prose nested inside a tinted block.

Because prose containers are matched by **descendant** selectors, a `.el--text` or `.question__stem`
nested at any depth still caps — which is what makes "prose caps wherever it lives" true without
per-container entries.

## Error handling

CSS has no error path; the failure modes are silent mis-rendering. Three are identified, each with a
required response rather than an assumption.

### R1 — drag-fill nests its widget inside the stem

Widget placement relative to `.question__stem` was checked in every question template:

| Type | Wide widget | Position | Capping the stem |
|---|---|---|---|
| choicegrid | `.scroll-x` (`choicegridquestionelement.html:9,24`) | **sibling** of stem (`:3`) | safe |
| multigrid | `.scroll-x` (`multigridquestionelement.html:9,24`) | **sibling** of stem (`:3`) | safe |
| dragimage | `.dragimage__stage` (`dragtoimagequestionelement.html:8,31`) | **sibling** of stem (`:3`) | safe |
| matchpair | pair widget | **sibling** of stem (`matchpairquestionelement.html:3`) | safe |
| fillblank | inline `<input>`s in prose | inside a `<fieldset>` stem (`fillblankquestionelement.html:17`) | safe — prose min-content is small |
| shorttext / shortnumeric / extendedresponse | none | — | safe |
| **dragfill** | **`.dnd__pool`** | **inside** the stem — `dragfillblankquestionelement.html:13` (fieldset branch) and `:22` (no-form branch) | **must be measured** |

Drag-fill is the single shape where capping `.question__stem` constrains a widget rather than prose.
Two failure modes point in opposite directions, **and each needs a different remedy** — which is why
this must be measured rather than guessed:

| Branch | Symptom | Remedy |
|---|---|---|
| **B1** — pool wraps | stem caps at 736px, `.dnd__pool` reflows to more rows, no overflow | none; drop the `:not(.el--dragfill)` from the stem entry |
| **B2** — cap does not bind | the `<fieldset>`'s default `min-inline-size: min-content` floor wins, stem stays ~1066px | add `min-inline-size: 0` to the stem so the cap can bind, then re-measure |

Note B2's remedy is **not** `:not(.el--dragfill)` — if the cap already fails to bind, excluding the
element from the cap changes nothing. This also potentially affects
`fillblankquestionelement.html:17`, likewise a `<fieldset class="question__stem">` whose inline
`style` sets border/padding/margin but not `min-inline-size`.

**Correct carve-out selector.** If drag-fill must be excluded, the working form is
`html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--dragfill) .question__stem`.
`.el--dragfill` sits on the element **root** (`dragfillblankquestionelement.html:2`:
`<div class="el el--question el--dragfill">`), never on the stem, so
`.question__stem:not(.el--dragfill)` would match **every** stem including drag-fill's — a silent
no-op that would look like the risk had been addressed. The spec's default is to ship the `:not()`
form and remove it only if B1 is measured.

**Mechanical definition of harm** (so two implementers reach the same verdict). Measure, at 1280×900
collapsed, on a seeded drag-fill question, and record all three numbers in the plan:

- `.question__stem` `getBoundingClientRect().width`
- `.dnd__pool` `scrollWidth` and `clientWidth`
- the pool's rendered row count

**Harm** is exactly: (a) stem width > 738 (the cap failed to bind → **B2**), **or** (b) pool
`scrollWidth > clientWidth` (horizontal overflow → **B1** carve-out retained). Row-count growth alone
is **not** harm.

### R2 — the change is invisible in the expanded state

Every selector edited lives under `html.unit-tree-collapsed`, so an implementation that accidentally
lifted a rule out of that block would change the expanded state.

**The existing guard does not cover this.** `tests/test_consumption_css.py:184-206` iterates
selectors and `continue`s on any selector *lacking* `html.unit-tree-collapsed` — a lifted rule is
**skipped, not caught**. Only the `examined >= 17` floor catches a lift, incidentally, via the count
dropping; and because it is `>=`, lifting one selector while adding two scoped ones still passes.

**Required:** add a positive assertion that the cap block's prelude contains **exactly** the expected
12 selectors, each containing both `html.unit-tree-collapsed` and `[data-unit-shell]`. Plus test 6
below, which measures the expanded state directly.

### R3 — a widened tinted box with short content

A text-only callout now paints tint across ~1066px while its body text stops at 736px, leaving
~330px of empty tint on the right. This is **accepted, not a defect** — the user chose it explicitly
over the alternative of letting text fill the box (~128 characters per line, past comfortable reading
length). Recorded so a later reviewer does not "fix" it.

## Testing

The repo convention applies without exception: **every new or changed assertion must be falsified
against a named mutant**, and a CSS claim needs an **A/B** — a measurement taken with the rule present
proves nothing on its own (`css-confirmation-needs-an-ab-not-a-measurement`).

**Viewports.** Tests 1-5 run at **1280×900**, matching `test_e2e_callout_container.py` (whose
docstring explains why 641px is too narrow: the collapsed content box there is ~555px, below the
736px cap, so the cap never binds). The existing `test_e2e_unit_nav.py` tests **stay at 1440×900**;
both viewports are above the cap, but their derived geometry differs, so do not unify them.

### Tests that must change

1. **`courses/tests/test_callout_nesting_css.py:22`**,
   `test_prose_cap_no_longer_applies_to_a_callout_with_children`. Its first assertion — that
   `.callout:not(:has(> .callout__children))` **exists** — inverts: the cap block must now contain
   **no `.callout` selector in any form**. Its second assertion (no bare `.callout,`) stays true and
   stays. Rename the test to match its new claim.

2. **`tests/test_e2e_callout_container.py:147-150`**,
   `test_a_table_in_a_callout_is_not_squeezed_by_the_prose_cap`. It currently asserts a prose-only
   callout measures 736px. Rewrite it to assert the two callout widths are **equal AND both exceed
   736px**. Equality alone is insufficient: it passes when *both* callouts are capped at 736 — i.e.
   the squeezed-table regression this test exists to prevent. Both halves are required, or the test
   fails in one direction only.

3. **`tests/test_e2e_unit_nav.py:1376-1398`**,
   `test_quiz_chrome_is_capped_across_both_page_states`. Four assertions go red: both loops assert
   `w <= 736 + 2`, and `.el--question` (a plain `ShortTextQuestionElement`),
   `[data-quiz-preview-notice]` and `.quiz-finish` all leave the cap under this change. Rewrite so
   `.lesson-unit__title` still asserts `<= 738` while the other three assert they now **equal the
   column width**. **Preserve the test's real purpose**, which its docstring states: proving those
   selectors *exist at all*, so their deletion cannot ship green. Keep the existence assertions
   (`locator(...).count() == 1`) untouched.

### Tests to add

4. **Card-width agreement (e2e):** on one seeded unit, a plain question card, a `choicegrid` card, a
   text-only callout and a container callout all have equal width; and on the quiz page,
   `[data-quiz-preview-notice]` equals the question-card width. The preview notice needs the
   owner-not-enrolled load (see `test_quiz_chrome_is_capped_across_both_page_states`'s docstring for
   how to reach that state). Compare pairwise — never against a shell-derived constant.

5. **Prose-inside-a-box (e2e):** `.callout__body` and `.question__stem` measure ~736px *inside* their
   widened boxes. Do **not** assert merely "narrower than its own box" — `.callout` has
   `padding: var(--space-4)` (`:1838`) and `.quiz .el--question` has `padding: var(--space-5)`
   (`:298`), so a child is *always* strictly narrower than its parent's border box, cap or no cap;
   on the mutant the stem measures ~1034px inside a 1066px card and still passes. Assert the 736px
   token, or `prose_width < box_width - 100`, and confirm **both halves** go red on the mutant.
   Include a **grid-type** stem (see test 7) in the same measurement.

6. **Expanded state unchanged (e2e):** load the same seeded unit with the TOC **expanded** and assert
   the callout, both question cards and `.el--text` all equal the column width — i.e. no cap binds.
   This is the only test that pins the Non-goal; every other test runs collapsed.

7. **Grid-type stems narrow (e2e):** `choicegrid`, `multigrid`, `dragimage`, `matchpair` and
   `dragfill` are excluded from the cap today, so their stems fill the column; adding
   `.question__stem` narrows all five from ~1066px to 736px. This is an **intended** consequence of
   S1 + the user's "prose stays readable" choice, but it is a behaviour change to types the Purpose
   section does not mention, so it must be pinned rather than left incidental. Assert a grid stem
   measures ~736px while its `.scroll-x` sibling stays at column width.

8. **Drag-fill (e2e), per R1:** pin whichever branch measurement selects, and record the three
   measured numbers in the plan.

### Falsification

Each test must be shown RED against a specific mutant, named in the plan and **run**, not merely
cited (`falsify-tests-not-run-them`):

| Test | Mutant |
|---|---|
| 1 | re-add `.callout:not(:has(> .callout__children))` to the block |
| 2 | re-add the callout entry (both boxes diverge again) — and separately, cap *both* callouts, to prove the `> 736` half fails too |
| 3 | re-add `[data-quiz-preview-notice]` and `.quiz-finish` |
| 4 | re-add the `:not(.el--choicegrid)` exclusion |
| 5 | delete the `.question__stem` entry (prose stretches to fill) |
| 6 | write any new rule without the `html.unit-tree-collapsed` prefix |
| 7 | delete the `.question__stem` entry |
| 8 (B1) | remove the `.question__stem` entry — pool goes full width |
| 8 (B2) | remove the `min-inline-size: 0` — stem stays wide despite the cap |

Note the trap from this file's own history: an assertion pinned to a bare class name can be satisfied
by `lesson_unit.html`'s inline pre-hide `<style>`, which emits `.callout__children` as a literal in
the page `<head>`. Source-scan assertions must be pinned to the attribute form
(`'class="callout__children"'`), and CSS-block assertions must **extract the block before scanning**.

### Regression scope

- Non-e2e suite plus the e2e files touching callouts, questions, the unit shell, and consumption CSS.
- `tests/test_consumption_css.py` changes in exactly two ways: the `>= 17` floor becomes `>= 16` with
  its comment re-derived, and the positive 12-selector assertion of R2 is added. Nothing else in it
  may be weakened.
- The teacher review page and quiz results page render none of these capped selectors inside
  `[data-unit-shell]`; confirm no e2e covering them changes.

### Visual verification

Screenshot the collapsed student unit page in **light and dark**, judged separately
(`verify-ui-with-screenshots`), showing a text-only callout, a container callout, a plain question
card and a grid question card together, plus a quiz page showing the `.quiz-finish` separator against
the card edges. The dark-mode judgement is what catches a tinted box whose widened area reads as a
different surface, and the quiz shot is what confirms the I1 chrome decision looks right.

### Test-run mechanics

Start the test-DB container **before** any pytest run, or the suite looks hung for ~4m21s. Run
narrowly scoped; a whole-repo sweep is a branch gate, not a task step. Two other pipeline worktrees
exist on this machine — never run two pytest sessions at once, since they contend for the same test
database. A worktree has no `.env`, so database settings must be passed explicitly rather than
assumed.
