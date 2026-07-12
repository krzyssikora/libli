# Spoiler Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new self-contained "Spoiler" content element — an author-labelled button that expands/collapses a block of rich text + math via native `<details>` — to libli's unit builder.

**Architecture:** A concrete `SpoilerElement(ElementBase)` model with `label` + sanitized `body`, rendered as a native `<details>`/`<summary>` disclosure (zero JS, zero server endpoint). It reuses the Text element's `body` sanitize/RTE path and the reveal-gate's label/palette/edit-partial conventions. Math renders at page load because the body carries `.el--text` and `views.py` `has_math` is extended to load `math.js` for spoiler-only units.

**Tech Stack:** Django (server-rendered), native HTML `<details>`, existing KaTeX auto-render (`math.js`), bespoke token-driven CSS (`core/static/core/css/app.css`), pytest.

## Global Constraints

- **Element type keys (verbatim):** form/palette/`FORM_FOR_TYPE`/`_EDITOR_TYPE_LABELS`/allow-tuple key = **`spoiler`**; model name / `_ELEMENT_LABELS` key = **`spoilerelement`**; transfer key (export/payloads/importer registries) = **`spoiler`**.
- **Palette naming:** EN **"Spoiler"**, PL **"Rozwijana treść"**. Default button label: EN **"Reveal"**, PL **"Pokaż"**.
- **No `FORMAT_VERSION` bump** — a new element type does not change existing on-disk shapes.
- **NOT nestable in Tabs** — do not touch `NESTABLE_TYPE_KEYS`.
- **No JS file / no reveal engine / no server-check / no `editor.html` `<script>` tag** — native `<details>` covers all behaviour.
- **Blank-label rendering:** use `{% if el.label %}{{ el.label }}{% else %}{% trans "Reveal" %}{% endif %}` — never `|default:_("Reveal")` (illegal in a Django template).
- **`body` sanitized** via `sanitize_html` in `save()`, identical to `TextElement`.
- **Tooling:** `ruff`/`pytest`/`python` are NOT on bash PATH — always prefix with `uv run` (e.g. `uv run pytest`, `uv run python manage.py …`). Run all commands from the worktree root `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/spoiler-element`.
- **No hardcoded test passwords** — use `tests.factories` helpers (`make_pa`, `make_verified_user`), never password literals.
- **DoD (whole build):** `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` all green; if translatable strings were removed, also run the i18n catalog no-obsolete tests.

---

### Task 1: SpoilerElement model + migration

**Files:**
- Modify: `courses/models.py` (add `"spoilerelement"` to `ELEMENT_MODELS` ~L259; add `SpoilerElement` class near `TextElement`/`RevealGateElement`)
- Create: `courses/migrations/00NN_spoilerelement.py` (generated)
- Test: `courses/tests/test_spoiler_model.py`

**Interfaces:**
- Produces: `courses.models.SpoilerElement` with fields `label: CharField(max_length=120, blank=True)`, `body: TextField(blank=True)`; `save()` sanitizes `body`; `render()` (inherited from `ElementBase`) resolves `courses/elements/spoilerelement.html`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_model.py`:

```python
import pytest

from courses.models import ELEMENT_MODELS
from courses.models import SpoilerElement

pytestmark = pytest.mark.django_db


def test_registered_in_element_models():
    assert "spoilerelement" in ELEMENT_MODELS


def test_body_is_sanitized_on_save():
    el = SpoilerElement.objects.create(
        label="Hint", body='<p>ok</p><script>alert(1)</script>'
    )
    el.refresh_from_db()
    assert "<script>" not in el.body
    assert "<p>ok</p>" in el.body


def test_label_and_body_may_be_blank():
    el = SpoilerElement.objects.create()
    assert el.label == ""
    assert el.body == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_model.py -q`
Expected: FAIL with `ImportError: cannot import name 'SpoilerElement'`.

- [ ] **Step 3: Write minimal implementation**

In `courses/models.py`, add `"spoilerelement"` to the `ELEMENT_MODELS` list (alongside the other element strings). Then add the model next to `TextElement` (it mirrors `TextElement.save` for `body` and `RevealGateElement` for `label`):

```python
class SpoilerElement(ElementBase):
    """A self-contained show/hide disclosure: an author-labelled button that
    expands/collapses a block of rich text + math. Rendered as a native
    <details>; two-way, repeatable, ungraded. See the spoiler-element design doc."""

    label = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def save(self, *args, **kwargs):
        self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)
