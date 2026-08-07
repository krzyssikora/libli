# Before / after element — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth container element — two fixed child slots ("before" / "after"), one toggle button that swaps between them, a spoiler-style left rule on the visible panel, and no persisted state.

**Architecture:** A `BeforeAfterElement` concrete whose two slots are **class constants, not persisted data**, so there is nothing to normalize. Children live in `Element` join rows keyed by `tab_id`, the same substrate Tabs/Spoiler/Callout use. The "after" side is hidden **before first paint** by a render-blocking pre-hide armed from an inline prepaint script, then handed over to the `hidden` attribute by a ~90-line client module. Recovery from any client failure is explicit and two-scoped.

**Tech Stack:** Django 5 templates + ORM, vanilla ES5-style IIFE JS (no build step), token-driven CSS, pytest + pytest-django + Playwright, `uv` for tooling.

**Spec:** `docs/superpowers/specs/2026-08-07-before-after-element-design.md` (1290 lines, 6 review rounds, 116 catches applied). Where this plan and the spec disagree, **the spec wins** — but they should not disagree; report it instead of guessing.

## Global Constraints

- **Slot ids are constants.** In Python and templates, always `BeforeAfterElement.SLOT_IDS` / `.BEFORE_SLOT_ID` / `.AFTER_SLOT_ID`. **Never** a `"before"` / `"after"` string literal. CSS is the sole exception (it cannot reference Python); Task 12 adds a guard test pinning the two together.
- **`FORMAT_VERSION` stays 9.** Do not bump it. A new element type has never bumped it (`callout` = `c10994bc`, `guess_number` = `f962a4a5`).
- **Transfer key** `before_after`; **element-form key** `beforeafter`; **model** `BeforeAfterElement`; **content-type model string** `beforeafterelement`. These four namespaces are all different and all load-bearing.
- **No `display` declaration** on `.ba__panel` / `.ba__child` in the element's base CSS block. State-scoped blocks (armed pre-hide, `html:not(.ba-js)`, `.ba--dead`, `@media print`) are the stated exceptions.
- **Start the test DB before any pytest run:** `docker compose -p libli-test -f docker-compose.test.yml up -d --wait`. If it is down the suite looks hung for ~4m21s before erroring.
- **All tooling is behind `uv run`.** `ruff`, `pytest` and `python` are not on PATH.
- **e2e files need `-m e2e`** or every test silently deselects and pytest exits 5.
- **Scope every test run narrowly** (`-k` / a single file). Whole-repo sweeps are a branch gate, not a task step.
- **Never** run two pytest invocations at once — the test DB container is shared across worktrees.
- Work in the worktree `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/before-after-element` on branch `pipeline/before-after-element`.
- Every task ends with a commit. Commit messages: `feat(before-after): …` / `test(before-after): …` / `docs(before-after): …`.

**Execution order: 1 → 2 → 3 → 4 → 5 → 4a → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15.**

Note **4a runs after 5**, not after 4: it is written out-of-sequence at the end of this
document (the self-review added it late) and it creates its own test file, so it has no
dependency on Task 5 — but grouping it with the other `views.py` context work is cheaper.

**Two commits are knowingly RED**, and they are the only ones:

| Task | Red test | Goes green at |
| --- | --- | --- |
| 1 | `test_render_seam.py` (template does not exist yet) | Task 2 Step 6 |
| 3 | `test_nestable_keys_are_a_subset_of_serializers` (no `SERIALIZERS` entry yet) | Task 4 Step 3 |

Everywhere else, "Expected: PASS" means the whole named selection passes. Do not treat
these two as licence to leave anything else red.

## File Structure

**Created**

| Path | Responsibility |
| --- | --- |
| `templates/courses/elements/beforeafterelement.html` | Student-facing render: toggle button + two panels |
| `templates/courses/manage/editor/_edit_beforeafter.html` | The open edit form (the `button_label` input only) |
| `courses/static/courses/js/beforeafter.js` | Client toggle, boot flag, per-instance recovery |
| `courses/migrations/0055_beforeafterelement_alter_element_content_type.py` | Schema |
| `courses/tests/test_beforeafter_model.py` | `resolved_slots()`, re-homing, `eid` |
| `courses/tests/test_beforeafter_nesting.py` | The five containment seams |
| `courses/tests/test_beforeafter_transfer.py` | Serializer / validator / builder / walker round-trip |
| `courses/tests/test_beforeafter_css.py` | Base-block display invariant, print rules, slot-id guard |
| `courses/tests/test_beforeafter_context.py` | `has_before_after` in lesson + quiz |
| `courses/tests/test_beforeafter_authoring.py` | End-to-end editor authoring of `button_label` |
| `tests/test_e2e_before_after.py` | Toggle, pre-hide, boot guard, per-instance failure, reveal |

**Modified** — `courses/models.py`, `courses/builder.py`, `courses/views.py`, `courses/views_manage.py`, `courses/element_forms.py`, `courses/templatetags/courses_manage_extras.py`, `courses/transfer/{export,payloads,importer}.py`, `courses/static/courses/js/{reveal.js,editor.js}`, `courses/static/courses/css/{courses.css,editor.css}`, `core/static/core/css/app.css`, `core/help.py`, `templates/courses/{lesson_unit,quiz_unit}.html`, `templates/courses/manage/editor/{_element_row,_add_menu,editor}.html`, `templates/courses/manage/_icon_sprite.html`, `docs/help/course-admin/content-editors{,.pl}.md`, `locale/{en,pl}/LC_MESSAGES/django.po`, and the existing tests named in Tasks 1, 10 and 11.

---

## Task 1: Model, `ELEMENT_MODELS`, migration

**Files:**
- Modify: `courses/models.py` (new concrete after `CalloutElement`; `ELEMENT_MODELS` at `:261`)
- Create: `courses/migrations/0055_beforeafterelement_alter_element_content_type.py`
- Create: `courses/tests/test_beforeafter_model.py`
- Modify: `tests/test_transfer_schema.py:10-11`, `tests/test_guessnumber_model.py:11`, `tests/test_models_multigrid.py:11`
- Modify: `courses/tests/test_render_seam.py:27` (`CONCRETES`), `:184-186` (`placement`)

**Interfaces:**
- Produces: `BeforeAfterElement` with `BEFORE_SLOT_ID = "before"`, `AFTER_SLOT_ID = "after"`, `SLOT_IDS = (BEFORE_SLOT_ID, AFTER_SLOT_ID)`, `button_label: CharField(max_length=120, blank=True)`, `elements: GenericRelation`, `join_row()`, `resolved_slots() -> list[tuple[str, list[Element]]]`, `render(*, element=None, state=None, slug=None, node_pk=None)`.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_beforeafter_model.py`:

```python
import pytest

from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit

# NOTE the path: `tests.factories`, NOT `courses.tests.factories` (which does not
# exist). Every file under courses/tests/ imports it this way.


def _ba(unit, label=""):
    obj = BeforeAfterElement.objects.create(button_label=label)
    return Element.objects.create(unit=unit, content_object=obj), obj


def _child(unit, parent, tab, body="x"):
    return Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=body),
        parent=parent,
        tab_id=tab,
    )


@pytest.mark.django_db
def test_resolved_slots_returns_pairs_in_slot_ids_order():
    """Pairs, not a bare tuple: the editor row template needs the slot id to pass
    as tab= to the add-menu include and to {% paste_buttons %}.

    Mutant: return a 2-tuple of lists -> unpacking `for slot_id, children` fails.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    _child(unit, join, BeforeAfterElement.AFTER_SLOT_ID, "A")
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID, "B")

    slots = obj.resolved_slots()
    assert [sid for sid, _ in slots] == list(BeforeAfterElement.SLOT_IDS)
    assert [c.content_object.body for c in slots[0][1]] == ["B"]
    assert [c.content_object.body for c in slots[1][1]] == ["A"]


@pytest.mark.django_db
def test_unknown_tab_id_is_rehomed_into_before_not_dropped():
    """TwoColumnElement.resolved_columns ends `by_col.get(col["id"], [])`, which
    DROPS a child whose tab_id matches no slot. Copying it verbatim here would
    make authored content invisible.

    Mutant: `by_slot.get(sid, [])` with no fallback -> the stray child vanishes.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID, "keep")
    _child(unit, join, "bogus-slot", "stray")

    before = obj.resolved_slots()[0][1]
    assert [c.content_object.body for c in before] == ["keep", "stray"]


