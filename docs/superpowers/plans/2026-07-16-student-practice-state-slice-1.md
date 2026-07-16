# Student practice state — Slice 1 (substrate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `UnitProgress.checklist_state` with a general `UnitProgress.element_state` keyed by `Element` join-row pk, migrate mark-done onto it, and add a student-facing Reset at any outline level.

**Architecture:** One JSON field on the existing `UnitProgress` row (keyed `(student, unit)`), one unit-scoped save endpoint (a generalisation of `markdone_save`), one reset endpoint (GET confirmation interstitial + POST), and a validator registry in a new pure module `courses/state.py`. The render seam already exists (`ElementBase.render` + `render_element` reading from context); this slice widens it to pass the `Element` join row down and renames `checklist` → `state`. **Slice 1 adds NO new element and NO client-side restore** — mark-done restores server-side via the `checked` context var.

**Tech Stack:** Django 5.2, Postgres (JSONField), pytest + pytest-django, Playwright (e2e), ruff, uv.

**Spec:** `docs/superpowers/specs/2026-07-16-student-practice-state-design.md` — **unfenced sections only.** Everything under `⚠️ SLICE 2 RECORD` / `⚠️ SLICE 3 RECORD` and the later-slice blob table is **out of scope**.

## Global Constraints

- **Key space: the `Element` join-row pk, everywhere.** `element_state` keys are `str(element.pk)` on write, `int(k)` on read. Item pks *inside* a blob are `int()`-coerced on both sides. Never the content-object pk.
- **Never a 500 from bad data.** Malformed input → `REJECT`/400; malformed *stored* data → treated as absent, element renders fresh.
- **`EMPTY` and `REJECT` are distinct sentinels, never a bare falsy value.** `EMPTY` deletes the stored key; `REJECT` leaves it untouched. Conflating them makes a malformed blob wipe good state.
- **Access gate is `can_access_course`, NOT `is_enrolled`** — on both the write (endpoint) and the read (`build_lesson_context`). Lifting it in only one silently fails to re-render.
- **The state read never creates a `UnitProgress` row.** The existing enrolled `get_or_create` (`views.py:353`) stays exactly as-is — it feeds `progress`/`seen_ids`/`seen_count`.
- **Reset never touches `seen_element_ids` / `completed`, and never touches `QuizSubmission` / `QuestionResponse` / `Attempt`.**
- **No new element types.** `ELEMENT_MODELS` does not change. **Three** files assert `len(ELEMENT_MODELS) == 31` — `tests/test_transfer_schema.py:11`, `tests/test_models_multigrid.py:11` and `tests/test_guessnumber_model.py:11` (all under `tests/`, none under `courses/tests/`). None must move; if one goes red, something is wrong.
- **Transfer untouched.** No `SERIALIZERS`/`VALIDATORS`/`BUILDERS` change, no `NESTABLE_TYPE_KEYS` change, `FORMAT_VERSION` stays **4**.
- **Migration number is provisional.** Highest existing is `0049_guessnumberelement_alter_element_content_type`. Run `makemigrations` against the real base and use what it assigns — never hardcode `0050`.
- **i18n:** every new user-facing string EN + PL. `makemessages` fuzzy-matches new msgids on every build; strip `#, fuzzy` (keep `python-format`/`python-brace-format`), drop `#| msgid` lines, set correct PL. `test_po_catalog_clean` fails on any `#, fuzzy` or `#~`.
- **Test DB isolation:** this branch runs in a worktree — export a unique `DATABASE_URL` (e.g. `postgres://libli:libli@localhost:5432/libli_sps1`; the role has CREATEDB) or concurrent worktrees collide on `test_libli`.
- **Commands:** `uv run pytest ...`, `uv run ruff check --fix . && uv run ruff format .`. Bash has no bare `pytest`/`ruff`/`python` on PATH.
- **Run tests FOREGROUND.** Never background/detach a pytest run. Heavy suites use `-n auto`. e2e is deselected by default (`addopts = -q -m 'not e2e'`) — an e2e file run without `-m e2e` exits 5 **looking like success**.

---

## File Structure

**Created:**
- `courses/state.py` — pure module: `EMPTY`/`REJECT` sentinels, the validator registry keyed by `content_type.model`, `validate_state()` dispatch. No Django views, no ORM writes.
- `courses/migrations/00NN_unitprogress_element_state.py` — add field, `RunPython` re-key, drop old field. Reversible.
- `courses/migrations/_state_rekey.py` — **production module**, not a test helper: the pure forward/backward re-key functions, extracted so they are unit-testable. The leading underscore is load-bearing — Django's migration loader skips modules starting with `_`, so it is never mistaken for a migration.
- `templates/courses/progress_reset_confirm.html` — the GET interstitial.
- `courses/tests/test_state_module.py` — validator registry + contract.
- `courses/tests/test_element_state_endpoint.py` — `element_state_save`.
- `courses/tests/test_progress_reset.py` — `progress_reset` (GET + POST + invariants).
- `courses/tests/test_state_migration.py` — the re-key, forward and backward.
- `courses/tests/test_rollups_units_under.py` — the `units_under` subtree helper.
- `courses/tests/test_reset_controls.py` — the reset controls + editor-preview inertness.
- `tests/test_e2e_practice_state.py` — e2e (mark-done persists; burst; reset).

**Modified:**
- `courses/models.py` — `UnitProgress.element_state` (replacing `checklist_state`); `ElementBase.render` + `_state_context`; the 7 `**_kwargs` overrides; `TabsElement.render`; `TwoColumnElement.render`; `MarkDoneElement` docstring (`:453`).
- `courses/templatetags/courses_extras.py` — `render_element` generic branch passes `element=` and `state=`.
- `courses/views.py` — `build_lesson_context` state read; `markdone_save` → `element_state_save`; new `progress_reset`.
- `courses/urls.py` — replace the `markdone_save` route; add two reset routes.
- `courses/rollups.py` — new `units_under(node)`.
- `templates/courses/elements/markdoneelement.html` — `eid` + anchor.
- `templates/courses/_lesson_article.html` — "Start fresh" control.
- `templates/courses/outline.html`, `templates/courses/_outline_node.html` — reset controls.
- `courses/static/courses/js/markdone.js` — save/reconcile rewrite.
- `courses/tests/test_markdone_scripts.py` — the envelope + `seq`-guard source assertions.
- `courses/static/courses/css/courses.css`, `core/static/core/css/app.css` — the six new classes.
- `locale/pl/LC_MESSAGES/django.po` — EN/PL for the reset + interstitial strings.
- `courses/tests/test_render_seam.py`, `courses/tests/test_markdone_models.py`, `courses/tests/test_markdone_render.py`, `tests/test_e2e_markdone.py` — updated for the new field/route/signature.

**Deleted:**
- `courses/tests/test_markdone_endpoint.py` — superseded by `test_element_state_endpoint.py` (Task 5).
- `courses/tests/test_markdone_models.py::test_unit_progress_checklist_state_defaults_to_dict` — a test *of* the removed field (Task 10).

---

### Task 1: `courses/state.py` — sentinels, registry, dispatch

**Files:**
- Create: `courses/state.py`
- Test: `courses/tests/test_state_module.py`

**Interfaces:**
- Consumes: **nothing** — validators receive `obj` and duck-type it (`obj.items`). The module imports no models; it is pure, like `courses/quiz.py`.
- Produces:
  - `EMPTY`, `REJECT` — module-level singleton sentinels.
  - `validate_state(element, obj, payload) -> dict | EMPTY | REJECT` — dispatches on `element.content_type.model`; unknown model → `REJECT`; any validator exception → `REJECT`.
  - `_val_markdone(element, obj, payload)` — registered for `"markdoneelement"`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_state_module.py`:

```python
import pytest

from courses import state
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _mk():
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    i2 = MarkDoneItem.objects.create(element=obj, content="b")
    return el, obj, i1, i2


def test_empty_and_reject_are_distinct_and_not_falsy():
    # Load-bearing: EMPTY deletes the stored key, REJECT preserves it. An
    # implementer conflating them makes a malformed blob wipe good state.
    assert state.EMPTY is not state.REJECT
    assert state.EMPTY is not None and state.REJECT is not None
    assert bool(state.EMPTY) and bool(state.REJECT)


def test_markdone_stores_only_valid_item_pks():
    el, obj, i1, _i2 = _mk()
    other = MarkDoneElement.objects.create(prompt="other")
    foreign = MarkDoneItem.objects.create(element=other, content="x")
    out = state.validate_state(el, obj, {"items": [i1.pk, foreign.pk, 999999]})
    assert out == {"items": [i1.pk]}


def test_markdone_coerces_string_pks():
    el, obj, i1, _i2 = _mk()
    assert state.validate_state(el, obj, {"items": [str(i1.pk)]}) == {"items": [i1.pk]}


def test_markdone_empty_selection_is_EMPTY_not_reject():
    el, obj, _i1, _i2 = _mk()
    assert state.validate_state(el, obj, {"items": []}) is state.EMPTY


def test_markdone_non_dict_payload_is_REJECT():
    el, obj, _i1, _i2 = _mk()
    assert state.validate_state(el, obj, ["nope"]) is state.REJECT


def test_markdone_items_not_a_list_is_REJECT():
    el, obj, _i1, _i2 = _mk()
    assert state.validate_state(el, obj, {"items": "abc"}) is state.REJECT


def test_unknown_content_type_is_REJECT():
    from courses.models import TextElement

    _course, unit = make_course_with_unit()
    obj = TextElement.objects.create(body="hi")
    el = add_element(unit, obj)
    assert state.validate_state(el, obj, {"anything": 1}) is state.REJECT


def test_validator_exception_maps_to_REJECT(monkeypatch):
    el, obj, _i1, _i2 = _mk()

    def boom(element, o, payload):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(state.VALIDATORS, "markdoneelement", boom)
    assert state.validate_state(el, obj, {"items": []}) is state.REJECT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_state_module.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'courses.state'`

- [ ] **Step 3: Write minimal implementation**

Create `courses/state.py`:

```python
"""Per-student practice state: the validator registry and its contract.

A pure module (no views, no writes) mirroring courses/quiz.py. Each participating
element type registers a validator that normalizes ITS OWN blob on save; the
storage layer never interprets a blob.

The contract -- validate(element, obj, payload) -> dict | EMPTY | REJECT:

  dict    STORE this (normalized) blob under the element's key.
  EMPTY   DELETE the key. The student asserted "nothing here" (all items unticked).
  REJECT  LEAVE the stored key untouched. The payload was malformed.

EMPTY and REJECT are OPPOSITE outcomes and are deliberately distinct truthy
sentinels: collapsing both into None/{}/False makes a malformed blob wipe the
student's prior good state -- a silent data-loss bug no 500 or log would reveal.

Validators check SHAPE and REFERENTIAL VALIDITY only; they never re-verify
correctness. Practice state is ungraded, absent from analytics, and the DOM is
already client-forgeable; the *_check endpoints remain the real check path.
"""


class _Sentinel:
    __slots__ = ("_name",)

    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return self._name


EMPTY = _Sentinel("EMPTY")
REJECT = _Sentinel("REJECT")


