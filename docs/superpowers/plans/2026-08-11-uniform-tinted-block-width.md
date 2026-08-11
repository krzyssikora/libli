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
  920, 648, 830 or 643.6 — read the column via the recipe or compare two elements.
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
- Produces: the sentinel markers `/* prose-cap:begin */` and `/* prose-cap:end */`, and the helper
  `_prose_cap_prelude()` in `tests/test_consumption_css.py`, both consumed by Task 2.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_consumption_css.py` (after the existing
`test_collapsed_rail_rules_are_deleted_and_every_new_rule_is_scoped`):

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

Then fix the five stale-count sites in `tests/test_consumption_css.py`:

- `:158` — "none of the thirteen capped selectors" → "none of the twelve capped selectors"
- `:163-164` — "four of the thirteen entries" → "one of the twelve entries" (after this change only
  `.lesson-unit__title` of that original four is still capped)
- `:190` — "the entire thirteen-selector list" → "the entire twelve-selector list"
- `:208-211` — "one per allow-list entry (13) = 17" → "one per allow-list entry (12) = 16"
- `:212-213` — `assert examined >= 17` → `assert examined >= 16`, and the message
  "expected >= 17" → "expected >= 16"

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_consumption_css.py --verbosity=0`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Falsify against three named mutants**

Run each, confirm RED, then **hand-edit the mutant back out** (never `git checkout`):

1. Delete `html.unit-tree-collapsed [data-unit-shell] .unit-crumbs,` from the CSS →
   expect FAIL on `expected 12 selectors, got 11`.
2. Duplicate `html.unit-tree-collapsed [data-unit-shell] .el--text,` →
   expect FAIL on the length assertion (the sorted comparison alone would pass).
3. Change `html.unit-tree-collapsed [data-unit-shell] .markdone` to
   `html.unit-tree-collapsed .markdone` → expect FAIL on the `[data-unit-shell]` assertion.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css tests/test_consumption_css.py
git commit -m "feat(courses): tinted blocks fill the column, prose caps at 46rem

Five selectors leave the collapsed-state prose cap (callout, question card,
the quiz preview alert, plus .quiz-finish and .lesson-unit__head, which frame
the cards) and four join it (.question__stem, .question__choices,
.question__feedback, textarea.question__text-input).

