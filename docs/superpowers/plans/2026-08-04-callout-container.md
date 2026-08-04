# Callout Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `CalloutElement` a single-slot container so a table can be nested inside a callout, and fix the `SpoilerElement` defect that makes a body unreachable once children exist — in one branch, so both elements behave identically for a content author.

**Architecture:** Callout reuses `SpoilerElement`'s existing single-slot container substrate verbatim (children are `Element` join rows whose `parent` is the callout's join row and whose `tab_id` is one fixed slot id). Registry membership is *not* sufficient: six further dispatch sites are hard-coded by model or type — the export walk, the palette guard, three reveal-cascade scope lists, and the math.js selector list — and each needs its own edit. Both elements switch to rendering `body` first, then children.

**Tech Stack:** Django 5.2, PostgreSQL, pytest + pytest-django, Playwright (e2e), vanilla JS (no framework), token-driven CSS.

**Spec:** `docs/superpowers/specs/2026-08-04-callout-container-design.md` (1122 lines, 7 review rounds, 79 catches applied).

## Global Constraints

- **Tooling is behind `uv run`** — `ruff`, `pytest`, `python` are NOT on PATH. Always `uv run pytest …`, `uv run ruff …`.
- **e2e tests need `-m e2e`** or they are silently deselected (exit 5).
- **`--verbosity=0`, never a second `-q`** — `addopts` already has `-q`; doubling it prints no verdict.
- **`MAX_NEST_DEPTH = 4`** (`courses/builder.py:25`). A top-level element is depth 1. Never monkeypatch it to its real value in a test — the test goes vacuous while still passing. Patch to `5`.
- **The slot literal is `"only"`.** It is a stored `Element.tab_id` value on every existing nested-spoiler child and must never change.
- **No hardcoded test passwords** — use `tests.factories.TEST_PASSWORD`.
- **Never create `courses/tests/__init__.py`** — it renames every module under that directory.
- **Django multi-line comments** use `{% comment %}`; `{# #}` must be single-line.
- **Module-level translatable strings** must use `gettext_lazy`.
- **`makemigrations --check --dry-run` must stay clean** (CI guards this since #204).
- **A passing test proves nothing** — for every test, delete the code it guards and confirm it goes RED before moving on.

## File Structure

Production files, in dependency order:

| File | Responsibility in this slice |
|---|---|
| `courses/models.py` | `SINGLE_SLOT_ID`; `CalloutElement` gains `SLOT_ID`/`join_row()`/`resolved_children()`/`render()`; `SpoilerElement.SLOT_ID` references the shared constant |
| `courses/transfer/payloads.py` | `_CONTAINER_SLOT_KEY["callout"]`; validate against `SINGLE_SLOT_ID` |
| `courses/builder.py` | `_CONTAINER_REGISTRY`, `CONTAINER_TRANSFER_KEYS` |
| `courses/transfer/export.py` | `walk_unit_joins`'s inner `emit()` — 4th `isinstance` arm |
| `courses/views.py` | `_callout_has_math`; `_spoiler_has_math` body OR |
| `templates/courses/elements/calloutelement.html` | body then `.callout__children` |
| `templates/courses/elements/spoilerelement.html` | body block **moved above** children |
| `courses/element_forms.py` | delete the `fields.pop("body")` guard |
| `templates/courses/manage/editor/_element_row.html` | `calloutelement` branch; reworded empty-states |
| `templates/courses/manage/editor/_add_menu.html` | depth-guard the Callout card |
| `courses/static/courses/css/courses.css` | `.callout__children`/`__child`, prose-cap narrowing, `.katex` heading reset |
| `courses/static/courses/css/editor.css` | `.el-row--callout .el-row__callout` |
| `core/static/core/css/app.css` | spoiler combined shape; `@media print` revert |
| `courses/static/courses/js/reveal.js` | `scopeOf` gains `.callout__children` |
| `templates/courses/lesson_unit.html` | 4th pre-hide selector |
| `courses/static/courses/js/math.js` | `renderInlineText` gains `.callout__heading` |
| `courses/migrations/00XX_*.py` | `RunPython` spoiler body cleanup |
| `docs/help/course-admin/{content-editors,interactive-elements}{,.pl}.md` | author documentation |

---

### Task 1: Shared `SINGLE_SLOT_ID` constant

Removes the write/import divergence: `validate_nesting` currently hard-codes `SpoilerElement.SLOT_ID` for *every* single-slot container, so a callout would validate only by string coincidence.

**Files:**
- Modify: `courses/models.py` (module level; `SpoilerElement:405`)
- Modify: `courses/transfer/payloads.py:750-753`, `:768`, `:788-792`
- Test: `courses/tests/test_single_slot_constant.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `courses.models.SINGLE_SLOT_ID: str` (value `"only"`), referenced by `SpoilerElement.SLOT_ID` and (Task 2) `CalloutElement.SLOT_ID`.

- [ ] **Step 1: Write the failing test**

`courses/tests/test_single_slot_constant.py`:

```python
"""The single-slot id must have ONE home, not a literal per model.

`validate_nesting` hard-coded SpoilerElement.SLOT_ID for every single-slot
container, so a second single-slot container would validate only because both
classes happen to spell "only".

Do NOT pin this with `CalloutElement.SLOT_ID is SpoilerElement.SLOT_ID`: "only" is
identifier-shaped, so CPython interns it and two INDEPENDENT `SLOT_ID = "only"`
literals are the same object -- the `is` test is green under the exact divergence
it would be written to catch. The pin is source-level instead.
"""

import inspect
import re

from courses.models import SINGLE_SLOT_ID
from courses.models import SpoilerElement


def _executable_source(cls):
    """Class source with `#` comments and the docstring removed.

    Both must go: `comments-can-fail-tests` is a standing lesson here, and
    SpoilerElement's docstring already narrates its slot -- scanning it would fail a
    CORRECT implementation whose prose happens to quote the literal.
    """
    src = inspect.getsource(cls)
    doc = cls.__doc__
    if doc:
        src = src.replace(doc, "", 1)
    return re.sub(r"#.*", "", src)


def test_single_slot_id_value_is_unchanged():
    # A stored Element.tab_id value on every existing nested-spoiler child.
    assert SINGLE_SLOT_ID == "only"


def test_spoiler_does_not_respell_the_slot_literal():
    assert 'SLOT_ID' in _executable_source(SpoilerElement)
    assert '"only"' not in _executable_source(SpoilerElement)
    assert "'only'" not in _executable_source(SpoilerElement)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_single_slot_constant.py --verbosity=0`
Expected: FAIL — `ImportError: cannot import name 'SINGLE_SLOT_ID'`.

- [ ] **Step 3: Add the constant and point both consumers at it**

In `courses/models.py`, at module level **above** `class SpoilerElement` (models.py must own it — defining it in `payloads.py` would make `courses.models` import `courses.transfer`, which imports `courses.models`: a circular import):

```python
# The single implicit child slot shared by every single-slot container
# (SpoilerElement, CalloutElement). This is a STORED Element.tab_id value on every
# existing nested-spoiler child -- changing it would orphan them. One home, so the
# write path (builder.resolve_scope) and the import path
# (transfer.payloads.validate_nesting) cannot drift apart.
SINGLE_SLOT_ID = "only"
```

In `SpoilerElement`, replace the literal:

```python
    SLOT_ID = SINGLE_SLOT_ID  # the single implicit child slot; child Element.tab_id
```

In `courses/transfer/payloads.py`, extend the lazy import inside `validate_nesting` (currently `from courses.models import SpoilerElement` at `:768`):

```python
    from courses.models import SINGLE_SLOT_ID
```

Delete the now-unused `SpoilerElement` import if nothing else in the function uses it, and change `:788-792`:

```python
        valid_slot_ids = (
            {SINGLE_SLOT_ID}
            if slot_key is None
            else {s["id"] for s in parent["data"][slot_key]}
        )
```

Update both false comments — `:750-752` and the second, distinct one at `:779-781` — to say the single-slot id comes from `SINGLE_SLOT_ID`, not from `SpoilerElement`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_single_slot_constant.py courses/tests/test_spoiler_transfer.py courses/tests/test_spoiler_nesting.py --verbosity=0`
Expected: PASS.

- [ ] **Step 5: Falsify**

Temporarily re-spell `SpoilerElement.SLOT_ID = "only"`. Run Step 4. Expected: `test_spoiler_does_not_respell_the_slot_literal` RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/transfer/payloads.py courses/tests/test_single_slot_constant.py
git commit -m "refactor(nesting): single shared SINGLE_SLOT_ID for single-slot containers"
```

---

### Task 2: `CalloutElement` container model + render template

**Files:**
- Modify: `courses/models.py:447-483` (`CalloutElement`)
- Modify: `templates/courses/elements/calloutelement.html`
- Test: `courses/tests/test_callout_container.py` (create)

**Interfaces:**
- Consumes: `courses.models.SINGLE_SLOT_ID` (Task 1).
- Produces: `CalloutElement.SLOT_ID`, `.join_row() -> Element | None`, `.resolved_children() -> list[Element]`, `.render(*, element=None, state=None, slug=None, node_pk=None) -> str`. Template emits `.callout__children > .callout__child`.

- [ ] **Step 1: Write the failing test**

`courses/tests/test_callout_container.py`:

```python
"""CalloutElement as a single-slot container (mirrors SpoilerElement)."""

import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import SINGLE_SLOT_ID
from courses.models import TextElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _callout_with_children(unit, bodies, callout_body=""):
    from tests.factories import add_element

    co = CalloutElement.objects.create(kind="example", body=callout_body)
    join = add_element(unit, co)
    for i, b in enumerate(bodies):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=b),
            parent=join,
            tab_id=SINGLE_SLOT_ID,
            order=i,
        )
    return co, join


def test_callout_does_not_respell_the_slot_literal():
    """The REAL pin. `CalloutElement.SLOT_ID is SINGLE_SLOT_ID` is VACUOUS: "only" is
    identifier-shaped, so CPython interns it and an independent `SLOT_ID = "only"`
    yields the SAME object -- green under exactly the divergence it would guard.
    Task 1 scans SpoilerElement; the spec's row says NEITHER model may re-spell it.
    """
    from courses.tests.test_single_slot_constant import _executable_source

    src = _executable_source(CalloutElement)
    assert "SLOT_ID" in src
    assert '"only"' not in src
    assert "'only'" not in src


