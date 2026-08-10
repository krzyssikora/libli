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
- **`focus()` is always `focus({ preventScroll: true })`, preceded by `window.libliAlignTopInPane`.** `scrollIntoView` is forbidden in these modules.
- **Every `hidden` element whose class sets `display` needs an explicit `[hidden] { display: none }` guard.**
- **Init passes must be idempotent** and must accept *either* an ancestor node or the wrapper itself (`root.matches(SEL) ? [root] : root.querySelectorAll(SEL)`).
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

HIDDEN_NONE = r"\{[^}]*display:\s*none[^}]*\}"


def _has_rule(css: str, selector: str, body: str = HIDDEN_NONE) -> bool:
    return re.search(re.escape(selector) + r"\s*" + body, css) is not None


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
    block = match.group(1)
    assert "inline-grid" in block, "style twin must set display: inline-grid"
    assert "flex:" in block, "style twin must set flex: 0 0 auto or the x shrinks"


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

```css
/* Switchgate reuses switchgrid's x component, but every rule for it is scoped to
   .el-editor--switchgrid, so a bare class inherits nothing. Duplicated under a
   scope rather than promoted to an unscoped rule: promoting would restyle
   switchgrid as a side effect, and an unscoped .el-editor__remove[hidden] ties on
   specificity with the block above, leaving the outcome to source order. */
.el-editor--switchgate .el-editor__remove {
  flex: 0 0 auto;
  /* ...copy the remaining declarations from .el-editor--switchgrid
     .el-editor__remove at :1452 verbatim, including display: inline-grid... */
}
/* inline-grid overrides the [hidden] attribute, so hide explicitly (JS toggles it) */
.el-editor--switchgate .el-editor__remove[hidden] { display: none; }
.el-editor--switchgate .el-editor__remove:hover { /* copy from :1470 */ }
.el-editor--switchgate .el-editor__remove:focus-visible { /* copy from :1475 */ }
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
uv run pytest tests/test_editor_row_css_guards.py -v
```

Expected: 7 PASSED.

- [ ] **Step 7: Falsify the guard**

