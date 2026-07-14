# Per-paragraph text alignment in rich-text bodies — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-block Left / Center / Right alignment controls to the text, callout, and spoiler rich-text editors, stored as allowlisted `ta-*` CSS classes and rendered via existing global utilities.

**Architecture:** Alignment is stored as a single allowlisted class (`ta-left`/`ta-center`/`ta-right`) on the block element — never inline `style`. The contenteditable surface edits with inline `text-align` (what `execCommand` emits); two pure JS conversions (`styleToClass` on sync-out, `classToStyle` on load-in) bridge surface ↔ stored HTML. The server sanitizer (`sanitize_html`, nh3 `allowed_classes`) keeps only those classes on block tags.

**Tech Stack:** Django (server-rendered templates), vanilla JS (contenteditable + `document.execCommand`), nh3 (HTML sanitizer), Playwright (e2e), pytest.

## Global Constraints

- **Reuse existing assets — do NOT recreate them.** The align icons `#ed-align-left`, `#ed-align-center`, `#ed-align-right` already exist in the sprite (`templates/courses/manage/editor/editor.html`, used by the table editor). The CSS utilities `.ta-left`/`.ta-center`/`.ta-right { text-align: … }` already exist globally in `courses/static/courses/css/courses.css:708-710` (used by table cells). This feature reuses both; it adds **no** new icons and **no** new CSS rules.
  - **Scope caveat (supersedes the spec's `.el--text`-scoped CSS reasoning):** these utilities are *global*, not `.el--text`-scoped. The spec's §5 assumed a new `.el--text .ta-*` rule so the class would be inert on out-of-scope surfaces (quiz/interactive stems, which `sanitize_html` will now also permit the class on). Because the global `.ta-*` already exists (and is used by table cells), that inert-outside-scope property was never achievable under the `ta-*` name; a stem carrying `ta-center` renders centered. This is benign and accepted: no toolbar produces the class on out-of-scope surfaces (only the three in-scope toolbars get buttons), and if an author hand-types it, centering is a reasonable outcome. Do NOT add redundant `.el--text`-scoped rules — the global utilities already deliver the rendering.
- **Class vocabulary:** exactly `ta-left`, `ta-center`, `ta-right`. Block tags that may carry them: `p, div, h2, h3, h4, blockquote, li`.
- **Sanitizer:** use nh3's `allowed_classes` kwarg; do **NOT** add `class` to `ALLOWED_ATTRIBUTES` (that bypasses value restriction). Do not touch `sanitize_cell` / `sanitize_label`.
- **Scope:** only the three block-body elements' own inline toolbars (`_edit_text.html`, `_edit_callout.html`, `_edit_spoiler.html`). Do **NOT** edit the shared `_rte_toolbar.html` (quiz/interactive stems, out of scope).
- **Tooling:** bash `ruff`/`pytest`/`python`/`manage.py` are NOT on PATH — always prefix with `uv run` (e.g. `uv run pytest …`, `uv run python manage.py …`).
- **Tests:** never hardcode passwords — use `tests.factories.TEST_PASSWORD`. e2e tests are marked `@pytest.mark.e2e` and run with `-m e2e`; drive the REAL toolbar click, never `page.evaluate`.
- **Django comments:** `{# #}` must be single-line; use `{% comment %}` for multi-line.

---

### Task 1: Sanitizer allows `ta-*` alignment classes on block tags

**Files:**
- Modify: `courses/sanitize.py` (module-level constants + `sanitize_html`)
- Modify: `pyproject.toml:14` (nh3 floor)
- Test: `courses/tests/test_sanitize_align.py` (create)

**Interfaces:**
- Consumes: existing `sanitize_html(value)`, `sanitize_cell(value)`, `sanitize_label(value)` in `courses/sanitize.py`.
- Produces: `sanitize_html` that keeps `class="ta-left|ta-center|ta-right"` on `{p,div,h2,h3,h4,blockquote,li}` and strips everything else. No signature change.

- [ ] **Step 1: Write the failing test**

Create `courses/tests/test_sanitize_align.py`:

```python
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html
from courses.sanitize import sanitize_label

BLOCK_TAGS = ["p", "div", "h2", "h3", "h4", "blockquote", "li"]


def test_keeps_align_class_on_each_block_tag():
    for tag in BLOCK_TAGS:
        out = sanitize_html(f'<{tag} class="ta-center">x</{tag}>')
        assert 'class="ta-center"' in out, f"{tag} lost ta-center: {out!r}"


def test_keeps_ta_left_and_ta_right():
    assert 'class="ta-left"' in sanitize_html('<p class="ta-left">x</p>')
    assert 'class="ta-right"' in sanitize_html('<p class="ta-right">x</p>')


def test_reduces_combined_class_to_the_align_token():
    out = sanitize_html('<p class="ta-center foo">x</p>')
    assert "ta-center" in out
    assert "foo" not in out


def test_drops_unknown_class_value():
    assert "evil" not in sanitize_html('<p class="evil">x</p>')


def test_drops_align_class_on_non_block_tag():
    assert "ta-center" not in sanitize_html('<b class="ta-center">x</b>')


def test_cell_and_label_stay_class_free():
    assert "class" not in sanitize_cell('<b class="ta-center">x</b>')
    assert "ta-center" not in sanitize_label('<span class="ta-center">x</span>')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest courses/tests/test_sanitize_align.py -v`
Expected: FAIL — `test_keeps_align_class_on_each_block_tag` fails (current `sanitize_html` strips the class).

- [ ] **Step 3: Implement — add the allowlist and wire `allowed_classes`**

In `courses/sanitize.py`, add module-level constants immediately after `ALLOWED_URL_SCHEMES = {...}` (around line 37):

```python
# Horizontal-alignment utility classes permitted on block elements of the rich-text
# subset. Token-level allowlist via nh3's allowed_classes — `class` is deliberately
# NOT added to ALLOWED_ATTRIBUTES (that would allow arbitrary class values). Mirrors
# the global .ta-* utilities in courses.css (also used by table cells).
ALIGN_CLASS_VALUES = {"ta-left", "ta-center", "ta-right"}
ALIGN_CLASS_TAGS = {"p", "div", "h2", "h3", "h4", "blockquote", "li"}
ALLOWED_CLASSES = {tag: ALIGN_CLASS_VALUES for tag in ALIGN_CLASS_TAGS}
```

Then add `allowed_classes=ALLOWED_CLASSES,` to the `nh3.clean(...)` call inside `sanitize_html`:

```python
def sanitize_html(value):
    """Strip everything outside the safe subset. Idempotent on already-clean input."""
    return nh3.clean(
        value or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        allowed_classes=ALLOWED_CLASSES,
        link_rel=None,  # manage rel ourselves via ALLOWED_ATTRIBUTES
        url_schemes=ALLOWED_URL_SCHEMES,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest courses/tests/test_sanitize_align.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Bump the nh3 dependency floor**

The `allowed_classes` kwarg must be guaranteed by the declared floor (not just the lockfile). In `pyproject.toml:14`, change:

```
    "nh3>=0.2.18",
```
to:
```
    "nh3>=0.3.5",
```

(0.3.5 is the empirically-verified version; keeping the floor at/above it prevents a lock regeneration from resolving an nh3 whose `sanitize_html` would raise `TypeError` on the new kwarg.)

Then confirm nothing broke: `uv run pytest courses/tests/test_sanitize_align.py courses/tests/test_table_sanitize.py tests/test_sanitize_gallery.py -q`
Expected: PASS (align + existing cell/gallery sanitizer tests all green).

- [ ] **Step 6: Commit**

```bash
git add courses/sanitize.py courses/tests/test_sanitize_align.py pyproject.toml
git commit -m "feat(sanitize): allow ta-* alignment classes on block tags"
```

---

### Task 2: Alignment buttons in the three inline toolbars

**Files:**
- Modify: `templates/courses/manage/editor/_edit_text.html`
- Modify: `templates/courses/manage/editor/_edit_callout.html`
- Modify: `templates/courses/manage/editor/_edit_spoiler.html`
- Test: `tests/test_align_toolbar_markup.py` (create)

**Interfaces:**
- Consumes: existing sprite symbols `#ed-align-left/center/right`; existing `.rte-btn` / `.rte-sep` classes; the `[data-rte-toolbar]` click delegation in `text_toolbar.js` (Task 3 adds the `data-cmd` handlers).
- Produces: three buttons `data-cmd="alignleft|aligncenter|alignright"` in each of the three toolbars, after the Code button, behind a `rte-sep`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_align_toolbar_markup.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDITORS = ROOT / "templates/courses/manage/editor"
IN_SCOPE = ["_edit_text.html", "_edit_callout.html", "_edit_spoiler.html"]


def test_align_buttons_present_in_each_in_scope_toolbar():
    for name in IN_SCOPE:
        html = (EDITORS / name).read_text(encoding="utf-8")
        for cmd, icon in [
            ("alignleft", "#ed-align-left"),
            ("aligncenter", "#ed-align-center"),
            ("alignright", "#ed-align-right"),
        ]:
            assert f'data-cmd="{cmd}"' in html, f"{name} missing {cmd}"
            assert icon in html, f"{name} missing {icon}"


def test_shared_partial_left_untouched():
    shared = (EDITORS / "_rte_toolbar.html").read_text(encoding="utf-8")
    assert "aligncenter" not in shared, "shared toolbar must NOT get align buttons"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_align_toolbar_markup.py -v`
Expected: FAIL — `test_align_buttons_present_in_each_in_scope_toolbar` (buttons absent).

- [ ] **Step 3: Add the alignment group to each of the three toolbars**

In each of `_edit_text.html`, `_edit_callout.html`, `_edit_spoiler.html`, find the Code button line:

```html
    <button type="button" class="rte-btn" data-cmd="code" title="{% trans 'Code' %}" aria-label="{% trans 'Code' %}"><svg class="ic"><use href="#ed-code"/></svg></button>
```

and insert immediately AFTER it (still inside the `<div class="rte-toolbar" data-rte-toolbar>`):

```html
    <span class="rte-sep"></span>
    <button type="button" class="rte-btn" data-cmd="alignleft" title="{% trans 'Align left' %}" aria-label="{% trans 'Align left' %}"><svg class="ic"><use href="#ed-align-left"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="aligncenter" title="{% trans 'Align center' %}" aria-label="{% trans 'Align center' %}"><svg class="ic"><use href="#ed-align-center"/></svg></button>
    <button type="button" class="rte-btn" data-cmd="alignright" title="{% trans 'Align right' %}" aria-label="{% trans 'Align right' %}"><svg class="ic"><use href="#ed-align-right"/></svg></button>
```

Note: `_edit_callout.html`'s toolbar has no math button and its Code button is the last toolbar control (line ~29); `_edit_text.html` Code button is line ~16; `_edit_spoiler.html` Code button is line ~23. In all three, the insertion point is the same "immediately after the Code button" position.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_align_toolbar_markup.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add templates/courses/manage/editor/_edit_text.html templates/courses/manage/editor/_edit_callout.html templates/courses/manage/editor/_edit_spoiler.html tests/test_align_toolbar_markup.py
git commit -m "feat(editor): add align buttons to text/callout/spoiler toolbars"
```

---

### Task 3: RTE JS — alignment commands, style↔class conversion, active-state

**Files:**
- Modify: `courses/static/courses/js/text_toolbar.js`

**Interfaces:**
- Consumes: existing `exec(cmd, value)`, `applyCmd(cmd, surface)`, `wireRte(textarea)`, `refreshActive()` in `text_toolbar.js`; the `data-cmd="alignleft|aligncenter|alignright"` buttons from Task 2; the `ta-*` classes from Task 1.
- Produces: alignment behavior — clicking an align button sets the current block's alignment; stored HTML uses `ta-*` classes; loaded content shows aligned in the surface; Center/Right buttons reflect active state.

There is no JS unit-test runner in this repo; this task is verified by `node --check` (syntax) here and end-to-end by Task 4's Playwright e2e. Make all four edits below, in `courses/static/courses/js/text_toolbar.js`.

- [ ] **Step 1: Add pure `styleToClass` / `classToStyle` converters**

Insert this helper and these two functions just after the `exec(...)` function (after line 13, before `applyCmd`):

```javascript
  // Toggle the persistent document-global styleWithCSS flag. MUST be a direct
  // execCommand call — the exec() wrapper does `value || null`, so exec("styleWithCSS",
  // false) would pass null, and any 3rd-arg other than the literal "false" turns
  // styleWithCSS ON. That inversion would break bold/italic/underline.
  function styleWithCss(on) {
    try { document.execCommand("styleWithCSS", false, on); } catch (e) { /* ignore */ }
  }

  // Surface speaks inline text-align (execCommand output); stored/submitted HTML
  // speaks ta-* classes (sanitizer-friendly). These bridge the two, both pure.
  function styleToClass(html) {
    var box = document.createElement("div");
    box.innerHTML = html;
    box.querySelectorAll("*").forEach(function (el) {
      var val = ((el.style && el.style.textAlign) || "").trim().toLowerCase();
      if (val === "left" || val === "center" || val === "right") {
        el.classList.remove("ta-left", "ta-center", "ta-right");
        el.classList.add("ta-" + val);
        el.style.textAlign = "";
        if (!el.getAttribute("style")) el.removeAttribute("style");
      }
    });
    return box.innerHTML;
  }

  function classToStyle(html) {
    var box = document.createElement("div");
    box.innerHTML = html;
    ["left", "center", "right"].forEach(function (v) {
      box.querySelectorAll(".ta-" + v).forEach(function (el) {
        el.style.textAlign = v;
        el.classList.remove("ta-" + v);
        if (!el.getAttribute("class")) el.removeAttribute("class");
      });
    });
    return box.innerHTML;
  }
```

- [ ] **Step 2: Add align cases + harden bold/italic/underline in `applyCmd`**

In `applyCmd`'s `switch`, change the bold/italic/underline cases to reset `styleWithCSS` first, and add the three align cases. Replace:

```javascript
      case "bold": exec("bold"); break;
      case "italic": exec("italic"); break;
      case "underline": exec("underline"); break;
```

with:

```javascript
      // Reset styleWithCSS so these emit <b>/<i>/<u> (sanitizer-kept), never
      // <span style> (stripped) — in case a prior align click left the flag true.
      case "bold": styleWithCss(false); exec("bold"); break;
      case "italic": styleWithCss(false); exec("italic"); break;
      case "underline": styleWithCss(false); exec("underline"); break;
      case "alignleft": case "aligncenter": case "alignright": {
        var JUSTIFY = { alignleft: "justifyLeft", aligncenter: "justifyCenter", alignright: "justifyRight" };
        styleWithCss(true);   // force inline text-align (not FF's align attr)
        exec(JUSTIFY[cmd]);
        styleWithCss(false);  // MUST reset — persistent document-global flag
        break;
      }
```

Note: styleWithCSS is toggled via the dedicated `styleWithCss(on)` helper (Step 1), which calls `document.execCommand("styleWithCSS", false, on)` **directly**. Do NOT route it through `exec()` — `exec` does `document.execCommand(cmd, false, value || null)`, so a `false` arg becomes `null`, and any 3rd-arg other than the literal `"false"` turns styleWithCSS ON, silently inverting the reset.

- [ ] **Step 3: Wire converters + cross-browser Enter into `wireRte`**

In `wireRte`, (a) make Enter produce block elements cross-browser, and (b) route load/sync through the converters.

Change the surface-init line:

```javascript
    surface.innerHTML = textarea.value;
```
to:
```javascript
    // Enter must yield a <div> block on BOTH Chrome and Firefox (FF defaults to <br>),
    // so per-block alignment is usable cross-browser.
    try { document.execCommand("defaultParagraphSeparator", false, "div"); } catch (e) { /* ignore */ }
    surface.innerHTML = classToStyle(textarea.value);
```

Change the `sync` function:

```javascript
    function sync() { textarea.value = surface.innerHTML; }
```
to:
```javascript
    function sync() { textarea.value = styleToClass(surface.innerHTML); }
```

- [ ] **Step 4: Extend `refreshActive` for alignment active-state**

At the end of `refreshActive`, after the existing `toolbar.querySelectorAll(...).forEach(...)` block (before the closing `}` of the function), append:

```javascript
      // Alignment buttons: data-cmd != queryCommandState name, and Left is derived,
      // so they can't join the flat bold/italic map above.
      var center = false, right = false;
      try { center = document.queryCommandState("justifyCenter"); } catch (e) { center = false; }
      try { right = document.queryCommandState("justifyRight"); } catch (e) { right = false; }
      var cBtn = toolbar.querySelector('[data-cmd="aligncenter"]');
      var rBtn = toolbar.querySelector('[data-cmd="alignright"]');
      var lBtn = toolbar.querySelector('[data-cmd="alignleft"]');
      if (cBtn) cBtn.classList.toggle("is-on", !!center);
      if (rBtn) rBtn.classList.toggle("is-on", !!right);
      if (lBtn) lBtn.classList.toggle("is-on", !center && !right);
```

- [ ] **Step 5: Verify syntax**

Run: `node --check courses/static/courses/js/text_toolbar.js`
Expected: no output, exit 0 (valid JS). (If `node` is unavailable, this is verified instead by Task 4's e2e; do not block on node's absence.)

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/text_toolbar.js
git commit -m "feat(rte): per-block alignment (style<->class, styleWithCSS reset, active-state)"
```

---

### Task 4: End-to-end tests (alignment, load round-trip, formatting-survives)

**Files:**
- Test: `tests/test_e2e_alignment.py` (create)

**Interfaces:**
- Consumes: helpers `_make_pa_user`, `_login`, `_seed_course_and_unit`, `_editor_url`, `_add_element` from `tests/test_e2e_editor.py`; `tests.factories.add_element`; `courses.models.TextElement`.
- Produces: three e2e tests proving the full click→sanitize→store→render path.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_e2e_alignment.py`:

```python
"""Playwright e2e for per-block text alignment in the text-element RTE (the
flagship/motivating case). Marked e2e (run with `-m e2e`)."""

import os

import pytest

from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _latest_text_body():
    from courses.models import TextElement

    el = TextElement.objects.order_by("-id").first()
    return el.body if el else ""


@pytest.mark.django_db(transaction=True)
def test_center_second_block_only(page, live_server):
    """Two Enter-separated blocks; centering the 2nd stores ta-center on it alone,
    and the preview renders that class."""
    _make_pa_user("al_center")
    _login(page, live_server, "al_center")
    unit = _seed_course_and_unit("al_center", slug="al-center")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("Skoro")
    page.keyboard.press("Enter")
    page.keyboard.type("Rownanie")  # caret now sits in the second block
    page.locator('[data-edit-slot] [data-cmd="aligncenter"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()

    preview = page.locator('[data-scope="preview"]')
    preview.get_by_text("Rownanie").wait_for()

    body = _latest_text_body()
    assert body.count("ta-center") == 1, f"expected exactly one ta-center: {body!r}"
    assert "Rownanie" in body and "Skoro" in body
    # The rendered preview carries the class (sanitizer kept it AND it rendered).
    assert "ta-center" in preview.inner_html()


@pytest.mark.django_db(transaction=True)
def test_load_round_trip_preserves_ta_center(page, live_server):
    """A pre-stored ta-center block loads into the editor (classToStyle), and a
    re-save preserves exactly one ta-center (no dup, no leftover inline style)."""
    from courses.models import TextElement
    from tests.factories import add_element

    _make_pa_user("al_rt")
    _login(page, live_server, "al_rt")
    unit = _seed_course_and_unit("al_rt", slug="al-rt")
    el = TextElement.objects.create(body='<div class="ta-center">Centered</div>')
    add_element(unit, el)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')

    # Open the row's editor (the real edit control is .el-act-edit in
    # _element_row.html), tweak, and save.
    page.locator(".el-row").first.locator(".el-act-edit").first.click()
    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("!")  # unrelated edit
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_timeout(300)

    el.refresh_from_db()
    assert el.body.count("ta-center") == 1, f"round-trip corrupted: {el.body!r}"
    assert "text-align" not in el.body, f"leftover inline style: {el.body!r}"


@pytest.mark.django_db(transaction=True)
def test_bold_after_align_survives_sanitize(page, live_server):
    """Bolding AFTER an align click must still emit <b>/<strong> (styleWithCSS reset),
    so bold survives sanitization on save."""
    _make_pa_user("al_bold")
    _login(page, live_server, "al_bold")
    unit = _seed_course_and_unit("al_bold", slug="al-bold")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("BoldMe")
    page.locator('[data-edit-slot] [data-cmd="aligncenter"]').click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="bold"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.locator('[data-scope="preview"]').get_by_text("BoldMe").wait_for()

    body = _latest_text_body()
    assert ("<b>" in body) or ("<strong>" in body), f"bold lost: {body!r}"
    assert "<span" not in body, f"styleWithCSS leaked a span: {body!r}"
```

- [ ] **Step 2: Run tests to verify they fail (or gate correctly)**

Run: `uv run pytest tests/test_e2e_alignment.py -m e2e -v`
Expected: the three tests run against a real browser. Before Tasks 1-3 exist they would fail; run this only after Tasks 1-3 are committed, at which point: PASS. (The round-trip test opens the row editor via `.el-act-edit` — the control in `_element_row.html`; if a row renders more than one such button, `.first` selects the visible one. The other two tests do not depend on it.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e_alignment.py
git commit -m "test(e2e): per-block alignment, load round-trip, bold-after-align"
```

---

### Task 5: Render + CSS-presence tests

**Files:**
- Test: `tests/test_align_render.py` (create)

**Interfaces:**
- Consumes: `sanitize_html` (Task 1); `courses.models.TextElement`/`CalloutElement`/`SpoilerElement`; existing `.ta-*` CSS in `courses.css`.
- Produces: Python tests proving a stored `ta-center` block survives the model save-sanitize and that the global `.ta-*` utilities exist.

- [ ] **Step 1: Write the failing test**

Create `tests/test_align_render.py`:

```python
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "courses/static/courses/css/courses.css"


def test_global_align_utilities_exist():
    css = CSS.read_text(encoding="utf-8")
    for cls in [".ta-left", ".ta-center", ".ta-right"]:
        assert cls in css, f"missing alignment utility: {cls}"


@pytest.mark.django_db
def test_align_class_survives_model_save():
    from courses.models import CalloutElement
    from courses.models import SpoilerElement
    from courses.models import TextElement

    body = '<div class="ta-center">Centered</div>'
    for model in (TextElement, SpoilerElement, CalloutElement):
        el = model.objects.create(body=body)
        el.refresh_from_db()
        assert 'class="ta-center"' in el.body, f"{model.__name__}: {el.body!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_align_render.py -v`
Expected: `test_global_align_utilities_exist` PASSES (classes already exist); `test_align_class_survives_model_save` FAILS if run before Task 1 is applied (sanitizer strips the class). If Task 1 is already committed, it PASSES — that is acceptable (this task documents/guards the behavior). If both already pass, add a temporary assertion inversion to confirm the test executes, then revert.

- [ ] **Step 3: Implement**

No implementation code — the behavior is delivered by Task 1 (sanitizer) and the pre-existing CSS. This task only adds the guarding tests. If `test_align_class_survives_model_save` fails, the fault is in Task 1; fix there.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_align_render.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add tests/test_align_render.py
git commit -m "test(align): render + CSS-presence guards for ta-* alignment"
```

---

### Task 6: Polish translations for the alignment strings

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (regenerated + PL msgstrs)
- Modify: `locale/pl/LC_MESSAGES/django.mo` (compiled)
- Test: `tests/test_align_i18n.py` (create)

**Interfaces:**
- Consumes: the three source strings `"Align left"`, `"Align center"`, `"Align right"` introduced by Task 2's `{% trans %}` tags.
- Produces: filled, non-fuzzy Polish translations, compiled into the catalog.

- [ ] **Step 1: Write the failing test**

Create `tests/test_align_i18n.py`:

```python
from django.utils import translation


def test_polish_alignment_strings():
    cases = {
        "Align left": "Wyrównaj do lewej",
        "Align center": "Wyśrodkuj",
        "Align right": "Wyrównaj do prawej",
    }
    with translation.override("pl"):
        for src, expected in cases.items():
            assert translation.gettext(src) == expected, src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_align_i18n.py -v`
Expected: FAIL — strings untranslated (gettext returns the English source).

- [ ] **Step 3: Extract messages**

Run: `uv run python manage.py makemessages -l pl`
This adds the three new `msgid`s to `locale/pl/LC_MESSAGES/django.po` (empty `msgstr`, possibly `#, fuzzy` if near a prior string).

- [ ] **Step 4: Fill the Polish translations and clear fuzzy flags**

In `locale/pl/LC_MESSAGES/django.po`, set the three entries (and remove any `#, fuzzy` line directly above them — a fuzzy entry is dropped from the compiled `.mo`):

```po
msgid "Align left"
msgstr "Wyrównaj do lewej"

msgid "Align center"
msgstr "Wyśrodkuj"

msgid "Align right"
msgstr "Wyrównaj do prawej"
```

- [ ] **Step 5: Compile and verify**

Run: `uv run python manage.py compilemessages -l pl`
Then: `uv run pytest tests/test_align_i18n.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo tests/test_align_i18n.py
git commit -m "i18n(align): Polish translations for alignment buttons"
```

---

## Self-Review

**Spec coverage:**
- Sanitizer `allowed_classes` on block tags + dependency floor → Task 1. ✓
- RTE JS (defaultParagraphSeparator, align cases, styleWithCSS reset, styleToClass/classToStyle, single-class invariant, refreshActive) → Task 3. ✓
- Toolbars (3 in-scope, shared partial untouched, placement after Code behind rte-sep) → Task 2. ✓
- Icons → reused existing `#ed-align-*` (Global Constraints + Task 2); no task needed. ✓
- CSS `.ta-*` → reused existing global utilities (Global Constraints + Task 5 guard); no new rules. ✓
- i18n (EN source via Task 2 `{% trans %}`; PL + fuzzy-clear + compile) → Task 6. ✓
- Testing §1 sanitizer → Task 1; §2 formatting-survives → Task 4; §3 render → Task 5; §4 CSS presence → Task 5; §5 e2e motivating case → Task 4; §6 load round-trip → Task 4; §7 i18n catalog → Task 6. ✓
- Scope carve-out (quiz stems, cells) → Global Constraints + Task 2's `test_shared_partial_left_untouched`. ✓

**Placeholder scan:** No TBD/TODO; every code step shows real code and exact `uv run` commands. ✓

**Type/name consistency:** `styleToClass`/`classToStyle` names match spec and are used consistently in Task 3; `ta-left/ta-center/ta-right` and block-tag set `{p,div,h2,h3,h4,blockquote,li}` identical across Tasks 1, 3, 5; `data-cmd` values `alignleft/aligncenter/alignright` consistent across Tasks 2, 3, 4. ✓

**Note on spec divergence (icons/CSS):** the spec's components §4 (icons) and §5 (CSS) said "add"; planning discovered both assets already exist and are reused instead. This is a strict simplification (less code, same behavior), reflected in Global Constraints and Task 5's presence guard.
