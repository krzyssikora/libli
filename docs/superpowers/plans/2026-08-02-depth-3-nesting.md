# Depth-3 Nesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the element nesting cap from 2 levels to 3, fold `SpoilerElement` into the existing container plumbing, and fix the four code paths that silently assume one level of nesting.

**Architecture:** One containment rule (`MAX_NEST_DEPTH = 3`, containers at depth 1–2 only, one leaf allowlist) enforced at exactly one place per surface: `resolve_scope` on the write path, `validate_nesting` on the import path, a recursive `seen`-guarded collector on the delete path, a recursive walk on the export path, and a `depth`/`max_nest_depth` pair threaded through the editor templates. Depth is computed by walking `Element.parent`, never stored — so there is **no migration**.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, Playwright (e2e), ruff, uv.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-02-depth-3-nesting-design.md`. Read it before starting. It carries a table of **fifteen of its own falsified claims** — several introduced by an earlier review round's fix. Treat every file:line in it as a claim to verify, not a fact.
- **Base:** master `901f6cf0`. Branch `pipeline/depth-3-nesting`. Worktree `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/depth-3-nesting` with its own `.env` (`DATABASE_URL=…/libli_d3n`).
- **Tooling:** `ruff`/`pytest`/`python` are NOT on PATH. Always `uv run pytest`, `uv run python`, `uv run ruff`.
- **`addopts` is already `-q -m 'not e2e'`** (`pyproject.toml:49`). NEVER add a second `-q` — it suppresses the summary entirely and leaves no verdict. Use `--verbosity=0`. For e2e, `-m e2e` is mandatory or every e2e test is silently deselected (exit 5).
- **Run the full suite serially** (no `-n`): the Windows xdist DB-setup race produces spurious failures at ~98%.
- **No migration is expected.** `makemigrations --check --dry-run` must stay clean. A migration appearing means the design was not followed.
- **Every test carries a named mutant, verified RED against that test by node id** — apply mutant, run `uv run pytest <node-id> --verbosity=0`, observe FAIL, revert. "The suite went red" proves nothing.
- **`pytest-timeout` is NOT installed.** A mutant that hangs can never be verified RED — it wedges the run. Where the spec forbids a hanging mutant, that prohibition is load-bearing.
- Commit after every task. Conventional-commit subjects.

---

## File Structure

| File | Responsibility in this slice |
|---|---|
| `courses/builder.py` | `MAX_NEST_DEPTH`, `CONTAINER_TRANSFER_KEYS`, `element_depth`, `_collect_subtree_pks`, `SpoilerElement` registry entry, `resolve_scope` rule, delete + tab-removal cleanup |
| `courses/transfer/payloads.py` | `validate_nesting` chain walk, `"spoiler": None` slot key, 3 reworded + 1 new message |
| `courses/transfer/export.py` | recursive `seen`-guarded `walk_unit_joins` |
| `courses/views.py` | `has_html` at both context builders; delete `html_ct_id` and the `HtmlElement` import |
| `courses/views_manage.py` | `max_nest_depth` into **both** editor context builders |
| `courses/lal_loader/builders.py` | keep the narrow spoiler-child gate as a local constant |
| `templates/courses/manage/editor/_editor_scope.html` | seeds `depth` |
| `templates/courses/manage/editor/_element_row.html` | depth threading, spoiler branch, add-menu guards |
| `templates/courses/manage/editor/_add_menu.html` | drop `in_spoiler`, depth-based card guards |
| `docs/help/course-admin/*.md` (4 files) | author-facing wording |

### Shared test fixture helper

Tasks 1, 3, 4, 7 and 8 all need to build nested `Element` trees, including depth-3 shapes that `resolve_scope` deliberately refuses. **Task 1 defines `_mk` in `courses/tests/test_nesting_rule.py` with the FULL type set any later task needs** — `text`, `math`, `table`, `tabs`, `two_column`, `spoiler` — and every later task imports it from there rather than redefining it:

```python
from courses.tests.test_nesting_rule import _mk
```

Task 4 needs `table`, Task 7 needs `math`; both are in the set above, so neither has to extend it. If a later task nonetheless must, extend `_mk` in place in Task 1's file rather than writing a parallel helper — two divergent builders is how fixture drift starts — and add `courses/tests/test_nesting_rule.py` to that task's `git add`, or the extension is left unstaged and the tree dirty across two commits.

**Test-code conventions for every task below.** The code blocks are abbreviated where a fixture is routine, but they must be written as real, runnable Python:

- Signatures are real (`def test_x():`, or naming the fixtures actually used). A bare `(...)` is a `SyntaxError`.
- Every DB test carries `@pytest.mark.django_db`.
- Names like `course`, `unit`, `unit_token` come from `make_course_with_unit()` (`tests/factories.py:133`) — **`tests.factories`, not `courses.tests.factories`**, which does not exist.
- `unit_token` is `unit.updated.isoformat()`.
- Before writing any fixture, open the helper and confirm its real signature. Inventing one is how a plan ships test code that cannot run.

---

## Task 0: Baseline — verify claims and re-derive the guardrail list

**No production code changes.** This task exists because the spec's own claim table records fifteen falsified claims, and because the guardrail-inversion list grew 3 → 9 → 14 → 16 across review rounds (round 8 found a whole file the previous seven missed). Trusting either would be a mistake.

**Files:**
- Create: `docs/superpowers/plans/baseline-2026-08-02.md` (scratch notes, committed)

- [ ] **Step 1: Record Group A gates green on the unmodified tree**

```bash
cd C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/depth-3-nesting
uv run pytest --verbosity=0        # expect: "N passed" line + exit 0. RECORD N.
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run pytest tests/test_i18n_po_health.py --verbosity=0   # 5th gate; Task 12 re-runs it
```

Record the baseline pass count `N`. Every later task compares against it.

- [ ] **Step 2: Record the Group B phrases still PRESENT on the unmodified tree**

Each phrase must still be **present (count ≥ 1)** now, and **absent (0)** after Task 10. A phrase already at 0 here is inert — it can never detect anything — and is itself a defect to fix before proceeding.

```bash
for p in "two container types" "cannot hold another container" "dwa typy kontenerów" \
         "może zawierać innego kontenera" "nestable inside Tabs and Columns" \
         "wewnątrz Zakładek" "zagnieżdżalne w Zakładkach i Kolumnach"; do
  printf '%-42s ' "$p"; grep -rc "$p" docs/help/ | grep -v ':0' | wc -l
done
```

Expected: every phrase matches ≥1 file. (`nestable inside Tabs and Columns` matches **two**.)

- [ ] **Step 3: Verify the load-bearing mechanism claims by execution**

```bash
DJANGO_SETTINGS_MODULE=config.settings.test uv run python -c "
import django; django.setup()
from courses.models import SpoilerElement, TabsElement, Element
from courses.builder import NESTABLE_TYPE_KEYS, SPOILER_CHILD_TYPES, _CONTAINER_REGISTRY
from courses.transfer.export import SERIALIZERS
print('spoiler fields   :', [f.name for f in SpoilerElement._meta.get_fields()])
print('spoiler has .data:', hasattr(SpoilerElement(), 'data'))   # MUST be False
print('NESTABLE count   :', len(NESTABLE_TYPE_KEYS))             # MUST be 19
print('SPOILER count    :', len(SPOILER_CHILD_TYPES))            # MUST be 14
print('subset invariant :', NESTABLE_TYPE_KEYS <= set(SERIALIZERS))
print('tabs+2col in ser :', {'tabs','two_column'} <= set(SERIALIZERS))
print('registry keys    :', [k.__name__ for k in _CONTAINER_REGISTRY])
print('Element.ordering :', Element._meta.ordering)
"
```

If `spoiler has .data` prints `True`, the spec's central call-site fix is wrong — **stop and report**.

- [ ] **Step 4: Re-derive the guardrail-inversion list by SEARCH**

Do not trust the spec's 16 rows. Run these and reconcile:

```bash
uv run python -c "print('--- NestingError assertions ---')"
grep -rn "NestingError" tests/ courses/tests/ --include=*.py
grep -rn "not in NESTABLE_TYPE_KEYS\|SPOILER_CHILD_TYPES" tests/ courses/tests/ --include=*.py
# Import sites specifically -- a module-level import of a deleted constant is a
# COLLECTION-time ImportError that takes a whole file down, and the usage-pattern
# greps above will not surface it:
grep -rn "import SPOILER_CHILD_TYPES" . --include=*.py
grep -rn "data-add-type" tests/ courses/tests/ --include=*.py
grep -rn "nested more than one level\|may not be nested" tests/ courses/tests/ --include=*.py
# Search the TEMPLATE NAMES, not the call: three of the five direct-render sites put
# the template path on the line AFTER `render_to_string(`, so a single-line pipe on
# the call finds only 2 of 5. This form also surfaces the two file-reading oracles
# (tests/test_help.py, tests/test_tabs_editor_dnd.py) Task 8 should know about.
grep -rn "_element_row\.html\|_add_menu\.html" tests/ courses/tests/ --include=*.py
grep -rn "validate_nesting" tests/ courses/tests/ --include=*.py
# View-level rejections: a test can guard the old cap with nothing but a bare
# `assert resp.status_code == 400` -- no constant, no exception, no card. Every grep
# above misses those. tests/test_tabs_registry.py:71-79 is exactly such a site and
# was found only by running the suite against the diff.
grep -rn "status_code == 400\|status_code) == 400" tests/ courses/tests/ --include=*.py
```

Write the reconciled list into `docs/superpowers/plans/baseline-2026-08-02.md`: every site, whether the spec listed it, and the intended action. **Any site the spec missed is expected, not anomalous** — record it and carry it forward.

**Grepping is necessary but NOT sufficient.** The 17th site was invisible to every pattern above. Before Task 1's commit, run the full suite against the applied diff and treat each failure as a candidate guardrail — that is the only search that is actually complete.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/baseline-2026-08-02.md
git commit -m "chore(depth-3): record baseline gates and re-derived guardrail list"
```

---

## Task 1: The containment rule on the write path

**Files:**
- Modify: `courses/builder.py` (constants ~`:24-102`, `resolve_scope` `:105-158`)
- Modify: `courses/transfer/payloads.py` — **imports `:758-760`, `_CONTAINER_SLOT_KEY:750`, and the `parent["type"] == "spoiler"` branch at `:774-785`.** See "Why payloads.py is in THIS task" below; omitting it leaves this task's commit red.
- Modify: `courses/lal_loader/builders.py:95-115` (keep gate narrow — see Task 2 for its test)
- Test: `courses/tests/test_nesting_rule.py` (create)
- Modify (invert): `tests/test_twocolumn_registry.py`, `courses/tests/test_spoiler_nesting.py` (**including its module-level import at `:8`**), `tests/test_tabs_form_views.py`, and the two transfer sites listed in Step 5b.

**Interfaces:**
- Produces: `builder.MAX_NEST_DEPTH: int`, `builder.CONTAINER_TRANSFER_KEYS: frozenset[str]`, `builder.element_depth(join) -> int`. Task 8 reads `MAX_NEST_DEPTH` via the module attribute; Task 5 extends `validate_nesting`'s walk.
- Consumes: `payloads._CONTAINER_SLOT_KEY`, which this task itself extends with `"spoiler": None`.

### Why `payloads.py` is in THIS task, not Task 5

Deleting `SPOILER_CHILD_TYPES` from `builder.py` breaks `payloads.py` immediately: `:759` does `from courses.builder import SPOILER_CHILD_TYPES` inside `validate_nesting` and `:782` uses it. Every archive/import/duplicate-unit test touching a nested element would `ImportError` at this task's own commit. Likewise the drift test below compares `CONTAINER_TRANSFER_KEYS` against `set(_CONTAINER_SLOT_KEY)`, so the `"spoiler": None` entry must land here too.

So this task does the **structural** payloads change — imports, the slot-key entry, and the membership two-step that replaces the spoiler branch. Task 5 does the **depth walk**, clauses 3/4 and the message rewording. Each task's commit leaves the suite green.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_nesting_rule.py`:

```python
import pytest

from courses import builder
from courses.builder import NestingError
from courses.models import Element

from tests.factories import make_course_with_unit
# NOTE the path: `tests.factories`, NOT `courses.tests.factories` (which does not
# exist). Every file under courses/tests/ imports it this way -- e.g.
# courses/tests/test_callout_authoring.py:10.


def _mk(unit, type_key, parent=None, tab=""):
    """Create an element join row directly through the ORM.

    Used for depth-3 parents: clause 4 forbids a container at depth 3, so such a
    fixture is UNREACHABLE through resolve_scope itself. This is deliberate
    defence-in-depth coverage, not dead code -- do not delete it.
    """
    from courses.models import (MathElement, SpoilerElement, TableElement,
                                TabsElement, TextElement, TwoColumnElement)

    obj = {
        "text": lambda: TextElement.objects.create(body="x"),
        "math": lambda: MathElement.objects.create(latex="x^2"),
        # NB: TableElement has NO default_data() -- only TabsElement (models.py:1355)
        # and TwoColumnElement (:1487) do. Build the dict literally; check
        # TableElement.save()'s sanitiser and the shape
        # tests/test_table_manage_plumbing.py already uses.
        "table": lambda: TableElement.objects.create(data={"cells": [[{"html": "x"}]]}),
        "tabs": lambda: TabsElement.objects.create(data=TabsElement.default_data()),
        "two_column": lambda: TwoColumnElement.objects.create(
            data=TwoColumnElement.default_data()
        ),
        "spoiler": lambda: SpoilerElement.objects.create(label="s"),
    }[type_key]()
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


@pytest.mark.django_db
def test_element_depth_counts_hops():
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    mid = _mk(unit, "tabs", parent=top, tab="t1")
    leaf = _mk(unit, "text", parent=mid, tab="t2")
    assert builder.element_depth(top) == 1
    assert builder.element_depth(mid) == 2
    assert builder.element_depth(leaf) == 3


@pytest.mark.django_db
def test_element_depth_terminates_on_a_cycle():
    _course, unit = make_course_with_unit()
    a = _mk(unit, "tabs")
    b = _mk(unit, "tabs", parent=a, tab="t1")
    a.parent = b
    a.save(update_fields=["parent"])
    # Bounded walk: returns a too-deep value rather than looping forever.
    assert builder.element_depth(a) > builder.MAX_NEST_DEPTH - 1


@pytest.mark.django_db
@pytest.mark.parametrize("child_form_key", ["tabs", "twocolumn", "spoiler"])
def test_container_child_accepted_at_depth_1(child_form_key):
    """A container inside a top-level container lands at depth 2 -- legal."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(top.pk), tab_id, child_form_key)
    assert join == top and slot == tab_id


@pytest.mark.django_db
@pytest.mark.parametrize("child_form_key", ["tabs", "twocolumn", "spoiler"])
def test_container_child_rejected_at_depth_2(child_form_key):
    """Clause 4: a container child of a depth-2 parent would sit at depth 3."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=tab_id)
    mid_tab = mid.content_object.data["tabs"][0]["id"]
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(mid.pk), mid_tab, child_form_key)


@pytest.mark.django_db
def test_leaf_child_accepted_at_depth_2():
    """The same depth-2 parent accepts a LEAF -- this is what makes depth 3 real."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=tab_id)
    mid_tab = mid.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(mid.pk), mid_tab, "text")
    assert join == mid and slot == mid_tab


@pytest.mark.django_db
def test_leaf_child_rejected_at_depth_3():
    """Clause 3. The depth-3 parent is ORM-built: clause 4 makes it unreachable
    through resolve_scope, so this is defence-in-depth. Do not delete as dead."""
    _course, unit = make_course_with_unit()
    top = _mk(unit, "tabs")
    t1 = top.content_object.data["tabs"][0]["id"]
    mid = _mk(unit, "tabs", parent=top, tab=t1)
    t2 = mid.content_object.data["tabs"][0]["id"]
    deep = _mk(unit, "tabs", parent=mid, tab=t2)
    t3 = deep.content_object.data["tabs"][0]["id"]
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(deep.pk), t3, "text")


@pytest.mark.django_db
def test_spoiler_accepts_a_spoiler_child():
    """Purpose bullet 1: spoiler-in-spoiler."""
    _course, unit = make_course_with_unit()
    from courses.models import SpoilerElement

    outer = _mk(unit, "spoiler")
    join, slot = builder.resolve_scope(
        unit, str(outer.pk), SpoilerElement.SLOT_ID, "spoiler"
    )
    assert join == outer and slot == SpoilerElement.SLOT_ID


@pytest.mark.django_db
def test_nested_spoiler_may_have_children():
    """Purpose bullet 3: a spoiler inside a tab may hold children."""
    _course, unit = make_course_with_unit()
    from courses.models import SpoilerElement

    top = _mk(unit, "tabs")
    tab_id = top.content_object.data["tabs"][0]["id"]
    sp = _mk(unit, "spoiler", parent=top, tab=tab_id)
    join, slot = builder.resolve_scope(
        unit, str(sp.pk), SpoilerElement.SLOT_ID, "text"
    )
    assert join == sp and slot == SpoilerElement.SLOT_ID


def test_container_key_spaces_do_not_drift():
    """PR2 adds Callout to THREE structures. Adding it to two silently leaves
    clause 4 permissive. No pre-existing test touches either structure."""
    from courses.transfer.payloads import _CONTAINER_SLOT_KEY

    assert builder.CONTAINER_TRANSFER_KEYS == set(_CONTAINER_SLOT_KEY)
    assert len(builder.CONTAINER_TRANSFER_KEYS) == len(builder._CONTAINER_REGISTRY)


def test_twocolumn_form_key_alias_exists():
    """Without the alias the Columns card is offered nested and every click 400s."""
    assert builder._NESTABLE_FORM_KEY_ALIASES["twocolumn"] == "two_column"
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_nesting_rule.py --verbosity=0
```
Expected: FAIL — `AttributeError: module 'courses.builder' has no attribute 'element_depth'` and `NestingError` where accepts are expected.

- [ ] **Step 3: Implement in `courses/builder.py`**

Move the `SpoilerElement` import to module level (it is currently function-local at `:128`, and the registry needs it as a dict key at import time):

```python
from courses.models import SpoilerElement   # NEW: was resolve_scope-local
```

Replace the allowlist block. Delete `SPOILER_CHILD_TYPES` **and its header comment** (`:58-63`) entirely, and add `tabs` / `two_column` to `NESTABLE_TYPE_KEYS`:

```python
MAX_NEST_DEPTH = 3  # a top-level element has depth 1

# Container TYPE KEYS (transfer namespace). Clause 4 of the containment rule tests
# membership here. PR2 (Callout as a container) must add its key to THIS set, to
# _CONTAINER_REGISTRY and to payloads._CONTAINER_SLOT_KEY -- all three. The drift
# test in test_nesting_rule.py is what stops it landing in only two.
CONTAINER_TRANSFER_KEYS = frozenset({"tabs", "two_column", "spoiler"})

NESTABLE_TYPE_KEYS = frozenset(
    {
        "text", "math", "image", "video", "iframe", "html", "table", "gallery",
        "callout", "spoiler", "reveal_gate", "fill_gate", "switch_gate",
        "switch_grid", "fill_blank", "fill_table", "stepper", "mark_done",
        "guess_number",
        # Containers, as of the depth-3 slice. Both are already in
        # transfer.export.SERIALIZERS, so NESTABLE_TYPE_KEYS <= SERIALIZERS holds.
        "tabs", "two_column",
    }
)
```

Add the alias (note: `builder.py:30-33`'s "except the reveal-gate" comment is now false — Task 9 rewrites it):

```python
_NESTABLE_FORM_KEY_ALIASES = {
    ...,
    "twocolumn": "two_column",   # NEW
}
```

Add the registry entry. **A single-slot container supplies a constant slot list rather than reading `data`:**

```python
_CONTAINER_REGISTRY = {
    TabsElement: (TabsElement.normalize_labels_and_ids, "tabs", "id"),
    TwoColumnElement: (TwoColumnElement.normalize_ids, "columns", "id"),
    # Single-slot: ignores its argument and returns one fixed slot. SpoilerElement
    # has no `data` field, which is why the call site below uses getattr().
    SpoilerElement: (
        lambda _data: {"slots": [{"id": SpoilerElement.SLOT_ID}]},
        "slots",
        "id",
    ),
}
```

Add the depth walk:

```python
def element_depth(join):
    """1 for a top-level element; +1 per parent hop.

    Bounded by MAX_NEST_DEPTH hops so a corrupt parent cycle returns a too-deep
    value instead of looping. The bound is for cycle safety ONLY -- what makes
    MAX_NEST_DEPTH load-bearing is clauses 3 and 4 comparing against it.
    """
    depth = 1
    parent = join.parent
    while parent is not None and depth <= MAX_NEST_DEPTH:
        depth += 1
        parent = parent.parent
    return depth
```

Rewrite `resolve_scope`. **The snippet below replaces `builder.py:121-158` ONLY. Lines 115-120 are unchanged and must be preserved verbatim** — they hold the `.strip()` normalisation, the top-level early return (`if not parent_ref and not tab: return None, ""`) and the both-or-neither check. Dropping the early return would break **every top-level element add**, and no test in this plan supplies a top-level scope, so nothing would catch it:

```python
    # UNCHANGED, builder.py:115-120 -- reproduced here so the boundary is unambiguous:
    parent_ref = (parent_ref or "").strip()
    tab = (tab or "").strip()
    if not parent_ref and not tab:
        return None, ""
    if not parent_ref or not tab:
        raise NestingError("parent and tab must be supplied together")
```

**Evaluation order is pinned: not-a-container, then clauses 1, 2, 3, 4.** (This moves clause 1 ahead of clause 2 relative to today's code — a deliberate, small message change.) Also add `select_related`:

```python
    try:
        join = (
            Element.objects.select_related("parent__parent")
            .filter(pk=int(parent_ref), unit=unit)
            .first()
        )
    except (TypeError, ValueError):
        raise NestingError("bad parent ref") from None
    if join is None:
        raise NestingError("unknown parent")

    parent_obj = join.content_object
    container = _CONTAINER_REGISTRY.get(type(parent_obj))
    if container is None:
        raise NestingError("parent is not a container")

    child_key = _NESTABLE_FORM_KEY_ALIASES.get(type_key, type_key)
    if child_key not in NESTABLE_TYPE_KEYS:                       # clause 1
        raise NestingError(f"{type_key} may not be nested")

    # normalize_data (behind normalized_data) is DESTRUCTIVE and read-side only: it
    # pads/truncates and mints fresh random ids on every call, so a slot validated
    # against it could be an ephemeral phantom that never matches again at render
    # time -- silently orphaning the child. A write path must validate against the
    # ids that actually exist, via the non-destructive normalizer.
    normalizer, list_key, id_key = container
    # getattr: a single-slot container (spoiler) has no `data` field at all, and the
    # argument is evaluated HERE, before the normalizer runs.
    slots = normalizer(getattr(parent_obj, "data", None))[list_key]
    if tab not in {s[id_key] for s in slots}:                     # clause 2
        raise NestingError("unknown slot")

    parent_depth = element_depth(join)
    if parent_depth >= MAX_NEST_DEPTH:                            # clause 3
        raise NestingError("too deep")
    if (                                                          # clause 4
        parent_depth >= MAX_NEST_DEPTH - 1
        and child_key in CONTAINER_TRANSFER_KEYS
    ):
        raise NestingError("a container may not be nested this deeply")
    return join, tab
```

**Fix `payloads.py`'s imports and slot key in the same diff** (see "Why `payloads.py` is in THIS task"). At `payloads.py:758-760`, isort `force-single-line` applies:

```python
from courses.builder import NESTABLE_TYPE_KEYS        # unchanged
from courses.models import SpoilerElement             # unchanged
# DELETE: from courses.builder import SPOILER_CHILD_TYPES
```

**Do NOT add `MAX_NEST_DEPTH` / `CONTAINER_TRANSFER_KEYS` here.** Nothing in this task uses them, so ruff reports `F401 imported but unused` on both — and ruff is a Group A gate, so this task's own commit would fail it. Worse, `ruff --fix` would silently delete the very imports Task 5 depends on. Task 5 adds them alongside their first use.

```python
# `None` means SINGLE-SLOT (the only valid id is SpoilerElement.SLOT_ID), NOT
# "missing". Membership is tested BEFORE this lookup, because `None` already
# serves as the not-a-container sentinel.
_CONTAINER_SLOT_KEY = {"tabs": "tabs", "two_column": "columns", "spoiler": None}
```

Replace the `parent["type"] == "spoiler"` branch at `payloads.py:774-785` — note this is a **string comparison on a payload dict**, not an `isinstance` check (the `isinstance` form is `builder.resolve_scope`'s, at `builder.py:130`; conflating them sends you to the wrong file) — with the membership two-step. Delete its two rationale comments (`:771-773`, `:776-781`) along with it:

```python
        if parent["type"] not in _CONTAINER_SLOT_KEY:          # membership FIRST
            _err(_("Element '%(el)s' has a parent that is not a container element."),
                 el=el["id"])
        slot_key = _CONTAINER_SLOT_KEY[parent["type"]]          # then read
        valid_slot_ids = (
            {SpoilerElement.SLOT_ID} if slot_key is None
            else {s["id"] for s in parent["data"][slot_key]}
        )
```

Leave the existing one-level depth check (`if parent["parent"] is not None`) in place for now — Task 5 replaces it with the chain walk.

Point the LAL loader at its own constant (`courses/lal_loader/builders.py:95-115`) so deleting `SPOILER_CHILD_TYPES` does not widen it — see Task 2 for the test:

```python
# The LAL corpus's permitted spoiler children. Deliberately NARROWER than
# builder.NESTABLE_TYPE_KEYS: this is a one-time import tool for a fixed corpus,
# and widening the gate would silently change what a re-run accepts.
LAL_SPOILER_CHILD_TYPES = frozenset({
    "text", "math", "image", "video", "iframe", "table", "gallery", "callout",
    "reveal_gate", "fill_gate", "switch_gate", "switch_grid", "fill_blank",
    "fill_table",
})
```
…then **delete the function-local import at `:95`** (`from courses.builder import SPOILER_CHILD_TYPES`, inside the spoiler branch) and replace the two usages at `:111` and `:115` with `LAL_SPOILER_CHILD_TYPES`. There are **three** references, not two — leaving `:95` in place makes every nested-spoiler LAL import raise `ImportError`, and Task 2's test would then fail with `ImportError` instead of the `LoaderError` it asserts.

Put the new constant at module scope **before** `build_element`. The longer name pushes `:111` past 88 columns, so rewrap the condition or ruff E501 fails.

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest courses/tests/test_nesting_rule.py --verbosity=0
```
Expected: PASS.

- [ ] **Step 5: Invert the guardrail tests found in Task 0**

Work from the reconciled list, not from memory. At minimum:

| Site | Action |
|---|---|
| `courses/tests/test_spoiler_nesting.py:8` | **`from courses.builder import SPOILER_CHILD_TYPES` at MODULE scope.** Deleting the constant makes this a **collection-time `ImportError`** that takes the whole file down — louder and earlier than the in-body edits below, and invisible to a usage-pattern grep. Repoint to `NESTABLE_TYPE_KEYS`. |
| `tests/test_twocolumn_registry.py:15` | `not in` → `in`; **rename** `test_two_column_not_nestable_itself` |
| `tests/test_twocolumn_registry.py:16` | **leave unchanged** — pins the form-key/transfer-key split |
| `tests/test_twocolumn_registry.py:48` | `"tabs"` case → accept; `"choicequestion"` stays reject; rename |
| `tests/test_tabs_form_views.py:119-131` | tabs-in-tabs now SUCCEEDS (`data=""` hits `clean_data`'s MIN_TABS default); rename |
| `courses/tests/test_spoiler_nesting.py:~149` | reject tuple → `("choicequestion",)`; add accepts for `tabs`/`spoiler` |
| `courses/tests/test_spoiler_nesting.py:163-165` | The **positive** half (`assert k in SPOILER_CHILD_TYPES`) swaps constant cleanly. The **negative** half at `:164-165` (`for k in ("tabs", "two_column", "spoiler"): assert k not in …`) does NOT: all three are now members, so a mechanical swap produces a failing assertion. Replace the negative tuple with genuinely non-nestable types — `("choicequestion", "slidebreak")` — and assert the three container keys are now **present**. |
| `courses/tests/test_spoiler_nesting.py:~190`, `:210-224` | both invert to accepts; rename |
| `tests/test_tabs_registry.py:71-79` — `test_nested_add_of_a_blocked_type_is_400`, parametrized over `choicequestion` / `slidebreak` / **`tabs`** | The `{"type": "tabs"}` param POSTs to `manage_element_add` and asserts **400**; once `tabs` joins `NESTABLE_TYPE_KEYS` the add returns 200. Move that param to an accept case; `choicequestion` and `slidebreak` stay blocked. Rename the test. **This site was found only by applying the diff and running the suite** — it asserts a bare `status_code == 400` and mentions no constant, no exception and no card, so every grep in Task 0 Step 4 misses it. |

- [ ] **Step 5b: Invert the two transfer guardrails THIS task's widening flips**

The allowlist widening changes import validity immediately, before Task 5 touches the depth logic. Both of these go red at this task's commit unless inverted here:

| Site | Why it flips now |
|---|---|
| `tests/test_tabs_transfer.py` — the tabs-in-tabs reject case | Parent is a **top-level** tabs element, so the surviving one-level check (`parent["parent"] is not None`) passes; `tabs` is now in `NESTABLE_TYPE_KEYS`; the slot id is valid. The document becomes VALID. Move it to the accept test. |
| `courses/tests/test_spoiler_transfer.py:141-160` — `test_validate_nesting_rejects_container_spoiler_child` | Same shape: a `tabs` child of a **top-level** spoiler. Valid as of this task. Invert and rename; rewrite the `:142-143` comment. |

**Not yet:** `test_spoiler_transfer.py:114-138`'s depth-2 half and `test_tabs_transfer.py:135` (`# depth > 1`) both stay **rejected** after this task — the first by the surviving one-level check, the second by the new not-a-container rule — so they remain green here and are handled in Task 5.

- [ ] **Step 6: Run the affected files and the full suite**

```bash
uv run pytest courses/tests/test_spoiler_nesting.py tests/test_twocolumn_registry.py \
              tests/test_tabs_form_views.py courses/tests/test_nesting_rule.py --verbosity=0
uv run pytest --verbosity=0
```

- [ ] **Step 7: Verify the named mutants RED**

Every test in this task's file gets a row. `(…)` in a node id means the parametrized variants.

| Mutant | Node id that must FAIL |
|---|---|
| `builder.MAX_NEST_DEPTH` `3 → 4` | `courses/tests/test_nesting_rule.py::test_container_child_rejected_at_depth_2` |
| delete the clause-4 branch | `…::test_container_child_rejected_at_depth_2` |
| delete `"twocolumn"` from `_NESTABLE_FORM_KEY_ALIASES` | `…::test_container_child_accepted_at_depth_1[twocolumn]` |
| add a 4th key to `CONTAINER_TRANSFER_KEYS` only | `…::test_container_key_spaces_do_not_drift` |
| revert the `getattr` at the registry call site | `…::test_spoiler_accepts_a_spoiler_child` (expect `AttributeError`) |
| `element_depth` → `return 1` unconditionally | `…::test_element_depth_counts_hops` |
| clause 3 `>=` → `>` | `…::test_leaf_child_rejected_at_depth_3` |
| delete clause 3 entirely | `…::test_leaf_child_rejected_at_depth_3` |
| clause 3 written `parent_depth >= MAX_NEST_DEPTH - 1` (off-by-one tightening) | `…::test_leaf_child_accepted_at_depth_2` |
| clause 4 written `parent_depth >= MAX_NEST_DEPTH - 2` (off-by-one tightening) | `…::test_container_child_accepted_at_depth_1[tabs]` and `[spoiler]` |

The last two rows exist because the **accept** cases would otherwise have no killing mutant: `MAX_NEST_DEPTH 3 → 4` and the clause deletions all leave them green. Worse, `test_leaf_child_accepted_at_depth_2` passes on the **unmodified** tree too (today's `resolve_scope` applies no depth check to a tabs parent), so without an off-by-one mutant it guards nothing — despite being the plan's stated "what makes depth 3 real" assertion.
| restore `isinstance(parent_obj, SpoilerElement)`'s `if join.parent_id is not None: raise` guard | `…::test_nested_spoiler_may_have_children` |
| remove `"twocolumn": "two_column"` from the aliases | `…::test_twocolumn_form_key_alias_exists` |

**`test_element_depth_terminates_on_a_cycle` is EXEMPT and must be marked so in the test docstring.** Its only natural mutant — unbounding `element_depth`'s `while` — **hangs**, and `pytest-timeout` is not installed, so it can never be verified RED; attempting it wedges the run. The bound is instead exercised indirectly by the delete-cycle test in Task 3, whose collector mutant raises `RecursionError` rather than looping.

For each row: apply, `uv run pytest <node-id> --verbosity=0`, confirm FAIL, revert.

- [ ] **Step 8: Commit**

```bash
git add courses/builder.py courses/transfer/payloads.py courses/lal_loader/builders.py \
        courses/tests/test_nesting_rule.py \
        tests/test_twocolumn_registry.py courses/tests/test_spoiler_nesting.py \
        tests/test_tabs_form_views.py tests/test_tabs_registry.py \
        tests/test_tabs_transfer.py courses/tests/test_spoiler_transfer.py
git commit -m "feat(nesting): one containment rule, depth 3, containers at depth 1-2"
```

---

## Task 2: LAL loader gate keeps its narrow constant

**Files:**
- Test: `tests/lal_import/test_loader_spoiler_gate.py` (create)

The gate is currently **untested** — its message `"not allowed inside a spoiler"` appears nowhere in the suite, so nothing signals if Task 1 widened it by mistake.

**Interfaces:** Consumes `LAL_SPOILER_CHILD_TYPES` from Task 1.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from courses.lal_loader.builders import LoaderError, build_element


@pytest.mark.django_db
def test_spoiler_gate_rejects_a_type_the_wider_allowlist_would_admit():
    """`mark_done` is in NESTABLE_TYPE_KEYS but NOT in the LAL corpus's narrow set.

    It must be a type the loader CAN build (builders.py:299) -- an unknown type
    would raise LoaderError from the unknown-type fallthrough at builders.py:392
    whether or not the gate fired, making the assertion vacuous. Asserting the
    MESSAGE, not just the class, is what makes this lethal.
    """
    spoiler_dict = {
        "type": "spoiler",
        "label": "Hint",
        "elements": [{"type": "mark_done", "prompt": "x", "items": ["a"]}],
    }
    with pytest.raises(LoaderError) as exc:
        build_element(course, unit, spoiler_dict, source_root=..., source_dir=...,
                      allow_html=False)
    assert "not allowed inside a spoiler" in str(exc.value)
```

Read `build_element`'s real signature and the existing `tests/lal_import/` fixtures before writing — do not invent helpers.

- [ ] **Step 2: Run — expect PASS immediately** (Task 1 preserved the narrow constant). This is a characterization test locking in behaviour that had no guard.

- [ ] **Step 3: Verify the mutant RED**

Mutant: repoint the gate at `builder.NESTABLE_TYPE_KEYS` (the naive widening the spec rejects).
Node id: `tests/lal_import/test_loader_spoiler_gate.py::test_spoiler_gate_rejects_a_type_the_wider_allowlist_would_admit`
Expected under mutant: FAIL (the build succeeds, no `LoaderError`).

- [ ] **Step 4: Commit**

```bash
git add tests/lal_import/test_loader_spoiler_gate.py
git commit -m "test(lal): guard the spoiler child-type gate that had no test"
```

---

## Task 3: Delete path — recursive subtree collection

**Files:**
- Modify: `courses/builder.py` — add `_collect_subtree_pks`, rewrite `delete_element:402-419` and the tab-removal branch `:665-672`
- Test: `courses/tests/test_delete_subtree.py` (create)

**Interfaces:**
- Produces: `builder._collect_subtree_pks(roots) -> set[int]` — root-INCLUSIVE, descends `join.children`, `seen`-guarded, recursive.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from courses import builder
from courses.models import Element, TextElement


@pytest.mark.django_db
def test_deleting_a_container_removes_grandchild_concretes():
    """Depth-3 subtree: tabs > spoiler > text. The text concrete is reachable only
    through the GFK, which DB cascade cannot traverse."""
    # build tabs > spoiler > text, capture the text concrete's pk
    builder.delete_element(course, tabs_join.pk, unit_token)
    assert not TextElement.objects.filter(pk=text_pk).exists()


@pytest.mark.django_db
def test_delete_collects_a_child_whose_tab_id_matches_no_slot():
    """resolved_tabs() runs the DESTRUCTIVE normalize_data and SKIPS children whose
    tab_id resolves to no slot. The collector must descend join.children instead, or
    this child's concrete orphans -- a REGRESSION vs today's filter(parent=el)."""
    # create a child with tab_id="nosuchslot" directly through the ORM
    builder.delete_element(course, tabs_join.pk, unit_token)
    assert not TextElement.objects.filter(pk=orphan_pk).exists()


@pytest.mark.django_db
def test_removing_a_tab_keeps_sibling_tab_content():
    """Two assertions. The second is what catches the wrong collection root:
    rooting at the tabs join sweeps KEPT tabs' descendants too, leaving live
    Element rows pointing at deleted concretes -- silent destruction, no error."""
    # FIXTURE: tab A: spoiler > text_a  |  tab B: spoiler > text_b
    #
    # ACT -- this is the test's action, not scaffolding, and it is the hard part:
    # save_element must receive a `data` payload that DROPS one tab id and keeps the
    # other, so that `old_ids - new_ids` is non-empty at builder.py:667. Read
    # save_element's real signature and tests/test_tabs_form_views.py's `_post`
    # helper before writing this; the shape is roughly:
    #
    #   builder.save_element(
    #       course, unit.pk, "tabs", str(tabs_join.pk),
    #       {"data": json.dumps({"tabs": [kept_tab]}),
    #        "unit_token": unit.updated.isoformat()},
    #       {},
    #   )
    #
    # Two of this task's five mutants are unverifiable until this call is right.
    assert not TextElement.objects.filter(pk=text_a_pk).exists()   # removed tab
    assert TextElement.objects.filter(pk=text_b_pk).exists()       # KEPT tab


@pytest.mark.django_db
def test_delete_terminates_on_a_parent_cycle():
    """The one genuinely reachable cycle: delete_element starts from a
    request-supplied element_pk, so an element inside a corrupt cycle IS reachable
    (unlike the export walk, which starts from parent__isnull=True roots)."""
    # ORM-build A.parent=B, B.parent=A
    builder.delete_element(course, a.pk, unit_token)   # must not hang or RecursionError
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_delete_subtree.py --verbosity=0
```
Expected: FAIL — grandchild/unmatched-slot concretes survive.

- [ ] **Step 3: Implement**

```python
def _collect_subtree_pks(roots):
    """Join pks of `roots` plus every descendant, ROOT-INCLUSIVE.

    Descends `join.children` -- every child row, container or not, matched slot or
    not. Deliberately NOT the slot accessors the export walk uses: resolved_tabs()
    runs the destructive normalize_data and skips children whose tab_id matches no
    slot. Export omits those on purpose; delete must not, or their concretes orphan.

    RECURSIVE and `seen`-guarded, not an iterative worklist: dropping the guard from
    a recursive walk raises RecursionError on a cycle, which a test can assert,
    whereas an iterative worklist would spin forever (pytest-timeout is not
    installed, so a hanging mutant can never be verified RED).

    Returns pks, not instances, so callers can hand
    _delete_element_content_objects a QuerySet -- it requires one
    (it calls .prefetch_related). Deletion ORDER is irrelevant: the prefetch
    materialises every row before the first delete fires.
    """
    seen = set()

    def walk(join):
        if join.pk in seen:
            return
        seen.add(join.pk)
        for child in join.children.all():
            walk(child)

    for root in roots:
        walk(root)
    return seen
```

`delete_element` — replace `:411-416`:

```python
    pks = _collect_subtree_pks([el])
    _delete_element_content_objects(Element.objects.filter(pk__in=pks))
    # Unconditional: the collector is root-inclusive, so this element's concrete --
    # and, via its GenericRelation cascade, this join row -- is already gone. The old
    # `if obj is not None` branch is therefore dead. A 0-row DELETE in the normal
    # case; it does real work only when the root carried no concrete at all.
    el.delete()
```

Tab removal — replace `:670-672`:

```python
            if removed:
                doomed = list(
                    Element.objects.filter(parent=join, tab_id__in=removed)
                )
                # Root at each DOOMED CHILD, never at `join`: rooting at the tabs
                # element would sweep KEPT tabs' descendants, whose join rows survive
                # (the delete below is tab_id__in=removed only) -- live rows pointing
                # at deleted concretes.
                pks = _collect_subtree_pks(doomed)
                _delete_element_content_objects(Element.objects.filter(pk__in=pks))
                Element.objects.filter(parent=join, tab_id__in=removed).delete()
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest courses/tests/test_delete_subtree.py --verbosity=0
uv run pytest --verbosity=0
```

- [ ] **Step 5: Verify the named mutants RED**

| Mutant | Node id that must FAIL |
|---|---|
| `builder.py` → `_delete_element_content_objects(Element.objects.filter(parent=el))` (one level) | `::test_deleting_a_container_removes_grandchild_concretes` |
| collector descends `resolved_tabs()`/`resolved_children()` instead of `join.children` | `::test_delete_collects_a_child_whose_tab_id_matches_no_slot` |
| tab removal without the subtree walk | `::test_removing_a_tab_keeps_sibling_tab_content` |
| root the tab-removal collection at `join` | `::test_removing_a_tab_keeps_sibling_tab_content` (the KEPT-tab assertion) |
| remove the `seen` guard from `_collect_subtree_pks` | `::test_delete_terminates_on_a_parent_cycle` (expect `RecursionError`) |

- [ ] **Step 6: Commit**

```bash
git add courses/builder.py courses/tests/test_delete_subtree.py
git commit -m "fix(nesting): delete whole subtrees so depth-3 concretes cannot orphan"
```

---

## Task 4: Export walk recursion (fixes silent Duplicate-Unit data loss)

**Files:**
- Modify: `courses/transfer/export.py:473-500` (`walk_unit_joins`)
- Test: `tests/test_export_depth3.py` (create)

This is the highest-severity item: `duplicate_unit` runs through `build_export`, so today a duplicated unit **silently loses** depth-3 content with no error.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.django_db
def test_duplicate_unit_keeps_depth_3_content():
    """tabs > spoiler > table. Today the table VANISHES from the copy, silently."""
    new_node = builder.duplicate_unit(course, unit.pk, token=unit.updated.isoformat())
    # assert the copied tree contains the table at depth 3


@pytest.mark.django_db
def test_round_trip_preserves_within_slot_sibling_order():
    """The fixture MUST place at least TWO siblings in the same NESTED slot -- with
    one leaf in one spoiler in one tab, `reversed(children)` is a no-op and the
    mutant is vacuous."""
    # tabs > spoiler > [text_a, text_b]  (two siblings in the SPOILER's slot)
    # export, import, assert the spoiler's children order is still [a, b]


@pytest.mark.django_db
def test_export_does_not_keyerror_on_forward_reference():
    """export.py:559's walk_index_by_join_pk[parent_join.pk] is an UNGUARDED dict
    lookup. Parents-before-children is required by the EXPORT side (the importer is
    explicitly order-robust)."""
    # a depth-3 tree exports without raising
```

- [ ] **Step 2: Run to verify they fail** — expect the duplicate test to fail with the depth-3 element missing.

- [ ] **Step 3: Implement**

Make each of the three existing per-type arms recurse, carrying a `seen` set:

```python
def walk_unit_joins(unit_pk, joins_by_unit):
    """Yield (join, parent_join_or_None, tab_id) for one unit, PARENTS BEFORE
    CHILDREN, each element exactly once.

    Recurses through each container arm and terminates on a `seen` set. NOT
    registry-driven -- _CONTAINER_REGISTRY is model-keyed, lives in builder.py and
    is imported nowhere here; making this registry-driven would re-introduce the
    traversal unification this slice deliberately descoped.

    Children are reached ONLY through resolved_tabs()/resolved_columns()/
    resolved_children(), never join.children.all(): a child whose tab_id matches no
    slot is deliberately OMITTED, because exporting it would produce a payload the
    import validator rejects. (The DELETE path differs and must use join.children --
    see builder._collect_subtree_pks.)

    Parents-before-children is an EXPORT-side requirement: build_export's
    walk_index_by_join_pk[parent_join.pk] lookup is unguarded and KeyErrors on a
    forward reference. The importer itself is order-robust.

    The `seen` set is defence for a future non-root entry point, not a live hang:
    this walk starts from parent__isnull=True roots and Element.parent is a
    single-valued FK, so every node in a cycle has a non-null parent, is never a
    root, and the reachable subgraph is acyclic by construction.
    """
    seen = set()

    def emit(join, parent_join, slot_id):
        if join.pk in seen:
            return
        seen.add(join.pk)
        yield join, parent_join, slot_id           # parent BEFORE children
        obj = join.content_object
        if isinstance(obj, TabsElement):
            for tab, children in obj.resolved_tabs():
                for child in children:
                    yield from emit(child, join, tab["id"])
        elif isinstance(obj, TwoColumnElement):
            for col, children in obj.resolved_columns():
                for child in children:
                    yield from emit(child, join, col["id"])
        elif isinstance(obj, SpoilerElement):
            for child in obj.resolved_children():
                yield from emit(child, join, SpoilerElement.SLOT_ID)

    for join in joins_by_unit.get(unit_pk, []):
        yield from emit(join, None, "")
```

- [ ] **Step 4: Run to verify they pass**, then the full suite.

- [ ] **Step 5: Verify the named mutants RED**

| Mutant | Node id that must FAIL |
|---|---|
| drop the recursive descent (yield one level only) | `::test_duplicate_unit_keeps_depth_3_content` |
| `for child in reversed(children)` in the slot descent | `::test_round_trip_preserves_within_slot_sibling_order` |
| move the parent `yield` to AFTER the slot descent | `::test_export_does_not_keyerror_on_forward_reference` |

**A BFS/level-order reordering is NOT a valid mutant** — it preserves relative sibling order, so the round trip stays byte-identical and the test would stay green.

- [ ] **Step 6: Commit**

```bash
git add courses/transfer/export.py tests/test_export_depth3.py courses/tests/test_nesting_rule.py
git commit -m "fix(transfer): recurse the export walk so duplicate-unit keeps depth-3 content"
```

---

## Task 5: Import validator — hop-bounded chain walk

**Files:**
- Modify: `courses/transfer/payloads.py` — `validate_nesting`'s depth check only, plus messages `:797/:805` and the new clause-4 message. (`_CONTAINER_SLOT_KEY` and `:784` were Task 1's.)
- Test: `tests/test_transfer_nesting_depth.py` (create)
- Modify (invert): `tests/test_tabs_transfer.py`, `courses/tests/test_spoiler_transfer.py`

- [ ] **Step 1: Write the failing tests**

**First define the payload helpers — the existing ones cannot build a nested container.** `tests/test_tabs_transfer.py:105-121` has `_els(*items)`, `_tabs_el(eid="e1", tabs=None)` and `_child(eid, parent, tab, type_)`, but `_tabs_el` hard-codes `"parent": None, "tab": ""` and takes no `parent`/`tab` kwargs. Add to the new file:

```python
from tests.test_tabs_transfer import _child, _els   # reuse; do NOT redefine

_SLOTS = [{"id": "taaaaaa"}, {"id": "tbbbbbb"}]     # must match _child's default tab


def _tabs(eid, parent=None, tab=_SLOTS[0]["id"]):
    """A tabs element that can itself be nested. `_tabs_el` cannot: it pins
    parent=None/tab="".

    `tab` defaults to a REAL slot id, not "". A nested element carries its own
    `tab`, and validate_nesting checks the slot BEFORE the depth clauses -- so
    `_tabs("b", parent="a")` with tab="" raises "references a slot its parent does
    not have" on element b, and element c/d never reach clause 3 or 4 at all. That
    made both depth tests assert the wrong message. Verified by executing the
    validator against these documents.
    """
    return {
        "id": eid, "type": "tabs", "parent": parent, "tab": tab if parent else "",
        "data": {"tabs": [dict(s, label=f"T{i}") for i, s in enumerate(_SLOTS)]},
    }
```

Confirm `_child`'s default `tab` against the real helper before relying on `_SLOTS`. A top-level `_tabs("a")` must carry `tab=""` (hence the `if parent` guard); a nested one must carry a real slot id.

Four cases. **Each asserts the specific message** — without that, the clause-3 and clause-4 mutants are indistinguishable and both vacuous.

```python
def test_depth_4_parents_first_reports_the_container_clause():
    """Parents-first ordering examines the depth-3 container before its child, so
    CLAUSE 4 fires."""
    doc = _els(_tabs("a"), _tabs("b", parent="a"), _tabs("c", parent="b"),
               _child("d", parent="c"))
    with pytest.raises(TransferError) as exc:
        validate_nesting(doc)
    assert "container" in str(exc.value)


def test_depth_4_child_before_parent_reports_the_depth_clause():
    """Child-before-parent ordering reaches D first, whose parent C is already at
    depth 3, so CLAUSE 3 fires and clause 4 never runs. Both clauses are reachable;
    which one fires is payload-order dependent."""
    doc = _els(_tabs("a"), _tabs("b", parent="a"),
               _child("d", parent="c"), _tabs("c", parent="b"))
    with pytest.raises(TransferError) as exc:
        validate_nesting(doc)
    assert "too deeply" in str(exc.value)


def test_parent_cycle_raises_rather_than_hanging():
    """Asserts the exception TYPE only, deliberately: a hop-bounded walk reports a
    cycle as a too-deep parent, emitting the same clause-3 message an ordinary
    depth-4 archive does. Distinguishing them would need the unbounded traversal the
    bound exists to avoid."""
    doc = _els(_tabs("a", parent="b"), _tabs("b", parent="a"))
    with pytest.raises(TransferError):
        validate_nesting(doc)


def test_missing_ancestor_mid_walk_names_the_element_under_validation():
    """Asserting the interpolated id is the ONLY thing that makes this lethal: a
    .get()-based walk still rejects the archive with the same message when the loop
    reaches B, so a test asserting merely 'TransferError mentioning unknown parent'
    stays green under that mutant."""
    doc = _els(_child("c", parent="b"), _tabs("b", parent="ghost"))
    with pytest.raises(TransferError) as exc:
        validate_nesting(doc)
    assert "'c'" in str(exc.value)        # the element under validation, not 'b'
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement**

**The structural edits already landed in Task 1** — the `"spoiler": None` slot key, the membership two-step that replaced the `parent["type"] == "spoiler"` branch, and the deletion of the `:784` spoiler msgid along with it. **Do not re-apply any of those here**: pasting the membership block again emits a second copy of it and of `valid_slot_ids`, and hunting for a `:784` message that no longer exists wastes the step. If those do not exist, Task 1 was not completed — stop rather than re-doing it.

**Add the two imports this step needs**, at `payloads.py`'s `validate_nesting`-local import block (isort `force-single-line`). Task 1 deliberately left them out: nothing there used them, so ruff would have flagged `F401` on that task's own commit.

```python
from courses.builder import CONTAINER_TRANSFER_KEYS   # NEW -- clause 4
from courses.builder import MAX_NEST_DEPTH            # NEW -- the hop bound
```

This step changes **one thing**: replace the surviving one-level check (`if parent["parent"] is not None`) with the hop-bounded chain walk and clauses 3/4, immediately after the `valid_slot_ids` assignment Task 1 left in place:

```python
        # Hop-bounded chain walk. NOT `while ... is not None`: a corrupt archive with
        # a parent cycle would hang the import worker.
        depth, node = 1, parent
        while node is not None and depth <= MAX_NEST_DEPTH:
            depth += 1
            ref = node["parent"]
            if ref is None:
                break
            node = by_id.get(ref)
            if node is None:
                # Mid-walk dangling ancestor. Bound to the element UNDER VALIDATION
                # (matching the immediate-parent check's convention), which is what
                # lets a test distinguish this raise from that one.
                _err(_("Element '%(el)s' references an unknown parent."), el=el["id"])

        if depth > MAX_NEST_DEPTH:                              # clause 3
            _err(_("Element '%(el)s' is nested too deeply."), el=el["id"])
        if depth >= MAX_NEST_DEPTH and el["type"] in CONTAINER_TRANSFER_KEYS:
            _err(_("Element '%(el)s' is a container and may not be nested this "
                   "deeply."), el=el["id"])                     # clause 4
        if el["tab"] not in valid_slot_ids:
            _err(_("Element '%(el)s' references a slot its parent does not have."),
                 el=el["id"])
        if el["type"] not in NESTABLE_TYPE_KEYS:
            _err(_("Element '%(el)s' may not be nested."), el=el["id"])
```

Reword the two surviving messages exactly as the spec's message table specifies — `:797` becomes the clause-3 "nested too deeply" and `:805` becomes the generic "may not be nested" — and add the new clause-4 message. **The spoiler-specific msgid at `:784` was already deleted in Task 1** with the branch that raised it; do not look for it.

- [ ] **Step 4: Run to verify they pass.**

- [ ] **Step 5: Invert the transfer guardrails**

| Site | Action |
|---|---|
| `tests/test_tabs_transfer.py:135` (`# depth > 1`) | Its middle element is **text**, so it is still rejected — by "parent is not a container", not by depth. Rebuild with a **container** middle element, or retire in favour of the new clause tests. |
| `tests/test_tabs_transfer.py` tabs-in-tabs reject case | Now VALID; move to the accept test. |
| `courses/tests/test_spoiler_transfer.py:114-138` | depth-2 half inverts (transfer-side twin of Purpose bullet 3); rename. |
| `courses/tests/test_spoiler_transfer.py:141-160` | tabs-child-of-spoiler now legal; rename; rewrite the `:142-143` comment. |

- [ ] **Step 6: Verify the named mutants RED**

| Mutant | Node id that must FAIL |
|---|---|
| delete the clause-4 branch | `::test_depth_4_parents_first_reports_the_container_clause` |
| delete the clause-3 branch | `::test_depth_4_child_before_parent_reports_the_depth_clause` |
| replace the hop-bounded loop with an unbounded **recursive** helper | `::test_parent_cycle_raises_rather_than_hanging` (expect `RecursionError`) |
| raw `by_id[ref]` subscript instead of the guarded `.get` | `::test_missing_ancestor_mid_walk_names_the_element_under_validation` (expect `KeyError`) |

**Forbidden mutants:** `while parent is not None` (hangs — no pytest-timeout) and raising the bound to a large finite number (still terminates, still raises → vacuous).

- [ ] **Step 7: Commit**

```bash
git add courses/transfer/payloads.py tests/test_transfer_nesting_depth.py \
        tests/test_tabs_transfer.py courses/tests/test_spoiler_transfer.py
git commit -m "feat(transfer): hop-bounded depth walk in the import validator"
```

---

## Task 6: `has_html` becomes depth-agnostic (both context builders)

**Files:**
- Modify: `courses/views.py:51` (import), `:328` (`html_ct_id`), `:346` (lesson), `:1198` (quiz)
- Test: `tests/test_has_html_nested.py` (create)

A **pre-existing** defect this slice widens: the HTML card sits in the Content group, *outside* `{% if not unit_is_quiz %}`, so nested HTML is authorable in both lessons and quizzes today and neither loads `html_element.js`.

- [ ] **Step 1: Write the failing tests** — both use an **isolated** unit whose ONLY html element is nested, or they pass vacuously.

```python
@pytest.mark.django_db
def test_lesson_with_only_nested_html_loads_the_bundle():
    # tabs > html, and NO top-level html anywhere in the unit
    assert "html_element.js" in response.content.decode()


@pytest.mark.django_db
def test_quiz_with_only_nested_html_loads_the_bundle():
    # same shape in a QUIZ unit -- views.py:1198 is a separate code path
    assert "html_element.js" in response.content.decode()
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** — both sites become flat queries; delete `html_ct_id` (`:328`) and the `HtmlElement` import (`:51`), which has exactly those two consumers and will otherwise trip ruff F401/F841:

```python
    # Flat unit-wide (NOT parent__isnull=True) so an html element nested in a tab,
    # column or spoiler still arms html_element.js -- children keep their own `unit`
    # FK. Matches every sibling has_* flag. app_label-pinned like
    # has_stateful_elements, to avoid cold-cache ContentType SELECTs.
    has_html = node.elements.filter(
        content_type__app_label="courses", content_type__model="htmlelement"
    ).exists()
```

- [ ] **Step 4: Run to verify they pass**, then `uv run ruff check .` (must be clean — this is where a forgotten import surfaces).

- [ ] **Step 5: Verify the named mutants RED**

| Mutant | Node id that must FAIL |
|---|---|
| `views.py:346` → same filter `+ parent__isnull=True` | `::test_lesson_with_only_nested_html_loads_the_bundle` |
| `views.py:1198` → same filter `+ parent__isnull=True` | `::test_quiz_with_only_nested_html_loads_the_bundle` |

**Do not** write these as "restore the pre-change expression" — both reference `HtmlElement`, whose import is now deleted, so a verbatim restore raises `NameError` on every render. That is noise, and it would be recorded "verified RED" while proving nothing.

- [ ] **Step 6: Check the query-count test**

`tests/test_html_element.py::test_lesson_html_render_query_count_invariant` asserts a **relative** invariant (`len(q3) == len(q1)`), so one extra constant query does not disturb it. Confirm it still passes; if its ContentType warm-up comment references `get_for_model(HtmlElement)` on a path this removed, update the comment.

- [ ] **Step 7: Commit**

```bash
git add courses/views.py tests/test_has_html_nested.py tests/test_html_element.py
git commit -m "fix(lesson): arm html_element.js for nested html elements"
```

---

## Task 7: Depth-3 characterization — `has_math` and student render

**Files:**
- Test: `tests/test_depth3_render.py` (create). **No production change.**

- [ ] **Step 1: Write the tests**

```python
@pytest.mark.django_db
def test_has_math_detects_math_at_depth_3():
    """Pinned chain: tabs > spoiler > math, with NO other math in the unit.
    Isolation is mandatory -- a unit with top-level math passes either way."""
    assert build_lesson_context(node, user)["has_math"] is True


@pytest.mark.django_db
def test_depth_3_leaf_renders_inside_its_nested_container():
    """EXEMPT from the mutant rule, deliberately: the render path is unchanged by
    this slice, so this is a characterization test pinning existing behaviour at a
    new depth, not a test of new logic."""
    assert "the leaf's marker text" in rendered
```

- [ ] **Step 2: Run — expect PASS** (`_element_has_math` already recurses; this pins it at depth 3).

- [ ] **Step 3: Verify the `has_math` mutant RED**

Mutant: replace **`_tabs_has_math`'s terminal `return any(...)` expression** (`courses/views.py`, the multi-line `return any(_element_has_math(child.content_object) for child in join.children…)`) with `return False`. **Cite the symbol, not a line range** — the expression spans four lines and is preceded by two other `return False` statements (the `isinstance` and `join is None` guards), so any range that splits it leaves an orphaned `)` and a `SyntaxError`. A `SyntaxError` "verified RED" proves nothing.
Node id: `tests/test_depth3_render.py::test_has_math_detects_math_at_depth_3`
**Not** `views.py:202` — the pinned chain passes through it, but that is the *spoiler* dispatch, not the tabs recursion this must prove reaches depth 3.

The render test carries no mutant (marked exempt above).

- [ ] **Step 4: Commit**

```bash
git add tests/test_depth3_render.py courses/tests/test_nesting_rule.py
git commit -m "test(nesting): pin has_math and student render at depth 3"
```

---

## Task 8: Editor templates — depth threading and the add-menu

The largest task and the one that decides whether the feature is reachable at all. **An implementer who only hides cards at depth 2 satisfies every other sentence in the spec and ships a UI no-op.**

**Files:**
- Modify: `courses/views_manage.py` — `_render_editor_fragments` (~`:1244-1272`) AND `_editor_page` (~`:1275-1298`)
- Modify: `templates/courses/manage/editor/_editor_scope.html:11,15`
- Modify: `templates/courses/manage/editor/_element_row.html` — `:80/:85`, `:126/:131`, `:136`, `:168/:177`
- Modify: `templates/courses/manage/editor/_add_menu.html` — `:20,24,25,35,36,37,38,39`
- Test: `tests/test_editor_depth.py` (create)
- Modify: the five direct-render sites; invert `tests/test_tabs_editor_partial.py:79-90`

- [ ] **Step 1: Write the failing tests**

**Every menu assertion MUST name its render scope, or it is vacuous or wrong.** `_editor_scope.html:15` unconditionally renders the **top-level** menu, which after this task still emits all three container cards (depth 0 < 2). So on a whole-page or fragment render:

- a *negative* assertion (`'data-add-type="tabs"' not in html`) **fails against a correct implementation** — the top-level card is always there;
- a *positive* assertion **passes no matter what the nested menu emits**, including under its own named mutant.

Use one of these two scopes for every test below, and say which in the test:

1. `render_to_string("courses/manage/editor/_add_menu.html", {"nested": True, "depth": 2, "max_nest_depth": 3, ...})` — renders exactly one menu; or
2. slice the target menu out of the page first, reusing `courses/tests/test_spoiler_nesting.py`'s existing `_spoiler_menu_block(html, join.pk)` helper, which exists for precisely this reason.

```python
@pytest.mark.django_db
def test_top_level_menu_still_offers_containers():
    """The depth-SEEDING regression. An unseeded `depth` resolves to '' and smartif
    swallows the TypeError, so every predicate is False and the cards vanish from
    the TOP-LEVEL menu -- silently."""
    assert 'data-add-type="tabs"' in html


@pytest.mark.django_db
def test_depth_1_nested_menu_offers_containers():
    """POSITIVE requirement. Use a LESSON unit: the Spoiler card sits inside
    {% if not unit_is_quiz %}.

    SCOPE: assert on the NESTED menu only -- the top-level menu always carries
    these cards, so a whole-page assertion passes under this test's own mutant."""
    menu = _menu_at_depth(html, depth=1)     # or render _add_menu.html directly
    for t in ("tabs", "twocolumn", "spoiler"):
        assert f'data-add-type="{t}"' in menu


@pytest.mark.django_db
def test_depth_2_nested_menu_hides_containers_but_keeps_leaves():
    """SCOPE is mandatory here: on a whole-page render the top-level menu's own
    Tabs card makes the negative assertion fail against a CORRECT implementation."""
    menu = _menu_at_depth(html, depth=2)     # or render _add_menu.html directly
    assert 'data-add-type="tabs"' not in menu
    assert 'data-add-type="callout"' in menu       # a legal depth-3 LEAF


@pytest.mark.django_db
def test_no_add_menu_inside_a_depth_3_element():
    """The depth-3 container MUST be a TABS element, matching the `:85` mutant.
    _element_row.html includes _add_menu.html at three sites -- :85 (tabs),
    :131 (two-column), :177 (spoiler) -- so a spoiler or two-column fixture would
    leave the named mutant green and this row vacuous.

    ORM-constructed: clause 4 makes a depth-3 container unreachable through
    resolve_scope. Defence in depth -- do not delete as dead."""
    assert "data-add-menu" not in depth3_row_html


@pytest.mark.django_db
def test_nested_spoiler_renders_children_and_menu():
    """A spoiler inside a tab: today it falls to the leaf branch with no children."""


@pytest.mark.django_db
def test_cap_agreement_cards(monkeypatch):
    """Guards must read max_nest_depth, not a literal.

    BRACKET the change: assert the depth-2 menu LACKS the cards at the real cap and
    GAINS them at 4. Asserting only the patched side passes vacuously, because the
    top-level menu satisfies it unconditionally."""
    assert 'data-add-type="tabs"' not in _menu_at_depth(render(), depth=2)
    monkeypatch.setattr("courses.builder.MAX_NEST_DEPTH", 4)
    assert 'data-add-type="tabs"' in _menu_at_depth(render(), depth=2)


@pytest.mark.django_db
def test_cap_agreement_include(monkeypatch):
    """The include guard is the likelier slip -- three sites, not one. Fixture's
    container is a TABS element, matching the :85 mutant."""
    monkeypatch.setattr("courses.builder.MAX_NEST_DEPTH", 4)
    # an add-menu IS emitted inside a depth-3 tabs element


@pytest.mark.django_db
def test_fragment_swap_still_emits_menu_and_cards():
    """Every add/save/move/delete returns through _render_editor_fragments. If
    max_nest_depth lands only in _editor_page the first load looks perfect and every
    later swap silently drops both."""


@pytest.mark.django_db
def test_top_level_lesson_menu_has_exactly_one_fillblank_card():
    """Line 39 becomes {% if nested %}; deleting it outright duplicates line 49's
    card. LESSON fixture -- no duplicate arises in a quiz."""
    assert html.count('data-add-type="fillblankquestion"') == 1
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement — context (both builders)**

In `courses/views_manage.py`, add to **both** context dicts. Read it as a **module attribute** so `monkeypatch.setattr("courses.builder.MAX_NEST_DEPTH", 4)` binds — a `from … import MAX_NEST_DEPTH` would freeze the value at import time and make the cap-agreement tests fail against a correct implementation:

```python
from courses import builder as builder_svc
...
    "max_nest_depth": builder_svc.MAX_NEST_DEPTH,   # module attr, NOT a from-import
```

- [ ] **Step 4: Implement — seeds**

`_editor_scope.html:11` → `{% include "…/_element_row.html" with el=el … depth=1 %}`
`_editor_scope.html:15` → `{% include "…/_add_menu.html" with depth=0 %}`

**Unquoted numeric literals.** `depth="1"` binds a string; `{% if depth < 2 %}` then evaluates False because smartif swallows the `str < int` TypeError — the exact silent-hide failure, with a seed apparently present.

- [ ] **Step 5: Implement — `_element_row.html`**

- `:136` — drop `and el.parent_id is None` from the spoiler branch condition.
- `:80`, `:126`, `:168` (child-row includes) → add `depth=depth|add:1`.
- `:85`, `:131`, `:177` (add-menu includes) → wrap in `{% if depth < max_nest_depth %}` and pass `depth=depth`.
- `:177` — **drop `in_spoiler=True`**; it is the sole producer of a flag whose every consumer is being deleted.
- Rewrite the three "realized depth is always exactly 2" comments (`:68-73`, `:114-119`, `:160-164`) with the real termination argument: the editor enters from `_editor_rows`' `parent__isnull=True` roots and descends only through the resolved-* accessors; since `Element.parent` is single-valued, every node in a cycle has a non-null parent and is never a root, so the reachable subgraph is acyclic by construction. The child-row recursion is deliberately unbounded; only the add-menu include carries the depth guard.

- [ ] **Step 6: Implement — `_add_menu.html`**

| Line | Change |
|---|---|
| 20, 36, 37, 38 | delete `{% if not in_spoiler %}` |
| 24, 25 | `{% if not nested %}` → `{% if depth < max_nest_depth|add:-1 %}` |
| 35 (Spoiler) | `{% if not in_spoiler %}` → the same depth predicate |
| 39 (fill-blank) | `{% if in_spoiler %}` → `{% if nested %}` |
| 2-8 | rewrite the header comment |

Callout (`:23`) stays unguarded — it is a plain leaf in this slice and legal at depth 3.

- [ ] **Step 7: Update the five direct-render sites**

Each must pass explicit **integer** `depth` AND `max_nest_depth`. Omitting `max_nest_depth` is worse than omitting `depth`: it suppresses the add-menu include as well as the cards.

| Site | Note |
|---|---|
| `courses/tests/test_reveal_gate_editor_row.py:46-49` | Future-vacuity insurance only, **not** a required fix: `_render_row` renders a `revealgateelement`, which falls to `_element_row.html`'s `{% else %}` leaf branch (`:180-203`) — no add-menu include, no recursive row include, so no depth predicate is evaluated. Add both keys anyway so a later branch change cannot make it vacuous. |
| `tests/test_tabs_editor_partial.py:70-72` | **will otherwise go RED** — it asserts the nested add-menu IS emitted |
| `tests/test_tabs_editor_partial.py:83-86` | add both |
| `tests/test_gallery_manage.py:26` | renders with no context at all; add both |
| `tests/test_table_manage_plumbing.py:23` | same |

- [ ] **Step 8: Invert the editor guardrails**

- `tests/test_tabs_editor_partial.py:79-90` — `'data-add-type="tabs"' not in html` inverts; must pass both integers.
- `courses/tests/test_spoiler_nesting.py:306-313` — the five banned cards move to allowed; the ten `banned_question` entries at `:315-327` stay banned.
- `courses/tests/test_spoiler_nesting.py:346` — the four become present; `:348-350` unchanged.
- `courses/tests/test_spoiler_nesting.py:394-399` — `fillblankquestion` now present in the tabs menu; rename `test_tabs_add_menu_unaffected`.

- [ ] **Step 9: Run everything**

```bash
uv run pytest tests/test_editor_depth.py courses/tests/test_spoiler_nesting.py \
              tests/test_tabs_editor_partial.py --verbosity=0
uv run pytest --verbosity=0
```

- [ ] **Step 10: Verify the named mutants RED**

| Mutant | Node id that must FAIL |
|---|---|
| delete `depth=1`/`depth=0` from `_editor_scope.html` | `::test_top_level_menu_still_offers_containers` |
| delete the depth predicate on the Tabs card | `::test_depth_2_nested_menu_hides_containers_but_keeps_leaves` |
| restore `and el.parent_id is None` on `:136` | `::test_nested_spoiler_renders_children_and_menu` |
| container-card guard as literal `{% if depth < 2 %}` | `::test_cap_agreement_cards` |
| `_element_row.html:85` as literal `{% if depth < 3 %}` | `::test_cap_agreement_include` |
| delete the depth guard at `:85` | `::test_no_add_menu_inside_a_depth_3_element` |
| omit `max_nest_depth` from `_render_editor_fragments` | `::test_fragment_swap_still_emits_menu_and_cards` |
| `_add_menu.html:39` → delete the guard entirely | `::test_top_level_lesson_menu_has_exactly_one_fillblank_card` |

- [ ] **Step 11: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/ tests/ courses/tests/
git commit -m "feat(editor): thread depth through the row recursion and add-menu"
```

---

## Task 9: Stale comments and docstrings

**Files:** the ten rows below. The spec's stale-comment table has twelve; three are already discharged — `builder.py:58-63` and `payloads.py:771-773`/`:776-781` are deleted outright in Task 1, and `_element_row.html`'s three comment blocks are rewritten in Task 8.

This repo has a test that regexes **raw source including comments**, and an earlier slice already needed a follow-up PR to retarget stale comments.

- [ ] **Step 1: Rewrite each site**

| Site | What becomes false |
|---|---|
| `payloads.py:754-757` | "a parent chain deeper than one level — that depth bound is what lets the editor's recursive row template terminate without a guard" |
| `payloads.py:747-749` | must now document `None` = single-slot and membership-before-lookup |
| `builder.py:404-407` | "If it is a tabs element…" — now every container, every level |
| `builder.py:95-98` | model-key + 3-tuple contract survive, but a single-slot container supplies a constant slot list |
| `builder.py:30-33` | "except the reveal-gate" — already false (eight aliases), worse with `twocolumn` |
| `export.py:473-486` | see Task 4's docstring — **do NOT write "registry-driven"** |
| `export.py:534-536` | "expands each **tabs** element's children inline … no recursive query here" |
| `views_manage.py:1534-1539` | "'tabs' … prove nesting is blocked" — `tabs` is now an accept |
| `_add_menu.html:2-8` | nested menus come from all three containers; hidden set is depth-dependent |
| `_element_row.html:68-73/114-119/160-164` | done in Task 8 Step 5 |

- [ ] **Step 2: Run the full suite** (the comment-regex test is the one to watch).

- [ ] **Step 3: Commit**

```bash
git commit -am "docs(nesting): retarget comments the depth-3 rule invalidates"
```

---

## Task 10: Author-facing help docs (Group B gate)

**Files:** `docs/help/course-admin/content-editors.md`, `content-editors.pl.md`, `interactive-elements.md`, `interactive-elements.pl.md`

- [ ] **Step 1: Rewrite all ten passages** (four files)

| File | Passages |
|---|---|
| `content-editors.md` | `:121-133` (two container types / cannot hold another container), `:123-129` (the "**nine** non-container Content types" enumeration), `:131-133` (the quiz sentence), `:151` (*See also*) |
| `content-editors.pl.md` | twins at `:131-145`, `:133-141`, **`:143-145` — the twin of the EN quiz sentence** ("menu dodawania kontenera Zakładki lub Kolumny oferuje wyłącznie typy treści"), which becomes false because Tabs/Columns cards now appear in nested quiz menus; it needs its **own** replacement sentence, not folding into the general list — and `:166` |
| `interactive-elements.md` | `:9` |
| `interactive-elements.pl.md` | `:10` |

New wording must state: **three** container types (Tabs, Columns, Spoiler); containers admissible at depth 1–2; depth 3 is leaves only; fill-in-the-blanks offered in nested **lesson** menus.

**Two quiz qualifications are load-bearing** — the Spoiler card (`_add_menu.html:35`) and fill-blank card (`:39`) sit inside `{% if not unit_is_quiz %}`, so in a quiz only Tabs and Columns are ever offered and fill-blank is never offered nested. The `:131-133` quiz passage needs its **own** sentence, not folding into the general list.

**The Polish rewrite must avoid the substring `wewnątrz Zakładek`** — e.g. `można je zagnieżdżać w kontenerach: Zakładki, Kolumny i Rozwijana treść.` Appending to the existing phrasing would leave the gate matching and failing on a correct fix.

- [ ] **Step 2: Run the Group B gate — it must now return NOTHING**

```bash
for p in "two container types" "cannot hold another container" "dwa typy kontenerów" \
         "może zawierać innego kontenera" "nestable inside Tabs and Columns" \
         "wewnątrz Zakładek" "zagnieżdżalne w Zakładkach i Kolumnach"; do
  printf '%-42s ' "$p"; grep -rc "$p" docs/help/ | grep -v ':0' | wc -l
done
```
Expected: every line prints `0`.

- [ ] **Step 3: Run the help-docs test suite** (`tests/test_help.py` — the palette oracle and the PL/EN icon-sequence test).

- [ ] **Step 4: Commit**

```bash
git add docs/help/
git commit -m "docs(help): depth-3 nesting and the third container type"
```

---

## Task 11: i18n catalogs

- [ ] **Step 1: Regenerate**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

`--no-obsolete` is mandatory. **Three existing msgids change plus one is added**, and the three old ones are near-identical, which makes them prime fuzzy-match bait for the two new ones:

| msgid | Fate | `.po` lines (en / pl) |
|---|---|---|
| `"Element '%(el)s' may not be nested inside a spoiler."` | **deleted** (Task 1) | 1825 / 1913 |
| `"Element '%(el)s' is nested more than one level deep."` | reworded → clause 3 | 1835 / 1924 |
| `"Element '%(el)s' may not be nested inside a tabs element."` | reworded → generic | 1845 / 1936 |
| *(new)* clause-4 container message | added | — |

- [ ] **Step 2: Translate the new/changed strings** — the reworded clause-3 and generic-nesting messages, plus the new clause-4 message.

- [ ] **Step 3: Compile the catalogs**

```bash
uv run python manage.py compilemessages -l pl -l en
```

`locale/{en,pl}/LC_MESSAGES/django.mo` are **tracked binaries** in this repo, and
`test_i18n_po_health.py` inspects only the `.po` files (its docstring: "Owns every assertion
about the catalogs AS FILES"). Skip this and the three changed validator messages never reach
a Polish runtime, with nothing in the suite noticing. `docs/development/conventions.md:50`
documents this as the repo convention.

- [ ] **Step 4: De-fuzz**

`makemessages` fuzzy-matches new msgids against existing ones and pre-fills **wrong** translations. Clearing one means deleting **two** lines: the `#, fuzzy` line and the `#| msgid` line.

```bash
grep -n "#, fuzzy" locale/*/LC_MESSAGES/django.po      # must return nothing
grep -c "^#~" locale/*/LC_MESSAGES/django.po           # must be 0
uv run pytest tests/test_i18n_po_health.py --verbosity=0
```

- [ ] **Step 5: Commit** (confirm the `.mo` diff is staged, not just the `.po`)

```bash
git add locale/
git commit -m "i18n(nesting): depth-3 validation messages"
```

---

## Task 12: e2e locator scoping and the full Definition of Done

- [ ] **Step 1: Scope the e2e locators**

**Derive the list, don't trust this one.** Run:

```bash
grep -rn "data-add-type" tests/*e2e*.py
```

That returns **~19 sites across ~15 files**, not the four an earlier draft named — and two of the unnamed ones (`tests/test_e2e_media_picker.py:75`, `tests/test_e2e_questions.py:92`) use byte-for-byte the same parametrized `page.locator(f"[data-add-type='{add_type}']").click()` shape as the named ones, so any four-item list is a sample, not a criterion.

For **each** site, record whether the clicked type newly appears in a nested menu — `tabs`, `twocolumn`, `spoiler`, `html`, `stepper`, `markdone`, `guessnumber`, `fillblankquestion` — or was already nested-visible. Scope the newly-at-risk ones to their `[data-add-menu]` ancestor and **state explicitly which you are leaving alone and why**.

The failure mode: these pass today only because they run against an editor with no container in it. Once nested menus emit the container cards, an unscoped click on a page that already contains a container matches more than one element and fails Playwright **strict mode**. `tests/test_e2e_tabs.py:137` and `tests/test_e2e_twocolumn.py:148` are the two confirmed to click a container card; the rest need the per-site judgement above.

- [ ] **Step 2: Add one e2e that drives the real gesture**

An e2e that bypasses the real UI gesture ships broken UX green. This is the only test in the plan that exercises the whole authoring path, so it gets named specifics rather than a description.

**File:** `tests/test_e2e_depth3.py`. Copy the login/course/editor setup from `tests/test_e2e_tabs.py` (same fixtures, same `pytestmark = pytest.mark.e2e`) rather than inventing one.

**Gesture:** open the editor → add a **Tabs** element → open the nested add-menu inside tab 1 → add a **Spoiler** → open the add-menu inside that spoiler → add a **Text** with a distinctive marker string.

**Every locator must be scoped to its `[data-add-menu]` ancestor** (per Step 1) — an unscoped `[data-add-type='spoiler']` now matches both the top-level and the nested menu and fails Playwright strict mode.

**Assertion:** navigate to the student lesson view and assert the marker string is present inside the spoiler's rendered body, i.e. the depth-3 text actually reaches the reader.

**Named mutant:** revert `_add_menu.html:35` to `{% if not nested %}` — which **suppresses** the Spoiler card in every nested menu, so step 2 of the gesture cannot complete.
**Node id that must FAIL:** `tests/test_e2e_depth3.py::test_author_a_depth_3_text_through_the_ui`

**Do NOT use "delete the depth predicate on `:35`" as the mutant.** After Task 8 that line reads `{% if depth < max_nest_depth|add:-1 %}`; deleting the guard makes the card render *unconditionally in every menu*, so the gesture still completes and the e2e stays GREEN. A deleted guard widens availability — it does not remove the card. This is the plan's only e2e mutant, and the one test that proves the feature is reachable through the real UI, so an inverted mutant here would leave it unfalsified.

- [ ] **Step 3: Run Group A gates**

```bash
uv run pytest --verbosity=0            # serial; compare to Task 0's baseline N
uv run pytest -m e2e --verbosity=0
uv run ruff check . && uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run     # expect NO new migration
uv run pytest tests/test_i18n_po_health.py --verbosity=0     # the 5th Group A gate
```

All **five** Group A gates, not four — the `.po` catalogue health check is one of them, and `test_i18n_po_health.py` owns every assertion about the catalogs as files (no fuzzy, no obsolete, no untranslated Polish string).

- [ ] **Step 4: Run Group B gates** — the seven help phrases return nothing; every coverage-table mutant has been recorded verified RED (except the exempt student-render row).

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test(e2e): scope add-menu locators and drive depth-3 authoring"
```

---

## Self-Review

**Spec coverage.** Containment rule → T1. One allowlist → T1. `element_depth` + query cost → T1. Registry entry + call-site `getattr` → T1. `CONTAINER_TRANSFER_KEYS` + drift → T1. LAL loader → T1/T2. Delete path (root, edge set, root-inclusive, `seen`, pk boundary, unconditional `el.delete()`) → T3. Export recursion + both ordering invariants → T4. Import validator (both clauses, cycle, missing ancestor, messages) → T5. `has_html` both sites + import removal → T6. `has_math` + render → T7. Editor (seeds, both context builders, module attr, guards, `in_spoiler` removal, 5 direct-render sites) → T8. Stale comments → T9. Help docs → T10. `.po` → T11. e2e + DoD → T12. Guardrail inversions: **17 sites**, all assigned — Task 1 owns eleven (Step 5 plus Step 5b), Task 5 four, Task 8 four, with `test_twocolumn_registry.py:16` explicitly left unchanged. Reconcile against Task 0's derived list rather than this count; round 2 added the 17th and round 3 confirmed by execution that there is no 18th.

**Placeholders.** Task 2's `build_element(...)` call and a few fixture bodies are marked "read the real helper first" rather than invented — deliberate, because inventing factory signatures is how a plan ships un-runnable test code. That licence covers **fixture construction only**: every test signature is real Python, every production change carries real code, and the one helper path this plan does assert (`tests.factories.make_course_with_unit`) was verified against the tree rather than recalled.

**Type consistency.** `element_depth(join) -> int`, `_collect_subtree_pks(roots) -> set[int]`, `CONTAINER_TRANSFER_KEYS: frozenset[str]`, `max_nest_depth` (context key, int) are used identically across T1/T3/T5/T8.