@pytest.mark.django_db
def test_both_slots_come_from_one_children_queryset():
    """One queryset filtered on parent_id with NO tab_id predicate, partitioned in
    Python. (Total query count is >1 -- join_row() is its own query and
    prefetch_related issues one per distinct child content type -- so the
    invariant is the SHAPE of the children query, not a count.)

    Mutant: call the queryset once per slot -> two parent_id queries.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID)
    _child(unit, join, BeforeAfterElement.AFTER_SLOT_ID)

    with CaptureQueriesContext(connection) as ctx:
        obj.resolved_slots()
    # Match on the WHERE clause, NOT the whole SQL string: every SELECT over
    # courses_element names "parent_id" and "tab_id" in its COLUMN LIST, so a
    # substring scan would count join_row()'s own query too and would find
    # "tab_id" in a query that does not filter on it.
    wheres = [q["sql"].split("WHERE", 1)[-1] for q in ctx.captured_queries if "WHERE" in q["sql"]]
    parent_filters = [w for w in wheres if '"parent_id" =' in w]
    assert len(parent_filters) == 1
    assert '"tab_id" =' not in parent_filters[0]


@pytest.mark.django_db
def test_transient_join_row_returns_empty_pairs():
    """The pairs are always present; only their child lists are empty."""
    obj = BeforeAfterElement.objects.create()
    assert obj.resolved_slots() == [
        (BeforeAfterElement.BEFORE_SLOT_ID, []),
        (BeforeAfterElement.AFTER_SLOT_ID, []),
    ]


def test_element_models_includes_before_after():
    """limit_choices_to on Element.content_type is fed by this list."""
    from courses.models import ELEMENT_MODELS

    assert "beforeafterelement" in ELEMENT_MODELS
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run pytest courses/tests/test_beforeafter_model.py -v
```
Expected: FAIL — `ImportError: cannot import name 'BeforeAfterElement'`.

- [ ] **Step 3: Add the model**

In `courses/models.py`, immediately after `CalloutElement`:

```python
class BeforeAfterElement(ElementBase):
    """Two fixed child slots the student swaps between with one button.

    The slots are CLASS CONSTANTS, not persisted data, so unlike TabsElement /
    TwoColumnElement there is nothing to normalize: no id minting, no truncation,
    and no way for the stored slot set to drift from what the code expects.
    Children live in Element rows whose `parent` is this element's join row and
    whose `tab_id` is one of SLOT_IDS.
    """

    BEFORE_SLOT_ID = "before"
    AFTER_SLOT_ID = "after"
    SLOT_IDS = (BEFORE_SLOT_ID, AFTER_SLOT_ID)  # order is the contract

    button_label = models.CharField(max_length=120, blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join row

    def join_row(self):
        """This concrete's single Element join row (the GFK is effectively 1:1)."""
        return self.elements.order_by("pk").first()

    def resolved_slots(self):
        """[(slot_id, children), ...] in SLOT_IDS order.

        ONE children queryset for both slots, partitioned in Python -- not one
        queryset per slot. A child whose tab_id is not in SLOT_IDS is APPENDED to
        the before bucket rather than dropped: TwoColumnElement.resolved_columns
        drops (`by_col.get(...)`), which would make authored content invisible.
        """
        join = self.join_row()
        if join is None:
            return [(sid, []) for sid in self.SLOT_IDS]
        rows = list(
            join.children.order_by("order", "pk")
            .select_related("content_type")
            .prefetch_related("content_object")
        )
        by_slot = {sid: [] for sid in self.SLOT_IDS}
        strays = []
        for row in rows:
            if row.tab_id in by_slot:
                by_slot[row.tab_id].append(row)
            else:
                strays.append(row)
        by_slot[self.BEFORE_SLOT_ID].extend(strays)
        return [(sid, by_slot[sid]) for sid in self.SLOT_IDS]

    def render(self, *, element=None, state=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        # `element.pk`, NOT node_pk: node_pk is the UNIT's pk (views.py:491), the
        # same for every element on the page, so keying DOM ids off it would make
        # one element's button control another's panels. `element` is None only in
        # direct render() calls (courses_extras.render_element always supplies it),
        # i.e. test_render_seam's CONCRETES loop -- so the 0 fallback cannot
        # collide on a served page.
        return render_to_string(
            "courses/elements/beforeafterelement.html",
            {
                "el": self,
                "eid": element.pk if element is not None else 0,
                "slots": self.resolved_slots(),
                # `element_state`, NOT `state`: courses_extras.render_element
                # reads that name.
                "element_state": state,
                "slug": slug,
                "node_pk": node_pk,
            },
        )
```

Append to `ELEMENT_MODELS` (`courses/models.py:261`), keeping the list's existing order convention:

```python
    "beforeafterelement",
```

- [ ] **Step 4: Generate the migration**

```bash
uv run python manage.py makemigrations courses
```
Expected: creates `0055_beforeafterelement_alter_element_content_type.py` with **two** operations — `CreateModel` and `AlterField` on `element.content_type`. The second appears **only because** `ELEMENT_MODELS` changed (it feeds `limit_choices_to`); if you see only `CreateModel`, the list edit is missing.

Verify no other app has pending changes:
```bash
uv run python manage.py makemigrations --check --dry-run
```

- [ ] **Step 5: Run the model tests**

```bash
uv run pytest courses/tests/test_beforeafter_model.py -v
```
Expected: PASS (5 tests). The template does not exist yet, so do **not** call `render()` here.

- [ ] **Step 6: Update the three count assertions that this breaks**

These live in files with no visible relationship to this feature; without this step the suite is red from here on.

- `tests/test_transfer_schema.py:10-11` — rename `test_element_models_lists_all_31_concrete_element_models` → `..._32_...` and change `31` → `32`.
- `tests/test_guessnumber_model.py:11` — `31` → `32`.
- `tests/test_models_multigrid.py:11` — `31` → `32`.

- [ ] **Step 7: Extend the render-seam guards**

`courses/tests/test_render_seam.py` carries **two** guards. Add to `CONCRETES` (`:27`):

```python
    (BeforeAfterElement, {}),
```

and to the `placement` parametrize list (`:184-186`):

```python
@pytest.mark.parametrize(
    "placement", ["top", "tabs", "twocolumn", "callout", "spoiler", "beforeafter"]
)
```

Add `from courses.models import BeforeAfterElement` to that file's imports — both the `CONCRETES` entry and the `parametrize` need it.

The placement fixture is an `elif placement == …` ladder inside `test_lesson_renders_200_with_each_concrete` (`:195` onward). Add a branch mirroring the `callout` one:

```python
    elif placement == "beforeafter":
        host = BeforeAfterElement.objects.create()
        host_join = Element.objects.create(unit=unit, content_object=host)
        Element.objects.create(
            unit=unit,
            content_object=obj,
            parent=host_join,
            # BEFORE_SLOT_ID, not a literal: a wrong id would be MASKED by
            # resolved_slots()' re-homing rule and the test would pass vacuously.
            tab_id=BeforeAfterElement.BEFORE_SLOT_ID,
        )
```

Read the `callout` branch first and match its exact local names — the sketch above uses `unit`/`obj`, which may differ.

**This step is expected RED until Task 2 creates the template.** Do not run it here; run it at Task 2 Step 6. Task 1's commit therefore contains a knowingly-red test — an explicit, bounded exception to "every task ends with a green commit", closed one task later.

- [ ] **Step 8: Run the count tests**

```bash
uv run pytest tests/test_transfer_schema.py tests/test_guessnumber_model.py tests/test_models_multigrid.py -v
```
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add courses/models.py courses/migrations/0055_*.py courses/tests/test_beforeafter_model.py \
        tests/test_transfer_schema.py tests/test_guessnumber_model.py tests/test_models_multigrid.py \
        courses/tests/test_render_seam.py
git commit -m "feat(before-after): model, ELEMENT_MODELS entry and migration"
```

---

## Task 2: Student template and base CSS

**Files:**
- Create: `templates/courses/elements/beforeafterelement.html`
- Modify: `courses/static/courses/css/courses.css` (new base block)
- Modify: `courses/tests/test_render_seam.py` (finish Task 1 Step 7)

**Interfaces:**
- Consumes: `BeforeAfterElement.resolved_slots()`, the `eid`/`slots` context from Task 1.
- Produces: DOM contract `[data-beforeafter]` > `.ba__panels#ba-<eid>-panels` > `.ba__panel[data-ba-side]` > `.ba__child`; button `.ba__toggle[aria-pressed][aria-controls]`.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_beforeafter_model.py`:

```python
@pytest.mark.django_db
def test_render_emits_namespaced_ids_and_both_panels():
    """Mutant: use node_pk instead of element.pk -> two elements on one page emit
    the same id and one button controls the other's panels.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit, label="Show solution")
    _child(unit, join, BeforeAfterElement.BEFORE_SLOT_ID, "problem")
    _child(unit, join, BeforeAfterElement.AFTER_SLOT_ID, "answer")

    html = obj.render(element=join, node_pk=999)

    assert f'id="ba-{join.pk}-panels"' in html
    assert f'aria-controls="ba-{join.pk}-panels"' in html
    assert "ba-999-panels" not in html  # node_pk must not be the id source
    assert 'data-ba-side="before"' in html and 'data-ba-side="after"' in html
    assert "problem" in html and "answer" in html
    assert 'aria-pressed="false"' in html
    assert "Show solution" in html


@pytest.mark.django_db
def test_render_without_label_carries_an_aria_label():
    """An icon-only button with no accessible name is a defect.

    Mutant: drop the {% if not el.button_label %} branch -> no aria-label.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    html = obj.render(element=join)
    assert "aria-label=" in html


@pytest.mark.django_db
def test_empty_slot_still_renders_its_panel():
    """Unlike calloutelement.html / spoilerelement.html (which wrap children in
    {% if children %}), an empty slot still emits its <section> -- that is what
    makes the "empty ruled panel" behaviour real.

    Mutant: wrap the panel in {% if children %} -> only one section renders.
    """
    _course, unit = make_course_with_unit()
    join, obj = _ba(unit)
    html = obj.render(element=join)
    assert html.count('class="ba__panel"') == 2
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_model.py -k "render or empty_slot" -v
```
Expected: FAIL — `TemplateDoesNotExist: courses/elements/beforeafterelement.html`.

- [ ] **Step 3: Create the template**

`templates/courses/elements/beforeafterelement.html`:

```html
{% load i18n courses_extras %}
{# `courses_extras` is required for render_element; loading only i18n raises
   Invalid block tag. Both sibling containers load the same pair. #}
<div class="el el--beforeafter" data-beforeafter>
  <button type="button" class="ba__toggle" aria-pressed="false"
          aria-controls="ba-{{ eid }}-panels"
          {% if not el.button_label %}aria-label="{% trans 'Switch content' %}"{% endif %}>
    <svg class="ic" aria-hidden="true" focusable="false"><use href="#el-beforeafter"/></svg>
    {% if el.button_label %}<span class="ba__label">{{ el.button_label }}</span>{% endif %}
  </button>
  <div class="ba__panels" id="ba-{{ eid }}-panels">
    {% for slot_id, children in slots %}
    <section class="ba__panel" data-ba-side="{{ slot_id }}">
      {# Visually hidden on screen; revealed by html:not(.ba-js) / .ba--dead / print.
         A <p>, not a heading -- these exist for print and the no-JS fallback, and
         real headings would pollute the lesson's document outline. #}
      <p class="ba__side-heading visually-hidden">
        {% if forloop.first %}{% trans "Before" %}{% else %}{% trans "After" %}{% endif %}
      </p>
      {% for child in children %}<div class="ba__child">{% render_element child %}</div>{% endfor %}
    </section>
    {% endfor %}
  </div>
</div>
```

There is deliberately **no `data-ba-eid`**: nothing reads it. The JS scopes by `data-beforeafter` + `closest()`, and the id namespacing is carried entirely by the `id` / `aria-controls` pair.

- [ ] **Step 4: Add the base CSS block**

In `courses/static/courses/css/courses.css`, near the other `.el--*` element blocks. **The opening comment is a test delimiter — Task 12's extraction helper anchors on it — so keep it exactly:**

```css
/* Before / after — base */
.el--beforeafter { margin-block: var(--space-6); }

/* Borrows .spoiler__toggle's token set (app.css:933-950) minus its two
   <summary>-specific declarations. Both are "press this to change what you see"
   controls; an author who has used one should recognise the other. */
.ba__toggle {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-4);
  font: inherit;
  font-weight: 600;
  line-height: 1;
  color: var(--primary);
  background: var(--primary-subtle);
  border: 1px solid color-mix(in srgb, var(--primary) 32%, transparent);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: background .15s ease, color .15s ease, border-color .15s ease;
}
/* Sized to the label's line-box so icon-only and icon+label buttons are the same
   height. An inline <svg> with no intrinsic size would otherwise collapse or
   render at the UA default -- only the screenshot step would catch it. */
.ba__toggle .ic { width: 1em; height: 1em; flex: none; }
.ba__toggle:hover { background: var(--primary); color: var(--text-inverse); border-color: transparent; }
.ba__toggle:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* The gap lives on the TOGGLE, not on .ba__panels. `.ba__toggle + .ba__panels`
   would select .ba__panels (the adjacent-sibling combinator names the subject on
   its RIGHT), breaking the no-margin invariant below -- and the two are not
   equivalent anyway: the toggle is inline-flex so its margin-bottom does not
   collapse and gives a fixed gap, whereas a margin-top on .ba__panels would
   collapse with the first panel content's own margin-top and give max(). */

/* .ba__panels deliberately gets NO rule at all: it is a bare grouping box --
   no margin, no padding, no border, not a flow-root -- so margins collapse
   through it untouched. An empty rule set would be dead CSS. */

/* Ported verbatim from app.css:986-990 (.spoiler__body, .spoiler > .spoiler__children).
   HORIZONTAL padding only, no vertical margin, not a flow-root -- so the
   children's own margins keep collapsing OUT and the rule starts and stops on the
   content rather than on the margins. Do NOT add :first-child/:last-child margin
   resets: those are the CALLOUT's treatment, needed only because .callout has
   padding that blocks collapsing (courses.css:1823-1834 says the spoiler's
   rationale does not transfer). They would defeat the hug.
   Each side is ONE box holding all that side's children, so a single border per
   side is continuous by construction -- which is why this needs no
   .spoiler__children-style wrapper.
   NO `display` here: that is what keeps the `hidden` attribute working through
   the UA default. */
.ba__panel {
  padding-left: var(--space-4);
  border-left: 2px solid color-mix(in srgb, var(--primary) 30%, transparent);
}
```

- [ ] **Step 5: Run the render tests**

```bash
uv run pytest courses/tests/test_beforeafter_model.py -v
```
Expected: PASS (8 tests).

- [ ] **Step 6: Run the render-seam guards from Task 1 Step 7**

```bash
uv run pytest courses/tests/test_render_seam.py -v
```
Expected: PASS. This proves `render()` accepts the state kwargs and that a lesson renders 200 with every concrete nested inside a before/after.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/elements/beforeafterelement.html courses/static/courses/css/courses.css \
        courses/tests/test_beforeafter_model.py
git commit -m "feat(before-after): student template and the spoiler-style left rule"
```

---

## Task 3: The five containment seams

**Files:**
- Modify: `courses/builder.py` (`:10-15` imports, `:62`, `:82-108`, `:111-121`, `:135`)
- Modify: `courses/transfer/payloads.py` (`:16-18` imports, `:811-823`, `:838`, `:849-862`)
- Create: `courses/tests/test_beforeafter_nesting.py`
- Modify: `courses/tests/test_nesting_rule.py` (`test_container_registry_carries_a_slot_cap`)

**Interfaces:**
- Consumes: `BeforeAfterElement.SLOT_IDS` (Task 1).
- Produces: `before_after` as a first-class container — `resolve_scope` accepts it as a parent, `paste_allowed` handles it, and it may nest inside Tabs/Spoiler/Callout/Two-column.

`courses/builder.py:58-62` says a new container must reach **three** structures. That comment is wrong for a *nestable* container — it needs **five**. Rewriting it is part of this task.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_beforeafter_nesting.py`:

```python
import pytest

from courses import builder
from courses.builder import NestingError
from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TabsElement
from tests.factories import make_course_with_unit


def _ba(unit, parent=None, tab=""):
    obj = BeforeAfterElement.objects.create()
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "slot", [BeforeAfterElement.BEFORE_SLOT_ID, BeforeAfterElement.AFTER_SLOT_ID]
)
def test_resolve_scope_accepts_both_slots(slot):
    """Mutant: registry lambda emits only one slot -> the other 400s."""
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    got_join, got_slot = builder.resolve_scope(unit, str(join.pk), slot, "text")
    assert got_join == join and got_slot == slot


@pytest.mark.django_db
def test_resolve_scope_rejects_an_unknown_slot():
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(unit, str(join.pk), "bogus", "text")


@pytest.mark.django_db
def test_before_after_nests_inside_another_container():
    """Seam 4: without "before_after" in NESTABLE_TYPE_KEYS this raises."""
    _course, unit = make_course_with_unit()
    top = Element.objects.create(
        unit=unit, content_object=TabsElement.objects.create(data=TabsElement.default_data())
    )
    tab_id = top.content_object.data["tabs"][0]["id"]
    join, slot = builder.resolve_scope(unit, str(top.pk), tab_id, "beforeafter")
    assert join == top and slot == tab_id


@pytest.mark.django_db
def test_a_graded_question_is_still_refused_as_a_child():
    """The allowlist is reused unchanged; `choice` must stay out.

    Mutant: add "choice" to NESTABLE_TYPE_KEYS -> accepted.
    """
    _course, unit = make_course_with_unit()
    join = _ba(unit)
    with pytest.raises(NestingError):
        builder.resolve_scope(
            unit, str(join.pk), BeforeAfterElement.BEFORE_SLOT_ID, "choice"
        )


def test_form_key_alias_exists():
    """Without the alias the card is offered nested and every click 400s."""
    assert builder._NESTABLE_FORM_KEY_ALIASES["beforeafter"] == "before_after"


def test_registry_cap_is_none():
    """A fixed-slot container is never truncated, so its cap is None -- not 2.
    None is what makes paste_allowed SKIP the position check rather than apply a
    bound that happens to work.
    """
    assert builder._CONTAINER_REGISTRY[BeforeAfterElement][3] is None


def test_slot_key_entry_is_the_fixed_id_set():
    from courses.transfer.payloads import _CONTAINER_SLOT_KEY

    assert _CONTAINER_SLOT_KEY["before_after"] == frozenset(BeforeAfterElement.SLOT_IDS)


def test_nestable_keys_are_a_subset_of_serializers():
    """The sibling-invariant guard every transfer test carries. This is what
    catches seam 4 landing before the export.py SERIALIZERS registration.
    """
    from courses.transfer.export import SERIALIZERS

    assert "before_after" in builder.NESTABLE_TYPE_KEYS
    assert builder.NESTABLE_TYPE_KEYS <= set(SERIALIZERS)
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_nesting.py -v
```
Expected: FAIL — `KeyError: 'beforeafter'` / `NestingError: parent is not a container`.

- [ ] **Step 3: Wire the three `builder.py` seams**

Add the import beside the existing container imports (`courses/builder.py:10-15`) — `_CONTAINER_REGISTRY` is evaluated at module import and keys on the class itself:

```python
from courses.models import BeforeAfterElement
```

`:62`:
```python
CONTAINER_TRANSFER_KEYS = frozenset({"tabs", "two_column", "spoiler", "callout", "before_after"})
```

In `NESTABLE_TYPE_KEYS` (`:82-108`) add `"before_after"`, and **rewrite the stale comment** above the container entries — "Both are already in transfer.export.SERIALIZERS" is false with a third key:

```python
        # Container keys. EVERY member of this set is in
        # transfer.export.SERIALIZERS, so NESTABLE_TYPE_KEYS <= SERIALIZERS
        # holds. (Phrased about the invariant, not a count -- "Both" was already
        # stale, and "all three" would ignore the callout/spoiler keys above.)
        "tabs",
        "two_column",
        "before_after",
```

`_NESTABLE_FORM_KEY_ALIASES` (`:111-121`):
```python
    "beforeafter": "before_after",
```

`_CONTAINER_REGISTRY` (`:135`) — ids derived from `SLOT_IDS`, never literals:
```python
    # Fixed TWO-slot: ignores its argument and returns both slots. Like Spoiler /
    # Callout it has no `data` field, which is why the call sites use getattr().
    BeforeAfterElement: (
        lambda _data: {"slots": [{"id": sid} for sid in BeforeAfterElement.SLOT_IDS]},
        "slots",
        "id",
        None,
    ),
```

Also rewrite the `CONTAINER_TRANSFER_KEYS` header comment at `:58-62`: a *nestable* container needs five structures, not three (add `NESTABLE_TYPE_KEYS` and `_NESTABLE_FORM_KEY_ALIASES`).

- [ ] **Step 4: Reshape the `payloads.py` sentinel**

Move the imports to module level (`courses/transfer/payloads.py:16-18`) — the dict below is module-level and would otherwise `NameError`:

```python
from courses.models import BeforeAfterElement
from courses.models import SINGLE_SLOT_ID
```

Delete the now-redundant local `from courses.models import SINGLE_SLOT_ID` inside `validate_nesting` (`:838`).

Replace the dict (`:818-823`) and **rewrite the comment above it** (`:811-817`), which documents the old `None` sentinel:

```python
# Module-level, transfer-type-string keyed (distinct from the model-keyed builder
# registry in courses.builder._CONTAINER_REGISTRY): the container type's transfer
# key -> either the key its `data` dict uses for the slot list, or a frozenset of
# its FIXED slot ids for a container that has no `data`. Membership is tested
# BEFORE this lookup.
_CONTAINER_SLOT_KEY = {
    "tabs": "tabs",
    "two_column": "columns",
    "spoiler": frozenset({SINGLE_SLOT_ID}),
    "callout": frozenset({SINGLE_SLOT_ID}),
    "before_after": frozenset(BeforeAfterElement.SLOT_IDS),
}
```

In `validate_nesting` (`:857-862`), and rewrite its inline comment (`:849-851`) too:

```python
        # Slot-membership: a fixed-slot container carries its valid ids directly;
        # every other container reads its slot list from `data`.
        slot_key = _CONTAINER_SLOT_KEY[parent["type"]]
        valid_slot_ids = (
            {s["id"] for s in parent["data"][slot_key]}
            if isinstance(slot_key, str)
            else set(slot_key)
        )
```

- [ ] **Step 5: Update the existing registry test**

`courses/tests/test_nesting_rule.py::test_container_registry_carries_a_slot_cap` — `len(reg) == 4` → `5`, and add:

```python
    # The second fixed-slot shape: two ids, still never truncated.
    assert reg[BeforeAfterElement][3] is None
```

- [ ] **Step 6: Run both nesting suites**

```bash
uv run pytest courses/tests/test_beforeafter_nesting.py courses/tests/test_nesting_rule.py -v
```
Expected: **PASS except `test_nestable_keys_are_a_subset_of_serializers`, which is
expected RED until Task 4 Step 3** — one of the plan's two knowingly-red checkpoints (see
Global Constraints). Everything else must be green.

`test_container_key_spaces_do_not_drift` and `test_container_keys_agree_by_key_not_by_count` must pass **unchanged** — they are the guard against a partial landing. If either fails, a seam is missing; do not relax them.

- [ ] **Step 7: Commit**

```bash
git add courses/builder.py courses/transfer/payloads.py courses/tests/test_beforeafter_nesting.py \
        courses/tests/test_nesting_rule.py
git commit -m "feat(before-after): register the fifth container across all five seams"
```

---

## Task 4: Transfer — serializer, validator, builder, walker

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_*` block, `SERIALIZERS` at `:461`, `emit()` walker at `~:626`, `walk_unit_joins` docstring at `:595-598`)
- Modify: `courses/transfer/payloads.py` (`_val_*` block, `VALIDATORS` at `:896`)
- Modify: `courses/transfer/importer.py` (`_build_*` block, `BUILDERS` at `:817`)
- Create: `courses/tests/test_beforeafter_transfer.py`

