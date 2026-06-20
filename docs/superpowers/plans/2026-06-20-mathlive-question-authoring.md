# MathLive Question Authoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let teachers insert mathematics into question stems, choices, accepted answers, and explanations using a MathLive visual equation editor (or raw LaTeX), with the result stored as inline `\(...\)` LaTeX and rendered live in the editor preview.

**Architecture:** Vendor the MathLive library under `static/courses/vendor/mathlive/`. A single reusable bespoke modal hosts a MathLive `<math-field>` (which is simultaneously a WYSIWYG editor and a LaTeX entry surface). A "∑" trigger opens the modal; on **Insert** the field's LaTeX value is wrapped as `\(…\)` and dropped at the caret of the active target. Two integration surfaces: (1) the shared RTE toolbar (covers stem + explanation for every question type, since both are `data-rte-source` contenteditable surfaces); (2) plain `<input>`/`<textarea>` fields (choice text, accepted answers) get an inline ∑ button + a live KaTeX preview. Storage is unchanged — `\(…\)` is plain text, sanitised on save, and rendered by the existing KaTeX auto-render path (now also active in the preview, per the prior commit).

**Tech Stack:** Django templates, vanilla JS (no framework), MathLive (vendored), KaTeX (already vendored), pytest + Playwright.

## Global Constraints

- Bespoke, token-driven CSS; no Bootstrap/React. MathLive is the only new third-party dependency (explicitly approved); style its host modal with existing CSS tokens. — see [[ui-foundation-bespoke-from-bonnot]]
- Progressive enhancement: with JS off, every field remains a plain input/textarea that submits raw text; the ∑/widget is an enhancement only.
- All new user-facing strings use `{% trans %}` / `gettext` and MUST have non-fuzzy Polish translations; the `locale/pl` catalog must stay clean (no `#, fuzzy`, no `#~`) — gate: `tests/test_i18n_auth.py::test_po_catalog_clean`.
- Python lints clean under `ruff` (line length 88).
- Editor runs with `DEBUG=False` locally → **restart the dev server after template changes** (cached template loader).
- Stored math is inline `\(LATEX\)`; never change the storage/sanitisation contract. `sanitize_html` must preserve `\(...\)` text (verify in Task 0).
- New translatable strings introduced by this plan: `"Insert math"`, `"Insert"`, `"Cancel"`, `"Math"`. Add PL translations in the task that introduces them.

---

## Task 0: Vendor MathLive + load it on the editor page

**Files:**
- Create: `courses/static/courses/vendor/mathlive/mathlive.min.js` (downloaded)
- Create: `courses/static/courses/vendor/mathlive/fonts/…` (downloaded font assets)
- Modify: `templates/courses/manage/editor/editor.html` (script include)
- Test: `tests/test_mathlive_assets.py`

**Interfaces:**
- Produces: a globally-registered `<math-field>` custom element and `window.MathfieldElement` on the editor page.

- [ ] **Step 1: Download the library + fonts into the vendor dir**

```bash
mkdir -p courses/static/courses/vendor/mathlive/fonts courses/static/courses/vendor/mathlive/sounds
curl -sL https://cdn.jsdelivr.net/npm/mathlive/dist/mathlive.min.js \
  -o courses/static/courses/vendor/mathlive/mathlive.min.js
# Fonts (MathLive needs these to render). Pull the dist fonts listing and fetch each.
# The font set is stable; fetch the known files:
for f in KaTeX_AMS-Regular.woff2 KaTeX_Caligraphic-Bold.woff2 KaTeX_Caligraphic-Regular.woff2 \
  KaTeX_Fraktur-Bold.woff2 KaTeX_Fraktur-Regular.woff2 KaTeX_Main-Bold.woff2 KaTeX_Main-BoldItalic.woff2 \
  KaTeX_Main-Italic.woff2 KaTeX_Main-Regular.woff2 KaTeX_Math-BoldItalic.woff2 KaTeX_Math-Italic.woff2 \
  KaTeX_SansSerif-Bold.woff2 KaTeX_SansSerif-Italic.woff2 KaTeX_SansSerif-Regular.woff2 \
  KaTeX_Script-Regular.woff2 KaTeX_Size1-Regular.woff2 KaTeX_Size2-Regular.woff2 KaTeX_Size3-Regular.woff2 \
  KaTeX_Size4-Regular.woff2 KaTeX_Typewriter-Regular.woff2; do
  curl -sL "https://cdn.jsdelivr.net/npm/mathlive/dist/fonts/$f" -o "courses/static/courses/vendor/mathlive/fonts/$f"
done
```

