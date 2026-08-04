# Element clipboard (PR2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the unit editor a clipboard — ⊹ *select* an element, then **📋 Move here** or **⧉ Copy here** on any legal slot — so an existing element can finally be moved *into* a container, and one element can seed several tabs.

**Architecture:** One authority (`paste_allowed`) decides admissibility and is called twice: once per slot by the render to decide which buttons exist, and once inside the paste transaction to enforce. A second new function (`enumerate_slots`) walks the unit's FK tree once to produce the slot list the render iterates. The mark lives in the session, so the paste buttons are part of the fragment pair every editor operation already returns — no new JavaScript. A move re-parents the root join and lets the FK carry the subtree; a copy reuses PR1's export/graft pair.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, server-rendered templates, vanilla JS (no framework), Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-03-element-clipboard-design.md`. This plan implements **PR2 only**; PR1 (duplicate in place) merged as #213 and is on master.

## Global Constraints

- **Tooling is not on PATH.** Every Python command runs through `uv run` — `uv run pytest`, `uv run ruff`, `uv run python`. A bare `pytest` will not resolve.
- **Worktree:** all work happens in `C:/Users/krzys/Documents/Python/own/libli/.claude/worktrees/elclip-pr2` on branch `feat/element-clipboard-pr2`. Never `cd` to the main checkout or to a sibling worktree.
- **One pytest invocation at a time, in the FOREGROUND.** Test databases are shared per `DATABASE_URL`; a backgrounded run that is abandoned leaves an idle connection and the next run dies with `DuplicateDatabase`.
- **`pyproject.toml` already sets `addopts = "-q -m 'not e2e'"`.** Do not pass a second `-q` — it suppresses the summary line entirely. e2e tests are deselected by default and need an explicit `-m e2e`; without it pytest exits 5 with no tests run, which reads like a pass.
- **`MAX_NEST_DEPTH = 4`** (`courses/builder.py:26`), a top-level element is depth 1.
- **`cap(n)` = `MAX_NEST_DEPTH - 1` for a container, `MAX_NEST_DEPTH` for a leaf** → 3 or 4. A container may live at depth 1–3 and never at 4.
- **Reason keys are a fixed set:** `paste_allowed` returns exactly one of `wrong_unit`, `into_own_subtree`, `not_a_container`, `unknown_slot`, `type_not_nestable`, `too_deep`, `own_slot` — and no others. The view adds one more of its own, `parent_gone`, which it synthesises from `ParentGoneError` rather than receiving from the rule. Each of the eight maps to one translatable string at the view.
- **Status mapping is fixed:** `ConflictError` → 409, `NestingError` → 400, `ParentGoneError` → 422, `PlacementRefused` → 422, `TransferError` → 422.
- **Editor-context errors never use `_op_error`.** `editor.js` swaps only `[data-scope]` elements and `_op_error.html` has no such wrapper. Every editor-context error renders through `_render_editor_fragments(..., status=…, error=…)`, whose slot PR1 already added to `_editor_scope.html:16`.
- **No hardcoded test passwords.** Use `tests.factories.TEST_PASSWORD`.
- **Run `uv run ruff format` before every commit step**, not only at the end. `ruff format --check .` and `ruff check .` run at the end and fail on code committed six tasks earlier just as readily as on the last task's. If a code block in this plan would trip `ruff check` (e.g. an unused local), rename it with a `_` prefix — that is this plan's own idiom, not a deviation.
- **Module-level translatable strings use `gettext_lazy`;** in-function strings use `gettext as _`. `courses/builder.py` already imports `gettext as _` (`:5`).
- **`Element.order` is `OrderField(for_fields=["unit"])`** (`courses/models.py:319`) — unit-wide, so a freshly created join is born with `max+1` and sorts last within its group.
- **Django template comments:** `{# #}` must be single-line; multi-line uses `{% comment %}`.
- **Slots are read with the NON-DESTRUCTIVE normalizer** from `_CONTAINER_REGISTRY`, always via `normalizer(getattr(obj, "data", None))[list_key]`. `SpoilerElement` has no `data` field at all and the argument is evaluated before the normalizer runs, so `obj.data` is an `AttributeError` — a 500 — on every unit containing a spoiler.
- **`request.session["element_clip"]` stores both pks as `int`**, coerced on write; the view stringifies on the way out (`str(clip["element"])`) because the template compares with `el.pk|stringformat:'s'`.
- **PR2 adds no JavaScript.** PR1 already shipped the `data-force-open` stamp and the `applyStoredTabs` skip that PR2's force-open depends on.
- **`reorder_element` is not touched.** Its "cross-scope move is impossible by construction" guarantee stays exactly as written.
- **Every line number in this plan is as of master (`e7535af0`) and WILL drift as the plan executes.** Task 2 alone doubles the `_CONTAINER_REGISTRY` block and Tasks 3, 5 and 6 add several hundred lines above `_copy_below`, so by Task 7 the anchors quoted for `courses/builder.py` are simply wrong as numbers. **Locate every insertion point by symbol name** — `resolve_scope`, `_copy_below`, `delete_node`, `_render_editor_fragments`, `_editor_page`, `element_duplicate` — and treat the numbers as a hint about which of several similar-looking places is meant. Report any drift you find rather than editing at the stated line.

---

## File Structure

**Created:**
- `courses/tests/test_paste_rule.py` — `subtree_facts`, `paste_allowed`, the truncation case
- `courses/tests/test_paste_rule_agreement.py` — the `paste_allowed` ↔ `resolve_scope` equivalence
- `tests/test_enumerate_slots.py` — the slot enumerator, its traps and its query count
- `tests/test_builder_paste_element.py` — the service: move semantics, copy semantics, ordering, token
- `tests/test_element_clip_view.py` — the select/cancel endpoint and the session lifecycle
- `tests/test_element_paste_view.py` — the paste endpoint's status matrix and bodies
- `tests/test_editor_clip_templates.py` — paste buttons, marked row, banner, forced-open
- `templates/courses/manage/editor/_paste_buttons.html` — the inclusion tag's template
- `tests/test_scope_parse.py` — the shared scope parse, `ParentGoneError`, and the `element_add` regression guard
- `tests/test_e2e_clipboard.py` — the one browser-only behaviour

**Modified:**
- `courses/transfer/export.py` — promote `_MODEL_TO_KEY` to a public `model_to_key()` helper
- `courses/builder.py` — `_CONTAINER_REGISTRY` gains a 4th element (slot cap); `resolve_scope`'s unpack; `_parse_scope_ref` split out; `ParentGoneError`; `PlacementRefused`; `subtree_facts`; `paste_allowed`; `enumerate_slots`; `paste_element`
- `courses/tests/test_nesting_rule.py` — the strengthened container-key drift assertion
- `courses/views_manage.py` — `_clip_context` helper; `element_clip`; `element_paste`; both context builders gain the clip keys
- `courses/urls.py` — two paths
- `courses/templatetags/courses_manage_extras.py` — the `paste_buttons` inclusion tag
- `templates/courses/manage/editor/_element_row_controls.html` — the ⊹ select form, between the duplicate and delete forms
- `templates/courses/manage/editor/_element_row.html` — paste-tag call at 3 nested sites, `clip_active` in both `<details>` conditions, marked-row modifier on all 6 branches
- `templates/courses/manage/editor/_editor_scope.html` — paste-tag call at the top-level slot, the mark banner in `.pane-head`
- `courses/static/courses/css/editor.css` — marked row, banner, paste-button grouping

**Responsibility split:** `builder` owns the rule, the transaction, the locks and the ordering; `views_manage` owns HTTP status, the session and rendering; templates own markup only and never re-derive the rule.

---

### Task 1: Verify the worktree environment

The worktree already has a `.env` (DB `libli_elclip2`) and a synced `.venv`, both created before this plan was written. This task confirms they work before any test is written, because pytest's failure mode for a bad DB is a wall of errors that looks like broken code.

**Files:** none changed.

- [ ] **Step 1: Confirm the branch**

Run: `git branch --show-current`
Expected: `feat/element-clipboard-pr2`. Anything else means you are in the wrong worktree — stop.

- [ ] **Step 2: Confirm the database name is this worktree's own**

Run: `grep DATABASE_URL .env`
Expected: the URL ends `/libli_elclip2`. Read it from `.env`, not from `os.environ` — the settings module loads that file, but it is never exported into the shell, so an `os.environ` probe prints `(unset)` on a correctly configured worktree. A shared name means two worktrees' test runs drop each other's databases mid-flight.

- [ ] **Step 3: Check the connection**

Run: `uv run python manage.py check --database default`
Expected: `System check identified no issues`.

- [ ] **Step 4: Run an existing test file end to end**

Run: `uv run pytest tests/test_builder_duplicate_element.py -v`
Expected: all PASS (this is PR1's suite, on master). If you see `DuplicateDatabase`, a previous run left an idle connection — find and kill the stray pytest process, then re-run.

No commit: nothing changed.

---

### Task 2: The model→key helper and the slot cap in the registry

Two shared-code preparations, together because both are registry/key plumbing that later tasks consume and neither is worth its own review round.

Clause 2 needs the marked element's **transfer** key, and the map exists only as the private `export._MODEL_TO_KEY` (`courses/transfer/export.py:402`). Clause 1's truncation check needs each container's slot **cap**, which the registry does not carry today.

**Files:**
- Modify: `courses/transfer/export.py:402` — add the public helper beside `_MODEL_TO_KEY`
- Modify: `courses/builder.py:86-100` — the `_CONTAINER_REGISTRY` block, comment included; `:190` — `resolve_scope`'s unpack
- Append to: `courses/tests/test_nesting_rule.py` — two new tests. The existing length assertion at `:286` is deliberately left untouched; Task 2's falsification depends on it still passing.

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `export.model_to_key(model) -> str | None`; `_CONTAINER_REGISTRY[model] == (normalizer, list_key, id_key, max_slots)` where `max_slots` is an `int` or `None` (`None` = never truncated).

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_nesting_rule.py`:

```python
def test_container_registry_carries_a_slot_cap():
    """Clause 1's truncation check needs each container's MAX. A registry entry
    without one forces an ad-hoc getattr(type(obj), "MAX_TABS", ...) inside
    paste_allowed -- a second copy of container knowledge outside the registry."""
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TwoColumnElement

    reg = builder._CONTAINER_REGISTRY
    assert len(reg[TabsElement]) == 4
    assert reg[TabsElement][3] == TabsElement.MAX_TABS
    # MAX_COLUMNS, not the DEFAULT column count: normalize_data truncates at 4 and
    # the author may pick 2, 3 or 4. A cap of 2 would silently make columns 3 and 4
    # unpasteable while the renderer still shows them.
    assert reg[TwoColumnElement][3] == TwoColumnElement.MAX_COLUMNS
    # A fixed-slot container is never truncated, so its cap is None -- not 1.
    # `None` is what makes paste_allowed SKIP the position check rather than
    # apply it with a bound that happens to work.
    assert reg[SpoilerElement][3] is None


def test_container_keys_agree_by_key_not_by_count():
    """The old assertion was `len(CONTAINER_TRANSFER_KEYS) == len(_CONTAINER_REGISTRY)`,
    which passes green when a fourth model is registered under a fourth key that is
    absent from CONTAINER_TRANSFER_KEYS -- exactly the seam cap(n) and clause 2 now
    both sit on."""
    from courses.transfer.export import model_to_key

    assert {model_to_key(m) for m in builder._CONTAINER_REGISTRY} == set(
        builder.CONTAINER_TRANSFER_KEYS
    )
```

`builder` is already imported at the top of that module; add no import for it.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest courses/tests/test_nesting_rule.py -v`
Expected: `test_container_registry_carries_a_slot_cap` FAILS on `len(...) == 4` (the tuples are 3 long), and `test_container_keys_agree_by_key_not_by_count` FAILS on `ImportError: cannot import name 'model_to_key'`.

- [ ] **Step 3: Promote the model→key map**

In `courses/transfer/export.py`, immediately after `_MODEL_TO_KEY = ...` (`:402`), add:

```python
def model_to_key(model):
    """Transfer key for a concrete element MODEL class, or None if unregistered.

    Public because builder's clause 2 needs it: NESTABLE_TYPE_KEYS is keyed by
    transfer key, while a paste holds a join and therefore a model. Reaching into
    the private _MODEL_TO_KEY from builder.py would be the same coupling with less
    notice. Takes the class, not an instance, so `type(None)` for a dangling GFK
    returns None and falls out of every membership test.
    """
    return _MODEL_TO_KEY.get(model)
```

- [ ] **Step 4: Give every registry entry a slot cap**

In `courses/builder.py`, replace the `_CONTAINER_REGISTRY` block (`:86-100`) with:

```python
# Container element registry: model class -> (non_destructive_normalizer,
# slot_list_key, slot_id_key, max_slots). CONTRACT: each normalizer returns
# {slot_list_key: [{slot_id_key: <id>}, ...]}. resolve_scope indexes the normalizer
# output by slot_list_key, so slot_list_key MUST equal the key the normalizer emits.
#
# max_slots is the number of slots the DESTRUCTIVE normalize_data will keep; the
# non-destructive normalizer keeps more. paste_allowed uses it to refuse a slot that
# render-time truncation would drop -- see its clause 1. None means "never truncated"
# (a fixed-slot container) and skips that check entirely.
_CONTAINER_REGISTRY = {
    TabsElement: (
        TabsElement.normalize_labels_and_ids,
        "tabs",
        "id",
        TabsElement.MAX_TABS,
    ),
    TwoColumnElement: (
        TwoColumnElement.normalize_ids,
        "columns",
        "id",
        TwoColumnElement.MAX_COLUMNS,
    ),
    # Single-slot: ignores its argument and returns one fixed slot. SpoilerElement
    # has no `data` field, which is why the call site below uses getattr().
    SpoilerElement: (
        lambda _data: {"slots": [{"id": SpoilerElement.SLOT_ID}]},
        "slots",
        "id",
        None,
    ),
}
```

Then update `resolve_scope`'s unpack (`:190`) — it currently reads `normalizer, list_key, id_key = container`:

```python
    normalizer, list_key, id_key, _max_slots = container
```

`resolve_scope` deliberately does **not** apply the truncation check: the spec keeps it unchanged so the two rules provably disagree only in the documented direction, and the agreement test in Task 4 is built around that.

- [ ] **Step 5: Confirm the two truncation bounds are what the registry now claims**

The cap is the bound the **destructive** `normalize_data` truncates at — NOT the number of slots a freshly-added element is born with. Those differ for two-column: `default_data()` yields 2 columns, but `MIN_COLUMNS = 2` / `MAX_COLUMNS = 4` and an author may pick 3 or 4.

Run:
```bash
uv run python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()
from courses.models import TabsElement, TwoColumnElement
print('MAX_TABS', TabsElement.MAX_TABS)
print('MAX_COLUMNS', TwoColumnElement.MAX_COLUMNS)
"
```
Expected: `MAX_TABS 10`, `MAX_COLUMNS 4`. If either differs, stop and report — the registry entry and `test_container_registry_carries_a_slot_cap` must both name the attribute, never a literal.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_nesting_rule.py -v`
Expected: all PASS, including the two new ones.

- [ ] **Step 7: Falsify the strengthened drift test**

The mutation has to keep the registry's **length** at 3, or the old assertion fails too and proves nothing. So *substitute* rather than add: temporarily replace the `SpoilerElement` entry in `_CONTAINER_REGISTRY` with a `CalloutElement` one — `callout` is a real transfer key (`courses/transfer/export.py:378`) that is deliberately absent from `CONTAINER_TRANSFER_KEYS`:

```python
    # TEMPORARY MUTATION — replaces the SpoilerElement entry, keeping len() at 3
    CalloutElement: (lambda _data: {"slots": [{"id": "c"}]}, "slots", "id", None),
```

(add `from courses.models import CalloutElement` for the moment, and comment out the `SpoilerElement` entry).

Run: `uv run pytest courses/tests/test_nesting_rule.py -v`
Expected, and record all three in your report:
- `test_container_keys_agree_by_key_not_by_count` **FAILS** — `{tabs, two_column, callout} != {tabs, two_column, spoiler}`.
- The old length assertion inside `test_container_key_spaces_do_not_drift` (`:286`) **still passes** — 3 == 3. That contrast is the entire justification for the new test.
- `test_container_registry_carries_a_slot_cap` — the test you just wrote — raises `KeyError: SpoilerElement` on its `reg[SpoilerElement][3] is None` line, and the file's other spoiler-scope tests fail too, because the mutation genuinely unregisters the spoiler container. All of that is expected noise, not a signal: the two assertions above are the result.

Revert the entry, the comment-out and the import, and confirm `git diff` shows no trace.

- [ ] **Step 8: Confirm no existing caller broke**

`resolve_scope` is the only place that unpacks the registry today.
Run: `uv run pytest courses/tests/test_nesting_rule.py tests/test_element_editor_ops.py tests/test_manage_element_ops.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add courses/transfer/export.py courses/builder.py courses/tests/test_nesting_rule.py
git commit -m "feat(builder): give the container registry a slot cap and a public model->key helper"
```

---

### Task 3: `subtree_facts` and `paste_allowed` — the one authority

The rule itself. Called by the render per slot, called again inside the paste transaction to enforce, and exercised directly by these tests. Nothing else may re-derive it.

**Files:**
- Modify: `courses/builder.py` — append after `resolve_scope` (which ends at `:204`)
- Test: `courses/tests/test_paste_rule.py`

**Interfaces:**
- Consumes: `export.model_to_key` and the 4-tuple registry (Task 2).
- Produces:
  - `builder.SubtreeFacts` — a frozen dataclass with `min_headroom: int` and `subtree_pks: frozenset`.
  - `builder.subtree_facts(join, children_map=None) -> SubtreeFacts`.
  - `builder.paste_allowed(unit, marked_join, dest_parent, tab, mode, facts=None, dest_depth=None) -> (bool, reason_key | None)`.

**Reason precedence is fixed by this task and every later test depends on it.** In order: `wrong_unit`, `into_own_subtree`, `not_a_container`, `unknown_slot`, `type_not_nestable`, `too_deep`, `own_slot`. Clause 4 is tested before the container checks so that "paste into your own child" reports the useful reason rather than "not a container" when the child happens to be a leaf.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_paste_rule.py`:

```python
"""The placement rule. Every case here names the mutant it catches; a row that
cannot go RED under any mutation is decoration, not a test."""

import pytest

from courses import builder
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _text(unit, parent=None, tab="", body="x"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _spoiler(unit, parent=None, tab=""):
    obj = SpoilerElement.objects.create(body="<p>s</p>")
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def test_top_level_destination_is_always_admissible():
    _course, unit = make_course_with_unit()
    tabs_join, _slots = _tabs(unit)

    ok, reason = builder.paste_allowed(unit, tabs_join, None, "", "copy")

    assert (ok, reason) == (True, None)


def test_a_non_nestable_root_is_refused_by_a_nested_slot():
    """Mutant: drop clause 2 -> this goes RED. A slidebreak lives legally at top
    level, which is why the root is the only node whose nestability is unproven."""
    _course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    sb = Element.objects.create(
        unit=unit, content_object=SlideBreakElement.objects.create()
    )

    ok, reason = builder.paste_allowed(unit, sb, dest, slots[0], "move")

    assert (ok, reason) == (False, "type_not_nestable")


def test_an_unknown_slot_is_refused():
    _course, unit = make_course_with_unit()
    dest, _slots = _tabs(unit)
    leaf = _text(unit)

    ok, reason = builder.paste_allowed(unit, leaf, dest, "no-such-slot", "move")

    assert (ok, reason) == (False, "unknown_slot")


def test_a_leaf_destination_is_not_a_container():
    _course, unit = make_course_with_unit()
    dest = _text(unit)
    leaf = _text(unit)

    ok, reason = builder.paste_allowed(unit, leaf, dest, "anything", "move")

    assert (ok, reason) == (False, "not_a_container")


def test_a_leaf_may_land_at_depth_four_but_a_container_may_not():
    """Mutant: replace cap(n) with a constant 4 -> the container row goes RED.
    A container at depth 4 would render slots that can never be filled."""
    _course, unit = make_course_with_unit()
    d1, s1 = _tabs(unit)
    d2, s2 = _tabs(unit, parent=d1, tab=s1[0])
    d3, s3 = _tabs(unit, parent=d2, tab=s2[0])  # depth 3; its slots are depth 4

    leaf = _text(unit)
    container, _cslots = _tabs(unit)

    assert builder.paste_allowed(unit, leaf, d3, s3[0], "move") == (True, None)
    assert builder.paste_allowed(unit, container, d3, s3[0], "move") == (
        False,
        "too_deep",
    )


def test_depth_within_the_subtree_counts_not_just_the_roots():
    """`rel` must be subtracted per node. Subtree: Spoiler(cap 3, rel 0) ->
    Spoiler(cap 3, rel 1) -> Text(cap 4, rel 2), so the headroom is
    min(3, 2, 2) = 2 and a destination at dest_depth 3 is one too far -- while an
    EMPTY tabs (headroom 3) fits there exactly.

    Mutant: ignore `rel` -> min(3, 3, 4) = 3, the destination is admitted, RED.
    This subtree is deliberately NOT the one the height mutant catches: a
    height-based bound computes 4 - 2 = 2 here, the same answer, so this case stays
    GREEN under that mutation. That contrast is what separates the two mutations.
    """
    _course, unit = make_course_with_unit()
    d1, s1 = _tabs(unit)
    d2, s2 = _tabs(unit, parent=d1, tab=s1[0])  # its slots are at dest_depth 3

    root = _spoiler(unit)
    mid = _spoiler(unit, parent=root, tab=SpoilerElement.SLOT_ID)
    _text(unit, parent=mid, tab=SpoilerElement.SLOT_ID)

    empty, _eslots = _tabs(unit)
    assert builder.paste_allowed(unit, empty, d2, s2[0], "move") == (True, None)
    assert builder.paste_allowed(unit, root, d2, s2[0], "move") == (False, "too_deep")


def test_a_container_inside_the_subtree_tightens_the_bound_more_than_height_does():
    """THE row that distinguishes min(cap(n) - rel(n)) from a plain subtree height.

    Subtree: Tabs(root, cap 3, rel 0) -> Spoiler(cap 3, rel 1). The correct bound is
    min(3-0, 3-1) = 2; a height-based bound computes MAX - max_rel = 4 - 1 = 3. At
    dest_depth 3 the two therefore disagree: the correct rule REFUSES (the spoiler
    would land at depth 4, which a container may never occupy) and the height-based
    one admits.

    Mutant: use subtree HEIGHT -> RED. The destination must be at dest_depth 3, not
    2: at 2 both bounds admit and the mutation is unobservable.
    """
    _course, unit = make_course_with_unit()
    d1, s1 = _tabs(unit)
    d2, s2 = _tabs(unit, parent=d1, tab=s1[0])  # its slots are at dest_depth 3

    root, rslots = _tabs(unit)
    _spoiler(unit, parent=root, tab=rslots[0])

    ok, reason = builder.paste_allowed(unit, root, d2, s2[0], "move")

    assert (ok, reason) == (False, "too_deep")


def test_a_destination_inside_the_marked_subtree_is_refused():
    _course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=root, tab=rslots[0])

    for mode in ("move", "copy"):
        ok, reason = builder.paste_allowed(unit, root, inner, islots[0], mode)
        assert (ok, reason) == (False, "into_own_subtree"), mode


def test_the_marked_element_itself_is_refused_as_its_own_destination():
    """Clause 4 covers {R} as well as descendants(R)."""
    _course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)

    ok, reason = builder.paste_allowed(unit, root, root, rslots[0], "copy")

    assert (ok, reason) == (False, "into_own_subtree")


def test_the_elements_own_slot_refuses_a_move_and_allows_a_copy():
    """Mutant: drop clause 5 -> the move case goes RED while the copy case stays
    green. A copy into your own slot is a meaningful sibling copy."""
    _course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    child = _text(unit, parent=dest, tab=slots[0])

    assert builder.paste_allowed(unit, child, dest, slots[0], "move") == (
        False,
        "own_slot",
    )
    assert builder.paste_allowed(unit, child, dest, slots[0], "copy") == (True, None)


def test_the_top_level_slot_is_the_own_slot_of_a_top_level_element():
    """The same clause on the synthetic (None, "") pair, where `P is None` and
    `R.parent_id is None` must compare equal with no instance on either side."""
    _course, unit = make_course_with_unit()
    top = _text(unit)

    assert builder.paste_allowed(unit, top, None, "", "move") == (False, "own_slot")
    assert builder.paste_allowed(unit, top, None, "", "copy") == (True, None)


def test_another_units_element_is_refused():
    _course, unit = make_course_with_unit()
    _course2, other_unit = make_course_with_unit()
    foreign = _text(other_unit)

    ok, reason = builder.paste_allowed(unit, foreign, None, "", "copy")

    assert (ok, reason) == (False, "wrong_unit")


def test_a_destination_parent_from_another_unit_is_refused():
    _course, unit = make_course_with_unit()
    _course2, other_unit = make_course_with_unit()
    dest, slots = _tabs(other_unit)
    leaf = _text(unit)

    ok, reason = builder.paste_allowed(unit, leaf, dest, slots[0], "move")

    assert (ok, reason) == (False, "wrong_unit")


def test_a_slot_the_renderer_would_truncate_away_is_refused():
    """Clause 1's position check, and the ONE case no template test can reach:
    the non-destructive normalizer KEEPS slots the renderer's destructive
    normalize_data drops, so no button renders (the UI is safe) but a hand-crafted
    POST would otherwise be admitted -- landing a populated subtree where neither
    resolved_tabs() nor the export walk will ever find it.

    Mutant: drop the `[:max_slots]` slice -> this goes RED and nothing else does.
    """
    _course, unit = make_course_with_unit()
    # Ids MUST match TabsElement.TAB_ID_RE (`t[0-9a-f]{6}`, fullmatch) or
    # TabsElement.save() -> normalize_labels_and_ids mints a fresh one for each
    # (courses/models.py:1386-1393). With "t0"-style ids every id here would be
    # replaced at create time, the "kept" assertion would fail as unknown_slot and
    # the "dropped" one would pass vacuously.
    over = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": f"t{i:06x}", "label": f"L{i}"}
                for i in range(TabsElement.MAX_TABS + 2)
            ]
        }
    )
    dest = Element.objects.create(unit=unit, content_object=over)
    leaf = _text(unit)

    kept = f"t{TabsElement.MAX_TABS - 1:06x}"  # last slot surviving truncation
    dropped = f"t{TabsElement.MAX_TABS:06x}"  # first one normalize_data throws away

    assert builder.paste_allowed(unit, leaf, dest, kept, "move") == (True, None)
    assert builder.paste_allowed(unit, leaf, dest, dropped, "move") == (
        False,
        "unknown_slot",
    )


def test_a_fixed_slot_container_skips_the_position_check():
    """A spoiler's cap is None. This assertion alone does NOT pin that -- a cap of
    1 would also pass -- which is why Task 2's registry test asserts `is None`
    directly."""
    _course, unit = make_course_with_unit()
    dest = _spoiler(unit)
    leaf = _text(unit)

    assert builder.paste_allowed(unit, leaf, dest, SpoilerElement.SLOT_ID, "move") == (
        True,
        None,
    )


def test_a_dangling_gfk_root_is_refused_below_but_allowed_at_top_level():
    """type(None) is in neither the model->key map nor the registry, so clause 2
    rejects it for any nested destination. A top-level MOVE of the same row is
    admissible and correctly so -- a move serialises nothing. (A COPY of one fails
    later, at export, as a 422; that is the service's test, not this one.)

    Repoint object_id rather than deleting the concrete: every concrete declares
    GenericRelation(Element), so deleting it CASCADES the join away and leaves no
    dangling row to test.
    """
    _course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    # NESTED, not top level: a top-level row's own slot IS the top-level slot, so
    # clause 5 would answer own_slot and the second assertion below would be
    # testing the wrong rule. This is a genuine relocation.
    broken = _text(unit, parent=dest, tab=slots[0])
    Element.objects.filter(pk=broken.pk).update(object_id=9_999_999)
    broken.refresh_from_db()

    assert builder.paste_allowed(unit, broken, dest, slots[1], "move") == (
        False,
        "type_not_nestable",
    )
    assert builder.paste_allowed(unit, broken, None, "", "move") == (True, None)


def test_a_callout_is_a_leaf_here_not_a_container():
    """Guards Task 2's registry edit against a stray fourth entry: callout is in
    NESTABLE_TYPE_KEYS but NOT in CONTAINER_TRANSFER_KEYS, so it may be pasted
    INTO a slot and may not BE one."""
    _course, unit = make_course_with_unit()
    dest = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    leaf = _text(unit)

    assert builder.paste_allowed(unit, leaf, dest, "x", "move") == (
        False,
        "not_a_container",
    )

    tabs_join, slots = _tabs(unit)
    callout_join = Element.objects.create(
        unit=unit, content_object=CalloutElement.objects.create(body="<p>c</p>")
    )
    assert builder.paste_allowed(unit, callout_join, tabs_join, slots[0], "move") == (
        True,
        None,
    )


def test_subtree_facts_reports_the_pks_and_the_headroom():
    _course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)
    child = _spoiler(unit, parent=root, tab=rslots[0])
    grandchild = _text(unit, parent=child, tab=SpoilerElement.SLOT_ID)

    facts = builder.subtree_facts(root)

    assert facts.subtree_pks == frozenset({root.pk, child.pk, grandchild.pk})
    # Tabs cap 3 at rel 0; Spoiler cap 3 at rel 1; Text cap 4 at rel 2.
    assert facts.min_headroom == min(3 - 0, 3 - 1, 4 - 2)


def test_subtree_facts_terminates_on_a_parent_cycle():
    """A corrupt cycle must terminate rather than spin -- the same guard
    _collect_subtree_pks carries, for the same reason."""
    _course, unit = make_course_with_unit()
    a, aslots = _tabs(unit)
    b, _bslots = _tabs(unit, parent=a, tab=aslots[0])
    Element.objects.filter(pk=a.pk).update(parent=b)
    a.refresh_from_db()

    facts = builder.subtree_facts(a)

    assert facts.subtree_pks == frozenset({a.pk, b.pk})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest courses/tests/test_paste_rule.py -v`
Expected: FAIL — `AttributeError: module 'courses.builder' has no attribute 'paste_allowed'`.

Two fixtures above are written from the models as they stand; if `SlideBreakElement.objects.create()` or `CalloutElement.objects.create(body=…)` raises, fix the call to match the model and say so in your report rather than dropping the case.

- [ ] **Step 3: Implement both functions in `courses/builder.py`**

Add `from dataclasses import dataclass` to the imports at the top of the file, then insert immediately after `resolve_scope` (which ends at `:204`):

```python
@dataclass(frozen=True)
class SubtreeFacts:
    """The two facts about a marked element that do NOT depend on the destination.

    Computed once per render and passed to every per-slot paste_allowed call; the
    endpoint omits it and paste_allowed computes it itself. That parameter is what
    makes the N advisory calls and the one enforcing call provably the same code --
    the alternative, a view applying `dest_depth <= scalar` on its own, would put a
    second copy of clause 3 outside the authority.
    """

    min_headroom: int
    subtree_pks: frozenset


def _slot_cap(join):
    """cap(n): a container may live at depth 1..MAX_NEST_DEPTH-1, a leaf at 1..MAX.

    A container at depth 4 would render slots that can never be filled. Reads the
    MODEL-keyed registry, not CONTAINER_TRANSFER_KEYS, because the subject is an
    existing row rather than an incoming request -- no model->key hop is needed. A
    dangling GFK gives type(None), which is in neither, so it counts as a leaf.
    """
    if type(join.content_object) in _CONTAINER_REGISTRY:
        return MAX_NEST_DEPTH - 1
    return MAX_NEST_DEPTH


def subtree_facts(join, children_map=None):
    """Facts about the subtree rooted at `join`, over the FK walk.

    `S` is `join.children` -- EVERY child row, matched slot or not. Deliberately
    NOT the export walk's resolved_tabs()/resolved_columns(), which group by slot
    and omit a child whose tab_id matches no slot: a move re-parents the root, so
    an orphaned child travels with it whether or not any slot resolves. Measuring
    with the export walk would let an over-deep orphaned branch through.

    `children_map` is the render's prefetched {parent_pk: [joins]} map (see
    enumerate_slots). Omitted, each level costs a query -- fine for the single call
    the endpoint makes, ruinous for the per-render walk.

    Cycle-guarded by `seen`, for the same reason _collect_subtree_pks is.
    """
    seen = set()
    headroom = [MAX_NEST_DEPTH]

    def walk(node, rel):
        if node.pk in seen:
            return
        seen.add(node.pk)
        headroom[0] = min(headroom[0], _slot_cap(node) - rel)
        if children_map is not None:
            kids = children_map.get(node.pk, [])
        else:
            kids = node.children.all()
        for child in kids:
            walk(child, rel + 1)

    walk(join, 0)
    return SubtreeFacts(min_headroom=headroom[0], subtree_pks=frozenset(seen))


def paste_allowed(
    unit, marked_join, dest_parent, tab, mode, facts=None, dest_depth=None
):
    """Is placing `marked_join`'s subtree into (`dest_parent`, `tab`) admissible?

    Returns `(True, None)` or `(False, reason_key)`. The reason exists because the
    422 has to say what was wrong; a bare bool would force the endpoint to invent a
    generic message.

    THE authority: called per slot by the render to decide which buttons exist, and
    again inside the paste transaction to enforce. The render-time call is advisory;
    the in-transaction call is what a hand-crafted POST cannot beat.

    `facts` and `dest_depth` follow one rule: the render supplies them, the endpoint
    omits them, and this function computes whatever it was not given.

    Reason precedence, fixed and depended on by every caller's tests: wrong_unit,
    into_own_subtree, not_a_container, unknown_slot, type_not_nestable, too_deep,
    own_slot. Clause 4 is tested before the container checks so that "into your own
    child" reports that rather than "not a container" when the child is a leaf.
    """
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
    else:
        if dest_parent.pk in facts.subtree_pks:  # clause 4 ({R} U descendants(R))
            return False, "into_own_subtree"

        container = _CONTAINER_REGISTRY.get(type(dest_parent.content_object))
        if container is None:  # clause 1
            return False, "not_a_container"
        normalizer, list_key, id_key, max_slots = container
        # getattr: a single-slot container (spoiler) has no `data` field at all,
        # and the argument is evaluated HERE, before the normalizer runs.
        slots = normalizer(getattr(dest_parent.content_object, "data", None))[list_key]
        ids = [s[id_key] for s in slots]
        if max_slots is not None:
            # Clause 1 is deliberately STRICTER than resolve_scope's clause 2: the
            # non-destructive normalizer keeps slots the render-side destructive one
            # truncates away, and a paste into one of those lands a populated
            # subtree where nothing will ever render or export it. The check is on
            # POSITION, not on the minted id, so it is stable across calls --
            # comparing ids against the destructive normalizer's output would
            # compare against freshly minted values.
            ids = ids[:max_slots]
        if tab not in ids:  # clause 1
            return False, "unknown_slot"

        # Clause 2 checks the ROOT only, deliberately: every descendant is already
        # nested, so it passed this when it was created. The root is the only node
        # whose nestability is unproven -- it may have been sitting at top level,
        # where non-nestable types legally live.
        #
        # Function-local import for the reason duplicate_element's transfer imports
        # are (see :419-421): the transfer package pulls courses.forms /
        # courses.media, so a module-level edge risks an import cycle.
        from courses.transfer.export import model_to_key

        if model_to_key(type(marked_join.content_object)) not in NESTABLE_TYPE_KEYS:
            return False, "type_not_nestable"

        if dest_depth is None:
            dest_depth = element_depth(dest_parent) + 1

    if dest_depth > facts.min_headroom:  # clause 3
        return False, "too_deep"

    if mode == "move":  # clause 5 -- pks, never instances
        here = (dest_parent.pk if dest_parent is not None else None, tab)
        if here == (marked_join.parent_id, marked_join.tab_id):
            return False, "own_slot"

    return True, None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest courses/tests/test_paste_rule.py -v`
Expected: all **19** PASS.

- [ ] **Step 5: Falsify the rule, one mutation at a time**

Apply each, run, confirm the named test goes RED, then revert before the next. Record every observation in your report — a mutation that reds nothing means the rule has an untested clause, which is a finding, not a nuisance.

Each expectation below is stated as the **exact set** of tests that must red — not as "only this one", which would be false for two of them. A mutation that reds a different set than stated means either the mutation or a fixture is wrong; work out which before continuing, and report it.

1. Delete the `type_not_nestable` check.
   Expected RED — two tests: `test_a_non_nestable_root_is_refused_by_a_nested_slot`, and `test_a_dangling_gfk_root_is_refused_below_but_allowed_at_top_level`, whose nested assertion names that same reason (a dangling GFK gives `type(None)`, which no key map knows).
2. In `_slot_cap`, `return MAX_NEST_DEPTH` unconditionally.
   Expected RED: `test_a_leaf_may_land_at_depth_four_but_a_container_may_not` and `test_a_container_inside_the_subtree_tightens_the_bound_more_than_height_does` (its bound also depends on a container's cap).
3. In `subtree_facts`, ignore `rel`: `headroom[0] = min(headroom[0], _slot_cap(node))`.
   Expected RED — three tests: `test_depth_within_the_subtree_counts_not_just_the_roots`, `test_a_container_inside_the_subtree_tightens_the_bound_more_than_height_does` (both subtrees bind below the root) and `test_subtree_facts_reports_the_pks_and_the_headroom`, which asserts the arithmetic directly.
4. Replace the headroom with a plain subtree height — track `max(rel)` in the walk and return `MAX_NEST_DEPTH - max_rel` as `min_headroom`.
   Expected RED: `test_a_container_inside_the_subtree_tightens_the_bound_more_than_height_does` and `test_a_leaf_may_land_at_depth_four_but_a_container_may_not`.
   Expected still GREEN, and this is the discriminating observation: `test_depth_within_the_subtree_counts_not_just_the_roots`, whose all-leaf-capped subtree gives the same answer either way (`min(cap−rel) = 2 = MAX − max_rel`). If that test also reds, the mutation was mis-written; if it reds under mutation 3 but not 4, the two rules are genuinely distinguished, which is what this pair exists to show.
5. Delete the clause 5 block.
   Expected: the move assertions in `test_the_elements_own_slot_refuses_a_move_and_allows_a_copy` and `test_the_top_level_slot_is_the_own_slot_of_a_top_level_element` FAIL; every copy assertion stays green.
6. Drop the `ids = ids[:max_slots]` slice.
   Expected: `test_a_slot_the_renderer_would_truncate_away_is_refused` FAILS and nothing else does.

- [ ] **Step 6: Commit**

```bash
git add courses/builder.py courses/tests/test_paste_rule.py
git commit -m "feat(builder): add the paste placement rule and its subtree facts"
```

---

### Task 4: The agreement invariant

For a **childless** element, `paste_allowed`'s verdict must equal `resolve_scope`'s. That is what stops the two rules drifting the next time the cap moves. Test-only task.

**Files:**
- Test: `courses/tests/test_paste_rule_agreement.py`

**Interfaces:**
- Consumes: `builder.paste_allowed` (Task 3), `builder.resolve_scope` (unchanged).
- Produces: nothing.

**Two traps this test is built around, both of which make it vacuous or falsely RED if missed:**

1. **It spans two key namespaces.** `resolve_scope` takes a *form* key and translates it through `_NESTABLE_FORM_KEY_ALIASES` (`courses/builder.py:181`); `paste_allowed` reaches the *transfer* key through `model_to_key`. A matrix built only from types whose two keys coincide (text, tabs, image) never exercises the nine aliased types — exactly where a drift would hide.
2. **The equivalence is over clauses 1–3 only.** Clauses 4 and 5 have no `resolve_scope` counterpart, so the destination parent must be a row distinct from the element under test and neither its ancestor nor its descendant — otherwise the matrix produces a false RED whose obvious "fix" is weakening a clause. For the same reason the destination's slot list must be within bounds: clause 1 is deliberately stricter than `resolve_scope`'s clause 2 for a truncated slot, and that case belongs to Task 3's direct test, not here.

- [ ] **Step 1: Write the test**

Create `courses/tests/test_paste_rule_agreement.py`:

```python
"""paste_allowed and resolve_scope must agree for a childless element.

They are two implementations of the same containment question reached from
different namespaces, and nothing else pins them together.
"""

import pytest

from courses import builder
from courses.models import Element
from courses.models import MarkDoneElement
from courses.models import RevealGateElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _tabs_at(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


# (form key as element_add sends it, factory for the concrete). The first two have
# IDENTICAL form and transfer keys; the last three are ALIASED -- twocolumn ->
# two_column, markdone -> mark_done, revealgate -> reveal_gate -- and they are the
# only rows that can catch a broken alias entry. All three concretes construct with
# no arguments (every field carries a default or is blank), which is why they were
# chosen over the more elaborate question types.
CASES = [
    ("text", lambda: TextElement.objects.create(body="<p>t</p>")),
    ("tabs", lambda: TabsElement.objects.create(data=TabsElement.default_data())),
    (
        "twocolumn",
        lambda: TwoColumnElement.objects.create(data=TwoColumnElement.default_data()),
    ),
    ("markdone", lambda: MarkDoneElement.objects.create()),
    ("revealgate", lambda: RevealGateElement.objects.create()),
]


def _resolve_ok(unit, dest, slot, form_key):
    try:
        builder.resolve_scope(unit, str(dest.pk), slot, form_key)
        return True
    except builder.NestingError:
        return False


@pytest.mark.parametrize("form_key,make", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("parent_depth", [1, 2, 3])
def test_the_two_rules_agree_for_a_childless_element(form_key, make, parent_depth):
    """Mutant: break one _NESTABLE_FORM_KEY_ALIASES entry -> the aliased rows go
    RED while text and tabs stay green."""
    _course, unit = make_course_with_unit()

    dest, slots = _tabs_at(unit)
    for _hop in range(parent_depth - 1):
        dest, slots = _tabs_at(unit, parent=dest, tab=slots[0])

    # A row distinct from the destination and neither its ancestor nor its
    # descendant, so clauses 4 and 5 -- which have no resolve_scope counterpart --
    # cannot fire and produce a false RED.
    subject = Element.objects.create(unit=unit, content_object=make())

    allowed, _reason = builder.paste_allowed(unit, subject, dest, slots[0], "move")

    assert allowed == _resolve_ok(unit, dest, slots[0], form_key)


@pytest.mark.parametrize("form_key,make", CASES, ids=[c[0] for c in CASES])
def test_the_two_rules_agree_at_the_unconstructible_parent_depth(form_key, make):
    """Parent depth 4 cannot be reached by any legal write -- a parent must be a
    container, and cap says a container never lives at depth 4. Built by direct ORM
    write precisely to prove both rules reject it identically; the normal add path
    could never produce this row.
    """
    _course, unit = make_course_with_unit()

    dest, slots = _tabs_at(unit)
    for _hop in range(3):
        dest, slots = _tabs_at(unit, parent=dest, tab=slots[0])
    assert builder.element_depth(dest) == 4

    subject = Element.objects.create(unit=unit, content_object=make())

    allowed, _reason = builder.paste_allowed(unit, subject, dest, slots[0], "move")

    assert allowed is False
    assert _resolve_ok(unit, dest, slots[0], form_key) is False
```

- [ ] **Step 2: Run it**

Run: `uv run pytest courses/tests/test_paste_rule_agreement.py -v`
Expected: all **20** PASS (5 types × 3 depths, plus 5 depth-4 rows). If a row fails, do **not** weaken a clause to make it pass — re-read trap 2, check the fixture, and report what you found.

The three aliased factories are written from the models as they stand. If an `objects.create(...)` raises, fix the call to match the model rather than dropping the row: those rows are the only ones that can catch a broken alias. Report any field you had to change.

- [ ] **Step 3: Falsify it**

Mutate one aliased entry in `_NESTABLE_FORM_KEY_ALIASES` (`courses/builder.py:74-84`).
Run: `uv run pytest courses/tests/test_paste_rule_agreement.py -v`
Temporarily change one aliased entry — e.g. `"revealgate": "reveal_gate_BROKEN"`.
Expected: the `revealgate` rows FAIL (`resolve_scope` now refuses what `paste_allowed` allows) while `text`, `tabs`, `twocolumn` and `markdone` stay green. Revert and confirm `git diff` is clean.

- [ ] **Step 4: Commit**

```bash
git add courses/tests/test_paste_rule_agreement.py
git commit -m "test(builder): pin paste_allowed against resolve_scope for childless elements"
```

---

### Task 5: `enumerate_slots`

Nothing in the repo enumerates a unit's slots — `_editor_rows` fetches top-level joins only and the template reaches nested containers lazily through `resolved_tabs()` as it renders. This is new code, and it carries three of the spec's named traps.

**Files:**
- Modify: `courses/builder.py` — append after `paste_allowed`
- Test: `tests/test_enumerate_slots.py`

**Interfaces:**
- Consumes: the 4-tuple registry (Task 2), `subtree_facts`'s `children_map` shape (Task 3).
- Produces: `builder.enumerate_slots(unit) -> (pairs, children_map)` where `pairs` is a list of `(parent_join | None, tab_id, dest_depth)` beginning with the synthetic `(None, "", 1)`, and `children_map` is `{parent_pk_or_None: [joins]}` — returned so the caller can hand it to `subtree_facts` instead of paying for a second walk.

**Why it returns the map too.** The spec's cost argument is that the marked render pays for this on *every* response while a mark is pending. One query builds the map; `subtree_facts` then reuses it. Returning only `pairs` would make the caller re-walk `join.children` from the ORM — one query per node.

**The FK walk is a superset of the rendered tree, and that is the agreement that matters.** The enumerator descends `join.children`; the renderer descends `resolved_tabs()` / `resolved_columns()` / `resolved_children()`. A container that is itself an orphan-slot child is reached here but never rendered, so this can emit pairs no template will ask about — harmless, because enumerator ⊇ renderer means extra pairs are unreachable rather than wrong. The reverse direction would hurt and cannot happen.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_enumerate_slots.py`:

```python
"""The slot enumerator. Template tests cannot cover this: they assert a MISSING
button, which stays green if the enumerator returns nothing at all."""

import pytest

from courses import builder
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def test_the_synthetic_top_level_pair_is_always_first():
    _course, unit = make_course_with_unit()

    pairs, _map = builder.enumerate_slots(unit)

    assert pairs[0] == (None, "", 1)


def test_every_slot_of_a_two_level_container_tree_is_emitted_with_its_depth():
    _course, unit = make_course_with_unit()
    outer, oslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=outer, tab=oslots[1])

    pairs, _map = builder.enumerate_slots(unit)

    assert (None, "", 1) in pairs
    for sid in oslots:
        assert (outer, sid, 2) in pairs
    for sid in islots:
        assert (inner, sid, 3) in pairs
    # Nothing else: 1 synthetic + 2 outer slots + 2 inner slots.
    assert len(pairs) == 5


def test_a_spoiler_nested_in_a_tab_contributes_its_single_slot():
    """Mutant: write `obj.data` instead of `getattr(obj, "data", None)` ->
    AttributeError, RED. SpoilerElement has no `data` field at all, and the
    argument is evaluated before the normalizer runs."""
    _course, unit = make_course_with_unit()
    tabs_join, slots = _tabs(unit)
    sp = Element.objects.create(
        unit=unit,
        content_object=SpoilerElement.objects.create(body="<p>s</p>"),
        parent=tabs_join,
        tab_id=slots[0],
    )

    pairs, _map = builder.enumerate_slots(unit)

    assert (sp, SpoilerElement.SLOT_ID, 3) in pairs


def test_a_two_column_element_contributes_both_columns():
    _course, unit = make_course_with_unit()
    obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    cols = [c["id"] for c in obj.data["columns"]]

    pairs, _map = builder.enumerate_slots(unit)

    for cid in cols:
        assert (join, cid, 2) in pairs


def test_a_join_with_a_dangling_gfk_is_skipped_without_raising():
    """Repoint object_id rather than deleting the concrete -- GenericRelation
    cascades, so a delete would remove the join and prove nothing."""
    _course, unit = make_course_with_unit()
    tabs_join, _slots = _tabs(unit)
    Element.objects.filter(pk=tabs_join.pk).update(object_id=9_999_999)

    pairs, _map = builder.enumerate_slots(unit)

    assert pairs == [(None, "", 1)]


def test_a_slot_the_renderer_would_truncate_away_is_not_emitted():
    """The same position check clause 1 applies, here so the UI never offers a
    button the rule would then refuse. Mutant: drop the [:max_slots] slice -> RED."""
    _course, unit = make_course_with_unit()
    # Ids MUST match TabsElement.TAB_ID_RE (`t[0-9a-f]{6}`, fullmatch) or
    # TabsElement.save() -> normalize_labels_and_ids mints a fresh one for each
    # (courses/models.py:1386-1393). With "t0"-style ids every id here would be
    # replaced at create time, the "kept" assertion would fail as unknown_slot and
    # the "dropped" one would pass vacuously.
    over = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": f"t{i:06x}", "label": f"L{i}"}
                for i in range(TabsElement.MAX_TABS + 2)
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=over)

    pairs, _map = builder.enumerate_slots(unit)

    emitted = {t for p, t, _d in pairs if p is not None}
    assert f"t{TabsElement.MAX_TABS - 1:06x}" in emitted
    assert f"t{TabsElement.MAX_TABS:06x}" not in emitted
    assert join.pk  # the fixture row, referenced so the name is not unused


def test_the_children_map_is_returned_for_reuse():
    """subtree_facts takes this map so the marked render walks the tree once, not
    once per node. Mutant: return only `pairs` -> RED at the unpack."""
    _course, unit = make_course_with_unit()
    outer, oslots = _tabs(unit)
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=outer,
        tab_id=oslots[0],
    )

    _pairs, children_map = builder.enumerate_slots(unit)

    assert [j.pk for j in children_map[outer.pk]] == [child.pk]
    assert [j.pk for j in children_map[None]] == [outer.pk]


