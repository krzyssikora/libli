# Uniform width for background-bearing blocks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the TOC-collapsed student unit view, make every tinted element-root block render at one
width (the 872px column) while prose stays capped at 46rem, so a callout with children is no longer
wider than a callout with only text.

**Architecture:** A single CSS allow-list in `courses/static/courses/css/courses.css` re-applies
`max-width: 46rem` per element in the collapsed state. Five selectors leave it (three tinted roots
plus two chrome rows that frame the cards) and four join it (the prose and answer controls inside a
card). Sentinel comments make the block machine-locatable so a source test can assert its exact
contents. No template markup, JavaScript or Python changes — only two rationale comments that the
change falsifies.

**Tech Stack:** Django 5.2, plain CSS (no preprocessor), pytest + pytest-django, Playwright e2e.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-11-uniform-tinted-block-width-design.md`. Read it before
  Task 1. Where this plan and the spec disagree, the spec wins — report the conflict rather than
  guessing.
- **R1 IS ALREADY MEASURED — both fieldset stems are B0.** Do **not** build a `:not()` carve-out, a
  `min-inline-size: 0` rule, or a `/* prose-cap-fieldset:* */` sentinel pair. Those branches are dead.
  The stem entry is exactly `.el--question .question__stem`.
- **Final shape is fixed:** the prelude is **12 selectors**; `examined` in `test_consumption_css.py`
  is **16**.
- **Measured geometry** (1280×900, collapsed): column **872px**, cap **736px**, card inner ~830px,
  `.lesson-unit__title` **643.6px**. Expanded column is **648px**.
- **Assertable constants:** only the tokens **736** (46rem) and **352** (22rem). Never assert 872,
  920, 648, 830 or 643.6 — read the column via `COLUMN_JS` or compare two elements.
- **Every new or changed assertion must be run RED against its named mutant.** Edit the mutant back
  out by hand; never `git checkout` the file (it would destroy the task's work).
- **Tooling:** `uv run pytest …` (pytest/ruff/python are not on PATH). e2e needs `-m e2e` or it
  silently deselects with **exit 5, which is not a pass**. Use `--verbosity=0`, never a second `-q`.
- **Test DB:** `libli-test-db` must be up (`docker compose -f docker-compose.test.yml up -d`) before
  any pytest run, or the suite looks hung for ~4m21s. The worktree needs a `.env` (copy from the main
  repo — it is gitignored). **Never run two pytest sessions at once**; two other pipeline worktrees
  exist on this machine and contend for the same database.
- **Commit after every task.** Do not squash tasks together.

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `courses/static/courses/css/courses.css` | the cap rule + sentinels + both rationale comments | 1, 3 |
| `tests/test_consumption_css.py` | source guard: exact 12-selector prelude, scoping, count floor | 1 |
| `courses/tests/test_callout_nesting_css.py` | source guard: no `.callout` in the cap block | 2 |
| `templates/courses/elements/calloutelement.html` | comment-only: strike the dead third reason | 3 |
| `tests/test_stale_rationale_comments.py` (new) | source guard: the two falsified comments are gone | 3 |
| `tests/test_e2e_uniform_block_width.py` (new) | behavioural pins for the whole change | 4-7 |
| `tests/test_e2e_unit_nav.py` | existing quiz-chrome test, rewritten | 8 |
| `tests/test_e2e_callout_container.py` | existing callout-cap test, rewritten | 9 |

---

### Task 1: The CSS change, pinned by an exact source assertion

**Files:**
- Modify: `courses/static/courses/css/courses.css:1062-1086`
- Test: `tests/test_consumption_css.py` (new assertion + five stale-count sites)

**Interfaces:**
- Produces: the sentinel markers `/* prose-cap:begin */` and `/* prose-cap:end */`. Task 2 re-slices
  on those two **strings**; it does not import anything from this file.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_consumption_css.py`, after
`test_collapsed_rail_rules_are_deleted_and_every_new_rule_is_scoped`:

```python
PROSE_CAP_SELECTORS = [
    "html.unit-tree-collapsed [data-unit-shell] .el--text",
    "html.unit-tree-collapsed [data-unit-shell] .el--question .question__stem",
    "html.unit-tree-collapsed [data-unit-shell] .question__choices",
    "html.unit-tree-collapsed [data-unit-shell] .question__feedback",
    "html.unit-tree-collapsed [data-unit-shell] textarea.question__text-input",
    "html.unit-tree-collapsed [data-unit-shell] .lesson-unit__title",
    "html.unit-tree-collapsed [data-unit-shell] .unit-crumbs",
    "html.unit-tree-collapsed [data-unit-shell] .markdone",
    "html.unit-tree-collapsed [data-unit-shell] .fillgate",
    "html.unit-tree-collapsed [data-unit-shell] .stepper",
    "html.unit-tree-collapsed [data-unit-shell] .switchgate",
    "html.unit-tree-collapsed [data-unit-shell] .guessnumber",
]


def _prose_cap_prelude():
    """The cap rule's selector list, sliced between the sentinels.

    FOUR steps, all mandatory, in this order:
      1. read UN-STRIPPED -- the sentinels are themselves comments;
      2. slice between them;
      3. strip comments from the slice;
      4. rsplit on the final '{' to get the prelude.
    Both sentinels sit INSIDE the @media block and wrap only the rule, so the
    slice never contains the at-rule prelude. Were the begin sentinel placed
    before `@media ... {`, step 4 would return the at-rule fused onto the first
    selector -- the trap documented at :186-190 of this file.
    """
    import re

    css = CSS.read_text(encoding="utf-8")
    start = css.index("/* prose-cap:begin */") + len("/* prose-cap:begin */")
    end = css.index("/* prose-cap:end */")
    sliced = re.sub(r"/\*.*?\*/", "", css[start:end], flags=re.S)
    prelude = sliced.rsplit("{", 1)[0]
    return [s.strip() for s in prelude.split(",") if s.strip()]


def test_prose_cap_prelude_is_exactly_the_expected_twelve_selectors():
    """The ONLY guard that catches a rule lifted out of the collapsed block.

    The per-selector scoping loop above cannot: it `continue`s on any selector
    LACKING html.unit-tree-collapsed, so a lifted rule is skipped, not caught.
    And the `examined` floor is `>=`, so a lift paired with two additions passes.
    Sorted comparison so a harmless reorder does not redden; separate length
    assertion so a DUPLICATED selector still does.
    """
    prelude = _prose_cap_prelude()
    assert len(prelude) == 12, f"expected 12 selectors, got {len(prelude)}: {prelude}"
    assert sorted(prelude) == sorted(PROSE_CAP_SELECTORS), (
        f"prose-cap prelude drifted.\n"
        f"  unexpected: {sorted(set(prelude) - set(PROSE_CAP_SELECTORS))}\n"
        f"  missing:    {sorted(set(PROSE_CAP_SELECTORS) - set(prelude))}"
    )
    for selector in prelude:
        assert "html.unit-tree-collapsed" in selector, selector
        assert "[data-unit-shell]" in selector, selector
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consumption_css.py::test_prose_cap_prelude_is_exactly_the_expected_twelve_selectors --verbosity=0`
Expected: FAIL with `ValueError: substring not found` (the sentinels do not exist yet).

- [ ] **Step 3: Write minimal implementation**

Replace `courses/static/courses/css/courses.css:1062-1086` (the rationale comment **and** the rule)
with exactly this:

```css
/* Prose cap. THE RULE: in the collapsed state, tinted element-root blocks fill the
   column; prose caps at 46rem wherever it lives, including inside a tinted block.
   46rem is the value in the shared `.quiz, .lesson` rule near the top of this file,
   reintroduced at element level in the collapsed state only.

   Still an allow-list, not cap-by-default: element root classes are heterogeneous,
   and a missed opt-out BREAKS layout (a squeezed table) whereas a missed entry only
   leaves prose wide. What changed is WHICH things are on it -- the tinted roots
   (callout, question card, the quiz preview alert) came OFF so they agree with each
   other, and the prose INSIDE a card went ON so widening the box does not stretch
   its text. `.quiz-finish` and `.lesson-unit__head` came off too: both are chrome
   drawn around the cards, and a separator that stops 136px short of the card edge
   reads as broken. `.lesson-unit__title` stays capped, so the heading keeps its
   measure while its row widens.

   `.callout__body` needs no entry -- it carries `.el--text`, already listed.
   Left alignment needs no declaration -- the global `* { margin: 0 }` leaves no auto
   margins to centre. `screen and` because printed output must not depend on a
   per-browser collapse preference.

   The sentinels below are load-bearing: tests/test_consumption_css.py slices between
   them to assert this prelude exactly. Keep them INSIDE the @media and wrapping only
   the rule -- moving the begin sentinel above `@media` fuses the at-rule onto the
   first selector when the slice is split on a brace. */
@media screen and (min-width: 641px) {
  /* prose-cap:begin */
  html.unit-tree-collapsed [data-unit-shell] .el--text,
  html.unit-tree-collapsed [data-unit-shell] .el--question .question__stem,
  html.unit-tree-collapsed [data-unit-shell] .question__choices,
  html.unit-tree-collapsed [data-unit-shell] .question__feedback,
  html.unit-tree-collapsed [data-unit-shell] textarea.question__text-input,
  html.unit-tree-collapsed [data-unit-shell] .lesson-unit__title,
  html.unit-tree-collapsed [data-unit-shell] .unit-crumbs,
  html.unit-tree-collapsed [data-unit-shell] .markdone,
  html.unit-tree-collapsed [data-unit-shell] .fillgate,
  html.unit-tree-collapsed [data-unit-shell] .stepper,
  html.unit-tree-collapsed [data-unit-shell] .switchgate,
  html.unit-tree-collapsed [data-unit-shell] .guessnumber {
    max-width: 46rem;
  }
  /* prose-cap:end */
}
```

Then fix the five stale sites in `tests/test_consumption_css.py`:

- `:158` — "none of the thirteen capped selectors" → "none of the twelve capped selectors"
- `:163-164` — replace the **count** phrasing, which later tasks would falsify, with a
  coverage-by-name phrasing: "Note the narrower claim: the e2e suite DOES give behavioural coverage
  that several of the twelve entries cap at 46rem (`.lesson-unit__title` in
  test_e2e_unit_nav.py, and `.el--text`, `.question__stem`, `.question__choices`,
  `.question__feedback` and `textarea.question__text-input` in test_e2e_uniform_block_width.py). Do
  not delete those assertions believing this test subsumes them" — naming the entries rather than a
  number, so the docstring cannot drift as tests are added.
- `:190` — "the entire thirteen-selector list" → "the entire twelve-selector list"
- `:208-211` — "one per allow-list entry (13) = 17" → "one per allow-list entry (12) = 16"
- `:212-213` — `assert examined >= 17` → `assert examined >= 16`, and the message
  "expected >= 17" → "expected >= 16"

**Record the spec's completeness enumeration here** (spec §"Completeness obligation" requires it be
recorded in the plan). Ten templates carry `.el--question`, all under
`templates/courses/elements/`: `choicegridquestionelement`, `choicequestion`,
`dragfillblankquestionelement`, `dragtoimagequestionelement`, `extendedresponsequestionelement`,
`fillblankquestionelement`, `matchpairquestionelement`, `multigridquestionelement`,
`shortnumericquestionelement`, `shorttextquestionelement`. Every block-box descendant, walking
through `.question__form` (an intentional pass-through that neither caps nor constrains):

| Descendant | Verdict |
|---|---|
| `.question__stem` (div form) | **capped** — new entry |
| `.question__stem` (fieldset form: `fillblank:17`, `dragfill:6`) | **capped** — measured B0, the cap binds |
| `.question__choices` | **capped** — new entry |
| `.question__feedback` | **capped** — new entry; also the *barrier* behind which `_question_feedback.html`, `_quiz_question_feedback.html` and the ten `_reveal_*.html` partials render, so none of those needs its own entry |
| `textarea.question__text-input` | **capped** — new entry |
| `input.question__text-input` | **capped elsewhere** at 22rem by `courses.css:319-320`; pinned by Task 6 |
| bare `<fieldset>` wrappers (`choicegrid:7`, `multigrid:7`, `matchpair:7`, `dragimage:7`) | pass-through, no width of their own |
| `.scroll-x` (choicegrid, multigrid) | **deliberately wide** — the grid must be able to exceed the prose measure |
| `.dragimage__stage` | **deliberately wide** |
| `.dnd__pool` in dragimage (`:23`) and matchpair (`:14`) | **deliberately wide** — these sit inside the *bare* fieldset, not inside the stem, so the barrier rule does not cover them; harmless because `courses.css:475` is `flex-wrap: wrap`, so widening changes only chip row count, never overflow |
| `<button type="submit">` | no entry needed — a button does not stretch to its container |

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_consumption_css.py --verbosity=0`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Falsify against three named mutants**

Run each, confirm RED, then **hand-edit the mutant back out** (never `git checkout`):

1. Delete `html.unit-tree-collapsed [data-unit-shell] .unit-crumbs,` from the CSS →
   expect FAIL on `expected 12 selectors, got 11`.
2. Duplicate `html.unit-tree-collapsed [data-unit-shell] .el--text,` →
   expect FAIL on the **length** assertion (`got 13`). The sorted comparison alone would pass, which
   is why the length check exists as a separate assertion.
3. Change `html.unit-tree-collapsed [data-unit-shell] .markdone` to
   `html.unit-tree-collapsed .markdone` → expect FAIL on the **sorted-list comparison**
   ("prose-cap prelude drifted"), which fires before the per-selector loop is reached. To falsify the
   `[data-unit-shell]` loop *specifically*, apply the same unscoping **and** edit the matching entry
   in `PROSE_CAP_SELECTORS`, so the list comparison passes and the loop is what reddens.

- [ ] **Step 6: Commit**

**Expected red after this task, repaired later — do not self-repair here.** This task deliberately
leaves three test files failing, because they assert the old behaviour:

| File | Assertion | Repaired by |
|---|---|---|
| `courses/tests/test_callout_nesting_css.py:29` | `".callout:not(:has(> .callout__children))" in css` | Task 2 |
| `tests/test_e2e_unit_nav.py:1379`, `:1398` | `w <= 736 + 2` for `.el--question` etc. | Task 8 |
| `tests/test_e2e_callout_container.py:148` | `abs(prose_box["width"] - 736) < 2` | Task 9 |

Run only `tests/test_consumption_css.py` for this task's gate. Do **not** run the full suite here and
do not attempt to fix the three files above — that is Tasks 2, 8 and 9.

```bash
git add courses/static/courses/css/courses.css tests/test_consumption_css.py
git commit -m "feat(courses): tinted blocks fill the column, prose caps at 46rem

