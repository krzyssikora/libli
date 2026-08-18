# Callout Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Number callouts consecutively within a unit — one shared sequence across kinds, with a per-callout checkbox and unnumbered kinds skipped rather than consuming a number.

**Architecture:** A new `courses/numbering.py` builds a `{Element.pk: number}` map by walking the unit's element tree in reading order, descending through the containers' own `resolved_*` accessors so the numbering can never disagree with the render. Four context builders call it; the map crosses the recursive render barrier as a seventh key in the existing `page` dict. A `CalloutElement.numbered` boolean drives which callouts consume a number.

**Tech Stack:** Django 5, PostgreSQL, pytest + pytest-django + pytest-xdist, Playwright (e2e), uv for tooling.

**Spec:** `docs/superpowers/specs/2026-08-18-callout-numbering-design.md` — read it alongside this plan; every task argues from it.

## Global Constraints

- **`FORMAT_VERSION` goes 12 → 13** (`courses/transfer/schema.py:14`). Eight existing assertions pin the old value and must be updated; one must NOT be (Task 7).
- **No trailing period after a bare number.** `Przykład 3`, never `Przykład 3.` The period appears only as the separator before a custom heading.
- **Assert in English.** `LANGUAGE_CODE = "en"` and `conftest.py`'s autouse `_reset_active_language` activates it around every test. Kind labels render as `Example` / `Task` / `Note` / `Tip` / `Important`. The Polish forms in the spec are exposition only.
- **Every test fixture must set `numbered` explicitly.** Kind never implies `numbered` at creation: the model default is a flat `True`, and `KIND_DEFAULT_NUMBERED` is consulted only by the migration and the importer.
- **Every production site that constructs a `CalloutElement` must pass `numbered` explicitly.** Today that is `_build_callout` (Task 7) and `seed_demo_course._callout` (Task 8).
- **Start the test-DB container before any pytest run**, or the first run looks hung for ~4 minutes:
  `docker compose -f docker-compose.test.yml up -d`
- **Tooling is behind uv.** `pytest`/`ruff` are not on PATH — always `uv run pytest ...`, `uv run ruff ...`.
- **`addopts` already contains `-q`.** Do not add a second `-q`; a doubled `-q` suppresses the failure summary.
- **Scope every test run to the files you touched.** A whole-repo sweep is a branch-level gate (Task 10), never a per-task step.

---

## File Structure

**Created:**
- `courses/numbering.py` — the walk. One public function, `callout_numbers(node)`. No Django view or template imports; it depends on `courses.models` and `courses.builder` only.
- `courses/migrations/00NN_calloutelement_numbered.py` — AddField + backfill.
- `courses/tests/test_callout_numbering.py` — the walk's own tests (ordering, pre-order, unnumbered rule, cycle guard, early-out, accessor-map invariant, query counts).
- `courses/tests/test_callout_numbering_render.py` — template/render-level tests.
- `courses/tests/test_callout_numbering_wiring.py` — the four context sites and the `page` barrier.
- `courses/tests/test_callout_numbered_migration.py` — the backfill.
- `tests/test_e2e_callout_numbering.py` — the R2 round trip.

**Modified:**
- `courses/models.py` — `numbered` field, `KIND_DEFAULT_NUMBERED`, `kind_label`, `display_heading`, `CalloutElement.render`.
- `templates/courses/elements/calloutelement.html:5` — the heading line.
- `courses/templatetags/courses_extras.py` — seventh `page` key + the six→seven comment.
- `courses/views.py` — `build_lesson_context`, `build_quiz_context`.
- `courses/views_manage.py` — `_render_editor_fragments`, `_editor_page`.
- `courses/element_forms.py:266` — `Meta.fields`.
- `templates/courses/manage/editor/_edit_callout.html` — the checkbox.
- `courses/transfer/export.py:122`, `courses/transfer/payloads.py:211`, `courses/transfer/importer.py:556`, `courses/transfer/schema.py:14`.
- `courses/management/commands/seed_demo_course.py:246-253`.
- `locale/pl/LC_MESSAGES/django.po` + `.mo`, `docs/help/course-admin/content-editors.md` + `.pl.md`.
- Nine existing test files (churn, itemised in the tasks that cause it).

---

### Task 1: Model field, per-kind constant, and the `kind_label` split

**Files:**
- Modify: `courses/models.py:485-520` (the `CalloutElement` class body and `display_heading`)
- Modify: `courses/models.py:569` (beside `KIND_DEFAULT_HEADING`)
- Test: `courses/tests/test_callout_numbering.py` (new file)

**Interfaces:**
- Consumes: nothing.
- Produces: `CalloutElement.numbered: bool` (field, `default=True`); `CalloutElement.kind_label -> str` (property); `courses.models.KIND_DEFAULT_NUMBERED: dict[str, bool]`. `display_heading` keeps its existing signature and behaviour.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_callout_numbering.py`:

```python
"""The callout numbering walk and its data layer."""

import pytest

from courses.models import KIND_DEFAULT_NUMBERED
from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_kind_default_numbered_covers_every_kind():
    """Mutant: delete one entry -> a sixth kind (or a renamed one) silently gets
    no per-kind decision at backfill and at legacy-archive import."""
    assert set(KIND_DEFAULT_NUMBERED) == {k.value for k in CalloutElement.Kind}


def test_kind_default_numbered_values():
    assert KIND_DEFAULT_NUMBERED["example"] is True
    assert KIND_DEFAULT_NUMBERED["task"] is True
    assert KIND_DEFAULT_NUMBERED["warning"] is True
    assert KIND_DEFAULT_NUMBERED["note"] is False
    assert KIND_DEFAULT_NUMBERED["tip"] is False


def test_model_default_is_a_flat_true_regardless_of_kind():
    """D2 is scoped to backfill and legacy import. An author-created Note is born
    numbered; the author unticks. Mutant: add a per-kind form/model initial -> this
    fails, which is the point (see spec section 1)."""
    assert CalloutElement(kind="note").numbered is True
    assert CalloutElement(kind="example").numbered is True


def test_kind_label_ignores_a_custom_heading():
    """kind_label is the KIND's label; display_heading is the author-facing one."""
    el = CalloutElement(kind="example", heading="Suma ciagu")
    assert el.kind_label == "Example"
    assert el.display_heading == "Suma ciagu"


def test_display_heading_falls_back_to_kind_label():
    el = CalloutElement(kind="warning", heading="")
    assert el.display_heading == "Important"
    assert el.display_heading == el.kind_label


def test_kind_label_survives_an_unknown_kind():
    """The string fallback key. Mutant: `KIND_DEFAULT_HEADING[self.kind]` -> KeyError."""
    el = CalloutElement(kind="bogus", heading="")
    assert el.kind_label == "Example"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose -f docker-compose.test.yml up -d
uv run pytest courses/tests/test_callout_numbering.py -v
```

Expected: FAIL — `ImportError: cannot import name 'KIND_DEFAULT_NUMBERED'`.

- [ ] **Step 3: Add the field**

In `courses/models.py`, inside `class CalloutElement`, directly after the `kind` field (line 502):

```python
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.EXAMPLE)
    # A FLAT default, deliberately not per-kind: a field default cannot vary by kind,
    # and the per-kind map (KIND_DEFAULT_NUMBERED, below the class) is consulted only
    # by the backfill migration and by the importer's pre-v13 fallback. No `blank=True`
    # -- models.BooleanField.formfield hard-codes required=False, because an unchecked
    # checkbox transmits nothing.
    numbered = models.BooleanField(default=True)
```

- [ ] **Step 4: Split `kind_label` out of `display_heading`**

Replace `courses/models.py:513-518` (the whole `display_heading` property) with:

```python
    @property
    def kind_label(self):
        # NOTE: unrelated to the `kind_label` simple_tag in
        # courses/templatetags/courses_manage_extras.py:266, which labels NODE kinds
        # (course/chapter/section). Same name, different concept -- a grep hits both.
        #
        # String fallback key ("example"), NOT bare `Kind.EXAMPLE` — `Kind` is a nested
        # class and would resolve against module globals (undefined -> NameError).
        return KIND_DEFAULT_HEADING.get(self.kind, KIND_DEFAULT_HEADING["example"])

    @property
    def display_heading(self):
        # The fallback lives in kind_label alone -- two copies of the string-key
        # subtlety above would drift.
        return self.heading or self.kind_label