Note: if the standalone `mathlive.min.js` is ESM-only (no global), fall back to the global build name `https://cdn.jsdelivr.net/npm/mathlive/dist/mathlive.min.js` is the UMD build that registers the element; verify in Step 4. If it is ESM, instead load with `<script type="module">` and `import 'mathlive'` is not possible from a vendored file without a bundler — in that case download `mathlive.min.mjs` and load via `<script type="module" src=...>`, which still auto-registers `<math-field>`.

- [ ] **Step 2: Write the asset-presence test**

```python
# tests/test_mathlive_assets.py
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "courses" / "static" / "courses" / "vendor" / "mathlive"


def test_mathlive_library_vendored():
    lib = VENDOR / "mathlive.min.js"
    assert lib.exists() and lib.stat().st_size > 100_000


def test_mathlive_fonts_vendored():
    fonts = list((VENDOR / "fonts").glob("*.woff2"))
    assert len(fonts) >= 15
```

- [ ] **Step 3: Run the test**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mathlive_assets.py -q`
Expected: PASS

- [ ] **Step 4: Load MathLive on the editor page + disable sounds, set fonts dir**

In `templates/courses/manage/editor/editor.html`, in `{% block extra_js %}`, add BEFORE `editor.js`:

```html
  <script src="{% static 'courses/vendor/mathlive/mathlive.min.js' %}" defer></script>
  <script>
    window.addEventListener("DOMContentLoaded", function () {
      // UMD build (v0.104.2) exposes window.MathLive; MathfieldElement may be on
      // window or under window.MathLive. Be tolerant.
      var MFE = window.MathfieldElement || (window.MathLive && window.MathLive.MathfieldElement);
      if (MFE) {
        MFE.fontsDirectory = "{% static 'courses/vendor/mathlive/fonts' %}";
        MFE.soundsDirectory = null;  // no keystroke sounds
      }
    });
  </script>
```

Confirmed at plan time: the dist is a UMD bundle (`global.MathLive = {}`) that auto-registers the `<math-field>` custom element on load — so the plain `<script defer>` include in Step 4 is correct; no `.mjs`/module fallback needed.

- [ ] **Step 5: Manually verify the custom element registers**

Run the dev server (`$env:DJANGO_SETTINGS_MODULE="config.settings.local"; .\.venv\Scripts\python.exe manage.py runserver 8000 --noreload`), open the editor, and in the browser console confirm: `customElements.get('math-field')` is defined and `window.MathfieldElement` exists. If undefined, switch to the `.mjs` module build per Step 1 note.

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/vendor/mathlive templates/courses/manage/editor/editor.html tests/test_mathlive_assets.py
git commit -m "chore(editor): vendor MathLive + load on the editor page"
```

---

## Task 1: The reusable math-input modal (`math_input.js`)

**Files:**
- Create: `courses/static/courses/js/math_input.js`
- Modify: `templates/courses/manage/editor/editor.html` (include `math_input.js` after `mathlive.min.js`, before `editor.js`)
- Modify: `courses/static/courses/css/editor.css` (modal + ∑ button + preview styles)
- Test: `tests/test_e2e_math_input.py` (Task 3 exercises it end-to-end; this task ships the API + a console-driveable smoke)

**Interfaces:**
- Produces: `window.libliMathInput.open(onInsert)` where `onInsert(latex)` is called with the field's LaTeX (no delimiters) when the user clicks Insert. The modal owns a single `<math-field>`, is created lazily, and is reused.
- Produces: CSS classes `.math-modal`, `.math-modal__backdrop`, `.math-modal__card`, `.math-modal__actions`, `.math-trigger`, `.math-preview`.

- [ ] **Step 1: Implement the modal module**