Five selectors leave the collapsed-state prose cap (callout, question card,
the quiz preview alert, plus .quiz-finish and .lesson-unit__head, which frame
the cards) and four join it (.question__stem, .question__choices,
.question__feedback, textarea.question__text-input).

Sentinels make the block machine-locatable so the new source assertion can
pin the prelude at exactly 12 selectors; examined drops 17 -> 16.

Leaves test_callout_nesting_css, test_e2e_unit_nav and test_e2e_callout_container
red on purpose; they assert the old widths and are rewritten in the next commits."
```

---

### Task 2: Invert the callout source guard

**Files:**
- Modify: `courses/tests/test_callout_nesting_css.py:22-31`

**Interfaces:**
- Consumes: the sentinel strings `/* prose-cap:begin */` / `/* prose-cap:end */` from Task 1.

- [ ] **Step 1: Write the failing test**

Replace `test_prose_cap_no_longer_applies_to_a_callout_with_children` (`:22-31`) entirely:

```python
def test_prose_cap_no_longer_applies_to_any_callout():
    """Every callout fills the column now, not just one with children.

    Was: `.callout:not(:has(> .callout__children))` must EXIST. That predicate is
    gone -- a callout with children and a callout with only text were rendering at
    two different widths, which is what this change fixes.

    Token boundary is mandatory. A bare `".callout" in block` also matches
    `.callout__body` / `__children` / `__heading`, and adding `.callout__body` to the
    cap would be a legitimate no-op (it already carries .el--text) -- so the naive
    form would redden on correct code.

    Replaces the old second assertion rather than keeping it: that one was
    `\\.callout\\s*,`, which REQUIRED a trailing comma, so a `.callout` re-added as
    the LAST prelude selector (followed by `{`, not `,`) escaped it. This regex has
    no such hole.

    Slices between the sentinels because the file has many @media blocks and many
    html.unit-tree-collapsed rules, and line numbers move the moment the block is
    edited.
    """
    import re

    css = _courses_css()
    start = css.index("/* prose-cap:begin */") + len("/* prose-cap:begin */")
    end = css.index("/* prose-cap:end */")
    block = re.sub(r"/\*.*?\*/", "", css[start:end], flags=re.S)
    assert re.search(r"\.callout(?![\w-])", block) is None, (
        f"a .callout selector is back in the prose-cap block: {block!r}"
    )
