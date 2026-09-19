# Cross-unit Element Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an author mark an element in unit X and paste a **copy** of it — into any admissible slot, or directly above a chosen element — in another unit Y of the same course.

**Architecture:** The existing session mark (`element_clip`) and paste endpoint (`element_paste` → `builder.paste_element` → `_copy_into` → transfer export + `graft_elements`) are generalised from "same unit" to "same course, copy only". The rule (`paste_allowed`) gains a cross-unit clause 0 and two cross-unit-only quiz clauses; the service locks two units in ascending pk order; `_clip_context` gains a cross-unit branch; the banner moves out of the pane head and gains a server-rendered "Copy to another unit…" tree.

**Tech Stack:** Django 5 / Python 3.13, PostgreSQL (psycopg 3), server-rendered templates + vanilla JS (`editor.js`), KaTeX auto-render, pytest + pytest-django, Playwright (sync) for e2e.

**Spec:** `docs/superpowers/specs/2026-09-18-cross-unit-element-copy-design.md` — read it alongside this plan. Every "§n" below refers to that spec. Where this plan and the spec disagree, the spec wins; stop and report the disagreement — **except for the deliberate deviations listed below**, which were settled in plan review, do not trigger stop-and-report, and are each listed in the PR body.

## Deliberate deviations from the spec (settled — do not "fix" back)

None touches an owner decision (D1–D12); each corrects a test or verification detail the spec got wrong or left out.

| # | Spec says | Plan does | Why |
|---|---|---|---|
| V1 | ≤ 480px: `documentElement.scrollWidth == clientWidth` | `overflow <= base_overflow` (the same page unmarked) | The unmarked editor page may already overflow at 400px; the banner must add none, not fix pre-existing overflow. |
| V2 | The "from"-link `position: relative` mutant is "re-confirmed red" | If it stays green, record that it is not caught | Its nearest positioned ancestor (`.clip-banner__line`) may keep the twin inside the viewport; faking a red would be worse than an honest gap. |
| V3 | Dropping `element` from `_paste_before` turns `test_a_paste_before_with_a_stale_token_is_a_409`'s pre-assertion red | The mutant is aimed at `test_a_paste_before_a_sibling_reorders_within_the_slot_and_clears_the_mark` | `_assert_posts_the_mark` checks the caller's argument, not the POSTed field, so the spec's predicted red cannot happen; the positive reorder test is what proves the field travels. |
| V4 | "e2e (one test, real UI)" | Three e2e tests | The narrow-viewport and nothing-fits checks need their own viewport / fixture. |
| V5 | No icon-size rule | `.iconbtn .ic { width: 1rem; height: 1rem; display: block; }` | The editor page does not load `builder.css` (home of the global `.ic` size); an unsized `<svg>` renders at 300×150. |
| V6 | List cap `min(35vh, 18rem)` in every layout | Tighter cap inside the 70rem media block **if** the Task 7 measurement shows `.pane-body` below ~40% | The spec's stated goal (~40%) wins over its arithmetic. **Outcome (Task 7):** `min(14vh, 7rem)`; measured share 0.084 base → 0.323 at `min(20vh, 12rem)` → 0.436. |
| V7 | `.clip-banner__label` `flex: 1 1 auto`; `.clip-banner__from` `flex: 0 1 auto; max-width: 45%` | Only the label shrinks; `.clip-banner__from` does not shrink, capped at 45% (its `<a>` still truncates inside) | Task 7's screenshots: with the spec's values the "from" link rendered 0px wide — violating §8/D6 "the link is never the first thing cut". Cost: with a short label a long "from" title truncates at 45% despite spare room. |
| V8 | §8: fully-expanded list; flat fallback above ~10% | D13 (owner, 2026-09-19): collapsible tree, levels loaded on expand — Tasks 9–10 | Measured 15–16% / 242 KB on mat-pp; see the spec's "Amendment: D13". |

## Global Constraints

- **Owner decisions D1–D12 (spec table) are fixed.** Copy only (D1); same course only (D2); the mark follows the author (D3); "Copy before" only in the destination unit (D4); the unit list is a server-rendered `<details>` of plain links, no JS, no new endpoint (D5/D12); destination banner "Selected: <label> — from <Unit>" (D6); no move control outside the source unit (D7); the mark persists after a copy, a foreign-course mark is ignored not cleared (D8); monochrome SVG icons, never emoji (D9); interactive elements refused into a quiz, cross-unit only (D10); rare deadlock outcomes accepted (D11).
- **Worktree:** every command runs from `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/cross-unit-element-copy`. Never operate on the main checkout.
- **Preflight (once, before Task 1):**
  ```bash
  cp C:/Users/krzys/Documents/Python/own/libli/.env .env
  docker compose -p libli-test -f docker-compose.test.yml up -d --wait
  echo "$TEST_DATABASE_URL"
  uv run python -c "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test'); django.setup(); from django.conf import settings; print(settings.DATABASES['default']['PORT'])"
  ```
  Expected: the port prints `55433` — **the Python probe is decisive**. The `echo` checks only for a stale **exported** value (an exported variable beats `.env`): an empty line is fine (the value comes from `.env`); a non-empty value must end `127.0.0.1:55433/libli`. **If the port differs, or the echo shows another URL, stop** — without it the suite creates and drops `test_libli` on the local server that holds mat-pp. `.env` is gitignored; never commit it.
- **Test mechanics:**
  - Tools are not on PATH: `uv run pytest …`, `uv run ruff …`, `uv run python manage.py …`.
  - **Never pass `-q`** (addopts already has it; a second one hides the summary).
  - e2e tests need `-m e2e` (addopts deselects them).
  - **Read the pytest summary line, not just the exit code** (exit 0 has been seen with failures).
  - Scope runs to the files a task touches. The whole suite is the branch gate only (Task 8), in chunks — one full run is OOM-killed.
  - Never run tests in two trees at once, and never kill a competing pytest mid-run.
  - Before each commit: `uv run ruff format <every .py file the task touched>`, then `uv run ruff check --no-cache .` and `uv run ruff format --check .`. The plan's code blocks are **not** pre-formatted — the formatter wins. A line the formatter cannot break must be split by hand (E501 is 88 columns). Imports are one per line (`force-single-line`).
- **Falsification (every *Mutant*):** apply the mutant **by hand with Edit**, run the named test, observe **red for the stated reason**, revert **by hand with Edit**, then `git diff` to confirm only intended changes remain. **Never `git checkout -- <file>` to revert a mutant** — it destroys the uncommitted implementation.
- **No assertion may compare pks of different models** (independent sequences). Compare titles, bodies, rendered text, or instances with `==`; build hrefs with `reverse`.
- **Django templates:** `{# … #}` is single-line only; multi-line notes use `{% comment %}…{% endcomment %}`.
- **Line citations:** comment rewrites in `editor.css` and `courses/transfer/importer.py` are **line-count neutral** where the spec says so (the repo cites line numbers in those files).
- **Commits:** one per task — except Task 8, which commits at **every step that says Commit** (Step 4b, Step 7, and Step 9 if the rebase needs it); never squash Step 4b into Step 7, it exists so the timing step can halt on a clean tree. Explicit paths (never `git add -A` / `git add .`), message ending with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `courses/builder.py` | `QUIZ_EXCLUDED_TYPE_KEYS`; `unit_children_map`; `SubtreeFacts.nested_question` / `has_interactive`; `paste_allowed` clause 0 / 2c / 2d; `paste_element` two-unit path; `_copy_into` source/dest | 1, 2, 3 |
| `courses/transfer/importer.py` | `graft_elements` docstring point 2 only | 3 |
| `courses/views_manage.py` | `PASTE_REFUSAL_MESSAGES["interactive_in_quiz"]`; `copy_units_tree`; `_clip_context` cross-unit branch + new keys; `element_paste` checks + deadlock mapping; docstring rewrites | 2, 4, 5 |
| `courses/templatetags/courses_manage_extras.py` | `paste_buttons` / `paste_before_button` return `clip_element_pk` (+ `mode`) | 5, 6 |
| `templates/courses/manage/editor/_paste_buttons.html` | hidden `element`; SVG icons | 5, 6 |
| `templates/courses/manage/editor/_paste_before_button.html` | hidden `element`; `mode`; move/copy SVG + label | 5, 6 |
| `templates/courses/manage/editor/_editor_scope.html` | banner restructure (div after `.pane-head`), "from" link, nothing-fits, copy-units include | 6 |
| `templates/courses/manage/editor/_copy_units_tree.html` (new) | the `<details>` wrapper + top-level loop | 6 |
| `templates/courses/manage/editor/_copy_units_node.html` (new) | one recursive tree row | 6 |
| `templates/courses/manage/editor/_element_row_controls.html` | Duplicate button SVG | 6 |
| `templates/courses/manage/editor/editor.html` | two `<symbol>`s: `ed-paste-move`, `ed-paste-copy` | 6 |
| `locale/{pl,en}/LC_MESSAGES/django.{po,mo}` | new msgids | 6 |
| `courses/static/courses/css/editor.css` | `.clip-banner` block rewrite; stale comments | 7 |
| `courses/static/courses/js/editor.js` | typeset `[data-math-title]` in the swapped editor scope | 7 |
| `courses/tests/test_paste_rule.py` | rule + facts + drift guard tests | 1, 2 |
| `courses/tests/test_nested_question_gates.py` | AST guard non-vacuity; endpoint test posts `element` | 2, 5 |
| `tests/test_builder_paste_element.py` | service tests | 3 |
| `tests/test_element_paste_view.py` | context, POST, cost, deadlock tests; helper migration | 4, 5 |
| `tests/test_editor_clip_templates.py` | render-level tests | 6 |
| `tests/test_editor_styles.py` | CSS guard class tuple | 7 |
| `tests/test_e2e_cross_unit_copy.py` (new) | the three e2e tests (V4) | 8 |

---

### Task 1: Subtree facts, the interactive set, and the shared children map

**Files:**
- Modify: `courses/builder.py` (constants block near `NESTABLE_QUESTION_KEYS`; `SubtreeFacts`; `subtree_facts`; `enumerate_slots`)
- Test: `courses/tests/test_paste_rule.py`

**Interfaces:**
- Produces:
  - `builder.QUIZ_EXCLUDED_TYPE_KEYS: frozenset[str]` — transfer keys.
  - `builder.unit_children_map(unit) -> dict[int | None, list[Element]]` — every join of `unit`, `content_type` selected and `content_object` prefetched, grouped by `parent_id`, each list ordered `("order", "pk")`.
  - `builder.SubtreeFacts(min_headroom: int, subtree_pks: frozenset, nested_question: bool, has_interactive: bool)`.
  - `builder.subtree_facts(join, children_map=None) -> SubtreeFacts` (signature unchanged).

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_paste_rule.py` (add the imports at the top, one per line, next to the existing ones):

```python
import re

from django.template.loader import render_to_string

from courses.models import CalloutElement
from courses.models import ChoiceQuestionElement
from courses.models import MarkDoneElement
from courses.models import StepperElement
```

(`CalloutElement` is already imported — do not duplicate it.)

```python
def _callout(unit, parent=None, tab=""):
    obj = CalloutElement.objects.create(kind="example")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _choice(unit, parent=None, tab=""):
    obj = ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False)
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _markdone(unit, parent=None, tab=""):
    obj = MarkDoneElement.objects.create(prompt="Tick")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _stepper(unit, parent=None, tab=""):
    obj = StepperElement.objects.create(prompt="Steps")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def test_nested_question_is_false_for_a_lone_question_root():
    """Mutant: make nested_question include the root (drop `rel >= 1`) -> RED."""
    _course, unit = make_course_with_unit()
    q = _choice(unit)

    assert builder.subtree_facts(q).nested_question is False


