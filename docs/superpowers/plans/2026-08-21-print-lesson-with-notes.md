# Print lesson with notes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A student can print a lesson — or save it as a PDF — with their own notes on the page.

**Architecture:** A `Print` button in the unit strip, gated on `html.js`; a new `print.js` that opens the note `<details>` panels on the print lifecycle and restores them after; a `@media print` block in `notes.css` (which has none today); and two print-only elements in `_note_card.html`.

**Tech Stack:** Django templates, vanilla JS (no framework), plain CSS, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-21-print-lesson-with-notes-design.md`

**Base branch:** `pipeline/lesson-print-foundations` (PR #267), **not** `master`. That PR fixes dark-theme printing and slideshow printing; this one assumes both are in place and does not re-state them.

## Global Constraints

- **`uv` is not on PATH.** Every command uses the resolved absolute path: `C:/Users/krzys/.local/bin/uv.exe`.
- **Never pass `-q`.** `pyproject.toml:49` sets `addopts = "-q -m 'not e2e'"`; a CLI `-q` makes it `-qq` and suppresses the summary.
- **pytest can exit 0 with failures.** Grep the summary line.
- `-m e2e` is **mandatory** for e2e tests or they deselect and the run exits 5. **A `no tests ran` / exit 5 is NOT red** — if a mutant produces it, the command was wrong.
- **Ruff:** `pyproject.toml:36` selects `["E","F","I","UP","B","S"]`, 88-char default. `ruff format --check` is a **CI gate** (`.github/workflows/ci.yml:21`) — run `ruff format` first, then `--check`.
- **All CSS files here are CRLF.** Append with a tool that preserves CRLF, not a heredoc. Verify with `git diff --stat`: a whole-file rewrite means the endings flipped.
- **New `courses.css` rules are APPENDED at the end**, so no existing line citation shifts. `notes.css` gets its print block at the end for the same reason **and** because the un-clamp rule depends on source order (§3).
- Test-DB container must be running: `docker ps | grep libli-test-db`.
- **Never run two pytest processes at once** across worktrees — they share the test database.

---

### Task 1: The Print button and its no-JS gate

**Files:**
- Modify: `templates/courses/_unit_strip.html`
- Modify: `templates/courses/lesson_unit.html:61` (pass `show_print=True`)
- Modify: `courses/static/courses/css/courses.css` (append at end)
- Create: `tests/test_print_button_template.py`

**Interfaces:**
- Produces: a `[data-print-lesson]` button rendered only when `show_print` is truthy, hidden unless `html.js`, and hidden again in print. Task 2's `print.js` binds to that attribute.

- [ ] **Step 1: Write the failing template test**

Create `tests/test_print_button_template.py`:

```python
"""The Print button renders on the lesson page and nowhere else.

_unit_strip.html is shared by lesson_unit.html, quiz_unit.html and
quiz_results.html. Only the lesson renders notes, and quiz print has never had a
design pass, so the button is gated on an explicit include flag rather than on
the strip itself.
"""

from types import SimpleNamespace

from django.template.loader import render_to_string


def _strip(**ctx):
    """_unit_strip.html's FIRST line includes tags/_unit_tag_panel.html, which
    renders `{% url 'tags:tag_add' slug=course.slug node_pk=unit.pk %}`
    unconditionally. With an empty context both resolve to '' and {% url %}
    (no `as var`) raises NoReverseMatch -- so the stub below is required for the
    template to render at all, on any build."""
    ctx.setdefault("course", SimpleNamespace(slug="stub-course"))
    ctx.setdefault("unit", SimpleNamespace(pk=1))
    return render_to_string("courses/_unit_strip.html", ctx)


def test_button_renders_when_the_include_passes_the_flag():
    html = _strip(show_print=True)
    assert "data-print-lesson" in html
    assert "unit-strip__print" in html


def test_button_is_absent_without_the_flag():
    # quiz_unit.html and quiz_results.html include the strip without it.
    assert "data-print-lesson" not in _strip()