```

(`sanitize_html` is already imported in `models.py` — it is used by `TextElement.save`.)

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/00NN_spoilerelement.py` adding the `SpoilerElement` table. Confirm it only creates the new model (no unrelated changes).

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_model.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add courses/models.py courses/migrations/ courses/tests/test_spoiler_model.py
git commit -m "feat(spoiler): add SpoilerElement model + migration"
```

---

### Task 2: SpoilerElementForm + FORM_FOR_TYPE

**Files:**
- Modify: `courses/element_forms.py` (add `SpoilerElementForm` near `RevealGateElementForm` ~L190; register in `FORM_FOR_TYPE` ~L919)
- Test: `courses/tests/test_spoiler_form.py`

**Interfaces:**
- Consumes: `courses.models.SpoilerElement` (Task 1).
- Produces: `courses.element_forms.SpoilerElementForm` (ModelForm, `fields=["label","body"]`); `FORM_FOR_TYPE["spoiler"] is SpoilerElementForm`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_form.py`:

```python
import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import SpoilerElementForm

pytestmark = pytest.mark.django_db


def test_form_registered():
    assert FORM_FOR_TYPE["spoiler"] is SpoilerElementForm


def test_form_valid_with_label_and_body():
    f = SpoilerElementForm(data={"label": "Show solution", "body": "<p>x</p>"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["label"] == "Show solution"


def test_form_valid_blank_label_and_body():
    f = SpoilerElementForm(data={"label": "", "body": ""})
    assert f.is_valid(), f.errors


def test_form_rejects_overlong_label():
    f = SpoilerElementForm(data={"label": "x" * 121, "body": ""})
    assert not f.is_valid()
    assert "label" in f.errors
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_form.py -q`
Expected: FAIL with `ImportError: cannot import name 'SpoilerElementForm'`.

- [ ] **Step 3: Write minimal implementation**

In `courses/element_forms.py`, add near `RevealGateElementForm`:

```python
class SpoilerElementForm(forms.ModelForm):
    class Meta:
        model = SpoilerElement
        fields = ["label", "body"]
```

Ensure `SpoilerElement` is imported at the top of `element_forms.py` (the module already imports the concrete element models — add `SpoilerElement` to that import group). Then register in `FORM_FOR_TYPE` (add the line alongside `"revealgate"`):

```python
    "spoiler": SpoilerElementForm,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_form.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/element_forms.py courses/tests/test_spoiler_form.py
git commit -m "feat(spoiler): add SpoilerElementForm + FORM_FOR_TYPE registration"
```

---

### Task 3: Student render template

**Files:**
- Create: `templates/courses/elements/spoilerelement.html`
- Test: `courses/tests/test_spoiler_render.py`

**Interfaces:**
- Consumes: `SpoilerElement` (Task 1); `ElementBase.render()` resolves this template from the model name.
- Produces: a `<details class="spoiler">` render with `<summary class="spoiler__toggle">` (label or default "Reveal") and `<div class="el el--text spoiler__body">` holding the sanitized body.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_render.py`:

```python
import pytest

from courses.models import SpoilerElement

pytestmark = pytest.mark.django_db


def test_render_shows_label_and_body():
    el = SpoilerElement.objects.create(label="Show solution", body="<p>answer</p>")
    html = el.render()
    assert "<details" in html and 'class="spoiler"' in html
    assert "<summary" in html and "Show solution" in html
    assert 'class="el el--text spoiler__body"' in html
    assert "<p>answer</p>" in html


def test_render_default_label_when_blank():
    el = SpoilerElement.objects.create(label="", body="<p>x</p>")
    html = el.render()
    assert "Reveal" in html  # {% trans "Reveal" %} default under the EN catalog
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_render.py -q`
Expected: FAIL with `TemplateDoesNotExist: courses/elements/spoilerelement.html`.

- [ ] **Step 3: Write minimal implementation**

Create `templates/courses/elements/spoilerelement.html`:

```html
{% load i18n courses_extras %}
<details class="spoiler">
  <summary class="spoiler__toggle">{% if el.label %}{{ el.label }}{% else %}{% trans "Reveal" %}{% endif %}</summary>
  <div class="el el--text spoiler__body">{{ el.body|sanitize }}</div>