def test_a_parent_cycle_terminates():
    _course, unit = make_course_with_unit()
    a, aslots = _tabs(unit)
    b, _bslots = _tabs(unit, parent=a, tab=aslots[0])
    Element.objects.filter(pk=a.pk).update(parent=b)

    pairs, _map = builder.enumerate_slots(unit)

    # Both rows are now unreachable from the roots (neither has parent None), so
    # only the synthetic pair survives. What matters is that this RETURNS.
    assert pairs == [(None, "", 1)]


def test_the_walk_costs_a_bounded_number_of_queries(django_assert_num_queries):
    """The cost is paid on EVERY response while a mark is pending, and every editor
    operation returns a full re-render. One query for the elements plus one per
    distinct content type (the GFK prefetch groups by type) -- and crucially NOT
    one per join.

    Mutant: drop the prefetch and read `join.content_object` per node -> the count
    scales with the number of elements and this goes RED.
    """
    _course, unit = make_course_with_unit()
    outer, oslots = _tabs(unit)
    for i in range(6):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=f"<p>{i}</p>"),
            parent=outer,
            tab_id=oslots[0],
        )

    # 2 distinct content types (TabsElement, TextElement) -> 1 + 2 = 3.
    with django_assert_num_queries(3):
        builder.enumerate_slots(unit)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_enumerate_slots.py -v`
Expected: FAIL — `AttributeError: module 'courses.builder' has no attribute 'enumerate_slots'`.

- [ ] **Step 3: Implement it in `courses/builder.py`**

Insert after `paste_allowed`:

```python
def enumerate_slots(unit):
    """Every container slot in `unit`, as (parent_join | None, tab_id, dest_depth).

    Returns `(pairs, children_map)`. The map is `{parent_pk_or_None: [joins]}` and
    is returned so the caller can hand it to subtree_facts rather than pay for a
    second walk.

    ONE query builds the map, plus one per distinct content type for the GFK
    prefetch. Descending `join.children` from the ORM at each node instead -- even
    with prefetch_related hung off it -- is WORSE than naive: one children query
    plus one per content type, per join. build_export is not a precedent to copy
    wholesale; it prefetches its roots in one query and then re-queries children per
    container through the resolved_* accessors, and that second half is the shape to
    avoid.

    The walk is the FK tree, the same walk subtree_facts uses, so the two cannot
    disagree about what exists. It is a SUPERSET of the rendered tree: a container
    that is itself an orphan-slot child is reached here but never rendered, so this
    can emit pairs no template asks about. Harmless in that direction -- extra pairs
    are unreachable rather than wrong -- and the reverse cannot happen.

    Skipped entirely when nothing is marked: no walk, no cost on the common render.
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

    pairs = [(None, "", 1)]
    seen = set()

    def walk(join, depth):
        if join.pk in seen:  # a corrupt parent cycle must terminate, not spin
            return
        seen.add(join.pk)
        obj = join.content_object  # None when the GFK dangles -- skipped below
        container = _CONTAINER_REGISTRY.get(type(obj))
        if container is not None:
            normalizer, list_key, id_key, max_slots = container
            # getattr: a single-slot container (spoiler) has no `data` field, and
            # the argument is evaluated HERE, before the normalizer runs.
            slots = normalizer(getattr(obj, "data", None))[list_key]
            ids = [s[id_key] for s in slots]
            if max_slots is not None:
                # Same position check as clause 1, so the UI never offers a slot
                # the rule would then refuse. Non-destructive normalizer here,
                # destructive one at render time: for well-formed data they agree,
                # and where they diverge this fails closed.
                ids = ids[:max_slots]
            for sid in ids:
                pairs.append((join, sid, depth + 1))
        for child in children_map.get(join.pk, []):
            walk(child, depth + 1)

    for root in children_map.get(None, []):
        walk(root, 1)
    return pairs, children_map
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_enumerate_slots.py -v`
Expected: all **9** PASS. If the query-count test reports a different number, do **not** simply edit the expected count to match: first confirm from the captured queries that the extra ones are per-content-type and not per-join, and say so in your report.

- [ ] **Step 5: Falsify the two traps**

1. Replace `getattr(obj, "data", None)` with `obj.data`.
   Expected: `test_a_spoiler_nested_in_a_tab_contributes_its_single_slot` FAILS with `AttributeError`.
2. Drop the `ids = ids[:max_slots]` slice.
   Expected: `test_a_slot_the_renderer_would_truncate_away_is_not_emitted` FAILS.
3. Remove `.prefetch_related("content_object")`.
   Expected: `test_the_walk_costs_a_bounded_number_of_queries` FAILS with a count that scales with the seven elements.

Revert each and confirm `git status` is clean before committing.

- [ ] **Step 6: Commit**

```bash
git add courses/builder.py tests/test_enumerate_slots.py
git commit -m "feat(builder): enumerate a unit's paste slots in one query"
```

---

### Task 6: Split the scope parse, and `ParentGoneError`

The paste endpoint must reuse `resolve_scope`'s *parsing* — `parent`/`tab` together-or-neither, the `int()` guard, the unit-scoped lookup — without its admissibility clauses, which all raise `NestingError` → 400 and would send an over-deep paste back as an invisible 400.

**Files:**
- Modify: `courses/builder.py` — `_parse_scope_ref` split out of `resolve_scope:159-174`; `ParentGoneError` beside `NestingError` (`:22`)
- Test: `tests/test_scope_parse.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `builder.ParentGoneError(NestingError)`; `builder._parse_scope_ref(unit, parent_ref, tab) -> (parent_join | None, tab_id)`, raising `NestingError` for a shape error and `ParentGoneError` for a well-formed but unresolvable parent pk.

**The subclassing is load-bearing.** `element_add` (`courses/views_manage.py:1614`) and `element_save` (`:1680`) catch `builder_svc.NestingError` and nothing else. A sibling exception class would turn their clean 400 into an uncaught 500 the moment a parent pk vanishes — a regression in two existing views, introduced by a refactor meant to be behaviour-preserving. As a subclass it is caught by construction; only the paste view, which catches it *first*, maps it to 422.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scope_parse.py`:

```python
import pytest
from django.urls import reverse

from courses import builder
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_parent_and_tab_come_together_or_not_at_all():
    _course, unit = make_course_with_unit()

    assert builder._parse_scope_ref(unit, "", "") == (None, "")
    with pytest.raises(builder.NestingError):
        builder._parse_scope_ref(unit, "5", "")
    with pytest.raises(builder.NestingError):
        builder._parse_scope_ref(unit, "", "t1")


def test_a_non_numeric_parent_ref_is_a_shape_error():
    _course, unit = make_course_with_unit()

    with pytest.raises(builder.NestingError) as exc:
        builder._parse_scope_ref(unit, "abc", "t1")
    assert not isinstance(exc.value, builder.ParentGoneError)


def test_a_vanished_parent_is_parent_gone_not_a_bare_shape_error():
    """"The destination container was deleted by another author between the render
    and the click" is the concurrent-edit case this design creates; it must reach
    the author as a visible 422, not the invisible 400 a shape error gets."""
    _course, unit = make_course_with_unit()

    with pytest.raises(builder.ParentGoneError):
        builder._parse_scope_ref(unit, "9999999", "t1")


def test_parent_gone_is_a_nesting_error_subclass():
    """element_add and element_save catch NestingError and nothing else. A sibling
    class would turn their 400 into an uncaught 500 the day a parent pk vanishes."""
    assert issubclass(builder.ParentGoneError, builder.NestingError)


def test_resolve_scope_still_reports_a_vanished_parent_through_the_same_path():
    _course, unit = make_course_with_unit()

    with pytest.raises(builder.NestingError):
        builder.resolve_scope(unit, "9999999", "t1", "text")


def test_element_add_still_answers_400_for_a_vanished_parent(client):
    """The regression the subclassing exists to prevent, driven through the real
    endpoint rather than asserted on the class."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )

    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "unit": unit.pk,
            "type": "text",
            "parent": "9999999",
            "tab": "t1",
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 400