def test_resolved_children_is_empty_when_join_row_is_transient():
    co = CalloutElement.objects.create(kind="example", body="<p>x</p>")
    assert co.resolved_children() == []


def test_render_emits_children_in_order():
    _course, unit = make_course_with_unit()
    co, join = _callout_with_children(unit, ("<p>FIRST</p>", "<p>SECOND</p>"))
    html = co.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "callout__children" in html
    assert html.index("FIRST") < html.index("SECOND")


def test_render_emits_body_ABOVE_children():
    _course, unit = make_course_with_unit()
    co, join = _callout_with_children(unit, ("<p>CHILD</p>",), callout_body="<p>BODY</p>")
    html = co.render(element=join, state={}, slug="x", node_pk=unit.pk)
    # Source ORDER, not mere presence -- a presence-only assertion is green under
    # the wrong order.
    assert html.index("BODY") < html.index("CHILD")


def test_render_passes_element_state_not_state():
    """The recursive {% render_element child %} reads context["element_state"].

    Passing `state=state` (matching the kwarg name) renders nested stateful children
    with empty state and an empty save URL -- a silent, 200-OK state loss.

    The child MUST be genuinely stateful: a TextElement has no blob and no save URL,
    so `state=` vs `element_state=` changes nothing observable and the test is vacuous.
    And no `or` -- each assertion must carry on its own.
    """
    from courses.models import StepperElement, StepperStep

    _course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    st = StepperElement.objects.create(prompt="p")
    StepperStep.objects.create(stepper=st, content="one", order=0)
    StepperStep.objects.create(stepper=st, content="two", order=1)
    child = Element.objects.create(
        unit=unit, content_object=st, parent=join, tab_id=CalloutElement.SLOT_ID
    )
    html = co.render(
        element=join,
        state={child.pk: {"shown": 2}},
        slug="course-slug",
        node_pk=unit.pk,
    )
    assert "shown" in html and "2" in html      # the stored blob reached the child
    assert "course-slug" in html                # the save URL is populated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_callout_container.py --verbosity=0`
Expected: FAIL — `AttributeError: type object 'CalloutElement' has no attribute 'SLOT_ID'`.

- [ ] **Step 3: Implement the model methods**

In `courses/models.py`, inside `CalloutElement` (it already has `elements = GenericRelation(Element)`):

```python
    SLOT_ID = SINGLE_SLOT_ID  # the single implicit child slot; child Element.tab_id

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1)."""
        return self.elements.order_by("pk").first()

    def resolved_children(self):
        """Ordered child Element join rows (order_by('order','pk')); [] when the
        join row is transient/mid-create. Grouped by `parent` alone — the single
        slot means tab_id is not needed to disambiguate."""
        join = self.join_row()
        if join is None:
            return []
        return list(
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        return render_to_string(
            "courses/elements/calloutelement.html",
            {
                "el": self,
                "children": self.resolved_children(),
                # `element_state`, NOT `state`: courses_extras.render_element reads
                # context.get("element_state") for the recursive child render.
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )
```

- [ ] **Step 4: Update the render template**

`templates/courses/elements/calloutelement.html` — body first, then children:

```html
{% load i18n courses_extras %}
<aside class="callout callout--{{ el.kind }}">
  <div class="callout__header">
    {% include "courses/elements/_callout_icon.html" %}
    <span class="callout__heading">{{ el.display_heading }}</span>
  </div>
  {% if el.body %}
    <div class="el el--text callout__body">{{ el.body|sanitize }}</div>
  {% endif %}
  {% if children %}
    {% comment %}
    One wrapper, for three reasons of its own (NOT the #212 continuous-rule
    argument, which is about .spoiler__children's 2px left rule -- this wrapper
    carries no rule): it is the node reveal.js `scopeOf` resolves to, the anchor for
    `.callout__body + .callout__children`, and the subject of the
    `:has(> .callout__children)` predicate the prose-cap narrowing keys on.
    `.callout__child` must carry NO `display` declaration -- if one is ever added,
    `.callout__child[hidden]` must join the app.css [hidden] guard, or the reveal
    cascade's `gateWrap.hidden = true` stops working.
    {% endcomment %}
    <div class="callout__children">
      {% for child in children %}
        <div class="callout__child">{% render_element child %}</div>
      {% endfor %}
    </div>
  {% endif %}
</aside>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_callout_container.py courses/tests/test_callout_render.py --verbosity=0`
Expected: PASS.

- [ ] **Step 6: Falsify**

Swap the two blocks in the template so children render first. Expected: `test_render_emits_body_ABOVE_children` RED. Revert.

- [ ] **Step 7: Commit**

```bash
git add courses/models.py templates/courses/elements/calloutelement.html courses/tests/test_callout_container.py
git commit -m "feat(callout): single-slot container model + child render"
```

---

### Task 3: Register callout in all three registries

**Files:**
- Modify: `courses/builder.py:27-31` (comment + `CONTAINER_TRANSFER_KEYS`), `:89-99` (`_CONTAINER_REGISTRY`)
- Modify: `courses/transfer/payloads.py:753` (`_CONTAINER_SLOT_KEY`)
- Test: `courses/tests/test_callout_nesting.py` (create)

**Interfaces:**
- Consumes: `CalloutElement.SLOT_ID`, `.resolved_children()` (Task 2).
- Produces: `builder.resolve_scope(unit, str(join.pk), "only", "<type>")` returns `(join, "only")` for a callout parent.

- [ ] **Step 1: Write the failing test**

`courses/tests/test_callout_nesting.py`:

```python
"""Callout as a nesting PARENT: the three registries plus the depth clauses."""

import pytest

from courses import builder
from courses.models import CalloutElement
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def _top_callout(unit):
    from tests.factories import add_element

    co = CalloutElement.objects.create(kind="example")
    return co, add_element(unit, co)


def test_registries_agree_with_callout_added():
    """The drift guard: all three must gain callout together."""
    from courses.transfer.payloads import _CONTAINER_SLOT_KEY

    assert "callout" in builder.CONTAINER_TRANSFER_KEYS
    assert builder.CONTAINER_TRANSFER_KEYS == set(_CONTAINER_SLOT_KEY)
    assert len(builder.CONTAINER_TRANSFER_KEYS) == len(builder._CONTAINER_REGISTRY)


def test_resolve_scope_accepts_a_table_into_a_callout():
    _course, unit = make_course_with_unit()
    _co, join = _top_callout(unit)
    parent, tab = builder.resolve_scope(unit, str(join.pk), CalloutElement.SLOT_ID, "table")
    assert (parent, tab) == (join, CalloutElement.SLOT_ID)


def test_resolve_scope_rejects_an_unknown_slot():
    _course, unit = make_course_with_unit()
    _co, join = _top_callout(unit)
    with pytest.raises(builder.NestingError):
        builder.resolve_scope(unit, str(join.pk), "nope", "table")


def test_callout_in_callout_is_authorable():
    """Same-type nesting -- the shape a fixture monoculture hides (PR #209)."""
    _course, unit = make_course_with_unit()
    _co, join = _top_callout(unit)
    parent, tab = builder.resolve_scope(unit, str(join.pk), CalloutElement.SLOT_ID, "callout")
    assert parent == join
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_callout_nesting.py --verbosity=0`
Expected: FAIL — `NestingError: parent is not a container`, and the drift assertion fails.

- [ ] **Step 3: Implement**

`courses/builder.py` — replace the stale PR2 to-do comment at `:27-31` (it is now done) and extend the set:

```python
# Container TYPE KEYS (transfer namespace). Clause 4 of the containment rule tests
# membership here. Any new container must be added to THIS set, to
# _CONTAINER_REGISTRY and to payloads._CONTAINER_SLOT_KEY -- all three. The drift
# test in test_nesting_rule.py is what stops it landing in only two.
CONTAINER_TRANSFER_KEYS = frozenset({"tabs", "two_column", "spoiler", "callout"})
```

In `_CONTAINER_REGISTRY`, alongside the spoiler entry:

```python
    # Single-slot, like SpoilerElement: ignores its argument and returns one fixed
    # slot. CalloutElement has no `data` field, which is why the call site uses
    # getattr(parent_obj, "data", None).
    CalloutElement: (
        lambda _data: {"slots": [{"id": CalloutElement.SLOT_ID}]},
        "slots",
        "id",
    ),
```

Add `from courses.models import CalloutElement` to the imports at the top of `builder.py`.

`courses/transfer/payloads.py:753`:

```python
_CONTAINER_SLOT_KEY = {"tabs": "tabs", "two_column": "columns", "spoiler": None, "callout": None}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_callout_nesting.py courses/tests/test_nesting_rule.py --verbosity=0`
Expected: PASS.

- [ ] **Step 5: Falsify the drift guard**

Remove `"callout"` from `_CONTAINER_SLOT_KEY` only. Expected: `test_registries_agree_with_callout_added` RED. Revert.

- [ ] **Step 6: Commit**

```bash
git add courses/builder.py courses/transfer/payloads.py courses/tests/test_callout_nesting.py
git commit -m "feat(callout): register as a container in all three registries"
```

---

### Task 4: Depth clauses and the D3a import break

Arming clause 4 for `callout` makes a depth-4 callout — legal today — rejected on import and on `duplicate_unit`. Measured exposure: **zero** rows (`libli` 71 at depth 1, 12 at depth 2, 0 at depth ≥3; `libli_mat` has no callouts). Accepted as decision D3a and pinned so it is a decided outcome, not an accident.

**Files:**
- Test: `courses/tests/test_callout_nesting.py` (extend), `courses/tests/test_callout_transfer.py` (extend)

**Interfaces:**
- Consumes: Task 3's registries.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_callout_nesting.py`:

```python
def test_canonical_spoiler_tabs_callout_table_is_authorable():
    """spoiler(1) > tabs(2) > callout(3) > table(4) -- the deepest legal shape."""
    from courses.models import Element, SpoilerElement, TabsElement
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)

    tabs = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "One"}]})
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    co = CalloutElement.objects.create(kind="example")
    co_join = Element.objects.create(
        unit=unit, content_object=co, parent=tabs_join, tab_id="t000001"
    )
    # depth(co_join) == 3, so a LEAF child at depth 4 is legal...
    parent, _tab = builder.resolve_scope(
        unit, str(co_join.pk), CalloutElement.SLOT_ID, "table"
    )
    assert parent == co_join


def test_a_container_may_not_be_nested_at_depth_4():
    """Clause 4: callout is now a container, so it is refused where a leaf is fine."""
    from courses.models import Element, SpoilerElement, TabsElement
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s")
    sp_join = add_element(unit, sp)
    tabs = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "One"}]})
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=sp_join, tab_id=SpoilerElement.SLOT_ID
    )
    sp2 = SpoilerElement.objects.create(label="s2")
    sp2_join = Element.objects.create(
        unit=unit, content_object=sp2, parent=tabs_join, tab_id="t000001"
    )
    with pytest.raises(builder.NestingError):
        builder.resolve_scope(unit, str(sp2_join.pk), SpoilerElement.SLOT_ID, "callout")
```