</details>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_render.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/spoilerelement.html courses/tests/test_spoiler_render.py
git commit -m "feat(spoiler): add student render template"
```

---

### Task 4: Edit partial + views_manage wiring (authoring path)

**Files:**
- Create: `templates/courses/manage/editor/_edit_spoiler.html`
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS` ~L738; `element_add` allow-tuple ~L884; `element_save` allow-tuple ~L941)
- Test: `courses/tests/test_spoiler_authoring.py`

**Interfaces:**
- Consumes: `SpoilerElementForm` (Task 2); the generic `save_element` `else` branch in `courses/builder.py` already handles any `FORM_FOR_TYPE` key (no builder edit needed — spoiler is not in `NESTABLE_TYPE_KEYS`, so `resolve_scope` returns top-level).
- Produces: clicking the palette card (`type=spoiler`) renders `_edit_spoiler.html` (200, no 500) and saving persists a `SpoilerElement`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_authoring.py`:

```python
import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import SpoilerElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_form_renders_spoiler_edit_partial(client):
    # A missing _edit_spoiler.html 500s (TemplateDoesNotExist) the moment the author
    # clicks "Spoiler" in the palette. This exercises element_add -> _host_form ->
    # _edit_spoiler.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "spoiler", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="label"' in html  # button-text field
    assert 'name="body"' in html   # RTE body field
    assert Element.objects.filter(unit=unit).count() == 0  # render-only


def test_save_round_trips_label_and_body(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "spoiler",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "label": "Show solution",
            "body": "<p>the answer</p>",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, SpoilerElement)
    assert el.content_object.label == "Show solution"
    assert "<p>the answer</p>" in el.content_object.body