def test_nested_question_is_true_for_a_container_holding_a_question():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    _choice(unit, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.subtree_facts(box).nested_question is True


def test_nested_question_is_true_for_a_question_two_levels_down():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    tabs, slots = _tabs(unit, parent=box, tab=CalloutElement.SLOT_ID)
    _choice(unit, parent=tabs, tab=slots[0])

    assert builder.subtree_facts(box).nested_question is True


def test_has_interactive_sees_an_interactive_root():
    _course, unit = make_course_with_unit()

    assert builder.subtree_facts(_stepper(unit)).has_interactive is True


def test_has_interactive_sees_an_interactive_two_levels_down():
    """callout > tabs > checklist, inside the depth cap.

    Mutant: stop the walk at depth 1 (e.g. `if rel >= 1: return` after the
    headroom line) -> RED."""
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    tabs, slots = _tabs(unit, parent=box, tab=CalloutElement.SLOT_ID)
    _markdone(unit, parent=tabs, tab=slots[0])

    assert builder.subtree_facts(box).has_interactive is True


def test_has_interactive_is_false_for_a_subtree_with_none():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    _text(unit, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.subtree_facts(box).has_interactive is False


def test_has_interactive_never_counts_a_dangling_gfk():
    """model_to_key(type(None)) is None, never an interactive key.

    Mutant: treat a None key as interactive
    (`key is None or key in QUIZ_EXCLUDED_TYPE_KEYS`) -> RED.

    Repoint object_id rather than deleting the concrete: every concrete declares
    GenericRelation(Element), so deleting it CASCADES the join away."""
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    broken = _text(unit, parent=box, tab=CalloutElement.SLOT_ID)
    Element.objects.filter(pk=broken.pk).update(object_id=9_999_999)

    facts = builder.subtree_facts(box)

    assert facts.has_interactive is False
    assert facts.nested_question is False


def test_the_map_walk_and_the_orm_walk_agree():
    """The render passes unit_children_map(); the endpoint omits it. Both must
    produce identical facts, or the advisory buttons and the enforcing check
    disagree."""
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    tabs, slots = _tabs(unit, parent=box, tab=CalloutElement.SLOT_ID)
    _markdone(unit, parent=tabs, tab=slots[0])
    _choice(unit, parent=tabs, tab=slots[1])

    mapped = builder.subtree_facts(box, children_map=builder.unit_children_map(unit))

    assert mapped == builder.subtree_facts(box)


def test_unit_children_map_groups_every_join_by_parent():
    _course, unit = make_course_with_unit()
    box = _callout(unit)
    child = _text(unit, parent=box, tab=CalloutElement.SLOT_ID)
    top = _text(unit)

    cmap = builder.unit_children_map(unit)

    assert cmap[None] == [box, top]
    assert cmap[box.pk] == [child]


_CARD = re.compile(r'data-add-type="([^"]+)"')


def _top_level_cards(unit_is_quiz):
    html = render_to_string(
        "courses/manage/editor/_add_menu.html",
        {
            "depth": 0,
            "nested": False,
            "max_nest_depth": builder.MAX_NEST_DEPTH,
            "unit_is_quiz": unit_is_quiz,
            "parent": "",
            "tab": "",
        },
    )
    return set(_CARD.findall(html))


def test_quiz_excluded_type_keys_match_the_add_menus_interactive_group():
    """DERIVED, never a hard-coded count: the add menu hides exactly these types
    in a quiz, so the paste rule must refuse exactly these types into one.

    Depth 0 and nested=False on purpose: a deeper menu drops the depth-gated
    spoiler card from BOTH menus and would fake a drift.

    Mutant: remove one key from QUIZ_EXCLUDED_TYPE_KEYS -> RED. Mutant: spell the
    set with card names ("revealgate", "markdone", ...) -> RED."""
    lesson = _top_level_cards(unit_is_quiz=False)
    quiz = _top_level_cards(unit_is_quiz=True)

    # A future quiz-only card must be noticed deliberately, not absorbed.
    assert quiz - lesson == set()
    hidden = {
        builder._NESTABLE_FORM_KEY_ALIASES.get(name, name) for name in lesson - quiz
    }
    assert hidden  # not vacuous: the menus really differ
    assert hidden == builder.QUIZ_EXCLUDED_TYPE_KEYS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_paste_rule.py -k "nested_question or has_interactive or map_walk or unit_children_map or quiz_excluded"`
Expected: FAIL — `AttributeError: 'SubtreeFacts' object has no attribute 'nested_question'` / `module 'courses.builder' has no attribute 'unit_children_map'` / `... 'QUIZ_EXCLUDED_TYPE_KEYS'`.

- [ ] **Step 3: Add the constant**

In `courses/builder.py`, directly after the `NESTABLE_QUESTION_KEYS = frozenset(...)` block, add:

```python
# The add menu's "Interactive" group, as TRANSFER keys (courses.transfer.export
# SERIALIZERS, what model_to_key returns). Quiz units hide this whole group
# (_add_menu.html, `{% if not unit_is_quiz %}`) and student state saves require a
# lesson, so a CROSS-UNIT copy into a quiz refuses any subtree holding one (clause
# 2d in paste_allowed). Pinned to the template by a derived drift guard in
# courses/tests/test_paste_rule.py -- never by a count.
QUIZ_EXCLUDED_TYPE_KEYS = frozenset(
    {
        "reveal_gate",
        "fill_gate",
        "switch_gate",
        "switch_grid",
        "fill_table",
        "spoiler",
        "stepper",
        "mark_done",
        "guess_number",
    }
)
```

- [ ] **Step 4: Extract `unit_children_map` and extend the facts**

Replace the `SubtreeFacts` class with:

```python
@dataclass(frozen=True)
class SubtreeFacts:
    """The four facts about a marked element that do NOT depend on the destination.

    Computed once per render and passed to every per-slot paste_allowed call; the
    endpoint omits it and paste_allowed computes it itself (a cross-unit paste
    computes it once, from the SOURCE unit's map). That parameter is what makes the
    N advisory calls and the one enforcing call provably the same code -- the
    alternative, a view applying `dest_depth <= scalar` on its own, would put a
    second copy of clause 3 outside the authority.

    `nested_question`: a question sits STRICTLY below the root (clause 2c).
    `has_interactive`: any node, root included, is a QUIZ_EXCLUDED_TYPE_KEYS type
    (clause 2d).
    """

    min_headroom: int
    subtree_pks: frozenset
    nested_question: bool
    has_interactive: bool
```

Replace the body of `subtree_facts` (keep its docstring, and append the paragraph below to it) with:

```python
    # Function-local, like paste_allowed's and unit_has_nested_question's: the
    # transfer package pulls courses.forms / courses.media, so a module-level edge
    # risks an import cycle.
    from courses.richtext import CONCRETE_QUESTION_MODELS
    from courses.transfer.export import model_to_key

    question_types = tuple(CONCRETE_QUESTION_MODELS)
    seen = set()
    headroom = [MAX_NEST_DEPTH]
    nested_question = [False]
    has_interactive = [False]

    def walk(node, rel):
        if node.pk in seen:
            return
        seen.add(node.pk)
        headroom[0] = min(headroom[0], _slot_cap(node) - rel)
        obj = node.content_object
        if rel >= 1 and isinstance(obj, question_types):
            nested_question[0] = True
        if model_to_key(type(obj)) in QUIZ_EXCLUDED_TYPE_KEYS:
            has_interactive[0] = True
        if children_map is not None:
            kids = children_map.get(node.pk, [])
        else:
            kids = node.children.all()
        for child in kids:
            walk(child, rel + 1)

    walk(join, 0)
    return SubtreeFacts(
        min_headroom=headroom[0],
        subtree_pks=frozenset(seen),
        nested_question=nested_question[0],
        has_interactive=has_interactive[0],
    )
```

Paragraph appended to the `subtree_facts` docstring (before the closing `"""`):

```
    Both quiz facts inherit this walk -- EVERY child row, matched slot or not --
    while a copy's payload comes from the export's resolved-slot walk, which drops
    orphaned children. So a container whose only question/interactive descendant is
    an orphan is refused into a quiz although its copy would carry neither. That is
    deliberate: the same facts govern moves, where orphans travel, and for copies
    the error is harmlessly strict. Do not "fix" the walk to match the export.
    A dangling GFK gives type(None): model_to_key returns None and isinstance is
    False, so it counts as neither.
```

In `enumerate_slots`, replace the map-building lines

```python
    joins = list(
        unit.elements.all()
        .select_related("content_type")
        .prefetch_related("content_object")
        .order_by("order", "pk")
    )
    children_map = {}
    for join in joins:
        children_map.setdefault(join.parent_id, []).append(join)
```

with

```python
    children_map = unit_children_map(unit)
```

and add, directly above `def enumerate_slots`:

```python
def unit_children_map(unit):
    """{parent_pk_or_None: [joins]} over EVERY join of `unit`, each list ordered by
    ("order", "pk"), with content_type selected and content_object prefetched.

    ONE query for the joins plus one per distinct content type for the GFK
    prefetch. Shared by enumerate_slots (the destination's slots) and by the
    cross-unit paste paths (the SOURCE subtree's facts) -- one builder, so the two
    walks cannot drift apart.
    """
    joins = list(
        unit.elements.all()
        .select_related("content_type")
        .prefetch_related("content_object")
        .order_by("order", "pk")
    )
    children_map = {}
    for join in joins:
        children_map.setdefault(join.parent_id, []).append(join)
    return children_map
```

Update the `enumerate_slots` docstring's first cost paragraph to say the map comes from `unit_children_map` (same cost).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_paste_rule.py tests/test_enumerate_slots.py tests/test_element_paste_view.py tests/test_editor_clip_templates.py`
Expected: all PASS (`tests/test_enumerate_slots.py` holds the refactored function's own tests, including its exact query count; the last two files prove the existing in-unit feature still works).

- [ ] **Step 6: Falsify**

Apply each mutant named in the Step 1 docstrings by hand, run its test, see red, revert by hand, `git diff`:
1. `nested_question`: change `if rel >= 1 and isinstance(...)` to `if isinstance(...)` → `test_nested_question_is_false_for_a_lone_question_root` red.
2. After the headroom line add `if rel >= 1: return` → `test_has_interactive_sees_an_interactive_two_levels_down` red (and the two-levels-down question test).
3. Change the interactive test to `key = model_to_key(type(obj)); if key is None or key in QUIZ_EXCLUDED_TYPE_KEYS:` → `test_has_interactive_never_counts_a_dangling_gfk` red.
4. Remove `"spoiler"` from `QUIZ_EXCLUDED_TYPE_KEYS` → drift guard red.
5. Replace `"mark_done"` with `"markdone"` → drift guard red.

- [ ] **Step 7: Commit**

```bash
uv run ruff format courses/builder.py courses/tests/test_paste_rule.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/builder.py courses/tests/test_paste_rule.py
git commit -m "feat(paste): subtree quiz facts, QUIZ_EXCLUDED_TYPE_KEYS, shared unit map"
```

---

### Task 2: `paste_allowed` — cross-unit clause 0 and quiz clauses 2c / 2d

**Files:**
- Modify: `courses/builder.py` (`paste_allowed`)
- Modify: `courses/views_manage.py` (`PASTE_REFUSAL_MESSAGES`)
- Test: `courses/tests/test_paste_rule.py`, `courses/tests/test_nested_question_gates.py`

**Interfaces:**
- Consumes: `SubtreeFacts.nested_question`, `SubtreeFacts.has_interactive`, `QUIZ_EXCLUDED_TYPE_KEYS` (Task 1).
- Produces: `paste_allowed(unit, marked_join, dest_parent, tab, mode, facts=None, dest_depth=None, positional=False)` — signature unchanged; `unit` is the DESTINATION; new reason key `"interactive_in_quiz"`; `PASTE_REFUSAL_MESSAGES["interactive_in_quiz"]`.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_paste_rule.py` (add `from tests.factories import ContentNodeFactory` and `from tests.factories import make_quiz_unit` to the imports):

```python
def _same_course_units(dest_type="lesson"):
    """(source lesson, destination unit) in ONE course."""
    course, src = make_course_with_unit()
    dest = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type=dest_type, title="D"
    )
    return src, dest


def test_a_cross_unit_copy_in_the_same_course_is_allowed_at_top_level():
    src, dest = _same_course_units()
    subject = _text(src)

    assert builder.paste_allowed(dest, subject, None, "", "copy") == (True, None)


def test_a_cross_unit_copy_in_the_same_course_is_allowed_into_a_slot():
    src, dest = _same_course_units()
    box, slots = _tabs(dest)
    subject = _text(src)

    assert builder.paste_allowed(dest, subject, box, slots[0], "copy") == (True, None)


def test_a_cross_unit_move_is_refused():
    src, dest = _same_course_units()
    subject = _text(src)

    assert builder.paste_allowed(dest, subject, None, "", "move") == (
        False,
        "wrong_unit",
    )


def test_a_cross_course_copy_is_refused():
    """Mutant: drop the course comparison from clause 0 -> RED."""
    _c1, dest = make_course_with_unit()
    _c2, src = make_course_with_unit()
    subject = _text(src)

    assert builder.paste_allowed(dest, subject, None, "", "copy") == (
        False,
        "wrong_unit",
    )


def test_a_callout_holding_a_question_is_refused_into_a_quiz_at_top_level():
    """Clause 2c. Mutant: delete the top-level-branch 2c return -> RED."""
    src, quiz = _same_course_units("quiz")
    box = _callout(src)
    _choice(src, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(quiz, box, None, "", "copy") == (
        False,
        "question_in_quiz",
    )


def test_a_callout_holding_a_question_is_refused_into_a_quiz_slot():
    """Clause 2c, container branch. Mutant: delete that 2c return -> RED."""
    src, quiz = _same_course_units("quiz")
    dest_box = _callout(quiz)
    box = _callout(src)
    _choice(src, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(
        quiz, box, dest_box, CalloutElement.SLOT_ID, "copy"
    ) == (False, "question_in_quiz")


def test_a_callout_holding_a_question_is_allowed_into_a_lesson():
    src, lesson = _same_course_units("lesson")
    box = _callout(src)
    _choice(src, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(lesson, box, None, "", "copy") == (True, None)


def test_a_bare_question_may_be_copied_to_a_quizs_top_level():
    src, quiz = _same_course_units("quiz")
    q = _choice(src)

    assert builder.paste_allowed(quiz, q, None, "", "copy") == (True, None)


def test_an_in_unit_move_of_a_question_callout_inside_a_quiz_is_allowed():
    """2c is CROSS-UNIT ONLY: pre-existing malformed quiz content must stay movable.

    The callout starts NESTED, so the move to top level is a genuine relocation
    and clause 5 (own_slot) cannot be what answers.

    Mutant: drop `cross_unit and` from the top-level 2c check -> RED."""
    course, _src = make_course_with_unit()
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    other, oslots = _tabs(quiz)
    box = _callout(quiz, parent=other, tab=oslots[0])
    _choice(quiz, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(quiz, box, None, "", "move") == (True, None)


def test_an_in_unit_move_of_a_question_callout_into_a_quiz_slot_is_allowed():
    """The container-branch 2c is cross-unit only too.

    Mutant: drop `cross_unit and` from the container-branch 2c check -> RED."""
    course, _src = make_course_with_unit()
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    dest_box, dslots = _tabs(quiz)
    box = _callout(quiz)
    _choice(quiz, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(quiz, box, dest_box, dslots[0], "move") == (
        True,
        None,
    )


def test_an_in_unit_move_of_a_stepper_to_a_quizs_top_level_is_allowed():
    """The top-level 2d is cross-unit only too. The stepper starts nested so the
    move is a genuine relocation.

    Mutant: drop `cross_unit and` from the top-level 2d check -> RED."""
    course, _src = make_course_with_unit()
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    box = _callout(quiz)
    s = _stepper(quiz, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(quiz, s, None, "", "move") == (True, None)


def test_a_stepper_is_refused_into_a_quiz():
    """Clause 2d. Mutant: delete the top-level-branch 2d return -> RED."""
    src, quiz = _same_course_units("quiz")
    s = _stepper(src)

    assert builder.paste_allowed(quiz, s, None, "", "copy") == (
        False,
        "interactive_in_quiz",
    )


def test_a_callout_holding_a_checklist_is_refused_into_a_quiz_at_top_level():
    src, quiz = _same_course_units("quiz")
    box = _callout(src)
    _markdone(src, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(quiz, box, None, "", "copy") == (
        False,
        "interactive_in_quiz",
    )


def test_a_callout_holding_a_checklist_is_refused_into_a_quiz_slot():
    """Mutant: delete the container-branch 2d return -> RED."""
    src, quiz = _same_course_units("quiz")
    dest_box = _callout(quiz)
    box = _callout(src)
    _markdone(src, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(
        quiz, box, dest_box, CalloutElement.SLOT_ID, "copy"
    ) == (False, "interactive_in_quiz")


def test_a_callout_holding_a_checklist_is_allowed_into_a_lesson():
    src, lesson = _same_course_units("lesson")
    box = _callout(src)
    _markdone(src, parent=box, tab=CalloutElement.SLOT_ID)

    assert builder.paste_allowed(lesson, box, None, "", "copy") == (True, None)


def test_an_in_unit_move_of_a_stepper_inside_a_quiz_is_allowed():
    """2d is CROSS-UNIT ONLY: a lesson flipped to quiz keeps its steppers.

    Mutant: drop `cross_unit and` from the container-branch 2d check -> RED."""
    course, _src = make_course_with_unit()
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    dest_box = _callout(quiz)
    s = _stepper(quiz)

    assert builder.paste_allowed(
        quiz, s, dest_box, CalloutElement.SLOT_ID, "move"
    ) == (True, None)
```

In `courses/tests/test_nested_question_gates.py`, in `test_every_paste_reason_has_a_message`, directly under `assert "question_in_quiz" in returned` add:

```python
    # Non-vacuity for clause 2d too: a 2c/2d return factored into a helper would be
    # invisible to this walk -- this line turns that refactor RED.
    assert "interactive_in_quiz" in returned
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_paste_rule.py courses/tests/test_nested_question_gates.py -k "cross_unit or cross_course or quiz or stepper or checklist or bare_question or paste_reason"`
Expected: FAIL — every same-course cross-unit case (the allowed copies AND the cross-unit quiz refusals built with `_same_course_units("quiz")`) answers `(False, "wrong_unit")` from the old clause 0, so the quiz-refusal tests fail on the reason, not on `(True, None)`; the AST test fails on `interactive_in_quiz`. The four `test_an_in_unit_move_of_…` tests and the two cross-course/cross-unit-move refusals **already pass** — they are regression guards, proven only by Step 5's `cross_unit and` / course-comparison mutants.

- [ ] **Step 3: Implement the clauses**

In `paste_allowed`, replace

```python
    if marked_join.unit_id != unit.pk:  # clause 0
        return False, "wrong_unit"
    if dest_parent is not None and dest_parent.unit_id != unit.pk:  # clause 0
        return False, "wrong_unit"

    if facts is None:
        facts = subtree_facts(marked_join)

    if dest_parent is None:
        # The synthetic top-level slot. A non-empty tab here cannot come from the
        # UI -- the parse helper rejects tab-without-parent with a 400 before this
        # runs -- so this is defence, not a reachable branch.
        if tab:
            return False, "unknown_slot"
        if dest_depth is None:
            dest_depth = 1
```

with

```python
    # Clause 0. `unit` is the DESTINATION. The same-unit test comes first and
    # short-circuits, so the common in-unit render never loads marked_join.unit.
    cross_unit = marked_join.unit_id != unit.pk
    if cross_unit:
        if mode == "move":  # a cross-unit MOVE would strand unit-keyed learner data
            return False, "wrong_unit"
        # Defence in depth: the endpoint's course filter already 409s a foreign
        # course's element before this runs (paste_element step 1).
        if marked_join.unit.course_id != unit.course_id:
            return False, "wrong_unit"
    if dest_parent is not None and dest_parent.unit_id != unit.pk:  # clause 0
        return False, "wrong_unit"

    if facts is None:
        facts = subtree_facts(marked_join)
    is_quiz = unit.unit_type == ContentNode.UnitType.QUIZ

    if dest_parent is None:
        # The synthetic top-level slot. A non-empty tab here cannot come from the
        # UI -- the parse helper rejects tab-without-parent with a 400 before this
        # runs -- so this is defence, not a reachable branch.
        if tab:
            return False, "unknown_slot"
        # Clauses 2c / 2d, top-level branch. CROSS-UNIT ONLY: a quiz can already
        # hold such content (imported, or a lesson flipped to quiz), and refusing
        # its in-unit move would be a regression. Literal returns, never a helper:
        # test_every_paste_reason_has_a_message walks these Return nodes.
        if cross_unit and is_quiz and facts.nested_question:  # clause 2c
            return False, "question_in_quiz"
        if cross_unit and is_quiz and facts.has_interactive:  # clause 2d
            return False, "interactive_in_quiz"
        if dest_depth is None:
            dest_depth = 1
```

In the container branch, replace the **whole** clause-2b comment block — both paragraphs, from `# Clause 2b: a question may be nested in a LESSON only.` through `# impossible -- the only way in is pre-existing malformed content.` (nine comment lines, directly above the 2b `if (`) — with:

```python
        # Clause 2b: a question may be nested in a LESSON only. INSIDE this branch
        # deliberately -- pasting a question back to TOP LEVEL in a quiz stays legal,
        # so the dest_parent is None branch must never see this check.
        #
        # It checks the pasted subtree's ROOT only. The rest of the subtree is
        # clause 2c's job, which runs for CROSS-UNIT pastes -- the one new way a
        # question-bearing container can reach a quiz. In-unit, rename_node stops a
        # unit becoming a quiz while such content exists, so the only way in is
        # pre-existing malformed content, which stays movable on purpose.
```

and directly after the 2b `return False, "question_in_quiz"` block (before `if dest_depth is None:`), add:

```python
        if cross_unit and is_quiz and facts.nested_question:  # clause 2c
            return False, "question_in_quiz"
        if cross_unit and is_quiz and facts.has_interactive:  # clause 2d
            return False, "interactive_in_quiz"
```

In the docstring, change the precedence paragraph to:

```
    Reason precedence, fixed and depended on by every caller's tests: wrong_unit,
    into_own_subtree, not_a_container, unknown_slot, type_not_nestable,
    question_in_quiz, interactive_in_quiz, too_deep, own_slot. Clause 4 is tested
    before the container checks so that "into your own child" reports that rather
    than "not a container" when the child is a leaf.

    Cross-unit (marked_join in another unit of the same course): only a COPY is
    admissible (clause 0), and a quiz destination additionally refuses a subtree
    holding a nested question (2c) or any interactive element (2d). Both are
    cross-unit only; in-unit they would block moves of content a quiz already holds.
```

In `courses/views_manage.py`, add to `PASTE_REFUSAL_MESSAGES` directly after the `question_in_quiz` entry:

```python
    "interactive_in_quiz": gettext_lazy(
        "Interactive elements can only be placed in a lesson unit."
    ),
```

(The catalogue entry and Polish translation land in Task 6.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_paste_rule.py courses/tests/test_nested_question_gates.py tests/test_element_paste_view.py tests/test_editor_clip_templates.py tests/test_builder_paste_element.py`
Expected: all PASS. `test_another_units_element_is_refused` (foreign course, copy) stays green through the course comparison.

- [ ] **Step 5: Falsify**

Each mutant from the Step 1 docstrings, by hand: delete each of the four new **whole `if …: return …` statements** in turn (top-level 2c, container 2c, top-level 2d, container 2d) — deleting only the `return` line leaves an empty `if` body, a SyntaxError that reds every test for the wrong reason; drop `cross_unit and` from each of the four 2c/2d checks in turn (top-level 2c, container 2c, top-level 2d, container 2d — each has its own in-unit-quiz-move test); delete the whole `if marked_join.unit.course_id != unit.course_id: return …` statement. Each turns its named test red. Revert each by hand; `git diff`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format courses/builder.py courses/views_manage.py courses/tests/test_paste_rule.py courses/tests/test_nested_question_gates.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/builder.py courses/views_manage.py courses/tests/test_paste_rule.py courses/tests/test_nested_question_gates.py
git commit -m "feat(paste): cross-unit copy rule with quiz clauses 2c/2d"
```

---

### Task 3: `paste_element` — the two-unit copy path

**Files:**
- Modify: `courses/builder.py` (`paste_element`, `_copy_into`)
- Modify: `courses/transfer/importer.py` (`graft_elements` docstring point 2 only)
- Test: `tests/test_builder_paste_element.py`

**Interfaces:**
- Consumes: `unit_children_map`, `subtree_facts` (Task 1); `paste_allowed` (Task 2); existing `_locked_element(course, pk) -> (el, unit)`, `_locked_unit(course, pk) -> unit`, `_check_token`, `_resolve_before(unit, el, before)`, `_parse_scope_ref(unit, parent_ref, tab)`, `_move_into(el, unit, dest_parent, tab_id, anchor=None)`.
- Produces:
  - `paste_element(course, element_pk, parent_ref, tab, mode, unit_token, before=None, dest_unit_pk=None) -> (dest_unit, placed_join)`.
  - `_copy_into(el, source_unit, dest_unit, dest_parent, tab_id, anchor=None) -> new_join`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_builder_paste_element.py`: add imports `from courses.models import CalloutElement`, `from courses.models import ChoiceQuestionElement`, `from courses.models import MarkDoneElement`, `from tests.factories import ContentNodeFactory`. **Delete** `test_a_copy_may_not_name_a_before_target` (it pins the removed refusal; its replacement is the first test below). Append:

```python
def _callout(unit, parent=None, tab=""):
    obj = CalloutElement.objects.create(kind="example")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _other_unit(course, title="Y", unit_type="lesson"):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type=unit_type, title=title
    )


def _bodies(unit, parent=None, tab=""):
    """Ordered bodies of one group -- content, never pks across models."""
    return [
        j.content_object.body
        for j in Element.objects.filter(unit=unit, parent=parent, tab_id=tab)
        .order_by("order", "pk")
        .prefetch_related("content_object")
    ]


def test_an_in_unit_copy_may_name_a_before_target():
    """Replaces test_a_copy_may_not_name_a_before_target: copy now accepts
    `before`. Anchored on a DIFFERENT sibling -- a self-anchor stays a 400."""
    course, unit = make_course_with_unit()
    anchor = _text(unit, body="<p>anchor</p>")
    subject = _text(unit, body="<p>subject</p>")

    paste_element(course, subject.pk, "", "", "copy", _tok(unit), before=anchor.pk)

    assert _bodies(unit) == ["<p>subject</p>", "<p>anchor</p>", "<p>subject</p>"]


def test_a_cross_unit_copy_lands_at_the_end_of_the_chosen_slot():
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x, body="<p>subject</p>")
    box, slots = _tabs(y)
    _text(y, parent=box, tab=slots[0], body="<p>first</p>")
    y.refresh_from_db()

    paste_element(
        course, subject.pk, str(box.pk), slots[0], "copy", _tok(y), dest_unit_pk=y.pk
    )

    assert _bodies(y, parent=box, tab=slots[0]) == ["<p>first</p>", "<p>subject</p>"]


def test_a_cross_unit_copy_before_lands_directly_above_the_anchor():
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x, body="<p>subject</p>")
    _text(y, body="<p>a</p>")
    b = _text(y, body="<p>b</p>")
    y.refresh_from_db()

    paste_element(
        course, subject.pk, "", "", "copy", _tok(y), before=b.pk, dest_unit_pk=y.pk
    )

    assert _bodies(y) == ["<p>a</p>", "<p>subject</p>", "<p>b</p>"]


def test_a_cross_unit_copy_leaves_the_source_untouched_and_bumps_the_destination():
    """Mutant: bump source_unit.updated too -> RED on the X assertion."""
    course, x = make_course_with_unit()
    y = _other_unit(course)
    _text(x, body="<p>one</p>")
    subject = _text(x, body="<p>two</p>")
    x.refresh_from_db()
    y.refresh_from_db()
    x_before, y_before = x.updated, y.updated
    x_rows_before = _bodies(x)

    paste_element(course, subject.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk)

    x.refresh_from_db()
    y.refresh_from_db()
    assert _bodies(x) == x_rows_before
    assert x.updated == x_before
    assert y.updated > y_before


def test_a_cross_unit_copy_returns_the_destination_unit():
    """Mutant: `return source_unit, placed` -> RED."""
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x)
    y.refresh_from_db()

    returned, placed = paste_element(
        course, subject.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk
    )

    assert returned.pk == y.pk  # same model: ContentNode vs ContentNode
    assert placed.unit_id == y.pk


def test_a_cross_unit_copy_shares_the_media_asset():
    course, x = make_course_with_unit()
    y = _other_unit(course)
    asset = make_image_asset(course)
    subject = Element.objects.create(
        unit=x, content_object=ImageElement.objects.create(media=asset)
    )
    y.refresh_from_db()

    _u, placed = paste_element(
        course, subject.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk
    )

    assert placed.content_object.media == asset
    assert MediaAsset.objects.filter(course=course).count() == 1


def test_a_link_to_the_source_unit_still_points_at_the_source_after_the_copy():
    """graft_elements skips _rewrite_links: running it would repoint this link at Y.
    The node pk inside the href is a ContentNode pk compared with a ContentNode pk."""
    course, x = make_course_with_unit()
    y = _other_unit(course)
    body = f'<p><a href="/courses/n/{x.pk}/">back</a></p>'
    subject = _text(x, body=body)
    y.refresh_from_db()

    _u, placed = paste_element(
        course, subject.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk
    )

    assert f'href="/courses/n/{x.pk}/"' in placed.content_object.body


def test_a_question_carries_its_marking_fields_into_a_quiz_unchanged():
    course, x = make_course_with_unit()
    quiz = _other_unit(course, title="Q", unit_type="quiz")
    q = ChoiceQuestionElement.objects.create(
        stem="Pick.", multiple=False, max_attempts=3, max_marks=4
    )
    subject = Element.objects.create(unit=x, content_object=q)
    quiz.refresh_from_db()

    _u, placed = paste_element(
        course, subject.pk, "", "", "copy", _tok(quiz), dest_unit_pk=quiz.pk
    )

    copied = placed.content_object
    assert (copied.marking_mode, copied.max_attempts, copied.max_marks) == (
        q.marking_mode,
        q.max_attempts,
        q.max_marks,
    )


def test_a_stale_destination_token_is_a_conflict():
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x)

    with pytest.raises(ConflictError):
        paste_element(
            course,
            subject.pk,
            "",
            "",
            "copy",
            "2020-01-01T00:00:00+00:00",
            dest_unit_pk=y.pk,
        )


def test_a_stale_source_token_is_irrelevant():
    """X is never token-checked: the author posts Y's token only.

    Mutant: check the token against source_unit instead -> RED here (Y's token
    does not match X). test_a_stale_destination_token_is_a_conflict stays green
    under that mutant -- its hard-coded 2020 token fails against X too."""
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x)
    y.refresh_from_db()

    paste_element(course, subject.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk)


def test_a_deleted_marked_element_is_a_conflict():
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x)
    pk = subject.pk
    subject.delete()
    y.refresh_from_db()

    with pytest.raises(ConflictError):
        paste_element(course, pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk)


def test_an_element_of_another_course_is_a_conflict():
    course, y = make_course_with_unit()
    _c2, foreign_unit = make_course_with_unit()
    foreign = _text(foreign_unit)
    y.refresh_from_db()

    with pytest.raises(ConflictError):
        paste_element(course, foreign.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk)


def test_a_non_numeric_element_is_a_conflict():
    course, y = make_course_with_unit()

    with pytest.raises(ConflictError):
        paste_element(course, "abc", "", "", "copy", _tok(y), dest_unit_pk=y.pk)


def test_a_cross_unit_move_is_refused_by_the_rule():
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x)
    y.refresh_from_db()

    with pytest.raises(PlacementRefused) as exc:
        paste_element(course, subject.pk, "", "", "move", _tok(y), dest_unit_pk=y.pk)

    assert exc.value.reason_key == "wrong_unit"


def test_the_export_reads_the_source_unit():
    """Mutant: call build_element_export(dest_unit, el) inside _copy_into -> the
    export's assert fires, _copy_into wraps it into TransferError, and this test
    goes RED on the TransferError (nothing is created in Y either)."""
    course, x = make_course_with_unit()
    y = _other_unit(course)
    subject = _text(x)
    y.refresh_from_db()

    paste_element(course, subject.pk, "", "", "copy", _tok(y), dest_unit_pk=y.pk)

    assert Element.objects.filter(unit=y).count() == 1


# --- refusals on the ENFORCING path (the render is advisory) -----------------


def _refused(course, subject, dest_unit, parent_ref="", tab=""):
    dest_unit.refresh_from_db()
    with pytest.raises(PlacementRefused) as exc:
        paste_element(
            course,
            subject.pk,
            parent_ref,
            tab,
            "copy",
            _tok(dest_unit),
            dest_unit_pk=dest_unit.pk,
        )
    return exc.value.reason_key


def test_a_question_callout_into_a_quiz_is_refused_on_the_enforcing_path():
    """Mutant: compute the service's facts from unit_children_map(dest_unit) -> RED
    (the root's children are missing, so nested_question reads False)."""
    course, x = make_course_with_unit()
    quiz = _other_unit(course, title="Q", unit_type="quiz")
    box = _callout(x)
    Element.objects.create(
        unit=x,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    count_before = Element.objects.filter(unit=quiz).count()

    assert _refused(course, box, quiz) == "question_in_quiz"
    assert Element.objects.filter(unit=quiz).count() == count_before


def test_a_checklist_callout_into_a_quiz_is_refused_on_the_enforcing_path():
    """Same mutant as above -> RED (has_interactive reads False)."""
    course, x = make_course_with_unit()
    quiz = _other_unit(course, title="Q", unit_type="quiz")
    box = _callout(x)
    Element.objects.create(
        unit=x,
        content_object=MarkDoneElement.objects.create(prompt="Tick"),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    count_before = Element.objects.filter(unit=quiz).count()

    assert _refused(course, box, quiz) == "interactive_in_quiz"
    assert Element.objects.filter(unit=quiz).count() == count_before


def test_a_two_level_container_into_a_depth_three_slot_is_too_deep():
    """Destination depth is PINNED to 3 (a slot of a container at depth 2): the
    root alone (a container, cap 3) would be admitted, the whole subtree is not.
    A deeper slot would refuse the root alone too and let the mutant survive.
    Same mutant as above -> RED."""
    course, x = make_course_with_unit()
    y = _other_unit(course)
    outer = _callout(x)
    _callout(x, parent=outer, tab=CalloutElement.SLOT_ID)  # callout > callout
    d1 = _callout(y)
    d2 = _callout(y, parent=d1, tab=CalloutElement.SLOT_ID)  # d2 is at depth 2
    count_before = Element.objects.filter(unit=y).count()

    reason = _refused(
        course, outer, y, parent_ref=str(d2.pk), tab=CalloutElement.SLOT_ID
    )

    assert reason == "too_deep"
    assert Element.objects.filter(unit=y).count() == count_before
```

The callers' explicit `count_before` assertions are what prove nothing was created in the destination.

Confirm the question's marking field names before running: `grep -n "marking_mode\|max_attempts\|max_marks" courses/models.py | head` (`ImageElement`'s FK is `media`; `PlacementRefused` exposes `.reason_key`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder_paste_element.py`
Expected: FAIL — `TypeError: paste_element() got an unexpected keyword argument 'dest_unit_pk'`, and `test_an_in_unit_copy_may_name_a_before_target` fails with `NestingError: before is a move-only argument`.

- [ ] **Step 3: Rewrite `paste_element`**

Replace the whole `paste_element` function (decorator, signature, docstring and body up to `return unit, placed`) with:

```python
@transaction.atomic
def paste_element(
    course,
    element_pk,
    parent_ref,
    tab,
    mode,
    unit_token,
    before=None,
    dest_unit_pk=None,
):
    """Move or copy the marked element's subtree into (parent_ref, tab) of the
    DESTINATION unit.

    Returns (dest_unit, placed_join) -- the destination, because the view rebinds
    `unit` from this tuple and renders its fragments (returning the source would
    paint unit X's editor into Y's page); the join, because the view derives the
    post-paste open-set by walking placed_join.parent upward.

    `dest_unit_pk` is the unit the author is looking at (the view passes the posted
    `unit`). None -- callers that predate cross-unit copy -- runs the in-unit path
    unchanged. Otherwise an unlocked lookup of the element's unit decides the path.

    LOCK ORDER (cross-unit). Every element-level writer locks exactly one unit, and
    in-unit writers on an element take it through _locked_element (element row +
    unit row in one joined SELECT ... FOR UPDATE). The copy takes the SOURCE through
    that same shape and the two unit rows in ascending pk order, so two opposite
    copies (X->Y, Y->X) cannot deadlock with each other, and a copy holding Y while
    waiting for (e, X) cannot deadlock with an element-level writer on X, which
    never wants Y. The general rule it does NOT cover: any transaction that locks or
    writes more than one unit row in an order other than ascending pk (sibling
    reorders and reparents, node add/delete compaction, subtree flag updates,
    cascade deletes) can deadlock with a copy. Postgres aborts one side (40P01): if
    it is the copy, element_paste answers 409; if it is the other writer, that
    endpoint answers 500 -- rare, consistent, accepted (spec D11).

    Locks first, token second, rule third: paste_allowed is re-evaluated INSIDE this
    transaction and these locks, so a concurrent add into the destination slot
    cannot interleave between the render-time check and the placement. The token is
    checked against the DESTINATION only; the source is only read, and its lock
    stops it changing mid-export.

    `before` names the join the subtree must land directly ABOVE (move or copy). The
    destination slot is then DERIVED from that join, so `parent_ref`/`tab` are
    ignored. Resolving the anchor here, inside the lock, keeps the placement
    race-free.
    """
    if mode not in ("move", "copy"):
        raise NestingError("unknown mode")

    facts = None
    if dest_unit_pk is None:
        el, dest_unit = _locked_element(course, element_pk)
        _check_token(dest_unit.updated, unit_token)
        source_unit = dest_unit
    else:
        try:
            dest_pk = int(dest_unit_pk)
            src_pk = (
                Element.objects.filter(pk=element_pk, unit__course=course)
                .values_list("unit_id", flat=True)
                .first()
            )
        except (ValueError, TypeError):
            raise ConflictError() from None
        if src_pk is None:  # gone, or another course's element
            raise ConflictError()
        if src_pk == dest_pk:
            el, dest_unit = _locked_element(course, element_pk)
            if dest_unit.pk != dest_pk:
                raise ConflictError()
            _check_token(dest_unit.updated, unit_token)
            source_unit = dest_unit
        else:
            if src_pk < dest_pk:
                el, source_unit = _locked_element(course, element_pk)
                dest_unit = _locked_unit(course, dest_pk)
            else:
                dest_unit = _locked_unit(course, dest_pk)
                el, source_unit = _locked_element(course, element_pk)
            if source_unit.pk != src_pk:
                raise ConflictError()
            _check_token(dest_unit.updated, unit_token)
            # Once, from the SOURCE unit's map: the destination's map does not hold
            # the marked subtree. In-unit keeps facts=None -- a whole-unit map would
            # make every in-unit paste of a leaf load the entire unit.
            facts = subtree_facts(el, children_map=unit_children_map(source_unit))

    anchor = None
    if before in (None, ""):
        dest_parent, tab_id = _parse_scope_ref(dest_unit, parent_ref, tab)
    else:
        anchor = _resolve_before(dest_unit, el, before)
        dest_parent, tab_id = anchor.parent, anchor.tab_id

    ok, reason = paste_allowed(
        dest_unit,
        el,
        dest_parent,
        tab_id,
        mode,
        facts=facts,
        positional=anchor is not None,
    )
    if not ok:
        raise PlacementRefused(reason)

    if mode == "move":  # reachable in-unit only: clause 0 refuses a cross-unit move
        placed = _move_into(el, dest_unit, dest_parent, tab_id, anchor=anchor)
    else:
        placed = _copy_into(el, source_unit, dest_unit, dest_parent, tab_id, anchor)

    dest_unit.save(update_fields=["updated"])
    return dest_unit, placed
```

Keep `_resolve_before` unchanged (its self-anchor `NestingError` stays for copies too). If `_resolve_before`'s docstring says `before` is move-only, change that sentence to "move or copy".

- [ ] **Step 4: Rewrite `_copy_into`**

Replace `_copy_into` with:

```python
def _copy_into(el, source_unit, dest_unit, dest_parent, tab_id, anchor=None):
    """Serialise the subtree out of SOURCE_UNIT and re-materialise it in the
    destination slot of DEST_UNIT (the same unit for an in-unit copy).

    The same three-step shape duplicate_element uses. Runs inside paste_element's
    transaction, holding both units' locks (source and destination).

    build_element_export needs the SOURCE: it asserts the root belongs to the unit
    it exports. The media map points at the source's MediaAsset rows, which is
    correct because both units are in the same course.
    """
    from courses.transfer import export as _export
    from courses.transfer import importer as _importer
    from courses.transfer.schema import TransferError

    try:
        document, media_assets, problems = _export.build_element_export(
            source_unit, el
        )
        if problems:
            # build_export RECORDS a dangling GFK and continues, dropping the broken
            # join and its ENTIRE subtree from the payload. With
            # drop_missing_media=False no media problem can be produced, so a
            # non-empty list means exactly one thing -- and copying anyway would
            # yield a silently thinned subtree with a 200.
            raise TransferError(_("This element is damaged and cannot be copied."))
        media_map = {mid: asset for (mid, asset, _ph) in media_assets}
        new_join = _importer.graft_elements(document, media_map, dest_unit)
    except TransferError:
        raise  # already normalized by graft_elements' _run_import
    except Exception as exc:
        # build_element_export is NOT wrapped by _run_import, so a serializer edge
        # or the export's own assert would otherwise escape as a 500.
        raise TransferError(str(exc) or "Copy failed.") from exc

    # The graft returns a PARENTLESS root: the payload root has no `parent`, and
    # _create_elements' second pass skips exactly those rows. place_element will not
    # fix it either -- it saves only `order`.
    new_join.parent = dest_parent
    new_join.tab_id = tab_id
    new_join.save(update_fields=["parent", "tab_id"])
    # None appends; an anchor lands the copy directly above it.
    ordering.place_element(new_join, dest_unit, None, before=anchor)
    return new_join
```

- [ ] **Step 5: Rewrite the `graft_elements` docstring point 2**

In `courses/transfer/importer.py`, replace point 2 of the `graft_elements` docstring (the paragraph beginning "2. No `_rewrite_links`, because for an element-scoped export that call is provably a NO-OP") with the same number of lines, saying: `_rewrite_links` is skipped, and the skip is a CORRECTNESS REQUIREMENT, not dead work. For a cross-unit graft `link_nodes` can name the SOURCE unit, and the fabricated node_map maps the source unit's export id to the DESTINATION, so running `_rewrite_links` would silently repoint a link to the source unit at the destination. A link to any node outside the export is left alone under `on_missing="keep"` either way. Count the lines before and after (`sed -n '/def graft_elements/,/"""$/p' courses/transfer/importer.py | wc -l`) and make them equal; the code is unchanged.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder_paste_element.py courses/tests/test_paste_rule.py tests/test_element_paste_view.py courses/tests/test_nested_question_gates.py`
Expected: all PASS.

- [ ] **Step 7: Falsify**

By hand, one at a time:
1. `_check_token(source_unit.updated, unit_token)` in the cross-unit branch → `test_a_stale_source_token_is_irrelevant` red (the destination-token test stays green: its 2020 token fails either way).
2. Add `source_unit.save(update_fields=["updated"])` before the return → `test_a_cross_unit_copy_leaves_the_source_untouched_and_bumps_the_destination` red.
3. `return source_unit, placed` → `test_a_cross_unit_copy_returns_the_destination_unit` red.
4. In `_copy_into`, `build_element_export(dest_unit, el)` → `test_the_export_reads_the_source_unit` red with `TransferError`.
5. `facts = subtree_facts(el, children_map=unit_children_map(dest_unit))` → the three enforcing-path refusal tests red.
6. In `courses/transfer/importer.py`, inside `graft_elements`'s `work()`, call `_rewrite_links(document, node_map, created, on_missing="keep", report=None)` after `_create_elements` (`report=None`, never a list: `_rewrite_links` calls `report.get(...)` when a report is given, and a list would raise AttributeError → TransferError, a red for the wrong reason) → `test_a_link_to_the_source_unit_still_points_at_the_source_after_the_copy` red, and the red must be the test's `href=".../n/{x.pk}/"` assertion failing **on a successful copy** (the link repointed at Y), not a `TransferError`. If it stays green, the test is vacuous — `link_nodes` does not contain X — and must be fixed before committing.
Revert each by hand; `git diff`.

- [ ] **Step 8: Commit**

```bash
uv run ruff format courses/builder.py courses/transfer/importer.py tests/test_builder_paste_element.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/builder.py courses/transfer/importer.py tests/test_builder_paste_element.py
git commit -m "feat(paste): two-unit copy path in paste_element"
```

---

### Task 4: `_clip_context` cross-unit branch and `copy_units_tree`

**Files:**
- Modify: `courses/views_manage.py` (`copy_units_tree` new; `_clip_context`; `element_clip` docstring)
- Test: `tests/test_element_paste_view.py`

**Interfaces:**
- Consumes: `builder_svc.unit_children_map`, `builder_svc.subtree_facts`, `builder_svc.enumerate_slots`, `builder_svc.paste_allowed`, `builder_svc.slot_key` (Tasks 1–2); `_children_map(course)` (existing).
- Produces:
  - `copy_units_tree(course) -> (pruned_map: dict, pruned_top: list, available: bool)`.
  - `_clip_context(request, unit)` keys (both builders): `clip_active`, `clip_element_pk`, `clip_label`, `move_slots`, `copy_slots`, `before_slots`, `clip_noop_pk`, **`clip_mode`**, **`clip_source_unit`**, **`clip_nothing_fits`**, **`copy_units_map`**, **`copy_units_top`**, **`copy_units_available`**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_element_paste_view.py` (add `from courses.models import CalloutElement`, `from courses.models import ChoiceQuestionElement`, `from courses.views_manage import copy_units_tree`, `from tests.factories import make_quiz_unit` to the imports):

```python
def _unit(course, title, unit_type="lesson", parent=None, kind="unit"):
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title
    )


def _editor_get(client, course, unit):
    unit.refresh_from_db()
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )


def test_copy_units_tree_keeps_units_at_any_depth_and_drops_empty_containers():
    course = CourseFactory()
    root_unit = _unit(course, "RootUnit")
    part = _unit(course, "Part", kind="part", unit_type="")
    chapter = _unit(course, "Chapter", kind="chapter", unit_type="", parent=part)
    section = _unit(course, "Section", kind="section", unit_type="", parent=chapter)
    deep = _unit(course, "Deep", parent=section)
    empty_section = _unit(
        course, "EmptySection", kind="section", unit_type="", parent=chapter
    )

    pruned, top, available = copy_units_tree(course)

    assert top == [root_unit, part] or top == [part, root_unit]
    assert pruned[chapter.pk] == [section]  # the unit-less section is dropped
    assert empty_section not in pruned.get(chapter.pk, [])
    assert pruned[section.pk] == [deep]
    assert available is True


def test_copy_units_tree_reports_a_one_unit_course_as_unavailable():
    course = CourseFactory()
    _unit(course, "Only")

    _pruned, _top, available = copy_units_tree(course)

    assert available is False


def test_copy_units_tree_reports_two_units_as_available():
    course = CourseFactory()
    _unit(course, "One")
    _unit(course, "Two")

    assert copy_units_tree(course)[2] is True


def test_a_mark_in_another_unit_of_the_course_offers_copy_only(client):
    """The cross-unit branch. Mutant: fill move_slots in the cross-unit branch
    (e.g. `move_slots = set(copy_slots)`) -> RED."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    box, slots = _tabs(y)
    _mark(client, course, x, subject)

    resp = _editor_get(client, course, y)

    ctx = resp.context
    assert ctx["clip_active"] is True
    assert ctx["clip_mode"] == "copy"
    assert ctx["clip_source_unit"] == x
    assert ctx["clip_element_pk"] == str(subject.pk)
    assert ctx["move_slots"] == set()
    assert slot_key(box.pk, slots[0]) in ctx["copy_slots"]
    assert ctx["before_slots"] == ctx["copy_slots"]
    assert ctx["clip_noop_pk"] == ""
    assert ctx["clip_nothing_fits"] is False
    assert ctx["copy_units_available"] is True


def test_the_source_unit_keeps_move_mode_and_no_source_link(client):
    course, x = _seed(client)
    _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    ctx = _editor_get(client, course, x).context

    assert ctx["clip_mode"] == "move"
    assert ctx["clip_source_unit"] is None


def test_a_mark_from_another_course_is_ignored_and_kept(client):
    """D8. Mutant: pop the session mark on the foreign-course path -> RED."""
    course, unit = _seed(client)
    other_course = CourseFactory(owner=course.owner)
    foreign_unit = _unit(other_course, "F")
    foreign = _text(foreign_unit)
    _mark(client, other_course, foreign_unit, foreign)
    assert client.session["element_clip"]["element"] == foreign.pk

    ctx = _editor_get(client, course, unit).context

    assert ctx["clip_active"] is False
    assert client.session["element_clip"]["element"] == foreign.pk


def test_a_mark_whose_source_unit_was_deleted_is_cleared(client):
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)
    x.delete()

    ctx = _editor_get(client, course, y).context

    assert ctx["clip_active"] is False
    assert "element_clip" not in client.session


def test_a_non_numeric_session_unit_is_cleared(client):
    course, unit = _seed(client)
    session = client.session
    session["element_clip"] = {"unit": "abc", "element": 1}
    session.save()

    ctx = _editor_get(client, course, unit).context

    assert ctx["clip_active"] is False
    assert "element_clip" not in client.session


def test_a_partial_session_mark_is_cleared_as_dead(client):
    """`none` is exactly `not clip`; {"unit": X} takes lookup step 1 and misses."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    session = client.session
    session["element_clip"] = {"unit": x.pk}
    session.save()

    ctx = _editor_get(client, course, y).context

    assert ctx["clip_active"] is False
    assert "element_clip" not in client.session


def test_a_question_callout_marked_for_a_quiz_fits_nowhere(client):
    """Mutant: never set clip_nothing_fits (always False) -> RED."""
    course, x = _seed(client)
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    box = Element.objects.create(
        unit=x, content_object=CalloutElement.objects.create(kind="example")
    )
    Element.objects.create(
        unit=x,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    _mark(client, course, x, box)

    ctx = _editor_get(client, course, quiz).context

    assert ctx["copy_slots"] == set()
    assert ctx["clip_nothing_fits"] is True


def test_the_copy_list_is_built_only_while_a_mark_is_active(client, monkeypatch):
    """0 calls unmarked, EXACTLY 1 marked (so a never-built tree also goes red).

    Mutant: build copy_units_tree unconditionally in _clip_context -> RED (1 call
    on the unmarked render)."""
    from courses import views_manage

    course, unit = _seed(client)
    _unit(course, "Y")
    subject = _text(unit)
    calls = []
    real = views_manage._children_map

    def _counting(c):
        calls.append(c)
        return real(c)

    monkeypatch.setattr(views_manage, "_children_map", _counting)

    _editor_get(client, course, unit)
    assert calls == []

    _mark(client, course, unit, subject)
    calls.clear()
    _editor_get(client, course, unit)
    assert len(calls) == 1


def test_a_cross_unit_marked_render_stays_within_its_query_ceiling(
    client, django_assert_max_num_queries
):
    """An order-of-magnitude tripwire on the CROSS-UNIT marked render.

    MEASURED BASELINE: <n> queries. To re-measure, set the ceiling to 1
    temporarily and read the real count from the failure message; the ceiling is
    that count + 5. At
    least 10 slots in Y and 2 descendants under the marked element, so a per-slot
    re-walk of the source clears the margin.

    Mutant: drop `facts=facts` from the cross-unit paste_allowed loop -> RED.
    NOT caught (stated, not claimed): dropping select_related("unit") -- a single
    query, which no sane ceiling separates (see the same-unit sibling test)."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    for _ in range(5):
        _tabs(y)  # 2 slots each -> 10 container slots
    root, rslots = _tabs(x)
    _text(x, parent=root, tab=rslots[0])
    _text(x, parent=root, tab=rslots[1])
    assert _mark(client, course, x, root).status_code == 200

    with django_assert_max_num_queries(60):  # tightened to measured + 5 in Step 5b
        _editor_get(client, course, y)


def test_a_cross_unit_marked_render_never_falls_back_to_walking_parents(
    client, monkeypatch
):
    """Mutant: drop `dest_depth=dest_depth` from the cross-unit loop -> RED."""
    from courses import builder as builder_mod

    course, x = _seed(client)
    y = _unit(course, "Y")
    outer, oslots = _tabs(y)
    _tabs(y, parent=outer, tab=oslots[0])
    subject = _text(x)
    assert _mark(client, course, x, subject).status_code == 200

    def _boom(_join):
        raise RuntimeError("paste_allowed must receive dest_depth from the render")

    monkeypatch.setattr(builder_mod, "element_depth", _boom)

    assert _editor_get(client, course, y).status_code == 200
```

The ceiling's starting value `60` is only a loose first bound; Step 5b measures and tightens it, and it must not be committed unmeasured.

`ContentNodeFactory` defaults: check `kind`/`unit_type` for containers (`grep -n "class ContentNodeFactory" -A12 tests/factories.py`); if `unit_type=""` fails validation for a container, pass whatever the factory uses for non-units (the builder's own container tests show it).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_element_paste_view.py -k "copy_units or another_unit or source_unit or another_course or deleted or non_numeric or partial or fits_nowhere or copy_list or cross_unit_marked"`
Expected: FAIL — `ImportError: cannot import name 'copy_units_tree'`, then `KeyError: 'clip_mode'`.

- [ ] **Step 3: Add `copy_units_tree`**

In `courses/views_manage.py`, directly after `_children_map`, add:

```python
def copy_units_tree(course):
    """(pruned_map, pruned_top, available) for the "Copy to another unit…" list.

    One query (_children_map) plus one post-order fold, the same shape as
    _fold_flag_counts: every container with no unit anywhere below it is dropped
    from its parent's list and from the roots, so the template iterates only what it
    renders -- a Django template cannot look ahead. `available` is True iff the
    course has at least two units (with one, the list would offer nothing).
    """
    cmap = _children_map(course)
    pruned = {}
    units = [0]

    def keep(parent_pk):
        kept = []
        for node in cmap.get(parent_pk, []):
            if node.kind == ContentNode.Kind.UNIT:
                units[0] += 1
                kept.append(node)
            elif keep(node.pk):
                kept.append(node)
        if kept:
            pruned[parent_pk] = kept
        return bool(kept)

    keep(None)
    return pruned, pruned.get(None, []), units[0] >= 2
```

- [ ] **Step 4: Rewrite `_clip_context`**

Replace `_clip_context`'s signature line, docstring and body **from the signature through `facts = builder_svc.subtree_facts(marked, children_map=children_map)`** (inclusive) with the block below. Everything from `move_slots, copy_slots = set(), set()` down to the final `return {...}` is **kept** — the block is NOT a whole-function replacement:

```python
def _clip_context(request, unit):
    """The mark-dependent context keys, for BOTH context builders -- thirteen:
    clip_active, clip_element_pk, clip_label, move_slots, copy_slots, before_slots,
    clip_noop_pk, clip_mode, clip_source_unit, clip_nothing_fits, copy_units_map,
    copy_units_top, copy_units_available.

    When nothing is marked this returns empty values and does NO query -- the
    common render pays nothing. While a mark IS pending the cost is paid on every
    response, which is why enumerate_slots is one query and why its children_map is
    reused by subtree_facts rather than re-walked.

    The mark is classified against `unit`:
      - same unit: move + copy slots, move-before rows (today's behaviour);
      - another unit of THIS course: copy slots and copy-before rows only -- the
        mark "follows the author" (spec D3/D7);
      - another course: ignored and KEPT (D8; the author may go back);
      - its element or unit gone, or the session malformed: cleared.
    """
    empty = {
        "clip_active": False,
        "clip_element_pk": "",
        "clip_label": "",
        "move_slots": set(),
        "copy_slots": set(),
        "before_slots": set(),
        "clip_noop_pk": "",
        "clip_mode": "",
        "clip_source_unit": None,
        "clip_nothing_fits": False,
        "copy_units_map": {},
        "copy_units_top": [],
        "copy_units_available": False,
    }
    clip = request.session.get(CLIP_SESSION_KEY) or {}
    if not clip:
        return empty
    if clip.get("unit") != unit.pk:
        return _cross_unit_clip_context(request, unit, clip, empty)

    # Same unit. Wrapped for the same reason as _clip_unit above: filter(pk=...)
    # raises ValueError/TypeError when a non-numeric pk is evaluated. element_clip
    # always writes an int() here, so this is unreachable through that path today --
    # but a session written any other way would otherwise raise on EVERY editor
    # render for that user until the cookie is cleared, which is a sticky failure
    # worth guarding cheaply rather than trusting the only writer forever.
    try:
        marked = unit.elements.filter(pk=clip.get("element")).first()
    except (ValueError, TypeError):
        marked = None
    if marked is None:
        request.session.pop(CLIP_SESSION_KEY, None)
        return empty

    pairs, children_map = builder_svc.enumerate_slots(unit)
    facts = builder_svc.subtree_facts(marked, children_map=children_map)
```

…keep the existing same-unit body from `move_slots, copy_slots = set(), set()` through the existing `obj = marked.content_object` line **unchanged**. Insert exactly one new line directly **before** that existing `obj = …` line:

```python
    units_map, units_top, units_available = copy_units_tree(unit.course)
```

and extend the existing final `return {...}` dict (its seven keys and their comments stay as they are) with these six entries:

```python
        "clip_mode": "move",
        "clip_source_unit": None,
        "clip_nothing_fits": False,
        "copy_units_map": units_map,
        "copy_units_top": units_top,
        "copy_units_available": units_available,
```

Then add, directly below `_clip_context`:

```python
def _cross_unit_clip_context(request, unit, clip, empty):
    """The mark lives in ANOTHER unit than `unit` (spec §1 lookups 1-5)."""
    try:
        # .get: a hand-written session missing a key gives None, which matches
        # nothing and takes the dead-mark path instead of an unguarded KeyError.
        marked = (
            Element.objects.select_related("unit")
            .filter(pk=clip.get("element"), unit_id=clip.get("unit"))
            .first()
        )
    except (ValueError, TypeError):
        marked = None
    if marked is None:  # element or unit gone, in whatever course -- or malformed
        request.session.pop(CLIP_SESSION_KEY, None)
        return empty
    if marked.unit.course_id != unit.course_id:
        return empty  # D8: another course's mark is ignored, NOT cleared
    if marked.unit_id == unit.pk:
        # Only a hand-written session whose `unit` is a numeric STRING gets here
        # (it failed the int comparison above). Classify on the loaded row, never on
        # the session value's type, so this branch can never run for its own unit.
        request.session.pop(CLIP_SESSION_KEY, None)
        return empty

    obj = marked.content_object  # one GFK: _slot_cap, has_interactive, the label
    # The SOURCE unit's map: the destination's does not hold the marked subtree.
    facts = builder_svc.subtree_facts(
        marked, children_map=builder_svc.unit_children_map(marked.unit)
    )
    pairs, _dest_map = builder_svc.enumerate_slots(unit)
    copy_slots = set()
    for parent, tab, dest_depth in pairs:
        ok, _reason = builder_svc.paste_allowed(
            unit, marked, parent, tab, "copy", facts=facts, dest_depth=dest_depth
        )
        if ok:
            key = builder_svc.slot_key(parent.pk if parent is not None else None, tab)
            copy_slots.add(key)

    units_map, units_top, units_available = copy_units_tree(unit.course)
    return {
        "clip_active": True,
        # STRINGIFIED, as in the same-unit branch. Load-bearing here too:
        # paste_before_button hides itself whenever this is empty, and the cancel
        # form posts it.
        "clip_element_pk": str(marked.pk),
        "clip_label": marked.title or element_summary(obj),
        "move_slots": set(),  # D7: move never appears outside the source unit
        "copy_slots": copy_slots,
        # The only rule separating an append from a positional placement is clause
        # 5, which is move-only -- so every copy slot also takes copy-before rows.
        "before_slots": set(copy_slots),
        "clip_noop_pk": "",  # a copy is never a no-op
        "clip_mode": "copy",
        "clip_source_unit": marked.unit,
        "clip_nothing_fits": not copy_slots,
        "copy_units_map": units_map,
        "copy_units_top": units_top,
        "copy_units_available": units_available,
    }
```

In `element_clip`'s docstring, change the sentence about `_locked_element(course, ...)` to say the paste re-resolves the element through `_locked_element(course, ...)` **and** locks the destination unit when it differs (see `builder.paste_element`).

In `test_the_clip_context_keys_reach_both_render_paths`, change "must carry the five clip keys" to "must carry the thirteen clip keys" and add, to both halves, `assert resp.context["clip_mode"] == "move"`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_element_paste_view.py tests/test_element_clip_view.py tests/test_editor_clip_templates.py courses/tests/test_paste_rule.py`
Expected: all PASS. `tests/test_element_clip_view.py` pins `_clip_context`'s guarded-lookup behaviour, which this task rewrites.

- [ ] **Step 5b: Measure and tighten the query ceiling**

In `test_a_cross_unit_marked_render_stays_within_its_query_ceiling`, temporarily set the ceiling to `1` and run `uv run pytest tests/test_element_paste_view.py -k cross_unit_marked_render_stays` — the failure message prints the real count. Set the ceiling to that count + 5, replace the docstring's `<n>` placeholder in the `MEASURED BASELINE:` line with the count, and re-run: PASS. The `<n>` placeholder must not survive into the commit.

- [ ] **Step 6: Falsify**

By hand: `move_slots = set(copy_slots)` in the cross-unit return → `test_a_mark_in_another_unit_of_the_course_offers_copy_only` red; add `request.session.pop(CLIP_SESSION_KEY, None)` before `return empty  # D8` → `test_a_mark_from_another_course_is_ignored_and_kept` red; `"clip_nothing_fits": False` → `test_a_question_callout_marked_for_a_quiz_fits_nowhere` red; move the **same-unit branch's** `units_map, units_top, units_available = copy_units_tree(unit.course)` line in `_clip_context` (not the one in `_cross_unit_clip_context`) above `if not clip:` → `test_the_copy_list_is_built_only_while_a_mark_is_active` red; in `copy_units_tree`, replace `elif keep(node.pk): kept.append(node)` with `else: keep(node.pk); kept.append(node)` (no pruning) → `test_copy_units_tree_keeps_units_at_any_depth_and_drops_empty_containers` red on `assert pruned[chapter.pk] == [section]` (it becomes `[section, empty_section]`; that line fails before the membership check is reached); drop `facts=facts` from the cross-unit loop → ceiling red; drop `dest_depth=dest_depth` → the `element_depth` test red. Revert each; `git diff`.

- [ ] **Step 7: Commit**

```bash
uv run ruff format courses/views_manage.py tests/test_element_paste_view.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/views_manage.py tests/test_element_paste_view.py
git commit -m "feat(paste): the mark follows the author to other units of the course"
```

---

### Task 5: `element_paste` — stale-form check, move reload, deadlock mapping

**Files:**
- Modify: `courses/views_manage.py` (`element_paste`)
- Modify: `courses/templatetags/courses_manage_extras.py` (`paste_buttons`, `paste_before_button`)
- Modify: `templates/courses/manage/editor/_paste_buttons.html`, `templates/courses/manage/editor/_paste_before_button.html` (hidden `element`, `mode` only — icons are Task 6)
- Modify: `courses/tests/test_nested_question_gates.py` (endpoint test payload)
- Test: `tests/test_element_paste_view.py`

**Interfaces:**
- Consumes: `paste_element(..., dest_unit_pk=...)` (Task 3); `clip_mode` context key (Task 4).
- Produces: both paste inclusion tags return `clip_element_pk`; `paste_before_button` returns `mode`. Every paste form posts `element`.

- [ ] **Step 1: Migrate the test helpers (explicit `element`)**

In `tests/test_element_paste_view.py`, change the helpers:

```python
def _paste(client, course, unit, parent, tab, mode="move", token=None, *, element):
    """`element` is REQUIRED and passed by the caller -- never read from the
    session -- so a test's pre-assertion compares two independently sourced
    values. Pass element=None to post no `element` field at all."""
    data = {
        "ctx": "editor",
        "parent": "" if parent is None else parent.pk,
        "tab": tab,
        "mode": mode,
        "unit": unit.pk,
        "unit_token": token if token is not None else unit.updated.isoformat(),
    }
    if element is not None:
        data["element"] = element if isinstance(element, (int, str)) else element.pk
    return client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _paste_before(client, course, unit, anchor, mode="move", token=None, *, element):
    """The before-path posts NO parent/tab: the slot is derived from the anchor."""
    data = {
        "ctx": "editor",
        "mode": mode,
        "before": anchor if isinstance(anchor, int) else anchor.pk,
        "unit": unit.pk,
        "unit_token": token if token is not None else unit.updated.isoformat(),
    }
    if element is not None:
        data["element"] = element if isinstance(element, (int, str)) else element.pk
    return client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _assert_posts_the_mark(client, element):
    """Pre-assertion for every 409 test: the `element` ARGUMENT the caller hands the
    helper equals the session mark. It does not inspect the POST data -- that the
    helpers really transmit the field is pinned by
    test_a_paste_before_a_sibling_reorders_within_the_slot_and_clears_the_mark,
    which 409s instead of reordering if `element` is not posted."""
    assert client.session["element_clip"]["element"] == element.pk
```

Update **every** call of `_paste` / `_paste_before` in the file to pass `element=<the marked element>` (the `subject` of that test; `element=None` in `test_a_paste_with_no_mark_is_a_409`). Update the inline `client.post` to `manage_element_paste` in `test_a_vanished_destination_is_a_422_not_a_400` to include `"element": <marked>.pk` in its data dict. Verify by running the file (`uv run pytest tests/test_element_paste_view.py`): `element` is a required keyword-only argument, so a missed `_paste` / `_paste_before` call fails as `TypeError: … missing 1 required keyword-only argument: 'element'` (a line-based grep cannot check calls that span lines). The inline `client.post` is not covered by that: check it by eye with `grep -n -A8 "manage_element_paste" tests/test_element_paste_view.py`.

In each existing 409 test — `test_a_mark_naming_another_unit_is_a_409`, `test_a_mark_pointing_at_a_deleted_row_is_a_409`, `test_a_stale_token_is_a_409`, `test_a_paste_before_with_a_stale_token_is_a_409` — add `_assert_posts_the_mark(client, <marked>)` directly before the request. (`test_a_paste_with_no_mark_is_a_409` is the exception: no mark exists, and the empty-clip check runs first.) In `test_a_mark_naming_another_unit_is_a_409`, after its 409 assertion, add `assert client.session["element_clip"]["element"] == subject.pk  # kept`. In `test_a_mark_pointing_at_a_deleted_row_is_a_409`, add `assert "element_clip" not in client.session` after the 409 (the same response's render cleared it).

In `courses/tests/test_nested_question_gates.py::test_the_paste_endpoint_shows_the_questions_own_message`, add `"element": marked.pk,` to the paste payload. Its 422 and message assertions stay **unchanged**.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_element_paste_view.py` (add `import psycopg` and `from django.db import OperationalError`):

```python
def test_a_cross_unit_copy_returns_the_destinations_fragments_and_keeps_the_mark(
    client,
):
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x, body="<p>COPYMARK</p>")
    _mark(client, course, x, subject)
    y.refresh_from_db()

    resp = _paste(client, course, y, None, "", mode="copy", element=subject)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert f'data-unit="{y.pk}"' in body  # Y's pane, not X's
    assert Element.objects.filter(unit=y).count() == 1
    assert client.session["element_clip"]["element"] == subject.pk


def test_a_paste_form_with_a_mismatched_element_is_a_409(client):
    """Mutant: delete the stale-form check -> RED (the copy is made, 200)."""
    course, unit = _seed(client)
    subject = _text(unit)
    other = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=other)

    assert resp.status_code == 409
    assert Element.objects.filter(unit=unit).count() == 2  # nothing copied


def test_a_paste_form_with_no_element_is_a_409(client):
    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=None)

    assert resp.status_code == 409


def test_a_paste_form_with_the_matching_element_succeeds(client):
    """Mutant: compare clip["element"] to the POSTed string without str() -> RED
    (an int never equals a str, so every paste would 409)."""
    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=subject)

    assert resp.status_code == 200


def test_a_mark_from_another_course_is_a_409_on_paste(client):
    """mode=copy on purpose: a default move would be stopped earlier by the
    move-reload rule and never reach the service's course filter."""
    course, unit = _seed(client)
    other_course = CourseFactory(owner=course.owner)
    foreign_unit = _unit(other_course, "F")
    foreign = _text(foreign_unit)
    _mark(client, other_course, foreign_unit, foreign)
    _assert_posts_the_mark(client, foreign)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "", mode="copy", element=foreign)

    assert resp.status_code == 409


def test_a_non_numeric_session_element_is_a_409_on_paste(client):
    """Posts the EXACT session value, so the stale-form check passes and the
    service's step-1 guard is what answers."""
    course, unit = _seed(client)
    y = _unit(course, "Y")
    session = client.session
    session["element_clip"] = {"unit": unit.pk, "element": "abc"}
    session.save()
    y.refresh_from_db()

    resp = _paste(client, course, y, None, "", mode="copy", element="abc")

    assert resp.status_code == 409


def test_a_cross_unit_move_reloads_instead_of_refusing(client):
    """Only a stale tab can post it. Mutant: drop the move-reload rule -> RED
    (the service answers 422 wrong_unit instead)."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)
    _assert_posts_the_mark(client, subject)
    y.refresh_from_db()

    resp = _paste(client, course, y, None, "", mode="move", element=subject)

    assert resp.status_code == 409
    assert client.session["element_clip"]["element"] == subject.pk


def _deadlock():
    try:
        raise psycopg.errors.DeadlockDetected("deadlock detected")
    except psycopg.errors.DeadlockDetected as inner:
        raise OperationalError("deadlock detected") from inner


def test_cancel_works_from_a_destination_unit(client):
    """The destination banner's cancel posts ITS unit with ANOTHER unit's element.
    It works because element_clip's cancel branch pops the session before any
    element check -- pinned here so a later "validate first" change cannot break
    cancel in every destination unit silently."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    resp = client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": subject.pk, "unit": y.pk, "action": "cancel"},
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    assert "element_clip" not in client.session


def test_a_deadlock_abort_of_the_copy_is_a_409(client, monkeypatch):
    """Mutant: delete the OperationalError handler -> RED (the error propagates)."""
    from courses import builder as builder_mod

    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    _assert_posts_the_mark(client, subject)
    unit.refresh_from_db()
    calls = []

    def _boom(*args, **kwargs):
        calls.append(1)
        _deadlock()

    monkeypatch.setattr(builder_mod, "paste_element", _boom)

    resp = _paste(client, course, unit, None, "", mode="copy", element=subject)

    assert calls == [1]  # the 409 provably came from the handler
    assert resp.status_code == 409
    assert client.session["element_clip"]["element"] == subject.pk


def test_any_other_operational_error_propagates(client, monkeypatch):
    """Mutant: drop the sqlstate check (map every OperationalError) -> RED."""
    from courses import builder as builder_mod

    course, unit = _seed(client)
    subject = _text(unit)
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    def _boom(*args, **kwargs):
        try:
            raise psycopg.errors.SerializationFailure("could not serialize")
        except psycopg.errors.SerializationFailure as inner:
            raise OperationalError("could not serialize") from inner

    monkeypatch.setattr(builder_mod, "paste_element", _boom)

    with pytest.raises(OperationalError):
        _paste(client, course, unit, None, "", mode="copy", element=subject)


def test_every_rendered_paste_form_carries_the_marked_element(client):
    """Both inclusion tags see ONLY the dict they return.

    Mutant: drop clip_element_pk from paste_before_button's dict -> RED."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    # The extra X row comes FIRST: a row directly below the mark is clip_noop_pk
    # and renders no before-button, so it must sit above the subject.
    _text(x)  # a row in X that offers move-before
    subject = _text(x)
    _tabs(y)
    _text(y)  # a row in Y that offers copy-before
    _mark(client, course, x, subject)

    for u in (x, y):
        body = _editor_get(client, course, u).content.decode()
        assert 'data-op="element-paste-before"' in body, u.title
        forms = re.findall(
            r'<form[^>]*data-op="element-paste(?:-before)?"[^>]*>.*?</form>',
            body,
            flags=re.S,
        )
        assert forms, u.title
        for form in forms:
            assert f'name="element" value="{subject.pk}"' in form
```

(Add `import re` to the imports.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_element_paste_view.py courses/tests/test_nested_question_gates.py`
Expected: FAIL — the cross-unit copy 409s; the mismatched-element test gets 200; the form test finds no `name="element"`; the deadlock test raises.

- [ ] **Step 4: Implement the view**

Add `from django.db import OperationalError` to `courses/views_manage.py`'s imports. In `element_paste`, replace the block from `clip = request.session.get(CLIP_SESSION_KEY) or {}` through the `except TransferError` clause with:

```python
    clip = request.session.get(CLIP_SESSION_KEY) or {}
    if not clip.get("element"):
        # Reachable in ordinary use: a move clears the mark, so a back-button
        # resubmit or a second tab's stale render posts against an empty clipboard.
        return _element_conflict(request, course)
    if request.POST.get("element") != str(clip["element"]):
        # Stale form: the page showed a DIFFERENT mark than the session now holds
        # (or predates this field). String-to-string on purpose -- the session holds
        # an int (see element_clip) and the POST a str.
        return _element_conflict(request, course)
    mode = request.POST.get("mode")
    if clip.get("unit") != unit.pk and mode == "move":
        # Only a stale tab showing an old in-unit mark's move buttons can send this:
        # the destination renders no move control (D7). Reload rather than show
        # wrong_unit's "That element is not part of this unit."
        return _element_conflict(request, course)

    try:
        unit, placed = builder_svc.paste_element(
            course,
            clip["element"],
            request.POST.get("parent"),
            request.POST.get("tab"),
            mode,
            request.POST.get("unit_token"),
            # Absent on the slot buttons, present on a row's "paste before" one.
            # The service ignores parent/tab whenever it is set, so the two forms
            # never have to agree about a destination.
            before=request.POST.get("before"),
            dest_unit_pk=unit.pk,
        )
    except builder_svc.ConflictError:
        return _element_conflict(request, course)
    except builder_svc.PlacementRefused as exc:
        return _refused(request, unit, exc.reason_key)
    except builder_svc.ParentGoneError:
        # Caught BEFORE NestingError -- it is a subclass, and this is the one
        # caller that treats it differently.
        return _refused(request, unit, "parent_gone")
    except builder_svc.NestingError:
        return HttpResponseBadRequest("bad nesting")
    except TransferError as exc:
        return _render_editor_fragments(request, unit, status=422, error=str(exc))
    except OperationalError as exc:
        # A deadlock abort of THIS transaction (spec D11): one __cause__ hop is where
        # Django's DatabaseErrorWrapper puts psycopg's DeadlockDetected. The
        # service's @transaction.atomic has already rolled back and ATOMIC_REQUESTS
        # is off, so rendering here is safe. Anything else is not ours to hide.
        if getattr(exc.__cause__, "sqlstate", None) != "40P01":
            raise
        return _element_conflict(request, course)
```

Keep the rest of the view (the move-clears-mark rule and the final render) unchanged, but change its `request.POST.get("mode") == "move"` to `mode == "move"`. Update the view docstring's status list to mention: a stale form, a cross-unit move and a deadlock abort → 409.

- [ ] **Step 5: Thread `element` and `mode` through the tags and forms**

In `courses_manage_extras.py`, `paste_buttons` returns one more key:

```python
        "clip_element_pk": context.get("clip_element_pk") or "",
```

`paste_before_button` becomes:

```python
    clip_pk = context.get("clip_element_pk") or ""
    row_pk = str(el.pk)
    if not clip_pk or row_pk in (clip_pk, context.get("clip_noop_pk") or ""):
        return {"show": False}
    key = builder.slot_key(el.parent_id, el.tab_id or "")
    return {
        "show": key in (context.get("before_slots") or set()),
        "unit": context.get("unit"),
        "el": el,
        # The partial sees ONLY this dict (inclusion tag): both keys must travel.
        "clip_element_pk": clip_pk,
        # "copy" in a destination unit, "move" in the source (spec D4). .get with a
        # default: a render path without the full clip context hides or falls back,
        # never raises.
        "mode": context.get("clip_mode") or "move",
    }
```

Extend its docstring by one sentence: the button posts `mode` from the context — copy-before in a destination unit, move-before in the source.

In `_paste_buttons.html`, after the `unit_token` input add:

```django
  <input type="hidden" name="element" value="{{ clip_element_pk }}">
```

In `_paste_before_button.html`, replace `<input type="hidden" name="mode" value="move">` with:

```django
  <input type="hidden" name="mode" value="{{ mode }}">
  <input type="hidden" name="element" value="{{ clip_element_pk }}">
```

(The label/icon switch is Task 6.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_element_paste_view.py tests/test_element_clip_view.py tests/test_editor_clip_templates.py courses/tests/test_nested_question_gates.py tests/test_builder_paste_element.py`
Expected: all PASS.

- [ ] **Step 7: Falsify**

By hand: delete the stale-form `if` → `test_a_paste_form_with_a_mismatched_element_is_a_409` red; replace `str(clip["element"])` with `clip["element"]` → `test_a_paste_form_with_the_matching_element_succeeds` red; delete the move-reload `if` → `test_a_cross_unit_move_reloads_instead_of_refusing` red; delete the `except OperationalError` clause → `test_a_deadlock_abort_of_the_copy_is_a_409` red; replace its sqlstate `if` with nothing (always 409) → `test_any_other_operational_error_propagates` red; drop `"clip_element_pk"` from `paste_before_button`'s dict → `test_every_rendered_paste_form_carries_the_marked_element` red; in the `_paste_before` helper, stop adding `element` to `data` → `test_a_paste_before_a_sibling_reorders_within_the_slot_and_clears_the_mark` red (409 instead of 200) — which proves the helper's `element` really travels, so `test_a_paste_before_with_a_stale_token_is_a_409` reaches its token path rather than the stale-form one. Revert each; `git diff`.

- [ ] **Step 8: Commit**

```bash
uv run ruff format courses/views_manage.py courses/templatetags/courses_manage_extras.py tests/test_element_paste_view.py courses/tests/test_nested_question_gates.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/views_manage.py courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/_paste_buttons.html templates/courses/manage/editor/_paste_before_button.html tests/test_element_paste_view.py courses/tests/test_nested_question_gates.py
git commit -m "feat(paste): stale-form check, cross-unit paste endpoint, deadlock 409"
```

---

### Task 6: Banner, unit list, copy-before label, SVG icons, catalogue

**Files:**
- Modify: `templates/courses/manage/editor/_editor_scope.html`
- Create: `templates/courses/manage/editor/_copy_units_tree.html`, `templates/courses/manage/editor/_copy_units_node.html`
- Modify: `templates/courses/manage/editor/_paste_before_button.html`, `_paste_buttons.html`, `_element_row_controls.html`, `editor.html`
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po` (+ `.mo`)
- Test: `tests/test_editor_clip_templates.py`

**Interfaces:**
- Consumes: context keys from Task 4; tag keys from Task 5.
- Produces: markup contracts relied on by Tasks 7–8 — `#clip-banner.clip-banner` (div, direct child of `section.editor-pane`, between `.pane-head` and `#editor-error`); `.clip-banner__line` > `.clip-banner__label`, optional `.clip-banner__from` (> `.clip-banner__from-prefix` + `a[data-math-title]`), cancel `form`; optional `p.clip-banner__nothing`; `details.clip-banner__units` > `summary` + `ol.clip-banner__units-list`; SVG symbols `#ed-paste-move`, `#ed-paste-copy`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_editor_clip_templates.py` (add `import re`, `from courses.models import CalloutElement`, `from courses.models import ChoiceQuestionElement`, `from tests.factories import make_quiz_unit`):

```python
def _unit(course, title, unit_type="lesson", parent=None, kind="unit"):
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title
    )


def _banner(body):
    start = body.index('id="clip-banner"')
    return body[start : body.index("</details>", start) + len("</details>")]


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


def test_the_destination_offers_copy_controls_and_no_move_controls(client):
    """D7. Paired with presence assertions, so an empty tag cannot pass it."""
    course, x = _seed(client)
    y = _unit(course, "Y")
    subject = _text(x)
    _tabs(y)
    _text(y)
    _mark(client, course, x, subject)

    body = _editor(client, course, y)

    assert "Copy before this element" in body
    assert 'value="copy"' in body
    assert "Move before this element" not in body
    assert "Move here" not in body
    for form in re.findall(
        r'<form[^>]*data-op="element-paste-before"[^>]*>.*?</form>', body, flags=re.S
    ):
        assert 'name="mode" value="copy"' in form


def test_the_source_rows_keep_move_before_only(client):
    """D4. The POSTED mode is asserted, not just the label: the label comes from
    `{% if mode == "copy" %}`, so a hard-coded hidden input would keep it.

    Mutant: hard-code `value="copy"` in _paste_before_button.html's mode input ->
    RED here; hard-code `value="move"` -> RED on the destination test above."""
    course, x = _seed(client)
    _unit(course, "Y")
    _text(x)
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)

    assert "Move before this element" in body
    assert "Copy before this element" not in body
    forms = re.findall(
        r'<form[^>]*data-op="element-paste-before"[^>]*>.*?</form>', body, flags=re.S
    )
    assert forms  # the loop below cannot pass on zero forms
    for form in forms:
        assert 'name="mode" value="move"' in form


def test_the_destination_banner_links_back_to_the_source(client):
    course, x = _seed(client)
    x.title = "SourceUnitTitle"
    x.save()
    y = _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    banner = _banner(_editor(client, course, y))
    # ONLY the "from" part: the unit list below it also links X with X's title,
    # so a whole-banner assertion would pass whatever the from-link points at.
    start = banner.index("clip-banner__from")
    from_part = banner[start : banner.index("<details", start)]

    assert f'href="{_editor_url(course, x)}"' in from_part
    assert "SourceUnitTitle" in from_part
    assert f'href="{_editor_url(course, y)}"' not in from_part


def test_the_source_banner_has_no_from_link(client):
    course, x = _seed(client)
    _unit(course, "Y")
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)

    assert "clip-banner__from" not in body


def test_the_unit_list_links_every_other_unit_and_not_the_current_one(client):
    """Mutant: render the current unit as a link too -> RED."""
    course, x = _seed(client)
    x.title = "CurrentUnit"
    x.save()
    y = _unit(course, "OtherUnit")
    subject = _text(x)
    _mark(client, course, x, subject)

    banner = _banner(_editor(client, course, x))

    assert f'href="{_editor_url(course, y)}"' in banner
    assert f'href="{_editor_url(course, x)}"' not in banner
    assert 'aria-current="page"' in banner
    assert "CurrentUnit" in banner


def test_a_one_unit_course_renders_no_unit_list(client):
    """Mutant: drop the `{% if copy_units_available %}` guard -> RED."""
    course, x = _seed(client)
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)

    assert 'id="clip-banner"' in body
    assert "clip-banner__units" not in body


def test_the_unit_list_handles_an_irregular_course(client):
    course, x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    under_part = _unit(course, "UnderPart", parent=part)
    _unit(course, "EmptySectionE", kind="section", unit_type="", parent=part)
    other_root = _unit(course, "OtherRoot")  # neither source nor current
    subject = _text(x)
    _mark(client, course, x, subject)
    y = _unit(course, "RootY")

    body = _editor(client, course, y)
    # The <details> part only: the "from" link above it also carries X's href.
    start = body.index("clip-banner__units")
    banner = body[start : body.index("</details>", start)]

    assert f'href="{_editor_url(course, other_root)}"' in banner  # root-level
    assert f'href="{_editor_url(course, under_part)}"' in banner
    assert "EmptySectionE" not in banner  # a unit-less container is omitted


def test_nothing_fits_is_said_out_loud(client):
    """Mutant: drop the clip_nothing_fits paragraph -> RED."""
    course, x = _seed(client)
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    box = Element.objects.create(
        unit=x, content_object=CalloutElement.objects.create(kind="example")
    )
    Element.objects.create(
        unit=x,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    _mark(client, course, x, box)

    body = _editor(client, course, quiz)

    assert "Nothing can be pasted into this unit." in body
    assert 'data-op="element-paste"' not in body


def test_the_banner_is_a_div_between_the_pane_head_and_the_error_slot(client):
    """Asserted on a 422 render, so the error slot really exists to order against."""
    course, x = _seed(client)
    quiz = make_quiz_unit(course=course, parent=None, title="Q")
    dest = Element.objects.create(
        unit=quiz, content_object=CalloutElement.objects.create(kind="example")
    )
    subject = Element.objects.create(
        unit=quiz,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
    )
    _mark(client, course, quiz, subject)
    quiz.refresh_from_db()

    resp = client.post(  # a question into a quiz container: 422 question_in_quiz
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": dest.pk,
            "tab": CalloutElement.SLOT_ID,
            "mode": "move",
            "element": subject.pk,
            "unit": quiz.pk,
            "unit_token": quiz.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    body = resp.content.decode()

    assert '<div id="clip-banner" class="clip-banner">' in body
    head_end = body.index("pane-head__count")
    banner = body.index('id="clip-banner"')
    error = body.index('id="editor-error"')
    pane_body = body.index('class="pane-body"')
    assert head_end < banner < error < pane_body


def test_no_emoji_or_text_glyph_icons_remain_on_paste_controls(client):
    """D9. Mutant: restore 📋 in _paste_buttons.html -> RED."""
    course, x = _seed(client)
    _tabs(x)
    _text(x)
    subject = _text(x)
    _mark(client, course, x, subject)

    body = _editor(client, course, x)
    scope = body[body.index('data-scope="editor"') : body.index('data-scope="preview"')]

    assert "📋" not in scope
    assert "⧉" not in scope
    assert '<use href="#ed-paste-move"/>' in scope  # slot move + move-before
    assert '<use href="#ed-paste-copy"/>' in scope  # slot copy + Duplicate
    for form in re.findall(
        r'<form[^>]*data-op="element-(?:paste|paste-before|duplicate)"[^>]*>.*?</form>',
        scope,
        flags=re.S,
    ):
        assert '<use href="#ed-paste-' in form
```

Re-anchor the existing fixed-window slice in `test_the_banner_falls_back_to_the_type_summary_when_the_title_is_empty`: replace `body[body.index('id="clip-banner"') : body.index('id="clip-banner"') + 400]` with a slice anchored on `clip-banner__label`:

```python
    start = body.index("clip-banner__label")
    banner = body[start : start + 400]
```

Check the other `clip-banner` assertions in the file still hold against the new markup (`test_the_banner_names_the_marked_element_inside_the_swapped_pane` checks `id="clip-banner"` positions — unchanged).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_editor_clip_templates.py`
Expected: FAIL on every new test (no `Copy before this element`, no `clip-banner__from`, no unit list, emoji present, banner still a `span`).

- [ ] **Step 3: SVG symbols**

In `editor.html`, directly after the `<symbol id="ed-header" …>` line, add:

```html
    <symbol id="ed-paste-move" viewBox="0 0 16 16"><path d="M8 2.5v7M5.2 6.8 8 9.6l2.8-2.8" fill="none" stroke="currentColor" stroke-width="1.35" stroke-linecap="round" stroke-linejoin="round"/><path d="M2.5 10.5v1.8a1.2 1.2 0 0 0 1.2 1.2h8.6a1.2 1.2 0 0 0 1.2-1.2v-1.8" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></symbol>
    <symbol id="ed-paste-copy" viewBox="0 0 16 16"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10.5 3.6v-.4a.9.9 0 0 0-.9-.9H3.4a.9.9 0 0 0-.9.9v6.2a.9.9 0 0 0 .9.9h.4" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></symbol>
```

Directly above the two new `<symbol>` lines, add a one-line comment (single-line `{# … #}` is fine here):

```django
    {# ed-paste-move (arrow into a tray) / ed-paste-copy (two stacked sheets): every paste control and Duplicate (spec D9), replacing the 📋 / ⧉ glyphs. #}
```

- [ ] **Step 4: Buttons**

`_paste_buttons.html` — replace the two button lines with:

```django
  {% if show_move %}<button class="iconbtn pastebtn" type="submit" name="mode" value="move" aria-label="{% trans 'Move here' %}" title="{% trans 'Move here' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-paste-move"/></svg></button>{% endif %}
  {% if show_copy %}<button class="iconbtn pastebtn" type="submit" name="mode" value="copy" aria-label="{% trans 'Copy here' %}" title="{% trans 'Copy here' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-paste-copy"/></svg></button>{% endif %}
```

`_paste_before_button.html` — replace the button line with:

```django
  {% if mode == "copy" %}<button class="iconbtn pastebtn" type="submit" aria-label="{% trans 'Copy before this element' %}" title="{% trans 'Copy before this element' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-paste-copy"/></svg></button>{% else %}<button class="iconbtn pastebtn" type="submit" aria-label="{% trans 'Move before this element' %}" title="{% trans 'Move before this element' %}"><svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-paste-move"/></svg></button>{% endif %}
```

`_element_row_controls.html` — the Duplicate button's `⧉` becomes `<svg class="ic" aria-hidden="true" focusable="false"><use href="#ed-paste-copy"/></svg>`.

- [ ] **Step 5: The unit-list partials**

Create `templates/courses/manage/editor/_copy_units_tree.html`:

```django
{% load i18n %}
{% comment %}
"Copy to another unit..." (spec D5/D12). Server-rendered, no JS, no endpoint: each
unit is a plain link to its editor page, so the pending mark follows the author
there. The data is copy_units_tree()'s PRUNED map -- containers with no unit below
them are already gone, because a template cannot look ahead. The scrolling <ol> is
position:relative in editor.css so KaTeX's absolute .katex-mathml twins stay
clipped inside it.
{% endcomment %}
<details class="clip-banner__units">
  <summary>{% trans "Copy to another unit…" %}</summary>
  <ol class="clip-banner__units-list">
    {% for n in copy_units_top %}{% include "courses/manage/editor/_copy_units_node.html" with n=n %}{% endfor %}
  </ol>
</details>
```

Create `templates/courses/manage/editor/_copy_units_node.html`:

```django
{% load courses_manage_extras %}
{% comment %}
One row of the copy-units list, recursive. Badges are the link picker's markup
(twinned in editor.css). The CURRENT unit is text with aria-current, never a link.
{% endcomment %}
<li class="clip-banner__unit">
  {% if n.kind == "unit" %}
    {% if n.unit_type == "quiz" %}<span class="tree__badge tree__badge--unit tree__badge--quiz" title="{{ n.get_unit_type_display }}">Q</span>{% else %}<span class="tree__badge tree__badge--unit tree__badge--lesson" title="{{ n.get_unit_type_display }}">L</span>{% endif %}
    {% if n.pk == unit.pk %}<span class="clip-banner__unit-current" aria-current="page" data-math-title>{{ n.title }}</span>{% else %}<a href="{% url 'courses:manage_editor' slug=unit.course.slug pk=n.pk %}" data-math-title>{{ n.title }}</a>{% endif %}
  {% else %}
    <span class="tree__badge tree__badge--{{ n.kind }}">{{ n.get_kind_display }}</span> <span class="clip-banner__unit-group" data-math-title>{{ n.title }}</span>
    {% with children=copy_units_map|get_item:n.pk %}<ol>{% for child in children %}{% include "courses/manage/editor/_copy_units_node.html" with n=child %}{% endfor %}</ol>{% endwith %}
  {% endif %}
</li>
```

- [ ] **Step 6: The banner**

In `_editor_scope.html`:
1. Remove the whole `{% if clip_active %}<span id="clip-banner" …>…</span>{% endif %}` block from inside `.pane-head` (so `.pane-head` holds only the `h2` and the count again).
2. Rewrite the `{% comment %}` attached to the count that says the banner "becomes a THIRD child" to say `.pane-head` has exactly two children; the banner is a sibling **after** it.
3. Directly after the `.pane-head`'s closing `</div>` and **before** the error slot's `{% comment %}`, insert:

```django
      {% comment %}
      The mark banner MUST live inside [data-scope="editor"]: applyFragments
      replaces only the two panes, and editor.html's header region sits outside
      both -- a banner there would render once on page load and then never reflect
      a select, a cancel or a paste. It is a DIV and a sibling AFTER .pane-head (not
      its third child): it holds flow content -- the <details> unit list -- which is
      invalid in a span and would wreck the flex head. Order: head, banner, error
      slot, body -- so a refusal sits between the banner and the list it concerns.
      {% endcomment %}
      {% if clip_active %}<div id="clip-banner" class="clip-banner">
        <div class="clip-banner__line">⊹ <span class="clip-banner__label">{% blocktranslate %}Selected: {{ clip_label }}{% endblocktranslate %}</span>{% if clip_source_unit %}<span class="clip-banner__from"><span class="clip-banner__from-prefix">— {% translate "from unit" context "clip banner" %}</span> <a href="{% url 'courses:manage_editor' slug=unit.course.slug pk=clip_source_unit.pk %}" data-math-title>{{ clip_source_unit.title }}</a></span>{% endif %}
          <form class="tree__inline" method="post" action="{% url 'courses:manage_element_clip' slug=unit.course.slug %}" data-op="element-clip">
            {% csrf_token %}
            <input type="hidden" name="ctx" value="editor">
            <input type="hidden" name="element" value="{{ clip_element_pk }}">
            <input type="hidden" name="unit" value="{{ unit.pk }}">
            <input type="hidden" name="action" value="cancel">
            <button class="iconbtn" type="submit" aria-label="{% trans 'Cancel selection' %}" title="{% trans 'Cancel selection' %}">✕</button>
          </form>
        </div>
        {% if clip_nothing_fits %}<p class="clip-banner__nothing">{% trans "Nothing can be pasted into this unit." %}</p>{% endif %}
        {% if copy_units_available %}{% include "courses/manage/editor/_copy_units_tree.html" %}{% endif %}
      </div>{% endif %}
```

Copy the cancel form's hidden inputs **verbatim from the block you removed** (the lines above show the current ones; if the removed block differs, the removed block wins). Move the old "The mark banner MUST live inside…" `{% comment %}` into the new one above rather than keeping two.

- [ ] **Step 7: Run the template tests**

Run: `uv run pytest tests/test_editor_clip_templates.py tests/test_element_paste_view.py`
Expected: all PASS. If `test_a_cross_unit_marked_render_stays_within_its_query_ceiling` (or the same-unit `test_a_marked_render_does_not_walk_parents_per_slot`) goes red, the banner templates added queries: first check it is not a per-node query in `_copy_units_node.html` (e.g. a `unit.course` lookup per row — `copy_units_tree(unit.course)` should already have cached it); if it is, fix the template. Otherwise re-measure the cross-unit ceiling as Task 4 Step 5b does (ceiling to `1`, read the count, set count + 5, update `MEASURED BASELINE`) and stage `tests/test_element_paste_view.py` in Step 10's commit. The same-unit ceiling is never raised here — a red there is investigated, not absorbed.

- [ ] **Step 8: Catalogue**

1. `uv run python manage.py makemessages -l pl -l en --no-obsolete`
2. In `locale/pl/LC_MESSAGES/django.po`, set these msgstrs (overwrite unconditionally; delete any `#, fuzzy` and `#| msgid` lines on each entry — `makemessages` fuzzy-prefills from similar msgids):

   | msgid (msgctxt) | msgstr |
   |---|---|
   | `from unit` (`clip banner`) | `z jednostki` |
   | `Copy to another unit…` | `Kopiuj do innej jednostki…` |
   | `Copy before this element` | `Kopiuj przed ten element` |
   | `Nothing can be pasted into this unit.` | `Do tej jednostki nie można niczego wkleić.` |
   | `Interactive elements can only be placed in a lesson unit.` | `Elementy interaktywne można umieszczać tylko w jednostce typu lekcja.` |

   Leave `locale/en` msgstrs empty (repo convention). The noun is checked against the catalogue: `grep -n -A1 '^msgid "Unit"' locale/pl/LC_MESSAGES/django.po` shows `msgstr "Jednostka"` (verified when this plan was written) — the table's "jednostki"/"jednostce"/"jednostka" forms follow it. If the grep shows a different noun, align all five msgstrs to it before compiling.
3. `grep -c "^#, fuzzy" locale/pl/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.po` → both `0` (do not anchor with `$`: the `.po` files are CRLF).
4. `uv run python manage.py compilemessages -l pl -l en`
5. `uv run pytest tests/test_i18n_po_health.py` → PASS.

- [ ] **Step 9: Falsify**

By hand: hard-code `value="move"` in `_paste_before_button.html`'s mode input → `test_the_destination_offers_copy_controls_and_no_move_controls` red; hard-code `value="copy"` → `test_the_source_rows_keep_move_before_only` red; in the banner, point the "from" link at `pk=unit.pk` instead of `pk=clip_source_unit.pk` → `test_the_destination_banner_links_back_to_the_source` red; render the current unit as a link (drop the `{% if n.pk == unit.pk %}` branch) → `test_the_unit_list_links_every_other_unit_and_not_the_current_one` red; drop `{% if copy_units_available %}` → `test_a_one_unit_course_renders_no_unit_list` red; move the whole `{% if clip_active %}<div id="clip-banner" …>…</div>{% endif %}` block below the `#editor-error` line → `test_the_banner_is_a_div_between_the_pane_head_and_the_error_slot` red on its index ordering; the pruning mutant from Task 4 (no pruning in `copy_units_tree`) also turns `test_the_unit_list_handles_an_irregular_course` red on `"EmptySectionE" not in banner`; delete the nothing-fits `<p>` → `test_nothing_fits_is_said_out_loud` red; restore `📋` in the slot move button → the icon test red. Revert each; `git diff`.

- [ ] **Step 10: Commit**

```bash
uv run ruff format tests/test_editor_clip_templates.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add templates/courses/manage/editor/_editor_scope.html templates/courses/manage/editor/_copy_units_tree.html templates/courses/manage/editor/_copy_units_node.html templates/courses/manage/editor/_paste_before_button.html templates/courses/manage/editor/_paste_buttons.html templates/courses/manage/editor/_element_row_controls.html templates/courses/manage/editor/editor.html locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo tests/test_editor_clip_templates.py
git add tests/test_element_paste_view.py  # only if Step 7 re-measured the ceiling
git commit -m "feat(paste): cross-unit banner, unit list, copy-before, SVG paste icons"
```

---

### Task 7: Banner CSS and swap-time title typesetting

**Files:**
- Modify: `courses/static/courses/css/editor.css`
- Modify: `courses/static/courses/js/editor.js`
- Test: `tests/test_editor_styles.py`

**Interfaces:**
- Consumes: the Task 6 markup contract.

- [ ] **Step 1: Extend the standing CSS guard (failing)**

In `tests/test_editor_styles.py::test_editor_css_styles_action_buttons`, replace the clipboard loop with a selector-boundary match (a bare substring test is satisfied by neighbours: `.clip-banner__from` by `.clip-banner__from-prefix`, `.clip-banner__units` by `.clip-banner__units-list`, `.clip-banner` by any of them):

```python
    # Selector BOUNDARY, not substring: `.clip-banner__from` must be styled itself,
    # not merely prefix `.clip-banner__from-prefix`. The class must be followed by
    # whitespace/combinator/`{`/`,`/`:`/`>` -- anything but another name character.
    for cls in (
        ".el-row--marked",
        ".clip-banner",
        ".clip-banner__line",
        ".clip-banner__label",
        ".clip-banner__from",
        ".clip-banner__units",
        ".pastewrap",
        ".pastebtn",
        ".iconbtn .ic",  # unsized, the paste/Duplicate SVGs render at 300x150
    ):
        assert re.search(re.escape(cls) + r"(?![\w-])", css), (
            f"editor.css must style {cls}"
        )
```

(`re` is already imported at the top of that file — used by `_code_only` — so add nothing). Also rewrite the comment directly above the old loop (`# Same argument for the clipboard's four classes: _element_row.html, _editor_scope.html and _paste_buttons.html reference them…`): it must no longer say "four", and must name the templates that now use these classes — `_element_row.html`, `_editor_scope.html`, `_paste_buttons.html`, `_paste_before_button.html`, `_element_row_controls.html`, `_copy_units_tree.html`, `_copy_units_node.html` (banner, unit list, paste controls, icon sizing). Mutant: delete the `.clip-banner__from { … }` rule (keep `.clip-banner__from-prefix` and `.clip-banner__from a`) → still green, because `.clip-banner__from a` styles the class at a boundary — acceptable, the class IS styled; delete all three `.clip-banner__from…` rules → red; delete the `.iconbtn .ic` rule → red.

Run: `uv run pytest tests/test_editor_styles.py`
Expected: FAIL on `.clip-banner__line`.

- [ ] **Step 2: Rewrite the `.clip-banner` block**

Replace the whole block in `editor.css` from the comment `/* Clipboard mark banner ("⊹ Selected: <label>" + a ✕ cancel), rendered into the` through the rule `.pane-head:has(.clip-banner) .pane-head__count { flex: none; }` (inclusive) with:

```css
/* Clipboard mark banner: a sibling AFTER .pane-head (never its child — it holds the
   <details> unit list, flow content the flex head cannot take). Same inline inset as
   `.editor-pane > .op-error` for the same measured reason: .pane has no padding of
   its own, so a bare child renders full-bleed with its border on the pane border.
   flex:none so the viewport-locked two-pane layout never squeezes it; .pane-body
   absorbs the list's height instead. */
.editor-pane > .clip-banner { margin: var(--space-3) var(--space-4) 0; flex: none; }
/* The pill. Accent family (not --primary) so it reads as the same "marked" colour as
   .el-row--marked and never as the editing/primary state. A FLEX ROW that never
   wraps: only the label and the "from" link truncate, so the link — the only way
   back to the source unit — is never the first thing cut. The cancel form is OUT OF
   FLOW in reserved trailing padding, so the ✕ can never be pushed away or clipped
   (measured: floating it instead dropped the ✕ onto a second line and doubled the
   head's height). position:relative anchors that ✕ to the pill, not the banner. */
.clip-banner__line {
  position: relative; display: flex; align-items: baseline; gap: var(--space-1);
  white-space: nowrap; min-width: 0;
  padding: var(--space-1) var(--space-2);
  padding-inline-end: calc(1.4rem + var(--space-3));
  border: 1px solid var(--accent); border-radius: var(--radius-full);
  background: var(--accent-subtle); color: var(--text-secondary);
  font-size: .72rem; line-height: 1.3;
}
.clip-banner__label {
  flex: 1 1 auto; min-width: 0; overflow: hidden; white-space: nowrap;
  text-overflow: ellipsis;
}
.clip-banner__from { display: inline-flex; flex: 0 1 auto; min-width: 0; max-width: 45%; gap: .25em; }
.clip-banner__from-prefix { flex: none; }
/* position:relative is load-bearing: KaTeX's .katex-mathml twin is position:absolute,
   and a static overflow box is nobody's containing block, so it would escape this
   clip and inflate the page's scroll area. */
.clip-banner__from a {
  min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
  position: relative; color: var(--accent);
}
.clip-banner__line .tree__inline {
  position: absolute; inset-inline-end: var(--space-1);
  top: 50%; transform: translateY(-50%);
}
/* Smaller than a row-bar .iconbtn (1.9rem): at that size the button alone would
   drive the pill's height. */
.clip-banner__line .iconbtn {
  min-width: 1.4rem; min-height: 1.4rem; padding: 0; line-height: 1;
  font-size: .72rem; border-color: transparent; color: var(--text-secondary);
}
.clip-banner__line .iconbtn:hover { color: var(--text-primary); border-color: var(--border-strong); }
.clip-banner__nothing { margin: var(--space-2) 0 0; font-size: .78rem; color: var(--text-secondary); }
.clip-banner__units { margin-top: var(--space-2); font-size: .78rem; }
.clip-banner__units > summary { cursor: pointer; color: var(--accent); }
/* Capped in EVERY layout: in the viewport-locked two-pane layout the list takes its
   height from .pane-body. position:relative for the KaTeX reason above. */
.clip-banner__units-list {
  position: relative; max-height: min(35vh, 18rem); overflow-y: auto;
  margin: var(--space-2) 0 0; padding-inline-start: var(--space-4);
  border: 1px solid var(--border-subtle); border-radius: var(--radius-sm, 6px);
  padding-block: var(--space-2);
}
.clip-banner__units-list ol { margin: 0; padding-inline-start: var(--space-4); }
.clip-banner__unit { list-style: none; margin: .15rem 0; }
.clip-banner__unit a { color: var(--text-primary); }
.clip-banner__unit-current { font-weight: 600; color: var(--text-secondary); }
/* The paste and Duplicate controls now hold an <svg class="ic">. The editor page does
   not load builder.css (home of the global `.ic` size), and an unsized <svg> renders
   at the UA default 300x150 -- so size it inside every icon button here. */
.iconbtn .ic { width: 1rem; height: 1rem; display: block; }
```

Check every token used exists in the project (`grep -n "\-\-radius-full\|--radius-sm\|--accent-subtle\|--border-strong\|--border-subtle" core/static/core/css/*.css | head`); replace `var(--radius-sm, 6px)` with the real small-radius token if one exists. Keep `.pane-body { padding: var(--space-4); }` and everything after it untouched.

- [ ] **Step 3: Rewrite the three stale comments, line-count neutral**

1. `.pastewrap` comment's first line: `/* Paste controls (📋 Move here / ⧉ Copy here) for one slot. …` → `/* Paste controls (move / copy SVG icons) for one slot. …` — keep the rest of the line so the comment's line count is unchanged.
2. `.pastebtn` comment: `/* Accent, matching .el-row--marked and .clip-banner: …` → `/* Accent, matching .el-row--marked and .clip-banner__line: …` — same line count.
3. The action-bar comment (~line 616): `(✎/✕ ↑ ↓ ⧉ ⊹ 🗑, six visible at a time)` → `(✎/✕ ↑ ↓ copy ⊹ 🗑, six visible at a time)` — same line.

Verify: `git diff --stat courses/static/courses/css/editor.css` and read the diff of those three hunks — each must show equal `-`/`+` line counts.

- [ ] **Step 4: Typeset titles in the swapped editor scope**

In `editor.js` `applyFragments`, directly after `applyStoredSlots(root);`, add:

```js
    // Node titles inside the swapped EDITOR scope -- the clip banner's "from" link
    // and the "Copy to another unit..." list -- carry data-math-title. math.js
    // typesets those only on page load, so re-run here. Only these nodes, never the
    // whole pane (row labels and forms must stay raw), and skip any without a
    // delimiter: mat-pp's list holds hundreds of titles and this runs on every op
    // while a mark is pending.
    var editorScope = root.querySelector('[data-scope="editor"]');
    if (editorScope) {
      editorScope.querySelectorAll("[data-math-title]").forEach(function (node) {
        var text = node.textContent;
        if (text.indexOf("\\(") === -1 && text.indexOf("\\[") === -1) return;
        renderPreviewMath(node);
      });
    }
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_editor_styles.py tests/test_editor_clip_templates.py`
Expected: all PASS.

- [ ] **Step 6: Manual check (screenshots)**

Start the dev server on the local mat-pp copy (`uv run python manage.py runserver`), hard-reload with the service worker bypassed (DevTools → Application → Service workers → "Bypass for network"; a stale worker serves old static). As a course owner: mark an element in one unit, open "Copy to another unit…", follow a link. Take screenshots, light and dark, of: the source banner with the list open; the destination banner (with the "from" link); a quiz destination showing "Nothing can be pasted into this unit."; a ≤ 480px viewport with a long element title (≥ 80 characters). Judge dark separately. **Measure the wide-layout share now, not in Task 8:** at a 1280×720 **viewport** (DevTools responsive/device mode set to exactly 1280×720 — a 1280×720 *window* is smaller, and the e2e sets the viewport exactly), with a course of 40+ units and the list open, run in the console `(p => p.querySelector('.pane-body').clientHeight / p.clientHeight)(document.querySelector('[data-scope="editor"]'))`. The spec expects `.pane-body` to keep ≥ ~40% of the pane (its "~40%" is derived arithmetic, not a measurement). If the share is below 0.4, add inside the existing `@media (min-width: 70rem)` block of `editor.css`:
```css
  /* Viewport-locked layout: the open list takes height from .pane-body, so it is
     capped tighter here -- MEASURED at 1280x720 the base cap left .pane-body
     <share>% of the pane. */
  .clip-banner__units-list { max-height: min(20vh, 12rem); }
```
re-measure, lower the cap further if still short, write the measured shares into the comment, and record the deviation from the spec's `min(35vh, 18rem)` in the PR body (the spec's stated goal — `.pane-body` keeps ~40% — wins over its arithmetic). Confirm: the row action bar's Duplicate button and every paste button show a normal-size (1rem) icon, not a 300×150 one; the **pre-existing** `.iconbtn .ic` handles keep their size under the new rule (V5 is deliberately global) — open a table, a fill-table, a gallery and a tabs editor and check the handle icons are unchanged (table/fill-table row/col handles ~11px, gallery/tabs ~14px; compare with the same editors on `origin/master`). The table handles win only by source order (`.table-editor__rowctl .ic` is (0,2,0), the same as `.iconbtn .ic`, and sits later in the file), so **add the new `.iconbtn .ic` rule where Step 2 puts it, above those rules — never move it below them**; the pill aligns with the "Editor" heading; the ✕ stays on the pill with the list open; the "from" link is visible when the label truncates; badges render (they are twinned in `editor.css`). Fix anything wrong before committing. Keep the screenshots for the PR, **saved in the session scratchpad, never inside the worktree** — an untracked file there would break Task 8's empty-`git status` checks.

- [ ] **Step 7: Commit**

```bash
uv run ruff format tests/test_editor_styles.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/static/courses/css/editor.css courses/static/courses/js/editor.js tests/test_editor_styles.py
git commit -m "feat(paste): banner below the pane head, unit list styling, swap-time title maths"
```

---

### Task 8: e2e, timing, and the branch gate

**Files:**
- Create: `tests/test_e2e_cross_unit_copy.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the e2e test**

Create `tests/test_e2e_cross_unit_copy.py`. Reuse the fixtures/helpers of `tests/test_e2e_paste_before.py` (`_allow_sync_orm_under_playwright`, `_make_pa_user`, `_login`) by copying them (e2e files do not import each other's helpers). The test body:

```python
"""Playwright e2e for cross-unit copy: mark in A, follow "Copy to another unit..."
to B, "Copy before" a middle row. The whole path crosses a full page navigation
AND a fragment swap, which no template or service test can see."""

import os

import pytest
from django.urls import reverse
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

LONG_LABEL = "L" * 90  # >= 80 characters, forces the label to truncate


# ... _allow_sync_orm_under_playwright, _make_pa_user, _login copied verbatim ...


def _seed(owner):
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug="crossunit", owner=owner)
    # A LONG title with the maths at the END, so at 400px the "from" link truncates
    # with the maths in the clipped tail -- the only case where an escaped
    # .katex-mathml twin could widen the page (the containment mutant needs it).
    a = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None,
        title="Unit A with a deliberately long source title for truncation \\(x^2\\)",
    )
    b = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Unit B"
    )
    # Enough extra units to overflow the capped list; the last ones carry maths.
    for i in range(40):
        title = f"Filler {i} \\(y_{i}\\)" if i >= 35 else f"Filler {i}"
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", parent=None, title=title
        )
    subject = Element.objects.create(
        unit=a,
        title=LONG_LABEL,
        content_object=TextElement.objects.create(body="<p>COPYMARKER</p>"),
    )
    # B must overflow .pane-body even with the list closed (1280x720 assertion).
    rows = [
        Element.objects.create(
            unit=b,
            content_object=TextElement.objects.create(body=f"<p>BROW-{i}</p>"),
        )
        for i in range(25)
    ]
    return course, a, b, subject, rows


def _editor(live_server, course, unit):
    return live_server.url + reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )


def _box(page, selector):
    return page.locator(selector).first.bounding_box()


def _inside(inner, outer, tol=1):
    return (
        inner["x"] >= outer["x"] - tol
        and inner["y"] >= outer["y"] - tol
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + tol
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + tol
    )


@pytest.mark.django_db(transaction=True)
def test_a_copy_follows_the_author_to_another_unit(page, live_server):
    page.set_viewport_size({"width": 1280, "height": 720})
    user = _make_pa_user("pa")
    course, a, b, subject, rows = _seed(user)
    _login(page, live_server, "pa")
    page.goto(_editor(live_server, course, a))

    # 1. Mark in A through the real control.
    row = page.locator(f".el-row[data-element='{subject.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator("> .el-row__head .el-actions form[data-op='element-clip'] button").click()
    expect(page.locator("#clip-banner")).to_be_visible()

    # 2. The pill lines up with the "Editor" heading (no full-bleed banner): the
    #    head's inline padding and the banner's inline margin are both --space-4.
    pill = _box(page, "#clip-banner .clip-banner__line")
    head = _box(page, "[data-scope='editor'] .pane-head h2")
    assert abs(pill["x"] - head["x"]) <= 1
```

If the two edges genuinely differ by a fixed amount (e.g. the `h2` carries its own margin), fix the CSS, not the tolerance.

Continue the test body:

```python
    # 3. Open the list in A and check the link to B is really visible.
    page.locator("#clip-banner .clip-banner__units > summary").click()
    link = page.locator(f"#clip-banner a[href$='/unit/{b.pk}/edit/']")
    expect(link).to_be_visible()
    assert _inside(link.bounding_box(), _box(page, "#clip-banner"))
    last = page.locator("#clip-banner .clip-banner__units-list a").last
    last.scroll_into_view_if_needed()
    vb = {"x": 0, "y": 0, "width": 1280, "height": 720}
    assert _inside(last.bounding_box(), vb)
    # The ✕ stays on the pill with the list open.
    assert _inside(
        _box(page, "#clip-banner .clip-banner__line form button"),
        _box(page, "#clip-banner .clip-banner__line"),
    )

    # 4. Follow the link to B: the mark followed, copy controls only.
    link.click()
    page.wait_for_url(f"**/unit/{b.pk}/edit/")
    expect(page.locator("#clip-banner .clip-banner__from a")).to_be_visible()
    # Split width, long label: the "from" link keeps a real share of the pill.
    line = _box(page, "#clip-banner .clip-banner__line")
    frm = page.locator("#clip-banner .clip-banner__from a").bounding_box()
    assert frm["width"] > 0 and _inside(frm, line)

    # KaTeX containment at 1280x720, measured in B -- whose 25 rows overflow
    # .pane-body even with the list CLOSED, so its scrollHeight is content-bound and
    # must not change: the page is viewport-locked and the list scrolls inside
    # itself. .pane-body keeps at least ~40% of the pane.
    pane_body_h = (
        "document.querySelector('[data-scope=\"editor\"] .pane-body').scrollHeight"
    )
    doc_h = page.evaluate("document.documentElement.scrollHeight")
    body_h = page.evaluate(pane_body_h)
    page.locator("#clip-banner .clip-banner__units > summary").click()
    assert page.evaluate("document.documentElement.scrollHeight") == doc_h
    assert page.evaluate(pane_body_h) == body_h
    share = page.evaluate(
        "(() => { const p = document.querySelector('[data-scope=\"editor\"]');"
        " return p.querySelector('.pane-body').clientHeight / p.clientHeight; })()"
    )
    assert share >= 0.4, share
    page.locator("#clip-banner .clip-banner__units > summary").click()  # close it
    expect(page.locator("form[data-op='element-paste'] button[value='move']")).to_have_count(0)

    # 5. Copy before the middle row, waiting on the REQUEST.
    anchor = rows[12]
    with page.expect_response(lambda r: "element/paste/" in r.url):
        page.locator(
            f".el-row[data-element='{anchor.pk}'] "
            "> .el-row__head .el-actions form[data-op='element-paste-before'] button"
        ).click()

    # Wait on a DOM condition first: the response can land before applyFragments
    # swaps the pane, and the order read below must see the NEW DOM.
    expect(page.locator('[data-scope="preview"]')).to_contain_text("COPYMARKER")
    order = page.eval_on_selector_all(
        '[data-scope="editor"] .element-list > .el-row[data-element]',
        "rows => rows.map(r => r.innerText)",
    )
    idx = next(i for i, t in enumerate(order) if "COPYMARKER" in t or LONG_LABEL[:20] in t)
    assert "BROW-12" in order[idx + 1]
    # The mark is kept (D8) and the swapped banner's maths is typeset.
    expect(page.locator("#clip-banner")).to_be_visible()
    expect(page.locator("#clip-banner .clip-banner__from a .katex")).to_have_count(1)
    page.locator("#clip-banner .clip-banner__units > summary").click()
    expect(
        page.locator("#clip-banner .clip-banner__units-list a .katex").first
    ).to_be_attached()
```

Then a second test at a narrow viewport:

```python
@pytest.mark.django_db(transaction=True)
def test_the_banner_survives_a_narrow_viewport(page, live_server):
    page.set_viewport_size({"width": 400, "height": 800})
    user = _make_pa_user("pa")
    course, a, b, subject, _rows = _seed(user)
    _login(page, live_server, "pa")
    # BASELINE: whatever horizontal overflow the unmarked editor page already has
    # at 400px is not the banner's doing; the banner must add none.
    page.goto(_editor(live_server, course, b))
    base_overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    page.goto(_editor(live_server, course, a))
    row = page.locator(f".el-row[data-element='{subject.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator("> .el-row__head .el-actions form[data-op='element-clip'] button").click()
    page.goto(_editor(live_server, course, b))

    line = _box(page, "#clip-banner .clip-banner__line")
    frm = page.locator("#clip-banner .clip-banner__from a").bounding_box()
    assert frm["width"] > 0 and _inside(frm, line)
    assert _inside(_box(page, "#clip-banner .clip-banner__line form button"), line)
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= base_overflow, (overflow, base_overflow)

    banner_h = page.evaluate("document.querySelector('#clip-banner').offsetHeight")
    doc_h = page.evaluate("document.documentElement.scrollHeight")
    page.locator("#clip-banner .clip-banner__units > summary").click()
    grew_doc = page.evaluate("document.documentElement.scrollHeight") - doc_h
    grew_banner = page.evaluate("document.querySelector('#clip-banner').offsetHeight") - banner_h
    assert abs(grew_doc - grew_banner) <= 1  # escaped .katex-mathml would add more
```

And the nothing-fits ✕ check, a third test:

```python
@pytest.mark.django_db(transaction=True)
def test_the_cancel_stays_on_the_pill_when_nothing_fits(page, live_server):
    from courses.models import CalloutElement
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from tests.factories import make_quiz_unit

    page.set_viewport_size({"width": 1280, "height": 720})
    user = _make_pa_user("pa")
    course, a, _b, _subject, _rows = _seed(user)
    quiz = make_quiz_unit(course=course, parent=None, title="Quiz Q")
    box = Element.objects.create(
        unit=a, content_object=CalloutElement.objects.create(kind="example")
    )
    Element.objects.create(
        unit=a,
        content_object=ChoiceQuestionElement.objects.create(stem="P.", multiple=False),
        parent=box,
        tab_id=CalloutElement.SLOT_ID,
    )
    _login(page, live_server, "pa")
    page.goto(_editor(live_server, course, a))
    # Mark through the row's own ⊹ control, as in the first test.
    row = page.locator(f".el-row[data-element='{box.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator("> .el-row__head .el-actions form[data-op='element-clip'] button").click()
    page.goto(_editor(live_server, course, quiz))

    expect(page.locator("#clip-banner .clip-banner__nothing")).to_be_visible()
    assert _inside(
        _box(page, "#clip-banner .clip-banner__line form button"),
        _box(page, "#clip-banner .clip-banner__line"),
    )
```

**The committed e2e file contains no `page.screenshot` calls.** Screenshots (Task 7 Step 6 covers them manually) come from a separate, **uncommitted** script modelled on the repo's tracked `tests/capture_*_screenshots.py` files, kept **outside the repo** (in the session scratchpad) and run from the worktree; it reuses `_seed`, drives the same steps, and writes light shots, then sets `user.theme = "dark"; user.save()` before a fresh login for the dark ones (never a cookie). Judge dark separately. Keeping it out of the tree matters: `ruff check .` / `ruff format --check .` in Step 6 lint untracked files too, so a scratch script under `tests/` would turn the gate red for a file never committed.

- [ ] **Step 2: Run the e2e tests**

Run: `uv run pytest -m e2e tests/test_e2e_cross_unit_copy.py`
Expected: all PASS.

- [ ] **Step 3: Falsify the KaTeX containment**

By hand: delete Task 7's new `editor.js` block (the `[data-math-title]` loop in `applyFragments`) → the post-swap `expect(page.locator("#clip-banner .clip-banner__from a .katex")).to_have_count(1)` red. Restore. Then remove `position: relative` from `.clip-banner__units-list` → the narrow test's growth assertion, or the first test's 1280×720 in-B assertion that the page's and `.pane-body`'s `scrollHeight` are unchanged, red. Restore. Then remove it from `.clip-banner__from a` → expected: the overflow-vs-baseline assertion red at 400px (the long source title truncates with its maths in the clipped tail). The nearest positioned ancestor is then `.clip-banner__line`, which may keep the twin inside the viewport: **if this mutant stays green, do not weaken or fake the assertion** — record in the PR body that the "from"-link containment is not caught by the e2e and why. Restore; `git diff`.

- [ ] **Step 4: Run the existing clipboard e2e tests**

Run: `uv run pytest -m e2e tests/test_e2e_clipboard.py tests/test_e2e_paste_before.py tests/test_e2e_before_after.py`
Expected: all PASS (they locate `#clip-banner`, which kept its id).

- [ ] **Step 4b: Commit the e2e test (before the timing step can halt)**

```bash
uv run ruff format tests/test_e2e_cross_unit_copy.py
uv run ruff check --no-cache .
uv run ruff format --check .
git status --short
git add tests/test_e2e_cross_unit_copy.py
# ALSO stage any file Steps 2-3 changed to make an e2e assertion pass -- most
# likely courses/static/courses/css/editor.css (alignment, share, containment)
# and possibly courses/static/courses/js/editor.js. Never the capture script.
git add courses/static/courses/css/editor.css courses/static/courses/js/editor.js  # only if changed
git commit -m "test(e2e): a copy follows the author to another unit"
git status --short
```

The final `git status --short` must show nothing (the capture script lives outside the repo) — any modified tracked file means an e2e fix was left out of the commit. If CSS/JS was changed, say so in the commit message (e.g. append "; fix banner geometry found by e2e").

- [ ] **Step 5: Timing on mat-pp (manual, reported in the PR)**

On the local dev database (never prod), in `uv run python manage.py shell`, pin the inputs:
```python
from django.db.models import Count
from django.test import Client
from courses.models import ContentNode, Course, Element
course = Course.objects.get(slug="mat-pp")  # the local copy; confirm the slug first
X, Y = (ContentNode.objects.filter(course=course, kind="unit")
        .annotate(n=Count("elements")).order_by("-n")[:2])  # the two largest units
def _descendants(j):
    kids = list(j.children.all())
    return len(kids) + sum(_descendants(k) for k in kids)
container_join = max(X.elements.filter(parent=None), key=_descendants)
client = Client(HTTP_HOST="localhost")
client.force_login(course.owner)
```
then write the mark and **save** it — `client.session` returns a fresh store on every access, so an unsaved assignment is silently lost and the GETs would time the cheap unmarked path:
```python
from django.urls import reverse

def editor_url(u):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": u.pk})

s = client.session
s["element_clip"] = {"unit": X.pk, "element": container_join.pk}
s.save()
# Untimed check that the GET really takes the marked CROSS-UNIT path. A body
# check, not response.context: context is None in a plain shell (it is only
# filled under Django's test instrumentation).
assert 'clip-banner__from' in client.get(editor_url(Y)).content.decode()
```
then time `client.get(editor_url(Y))` 5 times (median). Then time it again with the tree stubbed out — the difference is the **tree's** cost:
```python
from courses import views_manage
real_tree = views_manage.copy_units_tree
views_manage.copy_units_tree = lambda c: ({}, [], False)
# ... time client.get(editor_url(Y)) 5 times, median ...
views_manage.copy_units_tree = real_tree  # restore before any further timing
```
 Separately time `builder.unit_children_map(X)` 5 times — the **source-map** cost. Report both in the PR; the source-map cost is reported, not acted on. If the tree adds more than ~10% to the op, **stop and report** instead of improvising the flat fallback: it changes `copy_units_tree`'s return shape, both partials, and the tests that index the pruned map, and needs its own spec-level decision. Everything up to this point is committed (Step 4b), and Step 5 changes no tracked file, so the halt is clean — confirm with `git status --short` (empty) before stopping.

- [ ] **Step 6: Branch gate**

In chunks (a single full run is OOM-killed):

```bash
uv run pytest courses/tests
uv run pytest tests/test_[a-l]*.py --ignore-glob="*test_e2e_*"
uv run pytest tests/test_[m-r]*.py --ignore-glob="*test_e2e_*"
uv run pytest tests/test_[s-z]*.py --ignore-glob="*test_e2e_*"
uv run pytest tests/demo tests/lal_import
uv run pytest integrations notifications
uv run pytest -m e2e tests/test_e2e_clipboard.py tests/test_e2e_paste_before.py tests/test_e2e_before_after.py tests/test_e2e_cross_unit_copy.py tests/test_e2e_editor_row_layout.py tests/test_e2e_editor_force_open.py tests/test_e2e_preview_nested_locate.py
uv run ruff check --no-cache .
uv run ruff format --check .
```

(The last three e2e files click the Duplicate button or measure the row action bar, whose ⧉ became an SVG in Task 6. `tests/` alone is ~6,000 tests: one run of it is OOM-killed with 0-byte output, so it is split in three alphabetical chunks plus its two subdirectories. Before running, `ls -d tests/*/` and confirm every subdirectory under `tests/` is covered by a chunk — add one if a new directory exists. `addopts` already deselects e2e; the e2e line is separate.)

Read each summary line. Any failure in an unrelated file: A/B it on `origin/master` before blaming this branch.

Re-read the cross-unit query count now that Tasks 6–7's templates render on the same GET: set `test_a_cross_unit_marked_render_stays_within_its_query_ceiling`'s ceiling to `1` temporarily, read the real count from the failure, and if it moved since Task 4 update the `MEASURED BASELINE` line and the ceiling (count + 5). Commit that with Step 7.

Do the same for the SAME-UNIT sibling, `test_a_marked_render_does_not_walk_parents_per_slot`: every same-unit marked render now also pays `copy_units_tree`'s `_children_map` query (Task 4). Measure its real count the same way (ceiling to `1`, read the count, restore the ceiling — leave the ceiling at its current value if it still holds). In its docstring, add `copy_units_tree` (one `_children_map` query) to the cost list and replace "around 32" with the measured figure, keeping the docstring's line count unchanged. If the count exceeds the existing ceiling, stop and report — do not raise a ceiling without a reason. Commit with Step 7.

- [ ] **Step 7: Commit the branch-gate follow-ups (only if anything changed)**

```bash
git status --short
# If nothing is listed, skip this step: Step 4b already committed the e2e test.
uv run ruff format tests/test_element_paste_view.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add tests/test_element_paste_view.py  # only if either ceiling test changed (Step 6)
# ALSO any file a Step 6 failure fix touched -- by explicit path, never -A.
git commit -m "test(paste): re-measured cross-unit query ceiling after the banner templates"
git status --short
```

The final `git status --short` must show nothing — any modified tracked file means a Task 8 fix was left out of the commit. If a Step 6 fix touched anything beyond the ceiling, say so in the commit message.

- [ ] **Step 8: Collect what the PR body must include**

Write these into a scratch note **in the session scratchpad, never inside the worktree** (an untracked file there fails Step 9's empty-`git status` check), and pass its path to whoever opens the PR:
1. The deviations table V1–V6, each with its outcome — for V6 the measured `.pane-body` share and the cap actually used (or "not needed").
2. V2's result: whether removing `position: relative` from the "from" link was caught by the e2e.
3. The two timing figures from Step 5 (tree render cost; source-map cost) and whether the tree crossed ~10%.
4. The light and dark screenshots from Task 7 Step 6 / the capture script.
5. Any CSS/JS fix Task 8 made, and the final measured query ceiling.
6. Owner decisions D10 (interactive elements refused into a quiz, cross-unit only) and D11 (the rare deadlock outcomes) as reminders for the reviewer.

- [ ] **Step 9: Rebase and regenerate the binary catalogues**

The `.mo` files are binary and cannot be merged by hand, so bring the branch up to date before the PR:
```bash
git fetch origin
git rebase origin/master
```
If upstream touched either catalogue, the rebase **stops mid-way** at the replayed Task 6 commit with a conflict on the binary `.mo` (both sides changed it). Resolve it there, mid-rebase:
1. Resolve the `.po` conflict markers by hand (keep both sides' entries); never try to merge a `.mo`.
2. Re-run Task 6 Step 8's catalogue procedure: `makemessages -l pl -l en --no-obsolete`, re-check the five Polish msgstrs, the fuzzy count = 0, `compilemessages -l pl -l en` (this regenerates both `.mo` from the resolved `.po`), `uv run pytest tests/test_i18n_po_health.py`.
3. `git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo`
4. `git rebase --continue`. Repeat 1–4 if a later commit conflicts on the catalogues too.

If upstream changed a `.po` without a conflict stopping the rebase, still run step 2 after the rebase and commit all four catalogue files by explicit path. Step 6's branch gate ran **before** the rebase: re-run every Step 6 chunk that holds a file the rebase touched (`git diff --name-only ORIG_HEAD HEAD` lists them — upstream's changes as well as yours), plus `tests/test_i18n_po_health.py`, before handing off. `git status --short` must be empty afterwards.

---

## Self-review against the spec

| Spec section | Task |
|---|---|
| §1 `_clip_context` lookups, keys, empty dict, comment rewrites | 4 (element_paste comment: 5) |
| §2 clause 0 / 2c / 2d, `QUIZ_EXCLUDED_TYPE_KEYS`, drift guard, AST guard, 2b comment, precedence | 1, 2 |
| §3 `SubtreeFacts` fields, function-local imports, orphan note, cost split | 1, 3 |
| §4 `paste_element` steps 1–9, lock order + docstring, mode first, return dest | 3 |
| §5 `_copy_into` signature, source export, marking fields pinned | 3 |
| §6 `graft_elements` docstring, line-count neutral | 3 |
| §7 stale-form check, check order, move reload, deadlock 409, tag dicts | 5 |
| §8 banner div + order, flex line, KaTeX containment, ✕ re-scope, inset, `:has()` deletion, stale comments, wide layout cap, tree partials, pruning, typesetting after swap, icons, i18n both catalogues | 6, 7 |
| Error-handling table | 3, 4, 5 |
| Testing — rule, service, views, e2e, mutants | 1–8 |
| Out-of-scope in-unit changes (five) | 3 (before+copy), 5 (stale form, deadlock), 6 (banner, icons) |

---

## Amendment tasks — D13 (added 2026-09-19, after Task 8 halted at Step 5)

Task 8 is complete through Step 4b (commit `9c467ea5`: the e2e file). Its Step 5 halted: the fully-expanded unit list cost 15–16% of a marked render on mat-pp. The owner chose **D13** (spec, "Amendment: D13"): a collapsible tree whose levels load on expand. Task 9 builds it; Task 10 resumes Task 8 from Step 5.

### Task 9: The unit list loads each level on expand (D13)

**Files:**
- Modify: `courses/views_manage.py` (`copy_units_open_path` new; `copy_units_level` view new; `_clip_context` + `_cross_unit_clip_context` gain `copy_units_open`; `copy_units_tree` docstring)
- Modify: `courses/urls.py` (one path)
- Modify: `templates/courses/manage/editor/_copy_units_tree.html`, `templates/courses/manage/editor/_copy_units_node.html`
- Create: `templates/courses/manage/editor/_copy_units_level.html`
- Modify: `templates/courses/manage/editor/editor.html` (one `data-msg-*` attribute)
- Modify: `courses/static/courses/js/editor.js`, `courses/static/courses/css/editor.css`
- Modify: `locale/{pl,en}/LC_MESSAGES/django.{po,mo}`
- Test: `tests/test_element_paste_view.py`, `tests/test_editor_clip_templates.py`, `tests/test_e2e_cross_unit_copy.py`

**Interfaces:**
- Consumes: `copy_units_tree(course) -> (pruned_map, pruned_top, available)` (Task 4, unchanged).
- Produces:
  - `copy_units_open_path(units_map, unit) -> set[int]`.
  - `_clip_context` key `copy_units_open` (fourteenth key; `set()` in the empty dict).
  - URL `courses:manage_copy_units` → `copy_units_level(request, slug)`, GET `?parent=<pk>&current=<pk>`.
  - Row partial `_copy_units_node.html` variables: `n`, `copy_units_map`, `copy_units_open`, `current_pk`, `course_slug`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_element_paste_view.py` (add `from courses.views_manage import copy_units_open_path` to the imports; `ContentNode`, `CourseFactory`, `reverse` are needed — import any that are missing):

```python
def test_copy_units_open_path_is_every_container_above_the_unit():
    course = CourseFactory()
    part = _unit(course, "P", kind="part", unit_type="")
    chapter = _unit(course, "C", kind="chapter", unit_type="", parent=part)
    deep = _unit(course, "Deep", parent=chapter)
    _unit(course, "Other")

    units_map, _top, _available = copy_units_tree(course)

    assert copy_units_open_path(units_map, deep) == {part.pk, chapter.pk}


def test_copy_units_open_path_is_empty_for_a_root_level_unit():
    course = CourseFactory()
    root = _unit(course, "Root")
    part = _unit(course, "P", kind="part", unit_type="")
    _unit(course, "Under", parent=part)

    units_map, _top, _available = copy_units_tree(course)

    assert copy_units_open_path(units_map, root) == set()


def test_copy_units_open_path_is_empty_for_a_unit_not_in_the_map():
    course = CourseFactory()
    _unit(course, "A")
    _unit(course, "B")
    stranger = _unit(CourseFactory(), "Elsewhere")

    units_map, _top, _available = copy_units_tree(course)

    assert copy_units_open_path(units_map, stranger) == set()


def _level(client, course, parent=None, current=None):
    params = {}
    if parent is not None:
        params["parent"] = parent if isinstance(parent, (int, str)) else parent.pk
    if current is not None:
        params["current"] = current.pk
    return client.get(
        reverse("courses:manage_copy_units", kwargs={"slug": course.slug}), params
    )


def _other_course_with_a_part(course):
    other = CourseFactory(owner=course.owner)
    part = _unit(other, "ForeignPart", kind="part", unit_type="")
    _unit(other, "ForeignUnit", parent=part)
    return other, part


def test_a_level_lists_its_units_as_links_and_its_containers_collapsed(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    leaf = _unit(course, "LeafUnit", parent=part)
    chapter = _unit(course, "ChapterC", kind="chapter", unit_type="", parent=part)
    _unit(course, "GrandchildUnit", parent=chapter)

    resp = _level(client, course, part)

    assert resp.status_code == 200
    body = resp.content.decode()
    leaf_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": leaf.pk}
    )
    assert f'href="{leaf_url}"' in body
    assert "ChapterC" in body
    assert 'class="clip-banner__group"' in body
    assert "data-units-url=" in body
    assert "GrandchildUnit" not in body  # collapsed: no grandchild rows


def test_a_level_marks_the_current_unit_and_does_not_link_it(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    here = _unit(course, "HereUnit", parent=part)
    _unit(course, "ThereUnit", parent=part)

    body = _level(client, course, part, current=here).content.decode()

    here_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": here.pk}
    )
    assert 'aria-current="page"' in body
    assert f'href="{here_url}"' not in body


def test_a_level_of_a_unitless_container_is_a_404(client):
    """Mutant: serve the UNPRUNED _children_map instead of the pruned map -> RED."""
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)
    empty = _unit(course, "EmptySection", kind="section", unit_type="", parent=part)

    assert _level(client, course, empty).status_code == 404


def test_a_level_of_a_unit_or_a_foreign_or_bad_node_is_a_404(client):
    course, x = _seed(client)
    _other, foreign_part = _other_course_with_a_part(course)

    assert _level(client, course, x).status_code == 404  # a unit
    assert _level(client, course, foreign_part).status_code == 404
    assert _level(client, course, "abc").status_code == 404
    assert _level(client, course).status_code == 404  # no parent at all
```

For the permission test, look at how this file (or `tests/test_element_clip_view.py`) already builds "a logged-in author who cannot manage this course" and reuse that exact construction — do not invent one. Then:

```python
def test_a_level_is_refused_to_a_user_who_cannot_manage_the_course(client):
    """Mutant: drop the can_manage_course check -> RED."""
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)
    # <log the client in as an author who cannot manage `course`, as the existing
    #  permission tests do>

    assert _level(client, course, part).status_code == 403


def test_a_level_needs_a_login(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)
    client.logout()

    assert _level(client, course, part).status_code == 302


def test_a_level_refuses_post(client):
    course, _x = _seed(client)
    part = _unit(course, "PartP", kind="part", unit_type="")
    _unit(course, "Under", parent=part)

    resp = client.post(
        reverse("courses:manage_copy_units", kwargs={"slug": course.slug}),
        {"parent": part.pk},
    )

    assert resp.status_code == 405


def test_a_levels_query_count_does_not_grow_with_its_size(client):
    """Mutant: a per-row query in the row partial (e.g. n.course.slug instead of
    course_slug in the unit link) -> RED."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course, _x = _seed(client)
    small = _unit(course, "Small", kind="part", unit_type="")
    _unit(course, "S1", parent=small)
    big = _unit(course, "Big", kind="part", unit_type="")
    for i in range(30):
        _unit(course, f"B{i}", parent=big)
    _level(client, course, small)  # warm the session/auth path

    with CaptureQueriesContext(connection) as small_q:
        _level(client, course, small)
    with CaptureQueriesContext(connection) as big_q:
        _level(client, course, big)

    assert len(big_q) == len(small_q)
```

In `test_the_clip_context_keys_reach_both_render_paths`: "thirteen" → "fourteen", and add `copy_units_open` to whatever key list it checks.

In `tests/test_editor_clip_templates.py`:

- Re-anchor `_banner`'s end — nested `<details>` now close before the banner does, so "the first `</details>`" is no longer the banner's end:

```python
def _banner(body):
    start = body.index('id="clip-banner"')
    return body[start : body.index('class="pane-body"', start)]
```

  Re-run every existing test that uses `_banner` or slices on `</details>` (`test_the_destination_banner_links_back_to_the_source` slices to `"<details"` — still correct).
- Rewrite `test_the_unit_list_handles_an_irregular_course`: keep its root-level assertion and its `"EmptySectionE" not in banner` assertion; replace `f'href="{_editor_url(course, under_part)}"' in banner` with three assertions — the part renders as `<details class="clip-banner__group" data-units-url=` (collapsed: no `open`); `under_part`'s href is **absent** from the initial render; a GET of `courses:manage_copy_units` with `parent=part.pk` contains it.
- Add:

```python
def test_the_path_to_the_current_unit_is_open_and_other_containers_are_not(client):
    """Mutant: render every container open ({% elif True %} in
    _copy_units_node.html) -> RED on the sibling assertions."""
    course, x = _seed(client)
    part = _unit(course, "PathPart", kind="part", unit_type="")
    chapter = _unit(course, "PathChapter", kind="chapter", unit_type="", parent=part)
    here = _unit(course, "HereUnit", parent=chapter)
    sibling = _unit(course, "SiblingPart", kind="part", unit_type="")
    hidden = _unit(course, "HiddenUnit", parent=sibling)
    subject = _text(x)
    _mark(client, course, x, subject)

    banner = _banner(_editor(client, course, here))

    assert banner.count('<details class="clip-banner__group" open') == 2
    assert 'aria-current="page"' in banner and "HereUnit" in banner
    assert "SiblingPart" in banner  # its row is there, collapsed
    assert "HiddenUnit" not in banner
    assert f'href="{_editor_url(course, hidden)}"' not in banner
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_element_paste_view.py tests/test_editor_clip_templates.py -k "open_path or level or path_to_the_current or irregular or clip_context_keys"`
Expected: FAIL — `ImportError: cannot import name 'copy_units_open_path'`, `NoReverseMatch: … 'manage_copy_units'`, and the template assertions.

- [ ] **Step 3: Server**

In `courses/views_manage.py`, directly after `copy_units_tree`:

```python
def copy_units_open_path(units_map, unit):
    """The container pks with `unit` somewhere below them, from copy_units_tree()'s
    PRUNED map -- no query. These render open, with their rows, so the current unit is
    visible when the list opens (spec D13); every other container renders collapsed and
    loads its rows from copy_units_level on first open."""
    parent_of = {}
    for parent_pk, kids in units_map.items():
        for kid in kids:
            parent_of[kid.pk] = parent_pk
    path = set()
    node_pk = parent_of.get(unit.pk)
    while node_pk is not None:
        path.add(node_pk)
        node_pk = parent_of.get(node_pk)
    return path
```

Rewrite `copy_units_tree`'s docstring sentence "so the template iterates only what it renders -- a Django template cannot look ahead" to add that the banner renders only the top level and the open path, the rest arriving through `copy_units_level` (spec D13). Its code is unchanged.

In `_clip_context`: add `"copy_units_open": set(),` to `empty`; in the same-unit branch, directly after the `copy_units_tree(unit.course)` line, add `units_open = copy_units_open_path(units_map, unit)`, and add `"copy_units_open": units_open,` to the returned dict. The same two edits in `_cross_unit_clip_context`. Update both docstrings' key lists ("thirteen" → "fourteen", name `copy_units_open`).

New view, directly after `link_picker` (which it mirrors):

```python
@login_required
@require_GET
def copy_units_level(request, slug):
    """One level of the "Copy to another unit..." tree, as bare <li> rows (spec D13).

    The banner renders the top level and the open path; a collapsed container fetches
    its rows here the first time the author opens it (editor.js). `current` only marks
    the author's unit as aria-current text; a missing or bad value marks nothing. 404
    for anything that is not a container WITH a unit below it in this course -- the
    pruned map is the authority, so a crafted parent cannot list what the banner hides.
    """
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    units_map, _top, _available = copy_units_tree(course)
    try:
        parent_pk = int(request.GET.get("parent", ""))
    except ValueError:
        raise Http404 from None
    if parent_pk not in units_map:
        raise Http404
    try:
        current_pk = int(request.GET.get("current", ""))
    except ValueError:
        current_pk = None
    return render(
        request,
        "courses/manage/editor/_copy_units_level.html",
        {
            "rows": units_map[parent_pk],
            "copy_units_map": units_map,
            "copy_units_open": set(),
            "current_pk": current_pk,
            "course_slug": course.slug,
        },
    )
```

`None` is a key of the pruned map (the roots), but `int()` never yields it, so the top level is never served here (the banner always renders it). Import `require_GET` (`django.views.decorators.http`) and `Http404` (`django.http`) only if the file does not already. In `courses/urls.py`, directly after the `manage_link_picker` path:

```python
    path(
        "manage/courses/<slug:slug>/copy-units/",
        views_manage.copy_units_level,
        name="manage_copy_units",
    ),
```

- [ ] **Step 4: Templates**

`templates/courses/manage/editor/_copy_units_level.html` (new):

```django
{% comment %}
One level of the copy-units tree for copy_units_level (spec D13): bare <li> rows,
rendered by the SAME row partial as the banner, so the two can never differ.
{% endcomment %}
{% for n in rows %}{% include "courses/manage/editor/_copy_units_node.html" with n=n %}{% endfor %}
```

`templates/courses/manage/editor/_copy_units_node.html` (replace the whole file):

```django
{% load courses_manage_extras %}
{% comment %}
One row of the copy-units tree (spec D13). A unit is a link to its editor page, or --
the CURRENT unit -- text with aria-current. A container is its own <details>: OPEN with
its rows when it is on the path to the current unit (copy_units_open), otherwise
collapsed and EMPTY, carrying data-units-url so editor.js fetches its rows from
copy_units_level on first open. Recurses only into open containers. Badges are the
link picker's markup (twinned in editor.css). Takes n, copy_units_map,
copy_units_open, current_pk, course_slug -- never unit/course objects, so the endpoint
and the banner render identical rows and no row costs a query.
{% endcomment %}
<li class="clip-banner__unit">
  {% if n.kind == "unit" %}
    {% if n.unit_type == "quiz" %}<span class="tree__badge tree__badge--unit tree__badge--quiz" title="{{ n.get_unit_type_display }}">Q</span>{% else %}<span class="tree__badge tree__badge--unit tree__badge--lesson" title="{{ n.get_unit_type_display }}">L</span>{% endif %}
    {% if n.pk == current_pk %}<span class="clip-banner__unit-current" aria-current="page" data-math-title>{{ n.title }}</span>{% else %}<a href="{% url 'courses:manage_editor' slug=course_slug pk=n.pk %}" data-math-title>{{ n.title }}</a>{% endif %}
  {% elif n.pk in copy_units_open %}
    <details class="clip-banner__group" open data-loaded>
      <summary><span class="tree__badge tree__badge--{{ n.kind }}">{{ n.get_kind_display }}</span> <span class="clip-banner__unit-group" data-math-title>{{ n.title }}</span></summary>
      {% with children=copy_units_map|get_item:n.pk %}<ol>{% for child in children %}{% include "courses/manage/editor/_copy_units_node.html" with n=child %}{% endfor %}</ol>{% endwith %}
    </details>
  {% else %}
    <details class="clip-banner__group" data-units-url="{% url 'courses:manage_copy_units' slug=course_slug %}?parent={{ n.pk }}{% if current_pk %}&amp;current={{ current_pk }}{% endif %}">
      <summary><span class="tree__badge tree__badge--{{ n.kind }}">{{ n.get_kind_display }}</span> <span class="clip-banner__unit-group" data-math-title>{{ n.title }}</span></summary>
      <ol></ol>
    </details>
  {% endif %}
</li>
```

In `_copy_units_tree.html`: change the include to `{% include "courses/manage/editor/_copy_units_node.html" with n=n current_pk=unit.pk course_slug=unit.course.slug %}` (the other variables come from the context), and rewrite its `{% comment %}` for D13 (the server renders the top level and the open path; other levels load on expand from `copy_units_level`; every unit is still a plain link). The `.clip-banner__units` / `.clip-banner__units-list` classes stay.

`editor.html`: add to the editor root `<section class="editor" …>`, next to the other `data-msg-*` attributes: `data-msg-units-error="{% trans 'Could not load the units.' %}"`.

- [ ] **Step 5: JS**

In `editor.js`, add a helper next to `renderPreviewMath`, and replace the inline `[data-math-title]` loop Task 7 added in `applyFragments` with `typesetTitles(editorScope);` (keep that block's comment):

```js
  // Typeset only [data-math-title] nodes that hold a delimiter (see applyFragments).
  function typesetTitles(scope) {
    scope.querySelectorAll("[data-math-title]").forEach(function (node) {
      var text = node.textContent;
      if (text.indexOf("\\(") === -1 && text.indexOf("\\[") === -1) return;
      renderPreviewMath(node);
    });
  }
```

Add, directly before the existing capture-phase `root.addEventListener("toggle", …)`:

```js
  // "Copy to another unit..." (spec D13): a collapsed container fetches its rows once,
  // on first open. data-loading guards a double toggle; a failure leaves it unloaded,
  // so closing and re-opening retries.
  function loadUnitsLevel(details) {
    if (!details.open || details.hasAttribute("data-loaded") || details.hasAttribute("data-loading")) return;
    var list = details.querySelector(":scope > ol");
    var url = details.getAttribute("data-units-url");
    if (!list || !url) return;
    details.setAttribute("data-loading", "");
    fetch(url, { headers: { "X-Requested-With": "fetch" } })
      .then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.text(); })
      .then(function (html) {
        list.innerHTML = html;
        details.setAttribute("data-loaded", "");
        typesetTitles(list);
      })
      .catch(function () {
        list.innerHTML = "";
        var li = document.createElement("li");
        li.className = "clip-banner__unit clip-banner__unit--error";
        li.textContent = msg("units-error", "Could not load the units.");
        list.appendChild(li);
      })
      .then(function () { details.removeAttribute("data-loading"); });
  }