def test_a_resolvable_parent_comes_back_as_a_join():
    _course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]

    parent, slot = builder._parse_scope_ref(unit, str(join.pk), tab)

    assert (parent, slot) == (join, tab)


def test_a_parent_in_another_unit_is_parent_gone():
    """The lookup is unit-scoped, which is what makes same-unit -- and
    transitively same-course -- hold."""
    _course, unit = make_course_with_unit()
    _course2, other_unit = make_course_with_unit()
    foreign = Element.objects.create(
        unit=other_unit, content_object=TextElement.objects.create(body="x")
    )

    with pytest.raises(builder.ParentGoneError):
        builder._parse_scope_ref(unit, str(foreign.pk), "t1")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_scope_parse.py -v`
Expected: FAIL — `AttributeError: module 'courses.builder' has no attribute '_parse_scope_ref'`.

- [ ] **Step 3: Add `ParentGoneError`**

In `courses/builder.py`, immediately after `class NestingError(Exception)` (`:22-23`):

```python
class ParentGoneError(NestingError):
    """A well-formed parent pk that resolves to nothing in this unit.

    A SUBCLASS on purpose: element_add and element_save catch NestingError and
    nothing else, so a sibling class would turn their clean 400 into an uncaught
    500 the moment a parent pk vanishes. Only the paste view, which catches this
    first, treats it differently -- as a 422, because "the destination container
    was deleted by another author between the render and the click" is a
    concurrent-edit case the author must see, not a malformed payload.
    """
