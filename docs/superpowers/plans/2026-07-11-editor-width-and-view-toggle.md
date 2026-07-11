# Editor Width & 3-Way View Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Widen the course editor page beyond the app's 960px cap and add an Editor/Split/Preview view toggle, so the live preview always renders at real student width and the editor gets more room.

**Architecture:** Purely presentational — template + CSS + a small JS enhancer folded into `editor.js`. A single `--editor-wide` (70rem) breakpoint governs the grid; a `.view-toggle` control (distinct from the pre-existing `.type-toggle` unit-type switch) sets an `is-mode-*` class on `.editor-grid` that CSS reacts to; the chosen mode persists in `localStorage['libli-editor-view']`, stamped before paint by an inline pre-paint script. No backend/model/URL changes.

**Tech Stack:** Django templates, token-driven CSS (`core/css/tokens.css`), vanilla JS (`editor.js` IIFE), pytest + Playwright e2e, Django i18n (EN + PL).

## Global Constraints

- **No backend surface change:** no model, view, URL, or migration changes. The editor view (`courses:manage_editor`) is untouched.
- **Scope to the editor page only:** every CSS override is scoped to `body.editor-page`; no other page's width or layout may change.
- **`localStorage` key is exactly `libli-editor-view`; values are exactly `editor`, `split`, `preview`** — verbatim in both the pre-paint script and the enhancer.
- **Single breakpoint literal `70rem`** in every editor-grid `@media` (custom properties cannot be used in media-query conditions, so `--editor-wide` is a documentation name, written as the literal `70rem` in `@media`).
- **Distinct hook:** the view toggle uses `.view-toggle` / `[data-view-toggle]` / per-button `data-view` — never the pre-existing `.type-toggle*` selectors (the Lesson/Quiz switch at `editor.html:50`).
- **i18n:** every new user-facing / AT-visible string is wrapped in `{% trans %}` and translated in `locale/pl/LC_MESSAGES/django.po` (no fuzzy/obsolete entries).
- **Tooling:** ruff/pytest/manage.py are invoked via `uv run` (they are not on PATH). e2e tests are `-m e2e`; **run focused e2e in the foreground only** (never a full `-m e2e` background sweep — it spawns runaway headless browsers).

## File Structure

- `templates/courses/manage/editor/editor.html` — render the `.view-toggle` control (above the `_editor_scope` include, outside the swapped `[data-scope]` panes) + the pre-paint inline script (immediately after the include).
- `templates/courses/manage/editor/_editor_scope.html` — hardcode the default `is-mode-split` on `.editor-grid`.
- `templates/courses/manage/editor/_preview.html` — wrap preview content in `.prev-inner`.
- `courses/static/courses/css/editor.css` — width model, tokens, `is-mode-*` rules, `.view-toggle` styling + `[hidden]` override, `scrollbar-gutter`, page-cap override, breakpoint consolidation.
- `courses/static/courses/js/editor.js` — the view-toggle enhancer (reveal + wire), appended inside the existing IIFE.
- `locale/pl/LC_MESSAGES/django.po` (+ compiled `django.mo`) — PL translations for the new strings.
- Tests: `tests/test_editor_view_toggle.py` (Django test-client markup + CSS-content guards), `tests/test_e2e_editor_view_toggle.py` (Playwright behaviour), `tests/test_i18n_editor_view_toggle.py` (PL catalog gate).

---

### Task 1: Template markup — toggle, pre-paint script, preview wrapper, default mode class

**Files:**
- Modify: `templates/courses/manage/editor/editor.html` (insert toggle before the `_editor_scope` include at line 65; insert pre-paint `<script>` after it)
- Modify: `templates/courses/manage/editor/_editor_scope.html:2` (add `is-mode-split`)
- Modify: `templates/courses/manage/editor/_preview.html:4-19` (wrap content in `.prev-inner`)
- Test: `tests/test_editor_view_toggle.py`