def _int_or_none(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _val_markdone(element, obj, payload):
    """{"items": [MarkDoneItem.pk, ...]} -- intersected with THIS element's items."""
    if not isinstance(payload, dict):
        return REJECT
    raw = payload.get("items")
    if not isinstance(raw, list):
        return REJECT
    incoming = {p for p in (_int_or_none(x) for x in raw) if p is not None}
    valid = set(obj.items.values_list("pk", flat=True))
    checked = sorted(incoming & valid)
    return {"items": checked} if checked else EMPTY


# Keyed by content_type.model (the ELEMENT_MODELS namespace) -- NOT the form key
# ("markdone") and NOT the transfer key ("mark_done"). Those three namespaces have
# been a recurring trap; the registry does not add a fourth.
VALIDATORS = {
    "markdoneelement": _val_markdone,
}


def validate_state(element, obj, payload):
    """Dispatch to the per-type validator. Unknown type or any exception -> REJECT."""
    fn = VALIDATORS.get(element.content_type.model)
    if fn is None:
        return REJECT
    try:
        return fn(element, obj, payload)
    except Exception:
        return REJECT
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_state_module.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check --fix courses/state.py courses/tests/test_state_module.py
uv run ruff format courses/state.py courses/tests/test_state_module.py
git add courses/state.py courses/tests/test_state_module.py
git commit -m "feat(state): validator registry with EMPTY/REJECT contract"
```

---

### Task 2: `UnitProgress.element_state` + the re-key migration

**Files:**
- Modify: `courses/models.py:1996` (`checklist_state` → `element_state`), `courses/models.py:453` (docstring)
- Create: `courses/migrations/00NN_unitprogress_element_state.py`
- Test: `courses/tests/test_state_migration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UnitProgress.element_state` — `JSONField(default=dict)`, shape `{"<Element.pk>": {...blob}}`.

- [ ] **Step 1: Replace the field and fix the stale docstring**

In `courses/models.py`, replace the `checklist_state` field (`:1996`):

```python
    # Per-student practice state, keyed by Element (join-row) pk:
    # {"<Element.pk>": {...per-type blob}}. Personal, ungraded, invisible to
    # analytics. Reset (progress_reset) clears this and nothing else.
    element_state = models.JSONField(default=dict)
```

And in `MarkDoneElement`'s docstring (`:453`) replace the last sentence — it names the **wrong key space** once this lands:

```python
    """Self-tracking checklist: an optional prompt + an ordered list of short
    statement items the student ticks to record "I've done this". Ungraded,
    lesson-only, nestable. Ticks persist per-student in
    UnitProgress.element_state, keyed by the ELEMENT JOIN-ROW pk (not this
    object's pk), under {"items": [MarkDoneItem.pk, ...]}."""
```

- [ ] **Step 2: Generate the migration skeleton**

```bash
uv run python manage.py makemigrations courses --noinput
```

**`--noinput` is required, not cosmetic.** `checklist_state` and `element_state` are both
`JSONField(default=dict)` — field-identical — so the autodetector fires
`ask_rename`: *"Was unitprogress.checklist_state renamed to unitprogress.element_state (a
JSONField)? [y/N]"*. Under a non-TTY call that hangs or raises EOFError; answering **y**
produces a `RenameField` and **silently no re-key at all** — the migration would ship doing
nothing. `--noinput` answers "no" → `AddField` + `RemoveField`, which is what we want. If you
run it interactively, answer **N**.

Expected: creates `courses/migrations/00NN_...py` with `AddField(element_state)` + `RemoveField(checklist_state)`. **Note the number it assigns — use that, do not rename to 0050.**

- [ ] **Step 3: Write the failing migration test**

Create `courses/tests/test_state_migration.py`:

```python
import pytest

from courses.migrations import _state_rekey as rekey

pytestmark = pytest.mark.django_db


def _apps_shim():
    """The real app registry satisfies apps.get_model in these unit tests; the
    migration itself receives the historical registry at runtime."""
    from django.apps import apps

    return apps


def test_forward_rekeys_content_pk_to_join_row_pk_and_wraps_items():
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import UnitProgress
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    student = make_verified_user()
    # Simulate the OLD shape: content pk key, BARE LIST value.
    up = UnitProgress.objects.create(student=student, unit=unit, element_state={})
    old = {str(obj.pk): [i1.pk]}

    new = rekey.forward_state(_apps_shim(), up.unit_id, old)

    assert new == {str(el.pk): {"items": [i1.pk]}}


def test_forward_drops_orphaned_key():
    from courses.models import UnitProgress
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    student = make_verified_user()
    up = UnitProgress.objects.create(student=student, unit=unit, element_state={})
    # 999999: no MarkDoneElement, therefore no join row -> already-dead data.
    assert rekey.forward_state(_apps_shim(), up.unit_id, {"999999": [1]}) == {}


def test_backward_unwraps_items_and_drops_non_markdone_blobs():
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import RevealGateElement
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    gate = RevealGateElement.objects.create()
    gate_el = add_element(unit, gate)

    state = {str(el.pk): {"items": [i1.pk]}, str(gate_el.pk): {"open": True}}
    out = rekey.backward_state(_apps_shim(), state)

    # markdone -> content pk + BARE list; the gate blob is DROPPED (checklist_state
    # structurally cannot represent it).
    assert out == {str(obj.pk): [i1.pk]}


def test_forward_rekeys_a_TAB_NESTED_element():
    # [S1] spec requirement. The nested join row is created directly (parent+tab_id),
    # NOT via add_element -- and its pk necessarily differs from the content pk,
    # because the Tabs join row is created first.
    from courses.models import Element
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import TabsElement
    from courses.models import UnitProgress
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(
        data={"tabs": [{"id": "t000001", "label": "One"}]}
    )
    parent = add_element(unit, tabs)
    obj = MarkDoneElement.objects.create(prompt="P")
    child = Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id="t000001"
    )
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    student = make_verified_user()
    up = UnitProgress.objects.create(student=student, unit=unit, element_state={})

    new = rekey.forward_state(_apps_shim(), up.unit_id, {str(obj.pk): [i1.pk]})

    assert new == {str(child.pk): {"items": [i1.pk]}}
    # Element and MarkDoneElement draw from INDEPENDENT sequences, so divergence is
    # overwhelmingly likely but not guaranteed -- skip rather than fail if they collide,
    # since the real assertion above already holds either way.
    if child.pk == obj.pk:
        pytest.skip("Element and MarkDoneElement pks coincided; re-key is untested here")


def test_forward_and_backward_handle_empty_and_absent_state():
    # [S1] spec requirement: "{} and absent state".
    assert rekey.forward_state(_apps_shim(), None, {}) == {}
    assert rekey.forward_state(_apps_shim(), None, None) == {}
    assert rekey.backward_state(_apps_shim(), {}) == {}
    assert rekey.backward_state(_apps_shim(), None) == {}


def test_forward_and_backward_ignore_garbage_without_raising():
    assert rekey.forward_state(_apps_shim(), None, {"x": "nope"}) == {}
    assert rekey.backward_state(_apps_shim(), {"y": "nope"}) == {}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_state_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: courses.migrations._state_rekey`

- [ ] **Step 5: Write the re-key helpers**

Create `courses/migrations/_state_rekey.py` (a plain module beside the migrations so it is unit-testable; migrations import it):

```python
"""Pure re-key helpers for the checklist_state -> element_state migration.

Extracted so they can be unit-tested directly; the migration passes the historical
app registry in. NEVER import concrete models here.
"""


def _markdone_ct(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    return ContentType.objects.filter(
        app_label="courses", model="markdoneelement"
    ).first()


def forward_state(apps, unit_id, old):
    """{"<MarkDoneElement.pk>": [item_pk, ...]} -> {"<Element.pk>": {"items": [...]}}.

    Two shape changes, not one: the KEY moves content-pk -> join-row-pk, and the
    VALUE (a bare list today) is WRAPPED under "items". Orphaned keys are dropped --
    already-dead data the current read path ignores.
    """
    if not isinstance(old, dict):
        return {}
    Element = apps.get_model("courses", "Element")
    ct = _markdone_ct(apps)
    if ct is None:
        return {}
    out = {}
    for key, items in old.items():
        try:
            object_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(items, list):
            continue
        # The GFK is effectively 1:1 (see TabsElement.join_row); order_by("pk") makes
        # the impossible >1 case deterministic AND identical to what join_row() and
        # the render path resolve to, so migration and runtime agree.
        row = (
            Element.objects.filter(
                content_type=ct, object_id=object_id, unit_id=unit_id
            )
            .order_by("pk")
            .first()
        )
        if row is None:
            continue  # orphan: element deleted
        out[str(row.pk)] = {"items": list(items)}
    return out


def backward_state(apps, new):
    """{"<Element.pk>": {...}} -> {"<MarkDoneElement.pk>": [item_pk, ...]}.

    LOSSY BY NECESSITY, and deliberately so: every non-markdone blob is DROPPED,
    because checklist_state structurally cannot represent it (a revealgate's
    {"open": true} has nowhere to go). Also unwraps "items" back to a bare list.
    """
    if not isinstance(new, dict):
        return {}
    Element = apps.get_model("courses", "Element")
    ct = _markdone_ct(apps)
    if ct is None:
        return {}
    out = {}
    for key, blob in new.items():
        try:
            row_pk = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(blob, dict):
            continue
        items = blob.get("items")
        if not isinstance(items, list):
            continue  # not a markdone blob -> drop
        row = Element.objects.filter(pk=row_pk, content_type=ct).first()
        if row is None:
            continue  # not a markdone element -> drop
        out[str(row.object_id)] = list(items)
    return out
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_state_migration.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Wire the helpers into the generated migration**

Edit the generated `courses/migrations/00NN_....py` so the operations are ordered **add → re-key → remove**:

```python
from django.db import migrations
from django.db import models

from courses.migrations._state_rekey import backward_state
from courses.migrations._state_rekey import forward_state


def forwards(apps, schema_editor):
    UnitProgress = apps.get_model("courses", "UnitProgress")
    for up in UnitProgress.objects.all().iterator():
        up.element_state = forward_state(apps, up.unit_id, up.checklist_state or {})
        up.save(update_fields=["element_state"])


def backwards(apps, schema_editor):
    UnitProgress = apps.get_model("courses", "UnitProgress")
    for up in UnitProgress.objects.all().iterator():
        up.checklist_state = backward_state(apps, up.element_state or {})
        up.save(update_fields=["checklist_state"])


class Migration(migrations.Migration):
    dependencies = [("courses", "0049_guessnumberelement_alter_element_content_type")]

    operations = [
        migrations.AddField(
            model_name="unitprogress",
            name="element_state",
            field=models.JSONField(default=dict),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(model_name="unitprogress", name="checklist_state"),
    ]
```

**Fix the `dependencies` entry to the migration `makemigrations` actually generated against.** No batching or rollback design is needed — there is no live instance and no real student data (confirmed with the user); the helpers are still written correctly and reversibly because dev databases hold data.

- [ ] **Step 8: Verify the migration applies cleanly both ways**

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate courses
uv run python manage.py migrate courses 0049
uv run python manage.py migrate courses
```
Expected: `makemigrations --check` reports no changes; all three `migrate` calls succeed (the middle one exercises `backwards`).

- [ ] **Step 9: Commit**

```bash
uv run ruff check --fix courses/ && uv run ruff format courses/
git add courses/models.py courses/migrations/ courses/tests/test_state_migration.py
git commit -m "feat(progress): element_state replaces checklist_state, keyed by join-row pk"
```

---

### Task 3: The render seam — pass the join row down, rename `checklist` → `state`

**Files:**
- Modify: `courses/models.py:340` (`ElementBase.render` + new `_state_context`), `:632`, `:658`, `:690`, `:720`, `:804`, `:906`, `:989` (the seven `**_kwargs` overrides), `:1135` (`TabsElement.render`), `:1244` (`TwoColumnElement.render`)
- Modify: `courses/templatetags/courses_extras.py:64-70`
- Test: `courses/tests/test_render_seam.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ElementBase._state_context(self, element, state, slug, node_pk) -> dict` — returns `{"el", "eid", "mine", "slug", "node_pk"}`. **No `mine_json`** (no slice-1 leaf emits `data-state`; it would be dead code). **No `checked`** (mark-done-only, added by `render`).
  - `ElementBase.render(self, *, element=None, state=None, slug=None, node_pk=None)`.
  - `render_element` generic branch passes `element=element, state=context.get("state")`.

**NINE `render()` signatures change.** Two different sets of seven overlap in five members — do not conflate them:
- The **seven `eid` sites** (re-derive their own join-row pk): FillGate `:635`, SwitchGate `:661`, GuessNumber `:693`, SwitchGrid `:723`, FillTable `:910`, **Tabs** (via `join_row()` in `render`), **TwoColumn** (same).
- The **seven `**_kwargs` overrides**: FillGate `:632`, SwitchGate `:658`, GuessNumber `:690`, SwitchGrid `:720`, **Table `:804`**, FillTable `:906`, **Gallery `:989`**.
- Plus Tabs `:1135` and TwoColumn `:1244`, which already take `checklist=` and must be renamed. **Total: nine.**

- [ ] **Step 1: Write the failing test**

Replace `courses/tests/test_render_seam.py` entirely (its current calls use the old `checklist=` kwarg — this is the very `TypeError` class the seam guards, but in test code):

```python
import pytest

from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GalleryElement
from courses.models import GuessNumberElement
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

# Every concrete render() the generic branch can reach. A signature change that
# TypeErrors any of these breaks EVERY lesson containing that type -- the exact
# class of break plan-review and code-review both caught on the mark-done build.
# (model, required_kwargs) -- GuessNumberElement.target is NOT NULL with no default,
# so a bare .create() IntegrityErrors instead of testing the signature.
CONCRETES = [
    (TextElement, {}),
    (FillGateElement, {}),
    (SwitchGateElement, {}),
    (GuessNumberElement, {"target": 42}),
    (SwitchGridElement, {}),
    (TableElement, {}),
    (FillTableElement, {}),
    (GalleryElement, {}),
    (TabsElement, {}),
    (TwoColumnElement, {}),
]


@pytest.mark.parametrize(
    "model,kwargs", CONCRETES, ids=[m.__name__ for m, _ in CONCRETES]
)
def test_render_accepts_the_state_kwargs(model, kwargs):
    _course, unit = make_course_with_unit()
    obj = model.objects.create(**kwargs)
    el = add_element(unit, obj)
    # No TypeError, and no exception from any template.
    obj.render(element=el, state={}, slug="x", node_pk=unit.pk)


def test_fillgate_renders_the_eid():
    # NB this does NOT prove provenance: with one join row, a self-lookup and the passed
    # `element` resolve to the SAME pk, and it passes even before this task's change
    # (render(self, **_kwargs) absorbs element=/state= without a TypeError). Provenance is
    # covered with teeth by test_leaf_render_does_not_self_look_up_its_join_row below.
    _course, unit = make_course_with_unit()
    obj = FillGateElement.objects.create(stem="", answers=[])
    el = add_element(unit, obj)
    html = obj.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert str(el.pk) in html


def test_eid_is_zero_sentinel_when_no_join_row():
    # eid == 0 means "a content object with no join row" (transient/mid-create).
    obj = FillGateElement.objects.create(stem="", answers=[])
    obj.render(element=None, state={}, slug=None, node_pk=None)  # no TypeError


def test_markdone_checked_is_resolved_from_the_join_row_key():
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    i2 = MarkDoneItem.objects.create(element=obj, content="b")
    # Keyed by the JOIN-ROW pk. Keying by obj.pk (the old content-pk space) must NOT
    # resolve -- that is the whole point of the re-key.
    html = obj.render(element=el, state={el.pk: {"items": [i1.pk]}}, slug="s", node_pk=unit.pk)
    # Exactly one ticked box, and it is i1. ("checkbox" does not contain "checked".)
    assert html.count("checked") == 1
    # Scope the search to the ITEM LIST before indexing. Searching the whole document is
    # fragile: the hidden `element` field renders value="<pk>" BEFORE the list, and
    # Element / MarkDoneElement / MarkDoneItem draw from independent Postgres sequences
    # that are not reset between tests -- so that number can equal i2.pk, and the offset
    # comparison would fail against a CORRECT implementation.
    items_html = html[html.index('<ul class="markdone__list"'):]
    assert str(i1.pk) in items_html and str(i2.pk) in items_html  # both rendered
    i1_pos = items_html.index(f'value="{i1.pk}"')
    i2_pos = items_html.index(f'value="{i2.pk}"')
    assert i1_pos < items_html.index("checked") < i2_pos  # the tick sits on i1, not i2


def test_container_eid_comes_from_the_passed_row_not_join_row(monkeypatch):
    """Pin the containers' eid provenance BY IDENTITY: assertNumQueries cannot police
    them, because resolved_tabs() still calls join_row() (and must). Patch join_row to
    raise -- if render() still re-derives eid, this fails loudly.
    """
    _course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "One"}]})
    el = add_element(unit, obj)
    real = TabsElement.join_row
    calls = {"n": 0}

    def counting(self):
        calls["n"] += 1
        return real(self)

    monkeypatch.setattr(TabsElement, "join_row", counting)
    html = obj.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert str(el.pk) in html
    # resolved_tabs() legitimately calls join_row ONCE. If render() also calls it for
    # eid, this is 2 -- the lookup this task deletes.
    assert calls["n"] == 1