Append to `courses/tests/test_callout_transfer.py`:

```python
def test_import_rejects_a_depth_4_callout_archive():
    """D3a, a DECIDED break: a depth-4 callout was legal before this slice, so an
    archive containing one becomes unimportable. Measured exposure: 0 rows.
    """
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError

    elements = [
        {"id": "a", "type": "spoiler", "parent": None, "tab": "", "data": {}},
        {"id": "b", "type": "spoiler", "parent": "a", "tab": "only", "data": {}},
        {"id": "c", "type": "spoiler", "parent": "b", "tab": "only", "data": {}},
        {"id": "d", "type": "callout", "parent": "c", "tab": "only", "data": {}},
    ]
    with pytest.raises(TransferError):
        validate_nesting(elements)
```

- [ ] **Step 2: Run tests — expected PASS**

Run: `uv run pytest courses/tests/test_callout_nesting.py courses/tests/test_callout_transfer.py --verbosity=0`
Expected: **PASS.** These pin behaviour Task 3 already introduced, so there is no
red-first step here — Step 4's falsification is the mandatory RED evidence instead. If
either fails now, the defect is in Task 3, not in these tests.

- [ ] **Step 3: No production change**

These pin behaviour Task 3 introduced. If any fails, the defect is in Task 3.

- [ ] **Step 4: Falsify — this is the RED evidence for this task**

Remove `"callout"` from `CONTAINER_TRANSFER_KEYS` (leave the other two registries).
Expected: **both** `test_import_rejects_a_depth_4_callout_archive` and
`test_a_container_may_not_be_nested_at_depth_4` go RED. If either stays green the test
is vacuous and must be rewritten before proceeding. Revert.

- [ ] **Step 5: Commit**

```bash
git add courses/tests/test_callout_nesting.py courses/tests/test_callout_transfer.py
git commit -m "test(callout): pin the depth clauses and the D3a import break"
```

---

### Task 5: Export walk descends into a callout

`walk_unit_joins`'s inner `emit()` is an explicit `isinstance` ladder whose docstring says **"NOT registry-driven"**. Without a fourth arm, callout children are visited by nothing (they are excluded from the `parent__isnull=True` root query) and vanish from every export — and from every `duplicate_unit`, which routes through `build_export` + `materialize_duplicate`.

**Files:**
- Modify: `courses/transfer/export.py:507-523`, and the comments at `:560-562`, `:660-663`
- Test: `courses/tests/test_callout_transfer.py` (extend)

**Interfaces:**
- Consumes: `CalloutElement.resolved_children()`, `CalloutElement.SLOT_ID`.
- Produces: exported payloads containing callout children with `parent` and `tab = "only"`.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_callout_transfer.py`:

```python
def test_export_emits_a_table_inside_a_callout():
    from courses.models import CalloutElement, Element, TableElement
    from tests.factories import add_element
    from courses.transfer import export as _export
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example", body="<p>intro</p>")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "CELL-MARKER"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    _manifest, document, _media, _problems = _export.build_export(course)
    # Assert STRUCTURALLY, not on str(document): the child must appear in the element
    # list wired to its parent with tab == the single slot id. (`_ser_table` returns
    # `dict(el.data)` verbatim, so a stringified assertion would also pass with a
    # wrong data key -- see the "cells" vs "rows" trap.)
    elements = document["units"][0]["elements"]
    child = next(e for e in elements if e["type"] == "table")
    parent = next(e for e in elements if e["type"] == "callout")
    assert child["parent"] == parent["id"]
    assert child["tab"] == CalloutElement.SLOT_ID
    assert "CELL-MARKER" in str(child["data"])


def test_duplicate_unit_preserves_a_table_inside_a_callout():
    """Same missing emit() arm; duplicate_unit is the far more common gesture."""
    from courses.models import CalloutElement, ContentNode, Element, TableElement
    from tests.factories import add_element
    from courses import builder as _builder
    from tests.factories import make_course_with_unit

    course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "DUP-MARKER"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    new_node = _builder.duplicate_unit(course, unit.pk, token=unit.updated.isoformat())
    copied = Element.objects.filter(unit=new_node, parent__isnull=False)
    assert any(
        "DUP-MARKER" in str(getattr(e.content_object, "data", ""))
        for e in copied
    ), "the callout's child was dropped by the duplicate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_callout_transfer.py --verbosity=0`
Expected: FAIL — `CELL-MARKER`/`DUP-MARKER` absent.

- [ ] **Step 3: Add the fourth arm**

`courses/transfer/export.py`, in `emit()` after the `SpoilerElement` branch:

```python
        elif isinstance(obj, CalloutElement):
            for child in obj.resolved_children():
                yield from emit(child, join, CalloutElement.SLOT_ID)
```

`CalloutElement` is **already imported** at `courses/transfer/export.py:11` (used by `_ser_callout`) — adding it again is a ruff F811. Update the two comments that enumerate the containers: `:560-562` ("tabs, two_column, spoiler") and `:660-663` ("A parent is always a CONTAINER element (tabs, two_column, or spoiler)").

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_callout_transfer.py tests/test_transfer_schema.py --verbosity=0`
Expected: PASS.

- [ ] **Step 5: Falsify**

Comment out the new `elif`. Expected: both new tests RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/transfer/export.py courses/tests/test_callout_transfer.py
git commit -m "fix(export): descend into a callout's children"
```

---

### Task 6: `has_math` — recursion for callout, body OR for spoiler

Both are **silent** failures: no error, no bad status code, just raw LaTeX on the page.

**Files:**
- Modify: `courses/views.py:202-203` (dispatch), `:249-264` (`_spoiler_has_math`), and add `_callout_has_math`
- Test: `courses/tests/test_callout_has_math.py` (**extend**) — it already exists
  with 5 tests and is the established home for callout math detection. Do NOT create
  a near-identically-named `test_callout_math.py`; its existing tests are also the
  regression gate for this change and must keep passing.

**Interfaces:**
- Consumes: `CalloutElement.resolved_children()`.
- Produces: `_callout_has_math(el) -> bool` in `courses/views.py`.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_callout_has_math.py`:

```python
"""KaTeX arming for the newly-legal nesting shapes. A miss here is SILENT."""

import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import SpoilerElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.views import _element_has_math
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def test_callout_body_math_is_detected():
    co = CalloutElement.objects.create(kind="example", body=r"<p>\(x^2\)</p>")
    assert _element_has_math(co) is True


def test_transient_callout_with_body_math_is_detected():
    """No join row yet. The `join_row() is None` guard must sit on the CHILDREN walk
    only -- _twocolumn_has_math's top-of-function guard is correct there because a
    two-column element has no text of its own, but a callout does."""
    co = CalloutElement.objects.create(kind="example", body=r"<p>\(a\)</p>")
    assert co.join_row() is None
    assert _element_has_math(co) is True


def test_callout_stored_heading_math_is_detected():
    co = CalloutElement.objects.create(kind="example", heading=r"Wzór \(a^2\)")
    assert _element_has_math(co) is True


def test_math_in_a_table_inside_a_callout_is_detected():
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": r"\(x^2\)"}]]}
        ),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    assert _element_has_math(co) is True


def test_math_TWO_containers_deep_inside_a_callout_is_detected():
    """callout > tabs > table. Kills a non-recursive walk that special-cases tables."""
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    tabs = TabsElement.objects.create(data={"tabs": [{"id": "t000001", "label": "One"}]})
    tabs_join = Element.objects.create(
        unit=unit, content_object=tabs, parent=join, tab_id=CalloutElement.SLOT_ID
    )
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": r"\(y^3\)"}]]}
        ),
        parent=tabs_join,
        tab_id="t000001",
    )
    assert _element_has_math(co) is True


def test_spoiler_with_body_math_AND_children_is_detected():
    """The regression D1 INTRODUCES: before this slice a bodied spoiler with children
    could not render its body, so nothing covered this."""
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    sp = SpoilerElement.objects.create(label="s", body=r"<p>\(z^2\)</p>")
    join = add_element(unit, sp)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>no math here</p>"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    assert _element_has_math(sp) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_callout_has_math.py --verbosity=0`
Expected: FAIL on the heading, nested-table, two-deep and spoiler-body cases.

- [ ] **Step 3: Implement**

`courses/views.py` — change the dispatch at `:202-203` (keep the explicit branch; do **not** add callout to the trailing fallback chain, which exists for types with no explicit branch and would be unreachable dead code):

```python
    if isinstance(obj, CalloutElement):
        return _callout_has_math(obj)
```

Add, beside `_spoiler_has_math`:

```python
def _callout_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. Children are dispatched
    through _element_has_math, never has_math_delimiters directly: callout > tabs >
    table is legal, and a non-recursive walk passes a depth-1 test while silently
    missing math two containers deep.

    ORDER IS LOAD-BEARING: heading -> body -> children, with the transient guard on
    the CHILDREN walk only. A top-of-function `join_row() is None` guard (correct in
    _twocolumn_has_math, which has no text of its own) would make a transient callout
    carrying math in its heading or body report False.

    `heading` is the STORED field, never `display_heading` -- the per-kind defaults
    are translated labels and can never carry math.
    """
    from courses.models import CalloutElement

    if not isinstance(el, CalloutElement):
        return False
    if has_math_delimiters(el.heading):
        return True
    if has_math_delimiters(el.body):
        return True
    # The transient guard sits HERE, after heading/body -- never at the top. A
    # top-of-function guard (correct in _twocolumn_has_math, which has no text of its
    # own) would make a transient callout with heading/body math report False. The
    # spec chose to KEEP the guard rather than rely on resolved_children() == [], so
    # the "move it to the top" mutant stays applicable.
    if el.join_row() is None:
        return False
    return any(_element_has_math(c.content_object) for c in el.resolved_children())
```