```

- [ ] **Step 2: Run test to verify it fails — in the LAST position specifically**

The mutant must be genuinely last, or it proves nothing about the hole the old regex had. Two edits:

1. Change `  html.unit-tree-collapsed [data-unit-shell] .guessnumber {` to
   `  html.unit-tree-collapsed [data-unit-shell] .guessnumber,`
2. Add, on the following line: `  html.unit-tree-collapsed [data-unit-shell] .callout {`

Run: `uv run pytest courses/tests/test_callout_nesting_css.py::test_prose_cap_no_longer_applies_to_any_callout --verbosity=0`
Expected: FAIL — proving the assertion catches the last-position case the old `\.callout\s*,` regex
would have missed (there is no trailing comma after this `.callout`).

- [ ] **Step 3: Remove the mutant**

Hand-edit both lines back: restore `.guessnumber {` and delete the `.callout` line.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_callout_nesting_css.py --verbosity=0`
Expected: **3 passed** (this file has three test functions).

- [ ] **Step 5: Confirm the token boundary does NOT false-positive**

Add `html.unit-tree-collapsed [data-unit-shell] .callout__body,` to the prelude. Re-run this file.
Expected: **PASS** — `.callout__body` is a `.callout__*` name, not `.callout`. (It will redden Task
1's 12-selector assertion, which is correct.) Hand-edit the line back out and re-run both
`courses/tests/test_callout_nesting_css.py` and `tests/test_consumption_css.py` to confirm green.

- [ ] **Step 6: Commit**

```bash
git add courses/tests/test_callout_nesting_css.py
git commit -m "test(courses): assert no .callout selector survives in the prose cap

Inverts the old 'the :not(:has()) predicate must exist' assertion and folds in
the old trailing-comma regex, which a last-position .callout escaped. Uses a
token-boundary regex so .callout__body does not false-positive, and slices
between the sentinels so the guard survives the block moving."
```

---

### Task 3: Fix the two rationale comments this change falsifies

**Files:**
- Modify: `courses/static/courses/css/courses.css:315-318`
- Modify: `templates/courses/elements/calloutelement.html:11-20`
- Create: `tests/test_stale_rationale_comments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stale_rationale_comments.py`:

```python
"""Two rationale comments make claims this change falsifies.

This repo treats such prose as load-bearing (a wrong comment sends the next
reader down a dead path), so each gets an assertion rather than a promise.
"""

from pathlib import Path

# Anchored on __file__, matching tests/test_consumption_css.py:3 -- a cwd-relative
# path would silently depend on pytest being invoked from the repo root.
ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses" / "static" / "courses" / "css" / "courses.css"
CALLOUT = ROOT / "templates" / "courses" / "elements" / "calloutelement.html"


def test_text_input_comment_no_longer_claims_the_textarea_fills_the_card():
    """`textarea.question__text-input` is now capped at 46rem in the collapsed
    shell, so 'fills the card column, resizable up to it' is false on the surface
    it describes. (It was already misleading: app.css:150 is
    `textarea { resize: vertical }`, so it has never been draggable sideways.)

    Asserts on `app.css:150`, NOT on the string `resize: vertical` -- that string
    already occurs at courses.css:633 in an unrelated rule, so an assertion on it
    would pass on the unmodified file and pin nothing.
    """
    css = CSS.read_text(encoding="utf-8")
    assert "resizable up to it" not in css
    assert "app.css:150" in css, (
        "the amended comment must cite the rule that actually constrains the "
        "textarea, so the next reader does not re-derive it"
    )


def test_callout_children_comment_no_longer_cites_the_prose_cap_predicate():
    """The wrapper's third stated reason was being the subject of a :has()
    prose-cap predicate. This change deletes the only such predicate in the
    codebase, so a reader finding three reasons and only two mechanisms could
    wrongly conclude the wrapper is removable.
    """
    html = CALLOUT.read_text(encoding="utf-8")
    assert ":has(> .callout__children)" not in html
    assert "scopeOf" in html, "the two surviving reasons must remain documented"
    assert ".callout__body + .callout__children" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stale_rationale_comments.py --verbosity=0`
Expected: FAIL on both — `"resizable up to it"` is still present (and `app.css:150` is not), and
`":has(> .callout__children)"` is still present.

- [ ] **Step 3: Write minimal implementation**

Replace `courses/static/courses/css/courses.css:315-318` (the comment only; leave `:319-320`'s rule
untouched):

```css
/* A short-text / numeric answer never needs the full column width. Scoped to
   `input` so it caps only the single-line short-text/short-numeric answers. The
   extended-response `textarea` (same class) keeps app.css's width:100%, but is
   itself capped at 46rem in the collapsed shell by the prose-cap block below, so
   it no longer fills the card column. Growth is vertical only regardless --
   app.css:150 is `textarea { resize: vertical }`, which overrides the browser
   default `resize: both` precisely so a full-width textarea cannot be dragged
   past its container. */
```

In `templates/courses/elements/calloutelement.html`, change:

```
    One wrapper, for three reasons of its own (NOT the #212 continuous-rule
    argument, which is about .spoiler__children's 2px left rule -- this wrapper
    carries no rule): it is the node reveal.js `scopeOf` resolves to, the anchor for
    `.callout__body + .callout__children`, and the subject of the
    `:has(> .callout__children)` predicate the prose-cap narrowing keys on.
```

to:

```
    One wrapper, for two reasons of its own (NOT the #212 continuous-rule
    argument, which is about .spoiler__children's 2px left rule -- this wrapper
    carries no rule): it is the node reveal.js `scopeOf` resolves to, and the anchor
    for `.callout__body + .callout__children`. (A third reason once lived here -- a
    prose-cap predicate keyed on this wrapper -- but it was removed when all
    callouts were made one width. Do not go looking for it.)
```

**The replacement must not spell the predicate literally.** The test forbids the exact substring
`:has(> .callout__children)`, so paraphrase it as above rather than quoting it.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stale_rationale_comments.py --verbosity=0`
Expected: PASS (2 tests).

- [ ] **Step 5: Falsify both assertions**

1. Revert the CSS comment's final sentence so `app.css:150` disappears → expect FAIL on the first
   test. Restore.
2. Re-add the literal `:has(> .callout__children)` to the template comment → expect FAIL on the
   second test. Restore.

Then run `uv run pytest courses/tests/test_callout_nesting_css.py tests/test_consumption_css.py --verbosity=0`
— comment text can break regex-based source scans, and this confirms it did not.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css templates/courses/elements/calloutelement.html tests/test_stale_rationale_comments.py
git commit -m "docs(courses): correct the two rationale comments this change falsifies

The text-input comment claimed the textarea 'fills the card column, resizable
up to it' -- now capped, and never horizontally resizable in the first place.
The callout-children comment cited a :has() predicate this change deletes."
```

---

### Task 4: e2e — every tinted box, and the chrome, is one width

**Files:**
- Create: `tests/test_e2e_uniform_block_width.py`

**Interfaces:**
- Produces: `_make_pa_user`, `_login`, `_lesson_url`, `_seed_unit`, `COLUMN_JS`, `BOX_JS`,
  `_collapsed`, consumed by Tasks 5-7.

- [ ] **Step 1: Write the failing test**

Create `tests/test_e2e_uniform_block_width.py`:

```python
"""The user-visible pin for this change: a callout with children and a callout
with only text must be the same width, and so must every question card.

MANDATORY as e2e, not a render test: the server emits no computed style, and a
cascade defect leaves the HTML byte-identical.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD  # noqa: F401 -- used by the copied _login
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_verified_user  # noqa: F401 -- used by _make_pa_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Copied VERBATIM from tests/test_e2e_callout_container.py (same PA-user helper,
# same login-form drive), which copied them from tests/test_e2e_depth3.py.
def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _seed_unit(username):
    user = _make_pa_user(username)
    course = CourseFactory(owner=user)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return user, course, unit


# The article is `.lesson` on a lesson page and `.quiz` on a quiz page, and
# getBoundingClientRect() returns the BORDER box -- reading the article's own box
# gives 920, not the 872 its children see. Hence clientWidth minus padding.
COLUMN_JS = """() => {
  const a = document.querySelector('.quiz, .lesson');
  const s = getComputedStyle(a);
  return a.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight);
}"""

# Takes the selector as an ARGUMENT rather than interpolating it into the source:
# an f-string carrying JS braces has to double every one of them, and a single
# missed pair is a SyntaxError at evaluate() time, not a failed assertion.
BOX_JS = """(sel) => {
  const e = document.querySelector(sel);
  if (!e) return null;
  return {w: e.getBoundingClientRect().width,
          c: e.clientWidth, s: e.scrollWidth};
}"""


def _width(page, sel):
    box = page.evaluate(BOX_JS, sel)
    assert box is not None, f"{sel} is not present on the page"
    return box["w"]


def _collapsed(page, live_server, unit):
    """Seed the collapsed state BEFORE first paint, then PROVE it took.

    The class is set by the TOC-pin JS from localStorage, never by the server.
    The explicit class assertion is not decoration: expanded, the column is 648px
    and every capped element also measures 648, so a pure equality test would pass
    in the wrong state.
    """
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_init_script("localStorage.setItem('libli_unit_tree_collapsed', '1');")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("html.unit-tree-collapsed")
    assert page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "not in the collapsed state; every width assertion below would be vacuous"


@pytest.mark.django_db(transaction=True)
def test_every_tinted_block_and_its_chrome_is_one_width(page, live_server):
    from courses.models import CalloutElement
    from courses.models import ChoiceGridQuestionElement
    from courses.models import Element
    from courses.models import ShortTextQuestionElement
    from courses.models import TableElement

    user, _course, unit = _seed_unit("pa_uniform")

    prose = CalloutElement.objects.create(kind="note", body="<p>prose only</p>")
    add_element(unit, prose)
    wide = CalloutElement.objects.create(kind="example", body="<p>with a table</p>")
    wide_join = add_element(unit, wide)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "A"}, {"html": "B"}]]}
        ),
        parent=wide_join,
        tab_id=CalloutElement.SLOT_ID,
    )
    # A question element makes has_stateful_elements true, so .lesson-unit__reset
    # renders and the head is the THREE-item row the title assertion assumes.
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7"),
    )
    add_element(unit, ChoiceGridQuestionElement.objects.create(stem="Grid?"))

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    column = page.evaluate(COLUMN_JS)
    for sel in (
        ".callout:not(:has(> .callout__children))",
        ".callout:has(> .callout__children)",
        ".el--question:not(.el--choicegrid)",
        ".el--choicegrid",
        # Chrome that frames the cards. This is the one entry the spec flags as a
        # judgement call beyond the literal request, and the ONLY test that covers
        # it -- the quiz page has no .lesson-unit__head at all, and
        # test_e2e_unit_head_layout.py never collapses the TOC, so neither reaches it.
        ".lesson-unit__head",
    ):
        w = _width(page, sel)
        # Compared against the READ column, never a hard-coded 872: the derived
        # geometry moves whenever .app-main, the pin lane or the article padding does.
        assert abs(w - column) < 2, (
            f"{sel} is {w}, column is {column}; it must fill the column"
        )

    # The defect exactly as the user reported it.
    prose_w = _width(page, ".callout:not(:has(> .callout__children))")
    wide_w = _width(page, ".callout:has(> .callout__children)")
    assert abs(prose_w - wide_w) < 2, (
        f"the two callout shapes still differ: {prose_w} vs {wide_w}"
    )

    # The title stays capped while its row widens -- but it is a flex:1 child of a
    # THREE-item row, so it lands well under its own 736 cap (measured 643.6).
    # Directional, never abs(w - 736): a 736 assertion fails on correct code.
    title_w = _width(page, ".lesson-unit__title")
    assert title_w < 738, f"the title must stay within the prose cap, got {title_w}"
    assert title_w < column - 50, (
        f"the title must not fill the widened head: {title_w} vs column {column}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Mutant: hand-add `html.unit-tree-collapsed [data-unit-shell] .callout:not(:has(> .callout__children)),`
back into the prose-cap prelude.

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: FAIL — the prose-only callout measures 736 against a column of 872.

- [ ] **Step 3: Remove the mutant, then falsify the other two arms**

Hand-edit that selector out. Then, one at a time (restoring between each):

1. Re-add the **whole** old question entry
   `html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill),`
   → expect FAIL on `.el--question:not(.el--choicegrid)` (capped at 736 while `.el--choicegrid` stays
   at the column).
2. Re-add `html.unit-tree-collapsed [data-unit-shell] .lesson-unit__head,`
   → expect FAIL on the `.lesson-unit__head` arm.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS. Confirm the run reports `1 passed`, **not** `no tests ran` (exit 5 means `-m e2e` was
dropped and nothing was checked).

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin that every tinted block and its chrome is one width

The defect as reported: a callout with children was 136px wider than a callout
with only text. Also covers .lesson-unit__head, the judgement-call entry no
other test can reach -- the quiz page has none and the head-layout e2e never
collapses the TOC. Compares against the READ column, never a hard-coded 872."
```

---

### Task 5: e2e — prose inside a widened box stays at 46rem

**Files:**
- Modify: `tests/test_e2e_uniform_block_width.py`

**Interfaces:**
- Consumes: `_seed_unit`, `_login`, `_collapsed`, `_width`, `COLUMN_JS` from Task 4.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_e2e_uniform_block_width.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_prose_inside_a_widened_box_stays_capped(page, live_server):
    """The other half of the design: the BOX widens, its PROSE does not.

    All five newly-capped containers are measured here. Asserts the 736 token, not
    `narrower than its own box`: both containers have padding, so a child is ALWAYS
    strictly narrower than its parent's border box, cap or no cap -- that assertion
    cannot fail and would read as a pin while proving nothing.

    Fixture and locator requirements, each load-bearing:
      - the container callout carries a non-empty body, because calloutelement.html
        renders .callout__body under `{% if el.body %}` -- a children-only callout
        has no body element and the locator would resolve to nothing;
      - the short-text card is located STRUCTURALLY. There is no `.el--shorttext`
        class: shorttextquestionelement.html emits a bare
        `<div class="el el--question" data-question>`, and only the five grid-ish
        types plus fillblank carry a type modifier. Scoping on the input is what
        makes the locator resolve;
      - the short-text question is ANSWERED below. Its .question__feedback div is
        NOT :empty (the `{% if %}` sits on its own line, leaving a whitespace text
        node), so it renders as a zero-height box with a real width -- one
        whitespace edit away from courses.css:158
        `.el--question .question__feedback:empty { display: none }`. Driving an
        answer means the arm measures a box with actual content rather than that
        whitespace shell, and the width is read via getBoundingClientRect (BOX_JS)
        rather than bounding_box(), which is unreliable on a zero-height element.

    The Choice rows are realistic content, not a width requirement: courses.css:143
    makes .question__choices a block <ul> with no width rule, so it fills its
    container with or without <li> children.
    """
    from courses.models import CalloutElement
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import ShortTextQuestionElement
    from courses.models import TableElement

    user, _course, unit = _seed_unit("pa_prose")

    body = CalloutElement.objects.create(kind="note", body="<p>explanatory text</p>")
    body_join = add_element(unit, body)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "A"}, {"html": "B"}]]}
        ),
        parent=body_join,
        tab_id=CalloutElement.SLOT_ID,
    )
    add_element(
        unit,
        ExtendedResponseQuestionElement.objects.create(stem="<p>Explain briefly.</p>"),
    )
    mcq = ChoiceQuestionElement.objects.create(stem="<p>Pick one.</p>")
    Choice.objects.create(question=mcq, text="The first option", is_correct=True)
    Choice.objects.create(question=mcq, text="The second option", is_correct=False)
    add_element(unit, mcq)
    st = ShortTextQuestionElement.objects.create(
        stem="<p>Name a prime.</p>", accepted="7"
    )
    add_element(unit, st)

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    # Drive a real answer so the feedback slot carries content. The short-text
    # card has no type modifier class, so scope it on the input it is the only
    # bearer of.
    ST = "[data-question]:has(input.question__text-input)"
    st_card = page.locator(ST)
    st_card.locator("input.question__text-input").fill("11")
    st_card.locator("button[type='submit']").click()
    page.wait_for_function(
        "(sel) => { const f = document.querySelector(sel + ' .question__feedback');"
        " return f && f.textContent.trim().length > 0; }",
        ST,
    )

    column = page.evaluate(COLUMN_JS)
    for sel in (
        ".callout__body",
        ".el--question .question__stem",
        ".question__choices",
        f"{ST} .question__feedback",
        "textarea.question__text-input",
    ):
        w = _width(page, sel)
        assert abs(w - 736) < 2, f"{sel} must stay capped at 46rem, got {w}"
        assert w < column - 50, (
            f"{sel} is {w} against a column of {column} -- the cap is not binding"
        )