**Interfaces:**
- Produces: the DOM contract the CSS (Task 2) and JS (Task 3) bind to — `.view-toggle[hidden]` wrapper containing `.view-toggle__caption` and a `[data-view-toggle]` group of three `.view-toggle__btn[data-view="editor|split|preview"]` buttons (split active by default); `.editor-grid.is-mode-split`; `.prev-inner` inside `.pane-body.prev`; an inline pre-paint script referencing `localStorage['libli-editor-view']`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_editor_view_toggle.py`:

```python
import pytest
from django.urls import reverse

from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.fixture
def editor_html(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    add_element(unit, TextElement.objects.create(body="<p>Hello world</p>"))
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    return resp.content.decode("utf-8")


@pytest.mark.django_db
def test_view_toggle_renders_three_buttons(editor_html):
    assert 'data-view-toggle' in editor_html
    for mode in ("editor", "split", "preview"):
        assert f'data-view="{mode}"' in editor_html


@pytest.mark.django_db
def test_view_toggle_hidden_by_default(editor_html):
    # The wrapper is rendered hidden so no-JS users never see a dead control.
    assert 'class="view-toggle"' in editor_html
    assert 'hidden' in editor_html.split('class="view-toggle"')[1][:40]


@pytest.mark.django_db
def test_split_is_default_active(editor_html):
    assert 'is-mode-split' in editor_html
    # The split button is the pressed/active one by default.
    split_btn = editor_html.split('data-view="split"')[0][-120:] + editor_html.split('data-view="split"')[1][:120]
    assert 'aria-pressed="true"' in split_btn
    assert 'is-active' in split_btn


@pytest.mark.django_db
def test_prepaint_script_present(editor_html):
    assert "libli-editor-view" in editor_html


@pytest.mark.django_db
def test_preview_has_inner_wrapper(editor_html):
    assert 'class="prev-inner"' in editor_html
    assert "Hello world" in editor_html  # content still renders inside it
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_editor_view_toggle.py -v`
Expected: FAIL (assertions on `data-view-toggle`, `is-mode-split`, `prev-inner`, `libli-editor-view` — none exist yet).

- [ ] **Step 3: Add the default mode class in `_editor_scope.html`**

Change line 2 from:

```html
<div class="editor-grid">
```

to:

```html
<div class="editor-grid is-mode-split">
```

- [ ] **Step 4: Wrap preview content in `.prev-inner` in `_preview.html`**

Replace the `.pane-body.prev` body (lines 4–19) so the title + loop are wrapped:

```html
  <div class="pane-body prev">
    <div class="prev-inner">
      <h2 class="prev-unit-title">{{ unit.title }}</h2>
      {% for el in preview_elements %}
        {% comment %}
          "Try it" preview: questions render via the student template (a POST form) but
          point at the manage-gated, non-persisting try endpoint instead of the student
          check (which needs enrollment). editor.js intercepts the submit and posts via
          fetch with the CSRF header — the form's own csrf token is empty here
          (rendered without a request), exactly as on student pages (see question.js).
        {% endcomment %}
        {% url 'courses:manage_element_try' slug=unit.course.slug pk=el.pk as try_url %}
        <section class="prev-el" data-element-id="{{ el.pk }}">{% render_element el action_url=try_url %}</section>
      {% empty %}
        <p class="empty-state">{% trans "Nothing to preview yet." %}</p>
      {% endfor %}
    </div>
  </div>
```

- [ ] **Step 5: Add the toggle control + pre-paint script in `editor.html`**

> **Intentional wrapper/group split (vs. spec):** the spec sketched a single
> `<div class="view-toggle" role="group" aria-label="Editor view" data-view-toggle>`
> holding the buttons. This plan deliberately splits it into an outer `.view-toggle`
> (the `hidden` wrapper, holding the caption) and an inner `.view-toggle__group`
> (`role="group"` + `aria-label` + `data-view-toggle`, holding only the buttons) — so
> the caption is not a child of the button `role="group"` (an ARIA-correctness
> improvement). The hook contract is unchanged: JS/pre-paint still select the buttons
> via `[data-view-toggle]` and reveal via `.view-toggle`.

In `editor.html`, the content block currently ends (lines 64–66):

```html
  {% include "courses/manage/editor/_unit_settings.html" %}
  {% include "courses/manage/editor/_editor_scope.html" with open_form="" %}
</section>
```

Replace those three lines with:

```html
  {% include "courses/manage/editor/_unit_settings.html" %}
  <div class="view-toggle" hidden>
    <span class="view-toggle__caption">{% trans "View" %}</span>
    <div class="view-toggle__group" role="group" aria-label="{% trans 'Editor view' %}" data-view-toggle>
      <button type="button" class="view-toggle__btn" data-view="editor" aria-pressed="false">{% trans "Editor" %}</button>
      <button type="button" class="view-toggle__btn is-active" data-view="split" aria-pressed="true">{% trans "Split" %}</button>
      <button type="button" class="view-toggle__btn" data-view="preview" aria-pressed="false">{% trans "Preview" %}</button>
    </div>
  </div>
  {% include "courses/manage/editor/_editor_scope.html" with open_form="" %}
  {% comment %}Pre-paint: stamp the stored view mode + active button BEFORE first paint so
  neither the layout nor the active segment flashes to the split default. Inline (not
  deferred) and placed AFTER the grid so .editor-grid already exists at parse time.{% endcomment %}
  <script>
    (function () {
      try {
        var grid = document.querySelector(".editor-grid");
        if (!grid) return;
        var tog = document.querySelector("[data-view-toggle]");
        var modes = ["editor", "split", "preview"];
        var v;
        try { v = localStorage.getItem("libli-editor-view"); } catch (e) { v = null; }
        if (modes.indexOf(v) === -1) v = "split";
        modes.forEach(function (m) { grid.classList.remove("is-mode-" + m); });
        grid.classList.add("is-mode-" + v);
        if (tog) {
          tog.querySelectorAll("[data-view]").forEach(function (b) {
            var on = b.getAttribute("data-view") === v;
            b.classList.toggle("is-active", on);
            b.setAttribute("aria-pressed", on ? "true" : "false");
          });
        }
      } catch (e) { /* leave the server-rendered split default */ }
    })();
  </script>
</section>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_editor_view_toggle.py -v`
Expected: PASS (all 5 tests).

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/editor/editor.html templates/courses/manage/editor/_editor_scope.html templates/courses/manage/editor/_preview.html tests/test_editor_view_toggle.py
git commit -m "feat(editor): view-toggle markup, pre-paint script, preview inner wrapper"
```

---

### Task 2: CSS — width model, modes, toggle styling, breakpoint consolidation

**Files:**
- Modify: `courses/static/courses/css/editor.css` (rework `.editor-grid` at lines 12–21; move/rename the `@media (min-width: 901px)` block at 251–260 to `70rem`; remove the redundant `@media (max-width: 900px)` at 285–287; add tokens, mode rules, `.view-toggle`, `.prev-inner`, `scrollbar-gutter`, page-cap override)
- Test: extend `tests/test_editor_view_toggle.py` with CSS-content guards (mirrors `tests/test_editor_styles.py`)

**Interfaces:**
- Consumes: the DOM contract from Task 1 (`.editor-grid.is-mode-*`, `.view-toggle[hidden]`, `.prev-inner`, `.editor-pane`/`.preview-pane`).
- Produces: the visual width model the e2e in Task 3 asserts (wide → two columns; narrow → stacked; solo → one centered pane).

> **Line numbers vs. quoted blocks:** the exact quoted code blocks below are the
> authoritative match targets, **not** the cited line numbers. Step 3 replaces ~11
> lines with ~40, so the ranges quoted in Steps 4–6 (and the Files header) drift by
> ~+29 lines once Step 3 lands — match on the quoted content, not the numbers.

- [ ] **Step 1: Write the failing CSS-content guard test**

Append to `tests/test_editor_view_toggle.py`:

```python
from pathlib import Path

EDITOR_CSS = (
    Path(__file__).resolve().parent.parent
    / "courses" / "static" / "courses" / "css" / "editor.css"
)


def test_editor_css_defines_width_model_and_toggle():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    # Page breaks the app cap, scoped to the editor page only.
    assert "body.editor-page .app-main" in css
    assert "102rem" in css
    # Single 70rem breakpoint governs split's two columns.
    assert "min-width: 70rem" in css
    assert ".editor-grid.is-mode-split" in css
    # Solo hide-rules.
    assert ".editor-grid.is-mode-editor .preview-pane" in css
    assert ".editor-grid.is-mode-preview .editor-pane" in css
    # The [hidden] override is REQUIRED because .view-toggle carries a flex display
    # that would otherwise beat the UA [hidden]{display:none} rule.
    assert ".view-toggle[hidden]" in css
    # Preview reserves its scrollbar so content stays a true 46rem.
    assert "scrollbar-gutter" in css
    assert ".prev-inner" in css


def test_editor_css_has_no_stale_stacking_breakpoints():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    # The old 720/900 stacking rules are folded into the single-column base.
    assert "max-width: 900px" not in css
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_editor_view_toggle.py -k css -v`
Expected: FAIL (`body.editor-page .app-main`, `is-mode-split`, `.view-toggle[hidden]`, `scrollbar-gutter`, `.prev-inner` absent; `max-width: 900px` still present).

- [ ] **Step 3: Rework the base `.editor-grid` block**

In `editor.css`, replace the current block (lines 11–21):

```css
/* --- Editor two-column layout --- */
.editor-grid {
  /* Editor column capped narrow (2-row element tiles fit); preview takes the rest
     so it reads closer to the real student width. */
  display: grid; grid-template-columns: minmax(17rem, 22rem) 1fr; gap: var(--space-5);
  align-items: start;
}
.editor-pane { color: var(--text-primary); }
@media (max-width: 720px) {
  .editor-grid { grid-template-columns: 1fr; }
}
```

with:

```css
/* --- Editor width model + 3-way view toggle ---
   Tokens scoped to the editor page. NB: the 70rem grid breakpoint is written as a
   literal in every @media below — CSS custom properties cannot be used in media-query
   conditions, so "--editor-wide" is only a documentation name. */
body.editor-page {
  --preview-w: 48.5rem;      /* 46rem student content + 2×1rem pane padding + 0.5rem scrollbar gutter */
  --editor-min: 17rem;       /* editor never narrower than this (2-row tiles fit) */
  --editor-split-max: 48rem; /* editor's split cap = preview width when the screen allows */
  --editor-solo-max: 54rem;  /* editor's solo cap — a bit wider */
}

/* Editor page breaks the global 960px app cap (only this page), up to 102rem, then centers. */
body.editor-page .app-main { max-width: 102rem; }

/* Base (all widths): single column. This is the stacked/narrow layout and the safe
   default; only grid-template-columns changes from the old minmax()+1fr — gap and
   align-items are preserved because both stacked and split layouts need them. */
.editor-grid {
  display: grid; grid-template-columns: 1fr; gap: var(--space-5);
  align-items: start;
}
.editor-pane { color: var(--text-primary); }

/* Solo modes (all widths): hide the inactive pane; cap + center the visible one.
   Per-mode cap, scoped so it never bleeds into split (whose widths come from the grid tracks). */
.editor-grid.is-mode-editor .preview-pane,
.editor-grid.is-mode-preview .editor-pane { display: none; }
.editor-grid.is-mode-editor .editor-pane {
  max-width: var(--editor-solo-max); margin-inline: auto; width: 100%;
}
.editor-grid.is-mode-preview .preview-pane {
  max-width: var(--preview-w); margin-inline: auto; width: 100%;
}

/* Preview content mirrors the student 46rem, centered. Load-bearing below 70rem
   (there the preview is the base 1fr full-width column, so this is the sole cap). */
.prev-inner { max-width: 46rem; margin-inline: auto; }
/* Reserve the preview scrollbar gutter so the 46rem content region is stable whether
   or not the pane is currently overflowing (--preview-w bakes in the 0.5rem). */
.preview-pane .pane-body { scrollbar-gutter: stable; }
```

- [ ] **Step 4: Rework the wide-width block (901px → 70rem) and add split two-column**

Replace the existing block (lines 251–260):

```css
@media (min-width: 901px) {
  /* Lock the page to the viewport; only the pane bodies scroll. Scoped to body.editor-page
     (set by the editor template) so no other page's layout is touched. */
  body.editor-page { height: 100vh; overflow: hidden; display: flex; flex-direction: column; }
  body.editor-page .app-main { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
  .editor { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
  .editor-grid { flex: 1 1 auto; min-height: 0; align-items: stretch; }
  .editor-pane, .preview-pane { min-height: 0; display: flex; flex-direction: column; }
  .editor-pane .pane-body, .preview-pane .pane-body { overflow-y: auto; min-height: 0; }
}
```

with (note the `min-width: 70rem` and the appended split rule):

```css
@media (min-width: 70rem) {
  /* Lock the page to the viewport; only the pane bodies scroll. Scoped to body.editor-page
     (set by the editor template) so no other page's layout is touched. The threshold rises
     from the old 901px to 70rem (1120px) because a fixed student-width preview + a usable
     editor genuinely need ~1120px; 901–1119px viewports now stack (mitigated by solo modes). */
  body.editor-page { height: 100vh; overflow: hidden; display: flex; flex-direction: column; }
  body.editor-page .app-main { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
  .editor { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
  .editor-grid { flex: 1 1 auto; min-height: 0; align-items: stretch; }
  .editor-pane, .preview-pane { min-height: 0; display: flex; flex-direction: column; }
  .editor-pane .pane-body, .preview-pane .pane-body { overflow-y: auto; min-height: 0; }

  /* Split = two columns ONLY here; below 70rem the base 1fr stacks. Scoping the two-column
     template inside the media query is what stops the .is-mode-split class (specificity
     0,2,0) from out-specifying the narrow single-column base — there is simply no competing
     two-column declaration at narrow widths. justify-content:center balances the ~1.75rem
     slack near the page max so the equal columns sit centered, not trailing left. */
  .editor-grid.is-mode-split {
    grid-template-columns: minmax(var(--editor-min), var(--editor-split-max)) var(--preview-w);
    justify-content: center;
  }
}
```

Then fix the now-stale explanatory comment just above `.preview-pane { min-width: 0; }`
(the block that ends "…the page flows naturally (guarded by min-width: 901px below)."):
change the trailing `min-width: 901px` reference to `min-width: 70rem` so the shipped
comment names the breakpoint that actually exists after this task.

- [ ] **Step 5: Remove the redundant `max-width: 900px` stacking rule**

Delete the now-redundant block (lines 285–287):

```css
@media (max-width: 900px) {
  .editor-grid { grid-template-columns: 1fr; }
}
```

(The base rule is already `1fr`, so stacking below 70rem is automatic.)

- [ ] **Step 6: Add `.view-toggle` styling (shares the `.type-toggle` look, distinct selectors)**

Append near the `.type-toggle` rules (after editor.css:231):

```css
/* View toggle (Editor/Split/Preview). Distinct from .type-toggle (the Lesson/Quiz
   unit-type switch) so JS/pre-paint/e2e selectors never collide; shares its look. */
.view-toggle { display: inline-flex; align-items: center; gap: var(--space-2); margin: var(--space-2) 0; }
/* REQUIRED: .view-toggle is flex, and an author `display` overrides the UA
   [hidden]{display:none} rule regardless of specificity — without this explicit rule the
   `hidden` control would still show (the shipped-before [hidden] gotcha). */
.view-toggle[hidden] { display: none; }
.view-toggle__caption { font-size: .72rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-tertiary); }
.view-toggle__group { display: inline-flex; border: 1px solid var(--border-default); border-radius: var(--radius-md); overflow: hidden; }
.view-toggle__btn { padding: 4px 12px; background: var(--surface-sunken); color: var(--text-secondary); border: 0; cursor: pointer; font: inherit; }
.view-toggle__btn + .view-toggle__btn { border-left: 1px solid var(--border-default); }
.view-toggle__btn.is-active { background: var(--primary); color: var(--surface-raised); }
```

- [ ] **Step 7: Run the CSS-content tests to verify they pass**

Run: `uv run pytest tests/test_editor_view_toggle.py -k css -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/css/editor.css tests/test_editor_view_toggle.py
git commit -m "feat(editor): width model, is-mode-* rules, view-toggle styling, single 70rem breakpoint"
```

---

### Task 3: JS enhancer + Playwright e2e (behaviour + persistence + layout)

**Files:**
- Modify: `courses/static/courses/js/editor.js` (append the enhancer inside the IIFE, just before the closing `})();`)
- Test: `tests/test_e2e_editor_view_toggle.py`

**Interfaces:**
- Consumes: Task 1 DOM (`.view-toggle`, `[data-view-toggle]`, `[data-view]` buttons) + Task 2 CSS (mode rules). `root` is the existing `document.querySelector(".editor")` in editor.js.
- Produces: click-to-switch behaviour, `localStorage['libli-editor-view']` persistence, and the revealed toggle.

- [ ] **Step 1: Write the failing e2e test**

Create `tests/test_e2e_editor_view_toggle.py`:

```python
"""Playwright e2e for the editor view toggle (Editor/Split/Preview) + width model.

Mirrors the helpers in test_e2e_editor_ws3.py: DJANGO_ALLOW_ASYNC_UNSAFE session
fixture, PLATFORM_ADMIN seed, allauth login, and the courses:manage_editor URL.
Drives the REAL button clicks and a REAL reload (no page.evaluate shortcut)."""

import os

import pytest

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


def _seed_unit(pa, slug="viewtog"):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    return course, unit


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


@pytest.mark.django_db
def test_toggle_switches_and_persists(page, live_server):
    pa = _make_pa_user("pa")
    course, unit = _seed_unit(pa)
    page.set_viewport_size({"width": 1400, "height": 900})  # wide: two-column split
    _login(page, live_server, "pa")
    page.goto(_editor_url(live_server, course, unit))

    grid = page.locator(".editor-grid")
    editor_pane = page.locator('[data-scope="editor"]')
    preview_pane = page.locator('[data-scope="preview"]')

    # Default split: both panes visible, toggle revealed (enhancer removed [hidden]).
    assert "is-mode-split" in (grid.get_attribute("class") or "")
    page.wait_for_selector("[data-view-toggle]", state="visible")
    assert editor_pane.is_visible() and preview_pane.is_visible()

    # Wide split is genuinely two side-by-side columns (not stacked): preview sits to
    # the right of the editor and their vertical extents overlap (same row).
    eb = editor_pane.bounding_box()
    pb = preview_pane.bounding_box()
    assert pb["x"] > eb["x"]
    assert pb["y"] < eb["y"] + eb["height"] and eb["y"] < pb["y"] + pb["height"]

    # Click Preview: editor pane hidden, class + storage updated.
    page.locator('[data-view="preview"]').click()
    assert "is-mode-preview" in (grid.get_attribute("class") or "")
    assert not editor_pane.is_visible()
    assert preview_pane.is_visible()
    assert page.evaluate("localStorage.getItem('libli-editor-view')") == "preview"

    # Reload: persists to Preview end-state (pre-paint stamps it before paint).
    page.reload()
    grid = page.locator(".editor-grid")
    assert "is-mode-preview" in (grid.get_attribute("class") or "")
    assert not page.locator('[data-scope="editor"]').is_visible()


@pytest.mark.django_db
def test_corrupt_stored_value_falls_back_to_split(page, live_server):
    pa = _make_pa_user("pa2")
    course, unit = _seed_unit(pa, slug="viewtog2")
    page.set_viewport_size({"width": 1400, "height": 900})
    _login(page, live_server, "pa2")
    page.goto(_editor_url(live_server, course, unit))
    page.evaluate("localStorage.setItem('libli-editor-view', 'garbage')")
    page.reload()
    grid = page.locator(".editor-grid")
    assert "is-mode-split" in (grid.get_attribute("class") or "")


@pytest.mark.django_db
def test_narrow_viewport_stacks_split(page, live_server):
    pa = _make_pa_user("pa3")
    course, unit = _seed_unit(pa, slug="viewtog3")
    page.set_viewport_size({"width": 1000, "height": 900})  # <70rem/1120px: stacks
    _login(page, live_server, "pa3")
    page.goto(_editor_url(live_server, course, unit))
    ed = page.locator('[data-scope="editor"]').bounding_box()
    pv = page.locator('[data-scope="preview"]').bounding_box()
    # Stacked: preview sits below the editor (not side-by-side).
    assert pv["y"] >= ed["y"] + ed["height"] - 5
```

- [ ] **Step 2: Run the e2e test to verify it fails**

Run (focused, foreground): `uv run pytest tests/test_e2e_editor_view_toggle.py -m e2e -v`
Expected: FAIL (toggle never revealed / clicks do nothing — no enhancer yet).

- [ ] **Step 3: Append the enhancer to `editor.js`**

Immediately before the closing `})();` of the IIFE in `editor.js`, add:

```javascript
  // --- 3-way view toggle (Editor / Split / Preview) ---
  // The toggle lives in editor.html OUTSIDE the swapped [data-scope] panes, and
  // .editor-grid is never swapped by applyFragments — so these references and the
  // mode class both survive fragment updates. The enhancer TRUSTS the pre-paint DOM
  // on init (it does not re-read localStorage); it only reveals the control and wires
  // clicks. Validation on the write path keeps localStorage to the three known values.
  (function initViewToggle() {
    var toggle = root.querySelector(".view-toggle");
    var group = root.querySelector("[data-view-toggle]");
    var grid = root.querySelector(".editor-grid");
    if (!toggle || !group || !grid) return;
    var MODES = ["editor", "split", "preview"];
    function setMode(v) {
      if (MODES.indexOf(v) === -1) v = "split";
      MODES.forEach(function (m) { grid.classList.remove("is-mode-" + m); });
      grid.classList.add("is-mode-" + v);
      group.querySelectorAll("[data-view]").forEach(function (b) {
        var on = b.getAttribute("data-view") === v;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
      try { localStorage.setItem("libli-editor-view", v); } catch (e) { /* in-session only */ }
    }
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-view]");
      if (!btn || !group.contains(btn)) return;
      setMode(btn.getAttribute("data-view"));
    });
    toggle.hidden = false;  // reveal now that clicks are wired
  })();
```

- [ ] **Step 4: Run the e2e test to verify it passes**

Run (focused, foreground): `uv run pytest tests/test_e2e_editor_view_toggle.py -m e2e -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/editor.js tests/test_e2e_editor_view_toggle.py
git commit -m "feat(editor): view-toggle enhancer (reveal, wire clicks, persist mode)"
```

---

### Task 4: i18n — PL translations for the new strings

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ recompiled `locale/pl/LC_MESSAGES/django.mo`)
- Test: `tests/test_i18n_editor_view_toggle.py`