```

- [ ] **Step 4: Split the parse out of `resolve_scope`**

Replace `resolve_scope`'s body up to and including the `if join is None:` block (`:159-174`) with a call to the new helper, and add the helper immediately above it:

```python
def _parse_scope_ref(unit, parent_ref, tab):
    """Parse a (parent, tab) payload pair into (parent_join | None, tab_id).

    PARSE ONLY -- no admissibility. resolve_scope calls this and then applies its
    clauses; the paste path calls it and then applies paste_allowed instead. Two
    parses would be free to drift, which is the whole reason this is one function.

    Shape errors raise NestingError (400): a UI cannot produce them. A well-formed
    but unresolvable parent raises ParentGoneError (422 on the paste path).
    """
    parent_ref = (parent_ref or "").strip()
    tab = (tab or "").strip()
    if not parent_ref and not tab:
        return None, ""
    if not parent_ref or not tab:
        raise NestingError("parent and tab must be supplied together")
    try:
        join = (
            Element.objects.select_related("parent__parent__parent")
            .filter(pk=int(parent_ref), unit=unit)
            .first()
        )
    except (TypeError, ValueError):
        raise NestingError("bad parent ref") from None
    if join is None:
        raise ParentGoneError("unknown parent")
    return join, tab


def resolve_scope(unit, parent_ref, tab, type_key):
    """Validate and resolve a nested element's scope.

    Returns (parent_join|None, tab_id).

    `parent` and `tab` come together or not at all; neither means top-level. Any
    violation raises NestingError, which the view turns into a 400. Filtering the
    parent by `unit` enforces same-unit and (transitively) same-course, because `unit`
    was already resolved against the course by the caller.

    Parsing lives in _parse_scope_ref, shared with the paste path; the clauses below
    are this function's alone.
    """
    join, tab = _parse_scope_ref(unit, parent_ref, tab)
    if join is None:
        return None, ""
```

Everything from `parent_obj = join.content_object` (`:176`) down stays exactly as it is.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_scope_parse.py -v`
Expected: all **8** PASS.

- [ ] **Step 6: Prove the refactor changed no existing behaviour**

Run: `uv run pytest courses/tests/test_nesting_rule.py courses/tests/test_paste_rule.py courses/tests/test_paste_rule_agreement.py tests/test_element_editor_ops.py tests/test_manage_element_ops.py -v`
Expected: all PASS. `resolve_scope` is the shared surface here; a behaviour change would show up in the nesting-rule file first.

- [ ] **Step 7: Falsify the subclassing**

Temporarily change `class ParentGoneError(NestingError)` to `class ParentGoneError(Exception)`.
Run: `uv run pytest tests/test_scope_parse.py -v`
Expected: `test_parent_gone_is_a_nesting_error_subclass` FAILS **and** `test_element_add_still_answers_400_for_a_vanished_parent` FAILS with a 500 — the exact regression the subclassing prevents, and the reason the endpoint test is in this file rather than left to the view task. Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/builder.py tests/test_scope_parse.py
git commit -m "refactor(builder): share the scope parse and name the vanished-parent case"
```

---

### Task 7: `builder.paste_element`

The service. Locks, re-checks the rule inside the transaction, then either re-parents the root (move) or grafts a copy (copy), positions it at the end of the destination slot, and bumps the unit token.

**Files:**
- Modify: `courses/builder.py` — `PlacementRefused` beside the other exceptions; `paste_element` after `duplicate_element`'s helper `_copy_below`, which ends at `:481` — before the `@transaction.atomic` decorator on `delete_node` at `:484`
- Test: `tests/test_builder_paste_element.py`

**Interfaces:**
- Consumes: `paste_allowed` (Task 3), `_parse_scope_ref` / `ParentGoneError` (Task 6), and PR1's `export.build_element_export` / `importer.graft_elements`.
- Produces: `builder.PlacementRefused(Exception)` carrying `.reason_key`; `builder.paste_element(course, element_pk, parent_ref, tab, mode, unit_token) -> (unit, placed_join)`.

**`PlacementRefused` must NOT subclass `NestingError`,** or `element_add` / `element_save` would begin answering 400 to a condition they never raise, and the `ParentGoneError` handler would swallow it.

**Move step order is load-bearing** — `place_element` neither writes the scope nor is guaranteed to save the moved row at all (`courses/ordering.py:96-117` saves only rows whose `order` changed, and only `update_fields=["order"]`):

1. Capture `(old_parent, old_tab_id)` **before** mutating anything — `delete_element` does exactly this (`:568`, "capture before the row disappears"). A move mutates those same fields in place, so reading them afterwards would compact the *destination* twice and leave a hole in the source.
2. Set `parent` / `tab_id` and **persist them** with `save(update_fields=["parent", "tab_id"])`. A scope left unsaved here is a scope never written.
3. `ordering.place_element(el, unit, None)` — `None` clamps to the end of the group, which is the "a paste appends" decision. It reads the in-memory `parent`/`tab_id` to pick the sibling group, so step 2 is also its precondition.
4. `ordering.compact_elements` on the **captured** source group.
5. One `unit.save(update_fields=["updated"])`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_paste_element.py`:

```python
import pytest

from courses import builder
from courses.builder import ConflictError
from courses.builder import PlacementRefused
from courses.builder import paste_element
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _tok(unit):
    return unit.updated.isoformat()


def _text(unit, parent=None, tab="", body="<p>x</p>"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _orders(unit, parent, tab):
    return list(
        Element.objects.filter(unit=unit, parent=parent, tab_id=tab)
        .order_by("order", "pk")
        .values_list("pk", "order")
    )


def test_a_move_reparents_the_root_and_persists_the_scope():
    """Re-read from the DB, not the in-memory instance: place_element writes only
    `order`, so an unsaved scope is a scope never written.

    Mutant: delete step 2's save(update_fields=["parent", "tab_id"]) -> RED here
    and ONLY here, which is the point of re-reading."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)

    _u, placed = paste_element(course, subject.pk, str(dest.pk), slots[1], "move", _tok(unit))

    fresh = Element.objects.get(pk=subject.pk)
    assert placed.pk == subject.pk  # a move keeps the row
    assert fresh.parent_id == dest.pk
    assert fresh.tab_id == slots[1]


def test_a_move_carries_its_whole_subtree_without_touching_the_children():
    """Only the root's group membership changes; descendants keep their parent and
    unit FKs, so the subtree travels for free."""
    course, unit = make_course_with_unit()
    dest, dslots = _tabs(unit)
    root, rslots = _tabs(unit)
    child = _text(unit, parent=root, tab=rslots[0])
    before = (child.parent_id, child.tab_id, child.unit_id)

    paste_element(course, root.pk, str(dest.pk), dslots[0], "move", _tok(unit))

    child.refresh_from_db()
    assert (child.parent_id, child.tab_id, child.unit_id) == before


def test_a_move_compacts_the_source_group_and_appends_to_the_destination():
    """Mutants: swap steps 3 and 4 so the compaction runs before the placement ->
    the source assertion goes RED; read (parent, tab_id) AFTER mutating instead of
    before -> the source group is left with a hole and the same assertion reds."""
    course, unit = make_course_with_unit()
    a, b, c = _text(unit, body="<p>a</p>"), _text(unit, body="<p>b</p>"), _text(unit, body="<p>c</p>")
    dest, slots = _tabs(unit)
    existing = _text(unit, parent=dest, tab=slots[0], body="<p>in</p>")

    paste_element(course, b.pk, str(dest.pk), slots[0], "move", _tok(unit))

    # Source group: the hole b left is compacted away, orders 0..n-1 and distinct.
    src = _orders(unit, None, "")
    assert [pk for pk, _o in src] == [a.pk, c.pk, dest.pk]
    assert [o for _pk, o in src] == [0, 1, 2]
    # Destination: appended last, distinct orders.
    dst = _orders(unit, dest, slots[0])
    assert [pk for pk, _o in dst] == [existing.pk, b.pk]
    assert len({o for _pk, o in dst}) == 2


def test_a_move_whose_old_order_equals_its_new_index_is_still_persisted():
    """place_element saves only rows whose order CHANGED, so it may legitimately
    save the moved row not at all. Step 2 is what guarantees the move regardless --
    this is the case that proves it."""
    course, unit = make_course_with_unit()
    subject = _text(unit)  # order 0 at top level
    dest, slots = _tabs(unit)  # empty slot -> the moved row lands at index 0 again

    paste_element(course, subject.pk, str(dest.pk), slots[0], "move", _tok(unit))

    fresh = Element.objects.get(pk=subject.pk)
    assert (fresh.parent_id, fresh.tab_id, fresh.order) == (dest.pk, slots[0], 0)


def test_a_move_keeps_the_elements_pk_so_student_state_follows_it():
    """The converse of a copy, and the whole reason a move is worth having rather
    than delete-and-re-author: progress rows key on the element pk."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)
    pk_before = subject.pk

    _u, placed = paste_element(course, subject.pk, str(dest.pk), slots[0], "move", _tok(unit))

    assert placed.pk == pk_before


def test_a_copy_creates_fresh_rows_in_the_destination_slot():
    course, unit = make_course_with_unit()
    dest, dslots = _tabs(unit)
    root, rslots = _tabs(unit)
    _text(unit, parent=root, tab=rslots[0], body="<p>inner</p>")

    _u, placed = paste_element(course, root.pk, str(dest.pk), dslots[0], "copy", _tok(unit))

    assert placed.pk != root.pk
    assert placed.parent_id == dest.pk
    assert placed.tab_id == dslots[0]
    assert placed.content_object.pk != root.content_object.pk
    copied_child = placed.children.get()
    assert copied_child.content_object.body == "<p>inner</p>"
    # The source is untouched.
    root.refresh_from_db()
    assert root.parent_id is None


def test_a_copy_leaves_the_grafted_root_in_the_destination_not_at_top_level():
    """The graft returns a PARENTLESS root -- _create_elements' second pass skips
    exactly those rows -- and place_element saves only `order`. Mutant: skip the
    scope-setting step -> RED."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)

    _u, placed = paste_element(course, subject.pk, str(dest.pk), slots[0], "copy", _tok(unit))

    # Re-read: _copy_into sets parent/tab_id on the instance BEFORE saving and
    # returns that same object, so asserting on `placed` would stay green with the
    # save deleted -- while the DB row kept parent=NULL and the copy silently
    # landed at top level. That is exactly the mutant this test must catch.
    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (dest.pk, slots[0])


def test_a_copy_preserves_the_subtree_shape_at_every_depth():
    """Copy fidelity for a THREE-level subtree, which the single-level test above
    cannot show: Tabs -> (tab 1) Spoiler -> Text. Every join and every concrete row
    must be fresh, and the parent/slot grouping must survive at each hop.

    Mutant: share concrete rows instead of copying them -> the fresh-pk assertions
    go RED while the content-equality ones stay green.
    """
    course, unit = make_course_with_unit()
    dest, dslots = _tabs(unit)

    root, rslots = _tabs(unit)
    sp = Element.objects.create(
        unit=unit,
        content_object=SpoilerElement.objects.create(body="<p>sp</p>"),
        parent=root,
        tab_id=rslots[0],
    )
    leaf = _text(unit, parent=sp, tab=SpoilerElement.SLOT_ID, body="<p>deep</p>")

    _u, placed = paste_element(
        course, root.pk, str(dest.pk), dslots[0], "copy", _tok(unit)
    )

    assert placed.pk != root.pk
    copied_sp = placed.children.get()
    assert copied_sp.pk != sp.pk
    assert copied_sp.tab_id == rslots[0]
    assert copied_sp.content_object.pk != sp.content_object.pk
    copied_leaf = copied_sp.children.get()
    assert copied_leaf.pk != leaf.pk
    assert copied_leaf.tab_id == SpoilerElement.SLOT_ID
    assert copied_leaf.content_object.pk != leaf.content_object.pk
    assert copied_leaf.content_object.body == "<p>deep</p>"


def test_a_copy_reuses_the_media_row_rather_than_re_creating_it():
    """Two MediaAsset rows sharing a file.name share a LIFETIME -- deleting either
    deletes the file out from under the other."""
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "pic.png")
    src_image = ImageElement.objects.create(media=asset, alt="a", figcaption="")
    subject = Element.objects.create(unit=unit, content_object=src_image)
    dest, slots = _tabs(unit)

    _u, placed = paste_element(course, subject.pk, str(dest.pk), slots[0], "copy", _tok(unit))

    assert MediaAsset.objects.filter(course=course).count() == 1
    assert placed.content_object.pk != src_image.pk
    assert placed.content_object.media_id == asset.pk


def test_a_copy_into_the_elements_own_slot_lands_last_in_that_group():
    course, unit = make_course_with_unit()
    first = _text(unit, body="<p>1</p>")
    second = _text(unit, body="<p>2</p>")

    _u, placed = paste_element(course, first.pk, "", "", "copy", _tok(unit))

    order = [pk for pk, _o in _orders(unit, None, "")]
    assert order == [first.pk, second.pk, placed.pk]


def test_a_copy_of_a_damaged_subtree_refuses_rather_than_thinning_it():
    """build_export RECORDS a dangling GFK and continues, dropping the broken join
    and its whole subtree; discarding `problems` would yield a silent partial copy
    with a 200. Repoint object_id -- deleting the concrete cascades the join away."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    root, rslots = _tabs(unit)
    child = _text(unit, parent=root, tab=rslots[0])
    Element.objects.filter(pk=child.pk).update(object_id=9_999_999)

    with pytest.raises(TransferError):
        paste_element(course, root.pk, str(dest.pk), slots[0], "copy", _tok(unit))


def test_a_move_of_a_damaged_row_to_top_level_succeeds():
    """A move serialises nothing, so no export runs and no `problems` list exists.
    Stated in the spec because "paste" names both modes: a test written from the
    copy sentence alone would assert 422 here and be wrong."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit, parent=dest, tab=slots[0])
    Element.objects.filter(pk=subject.pk).update(object_id=9_999_999)

    _u, placed = paste_element(course, subject.pk, "", "", "move", _tok(unit))

    assert placed.parent_id is None


def test_an_inadmissible_placement_raises_placement_refused_with_its_reason():
    course, unit = make_course_with_unit()
    root, rslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=root, tab=rslots[0])

    with pytest.raises(PlacementRefused) as exc:
        paste_element(course, root.pk, str(inner.pk), islots[0], "move", _tok(unit))

    assert exc.value.reason_key == "into_own_subtree"


def test_placement_refused_is_not_a_nesting_error():
    """A NestingError subclass would make element_add/element_save answer 400 to a
    condition they never raise, and the ParentGoneError handler would swallow it."""
    assert not issubclass(PlacementRefused, builder.NestingError)


def test_an_unknown_mode_is_rejected():
    course, unit = make_course_with_unit()
    subject = _text(unit)

    with pytest.raises(builder.NestingError):
        paste_element(course, subject.pk, "", "", "teleport", _tok(unit))


def test_a_half_supplied_scope_is_a_shape_error():
    course, unit = make_course_with_unit()
    subject = _text(unit)

    with pytest.raises(builder.NestingError):
        paste_element(course, subject.pk, "", "t1", "move", _tok(unit))


def test_a_stale_token_conflicts():
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)

    with pytest.raises(ConflictError):
        paste_element(
            course, subject.pk, str(dest.pk), slots[0], "move",
            "2020-01-01T00:00:00+00:00",
        )


@pytest.mark.parametrize("mode", ["move", "copy"])
def test_every_paste_bumps_the_unit_token_exactly_once(mode):
    """Mutant: drop the bump from the copy path -> the copy row goes RED, and
    without it a stale-token 409 would never fire after a copy."""
    course, unit = make_course_with_unit()
    dest, slots = _tabs(unit)
    subject = _text(unit)
    before = unit.updated

    paste_element(course, subject.pk, str(dest.pk), slots[0], mode, _tok(unit))

    unit.refresh_from_db()
    assert unit.updated > before


def test_a_move_into_a_third_column_lands_there():
    """Columns are the one container whose slot id key is `column.id` rather than
    `tab.id`, and the one whose cap is MAX_COLUMNS (4), not the default count (2).
    A third column is ordinary authored data -- element_forms lets an author pick
    2..4 -- so a cap of 2 would refuse this with `unknown_slot` while the renderer
    happily shows the column. Nothing else in the service tests reaches a column."""
    from courses.models import TwoColumnElement

    course, unit = make_course_with_unit()
    cols_obj = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]}
    )
    cols = Element.objects.create(unit=unit, content_object=cols_obj)
    cols_obj.refresh_from_db()
    third = cols_obj.data["columns"][2]["id"]
    subject = _text(unit)

    _u, placed = paste_element(course, subject.pk, str(cols.pk), third, "move", _tok(unit))

    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (cols.pk, third)


def test_a_move_into_a_spoiler_uses_its_fixed_slot():
    course, unit = make_course_with_unit()
    sp = Element.objects.create(
        unit=unit, content_object=SpoilerElement.objects.create(body="<p>s</p>")
    )
    subject = _text(unit)

    _u, placed = paste_element(
        course, subject.pk, str(sp.pk), SpoilerElement.SLOT_ID, "move", _tok(unit)
    )

    fresh = Element.objects.get(pk=placed.pk)
    assert (fresh.parent_id, fresh.tab_id) == (sp.pk, SpoilerElement.SLOT_ID)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_builder_paste_element.py -v`