**Interfaces:**
- Consumes: `BeforeAfterElement.resolved_slots()`, `SLOT_IDS`.
- Produces: archive payload `{"button_label": str}` under type key `before_after`.

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_beforeafter_transfer.py`:

```python
import pytest

from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TextElement
from tests.factories import make_course_with_unit


def _ba_with_children(unit, label="Flip"):
    obj = BeforeAfterElement.objects.create(button_label=label)
    join = Element.objects.create(unit=unit, content_object=obj)
    for slot, body in (
        (BeforeAfterElement.BEFORE_SLOT_ID, "problem"),
        (BeforeAfterElement.AFTER_SLOT_ID, "answer"),
    ):
        Element.objects.create(
            unit=unit,
            content_object=TextElement.objects.create(body=body),
            parent=join,
            tab_id=slot,
        )
    return join, obj


# build_element_export(unit, root_join) -> (document, media_assets, problems).
# TWO positionals and a 3-TUPLE (export.py:993) -- not build_element_export(join).
# See tests/test_transfer_element_scope.py:54 for the call convention.


@pytest.mark.django_db
def test_export_emits_both_children_under_their_slot_ids():
    """Mutant: omit the emit() walker isinstance branch -> the serializer runs but
    ZERO children are emitted, and export succeeds silently.
    """
    from courses.transfer.export import build_element_export

    _course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit)
    document, _media, _problems = build_element_export(unit, join)
    tabs = {el["tab"] for el in document["elements"] if el["parent"] is not None}
    assert tabs == set(BeforeAfterElement.SLOT_IDS)


@pytest.mark.django_db
def test_export_carries_button_label():
    """Mutant: _ser_before_after returns {} -> the label is silently lost on every
    export, import AND duplicate_element.
    """
    from courses.transfer.export import build_element_export

    _course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit, label="Show solution")
    document, _media, _problems = build_element_export(unit, join)
    root = [el for el in document["elements"] if el["parent"] is None][0]
    assert root["data"] == {"button_label": "Show solution"}


@pytest.mark.django_db
def test_a_stray_child_exports_under_the_before_slot():
    """resolved_slots() re-homes an unknown tab_id into `before`, so the walker
    must yield the PAIR's slot id -- never the child's own tab_id, which would
    emit a payload validate_nesting rejects (export.py:595-598 documents exactly
    this invariant).

    Mutant: yield child.tab_id -> the archive carries "bogus" and re-import fails.
    """
    from courses.transfer.export import build_element_export

    _course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="stray"),
        parent=join,
        tab_id="bogus",
    )
    document, _media, _problems = build_element_export(unit, join)
    assert all(
        el["tab"] in BeforeAfterElement.SLOT_IDS
        for el in document["elements"]
        if el["parent"] is not None
    )


@pytest.mark.django_db
def test_duplicate_element_copies_children_and_label():
    """duplicate_element routes through build_element_export -> graft_elements, so
    the same walker mutant makes duplication return 200 with an empty copy.

    Signature is duplicate_element(course, element_pk, unit_token) returning
    (unit, new_join) -- builder.py:709. Model the call on
    tests/test_builder_duplicate_element.py.
    """
    from courses import builder

    course, unit = make_course_with_unit()
    join, _obj = _ba_with_children(unit, label="Flip")
    _unit, new_join = builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    copy = new_join.content_object
    assert copy.button_label == "Flip"
    assert [len(children) for _sid, children in copy.resolved_slots()] == [1, 1]


@pytest.mark.django_db
def test_validate_nesting_accepts_both_slots_and_rejects_a_bad_one():
    """The _CONTAINER_SLOT_KEY reshape in Task 3 changed the branch computing
    valid_slot_ids for ALL FIVE container types, not just this one. Nothing else
    in the plan exercises the rewritten `isinstance(slot_key, str)` ternary
    end-to-end, so inverting it could regress spoiler/callout imports with the
    whole suite green.

    Mutant: invert the ternary -> the before/after case raises and the spoiler
    case stops raising.
    """
    from courses.models import SINGLE_SLOT_ID
    from courses.transfer.payloads import validate_nesting
    from courses.transfer.schema import TransferError

    def _els(parent_type, tab, parent_data=None):
        return [
            {"id": "p", "type": parent_type, "parent": None, "tab": "",
             "data": parent_data or {}},
            {"id": "c", "type": "text", "parent": "p", "tab": tab, "data": {}},
        ]

    for slot in BeforeAfterElement.SLOT_IDS:
        validate_nesting(_els("before_after", slot))          # accepted
    with pytest.raises(TransferError):
        validate_nesting(_els("before_after", "bogus"))       # rejected
    # The reshape must not regress the other fixed-slot containers.
    validate_nesting(_els("spoiler", SINGLE_SLOT_ID))
    with pytest.raises(TransferError):
        validate_nesting(_els("spoiler", "bogus"))


def test_validator_rejects_unknown_and_missing_keys():
    from courses.transfer.payloads import VALIDATORS
    from courses.transfer.schema import TransferError

    val = VALIDATORS["before_after"]
    assert val({"button_label": "ok"}, "e1", set()) == set()
    with pytest.raises(TransferError):
        val({}, "e1", set())
    with pytest.raises(TransferError):
        val({"button_label": "ok", "extra": 1}, "e1", set())
    with pytest.raises(TransferError):
        val({"button_label": "x" * 121}, "e1", set())


