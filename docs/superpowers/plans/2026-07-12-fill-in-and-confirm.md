# Fill in & confirm Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Fill in & confirm" interactive element — a reveal gate whose trigger is a fill-in-the-blank; a correct, server-checked answer locks the inputs, removes Confirm, and reveals the following siblings via the existing cascade engine.

**Architecture:** A new generic-path `FillGateElement` (stem token-stem + `answers` JSON) reuses the fill-blank parser (`fillblank.parse`/`to_author_stem`/`render_inputs`) for authoring/render and `marking.blank_matches` for a server-side JSON check endpoint. The reveal cascade in `reveal.js` is refactored to export `libliRevealCascade(triggerEl, {hideWrapper})`, shared by the plain gate and a new `fillgate.js` enhancer. Nestable inside Tabs; records no marks; fail-open without JS.

**Tech Stack:** Django 5.2, Python, vanilla JS (no framework), pytest + Playwright e2e, gettext i18n (EN/PL), `uv` tooling.

## Global Constraints

- Tooling: shell `ruff`/`pytest`/`python`/`manage.py` are NOT on PATH — always invoke via `uv run` (e.g. `uv run pytest ...`, `uv run ruff check .`, `uv run python manage.py ...`).
- Full unit suite excludes e2e by default (`addopts = -m 'not e2e'`); run e2e explicitly and **foreground only** (`uv run pytest -m e2e path::test -q`), never backgrounded/detached.
- Three key namespaces (mirror the reveal-gate precedent): `model_name = fillgateelement`, form/editor key = `fillgate`, transfer key = `fill_gate`. The form→transfer alias lives ONLY in `_NESTABLE_FORM_KEY_ALIASES`.
- Records NO marks/analytics. The check endpoint only reports correctness.
- Python i18n: `from django.utils.translation import gettext_lazy as _`. Templates: `{% load i18n %}` + `{% trans %}`. Single project-level `locale/{en,pl}/LC_MESSAGES/django.po`.
- Palette label EN "Fill in & confirm" / PL "Uzupełnij i potwierdź"; Confirm button EN "Confirm" / PL "Potwierdź"; try-again EN "Not quite — try again" / PL "Niezupełnie — spróbuj ponownie".
- Reuse existing helpers verbatim — do NOT reimplement matching or parsing: `courses.fillblank.{parse,to_author_stem,render_inputs,strip_sentinel}`, `courses.marking.blank_matches`, `courses.sanitize.sanitize_html`, the `{% render_fill_blanks el %}` tag.
- Spec: `docs/superpowers/specs/2026-07-12-fill-in-and-confirm-design.md`.

---

### Task 1: `FillGateElement` model + registration + migration

**Files:**
- Modify: `courses/models.py` (add model near `RevealGateElement` ~line 469; add `"fillgateelement"` to `ELEMENT_MODELS` ~line 259-279)
- Create: `courses/migrations/0037_fillgateelement.py` (generated)
- Test: `courses/tests/test_fillgate_model.py`

**Interfaces:**
- Produces: `courses.models.FillGateElement` with fields `stem: TextField`, `answers: JSONField(default=list)`, `elements = GenericRelation(Element)`, and a `render()` override returning the `fillgateelement.html` template with `{"el": self, "eid": <join pk or 0>}`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_model.py
import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import ELEMENT_MODELS, Element, FillGateElement


@pytest.mark.django_db
def test_fillgate_defaults_and_registration():
    el = FillGateElement.objects.create(stem="a ￿0￿ b", answers=[["x", "y"]])
    assert el.answers == [["x", "y"]]
    # answers defaults to an empty list, not null/dict
    el2 = FillGateElement.objects.create(stem="")
    assert el2.answers == []
    assert "fillgateelement" in ELEMENT_MODELS


@pytest.mark.django_db
def test_fillgate_generic_relation_and_render(unit_factory):
    # unit_factory: an existing fixture that returns a saved unit ContentNode.
    unit = unit_factory()
    el = FillGateElement.objects.create(stem="hi ￿0￿", answers=[["a"]])
    join = Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    # GenericRelation reverse accessor resolves the join row
    assert el.elements.first().pk == join.pk
    # NOTE: render() output (data-element-pk exposure) is asserted in Task 3, once the
    # fillgateelement.html template exists — render() cannot be tested here in isolation.
```

> If no `unit_factory` fixture exists, use the project's standard unit-creation helper (grep `tests/factories.py` / `conftest.py` for how other element tests build a `unit`). Match the existing pattern.
>
> **The `render()` override is still added to the model in Step 3 of THIS task** (its code is below); it is simply not exercised until the template lands in Task 3.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_model.py -q`
Expected: FAIL — `ImportError: cannot import name 'FillGateElement'`.

- [ ] **Step 3: Implement the model**

In `courses/models.py`, add after `RevealGateElement` (near line 476):

```python
class FillGateElement(ElementBase):
    """A 'Fill in & confirm' gate: a reveal gate whose trigger is a fill-in blank.
    A correct (server-checked) answer reveals the following siblings. Records no
    marks. `stem` is the ￿n￿ token-stem (from fillblank.parse); `answers` is the
    parsed accepted-alternatives list (list[list[str]]). See the design doc."""

    stem = models.TextField(blank=True)
    answers = models.JSONField(default=list)
    elements = GenericRelation(Element)  # cascade: deleting this removes its join-row

    def render(self):
        from django.template.loader import render_to_string

        join = self.elements.order_by("pk").first()
        return render_to_string(
            "courses/elements/fillgateelement.html",
            {"el": self, "eid": join.pk if join else 0},
        )
```

Add `"fillgateelement"` as the last entry in `ELEMENT_MODELS` (after `"revealgateelement"`).

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations courses`
Expected: creates `courses/migrations/0037_fillgateelement.py` (CreateModel + an AlterField on `element.content_type` re-listing `model__in`). Confirm the filename/number is `0037`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_model.py -q`
Expected: PASS (both tests).

- [ ] **Step 6: Lint + migration check**

