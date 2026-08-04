# Element duplicate (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the unit editor a ⧉ *duplicate* control that deep-copies any element — including a populated container — directly below the source, in the source's own slot.

**Architecture:** The copy round-trips through the existing transfer layer, exactly as `builder.duplicate_unit` does, but scoped to one element subtree instead of a whole unit. That needs one new entry point per side: an export that substitutes `build_export`'s hard-coded top-level roots query, and an import that grafts into an *existing* unit instead of creating a node. The builder service then sets the copy's scope (the graft cannot) and positions it. The view answers with the editor+preview fragment pair every editor operation already returns, plus an "open these containers" set so a copy born inside tab 2 is visible.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, server-rendered templates, vanilla JS (no framework).

**Spec:** `docs/superpowers/specs/2026-08-03-element-clipboard-design.md`. This plan implements **PR1 only**. PR2 (the select / move-here / copy-here clipboard) gets its own plan once PR1 lands.

## Global Constraints

- **Tooling is not on PATH.** Every Python command runs through `uv run` — `uv run pytest`, `uv run ruff`, `uv run python`. A bare `pytest` will not resolve.
- **Worktree:** all work happens in `C:/Users/krzys/Documents/Python/own/libli/.claude/worktrees/element-clipboard` on branch `feat/element-clipboard`. Never `cd` to the main checkout.
- **One pytest invocation at a time.** Test databases are shared per `DATABASE_URL`; two concurrent runs in different worktrees corrupt each other.
- **`pyproject.toml` already sets `addopts = "-q -m 'not e2e'"`.** Do not pass a second `-q` — it suppresses the summary line entirely. e2e tests are deselected by default and need an explicit `-m e2e`.
- **`MAX_NEST_DEPTH = 4`** (`courses/builder.py:25`), a top-level element is depth 1. PR1 changes no nesting rule — a duplicate lands in the source's own slot, so depth is unchanged and no admissibility check applies.
- **No hardcoded test passwords.** Use `tests.factories.TEST_PASSWORD`.
- **Run `uv run ruff format` before every commit step**, not only in Task 10. `ruff format --check .` runs at the end, and it fails on code committed six tasks earlier just as readily as on the last task's.
- **Module-level translatable strings use `gettext_lazy`;** in-function strings use `gettext as _`.
- **`Element.order` is `OrderField(for_fields=["unit"])`** (`courses/models.py:319`) — unit-wide, so a freshly created join is born with `max+1` and sorts last within its group.
- **Editor-context errors never use `_op_error`.** `editor.js` swaps only `[data-scope]` elements and `_op_error.html` has no such wrapper, so an `_op_error` 422 is invisible in the editor. Every editor-context error renders through `_render_editor_fragments(..., status=…, error=…)`.

---

## File Structure

**Created:**
- `.env` — worktree-local test DB config (git-ignored)
- `tests/test_transfer_element_scope.py` — the two new transfer entry points
- `tests/test_builder_duplicate_element.py` — the service
- `tests/test_editor_error_channel.py` — the editor `error` render slot
- `tests/test_element_duplicate_view.py` — view, URL, button
- `tests/test_editor_open_slots.py` — `slot_key`, ancestor set, `<details>` markup
- `tests/test_e2e_editor_force_open.py` — the one JS behaviour a template test cannot cover

**Modified:**
- `courses/transfer/export.py` — `build_export(roots_by_unit=…)`; new `build_element_export`
- `courses/transfer/importer.py` — new `graft_elements`
- `courses/builder.py` — new `duplicate_element`, `slot_key`, `ancestor_slots`
- `courses/views_manage.py` — new `element_duplicate` view; `error` + `open_slots` context keys on **both** context builders
- `courses/urls.py` — one path
- `courses/templatetags/courses_manage_extras.py` — `slot_key` filter
- `templates/courses/manage/editor/_editor_scope.html` — error render slot
- `templates/courses/manage/editor/editor.html` — remove the now-duplicate error block
- `templates/courses/manage/editor/_element_row.html` — `<details>` force-open on both container branches
- `templates/courses/manage/editor/_element_row_controls.html` — the ⧉ form
- `courses/static/courses/js/editor.js` — `applyStoredTabs` skip

**Responsibility split:** the transfer layer knows how to serialise and materialise; `builder` owns transactions, locking, tokens and ordering; `views_manage` owns HTTP status and rendering; templates own markup only and never re-derive a rule.

---

### Task 1: Worktree test environment

The worktree has no `.env`, so every test run fails to connect. Each worktree needs its **own** database name — a shared one means two worktrees' test runs destroy each other's databases mid-run.

**Files:**
- Create: `.env` (git-ignored; `.env.example` is the template)

- [ ] **Step 1: Create `.env`**

The sibling worktree's file is the better source — it carries working local credentials that
`.env.example` does not:

```bash
cp "C:/Users/krzys/Documents/Python/own/libli/.claude/worktrees/spoiler-rule/.env" \
   "C:/Users/krzys/Documents/Python/own/libli/.claude/worktrees/element-clipboard/.env"
```

If that file is gone, fall back to `cp .env.example .env` and fill in the database
credentials by hand — the example ships placeholders, so the copy above is the fast path,
not the only one.

- [ ] **Step 2: Give this worktree a unique database name**

Edit `.env` and change the database name at the end of `DATABASE_URL` to `libli_elclip`
(the copied file ends `/libli_spoiler`; a from-`.env.example` file will differ). Leave user,
password, host and port as they are. Two worktrees sharing one name means each run drops the
other's databases mid-flight.

- [ ] **Step 3: Check the connection before running any test**

Run: `uv run python manage.py check --database default`
Expected: `System check identified no issues`. A `connection refused` means Postgres is not
running; `role ... does not exist` or `password authentication failed` means the copied
credentials are wrong for this machine — fix `.env` before going further, because pytest's
failure mode for both is a wall of errors that looks like broken code.

- [ ] **Step 3b: Verify the test environment by running an existing test**

Run: `uv run pytest tests/test_builder_duplicate_unit.py -v`
Expected: all tests PASS. If you see `DuplicateDatabase`, a previous run left an idle connection — find and kill the stray pytest process, then re-run.

- [ ] **Step 4: Confirm the branch before doing anything else**

Run: `git branch --show-current`
Expected: `feat/element-clipboard`. If it is anything else, stop — you are in the wrong worktree.

No commit: `.env` is git-ignored.

---

### Task 2: Element-scoped export

`build_export` hard-codes "roots are the top-level joins" (`courses/transfer/export.py:564-570`). An element-scoped export is that one query replaced by a single supplied join — everything else (`_ordered_nodes`, the manifest, `link_nodes`, passes 3–5) is reused untouched. `walk_unit_joins` needs **no** change: it already takes its roots as an argument, and its `emit` closure must be neither extracted nor re-implemented.

**Files:**
- Modify: `courses/transfer/export.py:529-531` (signature), `:564-570` (roots query), and append `build_element_export`
- Test: `tests/test_transfer_element_scope.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `export.build_element_export(unit, root_join) -> (document, media_assets, problems)`. `document` is the transfer document dict; `media_assets` is a list of `(mid, asset, placeholder)` triples; `problems` is a list — non-empty means a dangling GFK.

- [ ] **Step 1: Write the failing test**

Create `tests/test_transfer_element_scope.py`:

```python
import pytest

from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.export import build_element_export
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _unit_with_tabs():
    """A unit holding: a loose Text, and a Tabs whose second tab has one Text child."""
    course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>loose</p>")
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>tabbed</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    return course, unit, tabs_join, t2


def test_element_export_covers_the_subtree_and_nothing_else():
    _course, unit, tabs_join, t2 = _unit_with_tabs()

    document, _media, problems = build_element_export(unit, tabs_join)

    assert problems == []
    # Exactly the container plus its one child -- the loose Text is NOT exported.
    assert len(document["elements"]) == 2
    types = sorted(e["type"] for e in document["elements"])
    assert types == ["tabs", "text"]
    # The subtree root is parentless in the payload; the child carries its slot.
    root = [e for e in document["elements"] if not e.get("parent")]
    child = [e for e in document["elements"] if e.get("parent")]
    assert len(root) == 1 and root[0]["type"] == "tabs"
    assert len(child) == 1 and child[0]["tab"] == t2