```

and extend that existing listener (do not add a second `toggle` listener):

```js
  root.addEventListener("toggle", function (e) {
    if (e.target.matches && e.target.matches(SLOT_DETAILS)) saveSlot(e.target);
    if (e.target.matches && e.target.matches("details.clip-banner__group")) loadUnitsLevel(e.target);
  }, true);
```

Match the file's style (`var`, `function`, no arrow functions). `msg()` and `root` already exist.

- [ ] **Step 6: CSS**

In `editor.css`, directly after the `.clip-banner__unit-current` rule:

```css
/* D13: a container row is its own <details>; its rows arrive on first open. */
.clip-banner__group > summary { cursor: pointer; }
.clip-banner__group > ol { margin: 0; padding-inline-start: var(--space-4); }
.clip-banner__unit--error { color: var(--text-secondary); font-style: italic; }
```

Check it in light and dark with Task 7's scratch-script approach (screenshots in the scratchpad, never the worktree): the list with the open path, and one other part opened by clicking.

- [ ] **Step 7: Catalogue**

As Task 6 Step 8 (`makemessages -l pl -l en --no-obsolete`; never hand-edit `en`): Polish `Could not load the units.` → `Nie udało się wczytać jednostek.`; clear any `#, fuzzy` and `#|` line on it (makemessages fuzzy-prefills wrong translations); fuzzy count 0 (grep without `$`); `compilemessages -l pl -l en`; `uv run pytest tests/test_i18n_po_health.py` PASS.

