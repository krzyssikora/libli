# Show more reveal-gate element — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Show more" reveal-gate content element (new "Interactive" palette group) that progressively reveals the elements following it in a lesson, cascading gate-by-gate, with a no-JS/print/quiz-safe fail-open design.

**Architecture:** A thin `RevealGateElement` (one optional `label` field), cloned from the fieldless `slidebreak` wiring but using the normal add/edit form flow. Runtime behavior is a class-gated, pre-paint CSS hide (`reveal-armed` on `<html>`, set by a synchronous inline script) plus a deferred `reveal.js` enhancer that reveals runs on click; a `DOMContentLoaded` watchdog un-arms if the engine never boots. All three pieces are co-gated on a `has_reveal_gate` flag so they emit together only on lesson pages that contain a gate.

**Tech Stack:** Django (server-rendered templates, GFK polymorphic elements), vanilla JS enhancers (`tabs.js`/`gallery.js` idiom), CSS `:has()`, pytest + Playwright e2e, `uv run` tooling, EN/PL gettext catalogs.

## Global Constraints

- Tooling: bash `ruff`/`pytest`/`python` are NOT on PATH — use `uv run ruff …`, `uv run pytest …`, `uv run python manage.py …`. DoD includes `uv run ruff check` AND `uv run ruff format --check`.
- Element type keys differ by layer: **model_name** `revealgateelement`; **form/editor key** `revealgate`; **transfer key** `reveal_gate` (snake_case).
- `NESTABLE_TYPE_KEYS` uses the form key `revealgate`.
- **No `FORMAT_VERSION` bump** — additive element type (matches `gallery`/`table`/`slide_break`).
- Migration is `0036_...` depending on `0035_...` (current latest). It also alters `Element.content_type`'s `limit_choices_to` `model__in` list (mirrors `0032`).
- All module-level translatable strings use `gettext_lazy` (never eager `gettext`) — `_` in `courses_manage_extras.py` already aliases `gettext_lazy`.
- UI icons are monochrome `currentColor` line SVGs in the shared sprite.
- Django `{# #}` comments must be single-line; use `{% comment %}` for multi-line.
- e2e must drive the REAL gesture (click), never a `page.evaluate` shortcut. Run focused e2e in the FOREGROUND. The controller owns the full-suite DoD (incl. i18n catalog tests, since this slice adds translatable strings).
- Availability: gate offered in **lesson units only**; the whole "Interactive" palette **group (heading + card)** is gated on the non-quiz flag. Gates degrade to inert in quizzes (the quiz page carries none of the triad).

---

## File structure

- **Model/migration:** `courses/models.py`, `courses/migrations/0036_revealgateelement.py`
- **Form:** `courses/element_forms.py`
- **Builder:** `courses/builder.py`
- **Views (editor):** `courses/views_manage.py`
- **Views (student consumption):** `courses/views.py`
- **Labels/summary:** `courses/templatetags/courses_manage_extras.py`
- **Icon:** `templates/courses/manage/_icon_sprite.html`
- **Palette + editor row:** `templates/courses/manage/editor/_add_menu.html`, `.../_element_row.html`; the quiz flag is threaded by adding `unit_is_quiz` to the context dicts built in `courses/views_manage.py` (`_render_editor_fragments` and the `_editor_page` view function that renders `editor.html`) — `_add_menu.html` inherits it via `{% include %}` (no `only`), so no extra template plumbing
- **Student renderer:** `templates/courses/elements/revealgateelement.html`
- **CSS:** append to `core/static/core/css/app.css` (button `[hidden]` guards, reveal-shown, print) + the render-blocking pre-hide `<style>` emitted in the lesson template
- **Reveal engine:** `courses/static/courses/js/reveal.js`
- **Lesson template wiring:** `templates/courses/lesson_unit.html`
- **Transfer:** `courses/transfer/export.py`, `.../payloads.py`, `.../importer.py`
- **i18n:** `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`
- **Tests:** `courses/tests/` (model/form/builder/renderer/palette/transfer/view-flag) + `courses/tests/e2e/` (Playwright)

> **Before each task, read the named prior-art file(s) and mirror their exact idiom** — this plan gives concrete code, but the executor must match the surrounding style and any signatures that have drifted. Prior art: `slidebreak` (thin element), `tabs` (nesting), `tabs.js`/`gallery.js` (enhancer).

---

### Task 1: `RevealGateElement` model + migration

**Files:**
- Modify: `courses/models.py` (add model class; add `"revealgateelement"` to `ELEMENT_MODELS`)
- Create: `courses/migrations/0036_revealgateelement.py`
- Test: `courses/tests/test_reveal_gate_model.py`

**Interfaces:**
- Produces: `RevealGateElement(ElementBase)` with field `label: CharField(max_length=120, blank=True)`; model_name `revealgateelement`; renders template `courses/elements/revealgateelement.html`.

- [ ] **Step 1: Read prior art.** Read `SlideBreakElement` in `courses/models.py` (its `ElementBase` subclass + `GenericRelation`), the `ELEMENT_MODELS` list, and the latest migration `courses/migrations/0035_*.py` (its `AlterField` on `Element.content_type` with `limit_choices_to`).

- [ ] **Step 2: Write the failing test.**