```

- [ ] **Step 5: Add the per-kind constant**

In `courses/models.py`, immediately after the existing `KIND_DEFAULT_HEADING` assignment (line 569):

```python
# Per-kind numbering defaults. Built after the class body for the same reason as
# KIND_DEFAULT_HEADING: it reads the enum. Exactly ONE runtime caller -- the
# importer's default for pre-v13 archives (courses/transfer/payloads.py). The
# backfill migration encodes the same decision as a frozen literal, never an import.
# NOT read by CalloutElementForm: a new callout is always created as `example`,
# whose default equals the flat model default, so a form initial would be
# unobservable and untestable.
KIND_DEFAULT_NUMBERED = {
    CalloutElement.Kind.EXAMPLE.value: True,
    CalloutElement.Kind.TASK.value: True,
    CalloutElement.Kind.WARNING.value: True,
    CalloutElement.Kind.NOTE.value: False,
    CalloutElement.Kind.TIP.value: False,
}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest courses/tests/test_callout_numbering.py -v
```

Expected: 6 passed.

- [ ] **Step 7: Verify the existing callout tests still pass**

```bash
uv run pytest courses/tests/test_callout_model.py courses/tests/test_callout_render.py courses/tests/test_callout_authoring.py -v
```

Expected: all pass. `display_heading` is behaviourally identical.

- [ ] **Step 8: Falsify — run the named mutants**

Edit by hand (never `git checkout` to revert — it destroys uncommitted work; undo each edit by hand):

1. Delete the `"tip"` entry from `KIND_DEFAULT_NUMBERED` → `test_kind_default_numbered_covers_every_kind` must FAIL. Restore.
2. Change `display_heading` to `return self.heading or KIND_DEFAULT_HEADING[self.kind]` → `test_kind_label_survives_an_unknown_kind` still passes (it tests `kind_label`), so also confirm the fallback is only defined once by grepping: `grep -c 'KIND_DEFAULT_HEADING\["example"\]' courses/models.py` must return `1`. Restore.

- [ ] **Step 9: Commit**

```bash
git add courses/models.py courses/tests/test_callout_numbering.py
git commit -m "feat(callout): add numbered field, per-kind defaults, kind_label"
```

---

### Task 2: The migration

**Files:**
- Create: `courses/migrations/00NN_calloutelement_numbered.py`
- Test: `courses/tests/test_callout_numbered_migration.py` (new file)

**Interfaces:**
- Consumes: `CalloutElement.numbered` from Task 1.
- Produces: a schema column and a backfilled corpus. Nothing later imports from this file.

- [ ] **Step 1: Generate the schema migration**

```bash
uv run python manage.py makemigrations courses --name calloutelement_numbered
```

Note the number it assigns (the head at the time of writing is `0059_mediaasset_derivatives`, so expect `0060`). **Do not hand-pick a number or a dependency** — whatever `makemigrations` produces against the current graph head is correct.

- [ ] **Step 2: Write the failing migration test**

Create `courses/tests/test_callout_numbered_migration.py`. Replace `00NN_calloutelement_numbered` with the real name from Step 1, and `BEFORE` with that migration's own `dependencies` entry:

```python
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("courses", "0059_mediaasset_derivatives")   # <-- the new migration's dependency
AFTER = ("courses", "00NN_calloutelement_numbered")   # <-- the new migration


@pytest.mark.django_db(transaction=True)
def test_backfill_unnumbers_note_and_tip_only():
    """Mutant: drop the RunPython (or make it set every row True) -> the note and tip
    rows arrive numbered.

    transaction=True is MANDATORY: this unapplies and re-applies a migration, which
    cannot happen inside pytest-django's per-test atomic block. The `finally` restore
    targets graph HEAD, not AFTER -- a restore pinned to a node that a later migration
    supersedes runs BACKWARDS and poisons every later test on the worker.
    """
    executor = MigrationExecutor(connection)
    try:
        executor.migrate([BEFORE])
        executor.loader.build_graph()

        old_apps = executor.loader.project_state([BEFORE]).apps
        Callout = old_apps.get_model("courses", "CalloutElement")
        for kind in ("example", "task", "warning", "note", "tip"):
            Callout.objects.create(kind=kind, heading="", body="")

        executor = MigrationExecutor(connection)
        executor.migrate([AFTER])

        new_apps = MigrationExecutor(connection).loader.project_state([AFTER]).apps
        Callout = new_apps.get_model("courses", "CalloutElement")
        by_kind = {c.kind: c.numbered for c in Callout.objects.all()}
        assert by_kind == {
            "example": True,
            "task": True,
            "warning": True,
            "note": False,
            "tip": False,
        }
    finally:
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
```

- [ ] **Step 3: Run it to verify it fails**

```bash
uv run pytest courses/tests/test_callout_numbered_migration.py -v
```

Expected: FAIL — every kind arrives `True`, because only the `AddField` exists.

- [ ] **Step 4: Add the backfill operation**

Edit the generated migration. Add above `class Migration`:

```python
def _unnumber_note_and_tip(apps, schema_editor):
    """Kinds whose per-kind default is False (spec D2/D5).

    The list is a FROZEN LITERAL copied from courses.models.KIND_DEFAULT_NUMBERED,
    deliberately NOT an import: a migration that reads a live module constant
    silently changes meaning the day that constant is edited.

    Historical model + bulk update: the live CalloutElement.save() re-sanitises
    `body`, and .update() never touches it.
    """
    Callout = apps.get_model("courses", "CalloutElement")
    Callout.objects.filter(kind__in=["note", "tip"]).update(numbered=False)
```

and append to `operations`, after the `AddField`:

```python
        migrations.RunPython(_unnumber_note_and_tip, migrations.RunPython.noop),
```

`RunPython.noop` as the reverse — not a raising `unapply`, which cannot be tested because it raises before running anything. The `AddField`'s own reversal drops the column, so the data step has nothing to undo.

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest courses/tests/test_callout_numbered_migration.py -v
```

Expected: PASS.

- [ ] **Step 6: Verify the migration graph is clean**

```bash
uv run python manage.py makemigrations --check --dry-run
```

Expected: "No changes detected".

- [ ] **Step 7: Falsify**

Change the filter to `kind__in=[]` → the test must FAIL with note/tip `True`. Restore by hand.

- [ ] **Step 8: Commit**

```bash
git add courses/migrations/ courses/tests/test_callout_numbered_migration.py
git commit -m "feat(callout): migrate numbered, unnumbering note and tip"
```

---

### Task 3: The numbering walk — ordering core

**Files:**
- Create: `courses/numbering.py`
- Modify: `courses/tests/test_callout_numbering.py` (append)

**Interfaces:**
- Consumes: `CalloutElement.numbered` (Task 1).
- Produces: `courses.numbering.callout_numbers(node) -> dict[int, int]` mapping `Element.pk` → 1-based number, and `courses.numbering.ACCESSORS: dict[type, callable]`.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_callout_numbering.py` (add the imports at the top of the file):

```python
from courses.models import SINGLE_SLOT_ID
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.numbering import callout_numbers
from tests.factories import add_element
from tests.factories import make_course_with_unit


def _callout(unit, kind="example", numbered=True, parent=None, tab_id="", order=0):
    """EVERY fixture sets `numbered` explicitly -- kind never implies it (see the
    Global Constraints). Returns the join row, because the map is keyed by join pk."""
    co = CalloutElement.objects.create(kind=kind, numbered=numbered, body="")
    return Element.objects.create(
        unit=unit, content_object=co, parent=parent, tab_id=tab_id, order=order
    )


def test_numbers_run_in_document_order_at_top_level():
    _course, unit = make_course_with_unit()
    a = _callout(unit, "example", numbered=True, order=0)
    b = _callout(unit, "task", numbered=True, order=1)
    assert callout_numbers(unit) == {a.pk: 1, b.pk: 2}


def test_an_unnumbered_callout_does_not_consume_a_number():
    """The acceptance criterion from the spec's Purpose:
    example, task, note, warning, task -> 1, 2, -, 3, 4.

    Mutant: increment the counter BEFORE the `numbered` check -> 1, 2, -, 4, 5.
    """
    _course, unit = make_course_with_unit()
    a = _callout(unit, "example", numbered=True, order=0)
    b = _callout(unit, "task", numbered=True, order=1)
    note = _callout(unit, "note", numbered=False, order=2)
    d = _callout(unit, "warning", numbered=True, order=3)
    e = _callout(unit, "task", numbered=True, order=4)

    numbers = callout_numbers(unit)
    assert numbers == {a.pk: 1, b.pk: 2, d.pk: 3, e.pk: 4}
    assert note.pk not in numbers