```javascript
// courses/static/courses/js/math_input.js
(function () {
  "use strict";
  var modal, field, cb;

  function build() {
    modal = document.createElement("div");
    modal.className = "math-modal";
    modal.hidden = true;
    modal.innerHTML =
      '<div class="math-modal__backdrop" data-math-cancel></div>' +
      '<div class="math-modal__card" role="dialog" aria-modal="true">' +
      '  <math-field class="math-modal__field"></math-field>' +
      '  <div class="math-modal__actions">' +
      '    <button type="button" class="btn btn--small" data-math-insert></button>' +
      '    <button type="button" class="btn btn--small btn--ghost" data-math-cancel></button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(modal);
    field = modal.querySelector("math-field");
    // Labels are injected from data-* on the editor root (i18n, set in Task 1 Step 3).
    var root = document.querySelector(".editor");
    modal.querySelector("[data-math-insert]").textContent =
      (root && root.getAttribute("data-msg-insert")) || "Insert";
    modal.querySelector("[data-math-cancel]").textContent =
      (root && root.getAttribute("data-msg-cancel")) || "Cancel";
    modal.addEventListener("click", function (e) {
      if (e.target.closest("[data-math-cancel]")) { close(); return; }
      if (e.target.closest("[data-math-insert]")) {
        var latex = (field.value || "").trim();
        close();
        if (latex && cb) cb(latex);
      }
    });
    document.addEventListener("keydown", function (e) {
      if (!modal.hidden && e.key === "Escape") close();
    });
  }

  function close() { if (modal) { modal.hidden = true; field.value = ""; } cb = null; }

  function open(onInsert) {
    if (!modal) build();
    cb = onInsert;
    field.value = "";
    modal.hidden = false;
    setTimeout(function () { field.focus(); }, 0);
  }

  window.libliMathInput = { open: open };
})();
```

- [ ] **Step 2: Style the modal, trigger button, and preview**

Append to `courses/static/courses/css/editor.css`:

```css
/* --- Math input widget --- */
.math-modal[hidden] { display: none; }
.math-modal { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; }
.math-modal__backdrop { position: absolute; inset: 0; background: rgba(0,0,0,.45); }
.math-modal__card {
  position: relative; background: var(--surface-default); color: var(--text-primary);
  border: 1px solid var(--border-default); border-radius: var(--radius-md);
  padding: var(--space-4); min-width: 22rem; box-shadow: var(--shadow-lg, 0 10px 40px rgba(0,0,0,.3));
  display: grid; gap: var(--space-3);
}
.math-modal__field {
  font-size: 1.25rem; padding: var(--space-2); border: 1px solid var(--border-default);
  border-radius: var(--radius-sm); background: var(--surface-sunken);
}
.math-modal__actions { display: flex; gap: var(--space-2); justify-content: flex-end; }
.math-trigger {
  display: inline-flex; align-items: center; justify-content: center; min-width: 1.9rem;
  padding: 0 var(--space-2); background: var(--surface-sunken); cursor: pointer;
  border: 1px solid var(--border-default); border-radius: var(--radius-sm); color: var(--text-primary);
}
.math-trigger:hover { border-color: var(--primary); color: var(--primary); }
.math-preview { font-size: .9rem; color: var(--text-secondary); min-height: 1.2em; }
.math-preview:empty { display: none; }
```

- [ ] **Step 3: Inject i18n labels onto the editor root**

In `templates/courses/manage/editor/editor.html`, find the `.editor` root element and add data attributes (alongside any existing `data-msg-*`):

```html
data-msg-insert="{% trans 'Insert' %}" data-msg-cancel="{% trans 'Cancel' %}" data-msg-math="{% trans 'Insert math' %}"
```

(If the `.editor` element is in a parent template/partial, add them there; grep for `class="editor"`.)

- [ ] **Step 4: Include the script**

In `editor.html` `{% block extra_js %}`, add after `mathlive.min.js` and before `editor.js`:

```html
  <script src="{% static 'courses/js/math_input.js' %}" defer></script>
```

- [ ] **Step 5: Add PL translations + compile**

Run `makemessages`, set non-fuzzy PL for `"Insert"`→`"Wstaw"`, `"Cancel"`→`"Anuluj"`, `"Insert math"`→`"Wstaw wzór"`, `"Math"`→(already `"Wzór"`), strip any fuzzy/obsolete, then `compilemessages`.

```bash
.\.venv\Scripts\python.exe manage.py makemessages -l pl -l en --no-obsolete
# edit locale/pl/LC_MESSAGES/django.po: clear #, fuzzy on the new entries, add msgstr
.\.venv\Scripts\python.exe manage.py compilemessages -l pl -l en
.\.venv\Scripts\python.exe -m pytest tests/test_i18n_auth.py -q
```

- [ ] **Step 6: Commit**