```

- [ ] **Step 2: Falsify each arm independently**

Five mutants, each deleting **one** entry from the prelude. Run after each, confirm the named arm
reddens, then hand-edit the entry back before the next. A single mutant reddening the whole test
would leave the other four unproven.

| Delete from the prelude | Expected failing arm |
|---|---|
| `… .el--text,` | `.callout__body` (capped only via `.el--text` — this is the arm proving the body kept its cap when `.callout` left the list) |
| `… .el--question .question__stem,` | `.el--question .question__stem` |
| `… .question__choices,` | `.question__choices` |
| `… .question__feedback,` | the `{ST} .question__feedback` arm |
| `… textarea.question__text-input,` | `textarea.question__text-input` |

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS (2 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin that prose inside a widened tinted box stays at 46rem

All five newly-capped containers, each falsified against its own delete-one-entry
mutant. The feedback arm drives a real answer first -- .question__feedback is
:empty and display:none on a plain load, so it would otherwise be unmeasurable."
```

---

### Task 6: e2e — the expanded state is untouched, and short inputs keep 22rem

**Files:**
- Modify: `tests/test_e2e_uniform_block_width.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
@pytest.mark.django_db(transaction=True)
def test_expanded_state_has_no_cap_at_all(page, live_server):
    """The Non-goal, pinned by COMPUTED STYLE rather than width.

    A width test here cannot fail: the expanded column is 648px, BELOW the 736px
    cap, so a rule that lost its html.unit-tree-collapsed prefix would change no
    measured width and the test would pass on its own mutant. maxWidth === 'none'
    is what the mutant actually reddens.
    """
    from courses.models import CalloutElement
    from courses.models import ChoiceGridQuestionElement
    from courses.models import ShortTextQuestionElement

    user, _course, unit = _seed_unit("pa_expanded")
    add_element(unit, CalloutElement.objects.create(kind="note", body="<p>t</p>"))
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7"),
    )
    # Both card shapes, per the spec. The grid card was never in the cap, so it is
    # the arm that would catch a NEW unscoped rule reaching a previously-uncapped
    # element -- a case the plain card cannot show.
    add_element(unit, ChoiceGridQuestionElement.objects.create(stem="Grid?"))

    page.set_viewport_size({"width": 1280, "height": 900})
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-unit-shell]")
    assert not page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "this test must run EXPANDED; collapsed it proves nothing"

    for sel in (".callout", ".el--question:not(.el--choicegrid)", ".el--choicegrid"):
        mw = page.evaluate(
            "(s) => getComputedStyle(document.querySelector(s)).maxWidth", sel
        )
        assert mw == "none", f"{sel} has max-width {mw} in the expanded state"


@pytest.mark.django_db(transaction=True)
def test_short_answer_input_still_caps_at_22rem(page, live_server):
    """Specificity guard. The new entry MUST be `textarea.question__text-input`.

    Written with a bare class it still out-specifies
    `.quiz input.question__text-input` (courses.css:319-320) on the class
    component, and the single-line short-text/short-numeric boxes would silently
    jump from 352px to 736px.

    The collapsed assertion inside _collapsed() is mandatory here: the 22rem rule
    is unscoped, so the input measures 352 in BOTH states and the mutant diverges
    only collapsed.
    """
    from courses.models import ShortTextQuestionElement

    user, _course, unit = _seed_unit("pa_input")
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7"),
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    w = _width(page, "input.question__text-input")
    assert abs(w - 352) < 2, f"the short-answer input must stay at 22rem, got {w}"
```