def test_tab_children_are_numbered_tab_by_tab_not_by_flat_order():
    """THE test the whole accessor-based design exists for.

    Real content interleaves tab children in `order` (spec section 3: unit 349 reads
    t000000, t000001, t000002, t000000, ...), so reading order is TAB INDEX then
    order-within-tab. Two callouts per tab is mandatory: with one per tab, tab-major
    and flat order coincide and the mutant survives.

    Creation order A, B, C, D is pinned, and A/B live in data["tabs"][0], because the
    flat walk's tiebreak inside an order-group is pk == creation order.

    Mutant: replace the accessor descent with a flat
    `join.children.order_by("order", "pk")` -> A, C, B, D.
    """
    _course, unit = make_course_with_unit()
    top = _callout(unit, "example", numbered=True, order=0)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000000", "label": "One"}, {"id": "t000001", "label": "Two"}]}
    )
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=1)
    a = _callout(unit, "task", numbered=True, parent=tabs_join, tab_id="t000000", order=0)
    b = _callout(unit, "task", numbered=True, parent=tabs_join, tab_id="t000000", order=1)
    c = _callout(unit, "task", numbered=True, parent=tabs_join, tab_id="t000001", order=0)
    d = _callout(unit, "task", numbered=True, parent=tabs_join, tab_id="t000001", order=1)

    numbers = callout_numbers(unit)
    assert numbers == {top.pk: 1, a.pk: 2, b.pk: 3, c.pk: 4, d.pk: 5}
    # Spelled out so a failure reads as an ORDER failure, not a count failure:
    assert [numbers[j.pk] for j in (a, b, c, d)] == [2, 3, 4, 5]


def test_a_container_takes_its_number_before_its_children():
    """Pre-order. A callout is itself a container, so this is reachable.
    Mutant: assign the container's number AFTER walking its children -> 2, 1."""
    _course, unit = make_course_with_unit()
    outer = _callout(unit, "example", numbered=True, order=0)
    inner = _callout(
        unit, "task", numbered=True, parent=outer, tab_id=SINGLE_SLOT_ID, order=0
    )
    assert callout_numbers(unit) == {outer.pk: 1, inner.pk: 2}


def test_spoiler_children_are_numbered_in_order():
    _course, unit = make_course_with_unit()
    top = _callout(unit, "example", numbered=True, order=0)
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, order=1)
    inner = _callout(
        unit, "task", numbered=True, parent=sp_join, tab_id=SpoilerElement.SLOT_ID, order=0
    )
    assert callout_numbers(unit) == {top.pk: 1, inner.pk: 2}


def test_non_callout_leaves_are_walked_past_without_consuming_numbers():
    _course, unit = make_course_with_unit()
    add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    a = _callout(unit, "example", numbered=True, order=1)
    assert callout_numbers(unit) == {a.pk: 1}
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_callout_numbering.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'courses.numbering'`.

- [ ] **Step 3: Write the walk**

Create `courses/numbering.py`:

```python
"""Consecutive numbering of callouts within a unit.

ONE public function. It is deliberately self-contained -- it re-queries its own
roots rather than accepting a caller's element list -- so its query count is a
property of this module and not of each of its four call sites.

See docs/superpowers/specs/2026-08-18-callout-numbering-design.md section 3.
"""

from courses.models import BeforeAfterElement
from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TabsElement
from courses.models import TwoColumnElement


def _children_of(obj):
    return obj.resolved_children()


def _tab_children_of(obj):
    return [child for _tab, children in obj.resolved_tabs() for child in children]


def _column_children_of(obj):
    return [child for _col, children in obj.resolved_columns() for child in children]


def _slot_children_of(obj):
    return [child for _slot, children in obj.resolved_slots() for child in children]


# The accessor per container type. Keyed by model class; an entry MUST exist for
# every member of builder.CONTAINER_MODELS (pinned by test_accessors_cover_every_
# container). Descending through the containers' OWN accessors is the whole design:
# document order is NOT order_by("order", "pk") -- tab children interleave in `order`
# -- and re-deriving the grouping here would be a second implementation of reading
# order that drifts from the render the first time a container changes.
#
# Inheriting the accessors inherits their quirks, which is the point:
#   - resolved_tabs SKIPS a child whose tab_id matches no tab
#   - resolved_slots APPENDS an unknown-tab_id child to the `before` bucket
#   - resolved_columns applies the destructive 2..4 render clamp
# In each case the render drops or keeps exactly what the numbering does.
ACCESSORS = {
    SpoilerElement: _children_of,
    CalloutElement: _children_of,
    TabsElement: _tab_children_of,
    TwoColumnElement: _column_children_of,
    BeforeAfterElement: _slot_children_of,
}


def callout_numbers(node):
    """{Element.pk: number} for every numbered callout in `node`, in document order.

    `node` is a unit ContentNode. A node with no callouts returns {}.
    """
    from courses import builder  # module attribute, never a module-level from-import

    counter = 0
    numbers = {}
    seen = set()

    def walk(rows):
        nonlocal counter
        for row in rows:
            if row.pk in seen:
                continue
            seen.add(row.pk)
            obj = row.content_object
            if obj is None:
                continue  # dangling GFK: skipped, not counted, not an error
            if isinstance(obj, CalloutElement) and obj.numbered:
                counter += 1
                numbers[row.pk] = counter  # PRE-ORDER: before descending
            if type(obj) in builder.CONTAINER_MODELS:
                try:
                    accessor = ACCESSORS[type(obj)]
                except KeyError:
                    raise RuntimeError(
                        f"no accessor for container {type(obj).__name__}"
                    ) from None
                walk(accessor(obj))

    walk(
        node.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .select_related("content_type")
        .prefetch_related("content_object")
    )
    return numbers
```

- [ ] **Step 4: Run to verify they pass**

```bash
uv run pytest courses/tests/test_callout_numbering.py -v
```

Expected: all pass.

- [ ] **Step 5: Falsify — the ordering mutant**

In `courses/numbering.py`, replace the `ACCESSORS[type(obj)]` dispatch body with a flat descent:

```python
                walk(obj.join_row().children.order_by("order", "pk"))
```

Run `uv run pytest courses/tests/test_callout_numbering.py::test_tab_children_are_numbered_tab_by_tab_not_by_flat_order -v`.
Expected: **FAIL**, with `[2, 4, 3, 5]` — A, C, B, D. Undo the edit by hand.

- [ ] **Step 6: Falsify — the pre-order and unnumbered mutants**

1. Move the `counter += 1 / numbers[row.pk] = counter` block to after the `walk(...)` call → `test_a_container_takes_its_number_before_its_children` FAILS. Restore.
2. Move `counter += 1` above the `isinstance(...) and obj.numbered` check (counting every callout) → `test_an_unnumbered_callout_does_not_consume_a_number` FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
git add courses/numbering.py courses/tests/test_callout_numbering.py
git commit -m "feat(callout): add the unit-wide numbering walk"
```

---

### Task 4: Walk hardening — early-out, cycle guard, unmapped container, query counts

**Files:**
- Modify: `courses/numbering.py`
- Modify: `courses/tests/test_callout_numbering.py` (append)

**Interfaces:**
- Consumes: `callout_numbers`, `ACCESSORS` (Task 3).
- Produces: no new names. `callout_numbers` gains an early-out; its query count becomes a pinned invariant.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_callout_numbering.py`:

```python
def test_a_unit_with_no_callouts_short_circuits(django_assert_num_queries):
    """The early-out. Most units have no callout at all, and without this a
    callout-free unit with containers pays the full descent on every student and
    editor render.

    Mutant: delete the early-out -> the container is descended and the count exceeds 1.
    """
    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data={"tabs": [{"id": "t000000", "label": "One"}]})
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=0)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>x</p>"),
        parent=tabs_join,
        tab_id="t000000",
        order=0,
    )
    _warm_content_type_cache()
    with django_assert_num_queries(1):
        assert callout_numbers(unit) == {}


