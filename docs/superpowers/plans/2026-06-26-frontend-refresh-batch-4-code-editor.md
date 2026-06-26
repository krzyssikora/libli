# Frontend Refresh Batch 4 — Code-Editor Author Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the four code-bearing author textareas (element `HtmlElement.html`, course-wide `Course.html_css` / `Course.html_js`, unit `ContentNode.html_seed_js`) into the batch-1 `code-field` shell with a **live line-number gutter** and **Tab-to-indent**, as plain monospace progressive enhancement — no editor library, no syntax highlighting.

**Architecture:** Batch 1 already shipped the inert pieces — the `CodeTextarea` widget (`courses/widgets.py`, renders `.code-field[data-code-field] > .code-field__gutter + .code-field__area > textarea`), the `code-field` CSS (`courses/static/courses/css/courses.css`), and the `--font-mono` token. Batch 4 (1) swaps the three Django-form fields onto `CodeTextarea`, (2) hand-wraps the raw `html_seed_js` textarea in the same shell, (3) adds one focused JS module `code_field.js` that — via **delegated events + a MutationObserver** so it also enhances the editor's AJAX-injected element forms — renders the gutter (1:1 with logical lines, no soft-wrap), syncs the gutter's vertical scroll to the textarea, and makes Tab insert two spaces (Shift-Tab outdents). No model change, no migration.

**Tech Stack:** Django (server-rendered, ModelForm widgets), vanilla JS (IIFE, progressive enhancement, no framework), bespoke token-driven CSS, pytest + Playwright (`-m e2e`).

## Global Constraints

- **TDD always** — write the failing test, watch it fail for the right reason, minimal code, watch it pass, commit. (per project norms)
- **Tooling:** bash `ruff`/`pytest`/`python` are **NOT on PATH** — use `uv run ruff …`, `uv run pytest …`, `uv run python manage.py …`.
- **Lint:** every task ends green on `uv run ruff check .` AND `uv run ruff format --check .` (CI checks format too).
- **Reuse the batch-1 primitives, do not fork them:** the `CodeTextarea` widget (`courses/widgets.py`), the `code-field` CSS block (`courses/static/courses/css/courses.css:296-317`), and the `--font-mono` token (`core/static/core/css/tokens.css:54`) already exist. Do not duplicate the wrapper structure or rename the classes (`code-field`, `code-field__gutter`, `code-field__area`, the `data-code-field` hook).
- **No editor library, no syntax highlighting** — one text colour, plain monospace (spec §5).
- **No soft-wrap → 1:1 gutter mapping:** the textarea stays `white-space: pre; overflow-x: auto` (batch-1 CSS already sets this) so gutter line N maps to logical line N; an **empty field shows line "1"** (spec §5). The e2e gutter check targets this 1:1 mapping.
- **No-JS fallback:** with JS off, every field is still a styled monospace textarea inside the inert shell; the gutter stays empty and Tab is the browser default. Sandbox behaviour and help text are unchanged (spec §5).
- **No model/schema change** in this batch — no migration (spec: batches 2–4 add no schema).
- **e2e drives real gestures** (`e2e-must-drive-real-ui`): real `fill`, real `page.keyboard.press("Tab")`, no `page.evaluate` shortcut. Local `uv run pytest -q` EXCLUDES e2e; run `uv run pytest -m e2e` for the e2e task and before finishing.
- **i18n:** any NEW visible string is wrapped in `{% trans %}` / `gettext` and gets a **Polish** translation in `locale/pl/LC_MESSAGES/django.po` (recompile `.mo`). This batch is expected to add **no** new visible server strings (gutter numbers are not text content; no header strip is added — see the decision below). The `test_po_catalog_clean` test must stay green.

**Reference docs:** spec `docs/superpowers/specs/2026-06-25-frontend-design-refresh-and-navigation-design.md` §2 (the `code-field` primitive is batch 1), §5 (feature), §8 (tests/DoD); accepted mockup `docs/mockups/code-editor-field.html`.