def test_every_exported_element_points_at_the_single_node_id():
    """The coupling graft_elements actually depends on: it fabricates
    node_map = {document["nodes"][0]["id"]: unit}, and _create_elements then
    looks each element's "unit" key up in that map. Asserting only
    len(nodes) == 1 would duplicate build_element_export's own assert, which
    fires first and would mask this test."""
    _course, unit, tabs_join, _t2 = _unit_with_tabs()

    document, _media, _problems = build_element_export(unit, tabs_join)

    node_id = document["nodes"][0]["id"]
    assert {e["unit"] for e in document["elements"]} == {node_id}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_transfer_element_scope.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_element_export'`.

- [ ] **Step 3: Add the roots override to `build_export`**

In `courses/transfer/export.py`, change the signature at `:529-531` to:

```python
def build_export(
    course,
    node=None,
    source_host="",
    *,
    drop_missing_media=True,
    report=None,
    roots_by_unit=None,
):
```

Then replace `:560-570` with the block below. **The range starts at 560, not 564** — the
four-line `# Query only TOP-LEVEL joins;` comment sits at `:560-563` and is re-emitted inside
the replacement, so replacing only 564-570 leaves it duplicated:

```python
        # Query only TOP-LEVEL joins; walk_unit_joins expands each container
        # element's children inline (tabs, two_column, spoiler -- parents before
        # children), so every element is visited EXACTLY ONCE and no child needs
        # a recursive query here.
        #
        # `roots_by_unit` overrides that choice of roots and nothing else. It is
        # what makes an ELEMENT-scoped export possible without a second walk:
        # walk_unit_joins already takes its roots as an argument, so handing it
        # {unit.pk: [one_join]} yields that join as the first emission and its
        # subtree after it, through the very same `emit` closure. Do not add a
        # root parameter to walk_unit_joins -- it does not need one.
        if roots_by_unit is not None:
            joins_by_unit = dict(roots_by_unit)
        else:
            joins_by_unit = {}
            for join in (
                Element.objects.filter(unit_id__in=unit_pks, parent__isnull=True)
                .order_by("unit_id", "order", "pk")
                .prefetch_related("content_object")
            ):
                joins_by_unit.setdefault(join.unit_id, []).append(join)
```

- [ ] **Step 4: Add `build_element_export` at the end of `courses/transfer/export.py`**

```python
def build_element_export(unit, root_join):
    """Export ONE element subtree from `unit`, for an in-process copy.

    A single substitution on build_export -- the roots query -- not a new export
    path. `node=unit` is what keeps document["nodes"] a single entry, which
    importer.graft_elements relies on when it fabricates its node_map, so the
    assertion below guards a real coupling rather than restating the obvious.

    `drop_missing_media=False` matches duplicate_unit: a missing media file must
    not silently thin the copy. Returns `problems` to the caller rather than
    discarding it (duplicate_unit drops it) -- with media dropping disabled, a
    non-empty `problems` means exactly one thing, a dangling GFK, and the caller
    is expected to refuse the copy.
    """
    _manifest, document, media_assets, problems = build_export(
        unit.course,
        node=unit,
        drop_missing_media=False,
        roots_by_unit={unit.pk: [root_join]},
    )
    assert len(document["nodes"]) == 1, (
        "an element-scoped export must contain exactly one unit node"
    )
    return document, media_assets, problems
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_transfer_element_scope.py -v`
Expected: both PASS.

- [ ] **Step 6: Verify the override did not change whole-unit exports**

Run: `uv run pytest tests/test_builder_duplicate_unit.py tests/test_export_depth3.py -v`
Expected: all PASS. These exercise `build_export` with `roots_by_unit=None`, i.e. the untouched path.

- [ ] **Step 7: Commit**

```bash
git add courses/transfer/export.py tests/test_transfer_element_scope.py
git commit -m "feat(transfer): export a single element subtree via a roots override"
```

---

### Task 3: Graft an element subtree into an existing unit

`materialize_duplicate` calls `_create_nodes` and returns a `ContentNode` (`courses/transfer/importer.py:1093-1119`). Grafting into an *existing* unit must create no node, must not rewrite links, and must return the created root **join**.

**Files:**
- Modify: `courses/transfer/importer.py` — append `graft_elements`
- Test: `tests/test_transfer_element_scope.py` (append)

**Interfaces:**
- Consumes: `export.build_element_export` from Task 2.
- Produces: `importer.graft_elements(document, media_map, unit) -> Element` (the created root join row, sitting at `parent=None, tab_id=""` — the caller sets its scope).

- [ ] **Step 1: Write the failing test**

Add these two lines to the **imports at the top** of `tests/test_transfer_element_scope.py`
(not mid-file — ruff rejects a module-level import after code):

```python
from courses.models import ContentNode
from courses.transfer.importer import graft_elements
```

Then append the tests (both imports are already added above — do not repeat them):

```python
def test_graft_creates_the_subtree_in_the_same_unit_and_returns_its_root():
    _course, unit, tabs_join, t2 = _unit_with_tabs()
    document, media_assets, _problems = build_element_export(unit, tabs_join)
    media_map = {mid: asset for (mid, asset, _ph) in media_assets}
    before = unit.elements.count()

    new_root = graft_elements(document, media_map, unit)

    assert unit.elements.count() == before + 2  # container + its child
    assert new_root.unit_id == unit.pk
    assert new_root.pk != tabs_join.pk
    assert isinstance(new_root.content_object, TabsElement)
    # The graft does NOT place it: the payload root has no parent, and
    # _create_elements' second pass skips parentless rows. The builder service
    # is what sets the scope -- this assertion pins that contract.
    assert new_root.parent_id is None
    assert new_root.tab_id == ""
    # The child came across and kept its slot.
    child = new_root.children.get()
    assert child.tab_id == t2
    assert child.content_object.body == "<p>tabbed</p>"


def test_graft_does_not_create_a_content_node():
    _course, unit, tabs_join, _t2 = _unit_with_tabs()
    document, media_assets, _problems = build_element_export(unit, tabs_join)
    media_map = {mid: asset for (mid, asset, _ph) in media_assets}
    nodes_before = ContentNode.objects.count()

    graft_elements(document, media_map, unit)

    assert ContentNode.objects.count() == nodes_before
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_transfer_element_scope.py -v`
Expected: FAIL — `ImportError: cannot import name 'graft_elements'`.

- [ ] **Step 3: Add `graft_elements` at the end of `courses/transfer/importer.py`**

```python
def graft_elements(document, media_map, unit):
    """Graft an element-scoped document's subtree into an EXISTING unit.

    Mirrors materialize_duplicate's work() with three differences, each forced
    by grafting into a unit that already exists:

    1. No `_create_nodes`. The node_map is fabricated over `unit`, because
       _create_elements looks the unit up as node_map[el["unit"]].
    2. No `_rewrite_links`, because for an element-scoped export that call is
       provably a NO-OP -- not because it would corrupt anything. build_export
       emits link_nodes filtered to targets INSIDE the exported node set
       (`{pk: node_ids[pk] for pk in referenced if pk in node_ids}`,
       export.py:781-783), and here that set is exactly {unit}. So link_nodes
       names at most unit.pk, the fabricated node_map maps it back to the SAME
       unit, and _rewrite_links builds the identity mapping {unit.pk: unit.pk}
       (or an empty one). A link to any node outside the export never enters
       `mapping` and, under on_missing="keep", is left alone. Skipped as dead
       work.
    3. It returns the created root JOIN, not a ContentNode.

    The root is re-derived as the single created join with `parent_id is None`
    -- _create_elements' second pass has already set `parent` in memory for
    every child. Deliberately NOT `created[0]`, and deliberately not a zip
    against document["elements"]: both would rest on payload order surviving
    into the returned list, which nothing states or tests.

    Keeps _run_import's wrapper, so any failure rolls back and is normalised to
    TransferError.
    """

    def work():
        node_map = {document["nodes"][0]["id"]: unit}
        created = _create_elements(document, node_map, media_map)
        roots = [join for join in created if join.parent_id is None]
        if len(roots) != 1:
            raise TransferError(
                _("An element copy must produce exactly one root element.")
            )
        return roots[0]

    return _run_import(work, created_files=[])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_transfer_element_scope.py -v`