```python
# courses/tests/test_reveal_gate_model.py
import pytest
from django.contrib.contenttypes.models import ContentType
from courses.models import RevealGateElement, ELEMENT_MODELS

pytestmark = pytest.mark.django_db

def test_reveal_gate_creates_with_label():
    el = RevealGateElement.objects.create(label="Reveal step 2")
    assert el.pk is not None
    assert el.label == "Reveal step 2"

def test_reveal_gate_label_optional():
    el = RevealGateElement.objects.create()
    assert el.label == ""

def test_reveal_gate_in_element_models():
    assert "revealgateelement" in ELEMENT_MODELS

def test_reveal_gate_content_type_registered():
    # ContentType row exists after migrate (contenttypes' post_migrate creates
    # one for every installed model). The limit_choices_to wiring is exercised
    # end-to-end by the editor add/save test in Task 2, not asserted here.
    ct = ContentType.objects.get(app_label="courses", model="revealgateelement")
    assert ct is not None
```

- [ ] **Step 3: Run test to verify it fails.** Run: `uv run pytest courses/tests/test_reveal_gate_model.py -v` — Expected: FAIL (ImportError: cannot import name `RevealGateElement`).

- [ ] **Step 4: Add the model + registry entry.** In `courses/models.py`, next to `SlideBreakElement`, add:

```python
class RevealGateElement(ElementBase):
    """A 'Show more' gate: a thin divider that (client-side) hides the
    following sibling elements until its button is clicked. See the
    reveal-gate design doc."""
    label = models.CharField(max_length=120, blank=True)

    elements = GenericRelation(Element)
```

Add `"revealgateelement"` to the `ELEMENT_MODELS` list (keep alphabetic/existing ordering convention).

- [ ] **Step 5: Generate the migration.** Run: `uv run python manage.py makemigrations courses --name revealgateelement`. It creates `0036_revealgateelement.py` with `CreateModel(RevealGateElement)` AND an `AlterField` on `Element.content_type` — Django freezes the *resolved* `ELEMENT_MODELS` value into each migration, so adding an entry always produces this `AlterField` (it will not be "missing"). Confirm the `AlterField`'s `limit_choices_to` `model__in` now includes `revealgateelement`, and that the migration `dependencies` reference `0035_...`.

- [ ] **Step 6: Run tests to verify they pass.** Run: `uv run pytest courses/tests/test_reveal_gate_model.py -v` — Expected: PASS (4 tests).

- [ ] **Step 7: Commit.**

```bash
git add courses/models.py courses/migrations/0036_revealgateelement.py courses/tests/test_reveal_gate_model.py
git commit -m "feat(reveal-gate): add RevealGateElement model + migration"
```

---

### Task 2: Form, builder registration, nestability, editor add/save allow-tuples

**Files:**
- Modify: `courses/element_forms.py` (form + `FORM_FOR_TYPE["revealgate"]`)
- Modify: `courses/builder.py` (add `"revealgate"` to `NESTABLE_TYPE_KEYS`)
- Modify: `courses/views_manage.py` (add `"revealgate"` to `element_add` and `element_save` allow-tuples; `_EDITOR_TYPE_LABELS`)
- Test: `courses/tests/test_reveal_gate_form_builder.py`

**Interfaces:**
- Consumes: `RevealGateElement` (Task 1).
- Produces: `RevealGateElementForm` (`Meta.fields = ["label"]`); form key `"revealgate"` in `FORM_FOR_TYPE`, `NESTABLE_TYPE_KEYS`, and both editor allow-tuples.

- [ ] **Step 1: Read prior art.** Read `SlideBreakElementForm` and the `FORM_FOR_TYPE` dict in `courses/element_forms.py`; `NESTABLE_TYPE_KEYS` in `courses/builder.py`; the `element_add`/`element_save` allow-tuples and `_EDITOR_TYPE_LABELS` in `courses/views_manage.py`. Note the exact key spelling (`slidebreak` vs `revealgate`).

- [ ] **Step 2: Write the failing test.**

```python
# courses/tests/test_reveal_gate_form_builder.py
import pytest
from courses.element_forms import FORM_FOR_TYPE, RevealGateElementForm
from courses.builder import NESTABLE_TYPE_KEYS

def test_form_registered():
    assert FORM_FOR_TYPE["revealgate"] is RevealGateElementForm

def test_form_valid_with_label():
    f = RevealGateElementForm(data={"label": "Show the answer"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["label"] == "Show the answer"

def test_form_valid_blank_label():
    f = RevealGateElementForm(data={"label": ""})
    assert f.is_valid(), f.errors

def test_reveal_gate_is_nestable():
    assert "revealgate" in NESTABLE_TYPE_KEYS
```

- [ ] **Step 3: Run test to verify it fails.** Run: `uv run pytest courses/tests/test_reveal_gate_form_builder.py -v` — Expected: FAIL (ImportError / KeyError).

- [ ] **Step 4: Add the form + registry entries.** In `courses/element_forms.py`:

```python
class RevealGateElementForm(forms.ModelForm):
    class Meta:
        model = RevealGateElement
        fields = ["label"]
```

(import `RevealGateElement`). Add `"revealgate": RevealGateElementForm` to `FORM_FOR_TYPE`. In `courses/builder.py`, add `"revealgate"` to `NESTABLE_TYPE_KEYS`. In `courses/views_manage.py`, add `"revealgate"` to BOTH the `element_add` and `element_save` allow-tuples, and add `_EDITOR_TYPE_LABELS["revealgate"] = gettext_lazy("Show more")`.

- [ ] **Step 5: Run tests to verify they pass.** Run: `uv run pytest courses/tests/test_reveal_gate_form_builder.py -v` — Expected: PASS (4).

- [ ] **Step 6: Builder integration test (create + create-in-tab).**