Expected: FAIL — `ImportError: cannot import name 'PlacementRefused'`.

- [ ] **Step 3: Add `PlacementRefused`**

In `courses/builder.py`, after `ParentGoneError`:

```python
class PlacementRefused(Exception):
    """The in-transaction re-check refused a placement the render had offered.

    Deliberately NOT a NestingError: element_add and element_save catch that and
    would begin answering 400 to a condition they never raise, and the
    ParentGoneError handler would swallow this one. Carries the reason because
    paste_element returns (unit, placed_join), which has no room for one, and the
    422 has to say what was wrong.
    """

    def __init__(self, reason_key):
        super().__init__(reason_key)
        self.reason_key = reason_key
```

- [ ] **Step 4: Implement `paste_element`**

Insert after `_copy_below`, which ends at `:481`. Do NOT insert "after :484" — that line is the `@transaction.atomic` decorator belonging to `delete_node` at `:485`, and splitting a decorator from its `def` is a syntax error.

```python
@transaction.atomic
def paste_element(course, element_pk, parent_ref, tab, mode, unit_token):
    """Move or copy the marked element's subtree into (parent_ref, tab).

    Returns (unit, placed_join) -- the join, not just the unit, because the view
    derives the post-paste open-set by walking placed_join.parent upward.

    Locks first, token second, rule third: paste_allowed is re-evaluated INSIDE
    this transaction and this lock, so a concurrent add into the destination slot
    cannot interleave between the render-time check and the placement. The
    render-time call is advisory; this one is the enforcement.
    """
    if mode not in ("move", "copy"):
        raise NestingError("unknown mode")

    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)

    dest_parent, tab_id = _parse_scope_ref(unit, parent_ref, tab)
    ok, reason = paste_allowed(unit, el, dest_parent, tab_id, mode)
    if not ok:
        raise PlacementRefused(reason)

    if mode == "move":
        placed = _move_into(el, unit, dest_parent, tab_id)
    else:
        placed = _copy_into(el, unit, dest_parent, tab_id)

    unit.save(update_fields=["updated"])
    return unit, placed


def _move_into(el, unit, dest_parent, tab_id):
    """Re-parent the ROOT join row only; descendants keep their parent and unit
    FKs, so the whole subtree travels with it for free.

    The step order is load-bearing -- see the comments inline. Runs inside
    paste_element's transaction and its element+unit lock.
    """
    # 1. Capture BEFORE mutating: a move overwrites these same fields in place, so
    #    reading them afterwards would compact the DESTINATION twice and leave a
    #    hole in the source. delete_element captures for the same reason (:568).
    old_parent, old_tab = el.parent, el.tab_id

    # 2. Persist the scope. place_element saves only `order`
    #    (ordering.py:112-116), so a scope left unsaved here is never written --
    #    and it is also place_element's precondition, since it reads the in-memory
    #    parent/tab_id to pick the sibling group (:101-102).
    el.parent = dest_parent
    el.tab_id = tab_id
    el.save(update_fields=["parent", "tab_id"])

    # 3. None clamps to the end of the group: a paste APPENDS, and position is then
    #    adjusted with the existing arrows.
    ordering.place_element(el, unit, None)

    # 4. Compact the CAPTURED source group, as delete_element does (:576).
    ordering.compact_elements(unit, parent=old_parent, tab_id=old_tab)
    return el


def _copy_into(el, unit, dest_parent, tab_id):
    """Serialise the subtree and re-materialise it in the destination slot.

    The same three-step shape duplicate_element uses, with the destination being
    the caller's rather than the source's own scope. Runs inside paste_element's
    transaction and lock.
    """
    from courses.transfer import export as _export
    from courses.transfer import importer as _importer
    from courses.transfer.schema import TransferError

    try:
        document, media_assets, problems = _export.build_element_export(unit, el)
        if problems:
            # build_export RECORDS a dangling GFK and continues, dropping the broken
            # join and its ENTIRE subtree from the payload. With
            # drop_missing_media=False no media problem can be produced, so a
            # non-empty list means exactly one thing -- and copying anyway would
            # yield a silently thinned subtree with a 200.
            raise TransferError(_("This element is damaged and cannot be copied."))
        media_map = {mid: asset for (mid, asset, _ph) in media_assets}
        new_join = _importer.graft_elements(document, media_map, unit)
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
    ordering.place_element(new_join, unit, None)
    return new_join
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder_paste_element.py -v`
Expected: all **21** PASS (20 test functions, one parametrised over two modes).

- [ ] **Step 6: Falsify the four move/copy assertions that could be vacuous**

Apply, run, confirm RED, revert. "The source group is compacted" and "the destination keeps distinct orders" are both true of an implementation that never moves anything, so these mutations are what make them mean something.

1. Delete step 2's `el.save(update_fields=["parent", "tab_id"])` in `_move_into`.
   Expected RED — three tests, because an unpersisted scope leaves the row in its old group: `test_a_move_reparents_the_root_and_persists_the_scope`, `test_a_move_compacts_the_source_group_and_appends_to_the_destination` (the moved row never leaves the source list) and `test_a_move_whose_old_order_equals_its_new_index_is_still_persisted`. Still GREEN: `test_a_move_into_a_third_column_lands_there` and `test_a_move_into_a_spoiler_uses_its_fixed_slot`, which read the in-memory `placed` — which is precisely why the three above re-read from the DB.
2. In `_move_into`, compact the DESTINATION group instead of the captured source one — `ordering.compact_elements(unit, parent=dest_parent, tab_id=tab_id)`.
   Expected RED: `test_a_move_compacts_the_source_group_and_appends_to_the_destination`, on the source orders — the hole the moved row left is never closed.
   (Do **not** try "swap steps 3 and 4" as a mutation: `place_element` works on the destination group and `compact_elements` on the captured source group, and clause 5 guarantees those are disjoint for a move, so the two calls commute and nothing reds. Only the capture in step 1 and the save in step 2 are order-critical.)
3. Read `old_parent, old_tab` *after* the mutation instead of before.
   Expected: the same test FAILS — the source group keeps a hole.
4. Delete `new_join.save(update_fields=["parent", "tab_id"])` in `_copy_into`.
   Expected: `test_a_copy_leaves_the_grafted_root_in_the_destination_not_at_top_level` FAILS.
5. Change `if problems:` to `pass`.
   Expected: `test_a_copy_of_a_damaged_subtree_refuses_rather_than_thinning_it` FAILS.

- [ ] **Step 7: Commit**

```bash
git add courses/builder.py tests/test_builder_paste_element.py
git commit -m "feat(builder): move or copy an element subtree into a chosen slot"
```

---

### Task 8: The clipboard state and the select/cancel endpoint

The mark lives in the session, so the paste buttons are part of the render every operation already returns — and the feature works without JavaScript.

**Files:**
- Modify: `courses/views_manage.py` — `element_clip` after `element_duplicate` (which ends at `:1214`)
- Modify: `courses/urls.py` — one path beside `manage_element_duplicate` (`:224-228`)
- Test: `tests/test_element_clip_view.py`

**Interfaces:**
- Consumes: `_require_manage`, `_render_editor_fragments`, `_element_conflict`, `_render_tree` — all already defined in `courses/views_manage.py`.
- Produces: URL name `courses:manage_element_clip`, POST fields `element`, `unit`, `action=select|cancel`; and the session shape `request.session["element_clip"] = {"unit": int, "element": int}`.

**Both pks are stored as `int`, coerced on write, and that is not incidental.** The natural implementation stores `request.POST.get("element")` — a **string** — and the session is JSON, so a string stays a string across requests. Then `clip["element"] == el.pk` is False for every row: the toggle-off lifecycle never fires and the marked-row modifier never renders. Both fail silently and closed.

**`int()` can fail, and its status is 400.** `element` is deliberately not validated beyond belonging to the unit — the paste re-resolves it through `_locked_element` — but a malformed payload must not 500 the one endpoint whose whole job is to be cheap.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_element_clip_view.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    join = add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    unit.refresh_from_db()
    return course, unit, join


def _clip(client, course, unit, element, action="select"):
    return client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": element, "unit": unit.pk, "action": action},
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_select_marks_the_element_and_returns_both_fragments(client):
    course, unit, join = _seed(client)

    resp = _clip(client, course, unit, join.pk)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'data-scope="preview"' in body
    assert client.session["element_clip"] == {"unit": unit.pk, "element": join.pk}


def test_both_pks_are_stored_as_ints(client):
    """The session is JSON: a string written here stays a string on every later
    request, and `clip["element"] == el.pk` is then False for every row -- so the
    toggle-off lifecycle never fires and the marked-row modifier never renders.
    Both failures are silent and closed."""
    course, unit, join = _seed(client)

    _clip(client, course, unit, str(join.pk))

    clip = client.session["element_clip"]
    assert isinstance(clip["element"], int)
    assert isinstance(clip["unit"], int)


def test_selecting_a_second_element_replaces_the_mark(client):
    course, unit, join = _seed(client)
    other = add_element(unit, TextElement.objects.create(body="<p>2</p>"))

    _clip(client, course, unit, join.pk)
    _clip(client, course, unit, other.pk)

    assert client.session["element_clip"]["element"] == other.pk


def test_selecting_the_marked_element_again_clears_it(client):
    """The row's own control toggles."""
    course, unit, join = _seed(client)

    _clip(client, course, unit, join.pk)
    _clip(client, course, unit, join.pk)

    assert "element_clip" not in client.session


def test_cancel_clears_the_mark(client):
    course, unit, join = _seed(client)
    _clip(client, course, unit, join.pk)

    resp = _clip(client, course, unit, join.pk, action="cancel")

    assert resp.status_code == 200
    assert "element_clip" not in client.session


def test_cancel_with_no_mark_is_harmless(client):
    course, unit, join = _seed(client)

    resp = _clip(client, course, unit, join.pk, action="cancel")

    assert resp.status_code == 200
    assert "element_clip" not in client.session


def test_a_non_numeric_element_is_a_400(client):
    """The one endpoint whose whole job is to be cheap and side-effect-free must
    not 500 on a malformed payload."""
    course, unit, _join = _seed(client)

    resp = _clip(client, course, unit, "abc")

    assert resp.status_code == 400
    assert "element_clip" not in client.session


def test_an_unknown_action_is_a_400(client):
    course, unit, join = _seed(client)

    resp = _clip(client, course, unit, join.pk, action="teleport")

    assert resp.status_code == 400


def test_an_element_from_another_unit_is_refused(client):
    """The mark is qualified by unit; a mark naming a row that is not in this unit
    would render paste buttons for something the paste would then refuse."""
    course, unit, _join = _seed(client)
    other_unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    foreign = add_element(other_unit, TextElement.objects.create(body="<p>f</p>"))

    resp = _clip(client, course, unit, foreign.pk)

    assert resp.status_code == 409
    assert "element_clip" not in client.session