Change `_spoiler_has_math`'s tail — the body must be OR'd in unconditionally now that it always renders:

```python
    if has_math_delimiters(el.body):
        return True
    return any(_element_has_math(c.content_object) for c in el.resolved_children())
```

and update its docstring, which currently claims "A nested spoiler has an empty body".

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_callout_has_math.py courses/tests/test_spoiler_nesting.py --verbosity=0`
Expected: PASS.

- [ ] **Step 5: Falsify (three mutants)**

1. Move the `join_row() is None` guard to the top of `_callout_has_math` → `test_transient_callout_with_body_math_is_detected` RED.
2. Replace the children walk with `has_math_delimiters(str(c.content_object))` → `test_math_TWO_containers_deep_inside_a_callout_is_detected` RED.
3. Restore `if not children: return has_math_delimiters(el.body)` in `_spoiler_has_math` → `test_spoiler_with_body_math_AND_children_is_detected` RED.

Revert all three.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/tests/test_callout_has_math.py
git commit -m "fix(math): recurse into callout children; spoiler body always counts"
```

---

### Task 7: Spoiler body reachability (template + form)

**Files:**
- Modify: `templates/courses/elements/spoilerelement.html:7-30`
- Modify: `courses/element_forms.py:224-230`
- Modify: `courses/tests/test_spoiler_nesting.py:63`, `:266` (invert)
- Modify: `courses/models.py:399-401` (docstring)

**Interfaces:**
- Consumes: nothing.
- Produces: a spoiler that renders body-then-children; `SpoilerElementForm` always exposes `body`.

- [ ] **Step 1: Invert the two existing tests**

In `courses/tests/test_spoiler_nesting.py`, replace `test_render_prefers_children_over_body` (`:63`):

```python
def test_render_shows_body_ABOVE_children():
    """D1: content a CA enters must stay reachable. Both render; body first.

    Assert source ORDER -- a presence-only assertion is green under the wrong order,
    and the current template puts `{% if children %}` FIRST, so a bare elif->if
    conversion produces children-above-body.
    """
    _course, unit = make_course_with_unit()
    sp, join = _nested_spoiler(unit, ("<p>CHILD-BODY</p>",))
    sp.body = "<p>LEGACY-BODY</p>"
    sp.save()
    html = sp.render(element=join, state={}, slug="x", node_pk=unit.pk)
    assert "CHILD-BODY" in html
    assert "LEGACY-BODY" in html
    assert html.index("LEGACY-BODY") < html.index("CHILD-BODY")
```

Replace `test_spoiler_form_drops_body_when_instance_has_children` (`:266`):

```python
def test_spoiler_form_keeps_body_when_instance_has_children():
    """The `fields.pop` protected data nobody could reach: not rendered (template
    elif) and not editable (this pop), with no signal anywhere."""
    from courses.element_forms import SpoilerElementForm

    _course, unit = make_course_with_unit()
    sp, _join = _nested_spoiler(unit, ("<p>c</p>",))
    form = SpoilerElementForm(instance=sp)
    assert "body" in form.fields
    assert "label" in form.fields
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_spoiler_nesting.py --verbosity=0`
Expected: FAIL — `LEGACY-BODY` not in html; `"body"` not in `form.fields`.

- [ ] **Step 3: Move the body block above the children block**

`templates/courses/elements/spoilerelement.html` — the body block must **move**, not merely change `elif` to `if`:

```html
{% load i18n courses_extras %}
<details class="spoiler">
  <summary class="spoiler__toggle">
    <span class="spoiler__label spoiler__label--show">{% if el.label %}{{ el.label }}{% else %}{% trans "Reveal" %}{% endif %}</span>
    <span class="spoiler__label spoiler__label--hide">{% trans "Hide" %}</span>
  </summary>
  {% if el.body %}
    <div class="el el--text spoiler__body">{{ el.body|sanitize }}</div>
  {% endif %}
  {% if children %}
    {% comment %}
    The children share ONE wrapper so the revealed region can carry a single
    CONTINUOUS left rule. A border on each `.spoiler__child` cannot work: a child's
    inner element margins collapse THROUGH the child (measured: 16px holes).

    `.spoiler__child` stays a DIRECT child of this wrapper, and the wrapper is what
    the reveal cascade scopes to: reveal.js `scopeOf` matches `.spoiler__children`
    ahead of `.spoiler`, the pre-hide CSS in lesson_unit.html walks
    `.spoiler__children > .spoiler__child`, and the @media print revert in app.css
    must revert the same. Those must agree -- see the reveal-scope agreement test.

    Both blocks can now render together (body FIRST). See app.css for the combined
    shape's rule alignment.
    {% endcomment %}
    <div class="spoiler__children">
      {% for child in children %}
        <div class="spoiler__child">{% render_element child %}</div>
      {% endfor %}
    </div>
  {% endif %}
</details>
```

- [ ] **Step 4: Delete the form guard**

`courses/element_forms.py` — remove the whole `__init__` override:

```python
class SpoilerElementForm(forms.ModelForm):
    class Meta:
        model = SpoilerElement
        fields = ["label", "body"]
```

- [ ] **Step 5: Update the model docstring**