```python
# append to courses/tests/test_reveal_gate_form_builder.py
import pytest
from courses import builder
from courses.models import RevealGateElement, Element
# Use existing test factories for a course/unit + a tabs element; mirror
# the pattern in courses/tests/test_tabs_*.py for nesting setup.

pytestmark = pytest.mark.django_db

def test_builder_creates_top_level_gate(lesson_unit):  # fixture: a LESSON unit
    from django.http import QueryDict
    post = QueryDict(mutable=True)
    post["label"] = "Next"
    post["unit_token"] = lesson_unit.updated.isoformat()  # REQUIRED: _check_token
    # REAL signature (read courses/builder.py in Step 1 to confirm):
    #   save_element(course, unit_pk, type_key, element_ref, post_data, files)
    builder.save_element(lesson_unit.course, lesson_unit.pk, "revealgate",
                         "new", post, {})
    row = Element.objects.get(unit=lesson_unit,
                              content_type__model="revealgateelement")
    assert row.parent_id is None
    assert row.content_object.label == "Next"
```

**Confirm against `courses/builder.py` (Step 1):** `save_element` is positional `save_element(course, unit_pk, type_key, element_ref, post_data, files)` — NOT `unit=`/`type_key=`/`data=` kwargs; `post_data` is a `QueryDict`-like (build with `QueryDict(mutable=True)` then assign), `files` may be `{}`/an empty `MultiValueDict`. **`save_element` starts with `_check_token(unit.updated, post_data.get("unit_token"))` and raises `ConflictError` on a missing/mismatched token — so EVERY `save_element` call (here and in Task 5) MUST include `post["unit_token"]` set to the unit's `updated` timestamp in the format `_check_token`/`parse_datetime` accepts (read `_check_token` to confirm; `lesson_unit.updated.isoformat()` should parse). Adapt `.course`/`.pk` access to the real `unit`→`course` relation, and don't rely on the return value's type — assert via the `Element` lookup + `row.content_object.label`. Reuse the `slidebreak`/`tabs` builder-test setup for a `lesson_unit`; add the fixture from the existing course/unit factories if absent.

- [ ] **Step 7: Run + commit.** Run the file; Expected: PASS. Then:

```bash
git add courses/element_forms.py courses/builder.py courses/views_manage.py courses/tests/test_reveal_gate_form_builder.py
git commit -m "feat(reveal-gate): form, builder nestability, editor add/save wiring"
```

---

### Task 3: Labels, summary, icon

**Files:**
- Modify: `courses/templatetags/courses_manage_extras.py` (`_ELEMENT_LABELS`, `element_summary`)
- Modify: `templates/courses/manage/_icon_sprite.html` (`#el-revealgate`)
- Test: `courses/tests/test_reveal_gate_labels.py`

**Interfaces:**
- Consumes: `RevealGateElement` (Task 1).
- Produces: row label "Show more"; `element_summary(revealgateelement)` → the label or a default; sprite symbol `#el-revealgate`.

- [ ] **Step 1: Read prior art.** Read `_ELEMENT_LABELS`, `element_type_label`, and `element_summary` (incl. the `slidebreak` `"—"` special-case) in `courses/templatetags/courses_manage_extras.py`; read an existing 16×16 `currentColor` symbol in `templates/courses/manage/_icon_sprite.html`.

- [ ] **Step 2: Write the failing test.**

```python
# courses/tests/test_reveal_gate_labels.py
import pytest
from courses.templatetags.courses_manage_extras import element_summary
from courses.models import RevealGateElement

pytestmark = pytest.mark.django_db

def test_summary_uses_label():
    el = RevealGateElement.objects.create(label="Reveal hint")
    assert "Reveal hint" in element_summary(el)

def test_summary_default_when_blank():
    el = RevealGateElement.objects.create(label="")
    assert element_summary(el)  # non-empty default, e.g. "Show more"
```

- [ ] **Step 3: Run to verify fail.** Run: `uv run pytest courses/tests/test_reveal_gate_labels.py -v` — Expected: FAIL.

- [ ] **Step 4: Implement.** Add `_ELEMENT_LABELS["revealgateelement"] = _("Show more")` (module `_` is `gettext_lazy`). In `element_summary` (which dispatches on `name = el.__class__.__name__` via `if name == "…":` branches), add — alongside the other `name == "…"` branches, **before** the `stem` fallthrough, mirroring the `SlideBreakElement` case — `if name == "RevealGateElement": return el.label or _("Show more")`. Add to `_icon_sprite.html` a 16×16 `currentColor` symbol `id="el-revealgate"` (e.g. a downward chevron over a horizontal rule — match existing stroke/viewBox conventions).

- [ ] **Step 5: Run to verify pass + commit.** Run the file; Expected: PASS.

```bash
git add courses/templatetags/courses_manage_extras.py templates/courses/manage/_icon_sprite.html courses/tests/test_reveal_gate_labels.py
git commit -m "feat(reveal-gate): row label, summary, sprite icon"
```

---

### Task 4: Palette "Interactive" group + quiz-flag threading

**Files:**
- Modify: `courses/views_manage.py` (add `unit_is_quiz` to the context dicts in `_render_editor_fragments` and the `_editor_page` view — includes inherit it)
- Modify: `templates/courses/manage/editor/_add_menu.html` (new gated group)
- Test: `courses/tests/test_reveal_gate_palette.py`

**Interfaces:**
- Consumes: the editor render path (`_render_editor_fragments` → `_editor_page`/`_editor_scope` → `_add_menu`).
- Produces: an `is_quiz`-style boolean in the add-menu context (name it `unit_is_quiz` to avoid colliding with the existing form-host `is_quiz`); the Interactive group renders iff not quiz.