- [ ] **Step 8: e2e**

In `tests/test_e2e_cross_unit_copy.py`, `_seed` gains, after the filler units, a root-level part holding one unit with a maths title:

```python
    part = ContentNodeFactory(
        course=course, kind="part", unit_type="", parent=None, title="Deep part"
    )
    deep = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        title="Deep unit \\(z^2\\)",
    )
```

and returns them too (`return course, a, b, subject, rows, part, deep`; update every caller's unpacking — nothing else in the three existing tests changes, their units are root-level). Add:

```python
@pytest.mark.django_db(transaction=True)
def test_a_collapsed_part_loads_its_units_on_open(page, live_server):
    page.set_viewport_size({"width": 1280, "height": 720})
    user = _make_pa_user("pa")
    course, a, _b, subject, _rows, part, deep = _seed(user)
    _login(page, live_server, "pa")
    page.goto(_editor(live_server, course, a))
    row = page.locator(f".el-row[data-element='{subject.pk}']")
    with page.expect_response(lambda r: "element/clip/" in r.url):
        row.locator(
            "> .el-row__head .el-actions form[data-op='element-clip'] button"
        ).click()

    page.locator("#clip-banner .clip-banner__units > summary").click()
    deep_link = page.locator(f"#clip-banner a[href$='/unit/{deep.pk}/edit/']")
    expect(deep_link).to_have_count(0)  # collapsed: not in the DOM yet

    group = page.locator(
        f"#clip-banner details.clip-banner__group[data-units-url*='parent={part.pk}']"
    )
    with page.expect_response(lambda r: "copy-units/" in r.url and r.status == 200):
        group.locator("> summary").click()

    expect(deep_link).to_be_visible()
    expect(deep_link.locator(".katex")).to_have_count(1)
    deep_link.click()
    page.wait_for_url(f"**/unit/{deep.pk}/edit/")
    expect(page.locator("#clip-banner .clip-banner__from a")).to_be_visible()
```

(The `_seed` title for `part` must not be "Unit …" — the existing tests locate units by href, not title, so this is safe; check nothing in them counts top-level rows.)

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tests/test_element_paste_view.py tests/test_editor_clip_templates.py tests/test_element_clip_view.py tests/test_editor_styles.py tests/test_i18n_po_health.py`
then: `uv run pytest -m e2e tests/test_e2e_cross_unit_copy.py tests/test_e2e_clipboard.py tests/test_e2e_paste_before.py tests/test_e2e_before_after.py`
Expected: all PASS. If a query-ceiling test moved, re-measure the cross-unit one as Task 4 Step 5b does; the same-unit ceiling is never raised — investigate instead.

- [ ] **Step 10: Falsify**

By hand, one at a time, each reverted by hand, `git diff` after each:
1. In `_copy_units_node.html`, `{% elif n.pk in copy_units_open %}` → `{% elif True %}` → `test_the_path_to_the_current_unit_is_open_and_other_containers_are_not` red.
2. Delete the `can_manage_course` check in `copy_units_level` → `test_a_level_is_refused_to_a_user_who_cannot_manage_the_course` red.
3. In `copy_units_level`, serve the unpruned map (`cmap = _children_map(course)`, 404 only when `parent_pk not in cmap`, rows `cmap[parent_pk]`) → `test_a_level_of_a_unitless_container_is_a_404` red (`EmptySection` has no children so it is not a key of `cmap` either — if this mutant stays green, make the empty section hold a *container* with no unit, e.g. an empty chapter, so it IS a `cmap` key; record which fixture you used).
4. In the row partial's unit link, `slug=course_slug` → `slug=n.course.slug` → `test_a_levels_query_count_does_not_grow_with_its_size` red.
5. Delete the `loadUnitsLevel(e.target)` line from the toggle listener → `test_a_collapsed_part_loads_its_units_on_open` red (no `copy-units/` response).
6. Delete `typesetTitles(list);` in the loader → the same e2e test red on the `.katex` count.

- [ ] **Step 11: Commit**

```bash
uv run ruff format courses/views_manage.py courses/urls.py tests/test_element_paste_view.py tests/test_editor_clip_templates.py tests/test_e2e_cross_unit_copy.py
uv run ruff check --no-cache .
uv run ruff format --check .
git add courses/views_manage.py courses/urls.py templates/courses/manage/editor/_copy_units_tree.html templates/courses/manage/editor/_copy_units_node.html templates/courses/manage/editor/_copy_units_level.html templates/courses/manage/editor/editor.html courses/static/courses/js/editor.js courses/static/courses/css/editor.css locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo locale/en/LC_MESSAGES/django.po locale/en/LC_MESSAGES/django.mo tests/test_element_paste_view.py tests/test_editor_clip_templates.py tests/test_e2e_cross_unit_copy.py
git commit -m "feat(paste): the unit list loads each level on expand (D13)"
git status --short
```

`git status --short` must be empty afterwards.

### Task 10: Resume Task 8 from Step 5

Run Task 8's Steps 5–9 as written, with these changes:
- **Step 5 (timing):** same inputs and method; report the tree cost (full GET vs `copy_units_tree` stubbed) and the source-map cost. **No fallback triggers any more** (D13 replaced it): report the figures; if the tree still exceeds ~10%, say so plainly in the PR notes for the owner — do not change the design.
- **Step 6 (branch gate):** unchanged (the e2e line already lists `tests/test_e2e_cross_unit_copy.py`); both query-ceiling re-reads as written.
- **Step 7:** commit only if something changed.
- **Step 8 (PR notes):** add V7 and V8/D13 with the before/after timing, and that the `en` catalogue picked up the pre-existing untranslated "Equal columns" (#335).
- **Step 9 (rebase):** unchanged.