def test_format_version_is_unchanged():
    """A new element TYPE has never bumped it; the version rises only when an
    EXISTING payload shape changes. Not bumping also sidesteps the silent-merge
    hazard (two branches setting the same new number do not conflict in git).
    """
    from courses.transfer.schema import FORMAT_VERSION

    assert FORMAT_VERSION == 9
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_transfer.py -v
```
Expected: FAIL — `KeyError: 'before_after'`.

- [ ] **Step 3: Add the serializer and register it**

`courses/transfer/export.py`, beside `_ser_callout` (`:121`) — **two positionals**; a one-arg definition `TypeError`s on the first export:

```python
def _ser_before_after(concrete, media_ids):
    return {"button_label": concrete.button_label}
```

Register in `SERIALIZERS` (defined at `:461`):
```python
    "before_after": (BeforeAfterElement, _ser_before_after),
```

- [ ] **Step 4: Add the `emit()` walker branch**

In the `emit()` walker (`~:626`), after the `CalloutElement` branch (`:638`):

```python
        elif isinstance(obj, BeforeAfterElement):
            # The PAIR's slot id, never child.tab_id: resolved_slots() re-homes a
            # stray child into `before`, so yielding its own tab_id would emit a
            # slot id the import validator rejects -- breaking the invariant this
            # function's docstring states.
            for slot_id, children in obj.resolved_slots():
                for child in children:
                    # Positional: the inner function is emit(join, parent_join,
                    # slot_id) and every sibling branch calls it that way.
                    yield from emit(child, join, slot_id)
```

Match the exact call shape the sibling branches use — read `:627-640` and mirror it rather than copying the sketch above verbatim.

**Update the `walk_unit_joins` docstring (`:595-598`)**: it enumerates three accessors and asserts stray children are OMITTED. Add `resolved_slots()` as a fourth and record that this container **re-homes rather than omits**, so the invariant's purpose (never emit a slot id the validator rejects) still holds.

- [ ] **Step 5: Add the validator**

`courses/transfer/payloads.py`, beside `_val_callout` (`:206`):

```python
def _val_before_after(data, elid, media_kinds):
    _exact_keys(data, ["button_label"], _("before/after data"))
    check_str(data["button_label"], _("button label"), max_length=120)
    return set()  # references no media
```

`check_str`'s second positional is a translated field label in all ~20 call sites, and `_exact_keys`' third is required — used in all three messages it raises. Register in `VALIDATORS` (`:896`):
```python
    "before_after": _val_before_after,
```

- [ ] **Step 6: Add the builder**

`courses/transfer/importer.py`, beside `_build_callout` (`:544-550`) — a **2-tuple** of `(concrete, created_files)`, built with `_clean_save` so the validated `CharField` is checked:

```python
def _build_before_after(data, assets):
    return _clean_save(BeforeAfterElement(button_label=data["button_label"])), ()
```

Register in `BUILDERS` (`:817`):
```python
    "before_after": _build_before_after,
```

- [ ] **Step 7: Run the transfer tests**

```bash
uv run pytest courses/tests/test_beforeafter_transfer.py courses/tests/test_beforeafter_nesting.py -v
```
Expected: PASS, including `test_nestable_keys_are_a_subset_of_serializers` from Task 3.

- [ ] **Step 8: Round-trip through a real archive**

```bash
uv run pytest courses/tests/ -k "transfer" -v
```
Expected: PASS — no existing transfer test regressed.

- [ ] **Step 9: Commit**

```bash
git add courses/transfer/ courses/tests/test_beforeafter_transfer.py
git commit -m "feat(before-after): transfer serializer, validator, builder and walker branch"
```

---

## Task 5: Client module, pre-hide and lesson context

**Files:**
- Create: `courses/static/courses/js/beforeafter.js`
- Modify: `courses/views.py` (`:395-403` region, `:476-484` context)
- Modify: `templates/courses/lesson_unit.html` (`prepaint` block, `extra_css`, `extra_js`)
- Modify: `courses/static/courses/css/courses.css` (state-scoped rules)
- Create: `courses/tests/test_beforeafter_context.py`

**Interfaces:**
- Consumes: the Task 2 DOM contract.
- Produces: `window.libliInitBeforeAfter(root)`, `window.__beforeAfterBooted`, `window.__baDisarm()`, context flag `has_before_after`.

- [ ] **Step 1: Write the failing context test**

Create `courses/tests/test_beforeafter_context.py`:

**There is no `courses/tests/conftest.py`.** `lesson_unit_node` and `student_user` are
**file-local** fixtures redefined in each of `test_fillgate_context.py`,
`test_spoiler_context.py`, `test_switchgate_context.py` and `test_callout_has_math.py`.
Copy them in, or every test here errors with "fixture not found". A quiz-unit fixture
exists nowhere and must be written from scratch (`test_reveal_gate_editor_row.py` has a
local `quiz_unit` to model it on).

```python
import pytest

from courses.models import BeforeAfterElement
from courses.models import Element
from courses.models import TabsElement
from courses.views import build_lesson_context


# Copied from test_fillgate_context.py:21-35 -- these are file-local everywhere.
@pytest.fixture
def lesson_unit_node():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def student_user():
    from tests.factories import make_verified_user

    return make_verified_user(username="student_ba_ctx")


@pytest.fixture
def quiz_unit_node():
    """No such fixture exists in the repo. Build a quiz unit the way
    ContentNodeFactory is used elsewhere (see test_callout_authoring.py:16-19 for
    the lesson form) with unit_type="quiz".
    """
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory()
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz"
    )


@pytest.mark.django_db
def test_flag_is_set_for_a_top_level_instance(lesson_unit_node, student_user):
    unit = lesson_unit_node
    Element.objects.create(
        unit=unit, content_object=BeforeAfterElement.objects.create()
    )
    assert build_lesson_context(unit, student_user)["has_before_after"] is True


@pytest.mark.django_db
def test_flag_is_set_for_a_NESTED_instance(lesson_unit_node, student_user):
    """The query must be FLAT -- children keep their own `unit` FK.

    Mutant: scope it to parent__isnull=True -> a before/after inside a tab is
    undetected, no pre-hide is emitted, and the answer flashes on every load.
    """
    unit = lesson_unit_node
    tabs = Element.objects.create(
        unit=unit,
        content_object=TabsElement.objects.create(data=TabsElement.default_data()),
    )
    tab_id = tabs.content_object.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=BeforeAfterElement.objects.create(),
        parent=tabs,
        tab_id=tab_id,
    )
    assert build_lesson_context(unit, student_user)["has_before_after"] is True


@pytest.mark.django_db
def test_flag_is_false_without_the_element(lesson_unit_node, student_user):
    # Positional: the signature is build_lesson_context(node, user) -- views.py:314.
    # `unit=` raises TypeError, failing for the wrong reason both before and after
    # the implementation lands.
    assert build_lesson_context(lesson_unit_node, student_user)["has_before_after"] is False
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_context.py -v
```
Expected: FAIL — `KeyError: 'has_before_after'`.

- [ ] **Step 3: Add the context flag**

In `courses/views.py`, beside the other `has_*` flags. Use the **app_label-pinned** form `has_html` uses, not `has_reveal_gate`'s bare `content_type__model__in` — the neighbouring comment records that the pin avoids cold-cache `ContentType` SELECTs, and this is a single-model lookup:

```python
    # Flat query (NOT scoped to parent__isnull=True) so an instance nested inside a
    # tab -- children keep their own `unit` FK -- is still detected.
    has_before_after = node.elements.filter(
        content_type__app_label="courses",
        content_type__model="beforeafterelement",
    ).exists()
```

Add `"has_before_after": has_before_after,` to the returned context (`:476-484`).

- [ ] **Step 4: Run the context tests**

```bash
uv run pytest courses/tests/test_beforeafter_context.py -v
```
Expected: PASS.

- [ ] **Step 5: Write the client module**

Create `courses/static/courses/js/beforeafter.js`:

```javascript
(function () {
  "use strict";

  // Set at PARSE TIME, as reveal.js:9 and stepper.js:6 do: the IIFE runs after
  // parsing and before DOMContentLoaded, which is what lets the inline watchdog
  // see the engine is alive. Because it is already true by the time init runs,
  // the watchdog CANNOT catch a mid-init throw -- hence the try/catch below,
  // mirroring tabs.js's bail() (:435-450).
  window.__beforeAfterBooted = true;

  var AFTER = "after";  // must match BeforeAfterElement.AFTER_SLOT_ID (guard test)

  function ownPanels(container) {
    // Ownership, not containment: a before/after may legally contain another one,
    // and a descendant-wide lookup would let the outer instance drive the inner's
    // panels (tabs.js:34-63).
    var all = container.querySelectorAll(".ba__panel");
    var mine = [];
    for (var i = 0; i < all.length; i++) {
      if (all[i].closest("[data-beforeafter]") === container) mine.push(all[i]);
    }
    return mine;
  }

  function ownToggle(container) {
    var all = container.querySelectorAll(".ba__toggle");
    for (var i = 0; i < all.length; i++) {
      if (all[i].closest("[data-beforeafter]") === container) return all[i];
    }
    return null;
  }

  // Per-instance recovery: un-arm THIS container only, so one bad instance never
  // strands its siblings. .ba--dead is the per-instance analogue of
  // html:not(.ba-js) and shares its declarations by grouped selector.
  function killOne(container) {
    var panels = ownPanels(container);
    for (var i = 0; i < panels.length; i++) panels[i].removeAttribute("hidden");
    delete container.dataset.baReady;
    container.classList.add("ba--dead");
  }

  function initOne(container) {
    // Idempotent: the editor preview pane is rebuilt on every fragment swap and
    // re-runs init over the whole pane. Read/write through the dataset PROPERTY --
    // setAttribute("data-baReady", ...) lowercases to data-baready, which
    // dataset.baReady would never read, silently defeating this guard.
    if (container.dataset.baReady === "1") return;

    try {
      var panels = ownPanels(container);
      var toggle = ownToggle(container);
      if (panels.length !== 2 || !toggle) return;
      container.dataset.baReady = "1";

      for (var i = 0; i < panels.length; i++) {
        if (panels[i].getAttribute("data-ba-side") === AFTER) {
          // `hidden` ATTRIBUTE, never an inline display:none -- an inline style
          // cannot be overridden by the @media print rule that reveals both.
          panels[i].setAttribute("hidden", "");
        }
      }

      toggle.addEventListener("click", function () {
        var showingAfter = toggle.getAttribute("aria-pressed") === "true";
        var incoming = null;
        var outgoing = null;
        for (var k = 0; k < panels.length; k++) {
          var isAfter = panels[k].getAttribute("data-ba-side") === AFTER;
          if (isAfter === !showingAfter) incoming = panels[k];
          else outgoing = panels[k];
        }
        // ORDER IS LOAD-BEARING: un-hide the incoming panel FIRST, then hide the
        // outgoing one, then aria-pressed, then dispatch. A listener that measures
        // synchronously would read zero if the event fired first -- and the
        // gallery e2e would not catch it, because tabs.js's listener is
        // rAF-deferred and would mask the ordering.
        incoming.removeAttribute("hidden");
        outgoing.setAttribute("hidden", "");
        toggle.setAttribute("aria-pressed", showingAfter ? "false" : "true");
        // bubbles: a gallery/carousel/table inside the panel measured zero height
        // while hidden and needs to re-measure now that it is visible.
        incoming.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      });
    } catch (e) {
      killOne(container);
      if (window.console && console.error) console.error(e);
    }
  }

  // Root-scoped ENHANCER. Wraps each initOne so a throw can never escape into the
  // caller: editor.js calls this in a sequence of re-init calls, and an escaping
  // throw would abort every enhancer sequenced after it.
  function initAll(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-beforeafter]")) initOne(scope);
    var nodes = scope.querySelectorAll("[data-beforeafter]");
    for (var i = 0; i < nodes.length; i++) {
      try { initOne(nodes[i]); } catch (e) {
        if (window.console && console.error) console.error(e);
      }
    }
  }

  window.libliInitBeforeAfter = initAll;

  // Document-level boot: the ONLY place that mutates <html>.
  try {
    initAll(document);
    document.documentElement.classList.remove("ba-armed");
  } catch (e) {
    if (window.__baDisarm) window.__baDisarm();
    if (window.console && console.error) console.error(e);
  }
})();
```

- [ ] **Step 6: Add the prepaint block, pre-hide style and include**

In `templates/courses/lesson_unit.html`.

**In `{% block prepaint %}`** (which holds only arming scripts — the pre-hide `<style>` goes in `extra_css`, matching `has_reveal_gate`):

```html
{% if has_before_after %}
<script>
  (function () {
    "use strict";
    var d = document.documentElement;
    // BOTH classes here, before first paint. `ba-js` must NOT be set from the
    // deferred module: it runs after parsing with no guarantee of running before
    // paint, so the html:not(.ba-js) rules -- five !important declarations that
    // UN-HIDE the side headings -- would be live through first paint, flashing
    // "Before"/"After" and shifting layout on every load.
    d.classList.add("ba-armed");
    d.classList.add("ba-js");
    // Defined HERE, not in beforeafter.js: on the 404/blocked path the module
    // never executes, so a module-defined function would not exist for this
    // watchdog to call.
    window.__baDisarm = function () {
      d.classList.remove("ba-armed");
      d.classList.remove("ba-js");
      // Reverse the PER-INSTANCE state too. Removing only the classes would leave
      // `hidden` on the after panel while html:not(.ba-js) .ba__toggle hides the
      // one control that could clear it -- stranding the content.
      var nodes = document.querySelectorAll("[data-beforeafter]");
      for (var i = 0; i < nodes.length; i++) {
        var panels = nodes[i].querySelectorAll(".ba__panel");
        for (var k = 0; k < panels.length; k++) panels[k].removeAttribute("hidden");
        delete nodes[i].dataset.baReady;
      }
    };
    document.addEventListener("DOMContentLoaded", function () {
      if (!window.__beforeAfterBooted) window.__baDisarm();
    });
  })();