LEAF_SITES = [
    (FillGateElement, {}),
    (SwitchGateElement, {}),
    (GuessNumberElement, {"target": 42}),
    (SwitchGridElement, {}),
    (FillTableElement, {}),
]


@pytest.mark.parametrize(
    "model,kwargs", LEAF_SITES, ids=[m.__name__ for m, _ in LEAF_SITES]
)
def test_leaf_render_does_not_self_look_up_its_join_row(monkeypatch, model, kwargs):
    """The five leaves must take eid from the PASSED row, not re-derive it.

    Deterministic by construction: make `.elements` explode. A raw assertNumQueries
    baseline would need a magic number, and could not police Tabs/TwoColumn anyway --
    their resolved_*() join_row() call survives by design, so a re-introduced eid
    lookup would hide inside the total.
    """
    _course, unit = make_course_with_unit()
    obj = model.objects.create(**kwargs)
    el = add_element(unit, obj)

    class _Boom:
        def __get__(self, instance, owner):
            raise AssertionError(
                "render() self-looked-up its join row; take eid from `element`"
            )

    monkeypatch.setattr(model, "elements", _Boom())
    html = obj.render(element=el, state={}, slug="x", node_pk=unit.pk)
    assert str(el.pk) in html


def test_markdone_ignores_the_old_content_pk_key():
    # Falsification guard for the re-key: state keyed by the CONTENT pk must resolve
    # to nothing now. Without this, a half-done migration looks green.
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    html = obj.render(element=el, state={obj.pk: {"items": [i1.pk]}}, slug="s", node_pk=unit.pk)
    if obj.pk != el.pk:  # if the two pk spaces happen to coincide, the test is vacuous
        assert "checked" not in html


def test_markdone_tolerates_a_drifted_blob_and_renders_fresh():
    # Read-side fail-open: a malformed stored blob is treated as absent, never a 500.
    _course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    el = add_element(unit, obj)
    MarkDoneItem.objects.create(element=obj, content="a")
    for drifted in ({el.pk: "nope"}, {el.pk: {"items": "abc"}}, {el.pk: {}}):
        html = obj.render(element=el, state=drifted, slug="s", node_pk=unit.pk)
        assert "checked" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_render_seam.py -v`
Expected: FAIL — `TypeError: render() got an unexpected keyword argument 'element'`

- [ ] **Step 3: Rewrite `ElementBase.render` and add `_state_context`**

In `courses/models.py`, replace `ElementBase.render` (`:340`):

```python
    def _state_context(self, element, state, slug, node_pk):
        """{el, eid, mine, slug, node_pk} -- the leaf contract.

        NOT `checked`: mark-done-only, added by ElementBase.render below.
        NOT `mine_json`: no slice-1 leaf emits data-state, so serializing here
        would be dead code. Slice 2 adds it with the first client-restoring leaf.

        `eid == 0` means "a content object with no join row" (transient/mid-create),
        NOT "editor preview" -- the preview passes REAL join rows and is made inert
        by its context lacking slug/node_pk (so `{% url ... as save_url %}` -> "").
        """
        eid = element.pk if element is not None else 0
        mine = (state or {}).get(eid)
        if not isinstance(mine, dict):
            mine = {}  # read-side fail-open: drifted blob -> render fresh, never 500
        return {
            "el": self,
            "eid": eid,
            "mine": mine,
            "slug": slug,
            "node_pk": node_pk,
        }

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        name = self._meta.model_name
        ctx = self._state_context(element, state, slug, node_pk)
        raw = ctx["mine"].get("items", ())
        if not isinstance(raw, (list, tuple)):
            raw = ()
        checked = set()
        for x in raw:
            try:
                checked.add(int(x))
            except (TypeError, ValueError):
                continue
        return render_to_string(
            f"courses/elements/{name}.html", {**ctx, "checked": checked}
        )
```

- [ ] **Step 4: Update the seven `**_kwargs` overrides**

For **FillGate (`:632`)**, **SwitchGate (`:658`)**, **GuessNumber (`:690`)**, **SwitchGrid (`:720`)**, **FillTable (`:906`)** — take the real signature and **delete the self-lookup**, taking `eid` from the passed row. FillGate becomes:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        return render_to_string("courses/elements/fillgateelement.html", ctx)
```

Apply the identical shape to SwitchGate (`switchgateelement.html`), GuessNumber (`guessnumberelement.html`), SwitchGrid (`switchgridelement.html`). **FillTable (`:906`) keeps its extra `data` key:**

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        ctx = self._state_context(element, state, slug, node_pk)
        ctx["data"] = self.normalize_data(self.data)
        return render_to_string("courses/elements/filltableelement.html", ctx)
```

**Table (`:804`) and Gallery (`:989`) never resolved `eid` and persist nothing** — they need the signature only. Table:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        data = self.normalize_data(self.data)
        return render_to_string(
            "courses/elements/tableelement.html", {"el": self, "data": data}
        )
```

Gallery (`:989`): change only its `def render(self, **_kwargs):` line to
`def render(self, *, element=None, state=None, slug=None, node_pk=None):` and leave its body untouched.

- [ ] **Step 5: Update the two containers**

`TabsElement.render` (`:1135`) — rename the kwargs and **re-inject the whole `state` MAP** (not a resolved blob: children resolve their own), taking `eid` from the passed row:

```python
    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        return render_to_string(
            "courses/elements/tabselement.html",
            {
                "el": self,
                "tabs": self.resolved_tabs(),
                "eid": element.pk if element is not None else 0,
                "state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )
```

Apply the same change to `TwoColumnElement.render` (`:1244`), keeping its own `columns`/template. **Do NOT remove the `join_row()` call inside `resolved_tabs()` / `resolved_columns()`** — those resolve children and are shared with `has_math` and the export walk, which have no `element` to be handed.

- [ ] **Step 6: Update `render_element`'s generic branch**

In `courses/templatetags/courses_extras.py`, replace the tail (`:64-70`):

```python
    return mark_safe(  # noqa: S308 — each element template escapes its own fields
        obj.render(
            element=element,
            state=context.get("state"),
            slug=context.get("slug"),
            node_pk=context.get("node_pk"),
        )
    )
```

- [ ] **Step 7: Run the seam tests**

Run: `uv run pytest courses/tests/test_render_seam.py -v`

Expected: **PASS (21 tests)** — 10 (`test_render_accepts_the_state_kwargs`) + 5
(`test_leaf_render_does_not_self_look_up_its_join_row`) + 6 unparametrized.

**These are all direct-`render()` tests, deliberately.** The spec's `[S1]` lesson-GET
parametrization lives in **Task 4**, not here: `build_lesson_context` still reads the removed
`checklist_state` at `views.py:365` until Task 4 Step 3, so any real `lesson_unit` GET raises
`AttributeError` right now. See the red window noted in Tasks 2 and 4.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix courses/ && uv run ruff format courses/
git add courses/models.py courses/templatetags/courses_extras.py courses/tests/test_render_seam.py
git commit -m "feat(seam): pass the Element join row into render(); checklist -> state"
```

---

### Task 4: `build_lesson_context` reads `element_state`

**Files:**
- Modify: `courses/views.py:348-366` (the state read), `:390` (the context key)
- Test: `courses/tests/test_markdone_render.py`
- Test: `courses/tests/test_render_seam.py` (the `[S1]` lesson-GET parametrization moved here from Task 3 — it needs this task's state read to pass)

**Interfaces:**
- Consumes: `UnitProgress.element_state` (Task 2).
- Produces: `build_lesson_context(...)["state"]` — int-keyed `{element_pk: blob}`. The `"checklist"` key is **gone**.

- [ ] **Step 1: Update the existing render tests to the new field**

`courses/tests/test_markdone_render.py` constructs `checklist_state=` at `:37`, `:58`, `:95` — a `TypeError` once the field is gone. Re-key each to the join-row pk and wrap under `"items"`:

```python
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
```

**Where `row` comes from differs by site — the third one has no `add_element` call:**

- **`:37` and `:58`** — `add_element(unit, el)` returns the `Element` join row, but these sites
  discard it. Capture it: `row = add_element(unit, el)`.
- **`:95`** (`test_nested_in_tabs_checklist_resolves_checked`) — this site does **not** call
  `add_element`. It builds the child join row directly at `:91-93`:
  `Element.objects.create(unit=unit, content_object=el, parent=parent, tab_id="t000001")`,
  discarding the return. Capture **that** call's return value and key off its pk.

Also update the `:82` comment: `checklist_state` → `element_state`.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_render.py -v`
Expected: FAIL — **`AttributeError: 'UnitProgress' object has no attribute 'checklist_state'`**, raised from `views.py:365` inside `build_lesson_context` (Task 2 removed the field; this task is what stops reading it). It is an ERROR, not an assertion failure.

**Expected red window:** every lesson-page suite stays red from Task 2's commit until this task lands. That is intentional and bounded — do not "fix" it by reverting Task 2.

- [ ] **Step 3: Rewrite the state read**

In `courses/views.py`, replace `:348-366`:

```python
    progress = None
    seen_ids = set()
    state = {}
    state_row = None
    if is_enrolled(user, node.course):
        # UNCHANGED: this row feeds progress/seen_ids/seen_count. The rule is "the
        # STATE read never creates a row", NOT "no get_or_create on a GET".
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
        state_row = progress
    elif user.is_authenticated:
        # Non-enrolled but can view (author/teacher): read an EXISTING row for their
        # practice state (it persists too — see element_state_save) WITHOUT creating
        # one on GET, so passive viewers never get a spurious progress row.
        state_row = UnitProgress.objects.filter(student=user, unit=node).first()
    if state_row:
        # int-keyed {Element.pk: blob} — the render seam looks up by the join-row pk.
        # Read-side fail-open: drop any non-int-coercible key and any non-dict value
        # rather than 500 the lesson from inside a template tag.
        state = {}
        for k, blob in (state_row.element_state or {}).items():
            if not isinstance(blob, dict):
                continue
            try:
                state[int(k)] = blob
            except (TypeError, ValueError):
                continue
```

And in the returned dict, replace `"checklist": checklist,` (`:390`) with:

```python
        "state": state,
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest courses/tests/test_markdone_render.py -v`
Expected: PASS

- [ ] **Step 5: Add the drifted-row guard test**

Append to `courses/tests/test_markdone_render.py`:

```python
def test_drifted_element_state_row_renders_the_lesson_fresh(client):
    # Read-side fail-open at the build_lesson_context level: a hand-written drifted
    # row must render 200, not 500 from inside a template tag.
    from courses.models import Enrollment
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from courses.models import UnitProgress
    from django.urls import reverse
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    course, unit = make_course_with_unit()
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={"not-an-int": {"items": [1]}, "999": "not-a-dict"},
    )
    client.force_login(student)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
```

- [ ] **Step 6: Add the spec's [S1] lesson-GET parametrization — it belongs HERE, not in Task 3**

This is the spec's `[S1]` render-seam gate: *render a LESSON containing each concrete, top-level AND
nested, asserting 200*. It cannot live in Task 3 — `build_lesson_context` still read the removed
`checklist_state` until Step 3 above, so every lesson GET raised `AttributeError`. Now that the state
read is fixed, it can go green.

It catches what the direct-`render()` tests structurally cannot: a `render_element`/context-key
mismatch, and the container re-injection path — i.e. exactly what Task 3 Step 6 and this task's Step 3
change.

Append to `courses/tests/test_render_seam.py` (reusing its existing `CONCRETES` list and imports; add
`TabsElement`/`TwoColumnElement`/`Element`/`Enrollment` imports if not already present):

```python
@pytest.mark.parametrize(
    "model,kwargs", CONCRETES, ids=[m.__name__ for m, _ in CONCRETES]
)
@pytest.mark.parametrize("placement", ["top", "tabs", "twocolumn"])
def test_lesson_renders_200_with_each_concrete(client, model, kwargs, placement):
    """The spec's [S1] gate: render a LESSON containing each concrete, top-level AND
    nested, asserting 200. The direct render() test above cannot catch a
    render_element/context-key mismatch -- it bypasses the tag, the context builder
    and the view, which is exactly what Task 3 Step 6 changes.
    """
    from courses.models import Element
    from courses.models import Enrollment
    from django.urls import reverse
    from tests.factories import make_verified_user

    course, unit = make_course_with_unit()
    obj = model.objects.create(**kwargs)
    if placement == "top":
        add_element(unit, obj)
    elif placement == "tabs":
        parent_obj = TabsElement.objects.create(
            data={"tabs": [{"id": "t000001", "label": "One"}]}
        )
        parent = add_element(unit, parent_obj)
        Element.objects.create(
            unit=unit, content_object=obj, parent=parent, tab_id="t000001"
        )
    else:
        parent_obj = TwoColumnElement.objects.create(
            data={"columns": [{"id": "c000001"}, {"id": "c000002"}]}
        )
        parent = add_element(unit, parent_obj)
        Element.objects.create(
            unit=unit, content_object=obj, parent=parent, tab_id="c000001"
        )
    student = make_verified_user(username="seam", email="seam@school.edu")
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert r.status_code == 200
```

Run: `uv run pytest courses/tests/test_render_seam.py -v`
Expected: **PASS (51 tests)** — the 21 from Task 3 plus 30 here (10 concretes × 3 placements).

- [ ] **Step 7: Run and commit**

```bash
uv run pytest courses/tests/test_markdone_render.py courses/tests/test_render_seam.py -v
uv run ruff check --fix courses/ && uv run ruff format courses/
git add courses/views.py courses/tests/test_markdone_render.py courses/tests/test_render_seam.py
git commit -m "feat(lesson): read element_state into context as `state`, fail-open on drift"
```

---

### Task 5: `element_state_save` replaces `markdone_save`

**Files:**
- Modify: `courses/views.py:566-632` (rename + generalise), `courses/urls.py:25-28`
- Modify: `templates/courses/elements/markdoneelement.html`
- Create: `courses/tests/test_element_state_endpoint.py`
- Modify: `courses/tests/test_markdone_render.py` (the two `name="element" value=` assertions at `:42`/`:100`)
- **Delete**: `courses/tests/test_markdone_endpoint.py` (superseded by the new suite)

**Interfaces:**
- Consumes: `courses.state.validate_state`/`EMPTY`/`REJECT` (Task 1); `UnitProgress.element_state` (Task 2).
- Produces: route `courses:element_state_save` at `courses/<slug>/u/<node_pk>/state/`.
  - JSON in: `{"element": <join_row_pk>, "state": {...}}` → `JsonResponse({"element": pk, "state": <blob NOW STORED>})`.
  - Form-encoded in (mark-done no-JS only): `element` + repeated `item` → 302 + `#markdone-<eid>`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_element_state_endpoint.py`:

```python
import json

import pytest
from django.urls import reverse

from courses.models import ChoiceQuestionElement
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import MarkDoneItem
from courses.models import TextElement
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _url(course, unit):
    return reverse("courses:element_state_save", args=[course.slug, unit.pk])


def _setup():
    course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    i2 = MarkDoneItem.objects.create(element=obj, content="b")
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    return course, unit, obj, row, i1, i2, student


def _post(client, course, unit, payload):
    return client.post(
        _url(course, unit), data=json.dumps(payload), content_type="application/json"
    )


def test_json_persists_under_the_join_row_pk(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": [i1.pk]}})
    assert r.status_code == 200
    assert r.json() == {"element": row.pk, "state": {"items": [i1.pk]}}
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"items": [i1.pk]}}


def test_empty_selection_drops_the_key_and_echoes_empty(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": []}})
    assert r.status_code == 200 and r.json()["state"] == {}
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(row.pk) not in up.element_state


def test_rejected_blob_echoes_the_stored_blob_and_leaves_it_untouched(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"items": [i1.pk]}}
    )
    client.force_login(student)
    # "items": "abc" -> REJECT (not EMPTY): the stored key must SURVIVE.
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": "abc"}})
    assert r.status_code == 200
    assert r.json()["state"] == {"items": [i1.pk]}  # echo = what is STORED
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"items": [i1.pk]}}


def test_rejected_blob_creates_no_unitprogress_row(client):
    # validate BEFORE get_or_create: a garbage POST must not spawn a row.
    course, unit, _obj, row, _i1, _i2, student = _setup()
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": "abc"}})
    assert r.status_code == 200 and r.json()["state"] == {}
    assert not UnitProgress.objects.filter(student=student, unit=unit).exists()


def test_unknown_content_type_is_skipped_not_500(client):
    course, unit = make_course_with_unit()
    obj = TextElement.objects.create(body="hi")
    row = add_element(unit, obj)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {"x": 1}})
    assert r.status_code == 200 and r.json()["state"] == {}


def test_forged_element_400(client):
    course, unit, _obj, _row, _i1, _i2, student = _setup()
    client.force_login(student)
    assert _post(client, course, unit, {"element": 999999, "state": {}}).status_code == 400


def test_element_from_another_unit_400(client):
    course, unit, _obj, _row, _i1, _i2, student = _setup()
    _c2, unit2 = make_course_with_unit()
    other = MarkDoneElement.objects.create(prompt="X")
    row2 = add_element(unit2, other)
    client.force_login(student)
    assert _post(client, course, unit, {"element": row2.pk, "state": {}}).status_code == 400


def test_state_and_fields_both_present_400(client):
    course, unit, _obj, row, _i1, _i2, student = _setup()
    client.force_login(student)
    r = _post(client, course, unit, {"element": row.pk, "state": {}, "fields": {}})
    assert r.status_code == 400


def test_fields_on_a_non_question_400(client):
    course, unit, _obj, row, _i1, _i2, student = _setup()
    client.force_login(student)
    assert _post(client, course, unit, {"element": row.pk, "fields": {}}).status_code == 400


def test_fields_on_a_question_400_slice_1_gate(client):
    # SLICE-1 ONLY: no question validator is registered yet. Slice 3 REPLACES this
    # assertion (it is the one endpoint test slice 3 does not keep).
    course, unit = make_course_with_unit()
    q = ChoiceQuestionElement.objects.create(stem="s")
    row = add_element(unit, q)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    assert _post(client, course, unit, {"element": row.pk, "fields": {}}).status_code == 400


def test_previewer_persists(client):
    # PR #136 rule: ANY viewer with can_access_course persists their own practice
    # state — the write gate is can_access_course, NOT is_enrolled. The author is
    # NOT enrolled; under an is_enrolled gate this silently no-ops.
    # NB make_course_with_unit(owner=...) — it mints its own UserFactory owner by
    # default, and force_login on an unverified user is intercepted by allauth's
    # mandatory-verification middleware. Pass a verified one.
    author = make_verified_user(username="author", email="author@school.edu")
    course, unit = make_course_with_unit(owner=author)
    obj = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, obj)
    i1 = MarkDoneItem.objects.create(element=obj, content="a")
    client.force_login(author)
    r = _post(client, course, unit, {"element": row.pk, "state": {"items": [i1.pk]}})
    assert r.status_code == 200
    assert UnitProgress.objects.filter(student=author, unit=unit).exists()


def test_stranger_denied(client):
    course, unit, _obj, row, _i1, _i2, _student = _setup()
    stranger = make_verified_user(username="stranger", email="stranger@school.edu")
    client.force_login(stranger)
    assert _post(client, course, unit, {"element": row.pk, "state": {}}).status_code == 403


def test_quiz_node_404s(client):
    from courses.models import ContentNode

    course, unit, _obj, row, _i1, _i2, student = _setup()
    unit.unit_type = ContentNode.UnitType.QUIZ
    unit.save()
    client.force_login(student)
    assert _post(client, course, unit, {"element": row.pk, "state": {}}).status_code == 404


def test_foreign_course_node_404s(client):
    course, _unit, _obj, _row, _i1, _i2, student = _setup()
    _c2, unit2 = make_course_with_unit()
    client.force_login(student)
    r = client.post(
        reverse("courses:element_state_save", args=[course.slug, unit2.pk]),
        data=json.dumps({"element": 1, "state": {}}),
        content_type="application/json",
    )
    assert r.status_code == 404