Run: `uv run ruff check courses/models.py courses/tests/test_fillgate_model.py && uv run ruff format --check courses/tests/test_fillgate_model.py && uv run python manage.py makemigrations --check --dry-run`
Expected: clean; no pending migrations.

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0037_fillgateelement.py courses/tests/test_fillgate_model.py
git commit -m "feat(fillgate): FillGateElement model + migration"
```

---

### Task 2: `FillGateElementForm` + FORM_FOR_TYPE + save (answers persistence)

**Files:**
- Modify: `courses/element_forms.py` (add form near `RevealGateElementForm` ~line 186; add `"fillgate"` to `FORM_FOR_TYPE` ~line 792)
- Modify: `courses/views_manage.py` (add `"fillgate"` to the `element_add` allow-tuple ~line 872-891 and the `element_save` allow-tuple ~line 926-947)
- Test: `courses/tests/test_fillgate_form.py`

**Interfaces:**
- Consumes: `FillGateElement` (Task 1); `courses.fillblank`, `courses.sanitize.sanitize_html`.
- Produces: `FillGateElementForm` (form key `"fillgate"` in `FORM_FOR_TYPE`) whose `save()` persists `stem` (token-stem) and `answers` (parsed `list[list[str]]`); `__init__` re-hydrates `{{answer}}` markup for editing.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_form.py
import pytest

from courses.element_forms import FORM_FOR_TYPE, FillGateElementForm
from courses.models import FillGateElement


@pytest.mark.django_db
def test_form_parses_stem_and_persists_answers():
    form = FillGateElementForm(data={"stem": "2+2 = {{4|four}}"})
    assert form.is_valid(), form.errors
    obj = form.save()
    obj.refresh_from_db()
    assert obj.answers == [["4", "four"]]
    assert "￿0￿" in obj.stem  # stored as token-stem, not {{...}}
    assert FORM_FOR_TYPE["fillgate"] is FillGateElementForm


@pytest.mark.django_db
def test_form_rejects_stem_without_blanks():
    form = FillGateElementForm(data={"stem": "no blanks here"})
    assert not form.is_valid()
    assert "stem" in form.errors


@pytest.mark.django_db
def test_edit_shows_author_markup():
    obj = FillGateElement.objects.create(stem="x ￿0￿", answers=[["a", "b"]])
    form = FillGateElementForm(instance=obj)
    assert form.initial["stem"] == "x {{a|b}}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_form.py -q`
Expected: FAIL — `ImportError: cannot import name 'FillGateElementForm'`.

- [ ] **Step 3: Implement the form**

In `courses/element_forms.py`, add after `RevealGateElementForm` (~line 189):

```python
class FillGateElementForm(forms.ModelForm):
    parsed_blanks = None  # list[list[str]] after a successful clean_stem

    class Meta:
        model = FillGateElement
        fields = ["stem"]
        widgets = {"stem": forms.Textarea(attrs={"rows": 3, "data-rte-source": ""})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Editing: show the author's {{answer}} markup, not the stored ￿n￿ token-stem.
        if self.instance and self.instance.pk:
            self.initial["stem"] = fillblank.to_author_stem(
                self.instance.stem, self.instance.answers or []
            )

    def clean_stem(self):
        raw = self.cleaned_data.get("stem", "")
        clean = fillblank.strip_sentinel(sanitize_html(raw))
        try:
            token_stem, blanks = fillblank.parse(clean)
        except fillblank.FillBlankError:
            raise forms.ValidationError(
                _("Mark at least one blank with {{answer}} (use | for alternatives).")
            ) from None
        self.parsed_blanks = blanks
        return token_stem

    def save(self, commit=True):
        # `answers` is not a form field, so set it from the parsed blanks here.
        self.instance.answers = self.parsed_blanks or []
        return super().save(commit=commit)
```

Ensure `FillGateElement` is imported in this module's model imports, and add `"fillgate": FillGateElementForm,` to `FORM_FOR_TYPE` (after the `"tabs"` entry). Confirm `fillblank`, `sanitize_html`, and `_` are already imported at module top (they are — used by `FillBlankQuestionElementForm`).

- [ ] **Step 4: Add the form key to the allow-tuples**

In `courses/views_manage.py`, add `"fillgate",` to BOTH the `element_add` allow-tuple (~after `"revealgate",` at line 882) and the `element_save` allow-tuple (~after `"revealgate",` at line 937).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_form.py -q`
Expected: PASS (all three).

- [ ] **Step 6: Lint**

Run: `uv run ruff check courses/element_forms.py courses/views_manage.py courses/tests/test_fillgate_form.py && uv run ruff format --check courses/tests/test_fillgate_form.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add courses/element_forms.py courses/views_manage.py courses/tests/test_fillgate_form.py
git commit -m "feat(fillgate): form + FORM_FOR_TYPE + allow-tuples"
```

---

### Task 3: Student template `fillgateelement.html`

**Files:**
- Create: `templates/courses/elements/fillgateelement.html`
- Test: `courses/tests/test_fillgate_template.py`

**Interfaces:**
- Consumes: `FillGateElement.render()` context `{el, eid}` (Task 1); `{% render_fill_blanks el %}` tag.
- Produces: a container `<div data-reveal-gate data-fillgate>` with an inert-action form carrying `data-check-url` + `data-element-pk`, the blank inputs, a hidden Confirm submit, a feedback slot, and a persistent hidden translated message node.

> **URL ordering (resolved):** the `fillgate_check` URL name is defined in **Task 6** (endpoint + `urls.py`), which executes AFTER this task. To keep this task self-contained, this template's `data-check-url` uses the **hardcoded path** `/courses/element/{{ eid }}/fillgate-check/` (a stable, project-owned route). Task 6, Step 8 switches it to `{% url 'courses:fillgate_check' eid %}` once the named route exists. The reversed URL produces the identical path, so the Task 3 test (which asserts the presence of `data-check-url`, not its exact value) still passes after the Task 6 switch.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_template.py
import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import Element, FillGateElement


@pytest.mark.django_db
def test_template_structure(unit_factory):
    unit = unit_factory()
    el = FillGateElement.objects.create(stem="2+2 = ￿0￿", answers=[["4"]])
    join = Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    html = el.render()
    assert "data-reveal-gate" in html and "data-fillgate" in html
    assert 'name="blank"' in html  # render_fill_blanks emitted an input
    assert f'data-element-pk="{join.pk}"' in html
    assert "data-check-url" in html
    assert "data-fillgate-message" in html  # persistent translated message node
    # Confirm ships hidden (armed by fillgate.js)
    assert "fillgate__confirm" in html and "hidden" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_template.py -q`
Expected: FAIL — `TemplateDoesNotExist: courses/elements/fillgateelement.html`.

- [ ] **Step 3: Create the template**

`templates/courses/elements/fillgateelement.html`:

```html
{% load i18n courses_extras %}
<div class="fillgate" data-reveal-gate data-fillgate>
  {% comment %}The check URL lives in data-check-url (NOT the form action), so a no-JS
  Enter/submit cannot navigate to the JSON endpoint. fillgate.js reads data-check-url /
  data-element-pk and treats pk 0 (unsaved preview) as a no-op.{% endcomment %}
  {% comment %}data-check-url is the hardcoded path for now; Task 6 Step 8 switches it to
  {% url 'courses:fillgate_check' eid %} once the named route exists (identical output).{% endcomment %}
  <form class="fillgate__form"
        data-check-url="/courses/element/{{ eid }}/fillgate-check/"
        data-element-pk="{{ eid }}">
    <div class="fillgate__body">{% render_fill_blanks el %}</div>
    <button type="submit" class="fillgate__confirm" hidden>{% trans "Confirm" %}</button>
    <p class="fillgate__feedback" data-fillgate-feedback hidden></p>
    {% comment %}Persistent, pre-translated message source; fillgate.js copies its text
    into the feedback slot on a wrong answer and hides it on reset — never destroys it.{% endcomment %}
    <span class="fillgate__msg" data-fillgate-message hidden>{% trans "Not quite — try again" %}</span>
  </form>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_fillgate_template.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/courses/elements/fillgateelement.html courses/tests/test_fillgate_template.py
git commit -m "feat(fillgate): student render template"
```