def test_a_unit_from_another_course_renders_no_foreign_content(client):
    """It writes no data, but it ANSWERS with that unit's element list and live
    preview -- so a POST carrying a unit pk from a course this user does not manage
    must not render it."""
    course, unit, join = _seed(client, username="owner")
    other_course = CourseFactory(owner=CourseFactory().owner)
    foreign_unit = ContentNodeFactory(
        course=other_course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(foreign_unit, TextElement.objects.create(body="<p>SECRET</p>"))

    resp = client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": join.pk,
            "unit": foreign_unit.pk,
            "action": "select",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 409
    assert "SECRET" not in resp.content.decode()


def test_a_non_numeric_unit_is_a_409_not_a_500(client):
    """filter(pk="abc") raises ValueError when the queryset is evaluated.

    Guarding _clip_unit alone is NOT enough: _element_conflict opens with the same
    unguarded filter on the same POST field, so routing the failure there would
    re-raise the ValueError and answer 500. That is why this path returns
    _no_unit_409 instead, and why this test exists rather than being assumed."""
    course, unit, join = _seed(client)

    resp = client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": join.pk, "unit": "abc", "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 409


def test_a_user_who_cannot_manage_the_course_is_refused(client):
    from tests.factories import make_teacher

    course, unit, join = _seed(client, username="owner")
    client.logout()
    make_teacher(client, "teacher")

    resp = _clip(client, course, unit, join.pk)

    assert resp.status_code in (403, 404)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_element_clip_view.py -v`
Expected: FAIL — `NoReverseMatch: 'manage_element_clip' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the URL**

In `courses/urls.py`, immediately after the `manage_element_duplicate` path (`:224-228`):

```python
    path(
        "manage/courses/<slug:slug>/build/element/clip/",
        views_manage.element_clip,
        name="manage_element_clip",
    ),
```

- [ ] **Step 4: Add the view**

In `courses/views_manage.py`, insert after `element_duplicate` (which ends at `:1214`):

```python
CLIP_SESSION_KEY = "element_clip"


def _clip_unit(request, course):
    """Resolve the POSTed unit against the course, or None.

    It writes no data, but it ANSWERS through _render_editor_fragments, which
    renders that unit's element list AND its live preview -- so a POST carrying a
    unit pk from another course would render that course's content. Wrapped
    because filter(pk="abc") raises ValueError when the queryset is evaluated:
    that covers a missing pk (pk=None becomes pk__isnull=True) and a non-unit pk,
    but not a present-and-non-numeric one.
    """
    try:
        return ContentNode.objects.filter(
            pk=request.POST.get("unit"), course=course, kind=ContentNode.Kind.UNIT
        ).first()
    except (ValueError, TypeError):
        return None


def _no_unit_409(request, course):
    """The unit could not be resolved, so there is no editor pane to render.

    Deliberately NOT _element_conflict: that helper opens with the SAME unguarded
    `filter(pk=request.POST.get("unit"), ...)` (courses/views_manage.py:1232-1234),
    so on a non-numeric `unit` it re-raises the very ValueError this path just
    caught -- turning the guarded 409 back into a 500. Its unguarded shape is a
    pre-existing wart on a hand-crafted-only path and is left alone here; new code
    simply does not route through it.
    """
    return _render_tree(request, course, status=409)


@login_required
def element_clip(request, slug):
    """Editor-only: set or clear the clipboard mark. No DB write, so no token check
    -- the paste re-validates everything.

    The marked element is deliberately NOT validated beyond belonging to this unit:
    the paste re-resolves it through _locked_element(course, ...), which filters on
    unit__course, and a mark is only a session note until then.
    """
    course = _require_manage(request, slug)
    unit = _clip_unit(request, course)
    if unit is None:
        return _no_unit_409(request, course)

    action = request.POST.get("action")
    if action not in ("select", "cancel"):
        return HttpResponseBadRequest("bad action")

    if action == "cancel":
        request.session.pop(CLIP_SESSION_KEY, None)
        return _render_editor_fragments(request, unit)

    try:
        element_pk = int(request.POST.get("element"))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad element")

    if not unit.elements.filter(pk=element_pk).exists():
        return _element_conflict(request, course)

    current = request.session.get(CLIP_SESSION_KEY) or {}
    if current.get("element") == element_pk and current.get("unit") == unit.pk:
        # ⊹ on the already-marked element toggles it off.
        request.session.pop(CLIP_SESSION_KEY, None)
    else:
        # BOTH pks as int: the session is JSON, so a string written here stays a
        # string on every later request and `clip["element"] == el.pk` is then
        # False for every row -- the toggle above never fires and the marked-row
        # modifier never renders. Silent and closed, both of them.
        request.session[CLIP_SESSION_KEY] = {"unit": unit.pk, "element": element_pk}
    return _render_editor_fragments(request, unit)
```

`HttpResponseBadRequest` must be imported if it is not already — check the imports at the top of `courses/views_manage.py` and add `from django.http import HttpResponseBadRequest` only if absent.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_element_clip_view.py -v`
Expected: all **12** PASS.

- [ ] **Step 6: Falsify the int coercion**

Store the raw POST value instead: `request.session[CLIP_SESSION_KEY] = {"unit": unit.pk, "element": request.POST.get("element")}`.
Run: `uv run pytest tests/test_element_clip_view.py -v`
Expected: `test_both_pks_are_stored_as_ints` FAILS **and** `test_selecting_the_marked_element_again_clears_it` FAILS — the toggle stops working, which is the user-visible half of the same defect. Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/urls.py courses/views_manage.py tests/test_element_clip_view.py
git commit -m "feat(editor): mark an element for the clipboard in the session"
```

---

### Task 9: The clip context, and the paste endpoint

The render side of the mark (which slots get buttons, which row is marked, what the banner says) plus the endpoint that performs the paste.

**Files:**
- Modify: `courses/views_manage.py` — `_clip_context` helper; both context builders; `element_paste`
- Modify: `courses/urls.py` — one path
- Test: `tests/test_element_paste_view.py`

**Interfaces:**
- Consumes: `builder.enumerate_slots`, `builder.subtree_facts`, `builder.paste_allowed`, `builder.paste_element`, `builder.PlacementRefused`, `builder.ParentGoneError`, `builder.ancestor_slots` (PR1).
- Produces: URL name `courses:manage_element_paste`, POST fields `parent` (blank = top level), `tab`, `mode=move|copy`, `unit`, `unit_token`; and five context keys on **both** builders: `clip_active` (bool), `clip_element_pk` (str), `clip_label` (str), `move_slots` (set of slot keys), `copy_slots` (set of slot keys).

**Both context builders get the keys.** `_render_editor_fragments` (`:1275`) and `_editor_page` (`:1336`) build the editor context independently; a key on only one makes the first page load look perfect while every later fragment swap silently drops the feature. That is what the comment at `:1309-1317` already records for `max_nest_depth`.

**When nothing is marked, no walk happens** — `enumerate_slots` is skipped entirely, so the common render pays nothing.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_element_paste_view.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _text(unit, parent=None, tab="", body="<p>x</p>"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _mark(client, course, unit, element):
    return client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": element.pk, "unit": unit.pk, "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _paste(client, course, unit, parent, tab, mode="move", token=None):
    return client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": "" if parent is None else parent.pk,
            "tab": tab,
            "mode": mode,
            "unit": unit.pk,
            "unit_token": token if token is not None else unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_a_move_returns_both_fragments_and_relocates_the_element(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'data-scope="preview"' in body
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (dest.pk, slots[0])


def test_a_move_clears_the_mark_and_a_copy_keeps_it(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()

    _mark(client, course, unit, subject)
    unit.refresh_from_db()
    _paste(client, course, unit, dest, slots[0], mode="copy")
    assert "element_clip" in client.session  # one original can seed several slots

    unit.refresh_from_db()
    _paste(client, course, unit, dest, slots[1], mode="move")
    assert "element_clip" not in client.session  # it is now where you put it


def test_a_paste_with_no_mark_is_a_409(client):
    """Reachable in ordinary use: a move clears the mark, so a back-button
    resubmit, a double POST or a second tab holding a stale render all post a
    paste against an empty clipboard."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 409


def test_a_mark_naming_another_unit_is_a_409(client):
    course, unit = _seed(client)
    other_unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    subject = _text(other_unit)
    dest, slots = _tabs(unit)
    other_unit.refresh_from_db()
    _mark(client, course, other_unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 409


def test_a_mark_pointing_at_a_deleted_row_is_a_409(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    Element.objects.filter(pk=subject.pk).delete()
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code == 409


def test_a_stale_token_is_a_409(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)

    resp = _paste(
        client, course, unit, dest, slots[0], token="2020-01-01T00:00:00+00:00"
    )

    assert resp.status_code == 409


def test_a_half_supplied_scope_is_a_400(client):
    course, unit = _seed(client)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, None, "t1")

    assert resp.status_code == 400


def test_an_unknown_mode_is_a_400(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0], mode="teleport")

    assert resp.status_code == 400


def test_a_refused_placement_is_a_422_with_a_VISIBLE_reason(client):
    """Assert the BODY, not only the status. A 422 whose body is a bare op-error
    div passes a status-only assertion and is still invisible to the author --
    exactly how this error path was got wrong once already."""
    course, unit = _seed(client)
    root, rslots = _tabs(unit)
    inner, islots = _tabs(unit, parent=root, tab=rslots[0])
    unit.refresh_from_db()
    _mark(client, course, unit, root)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, inner, islots[0])

    assert resp.status_code == 422
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'id="editor-error"' in body
    # The mark survives a refusal, or the retry the message invites is impossible.
    assert "element_clip" in client.session


def test_a_vanished_destination_is_a_422_not_a_400(client):
    """"The destination container was deleted by another author between the render
    and the click" is the concurrent-edit case this design creates; a silent 400 is
    the outcome the error section exists to rule out."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    dest_pk, slot = dest.pk, slots[0]
    Element.objects.filter(pk=dest_pk).delete()
    unit.refresh_from_db()

    resp = client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": dest_pk,
            "tab": slot,
            "mode": "move",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 422
    assert 'id="editor-error"' in resp.content.decode()


def test_a_copy_of_a_damaged_subtree_is_a_422(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    root, rslots = _tabs(unit)
    child = _text(unit, parent=root, tab=rslots[0])
    Element.objects.filter(pk=child.pk).update(object_id=9_999_999)
    unit.refresh_from_db()
    _mark(client, course, unit, root)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[0], mode="copy")

    assert resp.status_code == 422
    assert 'id="editor-error"' in resp.content.decode()


def test_the_pasted_elements_ancestors_render_open(client):
    """A move CLEARS the mark, so the very re-render that shows the result has no
    mark pending -- without the ancestor chain every <details> would snap back to
    first-tab-only and the author would watch the row vanish."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, dest, slots[1], mode="move")

    body = resp.content.decode()
    marker = f'data-tab-id="{slots[1]}"'
    tag = body[body.index(marker) : body.index(marker) + 200]
    assert " open" in tag
    assert "data-force-open" in tag


def test_a_move_into_a_spoiler_works_end_to_end(client):
    course, unit = _seed(client)
    sp = Element.objects.create(
        unit=unit, content_object=SpoilerElement.objects.create(body="<p>s</p>")
    )
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, sp, SpoilerElement.SLOT_ID)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (sp.pk, SpoilerElement.SLOT_ID)


def test_a_paste_into_a_column_works_end_to_end(client):
    """The view-level column case. `column.id` is a different template expression
    from `tab.id`, and the columns branch is the one where a copied condition fails
    silently -- so the endpoint needs its own column row, not just the template
    tests."""
    from courses.models import TwoColumnElement

    course, unit = _seed(client)
    cols_obj = TwoColumnElement.objects.create(
        data={"columns": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]}
    )
    cols = Element.objects.create(unit=unit, content_object=cols_obj)
    cols_obj.refresh_from_db()
    third = cols_obj.data["columns"][2]["id"]
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()

    resp = _paste(client, course, unit, cols, third)

    assert resp.status_code == 200
    subject.refresh_from_db()
    assert (subject.parent_id, subject.tab_id) == (cols.pk, third)


def test_a_user_who_cannot_manage_the_course_is_refused(client):
    from tests.factories import make_teacher

    course, unit = _seed(client, username="owner")
    dest, slots = _tabs(unit)
    subject = _text(unit)
    unit.refresh_from_db()
    _mark(client, course, unit, subject)
    unit.refresh_from_db()
    client.logout()
    make_teacher(client, "teacher")

    resp = _paste(client, course, unit, dest, slots[0])

    assert resp.status_code in (403, 404)
    subject.refresh_from_db()
    assert subject.parent_id is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_element_paste_view.py -v`
Expected: FAIL — `NoReverseMatch: 'manage_element_paste'`.

- [ ] **Step 3: Add the URL**

In `courses/urls.py`, after the `manage_element_clip` path from Task 8:

```python
    path(
        "manage/courses/<slug:slug>/build/element/paste/",
        views_manage.element_paste,
        name="manage_element_paste",
    ),
```

- [ ] **Step 4: Add the clip context helper**

In `courses/views_manage.py`, after `_clip_unit`:

```python
# reason_key -> the message the author reads. paste_allowed returns a key rather
# than a bare bool precisely so this mapping can exist in one place; a generic
# "that did not work" would not deliver "the author sees why nothing moved".
PASTE_REFUSAL_MESSAGES = {
    "wrong_unit": gettext_lazy("That element is not part of this unit."),
    "into_own_subtree": gettext_lazy("An element cannot be placed inside itself."),
    "not_a_container": gettext_lazy("That destination is not a container."),
    "unknown_slot": gettext_lazy("That slot no longer exists."),
    "type_not_nestable": gettext_lazy("This type cannot be placed inside a container."),
    "too_deep": gettext_lazy("This element is too deep to fit there."),
    "own_slot": gettext_lazy("It is already there."),
    "parent_gone": gettext_lazy("The destination was removed while you were working."),
}


def _clip_context(request, unit):
    """The five mark-dependent context keys, for BOTH context builders.

    When nothing is marked this returns empty values and does NO walk -- the
    common render pays nothing. While a mark IS pending the cost is paid on every
    response, which is why enumerate_slots is one query and why its children_map is
    reused by subtree_facts rather than re-walked.

    Clears a stale mark lazily: a marked element that has been deleted, or that
    belongs to another unit, is treated as absent.
    """
    empty = {
        "clip_active": False,
        "clip_element_pk": "",
        "clip_label": "",
        "move_slots": set(),
        "copy_slots": set(),
    }
    clip = request.session.get(CLIP_SESSION_KEY) or {}
    if clip.get("unit") != unit.pk:
        # Rendering ANOTHER unit: ignored, not cleared -- you may navigate back.
        return empty

    marked = unit.elements.filter(pk=clip.get("element")).first()
    if marked is None:
        request.session.pop(CLIP_SESSION_KEY, None)
        return empty

    pairs, children_map = builder_svc.enumerate_slots(unit)
    facts = builder_svc.subtree_facts(marked, children_map=children_map)

    move_slots, copy_slots = set(), set()
    for parent, tab, dest_depth in pairs:
        key = builder_svc.slot_key(parent.pk if parent is not None else None, tab)
        for mode, bucket in (("move", move_slots), ("copy", copy_slots)):
            ok, _reason = builder_svc.paste_allowed(
                unit, marked, parent, tab, mode, facts=facts, dest_depth=dest_depth
            )
            if ok:
                bucket.add(key)

    obj = marked.content_object
    return {
        "clip_active": True,
        # STRINGIFIED here: the template compares with el.pk|stringformat:'s', and
        # passing the int straight through makes every row's comparison int == str
        # -> False, reproducing one layer later the exact failure the int coercion
        # at clip time exists to prevent.
        "clip_element_pk": str(marked.pk),
        "clip_label": marked.title or element_summary(obj),
        "move_slots": move_slots,
        "copy_slots": copy_slots,
    }
```

One import this needs at the top of `courses/views_manage.py`, added only if absent: `from courses.templatetags.courses_manage_extras import element_summary` (the banner labels title-or-summary exactly as the row label does — `Element.title` is routinely empty, so a naive label renders `"" is selected`).

- [ ] **Step 5: Wire the keys into both context builders**

In `_render_editor_fragments`, add to the context dict beside `"open_slots"`:

```python
            # The clipboard's render-side state. Must be set HERE as well as in
            # _editor_page: every editor operation returns through this renderer,
            # so a key on only one builder makes the first page load look perfect
            # while every later fragment swap silently drops the feature.
            **_clip_context(request, unit),
```

Add the identical line to `_editor_page`'s context dict.

- [ ] **Step 6: Add the paste view**

Insert after `element_clip`:

```python
@login_required
def element_paste(request, slug):
    """Editor-only: move or copy the marked element into a chosen slot.

    Status mapping, each channel already named by its exception: no mark / stale
    token / vanished element -> 409; a malformed payload no UI can produce -> 400;
    an inadmissible placement the render had offered, a vanished destination, or a
    failed copy -> 422 through the FRAGMENT renderer so the author actually sees
    the reason. _op_error is never used here: it has no [data-scope] wrapper, so
    applyFragments swaps nothing and the message is invisible.
    """
    course = _require_manage(request, slug)
    unit = _clip_unit(request, course)
    if unit is None:
        return _no_unit_409(request, course)

    clip = request.session.get(CLIP_SESSION_KEY) or {}
    if clip.get("unit") != unit.pk or not clip.get("element"):
        # Reachable in ordinary use: a move clears the mark, so a back-button
        # resubmit or a second tab's stale render posts against an empty clipboard.
        return _element_conflict(request, course)

    try:
        unit, placed = builder_svc.paste_element(
            course,
            clip["element"],
            request.POST.get("parent"),
            request.POST.get("tab"),
            request.POST.get("mode"),
            request.POST.get("unit_token"),
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

    # The session write happens only AFTER the service returns: it is not covered
    # by the service's @transaction.atomic, so a mark cleared before a rollback
    # would stay cleared while the database change did not. A copy KEEPS the mark
    # so one original can seed several slots; a move clears it.
    if request.POST.get("mode") == "move":
        request.session.pop(CLIP_SESSION_KEY, None)

    return _render_editor_fragments(
        request, unit, open_slots=builder_svc.ancestor_slots(placed)
    )


def _refused(request, unit, reason_key):
    """422 carrying the reason, as an editor fragment. The mark is NOT cleared: a
    message saying why nothing moved, on a page that has already discarded the
    selection, invites a retry that is impossible -- and that retry lands on the
    no-mark 409 path, compounding one confusing response into two."""
    message = PASTE_REFUSAL_MESSAGES.get(reason_key) or _("That placement is not allowed.")
    return _render_editor_fragments(request, unit, status=422, error=message)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_element_paste_view.py -v`
Expected: all **15** PASS.

- [ ] **Step 8: Confirm the unmarked render still costs nothing extra**

Run: `uv run pytest tests/test_element_editor_ops.py tests/test_element_duplicate_view.py tests/test_editor_open_slots.py tests/test_editor_error_channel.py -v`
Expected: all PASS. These are the existing editor paths; `_clip_context` runs on every one of them and must be a no-op when nothing is marked.

- [ ] **Step 9: Falsify the mark lifecycle**

1. Clear the mark before calling the service (move the `session.pop` above the `try`).
   Expected: `test_a_refused_placement_is_a_422_with_a_VISIBLE_reason` FAILS on its `"element_clip" in client.session` assertion.
2. Clear the mark on a copy as well as a move.
   Expected: `test_a_move_clears_the_mark_and_a_copy_keeps_it` FAILS.
3. Drop `open_slots=builder_svc.ancestor_slots(placed)` from the success return.
   Expected: `test_the_pasted_elements_ancestors_render_open` FAILS.

Revert each.

- [ ] **Step 10: Commit**

```bash
git add courses/urls.py courses/views_manage.py tests/test_element_paste_view.py
git commit -m "feat(editor): add the paste endpoint and the clipboard render context"
```

---

### Task 10: The paste buttons

A small inclusion tag, invoked at the four slot sites. The template never re-derives the rule — it tests the slot's key against the precomputed sets.

**Files:**
- Create: `templates/courses/manage/editor/_paste_buttons.html`
- Modify: `courses/templatetags/courses_manage_extras.py` — the `paste_buttons` tag
- Modify: `templates/courses/manage/editor/_element_row.html:91`, `:141`, `:195` (the three nested slots)
- Modify: `templates/courses/manage/editor/_editor_scope.html:32` (the top-level slot)
- Test: `tests/test_editor_clip_templates.py`

**Interfaces:**
- Consumes: `move_slots` / `copy_slots` / `clip_active` from the context (Task 9), `builder.slot_key`.
- Produces: the author-facing paste controls. `editor.js:289` intercepts any `form[data-op]`, so no JavaScript.

**The tag is invoked at the four include sites, not inside `_add_menu.html`.** Four edits rather than one, bought deliberately: the three nested add-menu includes sit behind `{% if depth < max_nest_depth %}`, so putting the buttons inside the menu would silently inherit that guard and make a slot unpasteable exactly where the menu is suppressed. Paste legality is `paste_allowed`'s business alone. **The tag call therefore goes OUTSIDE that guard**, on the same line. The consequence is that the buttons can render with no `.addwrap` beside them, so Task 12's CSS must define a standalone appearance as well as the grouped one.

**`takes_context=True`** so the tag can read `unit`, the token and the two sets off the ambient context. Note there is no `slug` key in the editor context — the templates all spell it `unit.course.slug`, and so must the tag. Not for CSRF: Django's `InclusionNode.render` copies `csrf_token` into the fresh context unconditionally, `takes_context` or not.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_editor_clip_templates.py`:

```python
"""Several cases here assert a button is ABSENT and would stay green if the tag
emitted nothing at all. The pairing is what makes them non-vacuous, so the mutant
is named once for the file: make the tag render nothing -> the top-level-slot and
own-slot-copy cases go RED while every "no button" case stays green.
"""

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _seed(client, username="pa"):
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return course, unit


def _text(unit, parent=None, tab="", body="<p>x</p>"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


def _tabs(unit, parent=None, tab=""):
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )
    return join, [t["id"] for t in obj.data["tabs"]]


def _mark(client, course, unit, element):
    unit.refresh_from_db()
    return client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": element.pk, "unit": unit.pk, "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _editor(client, course, unit):
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()


def _slot_section(body, marker):
    """The markup of ONE container slot: from its data-tab-id/data-column-id
    attribute to the end of its <details>.

    A fixed-width window does NOT work here. The paste tag is invoked AFTER the
    add-menu include on the same template line, and _add_menu.html renders ~8.7 kB
    (still several kB nested, where only the Questions group is hidden) -- so the
    paste form starts thousands of characters past the marker. A 1500-char slice
    would make every presence assertion fail against a correct implementation and,
    worse, every ABSENCE assertion pass regardless of what the tag emits.
    """
    at = body.index(marker)
    end = body.index("</details>", at)
    return body[at:end]


def test_no_paste_buttons_render_when_nothing_is_marked(client):
    course, unit = _seed(client)
    _tabs(unit)
    _text(unit)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste"' not in body


def test_the_top_level_slot_offers_its_buttons(client):
    """The key-shape failure is silent and closed -- a mismatched key makes EVERY
    paste button disappear, which reads as "the feature is broken" rather than as a
    bug in a key. This is the test that catches it."""
    course, unit = _seed(client)
    dest, _slots = _tabs(unit)
    subject = _text(unit, parent=dest, tab=_slots[0])
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    assert 'data-op="element-paste"' in body
    assert 'name="mode" value="move"' in body
    assert 'name="mode" value="copy"' in body


def test_the_marked_elements_own_slot_offers_copy_but_not_move(client):
    """Clause 5, rendered. A copy into your own slot is a meaningful sibling copy;
    a move there is "send myself to the end of my own group"."""
    course, unit = _seed(client)
    subject = _text(unit)  # top level, so the top-level slot is its own
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)
    top = body[body.index('class="addwrap"') :]

    assert 'value="copy"' in top
    # The top-level slot's own move button is gone; any move button still on the
    # page belongs to a different slot.
    assert 'value="move"' not in top[: top.index("</form>", top.index('value="copy"'))]


def test_a_slot_that_fails_the_rule_renders_no_buttons(client):
    """A slidebreak is non-nestable, so no container slot may take it -- but the
    top-level slot still may, which is what keeps this from being vacuous."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    sb = Element.objects.create(
        unit=unit, content_object=SlideBreakElement.objects.create()
    )
    _mark(client, course, unit, sb)

    body = _editor(client, course, unit)

    section = _slot_section(body, f'data-tab-id="{slots[0]}"')
    assert 'data-op="element-paste"' not in section
    assert 'data-op="element-paste"' in body  # the top-level slot still offers them


def test_a_columns_slot_gets_its_own_key_not_the_enclosing_tabs_one(client):
    """The `:132` condition binds `column`, NOT `tab`. Nested inside a tabs element
    the recursive include passes no `only`, so a copied `tab.id` silently names the
    enclosing TAB and matches nothing -- and the clip_active disjunct hides that
    until the render AFTER a paste."""
    course, unit = _seed(client)
    outer, oslots = _tabs(unit)
    cols_obj = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols = Element.objects.create(
        unit=unit, content_object=cols_obj, parent=outer, tab_id=oslots[0]
    )
    col_ids = [c["id"] for c in cols_obj.data["columns"]]
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    for cid in col_ids:
        section = _slot_section(body, f'data-column-id="{cid}"')
        assert 'data-op="element-paste"' in section, cid
    assert cols.pk


def test_a_spoiler_slot_offers_its_buttons(client):
    course, unit = _seed(client)
    sp = Element.objects.create(
        unit=unit, content_object=SpoilerElement.objects.create(body="<p>s</p>")
    )
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    # Assert on a SPOILER-SPECIFIC marker, not merely on a paste form appearing
    # somewhere after "el-row__spoiler": that slice runs to the end of the document
    # and always contains the top-level slot's own form (rendered after the element
    # list), so a bare substring check passes even when the spoiler site emits
    # nothing -- which is exactly the key-shape defect this test exists to catch,
    # since that site passes `obj.SLOT_ID` rather than `tab.id`.
    assert f'name="tab" value="{SpoilerElement.SLOT_ID}"' in body
    at = body.index(f'name="tab" value="{SpoilerElement.SLOT_ID}"')
    form = body[body.rindex("<form", 0, at) : at]
    assert 'data-op="element-paste"' in form
    assert sp.pk


def test_a_padded_slot_renders_no_paste_button(client):
    """The enumerator's NON-destructive normalizer and the renderer's destructive
    one diverge for a tabs element with fewer than MIN_TABS stored tabs: the
    renderer pads with a freshly minted id that is not in the enumerated set. That
    fails CLOSED -- no button on the padding slot -- which is what this pins.

    The stored id must match TabsElement.TAB_ID_RE (`t[0-9a-f]{6}`) or save()
    replaces it and the test loses its anchor. The minted padding id is not known
    in advance, so it is read back out of the rendered DOM rather than guessed.
    """
    import re as _re

    course, unit = _seed(client)
    thin = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "A"}]})
    join = Element.objects.create(unit=unit, content_object=thin)
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    rendered = _re.findall(r'data-tab-id="([^"]+)"', body)
    assert "t000001" in rendered  # the stored slot survived
    minted = [t for t in rendered if t != "t000001"]
    assert minted, "the renderer must have padded to MIN_TABS"

    # The stored slot offers its buttons; every minted padding slot offers none.
    assert 'data-op="element-paste"' in _slot_section(body, 'data-tab-id="t000001"')
    for mid in minted:
        assert 'data-op="element-paste"' not in _slot_section(
            body, f'data-tab-id="{mid}"'
        ), mid
    assert join.pk