```bash
git add courses/static/courses/js/math_input.js courses/static/courses/css/editor.css templates/courses/manage/editor/editor.html locale/
git commit -m "feat(editor): reusable MathLive insert modal (window.libliMathInput)"
```

---

## Task 2: Math button on the RTE toolbar (stem + explanation, all question types)

**Files:**
- Modify: `templates/courses/manage/editor/_rte_toolbar.html` (add the ∑ button)
- Modify: `courses/static/courses/js/text_toolbar.js` (handle the `math` command)
- Test: `tests/test_e2e_math_input.py::test_rte_math_button_inserts_into_stem`

**Interfaces:**
- Consumes: `window.libliMathInput.open(onInsert)` from Task 1.
- Produces: clicking the toolbar ∑ button inserts `\(LATEX\)` at the caret of the bound contenteditable `.rte-surface` and syncs the hidden textarea.

- [ ] **Step 1: Write the failing e2e test**

```python
# tests/test_e2e_math_input.py
import os
import pytest
from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _pa(username):
    from django.contrib.auth.models import Group
    from institution.roles import PLATFORM_ADMIN, seed_roles
    seed_roles()
    u = make_verified_user(username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD)
    u.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return u


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    f = page.locator("form[action*='login']")
    f.locator("input[name='login']").fill(username)
    f.locator("input[name='password']").fill(TEST_PASSWORD)
    f.locator("button[type='submit']").click()


def _unit(username, slug):
    from django.contrib.auth import get_user_model
    from tests.factories import ContentNodeFactory, CourseFactory
    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(course=course, kind="unit", unit_type="lesson", parent=None, title="U")


def _editor_url(live_server, unit):
    return f"{live_server.url}/manage/courses/{unit.course.slug}/build/unit/{unit.pk}/edit/"


@pytest.mark.django_db(transaction=True)
def test_rte_math_button_inserts_into_stem(browser, live_server):
    _pa("m_rte")
    unit = _unit("m_rte", "m-rte")
    ctx = browser.new_context(); page = ctx.new_page()
    _login(page, live_server, "m_rte")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    # add a single-choice question
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='choice-single']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    # open math widget from the RTE toolbar, type LaTeX into the math-field, insert
    page.locator("[data-edit-slot] [data-cmd='math']").first.click()
    page.wait_for_selector(".math-modal:not([hidden]) math-field")
    page.locator(".math-modal math-field").type("x^2")
    page.locator(".math-modal [data-math-insert]").click()
    # the hidden stem textarea now contains the delimited LaTeX
    val = page.locator("[data-edit-slot] textarea[name='stem']").input_value()
    assert "\\(" in val and "x^2" in val and "\\)" in val
    ctx.close()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_e2e_math_input.py::test_rte_math_button_inserts_into_stem -m e2e -q`
Expected: FAIL (no `[data-cmd='math']` button).

- [ ] **Step 3: Add the ∑ button to the RTE toolbar**

In `templates/courses/manage/editor/_rte_toolbar.html`, before the closing `</div>`:

```html
  <span class="rte-sep"></span>
  <button type="button" class="rte-btn rte-btn--text" data-cmd="math" title="{% trans 'Insert math' %}" aria-label="{% trans 'Insert math' %}">∑</button>
```

- [ ] **Step 4: Handle the `math` command in `text_toolbar.js`**

In `applyCmd`, add a case (before `default`):

```javascript
      case "math":
        if (!window.libliMathInput) break;
        var sel = window.getSelection();
        var range = sel && sel.rangeCount ? sel.getRangeAt(0) : null;
        window.libliMathInput.open(function (latex) {
          surface.focus();
          var node = document.createTextNode("\\(" + latex + "\\)");
          if (range) {
            range.deleteContents();
            range.insertNode(node);
            range.setStartAfter(node); range.collapse(true);
            sel.removeAllRanges(); sel.addRange(range);
          } else {
            surface.appendChild(node);
          }
        });
        break;
```

The existing `sync()` after `applyCmd` writes the surface HTML back into the textarea.