- [ ] **Step 1: Read prior art.** Read `_add_menu.html` (its group headers `{% trans "Content" %}` / `"Questions"` / `"Structure"`, the `not nested` guard on `slidebreak`), and trace the editor render path in `courses/views_manage.py` (`_render_editor_fragments`, `_editor_page`, `_editor_scope.html`) to see exactly what context each stage passes. Confirm the `element_add` `is_quiz` at `views_manage.py:835` is NOT in this path (it is not — it goes to `_host_form.html`).

- [ ] **Step 2: Write the failing test.**

```python
# courses/tests/test_reveal_gate_palette.py
import pytest
pytestmark = pytest.mark.django_db

def _editor_html(client, unit):
    # GET the editor page for `unit`; mirror the URL used by existing
    # editor tests (courses/tests/test_editor_*.py).
    resp = client.get(unit_editor_url(unit))
    return resp.content.decode()

def test_interactive_group_in_lesson(client_pa, lesson_unit):
    html = _editor_html(client_pa, lesson_unit)
    assert 'data-add-type="revealgate"' in html
    assert "Interactive" in html  # group heading present

def test_interactive_group_absent_in_quiz(client_pa, quiz_unit):
    html = _editor_html(client_pa, quiz_unit)
    assert 'data-add-type="revealgate"' not in html
    assert "Interactive" not in html  # whole group hidden, no stray heading

def test_gate_card_in_nested_add_menu(client_pa, lesson_unit_with_tabs):
    # the in-tab add-menu (rendered with nested=True) must also offer the gate,
    # since revealgate is nestable — guards against placing the group inside
    # the {% if not nested %} block.
    html = _editor_html(client_pa, lesson_unit_with_tabs)
    assert html.count('data-add-type="revealgate"') >= 2  # top-level + nested
```

(Adapt `unit_editor_url`, `client_pa`, `lesson_unit`, `quiz_unit`, `lesson_unit_with_tabs` to existing fixtures/helpers; the tabs fixture mirrors the tabs editor tests.)

- [ ] **Step 3: Run to verify fail.** Run: `uv run pytest courses/tests/test_reveal_gate_palette.py -v` — Expected: FAIL.

- [ ] **Step 4: Thread the flag.** In `courses/views_manage.py`, compute `unit_is_quiz = unit.unit_type == ContentNode.UnitType.QUIZ` and add it to the context dicts built by BOTH `_render_editor_fragments` and the `_editor_page` view (which renders `editor.html`). Because `_add_menu.html` is `{% include %}`d **without `only`**, it inherits this context — no separate template plumbing (and no nested-include edit) is needed. First confirm those includes have no `only`; if any does, pass `unit_is_quiz` explicitly there.

- [ ] **Step 5: Add the gated group.** In `_add_menu.html`, place the group **OUTSIDE** the existing `{% if not nested %}` block (which wraps the Questions/Structure groups, ~lines 25–42): `revealgate` is nestable (Task 2), and the only UI path to create an in-tab gate is the nested add-menu (`_element_row.html` includes `_add_menu.html with nested=True`), so the group must render in BOTH menus — alongside the nestable Content cards, not inside the not-nested block. Wrap it in `{% if not unit_is_quiz %} … {% endif %}` covering BOTH the heading and the card:

```django
{% if not unit_is_quiz %}
<div class="typemenu__group">
  <p class="typemenu__group-label">{% trans "Interactive" %}</p>
  <button type="button" class="typecard" data-add-type="revealgate">
    <svg class="ic" aria-hidden="true" focusable="false"><use href="#el-revealgate"></use></svg>
    <span>{% trans "Show more" %}</span>
  </button>
</div>
{% endif %}
```

(These are the REAL `_add_menu.html` classes — `typemenu__group` / `typemenu__group-label` / `typecard` / `svg.ic`. Copy the exact inner markup of a neighboring group's card verbatim before adjusting.)

- [ ] **Step 6: Run to verify pass + commit.** Run the file; Expected: PASS.

```bash
git add courses/views_manage.py templates/courses/manage/editor/_add_menu.html courses/tests/test_reveal_gate_palette.py
git commit -m "feat(reveal-gate): Interactive palette group gated to lesson units"
```

---

### Task 5: Bespoke editor row (caption + standard edit control + quiz-inactive flag)

**Files:**
- Modify: `templates/courses/manage/editor/_element_row.html`
- Test: `courses/tests/test_reveal_gate_editor_row.py`

**Interfaces:**
- Consumes: `_element_row.html` receives `el` and `unit`.
- Produces: a divider-styled row for `revealgateelement` that keeps the standard edit control and shows the label caption; a quiz-inactive flag when `unit.unit_type == QUIZ`.

- [ ] **Step 1: Read prior art.** Read the `slidebreakelement` branch in `_element_row.html` (its `element-row--slidebreak` markup and that it drops the edit control) and the generic editable-row branch (the one with the ✎ edit button + `_element_row_controls.html`). The gate needs the divider look BUT must keep the standard edit control.

- [ ] **Step 2: Write the failing test.**

```python
# courses/tests/test_reveal_gate_editor_row.py
import pytest
from django.template.loader import render_to_string
from courses.models import RevealGateElement, Element, ContentNode
pytestmark = pytest.mark.django_db

def _render_row(el_join, unit):
    # The real _element_row.html reads `obj` (the content_object) for the
    # label via `{{ obj|element_summary }}`; the caller passes it explicitly.
    return render_to_string("courses/manage/editor/_element_row.html",
                            {"el": el_join, "obj": el_join.content_object,
                             "unit": unit})

def test_row_shows_label_and_edit_control(lesson_unit):
    # build a gate join row in lesson_unit (reuse builder.save_element)
    ...
    html = _render_row(join, lesson_unit)
    assert "Show more" in html
    assert "data-add-type" not in html  # it's a row, not a palette card
    # standard edit affordance present (match the real edit-button marker)
    assert "el-row" in html

def test_row_quiz_inactive_flag(quiz_unit):
    ...
    html = _render_row(join, quiz_unit)
    assert "inactive in quizzes" in html.lower()
```

(Fill the `...` using the builder to create a gate join; adapt the edit-control assertion to the real marker you read in Step 1.)

- [ ] **Step 3: Run to verify fail.** Run: `uv run pytest courses/tests/test_reveal_gate_editor_row.py -v` — Expected: FAIL.

- [ ] **Step 4: Implement the row branch.** Add a `{% elif el.content_type.model == "revealgateelement" %}` branch in `_element_row.html`: divider-styled `<li class="el-row element-row--revealgate">` showing the label via the row's existing `obj` idiom — `{{ obj.label|default:_("Show more") }}` (NOT `el.label`; `obj` is the content_object the caller passes) — plus a short caption ("hides the following blocks until the student clicks"), the standard reorder grip + `_element_row_controls.html` + the standard edit button (open `element_save` form for `revealgate`; do NOT copy slidebreak's edit-suppression). Wrap a `{% if unit.unit_type == 'quiz' %}<span class="el-row__flag">{% trans "inactive in quizzes" %}</span>{% endif %}`. Confirm the `'quiz'` string matches `ContentNode.UnitType.QUIZ`'s value; if the enum isn't comparable from the template, pass a boolean in context.