**PLAN DECISION — no in-widget header strip (flag for plan-review / user):** the mockup shows a decorative header strip ("html / css / js · sandbox") above the code, but the **accepted batch-1 primitive deliberately ships without one** (`CodeTextarea` renders no header; the CSS defines no `.code-field__top`). Each of the four fields already has its own external, field-specific, i18n'd `<label>` above the widget ("HTML / CSS / JS", "Html css", "Html js", "Unit JS (seed)"). Adding an in-widget strip would duplicate those labels and introduce a new translatable string. **This plan treats the existing external label as the spec's "header strip label" and adds no in-widget header.** If the user wants the decorative strip, it is a small follow-up (CSS `.code-field__top` + a `{% trans %}` tag + widget change).

**Existing symbols this plan builds on (verbatim, do not rename):**
- `courses/widgets.py`: `CodeTextarea(forms.Textarea)` — sets `spellcheck="false"`, `autocomplete="off"`, `wrap="off"`; `render()` wraps the textarea in `<div class="code-field" data-code-field><div class="code-field__gutter" aria-hidden="true"></div><div class="code-field__area">{textarea}</div></div>`.
- `courses/static/courses/css/courses.css:296-317`: `.code-field`, `.code-field__gutter`, `.code-field__area`, `.code-field__area textarea` (textarea is `white-space: pre; overflow-x: auto; tab-size: 2`).
- `core/static/core/css/tokens.css:54`: `--font-mono`.
- Forms/templates: `courses/element_forms.py` `HtmlElementForm` (field `html`); `courses/forms.py` `CourseForm` (fields `html_css`, `html_js`); `templates/courses/manage/editor/_edit_html.html` (`{{ form.html }}`); `templates/courses/manage/course_form.html` (visible-fields loop + `{% block extra_js %}`); `templates/courses/manage/editor/_unit_settings.html` (raw `<textarea name="html_seed_js">`); `templates/courses/manage/editor/editor.html` (`{% block extra_js %}`, 11 deferred scripts).
- Test helpers — non-e2e: `make_pa(client)` (creates+logs in a platform-admin author) and the `tests/factories.py` factories (`CourseFactory`, `ContentNodeFactory`). e2e (`tests/test_e2e_editor.py`): `_make_pa_user(username)`, `_login(page, live_server, username)`, `_seed_course_and_unit(username, …) -> unit`, `_editor_url(live_server, unit)`, `_add_element(page, add_type)` (clicks `[data-add-toggle]` → `[data-add-type='<type>']`, waits for `[data-edit-slot] form[data-op='element-save']`); `tests/test_e2e_course_form.py` uses the same `_make_pa_user`/`_login`.

---

## File Structure

**Modified:**
- `courses/element_forms.py` — `HtmlElementForm.Meta.widgets["html"]` → `CodeTextarea(attrs={"rows": 12})`; import `CodeTextarea`.
- `courses/forms.py` — `CourseForm.Meta.widgets["html_css"]` / `["html_js"]` → `CodeTextarea(attrs={"rows": 10})`; import `CodeTextarea`.
- `templates/courses/manage/editor/_unit_settings.html` — wrap the raw `html_seed_js` textarea in the `.code-field` shell + `data-code-field`.
- `courses/static/courses/css/courses.css` — add `overflow: hidden;` to `.code-field__gutter` (so the JS can sync its vertical scroll via `scrollTop`).
- `templates/courses/manage/course_form.html` — load `code_field.js` in `extra_js`.
- `templates/courses/manage/editor/editor.html` — load `code_field.js` (deferred) in `extra_js`.

**New:**
- `courses/static/courses/js/code_field.js` — gutter render + scroll sync + Tab/Shift-Tab, delegated + MutationObserver.

**New / extended tests:**
- `tests/test_code_field_widget.py` (extend) — the three form fields use `CodeTextarea` and render the shell.
- `tests/test_code_field_seed.py` (**new**) — the unit-settings template renders the seed textarea inside `data-code-field`.
- `tests/test_e2e_editor.py` (extend) — editor html field: gutter line count + Tab inserts two spaces (real gestures).
- `tests/test_e2e_course_form.py` (extend) — course-form `html_css`: gutter line count (server-rendered, non-fragment path).

---

## Task 1: Wire `CodeTextarea` into the three Django form fields

**Files:**
- Modify: `courses/element_forms.py`, `courses/forms.py`
- Test: `tests/test_code_field_widget.py`