- [ ] **Step 5: Run the test to confirm it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_e2e_math_input.py::test_rte_math_button_inserts_into_stem -m e2e -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add templates/courses/manage/editor/_rte_toolbar.html courses/static/courses/js/text_toolbar.js tests/test_e2e_math_input.py
git commit -m "feat(editor): math-insert button on the RTE toolbar (stem + explanation)"
```

---

## Task 3: ∑ button + live preview on plain answer fields (choices + accepted answers)

**Files:**
- Modify: `templates/courses/manage/editor/_edit_choicequestion.html` (∑ button + preview per choice row)
- Modify: `templates/courses/manage/editor/_edit_shorttextquestion.html` (∑ button + preview for accepted answers)
- Modify: `courses/static/courses/js/math_input.js` (delegated wiring for `[data-math-for]` triggers + live preview)
- Test: `tests/test_e2e_math_input.py::test_choice_field_math_button_and_preview`

**Interfaces:**
- Consumes: `window.libliMathInput.open`, `renderMathInElement` (auto-render, loaded on the editor page).
- Produces: any `[data-math-trigger]` button, when clicked, opens the modal and inserts `\(…\)` at the caret of the sibling field marked `[data-math-target]`; the sibling `[data-math-preview]` renders that field's content live.

- [ ] **Step 1: Write the failing e2e test**

```python
@pytest.mark.django_db(transaction=True)
def test_choice_field_math_button_and_preview(browser, live_server):
    _pa("m_ch")
    unit = _unit("m_ch", "m-ch")
    ctx = browser.new_context(); page = ctx.new_page()
    _login(page, live_server, "m_ch")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator("[data-add-toggle]").click()
    page.locator("[data-add-type='choice-single']").click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    # focus the first choice input, open its math widget, insert
    row = page.locator("[data-edit-slot] [data-choice-row]").first
    row.locator("input[name='choices-0-text']").click()
    row.locator("[data-math-trigger]").click()
    page.wait_for_selector(".math-modal:not([hidden]) math-field")
    page.locator(".math-modal math-field").type("\\frac{1}{2}")
    page.locator(".math-modal [data-math-insert]").click()
    assert "\\(" in row.locator("input[name='choices-0-text']").input_value()
    # live preview renders KaTeX for the inserted math
    page.wait_for_function(
        "() => document.querySelectorAll('[data-edit-slot] [data-math-preview] .katex').length > 0",
        timeout=6000,
    )
    ctx.close()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_e2e_math_input.py::test_choice_field_math_button_and_preview -m e2e -q`
Expected: FAIL (no `[data-math-trigger]`).

- [ ] **Step 3: Add ∑ button + preview to the choice row**

In `templates/courses/manage/editor/_edit_choicequestion.html`, replace the `{{ f.text }}` line with a wrapper:

```html
        <span class="choice-row__text" data-math-field>
          {{ f.text }}
          <button type="button" class="math-trigger" data-math-trigger
                  title="{% trans 'Insert math' %}" aria-label="{% trans 'Insert math' %}">∑</button>
          <span class="math-preview" data-math-preview></span>
        </span>
```

Mark the rendered text input as the target: the Django widget renders `name="choices-N-text"`; the JS finds the target as the `input`/`textarea` inside the same `[data-math-field]`. No widget attr change needed.

- [ ] **Step 4: Add ∑ button + preview to accepted answers**

In `templates/courses/manage/editor/_edit_shorttextquestion.html`, wrap the accepted-answers textarea:

```html
  <span class="math-field-wrap" data-math-field>
    <textarea name="accepted" rows="3">{{ form.accepted.value|default:"" }}</textarea>
    <button type="button" class="math-trigger" data-math-trigger
            title="{% trans 'Insert math' %}" aria-label="{% trans 'Insert math' %}">∑</button>
    <span class="math-preview" data-math-preview></span>
  </span>