---

### Task 4: Authoring UI — edit partial, labels, palette card, icon, summary

**Files:**
- Create: `templates/courses/manage/editor/_edit_fillgate.html`
- Modify: `courses/views_manage.py` (`_EDITOR_TYPE_LABELS` ~line 738)
- Modify: `templates/courses/manage/editor/_add_menu.html` (Interactive group ~line 25-30)
- Modify: `templates/courses/manage/_icon_sprite.html` (add `#el-fillgate` symbol ~near line 30)
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS` ~line 26; `element_summary` ~line 72)
- Test: `courses/tests/test_fillgate_authoring.py`

**Interfaces:**
- Consumes: `FillGateElementForm` (Task 2), `FillGateElement` (Task 1).
- Produces: a working `manage_element_add` render path for `type=fillgate`; an `element_summary` branch for `FillGateElement`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_authoring.py
import pytest
from django.urls import reverse

from courses.models import FillGateElement
from courses.templatetags.courses_manage_extras import element_summary


@pytest.mark.django_db
def test_element_add_renders_edit_partial(manage_client, unit_in_managed_course):
    # manage_client: an authenticated PA/CA client; unit_in_managed_course: (slug, unit).
    slug, unit = unit_in_managed_course
    url = reverse("courses:manage_element_add", args=[slug])
    resp = manage_client.post(url, {"type": "fillgate", "unit": unit.pk})
    assert resp.status_code == 200
    assert b"name=\"stem\"" in resp.content  # the RTE textarea rendered


@pytest.mark.django_db
def test_element_summary_fillgate():
    el = FillGateElement.objects.create(stem="Cap of France is ￿0￿", answers=[["Paris"]])
    # summary falls through to the stem branch, rendering ￿0￿ as ___
    assert "Cap of France is ___" in element_summary(el)
```

> Use whatever fixtures other manage/editor tests use for an authenticated managing client + a unit (grep `test_reveal*` / `conftest.py`). Mirror them exactly; adjust the two fixture names above to the real ones.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_authoring.py -q`
Expected: FAIL — `element_add` 200 path raises `TemplateDoesNotExist: .../_edit_fillgate.html` (or 400 if the allow-tuple/label missing).

- [ ] **Step 3: Create the edit partial**

`templates/courses/manage/editor/_edit_fillgate.html`:

```html
{% load i18n %}
<div class="el-editor el-editor--fillgate">
  <label>{% trans "Prompt with blanks" %}
    <textarea name="stem" rows="3" data-rte-source>{{ form.stem.value|default:'' }}</textarea>
  </label>
  <p class="helptext">{% trans "Mark each blank with {{answer}}. Use | for alternatives, e.g. {{colour|color}}." %}</p>
  {% for e in form.stem.errors %}<p class="field-error">{{ e }}</p>{% endfor %}
</div>
```

> Check `_edit_fillblankquestion.html` for the exact RTE textarea attributes the editor JS expects (e.g. `data-rte-source`) and match them so the rich-text editor mounts.

- [ ] **Step 4: Wire the labels, palette card, icon, and summary**

`courses/views_manage.py` — add to `_EDITOR_TYPE_LABELS` (after the `"revealgate"` line):
```python
    "fillgate": gettext_lazy("Fill in & confirm"),
```

`templates/courses/manage/editor/_add_menu.html` — add inside the Interactive `typemenu__group` (after the revealgate button):
```html
      <button type="button" class="typecard" data-add-type="fillgate"><svg class="ic" aria-hidden="true" focusable="false"><use href="#el-fillgate"/></svg>{% trans "Fill in & confirm" %}</button>
```

`templates/courses/manage/_icon_sprite.html` — add near `#el-revealgate` (line 30):
```html
  <symbol id="el-fillgate" viewBox="0 0 16 16"><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" d="M1 5.5h14"/><path fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" d="M5 9l3 3 3-3"/><rect x="2" y="1.5" width="5" height="2.4" rx="0.6" fill="none" stroke="currentColor" stroke-width="1.2"/></symbol>
```

`courses/templatetags/courses_manage_extras.py` — add to `_ELEMENT_LABELS` (after `"revealgateelement"`):
```python
    "fillgateelement": _("Fill in & confirm"),
```
No `element_summary` branch is needed — `FillGateElement` has a `.stem`, so it falls through to the generic stem branch (renders `￿n￿` as `___`), which the second test asserts. Leave `element_summary` unchanged.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_authoring.py -q`
Expected: PASS (both).

- [ ] **Step 6: Lint**

Run: `uv run ruff check courses/views_manage.py courses/templatetags/courses_manage_extras.py courses/tests/test_fillgate_authoring.py && uv run ruff format --check courses/tests/test_fillgate_authoring.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/_edit_fillgate.html templates/courses/manage/editor/_add_menu.html templates/courses/manage/_icon_sprite.html courses/views_manage.py courses/templatetags/courses_manage_extras.py courses/tests/test_fillgate_authoring.py
git commit -m "feat(fillgate): authoring UI (edit partial, palette, icon, labels)"
```

---

### Task 5: Lesson context flags — `has_reveal_gate` (generalized), `has_fill_gate`, `has_math`

**Files:**
- Modify: `courses/views.py` (`build_lesson_context` ~line 197-247; `_element_has_math` ~line 118-129)
- Test: `courses/tests/test_fillgate_context.py`

**Interfaces:**
- Consumes: `FillGateElement` (Task 1), `has_math_delimiters`, `can_access_course` (already imported).
- Produces: `build_lesson_context` returns `has_reveal_gate` True for a fill-gate, a new `has_fill_gate` key, and `has_math` True when a fill-gate stem contains math (top-level and nested-in-tab).

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_context.py
import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import Element, FillGateElement
from courses.views import build_lesson_context


def _add_fillgate(unit, stem, answers):
    el = FillGateElement.objects.create(stem=stem, answers=answers)
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    return el


@pytest.mark.django_db
def test_fillgate_arms_flags(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_fillgate(unit, "plain ￿0￿", [["a"]])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_reveal_gate"] is True   # arms pre-hide + reveal.js
    assert ctx["has_fill_gate"] is True      # gates fillgate.js
    assert ctx["has_math"] is False


@pytest.mark.django_db
def test_fillgate_math_detected_top_level(lesson_unit_node, student_user):
    unit = lesson_unit_node
    _add_fillgate(unit, r"\(x^2\) = ￿0￿", [["4"]])
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True


@pytest.mark.django_db
def test_fillgate_math_detected_nested_in_tab(lesson_unit_node, student_user, tab_child_factory):
    # MANDATORY (spec Math-detection): a fill-gate nested in a tab whose stem has math
    # must set has_math via _element_has_math (the tabs recursion), not the top-level chain.
    unit = lesson_unit_node
    fg = FillGateElement.objects.create(stem=r"\(y\) = ￿0￿", answers=[["1"]])
    tab_child_factory(unit, fg)  # attach fg as a child of a TabsElement in this unit
    ctx = build_lesson_context(unit, student_user)
    assert ctx["has_math"] is True
```