Expected: all four PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/transfer/importer.py tests/test_transfer_element_scope.py
git commit -m "feat(transfer): graft an element subtree into an existing unit"
```

---

### Task 4: `builder.duplicate_element`

The service that ties the two halves together, sets the scope the graft leaves unset, and positions the copy below its source.

**Files:**
- Modify: `courses/builder.py` — append `duplicate_element` after `duplicate_unit`
- Test: `tests/test_builder_duplicate_element.py`

**Interfaces:**
- Consumes: `export.build_element_export` (Task 2), `importer.graft_elements` (Task 3).
- Produces: `builder.duplicate_element(course, element_pk, unit_token) -> (unit, new_join)`. Raises `ConflictError` on a stale token or vanished element; raises `TransferError` when the subtree is damaged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_builder_duplicate_element.py`:

```python
import pytest

from courses.builder import ConflictError
from courses.builder import duplicate_element
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _tok(unit):
    return unit.updated.isoformat()


def _unit_with_populated_tabs():
    """Tabs with a child in tab 2, sitting between two loose Text elements."""
    course, unit = make_course_with_unit()
    first = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>first</p>")
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>tabbed</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    last = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>last</p>")
    )
    return course, unit, first, tabs_join, last, t2


def _top_level(unit):
    return list(unit.elements.filter(parent__isnull=True).order_by("order", "pk"))


def test_duplicate_lands_directly_below_the_source():
    course, unit, first, tabs_join, last, _t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, tabs_join.pk, _tok(unit))

    order = [e.pk for e in _top_level(unit)]
    assert order == [first.pk, tabs_join.pk, new_join.pk, last.pk]


def test_duplicate_of_the_first_element_lands_second():
    """Boundary: idx + 1 == 1, with nothing above the source."""
    course, unit, first, tabs_join, last, _t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, first.pk, _tok(unit))

    order = [e.pk for e in _top_level(unit)]
    assert order == [first.pk, new_join.pk, tabs_join.pk, last.pk]


def test_duplicate_of_the_last_element_lands_last():
    """Boundary: the copy lands at the tail of the group. Note place_element
    still renumbers -- with unit-wide orders the copy is born at max+1 and the
    top-level group is compacted to 0..3 -- so this is not a no-write case."""
    course, unit, first, tabs_join, last, _t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, last.pk, _tok(unit))

    order = [e.pk for e in _top_level(unit)]
    assert order == [first.pk, tabs_join.pk, last.pk, new_join.pk]


def test_duplicate_copies_the_whole_subtree_with_fresh_rows():
    course, unit, _first, tabs_join, _last, t2 = _unit_with_populated_tabs()

    _unit, new_join = duplicate_element(course, tabs_join.pk, _tok(unit))

    assert new_join.pk != tabs_join.pk
    assert new_join.content_object.pk != tabs_join.content_object.pk
    child = new_join.children.get()
    assert child.pk != tabs_join.children.get().pk
    assert child.tab_id == t2
    assert child.content_object.body == "<p>tabbed</p>"


def test_duplicate_of_a_nested_child_stays_in_its_own_slot():
    """The graft returns a parentless root; without the scope-setting step the
    copy silently lands at TOP LEVEL instead of inside the tab."""
    course, unit, _first, tabs_join, _last, t2 = _unit_with_populated_tabs()
    source_child = tabs_join.children.get()

    _unit, new_join = duplicate_element(course, source_child.pk, _tok(unit))

    assert new_join.parent_id == tabs_join.pk
    assert new_join.tab_id == t2
    siblings = list(
        Element.objects.filter(unit=unit, parent=tabs_join, tab_id=t2)
        .order_by("order", "pk")
        .values_list("pk", flat=True)
    )
    assert siblings == [source_child.pk, new_join.pk]


def test_duplicate_deep_copies_related_rows_and_reuses_the_media_row():
    """The image must live INSIDE the duplicated subtree. An asset created beside
    it is never serialised, so media_map is empty and both media assertions are
    true before duplicate_element is even called."""
    course, unit = make_course_with_unit()
    asset = make_image_asset(course, "pic.png")
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    question = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    Choice.objects.create(question=question, text="a", is_correct=True)
    Choice.objects.create(question=question, text="b")
    Element.objects.create(
        unit=unit, content_object=question, parent=tabs_join, tab_id=t1
    )
    src_image = ImageElement.objects.create(media=asset, alt="a", figcaption="")
    Element.objects.create(
        unit=unit, content_object=src_image, parent=tabs_join, tab_id=t2
    )
    choices_before = Choice.objects.count()

    _unit, new_join = duplicate_element(course, tabs_join.pk, _tok(unit))

    assert Choice.objects.count() == choices_before * 2  # related rows deep-copied
    assert MediaAsset.objects.filter(course=course).count() == 1  # ROW reused
    copied_image = next(
        child.content_object
        for child in new_join.children.all()
        if isinstance(child.content_object, ImageElement)
    )
    # Compare ImageElement to ImageElement. Comparing it to `asset.pk` would be
    # comparing pks from two unrelated sequences -- vacuous, and able to collide.
    assert copied_image.pk != src_image.pk  # a fresh ImageElement...
    assert copied_image.media_id == asset.pk  # ...pointing at the SAME asset row


def test_duplicate_bumps_the_unit_token():
    course, unit, _first, tabs_join, _last, _t2 = _unit_with_populated_tabs()
    before = unit.updated

    duplicate_element(course, tabs_join.pk, _tok(unit))

    unit.refresh_from_db()
    assert unit.updated > before


def test_duplicate_rejects_a_stale_token():
    course, unit, _first, tabs_join, _last, _t2 = _unit_with_populated_tabs()

    with pytest.raises(ConflictError):
        duplicate_element(course, tabs_join.pk, "2020-01-01T00:00:00+00:00")


def test_duplicate_refuses_a_damaged_subtree_rather_than_copying_it_partially():
    """build_export records a dangling GFK in `problems` and CONTINUES, so
    without an explicit check the copy silently loses the broken element and
    everything under it, and still returns 200."""
    course, unit, _first, tabs_join, _last, _t2 = _unit_with_populated_tabs()
    child = tabs_join.children.get()
    # Repoint object_id; do NOT delete the concrete row. Every concrete element
    # declares GenericRelation(Element), so deleting it CASCADES the join away --
    # leaving no join at all rather than a dangling one, an export with no
    # `problems`, and a test that fails for the wrong reason. This is the
    # `_make_broken_join` idiom from tests/test_transfer_export.py:342-351, whose
    # docstring documents the same trap.
    Element.objects.filter(pk=child.pk).update(object_id=9_999_999)

    with pytest.raises(TransferError):
        duplicate_element(course, tabs_join.pk, _tok(unit))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_builder_duplicate_element.py -v`
Expected: FAIL — `ImportError: cannot import name 'duplicate_element'`.

- [ ] **Step 3: Widen `_locked_element`'s except clause**

`courses/builder.py:919` catches only `Element.DoesNotExist`, so `Element.objects.get(pk="abc")`
raises `ValueError` and escapes as a 500. Its sibling `_locked_element_in_unit` (`:882-886`)
already catches `(Element.DoesNotExist, ValueError, TypeError)`. Make them consistent:

```python
    except (Element.DoesNotExist, ValueError, TypeError):
        raise ConflictError() from None
```

This also hardens the existing `element_move` / `element_delete` paths, which 500 on the same
input today.

**The guard for this lives in Task 6**, not here: it needs
`tests/test_element_duplicate_view.py`, which does not exist until Task 6 Step 1 creates it,
and it needs the endpoint. Task 6's listing already contains
`test_duplicate_409s_on_a_non_numeric_element_pk` — do not add it here, and do not skip it
there. The token path is deliberately left alone: `_check_token`'s `parse_datetime`
(`courses/builder.py:175-178`) raises `ValueError` on a well-formed-but-invalid timestamp and
runs outside this service's `try`, so a garbage `unit_token` is still a 500. That is a
pre-existing wart on a hand-crafted-only path, shared with every element op, and out of scope
for PR1.

- [ ] **Step 3b: Run the shared helper's existing callers before going further**

`_locked_element` has exactly two other callers: `reorder_element` (`courses/builder.py:395`)
and `delete_element` (`:460`). (`save_element` uses the *sibling* `_locked_element_in_unit`,
whose `except` is already wide, so it is unaffected.) Widening this one must not change the
two real callers' behaviour.

