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

The goal is the user's stated rule: **every block that paints a background different from the page
background renders at one width.**

### Non-goals

- Changing anything in the TOC-**expanded** state. Nothing is capped there today (see Architecture),
  so widths are already uniform and must stay byte-identical.
- Changing the teacher review page or the quiz results page.
- Restructuring how the cap is applied. Two alternatives were considered and **explicitly rejected by
  the user**: (a) moving to an inner prose wrapper so element roots default to full width, and
  (b) leaving the allow-list intact and adding later `max-width: none` override rules. Neither is to
  be reintroduced during implementation.
- Narrowing anything. An earlier option to cap *all* tinted blocks at 46rem was considered and
  rejected, because it would squeeze a table nested inside a callout — the exact regression the
  current exclusion exists to prevent.

## Current behaviour (verified, not recalled)

Three rules interact. All line numbers are against `courses/static/courses/css/courses.css` at
`d197a4c7` unless stated.

1. `:291-292` — `.quiz, .lesson { max-width: 46rem; margin-inline: auto; }`. This is the standalone
   (non-shell) cap.
2. `:656-657` — `.unit-shell__main > .lesson, .unit-shell__main > .quiz { max-width: none;
   margin-inline: 0; padding: 1.25rem 1.5rem; }`. **Unconditional.** Inside the unit shell the
   article is never capped, in either TOC state.
3. `:1070-1086` — the "Prose cap" block, inside `@media screen and (min-width: 641px)`, every
   selector scoped `html.unit-tree-collapsed [data-unit-shell]`. Thirteen entries, each capped at
   `max-width: 46rem`.

Consequences, which the implementation must preserve:

- **TOC expanded:** rule 2 removes the cap and rule 3 does not match (no `html.unit-tree-collapsed`).
  *Nothing on the page is capped*, so every element is already the same width. This state is out of
  scope and must not change.
- **TOC collapsed:** rule 3 matches, and only the thirteen listed selectors are capped. Everything
  else fills the column. That is where the two widths come from.

The block's own comment states the design intent: it is an **allow-list, not cap-by-default**,
because "a missed opt-out BREAKS layout (a squeezed table) whereas a missed allow-list entry only
leaves prose wide."

### Derived geometry (for orientation only — tests must not assert these constants)

At a 1280×900 viewport in the collapsed state: `.unit-shell` is `min(1280px, 72rem) = 1152px`
(`:654`); `:1051` shifts it by `-2.4rem` at ≥1040px and the pin lane consumes `2.4rem`, leaving
`.unit-shell__main` at 1113.6px; `.lesson`'s `1.25rem 1.5rem` padding leaves a content box of
**1065.6px**. Capped elements sit at 46rem = **736px**.

These numbers are derived from the cascade, not measured. They are recorded to make the intent
legible and to size the e2e viewport; **no test may assert them as constants** (see Testing).

## The rule this change installs

> **In the TOC-collapsed state, tinted blocks fill the column; prose caps at 46rem wherever it lives —
> including inside a tinted block.**

This replaces the allow-list's current rationale comment. The value of the change is as much that a
future author can apply one sentence as that two boxes line up: the present list cannot be extended
correctly without guessing, which is how the callout and question splits arose in the first place.

## Architecture

One CSS block changes: `courses.css:1070-1086`. Three selectors out, three in. No template changes,
no JavaScript, no Python.

### Out — tinted blocks, which now fill the column

| Entry | Why it is tinted |
|---|---|
| `.callout:not(:has(> .callout__children))` | `:1834-1839`, `background: color-mix(in srgb, var(--callout-accent) 6%, var(--surface-raised))` |
| `.el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill)` | `:295-301`, `background: var(--surface-raised)` |
| `[data-quiz-preview-notice]` | `templates/courses/_quiz_article.html:20` renders it `class="alert alert--info"`; `core/static/core/css/app.css:216`, `background: var(--primary-subtle)` |

Each entry is removed **in full, including its `:not()` chain**. Removing the five `:not()` exclusions
from the question entry is what makes all seven question types one width; removing the
`:not(:has(> .callout__children))` from the callout entry is what makes both callout shapes one width.