- [ ] **Step 5: Run to verify pass + commit.** Run the file; Expected: PASS.

```bash
git add templates/courses/manage/editor/_element_row.html courses/tests/test_reveal_gate_editor_row.py
git commit -m "feat(reveal-gate): bespoke editor row with caption, edit control, quiz flag"
```

---

### Task 6: Student renderer + CSS

**Files:**
- Create: `templates/courses/elements/revealgateelement.html`
- Modify: `core/static/core/css/app.css` (button `[hidden]` guard + wrapper `[hidden]` guard + `.reveal-shown` + `@media print`)
- Test: `courses/tests/test_reveal_gate_render.py`

**Interfaces:**
- Consumes: `RevealGateElement.render()` (default `ElementBase.render()` finds the template by model_name).
- Produces: `<button class="reveal-gate" data-reveal-gate hidden>`; CSS rules named in the spec.

- [ ] **Step 1: Write the failing test.**

```python
# courses/tests/test_reveal_gate_render.py
import pytest
from courses.models import RevealGateElement
pytestmark = pytest.mark.django_db

def test_render_button_hidden_with_marker():
    html = RevealGateElement.objects.create(label="").render()
    assert 'data-reveal-gate' in html
    assert 'hidden' in html
    assert 'Show more' in html  # default label

def test_render_custom_label():
    html = RevealGateElement.objects.create(label="Reveal it").render()
    assert 'Reveal it' in html
```

- [ ] **Step 2: Run to verify fail.** Run: `uv run pytest courses/tests/test_reveal_gate_render.py -v` — Expected: FAIL (TemplateDoesNotExist).

- [ ] **Step 3: Create the template.** `templates/courses/elements/revealgateelement.html`:

```django
{% load i18n %}
<button type="button" class="reveal-gate" data-reveal-gate hidden>
  {% if el.label %}{{ el.label }}{% else %}{% trans "Show more" %}{% endif %}
</button>
```

- [ ] **Step 4: Add CSS to `app.css`.**

```css
/* Reveal gate — button hide guards (author display must never beat [hidden]) */
.reveal-gate[hidden] { display: none !important; }
.lesson-block[hidden], .tabs__child[hidden] { display: none !important; }

/* Pre-hide is emitted render-blocking in the lesson <head> (see lesson_unit.html);
   these rules support the reveal + print sides. */
@media print {
  .reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block,
  .reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child {
    display: revert !important;
  }
  [data-reveal-gate] { display: none !important; }
}
```

- [ ] **Step 5: Run to verify pass + commit.** Run the file; Expected: PASS.

```bash
git add templates/courses/elements/revealgateelement.html core/static/core/css/app.css courses/tests/test_reveal_gate_render.py
git commit -m "feat(reveal-gate): student renderer + hide-guard/print CSS"
```

---

### Task 7: `has_reveal_gate` flag in the consumption view + lesson-template triad wiring

**Files:**
- Modify: `courses/views.py` (compute `has_reveal_gate`, add to lesson context)
- Modify: `templates/courses/lesson_unit.html` (`{% block prepaint %}` setter+watchdog; `{% block extra_css %}` pre-hide `<style>`; `extra_js` reveal.js — all gated on `has_reveal_gate`)
- Test: `courses/tests/test_reveal_gate_view_flag.py`

**Interfaces:**
- Consumes: the lesson consumption view (already computes `has_math`/`has_questions`/`has_html`).
- Produces: context `has_reveal_gate: bool`; the co-gating triad emitted iff true.

- [ ] **Step 1: Read prior art.** Read the **LESSON** context builder in `courses/views.py` (around `views.py:197–235`, the one feeding `lesson_unit.html` that sets `has_math`/`has_questions`/`has_html`) — NOT the quiz builder (~`:541`, which sets `has_questions: True`) nor the other (~`:758`). Also read `lesson_unit.html`'s `{% block extra_js %}`/`extra_css` and how tabs.js is included. Confirm `base.html:43 {% block prepaint %}` (empty) precedes the app.css `<link>` at `base.html:46`, and `{% block extra_css %}` at `base.html:48` follows app.css.