def test_lesson_template_passes_the_flag_and_the_quiz_templates_do_not():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "templates/courses"
    lesson = (root / "lesson_unit.html").read_text(encoding="utf-8")
    assert "_unit_strip.html" in lesson and "show_print=True" in lesson, (
        "lesson_unit.html must pass show_print=True to the strip"
    )
    for name in ("quiz_unit.html", "quiz_results.html"):
        quiz = (root / name).read_text(encoding="utf-8")
        assert "show_print" not in quiz, (
            f"{name} must not opt into the Print button; quiz print is a separate "
            "feature with different answers"
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_button_template.py -v`
Expected: **2 failed, 1 passed**. `test_button_is_absent_without_the_flag` asserts an *absence*,
which is trivially true before the change — it passes vacuously now and becomes meaningful once the
button exists. Do not chase a phantom third failure.

- [ ] **Step 3: Add the button to `_unit_strip.html`**

Insert **before** the existing `{% if can_edit_unit %}` block, so Print precedes Edit unit:

```html
  {% if show_print %}
    <button type="button" class="btn btn--ghost btn--small unit-strip__print" data-print-lesson>
      <svg class="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M6 9V3h12v6"/><path d="M6 18H4v-6h16v6h-2"/><path d="M6 14h12v7H6z"/>
      </svg>
      {% trans "Print" %}
    </button>
  {% endif %}
```

`btn--small`, **not** `btn--sm`: only `.btn--small` is defined (`app.css:50`). The SVG carries `aria-hidden="true" focusable="false"`, matching the Edit icon beside it. The visible label is the accessible name.

- [ ] **Step 4: Pass the flag from `lesson_unit.html` only**

Change line 61 from:

```
  {% include "courses/_unit_strip.html" %}
```

to:

```
  {% include "courses/_unit_strip.html" with show_print=True %}
```

Leave `quiz_unit.html` and `quiz_results.html` untouched.

- [ ] **Step 5: Append the gate and the print hide to `courses.css`**

Append at the **end** of `courses/static/courses/css/courses.css`:

```css

/* ── Print affordance ──────────────────────────────────────────────────────
   The button's only behaviour is window.print(), so with JS off it is a dead
   control -- hide it rather than render it inert. base.html:15 already adds
   `js` to documentElement in its prepaint script.

   The print rule must ALSO be html.js-qualified. The gate is (0,2,1); a print
   rule at (0,1,0) would lose to it and the button would print on paper. The
   .unit-strip__edit precedent at :2308 gets away with (0,1,0) only because
   nothing gates .unit-strip__edit. Equal weights mean source order decides, so
   the print rule must FOLLOW the gate -- which appending guarantees. */
.unit-strip__print { display: none; }
html.js .unit-strip__print { display: inline-flex; }
@media print { html.js .unit-strip__print { display: none; } }
```

- [ ] **Step 6: Run the tests, lint, and check CRLF**

```bash
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_button_template.py -v
C:/Users/krzys/.local/bin/uv.exe run ruff format tests/
C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/
C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/
```
Expected: 3 passed, ruff clean.

Run: `git diff --stat -- courses/static/courses/css/courses.css`
Expected: a small insertion count, not a whole-file rewrite.

- [ ] **Step 7: Commit**

```bash
git add templates/courses/_unit_strip.html templates/courses/lesson_unit.html \
  courses/static/courses/css/courses.css tests/test_print_button_template.py
git commit -m "feat(print): add a Print button to the lesson unit strip"
```

---

### Task 2: `print.js` — the print lifecycle

**Files:**
- Create: `courses/static/courses/js/print.js`
- Modify: `templates/courses/lesson_unit.html` (load it after `slideshow.js`)

**Interfaces:**
- Consumes: `[data-print-lesson]` from Task 1.
- Produces: on the print-enter path, `.block-notes__panel` elements carrying note content are `open`; surviving composer textareas carry an inline `style.height`; composers with a typed draft carry `.note-composer--has-draft`. Task 3's CSS keys off all three.

- [ ] **Step 1: Write the file**

Create `courses/static/courses/js/print.js`:

```js
/* print.js — lesson print lifecycle.
 *
 * A print stylesheet cannot open a closed <details>: the content is hidden by
 * content-visibility on the UA ::details-content pseudo-element, which author
 * CSS cannot reliably override across engines. Adding `open` is the only
 * portable mechanism, so this file exists.
 *
 * Deliberately has NO mode flag. An earlier design used an `entered` boolean to
 * make a double-fire idempotent, but a flag cleared only on leave becomes a
 * trap: if NEITHER leave dispatcher fires, it sticks true and every later print
 * on that page silently sweeps nothing. Idempotence falls out of the data
 * structures instead -- enter only queries :not([open]), so a second enter finds
 * its work done; leave drains the Sets, so a second leave iterates empty ones.
 */
(function () {
  "use strict";

  var opened = new Set();   // panels WE opened -- never ones the student opened
  var stamped = new Set();  // textareas WE gave an inline height

  /* A textarea's value is not layout, so it reads correctly through a closed
     <details>. This is the only way to find a draft the student typed and then
     closed the panel on: the native toggle does not clear the textarea (only
     the Cancel path does, notes.js:230). */
  function hasTypedDraft(panel) {
    var inputs = panel.querySelectorAll(".note-composer__input");
    for (var i = 0; i < inputs.length; i++) {
      if (inputs[i].value.trim() !== "") return true;
    }
    return false;
  }

  function carriesNoteContent(panel) {
    return (
      panel.querySelector(".note-card, .note-composer--edit, .note-delete-confirm") !==
        null || hasTypedDraft(panel)
    );
  }

  /* "Surviving" = the composers §3's print CSS spares. Emphatically NOT every
     .note-composer__input: that reaches note-less panels the sweep never opens,
     which are still under content-visibility:hidden, so scrollHeight reads 0 and
     we would stamp height:0px across the whole lesson. */
  function survivingInputs(root) {
    var out = [];
    var forms = root.querySelectorAll(".note-composer");
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      var spared =
        f.classList.contains("note-composer--edit") ||
        f.classList.contains("note-composer--has-draft") ||
        f.querySelector(".note-composer__error") !== null;
      if (!spared) continue;
      var ta = f.querySelector(".note-composer__input");
      if (ta) out.push(ta);
    }
    return out;
  }

  /* Re-derived on EVERY enter, never only added: the mark is value-based and so
     runs even where the height stamp is skipped, so it is not covered by the
     stamped Set. A stale mark on a since-emptied composer would both spare it
     from the print hide and satisfy the empty-pop :has(), printing an empty
     bordered box on a note-less block. */
  function markDrafts() {
    var forms = document.querySelectorAll(".note-composer");
    for (var i = 0; i < forms.length; i++) {
      var ta = forms[i].querySelector(".note-composer__input");
      var has = ta && ta.value.trim() !== "";
      forms[i].classList.toggle("note-composer--has-draft", !!has);
    }
  }

  /* A textarea's intrinsic block size comes from `rows` (3 here), so height:auto
     resolves to three rows with the rest scrolled out of view. Stamping the
     measured scrollHeight is the mechanism that works on every engine;
     field-sizing:content in the CSS is Chromium-only progressive enhancement.
     Measured under the SCREEN cascade, which is wider on paper than the 15rem
     floating pop -- so the stamp is over-tall, never short. Over-tall prints
     trailing whitespace; short would clip the student's words. */
  function stampHeights() {
    var inputs = survivingInputs(document);
    for (var i = 0; i < inputs.length; i++) {
      var ta = inputs[i];
      var h = ta.scrollHeight;
      if (!h) {
        /* Inside a [hidden] deck slide, layout is skipped and scrollHeight is 0.
           Un-hide the ancestor just long enough to measure, synchronously, so
           nothing the user or the print snapshot can see is affected. */
        var slide = ta.closest(".slide[hidden]");
        if (slide) {
          slide.removeAttribute("hidden");
          h = ta.scrollHeight;
          slide.setAttribute("hidden", "");
        }
      }
      if (h) {
        ta.style.height = h + "px";
        stamped.add(ta);
      }
    }
  }

  function enter() {
    var panels = document.querySelectorAll(".block-notes__panel:not([open])");
    for (var i = 0; i < panels.length; i++) {
      if (carriesNoteContent(panels[i])) {
        panels[i].open = true;
        opened.add(panels[i]);
      }
    }
    var un = document.querySelector(".unanchored-notes > details:not([open])");
    if (un) {
      un.open = true;
      opened.add(un);
    }
    /* Strictly after opening: a textarea inside a still-closed <details> is
       under content-visibility:hidden and measures 0. */
    markDrafts();
    stampHeights();
  }

  function leave() {
    opened.forEach(function (el) {
      /* setupClamp (notes.js:97) runs from the capture-phase toggle handler and
         leaves .note-card__body--clamp plus injected .note-card__more buttons in
         the LIVE dom once the panel closes. Only the panels we opened: one the
         student opened was clamped by their own gesture. Every removal is a
         no-op when absent -- a throw here would abort the restore half-done. */
      var clamped = el.querySelectorAll(".note-card__body--clamp");
      for (var i = 0; i < clamped.length; i++) {
        clamped[i].classList.remove("note-card__body--clamp");
      }
      var more = el.querySelectorAll(".note-card__more");
      for (var j = 0; j < more.length; j++) more[j].remove();
      el.removeAttribute("open");
    });
    opened.clear();

    stamped.forEach(function (ta) {
      ta.style.height = "";
    });
    stamped.clear();

    var marked = document.querySelectorAll(".note-composer--has-draft");
    for (var k = 0; k < marked.length; k++) {
      marked[k].classList.remove("note-composer--has-draft");
    }
  }

  var btn = document.querySelector("[data-print-lesson]");
  if (btn) {
    btn.addEventListener("click", function () {
      window.print();
    });
  }

  /* Ctrl+P must work too -- most people will never find the button. */
  window.addEventListener("beforeprint", enter);
  window.addEventListener("afterprint", leave);

  /* Safari fires the above unreliably; the media query is the more dependable
     signal there. Routed on e.matches so a leave is never mistaken for an enter. */
  var mql = window.matchMedia("print");
  var onChange = function (e) {
    if (e.matches) enter();
    else leave();
  };
  if (mql.addEventListener) mql.addEventListener("change", onChange);
  else if (mql.addListener) mql.addListener(onChange);
})();
```

- [ ] **Step 2: Load it from `lesson_unit.html`**

Immediately after the `slideshow.js` line (currently line 81), add:

```html
  <script src="{% static 'courses/js/print.js' %}" defer></script>