### In — prose inside a tinted block, which stays readable

`.question__stem`, `.question__choices`, `.question__feedback`, each scoped identically to its
siblings (`html.unit-tree-collapsed [data-unit-shell] …`), capped at the same 46rem.

These exist because the user chose "the box widens, the prose inside does not." Without them a
question card would widen *and* stretch its stem and options to ~1066px, contradicting the rule for
callouts and worsening the readability the cap exists to protect.

`.callout__body` needs **no** entry: `templates/courses/elements/calloutelement.html:7` renders it as
`<div class="el el--text callout__body">`, and `.el--text` remains on the list. Adding a
`.callout__body` selector would be a no-op — a fact the existing test at
`courses/tests/test_callout_nesting_css.py:25` already records in a comment.

### Entries that stay (all transparent — no background of their own)

`.el--text`; `.lesson-unit__head` (`:824`); `.lesson-unit__title`; `.unit-crumbs` (`:849`);
`.quiz-finish` (`:322`, `border-top` only); and the five gate wrappers `.markdone`, `.fillgate`
(`app.css:1031`), `.stepper`, `.switchgate` (`app.css:1103`), `.guessnumber` (`app.css:1558`) — each
of which declares margin only. None paints a background, so none is in scope.

### Entry count

13 out, 3 removed, 3 added → **13**. `tests/test_consumption_css.py:212` asserts
`examined >= 17` (4 structural selectors + one per allow-list entry) and its comment instructs
re-derivation "only on a removal." The count is unchanged, so that assertion stays satisfied without
edit. **If implementation changes the count** (for example by adding a `:not(.el--dragfill)` carve-out
that splits an entry), re-derive the number and update the comment alongside it.

## Data flow

There is no runtime data flow; the flow is the CSS cascade resolving a used width. For a given
element on the student unit page:

1. Is `html.unit-tree-collapsed` set? Set pre-paint by `base.html` from a global localStorage key.
   If not → no cap, element fills the column. **Unchanged by this work.**
2. Is the viewport ≥641px and the medium `screen`? If not → no cap. **Unchanged.**
3. Is the element inside `[data-unit-shell]`? Scoping that keeps the rule off the teacher review page,
   which reuses the `.unit-shell` class but is not the student shell. **Unchanged.**
4. Does the element match one of the thirteen allow-list selectors? **This is the only step this
   change touches.** After the change: tinted block roots do not match (fill the column); prose
   containers do match (46rem), including prose nested inside a tinted block.

Because prose containers are matched by **descendant** selectors, a `.el--text` or `.question__stem`
nested at any depth still caps — which is precisely what makes "prose caps wherever it lives" true
without per-container entries.

## Error handling

CSS has no error path; the failure modes are silent mis-rendering. Three are identified, and each has
a required response rather than an assumption.

### R1 — drag-fill nests its widget inside the stem (the one real risk)

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
Two failure modes point in opposite directions, so guessing picks the wrong fix half the time:

- the pool wraps into more rows inside 736px — visually acceptable, no carve-out needed; or
- the `<fieldset>`'s default `min-inline-size: min-content` refuses to shrink, so `max-width` silently
  does not bind and the stem stays wide — the trap recorded in `fieldset-min-inline-size-defeats-scroll`
  (a `max-width` on a `fieldset` loses to its `min-inline-size` floor when a child has a large
  min-content contribution).

**Required response:** measure a drag-fill question at 1280×900 in the collapsed state, in the
worktree, and **record the measured numbers in the plan**. Add `:not(.el--dragfill)` to the
`.question__stem` entry **only if** measurement shows harm. If the carve-out is added, re-derive the
entry count for `tests/test_consumption_css.py:212`.

### R2 — the change is invisible in the expanded state

Every selector edited lives under `html.unit-tree-collapsed`, so an implementation that accidentally
lifts a rule out of that block would change the expanded state without any of the new tests noticing —
they all run collapsed. `tests/test_consumption_css.py:148-215` is the existing guard: it asserts
**per individual selector** that every `html.unit-tree-collapsed` selector also carries
`[data-unit-shell]`. It must stay green, and it must not be weakened.