def test_a_nested_only_callout_is_not_short_circuited():
    """The existence check is unit-wide, NOT parent__isnull=True.
    Mutant: add `parent__isnull=True` to the early-out filter -> {} is returned."""
    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, order=0)
    inner = _callout(
        unit, "task", numbered=True, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    assert callout_numbers(unit) == {inner.pk: 1}


def test_a_dangling_content_object_is_skipped_not_raised_on():
    """A row whose concrete is gone must not 500 the student page.
    Mutant: drop the `obj is None` guard -> AttributeError."""
    _course, unit = make_course_with_unit()
    orphan_target = TextElement.objects.create(body="<p>x</p>")
    orphan = add_element(unit, orphan_target)
    orphan_target.delete()
    a = _callout(unit, "example", numbered=True, order=1)

    numbers = callout_numbers(unit)
    assert numbers == {a.pk: 1}
    assert orphan.pk not in numbers


def test_the_walk_terminates_on_a_join_row_cycle():
    """`join_row()` returns the LOWEST-PK join row for a concrete, not the row the
    walk arrived on. Two join rows on one concrete therefore make a cycle in the
    walk's graph even though the `parent` tree is perfectly acyclic:

        R1 (root)      -> C_a
        R2 (parent=R1) -> C_b
        R3 (parent=R2) -> C_a      # join_row(C_a) is R1 -> back to the start

    C_a must be a CALLOUT: its accessor groups by parent alone (so the cycle forms
    at all), and its presence defeats the early-out. A spoiler satisfies only the
    first; a tabs container satisfies neither, because an unmatched tab_id makes
    resolved_tabs drop the child and dissolve the cycle.

    Mutant: drop the `seen` set -> RecursionError.
    """
    _course, unit = make_course_with_unit()
    c_a = CalloutElement.objects.create(kind="example", numbered=True, body="")
    c_b = CalloutElement.objects.create(kind="task", numbered=True, body="")
    r1 = Element.objects.create(unit=unit, content_object=c_a, order=0)
    r2 = Element.objects.create(
        unit=unit, content_object=c_b, parent=r1, tab_id=SINGLE_SLOT_ID, order=0
    )
    Element.objects.create(
        unit=unit, content_object=c_a, parent=r2, tab_id=SINGLE_SLOT_ID, order=0
    )

    numbers = callout_numbers(unit)  # must terminate
    assert numbers[r1.pk] == 1
    assert numbers[r2.pk] == 2


def test_accessors_cover_every_container():
    """Mutant: delete one ACCESSORS entry -> a real container's children are silently
    never numbered."""
    from courses import builder
    from courses.numbering import ACCESSORS

    assert set(ACCESSORS) == builder.CONTAINER_MODELS


def test_an_unmapped_container_raises_with_a_named_type(monkeypatch):
    """CONTAINER_MODELS is read as a MODULE ATTRIBUTE so this patch reaches the walk;
    a module-level from-import would freeze it and this test would fail against a
    CORRECT implementation (the MAX_NEST_DEPTH precedent, views_manage.py:1858-1861).

    TextElement, not an invented class: no Element.content_object is ever an instance
    of an invented class, so the walk would never dispatch and the test would pass
    vacuously on both builds. The fixture also needs a CALLOUT, or the early-out
    returns {} before any descent -- vacuous a second way.
    """
    from courses import builder

    _course, unit = make_course_with_unit()
    _callout(unit, "example", numbered=True, order=0)
    add_element(unit, TextElement.objects.create(body="<p>x</p>"))
    monkeypatch.setattr(
        builder, "CONTAINER_MODELS", builder.CONTAINER_MODELS | {TextElement}
    )

    with pytest.raises(RuntimeError, match="TextElement"):
        callout_numbers(unit)


def test_query_count_on_a_real_shaped_unit(django_assert_num_queries):
    """Shape (spec section 3):
        existence check + roots + per container (join_row + children + one prefetch
        per distinct child content type)

    The ContentType cache is warmed FIRST and deliberately: ContentTypeManager caches
    per process and survives --reuse-db, so an unwarmed count depends on test ordering
    and on which xdist worker ran what -- an intermittent failure with nothing in the
    test explaining it.

    EXPECTED_QUERIES is transcribed from an observed run, not derived from prose
    arithmetic. If it changes, reconcile the delta against the shape above before
    editing the number.
    """
    _course, unit = make_course_with_unit()
    _callout(unit, "example", numbered=True, order=0)
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": f"t00000{i}", "label": str(i)} for i in range(3)]}
    )
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=1)
    for i in range(3):
        _callout(
            unit, "task", numbered=True, parent=tabs_join, tab_id=f"t00000{i}", order=0
        )
    sp = SpoilerElement.objects.create(label="s")
    sp_join = Element.objects.create(unit=unit, content_object=sp, order=2)
    _callout(unit, "example", numbered=True, parent=sp_join, tab_id=SpoilerElement.SLOT_ID)

    _warm_content_type_cache()
    with django_assert_num_queries(EXPECTED_QUERIES):
        callout_numbers(unit)
```

and, near the top of the file beside `_callout`:

```python
EXPECTED_QUERIES = 0  # <-- replaced in Step 5 with the observed value


def _warm_content_type_cache():
    """Populate ContentTypeManager's per-process cache for every type the fixtures
    use, so an assertNumQueries below measures the walk and not cache warmth."""
    from django.contrib.contenttypes.models import ContentType

    for model in (CalloutElement, TabsElement, SpoilerElement, TextElement, Element):
        ContentType.objects.get_for_model(model)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_callout_numbering.py -v
```

Expected: FAIL — the early-out, cycle, unmapped-container and query-count tests all fail (the `seen` guard and `obj is None` guard from Task 3 already pass; leave them, they are regression cover).

- [ ] **Step 3: Add the early-out**

In `courses/numbering.py`, at the top of `callout_numbers`, before `counter = 0`:

```python
    # Early-out: most units have no callout at all, and the call is unconditional at
    # all four context sites. Filters on content_type__model rather than resolving a
    # ContentType object, so it never consults the process-wide ContentType cache and
    # the pinned query count cannot depend on cache warmth. `app_label` is required:
    # Element.content_type's limit_choices_to is a form/admin constraint, not a
    # database one. Unit-wide, NOT parent__isnull=True -- a unit whose only callout is
    # nested must NOT be short-circuited.
    if not Element.objects.filter(
        unit=node,
        content_type__app_label="courses",
        content_type__model="calloutelement",
    ).exists():
        return {}
```

- [ ] **Step 4: Run to verify the non-query tests pass**

```bash
uv run pytest courses/tests/test_callout_numbering.py -v -k "not query_count"
```

Expected: all pass.

- [ ] **Step 5: Observe and record the query count**

```bash
uv run pytest courses/tests/test_callout_numbering.py::test_query_count_on_a_real_shaped_unit -v
```

The failure message reads `Expected to perform 0 queries but N were done`. Set `EXPECTED_QUERIES = N` and add a comment breaking N down against the shape (`1 existence + 1 roots + …`). Re-run; expected: PASS.

- [ ] **Step 6: Falsify**

1. Delete the early-out block → `test_a_unit_with_no_callouts_short_circuits` FAILS. Restore.
2. Add `parent__isnull=True` to the early-out filter → `test_a_nested_only_callout_is_not_short_circuited` FAILS. Restore.
3. Delete `seen.add(row.pk)` and the `if row.pk in seen` guard → `test_the_walk_terminates_on_a_join_row_cycle` FAILS with `RecursionError`. Restore.
4. Change the module-attribute read to a module-level `from courses.builder import CONTAINER_MODELS` → `test_an_unmapped_container_raises_with_a_named_type` FAILS (the patch no longer reaches the walk). Restore.
5. Replace the `raise RuntimeError(...)` with `continue` → the same test FAILS. Restore.

- [ ] **Step 7: Commit**

```bash
git add courses/numbering.py courses/tests/test_callout_numbering.py
git commit -m "feat(callout): harden the numbering walk (early-out, cycle guard, query pin)"
```

---

### Task 5: Render the number

**Files:**
- Modify: `courses/models.py` (`CalloutElement.render`, ~line 545)
- Modify: `templates/courses/elements/calloutelement.html:5`
- Test: `courses/tests/test_callout_numbering_render.py` (new file)

**Interfaces:**
- Consumes: `kind_label` (Task 1); a `page` dict carrying `callout_numbers`.
- Produces: a `number` template-context key (`int` or `None`) and the `.callout__number` span.

- [ ] **Step 1: Capture today's unnumbered output**

Before touching the template, record the literal an unnumbered render produces, so Step 2's byte-identity assertion is transcribed rather than guessed:

```bash
uv run python manage.py shell -c "
from courses.models import CalloutElement
print(repr(CalloutElement(kind='example', heading='Suma ciagu', numbered=False).render()))
"
```

Note the exact `<span class="callout__heading">…</span>` fragment.

- [ ] **Step 2: Write the failing tests**

Create `courses/tests/test_callout_numbering_render.py`:

```python
"""Rendering of the callout number. Assertions are in ENGLISH: LANGUAGE_CODE is "en"
and conftest's _reset_active_language activates it around every test."""

import pytest

from courses.models import CalloutElement
from courses.models import Element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

UNNUMBERED_CUSTOM_HEADING = '<span class="callout__heading">Suma ciagu</span>'


def _rendered(el, join, numbers):
    return el.render(
        element=join, state={}, slug="s", node_pk=1, page={"callout_numbers": numbers}
    )


def test_a_numbered_callout_shows_label_space_number():
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 3})
    assert 'Example <span class="callout__number">3</span>' in html


def test_a_numbered_callout_has_no_trailing_period_without_a_heading():
    """Spec D7. Mutant: emit `{{ number }}.` -> this fails."""
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="task", numbered=True, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 2})
    assert '<span class="callout__number">2</span></span>' in html


def test_a_numbered_callout_with_a_custom_heading_reads_label_number_period_heading():
    """D4 -- the ONE row of the spec's table that changes existing semantics, and the
    only branch with zero real rows exercising it (0 of 369 callouts have a heading).

    Mutant A: swap the label/heading order.
    Mutant B: emit `display_heading` instead of `heading` in the numbered branch,
              which renders the custom text twice or drops the label.
    """
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(
        kind="example", heading="Suma ciagu", numbered=True, body=""
    )
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 3})
    assert (
        '<span class="callout__heading">Example '
        '<span class="callout__number">3</span>. Suma ciagu</span>'
    ) in html