</script>
{% endif %}
```

**In `{% block extra_css %}`**, beside the `has_reveal_gate` pre-hide:

```html
{% if has_before_after %}
<style>
  html.ba-armed .ba__panels > [data-ba-side="after"] { display: none; }
</style>
{% endif %}
```

**In `{% block extra_js %}`**, matching `tabs.js` at `:81` — `defer` is load-bearing (it is what makes the script run before `DOMContentLoaded`, which the boot guard and both script-failure e2e tests turn on):

```html
{% if has_before_after %}<script src="{% static 'courses/js/beforeafter.js' %}" defer></script>{% endif %}
```

- [ ] **Step 7: Add the state-scoped CSS**

In `courses/static/courses/css/courses.css`, **immediately after the base block** (the `html:not(.ba-js)` selector is Task 12's block delimiter, so its position matters) and **before** the print block Task 12 adds:

```css
/* Degraded states. Grouped with the .ba--dead per-instance twin so a single
   failed instance degrades exactly as a JS-less page does.
   The un-hide must invert ALL FIVE properties of .visually-hidden
   (app.css:1212) -- `clip`, NOT `clip-path`, which the utility does not use;
   a clip-path override is a no-op leaving a 1x1 clipped box. `white-space:
   nowrap` is deliberately not reverted: the headings are one word. */
html:not(.ba-js) .ba__side-heading,
.ba--dead .ba__side-heading {
  position: static !important; width: auto !important; height: auto !important;
  overflow: visible !important; clip: auto !important;
  font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; color: var(--text-secondary);
}
html:not(.ba-js) .ba__panel + .ba__panel,
.ba--dead .ba__panel + .ba__panel { margin-top: var(--space-5); }
/* A focusable button advertising aria-pressed="false" while doing nothing is
   worse than no button, since both panels are already shown. */
html:not(.ba-js) .ba__toggle,
.ba--dead .ba__toggle { display: none; }
```

- [ ] **Step 8: Verify in a browser**

```bash
uv run python manage.py runserver
```
Author a unit with a before/after, open it as a student, and check: only "before" shows on load, the button swaps both ways, and there is **no flash** of the "after" side or of the "Before"/"After" headings on reload.

- [ ] **Step 9: Commit**

```bash
git add courses/static/courses/js/beforeafter.js courses/views.py templates/courses/lesson_unit.html \
        courses/static/courses/css/courses.css courses/tests/test_beforeafter_context.py
git commit -m "feat(before-after): client toggle, render-blocking pre-hide and recovery contract"
```

---

## Task 6: Arm quiz units

**Files:**
- Modify: `courses/views.py` (`build_quiz_context`, `:1139`)
- Modify: `templates/courses/quiz_unit.html` (new `prepaint` block; existing `extra_css` `:4`, `extra_js` `:14`)
- Modify: `courses/tests/test_beforeafter_context.py`

Unlike a reveal gate — which is inert in quizzes because it interacts with submission — a before/after has no state, no endpoint and no grading interaction. Leaving it unarmed would permanently expose the answer side.

- [ ] **Step 1: Write the failing test**

Append to `courses/tests/test_beforeafter_context.py`:

```python
@pytest.mark.django_db
def test_flag_is_set_for_a_quiz_unit(quiz_unit_node, student_user):
    """Mutant: omit it from build_quiz_context -> the answer side is permanently
    visible in every quiz unit.
    """
    from courses.views import build_quiz_context

    Element.objects.create(
        unit=quiz_unit_node, content_object=BeforeAfterElement.objects.create()
    )
    assert build_quiz_context(quiz_unit_node, student_user)["has_before_after"] is True
```

Use whatever quiz-unit fixture the existing quiz context tests use; check `courses/tests/` for the name.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_context.py -k quiz -v
```
Expected: FAIL — `KeyError`.

- [ ] **Step 3: Add the flag to the quiz context**

In `build_quiz_context` (`courses/views.py:1139`), compute `has_before_after` with the **same** app_label-pinned flat query as Task 5 and add it to the returned context.

- [ ] **Step 4: Add the blocks to `quiz_unit.html`**

`quiz_unit.html` has **no `prepaint` block** — the reveal gate and stepper are lesson-only. `templates/base.html:43` renders it, empty by default, so overriding is safe.

To keep the arming script in one place, do this as three explicit edits:

1. **Create `templates/courses/_before_after_prepaint.html`** containing *only* the
   `<script>` element from Task 5 Step 6 — **without** the `{% if has_before_after %}`
   wrapper. The gate stays at each call site so the partial has no hidden dependency on a
   context name.
2. **Rewrite `lesson_unit.html`'s** `{% block prepaint %}` entry from Task 5 to:
   `{% if has_before_after %}{% include "courses/_before_after_prepaint.html" %}{% endif %}`.
   This *replaces* the inline block Task 5 added — do not leave both.
3. **Add the same two lines to `quiz_unit.html`** inside a new `{% block prepaint %}`.

The pre-hide `<style>` is **not** extracted: it stays inline in each template's
`extra_css` block, because Task 12's `test_after_slot_id_matches_every_css_selector`
reads exactly these three files for `[data-ba-side="after"]` —
`templates/courses/lesson_unit.html`, `templates/courses/quiz_unit.html`, and
`courses/static/courses/css/courses.css`. Keeping the selector in both templates is what
makes that guard cover three sites rather than one. Add the `defer` include to each
template's existing `extra_js` block.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest courses/tests/test_beforeafter_context.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py templates/courses/quiz_unit.html templates/courses/_before_after_prepaint.html \
        templates/courses/lesson_unit.html courses/tests/test_beforeafter_context.py
git commit -m "feat(before-after): arm quiz units too"
```

---

## Task 7: The fifth reveal-cascade scope

**Files:**
- Modify: `courses/static/courses/js/reveal.js` (`scopeOf` `:52-54`; comments `:40-42`, `:55-63`)
- Modify: `templates/courses/lesson_unit.html` (the `has_reveal_gate` `<style>` block)
- Modify: `core/static/core/css/app.css` (`@media print` `:1014-1022`)
- Modify: `courses/tests/test_reveal_scope_agreement.py`

A reveal gate is nestable, so one may be authored inside a panel. `.ba__panel` is the correct scope because it is the element whose **direct** children are the `.ba__child` rows the cascade walks sibling-by-sibling — what `ownWrapper` (`reveal.js:59-63`) requires.

- [ ] **Step 1: Update the agreement test first**

In `courses/tests/test_reveal_scope_agreement.py`, extend `SCOPES` (`:12`):

```python
SCOPES = (
    "[data-tab-panel]",
    ".slide",
    ".spoiler__children",
    ".callout__children",
    ".ba__panel",
)
```

Update the three test names and docstrings that say "four" → "five". The file has **no count assertions** — all three tests are containment loops — so this is wording plus the tuple.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_reveal_scope_agreement.py -v
```
Expected: FAIL ×3 — `.ba__panel missing from scopeOf` / `from the pre-hide CSS` / `from the @media print revert`.

- [ ] **Step 3: Add the scope in all three files**

`reveal.js:52-54`:
```javascript
  function scopeOf(btn) {
    return btn.closest("[data-tab-panel], .slide, .spoiler__children, .callout__children, .ba__panel, .spoiler");
  }
```
`.spoiler` stays last as the legacy body-only fallback.

`templates/courses/lesson_unit.html` — in the **`has_reveal_gate`** block (not the new `has_before_after` one; `_prehide_block` extracts only the block anchored on `has_reveal_gate %}\s*<style>`, so putting it elsewhere turns the test red). Include the `:not(.reveal-shown)` suffix every sibling selector carries:

```css
    .reveal-armed .ba__panel > .ba__child:has(> [data-reveal-gate]) ~ .ba__child:not(.reveal-shown),
```

`core/static/core/css/app.css:1014-1022`, in the existing `@media print` block:
```css
  .reveal-armed .ba__panel > .ba__child:has(> [data-reveal-gate]) ~ .ba__child,
```

- [ ] **Step 4: Rewrite the two stale `reveal.js` comments**

`:40-42` enumerates the scopes ("a slide…, a tab panel…, a spoiler body, or a callout's children wrapper") and `:55-63` says "Four scopes exist… those three scopes share the same direct-child form". Both are false now. `.ba__panel` shares the direct-child form.

- [ ] **Step 5: Run the agreement test**

```bash
uv run pytest courses/tests/test_reveal_scope_agreement.py courses/tests/ -k "reveal" -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/reveal.js templates/courses/lesson_unit.html \
        core/static/core/css/app.css courses/tests/test_reveal_scope_agreement.py
git commit -m "feat(before-after): add .ba__panel as the fifth reveal-cascade scope"
```

---

## Task 8: Editor form and authoring path

**Files:**
- Modify: `courses/element_forms.py` (new form; `FORM_FOR_TYPE` at `:1954`)
- Create: `templates/courses/manage/editor/_edit_beforeafter.html`
- Modify: `courses/views_manage.py` (`element_add` allow-tuple `~:1823`, `element_save` allow-tuple `~:1894`, `_EDITOR_TYPE_LABELS` `:1621-1652`)
- Create: `courses/tests/test_beforeafter_authoring.py`

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_beforeafter_authoring.py`, modelled on `courses/tests/test_callout_authoring.py`:

`test_callout_authoring.py` defines **no** `_add_url` / `_save_url` helpers and no
`editor_user` fixture — it uses `make_pa`, `CourseFactory`, a local `_lesson_unit`, and
inline `reverse(...)`. The POST body needs **`"unit": unit.pk`** and the
**`HTTP_X_REQUESTED_WITH="fetch"`** header; without them the add does not resolve the
unit. This is the real shape (`test_callout_authoring.py:22-36`, `:53-70`):

```python
import pytest
from django.urls import reverse

from courses.models import BeforeAfterElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