Run: `uv run pytest tests/test_element_editor_ops.py tests/test_manage_element_ops.py tests/test_builder_duplicate_unit.py -v`
Expected: all PASS.

- [ ] **Step 4: Add the gettext import to `courses/builder.py`**

The module does not currently import it — `builder.py`'s existing exception messages are
untranslated plain strings, but this one reaches the author through the editor's error slot.
Add to the imports at the top of the file:

```python
from django.utils.translation import gettext as _
```

Use `gettext`, not `gettext_lazy`: the string is built inside a function at call time, so the
active language is already correct and a lazy proxy would only defer the same result.

- [ ] **Step 5: Implement `duplicate_element` in `courses/builder.py`**

Insert immediately after `duplicate_unit` (which ends at `:375`):

```python
@transaction.atomic
def duplicate_element(course, element_pk, unit_token):
    """Deep-copy one element and its whole subtree into the SOURCE's own group,
    directly below the source. Returns (unit, new_join).

    Depth is unchanged -- the copy lands where the source already lives -- so a
    duplicate needs no admissibility check at all; it is safe by construction.
    """
    el, unit = _locked_element(course, element_pk)
    _check_token(unit.updated, unit_token)

    # Lazy imports: the transfer package pulls courses.forms / courses.media,
    # so a top-level edge here risks an import cycle (builder.py convention).
    from courses.transfer import export as _export
    from courses.transfer import importer as _importer
    from courses.transfer.schema import TransferError

    try:
        return _copy_below(el, unit, _export, _importer, TransferError)
    except ConflictError:
        # Defensive only: _check_token already ran above, so no ConflictError
        # normally reaches here. Keep the 409 path unwrapped -- never normalize
        # it to 422. (duplicate_unit carries the same guard for the same reason.)
        raise
    except TransferError:
        raise  # already normalized by graft_elements' _run_import
    except Exception as exc:
        # build_element_export is NOT wrapped by _run_import, so a serializer
        # edge or the export's own assert would otherwise escape as a 500 --
        # element_duplicate catches only ConflictError and TransferError.
        raise TransferError(str(exc) or "Duplicate failed.") from exc


def _copy_below(el, unit, _export, _importer, TransferError):
    """The export/graft/place region of duplicate_element, split out so the
    caller's try/except reads as one block. Runs inside the caller's atomic
    transaction and its element+unit lock."""
    document, media_assets, problems = _export.build_element_export(unit, el)
    if problems:
        # build_export RECORDS a dangling GFK and continues, dropping the broken
        # join and its entire subtree from the payload; duplicate_unit discards
        # this list outright. Copy that shape here and a damaged element yields a
        # silently thinned copy with a 200. drop_missing_media=False means no
        # media problem can be produced, so a non-empty list means exactly one
        # thing.
        raise TransferError(_("This element is damaged and cannot be copied."))

    media_map = {mid: asset for (mid, asset, _ph) in media_assets}
    new_join = _importer.graft_elements(document, media_map, unit)

    # The graft returns a PARENTLESS root: the payload root has no `parent`, and
    # _create_elements' second pass skips exactly those rows. place_element will
    # not fix it either -- it saves only `order`. So the scope is set and SAVED
    # here, or a copy of a nested element silently lands at top level.
    new_join.parent = el.parent
    new_join.tab_id = el.tab_id
    new_join.save(update_fields=["parent", "tab_id"])

    # Read the sibling list AFTER the graft. Element.order is
    # OrderField(for_fields=["unit"]), so the copy is born with a unit-wide max+1
    # and sorts last in its group -- the source's index is therefore unaffected
    # by the copy's presence. Do not "fix" this by excluding the copy from the
    # list or by reading the group before the graft: both change which index
    # means "below the source".
    siblings = list(
        ordering.element_siblings(unit, el.parent, el.tab_id).order_by("order", "pk")
    )
    idx = next(i for i, s in enumerate(siblings) if s.pk == el.pk)
    ordering.place_element(new_join, unit, idx + 1)

    unit.save(update_fields=["updated"])
    return unit, new_join
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_builder_duplicate_element.py -v`
Expected: all **nine** PASS (Step 7 then appends two more, for eleven).

- [ ] **Step 7: Pin the scoping fact the `_rewrite_links` skip rests on**

An earlier draft of this plan guarded the skip with "a copied link still points at its
original target". **That test cannot fail**, and it is worth knowing why before writing
another one like it: `rewrite_instance` only touches hrefs matching
`_PERMALINK` = `^/courses/n/(\d{1,12})/$` (`courses/richtext.py:62`) and only when the pk is
in `mapping`; `mapping` is built from `link_nodes`, which `build_export` has already filtered
to `pk in node_ids`. For an element export `node_ids` is `{unit.pk: "n1"}`, so a link to an
external node never enters `mapping` at all and a link to the source unit maps to itself.
Every variant of "assert the link survived" is green whether or not `_rewrite_links` runs.

So pin the **scoping fact** instead, which is falsifiable. Append to
`tests/test_builder_duplicate_element.py`:

```python
def test_element_export_scopes_link_nodes_to_the_unit_itself():
    """The reason graft_elements may skip _rewrite_links: link_nodes can only
    ever name nodes INSIDE the export, and an element-scoped export contains
    exactly one node -- the source unit. So the rewrite is provably an identity.
    If this ever stops holding, the skip stops being safe."""
    from courses.richtext import PERMALINK_PREFIX
    from courses.transfer.export import build_element_export

    course, unit = make_course_with_unit()
    other = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Target"
    )
    external = f"{PERMALINK_PREFIX}{other.pk}/"
    self_link = f"{PERMALINK_PREFIX}{unit.pk}/"
    join = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(
            body=f'<p><a href="{external}">out</a><a href="{self_link}">self</a></p>'
        ),
    )

    document, _media, _problems = build_element_export(unit, join)

    # The external target is filtered out; the self-link maps to the one node.
    assert document["link_nodes"] == {str(unit.pk): document["nodes"][0]["id"]}


def test_duplicate_keeps_an_internal_link_verbatim():
    """A plain regression check on the copy's body -- deliberately WITHOUT a
    mutant of its own, because no mutation CONFINED TO THE ELEMENT-SCOPED PATH
    can break it. (Mutating build_export's shared link_nodes filter does red it,
    along with much else -- see Step 8 mutation 3.)"""
    from courses.richtext import PERMALINK_PREFIX

    course, unit = make_course_with_unit()
    other = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Target"
    )
    href = f"{PERMALINK_PREFIX}{other.pk}/"
    join = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(
            body=f'<p><a href="{href}">see this</a></p>'
        ),
    )

    _unit, new_join = duplicate_element(course, join.pk, _tok(unit))

    assert href in new_join.content_object.body
```

`ContentNode` is already imported by Step 1's listing — no import change is needed here.

- [ ] **Step 8: Falsify the four assertions that could be vacuous**


Each mutation must turn exactly one test RED. Apply, run, confirm RED, then revert.

1. Delete the `new_join.save(update_fields=["parent", "tab_id"])` line.
   Expected: `test_duplicate_of_a_nested_child_stays_in_its_own_slot` FAILS.
2. Change `raise TransferError(...)` to `pass` in the `if problems:` branch.
   Expected: `test_duplicate_refuses_a_damaged_subtree_rather_than_copying_it_partially` FAILS.
3. Change the `link_nodes` comprehension in `build_export` (`export.py:781-783`) to drop its
   `if pk in node_ids` filter.
   Expected: `test_element_export_scopes_link_nodes_to_the_unit_itself` goes RED — as a
   `KeyError` on `node_ids[pk]`, not a changed-dict assertion failure, because the external
   pk is absent from `node_ids`. It also reds `test_duplicate_keeps_an_internal_link_verbatim`
   (which links to an external node), and — because the mutated line is on the **shared**
   `build_export` path — whole-course export tests carrying cross-node links. Expect a broad
   RED, not a single one. The point is that the filter is what confines `link_nodes` to the
   export, which is what makes the skip safe. (For an assertion-shaped RED confined to this
   file, mutate to `node_ids.get(pk, "n?")` instead.)