```

Unconditional — not behind a `has_*` flag like its neighbours — because `Ctrl+P` must work on every lesson. The position is **convention, not a dependency**: `notes.js` registers its capture-phase `toggle` listener at IIFE top level (`notes.js:530`), so it is bound whatever the order.

- [ ] **Step 3: Commit**

```bash
git add courses/static/courses/js/print.js templates/courses/lesson_unit.html
git commit -m "feat(print): open note panels on the print lifecycle"
```

No test here — but not because `print.js` is unobservable. Dispatching `beforeprint` opens the
panel and makes `.note-card__body` visible **on screen**, with zero print CSS; that is exactly what
Task 4's row 1 asserts, deliberately without `emulate_media`. What needs Task 3 is every
print-*rendering* assertion, so all e2e lands together in Task 4.

---

### Task 3: The `notes.css` print block and the card's print-only elements

**Files:**
- Modify: `notes/static/notes/css/notes.css` (append at end)
- Modify: `notes/templates/notes/_note_card.html`
- Create: `tests/test_notes_print_css.py`

**Interfaces:**
- Consumes: the classes Task 2 applies.
- Produces: printed note cards; Task 4's e2e asserts against them.

- [ ] **Step 1: Write the failing source test**

Create `tests/test_notes_print_css.py`:

```python
"""notes.css had ZERO print rules before this feature; these pin the ones that
would be silently inert if written at the wrong weight.

A deletion tripwire only. A substring assertion cannot detect a rule that is
present but loses on specificity -- that is what the e2e A/B in Task 4 is for.
"""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parent.parent / "notes/static/notes/css/notes.css"
).read_text(encoding="utf-8")

# Partition on the BRACE, not the bare words. The print block's own header
# comment contains the literal "@media print" (explaining that it adds no
# specificity) and quotes several of the selectors below verbatim -- so
# partitioning on "@media print" would put the comment inside PRINT, and every
# needle it happens to mention would be satisfied by prose even after the RULE
# was deleted. That is a tripwire that silently stops tripping.
SCREEN, _sep, PRINT = CSS.partition("@media print {")

REQUIRED = (
    # returns the pop to flow; must match the (0,4,0) screen rule verbatim
    ".notes-js .block-notes__panel[open] .block-notes__pop",
    "top: auto !important",
    # un-clamp: (0,1,0), wins on source order, deliberately UNSCOPED
    ".note-card__body--clamp",
    "-webkit-line-clamp: none",
    # the add-more hide must beat its (0,3,0) screen reveal
    ".lesson .block-notes__pop--has-notes .block-notes__add-more",
    # the three composer carve-outs
    ":not(.note-composer--edit)",
    ":not(.note-composer--has-draft)",
    ".note-composer__error",
    # empty-pop hide -- the full :has() list, not just its opening. The three
    # carve-out classes must appear INSIDE it: _block_notes.html renders a
    # composer for every block, so without them this rule hides the pop and the
    # draft/error carve-outs buy nothing.
    ":has(.note-card, .note-composer--edit, .note-composer--has-draft, "
    ".note-composer__error)",
    # focus-highlight reset, both (0,2,0)
    ".lesson-block.is-dimmed",
    ".lesson-block.is-highlighted",
    # print-only card elements
    ".note-card__print-label",
    ".note-card__print-date",
    ".note-card__meta-rel",
)


def test_notes_css_has_a_print_block():
    assert _sep, "notes.css must have an @media print block"


def test_print_block_declares_every_load_bearing_rule():
    for needle in REQUIRED:
        assert needle in PRINT, f"notes.css print block is missing {needle!r}"


def test_un_clamp_is_not_lesson_scoped():
    """notes.js:576-578 runs setupClamp on the hub too. A .lesson-scoped un-clamp
    would leave course_notes.html printing every long note truncated at six lines.
    Scope a hide, globalise an un-hide."""
    m = re.search(r"\.note-card__body--clamp\s*\{", PRINT)
    assert m, "no un-clamp rule in the print block"
    line_start = PRINT.rfind("\n", 0, m.start()) + 1
    assert ".lesson" not in PRINT[line_start : m.start()], (
        "the un-clamp rule must NOT carry the .lesson scope"
    )