Delete the `.stepper-row[hidden]` selector from `courses.css`, re-run, confirm `test_row_hidden_guards_in_courses_css` FAILS, then restore it. A guard test that cannot fail is worthless.

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
- Modify: `tests/test_editor_js_scroll_invariants.py:24-40`
- Test: `tests/test_formset_rows_assets.py` (create)

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
    wrap.querySelectorAll("[data-fsrow-item]").forEach(function (row) {
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

- [ ] **Step 5: Add both new modules to the scroll-invariant roster and add the focus regex**

In `tests/test_editor_js_scroll_invariants.py`, add `"formset_rows.js"` and `"switchgate_editor.js"` to `PANE_RESIDENT` (do **not** remove `stepper_editor.js` / `markdone_editor.js` yet — Task 4 does that), and append:

```python
# Bare focus() scrolls every ancestor scrollport, and this page's viewport is
# overflow:hidden. Scoped to the two NEW modules on purpose: 19 pre-existing call
# sites across filltable_editor.js, table_editor.js, gallery_editor.js,
# text_toolbar.js and tabs_editor.js would make a repo-wide version RED on arrival,
# and fixing those is separate work.
FOCUS_OPT_IN = ["formset_rows.js", "switchgate_editor.js"]
FOCUS_CALL = re.compile(r"\.focus\s*\(\s*(?!\{[^)]*preventScroll)")


def test_new_modules_never_focus_without_preventscroll():
    offenders = {}
    for name in FOCUS_OPT_IN:
        path = JS_DIR / name
        if not path.exists():
            continue  # module lands in a later task
        hits = [
            i
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if FOCUS_CALL.search(line) and not line.strip().startswith("//")
        ]
        if hits:
            offenders[name] = hits
    assert not offenders, (
        f"bare focus() in {offenders}: use focus({{ preventScroll: true }}), "
        "preceded by window.libliAlignTopInPane(el)"
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
- Produces: the match template as the reference shape every other formset template copies.

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

from courses.models import MarkDoneElement
from courses.models import StepperElement

pytestmark = pytest.mark.django_db


def rendered_rows(html: str):
    """Rows actually in the list — blueprint content removed first."""
    soup = BeautifulSoup(html, "html.parser")
    for tmpl in soup.select("template"):
        tmpl.decompose()
    listing = soup.select_one("[data-fsrows-list]")
    return listing.select("[data-fsrow-item]") if listing else []


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
        <label class="pair-row__del" data-fsrow-del>{{ formset.empty_form.DELETE }} {% trans "Remove" %}</label>
        <button type="button" class="btn btn--small btn--ghost"
                data-fsrow-remove hidden>{% trans "Remove" %}</button>
      </li>
    </template>
  </div>
```

- [ ] **Step 4: Run the render tests**

```bash
uv run pytest tests/test_editor_formset_rows_render.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Add the characterization POST tests**

Create `tests/test_matchpair_client_post_shapes.py`. These pin the "No server changes" claim — they are green on `master` by design and are a stated falsification exception.

```python
"""Characterization tests: the POST shapes formset_rows.js emits are already
accepted by the unmodified server. Green on master by design (no application
Python changes), so they are a stated exception to the RED-before-fix rule. Their
job is to catch a FUTURE parser change that would break the editors."""

import pytest

pytestmark = pytest.mark.django_db


def test_more_rows_than_were_rendered_all_save(pa_client, matchpair_element):
    """The path that is unreachable today: the Add button has no handler, so the
    POST can never carry more forms than the server rendered."""
    el = matchpair_element(pairs=[("a", "1"), ("b", "2")])
    data = {
        "type": "matchpairquestion", "element": el.pk, "stem": "",
        "pairs-TOTAL_FORMS": "5", "pairs-INITIAL_FORMS": "2",
        "pairs-MIN_NUM_FORMS": "0", "pairs-MAX_NUM_FORMS": "1000",
    }
    for i, (left, right) in enumerate([("a", "1"), ("b", "2"), ("c", "3"), ("d", "4"), ("e", "5")]):
        data[f"pairs-{i}-left"] = left
        data[f"pairs-{i}-right"] = right
    for i, pair in enumerate(el.pairs.all()):
        data[f"pairs-{i}-id"] = pair.pk
    resp = pa_client.post(save_url(el), data)
    assert resp.status_code == 200
    el.refresh_from_db()
    assert el.pairs.count() == 5


def test_ticked_delete_removes_exactly_that_pair(pa_client, matchpair_element):
    el = matchpair_element(pairs=[("a", "1"), ("b", "2"), ("c", "3")])
    pairs = list(el.pairs.all())
    data = {
        "type": "matchpairquestion", "element": el.pk, "stem": "",
        "pairs-TOTAL_FORMS": "3", "pairs-INITIAL_FORMS": "3",
        "pairs-MIN_NUM_FORMS": "0", "pairs-MAX_NUM_FORMS": "1000",
        "pairs-1-DELETE": "on",
    }
    for i, p in enumerate(pairs):
        data[f"pairs-{i}-id"] = p.pk
        data[f"pairs-{i}-left"] = p.left
        data[f"pairs-{i}-right"] = p.right
    resp = pa_client.post(save_url(el), data)
    assert resp.status_code == 200
    assert sorted(p.left for p in el.pairs.all()) == ["a", "c"]
```

Add `pa_client`, `matchpair_element` and `save_url` helpers to `tests/conftest.py`, following `tests/test_questions_2d_matchpair_form.py` for the field names and `courses:manage_element_save` for the URL.

- [ ] **Step 6: Run them**

```bash
uv run pytest tests/test_matchpair_client_post_shapes.py -v
```

Expected: 2 PASSED (green on master — that is the point).

- [ ] **Step 7: Write the e2e tests**

Create `tests/test_e2e_matchpair_rows.py`:

```python
"""e2e for the reported defect. The add test is RED on master by construction:
the ＋ Add pair button has never had a handler."""

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.e2e]


def test_add_three_pairs_without_saving(page, open_matchpair_editor_e2e):
    """The whole point: three new pairs in ONE session, no save-and-reopen."""
    page = open_matchpair_editor_e2e(saved_pairs=2)
    add = page.locator("[data-fsrows-add]")
    for _ in range(3):
        add.click()
    rows = page.locator("[data-fsrows-list] [data-fsrow-item]")
    # extra=2 blanks + 3 added = 7 rendered rows; fill the last three.
    for i, (left, right) in enumerate([("x", "9"), ("y", "8"), ("z", "7")], start=4):
        rows.nth(i).locator('input[name$="-left"]').fill(left)
        rows.nth(i).locator('input[name$="-right"]').fill(right)
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
    reopen_matchpair(page)
    assert page.locator("[data-fsrows-list] [data-fsrow-item] input[name$='-left']").count() >= 5


def test_remove_a_filled_pair(page, open_matchpair_editor_e2e):
    page = open_matchpair_editor_e2e(saved_pairs=3)
    # Playwright AUTO-DISMISSES confirm: without this handler the removal takes
    # the cancel path and the test fails against a CORRECT build.
    page.on("dialog", lambda d: d.accept())
    row = page.locator("[data-fsrows-list] [data-fsrow-item]").nth(1)
    row.locator("[data-fsrow-remove]").click()
    # A hidden row is still matched by count() — assert on VISIBILITY.
    assert not row.is_visible()
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
    reopen_matchpair(page)
    assert page.locator("[data-fsrows-list] [data-fsrow-item] input[name$='-left']").count() == 4
```

Model the fixtures on the existing e2e editor helpers (e.g. `tests/test_e2e_questions.py`), and reuse this repo's save/reopen helpers rather than inventing new ones.

- [ ] **Step 8: Falsify the add test against master, then run it**

```bash
git stash push -u -m "falsify-matchpair-add"
uv run pytest tests/test_e2e_matchpair_rows.py::test_add_three_pairs_without_saving -m e2e -v   # expect FAIL
git stash list --format='%H %gs'    # capture the SHA, then: git stash apply <sha>; git stash drop
uv run pytest tests/test_e2e_matchpair_rows.py -m e2e -v                                        # expect PASS
```

(Prefer a temporary WIP commit to stashing — the stash stack is shared across worktrees.)

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


@pytest.mark.parametrize("kind,label", [("stepper", "Add step"), ("markdone", "Add item")])
def test_add_row_still_works_after_retrofit(page, open_element_editor, kind, label):
    """GREEN on master AND after: proves the rewiring did not break a working editor.
    Located by visible label on purpose — the data hook changes in this commit."""
    page = open_element_editor(kind)
    page.get_by_role("button", name=label).click()
    rows = page.locator("[data-fsrows-list] li")
    rows.last.locator('input[type="text"]').fill("retrofit row")
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
    reopen(page, kind)
    assert page.get_by_display_value("retrofit row").count() == 1


@pytest.mark.parametrize("kind", ["stepper", "markdone"])
def test_remove_row_after_retrofit(page, open_element_editor, kind):
    """RED on master: there is no per-row remove BUTTON there, only a checkbox."""
    page = open_element_editor(kind, rows=["one", "two", "three"])
    page.on("dialog", lambda d: d.accept())   # persisted rows are non-blank
    row = page.locator("[data-fsrows-list] li").nth(1)
    row.locator("[data-fsrow-remove]").click()
    assert not row.is_visible()
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
    reopen(page, kind)
    assert page.get_by_display_value("two").count() == 0
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
       data-fsrows-min="{{ min_steps }}"
       data-fsrows-max="{{ max_steps }}"
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
        <label class="stepper-row__del" data-fsrow-del>{{ formset.empty_form.DELETE }} {% trans "Remove" %}</label>
        <button type="button" class="btn btn--small btn--ghost"
                data-fsrow-remove hidden>{% trans "Remove" %}</button>
      </li>
    </template>
  </div>
</div>
```

**Use `{{ form.instance.MIN_STEPS }}` / `{{ form.instance.MAX_STEPS }}` directly** — no view change and no new context variable. `StepperElementForm` is a `ModelForm` over `StepperElement` (`element_forms.py:1857-1860`), so `form.instance` is a `StepperElement` and Django's template attribute lookup resolves the class constants (`courses/models.py:618-619`) on it. This keeps the "no application Python is modified" constraint intact, and it is what makes the bounds-render test's constant comparison meaningful rather than literal-vs-literal.

So the wrapper reads:

```html
       data-fsrows-min="{{ form.instance.MIN_STEPS }}"
       data-fsrows-max="{{ form.instance.MAX_STEPS }}"
```

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

- `tests/test_stepper_editor_assets.py`: point at `formset_rows.js` / `libliInitFormsetRows`; **delete** the `steps-TOTAL_FORMS` assertion (a prefix-agnostic helper can never contain it) and the `stepper_editor.js` page assertion. The `__prefix__` coverage now lives in the blueprint-render test.
- `courses/tests/test_markdone_editor.py:20,30`: `data-markdone-editor` → `data-fsrows="items"`; `courses/js/markdone_editor.js` → `courses/js/formset_rows.js`.
- `tests/test_editor_stepper_add.py:27-28`: `data-stepper-editor` → `data-fsrows="steps"`, `data-stepper-row` → `data-fsrow-item>` (delimited).
- `tests/test_editor_js_scroll_invariants.py`: remove `stepper_editor.js` and `markdone_editor.js` from `PANE_RESIDENT`.

- [ ] **Step 7: Extend the render tests to stepper and checklist**

Add to `tests/test_editor_formset_rows_render.py`:

```python
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
```

- [ ] **Step 8: Run the affected suites**

```bash
uv run pytest tests/test_stepper_editor_assets.py courses/tests/test_markdone_editor.py tests/test_editor_stepper_add.py tests/test_editor_js_scroll_invariants.py tests/test_editor_formset_rows_render.py -v
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
- Modify: `courses/static/courses/js/editor.js` (`addChoiceRow` at `:419-443`; delete `:439`, `:492`, `:493-497`)
- Modify: `courses/static/courses/css/editor.css` (delete `:176-179`)
- Modify: `tests/test_e2e_questions.py` (`:262` docstring, `:310-317`)

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

Keep `class="choice-rows" data-choice-rows` **and add** `data-fsrows-list` to the `<ul>`; keep `data-choice-row` **and add** `data-fsrow-item` on each `<li>`; add `data-fsrow-del` to the `<label class="choice-row__del">`; add the remove button after it; keep `data-choice-add` on the add button and add `hidden`; add the `data-fsrows-hint` carrier. Choice has **no** `data-fsrows-add` and **no** `<template>` — they are optional and must be absent together.

- [ ] **Step 2: Amend `addChoiceRow`**

Seven changes at `editor.js:419-443`:

```js
  // Called with the clicked [data-choice-add] button so the wrapper is in hand;
  // resolving it from `root` would reintroduce the cross-talk closest() prevents.
  function addChoiceRow(btn) {
    var wrap = btn.closest("[data-fsrows]");
    if (!wrap) return;
    var list = wrap.querySelector("[data-fsrows-list]");
    var total = wrap.querySelector('input[name="choices-TOTAL_FORMS"]');
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
    // ...existing renumbering of name/id via /([-_])\d+([-_])/ ...
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

- [ ] **Step 4: Rewrite the broken e2e**

In `tests/test_e2e_questions.py`, replace the `:310-317` block:

```python
    # The DELETE checkbox now sits inside a hidden label, so .check() would fail
    # actionability. Drive the JS control instead.
    page.on("dialog", lambda d: d.accept())   # row was filled with "Gamma" at :301
    row2.locator("[data-fsrow-remove]").click()
    assert not row2.is_visible()
    assert row2.locator("input[name='choices-2-DELETE']").is_checked()
```

and remove `- "Remove" gives live feedback (row dims) before save;` from the docstring at `:262`.

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
- Test: `tests/test_switchgate_client_post_shapes.py`, `tests/test_e2e_switchgate_rows.py` (create)

**Interfaces:**
- Consumes: the CSS twins from Task 1.
- Produces: `window.libliInitSwitchGateEditor(root)` — four idempotent jobs (reveal, disabled state, hint, renumber).

- [ ] **Step 1: Write the failing e2e**

Create `tests/test_e2e_switchgate_rows.py`:

```python
import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.e2e]


def test_add_option_beyond_the_padded_blanks(page, open_switchgate_editor):
    page = open_switchgate_editor(options=["two", "three", "four"])
    before = page.locator("[data-sgate-row]").count()
    page.locator("[data-sgate-add]").click()
    assert page.locator("[data-sgate-row]").count() == before + 1


def test_removing_a_middle_option_keeps_the_right_answer(page, open_switchgate_editor):
    """The renumbering test: if the radio values are not rewritten, `answer` points
    at the wrong option and the question silently marks the wrong choice correct."""
    page = open_switchgate_editor(options=["alpha", "beta", "gamma"], answer=2)
    page.on("dialog", lambda d: d.accept())   # filled row -> confirm fires
    page.locator("[data-sgate-row]").nth(1).locator("[data-sgate-remove]").click()
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
    el = reload_switchgate()
    assert el.options[el.answer] == "gamma"


def test_removing_an_interior_blank_lets_the_save_succeed(page, open_switchgate_editor):
    """Today this is a dead end: clean() rejects interior blanks and there is no
    remove control, so an author who fills rows 1, 2 and 6 cannot save at all."""
    page = open_switchgate_editor(options=[])
    rows = page.locator("[data-sgate-row]")
    rows.nth(0).locator('input[name="option"]').fill("first")
    rows.nth(1).locator('input[name="option"]').fill("second")
    rows.nth(5).locator('input[name="option"]').fill("sixth")
    rows.nth(0).locator('input[name="answer"]').check()
    # Blank rows are removed WITHOUT a confirm — no dialog handler on purpose.
    for i in (4, 3, 2):
        rows.nth(i).locator("[data-sgate-remove]").click()
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
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
    wrap.querySelectorAll("[data-sgate-add], [data-sgate-remove]").forEach(function (b) {
      b.hidden = false;
    });
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

Add the script tag to `editor.html` with the customary `{% comment %}`.

- [ ] **Step 5: Add the switchgate characterization test**

Create `tests/test_switchgate_client_post_shapes.py` — a POST with a middle option removed and `answer` renumbered stores the intended option as correct. Green on master (a stated falsification exception).

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
"""Mechanisms that only appear when the pieces interact."""

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.e2e]


def test_post_init_state(page, open_matchpair_editor_e2e):
    """The JS half of the progressive-enhancement guarantee."""
    page = open_matchpair_editor_e2e(saved_pairs=2)
    row = page.locator("[data-fsrow-item]").first
    assert not row.locator("[data-fsrow-del]").is_visible()
    assert row.locator("[data-fsrow-remove]").is_visible()


def test_focus_after_removal_formset(page, open_matchpair_editor_e2e):
    """Blank row on purpose: no confirm fires, so NO dialog handler. A filled row
    would need one, and getting that wrong makes this RED on a correct build."""
    page = open_matchpair_editor_e2e(saved_pairs=4)
    rows = page.locator("[data-fsrow-item]")
    rows.nth(4).locator("[data-fsrow-remove]").click()   # an extra=2 blank
    assert page.evaluate("document.activeElement.tagName") != "BODY"


def test_focus_after_removal_switchgate(page, open_switchgate_editor):
    """The variant that covers capture-before-detach: module 2 removes the row from
    the DOM, so neighbours resolved afterwards would all be null."""
    page = open_switchgate_editor(options=[])
    page.locator("[data-sgate-row]").nth(2).locator("[data-sgate-remove]").click()
    assert page.evaluate("document.activeElement.tagName") != "BODY"


def test_at_minimum_hint(page, open_choice_editor):
    """A fresh choice question renders exactly extra=2 rows = data-fsrows-min."""
    page = open_choice_editor(options=[])
    assert page.locator("[data-fsrow-remove]").first.is_disabled()
    assert page.locator("[data-fsrows-hint]").is_visible()


def test_maximum_cap_and_its_residual_hole(page, open_stepper_editor_e2e):
    page = open_stepper_editor_e2e(steps=[f"step {i}" for i in range(20)])
    assert page.locator("[data-fsrows-add]").is_disabled()
    assert page.locator("[data-fsrows-hint]").is_visible()
    # The accepted residual hole: extra=1 renders a 21st row the author can type
    # into without touching Add. Pinned so the limitation is documented, not assumed.
    page.locator("[data-fsrows-list] li").last.locator('input[type="text"]').fill("21st")
    page.click("[data-el-save]")
    assert page.locator("text=at most 20").count() == 1


def test_422_reconciliation(page, open_matchpair_editor_e2e):
    """Remove a row, fail validation, and the removed row must come back NOT
    VISIBLE with its DELETE still ticked — the server re-renders from the POST and
    knows nothing about row.hidden."""
    page = open_matchpair_editor_e2e(saved_pairs=3)
    page.on("dialog", lambda d: d.accept())
    row = page.locator("[data-fsrow-item]").nth(1)
    row.locator("[data-fsrow-remove]").click()
    page.locator("[data-fsrow-item]").nth(0).locator('input[name$="-right"]').fill("")
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
    back = page.locator("[data-fsrow-item]").nth(1)
    assert not back.is_visible()
    assert back.locator('input[name$="-DELETE"]').is_checked()


def test_422_minimum_floor(page, open_choice_editor):
    """The dead-end guard. Written via page.evaluate because the obvious phrasing
    is not executable: java_script_enabled is per-CONTEXT and cannot be flipped
    mid-page, and the 422 body is a POST response that cannot be re-fetched."""
    page = open_choice_editor(options=["a", "b"])
    page.evaluate(
        "document.querySelectorAll('[name$=\\'-DELETE\\']')"
        ".forEach(function (d) { d.checked = true; })"
    )
    page.click("[data-el-save]")
    page.wait_for_load_state("networkidle")
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

New strings: five confirm strings, the add labels, the remove buttons' labels/`aria-label`s plus `title` on switchgate's `×`, **five at-min strings** (worded per editor — "at least one" for match/stepper/checklist, "at least two" for choice/switchgate) and **two at-cap strings**.

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
uv run pytest -m e2e -n 2 -q --verbosity=0
```

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