- [ ] **Step 2: Run tests to verify they fail**

Mutant A (expanded test): hand-add `[data-unit-shell] .callout { max-width: 46rem; }` **outside** any
collapsed scope, immediately after the prose-cap `@media` block.
Run: `uv run pytest tests/test_e2e_uniform_block_width.py::test_expanded_state_has_no_cap_at_all -m e2e --verbosity=0`
Expected: FAIL — `.callout` has max-width `736px` in the expanded state. Hand-edit it out.

Mutant B (input test): change `textarea.question__text-input` in the prelude to
`.question__text-input`.
Run: `uv run pytest tests/test_e2e_uniform_block_width.py::test_short_answer_input_still_caps_at_22rem -m e2e --verbosity=0`
Expected: FAIL — the input measures 736. Hand-edit `textarea` back on.

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS (4 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin the untouched expanded state and the 22rem short input

The expanded arm asserts computed style, not width: at 648px the column is
already under the 736px cap, so a width test would pass on its own mutant."
```

---

### Task 7: e2e — grid stems narrow, and both fieldset stems bind (B0)

**Files:**
- Modify: `tests/test_e2e_uniform_block_width.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
@pytest.mark.django_db(transaction=True)
def test_grid_and_fieldset_stems_cap_without_squeezing_their_widgets(page, live_server):
    """Two behaviour changes the Purpose section does not mention, pinned so they
    are intentional rather than incidental.

    1. The five grid types were excluded from the cap entirely, so their stems
       filled the card's inner box (~830). They now cap at 736.
    2. fillblank and dragfill put their widget INSIDE a `<fieldset class=
       "question__stem">`. A fieldset defaults to min-inline-size: min-content,
       which can refuse a max-width. MEASURED at spec time: it does not here --
       both stems bind at 736 and neither overflows (B0). This is the pin for
       that, so a future content or layout change that breaks it is caught.

    The choicegrid fixture MUST have a non-empty stem AND real columns/rows:
    choicegridquestionelement renders .question__stem under `{% if el.stem %}`, and
    render_choice_grid iterates el.columns/el.rows -- with neither seeded the table
    is an empty <thead><th></th></thead><tbody></tbody> and the widget-width
    assertion could not fail.
    """
    from courses.models import Blank
    from courses.models import ChoiceGridQuestionElement
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement
    from courses.models import FillBlankQuestionElement
    from courses.models import GridColumn
    from courses.models import GridRow

    user, _course, unit = _seed_unit("pa_stems")

    grid = ChoiceGridQuestionElement.objects.create(stem="Pick one per row.")
    cols = [
        GridColumn.objects.create(question=grid, label=label)
        for label in (
            "Strongly agree",
            "Agree",
            "Neither agree nor disagree",
            "Disagree",
            "Strongly disagree",
        )
    ]
    for statement in (
        "The first statement under consideration here",
        "The second statement under consideration here",
    ):
        GridRow.objects.create(
            question=grid, statement=statement, correct_column=cols[0]
        )
    add_element(unit, grid)

    gapped = (
        "The capital of France is ￿0￿, which stands on the "
        "￿1￿, and the capital of Italy is ￿2￿, which "
        "stands on the ￿3￿ river in central Europe."
    )
    fb = FillBlankQuestionElement.objects.create(stem=gapped)
    for i, ans in enumerate(("Paris", "Seine", "Rome", "Tiber")):
        Blank.objects.create(question=fb, order=i, accepted=ans)
    add_element(unit, fb)

    df = DragFillBlankQuestionElement.objects.create(
        stem=gapped, distractors="Madrid\nLisbon\nDanube\nVistula\nBerlin\nWarsaw"
    )
    for tok in ("Paris", "Seine", "Rome", "Tiber"):
        DragBlank.objects.create(question=df, correct_token=tok)
    add_element(unit, df)

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    # The pool ships `hidden` and EMPTY -- dnd.js reveals and fills it. Reading
    # before that returns clientWidth 0, which would satisfy "no overflow" and
    # fabricate a pass. Sync first, then assert it is genuinely live.
    page.wait_for_selector(".el--dragfill [data-dnd-pool]:not([hidden])")
    page.wait_for_function(
        "() => document.querySelectorAll('.el--dragfill .dnd__chip').length > 0"
    )
    pool = page.evaluate(BOX_JS, ".el--dragfill .dnd__pool")
    assert pool is not None and pool["c"] > 0, (
        f"INVALID: the pool is not live, the measurement is void: {pool}"
    )

    grid_stem = _width(page, ".el--choicegrid .question__stem")
    scroll_x = _width(page, ".el--choicegrid .scroll-x")
    assert abs(grid_stem - 736) < 2, f"grid stem must cap at 46rem, got {grid_stem}"
    # Directional. .scroll-x is the edge-shading wrapper (it does not itself scroll
    # -- the inner .choicegrid-scroll does) and the bare <fieldset> around it has no
    # min-inline-size: 0, so its width is not pinned to the card's inner box. A
    # generous constant here would be the fragility this suite bans.
    assert scroll_x > grid_stem + 2, (
        f"the grid widget must stay wider than the capped stem: "
        f"scroll-x {scroll_x} vs stem {grid_stem}"
    )

    for sel in (".el--fillblank .question__stem", ".el--dragfill .question__stem"):
        box = page.evaluate(BOX_JS, sel)
        assert box is not None, f"{sel} is not present"
        assert abs(box["w"] - 736) < 2, (
            f"{sel}: the fieldset min-inline-size floor refused the cap: {box}"
        )
        assert box["s"] <= box["c"] + 1, f"{sel} overflows horizontally: {box}"
```

- [ ] **Step 2: Run test to verify it fails**

Mutant: add `:not(.el--dragfill)` to the stem entry, making it
`html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--dragfill) .question__stem,`.

Run: `uv run pytest tests/test_e2e_uniform_block_width.py::test_grid_and_fieldset_stems_cap_without_squeezing_their_widgets -m e2e --verbosity=0`
Expected: FAIL — the drag-fill stem returns to the card's inner box (~830) instead of 736.

- [ ] **Step 3: Verify the grid arm can fail**

The `scroll_x > grid_stem + 2` assertion needs its own mutant, because the first one does not touch
it. **Do not try to falsify it by emptying the grid.** Two reasons that would not work:
`.scroll-x` is `position: relative` only (`app.css:1675`) with no width rule, so it is a plain block
div filling the bare `<fieldset>` (~830px) regardless of what the table contains — the inner
`.choicegrid-scroll` is the `overflow-x: auto` scroller (`courses.css:1373`), contributing no
min-content — so an empty grid still measures ~830 and the assertion still passes; and deleting the
`GridColumn` rows raises `IndexError` on `cols[0]` in the `GridRow` loop, which is a red that has
nothing to do with the assertion.

Use instead: temporarily delete `html.unit-tree-collapsed [data-unit-shell] .el--question
.question__stem,` from the prelude. `grid_stem` becomes ~830, so `scroll_x > grid_stem + 2` becomes
`830 > 832` and reddens (alongside the `abs(grid_stem - 736) < 2` half). Hand-edit it back.

The `GridColumn`/`GridRow` rows stay in the fixture as realistic content — a five-column grid is what
this widget looks like in use — but they are not what makes the assertion falsifiable.

- [ ] **Step 4: Remove the mutant and re-run**

Hand-edit the `:not(.el--dragfill)` back out.
Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin grid stems narrowing and both fieldset stems binding

Records the measured B0 outcome: the fieldset min-inline-size floor does not
refuse the 46rem cap on fillblank or dragfill, and neither overflows. Seeds a
real 5-column grid so the widget-width arm can actually fail, and syncs on the
dnd pool being live -- it ships hidden and empty, and a pre-JS read returns
zeros that would satisfy 'no overflow' and fabricate a pass."
```