4. In `_copy_below`, replace the media map with an empty one: `media_map = {}`.
   Expected: `test_duplicate_deep_copies_related_rows_and_reuses_the_media_row` FAILS —
   with no asset in the map the importer cannot resolve the mid, so the copy either loses
   its `media_id` or the graft raises. This is what pins "reuse the existing rows"; without
   it, a change that re-created assets would still satisfy the count assertion.

Run each with `uv run pytest tests/test_builder_duplicate_element.py -v`.

- [ ] **Step 9: Commit**

```bash
git add courses/builder.py tests/test_builder_duplicate_element.py
git commit -m "feat(builder): duplicate an element subtree below its source"
```

---

### Task 5: The editor's error channel

An editor-context 422 must be *visible*. `editor.js` swaps only `[data-scope]` elements, and both `_op_error.html` and `editor.html`'s existing `{% if error %}` block sit outside them — so the message must render inside `_editor_scope.html`.

**Files:**
- Modify: `courses/views_manage.py:1244-1282` (`_render_editor_fragments`), `:1285-1311` (`_editor_page`)
- Modify: `templates/courses/manage/editor/_editor_scope.html` — add the slot after `.pane-head`
- Modify: `templates/courses/manage/editor/editor.html:59` — remove the old block
- Test: `tests/test_editor_error_channel.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_render_editor_fragments(request, unit, status=200, open_form="", open_form_pk="", refresh=True, error="", open_slots=None, changed=False)`. `open_slots` is added here so both context builders gain all three keys in one edit; Task 7 gives it meaning.

- [ ] **Step 1: Write the failing test**

Create `tests/test_editor_error_channel.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _editor_with_banner(client):
    """`?changed=1` is the one banner reachable without a mutation, so it is what
    pins the render slot's LOCATION."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
        + "?changed=1"
    )


def test_the_banner_renders_inside_the_swapped_pane(client):
    """A message outside [data-scope] survives no fragment swap: applyFragments
    replaces only those two elements, and editor.html's chrome is outside both.
    That is why the block moves into _editor_scope.html."""
    resp = _editor_with_banner(client)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="editor-error"' in body
    assert body.index('id="editor-error"') > body.index('data-scope="editor"')


def test_the_banner_is_not_rendered_twice(client):
    """editor.html's old block must be REMOVED, not left beside the new one, or
    every settings-save 422 shows its message twice.

    Counts `class="op-error"`, NOT the new block's id: editor.html:58-59 render
    the div with no id at all, so an id-based count returns 1 whether or not
    Step 4 was done -- vacuous, and the removal would ship unguarded."""
    resp = _editor_with_banner(client)

    assert resp.content.decode().count('class="op-error"') == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_editor_error_channel.py -v`
Expected: `test_the_banner_renders_inside_the_swapped_pane` FAILS on
`assert 'id="editor-error"' in body` — no such slot exists yet.
`test_the_banner_is_not_rendered_twice` PASSES for now: `editor.html` renders exactly one
`op-error` div today. It becomes the guard on Step 4, which Step 3b below proves.

- [ ] **Step 3: Add the error slot to `_editor_scope.html`**

In `templates/courses/manage/editor/_editor_scope.html`, immediately after the `.pane-head` div (currently line 8) and before `<div class="pane-body">`, insert:

```html
      {% comment %}
      The editor's error slot. It MUST live inside [data-scope="editor"]:
      editor.js's applyFragments replaces only the two [data-scope] panes, so a
      message rendered in editor.html's chrome (where this block used to live)
      is swapped in never and seen only on a full page load. _op_error.html has
      the same defect and is therefore builder-context only.
      {% endcomment %}
      {% if error or changed %}<div id="editor-error" class="op-error" role="alert">{% if error %}{{ error }}{% else %}{% trans "This changed elsewhere — reloaded to the latest." %}{% endif %}</div>{% endif %}
```

One element, not two: `error` and `changed` can both be set on the same response, and two
blocks would then emit a duplicate `id`. `error` wins because it is the more specific
message.

- [ ] **Step 3b: Confirm the duplicate now exists**

Run: `uv run pytest tests/test_editor_error_channel.py -v`
Expected: `test_the_banner_is_not_rendered_twice` now FAILS with a count of 2 — the new slot
and the old chrome block both render. That RED is what makes it a real guard on Step 4 rather
than a test that was green all along.

- [ ] **Step 4: Remove the superseded blocks from `editor.html`**

In `templates/courses/manage/editor/editor.html`, delete both of these lines (currently `:58-59`):

```html
  {% if changed %}<div class="op-error" role="alert">{% trans "This changed elsewhere — reloaded to the latest." %}</div>{% endif %}
  {% if error %}<div class="op-error" role="alert">{{ error }}</div>{% endif %}
```

`editor.html` includes `_editor_scope.html` at `:93` **without** `only`, so `error` and `changed` flow through from `_editor_page`'s context unchanged.

- [ ] **Step 5: Add the three context keys to both builders**

`changed` is one of them, because the moved block references it and
`_render_editor_fragments` does not currently define it — a template variable that one of its
two renderers never supplies. It is added as a **kwarg defaulting to False, and nothing sets
it to True.**

That restraint is deliberate. It is tempting to have `_element_conflict` pass `changed=True`
so the editor's 409 fragment carries the message — but `editor.js` already calls
`flash(msg("conflict", "This changed elsewhere — reloaded to the latest."))` on a 409
(`:293-294`), prepending its own `.op-error` bar. Passing the flag too would show the author
the identical sentence **twice**, with the in-pane copy persisting until the next swap while
the flash bar self-removes. PR1 leaves 409 behaviour exactly as it is today; the kwarg exists
only so the template variable is always defined.

In `courses/views_manage.py`, change `_render_editor_fragments`'s signature to:

```python
def _render_editor_fragments(
    request,
    unit,
    status=200,
    open_form="",
    open_form_pk="",
    refresh=True,
    error="",
    open_slots=None,
    changed=False,
):
```

then add to `_render_editor_fragments`'s context dict, beside `max_nest_depth`:

```python
            # Editor-context errors render HERE, inside the swapped pane -- see
            # _editor_scope.html. _op_error cannot be used from this path.
            "error": error,
            # Slot keys whose <details> must render open regardless of the
            # first-tab default, so a just-created element is not born inside a
            # collapsed tab. Both context builders must carry this key: a key set
            # on only one makes the first page load look perfect while every
            # later fragment swap silently drops the feature.
            "open_slots": open_slots or set(),
            # Supplied by _editor_page already; added here so the moved banner
            # block has both of its variables defined on BOTH render paths.
            "changed": changed,
```

Add the same `"open_slots": open_slots or set(),` line to `_editor_page`'s context, and give `_editor_page` an `open_slots=None` keyword argument. `_editor_page` already has `error` and `changed`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_editor_error_channel.py -v`
Expected: both PASS (the file has two tests).

- [ ] **Step 7: Verify no existing editor test regressed**

Run: `uv run pytest tests/test_element_editor_ops.py tests/test_manage_element_ops.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/views_manage.py templates/courses/manage/editor/_editor_scope.html templates/courses/manage/editor/editor.html tests/test_editor_error_channel.py
git commit -m "fix(editor): render errors inside the swapped pane, not the page chrome"
```

---

### Task 6: The `element_duplicate` view and URL

**Files:**
- Modify: `courses/views_manage.py` — add `element_duplicate` after `element_delete` (`:1183`)
- Modify: `courses/urls.py` — add the path beside `manage_element_delete` (`:219-223`)
- Test: `tests/test_element_duplicate_view.py`