def test_an_unnumbered_callout_renders_exactly_as_before():
    """The custom heading still REPLACES the label when unnumbered -- unchanged
    behaviour. Mutant: make the numbered branch unconditional -> this fails."""
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(
        kind="example", heading="Suma ciagu", numbered=False, body=""
    )
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {join.pk: 3})
    assert UNNUMBERED_CUSTOM_HEADING in html
    assert "callout__number" not in html


def test_a_callout_absent_from_the_map_renders_no_number():
    _course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    join = Element.objects.create(unit=unit, content_object=el)
    html = _rendered(el, join, {})
    assert "callout__number" not in html
    assert '<span class="callout__heading">Example</span>' in html


def test_render_without_an_element_does_not_raise():
    """CalloutElement.render's signature is `element=None`, and eight sites in
    test_callout_render.py call `.render()` bare. Mutant: drop the
    `element is not None` guard -> AttributeError on NoneType.pk."""
    html = CalloutElement(kind="example", numbered=True, body="").render()
    assert "callout__number" not in html
```

- [ ] **Step 3: Run to verify they fail**

```bash
uv run pytest courses/tests/test_callout_numbering_render.py -v
```

Expected: FAIL — no `callout__number` anywhere.

- [ ] **Step 4: Read the number in `render`**

In `courses/models.py`, inside `CalloutElement.render`, add above the `return render_to_string(...)`:

```python
        # The lookup happens here, not in the template: a Django template cannot index
        # a dict by a variable key without a filter. The `element is not None` guard is
        # LOAD-BEARING -- eight sites in test_callout_render.py call .render() bare, and
        # test_render_seam.py pins that shape for the leaf case. A join-row-less callout
        # has no unit-wide position, so None is the right number for it.
        numbers = (page or {}).get("callout_numbers") or {}
```

and add to the context dict, beside `"children"`:

```python
                "number": numbers.get(element.pk) if element is not None else None,
```

- [ ] **Step 5: Rewrite the heading line**

Replace line 5 of `templates/courses/elements/calloutelement.html` with a **single line** — Django does not strip template whitespace, and a multi-line `{% if %}` would inject newlines into the heading and break the byte-identity guarantee:

```django
    <span class="callout__heading">{% if number %}{{ el.kind_label }} <span class="callout__number">{{ number }}</span>{% if el.heading %}. {{ el.heading }}{% endif %}{% else %}{{ el.display_heading }}{% endif %}</span>
```

- [ ] **Step 6: Run to verify they pass**

```bash
uv run pytest courses/tests/test_callout_numbering_render.py courses/tests/test_callout_render.py -v
```

Expected: all pass, including the eight pre-existing bare `.render()` tests.

- [ ] **Step 7: Falsify**

1. Delete `{% else %}{{ el.display_heading }}` and make the numbered branch unconditional → `test_an_unnumbered_callout_renders_exactly_as_before` FAILS. Restore.
2. Emit `{{ number }}.` instead of `{{ number }}` → `test_a_numbered_callout_has_no_trailing_period_without_a_heading` FAILS. Restore.
3. Swap to `{% if el.heading %}{{ el.heading }}. {% endif %}{{ el.kind_label }} …` → the custom-heading test FAILS. Restore.
4. Drop `if element is not None` → `test_render_without_an_element_does_not_raise` FAILS with `AttributeError`. Restore.

- [ ] **Step 8: Commit**

```bash
git add courses/models.py templates/courses/elements/calloutelement.html courses/tests/test_callout_numbering_render.py
git commit -m "feat(callout): render the number in the callout heading"
```

---

### Task 6: Context wiring — four sites and the `page` barrier

**Files:**
- Modify: `courses/templatetags/courses_extras.py:53-56` (comment) and `:162` (the `page` dict)
- Modify: `courses/views.py` (`build_lesson_context` ~`:347`, `build_quiz_context` ~`:1304`)
- Modify: `courses/views_manage.py` (`_render_editor_fragments` ~`:1853`, `_editor_page` ~`:1915`)
- Modify: `courses/tests/test_nested_question_nojs_feedback.py:641-650` (churn)
- Test: `courses/tests/test_callout_numbering_wiring.py` (new file)

**Interfaces:**
- Consumes: `callout_numbers` (Tasks 3-4); the `number` context key (Task 5).
- Produces: a `callout_numbers` key in four contexts and in the `page` dict.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_callout_numbering_wiring.py`:

```python
"""The four context sites and the render barrier. There is no single choke point
that covers all four (spec R1), so each gets its own test."""

import pytest
from django.urls import reverse

from courses.models import SINGLE_SLOT_ID
from courses.models import CalloutElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import TabsElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

NUMBER_SPAN = '<span class="callout__number">2</span>'


def _numbered_callout(unit, kind="example", parent=None, tab_id="", order=0):
    el = CalloutElement.objects.create(kind=kind, numbered=True, body="")
    return Element.objects.create(
        unit=unit, content_object=el, parent=parent, tab_id=tab_id, order=order
    )


def _unit_with_a_nested_callout(unit):
    """Top-level callout (number 1) + a callout inside tabs (number 2). The NESTED
    one is what proves the map crossed the render barrier."""
    _numbered_callout(unit, order=0)
    tabs = TabsElement.objects.create(data={"tabs": [{"id": "t000000", "label": "One"}]})
    tabs_join = Element.objects.create(unit=unit, content_object=tabs, order=1)
    return _numbered_callout(unit, "task", parent=tabs_join, tab_id="t000000")


def test_lesson_context_carries_the_map():
    from courses.views import build_lesson_context

    _course, unit = make_course_with_unit()
    _unit_with_a_nested_callout(unit)
    ctx = build_lesson_context(unit, user=None)
    assert len(ctx["callout_numbers"]) == 2


def test_quiz_context_carries_the_map():
    from courses.views import build_quiz_context

    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type=ContentNode.UnitType.QUIZ
    )
    _unit_with_a_nested_callout(unit)
    ctx = build_quiz_context(unit, user=None)
    assert len(ctx["callout_numbers"]) == 2


def test_the_student_lesson_page_numbers_a_NESTED_callout(client):
    """The barrier end-to-end. Mutant: drop `**(page or {})` from TabsElement.render
    -> the top-level callout keeps its number and this one loses it."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_a_nested_callout(unit)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert resp.status_code == 200
    assert NUMBER_SPAN in resp.content.decode()


def test_the_editor_full_page_load_numbers_a_nested_callout(client):
    """_editor_page. Mutant: wire only _render_editor_fragments -> the first load
    shows no numbers while every later swap does."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_a_nested_callout(unit)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    assert NUMBER_SPAN in resp.content.decode()


def test_an_editor_fragment_swap_numbers_a_nested_callout(client):
    """_render_editor_fragments. Mutant: wire only _editor_page -> the first load
    looks perfect and every add/save/move/paste silently drops the numbers."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_a_nested_callout(unit)
    unit.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "text", "unit": unit.pk, "unit_token": unit.updated.isoformat()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert NUMBER_SPAN in resp.content.decode()


def test_a_callout_nested_in_a_callout_is_numbered_on_the_page(client):
    """The map must survive TWO barrier crossings."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    outer = _numbered_callout(unit, order=0)
    _numbered_callout(unit, "task", parent=outer, tab_id=SINGLE_SLOT_ID)
    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert NUMBER_SPAN in resp.content.decode()
```

URL names verified against `courses/urls.py`: `lesson_unit` takes `slug` + `node_pk` (`:27`), `manage_editor` takes `slug` + `pk` (`:244-249`), `manage_element_add` takes `slug` (`:254`). Note the kwarg differs — `node_pk` for the student page, `pk` for the editor.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_callout_numbering_wiring.py -v
```

Expected: FAIL — `KeyError: 'callout_numbers'` on the two context tests, missing span on the rest.

- [ ] **Step 3: Add the seventh `page` key**

In `courses/templatetags/courses_extras.py`, beside `feedback_ancestor_pks` (~line 76):

```python
    callout_numbers_map = context.get("callout_numbers") or {}
```

and inside `extra["page"]` (~line 162), after `feedback_ancestor_pks`:

```python
            "callout_numbers": callout_numbers_map,
```

- [ ] **Step 4: Update the six→seven comment**

At `courses/templatetags/courses_extras.py:53`, change `Six explicit statements` to `Seven explicit statements`. The comment is deliberately invariant and this repo has tests that regex raw source, so a stale count is a live hazard rather than cosmetics.

- [ ] **Step 5: Wire the four context sites**

`courses/views.py`, in `build_lesson_context` — after the `elements = list(...)` block:

```python
    from courses.numbering import callout_numbers
```
(at the top of the module with the other imports), and in the returned context dict:
```python
        "callout_numbers": callout_numbers(node),