# Three separate mutants, each of which leaves the rest of the suite green:
#   * drop the FORM_FOR_TYPE entry
#   * drop "beforeafter" from the element_add allow-tuple
#   * drop it from the element_save allow-tuple
# Plus: the row branch omitting el-edit-slot (Task 9).


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_form_renders_the_beforeafter_edit_partial(client):
    """Proves _edit_beforeafter.html exists (else 500) and carries the field."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "beforeafter", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="button_label"' in html
    assert 'class="el-editor' in html   # the grid item the scroll fix keys on
    # Mutant: omit the _EDITOR_TYPE_LABELS entry -> the form opens with no heading.
    assert "Before / after" in html


def test_save_round_trips_the_button_label(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "beforeafter",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "button_label": "Show solution",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    obj = BeforeAfterElement.objects.get()
    assert obj.button_label == "Show solution"
    assert "Show solution" in obj.render(element=obj.join_row())
```

Read `test_callout_authoring.py` before writing this and match its conventions exactly;
the `manage_element_save` body above mirrors its `:53-70`.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_authoring.py -v
```
Expected: FAIL — the add POST 400s (type not in the allow-tuple).

- [ ] **Step 3: Add the form and register it**

`courses/element_forms.py`, mirroring `CalloutElementForm` (`:225-228`). `Meta.model` is what tells `element_add` which concrete row to create:

```python
class BeforeAfterElementForm(forms.ModelForm):
    class Meta:
        model = BeforeAfterElement
        fields = ["button_label"]
```

Register in `FORM_FOR_TYPE` (`:1954`):
```python
    "beforeafter": BeforeAfterElementForm,
```

- [ ] **Step 4: Create the edit partial**

`templates/courses/manage/editor/_edit_beforeafter.html`. It must open with the `.el-editor` wrapper — `_host_form.html` includes these via `{% include "courses/manage/editor/_edit_"|add:type_key|add:".html" %}`, and `.el-editor` is a load-bearing grid item in `editor.css` (the container the fieldset/`min-inline-size` scroll fix keys on), so a bare `<label>` would sit outside the grid:

```html
{% load i18n %}
<div class="el-editor el-editor--beforeafter">
  <label class="field">
    <span class="field__label">{% trans "Button label" %}</span>
    <input type="text" name="button_label" maxlength="120"
           value="{{ form.button_label.value|default:'' }}">
  </label>
  {% for e in form.button_label.errors %}<p class="field__error">{{ e }}</p>{% endfor %}
</div>
```

Match `_edit_callout.html`'s field markup exactly rather than the sketch above.

- [ ] **Step 5: Add both allow-tuples and the editor label**

In `courses/views_manage.py`: add `"beforeafter"` to the `element_add` allow-tuple (`~:1823`) **and** to the `element_save` allow-tuple (`~:1894`). These are **two separate edits** — the tuples genuinely differ (`slidebreak` is in save but not add).

Add to `_EDITOR_TYPE_LABELS` (`:1621-1652`), which supplies the open-form heading and is **form-key** keyed:
```python
    "beforeafter": gettext_lazy("Before / after"),
```

- [ ] **Step 6: Run the authoring tests**

```bash
uv run pytest courses/tests/test_beforeafter_authoring.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add courses/element_forms.py templates/courses/manage/editor/_edit_beforeafter.html \
        courses/views_manage.py courses/tests/test_beforeafter_authoring.py
git commit -m "feat(before-after): editor form, allow-tuples and open-form label"
```

---

## Task 9: Editor row branch

**Files:**
- Modify: `templates/courses/manage/editor/_element_row.html` (new branch)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` `:32-63`; `element_summary` `~:118`)
- Modify: `courses/static/courses/css/editor.css`
- Modify: `courses/tests/test_beforeafter_authoring.py`

- [ ] **Step 1: Write the failing tests**

Append to `courses/tests/test_beforeafter_authoring.py`:

```python
@pytest.mark.django_db
def test_row_renders_type_tag_and_summary(client, editor_user, lesson_unit_node):
    """el-tag is the ONLY consumer of the _ELEMENT_LABELS entry.

    Mutants: drop the el-tag span -> the entry has no consumer and the row ships
    untagged; drop the element_summary branch -> the label falls back to the
    generic and shows nothing useful.
    """
    client.force_login(editor_user)
    client.post(_add_url(lesson_unit_node), {"type": "beforeafter"})
    el = lesson_unit_node.elements.get()
    el.content_object.button_label = "Show solution"
    el.content_object.save()

    body = client.get(_editor_url(lesson_unit_node)).content.decode()
    # Assert on the TAG MARKUP, not the bare string: from Task 10 onward the
    # add-menu card also renders {% trans "Before / after" %} on this same page,
    # so `"Before / after" in body` is satisfied whether or not the row emits
    # el-tag -- the bare-substring trap this repo has hit before.
    assert '<span class="el-tag">Before / after</span>' in body
    assert "Show solution" in body           # el-row__label via element_summary
    assert 'class="el-edit-slot"' in body    # hosts the open form
    assert "element-list--nested" in body    # child-row wrapper
    # Mutant: drop {% paste_buttons %} from a slot -> this drops to 1.
    assert body.count('data-ba-slot="') == 2
    assert body.count("data-paste-into") == 2  # match the real paste_buttons markup


@pytest.mark.django_db
def test_element_title_wins_over_button_label(client, editor_user, lesson_unit_node):
    """Mutant: drop the {% if el.title %} branch -> before/after becomes the only
    type whose author-set Element.title is ignored in the editor tree.
    """
    client.force_login(editor_user)
    client.post(_add_url(lesson_unit_node), {"type": "beforeafter"})
    el = lesson_unit_node.elements.get()
    el.title = "My comparison"
    el.save()
    el.content_object.button_label = "Show solution"
    el.content_object.save()

    body = client.get(_editor_url(lesson_unit_node)).content.decode()
    assert "My comparison" in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_authoring.py -v
```
Expected: FAIL — no `el-tag`, no summary.

- [ ] **Step 3: Add the label map entry and the summary branch**

`courses/templatetags/courses_manage_extras.py` — `_ELEMENT_LABELS` (`:32-63`), **content-type-model** keyed (a different namespace from Task 8's form-key map):
```python
    "beforeafterelement": _("Before / after"),
```

`element_summary` (`~:118`), which dispatches on the concrete class name:
```python
    if name == "BeforeAfterElement":
        return el.button_label or _("Before / after")
```

- [ ] **Step 4: Add the row branch**

In `templates/courses/manage/editor/_element_row.html`, add a `beforeafterelement` branch. **Reproduce the sibling row scaffolding first** — read the callout branch at `:199-220` and mirror it exactly:

1. `<li class="el-row el-row--beforeafter{% if open_form_pk == el.pk|stringformat:'s' %} el-row--editing{% endif %}{% if clip_element_pk == el.pk|stringformat:'s' %} el-row--marked{% endif %}"` with `data-element`, `data-updated`, `data-unit`;
2. `<div class="el-row__head">` > grip + `<div class="el-row__body">` > `<div class="el-row__top">` > `<span class="el-tag">{% element_type_label el.content_type obj %}</span>` + `<span class="el-actions">` (edit with `data-form-url`, cancel, `_element_row_controls.html`);
3. the `el-row__label` button with `{% if el.title %}{{ el.title }}{% else %}{{ obj|element_summary }}{% endif %}`;
4. `<div class="el-edit-slot" data-edit-slot>{% if open_form_pk == el.pk|stringformat:'s' %}{{ open_form|safe }}{% endif %}</div>` — **the only place the rendered open form lands**;

then the container-specific tail:

```html
    <div class="el-row__ba">
      {% for slot_id, children in obj.resolved_slots %}
      <div class="ba-rows" data-ba-slot="{{ slot_id }}">
        <div class="ba-rows__label">{% if forloop.first %}{% trans "Before" %}{% else %}{% trans "After" %}{% endif %}
          <span class="ba-rows__count">{{ children|length }}</span></div>
        <ol class="element-list element-list--nested">
          {% for child in children %}
            {% include "courses/manage/editor/_element_row.html" with el=child %}
          {% empty %}
            <li class="empty-state">{% trans "No content yet" %}</li>
          {% endfor %}
        </ol>
        {% if depth < max_nest_depth %}{% include "courses/manage/editor/_add_menu.html" with nested=True parent=el.pk tab=slot_id depth=depth %}{% endif %}{% paste_buttons el.pk slot_id %}
      </div>
      {% endfor %}
    </div>
```

Match the child-include call exactly as the sibling branches write it (they pass more context than shown).

Three things that are easy to lose:
- **`<ol class="element-list element-list--nested">` is required.** Three `editor.css` rules key on it: `.element-list` (`:523`), `.element-list--nested`'s left rule (`:1060`), `.element-list--nested .ica--grip { display: none }` (`:584`). Loose `<li>`s would show bullets, no gap, no rule, and drag grips no other container shows.
- **`{% paste_buttons %}` per slot** — omitting it makes this the only container you cannot paste into.
- **Do not gate the branch on `el.parent_id is None`.** The spoiler branch's comment records that dropping exactly that clause was required for depth-3 nesting.

The slots are plain always-open `<div>`s, **not `<details>`** — with exactly two fixed slots there is nothing to collapse, so `open_slots` / `slot_key` / `in_set` / `clip_active` / `data-force-open` are all unnecessary. The class is `ba-rows__label`, not `__summary`: `columns-rows__summary` is on a literal `<summary>` and would carry marker/cursor styling that cannot transfer.

- [ ] **Step 5: Add the editor CSS**

In `courses/static/courses/css/editor.css`, style `.el-row__ba`, `.ba-rows`, `.ba-rows__label`, `.ba-rows__count`. These class names **must stay disjoint from the student `.ba__panel` / `.ba__child`** — if the editor reused `.ba__panel` and gave it a `display`, the `[hidden]`-through-the-UA-default invariant would break in the preview pane and Task 12's test (scoped to the base block in `courses.css`) would not see it.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest courses/tests/test_beforeafter_authoring.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_element_row.html courses/templatetags/courses_manage_extras.py \
        courses/static/courses/css/editor.css courses/tests/test_beforeafter_authoring.py
git commit -m "feat(before-after): editor row branch with both slot panels"
```

---

## Task 10: Add-menu card, icon and their guards

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html` (card; header comment `:12-16`)
- Modify: `templates/courses/manage/_icon_sprite.html` (`el-beforeafter`)
- Modify: `core/help.py` (`ELEMENT_ICON_SLUGS` `:40`)
- Modify: `tests/test_manage_editor_menu.py` (`EL_ICON_MAP` `:8`, count `:62`, comment `:77`)
- Modify: `tests/test_editor_depth.py` (`CONTAINER_CARDS` `:83`; docstring `:162-166`)

- [ ] **Step 1: Update the guards first (they define the target)**

`tests/test_manage_editor_menu.py`:
- `EL_ICON_MAP` (`:8`) — add `"beforeafter": "el-beforeafter"`. **This map does not go red on its own** when a card is added without an entry; it silently stops covering the new card, so a card pointing at a symbol the sprite never defines would ship green with a blank icon.
- `:62` — `== 23` → `== 24`, and the trailing comment.
- `:77` — `# 11 content cards` → `# 12 content cards`, and add `"beforeafter"` to the tuple above it.

`tests/test_editor_depth.py`:
- `CONTAINER_CARDS` (`:83`) → `("tabs", "twocolumn", "spoiler", "callout", "beforeafter")`. This shared constant already drives five depth tests; without the entry the existing matrix never exercises the new card.
- Rewrite the `:162-166` docstring: `_element_row.html` now includes `_add_menu.html` at **six** sites, not four (this element adds two, one per slot).

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_manage_editor_menu.py tests/test_editor_depth.py -v
```
Expected: FAIL — card count 23 ≠ 24, and `el-beforeafter` missing from the sprite.

- [ ] **Step 3: Add the sprite symbol**

In `templates/courses/manage/_icon_sprite.html`, beside the other `el-*` symbols — a monochrome `currentColor` line SVG on the same 16×16 grid, two arrows following a circle. Never emoji:

```html
  <symbol id="el-beforeafter" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" d="M13 6.5A5 5 0 0 0 3.5 5M3 9.5A5 5 0 0 0 12.5 11"/><path fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" d="M13 3v3.5h-3.5M3 13V9.5h3.5"/></symbol>
```

- [ ] **Step 4: Add the card**

In `templates/courses/manage/editor/_add_menu.html`, in the **Content** group (`:27`), beside the callout/tabs/columns cards at `:37-39`, with the same depth guard:

```html
      {% if depth < max_nest_depth|add:-1 %}<button type="button" class="typecard" data-add-type="beforeafter"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-beforeafter"/></svg>{% trans "Before / after" %}</button>{% endif %}
```

**Content group, not Interactive.** The Interactive group is wrapped in `{% if not unit_is_quiz %}` (`:41`); a card placed there could never be authored in a quiz unit, making Task 6 dead code.

Rewrite the header comment at `:12-16`, which enumerates "Tabs, Columns, Spoiler, Callout" as the container cards.

- [ ] **Step 5: Add the help icon slug**

`core/help.py:40` — add `"beforeafter"` to `ELEMENT_ICON_SLUGS` (the sprite id minus the `el-` prefix). `test_element_icon_slugs_match_sprite` goes red if the symbol lands without it.

- [ ] **Step 6: Run the guards**

```bash
uv run pytest tests/test_manage_editor_menu.py tests/test_editor_depth.py tests/test_help.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html \
        core/help.py tests/test_manage_editor_menu.py tests/test_editor_depth.py
git commit -m "feat(before-after): add-menu card, sprite icon and their guards"
```

---

## Task 11: Editor preview wiring

**Files:**
- Modify: `templates/courses/manage/editor/editor.html` (script include `:170`; new `prepaint` block)
- Modify: `courses/static/courses/js/editor.js` (`:105`)

Without the `ba-js` prepaint block the `html:not(.ba-js)` rules are permanently in force on the editor page: the preview's toggle is `display: none` and both headings un-hidden, while `initOne` still sets `hidden` on the "after" panel. The preview would show one labelled panel and no control.

- [ ] **Step 1: Add the prepaint block**

`editor.html` currently defines no `prepaint` block and `base.html:43` renders an empty one, so overriding is safe. Set **`ba-js` only, never `ba-armed`** — there is no pre-hide on this page, and arming without disarming would hide the panel permanently:

```html
{% block prepaint %}
<script>document.documentElement.classList.add("ba-js");</script>
{% endblock %}
```

Unconditional: the editor cannot know which element types a unit holds without a query, and one class costs nothing.

- [ ] **Step 2: Include the module**

Beside the `tabs.js` include at `:170`, with the same `{% comment %}` convention explaining that the preview renders the *student* template:

```html
  <script src="{% static 'courses/js/beforeafter.js' %}" defer></script>
```

- [ ] **Step 3: Re-init after each fragment swap**

`courses/static/courses/js/editor.js:105`, beside the `libliInitTabs` call:

```javascript
    if (preview && window.libliInitBeforeAfter) window.libliInitBeforeAfter(preview);  // re-enhance before/after
```

- [ ] **Step 4: Verify in a browser**

```bash
uv run python manage.py runserver
```
Open the editor for a unit with a before/after. Confirm: the preview shows the toggle **visible**, pressing it swaps, and after editing another element (which triggers a fragment swap) the toggle still works and has not been double-bound (one click = one swap).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/editor/editor.html courses/static/courses/js/editor.js
git commit -m "feat(before-after): wire the element into the editor preview pane"
```

---

## Task 12: Print, the display invariant and the slot-id guard

**Files:**
- Modify: `courses/static/courses/css/courses.css` (`@media print` block)
- Modify: `core/static/core/css/app.css` (`:1010` `[hidden]` guard)
- Create: `courses/tests/test_beforeafter_css.py`

- [ ] **Step 1: Write the failing tests**

Create `courses/tests/test_beforeafter_css.py`:

```python
import re
from pathlib import Path

from courses.models import BeforeAfterElement

COURSES_CSS = "courses/static/courses/css/courses.css"
APP_CSS = "core/static/core/css/app.css"


def _read(p):
    return Path(p).read_text(encoding="utf-8")


def _strip_comments(css):
    """Comments name the very selectors these tests look for, so a raw scan is
    green under its own mutant (the test_element_state_write_routes precedent).
    """
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _delimited(css, start_marker, end_marker):
    """Extract between two literal markers, asserting BOTH matched.

    Comments are stripped FIRST, then both delimiters are located in the stripped
    text: the plan's own prose and CSS comments mention `html:not(.ba-js)`, and
    locating the end marker in RAW text would let a comment truncate the block --
    making the invariant test vacuous.
    """
    stripped = _strip_comments(css)
    start = stripped.index(start_marker)
    end = stripped.index(end_marker, start + len(start_marker))
    return stripped[start:end]


def _rule_body(block, selector):
    """The declarations of one rule, so an invariant about `.ba__panel` is not
    asserted against a whole block that legitimately contains other rules."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", block)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_panel_and_child_declare_no_display():
    """The invariant is narrow: `.ba__panel` and `.ba__child` declare no display.
    It is NOT "the base block declares no display" -- the block also holds
    `.ba__toggle { display: inline-flex }`, which the spec requires.

    Mutant: add `display: block` to .ba__panel -> RED.
    """
    block = _delimited(_read(COURSES_CSS), "Before / after — base", "html:not(.ba-js)")
    panel = _rule_body(block, ".ba__panel")
    assert "border-left" in panel
    assert "display" not in panel
    if ".ba__child" in block:
        assert "display" not in _rule_body(block, ".ba__child")