- [ ] **Step 2: Write the failing test.**

```python
# courses/tests/test_reveal_gate_view_flag.py
import pytest
pytestmark = pytest.mark.django_db

def test_flag_true_top_level_gate(client_student, lesson_with_gate):
    html = client_student.get(lesson_url(lesson_with_gate)).content.decode()
    assert 'reveal-armed' in html          # setter present
    assert 'reveal.js' in html             # engine included

def test_flag_true_tab_nested_gate(client_student, lesson_with_tab_gate):
    # a lesson whose ONLY gate is inside a tab
    html = client_student.get(lesson_url(lesson_with_tab_gate)).content.decode()
    assert 'reveal-armed' in html

def test_flag_false_no_gate(client_student, plain_lesson):
    html = client_student.get(lesson_url(plain_lesson)).content.decode()
    assert 'reveal-armed' not in html
    assert 'reveal.js' not in html
```

- [ ] **Step 3: Run to verify fail.** Run: `uv run pytest courses/tests/test_reveal_gate_view_flag.py -v` — Expected: FAIL.

- [ ] **Step 4: Compute the flag (flat query).** In `courses/views.py` lesson context:

```python
from courses.models import Element
has_reveal_gate = Element.objects.filter(
    unit=unit, content_type__model="revealgateelement"
).exists()
```

Add `has_reveal_gate` to the render context. (Flat query over `Element` catches tab-nested gates because children keep their own `unit` FK.)

- [ ] **Step 5: Wire the lesson template triad.** In `lesson_unit.html`:

```django
{% block prepaint %}
{% if has_reveal_gate %}
<script>
  (function () {
    "use strict";
    document.documentElement.classList.add("reveal-armed");
    document.addEventListener("DOMContentLoaded", function () {
      if (!window.__revealBooted) {
        document.documentElement.classList.remove("reveal-armed");
      }
    });
  })();
</script>
{% endif %}
{% endblock %}

{# Append INSIDE lesson_unit.html's EXISTING {% block extra_css %} (which already
   links courses.css/notes.css/tags.css/katex), AFTER those links. Do NOT add
   {{ block.super }} — base.html's extra_css block is empty, and re-declaring the
   block without the existing links would DELETE them. #}
{% if has_reveal_gate %}
<style>
  .reveal-armed .slide > .lesson-block:has(> .lesson-block__body > [data-reveal-gate]) ~ .lesson-block:not(.reveal-shown),
  .reveal-armed [data-tab-panel] > .tabs__child:has(> [data-reveal-gate]) ~ .tabs__child:not(.reveal-shown) {
    display: none;
  }
</style>
{% endif %}
```

And in the deferred `extra_js` block, add (gated on `has_reveal_gate`) `<script src="{% static 'courses/js/reveal.js' %}" defer></script>`. **Note:** the `prepaint` override needs no `{{ block.super }}` (base block is empty, nothing to preserve). The `extra_css` addition must NOT use `{{ block.super }}` either — lesson_unit already fully overrides `extra_css` with real `<link>`s and base's block is empty, so just add the `<style>` at the end of that existing override block.

- [ ] **Step 6: Run to verify pass + commit.** Run the file; Expected: PASS.

```bash
git add courses/views.py templates/courses/lesson_unit.html courses/tests/test_reveal_gate_view_flag.py
git commit -m "feat(reveal-gate): has_reveal_gate flag + co-gated lesson triad"
```

---

### Task 8: `reveal.js` engine

**Files:**
- Create: `courses/static/courses/js/reveal.js`
- Test: covered by e2e in Task 10 (JS has no unit harness here).

**Interfaces:**
- Produces: `window.libliInitRevealGates(root)`; sets `window.__revealBooted = true`.

- [ ] **Step 1: Read prior art.** Read `courses/static/courses/js/tabs.js` (IIFE, `dataset` guard, `window.libliInitTabs`, self-init on `document`, the `libli:reveal` CustomEvent dispatch) and `gallery.js`'s consumption of `libli:reveal`.

- [ ] **Step 2: Write `reveal.js`.**