def test_concurrent_two_element_save_does_not_clobber(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    obj2 = MarkDoneElement.objects.create(prompt="Q")
    row2 = add_element(unit, obj2)
    j1 = MarkDoneItem.objects.create(element=obj2, content="c")
    client.force_login(student)
    _post(client, course, unit, {"element": row.pk, "state": {"items": [i1.pk]}})
    _post(client, course, unit, {"element": row2.pk, "state": {"items": [j1.pk]}})
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {
        str(row.pk): {"items": [i1.pk]},
        str(row2.pk): {"items": [j1.pk]},
    }


def test_no_js_form_persists_and_anchors_to_the_join_row_pk(client):
    course, unit, _obj, row, i1, _i2, student = _setup()
    client.force_login(student)
    r = client.post(_url(course, unit), data={"element": row.pk, "item": [str(i1.pk)]})
    assert r.status_code == 302 and r.url.endswith(f"#markdone-{row.pk}")
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {str(row.pk): {"items": [i1.pk]}}


def test_anonymous_is_redirected_by_login_required(client):
    # [S1] spec requirement. UnitProgress.student is a non-null FK; an AnonymousUser
    # is not a valid value, so @login_required must reject BEFORE the body runs.
    course, unit, _obj, row, _i1, _i2, _student = _setup()
    r = _post(client, course, unit, {"element": row.pk, "state": {}})
    assert r.status_code == 302 and "/login" in r.url


def test_no_js_form_on_a_non_markdone_element_400(client):
    course, unit = make_course_with_unit()
    obj = TextElement.objects.create(body="hi")
    row = add_element(unit, obj)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    assert client.post(_url(course, unit), data={"element": row.pk}).status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_element_state_endpoint.py -v`
Expected: FAIL — `NoReverseMatch: 'element_state_save' is not a valid view function or pattern name`

- [ ] **Step 3: Replace the view**

In `courses/views.py`, replace `markdone_save` (`:566-632`) with:

```python
@require_POST
@login_required
def element_state_save(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied

    is_json = request.content_type == "application/json"
    raw_fields = None
    if is_json:
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid JSON")
        if not isinstance(data, dict):
            return HttpResponseBadRequest("expected an object")
        raw_element = data.get("element")
        payload = data.get("state")
        raw_fields = data.get("fields")
        if raw_fields is not None and payload is not None:
            return HttpResponseBadRequest("state and fields are mutually exclusive")
    else:
        # Form-encoded fallback: mark-done's no-JS form only. It posts `element` +
        # a repeated `item` field; synthesize the blob so BOTH paths run the SAME
        # validator. getlist yields STRINGS -- the validator int-coerces.
        raw_element = request.POST.get("element")
        payload = {"items": request.POST.getlist("item")}

    try:
        element_pk = int(raw_element)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad element")

    element = Element.objects.filter(pk=element_pk, unit=node).first()
    if element is None:
        return HttpResponseBadRequest("unknown element")
    obj = element.content_object
    if obj is None:
        return HttpResponseBadRequest("unknown element")

    model = element.content_type.model
    if raw_fields is not None:
        # SLICE 1: the question write path does not exist yet. Slice 3 replaces this
        # branch with build_answer + answer_to_json behind an isinstance fallback.
        return HttpResponseBadRequest("fields is not supported yet")
    if not is_json and model != "markdoneelement":
        return HttpResponseBadRequest("form-encoded save is mark-done only")

    # Validate BEFORE the atomic write block: a rejected/unknown save must not spawn
    # a UnitProgress row for a passive previewer.
    result = state_svc.validate_state(element, obj, payload)

    def _stored():
        row = UnitProgress.objects.filter(student=request.user, unit=node).first()
        blob = (row.element_state or {}).get(str(element.pk)) if row else None
        return blob if isinstance(blob, dict) else {}

    def _resp(blob):
        if is_json:
            return JsonResponse({"element": element.pk, "state": blob})
        return redirect(
            reverse("courses:lesson_unit", args=[slug, node_pk])
            + f"#markdone-{element.pk}"
        )

    if result is state_svc.REJECT:
        # Echo what is STORED (never the rejected input): the client ADOPTS the echo,
        # which makes a silent rejection self-correcting rather than a desync.
        return _resp(_stored())

    # Practice state is personal self-tracking (ungraded, absent from analytics), so
    # ANY viewer who can access the lesson persists their own -- not just enrolled
    # students. This deliberately diverges from seen/quiz (which ignore previewers so
    # authors don't pollute their own progress/analytics); the can_access_course gate
    # above is the only guard the write needs.
    with transaction.atomic():
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        if result is state_svc.EMPTY:
            progress.element_state.pop(str(element.pk), None)
            blob = {}
        else:
            progress.element_state[str(element.pk)] = result
            blob = result
        progress.save()
    return _resp(blob)
```

Add the imports at the top of `courses/views.py` (alphabetical within their groups):

```python
from courses import state as state_svc
from courses.models import Element
```

(`Element` may already be imported — check before adding a duplicate.)

- [ ] **Step 4: Replace the route**

In `courses/urls.py`, replace the `markdone_save` path (**`:24-28`** — `path(` opens at `:24`; replacing only 25-28 leaves a duplicated `path(` and a SyntaxError):

```python
    path(
        "courses/<slug:slug>/u/<int:node_pk>/state/",
        views.element_state_save,
        name="element_state_save",
    ),
```

- [ ] **Step 5: Move the template's four content-pk sites to the join-row pk**

Replace `templates/courses/elements/markdoneelement.html` **lines 1-6** (`{% load i18n %}` is line 1 and is included in the block below -- replacing 2-6 duplicates the load tag). All four move **together** — missing the hidden field writes a key the read path never looks up; missing the `id`/anchor leaves the redirect fragment and the DOM id in different pk spaces:

```html
{% load i18n %}
{% url 'courses:element_state_save' slug=slug node_pk=node_pk as save_url %}
<div class="markdone" data-markdone data-markdone-url="{{ save_url }}">
  <form method="post" action="{{ save_url }}#markdone-{{ eid }}" id="markdone-{{ eid }}">
    {% csrf_token %}
    <input type="hidden" name="element" value="{{ eid }}">
```

- [ ] **Step 6: Re-point the two hidden-field assertions the template change breaks**

`courses/tests/test_markdone_render.py:42` and `:100` both assert
`f'name="element" value="{el.pk}"' in body` — the **content-object** pk. Step 5 just changed that
field to emit the **join-row** pk, so both now fail. Task 4 only touched the `checklist_state=`
constructor sites (`:37`, `:58`, `:95`), so this is not yet fixed.

At each site, capture the join row and assert on it instead:

```python
    assert f'name="element" value="{row.pk}"' in body
```

At `:100` (`test_nested_in_tabs_checklist_resolves_checked`) `row` is the child `Element` created
at `:91-93` (see Task 4 Step 1) — **not** `el`. This site is the one that proves the point: the Tabs
join row is created first, so `el.pk` and the markdone join-row pk are guaranteed to differ.

- [ ] **Step 7: Delete the superseded endpoint tests**

`courses/tests/test_markdone_endpoint.py` asserts `checklist_state` at `:42`, `:51`, `:58`, `:67`, `:116`, `:137` and reverses `courses:markdone_save`. Its coverage is now duplicated by `test_element_state_endpoint.py`. **Delete the file** (this supersedes the spec's "re-keyed to join-row pks" — porting it would duplicate the new suite verbatim):

```bash
git rm courses/tests/test_markdone_endpoint.py
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest courses/tests/test_element_state_endpoint.py -v courses/tests/test_markdone_render.py`
Expected: PASS (18 endpoint tests + the re-pointed render assertions)

- [ ] **Step 9: Commit**

```bash
uv run ruff check --fix courses/ && uv run ruff format courses/
git add -A courses/views.py courses/urls.py courses/tests/ templates/courses/elements/markdoneelement.html
git commit -m "feat(state): element_state_save replaces markdone_save"
```

---

### Task 6: `markdone.js` — adopt the echo, last-write-wins

**Files:**
- Modify: `courses/static/courses/js/markdone.js`
- Test: `courses/tests/test_markdone_scripts.py` (assert the export survives)

**Interfaces:**
- Consumes: route `courses:element_state_save` (Task 5); `eid` in the template (Task 5).
- Produces: `window.libliInitMarkDone(root)` — **same name, same arity** (`editor.js:83` calls it after every fragment swap).

**This is a rewrite, not a tweak.** Today it posts `{element, items}`, reads `{"element","items"}`, and keeps `last` as a per-checkbox `{value: bool}` map. It now posts `{element, state:{items:[...]}}`, **adopts** the echoed blob, and must guard the race adoption introduces.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_markdone_scripts.py`:

```python
def test_markdone_js_posts_the_state_envelope_and_guards_the_race():
    from pathlib import Path

    src = Path("courses/static/courses/js/markdone.js").read_text(encoding="utf-8")
    # The envelope changed: {element, state:{items}} -- not the old {element, items}.
    # NB each assertion is separate and non-vacuous. An earlier draft wrote
    #   assert "state:" in src and '"items"' in src or "items:" in src
    # which Python reads as (A and B) or C -- and C ("items:" in src) is TRUE of the
    # UNMODIFIED file, so it passed before the change was made and tested nothing.
    assert "state: { items: items }" in src
    # window.libliInitMarkDone must survive with the same name AND arity: editor.js:83
    # calls it over the preview pane after every fragment swap.
    assert "window.libliInitMarkDone = initMarkDone;" in src
    # Last-write-wins: adoption without a sequence guard unticks a box the student
    # just ticked (tick A -> tick B -> A's echo re-renders the widget from
    # {"items":[A]}). This is a regression adoption INTRODUCES -- the old client
    # ignored the response body entirely.
    assert "var mine = ++seq;" in src
    assert "if (mine !== seq) return;" in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_scripts.py -v`
Expected: FAIL — `assert "state: { items: items }" in src` (the FIRST assertion must fail
against the unmodified file; if it passes, the assertion is vacuous and needs fixing before you
proceed).

- [ ] **Step 3: Rewrite the client**

Replace `courses/static/courses/js/markdone.js` entirely:

```javascript
(function () {
  "use strict";
  window.__markdoneBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function boxes(root) {
    return root.querySelectorAll('input[type="checkbox"][name="item"]');
  }

  // Last-known-persisted as a {checkboxValue: bool} map over EVERY box -- deliberately
  // the DOM's shape, not the server's ({"items": [...]}), because paint() consumes it.
  // Adoption therefore TRANSLATES the echoed array into this shape; it is not an
  // assignment.
  function persisted(root) {
    var s = {};
    boxes(root).forEach(function (cb) { s[cb.value] = cb.checked; });
    return s;
  }

  function paint(root, map) {
    boxes(root).forEach(function (cb) {
      cb.checked = !!map[cb.value];
      var li = cb.closest(".markdone__item");
      if (li) li.classList.toggle("on", cb.checked);
    });
  }

  function initOne(root) {
    if (root.dataset.markdoneReady === "1") return;
    root.dataset.markdoneReady = "1";
    var url = root.getAttribute("data-markdone-url");
    var saveBtn = root.querySelector("[data-markdone-save]");
    // The Save button is the no-JS fallback only; whenever JS runs we hide it — incl.
    // the editor preview (empty url), where it can't submit anyway.
    if (saveBtn) saveBtn.hidden = true;
    if (!url) return;              // preview/empty-URL: nothing to auto-save
    var elInput = root.querySelector('input[name="element"]');
    var last = persisted(root);
    // Sequence guard. Adoption re-renders the widget from the echo, so without this a
    // burst (tick A -> tick B) lets A's echo {"items":[A]} arrive last and UNTICK B --
    // a regression this rewrite would otherwise introduce (the old client ignored the
    // response body entirely). Only the newest request may paint.
    var seq = 0;

    boxes(root).forEach(function (cb) {
      cb.addEventListener("change", function () {
        var li = cb.closest(".markdone__item");
        if (li) li.classList.toggle("on", cb.checked);
        var items = [];
        root.querySelectorAll('input[type="checkbox"][name="item"]:checked')
          .forEach(function (c) { items.push(parseInt(c.value, 10)); });
        var mine = ++seq;
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({
            element: parseInt(elInput.value, 10),
            state: { items: items },
          }),
          keepalive: true,
        })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function (data) {
            if (mine !== seq) return;   // stale echo: a newer save is in flight
            // ADOPT the echo -- do not compare-and-revert. The server normalizes
            // (an empty selection DROPS the key and echoes {}), so a comparing
            // client would re-tick the box the student just unticked.
            var blob = (data && data.state) || {};
            var arr = Array.isArray(blob.items) ? blob.items : [];
            var next = {};
            arr.forEach(function (pk) { next[String(pk)] = true; });
            last = next;
            paint(root, last);
          })
          .catch(function () {
            if (mine !== seq) return;
            // Mark-done is REVERSIBLE, so a failed save reverts the DOM to
            // last-known-persisted. (Monotone types must NOT: slice 2.)
            paint(root, last);
            if (saveBtn) saveBtn.hidden = false;
          });
      });
    });
  }

  function initMarkDone(root) {
    root = root || document;
    if (root.matches && root.matches("[data-markdone]")) initOne(root);
    (root.querySelectorAll ? root.querySelectorAll("[data-markdone]") : []).forEach(initOne);
  }

  window.libliInitMarkDone = initMarkDone;
  initMarkDone(document);
})();
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest courses/tests/test_markdone_scripts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/markdone.js courses/tests/test_markdone_scripts.py
git commit -m "feat(markdone): adopt the echoed blob, guard the burst with last-write-wins"
```

---

### Task 7: `units_under(node)` in rollups

**Files:**
- Modify: `courses/rollups.py` (add after `units_in_order`, `:58-64`)
- Test: `courses/tests/test_rollups_units_under.py`

**Interfaces:**
- Consumes: `ContentNode`.
- Produces: `units_under(node) -> set[ContentNode]` — every unit node in the subtree rooted at `node`, **inclusive** if `node` is itself a unit.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_rollups_units_under.py`:

```python
import pytest

from courses.models import ContentNode
from courses.rollups import units_under
from tests.factories import make_course

pytestmark = pytest.mark.django_db


def _node(course, kind, parent=None, unit_type=None, title="n"):
    kw = {}
    if unit_type:
        kw["unit_type"] = unit_type
    return ContentNode.objects.create(
        course=course, kind=kind, parent=parent, title=title, **kw
    )


def test_units_under_a_chapter_returns_its_units_only():
    course = make_course()
    ch1 = _node(course, ContentNode.Kind.CHAPTER, title="c1")
    ch2 = _node(course, ContentNode.Kind.CHAPTER, title="c2")
    u1 = _node(course, ContentNode.Kind.UNIT, ch1, ContentNode.UnitType.LESSON, "u1")
    u2 = _node(course, ContentNode.Kind.UNIT, ch1, ContentNode.UnitType.LESSON, "u2")
    _u3 = _node(course, ContentNode.Kind.UNIT, ch2, ContentNode.UnitType.LESSON, "u3")
    assert units_under(ch1) == {u1, u2}


def test_units_under_a_unit_is_inclusive():
    course = make_course()
    u1 = _node(course, ContentNode.Kind.UNIT, None, ContentNode.UnitType.LESSON, "u1")
    assert units_under(u1) == {u1}


def test_units_under_descends_through_nested_levels():
    course = make_course()
    part = _node(course, ContentNode.Kind.PART, title="p")
    ch = _node(course, ContentNode.Kind.CHAPTER, part, title="c")
    sec = _node(course, ContentNode.Kind.SECTION, ch, title="s")
    u = _node(course, ContentNode.Kind.UNIT, sec, ContentNode.UnitType.LESSON, "u")
    assert units_under(part) == {u}


def test_units_under_includes_quiz_units():
    # Reset clears whatever is there; quiz units simply hold nothing.
    course = make_course()
    ch = _node(course, ContentNode.Kind.CHAPTER, title="c")
    q = _node(course, ContentNode.Kind.UNIT, ch, ContentNode.UnitType.QUIZ, "q")
    assert units_under(ch) == {q}


def test_units_under_an_empty_chapter_is_empty():
    course = make_course()
    ch = _node(course, ContentNode.Kind.CHAPTER, title="c")
    assert units_under(ch) == set()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_rollups_units_under.py -v`
Expected: FAIL — `ImportError: cannot import name 'units_under'`

- [ ] **Step 3: Implement**

Add to `courses/rollups.py` after `units_in_order`:

```python
def units_under(node):
    """Every unit ContentNode in the subtree rooted at `node`, inclusive.

    A SET, not an ordered list: reset does not care about order, so the pre-order
    subtlety _walk_preorder warns about (sibling `order` is only locally monotonic)
    is irrelevant here and must not be cargo-culted in. _walk_preorder itself cannot
    serve: it walks from parent_id=None over a WHOLE course and cannot start from an
    arbitrary node.
    """
    if node.kind == ContentNode.Kind.UNIT:
        return {node}
    children = {}
    for n in node.course.nodes.all():
        children.setdefault(n.parent_id, []).append(n)
    out = set()
    stack = list(children.get(node.pk, []))
    while stack:
        cur = stack.pop()
        if cur.kind == ContentNode.Kind.UNIT:
            out.add(cur)
        else:
            stack.extend(children.get(cur.pk, []))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest courses/tests/test_rollups_units_under.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix courses/rollups.py courses/tests/test_rollups_units_under.py
uv run ruff format courses/rollups.py courses/tests/test_rollups_units_under.py
git add courses/rollups.py courses/tests/test_rollups_units_under.py
git commit -m "feat(rollups): units_under(node) subtree helper for reset"
```

---

### Task 8: `progress_reset` — GET interstitial + POST

**Files:**
- Modify: `courses/views.py` (new view), `courses/urls.py` (two routes)
- Create: `templates/courses/progress_reset_confirm.html`
- Test: `courses/tests/test_progress_reset.py`

**Interfaces:**
- Consumes: `units_under` (Task 7), `units_in_order` (existing, `rollups.py:58`), `UnitProgress.element_state` (Task 2).
- Produces: routes `courses:progress_reset_course` (`courses/<slug>/reset/`) and `courses:progress_reset` (`courses/<slug>/reset/<node_pk>/`).

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_progress_reset.py`:

```python
import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Enrollment
from courses.models import MarkDoneElement
from courses.models import QuizSubmission
from courses.models import UnitProgress
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _seed(client):
    course, unit = make_course_with_unit()
    obj = MarkDoneElement.objects.create(prompt="P")
    row = add_element(unit, obj)
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    up = UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(row.pk): {"items": [1]}},
        seen_element_ids=[row.pk],
        completed=True,
    )
    client.force_login(student)
    return course, unit, student, up


def test_get_renders_the_interstitial_and_writes_nothing(client):
    course, unit, student, _up = _seed(client)
    UnitProgress.objects.filter(student=student, unit=unit).delete()
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # GET is side-effect free: it must not spawn a row.
    assert not UnitProgress.objects.filter(student=student, unit=unit).exists()


def test_get_count_is_lessons_with_non_empty_state(client):
    course, unit, student, _up = _seed(client)
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.context["affected_count"] == 1


def test_get_count_zero_offers_no_destructive_action(client):
    course, unit, student, up = _seed(client)
    up.element_state = {}
    up.save()
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.context["affected_count"] == 0
    # Assert the BODY, not just the count: the name promises "offers no destructive
    # action", and a count assertion alone passes even if the template renders the
    # destructive form unconditionally.
    body = r.content.decode()
    assert "Nothing to clear here." in body
    # Do NOT assert `'type="submit"' not in body`: base.html emits it unconditionally
    # (the language switcher at :64 and the logout button at :136), so that negative is
    # false of a CORRECT page. `btn--danger` is safe -- it appears only in app.css, never
    # in base.html's markup -- and it already falsifies a template that renders the
    # destructive form unconditionally.
    assert "btn--danger" not in body


def test_post_clears_element_state(client):
    course, unit, student, _up = _seed(client)
    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 302
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.element_state == {}


def test_reset_does_not_touch_completion(client):
    # HARD INVARIANT. Completion is scroll-driven (an IntersectionObserver, not an act
    # of work) and feeds build_progress_matrix -> teacher analytics. A student revising
    # must not silently drag down what their teacher sees.
    course, unit, student, _up = _seed(client)
    client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.completed is True
    assert up.seen_element_ids != []


def test_reset_does_not_touch_graded_records(client):
    # HARD INVARIANT. Graded assessment history is not the student's to erase.
    course, unit, student, _up = _seed(client)
    sub = QuizSubmission.objects.create(student=student, unit=unit)
    client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert QuizSubmission.objects.filter(pk=sub.pk).exists()


def test_course_level_route_clears_every_unit(client):
    course, unit, student, _up = _seed(client)
    u2 = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="u2",
    )
    UnitProgress.objects.create(student=student, unit=u2, element_state={"9": {"x": 1}})
    r = client.post(reverse("courses:progress_reset_course", args=[course.slug]))
    assert r.status_code == 302
    assert UnitProgress.objects.get(student=student, unit=u2).element_state == {}


def test_reset_at_chapter_level_clears_its_units_only(client):
    # [S1] spec requirement: reset at unit / section / chapter, not just unit+course.
    # units_under's own unit tests are NOT the view -- this drives the real endpoint.
    course, unit, student, _up = _seed(client)
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    inside = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="inside",
    )
    up_in = UnitProgress.objects.create(
        student=student, unit=inside, element_state={"1": {"items": [1]}}
    )
    r = client.post(reverse("courses:progress_reset", args=[course.slug, ch.pk]))
    assert r.status_code == 302
    up_in.refresh_from_db()
    assert up_in.element_state == {}
    # The top-level unit is OUTSIDE the chapter and must be untouched.
    assert UnitProgress.objects.get(student=student, unit=unit).element_state != {}


def test_reset_at_section_level_descends_to_its_units(client):
    course, _unit, student, _up = _seed(client)
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    sec = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.SECTION, parent=ch, title="s"
    )
    deep = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=sec,
        unit_type=ContentNode.UnitType.LESSON,
        title="deep",
    )
    up_deep = UnitProgress.objects.create(
        student=student, unit=deep, element_state={"1": {"items": [1]}}
    )
    client.post(reverse("courses:progress_reset", args=[course.slug, sec.pk]))
    up_deep.refresh_from_db()
    assert up_deep.element_state == {}


def test_student_a_cannot_reset_student_b(client):
    course, unit, student, _up = _seed(client)
    other = make_verified_user(username="other", email="other@school.edu")
    Enrollment.objects.create(student=other, course=course)
    other_up = UnitProgress.objects.create(
        student=other, unit=unit, element_state={"7": {"items": [1]}}
    )
    client.post(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    other_up.refresh_from_db()
    assert other_up.element_state == {"7": {"items": [1]}}


def test_foreign_course_node_404s(client):
    # can_access_course authorizes against `slug`; NOTHING otherwise ties node_pk to
    # that course. Without get_node_or_404 this wipes state in another course.
    course, _unit, _student, _up = _seed(client)
    _c2, unit2 = make_course_with_unit()
    r = client.post(reverse("courses:progress_reset", args=[course.slug, unit2.pk]))
    assert r.status_code == 404


def test_foreign_next_falls_back_to_the_outline(client):
    course, unit, _student, _up = _seed(client)
    r = client.post(
        reverse("courses:progress_reset", args=[course.slug, unit.pk]),
        data={"next": "https://evil.example.com/x"},
    )
    assert r.status_code == 302
    assert r.url == reverse("courses:course_outline", args=[course.slug])


def test_foreign_next_on_the_GET_does_not_reach_the_cancel_href(client):
    # The GET half of the redirect guard: an unvalidated ?next= would render a
    # libli-hosted page whose Cancel button navigates off-site.
    course, unit, _student, _up = _seed(client)
    r = client.get(
        reverse("courses:progress_reset", args=[course.slug, unit.pk])
        + "?next=https://evil.example.com/x"
    )
    assert r.status_code == 200
    assert "evil.example.com" not in r.content.decode()
    assert r.context["cancel_url"] == reverse("courses:course_outline", args=[course.slug])


def test_local_next_is_honoured(client):
    course, unit, _student, _up = _seed(client)
    target = reverse("courses:lesson_unit", args=[course.slug, unit.pk])
    r = client.post(
        reverse("courses:progress_reset", args=[course.slug, unit.pk]),
        data={"next": target},
    )
    assert r.status_code == 302 and r.url == target


def test_anonymous_is_redirected(client):
    course, unit = make_course_with_unit()
    r = client.get(reverse("courses:progress_reset", args=[course.slug, unit.pk]))
    assert r.status_code == 302 and "/login" in r.url
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_progress_reset.py -v`
Expected: FAIL — `NoReverseMatch: 'progress_reset'`

- [ ] **Step 3: Implement the view**

Add to `courses/views.py`:

```python
@login_required
def progress_reset(request, slug, node_pk=None):
    """Clear the student's OWN practice state for a node's subtree, or the course.

    GET renders a confirmation interstitial (side-effect free); POST performs it.
    NOT POST-only: the count needs a server round-trip, and reset is the student's
    protection against automatic persistence -- shipping it as a one-click no-undo
    form for no-JS students would make the safety valve the hazard.
    """
    if node_pk is None:
        course = get_object_or_404(Course, slug=slug)
        targets = units_in_order(course)
    else:
        # NOT optional: can_access_course authorizes against `slug`, but nothing
        # otherwise ties node_pk to that course -- a foreign node_pk would resolve
        # its own subtree and wipe the student's state THERE.
        node = get_node_or_404(node_pk, slug, require_unit=False)
        course = node.course
        targets = units_under(node)
    if not can_access_course(request.user, course):
        raise PermissionDenied

    rows = UnitProgress.objects.filter(student=request.user, unit__in=targets)
    fallback = reverse("courses:course_outline", args=[slug])

    # Validate `next` ONCE, for BOTH methods. Validating only the POST would leave the
    # GET piping request.GET["next"] straight into the Cancel href -- a libli-hosted,
    # plausibly-styled page whose Cancel button navigates off-site. That is the same
    # open-redirect class the spec rejects for HTTP_REFERER, reached from the other side.
    raw_next = (request.POST.get("next") if request.method == "POST" else None) or request.GET.get("next") or ""
    safe_next = (
        raw_next
        if raw_next
        and url_has_allowed_host_and_scheme(
            raw_next, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        else ""
    )

    if request.method == "POST":
        # .update() deliberately bypasses save(): it fires neither auto_now on
        # updated_at nor the completed => completed_at invariant. Both are fine --
        # reset does not touch `completed`, and nothing reads updated_at for
        # practice state. IDOR-safe against other STUDENTS by construction
        # (student=request.user); the cross-COURSE hole is closed by
        # get_node_or_404 above, not by this filter.
        rows.update(element_state={})
        return redirect(safe_next or fallback)

    # Honest blast radius: lessons that actually HOLD work, not every lesson in the
    # subtree. Telling a student "this clears 14 lessons" when 3 have anything makes
    # a harmless reset sound destructive.
    affected_count = rows.exclude(element_state={}).count()
    return render(
        request,
        "courses/progress_reset_confirm.html",
        {
            "course": course,
            "node": None if node_pk is None else node,
            "affected_count": affected_count,
            "next": safe_next,
            "cancel_url": safe_next or fallback,
        },
    )
```

Add the imports:

```python
from django.utils.http import url_has_allowed_host_and_scheme

from courses.rollups import units_in_order
from courses.rollups import units_under
```

- [ ] **Step 4: Add the routes**

In `courses/urls.py`, next to the other course-scoped routes:

```python
    path(
        "courses/<slug:slug>/reset/",
        views.progress_reset,
        name="progress_reset_course",
    ),
    path(
        "courses/<slug:slug>/reset/<int:node_pk>/",
        views.progress_reset,
        name="progress_reset",
    ),
```

- [ ] **Step 5: Create the interstitial**

Create `templates/courses/progress_reset_confirm.html`:

**Note the `extra_css` block — it is load-bearing, not boilerplate.** `base.html:44-46` links only
`core/css/reset.css`, `tokens.css` and `app.css`; **`courses/css/courses.css` is linked PER PAGE**
via `{% block extra_css %}` (lesson_unit.html, quiz_unit.html, course_results.html, …). `.danger-zone`
lives at `courses.css:1190`, so without this block the class resolves to **nothing** and the page
ships unstyled — the repo's named "per-page CSS link + undefined classes" trap.

```html
{% extends "base.html" %}
{% load i18n static %}
{% block head_title %}{% trans "Start fresh" %} — libli{% endblock %}
{% block extra_css %}{{ block.super }}<link rel="stylesheet" href="{% static 'courses/css/courses.css' %}">{% endblock %}
{% block content %}
<section class="danger-zone reset-confirm" lang="{{ course.language }}">
  <h1>{% trans "Start fresh?" %}</h1>
  {% if affected_count %}
    <p class="reset-confirm__blast">
      {% blocktrans count counter=affected_count trimmed %}
        This clears your answers and ticks in {{ counter }} lesson.
      {% plural %}
        This clears your answers and ticks in {{ counter }} lessons.
      {% endblocktrans %}
    </p>
    <p class="reset-confirm__safe">{% trans "Your quiz results are not affected, and lessons you have completed stay completed." %}</p>
    <form method="post">
      {% csrf_token %}
      <input type="hidden" name="next" value="{{ next }}">
      <button type="submit" class="btn btn--danger">{% trans "Start fresh" %}</button>
      <a class="btn btn--ghost" href="{{ cancel_url }}">{% trans "Cancel" %}</a>
    </form>
  {% else %}
    <p class="reset-confirm__blast">{% trans "Nothing to clear here." %}</p>
    <a class="btn btn--ghost" href="{{ cancel_url }}">{% trans "Back" %}</a>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest courses/tests/test_progress_reset.py -v`
Expected: PASS (15 tests)

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix courses/ && uv run ruff format courses/
git add courses/views.py courses/urls.py templates/courses/progress_reset_confirm.html courses/tests/test_progress_reset.py
git commit -m "feat(reset): progress_reset with a GET confirmation interstitial"
```

---

### Task 9: Reset controls in the lesson and the outline

**Files:**
- Modify: `templates/courses/_lesson_article.html:5-23` (the head)
- Modify: `templates/courses/outline.html:8-11` (`.outline__head`)
- Modify: `templates/courses/_outline_node.html`
- Modify: `courses/static/courses/css/courses.css` (interstitial rules, beside `.danger-zone` at `:1190`)
- Modify: `core/static/core/css/app.css` (the three control rules — `outline.html` does **not** link `courses.css`)
- Test: `courses/tests/test_reset_controls.py`

**Interfaces:**
- Consumes: routes from Task 8.
- Produces: no Python interface — template links + CSS only.

**The outline control is a plain LINK to the interstitial, not a form.** That is what keeps the outline paint at **zero** extra queries: the count is computed only when a student actually asks to reset.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_reset_controls.py`:

```python
import pytest
from django.urls import reverse

from courses.models import ContentNode
from courses.models import Enrollment
from tests.factories import make_course_with_unit
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _login(client, course):
    student = make_verified_user()
    Enrollment.objects.create(student=student, course=course)
    client.force_login(student)
    return student


def test_lesson_page_links_to_the_reset_interstitial(client):
    course, unit = make_course_with_unit()
    _login(client, course)
    r = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    assert reverse("courses:progress_reset", args=[course.slug, unit.pk]) in r.content.decode()


def test_outline_links_to_the_course_level_reset(client):
    course, _unit = make_course_with_unit()
    _login(client, course)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert reverse("courses:progress_reset_course", args=[course.slug]) in r.content.decode()


def test_outline_links_reset_per_grouping_node(client):
    course, _unit = make_course_with_unit()
    ch = ContentNode.objects.create(
        course=course, kind=ContentNode.Kind.CHAPTER, title="c"
    )
    ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        parent=ch,
        unit_type=ContentNode.UnitType.LESSON,
        title="u",
    )
    _login(client, course)
    r = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert reverse("courses:progress_reset", args=[course.slug, ch.pk]) in r.content.decode()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_reset_controls.py -v`
Expected: FAIL — the URLs are not in the rendered HTML.

- [ ] **Step 3: Add the lesson control**

In `templates/courses/_lesson_article.html`, inside `.lesson-unit__head`, after the closing `</div>` of `.unit-done` (`:22`) and before `</div>` (`:23`), add:

```html
    <a class="btn btn--ghost btn--small lesson-unit__reset"
       href="{% url 'courses:progress_reset' slug=course.slug node_pk=unit.pk %}?next={% url 'courses:lesson_unit' slug=course.slug node_pk=unit.pk %}">
      {% trans "Start fresh" %}
    </a>
```

- [ ] **Step 4: Add the outline controls**

In `templates/courses/outline.html`, inside `.outline__head` after the "My notes" link (`:10`):

```html
    <a class="btn btn--ghost btn--small outline__reset" href="{% url 'courses:progress_reset_course' slug=course.slug %}?next={% url 'courses:course_outline' slug=course.slug %}">{% trans "Start fresh" %}</a>
```

In `templates/courses/_outline_node.html`, inside the `{% else %}` (non-unit) branch's `.outline-node__head`, after the rollup spans:

```html
      <a class="outline-node__reset" title="{% trans 'Start fresh' %}" aria-label="{% trans 'Start fresh' %}"
         href="{% url 'courses:progress_reset' slug=course.slug node_pk=item.node.pk %}?next={% url 'courses:course_outline' slug=course.slug %}">{% trans "Start fresh" %}</a>
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest courses/tests/test_reset_controls.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Write the CSS — six classes, none of which exist yet**

`.reset-confirm`, `.reset-confirm__blast`, `.reset-confirm__safe`, `.lesson-unit__reset`,
`.outline__reset` and `.outline-node__reset` are defined **nowhere** in the repo. Without this step
the feature's only new page and all three controls ship as unstyled HTML — this repo's standing rule
is that **no view ships bare**.

`.outline__reset` and `.outline-node__reset` are used by `outline.html`, which does **not** link
`courses.css`. Put those two in **`core/static/core/css/app.css`** (globally linked, and where
`.outline*` styling already lives); put the interstitial's three in
**`courses/static/courses/css/courses.css`**, next to `.danger-zone` (`:1190`), which the template
now links.

Append to `courses/static/courses/css/courses.css`, beside `.danger-zone`:

```css
/* --- Practice-state reset interstitial --- */
.reset-confirm { max-width: 44ch; margin: var(--space-6) auto; }
.reset-confirm__blast { margin: 0 0 var(--space-2); font-weight: 600; }
.reset-confirm__safe { margin: 0 0 var(--space-4); color: var(--text-secondary); font-size: .9rem; }
```

Append to `core/static/core/css/app.css`, beside the other `.outline*` rules:

```css
/* --- Practice-state reset controls --- */
.lesson-unit__reset,
.outline__reset { flex: none; }
.outline-node__reset {
  margin-left: var(--space-2);
  font-size: .8rem;
  color: var(--text-secondary);
  text-decoration: underline;
}
.outline-node__reset:hover { color: var(--danger); }
```

Use existing tokens only (`--space-*`, `--text-secondary`, `--danger`). Do **not** invent colours —
`.btn--danger` and `.btn--ghost` already carry the button styling.

- [ ] **Step 7: Verify light + dark with screenshots**

The spec requires the interstitial "styled per the existing `.btn--danger` / danger-zone pattern …
and **verified light + dark with screenshots**". Drive the real page with Playwright at both
schemes and **look at the images** — do not assert on CSS text.

`emulate_media(color_scheme=...)` works **only when the theme pref is `auto`** (the default: no
`libli_theme` cookie, no server `theme_pref`), because `base.html:22-24` reads
`matchMedia("(prefers-color-scheme: dark)")` and stamps `<html data-theme>` from it. A fresh test
user is on `auto`, so it works. If both shots come out pixel-identical, check the pref before
blaming `emulate_media` — and confirm by *looking* (a dark shot is obviously dark).

Check: the "Start fresh" button reads as destructive, body text is legible in both schemes, and the
count line is not clipped.

- [ ] **Step 8: Commit**

```bash
uv run ruff check --fix courses/tests/test_reset_controls.py
uv run ruff format courses/tests/test_reset_controls.py
git add templates/courses/ courses/static/courses/css/courses.css core/static/core/css/app.css courses/tests/test_reset_controls.py
git commit -m "feat(reset): Start fresh controls + interstitial styling"
```

---

### Task 10: Delete the dead field test; sweep the remaining `checklist_state` references

**Files:**
- Modify: `courses/tests/test_markdone_models.py:34-37`
- Modify: `tests/test_e2e_markdone.py`

**Interfaces:** none.

- [ ] **Step 1: Delete the test of the removed field**

`courses/tests/test_markdone_models.py:34-37` is `test_unit_progress_checklist_state_defaults_to_dict` — a test **of the removed field**. It is **deleted, not ported** (`element_state`'s default is already covered by `test_state_migration.py` and the endpoint tests).

**Delete the now-orphaned import with it:** `UnitProgress` is imported at `:6` and used **only** at `:36`, inside this test. Leaving it trips ruff `F401`, which would surface unexplained in Task 12's `ruff check .`.

- [ ] **Step 2: Fix the e2e route matcher**

`tests/test_e2e_markdone.py` has **two** matchers, not one — `page.expect_response(lambda r: "/markdone/" in r.url and r.request.method == "POST")` at **`:86-88`** (`test_tick_persists_across_reload`) and **`:123-125`** (`test_nested_in_tabs_tick_persists`). Update **both** to `"/state/" in r.url`; fixing one leaves the other hanging on `expect_response` until it times out. Also update the module docstring at **`:5`**, which names "the `.../markdone/` endpoint".

- [ ] **Step 3: Verify no references survive**

```bash
grep -rn "checklist_state\|markdone_save" --include=*.py --include=*.html --include=*.js . | grep -v "/migrations/" | grep -v "docs/"
```
Expected: **no output.** (`docs/` and `migrations/` legitimately retain the name.)

- [ ] **Step 4: Run the mark-done suite**

Run: `uv run pytest courses/tests/ -k markdone -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix courses/tests/ tests/
uv run ruff format courses/tests/ tests/
git add -A courses/tests/ tests/
git commit -m "chore(tests): drop the removed-field test, sweep checklist_state refs"
```

---

### Task 11: e2e — mark-done persists, the burst is safe, reset clears

**Files:**
- Create: `tests/test_e2e_practice_state.py`

**Interfaces:** none.

**Drive the REAL gesture.** Never `page.evaluate` — an e2e that bypasses the real click ships broken UX green.

- [ ] **Step 1: Write the e2e**

Create `tests/test_e2e_practice_state.py`. The helpers below are copied from
`tests/test_e2e_markdone.py` (module-level functions + an HTML-form login — that file defines **no**
fixtures, so do not invent `markdone_lesson`/`reset_url` fixtures):

```python
"""Playwright e2e for the practice-state substrate. Marked e2e (run with -m e2e).

Drives the REAL checkbox gesture (a page.evaluate shortcut is forbidden in this repo)
and waits for the auto-save POST to `.../state/` to COMPLETE before reloading, so
persistence is proven on a fresh server render -- not an optimistic client toggle.

Harness mirrors tests/test_e2e_markdone.py (login + seed helpers)."""

import os

import pytest
from django.urls import reverse

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug):
    """An enrolled student on a lesson holding one checklist with TWO items."""
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = MarkDoneElement.objects.create(prompt="Prep")
    for c in ("one", "two"):
        MarkDoneItem.objects.create(element=el, content=c)
    Element.objects.create(unit=unit, content_object=el)
    return course, unit


def _lesson_url(live_server, course, unit):
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _is_save(r):
    return "/state/" in r.url and r.request.method == "POST"


def test_tick_survives_a_reload(live_server, page):
    """The whole feature, end to end: a real click, a real reload."""
    course, unit = _seed("psstu", "practice-state-e2e")
    _login(page, live_server, "psstu")
    page.goto(_lesson_url(live_server, course, unit))
    page.wait_for_selector("[data-markdone]")

    first = page.locator(".markdone__item input[type='checkbox']").first
    assert not first.is_checked()
    # Wait for the SAVE to complete, not for the `on` class: markdone.js toggles `on`
    # SYNCHRONOUSLY before fetch(), so a wait_for_function on it resolves instantly and
    # the reload races the in-flight POST (keepalive guarantees the request is SENT,
    # not that the server committed it).
    with page.expect_response(_is_save) as resp:
        first.check()
    assert resp.value.ok

    page.reload()
    page.wait_for_selector("[data-markdone]")
    assert page.locator(".markdone__item input[type='checkbox']").first.is_checked()


def test_two_ticks_both_reach_the_server(live_server, page):
    """Two real ticks in succession -> both survive a reload.

    SCOPE, stated honestly: this does NOT police the `seq` last-write-wins guard, and
    must not claim to. Two earlier drafts did:
      - a post-reload assertion is guard-agnostic (paint() fires no `change` event, so
        the client never re-POSTs; the server holds [A, B] from B's request either way);
      - a pre-reload assertion only diverges when A's echo arrives AFTER B's, which does
        not happen in the ordinary in-order case -- and Playwright's check() actionability
        waits mean A's response usually lands before the second click even fires, so no
        burst occurs at all.
    The guard's real coverage is test_markdone_scripts.py's source assertions
    (`var mine = ++seq;` / `if (mine !== seq) return;`). A deterministic reorder e2e
    (page.route delaying the first response past the second) is DEFERRED -- it is worth
    doing if this ever regresses in the wild.
    What this DOES prove end-to-end: two successive REAL ticks each reach the server,
    and the second does not lose the first, on a fresh server render.
    (NB these are two ITEMS of ONE element -- two writes to the same element_state key.
    Multi-ELEMENT accumulation across keys is a different property, proven by
    test_concurrent_two_element_save_does_not_clobber in Task 5.)
    """
    course, unit = _seed("psburst", "practice-state-burst-e2e")
    _login(page, live_server, "psburst")
    page.goto(_lesson_url(live_server, course, unit))
    page.wait_for_selector("[data-markdone]")

    boxes = page.locator(".markdone__item input[type='checkbox']")
    with page.expect_response(_is_save) as r1:
        boxes.nth(0).check()
    assert r1.value.ok
    with page.expect_response(_is_save) as r2:
        boxes.nth(1).check()
    assert r2.value.ok

    page.reload()
    page.wait_for_selector("[data-markdone]")
    reloaded = page.locator(".markdone__item input[type='checkbox']")
    assert reloaded.nth(0).is_checked() and reloaded.nth(1).is_checked()


def test_reset_clears_the_ticks(live_server, page):
    course, unit = _seed("psreset", "practice-state-reset-e2e")
    _login(page, live_server, "psreset")
    url = _lesson_url(live_server, course, unit)
    page.goto(url)
    page.wait_for_selector("[data-markdone]")

    with page.expect_response(_is_save) as resp:
        page.locator(".markdone__item input[type='checkbox']").first.check()
    assert resp.value.ok

    reset_path = reverse(
        "courses:progress_reset", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{reset_path}")
    page.get_by_role("button", name="Start fresh").click()

    page.goto(url)
    page.wait_for_selector("[data-markdone]")
    assert not page.locator(".markdone__item input[type='checkbox']").first.is_checked()
```

**No `wait_for_timeout` anywhere:** every wait is an `expect_response` on the real POST. The repo has
form with timing crutches; do not add one back.

- [ ] **Step 2: Run the e2e FOREGROUND with an explicit marker**

Run: `uv run pytest tests/test_e2e_practice_state.py -m e2e -v`
Expected: PASS (3 tests).

**`-m e2e` is mandatory** — `addopts = -q -m 'not e2e'` deselects the file and pytest exits **5**, which looks like success. Run it foreground; never background a Playwright suite (runaway browsers).

- [ ] **Step 3: Commit**

```bash
uv run ruff check --fix tests/test_e2e_practice_state.py
uv run ruff format tests/test_e2e_practice_state.py
git add tests/test_e2e_practice_state.py
git commit -m "test(e2e): practice state persists, burst is safe, reset clears"
```

---

### Task 12: i18n, editor-preview guard, and the full DoD

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po`
- Test: `courses/tests/test_reset_controls.py` (preview inertness)

**Interfaces:** none.

- [ ] **Step 1: Add the editor-preview inertness test**

The preview renders **real join rows** (`_preview.html:16`), so `eid` is non-zero there; what makes it inert is its context lacking `slug`/`node_pk` → `{% url ... as save_url %}` resolves to `""`. **Test that**, not an `element=None` path that never occurs.

Append to `courses/tests/test_reset_controls.py`:

```python
def test_editor_preview_markdone_is_inert(client):
    """Drive the REAL preview view as the course author.

    Calling el.render(..., slug=None, node_pk=None) directly would only prove that
    `{% url ... as %}` swallows NoReverseMatch -- it hand-passes the very Nones it
    claims to discover, so it would stay green even if _preview.html's context GAINED
    slug/node_pk. The claim under test is about the preview VIEW's context.
    """
    from django.urls import reverse

    from courses.models import MarkDoneElement
    from courses.models import MarkDoneItem
    from tests.factories import add_element
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    author = make_verified_user(username="prevauth", email="prevauth@school.edu")
    course, unit = make_course_with_unit(owner=author)
    el = MarkDoneElement.objects.create(prompt="P")
    add_element(unit, el)
    MarkDoneItem.objects.create(element=el, content="a")
    client.force_login(author)
    r = client.get(reverse("courses:manage_editor", args=[course.slug, unit.pk]))
    assert r.status_code == 200
    # eid is NON-zero here (the preview passes real join rows). What makes it inert is
    # the absent slug/node_pk -> empty save_url -> markdone.js no-ops on fetch("").
    assert 'data-markdone-url=""' in r.content.decode()
    # The [S1] entry asks for both halves: empty save_url AND no row created/written.
    from courses.models import UnitProgress

    assert not UnitProgress.objects.filter(unit=unit).exists()
```

Run: `uv run pytest courses/tests/test_reset_controls.py -v` → PASS.

- [ ] **Step 2: Regenerate the catalog**

```bash
uv run python manage.py makemessages -l pl
```

- [ ] **Step 3: Fix the fuzzy entries by hand**

`makemessages` fuzzy-matches new msgids on **every** build in this project. Open `locale/pl/LC_MESSAGES/django.po` and for each **new** string ("Start fresh", "Start fresh?", "This clears your answers and ticks in %(counter)s lesson/lessons.", "Your quiz results are not affected…", "Nothing to clear here.", "Cancel", "Back"):

- delete the `#, fuzzy` token (**keep** `python-format` / `python-brace-format` on the same line if present),
- delete any `#| msgid` lines,
- write the correct Polish.

Then verify: `grep -n "#, fuzzy\|#~" locale/pl/LC_MESSAGES/django.po` → **no output.**

```bash
uv run python manage.py compilemessages
uv run pytest -k po_catalog_clean -v
```
Expected: PASS.

- [ ] **Step 4: Run the full DoD**

```bash
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest -m "not e2e" -n auto
uv run pytest tests/test_e2e_practice_state.py tests/test_e2e_markdone.py -m e2e
```

Expected: ruff clean (**both** `check` and `format --check` — implementers routinely run only the first and CI fails on the second); no pending migrations; `manage check` clean; **full non-e2e suite green**; e2e green.

**If `test_transfer_schema.py` or `test_models_multigrid.py` fail on an `ELEMENT_MODELS` count, something is wrong** — this slice adds no element type and those asserts must not move.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "i18n(pl): reset + interstitial strings; slice-1 DoD green"
```

---

## Self-Review

**Spec coverage (unfenced sections only):**

| Spec section | Task |
|---|---|
| Storage — `element_state` replaces `checklist_state` | 2 |
| Migration (add / re-key / drop, reversible, orphans, backward drops non-markdone) | 2 |
| Per-type state blobs + validator contract (EMPTY/REJECT, `courses/state.py`, dispatch key space) | 1 |
| Bounds | 1 — *N/A in slice 1*: mark-done's blob is bounded by intersecting against `obj.items`; the free-text types that need caps are slice 2. |
| The render seam (nine signatures, `_state_context`, `eid` provenance, `state` = map) | 3 |
| Save endpoint (recipe, dispatch, ownership, validate-before-`get_or_create`, echo, no-JS branch, `fields`→400) | 5 |
| Restore — server-side (`build_lesson_context`, two-branch read, read guards) | 4 |
| Reset (two routes, GET interstitial, `units_under`, `next`, invariants, count) | 7, 8, 9 |
| i18n | 12 |
| Transfer untouched | — (no task; asserted by the DoD's full suite) |
| Testing `[S1]` entries | 1–12 |
| Breakage list (`markdone.js`, `test_render_seam.py`, 3 markdone modules, `models.py:453`, `editor.js:77/83`) | 2, 3, 4, 5, 6, 10 |

**`editor.js:77`** (`libliInitRevealGates(preview)`) needs no change in slice 1 — the reveal gate is slice 2. **`editor.js:83`** (`libliInitMarkDone(preview)`) is honoured by Task 6 keeping the export name and arity, asserted in its test.

**Placeholder scan:** no TBD/TODO; every code step carries the actual code; no "similar to Task N".

**Type consistency:** `validate_state(element, obj, payload)` (Task 1) is called with exactly that signature in Task 5. `EMPTY`/`REJECT` are compared with `is` throughout. `_state_context(element, state, slug, node_pk)` (Task 3) returns `{"el","eid","mine","slug","node_pk"}` — consumed by the same-task overrides and by `markdoneelement.html`'s `{{ eid }}` (Task 5). `units_under(node)` returns a **set** (Task 7), consumed by `unit__in=` (Task 8). `element_state` keys are `str(pk)` on write / `int(k)` on read in Tasks 2, 4, 5 alike.

**Deviations from the spec, recorded:**

1. **`mine_json` omitted from `_state_context`** (Task 3): no slice-1 leaf emits `data-state`, so it would be dead code — which is what the spec's own prose says ("Slice 2 adds `mine_json` alongside the first client-restoring leaf"). The spec's docstring and its prose disagreed; the prose wins.
2. **`test_markdone_endpoint.py` is deleted, not re-keyed** (Task 5 Step 7). The spec's breakage list says "re-keyed to join-row pks", but `test_element_state_endpoint.py` supersedes it wholesale — porting it would duplicate the new suite verbatim.
3. **The `[S1]` `assertNumQueries` guard is replaced by a stronger, deterministic test** (Task 3): `.elements` is monkeypatched to raise, so a re-introduced self-lookup fails loudly and by name. A raw query-count baseline would need a magic number and could not police Tabs/TwoColumn anyway (their `resolved_*()` `join_row()` call survives by design, so a re-introduced `eid` lookup would hide inside the total).

**Post-review coverage corrections** (round 1 of plan-review): the `[S1]` lesson-GET-200 parametrization (top-level / tabs / two-column) is now in Task 3; container `eid` provenance is pinned by identity in Task 3; chapter- and section-level reset now drive the real view in Task 8; the anonymous endpoint case is in Task 5; the migration's tab-nested and empty/absent cases are in Task 2; and the interstitial's CSS + light/dark screenshots are in Tasks 8-9.