def test_ba_child_joins_the_hidden_guard():
    """.ba__child is a reveal-cascade wrapper exactly as .tabs__child is, so it
    needs the same protection against an author display beating [hidden].

    Anchor on the guard LINE itself: app.css:1009 is
    `.reveal-gate[hidden] { display: none !important; }`, which is the FIRST line
    matching a generic [hidden]+!important pattern and would never contain
    .ba__child -- making a first-match regex RED against correct code.
    """
    css = _strip_comments(_read(APP_CSS))
    guard = re.search(r"^.*\.lesson-block\[hidden\].*$", css, re.M)
    assert guard, "the shared [hidden] guard line moved"
    assert ".ba__child[hidden]" in guard.group(0)


# courses.css contains SEVEN @media print blocks (the first at :103). A
# first-match `@media print` regex -- the convention test_reveal_scope_agreement
# uses for app.css, where it holds -- extracts the WRONG one here, so all three
# print tests below would be RED against a correct implementation. Anchor on the
# element's own delimiter comment instead.


def _print_block(css):
    return _delimited(css, "Before / after — print", "\n}")


def test_print_unhides_with_block_not_revert():
    """`revert` rolls back to the UA origin, where [hidden] { display: none }
    lives -- so it CANNOT un-hide an element carrying the attribute.

    Mutant: change to `display: revert` -> the panel stays hidden in print.
    """
    block = _print_block(_read(COURSES_CSS))
    assert ".ba__panel[hidden]" in block and "display: block !important" in block
    assert ".ba__toggle" in block


def test_print_reverts_clip_not_clip_path():
    """.visually-hidden (app.css:1212) uses `clip`, not `clip-path`. A
    `clip-path: none` override is a no-op leaving a 1x1 overflow-hidden box --
    an unlabelled printed page that LOOKS handled.
    """
    block = _print_block(_read(COURSES_CSS))
    assert "clip: auto !important" in block
    assert "clip-path" not in block


def test_print_carries_the_eyebrow_and_separation_rules():
    """Print is the ONLY path that reaches these headings on a working JS page.

    Mutant: drop them -> two butted-together panels under unstyled bare <p>s.
    """
    block = _print_block(_read(COURSES_CSS))
    assert "text-transform: uppercase" in block
    assert ".ba__panel + .ba__panel" in block


def test_print_child_rule_follows_the_app_css_guard_in_document_order():
    """Both are `.ba__child[hidden]` at specificity 0-2-0 with !important, so
    NEITHER specificity nor @media print decides the winner -- only document
    order does. base.html loads app.css before courses.css, so the print
    declaration living in courses.css is what makes it win.

    Mutant: move the print block into app.css above :1010 -> the child stays
    hidden in print.
    """
    assert ".ba__child[hidden]" in _print_block(_read(COURSES_CSS))
    app = _strip_comments(_read(APP_CSS))
    if ".ba__child[hidden]" in app and "Before / after — print" in app:
        assert app.index("Before / after — print") > app.index(".lesson-block[hidden]")


def test_no_js_rules_revert_the_same_five_properties():
    """Bounded by the print delimiter -- a fixed character window would go red
    whenever the block grows, and would silently swallow the print block if it
    shrank."""
    block = _delimited(
        _read(COURSES_CSS), "html:not(.ba-js)", "Before / after — print"
    )
    for decl in ("position: static", "width: auto", "height: auto",
                 "overflow: visible", "clip: auto"):
        assert decl in block
    assert ".ba--dead" in block  # the per-instance twin shares the declarations


def test_after_slot_id_matches_every_css_selector():
    """CSS cannot reference a Python constant, so `after` is hardcoded in three
    sites. Renaming AFTER_SLOT_ID would silently disarm the pre-hide -- and the
    failure mode is a FLASHED ANSWER, not a test error.

    Two of the three sites are TEMPLATES, not stylesheets: a guard that globs
    *.css would cover one of three and ship green.
    """
    assert BeforeAfterElement.AFTER_SLOT_ID == "after"
    selector = '[data-ba-side="after"]'
    for path in (
        "templates/courses/lesson_unit.html",
        "templates/courses/quiz_unit.html",
        COURSES_CSS,
    ):
        text = _read(path)
        assert selector in text, f"{selector} missing from {path}"
```

These three paths are fixed by Task 6 step 4, which deliberately keeps the pre-hide
`<style>` inline in both unit templates (only the `<script>` is extracted to a partial)
precisely so this guard covers three sites. Do not "simplify" it to one.

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_css.py -v
```
Expected: FAIL — no `@media print` block for this element yet.

- [ ] **Step 3: Add `.ba__child` to the `[hidden]` guard**

`core/static/core/css/app.css:1010`:
```css
.lesson-block[hidden], .tabs__child[hidden], .ba__child[hidden] { display: none !important; }
```
`.ba__panel` is **not** added — its hiding is driven by this element's own JS, not the cascade.

- [ ] **Step 4: Add the print block**

At the **end** of the element's rules in `courses/static/courses/css/courses.css`, after the state-scoped block:

The opening comment is the test delimiter (`courses.css` has seven `@media print`
blocks, so a first-match regex would extract the wrong one) — keep it exactly:

```css
/* Before / after — print
   Print reveals both sides. `display: block !important`, NOT `revert`: revert
   rolls back to the UA origin, which is exactly where [hidden] { display: none }
   lives, so it cannot un-hide an element carrying the attribute.
   The .ba__child line is here because the shared print block in app.css uses
   `display: revert !important` and so cannot un-hide a cascade-hidden child --
   that entry satisfies scope agreement, this one does the work.
   The toggle is meaningless ink once both panels show (house precedent:
   [data-reveal-gate] and .unit-strip__edit are both hidden in print). */
@media print {
  .ba__panel[hidden] { display: block !important; }
  html.ba-armed .ba__panels > [data-ba-side="after"] { display: block !important; }
  .ba__child[hidden] { display: block !important; }
  .ba__toggle { display: none !important; }
  .ba__side-heading {
    position: static !important; width: auto !important; height: auto !important;
    overflow: visible !important; clip: auto !important;
    font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: var(--text-secondary);
  }
  .ba__panel + .ba__panel { margin-top: var(--space-5); }
}
```

**Cascade order note:** `.ba__child[hidden]` appears both here and in the `app.css` guard — identical selectors (0-2-0) both `!important`, so **only document order decides**, and the print declaration must be later. It is, because `base.html` loads `app.css` before `{% block extra_css %}` loads `courses.css`. Do not move either.

- [ ] **Step 5: Run the CSS tests**

```bash
uv run pytest courses/tests/test_beforeafter_css.py -v
```
Expected: PASS (7 tests).

- [ ] **Step 6: Verify print rendering**

Open a lesson with a before/after, print-preview it (Ctrl+P), and confirm both panels appear, each under a visible uppercase "BEFORE" / "AFTER" eyebrow, separated, with no toggle button.

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/css/courses.css core/static/core/css/app.css \
        courses/tests/test_beforeafter_css.py
git commit -m "feat(before-after): print reveal, hidden guard and the CSS invariant tests"
```

---

## Task 13: End-to-end tests

**Files:**
- Create: `tests/test_e2e_before_after.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the e2e suite**

Create `tests/test_e2e_before_after.py`. Read a sibling (`tests/test_e2e_twocolumn.py`) first and copy its fixture and unit-building helpers exactly.