```javascript
(function () {
  "use strict";
  window.__revealBooted = true;

  function scopeOf(btn) {
    return btn.closest("[data-tab-panel], .slide");
  }
  function ownWrapper(el, scope) {
    // the child of `scope` that contains el
    var node = el;
    while (node && node.parentElement !== scope) node = node.parentElement;
    return node;
  }
  function isGateWrapper(wrapper, scope) {
    if (!wrapper) return false;
    var sel = scope.matches("[data-tab-panel]")
      ? ":scope > [data-reveal-gate]"
      : ":scope > .lesson-block__body > [data-reveal-gate]";
    return !!wrapper.querySelector(sel);
  }
  function reveal(btn) {
    var scope = scopeOf(btn);
    if (!scope) return;
    var gateWrap = ownWrapper(btn, scope);
    var node = gateWrap.nextElementSibling;
    var lastRevealed = null;
    while (node) {
      node.classList.add("reveal-shown");
      node.dispatchEvent(new CustomEvent("libli:reveal", { bubbles: true }));
      lastRevealed = node;
      if (isGateWrapper(node, scope)) break; // include next gate, then stop
      node = node.nextElementSibling;
    }
    // consume the clicked gate
    gateWrap.classList.remove("reveal-shown");
    gateWrap.hidden = true;
    // focus management
    var nextBtn = lastRevealed && isGateWrapper(lastRevealed, scope)
      ? lastRevealed.querySelector("[data-reveal-gate]") : null;
    var target = nextBtn
      || (gateWrap.nextElementSibling
          && gateWrap.nextElementSibling.classList.contains("reveal-shown")
          ? firstRevealed(gateWrap, scope) : null);
    if (!target) {
      scope.setAttribute("tabindex", "-1");
      target = scope;
    }
    if (target && target.focus) target.focus();
  }
  function firstRevealed(gateWrap, scope) {
    var n = gateWrap.nextElementSibling;
    while (n && !n.classList.contains("reveal-shown")) n = n.nextElementSibling;
    if (n && !n.hasAttribute("tabindex")) n.setAttribute("tabindex", "-1");
    return n;
  }
  function initOne(btn) {
    if (btn.dataset.revealReady === "1") return;
    btn.dataset.revealReady = "1";
    btn.hidden = false; // un-hide every gate button; wrapper visibility gates it
    btn.addEventListener("click", function () { reveal(btn); });
  }
  function initRevealGates(root) {
    var scope = root || document;
    if (scope.matches && scope.matches("[data-reveal-gate]")) initOne(scope);
    Array.prototype.forEach.call(
      scope.querySelectorAll("[data-reveal-gate]"), initOne);
  }
  window.libliInitRevealGates = initRevealGates;
  initRevealGates(document);
})();
```

- [ ] **Step 3: Lint.** Run: `uv run ruff format --check` is Python-only; for JS just confirm no syntax errors by loading it in Task 10's e2e. Commit now (behavior verified in Task 10):

```bash
git add courses/static/courses/js/reveal.js
git commit -m "feat(reveal-gate): reveal.js cascade engine with watchdog boot flag"
```

> The focus-target logic above is a first cut — refine it against the real DOM during Task 10 e2e (the failing focus assertion will drive corrections). Keep the boot flag + un-hide + cascade + consume behavior.

---

### Task 9: Transfer (export / validate / import)

**Files:**
- Modify: `courses/transfer/export.py` (`_ser_reveal_gate` + `SERIALIZERS["reveal_gate"]`)
- Modify: `courses/transfer/payloads.py` (`_val_reveal_gate` + `VALIDATORS["reveal_gate"]`)
- Modify: `courses/transfer/importer.py` (`_build_reveal_gate` + `BUILDERS["reveal_gate"]`)
- Test: `courses/tests/test_reveal_gate_transfer.py`

**Interfaces:**
- Consumes: `RevealGateElement`.
- Produces: transfer key `reveal_gate` serializing `{"label": str}`; export auto-dispatches via `_MODEL_TO_KEY`.

- [ ] **Step 1: Read prior art.** Read the `slide_break` trio (`_ser_slide_break`/`_val_slide_break`/`_build_slide_break`) and the registry lines in the three transfer modules, plus `_MODEL_TO_KEY` at `export.py:233`.

- [ ] **Step 2: Write the failing round-trip test.**

```python
# courses/tests/test_reveal_gate_transfer.py
import pytest
pytestmark = pytest.mark.django_db

def test_reveal_gate_roundtrip(course_with_gate):
    # export the course, import into a fresh course, assert the gate + label survive.
    # Mirror courses/tests/test_transfer_*.py / test_tabs_transfer.py exactly.
    ...

def test_reveal_gate_in_tab_roundtrip(course_with_tab_gate):
    ...
```

(Fill `...` using the existing transfer round-trip helpers.)

- [ ] **Step 3: Run to verify fail.** Run: `uv run pytest courses/tests/test_reveal_gate_transfer.py -v` — Expected: FAIL.

- [ ] **Step 4: Implement the trio.**

Add each registration as an **entry inside the existing dict literal** (matching `slide_break`), NOT as a trailing `REGISTRY[...] = ...` assignment. For `SERIALIZERS` this is load-bearing: `_MODEL_TO_KEY = {model: key for key, (model, _fn) in SERIALIZERS.items()}` runs at `export.py:233`, so a post-233 assignment would be missed and export dispatch would silently drop the gate. Also add `from courses.models import RevealGateElement` to `export.py` and `importer.py` (payloads.py needs no model import).

```python
# export.py — import RevealGateElement; define the fn, then add the entry
# INSIDE the `SERIALIZERS = { ... }` literal (before the _MODEL_TO_KEY line):
def _ser_reveal_gate(concrete, media_ids):
    return {"label": concrete.label}
#   "reveal_gate": (RevealGateElement, _ser_reveal_gate),

# payloads.py — add the entry inside the `VALIDATORS = { ... }` literal:
def _val_reveal_gate(data, elid, media_kinds):
    return set()
#   "reveal_gate": _val_reveal_gate,

# importer.py — import RevealGateElement; add inside the `BUILDERS = { ... }` literal:
def _build_reveal_gate(data, assets):
    return RevealGateElement.objects.create(label=data.get("label", "")), ()
#   "reveal_gate": _build_reveal_gate,
```

(Match the exact signatures/return shapes of the `slide_break` functions you read in Step 1.)

- [ ] **Step 5: Run to verify pass + commit.** Run the file + the existing transfer schema tests (`uv run pytest courses/tests/test_transfer_schema.py -v`) to confirm no `FORMAT_VERSION` regression.

```bash
git add courses/transfer/export.py courses/transfer/payloads.py courses/transfer/importer.py courses/tests/test_reveal_gate_transfer.py
git commit -m "feat(reveal-gate): transfer export/validate/import (no format bump)"
```