def test_the_form_carries_the_scope_and_a_csrf_token(client):
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)
    at = body.index('data-op="element-paste"')
    form = body[at : at + 900]

    assert "csrfmiddlewaretoken" in form
    assert 'name="mode"' in form
    assert 'name="unit_token"' in form
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_editor_clip_templates.py -v`
Expected: `test_no_paste_buttons_render_when_nothing_is_marked` PASSES (nothing renders them yet — it becomes a real guard once the tag exists); the other seven FAIL on a missing `data-op="element-paste"`.

- [ ] **Step 3: Create the tag's template**

Create `templates/courses/manage/editor/_paste_buttons.html`:

```html
{% load i18n %}
{% if show_move or show_copy %}
<form class="pastewrap" method="post" action="{% url 'courses:manage_element_paste' slug=unit.course.slug %}" data-op="element-paste">
  {% csrf_token %}
  <input type="hidden" name="ctx" value="editor">
  <input type="hidden" name="parent" value="{{ parent }}">
  <input type="hidden" name="tab" value="{{ tab }}">
  <input type="hidden" name="unit" value="{{ unit.pk }}">
  <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
  {% if show_move %}<button class="iconbtn pastebtn" type="submit" name="mode" value="move" aria-label="{% trans 'Move here' %}" title="{% trans 'Move here' %}">📋</button>{% endif %}
  {% if show_copy %}<button class="iconbtn pastebtn" type="submit" name="mode" value="copy" aria-label="{% trans 'Copy here' %}" title="{% trans 'Copy here' %}">⧉</button>{% endif %}
</form>
{% endif %}
```

- [ ] **Step 4: Register the tag**

In `courses/templatetags/courses_manage_extras.py`, append:

```python
@register.inclusion_tag(
    "courses/manage/editor/_paste_buttons.html", takes_context=True
)
def paste_buttons(context, parent="", tab=""):
    """Render the paste controls for ONE slot, if the rule allows them.

    The template never re-derives the rule: it tests this slot's key against the
    two precomputed sets the view built by calling paste_allowed per slot per mode.

    takes_context so it can read `unit` and the sets off the ambient context. Note
    there is no `slug` key in the editor context -- the templates all spell it
    `unit.course.slug`, and so does the form action. NOT for CSRF: Django's
    InclusionNode.render copies csrf_token into the fresh context unconditionally.

    `parent` is "" for the synthetic top-level slot. The None test is explicit for
    the same reason builder.slot_key's is -- `parent or None` would collapse a pk
    of 0 onto the top-level key.
    """
    parent_pk = None if parent == "" or parent is None else parent
    key = builder.slot_key(parent_pk, tab or "")
    return {
        "unit": context.get("unit"),
        "parent": parent if parent_pk is not None else "",
        "tab": tab or "",
        "show_move": key in (context.get("move_slots") or set()),
        "show_copy": key in (context.get("copy_slots") or set()),
    }
```

`builder` is already imported in this module (PR1's `slot_key` filter delegates to it).

- [ ] **Step 5: Invoke it at the four slot sites**

`templates/courses/manage/editor/_element_row.html:91` — **outside** the depth guard:

```html
        {% if depth < max_nest_depth %}{% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=tab.id depth=depth %}{% endif %}{% paste_buttons el.pk tab.id %}
```

`:141` — note the loop variable is `column`, **not** `tab`:

```html
        {% if depth < max_nest_depth %}{% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=column.id depth=depth %}{% endif %}{% paste_buttons el.pk column.id %}
```

`:195` — the spoiler's fixed slot:

```html
    {% if depth < max_nest_depth %}{% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=obj.SLOT_ID depth=depth %}{% endif %}{% paste_buttons el.pk obj.SLOT_ID %}
```

`templates/courses/manage/editor/_editor_scope.html:32` — the top-level slot, which carries no parent and no tab:

```html
      {% include "courses/manage/editor/_add_menu.html" with depth=0 %}{% paste_buttons %}
```

`_element_row.html` already loads `courses_manage_extras`; confirm `_editor_scope.html` does too and add it to its `{% load %}` line if not.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_editor_clip_templates.py -v`
Expected: all **8** PASS.

- [ ] **Step 7: Falsify the absence assertions**

Make the tag return `{"show_move": False, "show_copy": False, ...}` unconditionally.
Run: `uv run pytest tests/test_editor_clip_templates.py -v`
Expected: `test_the_top_level_slot_offers_its_buttons`, `test_the_marked_elements_own_slot_offers_copy_but_not_move`, `test_a_columns_slot_gets_its_own_key_not_the_enclosing_tabs_one`, `test_a_spoiler_slot_offers_its_buttons` and `test_the_form_carries_the_scope_and_a_csrf_token` FAIL, while every "renders no button" case stays green. That contrast is what makes the absence assertions mean something. Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/templatetags/courses_manage_extras.py templates/courses/manage/editor/ tests/test_editor_clip_templates.py
git commit -m "feat(editor): offer move-here and copy-here on every legal slot"
```

---

### Task 11: The mark's own UI — row modifier, banner, forced-open containers

**Files:**
- Modify: `templates/courses/manage/editor/_element_row.html` — the `<li class="el-row…">` opening tag in **all six branches** (`:3`, `:19`, `:45`, `:97`, `:147`, `:199`), and the two `<details>` conditions (`:82`, `:132`)
- Modify: `templates/courses/manage/editor/_editor_scope.html:8` — the banner in `.pane-head`
- Modify: `templates/courses/manage/editor/_element_row_controls.html` — the ⊹ select form
- Test: `tests/test_editor_clip_templates.py` (append)

**Interfaces:**
- Consumes: `clip_active`, `clip_element_pk`, `clip_label` (Task 9).
- Produces: the ⊹ control and the mark's visible state.

**The row modifier is six edits, not one.** Only the *controls* come from the shared partial; the `<li class="el-row…">` opening tag is written out separately in every branch. A test asserting the modifier on a nested row as well as a top-level one is what stops five branches shipping unmarked.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_editor_clip_templates.py`:

```python
def test_every_container_renders_open_while_a_mark_is_pending(client):
    """A legal target could otherwise hide inside a collapsed tab. This test lives
    in THIS task, not with the paste-button tests: the `{% elif clip_active %}`
    disjunct it depends on is added in Step 5 below, so at the end of the previous
    task only `forloop.first` is open and this would be RED for a correct
    implementation."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    _text(unit, parent=dest, tab=slots[1])
    subject = _text(unit)
    _mark(client, course, unit, subject)

    body = _editor(client, course, unit)

    for sid in slots:
        marker = f'data-tab-id="{sid}"'
        tag = body[body.index(marker) : body.index(marker) + 200]
        assert " open" in tag, sid
        assert "data-force-open" in tag, sid


def test_every_row_offers_a_select_control(client):
    """The control lives in the shared partial, so one edit covers all six
    branches -- assert a NESTED row too, or a regression that drops the partial
    from one branch ships green."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    _text(unit, parent=dest, tab=slots[0], body="<p>nested</p>")

    body = _editor(client, course, unit)

    assert body.count('data-op="element-clip"') >= 2
    at = body.index('data-op="element-clip"')
    form = body[at : at + 700]
    assert "csrfmiddlewaretoken" in form
    assert 'name="action" value="select"' in form


def test_the_marked_row_carries_its_modifier_at_every_depth(client):
    """Six edits, not one: the <li class="el-row..."> tag is written out separately
    in every branch of _element_row.html."""
    course, unit = _seed(client)
    dest, slots = _tabs(unit)
    nested = _text(unit, parent=dest, tab=slots[0], body="<p>nested</p>")

    _mark(client, course, unit, nested)
    body = _editor(client, course, unit)

    at = body.index(f'data-element="{nested.pk}"')
    opening = body[body.rindex("<li", 0, at) : at]
    assert "el-row--marked" in opening


def test_a_marked_container_row_carries_the_modifier_too(client):
    course, unit = _seed(client)
    dest, _slots = _tabs(unit)

    _mark(client, course, unit, dest)
    body = _editor(client, course, unit)

    at = body.index(f'data-element="{dest.pk}"')
    opening = body[body.rindex("<li", 0, at) : at]
    assert "el-row--marked" in opening


def test_the_banner_names_the_marked_element_inside_the_swapped_pane(client):
    """applyFragments replaces only the two [data-scope] panes, so a banner in
    editor.html's chrome would render once on page load and then never reflect a
    select, a cancel or a paste."""
    course, unit = _seed(client)
    subject = _text(unit)
    subject.title = "My favourite paragraph"
    subject.save(update_fields=["title"])

    resp = _mark(client, course, unit, subject)
    body = resp.content.decode()

    assert 'id="clip-banner"' in body
    assert body.index('id="clip-banner"') > body.index('data-scope="editor"')
    assert "My favourite paragraph" in body
    assert 'data-op="element-clip"' in body
    assert 'value="cancel"' in body


def test_the_banner_falls_back_to_the_type_summary_when_the_title_is_empty(client):
    """Element.title is routinely empty, so a naive label renders `"" is selected`."""
    course, unit = _seed(client)
    subject = _text(unit, body="<p>Some prose here</p>")
    assert subject.title == ""

    resp = _mark(client, course, unit, subject)
    body = resp.content.decode()
    banner = body[body.index('id="clip-banner"') : body.index('id="clip-banner"') + 400]

    assert banner.strip() != ""
    assert "Some prose" in banner or "Text" in banner


def test_no_banner_renders_when_nothing_is_marked(client):
    course, unit = _seed(client)
    _text(unit)

    body = _editor(client, course, unit)

    assert 'id="clip-banner"' not in body
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_editor_clip_templates.py -v`
Expected: the six new positive tests FAIL — the five mark/banner ones plus `test_every_container_renders_open_while_a_mark_is_pending`, whose `clip_active` disjunct does not exist until Step 5. `test_no_banner_renders_when_nothing_is_marked` passes for now and becomes a real guard once the banner exists.