```

Do the same in `build_quiz_context`.

`courses/views_manage.py`, in **both** `_render_editor_fragments` and `_editor_page`, add to the inline context dict beside `"preview_elements": join_rows`:

```python
            # Both builders, deliberately: _editor_page renders the first load and
            # _render_editor_fragments every later swap. A key on only one of them
            # makes the other silently drop every number.
            "callout_numbers": callout_numbers(unit),
```

with `from courses.numbering import callout_numbers` at the top of the module.

- [ ] **Step 6: Update the `page` key-set assertion (churn)**

`courses/tests/test_nested_question_nojs_feedback.py:641-650` asserts the FULL key set. Add `"callout_numbers"` to it. **Keep it an equality** — relaxing it to a subset check would destroy the property it exists to hold (its own comment explains that `"mode" not in captured` is green when `page` never arrived at all).

- [ ] **Step 7: Run to verify everything passes**

```bash
uv run pytest courses/tests/test_callout_numbering_wiring.py courses/tests/test_nested_question_nojs_feedback.py courses/tests/test_render_seam.py -v
```

Expected: all pass.

- [ ] **Step 8: Falsify — one mutant per site plus the barrier**

1. Remove `"callout_numbers"` from `build_lesson_context` → the lesson context test and the student-page test FAIL.
2. Remove it from `build_quiz_context` → the quiz context test FAILS.
3. Remove it from `_editor_page` only → `test_the_editor_full_page_load_...` FAILS, the fragment test still passes.
4. Remove it from `_render_editor_fragments` only → `test_an_editor_fragment_swap_...` FAILS, the page test still passes.
5. In `courses/models.py`, delete `**(page or {}),` from `TabsElement.render`'s context → `test_the_student_lesson_page_numbers_a_NESTED_callout` FAILS while the top-level number survives. This is the mutant that isolates the barrier; deleting the key from `extra["page"]` would strip numbers at every depth and prove nothing.

Restore each by hand after observing RED.

- [ ] **Step 9: Commit**

```bash
git add courses/templatetags/courses_extras.py courses/views.py courses/views_manage.py courses/tests/
git commit -m "feat(callout): wire callout numbers through the four context sites"
```

---

### Task 7: Editor form and checkbox

**Files:**
- Modify: `courses/element_forms.py:263-266`
- Modify: `templates/courses/manage/editor/_edit_callout.html`
- Modify: `courses/tests/test_callout_form.py`, `courses/tests/test_callout_authoring.py` (churn)
- Test: append to `courses/tests/test_callout_numbering_render.py`

**Interfaces:**
- Consumes: `CalloutElement.numbered` (Task 1).
- Produces: a `numbered` form field and an `<input type="checkbox" name="numbered">` in the editor partial.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_callout_numbering_render.py`:

```python
def test_the_form_exposes_numbered():
    from courses.element_forms import CalloutElementForm

    assert "numbered" in CalloutElementForm.Meta.fields


def test_the_editor_partial_renders_the_checkbox(client):
    """Assert ATTRIBUTE SUBSTRINGS, not a whole tag: the markup carries
    `{% if form.numbered.value %}checked{% endif %}`, so the rendered output is
    `... name="numbered" checked>` or `... name="numbered" >` -- the literal
    `<input type="checkbox" name="numbered">` is a substring of NEITHER, and
    asserting it would be red on a correct build.
    """
    from django.urls import reverse

    from tests.factories import CourseFactory
    from tests.factories import ContentNodeFactory
    from tests.factories import make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "callout", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    body = resp.content.decode()
    assert 'type="checkbox"' in body
    assert 'name="numbered"' in body
    # The ticked default IS R2: a new callout must arrive checked.
    assert 'name="numbered" checked' in body


def test_an_unnumbered_instance_renders_the_box_unchecked():
    from courses.element_forms import CalloutElementForm

    el = CalloutElement(kind="tip", numbered=False)
    form = CalloutElementForm(instance=el)
    assert form["numbered"].value() is False


def test_element_summary_never_shows_a_number(client):
    """D6: the collapsed editor row list is deliberately unchanged.

    Do NOT assert `element_summary(el) == el.display_heading`: that branch is
    literally `return el.display_heading`, so both sides move together under the
    mutant and the assertion is a tautology. The discriminating assertions are the
    hardcoded literal and the no-digit check.

    Mutant: fold the number into display_heading -> this fails, while the template
    mutants in this file would all still pass.
    """
    # A registered @register.filter (courses_manage_extras.py:129-130); the callout
    # branch at :157-158 is `return el.display_heading`. Callable directly as a plain
    # function.
    from courses.templatetags.courses_manage_extras import element_summary

    el = CalloutElement(kind="example", numbered=True, heading="")
    summary = element_summary(el)
    assert summary == "Example"
    assert not any(ch.isdigit() for ch in summary)
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_callout_numbering_render.py -v -k "form or checkbox or summary or unchecked"
```

Expected: FAIL — `numbered` not in `Meta.fields`.

- [ ] **Step 3: Add the field to the form**

`courses/element_forms.py:266`:

```python
        fields = ["kind", "numbered", "heading", "body"]
```

No `__init__` hook and no per-kind initial — see spec §1 for why one would be unobservable.

- [ ] **Step 4: Add the checkbox to the partial**

In `templates/courses/manage/editor/_edit_callout.html`, immediately after the closing `</label>` of the Kind select and before the Heading label:

```django
  <label class="el-editor__check">
    <input type="checkbox" name="numbered" {% if form.numbered.value %}checked{% endif %}>
    {% trans "Number this callout" %}
  </label>
```

`el-editor__check` is the existing class (`courses/static/courses/css/editor.css:153`), copied from `templates/courses/manage/editor/_edit_shorttextquestion.html:19-22` — the same case, a model-backed boolean on a hand-written element-editor partial. Do not invent a class name.

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest courses/tests/test_callout_numbering_render.py -v
```

Expected: all pass.

- [ ] **Step 6: Update the three existing POST tests (churn)**

All three post `{"kind", "heading", "body"}` with no `numbered`. An unchecked checkbox transmits nothing, so those POSTs are indistinguishable from a deliberate untick and now silently create `numbered=False` rows while staying green. Add an explicit assertion to each:

- `courses/tests/test_callout_form.py::test_valid_full_save` → `assert el.numbered is False` (nothing was posted, so False is correct — pin it so the behaviour is deliberate).
- `courses/tests/test_callout_authoring.py::test_save_round_trips_kind_heading_body` → assert the created row's `numbered is False`.
- `courses/tests/test_callout_authoring.py::test_save_round_trips_the_task_kind` (line 117) → assert `numbered is False`. This is the strongest R2 evidence in the repo: `task` is the highest-volume kind (177 rows) and defaults to numbered.

`courses/tests/test_callout_form.py::test_blank_heading_and_body_are_valid` also posts without the key but uses `kind="tip"`, whose default is already `False` — harmless by coincidence. Leave it, and do not assume it was overlooked.

- [ ] **Step 7: Run the callout suite**

```bash
uv run pytest courses/tests/test_callout_form.py courses/tests/test_callout_authoring.py courses/tests/test_callout_editor_row.py -v
```

Expected: all pass.

- [ ] **Step 8: Falsify**

1. Remove `"numbered"` from `Meta.fields` → `test_the_form_exposes_numbered` FAILS and the checkbox no longer round-trips.
2. Delete the `{% if form.numbered.value %}checked{% endif %}` → `test_the_editor_partial_renders_the_checkbox`'s third assertion FAILS.
3. Change `display_heading` to append the number → `test_element_summary_never_shows_a_number` FAILS. Restore.

- [ ] **Step 9: Commit**

```bash
git add courses/element_forms.py templates/courses/manage/editor/_edit_callout.html courses/tests/
git commit -m "feat(callout): add the numbering checkbox to the element editor"
```

---

### Task 8: Transfer — exporter first, then validator and builder

**Files:**
- Modify: `courses/transfer/export.py:122` (`_ser_callout`)
- Modify: `courses/transfer/payloads.py:211` (`_val_callout`)
- Modify: `courses/transfer/importer.py:556` (`_build_callout`)
- Modify: `courses/transfer/schema.py:14` (`FORMAT_VERSION`)
- Modify: eight existing assertions (listed in Step 6)
- Test: `courses/tests/test_callout_transfer.py` (append)

**Interfaces:**
- Consumes: `KIND_DEFAULT_NUMBERED` (Task 1).
- Produces: a `numbered` key in the callout transfer payload; `FORMAT_VERSION == 13`.

**ORDER IS LOAD-BEARING.** The exporter change (Step 3) must land before or with the builder change (Step 5). `graft_elements` — the duplicate/paste path — runs **no validator**: `_run_import` → `_create_elements` calls the builders directly, and `importer.py:999-1003` documents exactly this for `link_nodes`. So on that path the key exists only because the exporter writes it. Builder-first ships a build where every duplicate and paste raises `KeyError`, surfaced to the author as `TransferError("Duplicate failed.")`.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_callout_transfer.py`:

```python
def test_the_serializer_emits_numbered():
    el = CalloutElement.objects.create(
        kind="warning", heading="Careful", numbered=False, body="<p>hi</p>"
    )
    _model, ser = SERIALIZERS["callout"]

    class _Ids:
        def register(self, *a, **k):
            return None

    assert ser(el, _Ids())["numbered"] is False


def test_a_pre_v13_payload_imports_with_the_per_kind_default():
    """Legacy archives have no `numbered` key. The validator seeds it from the kind,
    matching the backfill migration exactly, so an archive exported before this
    feature and a database migrated by it agree.

    Mutant: drop the setdefault -> _exact_keys raises TransferError.
    """
    for kind, expected in (("example", True), ("note", False), ("tip", False)):
        data = {"kind": kind, "heading": "", "body": "<p>x</p>"}
        VALIDATORS["callout"](data, "e1", set())
        assert data["numbered"] is expected


def test_a_payload_with_no_kind_still_fails_cleanly():
    """The setdefault runs BEFORE _exact_keys, so it may see an absent or non-string
    `kind`. It must be total: a missing kind must still produce the validator's
    TransferError, never a KeyError; a list kind must not raise TypeError:
    unhashable.
    """
    from courses.transfer.schema import TransferError

    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"heading": "", "body": "<p>x</p>"}, "e1", set())
    with pytest.raises(TransferError):
        VALIDATORS["callout"]({"kind": [], "heading": "", "body": ""}, "e1", set())


def test_numbered_must_be_a_bool():
    from courses.transfer.schema import TransferError

    with pytest.raises(TransferError):
        VALIDATORS["callout"](
            {"kind": "example", "heading": "", "body": "", "numbered": "yes"},
            "e1",
            set(),
        )


def test_the_builder_round_trips_numbered_false():
    """Mutant: drop `numbered=` from _build_callout -> comes back True."""
    data = {"kind": "example", "heading": "", "body": "<p>x</p>", "numbered": False}
    VALIDATORS["callout"](data, "e1", set())
    concrete, _media = BUILDERS["callout"](data, {})
    assert concrete.numbered is False
```

Match the existing imports at the top of that file (`SERIALIZERS`, `VALIDATORS`, `BUILDERS`) — add whichever are missing.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest courses/tests/test_callout_transfer.py -v
```

Expected: FAIL.

- [ ] **Step 3: Update the exporter — FIRST**

`courses/transfer/export.py:122`:

```python
def _ser_callout(concrete, media_ids):
    return {
        "kind": concrete.kind,
        "heading": concrete.heading,
        "body": concrete.body,
        "numbered": concrete.numbered,
    }
```

- [ ] **Step 4: Update the validator**

`courses/transfer/payloads.py`, in `_val_callout`. Join the new constant onto the existing function-local import (that import is local to avoid a cycle; a module-level one would reintroduce it), and seed the key before `_exact_keys`:

```python
def _val_callout(data, elid, media_kinds):
    from courses.models import KIND_DEFAULT_NUMBERED
    from courses.models import CalloutElement

    # `numbered` is optional for pre-v13 archives (the size/width pattern). This MUST
    # run before _exact_keys, which is the only reason `kind` is not yet validated
    # here -- so the lookup has to be TOTAL: `kind` may be absent (a bare data["kind"]
    # would raise KeyError where the contract is a translated TransferError) or a list
    # or dict (which would make .get() raise TypeError: unhashable type).
    _kind = data.get("kind")
    data.setdefault(
        "numbered",
        KIND_DEFAULT_NUMBERED.get(_kind, True) if isinstance(_kind, str) else True,
    )
    _exact_keys(data, ["kind", "heading", "body", "numbered"], _("callout data"))
    check_str(data["kind"], _("kind"))
    check_str(data["heading"], _("heading"), max_length=120)
    check_str(data["body"], _("body"))
    check_bool(data["numbered"], "numbered")
    if data["kind"] not in CalloutElement.Kind.values:
        _err(_("Element '%(el)s' has an unknown callout kind."), el=elid)
    return set()
```

- [ ] **Step 5: Update the builder**

`courses/transfer/importer.py:556`:

```python
def _build_callout(data, assets):
    el = CalloutElement(
        kind=data.get("kind", "example"),
        heading=data.get("heading", ""),
        body=data["body"],
        # Subscript, not .get(): TWO independent guarantees, one per caller family.
        # Archive import runs validate_document, so _val_callout's setdefault has
        # seeded the key on this same dict. Duplicate/paste run NO validator
        # (graft_elements -> _run_import -> _create_elements), so there the key exists
        # only because _ser_callout writes it -- which is why the exporter change must
        # land first.
        numbered=data["numbered"],
    )
    return _clean_save(el), ()
```

- [ ] **Step 6: Bump `FORMAT_VERSION` and update the eight pinned assertions**

`courses/transfer/schema.py:14` → `FORMAT_VERSION = 13`.

Mechanical, expected churn — not regressions:

| File | Line | Change |
| --- | --- | --- |
| `courses/tests/test_beforeafter_transfer.py` | 169 | `== 12` → `== 13` |
| `courses/tests/test_image_size_transfer.py` | 44 | `== 12` → `== 13` |
| `tests/test_link_transfer.py` | 54 | `== 12` → `== 13` |
| `tests/test_table_transfer.py` | 299 | `== 12` → `== 13` |
| `tests/test_tabs_transfer.py` | 62 | `== 12` → `== 13` |
| `tests/test_transfer_schema.py` | 57 | `== 12` → `== 13` |
| `tests/test_transfer_export.py` | 222 | `manifest["format_version"] == 12` → `13` |
| `courses/tests/test_callout_transfer.py` | 34 | add `"numbered": False` to the expected dict |

For the last one: the assertion is a full dict equality on `_ser_callout`'s output, and it breaks on Step 3 rather than on the bump. **Keep it a full dict equality** — relaxing it to a key-subset check would destroy the only assertion pinning the exact export payload, and dropping `numbered` from the serializer to "fix" it is precisely the defect Step 1's first test exists to catch. Set the expected value to whatever the fixture's callout carries.

**Do NOT touch `courses/tests/test_nested_question_transfer.py:260`**, which passes `format_version=12` as a *legacy archive fixture*. That 12 is the point of the test.

- [ ] **Step 7: Run the transfer suite**

```bash
uv run pytest courses/tests/test_callout_transfer.py courses/tests/test_beforeafter_transfer.py courses/tests/test_image_size_transfer.py courses/tests/test_nested_question_transfer.py tests/test_link_transfer.py tests/test_table_transfer.py tests/test_tabs_transfer.py tests/test_transfer_schema.py tests/test_transfer_export.py -v
```

Expected: all pass.

- [ ] **Step 8: Test the duplicate path explicitly**

Append to `courses/tests/test_callout_transfer.py`:

```python
def test_duplicating_an_unnumbered_callout_keeps_it_unnumbered():
    """Duplicate and paste round-trip through build_element_export -> graft_elements,
    which runs NO validator. Mutant: drop `numbered=` from _build_callout -> the copy
    comes back numbered. This is the consequence a user hits first."""
    from courses import builder
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    el = CalloutElement.objects.create(kind="example", numbered=False, body="<p>x</p>")
    join = add_element(unit, el)
    unit.refresh_from_db()

    _unit, new_join = builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    assert new_join.content_object.numbered is False
```

Signature verified: `duplicate_element(course, element_pk, unit_token)` returns `(unit, new_join)` (`courses/builder.py:929`).

- [ ] **Step 9: Falsify**

1. Drop the `setdefault` → `test_a_pre_v13_payload_imports_with_the_per_kind_default` FAILS with `TransferError`.
2. Replace the total lookup with `KIND_DEFAULT_NUMBERED.get(data["kind"], True)` → `test_a_payload_with_no_kind_still_fails_cleanly` FAILS with `KeyError`.
3. Drop `"numbered"` from `_ser_callout` → the serializer test and `test_duplicating_...` (with `KeyError`) FAIL.
4. Drop `numbered=` from `_build_callout` → `test_the_builder_round_trips_numbered_false` FAILS.

- [ ] **Step 10: Commit**

```bash
git add courses/transfer/ courses/tests/ tests/
git commit -m "feat(callout): carry numbered through transfer, FORMAT_VERSION 13"
```

---

### Task 9: Seed command, i18n, and help documentation

**Files:**
- Modify: `courses/management/commands/seed_demo_course.py:246-253`
- Modify: `locale/pl/LC_MESSAGES/django.po` and `django.mo`
- Modify: `docs/help/course-admin/content-editors.md` and `content-editors.pl.md`
- Test: append to `courses/tests/test_callout_numbering_render.py`

**Interfaces:**
- Consumes: everything above. Produces nothing new.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_callout_numbering_render.py`:

```python
def test_the_seeded_demo_tip_callout_is_not_numbered():
    """The only production CalloutElement construction site outside _build_callout.
    A seeded Tip arriving numbered contradicts D2 in the very course the help
    screenshots are taken against.

    Mutant: drop `numbered=False` from seed_demo_course._callout -> this fails.
    """
    import inspect

    from courses.management.commands import seed_demo_course

    src = inspect.getsource(seed_demo_course.Command._callout)
    assert "numbered=False" in src
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_callout_numbering_render.py::test_the_seeded_demo_tip_callout_is_not_numbered -v
```

Expected: FAIL.

- [ ] **Step 3: Sweep the seed command**

`courses/management/commands/seed_demo_course.py`, in `_callout`:

```python
    def _callout(self, unit):
        self._upsert(
            unit,
            CalloutElement,
            kind="tip",
            # Explicit: the model default is a flat True, and only the migration and
            # the importer consult the per-kind map. Every production construction
            # site must pass this.
            numbered=False,
            heading="Remember",
            body="<p>Order of operations matters.</p>",
        )
```

- [ ] **Step 4: Confirm there is no third construction site**

```bash
grep -rn "CalloutElement(" --include="*.py" . | grep -v "/.venv/" | grep -v "/tests/" | grep -v "/migrations/"
grep -rn "CalloutElement.objects.create" --include="*.py" . | grep -v "/.venv/" | grep -v "/tests/"
```

Expected: only `courses/transfer/importer.py:556` and the seed command. If a third appears, give it an explicit `numbered` and note it in the commit message.

- [ ] **Step 5: Extract and translate the new string**

```bash
uv run python manage.py makemessages -l pl
```

Open `locale/pl/LC_MESSAGES/django.po`, find `msgid "Number this callout"` and set:

```
msgid "Number this callout"
msgstr "Numeruj tę ramkę"
```

**"Ramka"** is the established Polish term for a callout in this catalogue (`msgid "Callout"` → `msgstr "Ramka"`), matching the sibling labels `Rodzaj` / `Nagłówek` on the same form.

Then check for a fuzzy pre-fill: if `makemessages` marked the new entry `#, fuzzy` with a wrong `msgstr` merged from a similar msgid, clearing it takes **two** deletions — the `#, fuzzy` line *and* the wrong `msgstr`. Verify no `#, fuzzy` remains on this entry.

```bash
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 6: Update both help pages**

`docs/help/course-admin/content-editors.md:115-121` describes the callout editor's controls. Extend the sentence listing them, e.g. after the Heading clause:

> …and a **Number this callout** checkbox (on by default; callouts numbered this way share one running sequence per unit, and Notes and Tips in existing content start unnumbered).

Make the equivalent edit to `docs/help/course-admin/content-editors.pl.md` **in the same commit**. Nothing in the test suite catches twin-file drift here.

- [ ] **Step 7: Run the affected tests**

```bash
uv run pytest courses/tests/test_callout_numbering_render.py courses/tests/test_help.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add courses/management/commands/seed_demo_course.py locale/ docs/help/ courses/tests/
git commit -m "feat(callout): seed sweep, Polish translation, help pages"
```

---

### Task 10: The e2e round trip, then the branch gate

**Files:**
- Create: `tests/test_e2e_callout_numbering.py`
- Test: itself

**Interfaces:**
- Consumes: everything.

- [ ] **Step 1: Write the failing e2e**

Create `tests/test_e2e_callout_numbering.py`, following the structure of an existing editor e2e (read `tests/test_e2e_editor.py` first for the fixture and login idiom, and reuse its helpers rather than inventing new ones):

```python
"""R2: saving a callout without touching the checkbox must not un-number it.

An unchecked checkbox transmits NOTHING, so a POST missing the key is
indistinguishable from a deliberate untick -- the same failure shape as the
existing `el_title` trap, where a POST missing that key blanks the element title.

THE INSTRUMENT IS THE RE-OPENED FORM'S CHECKBOX STATE, not the number visible in
the preview: a visible-number assertion also goes red for a missing context site
and for a dropped barrier key, so its failure would not identify R2.
"""

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_saving_a_callout_without_touching_the_checkbox_keeps_it_numbered(page, live_server):
    # 1. Seed a lesson unit with one numbered callout and open the editor.
    # 2. Click the callout row's edit button; wait for the form.
    # 3. Assert the checkbox is checked.
    # 4. Change ONLY the heading input; do not touch the checkbox.
    # 5. Save; wait for the fragment swap to settle.
    # 6. Re-open the same callout's form.
    # 7. Assert the checkbox is STILL checked.
    # 8. Additionally re-read the row: CalloutElement.objects.get(...).numbered is True.
    ...
```

Fill in each numbered comment with real Playwright calls copied from the closest existing editor e2e. Sync on conditions (`expect(...).to_be_visible()`, `wait_for_selector`), never on `sleep`.

- [ ] **Step 2: Run it — e2e needs the marker**

```bash
uv run pytest tests/test_e2e_callout_numbering.py -m e2e -v
```

`-m e2e` is mandatory: `addopts` carries `-m 'not e2e'`, so without it the file is silently deselected and pytest exits 5 having run nothing.

Expected: FAIL until Step 1's body is complete; then PASS.

- [ ] **Step 3: Falsify**

Remove `"numbered"` from `CalloutElementForm.Meta.fields` → the e2e must FAIL at step 7 with the checkbox unchecked. Restore.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_callout_numbering.py
git commit -m "test(callout): e2e round trip for the numbering checkbox"
```

- [ ] **Step 5: Branch gate — the full suite**

Only now, once every task is committed:

```bash
uv run pytest
```

Expected: green. **Grep the summary line** rather than trusting the exit code — a backgrounded run in this repo has reported exit 0 with `1 failed`.

- [ ] **Step 6: Branch gate — e2e**

```bash
uv run pytest -m e2e -n 2
```

`-n 2`, not `-n 8`: the e2e bottleneck is TRUNCATE teardown, and more workers is slower.

- [ ] **Step 7: Branch gate — lint, format, migrations**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
```

`--no-cache` is required: a stale `noqa` warning is cached away. `ruff format --check` is a separate gate from `ruff check`.

- [ ] **Step 8: Re-check the migration against graph head**

If any migration landed on `master` while this branch was open, rebase and confirm the new migration's `dependencies` still points at the real head. A restore pinned to a superseded node runs backwards and fails intermittently under `-n auto`.

- [ ] **Step 9: Regenerate the `.mo` if the branch was rebased**

A long-lived branch produces a binary `.mo` conflict on rebase. Never merge the binary — re-run `uv run python manage.py compilemessages -l pl` and commit the regenerated file.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
| --- | --- |
| §1 Data model (field, `KIND_DEFAULT_NUMBERED`, `kind_label`, `display_heading`) | 1 |
| §2 Migration (AddField + backfill, `RunPython.noop`, graph head) | 2 |
| §3 Walk: contract, pre-order, accessors, `seen`, early-out, dangling GFK, raise, query shape | 3, 4 |
| §4 Render (single-line template, number span, D7, `element=None` guard) | 5 |
| §5 Context wiring (four sites, `page` barrier, six→seven comment, key-set churn) | 6 |
| §6 Editor form (`Meta.fields`, checkbox markup, three churn tests) | 7 |
| §7 Transfer (5 steps, order constraint, `FORMAT_VERSION` 13, 8 churn assertions) | 8 |
| §8 Testing — mutants 1-14 | distributed: 1→T3, 2→T3, 3→T6, 4→T6, 5→T2, 6→T8, 7→T5, 8→T5, 9→T1, 10→T4, 11→T4, 12→T4, 13→T7, 14→T7 |
| §9 i18n + help twins | 9 |
| §10 R1-R4 | R1→T6 (per-site tests), R2→T7+T10, R3→T4 (query pins), R4→accepted, no code |
| Seed sweep (production construction sites) | 9 |

**Placeholder scan:** the only `...` is the e2e body in Task 10 Step 1, which is deliberate — the steps are enumerated and the instruction is to copy the idiom from the existing editor e2e rather than invent a second one. Three values are marked for transcription from an observed run rather than guessed: `EXPECTED_QUERIES` (T4 S5), the unnumbered heading literal (T5 S1), and the migration number (T2 S1). Each has an explicit step producing it.

**Type consistency:** `callout_numbers(node) -> dict[int, int]` keyed by `Element.pk` is used identically in Tasks 3-6. `ACCESSORS` is defined in Task 3 and asserted against `builder.CONTAINER_MODELS` in Task 4. The template context key is `number` (singular, an `int`) in Tasks 5-6; the context/`page` key is `callout_numbers` (a dict) in Tasks 4-6. `kind_label` is a property in Task 1 and consumed as `el.kind_label` in Task 5.