**Interfaces:**
- Consumes: `builder.duplicate_element` (Task 4), `_render_editor_fragments(..., error=…)` (Task 5).
- Produces: URL name `courses:manage_element_duplicate`, POST fields `element`, `unit`, `unit_token`, `ctx=editor`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_element_duplicate_view.py`:

Auth here follows `tests/test_element_editor_ops.py`. `can_manage_course` grants on
**ownership or** the Platform Admin group, so `make_login(client, "owner")` + `owner=` would
work equally well (`tests/factories.py:133-136` documents exactly that); `make_pa` is chosen
here only to match the neighbouring editor-ops tests. What does *not* work is a logged-in user
who neither owns the course nor holds the group — that is the 403 case, exercised below.

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
    """Returns (course, unit, join) with a logged-in manager."""
    pa = make_pa(client, username)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    join = add_element(unit, TextElement.objects.create(body="<p>hi</p>"))
    unit.refresh_from_db()  # add_element bumped nothing; re-read for a fresh token
    return course, unit, join


def _post(client, course, unit, join, token=None):
    return client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": join.pk,
            "unit": unit.pk,
            "unit_token": token if token is not None else unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )


def test_duplicate_returns_both_fragments(client):
    course, unit, join = _seed(client)

    resp = _post(client, course, unit, join)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'data-scope="preview"' in body
    assert unit.elements.count() == 2


def test_duplicate_409s_on_a_stale_token(client):
    course, unit, join = _seed(client)

    resp = _post(client, course, unit, join, token="2020-01-01T00:00:00+00:00")

    assert resp.status_code == 409
    assert unit.elements.count() == 1


def test_duplicate_422s_with_a_visible_message_on_a_damaged_element(client):
    """Assert the BODY, not only the status: a 422 whose body is a bare op-error
    div passes a status-only assertion and is still invisible to the author.
    That is exactly how this error path was got wrong once already."""
    course, unit, join = _seed(client)
    # Repoint, don't delete: GenericRelation(Element) cascades, so deleting the
    # concrete would remove `join` itself -- _locked_element would then raise
    # ConflictError and the endpoint would answer 409, never reaching the 422
    # path this test exists to check. See tests/test_transfer_export.py:342-351.
    Element.objects.filter(pk=join.pk).update(object_id=9_999_999)

    resp = _post(client, course, unit, join)

    assert resp.status_code == 422
    body = resp.content.decode()
    assert 'data-scope="editor"' in body
    assert 'id="editor-error"' in body


def test_duplicate_409s_on_a_non_numeric_element_pk(client):
    """Guards Task 4 Step 3's widened except clause: _locked_element caught only
    DoesNotExist, so Element.objects.get(pk="abc") raised ValueError and the
    author got a 500."""
    course, unit, _join = _seed(client)

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": "abc",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 409


def test_duplicate_refuses_a_user_who_cannot_manage_the_course(client):
    """Drive the surface AS the wrong role rather than asserting the decorator
    exists."""
    from tests.factories import make_teacher

    course, unit, join = _seed(client, username="owner")
    client.logout()
    make_teacher(client, "teacher")  # can log in, cannot manage this course

    resp = _post(client, course, unit, join)

    assert resp.status_code in (403, 404)
    assert unit.elements.count() == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_element_duplicate_view.py -v`
Expected: FAIL — `NoReverseMatch: 'manage_element_duplicate' is not a valid view function or pattern name`.

- [ ] **Step 3: Add the URL**

In `courses/urls.py`, immediately after the `manage_element_delete` path (`:219-223`), add:

```python
    path(
        "manage/courses/<slug:slug>/build/element/duplicate/",
        views_manage.element_duplicate,
        name="manage_element_duplicate",
    ),
```

- [ ] **Step 4: Add the view**

No new imports are needed: `TransferError` (`:41`), `ContentNode`, `builder_svc` (`:20`),
`_require_manage`, `_element_conflict`, `_render_tree` and `_render_editor_fragments` are all
already in `courses/views_manage.py`.

Insert immediately after `element_delete` (which ends at `:1183`):

```python
@login_required
def element_duplicate(request, slug):
    """Editor-only: deep-copy one element below itself.

    Always answers with the editor fragment pair -- there is no builder-context
    caller, because the builder's unit panel is a read-only list. The no-JS path
    therefore gets the bare fragment page, exactly as element_move and
    element_delete already do for ctx=editor.
    """
    course = _require_manage(request, slug)
    try:
        unit, new_join = builder_svc.duplicate_element(
            course, request.POST.get("element"), request.POST.get("unit_token")
        )
    except builder_svc.ConflictError:
        return _element_conflict(request, course)
    except TransferError as exc:
        # 422 through the FRAGMENT renderer, never _op_error: the latter has no
        # [data-scope] wrapper, so applyFragments swaps nothing and the author
        # sees no message at all.
        unit = ContentNode.objects.filter(
            pk=request.POST.get("unit"), course=course, kind=ContentNode.Kind.UNIT
        ).first()
        if unit is None:
            return _render_tree(request, course, status=409)
        return _render_editor_fragments(request, unit, status=422, error=str(exc))
    return _render_editor_fragments(request, unit)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_element_duplicate_view.py -v`
Expected: all **five** PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/urls.py courses/views_manage.py tests/test_element_duplicate_view.py
git commit -m "feat(editor): add the element-duplicate endpoint"
```

---

### Task 7: Keep the copy visible — `slot_key` and the open-ancestor set

A copy made inside tab 2 re-renders with only tab 1 open, so both the source and the brand-new copy vanish. The view passes the copy's ancestor slots; the `<details>` conditions honour them.

**Files:**
- Modify: `courses/builder.py` — add `slot_key` and `ancestor_slots` near `element_depth` (`:102-114`)
- Modify: `courses/templatetags/courses_manage_extras.py` — register the `slot_key` filter
- Modify: `courses/views_manage.py` — `element_duplicate` passes `open_slots`
- Modify: `templates/courses/manage/editor/_element_row.html:82` (tabs) and `:132` (columns)
- Test: `tests/test_editor_open_slots.py`

**Interfaces:**
- Consumes: `_render_editor_fragments(..., open_slots=…)` (Task 5), `element_duplicate` (Task 6).
- Produces: `builder.slot_key(parent_pk, tab_id) -> str`, `builder.ancestor_slots(join) -> set[str]`, and the `slot_key` template filter.

- [ ] **Step 1: Write the failing test**

Create `tests/test_editor_open_slots.py`:

```python
import pytest
from django.urls import reverse

from courses.builder import ancestor_slots
from courses.builder import slot_key
from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_slot_key_uses_an_explicit_none_test():
    """`parent_pk or ''` would collapse a pk of 0 onto the top-level key."""
    assert slot_key(None, "") == ":"
    assert slot_key(0, "t1") == "0:t1"
    assert slot_key(12, "t1") == "12:t1"


def test_ancestor_slots_names_every_container_above_a_join():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=tabs_join,
        tab_id=t2,
    )

    assert ancestor_slots(child) == {slot_key(tabs_join.pk, t2)}
    assert ancestor_slots(tabs_join) == set()