Sentinels make the block machine-locatable so the new source assertion can
pin the prelude at exactly 12 selectors; examined drops 17 -> 16."
```

---

### Task 2: Invert the callout source guard

**Files:**
- Modify: `courses/tests/test_callout_nesting_css.py:22-31`

**Interfaces:**
- Consumes: `/* prose-cap:begin|end */` from Task 1.

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

    Slices between the sentinels for the same reason test_consumption_css does: the
    file has many @media blocks and many html.unit-tree-collapsed rules, and line
    numbers move the moment the block is edited.
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

The old `:30` assertion (`unit-tree-collapsed[^{]*\]\s+\.callout\s*,`) is **folded in, not kept**:
it required a trailing comma, so a `.callout` re-added as the *last* prelude selector would be
followed by `{` and escape it. The token-boundary regex above has no such hole.

- [ ] **Step 2: Run test to verify it fails**

First introduce the mutant: add `html.unit-tree-collapsed [data-unit-shell] .callout,` as the **last**
selector in the prose-cap prelude (immediately before `.guessnumber`'s line ends with `{`).

Run: `uv run pytest courses/tests/test_callout_nesting_css.py::test_prose_cap_no_longer_applies_to_any_callout --verbosity=0`
Expected: FAIL — proving both that the assertion bites and that it catches the last-position case the
old regex missed.

- [ ] **Step 3: Remove the mutant**

Hand-edit the `.callout` line back out of the CSS.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_callout_nesting_css.py --verbosity=0`
Expected: PASS (all four tests in the file).

- [ ] **Step 5: Confirm the token boundary does NOT false-positive**

Add `html.unit-tree-collapsed [data-unit-shell] .callout__body,` to the prelude. Run the test again.
Expected: **PASS** (it is a `.callout__*` name, not `.callout`). Note this also reddens Task 1's
12-selector assertion, which is correct and expected. Hand-edit the line back out and re-run both
files to confirm green.

- [ ] **Step 6: Commit**

```bash
git add courses/tests/test_callout_nesting_css.py
git commit -m "test(courses): assert no .callout selector survives in the prose cap

Inverts the old 'the :not(:has()) predicate must exist' assertion. Uses a
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

CSS = Path("courses/static/courses/css/courses.css")
CALLOUT = Path("templates/courses/elements/calloutelement.html")


def test_text_input_comment_no_longer_claims_the_textarea_fills_the_card():
    """`textarea.question__text-input` is now capped at 46rem in the collapsed
    shell, so 'fills the card column, resizable up to it' is false on the surface
    it describes. (It was already misleading: app.css:150 is
    `textarea { resize: vertical }`, so it has never been draggable sideways.)
    """
    css = CSS.read_text(encoding="utf-8")
    assert "resizable up to it" not in css
    assert "resize: vertical" in css, (
        "the amended comment must name the real constraint, app.css:150"
    )


def test_callout_children_comment_no_longer_cites_the_prose_cap_predicate():
    """The wrapper's third stated reason was being the subject of
    `:has(> .callout__children)`. This change deletes the only such predicate in
    the codebase, so a reader finding three reasons and only two mechanisms could
    wrongly conclude the wrapper is removable.
    """
    html = CALLOUT.read_text(encoding="utf-8")
    assert ":has(> .callout__children)" not in html
    assert "scopeOf" in html, "the two surviving reasons must remain documented"
    assert ".callout__body + .callout__children" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stale_rationale_comments.py --verbosity=0`
Expected: FAIL on both — `"resizable up to it"` and `":has(> .callout__children)"` are still present.

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

In `templates/courses/elements/calloutelement.html`, strike the third reason from the
`{% comment %}` block — change:

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
    for `.callout__body + .callout__children`. (It was also the subject of a
    `:has(> .callout__children)` prose-cap predicate; that predicate was removed when
    all callouts were made one width, so do not go looking for it.)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stale_rationale_comments.py --verbosity=0`
Expected: PASS (2 tests).

- [ ] **Step 5: Confirm no other test scans this template**

Run: `uv run pytest courses/tests/test_callout_nesting_css.py tests/test_consumption_css.py --verbosity=0`
Expected: PASS. (Comment text can break regex-based source scans — this confirms it did not.)

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/css/courses.css templates/courses/elements/calloutelement.html tests/test_stale_rationale_comments.py
git commit -m "docs(courses): correct the two rationale comments this change falsifies

The text-input comment claimed the textarea 'fills the card column, resizable
up to it' -- now capped, and never horizontally resizable in the first place.
The callout-children comment cited a :has() predicate this change deletes."
```

---

### Task 4: e2e — every tinted box is one width

**Files:**
- Create: `tests/test_e2e_uniform_block_width.py`

**Interfaces:**
- Produces: `_make_pa_user`, `_login`, `_lesson_url`, `_seed_unit`, `COLUMN_JS`, `WIDTH_JS`,
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

WIDTH_JS = "(sel) => document.querySelector(sel).getBoundingClientRect().width"


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
def test_every_tinted_block_is_one_width(page, live_server):
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
    add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7")
    )
    add_element(unit, ChoiceGridQuestionElement.objects.create(stem="Grid?"))

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    column = page.evaluate(COLUMN_JS)
    widths = {
        sel: page.evaluate(WIDTH_JS, sel)
        for sel in (
            ".callout:not(:has(> .callout__children))",
            ".callout:has(> .callout__children)",
            ".el--question:not(.el--choicegrid)",
            ".el--choicegrid",
        )
    }
    # Compared against the READ column, never a hard-coded 872: the derived
    # geometry moves whenever .app-main, the pin lane or the article padding does.
    for sel, w in widths.items():
        assert abs(w - column) < 2, (
            f"{sel} is {w}, column is {column}; every tinted block must fill it"
        )
    # And explicitly to each other, which is the defect as the user reported it.
    assert (
        abs(
            widths[".callout:not(:has(> .callout__children))"]
            - widths[".callout:has(> .callout__children)"]
        )
        < 2
    ), f"the two callouts still differ: {widths}"
```

- [ ] **Step 2: Run test to verify it fails**

Mutant: hand-add `html.unit-tree-collapsed [data-unit-shell] .callout:not(:has(> .callout__children)),`
back into the prose-cap prelude.

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: FAIL — the prose-only callout measures 736 against a column of 872.

- [ ] **Step 3: Remove the mutant**

Hand-edit that selector back out.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS. Confirm the run reports `1 passed`, **not** `no tests ran` (exit 5 means `-m e2e`
was dropped and nothing was checked).

- [ ] **Step 5: Falsify the second mutant**

Mutant: re-add the **whole** old question entry
`html.unit-tree-collapsed [data-unit-shell] .el--question:not(.el--choicegrid):not(.el--multigrid):not(.el--dragimage):not(.el--matchpair):not(.el--dragfill),`.
Expected: FAIL on `.el--question:not(.el--choicegrid)` (capped at 736 while `.el--choicegrid` stays
at the column). Hand-edit it back out and re-run to confirm green.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin that every tinted block renders at one width

The defect as reported: a callout with children was 136px wider than a callout
with only text. Compares against the READ column, never a hard-coded 872."
```

---

### Task 5: e2e — prose inside a widened box stays at 46rem

**Files:**
- Modify: `tests/test_e2e_uniform_block_width.py`

**Interfaces:**
- Consumes: `_seed_unit`, `_login`, `_collapsed`, `WIDTH_JS`, `COLUMN_JS` from Task 4.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_e2e_uniform_block_width.py`:

```python
@pytest.mark.django_db(transaction=True)
def test_prose_inside_a_widened_box_stays_capped(page, live_server):
    """The other half of the design: the BOX widens, its PROSE does not.

    Asserts the 736 token, not `narrower than its own box`. Both containers have
    padding, so a child is ALWAYS strictly narrower than its parent's border box,
    cap or no cap -- that assertion cannot fail and would read as a pin while
    proving nothing.

    The container callout carries a non-empty body on purpose: calloutelement.html
    renders .callout__body under `{% if el.body %}`, so a children-only callout has
    no body element and the locator would resolve to nothing.
    """
    from courses.models import CalloutElement
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
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

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    column = page.evaluate(COLUMN_JS)
    for sel in (
        ".callout__body",
        ".el--question .question__stem",
        "textarea.question__text-input",
    ):
        w = page.evaluate(WIDTH_JS, sel)
        assert abs(w - 736) < 2, f"{sel} must stay capped at 46rem, got {w}"
        assert w < column - 50, (
            f"{sel} is {w} against a column of {column} -- the cap is not binding"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Mutant: delete `html.unit-tree-collapsed [data-unit-shell] .el--question .question__stem,` from the
prelude.

Run: `uv run pytest tests/test_e2e_uniform_block_width.py::test_prose_inside_a_widened_box_stays_capped -m e2e --verbosity=0`
Expected: FAIL — the stem stretches to the card's inner box (~830).

- [ ] **Step 3: Remove the mutant, then falsify the other two arms**

Hand-edit the stem selector back in. Then, one at a time (restoring between each):

- Delete `html.unit-tree-collapsed [data-unit-shell] .el--text,` → expect FAIL on
  `.callout__body` (it is capped only via `.el--text`; this is the arm proving the body did not
  lose its cap when `.callout` left the list).
- Delete `html.unit-tree-collapsed [data-unit-shell] textarea.question__text-input,` → expect FAIL
  on the textarea arm.

Each arm must be shown RED **independently** — a single mutant reddening the whole test would leave
the other two unproven.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin that prose inside a widened tinted box stays at 46rem

Three arms, each falsified independently: .callout__body (carried by .el--text),
.question__stem, and textarea.question__text-input."
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
    from courses.models import ShortTextQuestionElement

    user, _course, unit = _seed_unit("pa_expanded")
    add_element(unit, CalloutElement.objects.create(kind="note", body="<p>t</p>"))
    add_element(
        unit, ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7")
    )

    page.set_viewport_size({"width": 1280, "height": 900})
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("[data-unit-shell]")
    assert not page.evaluate(
        "() => document.documentElement.classList.contains('unit-tree-collapsed')"
    ), "this test must run EXPANDED; collapsed it proves nothing"

    for sel in (".callout", ".el--question"):
        mw = page.evaluate(
            f"() => getComputedStyle(document.querySelector({sel!r})).maxWidth"
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
        unit, ShortTextQuestionElement.objects.create(stem="Name a prime.", accepted="7")
    )

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    w = page.evaluate(WIDTH_JS, "input.question__text-input")
    assert abs(w - 352) < 2, f"the short-answer input must stay at 22rem, got {w}"
```

- [ ] **Step 2: Run tests to verify they fail**

Mutant A (expanded test): hand-add
`[data-unit-shell] .callout { max-width: 46rem; }` **outside** any collapsed scope, immediately after
the prose-cap `@media` block.
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
    """Two behaviour changes that the Purpose section does not mention, pinned so
    they are intentional rather than incidental.

    1. The five grid types were excluded from the cap entirely, so their stems
       filled the card's inner box (~830). They now cap at 736.
    2. fillblank and dragfill put their widget INSIDE a `<fieldset class=
       "question__stem">`. A fieldset defaults to min-inline-size: min-content,
       which can refuse a max-width. MEASURED at spec time: it does not here --
       both stems bind at 736 and neither overflows (B0). This is the pin for
       that, so a future content or layout change that breaks it is caught.

    The choicegrid fixture MUST set a non-empty stem: choicegridquestionelement
    renders .question__stem under `{% if el.stem %}`, so a stemless fixture has no
    stem at all and the locator would silently resolve to another question's.
    """
    from courses.models import Blank
    from courses.models import ChoiceGridQuestionElement
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement
    from courses.models import Element
    from courses.models import FillBlankQuestionElement

    user, _course, unit = _seed_unit("pa_stems")

    add_element(
        unit,
        ChoiceGridQuestionElement.objects.create(stem="Pick one per row."),
    )

    gapped = (
        "The capital of France is ￿0￿, which stands on the "
        "￿1￿, and the capital of Italy is ￿2￿, which "
        "stands on the ￿3￿ river in central Europe."
    )
    fb = FillBlankQuestionElement.objects.create(stem=gapped)
    for i, ans in enumerate(("Paris", "Seine", "Rome", "Tiber")):
        Blank.objects.create(question=fb, order=i, accepted=ans)
    Element.objects.create(unit=unit, content_object=fb)

    df = DragFillBlankQuestionElement.objects.create(
        stem=gapped, distractors="Madrid\nLisbon\nDanube\nVistula\nBerlin\nWarsaw"
    )
    for tok in ("Paris", "Seine", "Rome", "Tiber"):
        DragBlank.objects.create(question=df, correct_token=tok)
    Element.objects.create(unit=unit, content_object=df)

    _login(page, live_server, user.username)
    _collapsed(page, live_server, unit)

    # The pool ships `hidden` and EMPTY -- dnd.js reveals and fills it. Reading
    # before that returns clientWidth 0, which would satisfy "no overflow" and
    # fabricate a pass. Sync first, then assert it is genuinely live.
    page.wait_for_selector(".el--dragfill [data-dnd-pool]:not([hidden])")
    page.wait_for_function(
        "() => document.querySelectorAll('.el--dragfill .dnd__chip').length > 0"
    )
    pool = page.evaluate(
        "() => { const p = document.querySelector('.el--dragfill .dnd__pool');"
        " return {c: p.clientWidth, s: p.scrollWidth}; }"
    )
    assert pool["c"] > 0, f"INVALID: the pool is not live, measurement is void: {pool}"

    grid_stem = page.evaluate(WIDTH_JS, ".el--choicegrid .question__stem")
    scroll_x = page.evaluate(WIDTH_JS, ".el--choicegrid .scroll-x")
    assert abs(grid_stem - 736) < 2, f"grid stem must cap at 46rem, got {grid_stem}"
    # Directional only. .scroll-x is the edge-shading wrapper (it does not itself
    # scroll -- the inner .choicegrid-scroll does), and the bare <fieldset> around
    # it has no min-inline-size: 0, so its width is not pinned to the card's inner
    # box. A generous constant here would be the fragility this suite bans.
    assert scroll_x > grid_stem + 2, (
        f"the grid widget must stay wider than the capped stem: "
        f"scroll-x {scroll_x} vs stem {grid_stem}"
    )

    for sel in (".el--fillblank .question__stem", ".el--dragfill .question__stem"):
        box = page.evaluate(
            f"() => {{ const e = document.querySelector({sel!r});"
            " return {w: e.getBoundingClientRect().width,"
            " c: e.clientWidth, s: e.scrollWidth}; }}"
        )
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

- [ ] **Step 3: Remove the mutant and re-run**

Hand-edit the `:not(.el--dragfill)` back out.
Run: `uv run pytest tests/test_e2e_uniform_block_width.py -m e2e --verbosity=0`
Expected: PASS (5 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_uniform_block_width.py
git commit -m "test(e2e): pin grid stems narrowing and both fieldset stems binding

Records the measured B0 outcome: the fieldset min-inline-size floor does not
refuse the 46rem cap on fillblank or dragfill, and neither overflows. Syncs on
the dnd pool being live first -- it ships hidden and empty, and a pre-JS read
returns zeros that would satisfy 'no overflow' and fabricate a pass."
```

---

### Task 8: Rewrite the quiz-chrome test

**Files:**
- Modify: `tests/test_e2e_unit_nav.py:1339-1400`

- [ ] **Step 1: Write the failing test**

In `test_quiz_chrome_is_capped_across_both_page_states`, rename to
`test_quiz_chrome_tracks_the_column_across_both_page_states` and replace **both** measurement loops.

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
    assert title_w <= 736 + 2, f".lesson-unit__title must cap at 736px, got {title_w:.1f}"
    for sel in ("[data-quiz-preview-notice]", ".el--question"):
        w = page.evaluate(
            f"() => document.querySelector({sel!r}).getBoundingClientRect().width"
        )
        assert abs(w - column) < 2, f"{sel} must fill the column {column}, got {w:.1f}"
```

Replace `:1394-1398` with the same shape, swapping the loop tuple to
`(".quiz-finish", ".el--question")`.

Then replace the comment at `:1384-1388` with:

```python
    # Re-assert the collapsed state AFTER the reload. This is now MORE important,
    # not less: the title assertion is still one-sided (<= 738) and the EXPANDED
    # quiz column at 1440 is 648px -- under 738 -- while the column-equality
    # assertions compare against whatever column is actually rendered, so they too
    # hold expanded. Without this guard every assertion below passes in the wrong
    # state. Load A is safe because _collapse() waits on the class.
```

And update the docstring at `:1339-1351` — its first paragraph must now read:

```python
    """The quiz entries (.lesson-unit__title, [data-quiz-preview-notice],
    .quiz-finish) exist only for _quiz_article.html; without this the whole suite
    stays green if all three are deleted. The .count() assertions carry that;
    the width assertions carry which of them cap and which fill the column.
```

Keep every `locator(...).count()` assertion untouched — the docstring states they are the only thing
stopping a silent deletion.

- [ ] **Step 2: Run test to verify it fails**

First confirm the *current* file is red against the shipped change (it should already be, from Task 1):

Run: `uv run pytest tests/test_e2e_unit_nav.py::test_quiz_chrome_is_capped_across_both_page_states -m e2e --verbosity=0`
Expected: FAIL on `.el--question must cap at 736px, got 872.0` — this is the pre-existing test the
change breaks, and confirms it was really testing the old behaviour.

- [ ] **Step 3: Apply the rewrite from Step 1**

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_unit_nav.py::test_quiz_chrome_tracks_the_column_across_both_page_states -m e2e --verbosity=0`
Expected: PASS.

- [ ] **Step 5: Falsify — both the widths and the state guard**

1. Re-add `html.unit-tree-collapsed [data-unit-shell] [data-quiz-preview-notice],` and
   `html.unit-tree-collapsed [data-unit-shell] .quiz-finish,` to the prelude → expect FAIL on both
   column-equality assertions. Hand-edit out.
2. Delete the `page.wait_for_function(... 'unit-tree-collapsed' ...)` guard **and** change
   `_collapse(page)` in Load A to a no-op, so the page renders expanded → expect FAIL (the column
   reads 648 and `.el--question` no longer matches it, or the title assertion misleads). Restore both.

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

- [ ] **Step 1: Write the failing test**

Rename `test_a_table_in_a_callout_is_not_squeezed_by_the_prose_cap` to
`test_both_callout_shapes_render_at_one_width`, replace the docstring's second paragraph
(`:117-120`) and both measurement arms (`:146-155`).

New docstring second paragraph:

```python
    641px is NOT enough either: the collapsed content box is
    .app-main's 960px cap, less its 2x20px padding, less the 2.4rem pin lane and
    the 3rem .lesson padding -- 872px at any viewport >= 1040px, and far less at
    641px, which would put both arms under the 736px cap and make the comparison
    vacuous. Use 1280x900. (.unit-shell's max-width: 72rem never binds: .app-main
    caps the containing block first.)
```

New arms:

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

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_callout_container.py::test_a_table_in_a_callout_is_not_squeezed_by_the_prose_cap -m e2e --verbosity=0`
Expected: FAIL on the old `abs(prose_box["width"] - 736) < 2` control arm — the prose-only callout
now measures 872.

- [ ] **Step 3: Apply the rewrite from Step 1**

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_e2e_callout_container.py -m e2e --verbosity=0`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Falsify BOTH halves independently**

1. Re-add `html.unit-tree-collapsed [data-unit-shell] .callout:not(:has(> .callout__children)),` →
   expect FAIL on the **equality** half (736 vs 872). Hand-edit out.
2. Add `html.unit-tree-collapsed [data-unit-shell] .callout,` (capping *both* shapes) → expect FAIL
   on the **`> 736`** half, with equality still passing. Hand-edit out.

Mutant 2 is the one that proves the test would have caught the regression the old test guarded.

- [ ] **Step 6: Commit**

```bash
git add tests/test_e2e_callout_container.py
git commit -m "test(e2e): both callout shapes render at one width

Was: assert the prose-only callout is exactly 736. Now: assert the two shapes
are equal AND both exceed 736, so neither direction of failure passes. Also
corrects the docstring's pre-.app-main column formula."
```

---

### Task 10: Regression sweep and visual verification

**Files:** none modified (verification only, plus screenshots discarded after review)

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
  tests/test_e2e_questions_2d.py -m e2e --verbosity=0
```
Expected: all PASS. `test_e2e_unit_head_layout.py` is included deliberately — it guards the
three-item `.lesson-unit__head` row that this change widens.

If the run reports `no tests ran` / exit 5, `-m e2e` was dropped: that is **not** a pass. Re-run.

- [ ] **Step 3: Full branch gate**

```bash
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
uv run ruff check --no-cache .
uv run ruff format --check .
```
Expected: all PASS. Record the counts in the commit message. Note `ruff format --check` is a separate
CI gate from `ruff check` — both must pass.

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

- [ ] **Step 6: Commit**

```bash
git commit --allow-empty -m "chore: verification sweep for uniform tinted block width

non-e2e: <N> passed. e2e: <N> passed. ruff check + format: clean.
Screenshots reviewed light and dark; the four accepted consequences confirmed
as intended, not defects."
```

---

## Self-Review

**1. Spec coverage.** Every spec requirement maps to a task: the CSS change and R2's exact-list
assertion → Task 1; test 1 → Task 2; Architecture's two comment regions plus the calloutelement
comment → Task 3; tests 5/6/7/9/8/10 → Tasks 4-7; test 3 → Task 8; test 2 → Task 9; the regression
scope, `test_consumption_css`'s five stale sites (Task 1), and the visual checklist → Task 10. The
dead B1/B2 branches are excluded by the Global Constraints, as instructed.

**2. Placeholder scan.** No TBDs. Every code step carries real code; every mutant is named and its
expected failure stated; every command is runnable as written.

**3. Type consistency.** `_seed_unit`, `_login`, `_collapsed`, `COLUMN_JS` and `WIDTH_JS` are defined
once in Task 4 and used with the same signatures in Tasks 5-7. `PROSE_CAP_SELECTORS` and
`_prose_cap_prelude()` are defined in Task 1 and the sentinel names they depend on are reused verbatim
in Task 2. The twelve selector strings in Task 1's list are byte-identical to the twelve in the CSS
block of the same task.