**Interfaces:**
- Consumes: `courses.widgets.CodeTextarea`.
- Produces: `HtmlElementForm().fields["html"].widget` is a `CodeTextarea`; `CourseForm().fields["html_css"].widget` and `["html_js"].widget` are `CodeTextarea`. Each renders the `.code-field` / `data-code-field` / `code-field__gutter` shell. `rows` preserved (12 for `html`, 10 for the course fields).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_code_field_widget.py` (it already imports `CodeTextarea` for the existing widget test — reuse that import; the existing test asserts the widget renders the wrapper):

```python
def test_html_element_form_uses_code_field_widget():
    from courses.element_forms import HtmlElementForm

    form = HtmlElementForm()
    assert isinstance(form.fields["html"].widget, CodeTextarea)
    rendered = str(form["html"])
    assert "data-code-field" in rendered
    assert "code-field__gutter" in rendered
    assert 'rows="12"' in rendered


def test_course_form_code_fields_use_code_field_widget():
    from courses.forms import CourseForm

    form = CourseForm()
    for name in ("html_css", "html_js"):
        assert isinstance(form.fields[name].widget, CodeTextarea), name
        rendered = str(form[name])
        assert "data-code-field" in rendered, name
        assert "code-field__gutter" in rendered, name
        assert 'rows="10"' in rendered, name
```

> If `CodeTextarea` is not already imported at the top of `tests/test_code_field_widget.py`, add `from courses.widgets import CodeTextarea` to the import block (ruff/isort ordering).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_code_field_widget.py -q`
Expected: the two new tests FAIL — `assert isinstance(... forms.Textarea, CodeTextarea)` is False (the fields still use a plain `Textarea`).

- [ ] **Step 3: Implement**

In `courses/element_forms.py`, add the import (with the other `courses` imports, ruff/isort order) and swap the widget:

```python
from .widgets import CodeTextarea
```

```python
class HtmlElementForm(forms.ModelForm):
    class Meta:
        model = HtmlElement
        fields = ["html"]
        widgets = {"html": CodeTextarea(attrs={"rows": 12})}

    # No clean_html: the raw markup is stored verbatim (sandbox is the boundary).
```

In `courses/forms.py`, add `from .widgets import CodeTextarea` (ruff/isort order) and change the two widgets in `CourseForm.Meta.widgets`:

```python
            "html_css": CodeTextarea(attrs={"rows": 10}),
            "html_js": CodeTextarea(attrs={"rows": 10}),
```

Leave the `labels` and `help_texts` for `html_css`/`html_js` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_code_field_widget.py -q`
Expected: PASS (existing widget test + the two new ones). Then run the form/view suites that touch these forms to confirm no regression:
`uv run pytest tests/test_html_element.py -q` and any `test_course*`/`test_builder*` that exercise `CourseForm` — expected PASS (the widget change is presentational; field names/validation unchanged).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check courses/element_forms.py courses/forms.py tests/test_code_field_widget.py
uv run ruff format courses/element_forms.py courses/forms.py tests/test_code_field_widget.py
git add courses/element_forms.py courses/forms.py tests/test_code_field_widget.py
git commit -m "feat(code-field): wire CodeTextarea into html element + course css/js fields"
```

---

## Task 2: Wrap the raw `html_seed_js` textarea in the code-field shell

**Files:**
- Modify: `templates/courses/manage/editor/_unit_settings.html`
- Test: `tests/test_code_field_seed.py` (create)

**Interfaces:**
- Produces: the unit-settings form renders the `html_seed_js` textarea inside `<div class="code-field" data-code-field>…<div class="code-field__area"><textarea name="html_seed_js" …></textarea></div></div>`, mirroring `CodeTextarea`'s output structure (this field has no Django form, so the shell is hand-written). The textarea keeps `name="html_seed_js"`, `rows="6"`, `placeholder="{}"`, and gains `spellcheck="false"`, `autocomplete="off"`, `wrap="off"` (matching the widget); the old `class="code"` is dropped (styling now comes from `.code-field__area textarea`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_code_field_seed.py`:

```python
import pytest

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_unit_settings_wraps_seed_js_in_code_field(client):
    pa = make_pa(client)
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U1"
    )
    # The editor page renders _unit_settings.html for the unit.
    url = f"/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    body = client.get(url).content.decode()
    assert 'name="html_seed_js"' in body
    # The seed textarea is now inside the code-field shell with the JS hook.
    assert "data-code-field" in body
    assert "code-field__gutter" in body
    assert 'class="code"' not in body  # the old bare-textarea class is gone
```

