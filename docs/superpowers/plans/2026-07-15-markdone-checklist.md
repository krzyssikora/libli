# Mark-done checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `MarkDoneElement` self-tracking checklist content element whose per-student ticks persist server-side on `UnitProgress`.

**Architecture:** A new `ElementBase` subclass with an inline `MarkDoneItem` formset (mirrors `StepperElement`), rendered no-JS-correct with server-side checked state. Persistence rides a new `UnitProgress.checklist_state` JSONField, written by a new `markdone_save` endpoint. Because generic content elements have no per-student render context today, this plan **builds** that seam: `ElementBase.render` gains `checklist`/`slug`/`node_pk` kwargs, `render_element` reads them from the template context and passes them, existing zero-arg `render()` overrides absorb them, and container renders re-inject them into their isolated `render_to_string` context.

**Tech Stack:** Django 5.2, server-rendered templates, vanilla JS enhancers, Postgres, pytest, ruff, uv.

## Global Constraints

- Full design + rationale: `docs/superpowers/specs/2026-07-15-markdone-checklist-design.md`. Read it before starting — this plan is the HOW, the spec is the WHY (esp. the "Context plumbing" section).
- **No-JS invariant:** every element renders a working no-JS fallback; server renders correct state on every load.
- **Ungraded, lesson-only, nestable:** no marks, no correct answers; hidden when `unit_is_quiz`; nestable in tabs / two-column.
- **pk spaces:** `checklist_state` and the posted `element` payload use the **content-object pk** (`MarkDoneElement.pk`). Seen-tracking uses the **Element join-row pk** — never emit a leaf `data-element-id`.
- **Tooling:** run everything through `uv run` (e.g. `uv run pytest`, `uv run ruff`, `uv run python manage.py …`). bash `ruff`/`pytest`/`python` are NOT on PATH.
- **Per-task hygiene:** end every task with `uv run ruff check --fix . && uv run ruff format .` then `uv run python manage.py makemigrations --check --dry-run` + `uv run python manage.py check`. Run the heavy suite `uv run pytest -m "not e2e" -n auto` (serial exceeds subagent watchdog). Run e2e single-file FOREGROUND with `-m e2e` only.
- **Class constants:** `MarkDoneElement.MIN_ITEMS = 1`, `MAX_ITEMS = 20`, `MAX_LEN = 500`.
- **Transfer key** `mark_done` (snake_case) ≠ **form key** `markdone`. Do **not** bump `FORMAT_VERSION`.
- Isolate the test DB per worktree (unique `DATABASE_URL`) if running concurrently with other worktrees.

---

## File Structure

**Create:**
- `courses/migrations/0048_markdone.py` (generated) — MarkDoneElement, MarkDoneItem, UnitProgress.checklist_state.
- `templates/courses/elements/markdoneelement.html` — student render.
- `templates/courses/manage/editor/_edit_markdone.html` — editor partial.
- `courses/static/courses/js/markdone.js` — student enhancer (auto-save).
- `courses/static/courses/js/markdone_editor.js` — add-row enhancer.
- `courses/tests/test_markdone*.py` + `tests/test_e2e_markdone.py`.

**Modify:** `courses/models.py`, `courses/element_forms.py`, `courses/builder.py`, `courses/views.py`, `courses/urls.py`, `courses/views_manage.py`, `courses/templatetags/courses_extras.py`, `courses/templatetags/courses_manage_extras.py`, `courses/transfer/{export,payloads,importer}.py`, `courses/static/courses/js/{math,editor}.js`, `templates/courses/lesson_unit.html`, `templates/courses/manage/editor/{_add_menu,editor,_host_form check}.html`, `templates/courses/elements/{tabselement,twocolumnelement}.html` (no change expected — verify), plus test count asserts.

---

### Task 1: Models + migration + ELEMENT_MODELS

**Files:**
- Modify: `courses/models.py` (add `MarkDoneElement`, `MarkDoneItem`; add `"markdoneelement"` to `ELEMENT_MODELS`; add `checklist_state` to `UnitProgress`)
- Create: `courses/migrations/0048_markdone.py` (generated)
- Test: `courses/tests/test_markdone_models.py`

**Interfaces:**
- Produces: `MarkDoneElement(ElementBase)` with `prompt: CharField`, `MIN_ITEMS=1`, `MAX_ITEMS=20`, `MAX_LEN=500`, `items` reverse rel; `MarkDoneItem(element FK related_name="items", content, order)`; `UnitProgress.checklist_state: dict`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_markdone_models.py
import pytest
from courses.models import ELEMENT_MODELS, MarkDoneElement, MarkDoneItem, UnitProgress

pytestmark = pytest.mark.django_db


def test_markdone_element_and_items_order_and_strip():
    el = MarkDoneElement.objects.create(prompt="  do these  ")
    assert el.prompt == "do these"  # stripped in save()
    a = MarkDoneItem.objects.create(element=el, content="  first ")
    b = MarkDoneItem.objects.create(element=el, content="second")
    assert a.content == "first"  # stripped
    assert [i.pk for i in el.items.all()] == [a.pk, b.pk]  # order 0,1
    assert a.order == 0 and b.order == 1


def test_markdone_class_constants():
    assert (MarkDoneElement.MIN_ITEMS, MarkDoneElement.MAX_ITEMS, MarkDoneElement.MAX_LEN) == (1, 20, 500)


def test_element_models_includes_markdone():
    assert "markdoneelement" in ELEMENT_MODELS


def test_unit_progress_checklist_state_defaults_to_dict():
    from tests.factories import make_verified_user  # existing factory
    from courses.models import ContentNode, Course, Subject
    # minimal: checklist_state default is an empty dict
    up = UnitProgress()
    assert up.checklist_state == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_models.py -x`
Expected: FAIL (ImportError: cannot import name 'MarkDoneElement').

- [ ] **Step 3: Add the models (mirror StepperElement at `courses/models.py:403-436`)**

Add after `StepperStep` (near line 436):

```python
class MarkDoneElement(ElementBase):
    """Self-tracking checklist: an optional prompt + an ordered list of short statement
    items the student ticks to record "I've done this". Ungraded, lesson-only, nestable.
    Ticks persist per-student in UnitProgress.checklist_state (keyed by this element's pk)."""

    MIN_ITEMS = 1
    MAX_ITEMS = 20
    MAX_LEN = 500

    prompt = models.CharField(max_length=MAX_LEN, blank=True)
    elements = GenericRelation(Element)  # cascade join-row cleanup

    def save(self, *args, **kwargs):
        self.prompt = (self.prompt or "").strip()
        super().save(*args, **kwargs)