---

### Task 10: e2e (Playwright) — cascade, nested-in-tab, quiz-inert, watchdog, focus, single-slide

**Files:**
- Create: `courses/tests/e2e/test_reveal_gate_e2e.py`

**Interfaces:**
- Consumes: everything above, on a running server.

- [ ] **Step 1: Read prior art.** Read an existing Playwright e2e (e.g. `courses/tests/e2e/test_tabs_e2e.py` or the gallery e2e) for the fixture/server harness and the login/seed helpers.

- [ ] **Step 2: Write the e2e (drive the REAL click).** Cover, each as its own test:
  - **Cascade:** lesson with `[intro][gateA][B][C][gateB][D]`. Initially only gateA's button visible; B/C/gateB/D not visible. Click gateA → B, C visible, gateB button visible, gateA gone, D still hidden. Click gateB → D visible.
  - **Nested-in-tab:** a gate inside a tab gates only that tab's following `.tabs__child`; a *sibling slide-level* block after the tabs element is NOT hidden by the nested gate.
  - **Quiz-inert:** the same content in a quiz unit (built as a lesson then converted, `views_manage.py:302`) shows everything, no gate button, no `reveal-armed`.
  - **Watchdog:** route-intercept/abort `reveal.js`; after load, assert all content is visible (watchdog removed `reveal-armed`).
  - **Focus:** after clicking gateA, `document.activeElement` is gateB's button; for a trailing gate with an empty run, focus is the scope container, not `<body>`.
  - **Single-slide:** a single-slide lesson gate actually collapses its run.

```python
# skeleton — adapt harness to the existing e2e base
def test_reveal_cascade(live_server, page, lesson_with_two_gates):
    page.goto(lesson_url(lesson_with_two_gates))
    gate_a = page.locator("[data-reveal-gate]").first
    expect(gate_a).to_be_visible()
    expect(page.get_by_text("block C")).to_be_hidden()
    gate_a.click()
    expect(page.get_by_text("block C")).to_be_visible()
    # second gate now visible …
```

- [ ] **Step 3: Run focused e2e in the FOREGROUND.** Run: `uv run pytest courses/tests/e2e/test_reveal_gate_e2e.py -v` (foreground, not `-n`/background). Fix `reveal.js` focus/boundary logic until green. Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add courses/tests/e2e/test_reveal_gate_e2e.py courses/static/courses/js/reveal.js
git commit -m "test(reveal-gate): e2e cascade, nesting, quiz-inert, watchdog, focus"
```

---

### Task 11: i18n (EN/PL) + no-JS/print/completion assertions

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po`
- Test: `courses/tests/test_reveal_gate_render.py` (extend), existing i18n catalog tests.

- [ ] **Step 1: Extract messages.** Run: `uv run python manage.py makemessages -l en -l pl` (watch the fuzzy-flag gotcha — review the diff, remove stray `#, fuzzy` on the new entries).

- [ ] **Step 2: Translate PL.** Fill PL for: "Show more" → "Pokaż więcej"; "Interactive" → "Interaktywne"; the row caption; "inactive in quizzes". Leave EN as msgid.

- [ ] **Step 3: Add no-JS + completion assertions.**

```python
# extend test_reveal_gate_render.py
def test_no_reveal_armed_no_hidden_blocks(...):
    # render a lesson WITHOUT reveal-armed on <html>: assert no block is display:none
    # (renderer/DOM-level: the pre-hide is class-gated, so absent the class nothing hides)
    ...
```

Add a completion-interaction test per the spec (gated content not "seen" by `progress.js` until revealed) if a `progress.js`/seen unit-test harness exists; otherwise cover it in the e2e.

- [ ] **Step 4: Compile + run catalog tests.** Run: `uv run python manage.py compilemessages` and `uv run pytest courses/tests/ -k "i18n or catalog or messages" -v`. Expected: PASS (no obsolete `#~`, no fuzzy on new strings).

- [ ] **Step 5: Commit.**

```bash
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po courses/tests/test_reveal_gate_render.py
git commit -m "i18n(reveal-gate): EN/PL catalogs + no-JS render guard"
```

---

## Definition of Done (controller-owned)

- [ ] `uv run pytest` full suite green (incl. i18n catalog tests — this slice adds translatable strings).
- [ ] `uv run ruff check` AND `uv run ruff format --check` clean.
- [ ] `uv run python manage.py makemigrations --check --dry-run` reports no missing migrations.
- [ ] Focused reveal-gate e2e green in the foreground.
- [ ] Manual smoke (or e2e-covered): no-JS shows all content with no dead buttons; print reveals all + hides buttons; a converted lesson→quiz gate is inert.

## Self-review notes

- Spec coverage: model/migration (T1), form+builder+editor-views+nestable (T2), labels/icon (T3), palette+quiz-threading (T4), editor row (T5), renderer+CSS (T6), consumption-view flag+triad wiring incl. watchdog & prepaint/extra_css placement (T7), reveal.js cascade/focus/boundary (T8), transfer no-bump (T9), e2e incl. nested/quiz/watchdog/single-slide/focus (T10), i18n + no-JS guard (T11). Auto-completion interaction is covered in T10/T11 per available harness.
- Every task ends TDD-style with a run + commit. Type/name consistency: `revealgateelement` (model), `revealgate` (form/editor key), `reveal_gate` (transfer key), `reveal-armed`/`reveal-shown`/`data-reveal-gate`/`__revealBooted` used consistently across T4–T10.