> Implementer notes: (1) `make_pa(client)` is the non-e2e helper used by the batch-3 tests in `tests/` — confirm its import path (e.g. `from tests.factories import make_pa` or `from tests.conftest import make_pa`); use whatever the existing review/roster tests import. (2) Confirm the editor URL: the e2e helper builds `/manage/courses/{slug}/build/unit/{pk}/edit/`; if `reverse()` is preferred, the route name is the one `editor.html` is served under — use the same path the e2e `_editor_url` uses. (3) `class="code"` also must not appear for the OTHER fields once Task 1 ran, but here we assert the seed field specifically lost it; if another unrelated element on the page legitimately uses `class="code"`, tighten the assertion to the seed `<textarea>` substring instead.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_code_field_seed.py -q`
Expected: FAIL — `data-code-field` not present around the seed textarea (it is still a bare `<textarea name="html_seed_js" class="code" …>`).

- [ ] **Step 3: Implement**

In `templates/courses/manage/editor/_unit_settings.html`, replace the seed-JS label block (currently the `<textarea name="html_seed_js" class="code" rows="6" spellcheck="false" placeholder="{}">…</textarea>`) with the shell:

```html
    <label class="unit-seed">{% trans "Unit JS (seed)" %}
      <div class="code-field" data-code-field>
        <div class="code-field__gutter" aria-hidden="true"></div>
        <div class="code-field__area"><textarea name="html_seed_js" rows="6" spellcheck="false" autocomplete="off" wrap="off" placeholder="{}">{{ unit.html_seed_js }}</textarea></div>
      </div>
    </label>