> `lesson_unit_node` / `student_user`: reuse the fixtures the existing `build_lesson_context` / reveal-gate tests use (grep `test_reveal*context*` or `has_reveal_gate`). `tab_child_factory`: the nested test is **mandatory** (spec requires top-level AND nested-in-tab math coverage). Build the TabsElement + child-`Element` (parent + tab_id) the way the tabs tests do — grep `test_tabs*` / `resolve_scope` / `NESTABLE` usages for the exact join-row construction (parent = the TabsElement's join row, `tab_id` = a valid tab id from `TabsElement.normalize_labels_and_ids`). Inline that construction if no factory exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_context.py -q`
Expected: FAIL — `KeyError: 'has_fill_gate'` (and `has_math` False for the math case).

- [ ] **Step 3: Implement the flag changes**

In `courses/views.py` `build_lesson_context`, replace the `has_reveal_gate` computation (~line 215-220) with:

```python
    # Flat query (NOT scoped to parent__isnull=True) so a gate nested inside a tab —
    # children keep their own `unit` FK — is still detected. Both gate types arm the
    # pre-hide + reveal.js; only fill-gates need fillgate.js.
    has_reveal_gate = node.elements.filter(
        content_type__model__in=["revealgateelement", "fillgateelement"]
    ).exists()
    has_fill_gate = node.elements.filter(
        content_type__model="fillgateelement"
    ).exists()
```

Add `has_fill_gate` to the returned context dict (next to `"has_reveal_gate": has_reveal_gate,`):
```python
        "has_fill_gate": has_fill_gate,
```

Add a fill-gate clause to the `has_math` chain (inside the `has_math = (...)` expression, add a new `or any(...)`):
```python
        or any(
            isinstance(el.content_object, FillGateElement)
            and has_math_delimiters(el.content_object.stem)
            for el in elements
        )
```

Add a `FillGateElement` branch to `_element_has_math` (so the tabs recursion also catches a nested fill-gate) — after the `TextElement` branch:
```python
    from courses.models import FillGateElement

    if isinstance(obj, FillGateElement):
        return has_math_delimiters(obj.stem)
```

Ensure `FillGateElement` is importable where the `has_math` chain runs (add it to the existing `from courses.models import ...` used by `build_lesson_context`, or import locally).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_context.py -q`
Expected: PASS (both).

- [ ] **Step 5: Lint + regression**

Run: `uv run ruff check courses/views.py courses/tests/test_fillgate_context.py && uv run pytest courses/tests/ -k "reveal_gate or lesson_context" -q`
Expected: clean; existing reveal-gate/context tests still pass.

- [ ] **Step 6: Commit**

```bash
git add courses/views.py courses/tests/test_fillgate_context.py
git commit -m "feat(fillgate): lesson context flags (has_fill_gate + has_math)"
```

---

### Task 6: Check endpoint `fillgate_check` (view + URL)

**Files:**
- Modify: `courses/views.py` (add `fillgate_check` view near `check_answer` ~line 416)
- Modify: `courses/urls.py` (add route near `check_answer` ~line 20)
- Test: `courses/tests/test_fillgate_check.py`

**Interfaces:**
- Consumes: `FillGateElement` (Task 1), `Element`, `can_access_course`, `blank_matches`.
- Produces: `POST courses/element/<int:element_pk>/fillgate-check/` (name `fillgate_check`) → JSON `{"correct": bool, "blanks": [bool, ...]}`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_check.py
import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element, FillGateElement


def _gate(unit, answers):
    el = FillGateElement.objects.create(stem="q ￿0￿", answers=answers)
    return Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )


@pytest.mark.django_db
def test_correct_and_wrong(enrolled_client, enrolled_unit):
    unit = enrolled_unit
    join = _gate(unit, [["4", "four"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    ok = enrolled_client.post(url, {"blank": ["four"]}).json()
    assert ok == {"correct": True, "blanks": [True]}
    bad = enrolled_client.post(url, {"blank": ["5"]}).json()
    assert bad == {"correct": False, "blanks": [False]}


@pytest.mark.django_db
def test_multi_blank_and_numeric(enrolled_client, enrolled_unit):
    join = _gate(enrolled_unit, [["4"], ["3.14"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    data = enrolled_client.post(url, {"blank": ["4", "3,14"]}).json()  # comma decimal
    assert data == {"correct": True, "blanks": [True, True]}
    mixed = enrolled_client.post(url, {"blank": ["4", "9"]}).json()
    assert mixed == {"correct": False, "blanks": [True, False]}


@pytest.mark.django_db
def test_get_405_and_bad_id_404(enrolled_client, enrolled_unit):
    join = _gate(enrolled_unit, [["4"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    assert enrolled_client.get(url).status_code == 405
    assert enrolled_client.post(reverse("courses:fillgate_check", args=[999999])).status_code == 404


@pytest.mark.django_db
def test_access_denied(client_without_access, enrolled_unit):
    join = _gate(enrolled_unit, [["4"]])
    url = reverse("courses:fillgate_check", args=[join.pk])
    resp = client_without_access.post(url, {"blank": ["4"]})
    assert resp.status_code in (403, 302)  # PermissionDenied (or login redirect)
```

> Fixtures: `enrolled_client`/`enrolled_unit` = a logged-in student with course access + a lesson unit in that course; `client_without_access` = a logged-in user WITHOUT access. Reuse the fixtures `check_answer` tests use (grep `test_check_answer`); mirror them.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_check.py -q`
Expected: FAIL — `NoReverseMatch: 'fillgate_check'`.

- [ ] **Step 3: Implement the view**

In `courses/views.py`, near `check_answer` (~line 416), add:

```python
@require_POST
@login_required
def fillgate_check(request, element_pk):
    """Server-side check for a Fill-in-&-confirm gate. Reports correctness only —
    NOTHING is persisted. Flat route (no slug/node_pk): the course is derived from
    the element's join row for the access gate."""
    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk
    )
    # Access check FIRST (before the type 404), so a user without course access
    # cannot distinguish a fill-gate from a non-fill-gate id by probing pks.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    concrete = element.content_object
    if not isinstance(concrete, FillGateElement):
        raise Http404("not a fill-gate element")
    answers = concrete.answers or []
    n = len(answers)
    values = (request.POST.getlist("blank") + [""] * n)[:n]
    results = [blank_matches(values[i], answers[i]) for i in range(n)]
    return JsonResponse({"correct": bool(results) and all(results), "blanks": results})