---

### Task 8: Rewrite the quiz-chrome test

**Files:**
- Modify: `tests/test_e2e_unit_nav.py:1339-1400`

- [ ] **Step 1: Confirm the existing test is red**

Run: `uv run pytest tests/test_e2e_unit_nav.py::test_quiz_chrome_is_capped_across_both_page_states -m e2e --verbosity=0`
Expected: FAIL on `[data-quiz-preview-notice] must cap at 736px, got 872.0` — Load A's loop is
`(".lesson-unit__title", "[data-quiz-preview-notice]", ".el--question")` and the notice is the first
of the three to leave the cap. This confirms the test was really pinning the old behaviour.

- [ ] **Step 2: Apply the rewrite**

Rename the test to `test_quiz_chrome_tracks_the_column_across_both_page_states`.

Replace `:1375-1379` with:

```python
    column = page.evaluate(
        "() => { const a = document.querySelector('.quiz, .lesson');"
        " const s = getComputedStyle(a);"
        " return a.clientWidth - parseFloat(s.paddingLeft)"
        " - parseFloat(s.paddingRight); }"
    )
    title_w = page.evaluate(
        "() => document.querySelector('.lesson-unit__title')"
        ".getBoundingClientRect().width"
    )
    assert title_w <= 736 + 2, (
        f".lesson-unit__title must cap at 736px, got {title_w:.1f}"
    )
    for sel in ("[data-quiz-preview-notice]", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert abs(w - column) < 2, f"{sel} must fill the column {column}, got {w:.1f}"
```

Replace `:1394-1398` with the same block, swapping the loop tuple to
`(".quiz-finish", ".el--question")`.

Replace the comment at `:1384-1388` with:

```python
    # Re-assert the collapsed state AFTER the reload. This is now MORE important,
    # not less: the title assertion is still one-sided (<= 738), the EXPANDED quiz
    # column at 1440 is 648px -- under 738 -- and the column-equality assertions
    # compare against whatever column is actually rendered, so they hold expanded
    # too. Without this guard every assertion below passes in the wrong state.
    # Load A is safe because _collapse() waits on the class.
```

Replace the docstring's first paragraph (`:1339-1341`) with:

```python
    """The quiz entries (.lesson-unit__title, [data-quiz-preview-notice],
    .quiz-finish) exist only for _quiz_article.html; without this the whole suite
    stays green if all three are deleted. The .count() assertions carry that; the
    width assertions carry which of them cap and which fill the column.
```

Keep every `locator(...).count()` assertion untouched — the docstring states they are the only thing
stopping a silent deletion.

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states -m e2e --verbosity=0`
Expected: PASS.

- [ ] **Step 4: Falsify — widths and the state guard**

1. Re-add `html.unit-tree-collapsed [data-unit-shell] [data-quiz-preview-notice],` and
   `html.unit-tree-collapsed [data-unit-shell] .quiz-finish,` to the prelude → expect FAIL on both
   column-equality assertions. Hand-edit out.
2. Comment out **only** `_collapse(page)` in Load A, leaving the `wait_for_function` guard in place
   → expect FAIL (the guard times out waiting for a class the page never gets). Restore it.

   **Do not also delete the guard.** With both gone the page renders expanded, the column reads 648,
   `title_w` = 648 satisfies `<= 736 + 2`, and both `abs(w - column) < 2` arms compare 648 against a
   648 reading — the mutated run goes **green**. That is exactly what this task's own re-derived
   comment says ("the column-equality assertions compare against whatever column is actually
   rendered, so they hold expanded too"), and it is why the guard is a `wait_for_function` rather
   than a width assertion: no width assertion here can detect the wrong state.

- [ ] **Step 5: Run the whole file**

Run: `uv run pytest tests/test_e2e_unit_nav.py -m e2e --verbosity=0`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_unit_nav.py
git commit -m "test(e2e): quiz chrome now tracks the column, title still caps

.el--question, [data-quiz-preview-notice] and .quiz-finish left the prose cap,
so all four <= 736 assertions inverted to column-equality. The title keeps its
one-sided assertion; the collapsed-state guard is retained and re-argued."
```

---

### Task 9: Rewrite the callout-cap e2e and its stale docstring

**Files:**
- Modify: `tests/test_e2e_callout_container.py:110-156`

- [ ] **Step 1: Confirm the existing test is red**

Run: `uv run pytest tests/test_e2e_callout_container.py::test_a_table_in_a_callout_is_not_squeezed_by_the_prose_cap -m e2e --verbosity=0`
Expected: FAIL on the control arm `abs(prose_box["width"] - 736) < 2` — the prose-only callout now
measures 872.

- [ ] **Step 2: Apply the rewrite**

Rename to `test_both_callout_shapes_render_at_one_width`.

**Both** docstring paragraphs need rewriting, not just the second.

Replace the FIRST paragraph (`:112-115`, "Without seeding it, both arms measure the uncapped state
and the assertion is vacuous") — that sentence justified the *old* assertion (`prose == 736`
exactly). The rewritten pair is `equal AND both > 736`, which in the un-seeded expanded state
measures 648/648 and **fails** rather than passing vacuously, so the stale text now says the opposite
of how the test behaves:

```
    The cap is `html.unit-tree-collapsed [data-unit-shell] ...` under
    `@media screen and (min-width: 641px)`, and that class is set by the TOC-pin JS
    from localStorage -- NEVER by the server. Without seeding it the page renders
    expanded, both arms measure 648px, and the `> 736` half REDDENS -- so the seed
    is what makes this test meaningful, not merely non-vacuous.
```

Then replace the second paragraph — **lines 117-119 only**; line 120 is the closing `"""` and must be
left in place — with:

```
    641px is NOT enough either: the collapsed content box is .app-main's 960px cap,
    less its 2x20px padding, less the 2.4rem pin lane and the 3rem .lesson padding
    -- 872px at any viewport >= 1040px, and far less at 641px, which would put both
    arms under the 736px cap and make the comparison vacuous. Use 1280x900.
    (.unit-shell's max-width: 72rem never binds: .app-main caps the containing
    block first.)
```

Replace the two measurement arms (`:146-155` — `:156` is the blank separator before the next test and
must be left alone, or `ruff format` will flag the missing line) with:

```python
    prose_w = page.locator(".callout:not(:has(> .callout__children))").bounding_box()[
        "width"
    ]
    wide_w = page.locator(".callout:has(> .callout__children)").bounding_box()["width"]
    # BOTH halves are required. Equality alone passes when both callouts are capped
    # at 736 -- the squeezed-table regression this test exists to prevent -- and
    # `> 736` alone passes when they are both uncapped but unequal.
    assert abs(prose_w - wide_w) < 2, (
        f"the two callout shapes must render at one width: prose {prose_w}, "
        f"with-children {wide_w}"
    )
    assert prose_w > 736 and wide_w > 736, (
        f"both callouts must exceed the old 46rem cap: {prose_w}, {wide_w}"
    )
```