def test_duplicating_inside_tab_two_renders_that_tab_open(client):
    """Without the open-set the response shows only tab 1, so the author's new
    copy is born invisible."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="x"),
        parent=tabs_join,
        tab_id=t2,
    )

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    marker = f'data-tab-id="{t2}"'
    at = body.index(marker)
    tag = body[at : at + 200]
    assert " open" in tag
    assert "data-force-open" in tag


def test_a_column_nested_in_a_tab_opens_its_whole_ancestor_chain(client):
    """The `:132` edit uses `column.id`, not `tab.id`. Copying the tabs line
    verbatim there fails SILENTLY -- nested inside a tabs element, `tab` is still
    in scope (the recursive include at :86 passes no `only`), so the key names
    the enclosing TAB and matches nothing. Without this test that ships green,
    and it also gives ancestor_slots its only two-hop exercise."""
    from courses.models import TwoColumnElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    _t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    cols = TwoColumnElement.objects.create(data=TwoColumnElement.default_data())
    cols_join = Element.objects.create(
        unit=unit, content_object=cols, parent=tabs_join, tab_id=t2
    )
    _c1, c2 = [c["id"] for c in cols.data["columns"]]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>deep</p>"),
        parent=cols_join,
        tab_id=c2,
    )

    # Two hops: the column slot AND the tab slot above it.
    assert ancestor_slots(child) == {
        slot_key(cols_join.pk, c2),
        slot_key(tabs_join.pk, t2),
    }

    resp = client.post(
        reverse("courses:manage_element_duplicate", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "element": child.pk,
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    body = resp.content.decode()
    for marker in (f'data-column-id="{c2}"', f'data-tab-id="{t2}"'):
        tag = body[body.index(marker) : body.index(marker) + 200]
        assert "data-force-open" in tag, marker
        assert " open" in tag, marker
```

`TwoColumnElement.default_data()` returns `{"columns": [{"id": first}, {"id": second}]}`
(`courses/models.py:1487-1491`) — two columns, keyed `"columns"`, which is what the unpacking
above relies on.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_editor_open_slots.py -v`
Expected: FAIL — `ImportError: cannot import name 'ancestor_slots'`.

- [ ] **Step 3: Add the two helpers to `courses/builder.py`**

Insert after `element_depth` (which ends at `:114`):

```python
def slot_key(parent_pk, tab_id):
    """Flattened '<parent_pk>:<tab_id>' key for one container slot; the
    top-level slot is ':'.

    A single flattened string rather than a tuple, because Django's template
    language cannot construct a tuple and the <details> open test has to build
    this key from two values inside an expression. One helper for the view and
    the template so the two can never disagree about the shape.

    The `is None` test is explicit on purpose: `parent_pk or ""` would collapse a
    pk of 0 onto the top-level key.
    """
    return f"{'' if parent_pk is None else parent_pk}:{tab_id}"


def ancestor_slots(join):
    """Slot keys of every container slot ABOVE `join`, so a render can force
    those <details> open and a newly created element is not born inside a
    collapsed tab.

    Bounded by MAX_NEST_DEPTH hops for the same reason element_depth is: a
    corrupt parent cycle must terminate rather than spin.
    """
    keys, cur, hops = set(), join, 0
    while cur.parent_id is not None and hops <= MAX_NEST_DEPTH:
        keys.add(slot_key(cur.parent_id, cur.tab_id))
        cur = cur.parent
        hops += 1
    return keys
```

- [ ] **Step 4: Register the template filter**

In `courses/templatetags/courses_manage_extras.py`, add `from courses import builder` to the imports, and append beside the existing `in_set` filter:

```python
@register.filter
def slot_key(parent_pk, tab_id):
    """Template-side twin of builder.slot_key, registered as a FILTER because the
    <details> open test builds its key from two values inside an expression,
    where an inclusion tag cannot be used:

        {% if el.pk|slot_key:tab.id|in_set:open_slots %}

    Delegates rather than re-deriving, so the key shape has exactly one
    definition.
    """
    return builder.slot_key(parent_pk, tab_id)
```

- [ ] **Step 5: Pass the set from the view**

In `courses/views_manage.py`, change `element_duplicate`'s success return to:

```python
    return _render_editor_fragments(
        request, unit, open_slots=builder_svc.ancestor_slots(new_join)
    )
```

- [ ] **Step 6: Honour the set in both container branches**

In `templates/courses/manage/editor/_element_row.html`, replace line `:82` with:

```html
      <details class="tabs-rows" data-tab-id="{{ tab.id }}"{% if el.pk|slot_key:tab.id|in_set:open_slots %} open data-force-open{% elif forloop.first %} open{% endif %}>
```

and line `:132` with — note the loop variable here is `column`, **not** `tab`; copying the line above verbatim resolves `tab.id` to the empty string at top level, or leaks the *enclosing* tab's id when a two-column element is nested inside a tabs element (the recursive include at `:86` passes no `only`, so outer loop variables stay in scope), and either way the key silently matches nothing:

```html
      <details class="columns-rows" data-column-id="{{ column.id }}"{% if el.pk|slot_key:column.id|in_set:open_slots %} open data-force-open{% elif forloop.first %} open{% endif %}>
```

Ensure `{% load i18n courses_manage_extras %}` is the first line of the file (it already loads `courses_manage_extras`).

**There is no third edit for the spoiler**, and that is not an omission: the spoiler branch
renders `<div class="el-row__spoiler"><ol>…</ol></div>` (`_element_row.html:183-196`) with no
`<details>` at all, so its children are never collapsed. `ancestor_slots` still emits a key
for a spoiler slot; it simply matches nothing, which is harmless.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/test_editor_open_slots.py -v`
Expected: all **four** PASS.

- [ ] **Step 8: Falsify the open-set test**

Change the view's success return back to `_render_editor_fragments(request, unit)`.
Run: `uv run pytest tests/test_editor_open_slots.py -v`
Expected: **both** render tests FAIL —
`test_duplicating_inside_tab_two_renders_that_tab_open` and
`test_a_column_nested_in_a_tab_opens_its_whole_ancestor_chain` — since both read markers out
of a response body that depends on this argument. Revert.

- [ ] **Step 9: Commit**

```bash
git add courses/builder.py courses/templatetags/courses_manage_extras.py courses/views_manage.py templates/courses/manage/editor/_element_row.html tests/test_editor_open_slots.py
git commit -m "feat(editor): keep a duplicated element's container open after the swap"
```

---

### Task 8: The ⧉ button

**Files:**
- Modify: `templates/courses/manage/editor/_element_row_controls.html`
- Test: `tests/test_element_duplicate_view.py` (append)

**Interfaces:**
- Consumes: `courses:manage_element_duplicate` (Task 6).
- Produces: the author-facing control. `editor.js:283` intercepts any `form[data-op]`, so no JavaScript is needed.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_element_duplicate_view.py`:

```python
def test_every_row_offers_a_duplicate_button_at_every_depth(client):
    """The control lives in the shared partial, so one edit covers all six row
    branches -- assert a NESTED row too, or a regression that drops the partial
    from one branch ships green."""
    from courses.models import Element
    from courses.models import TabsElement

    course, unit, _join = _seed(client)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = Element.objects.create(unit=unit, content_object=tabs)
    t1 = tabs.data["tabs"][0]["id"]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>nested</p>"),
        parent=tabs_join,
        tab_id=t1,
    )

    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )

    body = resp.content.decode()
    # The COUNT is the real guard: `csrfmiddlewaretoken` and `value="<pk>"` both appear
    # in the existing move/delete forms on every row, so either alone would be green
    # before this task's change. csrf is therefore asserted INSIDE the first new form,
    # and the child-pk assertion is dropped: the first duplicate form belongs to the
    # Text row _seed() creates before this test adds the Tabs element, so it could
    # never contain the child's pk anyway.
    assert body.count('data-op="element-duplicate"') >= 2  # the Tabs row and its child
    form_at = body.index('data-op="element-duplicate"')
    new_form = body[form_at : form_at + 700]
    assert "csrfmiddlewaretoken" in new_form
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_element_duplicate_view.py -v`
Expected: FAIL — `data-op="element-duplicate"` appears zero times.

- [ ] **Step 3: Add the form to the shared partial**

In `templates/courses/manage/editor/_element_row_controls.html`, insert this **between** the move form and the delete form — the ordering is what puts ⧉ before 🗑 in the bar:

```html
<form class="tree__inline" method="post" action="{% url 'courses:manage_element_duplicate' slug=unit.course.slug %}" data-op="element-duplicate">
  {% csrf_token %}
  <input type="hidden" name="ctx" value="editor">
  <input type="hidden" name="element" value="{{ el.pk }}">
  <input type="hidden" name="unit" value="{{ unit.pk }}">
  <input type="hidden" name="unit_token" value="{{ unit.updated.isoformat }}">
  <button class="iconbtn" type="submit" aria-label="{% trans 'Duplicate' %}" title="{% trans 'Duplicate' %}">⧉</button>
</form>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_element_duplicate_view.py -v`
Expected: all **six** PASS (Task 6's five plus this one).

- [ ] **Step 5: Regenerate translations**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

`msgid "Duplicate"` / `msgstr "Duplikuj"` **already exists** in
`locale/pl/LC_MESSAGES/django.po` (the builder's node-duplicate control uses it), so this run
should only add a reference comment pointing at `_element_row_controls.html`. Confirm that:
no new untranslated entry, and no `#, fuzzy` marker anywhere in the diff — a fuzzy entry
carries a wrong pre-filled translation and is ignored until the marker is cleared. Then:

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_element_row_controls.html tests/test_element_duplicate_view.py locale/
git commit -m "feat(editor): add the duplicate control to every element row"
```

---

### Task 9: Stop `applyStoredTabs` re-collapsing a forced-open container

The server rendering `open` is not enough. `applyFragments` calls `applyStoredTabs(root)` after **every** swap, which sets `d.open` from localStorage — so any tab the author has ever collapsed is re-collapsed client-side, and the copy disappears anyway. A template test cannot catch this: it never runs `editor.js`.

**Files:**
- Modify: `courses/static/courses/js/editor.js:43-50` (`applyStoredTabs`)
- Test: `tests/test_e2e_editor_force_open.py`

**Interfaces:**
- Consumes: the `data-force-open` attribute from Task 7, and the ⧉ form from Task 8 — the e2e
  clicks the real button, so this task must come after it.
- Produces: nothing further.

- [ ] **Step 1: Write the failing e2e test**

Create `tests/test_e2e_editor_force_open.py`. The login/seed helpers mirror
`tests/test_e2e_depth3.py:47-100` exactly rather than being invented:

```python
"""Playwright e2e for the force-open skip — the ONE behaviour of PR1 that a
template test cannot cover.