### R3 — a widened tinted box with short content

A text-only callout now paints tint across ~1066px while its body text stops at 736px, leaving
~330px of empty tint on the right. This is **accepted, not a defect** — the user chose it explicitly
over the alternative of letting text fill the box (~128 characters per line, past comfortable reading
length). It is recorded here so a later reviewer does not "fix" it.

## Testing

The repo convention applies without exception: **every new or changed assertion must be falsified
against a named mutant**, and a CSS claim needs an **A/B** — a measurement taken with the rule present
proves nothing on its own (`css-confirmation-needs-an-ab-not-a-measurement`).

### Tests that must change

1. **`courses/tests/test_callout_nesting_css.py:22`**,
   `test_prose_cap_no_longer_applies_to_a_callout_with_children`. Its first assertion — that
   `.callout:not(:has(> .callout__children))` **exists** in the CSS — inverts: after this change the
   cap block must contain **no `.callout` selector in any form**. Its second assertion (no bare
   `.callout,` under `unit-tree-collapsed`) stays true and stays in place. Rename the test to match
   its new claim.

2. **`tests/test_e2e_callout_container.py:147-150`**,
   `test_a_table_in_a_callout_is_not_squeezed_by_the_prose_cap`. It currently asserts a prose-only
   callout measures 736px. Rewrite it to assert the prose-only callout's width **equals** the
   container callout's width. This is the test that proves the user-visible fix, so it must **compare
   the two boxes**, never assert a constant — a constant would pass on a build where both boxes are
   wrong in the same direction, and would need editing every time the shell geometry moves.

### Tests to add

3. **Card-width agreement (e2e):** a plain question card and a `choicegrid` card have equal width; a
   callout and a question card have equal width. Seed all four shapes on one unit so a single page
   load measures them, and compare pairwise.

4. **Prose-inside-a-box (e2e):** `.callout__body` and `.question__stem` still measure ~736px *inside*
   their widened boxes, and are strictly narrower than their own box. Without this, the "prose stays
   readable" half of the design can ship silently broken while test 3 passes.

5. **Drag-fill (e2e or measurement, per R1):** whichever way R1 resolves, the resolution must be
   pinned by a test, and the measured numbers recorded in the plan.

### Falsification

Each test above must be shown RED against a specific mutant, named in the plan. Suggested mutants,
one per test — the plan should confirm or replace them, and must run them rather than merely cite
them (`falsify-tests-not-run-them`):

- test 1 → re-add `.callout:not(:has(> .callout__children))` to the block.
- test 2 → re-add the callout entry (both boxes diverge again).
- test 3 → re-add the `:not(.el--choicegrid)` exclusion.
- test 4 → delete the `.question__stem` entry (prose stretches to fill).

Note the trap from this file's own history: an assertion pinned to a bare class name can be satisfied
by `lesson_unit.html`'s inline pre-hide `<style>`, which emits `.callout__children` as a literal in
the page `<head>`. Source-scan assertions must be pinned to the attribute form
(`'class="callout__children"'`), and CSS-block assertions must **extract the block before scanning**.

### Regression scope

- Non-e2e suite plus the e2e files touching callouts, questions, the unit shell, and consumption CSS.
- `tests/test_consumption_css.py` must stay green unmodified except for the entry-count comment, and
  only if R1 forces a count change.
- The teacher review page and quiz results page render none of these capped selectors inside
  `[data-unit-shell]`; confirm no e2e covering them changes.

### Visual verification

Screenshot the collapsed student unit page in **light and dark**, judged separately
(`verify-ui-with-screenshots`), showing a text-only callout, a container callout, a plain question
card and a grid question card together. The dark-mode judgement is what catches a tinted box whose
widened area reads as a different surface.

### Test-run mechanics

Start the test-DB container **before** any pytest run, or the suite looks hung for ~4m21s. Run
narrowly scoped; a whole-repo sweep is a branch gate, not a task step. Note that two other pipeline
worktrees exist on this machine — never run two pytest sessions at once, since they contend for the
same test database. A worktree has no `.env`, so database settings must be passed explicitly rather
than assumed.