```

Confirm imports at the top of `courses/views.py`: `from django.http import JsonResponse` (add if missing), `from courses.marking import blank_matches` (add), and `FillGateElement` in the `from courses.models import ...` block. `Http404`, `get_object_or_404`, `PermissionDenied`, `require_POST`, `login_required`, `Element`, `can_access_course` are already imported (used by `check_answer`).

- [ ] **Step 4: Add the URL**

In `courses/urls.py`, add near `check_answer` (inside `urlpatterns`):
```python
    path(
        "courses/element/<int:element_pk>/fillgate-check/",
        views.fillgate_check,
        name="fillgate_check",
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_check.py -q`
Expected: PASS (all four).

- [ ] **Step 6: Lint**

Run: `uv run ruff check courses/views.py courses/urls.py courses/tests/test_fillgate_check.py && uv run ruff format --check courses/tests/test_fillgate_check.py`
Expected: clean.

- [ ] **Step 7: Switch the template to the named URL**

Now that `courses:fillgate_check` exists, replace the hardcoded path in `templates/courses/elements/fillgateelement.html` (added in Task 3) with the named-URL tag, and drop the now-obsolete `{% comment %}` note above it:

```html
  <form class="fillgate__form"
        data-check-url="{% url 'courses:fillgate_check' eid %}"
        data-element-pk="{{ eid }}">
```

Run: `uv run pytest courses/tests/test_fillgate_template.py -q`
Expected: PASS (the reversed URL produces the identical `/courses/element/<pk>/fillgate-check/` path, so `data-check-url` is still present).

- [ ] **Step 8: Commit**

```bash
git add courses/views.py courses/urls.py templates/courses/elements/fillgateelement.html courses/tests/test_fillgate_check.py
git commit -m "feat(fillgate): server-side check endpoint + named URL in template"
```

---

### Task 7: `reveal.js` refactor — export `libliRevealCascade`, narrow selector, focus resolution

**Files:**
- Modify: `courses/static/courses/js/reveal.js`
- Test: `courses/tests/test_reveal_refactor_static.py` (static assertions) + run existing reveal-gate e2e (regression)

**Interfaces:**
- Produces: `window.libliRevealCascade(triggerEl, {hideWrapper})` — runs the sibling-reveal cascade from `triggerEl`'s wrapper, stopping at the next gate, with focus resolved to a focusable node; hides the trigger's wrapper only when `hideWrapper !== false`. The plain gate's click handler now calls it with `{hideWrapper: true}`. `initRevealGates` binds click enhancement ONLY to plain gate buttons (`button.reveal-gate[data-reveal-gate]`), never the fill-gate container.

- [ ] **Step 1: Write the failing test (static assertions)**

```python
# courses/tests/test_reveal_refactor_static.py
from pathlib import Path

SRC = Path("courses/static/courses/js/reveal.js").read_text(encoding="utf-8")


def test_exports_cascade():
    assert "window.libliRevealCascade" in SRC


def test_click_enhancement_is_narrowed_to_plain_gate():
    # The click-binding selector must not match the fill-gate container. NOTE: this is a
    # source-presence guard only; the BEHAVIORAL no-grading-bypass guarantee (clicking
    # inside the fill-gate container reveals nothing) is asserted by Task 12 e2e item 4.
    assert "button.reveal-gate[data-reveal-gate]" in SRC


def test_focus_targets_fill_gate_input():
    # Focus resolution must special-case a fill-gate (its <div> is not focusable).
    assert "data-fillgate" in SRC and 'input[name="blank"]' in SRC
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_reveal_refactor_static.py -q`
Expected: FAIL (strings absent).

- [ ] **Step 3: Refactor reveal.js**

Replace the `reveal(btn)` function and `initRevealGates` selector. New content (keep the existing `scopeOf`, `ownWrapper`, `isGateWrapper`, `firstRevealed`, `initOne` as-is except where noted):

```javascript
  // Resolve a FOCUSABLE node inside a gate wrapper. A plain gate is a <button>
  // (focusable); a fill-gate is a <div> whose first blank input is the focus target
  // (focusing the div itself is a silent no-op).
  function focusTargetIn(wrapper) {
    var gate = wrapper.querySelector("[data-reveal-gate]");
    if (!gate) return null;
    if (gate.matches("[data-fillgate]")) {
      var input = gate.querySelector('input[name="blank"]');
      if (input) return input;
      if (!gate.hasAttribute("tabindex")) gate.setAttribute("tabindex", "-1");
      return gate;
    }
    return gate; // plain gate <button>
  }

  // Shared cascade engine. Reveals following siblings from `triggerEl`'s wrapper,
  // stops after the next gate wrapper, dispatches libli:reveal, and moves focus.
  // Hides the trigger's own wrapper only when hideWrapper !== false (the plain gate
  // self-consumes; the fill-gate keeps its answered Q&A visible).
  function cascadeFrom(triggerEl, opts) {
    opts = opts || {};
    var hideWrapper = opts.hideWrapper !== false;
    var scope = scopeOf(triggerEl);
    if (!scope) return;
    var gateWrap = ownWrapper(triggerEl, scope);
    if (!gateWrap) return;

    var node = gateWrap.nextElementSibling;
    var lastRevealed = null;
    while (node) {
      node.classList.add("reveal-shown");
      node.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      lastRevealed = node;
      if (isGateWrapper(node, scope)) break;
      node = node.nextElementSibling;
    }

    if (hideWrapper) {
      gateWrap.classList.remove("reveal-shown");
      gateWrap.hidden = true;
    }

    var target =
      lastRevealed && isGateWrapper(lastRevealed, scope)
        ? focusTargetIn(lastRevealed)
        : null;
    target = target || firstRevealed(gateWrap, scope);
    if (!target) {
      scope.setAttribute("tabindex", "-1");
      if (window.getComputedStyle(scope).display === "contents") {
        scope.style.display = "block";
      }
      target = scope;
    }
    if (target && target.focus) target.focus();
  }

  function reveal(btn) {
    cascadeFrom(btn, { hideWrapper: true });
  }
```

Change `initRevealGates` to narrow the enhancement selector so the fill-gate container never gets a plain click handler:

```javascript
  function initRevealGates(root) {
    var scope = root || document;
    var sel = "button.reveal-gate[data-reveal-gate]";
    if (scope.matches && scope.matches(sel)) initOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll(sel), initOne);
  }
```

Add the export next to `window.libliInitRevealGates = initRevealGates;`:
```javascript
  window.libliRevealCascade = cascadeFrom;
```

- [ ] **Step 4: Run static tests + lint**

Run: `uv run pytest courses/tests/test_reveal_refactor_static.py -q`
Expected: PASS.

- [ ] **Step 5: Regression — existing reveal-gate e2e must stay green**

Run (foreground): `uv run pytest -m e2e -k reveal -q`
Expected: PASS — the plain gate's behavior (cascade + self-consume + focus) is unchanged.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/reveal.js courses/tests/test_reveal_refactor_static.py
git commit -m "refactor(reveal): export libliRevealCascade; narrow click selector; focusable target"
```