The server renders the destination <details> open, and then editor.js's
applyStoredTabs immediately re-applies the author's stored preference over the
top. For any tab the author has ever collapsed, a just-duplicated element is
therefore born invisible. The defect lives entirely in the browser: a template
test renders server HTML, never runs applyStoredTabs, and passes whether or not
the skip exists.
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


def _seed(owner, slug):
    """A unit holding a Tabs whose SECOND tab has one Text child.

    Seeded through the ORM on purpose: the gesture under test is the duplicate
    click and the swap that follows, not the authoring of a tab (which
    test_e2e_depth3 already drives through the real add-menu).
    """
    from courses.models import Element
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
    t2 = tabs.data["tabs"][1]["id"]
    child = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>FORCEOPEN-MARKER</p>"),
        parent=tabs_join,
        tab_id=t2,
    )
    return course, unit, tabs_join, t2, child


@pytest.mark.django_db(transaction=True)
def test_a_stored_collapse_does_not_hide_a_just_duplicated_element(page, live_server):
    user = _make_pa_user("pa")
    course, unit, tabs_join, t2, child = _seed(user, "forceopen")
    _login(page, live_server, "pa")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )

    tab2 = page.locator(f"details.tabs-rows[data-tab-id='{t2}']")
    # Tab 2 is not the first tab, so it renders closed. Open it -- the row inside
    # a closed <details> is in the DOM but not clickable (content-visibility),
    # so the duplicate button is unreachable until it is open.
    tab2.locator("summary").click()
    expect(tab2).to_have_attribute("open", "")

    # Now plant the stored preference the skip must override. Opening the tab
    # just wrote "1" via saveTab, so setting it directly is what reproduces "the
    # author collapsed this tab earlier"; clicking summary twice more would only
    # write "1" again by the time we click duplicate. The key shape is
    # editor.js's tabStoreKey: "libli:tabopen:" + <tabs row pk> + ":" + <tab id>.
    page.evaluate(
        "key => localStorage.setItem(key, '0')",
        f"libli:tabopen:{tabs_join.pk}:{t2}",
    )

    row = page.locator(f".el-row[data-element='{child.pk}']")
    with page.expect_response(lambda r: "element/duplicate/" in r.url):
        row.locator("form[data-op='element-duplicate'] button[type=submit]").click()

    tab2_after = page.locator(f"details.tabs-rows[data-tab-id='{t2}']")
    expect(tab2_after).to_have_attribute("data-force-open", "")
    # THIS is the assertion the defect breaks: applyStoredTabs has just re-applied
    # the stored "0" over the server's `open`.
    expect(tab2_after).to_have_attribute("open", "")
    # And this one proves the copy landed in the right slot. Note it does NOT
    # detect the defect: to_have_count matches DOM nodes regardless of visibility,
    # and a closed <details> keeps its children in the DOM (it hides them via
    # content-visibility), so the count is 2 either way.
    expect(tab2_after.locator(".el-row")).to_have_count(2)
```

- [ ] **Step 2: Run the e2e test to verify it fails**

Run: `uv run pytest tests/test_e2e_editor_force_open.py -m e2e -v`
Expected: FAIL — the tab is collapsed after the swap. **`-m e2e` is mandatory**; without it the test is silently deselected and pytest exits 5 with no tests run, which reads as a pass.

- [ ] **Step 3: Add the skip to `applyStoredTabs`**

In `courses/static/courses/js/editor.js`, change `applyStoredTabs` to:

```js
  function applyStoredTabs(scope) {
    (scope || root).querySelectorAll('[data-scope="editor"] details.tabs-rows, details.tabs-rows')
      .forEach(function (d) {
        // A server-forced-open container ignores the stored preference. Without
        // this, the server renders the destination tab open and we immediately
        // re-collapse it, so a just-duplicated element is born invisible. The
        // author's toggle is still RECORDED by saveTab and takes effect again as
        // soon as the force-open stops being rendered.
        if (d.hasAttribute("data-force-open")) return;
        var v;
        try { v = localStorage.getItem(tabStoreKey(d)); } catch (e) { v = null; }
        if (v !== null) d.open = v === "1";
      });
  }
```

- [ ] **Step 4: Run the e2e test to verify it passes**

Run: `uv run pytest tests/test_e2e_editor_force_open.py -m e2e -v`
Expected: PASS.

- [ ] **Step 5: Falsify it**

Remove the `if (d.hasAttribute("data-force-open")) return;` line.
Run: `uv run pytest tests/test_e2e_editor_force_open.py -m e2e -v`
Expected: FAIL. Restore the line.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/editor.js tests/test_e2e_editor_force_open.py
git commit -m "fix(editor): stored tab state must not re-collapse a forced-open container"
```

---

### Task 10: Visual verification

The button reuses `.iconbtn` and needs nothing new. **The error slot probably does need one
rule.** `.op-error` is `padding: var(--space-2) var(--space-3); margin-bottom: var(--space-3)`
(`editor.css:5-9`) with no horizontal inset, and it has moved from `editor.html`'s page chrome
to a direct child of `.pane` — which has no padding of its own, while `.pane-head` and
`.pane-body` both use `var(--space-4)`. Expect it to render edge-to-edge and out of line with
the pane's content column, and expect to add an inset. Treat "no change needed" as the
surprising outcome here, not the default.

**Files:**
- Modify (only if the screenshots show a problem): `courses/static/courses/css/editor.css`

- [ ] **Step 1: Start the app and open a unit editor**

Use the `/run` skill, or follow the project's documented dev-server steps, and navigate to a unit editor containing a Tabs element with children.

- [ ] **Step 2: Screenshot the row bar in light mode**

Capture a top-level row and a nested row. Check: ⧉ sits between ↓ and 🗑; the bar does not
wrap or overflow; the slidebreak row still lines up. Counts, on one consistent basis — inside
`.el-actions`, a normal row now holds ✎ ✕ ↑ ↓ ⧉ 🗑 (six) and a slidebreak row holds ↑ ↓ ⧉ 🗑
(four). The drag grip is a seventh/fifth control visually but lives in `.el-row__head`,
*outside* `.el-actions` (`_element_row.html:6-7`, `:48-49`, `:202-203`).

- [ ] **Step 3: Screenshot the same in dark mode**

Judge dark separately — do not infer it from the light pass. Check the glyph's contrast against the bar background.

- [ ] **Step 4: Screenshot the error slot**

Trigger a 422 and confirm the message renders inside the editor pane, above the element list,
and is legible in both themes. To reach that state, **repoint a join's `object_id`** — do not
delete the concrete row, which cascades the join away and removes the row (and its ⧉ button)
from the editor entirely:

```bash
uv run python manage.py shell -c "from courses.models import Element; Element.objects.filter(pk=<pk>).update(object_id=9999999)"
```

Then reload the editor and click ⧉ on that row.

- [ ] **Step 5: Fix any spacing or contrast problem in `editor.css`**

Add rules beside the existing `.el-actions` / `.op-error` definitions. If nothing is wrong, change nothing and say so.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest`
Expected: all PASS. Then the e2e subset: `uv run pytest -m e2e`

- [ ] **Step 7: Lint**

```bash
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 8: Commit anything that changed**

```bash
git add -A
git commit -m "style(editor): verify the duplicate control and error slot in both themes"
```

---

## Out of scope for PR1

Everything the clipboard needs: `paste_allowed`, `enumerate_slots`, the session mark, the ⊹ select control, the paste buttons, the `PlacementRefused` / `ParentGoneError` carriers, the model→key helper promotion and the strengthened container-key drift test. PR2's plan covers those.

**PR1 does not deliver the "three similar tabs" need.** A duplicate always lands in the source's own slot; seeding tab 2 from tab 1 needs PR2's ⧉ Copy here. What PR1 delivers is the same-slot near-identical sibling, plus the whole foundation PR2 stands on. Judge PR1 against that, not against the broader need.