def test_print_only_card_elements_are_hidden_on_screen():
    for cls in (".note-card__print-label", ".note-card__print-date"):
        m = re.search(re.escape(cls) + r"\s*\{([^}]*)\}", SCREEN)
        assert m, f"{cls} needs a base-block rule hiding it on screen"
        assert "display: none" in m.group(1), (
            f"{cls} must be display:none on screen, or every card shows it"
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_notes_print_css.py -v`
Expected: **4 failed** — `notes.css` has no `@media print` block at all.

- [ ] **Step 3: Add the print-only elements to `_note_card.html`**

Two edits. First, insert as the **first child** of `<article class="note-card">`, **outside** the `{% if note.element_id %}` guard (inside it, the label would vanish from exactly the unanchored notes that need it for provenance):

```html
  <p class="note-card__print-label" aria-hidden="true">{% trans "My note" %}</p>
```

Second, replace the `.note-card__meta` paragraph. The relative text is currently a **bare text node**, which no selector can target — that is why the span is needed:

```html
  <p class="note-card__meta">
    <span class="note-card__meta-rel">{% if note|note_edited %}{% blocktrans with when=note.updated|timesince %}edited {{ when }} ago{% endblocktrans %}{% else %}{% blocktrans with when=note.updated|timesince %}added {{ when }} ago{% endblocktrans %}{% endif %}</span>
    <span class="note-card__print-date">{% if note|note_edited %}
      {# Translators: %(date)s is a short date, e.g. 21.08.2026 #}
      {% blocktrans with date=note.updated|date:"SHORT_DATE_FORMAT" %}edited {{ date }}{% endblocktrans %}
    {% else %}
      {# Translators: %(date)s is a short date, e.g. 21.08.2026 #}
      {% blocktrans with date=note.updated|date:"SHORT_DATE_FORMAT" %}added {{ date }}{% endblocktrans %}
    {% endif %}</span>
  </p>
```

Each `blocktrans` gets **its own** `{# Translators: #}` line. xgettext attaches an extracted
comment to the *immediately following* msgid only, so a single comment above a line holding both
blocks would reach one of them and leave the other — one of the two maximum-fuzzy-hazard strings —
with no guidance at all.

The verb is kept: hiding `.note-card__meta-rel` would otherwise leave a naked `21.08.2026` with no indication whether it is a creation or last-edit date. Both phrasings already read `note.updated` — `note.created` is never rendered.

- [ ] **Step 4: Append the print block to `notes.css`**

Append at the **end** of `notes/static/notes/css/notes.css`:

```css

/* ── Print-only card furniture (hidden on screen) ─────────────────────────── */
.note-card__print-label { display: none; }
.note-card__print-date { display: none; }

/* ── Print ────────────────────────────────────────────────────────────────
   notes.css had NO print rules before this feature: every note lives inside a
   closed <details>, so a printed lesson showed none of them.

   @media print adds NO specificity, so each rule below must match or beat the
   screen rule it undoes. The weights that matter:
     (0,5,0) .notes-js .block-notes__pop--has-notes:not(.is-adding)
             .note-composer:not(.note-composer--edit)          -- notes.css:181
     (0,4,0) .notes-js .block-notes__panel[open] .block-notes__pop  -- :92
     (0,3,0) .notes-js .block-notes__pop--has-notes .block-notes__add-more -- :177
     (0,2,0) .lesson-block.is-highlighted / .is-dimmed         -- :278, :284
     (0,1,1) .unanchored-notes summary                         -- :270
   Note [attr] counts in the CLASS column; miscounting it is how an inert rule
   gets written.

   Scoping rule: scope a HIDE to .lesson, globalise an UN-HIDE. course_notes.html
   loads this sheet too and renders .note-card via _readonly_note_card.html, so an
   unscoped hide would strip content from the hub -- but a .lesson-scoped un-clamp
   would leave the hub printing truncated notes (notes.js:576 clamps there too). */
@media print {
  /* Return the pop to flow. Written VERBATIM as the (0,4,0) screen selector so
     it cannot be got wrong by miscounting; it wins on end-of-file source order.
     top needs !important because positionPop (notes.js:524) writes it INLINE.
     right is named because --clamped sets `left: auto; right: 0` -- resetting
     left alone leaves it. */
  .notes-js .block-notes__panel[open] .block-notes__pop {
    position: static; top: auto !important; left: auto; right: auto;
    width: auto; margin-top: .4rem; padding: 0;
    background: none; border: 0; border-radius: 0;
    max-height: none; overflow-y: visible; z-index: auto; box-shadow: none;
  }

  /* UNSCOPED, deliberately: the hub clamps too. (0,1,0) tying notes.css:186 and
     winning by source order -- the one equal-weight case here, safe only because
     this block is pinned to the end of the file. */
  .note-card__body--clamp {
    display: block; -webkit-line-clamp: none; overflow: visible;
  }
  .note-card__more { display: none; }

  /* Controls. add-more needs the (0,3,0) shape or it loses to its screen reveal. */
  .lesson .note-card__actions,
  .lesson .block-notes__add-label,
  .lesson .note-delete-confirm { display: none; }
  .lesson .block-notes__pop--has-notes .block-notes__add-more { display: none; }

  /* A composer survives only if it holds text the student would lose: an inline
     edit, a typed draft (print.js marks it -- CSS cannot see a textarea's value,
     since typing changes `value`, not DOM children), or a rejected no-JS draft.
     That last carve-out is a NO-JS guarantee only: with .notes-js present,
     notes.css:181 already hides it at (0,5,0), which nothing here beats. */
  .lesson .note-composer:not(.note-composer--edit):not(.note-composer--has-draft):not(:has(.note-composer__error)) {
    display: none;
  }
  .lesson .note-composer__actions { display: none; }
  .lesson .note-composer__input {
    field-sizing: content; height: auto; max-height: none;
    overflow: visible; resize: none;
    /* border:0 is load-bearing, not chrome: the input is box-sizing:border-box
       (:209) and inherits input[type] border/padding, so print.js's scrollHeight
       stamp (a padding-box measurement) is short by the border width. */
    border: 0;
  }

  /* An empty pop prints as a stray zero-height box. The :has() list MUST include
     the draft and error classes: _block_notes.html renders a composer for EVERY
     block, note-less ones included, and re-opens the panel with a rejected draft
     on note-less blocks too -- without them this rule hides the pop and both
     carve-outs above buy nothing. .note-delete-confirm is deliberately OUT, so a
     block whose only note is mid-delete loses its pop entirely, which is what
     "omitted cleanly" means. */
  .lesson .block-notes__pop:not(:has(.note-card, .note-composer--edit, .note-composer--has-draft, .note-composer__error)) {
    display: none;
  }

  /* Both <summary> elements: visibility, NOT display:none. Engines differ on
     whether a <details> renders its children when the summary is not rendered,
     and that <details> is load-bearing for the unanchored section printing at
     all. The full reset matters -- height:0 alone leaves padding, and with the
     global box-sizing:border-box a "zero-height" box still measures 8px.
     .lesson is LOAD-BEARING on the unanchored one: its padding comes from
     `.unanchored-notes summary` at (0,1,1) (:270), which (0,1,0) would lose to. */
  .lesson .block-notes__handle,
  .lesson .unanchored-notes__handle {
    visibility: hidden; height: 0; padding: 0; margin: 0; border: 0;
    overflow: hidden;
  }

  /* notes.css:45 pulls the affordance up against its element with a negative
     margin. With the handle gone that drags the card over the block it
     annotates. */
  .lesson .block-notes { margin-top: .35rem; margin-bottom: .75rem; }

  /* notes.js dims every OTHER block while a note card is hovered or focused, and
     clears it only on blur -- so clicking a note then pressing Ctrl+P printed
     most of the lesson at 45% opacity with one block visibly ringed. Outlines,
     like borders, survive the strip-backgrounds default. Both are (0,2,0). */
  .lesson .lesson-block.is-dimmed { opacity: 1; }
  .lesson .lesson-block.is-highlighted { background: none; outline: none; }

  /* Keep the per-block accent rail -- borders paint even when backgrounds are
     stripped -- and never split a note across a page boundary. */
  .lesson .note-card { break-inside: avoid; }

  /* Flatten the unanchored container; its notes print as ordinary cards, their
     provenance carried by the My note label. */
  .lesson .unanchored-notes {
    border: 0; border-top: 1px solid var(--border-strong);
    background: none; border-radius: 0;
  }

  /* Print-only furniture. Uppercase is presentation, not a msgid -- the same
     treatment .ba__side-heading gets at courses.css:2113. */
  .lesson .note-card__print-label {
    display: block; text-transform: uppercase; letter-spacing: .08em;
    font-size: .62rem; font-weight: 700; color: var(--text-secondary);
    margin: 0 0 .2rem;
  }
  .lesson .note-card__print-date { display: inline; }
  .lesson .note-card__meta-rel { display: none; }
}
```

- [ ] **Step 5: Run the tests, lint, check CRLF**

```bash
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_notes_print_css.py -v
C:/Users/krzys/.local/bin/uv.exe run ruff format tests/
C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/
C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/
```
Expected: 4 passed, ruff clean.

Run: `git diff --stat -- notes/static/notes/css/notes.css`
Expected: a small insertion count, not a whole-file rewrite.

- [ ] **Step 6: Run the existing notes tests — the template changed**

```bash
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_notes_presentation.py tests/test_notes_views.py tests/test_i18n_notes.py tests/test_tags_notes_hub.py
```
Expected: all pass. `test_i18n_notes.py` asserts `added %(when)s ago`, which the `.note-card__meta-rel` span preserves verbatim.

- [ ] **Step 7: Commit**

```bash
git add notes/static/notes/css/notes.css notes/templates/notes/_note_card.html \
  tests/test_notes_print_css.py
git commit -m "feat(print): print styling for personal notes"
```

---

### Task 4: e2e coverage, i18n, and the falsification battery

**Files:**
- Create: `tests/test_e2e_print_lesson_notes.py`
- Create: `tests/test_i18n_print_notes.py`
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ regenerate `.mo`)

**Interfaces:**
- Consumes: everything from Tasks 1–3.

- [ ] **Step 1: Write the e2e suite**

Create `tests/test_e2e_print_lesson_notes.py`. Entry-path rules, which decide several assertions:

- `emulate_media(media="print")` re-evaluates CSS media queries **and** fires a `matchMedia("print")` change (measured in this repo's Chromium), so **it runs the enter path**.
- Therefore a row proving the `beforeprint` listener exists must **not** call `emulate_media` first, or the mutant is rescued by the media route. Row 1 asserts **on screen**.
- A row needing *no* enter path must block `print.js` from loading (`page.route("**/print.js", lambda r: r.abort())`), not merely withhold a dispatch.
- Never `mql.dispatchEvent(new Event("change"))` — it carries no `matches`, so the handler takes the *leave* path and goes red on a correct build.

```python
"""Playwright e2e for printing a lesson with the student's own notes.

Assumes PR #267 (lesson print foundations) is in the base: dark-theme printing
and slideshow printing are already correct and are not re-asserted here.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _lesson_with_note(slug, body="a note the student wrote", elements=1):
    """A published lesson with `elements` blocks, each carrying one note.

    Two blocks are the minimum for several rows, and the reason is not cosmetic:
    applyHighlight (notes.js:434) dims only blocks OTHER than the target, so with
    a single block nothing is ever .is-dimmed and an opacity assertion cannot
    fail. The restore rows likewise need one panel the student opens by hand and
    a DIFFERENT one for the sweep to open.

    Returns (course, unit, student, [notes...]).
    """
    from django.contrib.auth.models import Group as AuthGroup

    from courses.models import ContentNode
    from courses.models import Enrollment
    from courses.models import TextElement
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from notes.models import Note
    from tests.factories import CourseFactory
    from tests.factories import add_element
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory(slug=slug)
    unit = ContentNode.objects.create(
        course=course,
        kind=ContentNode.Kind.UNIT,
        unit_type=ContentNode.UnitType.LESSON,
        title="Printable",
        published=True,
    )
    els = [
        add_element(unit, TextElement.objects.create(body=f"<p>Block {i}.</p>"))
        for i in range(elements)
    ]
    student = make_verified_user(
        username=f"{slug}-student", email=f"{slug}@test.example.com"
    )
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    Enrollment.objects.create(student=student, course=course, source="manual")
    notes = [
        Note.objects.create(author=student, unit=unit, element=el, body=body)
        for el in els
    ]
    return course, unit, student, notes


def _open(page, live_server, course, unit, student):
    _login(page, live_server, student.username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".block-notes__panel", state="attached")


def _visible(page, selector):
    """checkVisibility() with NO options -- the only correct discriminator for a
    closed <details>. bounding_box() stays non-zero through one (measured 52.4x22)
    and querySelectorAll counts it, so both are useless here."""
    return page.evaluate(
        "s => { const el = document.querySelector(s);"
        "       return !!el && el.checkVisibility(); }",
        selector,
    )


@pytest.mark.django_db(transaction=True)
def test_note_body_visible_after_the_event_route(page, live_server):
    """Row 1. NO emulate_media: with both listeners live it would run the enter
    path via the media route and rescue this row's mutant. An open <details> is
    visible on screen, so this is a valid observation."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-event")
    _open(page, live_server, course, unit, student)

    assert not _visible(page, ".note-card__body"), "panel should start closed"
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    assert _visible(page, ".note-card__body"), (
        "the beforeprint listener did not open the panel"
    )


@pytest.mark.django_db(transaction=True)
def test_note_body_visible_after_the_media_route(page, live_server):
    """Row 2. emulate_media only -- this IS a real matchMedia('print') change."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-media")
    _open(page, live_server, course, unit, student)

    page.emulate_media(media="print")
    from playwright.sync_api import expect

    expect(page.locator(".note-card__body")).to_have_count(1)
    page.wait_for_function(
        "() => { const el = document.querySelector('.note-card__body');"
        "        return el && el.checkVisibility(); }"
    )


@pytest.mark.django_db(transaction=True)
def test_the_real_button_calls_window_print(page, live_server):
    """Row 3. Drives the actual control, not a page.evaluate shortcut."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-button")
    stub = "window.__printed = 0; window.print = () => { window.__printed++; };"
    page.add_init_script(stub)
    _open(page, live_server, course, unit, student)

    page.locator("[data-print-lesson]").click()
    assert page.evaluate("window.__printed") == 1, (
        "the Print button did not call window.print()"
    )


@pytest.mark.django_db(transaction=True)
def test_the_button_is_visible_on_screen_and_not_in_print(page, live_server):
    """Row 15. The gate is (0,2,1); a print rule at (0,1,0) loses to it."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-btnvis")
    _open(page, live_server, course, unit, student)

    assert _visible(page, "[data-print-lesson]"), "button must show on screen"
    page.emulate_media(media="print")
    assert not _visible(page, "[data-print-lesson]"), (
        "the Print button printed; its print rule must be html.js-qualified to "
        "beat the (0,2,1) gate"
    )


@pytest.mark.django_db(transaction=True)
def test_long_note_prints_in_full(page, live_server):
    """Row 4. INJECTS the clamp class rather than waiting for setupClamp: the
    toggle is async, and setupClamp measures AFTER adding the class
    (notes.js:104), so with the un-clamp rule live it detects no overflow and
    removes the class again -- leaving this row green on its own mutant."""
    long_body = "\n".join(f"line {i}" for i in range(20))
    course, unit, student, _ = _lesson_with_note("e2e-pn-clamp", body=long_body)
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.evaluate(
        "document.querySelector('.note-card__body')"
        ".classList.add('note-card__body--clamp')"
    )
    page.emulate_media(media="print")
    box = page.locator(".note-card__body").bounding_box()
    # .note-card__body is font-size .9rem (14.4px); -webkit-line-clamp: 6 means a
    # clamped body measures ~121-138px at any plausible line-height. A 100px
    # threshold sits BELOW that, so the un-clamp mutant would still pass. The
    # 20-line body prints at ~400px unclamped, so 300 separates the two regimes.
    assert box["height"] > 300, (
        f"clamped note prints {box['height']}px -- the un-clamp rule is missing "
        "or lost on specificity"
    )


@pytest.mark.django_db(transaction=True)
def test_controls_do_not_print(page, live_server):
    """Row 6a. Only display:none targets, asserted with checkVisibility()."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-controls")
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.emulate_media(media="print")
    for sel in (".note-card__actions", ".block-notes__add-more"):
        assert not _visible(page, sel), f"{sel} printed"


@pytest.mark.django_db(transaction=True)
def test_the_note_handle_has_zero_height_in_print(page, live_server):
    """Row 6a2. MUST measure the box, not checkVisibility(): the handle is
    suppressed with visibility:hidden, and checkVisibility()'s default
    visibilityProperty:false means it returns TRUE for such an element -- this
    row would be RED on a correct build."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-handle")
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.emulate_media(media="print")
    box = page.locator(".block-notes__handle").first.bounding_box()
    assert box["height"] == 0, (
        f"the note handle prints {box['height']}px tall; the suppression must "
        "reset padding too, or box-sizing:border-box leaves ~8px"
    )


@pytest.mark.django_db(transaction=True)
def test_label_and_date_print_and_are_absent_on_screen(page, live_server):
    """Rows 11 and 12, both directions."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-label")
    _open(page, live_server, course, unit, student)
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")

    assert not _visible(page, ".note-card__print-label"), "label showed on screen"
    assert not _visible(page, ".note-card__print-date"), "date showed on screen"

    page.emulate_media(media="print")
    assert _visible(page, ".note-card__print-label"), "My note label did not print"
    assert _visible(page, ".note-card__print-date"), "absolute date did not print"
    assert not _visible(page, ".note-card__meta-rel"), (
        "the relative 'x ago' text printed alongside the absolute date"
    )
    box = page.locator(".note-card__print-label").bounding_box()
    assert box["height"] > 1, "label is present but clipped"


@pytest.mark.django_db(transaction=True)
def test_blocks_are_not_dimmed_or_ringed_in_print(page, live_server):
    """Row 14. Outlines survive the strip-backgrounds default, so a focused block
    would print visibly ringed. Both rules are (0,2,0)."""
    # TWO blocks: applyHighlight (notes.js:434) dims only blocks OTHER than the
    # target, so a single-block fixture is never .is-dimmed and the opacity
    # assertion could not fail.
    course, unit, student, _ = _lesson_with_note("e2e-pn-dim", elements=2)
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    # A real gesture, not .focus() on a card. (notes.js:64-71 does give cards a
    # tabindex, so focus() would fire the delegate -- but hovering the handle is
    # the gesture a student actually makes, and it needs no synthetic focus.)
    page.locator(".block-notes__handle").first.hover()
    page.wait_for_function(
        "() => document.querySelector('.lesson-block.is-dimmed') !== null"
    )

    page.emulate_media(media="print")
    state = page.evaluate(
        "() => { const dim = document.querySelector('.lesson-block.is-dimmed');"
        "        const hi = document.querySelector('.lesson-block.is-highlighted');"
        "        return { dimOpacity: getComputedStyle(dim).opacity,"
        "                 hiOutline: getComputedStyle(hi).outlineStyle }; }"
    )
    assert float(state["dimOpacity"]) == 1.0, f"other block printed dimmed: {state}"
    assert state["hiOutline"] == "none", f"focused block printed ringed: {state}"


@pytest.mark.django_db(transaction=True)
def test_panels_print_opened_are_closed_again_and_hand_opened_ones_are_not(
    page, live_server
):
    """Rows 17 and 18 together, and the residue cleanup (row 19).

    The residue is INJECTED rather than waited for: the toggle is async, so an
    absence assertion would pass vacuously on a build with the cleanup deleted."""
    # TWO blocks, and the distinction is the whole point: panel A is opened by
    # the STUDENT (so enter() never sees it -- it queries :not([open]) -- and
    # leave() must not touch it), panel B is opened by the sweep. With one block
    # the sweep opens nothing, `opened` stays empty, and the residue assertion is
    # RED on a correct build.
    course, unit, student, _ = _lesson_with_note("e2e-pn-restore", elements=2)
    _open(page, live_server, course, unit, student)

    page.locator(".block-notes__handle").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('.block-notes__panel[open]').length === 1"
    )

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.wait_for_function(
        "() => document.querySelectorAll('.block-notes__panel[open]').length === 2"
    )
    # Inject the residue into the panel the SWEEP opened (the second one).
    page.evaluate(
        "() => { const p = document.querySelectorAll('.block-notes__panel')[1];"
        "        p.querySelector('.note-card__body')"
        "         .classList.add('note-card__body--clamp'); }"
    )
    page.evaluate("window.dispatchEvent(new Event('afterprint'))")

    state = page.evaluate(
        "() => { const ps = document.querySelectorAll('.block-notes__panel');"
        "        return { handOpen: ps[0].open, sweptOpen: ps[1].open,"
        "                 residue: !!document.querySelector"
        "                            ('.note-card__body--clamp') }; }"
    )
    assert state["handOpen"], "the leave path closed a panel the STUDENT opened"
    assert not state["sweptOpen"], "the leave path left a swept panel open"
    assert not state["residue"], "clamp residue survived the leave path"


@pytest.mark.django_db(transaction=True)
def test_two_enters_with_no_leave_then_one_leave(page, live_server):
    """Row 20b. The re-close between the enters is what makes this falsifiable:
    without it the first enter has already opened everything and a reintroduced
    mode flag's early return would be invisible."""
    course, unit, student, _ = _lesson_with_note("e2e-pn-idempotent", elements=2)
    _open(page, live_server, course, unit, student)

    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    page.evaluate("document.querySelector('.block-notes__panel').open = false")
    page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
    assert page.evaluate("document.querySelector('.block-notes__panel').open"), (
        "the second enter did not re-open the panel -- a mode flag was reintroduced"
    )

    page.evaluate("window.dispatchEvent(new Event('afterprint'))")
    assert not page.evaluate("document.querySelector('.block-notes__panel').open")
```

- [ ] **Step 2: Run the e2e suite**

```bash
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_e2e_print_lesson_notes.py -m e2e -v
```
Expected: 11 passed. `-m e2e` is mandatory.

Then format and lint — `ruff format --check` is a CI gate (`ci.yml:21`) and no other step in this
task runs it:

```bash
C:/Users/krzys/.local/bin/uv.exe run ruff format tests/
C:/Users/krzys/.local/bin/uv.exe run ruff format --check tests/
C:/Users/krzys/.local/bin/uv.exe run ruff check --no-cache tests/
```
Expected: clean.

- [ ] **Step 3: Regenerate the `pl` catalogue**

```bash
C:/Users/krzys/.local/bin/uv.exe run python manage.py makemessages -l pl
```

Then edit `locale/pl/LC_MESSAGES/django.po`:

| msgid | msgstr |
|---|---|
| `My note` | `Moja notatka` |
| `added %(date)s` | `dodano %(date)s` |
| `edited %(date)s` | `edytowano %(date)s` |

**`Print` is NOT new** — `msgid "Print"` already exists at `django.po:5231` with `msgstr "Drukuj"`; `makemessages` only adds a `#:` source reference.

**Check every new entry for a `#, fuzzy` marker.** The hazard is at its maximum here: the catalogue already carries `added %(when)s ago` (`:3210`) and `edited %(when)s ago` (`:3204`), so `makemessages` will very likely pre-fill the new entries with those wrong translations. Clearing one requires deleting **both** the `#, fuzzy` line and the bogus `msgstr`.

Then: `C:/Users/krzys/.local/bin/uv.exe run python manage.py compilemessages -l pl`

- [ ] **Step 3b: Pin the catalogue with a test — prose warnings do not fail a build**

The fuzzy hazard above is exactly the kind of thing that gets missed under time pressure, and a
`#, fuzzy` entry ships a *wrong* Polish string silently. Create `tests/test_i18n_print_notes.py`:

```python
"""The three new msgids must land translated, non-empty and non-fuzzy.

makemessages will very likely pre-fill `added %(date)s` / `edited %(date)s` from
the near-identical `added %(when)s ago` (django.po:3210) and
`edited %(when)s ago` (:3204) -- and a fuzzy entry ships the WRONG string with no
error. Clearing one means deleting BOTH the `#, fuzzy` line and the bogus msgstr.
"""

import re
from pathlib import Path

PO = (
    Path(__file__).resolve().parent.parent / "locale/pl/LC_MESSAGES/django.po"
).read_text(encoding="utf-8")

EXPECTED = {
    "My note": "Moja notatka",
    "added %(date)s": "dodano %(date)s",
    "edited %(date)s": "edytowano %(date)s",
}


def _entry(msgid):
    """The full entry block for one msgid, comment lines included."""
    pattern = (
        r"((?:^#.*\n)*)"                      # leading comments, incl. #, fuzzy
        r'^msgid "' + re.escape(msgid) + r'"\n'
        r'^msgstr "([^"]*)"'
    )
    return re.search(pattern, PO, re.M)


def test_the_three_new_msgids_are_translated_and_not_fuzzy():
    for msgid, expected in EXPECTED.items():
        m = _entry(msgid)
        assert m, f"msgid {msgid!r} is missing from the pl catalogue"
        comments, msgstr = m.group(1), m.group(2)
        assert "#, fuzzy" not in comments, (
            f"{msgid!r} is marked fuzzy -- makemessages pre-filled it from a "
            "near-identical entry. Delete BOTH the marker and the bogus msgstr."
        )
        assert msgstr == expected, (
            f"{msgid!r} translates to {msgstr!r}, expected {expected!r}"
        )


def test_print_is_reused_not_redefined():
    """`Print` already exists (django.po:5231, "Drukuj"). makemessages should add
    a source reference to that entry, not a second definition."""
    assert PO.count('msgid "Print"\n') == 1, (
        "msgid \"Print\" is defined more than once -- the template should reuse "
        "the existing entry"
    )
    m = _entry("Print")
    assert m and m.group(2) == "Drukuj"
    assert "_unit_strip.html" in m.group(1), (
        "the new {% trans \"Print\" %} did not add a source reference to the "
        "existing entry -- did makemessages run?"
    )
```

Run: `C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_i18n_print_notes.py -v`
Expected: 2 passed.

- [ ] **Step 4: The falsification battery**

Apply each mutant **by hand-editing the file**, run the named test, confirm **RED**, then **edit it back out by hand**. Never `git checkout` — this repo has lost work to that three times.

Commands:
```bash
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_e2e_print_lesson_notes.py::<name> -m e2e -v
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_notes_print_css.py::<name> -v
C:/Users/krzys/.local/bin/uv.exe run pytest tests/test_print_button_template.py::<name> -v
```
Pick the command by the **test file each row names**: rows naming
`test_e2e_print_lesson_notes.py` need `-m e2e`; rows naming `test_notes_print_css.py` or
`test_print_button_template.py` must **not** use it.

**`no tests ran` / exit 5 is NOT red.** Passing `-m e2e` to a non-e2e test deselects it and exits 5
with no failure, which reads exactly like a pass. If a mutant produces that, the command was wrong.

| # | Mutant | Must turn RED |
|---|---|---|
| 1 | Delete the `beforeprint`/`afterprint` registration from `print.js` | `test_note_body_visible_after_the_event_route` |
| 2 | Delete the `matchMedia` registration | `test_note_body_visible_after_the_media_route` |
| 3 | Delete the button's click listener | `test_the_real_button_calls_window_print` |
| 4 | Write the print rule for the button at (0,1,0) (drop `html.js`) | `test_the_button_is_visible_on_screen_and_not_in_print` |
| 5 | Delete the un-clamp rule | `test_long_note_prints_in_full` |
| 6 | Write the add-more hide at (0,2,0) (`.lesson .block-notes__add-more`) | `test_controls_do_not_print` |
| 7 | Delete the control-hiding rule | `test_controls_do_not_print` |
| 8 | Drop `padding: 0` from the summary suppression | `test_the_note_handle_has_zero_height_in_print` |
| 9 | Delete the base-block `display: none` for `.note-card__print-label` | `test_label_and_date_print_and_are_absent_on_screen` |
| 10 | Delete the `.note-card__meta-rel` hide | same |
| 11 | Write the `.is-highlighted` reset at (0,1,0) | `test_blocks_are_not_dimmed_or_ringed_in_print` |
| 12 | Delete the `.is-dimmed` reset | same |
| 13 | Make the leave path close **all** panels, not just the recorded Set | `test_panels_print_opened_are_closed_again_and_hand_opened_ones_are_not` |
| 14 | Skip the de-clamp cleanup on the leave path | same |
| 15 | Add an `entered` boolean that makes `enter()` return early | `test_two_enters_with_no_leave_then_one_leave` |
| 16 | Add `.lesson` to the un-clamp rule | `test_un_clamp_is_not_lesson_scoped` (non-e2e) |
| 17 | Drop `.note-composer--has-draft` from the empty-pop `:has()` list | `test_print_block_declares_every_load_bearing_rule` (non-e2e) |
| 18 | Remove the `{% if show_print %}` / `{% endif %}` wrapper in `_unit_strip.html`, so the button renders unconditionally | `test_print_button_template.py::test_button_is_absent_without_the_flag` (non-e2e). *This is the only demonstration that the quiz-template guard can fail: in Task 1's red phase that assertion passes vacuously, because the button does not exist yet* |

After the battery, run **`git status --short`** as well as `git diff`. `git diff` alone cannot see
an untracked file, so it would not notice a new test that was never staged — only a leftover mutant
in a tracked file.

- [ ] **Step 5: Full-suite gate**

`notes.css`, `courses.css` and `templates/` are all touched. Check whether the affected-tests selection applies; if any touched path is in `is_global_path` (`tests/test_affected_tests.py:133`), budget for the full suite — roughly 20 minutes non-e2e plus 37 minutes e2e, measured on PR #267.

```bash
C:/Users/krzys/.local/bin/uv.exe run pytest
C:/Users/krzys/.local/bin/uv.exe run pytest -m e2e
```
Grep both summary lines.

- [ ] **Step 6: Manual print-preview check**

`break-inside: avoid` cannot be observed by `emulate_media`, which does not paginate. Use `page.pdf()` (which does) or a real browser preview on a lesson with several long notes, in **both light and dark**, and confirm no note is split across a page boundary.

- [ ] **Step 7: Commit**

```bash
git add tests/test_e2e_print_lesson_notes.py tests/test_i18n_print_notes.py \
  locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git status --short
git commit -m "test(print): e2e coverage for printing a lesson with notes"
```

`git status --short` **before** the commit, not `git diff`: a newly created file that was never
`git add`ed is **untracked**, so it does not appear in `git diff` at all. That is exactly how a test
file gets written, run, and then silently left out of the branch.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 button, `btn--small`, icon, include flag, `html.js` gate + (0,2,1) print rule | Task 1 |
| §2 `print.js`: sweep filter incl. `hasTypedDraft`, Set, ordering, draft marks, stamp, leave path, two dispatchers, no mode flag | Task 2 |
| §2a `positionPop` inline `top` | Task 3 (`top: auto !important`) |
| §2b edit / delete transients | Task 3 (`:not(--edit)`, `.note-delete-confirm` hidden) |
| §2c `setupClamp` truncation + residue | Task 3 (un-clamp) + Task 2 (leave cleanup) |
| §3 specificity table, scoping rule, every listed rule | Task 3 |
| §3 textarea fit (stamp + `field-sizing`, `border: 0`) | Tasks 2 and 3 |
| §3 template edits (label, date, `meta-rel` span) | Task 3 |
| §4 no-JS degradation | Task 1 (gate) — `?notes=1` needs no new work |
| §5 i18n, three msgids, fuzzy hazard | Task 4, Step 3 |
| Testing rows 1, 2, 3, 4, 6a, 6a2, 11, 12, 14, 15, 17, 18, 19, 20b | Task 4, Step 1 |
| Measurement traps | Task 4 (`_visible` helper; row 6a2 measures the box) |
| Manual check | Task 4, Step 6 |

**Placeholder scan:** none — every step carries literal content or a literal command.

**Type consistency:** `_login`, `_lesson_with_note`, `_open`, `_visible` are each defined once and used with matching signatures. `hasTypedDraft`, `carriesNoteContent`, `survivingInputs`, `markDrafts`, `stampHeights`, `enter`, `leave` are each defined once in `print.js`; `enter`/`leave` are the only ones referenced by the listeners.

**Known gap — the full list, stated rather than hidden.** Task 4 defines 11 e2e tests against
roughly 30 spec rows. These spec rows have **no e2e coverage**:

| Spec rows | What is uncovered | Mitigation |
|---|---|---|
| 5a, 5b, 5c | the pop-to-flow reset — `top: auto !important`, the `right` reset, the (0,4,0) weight | `test_notes_print_css.py` pins the selector and `top: auto !important` as source text, so deletion fails; a rule present but *inert* would not be caught |
| 6b | the `.is-adding` composer | same |
| 7, 7b, 7b2, 7c, 7d | mid-edit and typed-draft textareas, incl. the `scrollHeight` stamp | the three `:not()` carve-outs are pinned as source text |
| 8, 8a, 8b | mid-delete, solitary mid-delete, no-JS rejected draft | `.note-delete-confirm` and the empty-pop `:has()` list are pinned |
| 9, 9b, 9c, 9d, 9e | the sweep filter's arms and the empty-pop rule | `hasTypedDraft` has **no** coverage of any kind |
| 10, 10b, 10c | the unanchored section, its handle, the `.block-notes` margin reset | `.unanchored-notes > details` in the sweep has **no** coverage |
| 13 | the notes hub printing un-truncated | `test_un_clamp_is_not_lesson_scoped` covers the scoping, not the rendering |
| 16, 16c | a note on a non-active slide | the `.slide[hidden]` measure-through branch has **no** coverage |
| 20 | the empty-residue leave path | — |

**Two `print.js` branches are entirely unverified**: the `hasTypedDraft` filter arm and the
`.slide[hidden]` temporary-un-hide in `stampHeights`. Rows **10** (unanchored sweep) and **16**
(note on a non-active slide) are the minimum worth adding before merge, since row 16 is the one
place this PR and PR #267 interact and neither PR covers it. The rest are defensible as a follow-up:
they are transient two-click states whose CSS is pinned as source text.

This is a real reduction against the spec. It is recorded here so the decision is explicit at review
time rather than discovered by its absence.