`courses/models.py:399-401` — `SpoilerElement` no longer expands "either … OR"; it renders body **and** children.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_spoiler_nesting.py courses/tests/test_spoiler_render.py courses/tests/test_spoiler_form.py courses/tests/test_spoiler_context.py --verbosity=0`
Expected: PASS. Then run the concrete sweep for any other either/or assumption:

```bash
rg -n "spoiler__body|spoiler__children" courses/tests/test_spoiler_*.py
```

Check each hit's fixture: only a spoiler that has children is affected.
`test_spoiler_render.py:46-58` is the only place asserting on both shapes and its
fixtures are body-only, so it is **expected to stay green** — if it goes red, something
else changed.

- [ ] **Step 7: Add the bodied same-type nesting fixture**

The spec mandates `spoiler > spoiler` **where the outer has a body** — the newly-legal
combination D1 creates, and the one both the combined-shape CSS and the
`_spoiler_has_math` change key on. Task 13's render-seam branch builds a *body-less*
spoiler, so it does not cover this. Append to `courses/tests/test_spoiler_nesting.py`:

```python
def test_bodied_spoiler_nesting_a_spoiler_keeps_body_above_children_at_both_levels():
    """Same-type nesting with a bodied outer -- the fixture-monoculture gap PR #209
    root-caused. Both levels must render body first."""
    from courses.models import Element, SpoilerElement, TextElement
    from tests.factories import add_element

    _course, unit = make_course_with_unit()
    outer = SpoilerElement.objects.create(label="outer", body="<p>OUTER-BODY</p>")
    outer_join = add_element(unit, outer)
    inner = SpoilerElement.objects.create(label="inner", body="<p>INNER-BODY</p>")
    inner_join = Element.objects.create(
        unit=unit, content_object=inner, parent=outer_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>INNER-CHILD</p>"),
        parent=inner_join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    html = outer.render(element=outer_join, state={}, slug="x", node_pk=unit.pk)
    assert html.index("OUTER-BODY") < html.index("INNER-BODY")
    assert html.index("INNER-BODY") < html.index("INNER-CHILD")
```

- [ ] **Step 8: Falsify**

Put the body block back below the children block. Expected:
`test_render_shows_body_ABOVE_children` **and** the new bodied-nesting test both RED.
Revert.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/elements/spoilerelement.html courses/element_forms.py courses/models.py courses/tests/test_spoiler_nesting.py
git commit -m "fix(spoiler): render body above children and keep it editable"
```

---

### Task 8: Cleanup migration

Without this, spoiler pk 1396 renders its explanation **twice** — its stranded body is byte-identical to its own child.

**Files:**
- Create: `courses/migrations/00XX_spoiler_body_cleanup.py`
- Test: `courses/tests/test_spoiler_body_cleanup.py` (create)

**Interfaces:**
- Consumes: nothing (historical models only).
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

`courses/tests/test_spoiler_body_cleanup.py` — test the predicate as an importable helper so it can be unit-tested without running the migration:

```python
"""Category A/B/C classification for the spoiler body cleanup.

Measured on the real data: libli 1xA + 1xB + 0xC; libli_mat 0. The predicate is
written defensively for shapes NOT observed locally, because production has not yet
taken the mat-pp cutover.
"""

import pytest

from courses.migrations_support import body_is_empty_ish

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "body",
    [
        "<br>",                 # the shape actually observed (pk 1395)
        "<p><br></p>",          # the RTE's normal "empty" output
        "<div><br></div>",
        "<div>&nbsp;</div>",
        "<p> </p>",        # decoded nbsp
        "   ",
    ],
)
def test_empty_ish_bodies_are_category_A(body):
    assert body_is_empty_ish(body) is True


@pytest.mark.parametrize("body", ["<p>real</p>", "<p>a &nbsp; b</p>", "<br>x"])
def test_real_content_is_not_category_A(body):
    assert body_is_empty_ish(body) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_body_cleanup.py --verbosity=0`
Expected: FAIL — `ModuleNotFoundError: courses.migrations_support`.

- [ ] **Step 3: Write the predicate helper**

`courses/migrations_support.py` (a leaf module so a migration can import it without dragging in models):

```python
"""Helpers a data migration can import without touching live model classes."""

import html
import re

_TAG = re.compile(r"<[^>]*>")


def body_is_empty_ish(body):
    """True when a rich-text body carries no visible content.

    strip tags -> unescape entities -> strip whitespace (str.strip() covers U+00A0 — it is `.isspace()`). Must catch
    `<br>`, `<p><br></p>`, `<div>&nbsp;</div>` and a decoded-nbsp body: both `div`
    and `p` are in ALLOWED_TAGS, and the RTE's normal empty output is `<p><br></p>`,
    not a bare `<br>`.
    """
    text = html.unescape(_TAG.sub("", body or ""))
    # str.strip() with no argument removes U+00A0 too: ' '.isspace() is True in
    # Python 3. No explicit nbsp pass is needed.
    return text.strip() == ""
```

- [ ] **Step 4: Write the migration**

`courses/migrations/00XX_spoiler_body_cleanup.py` — get the real number from `uv run python manage.py makemigrations --empty courses --name spoiler_body_cleanup`:

```python
from django.db import migrations

from courses.migrations_support import body_is_empty_ish

# Inlined, NEVER imported from the live model: a migration must not depend on
# today's value of a constant.
SLOT_ID = "only"


def clear_unreachable_bodies(apps, schema_editor):
    """Clear a spoiler `body` that is empty-ish (A) or an exact duplicate of one of
    its child TextElements (B). Anything else (C) is LEFT ALONE, so genuinely
    stranded content reappears above the children -- the correct outcome.

    Row filter is EVERY bodied spoiler, not only those with children: ~12 rows in
    libli carry a body and none, and the moment an author adds a child an empty-ish
    body would start rendering as a blank paragraph. Category A is safe to clear
    regardless of children; category B is only evaluated where children exist.
    """
    ContentType = apps.get_model("contenttypes", "ContentType")
    Element = apps.get_model("courses", "Element")
    SpoilerElement = apps.get_model("courses", "SpoilerElement")
    TextElement = apps.get_model("courses", "TextElement")

    try:
        sp_ct = ContentType.objects.get(app_label="courses", model="spoilerelement")
        text_ct = ContentType.objects.get(app_label="courses", model="textelement")
    except ContentType.DoesNotExist:
        return

    for sp in SpoilerElement.objects.exclude(body=""):
        if body_is_empty_ish(sp.body):
            SpoilerElement.objects.filter(pk=sp.pk).update(body="")
            continue

        join = (
            Element.objects.filter(content_type=sp_ct, object_id=sp.pk)
            .order_by("pk")
            .first()
        )
        if join is None:
            continue
        # `parent` ALONE, no tab_id filter -- mirrors resolved_children(), whose
        # docstring says the single slot makes tab_id unnecessary. A narrower filter
        # would let a drifted-tab_id child render (duplicating the body) while
        # staying invisible to this check.
        child_ids = Element.objects.filter(
            parent=join, content_type=text_ct
        ).values_list("object_id", flat=True)
        if TextElement.objects.filter(pk__in=list(child_ids), body=sp.body).exists():
            SpoilerElement.objects.filter(pk=sp.pk).update(body="")


def noop_reverse(apps, schema_editor):
    """Documented no-op: the migration only cleared fields that were unreachable."""


class Migration(migrations.Migration):
    dependencies = [("courses", "00XX_previous")]
    operations = [migrations.RunPython(clear_unreachable_bodies, noop_reverse)]
```

- [ ] **Step 5: Add the A/B/C behaviour test**

Append to `courses/tests/test_spoiler_body_cleanup.py`:

```python
# Fill in from the `makemigrations --empty` output, e.g. "0053".
_MIGRATION_PREFIX = "00XX"


def test_migration_clears_A_and_B_but_preserves_C():
    from courses.models import Element, SpoilerElement, TextElement
    from tests.factories import add_element
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()

    def _sp(body, child_body=None):
        sp = SpoilerElement.objects.create(label="s", body=body)
        join = add_element(unit, sp)
        if child_body is not None:
            Element.objects.create(
                unit=unit,
                content_object=TextElement.objects.create(body=child_body),
                parent=join,
                tab_id=SpoilerElement.SLOT_ID,
            )
        return sp

    dup = "<p>identical</p>"
    a = _sp("<p><br></p>", "<p>c</p>")
    b = _sp(dup, dup)
    c = _sp("<p>GENUINELY STRANDED</p>", "<p>different</p>")
    childless_a = _sp("<div>&nbsp;</div>")

    # Invoke the migration function directly against the live app registry.
    from django.apps import apps as live_apps
    from importlib import import_module

    mod = import_module(f"courses.migrations.{_MIGRATION_PREFIX}_spoiler_body_cleanup")
    mod.clear_unreachable_bodies(live_apps, None)

    a.refresh_from_db(); b.refresh_from_db(); c.refresh_from_db(); childless_a.refresh_from_db()
    assert a.body == ""
    assert b.body == ""
    assert c.body == "<p>GENUINELY STRANDED</p>", "category C must be preserved"
    assert childless_a.body == "", "category A applies to childless spoilers too"
```

`_MIGRATION_PREFIX` is a real module-level line in that test file — set it to the
number `makemigrations --empty` produced before running.

- [ ] **Step 6: Run tests and the migration check**

Run: `uv run pytest courses/tests/test_spoiler_body_cleanup.py --verbosity=0`
Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: tests PASS; migration check clean.

- [ ] **Step 7: Falsify**

Broaden the predicate so category C is also cleared. Expected: `test_migration_clears_A_and_B_but_preserves_C` RED. Revert. Then narrow the row filter to `children__isnull=False` — expected: the `childless_a` assertion RED. Revert.

- [ ] **Step 8: Commit**

```bash
git add courses/migrations_support.py courses/migrations/ courses/tests/test_spoiler_body_cleanup.py
git commit -m "fix(spoiler): clear unreachable bodies that would now render twice"
```

---

### Task 9: Editor row branch + palette guard

Two failure modes, both silent server-side: omit the branch and a callout falls to the generic leaf row (children unauthorable through the UI); leave the palette card unguarded and every click at depth 3 returns HTTP 400.

**Files:**
- Modify: `templates/courses/manage/editor/_element_row.html` (new `calloutelement` branch; reword `:189`)
- Modify: `templates/courses/manage/editor/_add_menu.html:12-17` (comment), `:38` (guard)
- Modify: `tests/test_editor_depth.py:82` (`CONTAINER_CARDS`), `:157` (invert), `:161` (docstring)
- Test: `courses/tests/test_callout_editor_row.py` (create)

**Interfaces:**
- Consumes: `CalloutElement.resolved_children()`, `.SLOT_ID`.
- Produces: `<li class="el-row el-row--callout" data-element="…">` containing `.el-row__callout > ol.element-list--nested` and a depth-guarded add-menu.

- [ ] **Step 1: Invert the existing depth tests**

`tests/test_editor_depth.py` — **anchor by content, not line number**; several cited
numbers in this plan drift by 1–6 lines and the `:157` one points at the
`CONTAINER_CARDS` loop rather than the callout assertion. Find the literal
`CONTAINER_CARDS = ` line:

```python
CONTAINER_CARDS = ("tabs", "twocolumn", "spoiler", "callout")
```

Then find the literal line `assert 'data-add-type="callout"' in menu` (around `:158`)
and flip it, keeping a genuine leaf so the test still proves the menu rendered:

```python
    assert 'data-add-type="callout"' not in menu  # now a CONTAINER, depth-guarded
    assert 'data-add-type="text"' in menu         # a real leaf still offered
```

Update the docstring that reads "includes `_add_menu.html` at **three** sites" (around
`:164`) — there are now four, and the fixture-choice rationale needs a callout clause.

- [ ] **Step 2: Write the failing editor-row test**

`courses/tests/test_callout_editor_row.py`:

```python
"""The editor row for a callout.

Every other test in this slice passes without this branch existing at all: the
depth tests use tabs fixtures, and "a callout accepts a table child" is satisfiable
through resolve_scope/POST without ever rendering the editor. So the branch needs
its own pins.
"""

import pytest

from courses.models import CalloutElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _editor_html(client, course, unit):
    from django.urls import reverse

    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    resp = client.get(url)
    # Assert 200 first, mirroring tests/test_editor_depth.py::_page -- otherwise a
    # 403/302 surfaces as "el-row--callout not in html" and misdirects the debugging.
    assert resp.status_code == 200
    return resp.content.decode()


def test_callout_row_renders_children_and_its_own_add_menu(client):
    from tests.factories import add_element

    pa = make_pa(client, "pa")
    course, unit = make_course_with_unit(owner=pa)
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>NESTED-CHILD</p>"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
    )
    html = _editor_html(client, course, unit)
    assert "el-row--callout" in html
    assert "el-row__callout" in html
    assert "NESTED-CHILD" in html
    # `_add_menu.html:25` emits data-parent/data-tab -- there is no `data-add-parent`.
    # And no `or`: `value="{pk}"` is emitted by _element_row_controls.html on EVERY
    # row, so it holds whether or not the nested menu rendered.
    assert f'data-parent="{join.pk}" data-tab="{CalloutElement.SLOT_ID}"' in html


def test_callout_row_keeps_the_base_class_and_data_element(client):
    """editor.js selects `.el-row[data-element]` at :147/:289/:391 for selection,
    alignment and the edit-slot lifecycle. A modifier-only row silently drops out."""
    from tests.factories import add_element

    pa = make_pa(client, "pa")
    course, unit = make_course_with_unit(owner=pa)
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    html = _editor_html(client, course, unit)
    assert 'class="el-row el-row--callout' in html
    assert f'data-element="{join.pk}"' in html
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest courses/tests/test_callout_editor_row.py tests/test_editor_depth.py --verbosity=0`
Expected: FAIL — `el-row--callout` absent; `data-add-type="callout"` still present at depth 3.

- [ ] **Step 4: Guard the palette card**

`templates/courses/manage/editor/_add_menu.html:38` — wrap it exactly like Tabs/Columns/Spoiler:

```html
      {% if depth < max_nest_depth|add:-1 %}<button type="button" class="typecard" data-add-type="callout"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-callout"/></svg>{% trans "Callout" %}</button>{% endif %}
```

Update the block comment at `:12-17`: the container list at `:12-13` is now four, and the "Callout is a plain LEAF in this slice and stays unguarded" claim at `:16-17` is false.

- [ ] **Step 5: Add the editor row branch**

`templates/courses/manage/editor/_element_row.html` — a `{% elif el.content_type.model == "calloutelement" %}` branch mirroring the spoiler branch at `:146-197`. The `<li>` MUST carry `class="el-row el-row--callout…"` and `data-element`. Empty-states, exact strings:

```html
      {% empty %}
        {% if obj.body %}
          <li class="empty-state">{% trans "This callout shows its text above. Add an element below to nest content inside it." %}</li>
        {% else %}
          <li class="empty-state">{% trans "This callout is empty." %}</li>
        {% endif %}
```

and the add-menu include, guarded:

```html
    {% if depth < max_nest_depth %}{% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=obj.SLOT_ID depth=depth %}{% endif %}
```

Reword the spoiler empty-state at `:189` — the body now renders, so the old text describes a hazard that no longer exists:

```html
          <li class="empty-state">{% trans "This spoiler shows its text above. Add an element below to nest more content." %}</li>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_callout_editor_row.py tests/test_editor_depth.py tests/test_manage_editor_menu.py --verbosity=0`
Expected: PASS.

- [ ] **Step 7: Falsify (two mutants)**

1. Delete the `calloutelement` branch → `test_callout_row_renders_children_and_its_own_add_menu` RED.
2. Emit `class="el-row--callout"` without the base class → `test_callout_row_keeps_the_base_class_and_data_element` RED.

Revert both.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/editor/ tests/test_editor_depth.py courses/tests/test_callout_editor_row.py
git commit -m "feat(editor): callout container row and depth-guarded palette card"
```

---

### Task 10: Callout CSS + editor row CSS + prose cap

`.callout` has `padding: var(--space-4)`, and **padding blocks margin collapsing** — the spoiler's "margins collapse through, height unchanged" rationale does not transfer.

**Files:**
- Modify: `courses/static/courses/css/courses.css` (after `:1589-1590`; the allowlist at `:959-975`; a `.katex` reset)
- Modify: `courses/static/courses/css/editor.css` (beside `:827`)
- Test: `courses/tests/test_callout_css.py` (create)

**Interfaces:**
- Consumes: `.callout__children` / `.callout__child` markup (Task 2), `.el-row--callout` (Task 9).
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

`courses/tests/test_callout_css.py`:

```python
"""Structural CSS pins. Computed-style behaviour is covered by e2e (Task 13)."""

import glob
import re
from pathlib import Path


def _courses_css():
    return "".join(
        Path(p).read_text(encoding="utf-8")
        for p in glob.glob("courses/static/courses/css/courses.css")
    )


def test_callout_children_have_edge_margin_resets_and_a_sibling_gap():
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    assert ".callout__children" in css
    assert ".callout__child + .callout__child" in css, "no gap between two children"
    assert ".callout__body + .callout__children" in css, "no body/children separation"


def test_prose_cap_no_longer_applies_to_a_callout_with_children():
    """A table nested in a callout must not inherit the 46rem prose cap.

    Adding a `.callout__body` selector would be a NO-OP (it already carries el--text,
    which is already in the allowlist); the load-bearing edit is narrowing `.callout`.
    """
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    assert ".callout:not(:has(> .callout__children))" in css
    assert re.search(r"unit-tree-collapsed[^{]*\]\s+\.callout\s*,", css) is None


def test_callout_heading_katex_resets_the_eyebrow_treatment():
    css = re.sub(r"/\*.*?\*/", "", _courses_css(), flags=re.S)
    block = css.split(".callout__heading .katex")[1].split("}")[0]
    assert "text-transform" in block
    assert "letter-spacing" in block
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_callout_css.py --verbosity=0`
Expected: FAIL — none of those selectors exist.

- [ ] **Step 3: Add the callout child rules**

`courses/static/courses/css/courses.css`, after the existing `.callout__body` pair at `:1589-1590`:

```css
/* Nested children. `.callout` has padding, which BLOCKS margin collapsing -- the
   spoiler's "margins collapse through, height unchanged" rationale does NOT
   transfer, which is why `.callout__body > :first-child/:last-child` already exist
   above and why the children need the same treatment.
   `.callout__child` deliberately carries NO `display` declaration: app.css's
   `[hidden] { display: none !important }` guard lists only .lesson-block and
   .tabs__child, and the reveal cascade sets `gateWrap.hidden = true`. If a display
   is ever added here, `.callout__child[hidden]` must join that guard. */
.callout__body + .callout__children { margin-top: var(--space-3); }
.callout__children > .callout__child:first-child > :first-child { margin-top: 0; }
.callout__children > .callout__child:last-child > :last-child { margin-bottom: 0; }
.callout__children > .callout__child + .callout__child { margin-top: var(--space-5); }

/* KaTeX inside the heading. The heading is the house eyebrow (0.75rem / 700 /
   0.08em / uppercase), and KaTeX emits glyphs as ordinary inherited-style spans --
   so without this reset `\(x^2\)` renders UPPERCASED and letter-spaced. KaTeX's own
   sheet sets `.katex { font-size: 1.21em }`, i.e. 0.9075rem against a 0.75rem
   label; 1em matches the label exactly. */
.callout__heading .katex {
  text-transform: none;
  letter-spacing: normal;
  font-size: 1em;
  color: inherit;
  font-weight: inherit;
}
```

- [ ] **Step 4: Narrow the prose cap**

In the allowlist at `:959-975`, replace the `.callout` line:

```css
  html.unit-tree-collapsed [data-unit-shell] .callout:not(:has(> .callout__children)),
```

Leave every other entry untouched. A prose-only callout keeps today's cap byte-for-byte; only one holding children un-caps.

- [ ] **Step 5: Add the editor row rule**

`courses/static/courses/css/editor.css`, beside the spoiler rule at `:827`:

```css
.el-row--callout .el-row__callout { margin-top: var(--space-3); }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_callout_css.py --verbosity=0`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/css/courses.css courses/static/courses/css/editor.css courses/tests/test_callout_css.py
git commit -m "style(callout): nested child spacing, prose-cap opt-out, heading katex reset"
```

---

### Task 11: Spoiler combined-shape CSS

The two shapes were mutually exclusive until Task 7, so nobody has seen them stacked: `.spoiler__body` carries `margin-left: var(--space-3)` while `.spoiler > .spoiler__children` carries none, so the two 2px rules render at **different left offsets with a vertical gap**.

**Files:**
- Modify: `core/static/core/css/app.css` — **below** `:986-993`
- Test: `courses/tests/test_spoiler_combined_shape.py` (create — the placement
  guard below); the *behaviour* is pinned only by Task 13's first e2e

**Interfaces:** none.

- [ ] **Step 1: Add the rules, BELOW the shared block**

**Placement is a real trap and it is cross-file.** `courses/tests/test_spoiler_css.py:34` does `css.split(".spoiler__children")[1].split("}")[0]` on the concatenation, and `_all_css()` globs `courses/static/courses/css/*.css` **first**, then `core/static/core/css/*.css`. So every new selector mentioning `.spoiler__children` must live in `app.css` **below** the shared block, and **none may appear in `courses.css`/`editor.css` at all**.

In `core/static/core/css/app.css`, immediately after the `.spoiler__body { margin: … }` rule:

```css
/* COMBINED SHAPE (body AND children, newly possible): the two 2px rules must read
   as ONE continuous line. The gap has TWO symmetric sources -- `.spoiler__body` has
   no bottom padding or border, so its own last child's margin-bottom collapses
   THROUGH it and survives a margin-bottom:0 on the body itself; and the wrapper is
   deliberately not a flow-root, so the first child's margin-top collapses through
   it too.
   These rules MUST stay below the shared `.spoiler__body, .spoiler >
   .spoiler__children` block above: test_spoiler_css.py splits the concatenated CSS
   on the FIRST occurrence of `.spoiler__children`. */
.spoiler__body:has(+ .spoiler__children) { margin-left: 0; margin-bottom: 0; }
.spoiler__body:has(+ .spoiler__children) > :last-child { margin-bottom: 0; }
.spoiler__body + .spoiler__children > .spoiler__child:first-child > :first-child { margin-top: 0; }
```

- [ ] **Step 2: Run the existing CSS test**

Run: `uv run pytest courses/tests/test_spoiler_css.py --verbosity=0`
Expected: PASS (the split still lands on the shared block).

- [ ] **Step 3: Falsify the placement constraint**

Move the three new rules **above** the shared block. Expected: `test_spoiler_css.py` RED (the split reads the new declarations). Move them back.

- [ ] **Step 4: Commit**

```bash
git add core/static/core/css/app.css
git commit -m "style(spoiler): align the body and children rules into one continuous line"
```

---

### Task 12: Reveal cascade — three scope lists + agreement test

`reveal_gate`, `fill_gate` and `switch_gate` are all nestable, so they become legal callout children. Today a gate inside a callout resolves to `.slide` (never `null` — `_lesson_article.html:35-36` wraps **every** lesson's elements in `<div class="slide">`), so `gateWrap.hidden = true` hides the **entire callout** and the cascade marks every following lesson-block revealed.

**Files:**
- Modify: `courses/static/courses/js/reveal.js:51-52` (`scopeOf`), `:41-50` and `:68-78` (comments)
- Modify: `templates/courses/lesson_unit.html:39-41` (4th pre-hide selector)
- Modify: `core/static/core/css/app.css:1001-1005` (`@media print` revert — add **both** `.callout__children` and the already-missing `.spoiler__children`)
- Test: `courses/tests/test_reveal_scope_agreement.py` (create)

**Interfaces:** none importable.

- [ ] **Step 1: Write the failing agreement test**

`courses/tests/test_reveal_scope_agreement.py`:

```python
"""The four cascade scopes must agree across THREE files.

This test must EXTRACT each block before scanning, or it is green under its own
mutant: `.spoiler__children` also occurs at app.css:987 (the shared rule) OUTSIDE
the print block, so a file-wide scan stays green when it is missing from the print
revert -- which is the state that file is in today.
"""

import re
from pathlib import Path

SCOPES = ("[data-tab-panel]", ".slide", ".spoiler__children", ".callout__children")


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _print_block(css):
    m = re.search(r"@media print\s*\{(.*?)\n\}", css, re.S)
    assert m, "no @media print block in app.css"
    return m.group(1)


def _prehide_block(html):
    m = re.search(r"has_reveal_gate %\}(.*?)\{% endif %\}", html, re.S)
    assert m, "no has_reveal_gate style block in lesson_unit.html"
    return m.group(1)


def _scope_of(js):
    m = re.search(r"function scopeOf\(btn\)\s*\{(.*?)\}", js, re.S)
    assert m, "no scopeOf in reveal.js"
    return m.group(1)


def _has_scope(block, scope):
    """`.spoiler` is a substring of `.spoiler__children`, so match on a boundary."""
    return re.search(re.escape(scope) + r"(?![\w-])", block) is not None


def test_all_four_scopes_are_in_scope_of():
    scope_of = _scope_of(_read("courses/static/courses/js/reveal.js"))
    for s in SCOPES:
        assert _has_scope(scope_of, s), f"{s} missing from scopeOf"
    # scopeOf carries a FIFTH selector: `.spoiler` is a deliberate legacy fallback
    # for the body-only shape and is intentionally absent from both CSS blocks. So
    # scopeOf is asserted by CONTAINMENT, the CSS blocks by exact-four.
    assert _has_scope(scope_of, ".spoiler")


def test_all_four_scopes_are_in_the_prehide_block():
    block = _prehide_block(_read("templates/courses/lesson_unit.html"))
    for s in SCOPES:
        assert _has_scope(block, s), f"{s} missing from the pre-hide CSS"


def test_all_four_scopes_are_in_the_print_revert():
    block = _print_block(_read("core/static/core/css/app.css"))
    for s in SCOPES:
        assert _has_scope(block, s), f"{s} missing from the @media print revert"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_reveal_scope_agreement.py --verbosity=0`
Expected: FAIL — `.callout__children` missing from all three; `.spoiler__children` missing from the print revert.

- [ ] **Step 3: Update `scopeOf`**

`courses/static/courses/js/reveal.js:51-52`:

```javascript
  function scopeOf(btn) {
    return btn.closest("[data-tab-panel], .slide, .spoiler__children, .callout__children, .spoiler");
  }
```

(Order within the list is cosmetic — `closest()` returns the nearest matching ancestor regardless.) Update the comments at `:41-50` and `:68-78` — the latter says "Three scopes exist" and there are now four, with `.callout__child` a third member of the direct-child family.

- [ ] **Step 4: Add the 4th pre-hide selector**

`templates/courses/lesson_unit.html:39-41`:

```css
    .reveal-armed .callout__children > .callout__child:has(> [data-reveal-gate]) ~ .callout__child:not(.reveal-shown),
```

- [ ] **Step 5: Fix the print revert (both scopes)**

`core/static/core/css/app.css:1001-1005`:

```css
@media print {
  .reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block,
  .reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child,
  .reveal-armed .spoiler__children > .spoiler__child:has(> [data-reveal-gate]) ~ .spoiler__child,
  .reveal-armed .callout__children > .callout__child:has(> [data-reveal-gate]) ~ .callout__child {
    display: revert !important;
  }
```

`.spoiler__children` was already missing — #212 shipped that gap, and adding a pre-hide selector without a print revert means permanent content loss in print/PDF.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_reveal_scope_agreement.py courses/tests/test_reveal_gate_render.py --verbosity=0`
Expected: PASS.

- [ ] **Step 7: Falsify (two mutants)**

1. Delete the `.spoiler__children` line from the `@media print` block only → `test_all_four_scopes_are_in_the_print_revert` RED. **This is the mutant a file-wide scan would survive.**
2. Delete `.callout__children` from `scopeOf` → `test_all_four_scopes_are_in_scope_of` RED.

Revert both.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/reveal.js templates/courses/lesson_unit.html core/static/core/css/app.css courses/tests/test_reveal_scope_agreement.py
git commit -m "fix(reveal): callout is a cascade scope in all three scope lists"
```

---

### Task 13: math.js heading selector + render-seam matrix + e2e

**Files:**
- Modify: `courses/static/courses/js/math.js:31`
- Modify: `courses/tests/test_render_seam.py:25-36`, `:178-208`
- Test: `tests/test_e2e_callout_container.py` (create)

**Interfaces:** none importable.

- [ ] **Step 1: Add `.callout__heading` to `renderInlineText`**

`courses/static/courses/js/math.js:31` — append to the selector list:

```javascript
    (root || document).querySelectorAll(".el--text, .el--table, .el--gallery, .el--tabs, .fillgate, .stepper, .markdone, .guessnumber, .spoiler__toggle, .callout__heading").forEach(function (el) {
```

(The callout *body* already typesets because `.callout__body` carries `el--text`; the heading is a `<span>` outside that div and matches nothing in the list.)

- [ ] **Step 1b: Pin the math.js selector list**

`math.js`'s `renderInlineText` list is an identically literal, identically drift-prone
enumeration to the three reveal scope lists — and the spec's mutant ("remove
`.callout__heading` from `math.js`") is otherwise killed only by the e2e. Add
`courses/tests/test_math_selectors.py`:

```python
"""renderInlineText's selector list must include every typeset region.

EXTRACT the function first: `.callout__heading` also appears in courses.css, and a
file-wide scan of the wrong file would be vacuous.
"""

import re
from pathlib import Path


def _render_inline_text_selectors():
    js = Path("courses/static/courses/js/math.js").read_text(encoding="utf-8")
    fn = re.search(r"function renderInlineText\(root\)\s*\{(.*?)\n  \}", js, re.S)
    assert fn, "renderInlineText not found in math.js"
    sel = re.search(r"querySelectorAll\(\s*"([^"]+)"", fn.group(1))
    assert sel, "no querySelectorAll selector string in renderInlineText"
    return sel.group(1)


def test_every_typeset_region_is_in_the_selector_list():
    sel = _render_inline_text_selectors()
    for region in (".el--text", ".spoiler__toggle", ".callout__heading"):
        assert region in sel, f"{region} missing from renderInlineText"
```

Run: `uv run pytest courses/tests/test_math_selectors.py --verbosity=0` — expected PASS
after Step 1. Falsify: remove `.callout__heading` from `math.js` → RED.

- [ ] **Step 2: Extend the render-seam matrix**

`courses/tests/test_render_seam.py` — first add the two missing model imports to the
existing alphabetical block at `:3-14`; neither is currently imported, so the snippets
below would `NameError` at collection:

```python
from courses.models import CalloutElement
from courses.models import SpoilerElement
```

Then add both currently-absent concretes to `CONCRETES`:

```python
    (SpoilerElement, {}),
    (CalloutElement, {}),
```

`:180` — add both placements:

```python
@pytest.mark.parametrize("placement", ["top", "tabs", "twocolumn", "callout", "spoiler"])
```

**The ids alone are worse than useless**: the dispatch ends in `else:` = the two-column branch, so a new id with no branch silently builds a `TwoColumnElement` parent and passes. Add explicit branches before the `else`:

```python
    elif placement == "callout":
        parent_obj = CalloutElement.objects.create(kind="example")
        parent = add_element(unit, parent_obj)
        Element.objects.create(
            unit=unit, content_object=obj, parent=parent,
            tab_id=CalloutElement.SLOT_ID,
        )
    elif placement == "spoiler":
        parent_obj = SpoilerElement.objects.create(label="s")
        parent = add_element(unit, parent_obj)
        Element.objects.create(
            unit=unit, content_object=obj, parent=parent,
            tab_id=SpoilerElement.SLOT_ID,
        )
```

and, so both new ids are provably distinguishable from the fallthrough, assert the marker at the end of the test:

```python
    if placement == "callout":
        assert "callout__children" in resp.content.decode()
    if placement == "spoiler":
        assert "spoiler__children" in resp.content.decode()
```

- [ ] **Step 3: Write the e2e**

`tests/test_e2e_callout_container.py` — computed style and cascade behaviour cannot be
seen by a Django render test. Login/seed helpers are copied from
`tests/test_e2e_depth3.py:58-101` (`_make_pa_user`, `_login`, `_editor_url`,
`_lesson_url`, plus `CourseFactory`/`ContentNodeFactory`), **not invented**. Existing
e2e modules set `pytestmark = pytest.mark.e2e` only — `live_server` already pulls in
`transactional_db`, so do NOT add `django_db`.

```python
"""e2e for the seams a render test is byte-identical across.

MANDATORY, not preferred: the server emits no computed style, and a CSS-cascade defect
leaves the rendered HTML unchanged. These four tests are the ONLY pin for the combined
spoiler rule (Task 11), the prose-cap narrowing, the heading katex reset, and the
reveal cascade inside a callout.
"""

import os

import pytest

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element

pytestmark = pytest.mark.e2e

MARKER = "CALLOUT-E2E-9f3a"


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# Copy _make_pa_user / _login / _editor_url / _lesson_url VERBATIM from
# tests/test_e2e_depth3.py:58-101 -- same PA-user helper, same login form drive.


def _seed_unit(username):
    user = _make_pa_user(username)
    course = CourseFactory(owner=user)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    return user, course, unit


def test_spoiler_body_and_children_show_one_continuous_rule(page, live_server):
    """MUST open the <details> first: a closed one is not rendered, so BOTH rects come
    back all-zeros and `equal left` (0==0) / `zero gap` (0-0) hold WITH and WITHOUT the
    fix -- green under the named mutant. On the BROKEN build the two `left` values
    differ by var(--space-3) and the gap is non-zero; check that before trusting green.
    """
    from courses.models import Element, SpoilerElement, TextElement

    user, _course, unit = _seed_unit("pa_rule")
    sp = SpoilerElement.objects.create(label="Reveal", body="<p>BODY</p>")
    join = add_element(unit, sp)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=f"<p>{MARKER}</p>"),
        parent=join,
        tab_id=SpoilerElement.SLOT_ID,
    )
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.eval_on_selector("details.spoiler", "d => { d.open = true; }")
    page.wait_for_selector(".spoiler__body", state="visible")
    page.wait_for_selector(".spoiler__children", state="visible")
    body = page.locator(".spoiler__body").bounding_box()
    kids = page.locator(".spoiler__children").bounding_box()
    assert abs(body["x"] - kids["x"]) < 1, "rules sit at different left offsets"
    gap = kids["y"] - (body["y"] + body["height"])
    assert abs(gap) < 1, f"vertical gap between the two rules: {gap}px"


def test_a_table_in_a_callout_is_not_squeezed_by_the_prose_cap(page, live_server):
    """The cap is `html.unit-tree-collapsed [data-unit-shell] ...` under
    `@media screen and (min-width: 641px)`, and that class is set by the TOC-pin JS
    from localStorage -- NEVER by the server. Without seeding it, both arms measure
    the uncapped state and the assertion is vacuous.

    641px is NOT enough either: the collapsed content box is
    min(viewport, 72rem) - 2.4rem (pin lane) - 3rem (.lesson padding), i.e. ~555px at
    641px -- under 46rem (736px), so the cap never binds. Use 1280x900.
    """
    from courses.models import CalloutElement, Element, TableElement

    user, _course, unit = _seed_unit("pa_cap")
    prose = CalloutElement.objects.create(kind="note", body="<p>prose only</p>")
    add_element(unit, prose)
    wide = CalloutElement.objects.create(kind="example")
    wide_join = add_element(unit, wide)
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": [[{"html": "A"}, {"html": "B"}]]}
        ),
        parent=wide_join,
        tab_id=CalloutElement.SLOT_ID,
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    _login(page, live_server, user.username)
    # Seed the collapsed state BEFORE first paint. Grep `unit-tree-collapsed` under
    # courses/static/courses/js/ for the exact localStorage key the TOC pin reads and
    # use it verbatim -- a wrong key silently leaves the page uncollapsed.
    page.add_init_script("localStorage.setItem('<TOC_KEY>', '1');")
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("html.unit-tree-collapsed")
    # CONTROL ARM first: proves the cap is live before the negative arm is trusted.
    prose_box = page.locator(".callout:not(:has(> .callout__children))").bounding_box()
    assert abs(prose_box["width"] - 736) < 2, (
        f"control: a prose-only callout must stay capped at 46rem, got {prose_box['width']}"
    )
    wide_box = page.locator(".callout:has(> .callout__children)").bounding_box()
    assert wide_box["width"] > 736, (
        f"a callout with children must not inherit the cap, got {wide_box['width']}"
    )


def test_callout_heading_math_is_not_uppercased_or_letter_spaced(page, live_server):
    """Assert what actually CHANGES under the defect. `text-transform` is paint-time
    and never alters textContent, so a textContent assertion is green either way. The
    sample is superscript-free so `.mord` selection is unambiguous (KaTeX emits
    `.mord.mtight` at ~0.7em for a superscript).
    """
    from courses.models import CalloutElement

    user, _course, unit = _seed_unit("pa_head")
    co = CalloutElement.objects.create(
        kind="tip", heading=r"Wzor \(a\cdot b\)", body="<p>x</p>"
    )
    add_element(unit, co)
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".callout__heading .katex")
    mord = page.locator(".callout__heading .katex-html .mord").first
    style = mord.evaluate(
        "e => { const c = getComputedStyle(e);"
        " return {t: c.textTransform, l: c.letterSpacing, f: parseFloat(c.fontSize)}; }"
    )
    assert style["t"] == "none", f"heading math is being uppercased: {style['t']}"
    assert style["l"] in ("normal", "0px"), f"heading math is letter-spaced: {style['l']}"
    head_size = page.locator(".callout__heading").evaluate(
        "e => parseFloat(getComputedStyle(e).fontSize)"
    )
    assert abs(style["f"] - head_size) < 1, (
        f"math {style['f']}px vs label {head_size}px -- KaTeX's 1.21em default leaked"
    )


def test_a_gate_in_a_callout_cascades_without_hiding_the_callout(page, live_server):
    """Pre-fix, scopeOf resolved to `.slide` (emitted in EVERY lesson, not just a
    slideshow), so `gateWrap.hidden = true` hid the WHOLE callout and the cascade,
    finding no stopping point, marked every following top-level .lesson-block
    .reveal-shown. Do NOT assert "the button did nothing" -- that is green under the
    defect and RED under the fix.
    """
    from courses.models import CalloutElement, Element, RevealGateElement, TextElement

    user, _course, unit = _seed_unit("pa_gate")
    co = CalloutElement.objects.create(kind="example")
    join = add_element(unit, co)
    Element.objects.create(
        unit=unit,
        content_object=RevealGateElement.objects.create(label="Show more"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
        order=0,
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=f"<p>{MARKER}</p>"),
        parent=join,
        tab_id=CalloutElement.SLOT_ID,
        order=1,
    )
    # A sibling OUTSIDE the callout: the cascade must not sweep it.
    add_element(unit, TextElement.objects.create(body="<p>OUTSIDE-SIBLING</p>"))

    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    # (a) gated content hidden BEFORE the click -- what the 4th pre-hide selector buys
    assert not page.locator(f"text={MARKER}").is_visible(), "gated content leaked pre-click"
    page.click(".callout__children [data-reveal-gate]")
    page.wait_for_selector(f"text={MARKER}", state="visible")
    # (b) the callout itself survives the cascade
    assert page.locator(".callout").is_visible(), "the callout itself vanished"
    # (c) the cascade did not escape to a top-level sibling
    outside = page.locator(".lesson-block:has-text('OUTSIDE-SIBLING')")
    assert "reveal-shown" not in (outside.get_attribute("class") or ""), (
        "the cascade escaped the callout and swept a top-level sibling"
    )
```

Replace `<TOC_KEY>` with the real localStorage key before running.

- [ ] **Step 4: Run tests**

Run: `uv run pytest courses/tests/test_render_seam.py --verbosity=0`
Run: `uv run pytest tests/test_e2e_callout_container.py -m e2e --verbosity=0`
Expected: PASS.

- [ ] **Step 5: Falsify**

Remove the two new `elif` branches from `test_render_seam.py` (keep the ids). Expected: the `callout__children` / `spoiler__children` assertions RED. Restore.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math.js courses/tests/test_render_seam.py tests/test_e2e_callout_container.py
git commit -m "feat(callout): typeset the heading; extend the render-seam matrix; e2e"
```

---

### Task 14: Comment sweep, help docs, catalogs

**Files:**
- Modify: the comment sites listed below
- Modify: `docs/help/course-admin/content-editors{,.pl}.md`, `docs/help/course-admin/interactive-elements{,.pl}.md`
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 0: The client-enhancer audit (the PR #209 lesson)**

The spec requires this and no other task schedules it. The render-seam matrix (Task 13)
is the *mechanical backbone* — it proves a 200 — but cannot see computed style or
cascade behaviour, which is exactly what #209 shipped broken.

```bash
rg -n "querySelectorAll|closest\(|\.matches\(" courses/static/courses/js/
```

For every hit, check whether the selector is scoped to its own element root. Then check
each newly-legal combination against it: `reveal_gate`, `fill_gate`, `switch_gate`,
`stepper`, `mark_done` nested **inside a callout**, and `callout` nested inside each of
{`tabs`, `two_column`, `spoiler`, `callout`}. `tabs.js` is already
`closest("[data-tabs]")`-scoped and `.callout` has no JS of its own, so the risk is a
nested enhancer's descendant-wide query absorbing callout markup.

Record what you checked, and anything found, in the commit message. If the audit finds a
defect, it gets its own test before the fix.

- [ ] **Step 1: Sweep the falsified comments**

At minimum these (several were already updated in earlier tasks — verify each):

| Site | False claim |
|---|---|
| `_add_menu.html:12-17` | container list at `:12-13`; "Callout is a plain LEAF" at `:16-17` |
| `payloads.py:750-752`, `:779-781` | two distinct "the only valid id is `SpoilerElement.SLOT_ID`" claims |
| `builder.py:27-31` | the PR2 to-do — now done |
| `views.py` `_spoiler_has_math` docstring | "A nested spoiler has an empty body" |
| `models.py:399-401` | "either … OR" |
| `spoilerelement.html:8-24` | the mutually-exclusive-shapes comment |
| `app.css:978-985` | "Two shapes get the SAME treatment"; "measured 154px" |
| `export.py:560-562`, `:660-663` | "tabs, two_column, spoiler" |
| `reveal.js:41-50`, `:68-78` | three-scope enumerations |
| `tests/test_editor_depth.py:161` | "three sites -- tabs, two-column and spoiler" |

Then grep for stragglers:

```bash
rg -n "tabs.*two_column.*spoiler|Tabs, Columns,? and Spoiler"
rg -ni "three scopes|three container types"
```

- [ ] **Step 2: Update the help docs — pair each English edit with its Polish twin**

**Pairing, not grepping, is the discovery rule.** `rg -ni "kontener" docs/help` misses two required Polish anchors entirely.

| English | Polish twin | Change |
|---|---|---|
| `content-editors.md:95` | `content-editors.pl.md:103` | Callout is no longer only a leaf |
| `content-editors.md:123` | `content-editors.pl.md:133-134` | "three container types" → four |
| `content-editors.md:130-133` | `content-editors.pl.md:141-144` | Callout moves into the depth-guarded list |
| `content-editors.md:140-142` | `content-editors.pl.md:151-153` — **verify the exact line**, the offset drifts | the quiz add-menu paragraph |
| `interactive-elements.md:11-12` | `interactive-elements.pl.md:11-14` | "three container types" → four |
| `interactive-elements.md:74-85` | `interactive-elements.pl.md:85` | Spoiler now renders body **and** children |

State explicitly that a callout consumes a nesting level (D3). Check for a matching help screenshot.

- [ ] **Step 3: Regenerate the catalogs**

The spoiler reword is a **deletion plus an addition** — the old "This spoiler shows saved text (edit it with the pencil). Add an element below to start nesting content." must go from both catalogs:

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

Translate the three new/changed msgids. Delete any `#, fuzzy` marker **and** its `#| msgid` line — `msgmerge` reliably pre-fills a wrong Polish translation here.

- [ ] **Step 4: Full verification**

```bash
uv run ruff check . && uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
uv run pytest --verbosity=0
uv run pytest -m e2e --verbosity=0
```

Expected: all green. Record the pass counts.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs(callout): update author manuals, comments and catalogs"
```

---

## Self-Review

**Spec coverage.** Change-set rows 1–16 map to tasks: 1→T3, 2→T1/T3, 3→T5, 4→T9, 5→T12, 6→T13, 7→T10, 8→T14, 9→T1/T2, 10→T2, 11→T7, 12→T7, 13→T6, 14→T9, 15→T10, 16→T8. Decisions D1→T2/T7, D2→T2, D3→T4, D3a→T4, D4→T3, D5 (one branch) is the plan itself. Every "Cases to pin" row has a task: registry drift→T3, export/duplicate→T5, has_math (4 rows)→T6, editor row (2 rows)→T9, depth+D3a→T4, slot literal→T1, print revert (2 rows)→T12, heading math→T13, prose cap→T13, combined rule→T13, migration (3 rows)→T8, body order→T7, form body→T7.

**Placeholders.** Two remain, both flagged inline at their use site rather than left as
"TBD": Task 8's `_MIGRATION_PREFIX`, filled from the `makemigrations --empty` output, and
Task 13's `<TOC_KEY>` localStorage key, read from the TOC-pin JS. Task 13's e2e bodies are
fully written — seeding, login, navigation and assertions — reusing
`tests/test_e2e_depth3.py:58-101`'s helpers verbatim; an earlier draft elided them, which
was wrong, since those four tests are the ONLY pin for Task 11's combined-shape CSS, the
prose-cap narrowing, the heading katex reset and the callout reveal cascade.

**Type consistency.** `SINGLE_SLOT_ID` (T1) → `CalloutElement.SLOT_ID` (T2) → `resolve_scope(…, CalloutElement.SLOT_ID, …)` (T3) → `emit(child, join, CalloutElement.SLOT_ID)` (T5) → `tab=obj.SLOT_ID` (T9): one name throughout. `resolved_children()` and `join_row()` match `SpoilerElement`'s existing signatures. `_callout_has_math(el) -> bool` matches its siblings.