class MarkDoneItem(models.Model):
    element = models.ForeignKey(
        MarkDoneElement, on_delete=models.CASCADE, related_name="items"
    )
    content = models.CharField(max_length=MarkDoneElement.MAX_LEN)  # plain text + KaTeX
    order = OrderField(for_fields=["element"], blank=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.content

    def save(self, *args, **kwargs):
        self.content = (self.content or "").strip()
        super().save(*args, **kwargs)
```

Add `"markdoneelement"` to `ELEMENT_MODELS` (`courses/models.py:259`), after `"twocolumnelement"`.

Add to `UnitProgress` (after `seen_element_ids`, `courses/models.py:1906`):

```python
    # Per-element checklist ticks: {"<MarkDoneElement.pk>": [<MarkDoneItem.pk>, ...]}.
    checklist_state = models.JSONField(default=dict)
```

- [ ] **Step 4: Generate migration + run tests**

Run: `uv run python manage.py makemigrations courses` (accept the name, or `--name markdone`). Confirm it adds `MarkDoneElement`, `MarkDoneItem`, and `UnitProgress.checklist_state`. Do NOT hand-edit the number; on the current `master` base it is `0048`.

Run: `uv run pytest courses/tests/test_markdone_models.py -x`
Expected: PASS.

- [ ] **Step 5: Update the ELEMENT_MODELS count assert**

`tests/test_transfer_schema.py:11` — read the current value (29 on this base) and bump to 30. Verify with `uv run pytest tests/test_transfer_schema.py -x` (it may fail later assertions until transfer is wired in Task 9 — if so, only run the length assert here: `uv run pytest tests/test_transfer_schema.py -k length -x` or note the expected transfer failures to fix in Task 9).

- [ ] **Step 6: Hygiene + commit**

Run: `uv run ruff check --fix . && uv run ruff format . && uv run python manage.py makemigrations --check --dry-run && uv run python manage.py check`
Expected: all clean.

```bash
git add courses/models.py courses/migrations/0048_markdone.py courses/tests/test_markdone_models.py tests/test_transfer_schema.py
git commit -m "feat(markdone): models + checklist_state + ELEMENT_MODELS entry"
```

---

### Task 2: Forms + save_element branch

**Files:**
- Modify: `courses/element_forms.py` (form stack + `FORM_FOR_TYPE`)
- Modify: `courses/builder.py` (`save_element` markdone branch)
- Test: `courses/tests/test_markdone_forms.py`

**Interfaces:**
- Consumes: `MarkDoneElement`, `MarkDoneItem` (Task 1).
- Produces: `MarkDoneElementForm`, `build_markdone_formset(*, data, files, instance, prefix="items")`, `FORM_FOR_TYPE["markdone"]`; `save_element(course, unit_pk, "markdone", ...)` persisting element + ordered items.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_markdone_forms.py
import pytest
from courses.element_forms import MarkDoneElementForm, build_markdone_formset
from courses.models import MarkDoneElement

pytestmark = pytest.mark.django_db


def _post(prompt="Prep", items=("a", "b"), total=None):
    total = len(items) if total is None else total
    data = {"prompt": prompt, "items-TOTAL_FORMS": str(total),
            "items-INITIAL_FORMS": "0", "items-MIN_NUM_FORMS": "0", "items-MAX_NUM_FORMS": "1000"}
    for i, c in enumerate(items):
        data[f"items-{i}-content"] = c
    return data


def test_formset_requires_at_least_one_item():
    data = _post(items=(), total=0)
    form = MarkDoneElementForm(data=data)
    fs = build_markdone_formset(data=data, instance=MarkDoneElement())
    assert form.is_valid()
    assert not fs.is_valid()  # MIN_ITEMS violated


def test_valid_form_and_formset():
    data = _post()
    form = MarkDoneElementForm(data=data)
    fs = build_markdone_formset(data=data, instance=MarkDoneElement())
    assert form.is_valid() and fs.is_valid()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_forms.py -x`
Expected: FAIL (ImportError).

- [ ] **Step 3: Add the form stack (mirror Stepper at `courses/element_forms.py:1486-1540`)**

```python
class MarkDoneElementForm(forms.ModelForm):
    class Meta:
        model = MarkDoneElement
        fields = ["prompt"]


class MarkDoneItemForm(forms.ModelForm):
    class Meta:
        model = MarkDoneItem
        fields = ["content"]


class BaseMarkDoneFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        kept = 0
        for f in self.forms:
            cd = f.cleaned_data
            if not cd or cd.get("DELETE"):
                continue
            if (cd.get("content") or "").strip():
                kept += 1
        if not (MarkDoneElement.MIN_ITEMS <= kept <= MarkDoneElement.MAX_ITEMS):
            from django.core.exceptions import ValidationError
            raise ValidationError(
                _("A checklist needs between %(lo)s and %(hi)s items."),
                params={"lo": MarkDoneElement.MIN_ITEMS, "hi": MarkDoneElement.MAX_ITEMS},
            )


MarkDoneItemFormSet = inlineformset_factory(
    MarkDoneElement, MarkDoneItem,
    form=MarkDoneItemForm, formset=BaseMarkDoneFormSet,
    fields=["content"], extra=1, can_delete=True,
)


def build_markdone_formset(*, data=None, files=None, instance=None, prefix="items"):
    return MarkDoneItemFormSet(data=data, files=files, instance=instance, prefix=prefix)
```

Add `"markdone": MarkDoneElementForm,` to `FORM_FOR_TYPE` (`courses/element_forms.py:1543-1573`). Add the imports for `MarkDoneElement`, `MarkDoneItem` at the top of the file (mirror how `StepperElement`/`StepperStep` are imported). Ensure `_` is `gettext_lazy` (it is, module-wide) so the validation string isn't frozen.

- [ ] **Step 4: Add the save_element branch (mirror Stepper at `courses/builder.py:599-628`)**

Insert an `elif type_key == "markdone":` branch:

```python
    elif type_key == "markdone":
        from courses.element_forms import MarkDoneElementForm, build_markdone_formset

        form = MarkDoneElementForm(data=post_data, instance=instance)
        form_valid = form.is_valid()
        formset = build_markdone_formset(data=post_data, files=files, instance=instance)
        if not form_valid or not formset.is_valid():
            raise ElementFormInvalid(form, formset)
        obj = form.save()
        formset.instance = obj
        idx = 0
        for f in formset.forms:
            cd = f.cleaned_data
            if not cd:
                continue
            if cd.get("DELETE"):
                if f.instance.pk:
                    f.instance.delete()
                continue
            if not (cd.get("content") or "").strip():
                if f.instance.pk:
                    f.instance.delete()
                continue
            f.instance.element = obj
            f.instance.content = cd["content"]
            f.instance.order = idx
            f.instance.save()
            idx += 1
```

- [ ] **Step 5: Add a save_element persistence test + run**

```python
def test_save_element_persists_ordered_items(db):
    from courses.builder import save_element
    from tests.factories import make_course_with_unit  # use the project's helper; else build a course+unit
    course, unit = make_course_with_unit()
    data = _post(items=("one", "", "three"), total=3)  # blank middle row dropped
    data["unit_token"] = unit.updated.isoformat()
    save_element(course, unit.pk, "markdone", element_ref="new", post_data=data, files=None)
    el = MarkDoneElement.objects.latest("pk")
    assert [i.content for i in el.items.all()] == ["one", "three"]
    assert [i.order for i in el.items.all()] == [0, 1]
```

> NOTE: use the project's real course/unit factory (grep `def make_course` / existing element tests, e.g. `courses/tests/test_stepper*`). Match the exact `save_element` signature and required `post` keys (e.g. `unit_token`) used by the stepper save test.

Run: `uv run pytest courses/tests/test_markdone_forms.py -x`
Expected: PASS.

- [ ] **Step 6: Hygiene + commit**

```bash
git add courses/element_forms.py courses/builder.py courses/tests/test_markdone_forms.py
git commit -m "feat(markdone): forms + save_element branch"
```

---

### Task 3: Build the per-student render seam (signatures only)

**Files:**
- Modify: `courses/models.py` (`ElementBase.render`; the six zero-arg `render()` overrides; `TabsElement.render`, `TwoColumnElement.render`)
- Modify: `courses/templatetags/courses_extras.py` (`render_element` generic branch)
- Modify: `templates/courses/elements/tabselement.html`, `templates/courses/elements/twocolumnelement.html` (VERIFY no change needed)
- Test: `courses/tests/test_render_seam.py`

**Interfaces:**
- Produces: `ElementBase.render(self, *, checklist=None, slug=None, node_pk=None)` putting `checked`/`slug`/`node_pk` into leaf context; every generic-dispatched `render()` tolerates these kwargs; containers inject `checklist`/`slug`/`node_pk` into their `render_to_string` context.

- [ ] **Step 1: Write the failing test** (renders existing elements through the new kwargs — must not raise)

```python
# courses/tests/test_render_seam.py
import pytest
from courses.models import ElementBase

pytestmark = pytest.mark.django_db


def test_elementbase_render_accepts_context_kwargs():
    # A plain content element (TextElement) must accept the new kwargs and ignore them.
    from courses.models import TextElement
    el = TextElement.objects.create(body="hi")
    html = el.render(checklist={}, slug="x", node_pk=1)
    assert "hi" in html


def test_zero_arg_override_absorbs_kwargs():
    # e.g. GalleryElement overrides render(self); it must not TypeError on kwargs.
    from courses.models import GalleryElement
    g = GalleryElement.objects.create()
    g.render(checklist={}, slug="x", node_pk=1)  # no TypeError
```

> Adjust constructors to the real minimal-valid form for `TextElement`/`GalleryElement` (grep their tests). The point is: `render(**those_kwargs)` must not raise.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_render_seam.py -x`
Expected: FAIL (`render() got an unexpected keyword argument 'checklist'`).

- [ ] **Step 3: Change `ElementBase.render` (`courses/models.py:338`)**

```python
    def render(self, *, checklist=None, slug=None, node_pk=None):
        name = self._meta.model_name
        return render_to_string(
            f"courses/elements/{name}.html",
            {
                "el": self,
                "checked": (checklist or {}).get(self.pk, set()),
                "slug": slug,
                "node_pk": node_pk,
            },
        )
```

- [ ] **Step 4: Make the six zero-arg overrides tolerant**

For each of `FillGateElement.render`, `SwitchGateElement.render`, `SwitchGridElement.render`, `TableElement.render`, `FillTableElement.render`, `GalleryElement.render` (grep `def render(self):` in `courses/models.py`), change the signature to absorb the kwargs:

```python
    def render(self, **_kwargs):   # was: def render(self):
        ...
```

(`HtmlElement.render(self, unit, course, theme=None)` and `QuestionElement.render(...)` are on their own `render_element` branches — leave them.)

- [ ] **Step 5: Container renders accept + inject (`courses/models.py`)**

`TabsElement.render` (~:1057):

```python
    def render(self, *, checklist=None, slug=None, node_pk=None):
        from django.template.loader import render_to_string

        join = self.join_row()
        return render_to_string(
            "courses/elements/tabselement.html",
            {
                "el": self, "tabs": self.resolved_tabs(),
                "eid": join.pk if join else 0,
                "checklist": checklist, "slug": slug, "node_pk": node_pk,
            },
        )
```

`TwoColumnElement.render` — same treatment: accept `*, checklist=None, slug=None, node_pk=None` and add those three keys to its `render_to_string` context dict.

- [ ] **Step 6: `render_element` generic branch (`courses/templatetags/courses_extras.py:62`)**

```python
    return mark_safe(  # noqa: S308 — each element template escapes its own fields
        obj.render(
            checklist=context.get("checklist"),
            slug=context.get("slug"),
            node_pk=context.get("node_pk"),
        )
    )
```

(Do NOT add tag parameters; `render_element` reads from `context`. The Html/Question branches above are unchanged.)

- [ ] **Step 7: Verify container templates need no change**

Confirm `tabselement.html:20` and `twocolumnelement.html:14` call `{% render_element child %}` bare. They do — because step 5 re-injects `checklist`/`slug`/`node_pk` into the container's `render_to_string` context, `render_element` (takes_context) reads them there. No template edit.

- [ ] **Step 8: Run tests**

Run: `uv run pytest courses/tests/test_render_seam.py -x`
Expected: PASS. Also run a broad render smoke: `uv run pytest -m "not e2e" -n auto -k "lesson or render or element"` — no TypeErrors from any element type.

- [ ] **Step 9: Hygiene + commit**

```bash
git add courses/models.py courses/templatetags/courses_extras.py courses/tests/test_render_seam.py
git commit -m "feat(markdone): thread per-student checklist context through render seam"
```

---

### Task 4: build_lesson_context map + student template

**Files:**
- Modify: `courses/views.py` (`build_lesson_context`: `checklist`, `slug`, `node_pk`, `has_markdone`)
- Create: `templates/courses/elements/markdoneelement.html`
- Test: `courses/tests/test_markdone_render.py`

**Interfaces:**
- Consumes: render seam (Task 3), models (Task 1).
- Produces: lesson context keys `checklist` (int-keyed `{content_pk: {item_pk}}`), `slug`, `node_pk`, `has_markdone`; the leaf template.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_markdone_render.py
import pytest
from django.urls import reverse
from courses.models import MarkDoneElement, MarkDoneItem, UnitProgress

pytestmark = pytest.mark.django_db


def test_enrolled_student_sees_checked_items(client):
    from tests.factories import make_course_with_unit, enroll, make_verified_user, TEST_PASSWORD
    course, unit = make_course_with_unit(lesson=True)
    el = MarkDoneElement.objects.create(prompt="Prep")
    # attach el to unit via the Element join-row exactly as other element tests do:
    attach_element(unit, el)  # replace with the project helper / builder call
    i1 = MarkDoneItem.objects.create(element=el, content="one")
    i2 = MarkDoneItem.objects.create(element=el, content="two")
    student = make_verified_user()
    enroll(student, course)
    UnitProgress.objects.create(student=student, unit=unit,
                                checklist_state={str(el.pk): [i1.pk]})
    client.force_login(student)
    resp = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk]))
    body = resp.content.decode()
    assert 'name="element" value="%d"' % el.pk in body
    # i1 checked + on; i2 not
    assert f'value="{i1.pk}"' in body and "checked" in body
    assert "markdone__item on" in body
```

> Replace `attach_element` / `make_course_with_unit(lesson=True)` / `enroll` with the project's real helpers (grep an existing lesson render test, e.g. `courses/tests/test_stepper_render*` or `tests/test_*lesson*`). Mirror exactly how they attach a content element to a unit.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_render.py -x`
Expected: FAIL (TemplateDoesNotExist: markdoneelement.html).

- [ ] **Step 3: Create the leaf template**

```html
{# templates/courses/elements/markdoneelement.html #}
{% load i18n %}
{% url 'courses:markdone_save' slug=slug node_pk=node_pk as save_url %}
<div class="markdone" data-markdone data-markdone-url="{{ save_url }}">
  <form method="post" action="{{ save_url }}#markdone-{{ el.pk }}" id="markdone-{{ el.pk }}">
    {% csrf_token %}
    <input type="hidden" name="element" value="{{ el.pk }}">
    {% if el.prompt %}<p class="markdone__prompt">{{ el.prompt }}</p>{% endif %}
    <ul class="markdone__list">
      {% for item in el.items.all %}
        <li class="markdone__item{% if item.pk in checked %} on{% endif %}">
          <label>
            <input type="checkbox" name="item" value="{{ item.pk }}"
                   {% if item.pk in checked %}checked{% endif %}>
            <span class="markdone__text">{{ item.content }}</span>
          </label>
        </li>
      {% endfor %}
    </ul>
    <button type="submit" class="btn btn--small markdone__save" data-markdone-save>{% trans "Save" %}</button>
  </form>
</div>
```

- [ ] **Step 4: Extend `build_lesson_context` (`courses/views.py:243-355`)**

Add the `has_markdone` flat query alongside `has_stepper` (~:323):

```python
    has_markdone = node.elements.filter(content_type__model="markdoneelement").exists()
```

In the enrolled branch (~:327-329), build the int-keyed checklist map from stored state:

```python
    progress = None
    seen_ids = set()
    checklist = {}
    if is_enrolled(user, node.course):
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
        checklist = {
            int(k): {int(v) for v in vals}
            for k, vals in (progress.checklist_state or {}).items()
        }
```

Add `checklist`, `slug`, `node_pk`, `has_markdone` to the returned dict:

```python
        "has_stepper": has_stepper,
        "has_markdone": has_markdone,
        "checklist": checklist,
        "slug": node.course.slug,
        "node_pk": node.pk,
```

Add a prefetch for items alongside the other prefetches (so `el.items.all` and math scan don't N+1):

```python
    markdone_els = [e.content_object for e in elements
                    if e.content_object.__class__.__name__ == "MarkDoneElement"]
    if markdone_els:
        prefetch_related_objects(markdone_els, "items")
```

> The `checklist` map is keyed by **content-object pk**; `render_element`→`ElementBase.render` looks it up by `self.pk` (the content object). Consistent with the template's `value="{{ el.pk }}"` and the endpoint's `checklist_state` key.

- [ ] **Step 5: Add a nested-render test** (proves the container injection from Task 3 reaches a nested checklist)

```python
def test_nested_in_tabs_checklist_resolves_checked(client):
    # Build a TabsElement with a MarkDoneElement child (mirror an existing nested-in-tabs test),
    # store a tick, GET the lesson, assert the nested item renders checked + `on`.
    ...
```

> Model this on an existing "nested in tabs" test (grep `tab` in `courses/tests/`, e.g. stepper/spoiler nesting tests). Attach the MarkDone as a tab child, store `checklist_state`, assert `checked` + `markdone__item on` appear.

- [ ] **Step 6: Run tests**

Run: `uv run pytest courses/tests/test_markdone_render.py -x`
Expected: PASS.

- [ ] **Step 7: Hygiene + commit**

```bash
git add courses/views.py templates/courses/elements/markdoneelement.html courses/tests/test_markdone_render.py
git commit -m "feat(markdone): lesson checklist map + student render (top-level + nested)"
```

---

### Task 5: markdone_save endpoint + URL

**Files:**
- Modify: `courses/views.py` (add `markdone_save`)
- Modify: `courses/urls.py` (add route)
- Test: `courses/tests/test_markdone_endpoint.py`

**Interfaces:**
- Consumes: models (Task 1), `can_access_course`/`is_enrolled`/`get_node_or_404` (existing, used by `seen`).
- Produces: `POST courses/<slug>/u/<node_pk>/markdone/` → JSON `{element, items}` / redirect.

- [ ] **Step 1: Write the failing tests**

```python
# courses/tests/test_markdone_endpoint.py
import json
import pytest
from django.urls import reverse
from courses.models import MarkDoneElement, MarkDoneItem, UnitProgress

pytestmark = pytest.mark.django_db


def _url(course, unit):
    return reverse("courses:markdone_save", args=[course.slug, unit.pk])


def _setup():
    from tests.factories import make_course_with_unit, enroll, make_verified_user
    course, unit = make_course_with_unit(lesson=True)
    el = MarkDoneElement.objects.create(prompt="P")
    attach_element(unit, el)  # project helper
    i1 = MarkDoneItem.objects.create(element=el, content="a")
    i2 = MarkDoneItem.objects.create(element=el, content="b")
    student = make_verified_user()
    enroll(student, course)
    return course, unit, el, i1, i2, student


def test_enrolled_json_persists(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    r = client.post(_url(course, unit), data=json.dumps({"element": el.pk, "items": [i1.pk]}),
                    content_type="application/json")
    assert r.status_code == 200 and r.json() == {"element": el.pk, "items": [i1.pk]}
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.checklist_state == {str(el.pk): [i1.pk]}


def test_no_js_form_persists(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    r = client.post(_url(course, unit), data={"element": el.pk, "item": [i1.pk, i2.pk]})
    assert r.status_code in (302, 303)
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert set(up.checklist_state[str(el.pk)]) == {i1.pk, i2.pk}


def test_empty_selection_drops_key(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    UnitProgress.objects.create(student=student, unit=unit, checklist_state={str(el.pk): [i1.pk]})
    r = client.post(_url(course, unit), data=json.dumps({"element": el.pk, "items": []}),
                    content_type="application/json")
    assert r.status_code == 200
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert str(el.pk) not in up.checklist_state


def test_forged_item_filtered_and_forged_element_400(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    # forged item pk dropped
    r = client.post(_url(course, unit), data=json.dumps({"element": el.pk, "items": [i1.pk, 999999]}),
                    content_type="application/json")
    assert r.json()["items"] == [i1.pk]
    # forged element pk -> 400
    r2 = client.post(_url(course, unit), data=json.dumps({"element": 999999, "items": []}),
                     content_type="application/json")
    assert r2.status_code == 400


def test_non_list_items_never_500(client):
    course, unit, el, i1, i2, student = _setup()
    client.force_login(student)
    r = client.post(_url(course, unit), data=json.dumps({"element": el.pk, "items": "abc"}),
                    content_type="application/json")
    assert r.status_code == 200 and r.json()["items"] == []


def test_non_enrolled_no_write(client):
    from tests.factories import make_verified_user
    course, unit, el, i1, i2, _student = _setup()
    other = make_verified_user()  # not enrolled
    client.force_login(other)
    # requires can_access_course true but not enrolled; if access requires enrollment,
    # use a previewer/author per the project's access rules.
    r = client.post(_url(course, unit), data=json.dumps({"element": el.pk, "items": [i1.pk]}),
                    content_type="application/json")
    assert not UnitProgress.objects.filter(unit=unit, student=other).exists() or \
        UnitProgress.objects.get(unit=unit, student=other).checklist_state == {}


def test_merge_not_clobber(client):
    """Two elements' saves both survive -> read-modify-write, not whole-dict overwrite."""
    course, unit, el, i1, i2, student = _setup()
    el2 = MarkDoneElement.objects.create(prompt="P2")
    attach_element(unit, el2)
    j1 = MarkDoneItem.objects.create(element=el2, content="x")
    client.force_login(student)
    client.post(_url(course, unit), data=json.dumps({"element": el.pk, "items": [i1.pk]}),
                content_type="application/json")
    client.post(_url(course, unit), data=json.dumps({"element": el2.pk, "items": [j1.pk]}),
                content_type="application/json")
    up = UnitProgress.objects.get(student=student, unit=unit)
    assert up.checklist_state == {str(el.pk): [i1.pk], str(el2.pk): [j1.pk]}
```

> Fix `attach_element`, `_setup`'s access assumptions, and `test_non_enrolled_no_write` to the project's real access model (grep the `seen` view's tests for the exact enrolled-vs-previewer setup).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_endpoint.py -x`
Expected: FAIL (NoReverseMatch: markdone_save).

- [ ] **Step 3: Add the view (mirror `seen` at `courses/views.py:474-503`)**

```python
@require_POST
@login_required
def markdone_save(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied

    is_json = request.content_type == "application/json"
    if is_json:
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid JSON")
        if not isinstance(data, dict):
            return HttpResponseBadRequest("expected an object")
        raw_element = data.get("element")
        raw_items = data.get("items")
    else:
        raw_element = request.POST.get("element")
        raw_items = request.POST.getlist("item")

    try:
        element_pk = int(raw_element)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad element")

    if not isinstance(raw_items, list):
        raw_items = []
    incoming = set()
    for x in raw_items:
        try:
            incoming.add(int(x))
        except (TypeError, ValueError):
            continue  # skip garbage item, never 500

    # Ownership: element must be a MarkDoneElement in THIS unit (covers nested).
    element = MarkDoneElement.objects.filter(pk=element_pk, elements__unit=node).first()
    if element is None:
        return HttpResponseBadRequest("unknown element")
    valid = set(element.items.values_list("pk", flat=True))
    checked = sorted(incoming & valid)

    def _resp():
        if is_json:
            return JsonResponse({"element": element.pk, "items": checked})
        return redirect(
            reverse("courses:lesson_unit", args=[slug, node_pk]) + f"#markdone-{element.pk}"
        )

    if not is_enrolled(request.user, course):
        # previewer: no write, synthetic empty response
        if is_json:
            return JsonResponse({"element": element.pk, "items": []})
        return redirect(reverse("courses:lesson_unit", args=[slug, node_pk]) + f"#markdone-{element.pk}")

    with transaction.atomic():
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        if checked:
            progress.checklist_state[str(element.pk)] = checked
        else:
            progress.checklist_state.pop(str(element.pk), None)
        progress.save()
    return _resp()
```

Confirm the needed imports already exist in `views.py` (they do, for `seen`): `json`, `transaction`, `JsonResponse`, `HttpResponseBadRequest`, `redirect`, `reverse`, `require_POST`, `login_required`, `PermissionDenied`, `get_node_or_404`, `can_access_course`, `is_enrolled`, `MarkDoneElement`, `UnitProgress`. Add any missing import.

- [ ] **Step 4: Add the URL (`courses/urls.py`, next to `seen`/`complete`)**

```python
    path("courses/<slug:slug>/u/<int:node_pk>/markdone/", views.markdone_save, name="markdone_save"),
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest courses/tests/test_markdone_endpoint.py -x`
Expected: PASS.

- [ ] **Step 6: Hygiene + commit**

```bash
git add courses/views.py courses/urls.py courses/tests/test_markdone_endpoint.py
git commit -m "feat(markdone): markdone_save endpoint (persist ticks, IDOR-safe, locked)"
```

---

### Task 6: Student JS + lesson script include

**Files:**
- Create: `courses/static/courses/js/markdone.js`
- Modify: `templates/courses/lesson_unit.html` (conditionally include `markdone.js` on `has_markdone`)
- Test: `courses/tests/test_markdone_scripts.py`

**Interfaces:**
- Consumes: `has_markdone` (Task 4), the leaf template's `data-markdone`/`data-markdone-url`/`data-markdone-save` hooks (Task 4).
- Produces: `window.libliInitMarkDone(root)`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_markdone_scripts.py
import pytest
from django.urls import reverse
from courses.models import MarkDoneElement
pytestmark = pytest.mark.django_db


def test_lesson_includes_markdone_js_when_present(client):
    from tests.factories import make_course_with_unit, enroll, make_verified_user
    course, unit = make_course_with_unit(lesson=True)
    el = MarkDoneElement.objects.create(prompt="P")
    attach_element(unit, el)
    from courses.models import MarkDoneItem
    MarkDoneItem.objects.create(element=el, content="a")
    s = make_verified_user(); enroll(s, course); client.force_login(s)
    body = client.get(reverse("courses:lesson_unit", args=[course.slug, unit.pk])).content.decode()
    assert "courses/js/markdone.js" in body
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_scripts.py -x`
Expected: FAIL (markdone.js not in body).

- [ ] **Step 3: Write `markdone.js`** (mirror `stepper.js` boot + `progress.js` beacon)

```javascript
(function () {
  "use strict";
  window.__markdoneBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function persisted(root) {
    // last-known state = checkboxes' checked at init time
    var s = {};
    root.querySelectorAll('input[type="checkbox"][name="item"]').forEach(function (cb) {
      s[cb.value] = cb.checked;
    });
    return s;
  }

  function initOne(root) {
    if (root.dataset.markdoneReady === "1") return;
    root.dataset.markdoneReady = "1";
    var url = root.getAttribute("data-markdone-url");
    var saveBtn = root.querySelector("[data-markdone-save]");
    if (!url) return;              // preview/empty-URL: leave Save button, no auto-save
    if (saveBtn) saveBtn.hidden = true;
    var elInput = root.querySelector('input[name="element"]');
    var last = persisted(root);

    root.querySelectorAll('input[type="checkbox"][name="item"]').forEach(function (cb) {
      cb.addEventListener("change", function () {
        var li = cb.closest(".markdone__item");
        if (li) li.classList.toggle("on", cb.checked);
        var items = [];
        root.querySelectorAll('input[type="checkbox"][name="item"]:checked')
          .forEach(function (c) { items.push(parseInt(c.value, 10)); });
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
          body: JSON.stringify({ element: parseInt(elInput.value, 10), items: items }),
          keepalive: true,
        })
          .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
          .then(function () { last[cb.value] = cb.checked; })
          .catch(function () {
            // save failed: revert the toggle + on-class to last-known-persisted
            cb.checked = last[cb.value];
            if (li) li.classList.toggle("on", cb.checked);
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

- [ ] **Step 4: Include it in the lesson template**

In `templates/courses/lesson_unit.html`, find the `has_stepper` conditional script include and add a sibling:

```html
{% if has_markdone %}<script src="{% static 'courses/js/markdone.js' %}" defer></script>{% endif %}
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest courses/tests/test_markdone_scripts.py -x`
Expected: PASS.

- [ ] **Step 6: Hygiene + commit**

```bash
git add courses/static/courses/js/markdone.js templates/courses/lesson_unit.html courses/tests/test_markdone_scripts.py
git commit -m "feat(markdone): student JS auto-save enhancer + lesson include"
```

---

### Task 7: Editor (partial, add-row JS, wiring)

**Files:**
- Create: `templates/courses/manage/editor/_edit_markdone.html`
- Create: `courses/static/courses/js/markdone_editor.js`
- Modify: `courses/static/courses/js/editor.js` (re-init calls)
- Modify: `templates/courses/manage/editor/editor.html` (two `<script defer>` includes)
- Modify: `courses/views_manage.py` (`_render_open_form` branch; `element_add`/`element_save` tuples; `_EDITOR_TYPE_LABELS`)
- Test: `courses/tests/test_markdone_editor.py`

**Interfaces:**
- Consumes: `build_markdone_formset` (Task 2).
- Produces: working `element_add`/`element_save` for `markdone`; `window.libliInitMarkDoneEditor`.

- [ ] **Step 1: Write the failing test** (the render path that's easy to leave untested — `element_add`)

```python
# courses/tests/test_markdone_editor.py
import pytest
from django.urls import reverse
pytestmark = pytest.mark.django_db


def test_element_add_markdone_renders_200(client):
    from tests.factories import make_course_with_unit, make_author, TEST_PASSWORD  # project helpers
    course, unit = make_course_with_unit()
    author = make_author(course)
    client.force_login(author)
    # POST/GET manage_element_add for type=markdone exactly as stepper's editor test does
    resp = add_element(client, course, unit, type_key="markdone")  # helper mirroring stepper test
    assert resp.status_code == 200
    assert 'data-markdone-editor' in resp.content.decode()


def test_editor_html_includes_markdone_scripts(client):
    from tests.factories import make_course_with_unit, make_author
    course, unit = make_course_with_unit()
    client.force_login(make_author(course))
    body = client.get(reverse("courses:manage_editor", args=[course.slug, unit.pk])).content.decode()
    assert "courses/js/markdone.js" in body
    assert "courses/js/markdone_editor.js" in body
```

> Replace `add_element`/`make_author`/`make_course_with_unit` with the exact helpers/URL names the stepper editor test uses (grep `courses/tests/test_*editor*` and `test_editor_scripts.py`).

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_editor.py -x`
Expected: FAIL (TemplateDoesNotExist `_edit_markdone.html`, or 500).

- [ ] **Step 3: Create `_edit_markdone.html`** (clone `_edit_stepper.html`, rename steps→items)

```html
{# templates/courses/manage/editor/_edit_markdone.html #}
{% load i18n %}
<div class="el-editor el-editor--markdone" data-markdone-editor>
  <label class="el-editor__label">{% trans "Intro prompt (optional)" %}</label>
  <input type="text" name="prompt" class="el-editor__input" maxlength="500"
         value="{{ form.prompt.value|default:'' }}">

  <label class="el-editor__label">{% trans "Checklist items" %}</label>
  <p class="el-editor__hint">{% trans "Each item is one short line the student ticks. Math like \\(x^2\\) is allowed." %}</p>
  {{ formset.management_form }}
  <ul class="markdone-rows" data-markdone-rows>
    {% for f in formset %}
      <li class="markdone-row" data-markdone-row>
        {{ f.id }}
        {{ f.content }}
        {% if formset.can_delete %}
          <label class="markdone-row__del">{{ f.DELETE }} {% trans "Remove" %}</label>
        {% endif %}
      </li>
    {% endfor %}
  </ul>
  <button type="button" class="btn btn--small btn--ghost" data-markdone-add-row>＋ {% trans "Add item" %}</button>
  {% for e in formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}

  <template data-markdone-row-template>
    <li class="markdone-row" data-markdone-row>
      <input type="text" name="items-__prefix__-content" maxlength="500">
      <label class="markdone-row__del">
        <input type="checkbox" name="items-__prefix__-DELETE"> {% trans "Remove" %}
      </label>
    </li>
  </template>
</div>
```

- [ ] **Step 4: Create `markdone_editor.js`** (clone `stepper_editor.js`)

```javascript
(function () {
  "use strict";
  function initOne(editor) {
    if (editor.dataset.markdoneEditorReady === "1") return;
    editor.dataset.markdoneEditorReady = "1";
    var list = editor.querySelector("[data-markdone-rows]");
    var addBtn = editor.querySelector("[data-markdone-add-row]");
    var tmpl = editor.querySelector("[data-markdone-row-template]");
    var total = editor.querySelector('input[name="items-TOTAL_FORMS"]');
    if (!list || !addBtn || !tmpl || !total) return;
    addBtn.addEventListener("click", function () {
      var idx = parseInt(total.value, 10) || 0;
      var html = tmpl.innerHTML.replace(/__prefix__/g, String(idx)).trim();
      var tpl = document.createElement("template");
      tpl.innerHTML = html;
      var row = tpl.content.firstElementChild;
      list.appendChild(row);
      total.value = String(idx + 1);
      var input = row.querySelector('input[type="text"]');
      if (input) input.focus();
    });
  }
  function initMarkDoneEditor(root) {
    root = root || document;
    if (root.matches && root.matches("[data-markdone-editor]")) initOne(root);
    (root.querySelectorAll ? root.querySelectorAll("[data-markdone-editor]") : []).forEach(initOne);
  }
  window.libliInitMarkDoneEditor = initMarkDoneEditor;
  initMarkDoneEditor(document);
})();
```

- [ ] **Step 5: Wire editor.js + editor.html**

In `courses/static/courses/js/editor.js`, next to the stepper re-init calls (`:82`, `:93`):

```javascript
    if (preview && window.libliInitMarkDone) window.libliInitMarkDone(preview);
    ...
    if (editorPane && window.libliInitMarkDoneEditor) window.libliInitMarkDoneEditor(editorPane);
```

In `templates/courses/manage/editor/editor.html`, next to the stepper `<script defer>` lines (`:170`, `:175`):

```html
  <script src="{% static 'courses/js/markdone.js' %}" defer></script>
  <script src="{% static 'courses/js/markdone_editor.js' %}" defer></script>
```

- [ ] **Step 6: Wire views_manage.py**

- `_render_open_form` (`courses/views_manage.py:847`): add
  ```python
      elif type_key == "markdone" and formset is None:
          from courses.element_forms import build_markdone_formset
          instance = form.instance if form.instance.pk else None
          formset = build_markdone_formset(instance=instance)
  ```
- `element_add` allow-tuple (`:913-942`): add `"markdone"`.
- `element_save` allow-tuple (`:977-1007`): add `"markdone"`.
- `_EDITOR_TYPE_LABELS` (`:740-759`): add `"markdone": gettext_lazy("Checklist"),`.

- [ ] **Step 7: Run tests**

Run: `uv run pytest courses/tests/test_markdone_editor.py tests/test_editor_scripts.py -x`
Expected: PASS. (If `test_editor_scripts.py` asserts a script-count, bump it.)

- [ ] **Step 8: Hygiene + commit**

```bash
git add templates/courses/manage/editor/_edit_markdone.html courses/static/courses/js/markdone_editor.js courses/static/courses/js/editor.js templates/courses/manage/editor/editor.html courses/views_manage.py courses/tests/test_markdone_editor.py tests/test_editor_scripts.py
git commit -m "feat(markdone): editor partial + add-row JS + wiring"
```

---

### Task 8: Palette card, icon, labels, summary, math

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html` (Interactive-group card) + the icon sprite (add `#el-markdone`)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`, `element_summary`)
- Modify: `courses/views.py` (`_element_has_math` branch)
- Modify: `courses/static/courses/js/math.js` (allowlist `.markdone`)
- Test: `courses/tests/test_markdone_meta.py`

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_markdone_meta.py
import pytest
from courses.models import MarkDoneElement, MarkDoneItem
pytestmark = pytest.mark.django_db


def test_element_summary_uses_prompt_or_first_item():
    from courses.templatetags.courses_manage_extras import element_summary
    el = MarkDoneElement.objects.create(prompt="")
    MarkDoneItem.objects.create(element=el, content="first thing")
    assert "first thing" in element_summary(el)


def test_has_math_detects_prompt_and_item():
    from courses.views import _element_has_math
    el = MarkDoneElement.objects.create(prompt="")
    MarkDoneItem.objects.create(element=el, content=r"value \(x^2\)")
    assert _element_has_math(el) is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_meta.py -x`
Expected: FAIL.

- [ ] **Step 3: Labels + summary (`courses/templatetags/courses_manage_extras.py`)**

`_ELEMENT_LABELS` (`:29-59`): `"markdoneelement": _("Checklist"),`.
`element_summary` (`:86-164`, after the stepper branch): 

```python
    if name == "MarkDoneElement":
        first = el.items.first()
        text = el.prompt or (first.content if first else "")
        text = re.sub(r"\s+", " ", strip_tags(text)).strip()
        return Truncator(unescape(text)).chars(60) or _("Checklist")
```

- [ ] **Step 4: Math (`courses/views.py` `_element_has_math`; `math.js`)**

`_element_has_math` (`:165`, add before the fallthrough, mirror the StepperElement branch at `:195`):

```python
    if isinstance(obj, MarkDoneElement):
        return has_math_delimiters(obj.prompt) or any(
            has_math_delimiters(i.content) for i in obj.items.all()
        )
```

`math.js` (`:31`) — add `.markdone` to the `renderInlineText` selector allowlist:

```javascript
  (root || document).querySelectorAll(".el--text, .el--table, .el--gallery, .el--tabs, .fillgate, .stepper, .markdone").forEach(...)
```

- [ ] **Step 5: Palette card + icon (`_add_menu.html`)**

In the Interactive group (inside `{% if not unit_is_quiz %}`, next to the stepper card `:36`):

```html
<button type="button" class="typecard" data-add-type="markdone"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-markdone"/></svg>{% trans "Checklist" %}</button>
```

Add an `#el-markdone` `<symbol>` to the icon sprite (grep `#el-stepper` to find the sprite file; add a simple monochrome `currentColor` checklist line-icon — a box with a check, per [[icons-monochrome-svg]]). If `tests/test_manage_editor_menu.py::test_add_menu_icons_are_svg` enumerates `EL_ICON_MAP`, add `markdone` there.

- [ ] **Step 6: Verify the menu-count assert unchanged**

Confirm `tests/test_manage_editor_menu.py:62` renders a **quiz** unit (`unit_type="quiz"`) and the card is inside `{% if not unit_is_quiz %}` — so `== 23` is UNCHANGED. Run `uv run pytest tests/test_manage_editor_menu.py -x`; if it renders a lesson unit or the count changed, bump the assert with a comment.

- [ ] **Step 7: Run tests**

Run: `uv run pytest courses/tests/test_markdone_meta.py tests/test_manage_editor_menu.py -x`
Expected: PASS.

- [ ] **Step 8: Hygiene + commit**

```bash
git add templates/courses/manage/editor/_add_menu.html courses/templatetags/courses_manage_extras.py courses/views.py courses/static/courses/js/math.js courses/tests/test_markdone_meta.py
# + the sprite file + tests/test_manage_editor_menu.py if touched
git commit -m "feat(markdone): palette card, icon, labels, summary, math"
```

---

### Task 9: Transfer trio + NESTABLE

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_mark_done` + `SERIALIZERS`)
- Modify: `courses/transfer/payloads.py` (`_val_mark_done` + `VALIDATORS`)
- Modify: `courses/transfer/importer.py` (`_build_mark_done` + `BUILDERS`)
- Modify: `courses/builder.py` (`NESTABLE_TYPE_KEYS` += `"mark_done"`; `_NESTABLE_FORM_KEY_ALIASES["markdone"] = "mark_done"`)
- Test: `courses/tests/test_markdone_transfer.py`

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_markdone_transfer.py
import pytest
from courses.models import MarkDoneElement, MarkDoneItem
pytestmark = pytest.mark.django_db


def test_roundtrip_serialize_validate_build():
    from courses.transfer.export import SERIALIZERS
    from courses.transfer.payloads import VALIDATORS
    from courses.transfer.importer import BUILDERS
    el = MarkDoneElement.objects.create(prompt="Prep")
    MarkDoneItem.objects.create(element=el, content="one")
    MarkDoneItem.objects.create(element=el, content="two")
    model, ser = SERIALIZERS["mark_done"]
    payload = ser(el, {})
    assert payload == {"prompt": "Prep", "items": ["one", "two"]}
    VALIDATORS["mark_done"](payload, "e1", {})  # no raise
    new_el, items = BUILDERS["mark_done"](payload, {})
    new_el.save()
    for it in items:
        it.element = new_el
        it.full_clean(); it.save()
    assert [i.content for i in new_el.items.all()] == ["one", "two"]


def test_validator_rejects_bad_shape():
    from courses.transfer.payloads import VALIDATORS
    from courses.transfer.schema import TransferError
    with pytest.raises(TransferError):
        VALIDATORS["mark_done"]({"prompt": "x"}, "e1", {})  # missing items
    with pytest.raises(TransferError):
        VALIDATORS["mark_done"]({"prompt": "x", "items": ["a" * 600]}, "e1", {})  # MAX_LEN
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest courses/tests/test_markdone_transfer.py -x`
Expected: FAIL (KeyError 'mark_done').

- [ ] **Step 3: Serializer (`courses/transfer/export.py`, mirror `_ser_stepper` :138)**

```python
def _ser_mark_done(el, media_ids):
    return {"prompt": el.prompt, "items": [i.content for i in el.items.all()]}
```

Register: `"mark_done": (MarkDoneElement, _ser_mark_done),` in `SERIALIZERS`. Import `MarkDoneElement`.

- [ ] **Step 4: Validator (`courses/transfer/payloads.py`, mirror `_val_stepper` :294)**

```python
def _val_mark_done(data, elid, media_kinds):
    from courses.models import MarkDoneElement

    if not isinstance(data, dict):
        _err(_("mark-done data must be an object."))
    check_str(data.get("prompt", ""), _("prompt"), max_length=MarkDoneElement.MAX_LEN)
    items = data.get("items")
    if items is None:
        _err(_("Element '%(el)s': at least one item is required."), el=elid)
    items = check_list(items, _("items"))
    if not (MarkDoneElement.MIN_ITEMS <= len(items) <= MarkDoneElement.MAX_ITEMS):
        _err(_("Element '%(el)s': item count out of range."), el=elid)
    for it in items:
        check_str(it, _("item"), max_length=MarkDoneElement.MAX_LEN, required=True)
    return set()
```

Register: `"mark_done": _val_mark_done,` in `VALIDATORS`.

- [ ] **Step 5: Builder (`courses/transfer/importer.py`, mirror `_build_stepper` :739)**

```python
def _build_mark_done(data, assets):
    el = _clean_save(MarkDoneElement(prompt=data.get("prompt", "")))
    items = [MarkDoneItem(element=el, content=c) for c in data["items"]]
    return el, items  # generic loop full_clean+saves the items
```

Register: `"mark_done": _build_mark_done,` in `BUILDERS`. Import `MarkDoneElement`, `MarkDoneItem`.

- [ ] **Step 6: NESTABLE (`courses/builder.py`)**

Add `"mark_done"` to `NESTABLE_TYPE_KEYS` (`:34-53`) and `"markdone": "mark_done"` to `_NESTABLE_FORM_KEY_ALIASES` (`:56-62`).

- [ ] **Step 7: Run tests**

Run: `uv run pytest courses/tests/test_markdone_transfer.py tests/test_transfer_schema.py -x`
Expected: PASS (including the `ELEMENT_MODELS == 30` assert from Task 1).

- [ ] **Step 8: Hygiene + commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/builder.py courses/tests/test_markdone_transfer.py
git commit -m "feat(markdone): transfer trio + nestable"
```

---

### Task 10: i18n (EN/PL)

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ any JS catalog)
- Test: existing `test_po_catalog_clean` (in `tests/test_i18n_*`, `tests/test_tags_i18n.py`)

- [ ] **Step 1: Extract**

Run: `uv run python manage.py makemessages -l pl` (and `-d djangojs -l pl` if the project extracts JS strings; grep whether `.js` `{% trans %}`/`gettext` are extracted).

- [ ] **Step 2: Fix fuzzies + translate**

`makemessages` will fuzzy-match new msgids to wrong existing translations (incl. validator strings "mark-done data must be an object.", "items", "item", "Checklist", "A checklist needs between…", "Save", "Add item", "Checklist items", the hint). For EACH new entry: strip the `#, fuzzy` token (keep `python-format`/`python-brace-format`), drop `#| msgid` lines, and set the correct Polish. Suggested PL: `Checklist`→`Lista zadań`; `Save`→`Zapisz`; `Add item`→`Dodaj pozycję`; `Checklist items`→`Pozycje listy`; `Intro prompt (optional)`→(reuse existing if present); `A checklist needs between %(lo)s and %(hi)s items.`→`Lista musi mieć od %(lo)s do %(hi)s pozycji.`; validator strings translated in kind.

- [ ] **Step 3: Compile + verify**

Run: `uv run python manage.py compilemessages`
Run: `uv run pytest tests/test_tags_i18n.py -k po_catalog -x` (or the project's `test_po_catalog_clean`) — must be fuzzy-free.

- [ ] **Step 4: Commit**

```bash
git add locale/
git commit -m "i18n(markdone): EN/PL catalog entries"
```

---

### Task 11: e2e (real browser)

**Files:**
- Create: `tests/test_e2e_markdone.py`

- [ ] **Step 1: Write the e2e** (mirror an existing lesson e2e, e.g. stepper/spoiler)

```python
# tests/test_e2e_markdone.py  — real browser, drive the actual checkbox gesture
import pytest
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_tick_persists_across_reload(live_server, page, ...):
    # 1. Author or seed a lesson with a MarkDoneElement (prompt + 2 items) as an ENROLLED student.
    # 2. Navigate to the lesson; click the FIRST checkbox (real click, not page.evaluate).
    # 3. Wait for the save fetch (expect_response to markdone/ url) to complete.
    # 4. page.reload(); assert the first checkbox is checked and its row has class `on`.
    ...


def test_nested_in_tabs_tick_persists(live_server, page, ...):
    # A MarkDoneElement nested in a Tabs element; tick, reload, assert persisted.
    ...
```

> Copy the harness (fixtures, login, seeding, `expect_response`) verbatim from the newest lesson e2e that persists via fetch (grep `tests/test_e2e_*` for `keepalive`/`data-seen-url`/stepper). Drive the real click path — never `page.evaluate` the checkbox (per [[e2e-must-drive-real-ui]]).

- [ ] **Step 2: Run FOREGROUND, single file, explicit `-m e2e`**

Run: `uv run pytest tests/test_e2e_markdone.py -m e2e -x`
Expected: PASS. (NEVER background or whole-suite `-m e2e` → runaway browsers.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_markdone.py
git commit -m "test(markdone): e2e tick-persists (top-level + nested)"
```

---

## Self-Review

**Spec coverage:** models+checklist_state (T1) · forms+save_element (T2) · render seam incl. six overrides + containers (T3) · lesson map + student template + nested (T4) · endpoint incl. int-coercion/non-list/forged/merge/empty-drop/IDOR/enrollment (T5) · student JS incl. save-failure revert + preview no-op (T6) · editor incl. `element_add` 200 + editor.html scripts (T7) · palette/icon/labels/summary/math (T8) · transfer trio + NESTABLE + count assert (T9) · i18n (T10) · e2e top-level+nested (T11). No spec section is unmapped.

**Placeholder scan:** All test helpers flagged as "replace with the project's real helper" are deliberate — the executor must match the codebase's existing factory/URL names (they vary and must be read from sibling element tests), NOT invent them. Every code block that changes production code is complete.

**Type consistency:** `checklist` is int-keyed `{content_pk: {item_pk}}` everywhere (build_lesson_context builds it, ElementBase.render looks up `self.pk`, template tests `item.pk in checked`). Endpoint keys `checklist_state` by `str(element.pk)`; response is `{"element": pk, "items": [...]}`. Form prefix `items`; transfer key `mark_done`; form key `markdone`. `window.libliInitMarkDone` / `window.libliInitMarkDoneEditor` match between Task 6/7 and editor.js.
