# Uniform width for background-bearing blocks on the student unit page

## What this fixes

On a student unit page with the course tree collapsed, a callout **with child elements** rendered
136px wider than a callout with **only text** — 872px against 736px. Students reading two worked
examples saw one box wider than the other with no meaning attached to the difference. The same split
already affected question cards: the five grid-ish types were exempt from the cap while plain
question types were not, so a quiz showed two card widths for the same reason.

Now every tinted element-root block renders at one width (the 872px column), and prose caps at 46rem
wherever it lives — including inside a widened box.

## The change

One CSS region: the prose-cap allow-list in `courses/static/courses/css/courses.css`, which
re-applies `max-width: 46rem` per element in the TOC-collapsed state. **Five selectors out, four in**
— 13 entries become 12. No template markup, no JavaScript, no Python.

**Out** (tinted element roots, which now fill the column): `.callout` (both shapes), `.el--question`
(all seven types), `[data-quiz-preview-notice]`.

**In** (prose and answer controls inside a card): `.question__stem`, `.question__choices`,
`.question__feedback`, `textarea.question__text-input`.

Sentinel comments (`/* prose-cap:begin|end */`) make the block machine-locatable so a source test can
assert its contents exactly — the previous guard could not catch a rule lifted out of the collapsed
scope.

## One judgement call beyond the literal request — easy to revert

`.quiz-finish` and `.lesson-unit__head` are **not** tinted, so by the letter of "blocks with a
background" they would have stayed capped at 736px. Both are chrome drawn *around* the question
cards: `.quiz-finish` is the separator rule under them, and `.lesson-unit__head` holds the
right-aligned "Mark as done" pill. Left capped, each would stop 136px short of the card edges it
frames — a separator that visibly ends early. They were moved out of the cap so their edges align.

**Side effect if kept:** `.lesson-unit__head .lesson-unit__title` is `flex: 1`, so widening the row
grows the title's measure from ~514px to ~644px and a long title re-wraps. It never exceeds its own
736px cap.

**To revert just this part**, five edits:

1. Re-add `html.unit-tree-collapsed [data-unit-shell] .quiz-finish,` and
   `html.unit-tree-collapsed [data-unit-shell] .lesson-unit__head,` to the prose-cap prelude.
2. Add both to `PROSE_CAP_SELECTORS` in `tests/test_consumption_css.py` (12 → 14 entries).
3. Change `assert len(prelude) == 12` to 14 in the same file.
4. Change `assert examined >= 16` to 18.
5. Drop the `.lesson-unit__head` arm from `test_every_tinted_block_and_its_chrome_is_one_width`, and
   move `.quiz-finish` / `[data-quiz-preview-notice]` back from the column-equality loops to
   `<= 736 + 2` in `tests/test_e2e_unit_nav.py`.

## Measured, not assumed

The one genuine unknown was whether capping `.question__stem` would break the two question types
that nest their widget **inside** a `<fieldset class="question__stem">` (fill-blank and drag-fill).
A `<fieldset>` defaults to `min-inline-size: min-content`, which can refuse a `max-width` outright.

Measured before planning, in a JS-enabled browser at 1280×900 collapsed, against a scratch build:

| Subject | width | scrollWidth | clientWidth | verdict |
|---|---|---|---|---|
| fill-blank stem | 736 | 736 | 736 | healthy |
| drag-fill stem | 736 | 736 | 736 | healthy |
| drag-fill `.dnd__pool` | 736 | 736 | 736 | wraps to 2 rows, no overflow |

Neither refused the cap and neither overflows, so no carve-out and no `min-inline-size` override
ships. The measurement synchronises on the drag-fill pool actually being live first — it ships
`hidden` and empty, and a pre-JS read returns zeros that would have satisfied "no overflow" and
fabricated a clean verdict.

## Accepted consequences

Four, all deliberate:

1. A text-only callout paints 136px of empty tint on its **right** (right only — capped elements are
   left-aligned, not centred).
2. A `.question__feedback-panel` renders at ≤736px inside an 872px card. The rule governs element
   **roots**; sub-element tints track their prose container.
3. The lesson title's measure grows ~130px and long titles re-wrap (see above).
4. The extended-response textarea renders at 736px rather than the card's inner ~830px. It has never
   been horizontally resizable — `app.css:150` is `textarea { resize: vertical }`.

## Tests

Six new e2e tests plus rewrites of the two existing tests this change turns red. Every assertion was
run RED against a named mutant before being accepted. Two are worth calling out:

- **The expanded-state test asserts computed style, not width.** The expanded column is 648px, *below*
  the 736px cap, so a rule that lost its `html.unit-tree-collapsed` prefix would change no measured
  width — a width-based test would have passed on its own mutant.
- **The title assertions in the three-item-head test are inert by construction** and documented as
  such. With `flex: 1` and a three-item row the title lands at ~644px whether or not it is capped, so
  a separate two-item-head test carries the real pin. Deleting the `.lesson-unit__title` entry
  confirms it: the three-item test passes, the two-item one fails.

Two stale rationale comments that this change falsifies are corrected and pinned by assertion: the
`input.question__text-input` comment (which claimed the textarea "fills the card column, resizable up
to it") and the `.callout__children` wrapper comment (which cited a `:has()` predicate this change
deletes).

## Spec and plan

- Spec: `docs/superpowers/specs/2026-08-11-uniform-tinted-block-width-design.md`
- Plan: `docs/superpowers/plans/2026-08-11-uniform-tinted-block-width.md`