```python
import pytest

pytestmark = pytest.mark.e2e

# STALLING and ABORTING are NOT interchangeable, and the boot guard is why.
# An ABORT makes the deferred script fail immediately, so DOMContentLoaded fires,
# the watchdog drops ba-armed, and the after panel becomes VISIBLE -- a pre-hide
# test written against an abort is RED on a correct build. Only a STALL (a route
# handler that never resolves) keeps the script pending, blocks DOMContentLoaded,
# and leaves ba-armed applied.


@pytest.mark.django_db(transaction=True)
def test_toggle_swaps_both_ways(page, live_server):
    ...
    # assert before visible / after hidden
    # click -> after visible, before hidden, aria-pressed == "true"
    # click -> back, aria-pressed == "false"


@pytest.mark.django_db(transaction=True)
def test_after_is_not_visible_while_the_script_is_pending(page, live_server):
    """Mutant: remove the pre-hide <style> -> RED. A plain post-load assertion
    would be GREEN under that mutant, because init sets `hidden` either way --
    stalling is what brackets the pre-paint window rather than measuring the
    settled state.
    """
    # A stalled `defer` script blocks BOTH DOMContentLoaded and load, so a plain
    # page.goto() (default wait_until="load") times out after 30s and the test
    # fails on a CORRECT build. Navigate with wait_until="commit", and unroute
    # before the test ends -- a handler that neither fulfils, aborts nor continues
    # leaves the route unhandled and can raise at context teardown.
    page.route("**/beforeafter.js", lambda route: None)  # never fulfil
    page.goto(url, wait_until="commit")
    ...
    page.unroute("**/beforeafter.js")


@pytest.mark.django_db(transaction=True)
def test_boot_guard_recovers_from_an_aborted_script(page, live_server):
    """Two mutants:
      * delete the guard -> the after side is stranded
      * watchdog removes only ba-armed -> panels show BUT the headings stay
        hidden and the dead toggle stays visible
    Asserting only "both panels show" leaves the second one green.
    """
    page.route("**/beforeafter.js", lambda route: route.abort())
    ...
    # assert both panels visible
    # assert the side headings are VISIBLE
    # assert the toggle is HIDDEN


@pytest.mark.django_db(transaction=True)
def test_a_failing_instance_does_not_strand_its_siblings(page, live_server):
    """Build three instances and break the middle one's DOM so initOne throws.

    Mutant: move the try/catch to the document level -> instances 1 and 3 are
    stranded too.
    """
    ...
    # assert instance 2 shows both panels and carries .ba--dead
    # assert instances 1 and 3 still toggle


@pytest.mark.django_db(transaction=True)
def test_recovery_clears_hidden_not_just_the_html_classes(page, live_server):
    """Mutant: have __baDisarm remove only the classes -> the after panel stays
    hidden with no control to reveal it.
    """
    ...


@pytest.mark.django_db(transaction=True)
def test_gallery_inside_after_measures_non_zero_after_the_first_press(page, live_server):
    """Mutant: drop the libli:reveal dispatch -> the gallery keeps the zero height
    it measured while hidden.
    """
    ...


@pytest.mark.django_db(transaction=True)
def test_no_heading_flash_on_a_normal_load(page, live_server):
    """Mutant: set ba-js from the module instead of the prepaint script -> the
    headings paint visible, then vanish.
    """
    ...


@pytest.mark.django_db(transaction=True)
def test_editor_slots_accept_a_child_each(page, live_server):
    ...


@pytest.mark.django_db(transaction=True)
def test_editor_row_renders_for_a_NESTED_instance(page, live_server):
    """Mutant: gate the row branch on el.parent_id is None -> RED."""
    ...


@pytest.mark.django_db(transaction=True)
def test_preview_toggle_is_visible_and_works(page, live_server):
    """Mutant: omit editor.html's ba-js prepaint block -> html:not(.ba-js)
    .ba__toggle hides it. The "toggles after a swap" assertion alone cannot
    distinguish this from "not wired".
    """
    ...


@pytest.mark.django_db(transaction=True)
def test_preview_toggle_still_works_after_a_fragment_swap(page, live_server):
    """Edit a DIFFERENT element (forcing a preview fragment swap), then toggle.

    Mutants: omit the editor.js re-init call -> the button is dead after the
    swap; break the dataset.baReady guard -> the handler is double-bound and one
    click swaps twice (back to where it started).
    """
    ...


@pytest.mark.django_db(transaction=True)
def test_preview_re_init_does_not_touch_html_classes(page, live_server):
    """libliInitBeforeAfter is initAll -- the root-scoped ENHANCER, not the
    document-level boot. The editor page has no ba-armed at all.

    Mutant: bind the export to the document-level boot -> re-init throws on the
    absent class or re-runs once-only work on every swap.
    """
    before = page.evaluate("document.documentElement.className")
    ...  # trigger a fragment swap
    assert page.evaluate("document.documentElement.className") == before
```

Fill in every body — the skeletons above are the required coverage, not the deliverable. Drive the **real UI** (click the actual button); do not call JS directly. Sync on conditions (`expect(...).to_be_visible()`), never `sleep`.

- [ ] **Step 2: Run the e2e suite**

```bash
uv run pytest tests/test_e2e_before_after.py -m e2e -v
```
Expected: PASS. `-m e2e` is mandatory — without it every test silently deselects and pytest exits 5.

- [ ] **Step 3: Falsify the two highest-value tests**

Temporarily remove the pre-hide `<style>`, re-run `test_after_is_not_visible_while_the_script_is_pending`, and **confirm it goes RED**. Restore. Then change `__baDisarm` to remove only the classes, re-run `test_recovery_clears_hidden_not_just_the_html_classes`, confirm RED, restore. A passing test proves nothing until you have seen it fail.

- [ ] **Step 4: Screenshots**

Capture the element in **light and dark**, judged separately: normal state, after pressing, and the no-JS fallback. The 2px rule is decorative (not held to AA text contrast, and its `color-mix` is ported verbatim from a shipped rule); what must clear AA is the button's label and icon.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_before_after.py
git commit -m "test(before-after): end-to-end toggle, pre-hide, recovery and editor coverage"
```

---

## Task 14: Help docs and translations

**Files:**
- Modify: `docs/help/course-admin/content-editors.md` (`:115` area, `:146`, `:155`, `:163`)
- Modify: `docs/help/course-admin/content-editors.pl.md` (the same four places)
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`

- [ ] **Step 1: Add the element to the help manual**

In `docs/help/course-admin/content-editors.md`, add a `{el:beforeafter}` paragraph in the Content section describing what the element does and that quiz questions cannot go inside it. Then fix **three enumerations this feature falsifies**:

- `:146` "Tabs, Columns, Spoiler, and Callout are the four container types" → five, naming Before / after;
- `:155` the nested add-menu list;
- `:163` the quiz-specific list (Before / after **is** offered in quiz units — it is in the Content group).

Mirror all four edits in `content-editors.pl.md`.

- [ ] **Step 2: Regenerate the catalogues**

```bash
uv run python manage.py makemessages -l en -l pl
```

- [ ] **Step 3: Fill in the Polish translations**

| msgid | Polish |
| --- | --- |
| `Before / after` | `Przed / po` |
| `Before` | `Przed` |
| `After` | `Po` |
| `Switch content` | `Zmień treść` |
| `Button label` | `Etykieta przycisku` |
| `No content yet` | `Brak treści` |
| `before/after data` | `dane przed/po` |

**Clear every `#, fuzzy` marker** on these entries. `makemessages` pre-fills a fuzzy translation from a similar string, and a fuzzy entry ships the **wrong** text — clearing it means deleting both the `#, fuzzy` line and the wrong `msgstr`.

- [ ] **Step 4: Compile and verify**

```bash
uv run python manage.py compilemessages
uv run pytest tests/test_help.py -v
```
Expected: PASS.

Load the editor with `?lang=pl` (or the project's language switch) and confirm the card reads "Przed / po".

- [ ] **Step 5: Commit**

```bash
git add docs/help/ locale/
git commit -m "docs(before-after): help manual entry and Polish translations"
```

---

## Task 15: Branch gate

**Files:** none — verification only.

- [ ] **Step 1: Lint**

```bash
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 2: Migration check**

```bash
uv run python manage.py makemigrations --check --dry-run
```
Expected: "No changes detected".

- [ ] **Step 3: Re-check the migration head**

```bash
git fetch origin && git log origin/master --oneline -- courses/migrations/ | head -5
```
If another branch has landed `0055`, **renumber ours**. Two branches both minting `0055` merge without a git conflict — the same silent-merge hazard that keeps `FORMAT_VERSION` at 9.

- [ ] **Step 4: Full unit suite**

```bash
uv run pytest -m "not e2e" -q
```
Expected: PASS. This is the branch gate — the first whole-repo run in the plan, deliberately not a per-task step.

- [ ] **Step 5: Full e2e suite**

```bash
uv run pytest -m e2e -n 2 -q
```
`-n 2`, not `-n 8` — higher parallelism is measurably **slower** here. This run takes ~50 minutes; launch it detached (`Start-Process`) and poll the PID rather than backgrounding it through the harness, which reaps long-running pytest mid-run and orphans the test database.

- [ ] **Step 6: Commit any fixes**

```bash
git commit -am "fix(before-after): branch-gate fixes"
```

---

## Self-review

**Spec coverage.** Every numbered spec section maps to a task: §1 → 1, §2 → 2/4/12, §3 → 2, §4 → 2/5/12, §5.1-5.3 → 5, §5.4 → 6, §5.5 → 12, §6 → 5, §7 → 7, §8 → 8/9/10/11, §9 (math) → **see below**, §10 → 14, §11 → 4. Error-handling table → Tasks 5, 12, 13. Testing table → distributed, with the e2e rows in 13.

**Gap found and closed:** spec §9 (`_before_after_has_math`) had no task. It is **added as Task 4a below** rather than renumbering.

**Placeholders:** the e2e bodies in Task 13 are deliberately skeletal — the required coverage and every mutant are named, and Step 1 says explicitly to fill each body. All other steps carry real code.

**Type consistency:** `resolved_slots()` returns `[(slot_id, children)]` everywhere (Tasks 1, 2, 4, 9). `SLOT_IDS` order is the contract in all four. `eid` is `element.pk` in Tasks 1 and 2. `window.libliInitBeforeAfter` = `initAll` in Tasks 5 and 11.

---

## Task 4a: Math detection

**Runs after Task 5** (see the execution order in Global Constraints).

**Files:**
- Modify: `courses/views.py` (`_element_has_math` `:176-222`; new helper beside `_twocolumn_has_math` `:298`)
- Create: `courses/tests/test_beforeafter_math.py` — its **own** file with its own imports
  and its own copy of the `lesson_unit_node` / `student_user` fixtures (they are
  file-local everywhere; there is no `courses/tests/conftest.py`). Written this way so
  this task has no ordering dependency on Task 5's file.

Without this, KaTeX's CSS and JS never load for a unit whose only math sits inside a before/after, and `\(…\)` renders literally. "An equation before and after simplification" is a headline use case in the spec's Purpose.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
def test_has_math_finds_math_nested_in_a_panel(lesson_unit_node, student_user):
    """Mutant: make _before_after_has_math non-recursive -> KaTeX never loads and
    the lesson ships raw LaTeX.
    """
    from courses.models import MathElement
    from courses.views import build_lesson_context

    join = Element.objects.create(
        unit=lesson_unit_node, content_object=BeforeAfterElement.objects.create()
    )
    Element.objects.create(
        unit=lesson_unit_node,
        content_object=MathElement.objects.create(latex="x^2"),
        parent=join,
        tab_id=BeforeAfterElement.AFTER_SLOT_ID,
    )
    assert build_lesson_context(lesson_unit_node, student_user)["has_math"] is True
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest courses/tests/test_beforeafter_context.py -k math -v
```
Expected: FAIL — `has_math is False`.

- [ ] **Step 3: Add the helper**

Model it on `_twocolumn_has_math` (`:298-311`), **not** `_callout_has_math`. The callout's transient guard sits *after* its heading/body checks, and its own docstring (`:270-274`) says a top-of-function guard is "correct in `_twocolumn_has_math`, which has no text of its own". `BeforeAfterElement` likewise has no text of its own — `button_label` is plain text with no math by decision:

```python
def _before_after_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _twocolumn_has_math. has_math consumes the
    element list AFTER the render filter strips nested children, so it walks into
    them here. The transient guard sits at the top because this element has no
    text of its own to check first."""
    from courses.models import BeforeAfterElement

    if not isinstance(el, BeforeAfterElement):
        return False
    # No redundant `join_row() is None` guard: resolved_slots() already returns
    # empty pairs for a transient join row, and calling join_row() here would
    # issue the SAME query twice per element on every lesson render.
    return any(
        _element_has_math(child.content_object)
        for _slot_id, children in el.resolved_slots()
        for child in children
    )
```

- [ ] **Step 4: Wire it into the dispatcher**

Writing the helper is not enough — unwired it is dead code and the bug survives. `_element_has_math` wires helpers two ways: explicit `isinstance` clauses at `:200-203` (spoiler, callout) and the trailing `return _table_has_math(obj) or …` chain at `:216-221` (two-column). Use an **explicit clause beside the spoiler/callout ones** — the closer match, and unmissable:

```python
    if isinstance(obj, BeforeAfterElement):
        return _before_after_has_math(obj)
```

- [ ] **Step 5: Run the test**

```bash
uv run pytest courses/tests/test_beforeafter_context.py -v
```
Expected: PASS.

`math.js`'s scope list (`courses/static/courses/js/math.js:31`) is deliberately **unchanged**: children are rendered elements (`.el--text` etc.) already covered by it, and `button_label` is plain text by decision.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/tests/test_beforeafter_context.py
git commit -m "feat(before-after): recurse into both slots for math detection"
```

---

**Execution order** is stated in Global Constraints at the top of this document:
**1 → 2 → 3 → 4 → 5 → 4a → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15.**

Tasks 3 and 4 are coupled (`test_nestable_keys_are_a_subset_of_serializers` spans both) and 8–11 are coupled (the editor path is not exercisable until 11). Everything else is independently verifiable at its own commit.