---

### Task 8: `fillgate.js` enhancer + wiring (editor + lesson page + watchdog)

**Files:**
- Create: `courses/static/courses/js/fillgate.js`
- Modify: `templates/courses/manage/editor/editor.html` (add script after reveal.js ~line 140)
- Modify: `courses/static/courses/js/editor.js` (re-init after `libliInitRevealGates(preview)` ~line 77)
- Modify: `templates/courses/lesson_unit.html` (prepaint watchdog ~line 4-18; script load ~line 58)
- Test: `courses/tests/test_fillgate_wiring.py`

**Interfaces:**
- Consumes: `window.libliRevealCascade` (Task 7); the endpoint (Task 6); template attrs `data-check-url`/`data-element-pk`/`data-fillgate-message` (Task 3); `has_fill_gate` (Task 5).
- Produces: `window.libliInitFillGates(root)`; `window.__fillGateBooted`; the enhancer loaded in the editor preview and on the student lesson page.

- [ ] **Step 1: Write the failing test (script presence)**

```python
# courses/tests/test_fillgate_wiring.py
import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from courses.models import Element, FillGateElement


@pytest.mark.django_db
def test_editor_loads_fillgate_js(manage_client, managed_unit):
    slug, unit = managed_unit
    resp = manage_client.get(reverse("courses:manage_editor", args=[slug, unit.pk]))
    assert b"courses/js/fillgate.js" in resp.content


@pytest.mark.django_db
def test_lesson_loads_fillgate_js_only_with_gate(enrolled_client, enrolled_unit):
    unit = enrolled_unit
    url = reverse("courses:lesson_unit", args=[unit.course.slug, unit.pk])
    # No fill-gate yet → not loaded
    assert b"courses/js/fillgate.js" not in enrolled_client.get(url).content
    # Add a fill-gate → loaded
    el = FillGateElement.objects.create(stem="q ￿0￿", answers=[["a"]])
    Element.objects.create(
        unit=unit,
        content_type=ContentType.objects.get_for_model(FillGateElement),
        object_id=el.pk,
    )
    assert b"courses/js/fillgate.js" in enrolled_client.get(url).content
```

> Fixtures: `manage_client`/`managed_unit` mirror Task 4; `enrolled_client`/`enrolled_unit` mirror Task 6.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_wiring.py -q`
Expected: FAIL — `fillgate.js` not present.

- [ ] **Step 3: Create the enhancer**

`courses/static/courses/js/fillgate.js`:

```javascript
(function () {
  "use strict";

  // Parse-time boot flag: the lesson_unit.html prepaint watchdog fails the gate OPEN
  // (disarms the pre-hide) if this flag is still falsy at DOMContentLoaded, so a
  // booted reveal.js + a dead fillgate.js can't trap content permanently hidden.
  window.__fillGateBooted = true;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? m[1] : "";
  }

  function inputs(form) {
    return form.querySelectorAll('input[name="blank"]');
  }

  // Clear the previous attempt: drop wrong-markers and hide the message (never
  // destroy the message source node).
  function reset(form) {
    Array.prototype.forEach.call(inputs(form), function (inp) {
      inp.classList.remove("is-wrong");
    });
    var slot = form.querySelector("[data-fillgate-feedback]");
    if (slot) slot.hidden = true;
  }

  function showWrong(form, blanks) {
    var ins = inputs(form);
    for (var i = 0; i < ins.length; i++) {
      if (blanks && blanks[i] === false) ins[i].classList.add("is-wrong");
    }
    var msg = form.querySelector("[data-fillgate-message]");
    var slot = form.querySelector("[data-fillgate-feedback]");
    if (msg && slot) {
      slot.textContent = msg.textContent;  // copy the pre-translated text
      slot.hidden = false;
    }
  }

  function lock(form) {
    Array.prototype.forEach.call(inputs(form), function (inp) {
      inp.readOnly = true;
      inp.classList.add("is-correct");
    });
    var btn = form.querySelector(".fillgate__confirm");
    if (btn) btn.remove();  // Confirm is done
    var container = form.closest("[data-fillgate]");
    if (container) container.classList.add("fillgate--done");
    return container;
  }

  function submit(form) {
    var pk = form.getAttribute("data-element-pk");
    var url = form.getAttribute("data-check-url");
    if (!pk || pk === "0" || !url) return;  // unsaved preview: no-op
    reset(form);
    fetch(url, {
      method: "POST",
      headers: { "X-Requested-With": "fetch", "X-CSRFToken": csrf() },
      body: new FormData(form),
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.correct) {
          var container = lock(form);
          if (window.libliRevealCascade && container) {
            window.libliRevealCascade(container, { hideWrapper: false });
          }
        } else {
          showWrong(form, data.blanks);
        }
      })
      .catch(function () { /* leave gate closed, inputs editable */ });
  }

  function initOne(form) {
    if (form.dataset.fillgateReady === "1") return;
    form.dataset.fillgateReady = "1";
    var btn = form.querySelector(".fillgate__confirm");
    if (btn) btn.hidden = false;  // arm Confirm now that JS is live
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      submit(form);
    });
  }

  // Idempotent; re-run over the editor preview after each fragment swap.
  function initFillGates(root) {
    var scope = root || document;
    Array.prototype.forEach.call(
      scope.querySelectorAll("[data-fillgate] form"), initOne
    );
  }

  window.libliInitFillGates = initFillGates;
  initFillGates(document);
})();
```

- [ ] **Step 4: Wire the editor preview**

`templates/courses/manage/editor/editor.html` — add immediately AFTER the reveal.js `<script>` (line 140), BEFORE editor_dnd.js:
```html
  {% comment %}The preview renders the student fill-gate, whose Confirm ships `hidden`
  (fillgate.js arms it) and whose check submit is inert without JS. Load after reveal.js
  (fillgate.js calls window.libliRevealCascade). editor.js re-runs libliInitFillGates
  over the pane after each fragment swap.{% endcomment %}
  <script src="{% static 'courses/js/fillgate.js' %}" defer></script>
```

`courses/static/courses/js/editor.js` — add immediately after the `libliInitRevealGates(preview)` line (line 77):
```javascript
    if (preview && window.libliInitFillGates) window.libliInitFillGates(preview);  // re-arm fill-gates
```

- [ ] **Step 5: Wire the student lesson page + watchdog**

`templates/courses/lesson_unit.html` — extend the prepaint DOMContentLoaded check (line ~10-12) so a lesson WITH a fill-gate also fails open when fillgate.js never boots:
```html
      if (!window.__revealBooted{% if has_fill_gate %} || !window.__fillGateBooted{% endif %}) {
        document.documentElement.classList.remove("reveal-armed");
      }