- [ ] **Step 3: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_callout_container.py -m e2e --verbosity=0`
Expected: PASS (all tests in the file).

- [ ] **Step 4: Falsify BOTH halves independently**

1. Re-add `html.unit-tree-collapsed [data-unit-shell] .callout:not(:has(> .callout__children)),` →
   expect FAIL on the **equality** half (736 vs 872). Hand-edit out.
2. Add `html.unit-tree-collapsed [data-unit-shell] .callout,` (capping *both* shapes) → expect FAIL
   on the **`> 736`** half, with equality still passing. Hand-edit out.

Mutant 2 is the one proving this test would still catch the squeezed-table regression the old test
guarded.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_callout_container.py
git commit -m "test(e2e): both callout shapes render at one width

Was: assert the prose-only callout is exactly 736. Now: assert the two shapes
are equal AND both exceed 736, so neither direction of failure passes. Also
corrects the docstring's pre-.app-main column formula."
```

---

### Task 10: Regression sweep, visual verification, and the PR-body note

**Files:** none modified (verification only, plus a drafted PR-body paragraph)

- [ ] **Step 1: Run the affected non-e2e tests**

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest tests/test_consumption_css.py courses/tests/test_callout_nesting_css.py \
  tests/test_stale_rationale_comments.py tests/test_unit_nav_render.py --verbosity=0
```
Expected: all PASS.

- [ ] **Step 2: Run every e2e file this change touches**

```bash
uv run pytest tests/test_e2e_uniform_block_width.py tests/test_e2e_callout_container.py \
  tests/test_e2e_unit_nav.py tests/test_e2e_unit_head_layout.py \
  tests/test_e2e_scroll_affordance.py tests/test_e2e_questions_2b.py \
  tests/test_e2e_questions_2d.py tests/test_e2e_choice_inline_feedback.py \
  tests/test_e2e_choicegrid.py -m e2e --verbosity=0
```
Expected: all PASS. `test_e2e_unit_head_layout.py` is included because it exercises the same
`.lesson-unit__head` row — **note it runs EXPANDED** (it never seeds `libli_unit_tree_collapsed`), so
it is a no-regression check for the untouched state, **not** coverage of this change. Task 4 is what
covers the collapsed head.

If any run reports `no tests ran` / exit 5, `-m e2e` was dropped: that is **not** a pass. Re-run.

- [ ] **Step 3: Full branch gate**

```bash
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
uv run ruff check --no-cache .
uv run ruff format --check .
```
Expected: all PASS. Record the counts for the commit message. `ruff format --check` is a separate CI
gate from `ruff check` — both must pass. Use `--no-cache` on `ruff check`: a `# noqa` warning is
cached away, so a second run reports "All checks passed" on a file that has one.

- [ ] **Step 4: Screenshots, light and dark, judged separately**

Capture the collapsed student unit page at 1280×900 showing, on one unit: a text-only callout, a
container callout, a plain question card and a grid question card. Capture a quiz page showing the
`.quiz-finish` separator against the card edges. Capture a unit with a **long title and a stateful
element** so the three-item head renders and the title re-wrap is visible.

Judge dark mode **separately**, not as a recolour of the light shot — the specific risk is that a
widened tinted box reads as a different surface against the page.

- [ ] **Step 5: Confirm the four accepted consequences look right**

Against the screenshots, confirm each is acceptable rather than a defect:

1. A text-only callout paints 136px of empty tint on its right (right only — capped elements are
   left-aligned).
2. A `.question__feedback-panel` renders at ≤736 inside an 872 card (sub-element tints are out of
   scope by S1).
3. The lesson title's measure grows to ~644 and a long title re-wraps.
4. The extended-response textarea renders at 736, not the card's inner ~830.

If any reads as broken, **stop and report** rather than patching — each was an explicit design
decision, and reversing one is the user's call.

- [ ] **Step 6: Draft the PR-body note for the chrome decision**

The spec requires the chrome decision be called out so the user can reverse it cheaply. Write this
paragraph into the PR body at the pipeline's PR-opening step (or by hand, if opening the PR
manually):

> **One judgement call beyond the literal request.** `.quiz-finish` and `.lesson-unit__head` are not
> tinted, so by the letter of "blocks with a background" they would have stayed capped at 736px. Both
> are chrome drawn *around* the question cards: `.quiz-finish` is the separator rule under them, and
> `.lesson-unit__head` holds the right-aligned "Mark as done" pill. Left capped, each would stop
> 136px short of the card edges it frames. They were moved out of the cap so their edges align.
> **To revert just this part**, five edits — re-add
> `html.unit-tree-collapsed [data-unit-shell] .quiz-finish,` and
> `html.unit-tree-collapsed [data-unit-shell] .lesson-unit__head,` to the prose-cap prelude, then in
> `tests/test_consumption_css.py` add both to `PROSE_CAP_SELECTORS` (12 → 14 entries) and change
> `assert len(prelude) == 12` to 14 and `assert examined >= 16` to 18; drop the `.lesson-unit__head`
> arm from `test_every_tinted_block_and_its_chrome_is_one_width`; and move `.quiz-finish` and
> `[data-quiz-preview-notice]` back from the column-equality loops to `<= 736 + 2` in
> `test_e2e_unit_nav.py`.
> Side effect if kept: the lesson title's measure grows from ~514px to ~644px, so long titles re-wrap.

- [ ] **Step 7: Commit**

```bash
git commit --allow-empty -m "chore: verification sweep for uniform tinted block width

non-e2e: <N> passed. e2e: <N> passed. ruff check + format: clean.
Screenshots reviewed light and dark; the four accepted consequences confirmed
as intended, not defects. PR-body note drafted for the chrome decision."
```

---

## Self-Review

**1. Spec coverage.** The CSS change and R2's exact-list assertion → Task 1; spec test 1 → Task 2;
Architecture's two comment regions plus the `calloutelement.html` comment → Task 3; spec tests
5/6/7/8/9/10 → Tasks 4-7; spec test 3 → Task 8; spec test 2 → Task 9; regression scope, the five
stale sites in `test_consumption_css` (Task 1), the visual checklist and the PR-body callout →
Task 10. The spec's "record the enumeration in the plan" obligation is discharged in Task 1 Step 3.
The dead B1/B2 branches are excluded by the Global Constraints.

**2. Placeholder scan.** No TBDs. Every code step carries runnable code; every mutant is named with
its expected failure; every fixture whose emptiness would neuter an assertion (choicegrid rows,
callout body, choice options, rendered feedback) carries an explicit requirement and, where the risk
is highest, a step that proves the assertion can fail.

**3. Type consistency.** `_seed_unit`, `_login`, `_collapsed`, `_width`, `COLUMN_JS` and `BOX_JS` are
defined once in Task 4 and used with the same signatures in Tasks 5-7. `BOX_JS` returns
`{w, c, s}` and every consumer uses those three keys. The twelve selector strings in Task 1's
`PROSE_CAP_SELECTORS` are byte-identical to the twelve in the CSS block of the same task. Task 2
shares only the two sentinel *strings* with Task 1, which its Interfaces block now states explicitly.