**Interfaces:**
- Consumes: the `{% trans %}` msgids introduced in Task 1 (`View`, `Editor view`, `Editor`, `Split`, `Preview`).
- Produces: PL catalog entries so `gettext` returns a non-identity translation and the catalog tests stay green.

Note: `Editor` and `Preview` may already exist as msgids elsewhere in the catalog (e.g. `editor.html` head title, the preview pane heading). Reusing an existing translated msgid is fine — this task only needs to guarantee each of the five is translated in PL, adding entries only for those not already present.

- [ ] **Step 1: Write the failing test**

Create `tests/test_i18n_editor_view_toggle.py`:

```python
import pytest
from django.utils import translation

# Exact msgids introduced by the view toggle (Task 1). Keep character-for-character
# in sync with the {% trans %} strings in editor.html.
VIEW_TOGGLE_MSGIDS = [
    "View",
    "Editor view",
    "Editor",
    "Split",
    "Preview",
]


@pytest.mark.parametrize("msgid", VIEW_TOGGLE_MSGIDS)
def test_view_toggle_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        out = translation.gettext(msgid)
    assert out and out != msgid, f"view-toggle msgid not translated to PL: {msgid!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_i18n_editor_view_toggle.py -v`
Expected: FAIL for any of the new msgids not yet translated (e.g. `Split`, `View`, `Editor view`).