```

- [ ] **Step 5: Wire delegated trigger + live preview in `math_input.js`**

Append inside the IIFE (before the `window.libliMathInput` assignment), and extend the public API call site to attach a delegated listener on `document`:

```javascript
  function fieldOf(trigger) {
    var wrap = trigger.closest("[data-math-field]");
    return wrap ? wrap.querySelector("input, textarea") : null;
  }
  function previewOf(trigger) {
    var wrap = trigger.closest("[data-math-field]");
    return wrap ? wrap.querySelector("[data-math-preview]") : null;
  }
  function insertAtCaret(input, text) {
    var s = input.selectionStart, e = input.selectionEnd;
    if (s == null) { input.value += text; }
    else { input.value = input.value.slice(0, s) + text + input.value.slice(e); var p = s + text.length; input.setSelectionRange(p, p); }
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.focus();
  }
  function renderPreview(input, preview) {
    if (!preview) return;
    preview.textContent = input.value;
    if (typeof renderMathInElement === "function") {
      try { renderMathInElement(preview, { delimiters: [{ left: "\\(", right: "\\)", display: false }, { left: "\\[", right: "\\]", display: true }], throwOnError: false }); } catch (e) { /* raw */ }
    }
  }
  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-math-trigger]");
    if (!trigger) return;
    var input = fieldOf(trigger);
    if (!input) return;
    open(function (latex) {
      insertAtCaret(input, "\\(" + latex + "\\)");
      renderPreview(input, previewOf(trigger));
    });
  });
  document.addEventListener("input", function (e) {
    var wrap = e.target.closest && e.target.closest("[data-math-field]");
    if (!wrap) return;
    renderPreview(e.target, wrap.querySelector("[data-math-preview]"));
  });
```

(Delegation on `document` means cloned choice rows and fragment-swapped editors are covered automatically.)

- [ ] **Step 6: Run the test to confirm it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_e2e_math_input.py::test_choice_field_math_button_and_preview -m e2e -q`
Expected: PASS

- [ ] **Step 7: Verify the add-option clone keeps a working ∑**

The choice-row clone in `editor.js` (`addChoiceRow`) deep-clones the row including the ∑ button and preview; delegation handles clicks; the preview span clears on clone (its content is regenerated on input). No code change expected — confirm via a quick manual check or extend the existing add-option e2e to assert the new row has `[data-math-trigger]`.

- [ ] **Step 8: Commit**

```bash
git add templates/courses/manage/editor/_edit_choicequestion.html templates/courses/manage/editor/_edit_shorttextquestion.html courses/static/courses/js/math_input.js tests/test_e2e_math_input.py
git commit -m "feat(editor): math-insert button + live preview on choice & accepted-answer fields"
```

---

## Task 4: Full-suite regression, lint, i18n gate, server restart

**Files:** none (verification task)

- [ ] **Step 1: Run the full non-e2e suite**

Run: `.\.venv\Scripts\python.exe -m pytest -q -m "not e2e"`
Expected: all pass.

- [ ] **Step 2: Run the new e2e tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_e2e_math_input.py tests/test_e2e_questions.py -m e2e -q`
Expected: all pass.

- [ ] **Step 3: Lint**

Run: `.\.venv\Scripts\python.exe -m ruff check tests/test_mathlive_assets.py tests/test_e2e_math_input.py`
Expected: All checks passed.

- [ ] **Step 4: i18n catalog gate**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_i18n_auth.py -q`
Expected: pass (no fuzzy/obsolete; new strings translated).

- [ ] **Step 5: Restart the dev server (DEBUG=False caches templates)**

Kill the listener on 8000 and relaunch `manage.py runserver 8000 --noreload`, then smoke-check `GET /accounts/login/` → 200.

- [ ] **Step 6: Final commit (if any catalog/.mo changes)**

```bash
git add -A
git commit -m "test(editor): math authoring — full regression green"
```

---

## Self-Review

**Spec coverage:**
- LaTeX option for those who know it → `<math-field>` accepts typed LaTeX; raw `\(...\)` typing in plain fields still works. ✓
- Visual widget for non-LaTeX users → MathLive `<math-field>` (Task 0–1). ✓
- Stem (all types) → RTE toolbar button (Task 2). ✓
- Explanation (all types) → same RTE toolbar button (explanation is also a `data-rte-source` surface). ✓
- Choice text → Task 3. ✓
- Short-text accepted answers → Task 3. ✓
- Render everywhere (preview) → already shipped (prior commit: auto-render in preview); live field preview added in Task 3. ✓

**Placeholder scan:** Font filenames are concrete; the only conditional is the ESM-vs-UMD fallback in Task 0 (a real verification step, not a placeholder).

**Type consistency:** `window.libliMathInput.open(onInsert)` is defined in Task 1 and consumed identically in Tasks 2 and 3. Data attributes: `[data-math-field]` (wrapper), `[data-math-trigger]` (button), `[data-math-preview]` (preview), `[data-cmd='math']` (RTE button) — used consistently.

**Open risk:** MathLive distribution format (UMD global vs ESM). Task 0 Step 5 verifies and gives the `.mjs` fallback. This is the one place execution may need to adapt.
