# Instant add/remove of repeatable editor rows — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make repeatable rows in the element editor appear and disappear immediately — fixing the match-pairs `＋ Add pair` button that has never had a handler, and giving Choose & confirm add/remove controls it has never had.

**Architecture:** Two new client-side modules. `formset_rows.js` drives any Django inline formset by data attributes (add clones a `<template>`; remove ticks `DELETE` and sets `row.hidden`, never detaching and never decrementing `TOTAL_FORMS`). `switchgate_editor.js` drives switchgate's *positional* option list (remove must detach and renumber the radio index). Both use document-level delegation plus an idempotent exported init pass, matching `switchgrid_editor.js`. No application Python changes.

**Tech Stack:** Django templates + inline formsets, vanilla ES5-style IIFE JavaScript (no build step), plain CSS with custom properties, pytest + pytest-django, Playwright for e2e.

## Global Constraints

- **No application Python is modified.** The only `.py` files touched are tests. No model change, no migration, **no `FORMAT_VERSION` bump**.
- **Never detach a formset row and never decrement `TOTAL_FORMS`** (module 1). Django validates forms `0 … TOTAL_FORMS-1`; a gap makes a persisted row lose its `id` field.
- **Switchgate rows MUST be detached** (module 2) — a hidden input still submits and `clean()` rejects interior blanks.
- **Every new control renders `type="button"`** — a bare `<button>` in the editor form defaults to `submit`.
- **`focus()` is always `focus({ preventScroll: true })`.** On the **add** path it is preceded by `window.libliAlignTopInPane(row)` — the new row may be below the fold. On the **remove** path focus moves without aligning: the surviving neighbour is already on screen, and scrolling after a deletion is disorienting. `scrollIntoView` is forbidden in both modules.
- **Every `hidden` element whose class sets `display` needs an explicit `[hidden] { display: none }` guard.**
- **Init passes must be idempotent** and must accept *either* an ancestor node or the wrapper itself (`root.matches(SEL) ? [root] : root.querySelectorAll(SEL)`).
- **Every new e2e file uses this repo's Playwright harness**, copied from `tests/test_e2e_switchgate.py:33-41`. Without it there is no server URL and the server thread cannot see fixture data:

```python
pytestmark = pytest.mark.e2e          # NOT [django_db, e2e] — django_db goes per-test

@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield

@pytest.mark.django_db(transaction=True)   # the server thread must see the fixtures
def test_x(page, live_server, ...):        # live_server provides the base URL
```

- **The save gesture is `page.locator("[data-edit-slot] button[type='submit']").click()`** (`tests/test_e2e_questions.py:184`). There is no `data-el-save` attribute in this repo — do not invent one.
- **The preview pane is `[data-scope="preview"]`** (`_preview.html:2`), used by `tests/test_e2e_questions.py:186`. There is no `data-preview` attribute — only unrelated `data-preview-el` / `-logo` / `-name`.
- **Never `wait_for_load_state("networkidle")` after a save.** Saving posts via `postFragment` and swaps the `[data-scope]` panes — there is no navigation, so `networkidle` is a timing heuristic. Wait on a concrete selector instead.
- **A post-save wait must target a node the swap *introduces*, not the pane that hosts it.** `[data-scope="preview"]` exists before the save, so waiting on it returns immediately and gives no synchronisation at all. Wait on the new content (`[data-scope="preview"] [data-question]`) on success, and on `[data-edit-slot] .field-error` when the save is expected to fail with a 422.
- **Every editor-opener fixture has one contract:** `opener(page, live_server, **kwargs) -> element`. It logs in, seeds the element, navigates, opens its edit form, and returns the **model instance** (so tests can `refresh_from_db()`). It never returns the page.
- **Shared e2e/test helpers live in `tests/helpers_editor_rows.py`** (created in Task 3 Step 0). Module-level helper *functions* cannot be pytest fixtures — a fixture is only injectable via a test signature.
- **Translated strings come from server-rendered data attributes**, with a hard-coded English fallback + `console.warn` when absent.
- **Start the test-DB container before any pytest run**, or the suite appears to hang for ~4m21s.
- **Playwright auto-dismisses `confirm`.** Every test that removes a *non-blank* row needs an explicit `dialog` handler, or it takes the cancel path and fails against a correct build.
- **Run `uv run ruff format .` last**, after every other edit. Tooling is `uv run <tool>`; `-m e2e` is mandatory for e2e or they silently deselect.

---

### Task 1: CSS guards and the stylesheet guard test

The `[hidden]` attribute does nothing against these classes — each sets an author-level `display` at equal specificity, beating the UA rule. This task lands all eleven CSS rules the rest of the plan depends on, plus the test that stops any of them being deleted.

**Files:**
- Modify: `courses/static/courses/css/editor.css` (add rules near `:141-165`)
- Modify: `courses/static/courses/css/courses.css` (add rules near `:1990-2050`)
- Modify: `core/static/core/css/app.css` (add rules after `:1478`)
- Test: `tests/test_editor_row_css_guards.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: the CSS contract every later task relies on — `[hidden]` actually hides rows, `__del` labels and switchgate's `×`; `[data-fsrows], [data-sgate]` are `display: contents`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_editor_row_css_guards.py`:

```python
"""The [hidden] attribute is inert against any class that sets `display` at equal
specificity, and this repo has shipped that bug at least five times (see the guards
at core/static/core/css/app.css:42, :185, :546, :1009, :1191). Every rule below is
load-bearing for the editor's instant add/remove; deleting one is a silent visual
regression, so each is asserted individually."""

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
EDITOR_CSS = BASE / "courses" / "static" / "courses" / "css" / "editor.css"
COURSES_CSS = BASE / "courses" / "static" / "courses" / "css" / "courses.css"
APP_CSS = BASE / "core" / "static" / "core" / "css" / "app.css"

def _has_rule(css: str, selector: str) -> bool:
    """True if `selector` heads a rule declaring display:none.

    The selector may appear anywhere in a comma-separated list, so we allow any
    run of further selector characters between it and the `{`. A naive
    `re.escape(selector) + r"\\s*\\{"` matches only the LAST selector in a group —
    `.pair-row[hidden], .choice-row[hidden] { ... }` would report the first as
    missing and the assertion would be red against correct CSS.
    """
    pattern = re.escape(selector) + r"[^{}]*\{[^}]*display:\s*none[^}]*\}"
    return re.search(pattern, css) is not None


def test_row_hidden_guards_in_editor_css():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for selector in (".pair-row[hidden]", ".choice-row[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from editor.css"


def test_del_label_hidden_guards_in_editor_css():
    css = EDITOR_CSS.read_text(encoding="utf-8")
    for selector in (".pair-row__del[hidden]", ".choice-row__del[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from editor.css"


def test_row_hidden_guards_in_courses_css():
    css = COURSES_CSS.read_text(encoding="utf-8")
    for selector in (".stepper-row[hidden]", ".markdone-row[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from courses.css"


def test_del_label_hidden_guards_in_courses_css():
    css = COURSES_CSS.read_text(encoding="utf-8")
    for selector in (".stepper-row__del[hidden]", ".markdone-row__del[hidden]"):
        assert _has_rule(css, selector), f"{selector} guard missing from courses.css"


def test_wrapper_is_display_contents():
    """Without this the wrapper becomes a single grid item and .el-editor's
    --space-3 gap between the list and the add button collapses in all five
    editors, with nothing else to catch it."""
    css = EDITOR_CSS.read_text(encoding="utf-8")
    assert re.search(
        r"\[data-fsrows\][^{]*\[data-sgate\]\s*\{[^}]*display:\s*contents", css
    ), "[data-fsrows], [data-sgate] { display: contents } missing from editor.css"


def test_switchgate_remove_style_twin():
    """.el-editor__remove is entirely switchgrid-scoped (app.css:1452-1478), so a
    bare class in a switchgate row inherits nothing and renders a raw UA button."""
    css = APP_CSS.read_text(encoding="utf-8")
    match = re.search(
        r"\.el-editor--switchgate\s+\.el-editor__remove\s*\{([^}]*)\}", css
    )
    assert match, "switchgate .el-editor__remove style twin missing from app.css"
    # Strip comments first: otherwise a stub body of `/* ...display: inline-grid... */`
    # satisfies every assertion below and the test cannot tell a placeholder from
    # the finished rule.
    block = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
    assert "inline-grid" in block, "style twin must set display: inline-grid"
    assert "flex:" in block, "style twin must set flex: 0 0 auto or the x shrinks"
    assert "width:" in block, "style twin must set an explicit size"


def test_switchgate_remove_hidden_guard():
    css = APP_CSS.read_text(encoding="utf-8")
    assert _has_rule(css, ".el-editor--switchgate .el-editor__remove[hidden]"), (
        "switchgate .el-editor__remove[hidden] guard missing from app.css"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_editor_row_css_guards.py -v
```

Expected: 7 FAILED, each naming the missing selector.

- [ ] **Step 3: Add the guards to `editor.css`**

Insert immediately after the `.choice-row__del` block (around `:165`):

```css
/* [hidden] is inert against the display: flex/grid these rows and labels set at
   equal specificity. formset_rows.js hides a removed row and swaps the no-JS
   DELETE label for the JS remove button, so both need an explicit guard. */
.pair-row[hidden], .choice-row[hidden] { display: none; }
.pair-row__del[hidden], .choice-row__del[hidden] { display: none; }

/* The add/remove wrapper must not become a grid item itself: .el-editor is a grid
   with gap var(--space-3), and the list and the add button are separate items. */
[data-fsrows], [data-sgate] { display: contents; }
```

- [ ] **Step 4: Add the guards to `courses.css`**

Insert immediately after the `.markdone-row__del` rule (around `:2050`):

```css
/* See editor.css: [hidden] is inert against these display: inline-flex rules. */
.stepper-row[hidden], .markdone-row[hidden] { display: none; }
.stepper-row__del[hidden], .markdone-row__del[hidden] { display: none; }
```

- [ ] **Step 5: Add the switchgate twins to `app.css`**

Insert after the switchgrid `.el-editor__remove:focus-visible` block (after `:1478`). Copy the declarations from the `.el-editor--switchgrid .el-editor__remove` block at `:1452` verbatim, including `flex: 0 0 auto`:

**Open `app.css:1452-1478` and copy each of the four blocks verbatim, changing only the
`--switchgrid` scope to `--switchgate`.** Do not paste a stub with a "copy the rest" comment: a
comment body still satisfies a naive substring assertion, so the guard test would pass on a `×` that
renders with no size and no `inline-grid`. The result should look like this — fill each `…` from the
source block rather than from memory:

```css
/* Switchgate reuses switchgrid's x component, but every rule for it is scoped to
   .el-editor--switchgrid, so a bare class inherits nothing. Duplicated under a
   scope rather than promoted to an unscoped rule: promoting would restyle
   switchgrid as a side effect, and an unscoped .el-editor__remove[hidden] ties on
   specificity with the block above, leaving the outcome to source order. */
.el-editor--switchgate .el-editor__remove {
  flex: 0 0 auto;
  width: …; height: …;              /* from :1452 */
  display: inline-grid;
  place-items: center;
  …                                  /* every remaining declaration from :1452-1468 */
}
/* inline-grid overrides the [hidden] attribute, so hide explicitly (JS toggles it) */
.el-editor--switchgate .el-editor__remove[hidden] { display: none; }
.el-editor--switchgate .el-editor__remove:hover { … }           /* from :1470-1474 */
.el-editor--switchgate .el-editor__remove:focus-visible { … }   /* from :1475-1478 */
```

Verify by opening a switchgate editor and a switchgrid editor side by side: the two `×` controls must
be visually identical.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/test_editor_row_css_guards.py -v
```

Expected: 7 PASSED.

- [ ] **Step 7: Falsify the guard**

Delete the **whole** `.stepper-row[hidden], .markdone-row[hidden] { display: none; }` rule from
`courses.css`, re-run, confirm `test_row_hidden_guards_in_courses_css` FAILS naming both selectors,
then restore it.

Deleting only the `.stepper-row[hidden]` *selector* from the group is the wrong mutant: it leaves
`.markdone-row[hidden] { display: none; }` behind, and the point of this falsification is that
`_has_rule` finds a selector **anywhere** in a comma-separated list. Run that variant too and confirm
it also fails — that is what proves the helper is not silently matching only the last selector in
each group.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/css/editor.css courses/static/courses/css/courses.css core/static/core/css/app.css tests/test_editor_row_css_guards.py
git commit -m "feat(editor): add [hidden] guards and display:contents for row wrappers"
```

---

### Task 2: `formset_rows.js` and its page wiring

Lands the module and loads it, with no template consuming it yet. Deliverable: the module exists, is served, and the scroll-invariant roster covers it.

**Files:**
- Create: `courses/static/courses/js/formset_rows.js`
- Modify: `templates/courses/manage/editor/editor.html` (add a `<script>` + `{% comment %}`)
- Modify: `courses/static/courses/js/editor.js:125` (add the post-swap init call)
- Modify: `tests/test_editor_js_scroll_invariants.py:24-40`
- Test: `tests/test_formset_rows_assets.py` (create)

**Ordering is load-bearing:** the init call must land *here*, not in Task 4. Every JS-only control
renders with a bare `hidden` attribute and only the init pass reveals it, and the editor form arrives
through a **fragment swap** (`editor.js:110-135`), not on `DOMContentLoaded`. Without the post-swap
call, Task 3's e2e would click an element that is still `hidden` and fail Playwright actionability —
and the `{% comment %}` added in Step 4 would describe wiring that does not yet exist.

**Interfaces:**
- Consumes: the CSS contract from Task 1.
- Produces: `window.libliInitFormsetRows(root)` — accepts an ancestor **or** a `[data-fsrows]` wrapper; idempotent. Delegated `click` handlers for `[data-fsrows-add]` and `[data-fsrow-remove]`, and a delegated `input` handler for the max recompute. Markup contract: `data-fsrows` (prefix), `-confirm`, `-list`, `-min`, `-max`, `-hint`, `-atmin`, `-atcap`, `-add`, `-template`, and per row `data-fsrow-item`, `data-fsrow-del`, `data-fsrow-remove`.

- [ ] **Step 1: Write the failing asset test**

Create `tests/test_formset_rows_assets.py`:

```python
import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_formset_rows_js_exports():
    src = open(finders.find("courses/js/formset_rows.js"), encoding="utf-8").read()
    assert "window.libliInitFormsetRows" in src
    assert "__prefix__" in src
    # The module is prefix-agnostic: it must never hardcode one formset's prefix.
    assert "steps-TOTAL_FORMS" not in src


def test_editor_page_loads_formset_rows_js(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert b"courses/js/formset_rows.js" in resp.content
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_formset_rows_assets.py -v
```

Expected: FAIL — `finders.find` returns `None`, `open(None)` raises `TypeError`.

- [ ] **Step 3: Create `courses/static/courses/js/formset_rows.js`**

```js
/* Generic add/remove for Django inline formsets, driven entirely by data
   attributes so no per-element JS is needed. Sibling module: switchgate_editor.js
   (a positional list, NOT a formset — it detaches rows; this one never does).

   Contract on the wrapper: data-fsrows="<prefix>", -confirm, -list, -min, -max,
   -hint, -atmin, -atcap, -add, -template. Per row: data-fsrow-item,
   data-fsrow-del, data-fsrow-remove.

   Delegated at document level (like switchgrid_editor.js) so fragment swaps need
   no re-wiring; the exported init pass exists for the progressive-enhancement
   reveal and the 422 reconciliation, which delegation cannot do. */
(function () {
  "use strict";
  var WRAP = "[data-fsrows]";
  var FALLBACK_CONFIRM = "Remove this row?";

  function wrappers(root) {
    var scope = root || document;
    // querySelectorAll finds DESCENDANTS only; addChoiceRow hands us the wrapper
    // itself while editor.js hands us an ancestor. Mirrors syncChoiceFeedback.
    if (scope.matches && scope.matches(WRAP)) return [scope];
    return Array.prototype.slice.call(scope.querySelectorAll(WRAP));
  }

  function rowsOf(wrap) {
    var list = wrap.querySelector("[data-fsrows-list]");
    if (!list) return [];
    return Array.prototype.slice.call(list.querySelectorAll("[data-fsrow-item]"));
  }

  function visibleRows(wrap) {
    return rowsOf(wrap).filter(function (r) { return !r.hidden; });
  }

  function firstText(row) {
    return row.querySelector('input[type="text"]') || row.querySelector("textarea");
  }

  function filledCount(wrap) {
    return visibleRows(wrap).filter(function (r) {
      var f = firstText(r);
      return f && f.value.trim() !== "";
    }).length;
  }

  function isEmptyRow(row) {
    var fields = row.querySelectorAll('input[type="text"], textarea');
    for (var i = 0; i < fields.length; i++) {
      if (fields[i].value.trim() !== "") return false;
    }
    return true;
  }

  function totalInput(wrap) {
    var prefix = wrap.getAttribute("data-fsrows") || "";
    return wrap.querySelector('input[name="' + prefix + '-TOTAL_FORMS"]');
  }

  function delInput(row) { return row.querySelector('[name$="-DELETE"]'); }

  function num(wrap, attr, fallback) {
    var raw = wrap.getAttribute(attr);
    if (raw === null || raw === "") return fallback;
    var n = parseInt(raw, 10);
    return isNaN(n) ? fallback : n;
  }

  /* ---- job 3: bounds ---- */
  function recompute(wrap) {
    var min = num(wrap, "data-fsrows-min", 1);
    var max = num(wrap, "data-fsrows-max", Infinity);
    var visible = visibleRows(wrap);
    var atMin = visible.length <= min;
    // The max counts NON-BLANK rows, not rows: extra=1 means a 19-step stepper
    // renders 20 rows, and a row-based cap would disable Add at nineteen.
    var atMax = filledCount(wrap) >= max;

    visible.forEach(function (row) {
      var btn = row.querySelector("[data-fsrow-remove]");
      if (btn) btn.disabled = atMin;
    });

    var add = wrap.querySelector("[data-fsrows-add], [data-choice-add]");
    if (add) add.disabled = atMax;

    var hint = wrap.querySelector("[data-fsrows-hint]");
    if (!hint) return;
    var msg = atMax
      ? wrap.getAttribute("data-fsrows-atcap")
      : atMin
        ? wrap.getAttribute("data-fsrows-atmin")
        : null;
    // A greyed-out control with no explanation is its own small version of the
    // dead-button defect this module exists to fix.
    hint.textContent = msg || "";
    hint.hidden = !msg;
  }

  /* ---- init: three idempotent jobs ---- */
  function initOne(wrap) {
    // job 1 — swap the no-JS DELETE label for the JS-only buttons.
    // Array.prototype.forEach.call, not NodeList.forEach: matches editor.js and the
    // rest of this file's ES5 idiom.
    Array.prototype.forEach.call(wrap.querySelectorAll("[data-fsrow-item]"), function (row) {
      var label = row.querySelector("[data-fsrow-del]");
      if (!label) {
        if (window.console) console.warn("formset_rows: row without [data-fsrow-del]", row);
        return;
      }
      label.hidden = true;
      var btn = row.querySelector("[data-fsrow-remove]");
      if (btn) btn.hidden = false;
    });
    var add = wrap.querySelector("[data-fsrows-add], [data-choice-add]");
    if (add) add.hidden = false;

    // job 2 — reconcile a 422 re-render, but never below the minimum. Without the
    // floor, a no-JS author who ticked every row and hit a validation error comes
    // back to zero visible rows, no way to untick, and (for choice) nothing to
    // clone: an unrecoverable editor.
    var min = num(wrap, "data-fsrows-min", 1);
    var ticked = rowsOf(wrap).filter(function (r) {
      var d = delInput(r);
      return d && d.checked;
    });
    var keepVisible = rowsOf(wrap).length - ticked.length;
    ticked.forEach(function (row) {
      var d = delInput(row);
      if (keepVisible < min) {
        d.checked = false;   // state and appearance must never disagree
        keepVisible += 1;
        return;
      }
      row.hidden = true;
    });

    // job 3 — bounds.
    recompute(wrap);
  }

  function initFormsetRows(root) { wrappers(root).forEach(initOne); }

  /* ---- add ---- */
  function addRow(wrap) {
    var tmpl = wrap.querySelector("[data-fsrows-template]");
    var list = wrap.querySelector("[data-fsrows-list]");
    var total = totalInput(wrap);
    if (!tmpl || !list || !total) {
      // Loud, because a silent no-op here IS the reported defect.
      if (window.console) console.warn("formset_rows: add is not wired on", wrap);
      return;
    }
    var idx = parseInt(total.value, 10) || 0;
    var holder = document.createElement("div");
    holder.innerHTML = tmpl.innerHTML.replace(/__prefix__/g, String(idx)).trim();
    var row = holder.firstElementChild;
    if (!row) return;
    list.appendChild(row);
    total.value = String(idx + 1);
    // Mandatory: the blueprint copies the loop body verbatim, so the new row
    // arrives with a VISIBLE DELETE label and a HIDDEN remove button.
    initFormsetRows(wrap);
    if (window.libliAlignTopInPane) window.libliAlignTopInPane(row);
    var target = firstText(row);
    // preventScroll: the editor viewport is overflow:hidden, so a bare focus()
    // scrolls every ancestor scrollport and the author cannot scroll back.
    if (target) target.focus({ preventScroll: true });
  }

  /* ---- remove ---- */
  function focusable(el) { return el && !el.hidden && !el.disabled; }

  function removeRow(wrap, row) {
    var min = num(wrap, "data-fsrows-min", 1);
    if (visibleRows(wrap).length <= min) return;   // guard; button is disabled too
    if (!isEmptyRow(row)) {
      var msg = wrap.getAttribute("data-fsrows-confirm");
      if (!msg) {
        if (window.console) console.warn("formset_rows: no data-fsrows-confirm on", wrap);
        msg = FALLBACK_CONFIRM;   // never window.confirm(null) -> a dialog reading "null"
      }
      if (!window.confirm(msg)) return;
    }
    var d = delInput(row);
    if (!d) {
      if (window.console) console.warn("formset_rows: row has no DELETE input", row);
      return;
    }
    var after = visibleRows(wrap).filter(function (r) {
      return r !== row && row.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_FOLLOWING;
    });
    var before = visibleRows(wrap).filter(function (r) {
      return r !== row && row.compareDocumentPosition(r) & Node.DOCUMENT_POSITION_PRECEDING;
    });

    d.checked = true;
    row.hidden = true;
    recompute(wrap);   // AFTER hiding, so the disabled state reflects the new count

    // Focus would otherwise fall to <body>. Candidates must be FOCUSABLE, not
    // merely present: at the minimum boundary recompute() has just disabled every
    // remove button, and focus() on a disabled button is a silent no-op.
    var candidates = [];
    if (after[0]) candidates.push(after[0].querySelector("[data-fsrow-remove]"));
    if (before[before.length - 1]) {
      candidates.push(before[before.length - 1].querySelector("[data-fsrow-remove]"));
    }
    var near = after[0] || before[before.length - 1];
    if (near) candidates.push(firstText(near));   // always focusable; min >= 1
    for (var i = 0; i < candidates.length; i++) {
      if (focusable(candidates[i])) {
        candidates[i].focus({ preventScroll: true });
        return;
      }
    }
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;   // non-Element target (synthetic dispatch)
    var add = e.target.closest("[data-fsrows-add]");
    if (add) {
      var w = add.closest(WRAP);
      if (w) addRow(w);
      return;
    }
    var rm = e.target.closest("[data-fsrow-remove]");
    if (rm) {
      var wrap = rm.closest(WRAP);
      var row = rm.closest("[data-fsrow-item]");
      if (wrap && row) removeRow(wrap, row);
    }
  });

  // The max counts non-blank rows, so typing can cross it.
  document.addEventListener("input", function (e) {
    var wrap = e.target.closest && e.target.closest(WRAP);
    if (wrap) recompute(wrap);
  });

  window.libliInitFormsetRows = initFormsetRows;
  document.addEventListener("DOMContentLoaded", function () {
    initFormsetRows(document);
  });
})();
```

- [ ] **Step 4: Wire it into `editor.html`**

Add near the other editor modules (keep the repo's comment convention):

```html
  {% comment %}Generic inline-formset row add/remove (match pairs, stepper,
  checklist, choice removal). Delegated at document level; editor.js re-runs
  window.libliInitFormsetRows over the pane after each fragment swap for the
  progressive-enhancement reveal and the 422 reconciliation.{% endcomment %}
  <script src="{% static 'courses/js/formset_rows.js' %}" defer></script>
```

- [ ] **Step 4b: Add the post-swap init call**

In `courses/static/courses/js/editor.js`, immediately after the existing init block at `:125-126`
(leave the two retired calls alone — Task 4 removes them):

```js
    if (editorPane && window.libliInitFormsetRows) window.libliInitFormsetRows(editorPane);
```

The `libliInitSwitchGateEditor` line is added in Task 6, when that module exists.

- [ ] **Step 5: Add `formset_rows.js` to the scroll-invariant roster and add the focus regex**

In `tests/test_editor_js_scroll_invariants.py`, add **only** `"formset_rows.js"` to `PANE_RESIDENT`
(do **not** remove `stepper_editor.js` / `markdone_editor.js` yet — Task 4 does that; and do **not**
add `switchgate_editor.js` — that roster entry belongs in Task 6). `PANE_RESIDENT` is consumed by a
loop whose first statement is `assert path.exists(), f"{name} moved or was renamed"`, so listing a
file four tasks before it is created leaves the suite red through Tasks 2-5.

Append:

```python
# Bare focus() scrolls every ancestor scrollport, and this page's viewport is
# overflow:hidden. Scoped to the two NEW modules on purpose: 19 pre-existing call
# sites across filltable_editor.js, table_editor.js, gallery_editor.js,
# text_toolbar.js and tabs_editor.js would make a repo-wide version RED on arrival,
# and fixing those is separate work.
FOCUS_OPT_IN = ["formset_rows.js", "switchgate_editor.js"]
FOCUS_CALL = re.compile(r"\.focus\s*\(")


def test_new_modules_never_focus_without_preventscroll():
    """A positive, line-level check: flag any line that CALLS .focus( without also
    mentioning preventScroll. Deliberately not a negative lookahead like
    `\\.focus\\s*\\(\\s*(?!\\{[^)]*preventScroll)` — that form is spacing-sensitive
    (it false-positives on `focus( { preventScroll: true } )`, because `\\s*`
    backtracks to zero and the lookahead then tests a space instead of the brace).
    Comment lines are skipped: filltable_editor.js and unit_nav.js discuss .focus()
    in prose, the mention-vs-call hazard the file's existing CALL comment warns of."""
    offenders = {}
    for name in FOCUS_OPT_IN:
        path = JS_DIR / name
        if not path.exists():
            continue  # module lands in a later task
        hits = [
            i
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if FOCUS_CALL.search(line)
            and "preventScroll" not in line
            and not line.strip().startswith("//")
            and not line.strip().startswith("*")
        ]
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"bare focus() in {offenders}: use focus({{ preventScroll: true }}) — "
        "the editor viewport is overflow:hidden, so a scrolling focus strands the author"
    )
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_formset_rows_assets.py tests/test_editor_js_scroll_invariants.py -v
```

Expected: all PASS.

- [ ] **Step 7: Falsify the focus guard**

Temporarily change `target.focus({ preventScroll: true })` in `formset_rows.js` to `target.focus()`, re-run `test_new_modules_never_focus_without_preventscroll`, confirm it FAILS, then restore.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/formset_rows.js templates/courses/manage/editor/editor.html tests/test_formset_rows_assets.py tests/test_editor_js_scroll_invariants.py
git commit -m "feat(editor): add formset_rows.js row add/remove helper"
```

---

### Task 3: Match pairs onto module 1 — the headline fix

**Files:**
- Modify: `templates/courses/manage/editor/_edit_matchpairquestion.html`
- Test: `tests/test_editor_formset_rows_render.py` (create)
- Test: `tests/test_matchpair_client_post_shapes.py` (create)
- Test: `tests/test_e2e_matchpair_rows.py` (create)

**Interfaces:**
- Consumes: `window.libliInitFormsetRows`, the markup contract, and the CSS guards.
- Produces: the match template as the reference shape every other formset template copies, plus `tests/helpers_editor_rows.py` with **exactly these six signatures** (later tasks import them, so the names and argument lists are the contract):
  - `save_url(course) -> str`
  - `form_url(course, element) -> str`
  - `open_element_form(client, course, element) -> str` (HTML)
  - `base_post(course, unit, element, type_key) -> dict`
  - `rendered_rows(html) -> list` (blueprint decomposed first)
  - `reopen(page, element_pk) -> None`
- Produces: the **fixture roster** in `tests/conftest.py`, all of which follow the opener contract in Global Constraints (`opener(page, live_server, **kwargs) -> element`):

| Fixture | Kind | Seeds / returns |
|---|---|---|
| `pa_client` | Django test client | a logged-in platform admin |
| `matchpair_element(pairs=[…])` | factory | `(course, unit, element)` with those pairs saved |
| `switchgate_element(options=[…], answer=N, stem=…)` | factory | `(course, unit, element)` |
| `open_matchpair_editor(saved_pairs=N)` | server-render | returns the edit fragment's HTML |
| `open_stepper_editor()` / `open_markdone_editor()` / `open_choice_editor_html()` | server-render | edit fragment HTML |
| `open_matchpair_editor_e2e(page, live_server, saved_pairs=N)` | e2e opener | returns the element |
| `open_element_editor(page, live_server, kind, rows=[…])` | e2e opener | `kind` in `{"stepper","markdone"}`; returns the element |
| `open_stepper_editor_e2e(page, live_server, steps=[…])` | e2e opener | returns the element (used at 20 steps) |
| `open_choice_editor(page, live_server, options=[…])` | e2e opener | returns the element |
| `open_switchgate_editor(page, live_server, options=[…], answer=N)` | e2e opener | returns the element |

Write them all in Step 0 alongside the helpers, modelled on the login/seed helpers in
`tests/test_e2e_questions.py` and `tests/test_e2e_switchgate.py`. Every later task assumes this
roster exists; leaving any of them to be invented mid-task is what the plan exists to prevent.

- [ ] **Step 0: Create the shared helper module**

These are plain functions, **not fixtures** — a fixture is only injectable through a test signature,
so `save_url(el)` called at module level from a test that never requests it would raise `NameError`.
Every later task imports from here.

```python
"""Shared helpers for the editor row-mechanics tests. Plain functions, not fixtures:
the tests call them directly rather than injecting them."""

from bs4 import BeautifulSoup
from django.urls import reverse


def save_url(course):
    """courses:manage_element_save takes only the course slug; the element and unit
    travel in the POST body (see views_manage.element_save)."""
    return reverse("courses:manage_element_save", kwargs={"slug": course.slug})


def form_url(course, element):
    return reverse(
        "courses:manage_element_form", kwargs={"slug": course.slug, "pk": element.pk}
    )


def open_element_form(client, course, element):
    """GET the element's edit fragment and return its HTML."""
    resp = client.get(form_url(course, element))
    assert resp.status_code == 200
    return resp.content.decode()


def base_post(course, unit, element, type_key):
    """The host-form keys every element save requires.

    `unit` is mandatory — views_manage.element_save reads request.POST['unit'] and
    filters ContentNode on it.

    `unit_token` is an OPTIMISTIC-CONCURRENCY token, not an id: _host_form.html:9
    posts `unit.updated.isoformat`, and builder._check_token (:524-527) does
    parse_datetime(token) and raises ConflictError unless it equals unit.updated.
    Passing unit.pk parses to None and every save returns **409**, not 200 — and
    409 is easy to misdiagnose, because it looks like neither the 404 of a missing
    unit nor the 422 of a validation error."""
    return {
        "type": type_key,
        "element": element.pk,
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
    }


def rendered_rows(html):
    """Rows actually in the list, with <template> content removed first.

    bs4 exposes <template> children as ordinary nodes, so a plain
    select("[data-fsrow-item]") also matches the blueprint row — an assertion that
    passes even when the list renders nothing."""
    soup = BeautifulSoup(html, "html.parser")
    for tmpl in soup.select("template"):
        tmpl.decompose()
    listing = soup.select_one("[data-fsrows-list]")
    return listing.select("[data-fsrow-item]") if listing else []


def reopen(page, element_pk):
    """Re-open an element's editor after a save, and wait for the swapped fragment.

    The edit trigger lives in the element ROW HEAD (`_element_row.html`), NOT inside
    [data-edit-slot] — the slot is where the form is swapped IN. Scoping the click
    to the slot finds nothing and the test hangs until timeout."""
    page.locator(f'.el-act-edit[data-element-id="{element_pk}"]').first.click()
    page.locator("[data-fsrows-list]").first.wait_for(timeout=8000)
```

Before writing it, **verify three things against the tree**, because getting any of them wrong
produces a confusing failure rather than an obvious one:

1. the URL names and their kwargs (`courses/views_manage.py`);
2. the host-form hidden keys (`_host_form.html`) — `unit_token` especially, per the docstring above;
3. the real edit-trigger selector in `templates/courses/manage/editor/_element_row.html` — the class
   is `el-act-edit` / `el-select` with a `data-element-id`, handled by `editor.js`'s `.el-select`
   branch. Adapt `reopen` to what is actually there.

- [ ] **Step 1: Write the failing render tests**

Create `tests/test_editor_formset_rows_render.py`. Note the two anti-patterns this guards: a bare `data-fsrow` prefix matches the wrapper, and the `<template>` blueprint contains a row, so a naive count passes on a zero-row render.

```python
"""Render-level guards for the formset row contract.

Two traps, both of which produce an assertion that cannot fail:
  * `data-fsrow` is a strict PREFIX of `data-fsrows`, `data-fsrows-list` and
    `data-fsrow-remove` — so a substring count matches the wrapper alone.
  * the <template> blueprint reproduces the loop body verbatim, and bs4 exposes
    <template> content as ordinary children — so a parsed `select()` picks up
    blueprint rows even when the list renders none.
Every assertion below therefore scopes to [data-fsrows-list] with the template
decomposed first.
"""

import pytest
from bs4 import BeautifulSoup

from tests.helpers_editor_rows import rendered_rows

pytestmark = pytest.mark.django_db


def test_matchpair_renders_exactly_the_formset_rows(open_matchpair_editor):
    """A saved 2-pair question renders 2 saved + extra=2 blank = 4 rows."""
    html = open_matchpair_editor(saved_pairs=2)
    assert len(rendered_rows(html)) == 4


def test_matchpair_blueprint_carries_the_prefix_token(open_matchpair_editor):
    """Match gains its first <template>; without this it has no test that it exists."""
    html = open_matchpair_editor(saved_pairs=2)
    soup = BeautifulSoup(html, "html.parser")
    tmpl = soup.select_one("[data-fsrows-template]")
    assert tmpl is not None, "match template must ship a blueprint"
    assert "pairs-__prefix__-left" in tmpl.decode_contents()


def test_matchpair_progressive_enhancement(open_matchpair_editor):
    """(a) JS-only controls ship hidden; (b) the DELETE label does not.
    This is the ONLY guard on the no-JS story."""
    html = open_matchpair_editor(saved_pairs=2)
    soup = BeautifulSoup(html, "html.parser")
    for tmpl in soup.select("template"):
        tmpl.decompose()
    add = soup.select_one("[data-fsrows-add]")
    assert add is not None and add.has_attr("hidden")
    row = soup.select_one("[data-fsrows-list] [data-fsrow-item]")
    assert row.select_one("[data-fsrow-remove]").has_attr("hidden")
    assert not row.select_one("[data-fsrow-del]").has_attr("hidden")


def test_matchpair_bounds(open_matchpair_editor):
    """Match's minimum is a bare `len(kept) < 1` in BaseMatchPairFormSet with no
    named constant, so this is a documented literal-vs-literal exception."""
    html = open_matchpair_editor(saved_pairs=2)
    soup = BeautifulSoup(html, "html.parser")
    wrap = soup.select_one("[data-fsrows]")
    assert wrap["data-fsrows"] == "pairs"
    assert wrap["data-fsrows-min"] == "1"
    assert not wrap.has_attr("data-fsrows-max")
    assert wrap.get("data-fsrows-atmin")
    assert wrap.get("data-fsrows-confirm")
```

Add an `open_matchpair_editor` fixture to `tests/conftest.py` that logs in a PA, creates a course/unit with a `MatchPairQuestionElement` carrying `saved_pairs` pairs, GETs the element's edit form and returns the response body as text. Follow the existing editor-fixture patterns in `tests/test_editor_stepper_add.py`.

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_editor_formset_rows_render.py -v
```

Expected: FAIL — no `[data-fsrows-list]`, so `rendered_rows` is empty and the selectors return `None`.

- [ ] **Step 3: Rewrite `_edit_matchpairquestion.html`**

Replace lines 11-24 (management form through non-form errors) with:

```html
  <div data-fsrows="pairs"
       data-fsrows-min="1"
       data-fsrows-confirm="{% trans 'Remove this pair?' %}"
       data-fsrows-atmin="{% trans 'A matching question needs at least one pair.' %}">
    {{ formset.management_form }}
    <ul class="pair-rows" data-fsrows-list>
      {% for f in formset %}
        <li class="pair-row" data-fsrow-item>
          {{ f.id }}
          {{ f.left }} {{ f.right }}
          {% if formset.can_delete %}
            <label class="pair-row__del" data-fsrow-del>{{ f.DELETE }} {% trans "Remove" %}</label>
            <button type="button" class="btn btn--small btn--ghost"
                    data-fsrow-remove hidden>{% trans "Remove" %}</button>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
    <button type="button" class="btn btn--small btn--ghost"
            data-fsrows-add hidden>＋ {% trans "Add pair" %}</button>
    <p class="el-editor__hint" data-fsrows-hint hidden></p>
    {% for e in formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
    {% comment %}Blueprint: the loop body verbatim, with each {{ f.X }} swapped for
    {{ formset.empty_form.X }} so the added row inherits the ModelForm widget's
    attributes exactly. Django renders empty_form's index literal as __prefix__.
    Never {{ formset.empty_form }} bare — that emits Django's default layout.{% endcomment %}
    <template data-fsrows-template>
      <li class="pair-row" data-fsrow-item>
        {{ formset.empty_form.id }}
        {{ formset.empty_form.left }} {{ formset.empty_form.right }}
        {% if formset.can_delete %}
          <label class="pair-row__del" data-fsrow-del>{{ formset.empty_form.DELETE }} {% trans "Remove" %}</label>
          <button type="button" class="btn btn--small btn--ghost"
                  data-fsrow-remove hidden>{% trans "Remove" %}</button>
        {% endif %}
      </li>
    </template>
  </div>
```

- [ ] **Step 4: Run the render tests**

```bash
uv run pytest tests/test_editor_formset_rows_render.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Add the characterization POST tests**

Create `tests/test_matchpair_client_post_shapes.py`. These pin the "No server changes" claim — they are green on `master` by design and are a stated falsification exception.

```python
"""Characterization tests: the POST shapes formset_rows.js emits are already
accepted by the unmodified server. Green on master by design (no application
Python changes), so they are a stated exception to the RED-before-fix rule. Their
job is to catch a FUTURE parser change that would break the editors."""

import pytest

pytestmark = pytest.mark.django_db


from tests.helpers_editor_rows import base_post, save_url


def test_more_rows_than_were_rendered_all_save(pa_client, matchpair_element):
    """The path that is unreachable today: the Add button has no handler, so the
    POST can never carry more forms than the server rendered."""
    course, unit, el = matchpair_element(pairs=[("a", "1"), ("b", "2")])
    data = base_post(course, unit, el, "matchpairquestion")
    data.update({
        "stem": "",
        "pairs-TOTAL_FORMS": "5", "pairs-INITIAL_FORMS": "2",
        "pairs-MIN_NUM_FORMS": "0", "pairs-MAX_NUM_FORMS": "1000",
    })
    for i, (left, right) in enumerate(
        [("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5")]
    ):
        data[f"pairs-{i}-left"] = left
        data[f"pairs-{i}-right"] = right
    for i, pair in enumerate(el.pairs.all()):
        data[f"pairs-{i}-id"] = pair.pk
    # X-Requested-With: the success path ends `if not _wants_fragment(request):
    # return redirect(...)`, so a plain post returns 302, not 200.
    resp = pa_client.post(save_url(course), data, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.pairs.count() == 5


def test_ticked_delete_removes_exactly_that_pair(pa_client, matchpair_element):
    course, unit, el = matchpair_element(pairs=[("a", "1"), ("b", "2"), ("c", "3")])
    pairs = list(el.pairs.all())
    data = base_post(course, unit, el, "matchpairquestion")
    data.update({
        "stem": "",
        "pairs-TOTAL_FORMS": "3", "pairs-INITIAL_FORMS": "3",
        "pairs-MIN_NUM_FORMS": "0", "pairs-MAX_NUM_FORMS": "1000",
        "pairs-1-DELETE": "on",
    })
    for i, p in enumerate(pairs):
        data[f"pairs-{i}-id"] = p.pk
        data[f"pairs-{i}-left"] = p.left
        data[f"pairs-{i}-right"] = p.right
    resp = pa_client.post(save_url(course), data, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert sorted(p.left for p in el.pairs.all()) == ["a", "c"]
```

Add `pa_client` and `matchpair_element` fixtures to `tests/conftest.py` — `matchpair_element`
returns the `(course, unit, element)` triple the payload needs. Follow
`tests/test_questions_2d_matchpair_form.py` for the formset field names and
`courses/tests/test_markdone_editor.py:16` for the `HTTP_X_REQUESTED_WITH="fetch"` idiom.

**Before writing these, POST once by hand and print `resp.status_code` and `resp.content[:400]`.**
The host form carries several hidden keys (`unit`, `unit_token`, `parent`, `tab`, `el_title`) and a
missing one fails as a 404 or a re-rendered 422 rather than an obvious error. Fix the payload from
what the real form posts, not from this plan.

- [ ] **Step 6: Run them**

```bash
uv run pytest tests/test_matchpair_client_post_shapes.py -v
```

Expected: 2 PASSED (green on master — that is the point).

- [ ] **Step 7: Write the e2e tests**

Create `tests/test_e2e_matchpair_rows.py`:

```python
"""e2e for the reported defect. The add test is RED on master by construction:
the ＋ Add pair button has never had a handler.

Harness mirrors tests/test_e2e_switchgate.py — see the Global Constraints."""

import os

import pytest

from tests.helpers_editor_rows import reopen

pytestmark = pytest.mark.e2e

SAVE = "[data-edit-slot] button[type='submit']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_add_three_pairs_without_saving(page, live_server, open_matchpair_editor_e2e):
    """The whole point: three new pairs in ONE session, no save-and-reopen."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=2)
    add = page.locator("[data-fsrows-add]")
    for _ in range(3):
        add.click()
    rows = page.locator("[data-fsrows-list] [data-fsrow-item]")
    # 2 saved + extra=2 blanks + 3 added = 7 rendered rows; fill the last three.
    for i, (left, right) in enumerate([("x", "9"), ("y", "8"), ("z", "7")], start=4):
        rows.nth(i).locator('input[name$="-left"]').fill(left)
        rows.nth(i).locator('input[name$="-right"]').fill(right)
    page.locator(SAVE).click()
    # Wait on the swapped-in preview, not networkidle: the save is a fetch +
    # fragment swap with no navigation, so networkidle is a timing heuristic.
    page.locator('[data-scope="preview"] [data-question]').first.wait_for(timeout=8000)
    reopen(page)
    assert page.locator("[data-fsrows-list] input[name$='-left']").count() >= 5


@pytest.mark.django_db(transaction=True)
def test_remove_a_filled_pair(page, live_server, open_matchpair_editor_e2e):
    open_matchpair_editor_e2e(page, live_server, saved_pairs=3)
    # Playwright AUTO-DISMISSES confirm: without this handler the removal takes
    # the cancel path and the test fails against a CORRECT build.
    page.on("dialog", lambda d: d.accept())
    row = page.locator("[data-fsrows-list] [data-fsrow-item]").nth(1)
    row.locator("[data-fsrow-remove]").click()
    # A hidden row is still matched by count() — assert on VISIBILITY, and wait
    # rather than asserting immediately after the click.
    row.wait_for(state="hidden", timeout=4000)
    page.locator(SAVE).click()
    page.locator('[data-scope="preview"] [data-question]').first.wait_for(timeout=8000)
    reopen(page)
    assert page.locator("[data-fsrows-list] input[name$='-left']").count() == 4
```

Build `open_matchpair_editor_e2e` from the login/seed/open helpers in `tests/test_e2e_questions.py`
(it takes `page` and `live_server` and navigates to the unit editor with the element's form open).
Confirm the real post-save selector against `tests/test_e2e_questions.py:186` before relying on
`[data-scope="preview"] [data-question]` — copy whatever the existing question e2e wait on.

- [ ] **Step 8: Falsify the add test against master, then run it**

**Revert only the template**, never `git stash -u`. At this point the four new test files are still
*untracked* (the commit is Step 9), so `-u` would stash the very test being run and pytest would exit
"file or directory not found" — an error, not the RED this step demonstrates. The module from Task 2
is already committed and must stay.

```bash
cp templates/courses/manage/editor/_edit_matchpairquestion.html /tmp/keep.html
git checkout HEAD -- templates/courses/manage/editor/_edit_matchpairquestion.html
uv run pytest tests/test_e2e_matchpair_rows.py::test_add_three_pairs_without_saving -m e2e -v   # expect FAIL
cp /tmp/keep.html templates/courses/manage/editor/_edit_matchpairquestion.html
uv run pytest tests/test_e2e_matchpair_rows.py -m e2e -v                                        # expect PASS
```

Confirm the failure is "the add button did nothing" (no new rows), not a fixture or selector error —
the mutant must fail for the reason under test.

- [ ] **Step 9: Commit**

```bash
git add templates/courses/manage/editor/_edit_matchpairquestion.html tests/test_editor_formset_rows_render.py tests/test_matchpair_client_post_shapes.py tests/test_e2e_matchpair_rows.py tests/conftest.py
git commit -m "fix(editor): make Add pair work without saving and re-opening"
```

---

### Task 4: Stepper and checklist retrofit; retire the two modules

**Files:**
- Modify: `templates/courses/manage/editor/_edit_stepper.html`, `_edit_markdone.html`
- Delete: `courses/static/courses/js/stepper_editor.js`, `courses/static/courses/js/markdone_editor.js`
- Modify: `templates/courses/manage/editor/editor.html` (remove two `<script>` lines **and their whole `{% comment %}` blocks**)
- Modify: `courses/static/courses/js/editor.js:125-126`
- Modify: `tests/test_stepper_editor_assets.py`, `courses/tests/test_markdone_editor.py`, `tests/test_editor_stepper_add.py`, `tests/test_editor_js_scroll_invariants.py`
- Test: `tests/test_e2e_retrofit_rows.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1-3.
- Produces: `stepper_editor.js` and `markdone_editor.js` no longer exist; `libliInitStepperEditor` / `libliInitMarkDoneEditor` are gone.

- [ ] **Step 1: Write the retrofit e2e**

Create `tests/test_e2e_retrofit_rows.py`. The **add** half is a GREEN-on-master no-regression test and must find the button **by visible label** (the hook changes, so a new-attribute selector is red on master and proves nothing). The **remove** half is a normal RED-first test — master renders no remove button at all.

```python
import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.e2e]


import os

import pytest

from tests.helpers_editor_rows import reopen

pytestmark = pytest.mark.e2e   # NOT [django_db, e2e] — see Global Constraints

SAVE = "[data-edit-slot] button[type='submit']"
ROWS = {"stepper": ".stepper-rows li", "markdone": ".markdone-rows li"}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _values(page, kind):
    """Playwright has NO get_by_display_value (that is a Testing Library API — the
    real roster is get_by_alt_text/label/placeholder/role/test_id/text/title). Read
    input_value() off the located rows instead: for JS-filled fields the `value`
    PROPERTY is what changed, while the `value` ATTRIBUTE selector would still match
    the server-rendered original."""
    inputs = page.locator(f'{ROWS[kind]} input[type="text"]')
    return [inputs.nth(i).input_value() for i in range(inputs.count())]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind,label", [("stepper", "Add step"), ("markdone", "Add item")])
def test_add_row_still_works_after_retrofit(page, live_server, open_element_editor, kind, label):
    """GREEN on master AND after: proves the rewiring did not break a working editor.

    EVERY selector here must survive the retrofit, not just the button. The button is
    found by visible label because data-stepper-add-row becomes data-fsrows-add; the
    row list is found by its CLASS (.stepper-rows / .markdone-rows, unchanged by this
    change) because data-stepper-rows becomes data-fsrows-list. Selecting the list by
    the NEW hook would make this red on master, and the no-regression guarantee — the
    riskiest part of this change — would not actually be established."""
    el = open_element_editor(page, live_server, kind)
    page.get_by_role("button", name=label).click()
    rows = page.locator(ROWS[kind])
    rows.last.locator('input[type="text"]').fill("retrofit row")
    page.locator(SAVE).click()
    page.locator('[data-scope="preview"] [data-question]').first.wait_for(timeout=8000)
    reopen(page, el.pk)
    assert "retrofit row" in _values(page, kind)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["stepper", "markdone"])
def test_remove_row_after_retrofit(page, live_server, open_element_editor, kind):
    """RED on master: there is no per-row remove BUTTON there, only a checkbox."""
    el = open_element_editor(page, live_server, kind, rows=["one", "two", "three"])
    page.on("dialog", lambda d: d.accept())   # persisted rows are non-blank
    row = page.locator(ROWS[kind]).nth(1)
    row.locator("[data-fsrow-remove]").click()
    row.wait_for(state="hidden", timeout=4000)
    page.locator(SAVE).click()
    page.locator('[data-scope="preview"] [data-question]').first.wait_for(timeout=8000)
    reopen(page, el.pk)
    assert "two" not in _values(page, kind)
```

- [ ] **Step 2: Run to verify the remove half fails and the add half passes**

```bash
uv run pytest tests/test_e2e_retrofit_rows.py -m e2e -v
```

Expected: `test_add_row_still_works_after_retrofit` PASS (pre-retrofit), `test_remove_row_after_retrofit` FAIL.

- [ ] **Step 3: Rewrite `_edit_stepper.html`**

Replace the whole file body. Note the file's own header `{% comment %}` at `:2-6` names the retired module and must be rewritten too.

```html
{% load i18n %}
{% comment %}
Step-by-step editor. One inline formset of steps (prefix "steps"). Rows are added
and removed client-side by formset_rows.js via the [data-fsrows] contract; the
DELETE checkbox stays in the DOM as the no-JS affordance and the JS-only buttons
ship hidden until the init pass reveals them.
{% endcomment %}
<div class="el-editor el-editor--stepper">
  <label class="el-editor__label">{% trans "Intro prompt (optional)" %}</label>
  <input type="text" name="prompt" class="el-editor__input" maxlength="500"
         value="{{ form.prompt.value|default:'' }}">

  <label class="el-editor__label">{% trans "Steps" %}</label>
  <p class="el-editor__hint">{% trans "Each step is a short line (text or math, e.g. \\(2^{10}\\)). The first shows immediately; the button reveals the rest one at a time." %}</p>
  <div data-fsrows="steps"
       data-fsrows-min="{{ form.instance.MIN_STEPS }}"
       data-fsrows-max="{{ form.instance.MAX_STEPS }}"
       data-fsrows-confirm="{% trans 'Remove this step?' %}"
       data-fsrows-atmin="{% trans 'A stepper needs at least one step.' %}"
       data-fsrows-atcap="{% trans 'No room for another step.' %}">
    {{ formset.management_form }}
    <ul class="stepper-rows" data-fsrows-list>
      {% for f in formset %}
        <li class="stepper-row" data-fsrow-item>
          {{ f.id }}
          {{ f.content }}
          {% if formset.can_delete %}
            <label class="stepper-row__del" data-fsrow-del>{{ f.DELETE }} {% trans "Remove" %}</label>
            <button type="button" class="btn btn--small btn--ghost"
                    data-fsrow-remove hidden>{% trans "Remove" %}</button>
          {% endif %}
        </li>
      {% endfor %}
    </ul>
    <button type="button" class="btn btn--small btn--ghost"
            data-fsrows-add hidden>＋ {% trans "Add step" %}</button>
    <p class="el-editor__hint" data-fsrows-hint hidden></p>
    {% for e in formset.non_form_errors %}<p class="field-error">{{ e }}</p>{% endfor %}
    <template data-fsrows-template>
      <li class="stepper-row" data-fsrow-item>
        {{ formset.empty_form.id }}
        {{ formset.empty_form.content }}
        {% if formset.can_delete %}
          <label class="stepper-row__del" data-fsrow-del>{{ formset.empty_form.DELETE }} {% trans "Remove" %}</label>
          <button type="button" class="btn btn--small btn--ghost"
                  data-fsrow-remove hidden>{% trans "Remove" %}</button>
        {% endif %}
      </li>
    </template>
  </div>
</div>
```

**Why `{{ form.instance.MIN_STEPS }}` works** — and why no view change is needed:
`StepperElementForm` is a `ModelForm` over `StepperElement` (`element_forms.py:1857-1860`), so
`form.instance` is a `StepperElement` and Django's template attribute lookup resolves the class
constants (`courses/models.py:618-619`) on it. This keeps the "no application Python is modified"
constraint intact, and it is what makes the bounds-render test's constant comparison meaningful
rather than literal-vs-literal.

- [ ] **Step 4: Rewrite `_edit_markdone.html` the same way**

Identical shape with prefix `items`, class `markdone-row`, `{{ f.content }}`,
`data-fsrows-min="{{ form.instance.MIN_ITEMS }}"`, `data-fsrows-max="{{ form.instance.MAX_ITEMS }}"`,
and strings "Remove this item?" / "A checklist needs at least one item." / "No room for another
item." / "＋ Add item". `MarkDoneElementForm` is likewise a `ModelForm` over `MarkDoneElement`
(`element_forms.py:1914-1917`), so the same instance-attribute lookup applies.

- [ ] **Step 5: Delete the two modules and their wiring**

```bash
git rm courses/static/courses/js/stepper_editor.js courses/static/courses/js/markdone_editor.js
```

In `editor.html`, delete **each retired `<script>` line together with its entire `{% comment %}` block** — the stepper block *opens at `:265`*, not `:266`. Deleting a partial range leaves an unterminated `{% comment %}` and the page raises `TemplateSyntaxError`.

In `editor.js:125-126`, replace the two retired init calls with:

```js
    if (editorPane && window.libliInitFormsetRows) window.libliInitFormsetRows(editorPane);
    if (editorPane && window.libliInitSwitchGateEditor) window.libliInitSwitchGateEditor(editorPane);
```

- [ ] **Step 6: Retarget the broken tests**

- `tests/test_stepper_editor_assets.py`: **`git rm` the file.** Retargeting it leaves nothing behind — its `steps-TOTAL_FORMS` assertion must go (a prefix-agnostic helper can never contain that literal), its `__prefix__` assertion is replaced by the blueprint-render test below, its `libliInitStepperEditor` export check becomes byte-identical to `test_formset_rows_js_exports`, and deleting the page assertion from `test_editor_page_loads_stepper_editor_js` would leave a test body with no assertion at all — one that passes forever. Say in the commit message that the coverage moved to `tests/test_formset_rows_assets.py` and `tests/test_editor_formset_rows_render.py` rather than vanishing.
- `courses/tests/test_markdone_editor.py:20,30`: `data-markdone-editor` → `data-fsrows="items"`; `courses/js/markdone_editor.js` → `courses/js/formset_rows.js`.
- `tests/test_editor_stepper_add.py:27-28`: `data-stepper-editor` → `data-fsrows="steps"`. For the row assertion, **do not** simply swap `data-stepper-row` for a delimited `data-fsrow-item>` count: the new `<template>` blueprint always emits one, so `count(...) >= 1` would pass on a render with **zero** rows — the exact trap this plan documents in Task 3. Replace it with an exact scoped count instead:

```python
from tests.helpers_editor_rows import rendered_rows
...
    assert len(rendered_rows(resp.content.decode())) == 1   # extra=1 on a fresh stepper
```
- `tests/test_editor_js_scroll_invariants.py`: remove `stepper_editor.js` and `markdone_editor.js` from `PANE_RESIDENT`.

- [ ] **Step 7: Extend the render tests to stepper and checklist**

Add to `tests/test_editor_formset_rows_render.py` (adding the two model imports **here**, not in
Task 3, so `ruff check` never sees them unused):

```python
from courses.models import MarkDoneElement
from courses.models import StepperElement


def test_stepper_bounds_come_from_the_model_constants(open_stepper_editor):
    """Literals on both sides stay green when MAX_STEPS changes — build the
    expected value from the constant so the test can catch the drift it exists for."""
    html = open_stepper_editor()
    assert f'data-fsrows-max="{StepperElement.MAX_STEPS}"' in html
    assert f'data-fsrows-min="{StepperElement.MIN_STEPS}"' in html


def test_markdone_bounds_come_from_the_model_constants(open_markdone_editor):
    html = open_markdone_editor()
    assert f'data-fsrows-max="{MarkDoneElement.MAX_ITEMS}"' in html
    assert f'data-fsrows-min="{MarkDoneElement.MIN_ITEMS}"' in html


@pytest.mark.parametrize(
    "opener,prefix,field",
    [("open_stepper_editor", "steps", "content"),
     ("open_markdone_editor", "items", "content")],
)
def test_retrofit_blueprint_carries_the_prefix_token(request, opener, prefix, field):
    """The retrofit swaps hand-written blueprints for formset.empty_form ones — the
    highest-drift edit in this task. Task 4 also DELETES the old __prefix__
    assertion, so without this the coverage net-decreases on exactly the change
    most likely to break."""
    html = request.getfixturevalue(opener)()
    soup = BeautifulSoup(html, "html.parser")
    tmpl = soup.select_one("[data-fsrows-template]")
    assert tmpl is not None
    assert f"{prefix}-__prefix__-{field}" in tmpl.decode_contents()


@pytest.mark.parametrize(
    "opener", ["open_stepper_editor", "open_markdone_editor"]
)
def test_retrofit_progressive_enhancement(request, opener):
    """Half (a) and (b) of the no-JS guarantee, for the two retrofitted editors."""
    html = request.getfixturevalue(opener)()
    soup = BeautifulSoup(html, "html.parser")
    for tmpl in soup.select("template"):
        tmpl.decompose()
    assert soup.select_one("[data-fsrows-add]").has_attr("hidden")
    row = soup.select_one("[data-fsrows-list] [data-fsrow-item]")
    assert row.select_one("[data-fsrow-remove]").has_attr("hidden")
    assert not row.select_one("[data-fsrow-del]").has_attr("hidden")
```

- [ ] **Step 8: Run the affected suites**

```bash
uv run pytest tests/test_formset_rows_assets.py courses/tests/test_markdone_editor.py tests/test_editor_stepper_add.py tests/test_editor_js_scroll_invariants.py tests/test_editor_formset_rows_render.py -v
uv run pytest tests/test_e2e_retrofit_rows.py -m e2e -v
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(editor): retrofit stepper and checklist onto formset_rows.js"
```

---

### Task 5: Choice — remove-only wiring, `addChoiceRow` amendments, dead-code removal

Choice keeps its own add path. Its existing hooks stay **in addition** to the new ones: `editor.js` and three e2e files consume them.

**Files:**
- Modify: `templates/courses/manage/editor/_edit_choicequestion.html`
- Modify: `courses/static/courses/js/editor.js` (`addChoiceRow`; delete the `choice-row--del` line in the clone, the "Reversible" comment, and the DELETE branch in the `change` handler)
- Modify: `courses/static/courses/css/editor.css` (delete the `.choice-row--del` block **and the comment above it**)
- Modify: `tests/test_e2e_questions.py` (module docstring; the `.check()` block)

**Cite by content, not line number, from here on.** Task 1 inserted ~7 lines into `editor.css` and
Step 1 below edits `_edit_choicequestion.html`, so every line reference in the spec and in earlier
tasks has drifted. The spec's numbers are as-of-master.

**Interfaces:**
- Consumes: `libliInitFormsetRows`.
- Produces: choice rows removable client-side; `choice-row--del` no longer exists anywhere.

- [ ] **Step 1: Wrap choice's formset**

In `_edit_choicequestion.html`, wrap from `{{ formset.management_form }}` through the non-form-errors block in:

```html
  <div data-fsrows="choices"
       data-fsrows-min="2"
       data-fsrows-confirm="{% trans 'Remove this option?' %}"
       data-fsrows-atmin="{% trans 'A question needs at least two options.' %}">
```

Keep `class="choice-rows" data-choice-rows` **and add** `data-fsrows-list` to the `<ul>`; keep `data-choice-row` **and add** `data-fsrow-item` on each `<li>`; add `data-fsrow-del` to the `<label class="choice-row__del">`; add the remove button after it; keep `data-choice-add` on the add button and add `hidden`. Choice has **no** `data-fsrows-add` and **no** `<template>` — they are optional and must be absent together.

The hint carrier goes immediately after the **`data-choice-add`** button (choice's add button is not
`data-fsrows-add`, so "after the add button" would otherwise be ambiguous) and before the
`non_form_errors` loop, matching the other four templates:

```html
    <p class="el-editor__hint" data-fsrows-hint hidden></p>
```

- [ ] **Step 2: Amend `addChoiceRow`**

Seven changes at `editor.js:419-443`:

```js
  // Called with the clicked [data-choice-add] button so the wrapper is in hand;
  // resolving it from `root` would reintroduce the cross-talk closest() prevents.
  function addChoiceRow(btn) {
    var wrap = btn.closest("[data-fsrows]");
    if (!wrap) return;
    var list = wrap.querySelector("[data-fsrows-list]");
    // Read the prefix from the attribute, as module 1's totalInput() does —
    // hardcoding "choices" re-creates the drift hazard data-fsrows exists to remove.
    var total = wrap.querySelector(
      'input[name="' + wrap.getAttribute("data-fsrows") + '-TOTAL_FORMS"]'
    );
    if (!list || !total) return;
    var rows = list.querySelectorAll("[data-choice-row]");
    // Clone the last NON-HIDDEN row: cloning a removed one yields a new row the
    // author cannot see while TOTAL_FORMS still increments.
    var last = null;
    for (var i = rows.length - 1; i >= 0; i--) {
      if (!rows[i].hidden) { last = rows[i]; break; }
    }
    if (!last) {
      // Unreachable while init job 2's minimum floor holds; loud so a regression
      // of that floor shows up as a message rather than a mute button.
      if (window.console) console.warn("addChoiceRow: no visible row to clone");
      return;
    }
    var idx = parseInt(total.value, 10);
    var clone = last.cloneNode(true);
    // BOTH existing loops, unchanged and in order — reproduced in full rather than
    // described, because losing the second one ships clones carrying the source
    // row's option text, feedback textarea and is_correct state, and losing the
    // first produces duplicate choices-N-* names that silently corrupt the POST.
    Array.prototype.forEach.call(clone.querySelectorAll("[name],[id],[for]"), function (el) {
      ["name", "id", "for"].forEach(function (attr) {
        var v = el.getAttribute(attr);
        // replace the form index (the first -N- / _N_ run) with the new index
        if (v) el.setAttribute(attr, v.replace(/([-_])\d+([-_])/, "$1" + idx + "$2"));
      });
    });
    Array.prototype.forEach.call(clone.querySelectorAll("input, textarea"), function (el) {
      if (el.type === "checkbox" || el.type === "radio") el.checked = false;
      else el.value = "";
    });
    clone.hidden = false;
    var del = clone.querySelector('[name$="-DELETE"]');
    if (del) del.checked = false;
    var rm = clone.querySelector("[data-fsrow-remove]");
    if (rm) rm.disabled = false;      // cloneNode(true) copies `disabled`
    list.appendChild(clone);
    total.value = idx + 1;
    syncChoiceFeedback(list);
    if (window.libliInitFormsetRows) window.libliInitFormsetRows(wrap);
  }
```

Update the call site at `:375-376` to `addChoiceRow(addChoice)`.

- [ ] **Step 3: Delete the dead code**

Once init job 1 hides the DELETE label, the checkbox is out of the accessibility tree and out of tab order, so **no JS author can fire its `change` event** and its only listener is unreachable. Delete:

- `editor.js:493-497` — the DELETE branch toggling `choice-row--del`;
- `editor.js:492` — the now-false "Reversible: untick to restore the row." comment;
- `editor.js:439` — `clone.classList.remove("choice-row--del")` (already gone via Step 2);
- `editor.css:176-179` — the dim rule **and its comment**, which says the row stays "visible so the author can undo by un-ticking Remove before saving".

Verify first that `choice-row--del` has no other consumers:

```bash
grep -rn "choice-row--del" courses/ templates/ tests/
```

- [ ] **Step 3b: Add a clone-is-blank assertion**

The clearing loop above has no coverage today, because the choice e2e `fill()`s the new row
immediately. Add one line to `test_choice_editor_add_remove_and_radio_js` in
`tests/test_e2e_questions.py`, immediately after the existing `wait_for_function` that follows the
add click and **before** the three `fill()` calls. Use the binding that is actually there — the test
has no `new_row`; it addresses the new row as `slot.locator("input[name='choices-2-text']")`:

```python
    # The clone must arrive blank: addChoiceRow copies the last row, so losing its
    # value-clearing loop would carry the source row's text into every new option.
    assert slot.locator("input[name='choices-2-text']").input_value() == ""
```

- [ ] **Step 4: Rewrite the broken e2e**

In `tests/test_e2e_questions.py`, **keep** the `row2 = slot.locator("[data-choice-row]").nth(2)`
binding (it is inside the block being replaced and is used by the new code) and replace only from the
`.check()` call onward. Match on the existing text rather than a line range — the line numbers have
already drifted from Task 1's CSS insertions and Step 1's template edits:

Replace (note the real text is an implicitly concatenated two-part string scoped to the slot — copy
it from the file rather than from here):

```python
    row2.locator("input[name='choices-2-DELETE']").check()
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'[data-edit-slot] .choice-row--del').length === 1"
    )
```

with:

```python
    # The DELETE checkbox now sits inside a hidden label, so .check() would fail
    # actionability. Drive the JS control instead.
    page.on("dialog", lambda d: d.accept())   # the row was filled with "Gamma" above
    row2.locator("[data-fsrow-remove]").click()
    # Replaces the removed wait_for_function: without an explicit wait the
    # assertion races the click handler.
    row2.wait_for(state="hidden", timeout=4000)
    assert row2.locator("input[name='choices-2-DELETE']").is_checked()
```

Read the surrounding lines first and adapt the `before` text to what is actually there. Then remove
`- "Remove" gives live feedback (row dims) before save;` from the module docstring.

- [ ] **Step 5: Run the choice suites**

```bash
uv run pytest tests/test_e2e_questions.py tests/test_e2e_choice_editor_feedback.py tests/test_e2e_math_input.py -m e2e -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(editor): instant remove for choice rows; drop the unreachable dim branch"
```

---

### Task 6: `switchgate_editor.js` and the switchgate template

**Files:**
- Create: `courses/static/courses/js/switchgate_editor.js`
- Modify: `templates/courses/manage/editor/_edit_switchgate.html`
- Modify: `templates/courses/manage/editor/editor.html` (script tag)
- Modify: `courses/static/courses/js/editor.js` (add the `libliInitSwitchGateEditor` post-swap call)
- Modify: `tests/test_editor_js_scroll_invariants.py` (add `switchgate_editor.js` to `PANE_RESIDENT` — **now**, not in Task 2, because the roster asserts the file exists)
- Modify: `tests/test_formset_rows_assets.py` (add the module-2 asset assertions)
- Test: `tests/test_switchgate_client_post_shapes.py`, `tests/test_e2e_switchgate_rows.py` (create)

**Interfaces:**
- Consumes: the CSS twins from Task 1.
- Produces: `window.libliInitSwitchGateEditor(root)` — four idempotent jobs (reveal, disabled state, hint, renumber).

- [ ] **Step 1: Write the failing e2e**

Create `tests/test_e2e_switchgate_rows.py`:

```python
import os

import pytest

pytestmark = pytest.mark.e2e

SAVE = "[data-edit-slot] button[type='submit']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_add_option_beyond_the_padded_blanks(page, live_server, open_switchgate_editor):
    open_switchgate_editor(page, live_server, options=["two", "three", "four"])
    before = page.locator("[data-sgate-row]").count()
    page.locator("[data-sgate-add]").click()
    assert page.locator("[data-sgate-row]").count() == before + 1


@pytest.mark.django_db(transaction=True)
def test_removing_a_middle_option_keeps_the_right_answer(
    page, live_server, open_switchgate_editor
):
    """The renumbering test: if the radio values are not rewritten, `answer` points
    at the wrong option and the question silently marks the wrong choice correct."""
    el = open_switchgate_editor(
        page, live_server, options=["alpha", "beta", "gamma"], answer=2
    )
    page.on("dialog", lambda d: d.accept())   # filled row -> confirm fires
    page.locator("[data-sgate-row]").nth(1).locator("[data-sgate-remove]").click()
    page.locator(SAVE).click()
    page.locator('[data-scope="preview"] [data-question]').first.wait_for(timeout=8000)
    el.refresh_from_db()
    assert el.options[el.answer] == "gamma"


@pytest.mark.django_db(transaction=True)
def test_removing_an_interior_blank_lets_the_save_succeed(
    page, live_server, open_switchgate_editor
):
    """Today this is a dead end: clean() rejects interior blanks and there is no
    remove control, so an author who fills rows 1, 2 and 6 cannot save at all."""
    open_switchgate_editor(page, live_server, options=[])
    rows = page.locator("[data-sgate-row]")
    rows.nth(0).locator('input[name="option"]').fill("first")
    rows.nth(1).locator('input[name="option"]').fill("second")
    rows.nth(5).locator('input[name="option"]').fill("sixth")
    rows.nth(0).locator('input[name="answer"]').check()
    # Blank rows are removed WITHOUT a confirm — no dialog handler on purpose.
    # Descending order: each removal renumbers, so ascending indices would shift.
    for i in (4, 3, 2):
        rows.nth(i).locator("[data-sgate-remove]").click()
    page.locator(SAVE).click()
    page.locator('[data-scope="preview"] [data-question]').first.wait_for(timeout=8000)
    assert page.locator("text=Options cannot be empty").count() == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_e2e_switchgate_rows.py -m e2e -v
```

Expected: all FAIL — `[data-sgate-add]` / `[data-sgate-remove]` do not exist.

- [ ] **Step 3: Create `courses/static/courses/js/switchgate_editor.js`**

```js
/* Choose & confirm (switchgate) option list.

   SIBLING FILES, ONE LETTER APART — do not confuse them:
     switchgate.js         student runtime for this element
     switchgrid_editor.js  a DIFFERENT element's editor

   Switchgate is NOT a formset: options are repeated name="option" inputs read
   positionally via getlist("option"), and the correct answer is a radio whose
   value is the option's INDEX. So a removed row must be DETACHED (a hidden input
   still submits, and clean() rejects interior blanks) and every survivor
   renumbered — otherwise `answer` points at the wrong option. */
(function () {
  "use strict";
  var WRAP = "[data-sgate]";
  var FALLBACK_CONFIRM = "Remove this option?";

  function wrappers(root) {
    var scope = root || document;
    if (scope.matches && scope.matches(WRAP)) return [scope];
    return Array.prototype.slice.call(scope.querySelectorAll(WRAP));
  }

  function rowsOf(wrap) {
    return Array.prototype.slice.call(wrap.querySelectorAll("[data-sgate-row]"));
  }

  function renumber(wrap) {
    // Never parse the rendered placeholder: it is a fully substituted TRANSLATED
    // literal ("Opcja 3" under pl) with no token left, and a /\d+$/ rewrite is
    // locale-fragile. Rebuild from the single template string instead.
    var tmpl = wrap.getAttribute("data-sgate-placeholder") || "";
    rowsOf(wrap).forEach(function (row, i) {
      var radio = row.querySelector('input[name="answer"]');
      if (radio) radio.value = String(i);            // 0-based
      var text = row.querySelector('input[name="option"]');
      if (text) text.placeholder = tmpl.replace(/__pos__/g, String(i + 1));  // 1-based
    });
  }

  function recompute(wrap) {
    var min = parseInt(wrap.getAttribute("data-sgate-min"), 10) || 2;
    var rows = rowsOf(wrap);
    var atMin = rows.length <= min;
    rows.forEach(function (row) {
      var btn = row.querySelector("[data-sgate-remove]");
      if (btn) btn.disabled = atMin;
    });
    var hint = wrap.querySelector("[data-sgate-hint]");
    if (!hint) return;
    var msg = atMin ? wrap.getAttribute("data-sgate-atmin") : null;
    hint.textContent = msg || "";
    hint.hidden = !msg;
  }

  function initOne(wrap) {
    Array.prototype.forEach.call(
      wrap.querySelectorAll("[data-sgate-add], [data-sgate-remove]"),
      function (b) { b.hidden = false; }
    );
    recompute(wrap);
    renumber(wrap);
  }

  function initSwitchGateEditor(root) { wrappers(root).forEach(initOne); }

  function addRow(wrap) {
    var tmpl = wrap.querySelector("[data-sgate-template]");
    var list = wrap.querySelector("[data-sgate-list]");
    if (!tmpl || !list) {
      if (window.console) console.warn("switchgate_editor: add is not wired on", wrap);
      return;
    }
    var idx = rowsOf(wrap).length;
    var holder = document.createElement("div");
    holder.innerHTML = tmpl.innerHTML
      .replace(/__index__/g, String(idx))
      .replace(/__pos__/g, String(idx + 1))
      .trim();
    var row = holder.firstElementChild;
    if (!row) return;
    list.appendChild(row);
    initSwitchGateEditor(wrap);   // the blueprint carries `hidden` on its remove button
    if (window.libliAlignTopInPane) window.libliAlignTopInPane(row);
    var text = row.querySelector('input[name="option"]');
    if (text) text.focus({ preventScroll: true });
  }

  function focusable(el) { return el && !el.hidden && !el.disabled; }

  function removeRow(wrap, row) {
    var min = parseInt(wrap.getAttribute("data-sgate-min"), 10) || 2;
    if (rowsOf(wrap).length <= min) return;
    var text = row.querySelector('input[type="text"]');
    if (text && text.value.trim() !== "") {
      var msg = wrap.getAttribute("data-sgate-confirm");
      if (!msg) {
        if (window.console) console.warn("switchgate_editor: no data-sgate-confirm");
        msg = FALLBACK_CONFIRM;
      }
      if (!window.confirm(msg)) return;
    }
    // Capture BEFORE detaching: once row.remove() runs, its siblings are null and
    // every focus candidate would resolve to nothing.
    var next = row.nextElementSibling;
    var prev = row.previousElementSibling;

    row.remove();
    initSwitchGateEditor(wrap);   // renumber + recompute; the guard is a live check

    var candidates = [];
    if (next) candidates.push(next.querySelector("[data-sgate-remove]"));
    if (prev) candidates.push(prev.querySelector("[data-sgate-remove]"));
    var near = next || prev;
    if (near) candidates.push(near.querySelector('input[name="option"]'));
    for (var i = 0; i < candidates.length; i++) {
      if (focusable(candidates[i])) {
        candidates[i].focus({ preventScroll: true });
        return;
      }
    }
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;   // non-Element target (synthetic dispatch)
    var add = e.target.closest("[data-sgate-add]");
    if (add) {
      var w = add.closest(WRAP);
      if (w) addRow(w);
      return;
    }
    var rm = e.target.closest("[data-sgate-remove]");
    if (rm) {
      var wrap = rm.closest(WRAP);
      var row = rm.closest("[data-sgate-row]");
      if (wrap && row) removeRow(wrap, row);
    }
  });

  window.libliInitSwitchGateEditor = initSwitchGateEditor;
  document.addEventListener("DOMContentLoaded", function () {
    initSwitchGateEditor(document);
  });
})();
```

- [ ] **Step 4: Rewrite `_edit_switchgate.html`'s options block**

```html
  <label class="el-editor__label">{% trans "Options (mark the correct one)" %}</label>
  <div data-sgate
       data-sgate-min="2"
       data-sgate-confirm="{% trans 'Remove this option?' %}"
       data-sgate-atmin="{% trans 'A choice needs at least two options.' %}"
       data-sgate-placeholder="{% trans 'Option' %} __pos__">
    <div class="el-editor__options" data-sgate-list>
      {% for row in form.option_rows %}
        <div class="el-editor__option-row" data-sgate-row>
          <input type="radio" name="answer" value="{{ forloop.counter0 }}"{% if row.checked %} checked{% endif %}
                 aria-label="{% trans 'Correct option' %}">
          <input type="text" name="option" class="rte-source" value="{{ row.value }}"
                 placeholder="{% trans 'Option' %} {{ forloop.counter }}">
          <button type="button" class="el-editor__remove" data-sgate-remove hidden
                  aria-label="{% trans 'Remove option' %}"
                  title="{% trans 'Remove option' %}">&times;</button>
        </div>
      {% endfor %}
    </div>
    <button type="button" class="btn btn--small btn--ghost"
            data-sgate-add hidden>＋ {% trans "Add option" %}</button>
    <p class="el-editor__hint" data-sgate-hint hidden></p>
    {% comment %}Blueprint: the loop body verbatim. Two tokens are required because
    the radio is 0-based and the placeholder 1-based; one token would render
    "Option 0, Option 1, ...".{% endcomment %}
    <template data-sgate-template>
      <div class="el-editor__option-row" data-sgate-row>
        <input type="radio" name="answer" value="__index__" aria-label="{% trans 'Correct option' %}">
        <input type="text" name="option" class="rte-source" value=""
               placeholder="{% trans 'Option' %} __pos__">
        <button type="button" class="el-editor__remove" data-sgate-remove hidden
                aria-label="{% trans 'Remove option' %}"
                title="{% trans 'Remove option' %}">&times;</button>
      </div>
    </template>
  </div>
```

`_edit_switchgate.html`'s `{% for e in form.non_field_errors %}` block **stays outside** the
`[data-sgate]` wrapper, after it. Module 2's wrapper only needs to enclose the list, the add button
and the `<template>` for `closest()` to work; module 1's wrapper encloses its errors block only
because the formset's `management_form` and `<template>` sit on either side of it. The wrapper is
`display: contents`, so the placement has no visual effect either way — this is stated so the
implementer does not have to guess.

Add the script tag to `editor.html` with the customary `{% comment %}`, add the
`libliInitSwitchGateEditor` post-swap call in `editor.js` beside the `libliInitFormsetRows` one from
Task 2, and add `"switchgate_editor.js"` to `PANE_RESIDENT`.

- [ ] **Step 4b: Add the module-2 asset assertions**

Without these, a forgotten `<script>` tag leaves switchgate's controls permanently `hidden` while
every server-side test stays green — the exact failure mode of the defect being fixed. Add to
`tests/test_formset_rows_assets.py`:

```python
def test_switchgate_editor_js_exports():
    src = open(finders.find("courses/js/switchgate_editor.js"), encoding="utf-8").read()
    assert "window.libliInitSwitchGateEditor" in src
    assert "__index__" in src and "__pos__" in src   # both tokens, not one


def test_editor_page_loads_switchgate_editor_js(client):
    ...  # same body as the formset_rows variant
    assert b"courses/js/switchgate_editor.js" in resp.content
```

- [ ] **Step 5: Add the switchgate characterization and bounds tests**

Create `tests/test_switchgate_client_post_shapes.py`. Green on master (a stated falsification
exception) — its job is to pin the "No server changes" claim for module 2.

```python
import pytest

from courses.element_forms import _MIN_OPTIONS
from tests.helpers_editor_rows import base_post, open_element_form, save_url

pytestmark = pytest.mark.django_db


def test_middle_option_removed_and_renumbered(pa_client, switchgate_element):
    """What module 2 emits after removing the middle of three options: a SHORTER
    option list plus an `answer` index renumbered to match its new position."""
    course, unit, el = switchgate_element(
        options=["alpha", "beta", "gamma"], answer=2, stem="2 {{choice}} 2 = 4"
    )
    data = base_post(course, unit, el, "switchgate")
    data["stem"] = "2 {{choice}} 2 = 4"
    data["option"] = ["alpha", "gamma"]   # beta detached
    data["answer"] = "1"                  # gamma moved from index 2 to 1
    resp = pa_client.post(save_url(course), data, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.options == ["alpha", "gamma"]
    assert el.options[el.answer] == "gamma"


def test_switchgate_min_bound_matches_the_server_constant(pa_client, switchgate_element):
    """Built from _MIN_OPTIONS, not a literal 2: a literal on both sides stays green
    when the constant changes, so it could not catch the drift it exists for."""
    course, unit, el = switchgate_element(options=["a", "b"], answer=0)
    html = open_element_form(pa_client, course, el)
    assert f'data-sgate-min="{_MIN_OPTIONS}"' in html
```

Note `data["option"]` is a **list** — Django's test client encodes a list as repeated keys, which is
what `getlist("option")` reads. Passing a string would post one option and the test would pass for
the wrong reason.

- [ ] **Step 6: Run**

```bash
uv run pytest tests/test_switchgate_client_post_shapes.py -v
uv run pytest tests/test_e2e_switchgate_rows.py -m e2e -v
```

Expected: all PASS.

- [ ] **Step 7: Falsify the renumbering test**

Comment out the `radio.value = String(i)` line in `renumber()` and confirm `test_removing_a_middle_option_keeps_the_right_answer` FAILS with the wrong option marked correct — the failure mode, not the assertion. Restore.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(editor): add/remove options in the Choose & confirm editor"
```

---

### Task 7: Cross-cutting behavioural e2e

The mechanisms that only appear when the pieces interact. Each of these covers something no per-editor test reaches.

**Files:**
- Test: `tests/test_e2e_editor_row_mechanics.py` (create)

- [ ] **Step 1: Write the tests**

```python
"""Mechanisms that only appear when the pieces interact.

EVERY test below carries the full harness written out — no abbreviation. The
per-test @pytest.mark.django_db(transaction=True) is load-bearing: conftest's
autouse _enable_db_access(db) otherwise supplies a NON-transactional db, and the
live_server thread then sees none of the seeded rows. That is the single most
common way this repo's e2e fail."""

import os

import pytest

pytestmark = pytest.mark.e2e

SAVE = "[data-edit-slot] button[type='submit']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_post_init_state(page, live_server, open_matchpair_editor_e2e):
    """The JS half of the progressive-enhancement guarantee."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=2)
    row = page.locator("[data-fsrow-item]").first
    assert not row.locator("[data-fsrow-del]").is_visible()
    assert row.locator("[data-fsrow-remove]").is_visible()


@pytest.mark.django_db(transaction=True)
def test_focus_after_removal_formset(page, live_server, open_matchpair_editor_e2e):
    """Blank row on purpose: no confirm fires, so NO dialog handler. A filled row
    would need one, and getting that wrong makes this RED on a correct build."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=4)
    rows = page.locator("[data-fsrow-item]")
    rows.nth(4).locator("[data-fsrow-remove]").click()   # an extra=2 blank
    assert page.evaluate("document.activeElement.tagName") != "BODY"


@pytest.mark.django_db(transaction=True)
def test_focus_after_removal_switchgate(page, live_server, open_switchgate_editor):
    """The variant that covers capture-before-detach: module 2 removes the row from
    the DOM, so neighbours resolved afterwards would all be null."""
    open_switchgate_editor(page, live_server, options=[])
    page.locator("[data-sgate-row]").nth(2).locator("[data-sgate-remove]").click()
    assert page.evaluate("document.activeElement.tagName") != "BODY"


@pytest.mark.django_db(transaction=True)
def test_at_minimum_hint(page, live_server, open_choice_editor):
    """A fresh choice question renders exactly extra=2 rows = data-fsrows-min."""
    open_choice_editor(page, live_server, options=[])
    assert page.locator("[data-fsrow-remove]").first.is_disabled()
    assert page.locator("[data-fsrows-hint]").is_visible()


@pytest.mark.django_db(transaction=True)
def test_maximum_cap_and_its_residual_hole(page, live_server, open_stepper_editor_e2e):
    open_stepper_editor_e2e(page, live_server, steps=[f"step {i}" for i in range(20)])
    assert page.locator("[data-fsrows-add]").is_disabled()
    assert page.locator("[data-fsrows-hint]").is_visible()
    # The accepted residual hole: extra=1 renders a 21st row the author can type
    # into without touching Add. Pinned so the limitation is documented, not assumed.
    page.locator("[data-fsrows-list] li").last.locator('input[type="text"]').fill("21st")
    page.locator(SAVE).click()
    # wait_for BEFORE count(): the save is a fetch + fragment swap, so counting
    # immediately after the click reads the pre-save DOM and returns 0.
    page.locator("text=at most 20").first.wait_for(timeout=8000)
    assert page.locator("text=at most 20").count() == 1


@pytest.mark.django_db(transaction=True)
def test_422_reconciliation(page, live_server, open_matchpair_editor_e2e):
    """Remove a row, fail validation, and the removed row must come back NOT
    VISIBLE with its DELETE still ticked — the server re-renders from the POST and
    knows nothing about row.hidden."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=3)
    page.on("dialog", lambda d: d.accept())
    row = page.locator("[data-fsrow-item]").nth(1)
    row.locator("[data-fsrow-remove]").click()
    page.locator("[data-fsrow-item]").nth(0).locator('input[name$="-right"]').fill("")
    page.locator(SAVE).click()
    # Wait on the ERROR, not the preview: this save is expected to fail, so the
    # preview never changes — and [data-scope="preview"] already exists, so waiting
    # on it returns instantly and the assertions below would read the pre-swap DOM.
    page.locator("[data-edit-slot] .field-error").first.wait_for(timeout=8000)
    back = page.locator("[data-fsrow-item]").nth(1)
    assert not back.is_visible()
    assert back.locator('input[name$="-DELETE"]').is_checked()


@pytest.mark.django_db(transaction=True)
def test_422_minimum_floor(page, live_server, open_choice_editor):
    """The dead-end guard. Written via page.evaluate because the obvious phrasing
    is not executable: java_script_enabled is per-CONTEXT and cannot be flipped
    mid-page, and the 422 body is a POST response that cannot be re-fetched."""
    open_choice_editor(page, live_server, options=["a", "b"])
    page.evaluate(
        "document.querySelectorAll('[name$=\\'-DELETE\\']')"
        ".forEach(function (d) { d.checked = true; })"
    )
    page.locator(SAVE).click()
    # Expected to fail validation ("Add at least two choices."), so wait on the error.
    page.locator("[data-edit-slot] .field-error").first.wait_for(timeout=8000)
    visible = page.locator("[data-fsrow-item]:visible")
    assert visible.count() >= 2
    assert not visible.first.locator('input[name$="-DELETE"]').is_checked()
```

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/test_e2e_editor_row_mechanics.py -m e2e -v
```

- [ ] **Step 3: Falsify the minimum floor**

Remove the `if (keepVisible < min)` branch from init job 2, confirm `test_422_minimum_floor` FAILS with zero visible rows, then restore. This is the test whose absence would let an unrecoverable editor ship.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_editor_row_mechanics.py
git commit -m "test(editor): cover 422 reconciliation, bounds, focus and the min floor"
```

---

### Task 8: Translations, catalogs and final formatting

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` + `.mo`, `locale/en/LC_MESSAGES/django.po` + `.mo`
- Modify: `tests/test_i18n_stepper.py` (extend)

- [ ] **Step 1: Extract the new strings**

```bash
uv run python manage.py makemessages -l pl -l en --no-obsolete
```

**Exactly eleven new msgids.** gettext deduplicates identical strings, so count *distinct* ones:

- **four confirm strings**: "Remove this pair?", "Remove this step?", "Remove this item?",
  "Remove this option?" — choice and switchgate share the last one, so it is one msgid, not two;
- **five at-min strings**, worded per editor: "at least one …" for match/stepper/checklist, "at
  least two …" for choice/switchgate;
- **two at-cap strings**: "No room for another step." / "No room for another item."

**Already in the catalog — do not add them, and do not assert the `＋` forms.** The `＋` sits
*outside* the `{% trans %}` tag in every template (`＋ {% trans "Add pair" %}`), so the msgids are
`Add pair` / `Add step` / `Add item` / `Add option` with no `＋`. All four already ship
(`_edit_stepper.html:26`, `_edit_markdone.html:26`, `_edit_choicequestion.html:47`,
`_edit_matchpairquestion.html:23`), as do `Remove` and `Remove option`
(`_edit_switchgrid.html:30`) — the last serving both switchgate's `aria-label` and its `title`, one
msgid either way. A catalog guard written against `"＋ Add step"` asserts a msgid that can never
exist.

Confirm the roster against `makemessages`' actual output before writing the guard.

- [ ] **Step 2: Translate and clear every fuzzy flag**

Fill in the Polish translations. `makemessages` fuzzy-prefills a *wrong* translation from a similar string — clearing a fuzzy entry is **two** deletions (the `#, fuzzy` line and the wrong `msgstr`). Verify:

```bash
grep -c "fuzzy" locale/pl/LC_MESSAGES/django.po   # expect 0
grep -c "#~" locale/pl/LC_MESSAGES/django.po      # expect 0 (no obsolete)
```

- [ ] **Step 3: Extend the catalog guard**

Add the new msgids to `tests/test_i18n_stepper.py` (or a sibling), asserting each has a non-empty Polish `msgstr`.

- [ ] **Step 4: Compile**

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 5: Format**

```bash
uv run ruff format .
uv run ruff check .
```

Run this **last** — CI gates on `ruff format --check` and any later edit re-dirties the files.

- [ ] **Step 6: Run the affected-test selection, then the branch gate**

```bash
uv run python scripts/affected_tests.py          # ~30s targeted selection
uv run pytest tests/ courses/tests/ -q --verbosity=0
```

Then the e2e branch gate — **detached**, not in the foreground. The full e2e suite runs far past any
single tool timeout here, and a reaped run orphans the test database so the next invocation dies with
`DuplicateDatabase`:

```powershell
Start-Process -NoNewWindow -PassThru uv -ArgumentList 'run','pytest','-m','e2e','-n','2','-q','--verbosity=0'
# poll the returned PID; do not foreground this
```

Before the next pytest call, confirm no orphaned `test_libli_*` database remains.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore(i18n): add Polish translations for the new editor row strings"
```

---

## Self-review notes

**Spec coverage.** Every spec section maps to a task: CSS guards + `display: contents` + switchgate twins → T1; module 1 + wiring + scroll roster → T2; match template, blueprint, PE render, bounds, characterization POSTs, headline e2e → T3; stepper/checklist retrofit, module retirement, four retargeted tests, retrofit e2e → T4; choice wiring, `addChoiceRow`'s seven amendments, dead-code removal, rewritten e2e → T5; module 2 + switchgate template + its e2e → T6; 422 reconciliation, 422 floor, both focus variants, max cap, at-min hint, post-init state → T7; i18n + ruff → T8.

**Resolved while writing this plan:** the bounds constants are reachable from the template as
`{{ form.instance.MIN_STEPS }}` etc., because both forms are `ModelForm`s over the model that carries
them — so no view context and no application Python is needed. That was the only thing in this plan
that risked breaching the "no application Python is modified" constraint.

**One open item for the implementer** (flagged rather than guessed): this plan names fixtures
(`open_matchpair_editor`, `pa_client`, `matchpair_element`, `open_element_editor`,
`open_switchgate_editor`, …) that must be built from the existing patterns in
`tests/test_editor_stepper_add.py`, `tests/test_questions_2d_matchpair_form.py` and
`tests/test_e2e_questions.py`. Reuse those helpers rather than inventing parallel ones; the exact
signatures depend on what those files already expose.

**Falsification ledger.** RED-first: the match add e2e (T3), the retrofit *remove* half (T4), the switchgate trio (T6), and every T7 mechanism test. Explicitly exempt: the retrofit *add* half (GREEN-on-master no-regression, located by visible label) and the three characterization POST tests (T3, T6) — no application Python changes, so no mutant exists.