- [ ] **Step 3: Add the ⊹ select form to the shared partial**

In `templates/courses/manage/editor/_element_row_controls.html`, insert **between** the duplicate form and the delete form — that ordering is what puts ⧉ ⊹ before 🗑:

```html
<form class="tree__inline" method="post" action="{% url 'courses:manage_element_clip' slug=unit.course.slug %}" data-op="element-clip">
  {% csrf_token %}
  <input type="hidden" name="ctx" value="editor">
  <input type="hidden" name="element" value="{{ el.pk }}">
  <input type="hidden" name="unit" value="{{ unit.pk }}">
  <input type="hidden" name="action" value="select">
  <button class="iconbtn" type="submit" aria-label="{% trans 'Select' %}" title="{% trans 'Select' %}">⊹</button>
</form>
```

Glyph assignment is fixed, one meaning each: ⧉ is the copy family (duplicate below, Copy here), ⊹ is select, 📋 is move here.

- [ ] **Step 4: Add the modifier to all six row branches**

In `templates/courses/manage/editor/_element_row.html`, add `{% if clip_element_pk == el.pk|stringformat:'s' %} el-row--marked{% endif %}` inside the `class="…"` attribute of the `<li>` at `:3`, `:19`, `:45`, `:97`, `:147` and `:199`. For example, the slidebreak branch at `:3` becomes:

```html
<li class="el-row element-row--slidebreak{% if clip_element_pk == el.pk|stringformat:'s' %} el-row--marked{% endif %}" data-slidebreak-row
```

and the plain branch at `:199`:

```html
<li class="el-row{% if open_form_pk == el.pk|stringformat:'s' %} el-row--editing{% endif %}{% if clip_element_pk == el.pk|stringformat:'s' %} el-row--marked{% endif %}"
```

The comparison spelling is the repo's existing one (`_element_row.html:19` uses it for `open_form_pk`) and is why the view stringifies `clip_element_pk`: passing the int through would make every row's comparison `int == str` → False.

- [ ] **Step 5: Force containers open while a mark is pending**

In the same file, add the `clip_active` disjunct to both `<details>` conditions. `:82` (tabs):

```html
      <details class="tabs-rows" data-tab-id="{{ tab.id }}"{% if el.pk|slot_key:tab.id|in_set:open_slots %} open data-force-open{% elif clip_active %} open data-force-open{% elif forloop.first %} open{% endif %}>
```

`:132` (columns — the loop variable is `column`):

```html
      <details class="columns-rows" data-column-id="{{ column.id }}"{% if el.pk|slot_key:column.id|in_set:open_slots %} open data-force-open{% elif clip_active %} open data-force-open{% elif forloop.first %} open{% endif %}>
```

`data-force-open` is stamped in the `clip_active` branch too, because PR1's `applyStoredTabs` skip is keyed on that attribute — without it the author's stored collapse re-collapses the destination immediately after the swap and hides the very paste button the mark exists to reach.

- [ ] **Step 6: Add the banner to the pane head**

In `templates/courses/manage/editor/_editor_scope.html`, replace the `.pane-head` div (`:8`) with:

```html
    <div class="pane-head"><h2>{% trans "Editor" %}</h2><span class="pane-head__count">{% blocktranslate count n=rows|length %}{{ n }} element{% plural %}{{ n }} elements{% endblocktranslate %}</span>
      {% comment %}
      The mark banner MUST live inside [data-scope="editor"]: applyFragments
      replaces only the two panes, and editor.html's header region sits outside
      both -- a banner there would render once on page load and then never reflect
      a select, a cancel or a paste.
      {% endcomment %}
      {% if clip_active %}<span id="clip-banner" class="clip-banner">⊹ {% blocktranslate %}Selected: {{ clip_label }}{% endblocktranslate %}
        <form class="tree__inline" method="post" action="{% url 'courses:manage_element_clip' slug=unit.course.slug %}" data-op="element-clip">
          {% csrf_token %}
          <input type="hidden" name="ctx" value="editor">
          <input type="hidden" name="element" value="{{ clip_element_pk }}">
          <input type="hidden" name="unit" value="{{ unit.pk }}">
          <input type="hidden" name="action" value="cancel">
          <button class="iconbtn" type="submit" aria-label="{% trans 'Cancel selection' %}" title="{% trans 'Cancel selection' %}">✕</button>
        </form>
      </span>{% endif %}
    </div>
```

`✕` is context-scoped: on a row it cancels the open editor, in the banner it cancels the mark. The two never appear in the same control group and both read as "dismiss this".

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_editor_clip_templates.py -v`
Expected: all **15** PASS (this task's 7 appended tests plus Task 10's 8).

- [ ] **Step 8: Regenerate translations**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

**Expect several new msgids** — `Select`, `Cancel selection`, `Move here`, `Copy here`, `Selected: %(clip_label)s`, and the eight refusal messages from Task 9. Every one of them is new to this branch.

Then, before compiling:
- **Check the diff for `#, fuzzy` markers.** A fuzzy entry carries a WRONG pre-filled translation from an unrelated msgid and is ignored until the marker is cleared — and clearing it is TWO deletions, the `#, fuzzy` line **and** the `#| msgid "…"` provenance comment. Read every new `msgstr` rather than trusting it.
- Fill in a Polish translation for each new entry. Suggested, all to be flagged in your report for a native-speaker check:
  - `Select` → `Zaznacz`
  - `Cancel selection` → `Anuluj zaznaczenie`
  - `Move here` → `Przenieś tutaj`
  - `Copy here` → `Kopiuj tutaj`
  - `Selected: %(clip_label)s` → `Zaznaczono: %(clip_label)s`
  - `That element is not part of this unit.` → `Ten element nie należy do tej lekcji.`
  - `An element cannot be placed inside itself.` → `Nie można umieścić elementu w nim samym.`
  - `That destination is not a container.` → `To miejsce nie jest kontenerem.`
  - `That slot no longer exists.` → `To miejsce już nie istnieje.`
  - `This type cannot be placed inside a container.` → `Tego typu nie można umieścić w kontenerze.`
  - `This element is too deep to fit there.` → `Ten element jest zbyt zagnieżdżony, aby się tam zmieścić.`
  - `It is already there.` → `Element już tam jest.`
  - `The destination was removed while you were working.` → `Miejsce docelowe zostało usunięte w trakcie pracy.`
- A placeholder must survive verbatim: `%(clip_label)s` in the Polish string too, or the render raises.

Then: `uv run python manage.py compilemessages`

Report exactly which msgids were added, which arrived fuzzy, and what you did about each.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/editor/ tests/test_editor_clip_templates.py locale/
git commit -m "feat(editor): show the clipboard mark, its banner and its select control"
```

---

### Task 12: Styling and visual verification

A modifier class with no rule is invisible, which for the mark is indistinguishable from the feature being broken.

**Files:**
- Modify: `courses/static/courses/css/editor.css`

`.el-row`, `.el-actions`, `.pane-head`, `.addwrap`, `.iconbtn` and `.tabs-rows` are all defined in `editor.css` and nowhere else on this page, so the new rules belong beside them. `courses.css` loads first with the shared base, so equal-specificity rules here win.

- [ ] **Step 1: Add the three rule groups**

Beside the existing `.el-row` / `.pane-head` / `.addwrap` definitions, using the project's `--space-*` and colour tokens rather than raw pixels:

1. `.el-row--marked` — a visible but non-shouty selected state (an accent left border or ring plus a faint background tint). It must read as "selected", distinct from `.el-row--editing`.
2. `.clip-banner` — sits in `.pane-head` beside the element count; must not push the count onto a second line at a narrow pane width, and its ✕ button aligns with the text.
3. `.pastewrap` / `.pastebtn` — grouped against `.addwrap`, since in practice an add-menu is always beside them.

   **On the "standalone" appearance:** the tag call sits outside the `{% if depth < max_nest_depth %}` guard on purpose (paste legality is `paste_allowed`'s business, not the menu's), but that guard compares the CONTAINER's depth against 4 — and a container may only live at depths 1–3, so `depth < 4` holds at every legally reachable slot and the menu is never actually suppressed beside a paste button. A standalone rule is therefore defensive-only, reachable solely through a corrupt depth-4 container written directly by the ORM. Add one if it costs a line, but do not treat it as a shipping requirement and do not go hunting for the screenshot.

- [ ] **Step 2: Screenshot a marked row and a slot's paste buttons, light mode**

Use the `/run` skill or the project's documented dev-server steps, drive a real browser, and capture: a marked top-level row, a marked nested row, and a slot showing both paste buttons beside its add-menu. Check the row bar does not wrap now that it holds ✎ ✕ ↑ ↓ ⧉ ⊹ 🗑 — that is the highest-risk item here, since this task adds the seventh control.

Do **not** try to screenshot a paste button with no add-menu beside it: as Step 1 explains, that state is unreachable for any legally authored container.

- [ ] **Step 3: Screenshot the same in dark mode**

Judge dark separately — never infer it from the light pass. Check the marked-row tint against the row background and the banner's contrast in the pane head.

- [ ] **Step 4: Fix what the screenshots show, and re-screenshot to prove it**

If nothing is wrong, change nothing and say so explicitly with the evidence that convinced you.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/css/editor.css
git commit -m "style(editor): style the clipboard mark, its banner and the paste controls"
```

---

### Task 13: The e2e — a populated container moved into a spoiler

Per the depth-3 lesson, the fixture must move a **populated container**: that is the state an *add* can never produce, and therefore the state no existing test covers.

**Files:**
- Create: `tests/test_e2e_clipboard.py`

- [ ] **Step 1: Write the e2e**

Create `tests/test_e2e_clipboard.py`. The login/seed helpers mirror `tests/test_e2e_editor_force_open.py:26-60` (PR1 created it) and `tests/test_e2e_depth3.py:91-101` exactly rather than being invented:

```python
"""Playwright e2e for the clipboard: select a POPULATED container and move it
into a spoiler, through the real buttons.

A populated container landing in a new slot is a shape an ADD can never produce,
so no existing test covers it -- which is exactly how the depth-3 slice shipped
two client-side defects that thirteen per-task reviews missed.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


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


def _seed(owner, slug):
    """A unit holding a POPULATED Tabs (child in tab 2) and an empty Spoiler.

    Seeded through the ORM on purpose: the gesture under test is select-then-paste,
    not the authoring of a container (test_e2e_depth3 already drives the real
    add-menu for that).
    """
    from courses.models import Element
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>CLIPMARKER-child</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    spoiler = Element.objects.create(
        unit=unit,
        content_object=SpoilerElement.objects.create(
            label="Rozwiązanie", body="<p>s</p>"
        ),
    )
    return course, unit, tabs_join, t1, t2, child, spoiler


@pytest.mark.django_db(transaction=True)
def test_a_populated_container_moves_into_a_spoiler_and_reaches_the_student(
    page, live_server
):
    user = _make_pa_user("pa")
    course, unit, tabs_join, t1, _t2, child, spoiler = _seed(user, "clipboard")
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )

    # Plant a stored collapse on tab 1 BEFORE marking. Without the force-open
    # stamp the mark's re-render would re-collapse it client-side, and this is the
    # only way to prove the stamp is honoured -- a template test never runs
    # applyStoredTabs. The key shape is editor.js's tabStoreKey.
    tab1 = page.locator(f"details.tabs-rows[data-tab-id='{t1}']")
    tab1.locator("summary").click()  # toggle -> saveTab writes an entry
    page.evaluate(
        "key => localStorage.setItem(key, '0')",
        f"libli:tabopen:{tabs_join.pk}:{t1}",
    )

    # 1. Select the POPULATED container, through the real button.
    #
    # The locator must be scoped to the row's OWN control bar. A tabs row nests its
    # child rows inside its own <li class="el-row" data-element=...> (_element_row
    # .html:80-95), and every row carries its own element-clip form -- so a plain
    # descendant locator matches the container's button AND its child's, and
    # Playwright's strict mode raises before anything is clicked.
    tabs_row = page.locator(f".el-row[data-element='{tabs_join.pk}']")
    tabs_controls = tabs_row.locator(
        "> .el-row__head .el-actions form[data-op='element-clip'] button"
    )
    with page.expect_response(lambda r: "element/clip/" in r.url):
        tabs_controls.click()

    expect(page.locator("#clip-banner")).to_be_visible()
    expect(page.locator(f".el-row[data-element='{tabs_join.pk}']")).to_have_class(
        __import__("re").compile(r"el-row--marked")
    )
    # The stored collapse must NOT win while a mark is pending.
    expect(page.locator(f"details.tabs-rows[data-tab-id='{t1}']")).to_have_attribute(
        "open", ""
    )

    # 2. Paste it into the spoiler's slot, through the real button. Scoped to the
    #    spoiler's own slot container for the same strict-mode reason: once the
    #    tabs element lands inside it, that subtree carries paste forms of its own.
    spoiler_row = page.locator(f".el-row[data-element='{spoiler.pk}']")
    with page.expect_response(lambda r: "element/paste/" in r.url):
        spoiler_row.locator(
            "> .el-row__spoiler > form[data-op='element-paste'] button[value='move']"
        ).click()

    # 3. The container and its child are now inside the spoiler.
    moved = page.locator(
        f".el-row[data-element='{spoiler.pk}'] .el-row__spoiler "
        f".el-row[data-element='{tabs_join.pk}']"
    )
    expect(moved).to_have_count(1)
    expect(
        page.locator(f".el-row[data-element='{child.pk}']")
    ).to_have_count(1)
    # The mark is cleared by a move, so the banner is gone.
    expect(page.locator("#clip-banner")).to_have_count(0)

    # 4. The student sees it. A move the student page cannot render is worthless.
    page.goto(_lesson_url(live_server, unit))
    expect(page.get_by_text("CLIPMARKER-child")).to_have_count(1)
```

`to_have_class` takes a regex here because the row's class list also carries `el-row--tabs`; importing `re` inline keeps the import block matching the neighbouring e2e files. If your `ruff` configuration objects to `__import__`, add a plain `import re` at the top instead and say so in your report.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_e2e_clipboard.py -m e2e -v`
Expected: PASS, with the summary line showing **1** test actually ran. `-m e2e` is mandatory — without it the test is silently deselected and pytest exits 5, which reads as a pass.

- [ ] **Step 3: Falsify it — twice**

1. Make `_clip_context` return its `empty` dict unconditionally.
   Expected: FAIL at the paste step — no paste button exists to click.
2. Restore that, then remove the `{% elif clip_active %} open data-force-open` branch from the tabs `<details>` condition.
   Expected: FAIL at the `to_have_attribute("open", "")` assertion — the stored collapse wins and the destination hides.

Restore both, re-run to confirm GREEN, and record all three observations. The second falsification is the one a template test can never perform.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_clipboard.py
git commit -m "test(e2e): move a populated container into a spoiler through the real UI"
```

---

### Task 14: Full suite, lint, and the newly-legal combinations

- [ ] **Step 1: Confirm the newly-legal combinations are covered**

A move can produce shapes an add never could — that is how the depth-3 slice shipped two client-side defects thirteen per-task reviews missed. This enumeration is **already resolved**; your job is to confirm each named test exists and passes, not to audit afresh. Run:

```bash
uv run pytest tests/test_builder_paste_element.py tests/test_element_paste_view.py -v
```

and tick each combination against its test:

| Newly-legal shape | Covering test |
|---|---|
| populated container into a **tabs** slot | `test_a_copy_creates_fresh_rows_in_the_destination_slot`, `test_a_move_carries_its_whole_subtree_without_touching_the_children` |
| into a **columns** slot (incl. a 3rd column) | `test_a_move_into_a_third_column_lands_there`, `test_a_paste_into_a_column_works_end_to_end` |
| into a **spoiler** slot | `test_a_move_into_a_spoiler_uses_its_fixed_slot`, `test_a_move_into_a_spoiler_works_end_to_end` |
| same type inside itself (Tabs in Tabs) | `test_a_copy_preserves_the_subtree_shape_at_every_depth` places a Tabs subtree into a Tabs slot; `courses/tests/test_paste_rule.py::test_a_leaf_may_land_at_depth_four_but_a_container_may_not` pins the depth limit of that shape |
| moved **out** of a container to top level | `test_a_move_of_a_damaged_row_to_top_level_succeeds` (structural), plus the e2e's student-page assertion |
| between two slots of the **same** container | `test_a_move_clears_the_mark_and_a_copy_keeps_it` pastes into `slots[0]` then `slots[1]` of one container |
| a subtree reaching exactly depth 4 | `courses/tests/test_paste_rule.py::test_a_leaf_may_land_at_depth_four_but_a_container_may_not` |

If any row's test is missing or fails, that is a finding: report it rather than adding an untested fixture here — new coverage belongs in Task 7 or Task 9 with a named mutant, not in this task's `chore` commit.

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest --verbosity=0 -n 4` (about 8 minutes; foreground)
Expected: no failures. Report the summary line verbatim.

- [ ] **Step 3: Run the e2e suite**

Run: `uv run pytest -m e2e --verbosity=0` (over an hour; foreground, and the only pytest running)
Expected: no failures. Report how many tests actually ran — a run reporting "no tests ran" is not evidence.

- [ ] **Step 4: Lint**

```bash
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 5: Commit anything outstanding**

```bash
git add -A
git commit -m "chore(editor): final checks for the element clipboard"
```

---

## Out of scope for PR2

Cross-unit and cross-course clipboard (both reachable later on this machinery — the transfer layer already re-homes media and rewrites internal links). Dragging a row into a container. Multi-select. Undo of a move. Any change to `reorder_element`. Making the pasted element the scroll anchor: `editor.js` computes its anchor from the form's nearest `.el-row` *before* the POST, so it can only ever name a row that already exists; forcing the ancestor chain open is what keeps the result visible instead.