def test_save_allows_blank_label(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "spoiler",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "label": "",
            "body": "",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert el.content_object.label == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_authoring.py -q`
Expected: FAIL — `element_add`/`element_save` reject `type=spoiler` (not in allow-tuple) and/or `TemplateDoesNotExist: .../_edit_spoiler.html`.

- [ ] **Step 3: Create the edit partial**

Create `templates/courses/manage/editor/_edit_spoiler.html` (label input mirrors `_edit_revealgate.html`; the RTE toolbar + textarea are copied verbatim from `_edit_text.html`; render BOTH `form.label.errors` and `form.body.errors`):

```html
{% load i18n %}
<div class="el-editor el-editor--spoiler">
  <label>{% trans "Button text" %}
    <input type="text" name="label" maxlength="120"
           value="{{ form.label.value|default:'' }}"
           placeholder="{% trans 'Reveal' %}">
  </label>
  <p class="helptext">{% trans "Shown on the spoiler button. Leave blank for the default “Reveal”." %}</p>
  {% for e in form.label.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
  <div class="rte-toolbar" data-rte-toolbar>
    <button type="button" class="rte-btn" data-cmd="bold" title="{% trans 'Bold' %}" aria-label="{% trans 'Bold' %}"><svg class="ic"><use href="#ed-bold"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="italic" title="{% trans 'Italic' %}" aria-label="{% trans 'Italic' %}"><svg class="ic"><use href="#ed-italic"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="underline" title="{% trans 'Underline' %}" aria-label="{% trans 'Underline' %}"><svg class="ic"><use href="#ed-underline"/></svg></button>
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h2" title="{% trans 'Heading 2' %}">H2</button>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h3" title="{% trans 'Heading 3' %}">H3</button>
    <button type="button" class="rte-btn rte-btn--text" data-cmd="h4" title="{% trans 'Heading 4' %}">H4</button>
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn" data-cmd="ul" title="{% trans 'Bullet list' %}" aria-label="{% trans 'Bullet list' %}"><svg class="ic"><use href="#ed-ul"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="ol" title="{% trans 'Numbered list' %}" aria-label="{% trans 'Numbered list' %}"><svg class="ic"><use href="#ed-ol"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="link" title="{% trans 'Link' %}" aria-label="{% trans 'Link' %}"><svg class="ic"><use href="#ed-link"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="blockquote" title="{% trans 'Quote' %}" aria-label="{% trans 'Quote' %}"><svg class="ic"><use href="#ed-quote"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="code" title="{% trans 'Code' %}" aria-label="{% trans 'Code' %}"><svg class="ic"><use href="#ed-code"/></svg></button>
  </div>
  <textarea name="body" class="rte-source" data-rte-source rows="6">{{ form.body.value|default:"" }}</textarea>
  {% for e in form.body.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

- [ ] **Step 4: Wire views_manage.py**

In `courses/views_manage.py`:

Add to `_EDITOR_TYPE_LABELS` (~L738), alongside `"revealgate"`:

```python
    "spoiler": gettext_lazy("Spoiler"),
```

Add `"spoiler",` to BOTH allow-tuples — the `element_add` `if type_key not in (...)` tuple (~L884) and the `element_save` `if type_key not in (...)` tuple (~L941) — next to `"revealgate"` in each.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_authoring.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_edit_spoiler.html courses/views_manage.py courses/tests/test_spoiler_authoring.py
git commit -m "feat(spoiler): edit partial + element add/save wiring"
```

---

### Task 5: Load math.js for spoiler-only units (has_math)

**Files:**
- Modify: `courses/views.py` (`_element_has_math` ~L121; `build_lesson_context` `has_math` OR-chain ~L206; import `SpoilerElement`)
- Test: `courses/tests/test_spoiler_context.py`

**Interfaces:**
- Consumes: `SpoilerElement` (Task 1); `build_lesson_context(unit, user)` returns a dict including `has_math`.
- Produces: `has_math is True` for a unit whose only math-bearing element is a spoiler (so `lesson_unit.html` loads `math.js`/KaTeX).

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_context.py`:

```python
import pytest

from courses.models import Element
from courses.models import SpoilerElement
from courses.views import build_lesson_context


@pytest.fixture
def lesson_unit_node():
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def student_user():
    from tests.factories import make_verified_user

    return make_verified_user(username="spoiler_ctx")


@pytest.mark.django_db
def test_spoiler_only_unit_arms_has_math(lesson_unit_node, student_user):
    # The ONLY math-bearing element is the spoiler (no Math/Text-with-math sibling),
    # so this actually exercises the has_math OR-chain branch — it would fail
    # without the views.py fix (math.js would never load for this unit).
    unit = lesson_unit_node
    el = SpoilerElement.objects.create(label="Show", body="Value \\(x^2\\)")
    Element.objects.create(unit=unit, content_object=el)
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


@pytest.mark.django_db
def test_spoiler_without_math_does_not_arm(lesson_unit_node, student_user):
    unit = lesson_unit_node
    el = SpoilerElement.objects.create(label="Show", body="<p>no math here</p>")
    Element.objects.create(unit=unit, content_object=el)
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_context.py -q`
Expected: FAIL — `test_spoiler_only_unit_arms_has_math` asserts True but gets False (no SpoilerElement branch in `has_math`).

- [ ] **Step 3: Write minimal implementation**

In `courses/views.py`:

Add the import next to the other model imports (near `from courses.models import FillGateElement`):

```python
from courses.models import SpoilerElement
```

Extend the `build_lesson_context` `has_math = ( ... )` OR-chain (~L206) with a spoiler clause (add it alongside the existing `FillGateElement` / `SwitchGateElement` clauses):

```python
        or any(
            isinstance(el.content_object, SpoilerElement)
            and has_math_delimiters(el.content_object.body)
            for el in elements
        )
```

Also add a defensive branch to `_element_has_math` (~L121) so a future nested spoiler is covered (add before the final `return`):

```python
    if isinstance(obj, SpoilerElement):
        return has_math_delimiters(obj.body)
```

(`has_math_delimiters` is already imported in `views.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_context.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/views.py courses/tests/test_spoiler_context.py
git commit -m "feat(spoiler): load math.js for spoiler-only units (has_math)"
```

---

### Task 6: Builder-row summary label

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` ~L45; `element_summary` ~L75 add a branch)
- Test: `courses/tests/test_spoiler_summary.py`

**Interfaces:**
- Consumes: `SpoilerElement` (Task 1).
- Produces: `element_summary(spoiler)` returns `el.label or _("Reveal")` (never the literal "SpoilerElement"); `_ELEMENT_LABELS["spoilerelement"] == _("Spoiler")`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_summary.py`:

```python
import pytest

from courses.models import SpoilerElement
from courses.templatetags.courses_manage_extras import element_summary

pytestmark = pytest.mark.django_db


def test_summary_uses_label():
    el = SpoilerElement.objects.create(label="Show solution", body="<p>x</p>")
    assert element_summary(el) == "Show solution"


def test_summary_falls_back_to_reveal_not_class_name():
    el = SpoilerElement.objects.create(label="", body="<p>x</p>")
    summary = str(element_summary(el))
    assert summary == "Reveal"          # EN catalog default
    assert summary != "SpoilerElement"  # never the raw class name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_summary.py -q`
Expected: FAIL — `element_summary` falls through and returns the raw model string / class name.

- [ ] **Step 3: Write minimal implementation**

In `courses/templatetags/courses_manage_extras.py`:

Add to `_ELEMENT_LABELS` (~L45), alongside `"revealgateelement"`:

```python
    "spoilerelement": _("Spoiler"),
```

Add a branch to `element_summary` next to the `RevealGateElement` branch:

```python
    if name == "SpoilerElement":
        return el.label or _("Reveal")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_summary.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/templatetags/courses_manage_extras.py courses/tests/test_spoiler_summary.py
git commit -m "feat(spoiler): builder-row summary + element label"
```

---

### Task 7: Palette card + icon sprite

**Files:**
- Modify: `templates/courses/manage/editor/_add_menu.html` (Interactive group ~L28)
- Modify: `templates/courses/manage/_icon_sprite.html` (add `#el-spoiler` symbol next to `#el-revealgate`)
- Test: `courses/tests/test_spoiler_palette.py`

**Interfaces:**
- Consumes: the `spoiler` allow-tuple wiring (Task 4) — the card's `data-add-type="spoiler"` must equal that key.
- Produces: a palette card in the Interactive group carrying `data-add-type="spoiler"` and `<use href="#el-spoiler"/>`; the `#el-spoiler` sprite symbol exists.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_palette.py`:

```python
import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_palette_card_present_with_data_add_type(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'data-add-type="spoiler"' in html
    assert 'href="#el-spoiler"' in html
    assert 'id="el-spoiler"' in html  # sprite symbol defined


def test_spoiler_card_absent_from_nested_add_menu(client):
    # Spoiler is NOT nestable, so its card must be guarded by {% if not nested %}
    # and appear ONLY at top level — never in the in-tab (nested=True) add-menu,
    # where clicking it would 400. Build a unit with a Tabs element so BOTH menus
    # render; the card must then appear exactly once (top-level only).
    from courses.models import Element
    from courses.models import TabsElement
    from courses.models import TextElement

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="child"),
        parent=join,
        tab_id=tab_id,
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    html = resp.content.decode()
    # revealgate IS nestable, so it appears >= 2 (top-level + nested) — a sanity
    # check that the nested menu really rendered.
    assert html.count('data-add-type="revealgate"') >= 2
    # spoiler is NOT nestable — top-level only.
    assert html.count('data-add-type="spoiler"') == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_palette.py -q`
Expected: FAIL — neither the card nor the sprite symbol exists yet.

- [ ] **Step 3: Add the palette card**

In `templates/courses/manage/editor/_add_menu.html`, add to the Interactive group (after the `switchgate` card, ~L30). **Wrap it in `{% if not nested %}`** — spoiler is NOT nestable, and the Interactive group as a whole is only guarded by `{% if not unit_is_quiz %}` (its gate siblings ARE nestable), so `_element_row.html` includes this menu with `nested=True` inside a tab. An unguarded spoiler card would render in the in-tab menu and 400 (`resolve_scope` → `NestingError` → `HttpResponseBadRequest`) when clicked — the broken-palette footgun. The `tabs` card at ~L23 uses the same `{% if not nested %}` guard:

```html
      {% if not nested %}<button type="button" class="typecard" data-add-type="spoiler"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-spoiler"/></svg>{% trans "Spoiler" %}</button>{% endif %}
```

- [ ] **Step 4: Add the sprite symbol**

In `templates/courses/manage/_icon_sprite.html`, add next to `#el-revealgate` (same `viewBox="0 0 16 16"` as its siblings — an "eye" disclosure glyph):

```html
  <symbol id="el-spoiler" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" d="M1 8s2.5-4.5 7-4.5 7 4.5 7 4.5-2.5 4.5-7 4.5S1 8 1 8Z"/><circle cx="8" cy="8" r="1.9" fill="currentColor"/></symbol>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_palette.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html courses/tests/test_spoiler_palette.py
git commit -m "feat(spoiler): palette card + icon sprite symbol"
```

---

### Task 8: CSS styling for the disclosure

**Files:**
- Modify: `core/static/core/css/app.css` (add `.spoiler*` rules near the `.reveal-gate` block ~L858)
- Test: `courses/tests/test_spoiler_css.py`

**Interfaces:**
- Consumes: the BEM classes rendered in Task 3 (`.spoiler`, `.spoiler__toggle`, `.spoiler__body`).
- Produces: themed disclosure styling using existing tokens (`--primary`, `--primary-subtle`, `--text-inverse`), native marker suppressed, chevron pseudo-element rotating on `[open]`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_css.py`:

```python
import glob
from pathlib import Path


def _all_css():
    # Scan BOTH static CSS trees so the test finds the rules wherever they land
    # (the .spoiler rules go in core/static/core/css/app.css alongside
    # .reveal-gate). Mirrors test_fillgate_css.py exactly.
    return "".join(
        Path(p).read_text(encoding="utf-8")
        for pattern in (
            "courses/static/courses/css/*.css",
            "core/static/core/css/*.css",
        )
        for p in glob.glob(pattern)
    )


def test_spoiler_css_present():
    css = _all_css()
    assert ".spoiler__toggle" in css
    assert ".spoiler__body" in css


def test_spoiler_marker_suppressed_cross_browser():
    css = _all_css()
    # Native disclosure triangle removed in both Firefox and WebKit/Blink.
    assert "list-style: none" in css
    assert "::-webkit-details-marker" in css


def test_spoiler_chevron_rotates_on_open():
    css = _all_css()
    assert ".spoiler[open]" in css
```

(The glob patterns are relative to the repo root; pytest runs from there. This matches `test_fillgate_css.py`, which globs both trees precisely so the assertion is robust to which stylesheet the rules land in.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_css.py -q`
Expected: FAIL — no `.spoiler` rules in `app.css`.

- [ ] **Step 3: Write minimal implementation**

In `core/static/core/css/app.css`, add after the `.reveal-gate` block (the tokens `--primary`, `--primary-subtle`, `--text-inverse`, `--radius-full`, `--space-*` are already used by `.reveal-gate`, so this themes correctly in light + dark):

```css
/* Spoiler — self-contained show/hide disclosure (native <details>). */
.spoiler { margin: var(--space-4) 0; }
.spoiler__toggle {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  font: inherit;
  font-weight: 600;
  line-height: 1;
  color: var(--primary);
  background: var(--primary-subtle);
  border: 1px solid color-mix(in srgb, var(--primary) 32%, transparent);
  border-radius: var(--radius-full);
  cursor: pointer;
  list-style: none; /* remove default marker (Firefox) */
  transition: background .15s ease, color .15s ease, border-color .15s ease;
}
.spoiler__toggle::-webkit-details-marker { display: none; } /* Safari/Chrome */
.spoiler__toggle:hover { background: var(--primary); color: var(--text-inverse); border-color: transparent; }
.spoiler__toggle:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
/* Chevron via pseudo-element; rotates from "collapsed" caret to "expanded" on [open]. */
.spoiler__toggle::after {
  content: "";
  width: .5em;
  height: .5em;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(45deg);
  transition: transform .15s ease;
}
.spoiler[open] .spoiler__toggle::after { transform: rotate(-135deg); }
@media (prefers-reduced-motion: reduce) {
  .spoiler__toggle::after { transition: none; }
}
.spoiler__body { margin-top: var(--space-3); }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_css.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add core/static/core/css/app.css courses/tests/test_spoiler_css.py
git commit -m "feat(spoiler): themed disclosure CSS (marker suppression + chevron)"
```

---

### Task 9: Transfer trio (export / validate / import)

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_spoiler` + `SERIALIZERS`; import `SpoilerElement`)
- Modify: `courses/transfer/payloads.py` (`_val_spoiler` + `VALIDATORS`)
- Modify: `courses/transfer/importer.py` (`_build_spoiler` + `BUILDERS`; import `SpoilerElement`)
- Test: `courses/tests/test_spoiler_transfer.py`

**Interfaces:**
- Consumes: `SpoilerElement` (Task 1); helpers `_exact_keys(obj, keys, what)`, `check_str(value, what, *, max_length=None)`, `_clean_save(obj)`.
- Produces: transfer key `spoiler` in all three registries; `_ser_spoiler → {"label", "body"}`; strict `_val_spoiler`; `_build_spoiler` via `_clean_save`. No `FORMAT_VERSION` bump; `spoiler` NOT added to `NESTABLE_TYPE_KEYS`.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_spoiler_transfer.py`:

```python
import pytest

from courses.builder import NESTABLE_TYPE_KEYS
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import TransferError


def test_registered_in_all_three_and_not_nestable():
    assert "spoiler" in SERIALIZERS
    assert "spoiler" in VALIDATORS
    assert "spoiler" in BUILDERS
    assert "spoiler" not in NESTABLE_TYPE_KEYS  # not nestable in v1
    # invariant guarded by the tabs transfer tests
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip():
    from courses.models import SpoilerElement

    model, ser = SERIALIZERS["spoiler"]
    assert model is SpoilerElement
    el = SpoilerElement.objects.create(label="Hint", body="<p>x</p>")
    payload = ser(el, {})
    assert payload == {"label": "Hint", "body": "<p>x</p>"}
    built, media = BUILDERS["spoiler"](payload, {})
    assert built.label == "Hint"
    assert "<p>x</p>" in built.body
    assert media == ()


def test_validator_is_strict():
    val = VALIDATORS["spoiler"]
    # valid shape
    assert val({"label": "a", "body": "<p>x</p>"}, "e1", {}) == set()
    # missing key
    with pytest.raises(TransferError):
        val({"body": "<p>x</p>"}, "e1", {})
    # unknown key
    with pytest.raises(TransferError):
        val({"label": "a", "body": "x", "extra": 1}, "e1", {})
    # non-string body
    with pytest.raises(TransferError):
        val({"label": "a", "body": 5}, "e1", {})
    # overlong label
    with pytest.raises(TransferError):
        val({"label": "x" * 121, "body": "x"}, "e1", {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_spoiler_transfer.py -q`
Expected: FAIL — `"spoiler"` not in the registries.

- [ ] **Step 3: Add the serializer**

In `courses/transfer/export.py`, add `SpoilerElement` to the model imports (next to `from courses.models import RevealGateElement`), add the serializer near `_ser_reveal_gate` — **return BOTH keys; do NOT copy `_ser_reveal_gate`, which drops `body`**:

```python
def _ser_spoiler(concrete, media_ids):
    return {"label": concrete.label, "body": concrete.body}
```

Register in `SERIALIZERS` (next to `"reveal_gate"`):

```python
    "spoiler": (SpoilerElement, _ser_spoiler),
```

- [ ] **Step 4: Add the validator**

In `courses/transfer/payloads.py`, add near `_val_reveal_gate` — **strict, mirroring `_val_text` (not the lax no-op)**:

```python
def _val_spoiler(data, elid, media_kinds):
    _exact_keys(data, ["label", "body"], _("spoiler data"))
    check_str(data["body"], _("body"))
    check_str(data["label"], _("label"), max_length=120)
    return set()
```

Register in `VALIDATORS` (next to `"reveal_gate"`):

```python
    "spoiler": _val_spoiler,
```

- [ ] **Step 5: Add the builder**

In `courses/transfer/importer.py`, add `SpoilerElement` to the model imports, add near `_build_reveal_gate` — **use `_clean_save` (like `_build_text`), NOT `.objects.create`**:

```python
def _build_spoiler(data, assets):
    return _clean_save(SpoilerElement(label=data.get("label", ""), body=data["body"])), ()
```

Register in `BUILDERS` (next to `"reveal_gate"`):

```python
    "spoiler": _build_spoiler,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_spoiler_transfer.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/tests/test_spoiler_transfer.py
git commit -m "feat(spoiler): export/validate/import transfer trio"
```

---

### Task 10: i18n catalogs (EN default + PL) + full DoD

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (translate the new strings)
- Regenerate: message catalogs
- Test: full suite + lint

**Interfaces:**
- Consumes: all translatable strings introduced above (`"Spoiler"`, `"Reveal"`, `"Button text"`, the helptext, `"spoiler data"`, `"Rozwijana treść"` target, `"Pokaż"` target).

- [ ] **Step 1: Regenerate the message catalog**

Run: `uv run python manage.py makemessages -l pl -l en`
(If the project keeps only a `pl` catalog with EN as source msgids, run `uv run python manage.py makemessages -l pl`.) Confirm the new msgids appear: `Spoiler`, `Reveal`, `Button text`, `Shown on the spoiler button. Leave blank for the default "Reveal".`, `spoiler data`.

**`en` catalog note:** `LANGUAGE_CODE=en`, so the `en` catalog uses empty `msgstr ""` as intentional passthrough (English msgid is the source of truth — e.g. `msgid "Show more"` → `msgstr ""`). Leave the new `en` entries with empty msgstrs; do NOT translate them. If `makemessages` marks any new `en` entry `#, fuzzy`, remove that flag (an empty-but-fuzzy entry can trip the Step-4 catalog check), but do not add English text.

- [ ] **Step 2: Fill in the Polish translations**

In `locale/pl/LC_MESSAGES/django.po`, set (and **remove any `#, fuzzy` flags** on these entries so they are used):

```
msgid "Spoiler"
msgstr "Rozwijana treść"

msgid "Reveal"
msgstr "Pokaż"

msgid "Button text"
msgstr "Tekst przycisku"

msgid "Shown on the spoiler button. Leave blank for the default “Reveal”."
msgstr "Wyświetlany na przycisku. Pozostaw puste, aby użyć domyślnego „Pokaż”."

msgid "spoiler data"
msgstr "dane elementu „Rozwijana treść”"
```

(If `Button text` already exists from the reveal-gate work, reuse its existing translation rather than duplicating.)

- [ ] **Step 3: Compile messages**

Run: `uv run python manage.py compilemessages -l pl`
Expected: no errors; `django.mo` regenerated.

- [ ] **Step 4: Run the i18n catalog tests**

Run: `uv run pytest -k "i18n or messages or catalog" -q`
Expected: PASS (no obsolete `#~` entries, no fuzzy on the new strings).

- [ ] **Step 5: Full DoD — lint + format + whole suite**

Run:
```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```
Expected: all green. Fix any failures before committing.

- [ ] **Step 6: Commit**

```bash
git add locale/ 
git commit -m "i18n(spoiler): EN/PL catalog strings for the Spoiler element"
```

---

## Self-Review Notes (for the executor)

- **Element-count assertions:** this project uses membership assertions (`"xelement" in ELEMENT_MODELS`), not a hard count — Task 1's `test_registered_in_element_models` matches that convention; there is no numeric total to bump.
- **No `save_element` edit:** the generic `else` branch in `courses/builder.py` dispatches any `FORM_FOR_TYPE` key, and spoiler is not nestable, so `resolve_scope` returns top-level unchanged. No builder change is needed (verified against builder.py:415-424).
- **No editor.html `<script>` and no JS enhancer:** native `<details>` shows the summary + (collapsed) body without JS, so the preview pane works unwired. Math renders via the whole-document `math.js` pass (Task 5 ensures it loads). Do not add a JS file.
- **Verification obligation (spec):** after Task 5 + Task 8, manually or via `/run` confirm inline `\(...\)` and display math render inside a *collapsed* spoiler at page load. If (and only if) they do not, the bounded fix is dispatching a bubbling `libli:reveal` on the `<details>` `toggle`→open — not a speculative enhancer.