- [ ] **Step 3: Regenerate the PL catalog**

Run: `uv run python manage.py makemessages -l pl`

This adds the new msgids to `locale/pl/LC_MESSAGES/django.po`. Guard against the fuzzy-flag gotcha: `makemessages` may mark near-matches `#, fuzzy` — those must be resolved (translated + fuzzy flag removed), or `gettext` returns the msgid unchanged.

- [ ] **Step 4: Fill in the PL translations**

In `locale/pl/LC_MESSAGES/django.po`, set (add the entry if `makemessages` didn't, and remove any `#, fuzzy` line above these):

```po
msgid "View"
msgstr "Widok"

msgid "Editor view"
msgstr "Widok edytora"

msgid "Split"
msgstr "Podział"

msgid "Editor"
msgstr "Edytor"

msgid "Preview"
msgstr "Podgląd"
```

(If `Editor` / `Preview` already carry a PL translation elsewhere in the catalog, leave the existing entry — do not duplicate the msgid.)

- [ ] **Step 5: Compile the catalog**

Run: `uv run python manage.py compilemessages -l pl`
Expected: writes `locale/pl/LC_MESSAGES/django.mo` with no errors.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_i18n_editor_view_toggle.py -v`
Expected: PASS (5 parametrized cases).

- [ ] **Step 7: Verify the catalog has no obsolete/fuzzy regressions**

Run the repo's actual catalog-cleanliness guard — `test_po_catalog_clean` asserts
`"#, fuzzy" not in text` and `"#~" not in text` on the `.po` (the fallout Step 3
warns about). NOTE: `tests/test_i18n_catalog.py` is **not** this guard — it only
checks that the catalog page renders specific PL strings, so it would pass green
even with fuzzy/obsolete entries. Run:
`uv run pytest tests/test_i18n_auth.py::test_po_catalog_clean -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_i18n_editor_view_toggle.py
git commit -m "i18n(editor): PL translations for view-toggle strings"
```

---

## Definition of Done (controller-run, after all tasks)

- Full suite green: `uv run pytest -q` (excluding `-m e2e`, per repo convention), plus the focused e2e file `uv run pytest tests/test_e2e_editor_view_toggle.py -m e2e`.
- Lint clean: `uv run ruff check` and `uv run ruff format --check`.
- Visual QA (per "verify UI with screenshots"): Playwright screenshots, light + dark, at **~102rem** (wide — split two ~equal columns), **~80rem** (medium — editor narrower than the fixed preview, no overflow), and **~64rem** (narrow — split stacks), capturing each of the three modes (Editor / Split / Preview).