```

Add the fillgate.js load immediately AFTER the conditional reveal.js load (line 58). Because `has_fill_gate` ⟹ `has_reveal_gate`, reveal.js is always present first:
```html
  {% if has_fill_gate %}<script src="{% static 'courses/js/fillgate.js' %}" defer></script>{% endif %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_wiring.py -q`
Expected: PASS (both).

- [ ] **Step 7: Commit**

```bash
git add courses/static/courses/js/fillgate.js templates/courses/manage/editor/editor.html courses/static/courses/js/editor.js templates/courses/lesson_unit.html courses/tests/test_fillgate_wiring.py
git commit -m "feat(fillgate): enhancer + editor/lesson wiring + fail-open watchdog"
```

---

### Task 9: Transfer (export/import) + nesting

**Files:**
- Modify: `courses/transfer/export.py` (add `_ser_fill_gate` + SERIALIZERS entry)
- Modify: `courses/transfer/payloads.py` (add `_val_fill_gate` + VALIDATORS entry)
- Modify: `courses/transfer/importer.py` (add `_build_fill_gate` + BUILDERS entry)
- Modify: `courses/builder.py` (add `"fill_gate",` inside the `NESTABLE_TYPE_KEYS = frozenset({...})` literal — it is an immutable frozenset literal, not a mutable collection; add `"fillgate": "fill_gate"` to the `_NESTABLE_FORM_KEY_ALIASES` dict)
- Test: `courses/tests/test_fillgate_transfer.py`

**Interfaces:**
- Consumes: `FillGateElement` (Task 1). Mirror the `reveal_gate` entries exactly (same call sites: `export.py` ~line 226, `payloads.py` ~line 480, `importer.py` ~line 635).
- Produces: transfer key `fill_gate` serializes/validates/builds `{stem, answers}`; `fill_gate` is nestable, form key `fillgate` aliased.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_transfer.py
import pytest

from courses.builder import NESTABLE_TYPE_KEYS, _NESTABLE_FORM_KEY_ALIASES
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS


def test_registered_and_nestable():
    assert "fill_gate" in SERIALIZERS
    assert "fill_gate" in VALIDATORS
    assert "fill_gate" in BUILDERS
    assert "fill_gate" in NESTABLE_TYPE_KEYS
    assert _NESTABLE_FORM_KEY_ALIASES["fillgate"] == "fill_gate"
    # invariant guarded by the tabs transfer tests
    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


@pytest.mark.django_db
def test_round_trip():
    from courses.models import FillGateElement

    model, ser = SERIALIZERS["fill_gate"]
    assert model is FillGateElement
    el = FillGateElement.objects.create(stem="s ￿0￿", answers=[["a", "b"]])
    payload = ser(el, {})
    assert payload == {"stem": "s ￿0￿", "answers": [["a", "b"]]}
    built, media = BUILDERS["fill_gate"](payload, {})
    assert built.stem == el.stem and built.answers == [["a", "b"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_transfer.py -q`
Expected: FAIL — `"fill_gate"` absent from the registries.

- [ ] **Step 3: Implement the transfer trio + nesting**

`courses/transfer/export.py` — mirror `_ser_reveal_gate`:
```python
def _ser_fill_gate(concrete, media_ids):
    return {"stem": concrete.stem, "answers": concrete.answers}
```
Add to `SERIALIZERS` (import `FillGateElement`):
```python
    "fill_gate": (FillGateElement, _ser_fill_gate),
```

`courses/transfer/payloads.py` — register a validator. Light shape-validation is fine, but it MUST use the module's own rejection helper — there is **no `PayloadError` class** in `payloads.py`; malformed payloads are rejected via `_err(_("Element '%(el)s': …"), el=elid)`, which raises the translated `TransferError`. Match that convention (and the `_`/`_err` names already imported in the module — see how `_val_table` / `_val_gallery` reject):
```python
def _val_fill_gate(data, elid, media_kinds):
    stem = data.get("stem", "")
    answers = data.get("answers", [])
    if not isinstance(stem, str) or not isinstance(answers, list) or not all(
        isinstance(alt, list) and all(isinstance(x, str) for x in alt) for alt in answers
    ):
        _err(_("Element '%(el)s': malformed fill-gate payload."), el=elid)
    return set()  # no media refs
```
Add to `VALIDATORS`: `"fill_gate": _val_fill_gate,`. (Confirm the exact `_err` signature/message style against `_val_table`/`_val_gallery` and copy it — do NOT invent an f-string exception. `_val_reveal_gate` itself is just `return set()`; this validator adds shape-checking because `answers` is structured, but the rejection path must match the module.)

`courses/transfer/importer.py` — mirror `_build_reveal_gate` (import `FillGateElement`):
```python
def _build_fill_gate(data, assets):
    return FillGateElement.objects.create(
        stem=data.get("stem", ""), answers=data.get("answers", [])
    ), ()
```
Add to `BUILDERS`: `"fill_gate": _build_fill_gate,`.

`courses/builder.py` — add `"fill_gate",` to `NESTABLE_TYPE_KEYS` and `"fillgate": "fill_gate"` to `_NESTABLE_FORM_KEY_ALIASES`:
```python
_NESTABLE_FORM_KEY_ALIASES = {"revealgate": "reveal_gate", "fillgate": "fill_gate"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest courses/tests/test_fillgate_transfer.py -q`
Expected: PASS (both).

- [ ] **Step 5: Lint + transfer regression**

Run: `uv run ruff check courses/transfer/ courses/builder.py courses/tests/test_fillgate_transfer.py && uv run pytest courses/tests/ -k "transfer or nestable" -q`
Expected: clean; existing transfer/nestable-invariant tests pass.

- [ ] **Step 6: Commit**

```bash
git add courses/transfer/ courses/builder.py courses/tests/test_fillgate_transfer.py
git commit -m "feat(fillgate): transfer trio + nestable-in-tabs"
```

---

### Task 10: Styling (student + editor)

**Files:**
- Modify: the stylesheet that already holds the `.reveal-gate` rules (grep `\.reveal-gate` under `courses/static/courses/css/` — likely `courses.css` or `app.css`)
- Test: `courses/tests/test_fillgate_css.py` (static presence) + manual/e2e visual

**Interfaces:**
- Produces: theme-token styling for `.fillgate`, `.fillgate__confirm`, input `.is-correct` / `.is-wrong` states, `.fillgate--done`, and `.fillgate__feedback`.

- [ ] **Step 1: Write the failing test**

```python
# courses/tests/test_fillgate_css.py
from pathlib import Path
import glob


def test_fillgate_css_present():
    css = "".join(
        Path(p).read_text(encoding="utf-8")
        for p in glob.glob("courses/static/courses/css/*.css")
    )
    for sel in [".fillgate", ".fillgate__confirm", ".is-wrong", ".fillgate--done"]:
        assert sel in css, sel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_fillgate_css.py -q`
Expected: FAIL.

- [ ] **Step 3: Add the CSS**

In the stylesheet holding `.reveal-gate`, add fill-gate rules using the existing theme tokens (mirror `.reveal-gate` and the quiz `.question__blank-input` conventions). The inputs already carry `question__blank-input`; scope the fill-gate look under `[data-fillgate]`. Include:
- `.fillgate` container spacing;
- `.fillgate__confirm` styled like the primary button used elsewhere (reuse the `.btn`/`.reveal-gate` token pattern);
- `[data-fillgate] .question__blank-input.is-correct` → success token border/background; `:read-only` locked affordance;
- `[data-fillgate] .question__blank-input.is-wrong` → error token border;
- `.fillgate__feedback` → error/muted text token;
- `.fillgate--done` → subtle "answered" affordance.

Use `var(--...)` tokens (grep existing usages of `--primary`, `--success`, `--danger`/`--error`, `--border-strong`) so both light and dark themes work. Do NOT hardcode colors.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_fillgate_css.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/css/ courses/tests/test_fillgate_css.py
git commit -m "feat(fillgate): student + editor styling"
```

> Visual light+dark verification happens in the pipeline's finish-stage review (screenshot both themes).

---

### Task 11: i18n EN/PL catalogs

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compiled `.mo`)

**Interfaces:**
- Produces: EN/PL translations for all new UI strings.

- [ ] **Step 1: Extract messages**

Run: `uv run python manage.py makemessages -l en -l pl --no-obsolete`
Expected: new `msgid`s appear — "Fill in & confirm", "Confirm", "Not quite — try again", "Prompt with blanks", and "Mark each blank with {{answer}}. Use | for alternatives, e.g. {{colour|color}}." (the edit-partial help text). **Already-existing msgids that are REUSED, not new** (do not add PL duplicates; they already have translations): "Show more", "Interactive", "Button text", and — importantly — the `clean_stem` validation message `"Mark at least one blank with {{answer}} (use | for alternatives)."`, which is the exact string the fill-blank form (`element_forms.py:374`) already raises and translates. So the fill-gate `clean_stem` should use that identical string (as the plan's Task 2 code does) to share the msgid; it needs no new PL entry.

- [ ] **Step 2: Translate**

In `locale/pl/LC_MESSAGES/django.po`, fill the PL `msgstr` for each NEW `msgid`:
- "Fill in & confirm" → "Uzupełnij i potwierdź"
- "Confirm" → "Potwierdź"
- "Not quite — try again" → "Niezupełnie — spróbuj ponownie"
- "Prompt with blanks" → "Treść z lukami"
- The `{{answer}}` help-text hint → translate the prose, keep `{{answer}}`/`{{colour|color}}` literal.
- (The `clean_stem` validation message is REUSED from the fill-blank form and already
  translated — do NOT add a new PL entry for it.)

Leave EN `msgstr` empty (EN uses the msgid verbatim, per the existing catalog convention). Do NOT introduce `#~` obsolete entries.

- [ ] **Step 3: Compile + verify**

Run: `uv run python manage.py compilemessages -l en -l pl && uv run pytest courses/tests/ -k "i18n or catalog or translation" -q`
Expected: compiles clean; catalog tests (no-obsolete / all-translated) pass.

> Watch the `makemessages` fuzzy-flag gotcha: remove any `#, fuzzy` markers on the new entries after translating.

- [ ] **Step 4: Commit**

```bash
git add locale/
git commit -m "i18n(fillgate): EN/PL catalogs"
```

---

### Task 12: End-to-end behavior (Playwright)

**Files:**
- Create: `courses/tests/e2e/test_fillgate_e2e.py` (match the existing e2e directory/module convention — grep the reveal-gate e2e location)

**Interfaces:**
- Consumes: everything above. Validates the full behavior matrix in a real browser.

- [ ] **Step 1: Write the e2e tests**

Mirror the reveal-gate e2e setup (grep `test_reveal*e2e*` for the fixture/harness that builds a lesson with elements and drives Playwright). Cover:
1. **Correct reveals + locks:** a fill-gate followed by a text block. Fill the correct answer, click Confirm → the following block becomes visible (`.reveal-shown`), inputs become `readonly`/`.is-correct`, Confirm is gone.
2. **Wrong stays gated:** a wrong answer → following block stays hidden, try-again message visible, the wrong input has `.is-wrong`, inputs still editable.
3. **Multi-attempt reset:** wrong then correct → no stale `.is-wrong`, message gone, block revealed.
4. **No grading bypass:** clicking inside the fill-gate container (not a correct submit) reveals nothing.
5. **Focus:** when a preceding PLAIN gate's cascade stops at a fill-gate, focus lands on the fill-gate's first `input[name="blank"]` (assert `document.activeElement`).
6. **Stop boundary:** a plain gate before a fill-gate reveals up to and including the fill-gate, then stops.
7. **Nested-in-tab:** a fill-gate inside a tab panel cascades within that panel only.

Drive the REAL gestures (type into the input, click the real Confirm) — do not shortcut via `page.evaluate`.

- [ ] **Step 2: Run the e2e (foreground, focused)**

Run: `uv run pytest -m e2e courses/tests/e2e/test_fillgate_e2e.py -q`
Expected: PASS. (Foreground only — never background/`-m e2e` detached.)

- [ ] **Step 3: Commit**

```bash
git add courses/tests/e2e/test_fillgate_e2e.py
git commit -m "test(fillgate): e2e behavior matrix"
```

---

## Definition of Done (controller-owned, after all tasks)

- [ ] Full unit suite green: `uv run pytest -q` (excludes e2e by default).
- [ ] e2e green (foreground): `uv run pytest -m e2e -k "fillgate or reveal" -q`.
- [ ] Lint/format/migrations: `uv run ruff check . && uv run ruff format --check . && uv run python manage.py makemigrations --check --dry-run`.
- [ ] i18n catalog tests green (a build that adds translatable strings must pass the no-obsolete/`#~` catalog checks).
- [ ] Visual: screenshot the fill-gate on a lesson (light + dark) — Confirm styling, correct/locked state, wrong-marker, try-again message — during the finish-stage review.

## Self-Review notes (coverage map)

- Spec §Data model → Task 1 (fields incl. `answers=JSONField(default=list)`, GenericRelation, render override) + Task 9 (transfer).
- Spec §Authoring → Task 2 (form/clean_stem/save/to_author_stem) + Task 4 (edit partial, palette, labels, icon).
- Spec §Student render + no-JS → Task 3 (inert action, data-check-url, hidden Confirm, persistent message node) + Task 8 (fillgate.js).
- Spec §Confirm flow (endpoint) → Task 6 (require_POST, can_access_course via element.unit.course, 404/405) + Task 8 (JS reset/mark/lock/cascade).
- Spec §Reveal-engine integration → Task 7 (cascade export, narrowed selector, focus).
- Spec §Pre-hide arming + math → Task 5.
- Spec §Nesting → Task 9.
- Spec §Testing → Tasks 1-12 unit + Task 12 e2e; i18n Task 11; CSS Task 10.