```

Leave the `{% trans "Unit JS (seed)" %}` label and the `helptext` paragraph unchanged. (No new visible string is introduced.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_code_field_seed.py -q`
Expected: PASS. Then `uv run pytest tests/test_e2e_editor.py -q` is e2e-only (skipped here) — instead run any existing non-e2e editor/unit-settings render or `node_rename` POST test to confirm the seed field still round-trips: `uv run pytest -q -k "unit_settings or node_rename or seed"` — expected PASS (the `name="html_seed_js"` POST field is unchanged).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check tests/test_code_field_seed.py
uv run ruff format tests/test_code_field_seed.py
git add templates/courses/manage/editor/_unit_settings.html tests/test_code_field_seed.py
git commit -m "feat(code-field): wrap unit seed-JS textarea in the code-field shell"
```

---

## Task 3: `code_field.js` — gutter render + scroll sync + Tab indent; load on both pages

**Files:**
- Create: `courses/static/courses/js/code_field.js`
- Modify: `courses/static/courses/css/courses.css` (gutter `overflow: hidden`), `templates/courses/manage/course_form.html`, `templates/courses/manage/editor/editor.html`
- Test: covered by e2e (Task 4); no unit test for vanilla JS. Step 4 here is a render-smoke + manual wiring check.

**Interfaces:**
- Consumes: every `[data-code-field]` shell rendered by Tasks 1–2 (its `.code-field__gutter` and `.code-field__area textarea`).
- Produces: on load AND for any later-injected `[data-code-field]` (the editor adds element forms via AJAX), the gutter shows line numbers `1..N` where `N = value.split("\n").length` (min 1, so an empty field shows `1`); the gutter's vertical scroll tracks the textarea's; **Tab** inserts two spaces at the caret without moving focus, **Shift-Tab** removes up to two leading spaces from the caret's line.

- [ ] **Step 1: Add the gutter `overflow` so scroll-sync works**

In `courses/static/courses/css/courses.css`, add `overflow: hidden;` to the existing `.code-field__gutter` rule (it currently has none; without it `gutter.scrollTop` is a no-op because the content does not establish a scroll offset). The rule becomes:

```css
.code-field__gutter {
  flex: none; min-width: 2.25rem; padding: var(--space-2) var(--space-2);
  text-align: right; color: var(--text-tertiary); background: var(--surface-sunken);
  border-right: 1px solid var(--border-subtle); user-select: none; white-space: pre;
  overflow: hidden;
}
```

(Do not touch the other `.code-field*` rules. `.code-field` already has `overflow: hidden`, so any gutter overflow beyond the field box stays clipped; the gutter is stretched to the textarea's height by the row flex, so its number content overflows exactly when the textarea content does — `scrollTop` then aligns the two.)

- [ ] **Step 2: Write the JS module**

Create `courses/static/courses/js/code_field.js`:

```javascript
(function () {
  "use strict";

  function gutterOf(field) {
    return field.querySelector(".code-field__gutter");
  }
  function textareaOf(field) {
    return field.querySelector(".code-field__area textarea");
  }

  // Render line numbers 1..N (N = logical lines, min 1) and keep the gutter's
  // vertical scroll aligned with the textarea after the content changes.
  function renderGutter(ta, gutter) {
    var lines = ta.value.split("\n").length || 1;
    var out = "1";
    for (var i = 2; i <= lines; i++) out += "\n" + i;
    gutter.textContent = out;
    gutter.scrollTop = ta.scrollTop;
  }

  function enhance(field) {
    if (field.dataset.codeFieldReady) return;
    var ta = textareaOf(field);
    var gutter = gutterOf(field);
    if (!ta || !gutter) return;
    field.dataset.codeFieldReady = "1";
    renderGutter(ta, gutter);
  }

  function enhanceAll(root) {
    var fields = (root || document).querySelectorAll("[data-code-field]");
    for (var i = 0; i < fields.length; i++) enhance(fields[i]);
  }

  function fieldFor(node) {
    return node && node.closest ? node.closest("[data-code-field]") : null;
  }

  // Delegated input → re-render that field's gutter.
  document.addEventListener("input", function (e) {
    if (!e.target || e.target.tagName !== "TEXTAREA") return;
    var field = fieldFor(e.target);
    if (field) renderGutter(e.target, gutterOf(field));
  });

  // Delegated scroll (capture: scroll does not bubble) → sync the gutter offset.
  document.addEventListener(
    "scroll",
    function (e) {
      if (!e.target || e.target.tagName !== "TEXTAREA") return;
      var field = fieldFor(e.target);
      if (field) gutterOf(field).scrollTop = e.target.scrollTop;
    },
    true
  );

  // Delegated Tab → insert two spaces (Shift-Tab outdents up to two leading
  // spaces on the caret's line); never move focus while editing code.
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Tab" || !e.target || e.target.tagName !== "TEXTAREA") return;
    var field = fieldFor(e.target);
    if (!field) return;
    e.preventDefault();
    var ta = e.target;
    var start = ta.selectionStart;
    var end = ta.selectionEnd;
    var val = ta.value;
    if (e.shiftKey) {
      var lineStart = val.lastIndexOf("\n", start - 1) + 1;
      var removed = 0;
      while (removed < 2 && val.charAt(lineStart + removed) === " ") removed++;
      if (removed) {
        ta.value = val.slice(0, lineStart) + val.slice(lineStart + removed);
        ta.selectionStart = ta.selectionEnd = Math.max(lineStart, start - removed);
      }
    } else {
      ta.value = val.slice(0, start) + "  " + val.slice(end);
      ta.selectionStart = ta.selectionEnd = start + 2;
    }
    renderGutter(ta, gutterOf(field));
  });

  function init() {
    enhanceAll(document);
    if (typeof MutationObserver === "function") {
      var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var added = muts[i].addedNodes;
          for (var j = 0; j < added.length; j++) {
            var n = added[j];
            if (n.nodeType !== 1) continue;
            if (n.matches && n.matches("[data-code-field]")) enhance(n);
            if (n.querySelectorAll) enhanceAll(n);
          }
        }
      });
      mo.observe(document.body, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
```

- [ ] **Step 3: Load the module on both pages**

In `templates/courses/manage/course_form.html`, change the `extra_js` block to also load the module:

```html
{% block extra_js %}<script src="{% static 'courses/js/course_form.js' %}"></script><script src="{% static 'courses/js/code_field.js' %}" defer></script>{% endblock %}
```

In `templates/courses/manage/editor/editor.html`, append one line inside the existing `{% block extra_js %}` (after the last `<script … html_element.js …>` line):

```html
  <script src="{% static 'courses/js/code_field.js' %}" defer></script>
```

(These two pages render all four fields: course form → `html_css`/`html_js`; editor → `html_seed_js` (unit settings) + the `html` field of the AJAX-loaded HtmlElement form, which the MutationObserver enhances.)

- [ ] **Step 4: Wire-up check (no JS unit test)**

Confirm `base.html` defines an `extra_js` block (it does — `course_form.html`/`editor.html` already use it). Run the render assertions that prove the hook + script are present:

```bash
uv run pytest tests/test_code_field_widget.py tests/test_code_field_seed.py -q
```
Expected: PASS (still green — the JS does not change server render). The actual gutter/Tab behaviour is verified by the e2e in Task 4.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check .
uv run ruff format --check courses/ tests/
git add courses/static/courses/js/code_field.js courses/static/courses/css/courses.css templates/courses/manage/course_form.html templates/courses/manage/editor/editor.html
git commit -m "feat(code-field): gutter line-numbers + scroll-sync + Tab-indent JS"
```

---

## Task 4: e2e — gutter line count + Tab indent (real gestures)

**Files:**
- Modify: `tests/test_e2e_editor.py`, `tests/test_e2e_course_form.py`

**Interfaces:** drives the real browser per `e2e-must-drive-real-ui` — types into the actual textarea and presses the actual Tab key; asserts on the rendered gutter and the textarea value.

- [ ] **Step 1: Write the failing e2e — editor html field (AJAX-injected, MutationObserver path)**

Append to `tests/test_e2e_editor.py` (reuse the file's `_make_pa_user`, `_login`, `_seed_course_and_unit`, `_editor_url`, `_add_element`; mirror the file's `pytestmark`/fixtures):

```python
@pytest.mark.django_db(transaction=True)
def test_code_field_gutter_and_tab_indent(page, live_server):
    _make_pa_user("cfauthor")
    unit = _seed_course_and_unit("cfauthor")
    _login(page, live_server, "cfauthor")
    page.goto(_editor_url(live_server, unit))

    # Add an HTML element; its form (with the code-field) is injected via fetch,
    # so this exercises the MutationObserver enhancement path.
    _add_element(page, "html")  # verify the add-menu type key for HtmlElement

    field = page.locator("[data-code-field]").last
    ta = field.locator("textarea")
    gutter = field.locator(".code-field__gutter")

    # Gutter maps 1:1 to logical lines: three lines -> last gutter number is "3".
    ta.fill("alpha\nbeta\ngamma")
    assert gutter.inner_text().strip().splitlines()[-1] == "3"

    # Tab inserts two spaces at the caret and does NOT move focus.
    ta.click()
    page.keyboard.press("Control+Home")  # caret to start of the field
    page.keyboard.press("Tab")
    assert ta.input_value().startswith("  ")
    assert ta.evaluate("el => el === document.activeElement") is True
```

> Implementer: confirm the HtmlElement add-menu key passed to `_add_element` (it clicks `[data-add-type='<key>']`). Inspect the add menu in `builder`/`editor` markup for the HTML element's `data-add-type` value (likely `"html"`); if it differs, use the real key. If `Control+Home` does not move the caret in this browser build, use `ta.evaluate("el => el.setSelectionRange(0,0)")` ONLY to position the caret (that is setup, not the load-bearing gesture) — the Tab press itself must stay a real `page.keyboard.press`.

- [ ] **Step 2: Write the failing e2e — course form field (server-rendered, non-fragment path)**

Append to `tests/test_e2e_course_form.py` (reuse its `_make_pa_user`/`_login`):

```python
@pytest.mark.django_db(transaction=True)
def test_course_form_code_field_gutter(page, live_server):
    _make_pa_user("cfowner")
    _login(page, live_server, "cfowner")
    page.goto(f"{live_server.url}/manage/courses/new/")

    field = page.locator('[data-field="html_css"] [data-code-field]')
    ta = field.locator("textarea")
    gutter = field.locator(".code-field__gutter")
    ta.fill("x\ny")
    assert gutter.inner_text().strip().splitlines()[-1] == "2"
```

- [ ] **Step 3: Run to verify they fail, then make them pass**

Run: `uv run pytest tests/test_e2e_editor.py tests/test_e2e_course_form.py -q -m e2e -k "code_field or gutter"`
Expected: FAIL first (gutter empty / numbers absent until `code_field.js` runs — if Tasks 1–3 are already committed they may pass first try; if so, briefly break the hook locally to confirm the assertions are load-bearing, then restore). Iterate selectors against the rendered markup until green. Run each e2e file alone if you hit `live_server` port contention (infra artifact, not a real failure):
`uv run pytest tests/test_e2e_editor.py -q -m e2e` then `uv run pytest tests/test_e2e_course_form.py -q -m e2e`.

- [ ] **Step 4: Commit**

```bash
uv run ruff check tests/test_e2e_editor.py tests/test_e2e_course_form.py
uv run ruff format tests/test_e2e_editor.py tests/test_e2e_course_form.py
git add tests/test_e2e_editor.py tests/test_e2e_course_form.py
git commit -m "test(code-field): e2e gutter line-count + Tab-indent on editor + course form"
```

---

## Task 5: DoD — full suite, lint, i18n check, light/dark screenshots

**Files:**
- (verification only; possible `locale/pl/LC_MESSAGES/django.po` + `.mo` only if a new string slipped in)

- [ ] **Step 1: i18n check (expected: no new strings)**

Run `uv run python manage.py makemessages -l pl` and `git diff --stat locale/`. **Expected: no change** (batch 4 adds no new visible server string — the only literals added are the seed-field attributes and gutter digits, neither translatable). If `django.po` DID change, you introduced a string — wrap it in `{% trans %}`, add the Polish translation, clear any `#, fuzzy`/`#~` (the makemessages fuzzy gotcha), and `uv run python manage.py compilemessages`. Then:
Run: `uv run pytest -k po_catalog_clean -q` → PASS.

- [ ] **Step 2: Full suite + lint**

```bash
uv run pytest -q            # non-e2e: expect all green
uv run pytest -q -m e2e     # e2e: expect green (run the two touched files alone if port contention)
uv run ruff check .
uv run ruff format --check .
```
Expected: all green.

- [ ] **Step 3: Screenshot self-review (light + dark)**

Per `verify-ui-with-screenshots`: throwaway Playwright harness (reuse the e2e login/seed helpers). Screenshot **light + dark** of (a) the **editor** with an HtmlElement code-field populated with ~6 lines (gutter numbers aligned to the lines, theme-following surfaces, focus ring on the textarea) and (b) the **course form** `html_css`/`html_js` fields. Self-critique: gutter digits right-aligned and vertically aligned to their code lines; no soft-wrap (a long line scrolls horizontally, gutter unaffected); empty field shows "1"; dark theme inverts surfaces and stays legible; the textarea resize handle still works. Fix any issue (CSS only — do not change the JS contract), re-screenshot. Save the final PNGs to the session scratchpad and report their paths; delete the harness (delete-after pattern).

- [ ] **Step 4: Commit (only if i18n/CSS changed in this task)**

```bash
# only if Step 1 produced .po/.mo changes or Step 3 produced a CSS tweak:
git add -A
git commit -m "i18n/polish(code-field): <describe>"
```

---

## Self-Review (author checklist — completed)

**Spec coverage (§5 + §8):**
- Styled monospace container, theme-following, line-number gutter synced to line count + scroll, no soft-wrap (1:1), empty → "1" → batch-1 CSS (reused) + Tasks 1–3. ✓
- Tab inserts indentation without moving focus (Shift-Tab outdent — the spec's optional extra) → Task 3 JS + Task 4 e2e. ✓
- Applies to exactly the four enumerated fields (`HtmlElement.html`, `Course.html_css`, `Course.html_js`, `ContentNode.html_seed_js`) → Tasks 1–2. ✓
- No-JS fallback = styled monospace textarea, sandbox/help unchanged → the shell is inert without JS; help text untouched. ✓
- "header strip label" → satisfied by the existing external per-field label; no in-widget strip added (documented decision, flagged for review). ⚠️ (intentional deviation from the mockup's decorative strip)
- §8 tests: e2e real-gesture gutter-sync + Tab-indent → Task 4; render/widget tests → Tasks 1–2; every-batch DoD (full suite + ruff check/format + i18n) → Task 5. ✓

**Placeholder scan:** the e2e add-menu key for the HtmlElement type (`_add_element(page, "html")`), the `make_pa` import path, and the editor URL/route name are flagged inline to verify against the codebase, not silent TODOs — all behavioural code is complete.

**Type consistency:** the shell classes (`code-field`, `code-field__gutter`, `code-field__area`, `data-code-field`) and the `data-code-field-ready` guard are used identically across the widget (batch 1), the seed template wrap (Task 2), the JS (Task 3), and the tests (Tasks 1/2/4). `rows` values match per field (12 / 10 / 10 / 6). No model/migration change.
