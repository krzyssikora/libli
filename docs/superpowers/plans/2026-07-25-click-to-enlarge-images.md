# Click-to-enlarge Images Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Click or tap any student-facing content image to show it alone on an opaque full-viewport overlay, fitted to the screen but never enlarged past its natural size; click, tap, or press Escape to return.

**Architecture:** Templates gain one `data-zoomable` attribute per armed `<img>`. A new progressive-enhancement module `imagezoom.js` arms those images (`role="button"`, `tabindex="0"`, accessible name) and opens one reused, lazily-created modal `<dialog>` holding a copy of the image. CSS does all sizing — `max-width`/`max-height` only shrink, so "at most natural size, fitted to the viewport" needs no JS measurement. `gallery.js` additionally learns to pair `inert` with its existing `aria-hidden` writes, because arming makes something inside a carousel figure focusable for the first time.

**Tech Stack:** Django 5.2 templates, vanilla ES5-level JS (no build step), token-driven CSS, pytest + pytest-django, Playwright (Chromium), Pillow (test fixtures only).

## Global Constraints

- **Read the spec first:** `docs/superpowers/specs/2026-07-25-click-to-enlarge-images-design.md`. It carries the reasoning behind every non-obvious line below; this plan carries the code.
- **All commands run via `uv run`** from the worktree root. Bare `pytest`/`ruff`/`python` are not on PATH.
- **This worktree's `.env` is already configured** with `DATABASE_URL=…/libli_imgzoom` (test DB `test_libli_imgzoom`), isolated from the two other pipeline worktrees on this machine. Do not change it.
- **Branch is `pipeline/click-to-enlarge-images`.** Run `git branch --show-current` immediately before every commit — a parallel session has switched branches under this repo before.
- **JS style:** IIFE, `"use strict"`, ES5-level syntax (`var`, `Array.prototype.forEach.call`), no dependencies, no build step. Match `gallery.js` / `stepper.js`.
- **Falsify every test before trusting it.** Break the thing it guards, watch it go RED, restore, watch it go GREEN. A test never seen to fail proves nothing. Each task names the break.
- **e2e tests are marked `pytest.mark.e2e`** and excluded from the default run. Run them **focused and in the foreground** — a background `-m e2e` sweep spawns runaway browsers.
- **Never `git add -A`.** Stage explicit paths.
- **Two i18n strings only:** `enlarge` = "Enlarge image", `dialog` = "Enlarged image". Both catalogs (`locale/en`, `locale/pl`) must carry them, with no `#~` obsolete entries.
- **Scrim token value:** `--scrim-solid: rgba(12,11,10,0.97)`, declared exactly once, in `tokens.css`'s `:root` block, **never** in the `[data-theme="dark"]` block.

---

## File Structure

| File | Responsibility |
|---|---|
| `courses/static/courses/js/imagezoom.js` | **New.** Arm `[data-zoomable]`, own the single reused `<dialog>`, delegate click/keydown, guard Escape. Exports `window.libliInitImageZoom`. |
| `courses/static/courses/css/courses.css` | **Modify** (append a section). Trigger cursor + focus ring; `[open]`-scoped dialog box; `::backdrop`; image sizing. |
| `core/static/core/css/tokens.css` | **Modify.** One new `--scrim-solid` token in `:root` only. |
| `templates/courses/elements/imageelement.html` | **Modify.** `data-zoomable` on the `<img>`. |
| `templates/courses/elements/galleryelement.html` | **Modify.** `data-zoomable` on the figure `<img>`. |
| `templates/courses/elements/_filltable_cell.html` | **Modify.** `data-zoomable` on the `image`-branch `<img>`. |
| `templates/courses/lesson_unit.html` | **Modify.** `IMAGEZOOM_I18N` blob + script tag, after `gallery.js`. |
| `templates/courses/quiz_unit.html` | **Modify.** Same. |
| `templates/courses/manage/editor/editor.html` | **Modify.** Same (the preview pane renders student templates). |
| `courses/static/courses/js/gallery.js` | **Modify.** Pair `inert` with the four `aria-hidden` item writes; add `rescueFocus`. |
| `courses/static/courses/js/editor.js` | **Modify.** One re-arm line beside `libliInitGallery`. |
| `tests/factories.py` | **Modify.** `make_image_asset` gains `size` and `color` named parameters. |
| `tests/test_imagezoom_render.py` | **New.** Template + JS/CSS source invariants. |
| `tests/test_e2e_imagezoom.py` | **New.** 23 test functions covering the spec's 20 numbered cases, plus the media-route harness and fixtures. |
| `locale/{en,pl}/LC_MESSAGES/django.po` | **Modify.** Two new msgids. |

---

## Task 1: The `data-zoomable` hook and its guards

**Files:**
- Modify: `templates/courses/elements/imageelement.html`
- Modify: `templates/courses/elements/galleryelement.html`
- Modify: `templates/courses/elements/_filltable_cell.html`
- Test: `tests/test_imagezoom_render.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: the `data-zoomable` attribute contract that `imagezoom.js` (Task 3) selects on, and `tests/test_imagezoom_render.py`, which later tasks extend with more source invariants.

- [ ] **Step 1: Write the failing test**

Create `tests/test_imagezoom_render.py`:

```python
"""Template + source invariants for click-to-enlarge images.

The positive half (`data-zoomable` IS rendered) is what arms the feature. The negative
half (it is NOT in the authoring templates or the drag-to-image stage) is the half that
would rot silently — nothing else would notice an editor thumbnail quietly becoming
clickable, or a graded drag interaction gaining a zoom overlay.

Source-level assertions for the negatives on purpose: two of those templates need a
form/formset context to render, and the claim is about what the template *says*, not
about what one particular context happens to produce.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import render_to_string

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = REPO / "templates"

HOOK = "data-zoomable"


def _media(url="/media/x.png"):
    return SimpleNamespace(file=SimpleNamespace(url=url))


def test_fragment_anchor_survives_sanitisation():
    """The e2e Tab-traversal cases anchor on a seeded <a href="#">, and four of them would
    fail for an unrelated reason if the sanitiser dropped a bare fragment href. Nothing
    else in this repo seeds one, so pin it here rather than discovering it in Playwright.
    """
    from courses.sanitize import sanitize_html

    assert 'href="#"' in sanitize_html('<p><a href="#">Anchor link</a></p>')


def test_image_element_renders_the_hook():
    el = SimpleNamespace(media=_media(), alt="A labelled diagram", figcaption="")
    html = render_to_string("courses/elements/imageelement.html", {"el": el})
    assert HOOK in html


def test_gallery_figure_renders_the_hook():
    html = render_to_string(
        "courses/elements/galleryelement.html",
        {
            "figures": [{"url": "/media/a.png", "alt": "A", "desc": ""}],
            "desc_pos": "below",
        },
    )
    assert HOOK in html


def test_filltable_image_cell_renders_the_hook():
    html = render_to_string(
        "courses/elements/_filltable_cell.html",
        {"cell": {"kind": "image", "media": _media("/media/c.png"), "alt": "Cell"}},
    )
    assert HOOK in html


# Authoring thumbnails and the graded drag-to-image stage must never be armed.
NEVER_ARMED = [
    "courses/manage/editor/_edit_filltable.html",
    "courses/manage/editor/_edit_gallery.html",
    "courses/elements/dragtoimagequestionelement.html",
]


def test_authoring_and_dragimage_templates_have_no_hook():
    for rel in NEVER_ARMED:
        source = (TEMPLATES / rel).read_text(encoding="utf-8")
        assert HOOK not in source, rel
```

- [ ] **Step 2: Run the tests and verify the three positives fail**

Run: `uv run pytest tests/test_imagezoom_render.py -v`
Expected: the three `*_renders_the_hook` tests FAIL (`assert 'data-zoomable' in html`). Two already PASS, which is fine and expected: `test_authoring_and_dragimage_templates_have_no_hook` guards an absence that is currently true (its falsification comes in Step 5), and `test_fragment_anchor_survives_sanitisation` pins existing sanitiser behaviour rather than new code.

- [ ] **Step 3: Add the hook to the three student templates**

`templates/courses/elements/imageelement.html` — the `<img>` becomes:

```html
  <img src="{{ el.media.file.url }}" alt="{{ el.alt }}" data-zoomable>
```

`templates/courses/elements/galleryelement.html` — the frame `<img>` becomes:

```html
      <div class="gallery__frame"><img src="{{ f.url }}" alt="{{ f.alt }}" data-zoomable></div>
```

`templates/courses/elements/_filltable_cell.html` — in the `cell.kind == "image"` branch only:

```html
<img class="filltable__img" src="{{ cell.media.file.url }}" alt="{{ cell.alt }}" data-zoomable>
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_imagezoom_render.py -v`
Expected: 5 passed.

- [ ] **Step 5: Falsify all four**

For each of the three student templates: delete `data-zoomable`, re-run, confirm that test goes RED, restore.
For the negative test: add `data-zoomable` to the `<img>` in `_edit_gallery.html`, re-run, confirm RED, restore.
For `test_fragment_anchor_survives_sanitisation`: remove `"href"` from `ALLOWED_ATTRIBUTES["a"]` in `courses/sanitize.py`, re-run, confirm RED, restore. (It guards existing behaviour rather than new code, but it is falsifiable, so it is not an exemption.)
Expected: every test observed RED at least once, then 5 passed again.

- [ ] **Step 6: Commit**

```bash
git branch --show-current   # must be pipeline/click-to-enlarge-images
git add templates/courses/elements/imageelement.html \
        templates/courses/elements/galleryelement.html \
        templates/courses/elements/_filltable_cell.html \
        tests/test_imagezoom_render.py
git commit -m "feat(imagezoom): mark student content images data-zoomable"
```

---

## Task 2: Scrim token and overlay CSS

**Files:**
- Modify: `core/static/core/css/tokens.css` (`:root` block, lines 20–63)
- Modify: `courses/static/courses/css/courses.css` (append a section)
- Test: `tests/test_imagezoom_render.py` (extend)

**Interfaces:**
- Consumes: nothing.
- Produces: `--scrim-solid`; the classes `.imgzoom` (dialog), `.imgzoom__img` (overlay image), `.imgzoom-trigger` (armed trigger) that `imagezoom.js` sets in Task 3.

- [ ] **Step 1: Write the failing test**

In `tests/test_imagezoom_render.py`, **first add `import re` to the existing import block at the top of the file**, then append the constants and tests below. Two ruff rules pull in opposite directions here: appending `import re` beside the new code trips E402 (import not at top), but Task 1 could not carry the import pre-emptively because nothing there used it and that trips F401 (unused). Editing the top-of-file import block satisfies both.

```python
TOKENS_CSS = REPO / "core" / "static" / "core" / "css" / "tokens.css"
COURSES_CSS = REPO / "courses" / "static" / "courses" / "css" / "courses.css"

# Match DECLARATIONS, not substring occurrences: tokens.css also carries a comment
# explaining why this token is deliberately not repeated for dark, and a comment that
# names its own subject must not break the count.
SCRIM_DECL = re.compile(r"--scrim-solid\s*:")


def test_scrim_token_is_declared_once_and_never_in_the_dark_block():
    source = TOKENS_CSS.read_text(encoding="utf-8")
    decls = list(SCRIM_DECL.finditer(source))
    assert len(decls) == 1, f"expected one --scrim-solid declaration, got {len(decls)}"
    # The absence from the dark block IS the light/dark mechanism; this catches a
    # *relocated* definition, which the count alone would not.
    #
    # Anchor on the SELECTOR, not the first occurrence of the string: the comment this
    # token ships with names the `[data-theme="dark"]` block in prose, and that mention
    # sits ABOVE the declaration it documents -- so a plain str.index would find the
    # comment and the assertion would fail for a reason unrelated to the invariant.
    dark_selector = re.search(r'^\[data-theme="dark"\]\s*\{', source, re.MULTILINE)
    assert dark_selector, "tokens.css must still have a dark-theme block"
    assert decls[0].start() < dark_selector.start()


def test_closed_dialog_is_display_none_and_box_rules_are_open_scoped():
    source = COURSES_CSS.read_text(encoding="utf-8")
    assert "dialog.imgzoom:not([open]) { display: none; }" in source
    # Any `display` on the dialog must be [open]-scoped, or it beats the guard above
    # and leaves the overlay permanently covering the page.
    assert ".imgzoom[open] {" in source
    assert re.search(r"^\.imgzoom\s*\{", source, re.MULTILINE) is None


def test_overlay_image_can_only_shrink():
    source = COURSES_CSS.read_text(encoding="utf-8")
    assert ".imgzoom__img { max-width: 100%; max-height: 100%;" in source
    # No 100vw anywhere in the overlay block: vw includes the classic scrollbar.
    block = source[source.index(".imgzoom-trigger") :]
    assert "100vw" not in block
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_imagezoom_render.py -v -k "scrim or dialog or overlay_image"`
Expected: all three FAIL (token and rules do not exist yet). All three fail with plain
`AssertionError`. (An earlier draft of this plan predicted `ValueError: substring not found`
from `source.index(".imgzoom-trigger")` for `test_overlay_image_can_only_shrink`; that is wrong
and was disproved when the run was actually performed — the exact-substring assertion is
evaluated before the `.index()` call, so it fails first and short-circuits.)

- [ ] **Step 3: Add the token**

In `core/static/core/css/tokens.css`, inside the `:root` block, **after the `--scroll-edge` declaration** (line 41). Not immediately after `--surface-overlay` (line 36): the lines between it and `--scroll-edge` (line 41) are that token's own explanatory comment, and inserting there would wedge this token between that comment and the declaration it documents.

```css
  /* Lightbox scrim for the click-to-enlarge overlay. Declared ONCE, here, and
     deliberately NOT repeated in the [data-theme="dark"] block below: that absence is
     the mechanism by which the overlay is identical in both themes (image viewers are
     conventionally dark). A source-level test enforces it, because every neighbouring
     surface token IS defined twice and the next routine edit here is the one that would
     silently break it. Near-opaque, unlike --surface-overlay: nothing of the page may
     show through. */
  --scrim-solid: rgba(12,11,10,0.97);
```

- [ ] **Step 4: Add the overlay CSS**

Append to `courses/static/courses/css/courses.css`:

```css
/* ---------------------------------------------------------------------------
   Click-to-enlarge images. imagezoom.js arms [data-zoomable] images as buttons
   and opens one reused modal <dialog> holding a copy of the image. All sizing is
   here: max-width/max-height only ever SHRINK a replaced element, so the rendered
   size is exactly min(natural, viewport-fit) with no JS measurement.
   --------------------------------------------------------------------------- */
.imgzoom-trigger { cursor: zoom-in; }
.imgzoom-trigger:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }

/* Every box declaration below is scoped to [open]: an unscoped author-origin
   `display` would beat the UA's `dialog:not([open]) { display: none }` and leave the
   dialog permanently covering the page — the same trap as `[hidden]` vs `display:grid`
   at courses.css:353. This rule makes that explicit and guards a future edit that
   forgets the scoping; at (0,2,1) it also outranks an unscoped `.imgzoom` at (0,1,0),
   so it — not the UA rule — is what governs the closed state. */
dialog.imgzoom:not([open]) { display: none; }

.imgzoom[open] {
  /* One viewport metric per axis, deliberately: horizontal from the initial
     containing block (top/left/right), which EXCLUDES a classic scrollbar; vertical
     from 100dvh, which tracks a mobile collapsing toolbar. `inset: 0` plus an explicit
     height would over-constrain the vertical axis and mix two metrics on one axis. */
  position: fixed; top: 0; left: 0; right: 0; height: 100dvh;
  /* The UA gives dialog `max-width/max-height: calc(100% - 6px - 2em)` and
     `width/height: fit-content`; all four must be overridden. `width: auto` is NOT
     optional: leaving `fit-content` with left:0/right:0/margin:0 over-constrains the
     axis, CSS drops `right`, and the dialog collapses to a fit-content box flush LEFT —
     `place-items: center` then centres the image inside a box only as wide as the
     image, so it renders left-aligned. `margin: 0` is only safe because
     left/right/width:auto resolve the horizontal axis between them. */
  width: auto; max-width: none; max-height: none;
  margin: 0; padding: 0; border: 0; overflow: hidden;
  background: var(--scrim-solid);
  display: grid; place-items: center;
  cursor: zoom-out;
}
/* Belt-and-braces for any engine where the box does not fill the viewport. Note that
   ::backdrop only inherits custom properties from its originating element in newer
   engines (Chromium 122+); before that var(--scrim-solid) resolves to nothing here and
   the declaration is simply inert. Harmless either way, because .imgzoom[open] already
   covers the viewport -- so this rule buys less than it appears to. */
.imgzoom::backdrop { background: var(--scrim-solid); }
/* 100% of the dialog's content box — which IS the fitted viewport, per above.
   Full-bleed by design: a gutter must come as max-height: calc(100% - 2 * gutter)
   here, never as padding on the dialog, which this max-height would overflow. */
.imgzoom__img { max-width: 100%; max-height: 100%; width: auto; height: auto; display: block; }
```

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/test_imagezoom_render.py -v`
Expected: 8 passed.

- [ ] **Step 6: Falsify**

- Add a second `--scrim-solid: …` inside the `[data-theme="dark"]` block → the count test goes RED. Restore.
- Move the declaration into the dark block → the position test goes RED. Restore.
- Change `.imgzoom[open] {` to `.imgzoom {` → the open-scoping test goes RED. Restore.
- Replace `max-width: 100%; max-height: 100%` in `.imgzoom__img` with `width: 100%; height: 100%` → the first assertion goes RED. Restore.
- Change **`.imgzoom[open]`'s** `max-width: none` to `max-width: 100vw` → the no-`100vw` assertion goes RED, and only that one. Restore. Do **not** put the `100vw` on `.imgzoom__img`: its `max-width: 100%` is inside the test's exact-substring assertion, which would then fail first and short-circuit before the `100vw` scan is ever evaluated — leaving that assertion unfalsified while appearing to have been broken.
  (Editing `width: auto` → `width: 100%` is **not** a valid break here: the substring and the `100vw` scan both still hold, so the test stays green. That break belongs to Task 10's no-upscale e2e.)

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add core/static/core/css/tokens.css \
        courses/static/courses/css/courses.css \
        tests/test_imagezoom_render.py
git commit -m "feat(imagezoom): scrim token and full-viewport overlay CSS"
```

---

## Task 3: `imagezoom.js` and page wiring

**Files:**
- Create: `courses/static/courses/js/imagezoom.js`
- Modify: `templates/courses/lesson_unit.html` (after the `gallery.js` tag, ~line 74)
- Modify: `templates/courses/quiz_unit.html` (after the `gallery.js` tag, ~line 28)
- Modify: `templates/courses/manage/editor/editor.html` (after the `gallery.js` tag, ~line 152)
- Modify: `courses/static/courses/js/editor.js` (~line 97)
- Test: `tests/test_imagezoom_render.py` (extend)

**Interfaces:**
- Consumes: `data-zoomable` (Task 1); `.imgzoom`, `.imgzoom__img`, `.imgzoom-trigger` (Task 2).
- Produces: `window.libliInitImageZoom(root)` — arms `[data-zoomable]` within `root`, and `root` itself if it matches; idempotent. Consumed by `editor.js` and by `gallery.js`'s `rescueFocus` (Task 4), which targets `.imgzoom-trigger`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_imagezoom_render.py`:

```python
JS = REPO / "courses" / "static" / "courses" / "js"

PAGES_THAT_ARM = [
    "courses/lesson_unit.html",
    "courses/quiz_unit.html",
    "courses/manage/editor/editor.html",
]


def test_every_arming_page_ships_the_script_and_its_i18n_after_gallery():
    for rel in PAGES_THAT_ARM:
        source = (TEMPLATES / rel).read_text(encoding="utf-8")
        # A script tag without its i18n blob is a live failure mode, so both together.
        assert "IMAGEZOOM_I18N" in source, rel
        assert "courses/js/imagezoom.js" in source, rel
        assert source.index("courses/js/imagezoom.js") > source.index(
            "courses/js/gallery.js"
        ), f"{rel}: imagezoom.js must load after gallery.js"


def test_editor_rearms_the_preview_with_the_same_literal_the_module_exports():
    # A grep of the call site alone cannot catch a typo'd export, so pin both sides.
    editor = (JS / "editor.js").read_text(encoding="utf-8")
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    assert "window.libliInitImageZoom(preview)" in editor
    assert "window.libliInitImageZoom = " in module


def test_close_handler_focuses_the_trigger():
    # The SOLE guard on this line: Chromium focuses the trigger on mousedown, so
    # <dialog>'s native restore satisfies every e2e assertion even with it deleted.
    # The line exists for WebKit, where a click does not focus a non-form element.
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    assert "if (trigger) trigger.focus();" in module


def test_close_handler_removes_src_rather_than_emptying_it():
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    assert 'removeAttribute("src")' in module
    # `img.src = ""` resolves against the document URL and refetches the HTML page as
    # an image on every close.
    assert re.search(r"\.src\s*=\s*([\"'])\1", module) is None


def test_escape_guard_is_capture_phase_and_uses_stop_immediate():
    # unit_nav.js registers its drawer handler as a CAPTURE listener on document, so a
    # bubble-phase listener on the dialog could never stop it, and stopPropagation
    # cannot stop a same-node/same-phase peer.
    module = (JS / "imagezoom.js").read_text(encoding="utf-8")
    # Comments MUST be stripped first. imagezoom.js's own comment quotes unit_nav.js's
    # `document.addEventListener("keydown", onKeydown, true)`, so a bare `, true)` regex
    # is satisfied by that prose and the guard passes even with capture removed from the
    # real call -- proven by mutation during Task 3's review. Strip comments, then require
    # the flag to be the third argument of the SAME call that stops the event.
    code = _js_code_only(module)
    assert "stopImmediatePropagation()" in code
    assert "dialog && dialog.open" in code  # lazily created: null before first open
    assert re.search(
        r"stopImmediatePropagation\(\);?[\s\S]{0,120}?\},\s*true\s*\)", code
    ), "Escape listener must be registered capture-phase"
```

Add this helper beside the other module-level helpers:

```python
def _js_code_only(source):
    """JS source with comments stripped, so a source assertion cannot be satisfied by prose."""
    no_block = re.sub(r"/\*[\s\S]*?\*/", "", source)
    return re.sub(r"(?m)//.*$", "", no_block)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_imagezoom_render.py -v -k "arming_page or editor_rearms or close_handler or escape_guard"`
Expected: all five FAIL (`imagezoom.js` does not exist; `FileNotFoundError` on the module reads is an acceptable RED).

- [ ] **Step 3: Create the module**

Create `courses/static/courses/js/imagezoom.js`:

```js
(function () {
  "use strict";
  // Progressive enhancement: [data-zoomable] images become click/Enter/Space triggers
  // that open ONE reused modal <dialog> holding a copy of the image, fitted to the
  // viewport and never upscaled (courses.css does the sizing -- no JS measurement).
  // With this script absent the images stay plain, non-interactive <img> elements.

  // Feature-detect on a throwaway element: the real dialog is created lazily on first
  // open, so there is nothing to probe yet. Returning here also leaves
  // window.libliInitImageZoom unexported, which editor.js's `&&` guard tolerates --
  // and means no image is ever made to look clickable when clicking cannot work.
  if (typeof document.createElement("dialog").showModal !== "function") return;

  function label(key, fallback) {
    // Read defensively: a page that ships the script without the i18n blob must not
    // throw, it must fall back.
    var blob = window.IMAGEZOOM_I18N || {};
    return blob[key] || fallback;
  }

  function trimmedAlt(img) {
    return (img.getAttribute("alt") || "").trim();
  }

  var dialog = null;
  var dialogImg = null;
  var trigger = null;

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "imgzoom";
    // The dialog is named for the CONTROL, always the generic string -- never the
    // image's alt, which the contained <img> already carries. Naming both would make a
    // screen reader read the description twice on entry.
    dialog.setAttribute("aria-label", label("dialog", "Enlarged image"));

    dialogImg = document.createElement("img");
    dialogImg.className = "imgzoom__img";
    dialog.appendChild(dialogImg);

    // Any click inside the overlay closes it, the image included. A double-click on a
    // trigger therefore opens then closes (the second click lands on the dialog, which
    // now sits under the cursor) -- that is the accepted behaviour, not a bug.
    dialog.addEventListener("click", function () {
      dialog.close();
    });

    dialog.addEventListener("close", function () {
      // removeAttribute, NOT src = "": an empty src resolves against the document URL
      // and makes the browser refetch the current HTML page as an image every close.
      dialogImg.removeAttribute("src");
      if (trigger) trigger.focus();
    });

    document.body.appendChild(dialog);
  }

  function openOverlay(img) {
    if (!dialog) build();
    if (dialog.open) return; // showModal() on an open dialog throws InvalidStateError
    trigger = img;
    dialogImg.src = img.currentSrc || img.src; // already fetched: served from cache
    dialogImg.alt = trimmedAlt(img); // whitespace-only alt must not read as content
    dialog.showModal();
  }

  function armOne(img) {
    if (img.dataset.imgzoomReady === "1") return; // idempotent: the editor re-arms
    img.dataset.imgzoomReady = "1";
    img.setAttribute("role", "button");
    img.setAttribute("tabindex", "0");
    img.classList.add("imgzoom-trigger");
    // A trimmed-empty alt means the author declared the image decorative: name the
    // CONTROL so it is never a nameless button, and leave the image itself silent.
    if (!trimmedAlt(img)) {
      img.setAttribute("aria-label", label("enlarge", "Enlarge image"));
    }
  }

  function armAll(root) {
    var scope = root || document;
    // Arm `scope` itself when it matches, for parity with gallery.js's initGallery:
    // this is a public hook a caller may point straight at an image.
    if (scope.matches && scope.matches("[data-zoomable]")) armOne(scope);
    Array.prototype.forEach.call(scope.querySelectorAll("[data-zoomable]"), armOne);
  }

  // Two delegated listeners rather than N per image, so the click path does not depend
  // on the arming pass: an image in the DOM but not yet armed still zooms.
  document.addEventListener("click", function (e) {
    var img = e.target.closest && e.target.closest("[data-zoomable]");
    if (!img) return;
    // Defence in depth for a future container that nests an image in a <summary> or
    // <label>. It does NOT suppress image drag or text selection -- those start at
    // mousedown, long before click -- and no such suppression is wanted.
    e.preventDefault();
    openOverlay(img);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var img = e.target.closest && e.target.closest("[data-zoomable]");
    if (!img) return;
    e.preventDefault(); // Space would scroll the page
    openOverlay(img); // auto-repeat is harmless: later events hit the dialog.open guard
  });

  // Escape must close ONLY the overlay. unit_nav.js registers its drawer handler as
  // `document.addEventListener("keydown", onKeydown, true)` -- CAPTURE phase, on
  // document -- so it fires on the way down, before any listener on the dialog could
  // run: one Escape would close the overlay AND the drawer. Registering ours at boot,
  // also capture, also on document, puts it earlier in registration order, and
  // stopImmediatePropagation is what stops a same-node/same-phase peer. Never
  // preventDefault: that would suppress the dialog's own close request.
  document.addEventListener(
    "keydown",
    function (e) {
      if (e.key === "Escape" && dialog && dialog.open) e.stopImmediatePropagation();
    },
    true
  );

  window.libliInitImageZoom = armAll;
  armAll(document);
})();
```

- [ ] **Step 4: Wire the three pages**

In `templates/courses/lesson_unit.html`, immediately after the `gallery.js` `<script>` tag:

```html
  <script>window.IMAGEZOOM_I18N = { enlarge: "{% trans 'Enlarge image' %}", dialog: "{% trans 'Enlarged image' %}" };</script>
  <script src="{% static 'courses/js/imagezoom.js' %}" defer></script>
```

Add the identical two lines after the `gallery.js` tag in `templates/courses/quiz_unit.html` and in `templates/courses/manage/editor/editor.html`. In `editor.html`, precede them with a comment matching the file's house style:

```html
  {% comment %}The live-preview pane renders the student image/gallery/fill-table
  templates, whose images carry data-zoomable; imagezoom.js is what makes them
  clickable there too. editor.js re-runs window.libliInitImageZoom over the pane after
  each fragment swap.
  {% endcomment %}
```

- [ ] **Step 5: Add the editor re-arm line**

In `courses/static/courses/js/editor.js`, directly after the `libliInitGallery` line:

```js
    if (preview && window.libliInitImageZoom) window.libliInitImageZoom(preview);  // re-arm zoomable images
```

- [ ] **Step 6: Run the tests and verify they pass**

Run: `uv run pytest tests/test_imagezoom_render.py -v`
Expected: 13 passed.

- [ ] **Step 7: Falsify**

- Swap the `imagezoom.js` and `gallery.js` tags in `lesson_unit.html` → the order test goes RED. Restore.
- Delete the `IMAGEZOOM_I18N` blob from `quiz_unit.html` → same test goes RED. Restore.
- Rename the export to `window.libliInitImageZoomer` → the literal test goes RED. Restore.
- Delete `if (trigger) trigger.focus();` → its test goes RED. Restore.
- Change `stopImmediatePropagation()` to `stopPropagation()` → the Escape test goes RED. Restore.
- **Delete the third `true` argument** from the real `document.addEventListener("keydown", …, true)` registration, leaving every comment intact → the Escape test must go RED. This is the break that matters: with an unstripped source the comment's quoted `onKeydown, true)` rescues the assertion and a genuine bubble-phase regression ships green. Restore.

- [ ] **Step 8: Commit**

```bash
git branch --show-current
git add courses/static/courses/js/imagezoom.js \
        courses/static/courses/js/editor.js \
        templates/courses/lesson_unit.html \
        templates/courses/quiz_unit.html \
        templates/courses/manage/editor/editor.html \
        tests/test_imagezoom_render.py
git commit -m "feat(imagezoom): dialog overlay module, wired on lesson, quiz and editor"
```

---

## Task 4: `gallery.js` — `inert` plus focus rescue

**Files:**
- Modify: `courses/static/courses/js/gallery.js` (lines 41, 97, 119, 125; new `rescueFocus` helper)
- Test: `tests/test_imagezoom_render.py` (extend)

**Interfaces:**
- Consumes: `.imgzoom-trigger` (Task 3) — the class marking an image that arming actually made focusable.
- Produces: `inert` on every inactive `.gallery__item`; `rescueFocus(out, inn)`, internal to `initOne`.

**Why:** inactive carousel figures stay laid out (`position:absolute; opacity:0; pointer-events:none` + `aria-hidden`) so `gallery.js` can measure their height. `pointer-events:none` blocks clicks but nothing removes them from the tab order, so arming would give a 6-figure gallery 6 tab stops, 5 landing on an invisible image inside an `aria-hidden` subtree. `inert` fixes both in one attribute and changes no layout. But inerting a subtree blurs any focus inside it to `<body>`, and the arrow-key handler bails when focus is outside `container` (`:143`) — so without a rescue, keyboard carousel navigation would die after exactly one step.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_imagezoom_render.py`:

```python
def test_gallery_pairs_inert_with_every_item_level_aria_hidden():
    source = (JS / "gallery.js").read_text(encoding="utf-8")
    # Per-site, not a total count: gallery.js also sets aria-hidden on the indicator
    # and inside an SVG string, neither of which takes inert.
    assert source.count('it.setAttribute("inert", "")') == 2, "rest-init + settleHidden"
    assert 'out.setAttribute("inert", "")' in source, "outgoing item at fade start"
    assert 'inn.removeAttribute("inert")' in source, "incoming item's clear"


def test_gallery_rescues_focus_before_inerting_the_outgoing_item():
    source = (JS / "gallery.js").read_text(encoding="utf-8")
    assert "function rescueFocus(" in source
    # Must target the ARMED trigger: tabindex comes from imagezoom.js, not the
    # template, so focus() on a bare [data-zoomable] is a no-op when that script is
    # absent -- and gallery descriptions permit <a href>, so focus CAN sit in an
    # outgoing figure even then.
    assert ".imgzoom-trigger" in source
    # Must skip disabled controls: prev/next are disabled at the boundary slides and
    # focus() on a disabled button drops focus to <body>.
    assert 'button:not([disabled])' in source
    # The rescue must run BEFORE the outgoing item is inerted -- and the comparison
    # must anchor on the CALL, not the definition: rescueFocus is defined next to
    # settleHidden, i.e. earlier in the file than show(), so str.index would find the
    # definition and be true no matter where the call sits.
    show_at = source.index("function show(")
    call_at = source.index("rescueFocus(out, inn);", show_at)
    inert_at = source.index('out.setAttribute("inert", "")', show_at)
    assert call_at < inert_at
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_imagezoom_render.py -v -k gallery`
Expected: the two new `test_gallery_*` invariants FAIL. Note `-k gallery` also selects Task 1's `test_gallery_figure_renders_the_hook`, which passes — so the line reads "2 failed, 1 passed", not "both failed".

- [ ] **Step 3: Add `inert` to two of the three setting sites** (the third, the outgoing item in `show()`, lands in Step 4 with the rescue it depends on)

In `courses/static/courses/js/gallery.js`:

Rest-init (~line 41) — extend the comment and the write:

```js
    // At rest every item is aria-hidden AND inert; show(0) reveals the first. Items
    // stay laid out (CSS: absolute, height auto) so measure() can read their natural
    // height even while invisible. `inert` is what keeps their now-focusable zoom
    // triggers out of the tab order (aria-hidden alone does not).
    items.forEach(function (it) {
      stage.appendChild(it);
      it.setAttribute("aria-hidden", "true");
      it.setAttribute("inert", "");
    });
```

`settleHidden` (~line 97):

```js
    function settleHidden(it) {
      it.classList.remove("is-active");
      it.style.opacity = "";
      it.setAttribute("aria-hidden", "true");
      it.setAttribute("inert", "");  // re-assert: show() already inerted it at the fade start
    }
```

The incoming item's clear inside `show()` (~line 119):

```js
      inn.removeAttribute("aria-hidden");
      inn.removeAttribute("inert");  // must precede any focus move into this subtree
```

- [ ] **Step 4: Add `rescueFocus` and call it before inerting the outgoing item**

Add the helper inside `initOne`, next to `settleHidden` (it closes over `container` and `bar`):

```js
    // Inerting a subtree blurs any focus inside it to <body>, and the arrow-key handler
    // below bails when focus is outside `container` -- so without this, keyboard
    // carousel navigation dies after exactly one step. This is the ONLY site that needs
    // it: rest-init runs before anything inside a figure is focused, and settleHidden
    // re-asserts inert on an item show() already inerted 320ms earlier.
    function rescueFocus(out, inn) {
      if (!out.contains(document.activeElement)) return; // focus is on a bar control
      // The incoming item's inert was already cleared above, which is why focus can
      // land there. Prefer its ARMED trigger; a bare [data-zoomable] has no tabindex
      // when imagezoom.js is absent, and focus() on it would be a silent no-op.
      var target =
        inn.querySelector(".imgzoom-trigger") ||
        bar.querySelector("button:not([disabled])");
      if (!target) {
        // Defensive only, and unreachable by construction: initOne returns early for
        // items.length < 2, so prev and next can never both be disabled.
        container.setAttribute("tabindex", "-1");
        target = container;
      }
      target.focus();
    }
```

In `show()`, immediately before the outgoing item's `aria-hidden` write (~line 125):

```js
      rescueFocus(out, inn);
      out.setAttribute("aria-hidden", "true");  // AT sees only the incoming slide during the fade
      out.setAttribute("inert", "");
```

- [ ] **Step 5: Run the tests and the existing gallery suite**

Run: `uv run pytest tests/test_imagezoom_render.py tests/test_gallery_render.py tests/test_gallery_model.py -v`
Expected: all pass.

Then, in the **foreground**, the tests that actually execute `gallery.js`:

Run: `uv run pytest tests/test_e2e_gallery.py -m e2e -v`
Expected: all pass. This step is not optional, but be precise about what it proves and what it
does not. It proves this change did not break the **existing** carousel: mouse/click navigation,
math rendering, and two galleries staying independent. `test_gallery_render.py` and
`test_gallery_model.py` are template/model tests that never execute the JS, so they cannot detect
an `inert` regression at all — this run can.

It does **not** verify the focus rescue. `tests/test_e2e_gallery.py` contains no `ArrowRight`, no
`keyboard.press` and no `.focus()`: it advances the carousel by clicking the "Next image" button,
which leaves `document.activeElement` on that button — outside the outgoing item — so
`rescueFocus`'s `if (!out.contains(document.activeElement)) return;` bails immediately and the
meaningful branch never runs. The suite would pass with `rescueFocus` deleted entirely.

The rescue's behavioural verification is owed to **Task 9's `test_arrow_key_navigation_survives_inerting`**,
which focuses a gallery `.imgzoom-trigger`, presses ArrowRight twice, and asserts the carousel
advanced twice with focus still inside the container. Until that test is green, the rescue is
verified by source inspection only. Do not mark Task 9 complete without it passing.

- [ ] **Step 6: Falsify**

- Delete `it.setAttribute("inert", "")` from `settleHidden` → the count test goes RED. Restore.
- Move the `rescueFocus(out, inn)` call to after the `inert` write → the ordering test goes RED. Restore.
- Change `button:not([disabled])` to `button` → the disabled test goes RED. Restore.

- [ ] **Step 7: Commit**

```bash
git branch --show-current
git add courses/static/courses/js/gallery.js tests/test_imagezoom_render.py
git commit -m "fix(gallery): inert inactive figures and rescue focus before inerting"
```

---

## Task 5: i18n catalogs

**Files:**
- Modify: `locale/en/LC_MESSAGES/django.po`
- Modify: `locale/pl/LC_MESSAGES/django.po`

**Interfaces:**
- Consumes: the two `{% trans %}` strings added in Task 3.
- Produces: nothing downstream.

- [ ] **Step 1: Confirm the catalog guard currently passes**

Run: `uv run pytest tests/test_i18n_po_health.py -v`
Expected: PASS (baseline).

- [ ] **Step 2: Extract the new msgids**

Run: `uv run python manage.py makemessages -l pl -l en --no-obsolete`

- [ ] **Step 3: Fill in both catalogs**

In `locale/en/LC_MESSAGES/django.po` and `locale/pl/LC_MESSAGES/django.po`, find the two new entries and complete them:

- en: `"Enlarge image"` → `"Enlarge image"`; `"Enlarged image"` → `"Enlarged image"`
- pl: `"Enlarge image"` → `"Powiększ obraz"`; `"Enlarged image"` → `"Powiększony obraz"`

**Fuzzy trap:** if `makemessages` marked either entry `#, fuzzy`, it may have pre-filled a translation copied from an *unrelated* msgid. Clearing a fuzzy flag is **two deletions** — the `#, fuzzy` line **and** the `#| msgid "…"` line above it. Verify the msgstr is actually the right Polish text before clearing, do not trust the pre-fill.

- [ ] **Step 4: Verify catalog health**

Run: `uv run pytest tests/test_i18n_po_health.py -v`
Expected: PASS, with no `#~` obsolete entries introduced.

- [ ] **Step 5: Commit**

```bash
git branch --show-current
git add locale/en/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.po
git commit -m "i18n: Enlarge image / Enlarged image in en and pl"
```

---

## Task 6: e2e harness — media route, isolated MEDIA_ROOT, fixtures

**Files:**
- Modify: `tests/factories.py` (`make_image_asset`)
- Create: `tests/test_e2e_imagezoom.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `make_image_asset(course, filename="x.png", size=(1, 1), color="black", **kw)`; and in the new test module: `_isolated_media` (autouse), `zoom_lesson`, `tall_lesson`, `gallery_lesson`, `hidden_lesson`, `filltable_lesson`, `tiny_lesson`, `editor_unit`, `_open(page, trigger)`, `_box(locator)`, `_natural_width(locator)`.

**Why this task exists:** Tasks 7-10 all measure real pixel geometry, so they need fixture images that genuinely load, at known sizes, without polluting the developer's media tree — and a decode wait, because an `<img>` has a layout box from its alt text before its bytes arrive. Note what this task does **not** need: media interception. Django's `live_server` serves `/media/` itself from `settings.MEDIA_ROOT` (`django/test/testcases.py:1755`), regardless of `DEBUG` and regardless of `config/urls.py` gating its own route — so pointing `MEDIA_ROOT` at `tmp_path` via `_isolated_media` is the whole mechanism.

- [ ] **Step 1: Extend the factory (test-first via the harness smoke test below)**

In `tests/factories.py`, replace `make_image_asset` with:

```python
def make_image_asset(course, filename="x.png", size=(1, 1), color="black", **kw):
    """A MediaAsset(kind="image") backed by a real in-memory PNG, so any
    file-content/extension validation would pass if invoked. Mirrors the PNG
    built in test_image_file_extension_allowlist (tests/test_courses_elements.py).

    `size` and `color` are explicit named parameters, NOT part of **kw: kw is splatted
    into MediaAsset.objects.create() and an unknown key would raise on a model field.
    Defaults reproduce the previous behaviour (1x1 black) exactly, so existing callers
    are unaffected. A non-default `color` matters for the zoom e2e: the default black
    is indistinguishable from the near-black overlay scrim, which would let an
    occlusion assertion pass for the wrong reason.
    """
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    kw.setdefault("kind", "image")
    kw.setdefault("original_filename", filename)
    kw.setdefault("file", SimpleUploadedFile(filename, buf.getvalue()))
    return MediaAsset.objects.create(course=course, **kw)
```

- [ ] **Step 2: Write the harness and one smoke test**

Create `tests/test_e2e_imagezoom.py`:

```python
"""Playwright e2e for click-to-enlarge images.

Media IS served here, and nothing needs to intercept it. Django's LiveServerThread wraps
the WSGI app as `self.static_handler(_MediaFilesHandler(WSGIHandler()))` --
django/test/testcases.py:1755, unconditional, no DEBUG check -- and _MediaFilesHandler
(:1716-1726) resolves each request against settings.MEDIA_ROOT / settings.MEDIA_URL. So
/static/ and /media/ both load under live_server even though config/settings/test.py sets
DEBUG = False and config/urls.py gates its own /media/ route behind DEBUG.

That is why `_isolated_media` is doubly load-bearing: it keeps fixture PNGs out of the
developer's real media/ tree AND, because _MediaFilesHandler reads settings.MEDIA_ROOT per
request, it is what makes the fixture images resolve at all. Every geometry case still
asserts the natural size it expects BEFORE measuring anything -- that precondition now
catches a MEDIA_ROOT misconfiguration or a mis-sized fixture.

Focus placement via locator.focus()/blur() is sanctioned SETUP here: several cases need a
trigger focused but not activated, and a real click on an armed image opens the overlay.
The interaction under test -- the click, the keypress, the wheel -- is always real. The
one exception is the Tab-traversal cases, which must use real Tab presses because the tab
order IS what they test.

Marked e2e (excluded from the default run). Run focused and in the FOREGROUND -- a
background `-m e2e` sweep spawns runaway browsers.
"""

import os
import urllib.parse
from pathlib import Path

import pytest

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

VIEWPORT = {"width": 1280, "height": 800}
BIG = (1400, 900)
MAGENTA = "#FF00FF"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    Autouse and depended on by every asset fixture, deliberately: make_image_asset
    writes its bytes through the FileField at create() time, so an override applied
    later would drop a 1400x900 PNG into the developer's real media/ tree AND leave the
    route resolver with nothing to map under tmp_path.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _student(username="zoomstudent"):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _login(page, live_server, user):
    # Scope to the login form. base.html renders one <button type="submit"
    # name="language"> per enabled language in the header (templates/base.html:60-67),
    # and page.click is non-strict -- an unscoped click POSTs the language switcher and
    # reloads the login page with nobody authenticated. Mirrors the proven helper at
    # tests/test_e2e_editor.py:38-47.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(user.username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _image_unit(course, size=BIG, color=MAGENTA, alt="A labelled diagram", name="z.png"):
    from courses.models import ImageElement

    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename=name, size=size, color=color)
    add_element(unit, ImageElement.objects.create(media=asset, alt=alt))
    return unit


@pytest.fixture
def zoom_lesson(db, _isolated_media):
    """One lesson unit, one ImageElement, 1400x900 magenta, non-empty alt.

    _isolated_media is listed explicitly, not relied on as autouse-ordering: the asset
    is written through the FileField at create() time, and a silent mis-ordering would
    drop a 1400x900 PNG into the developer's real media/ tree.
    """
    course = CourseFactory()
    unit = _image_unit(course)
    user = _student()
    EnrollmentFactory(course=course, student=user)
    return unit, user


def _goto(page, live_server, unit, user):
    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))


def _trigger(page):
    return page.locator("[data-zoomable]").first


def _open(page, trigger):
    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")
    # The [open] attribute is set synchronously, but the overlay <img> re-requests
    # from the network rather than a warm cache, so
    # measuring immediately can read naturalWidth == 0 and a zero-area box. Wait for the
    # decode before any geometry is taken.
    page.wait_for_function(
        "() => { const i = document.querySelector('.imgzoom__img');"
        " return i && i.complete && i.naturalWidth > 0; }"
    )
    return page.locator("dialog.imgzoom")


def _await_decoded(page, locator):
    """Wait for an <img> to actually have pixels before measuring it.

    locator.wait_for() defaults to state="visible", which only needs a non-empty box --
    and an <img> whose bytes have not arrived still gets one from its alt text, so
    naturalWidth can legitimately read 0. Every fixture image is served through
    the live server rather than a warm cache, so this race is real for the inline trigger
    exactly as it is for the overlay image.
    """
    locator.wait_for()
    page.wait_for_function(
        "el => el.complete && el.naturalWidth > 0", arg=locator.element_handle()
    )


def _box(locator):
    box = locator.bounding_box()
    assert box is not None, "expected a laid-out box"
    return box


def _natural_width(locator):
    return locator.evaluate("el => el.naturalWidth")


def test_harness_serves_the_real_fixture_image(page, live_server, zoom_lesson):
    """The precondition every geometry case depends on.

    Without the media route this fails with naturalWidth == 0, which is exactly the
    silent failure the route exists to prevent.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    assert _natural_width(trigger) == 1400
```

- [ ] **Step 3: Run the smoke test and watch it pass**

Run: `uv run pytest tests/test_e2e_imagezoom.py -m e2e -v`
Expected: PASS.

- [ ] **Step 4: Falsify the harness**

The guard here is `_isolated_media`, not an interception. Point `MEDIA_ROOT` somewhere with no
fixture file in it — e.g. temporarily set `settings.MEDIA_ROOT = str(tmp_path / "empty")` in
`_isolated_media` — and re-run.
Expected: RED. Django's `_MediaFilesHandler` then 404s the image, `naturalWidth` reads 0, and the
smoke test's `== 1400` precondition fails — proving that precondition is load-bearing and that a
missing image cannot be silently measured as a valid one. Restore.

(An earlier draft prescribed "comment out the `media_route(page)` call and expect `assert 0 == 1400`".
That break provably could not go RED, because Django serves the media itself — see the module
docstring. Verified twice in Task 6: from `django/test/testcases.py:1755`, and empirically.)

- [ ] **Step 5: Confirm the factory change broke nothing and left no files behind**

Run: `uv run pytest tests/test_gallery_render.py tests/test_courses_elements.py tests/test_media_model.py -v`
Expected: PASS (defaults reproduce the old 1×1 black PNG exactly).

Run: `git status --porcelain --ignored media/` — expected: **empty**. `--ignored` is mandatory: `.gitignore:8` is `/media/`, so a plain `git status --porcelain media/` is empty whether or not a stray PNG landed there — a vacuous guard on exactly the file-lifetime incident this is meant to catch.

- [ ] **Step 6: Commit**

```bash
git branch --show-current
git add tests/factories.py tests/test_e2e_imagezoom.py
git commit -m "test(imagezoom): e2e harness with isolated MEDIA_ROOT and decode waits"
```

---

## Task 7: e2e — closed state, geometry, occlusion (cases 1–3)

**Files:**
- Modify: `tests/test_e2e_imagezoom.py`

**Interfaces:**
- Consumes: `zoom_lesson`, `_goto`, `_open`, `_box`, `_natural_width`, `_trigger`, `_await_decoded` (Task 6).
- Produces: nothing downstream.

- [ ] **Step 1: Write the tests**

Append to `tests/test_e2e_imagezoom.py`:

```python
def test_closed_dialog_is_not_rendered(page, live_server, zoom_lesson):
    """Open, close, THEN assert -- the dialog is created lazily.

    Asserting "absent or invisible" before the first open would be vacuous: it passes
    even with `display: grid` unscoped, which is the very bug this case exists to catch.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    dialog.click()
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")

    assert dialog.evaluate("el => el.checkVisibility()") is False
    assert dialog.bounding_box() is None  # display:none -> None, not a zero-area box


def test_overlay_enlarges_without_upscaling_and_fits_the_viewport(
    page, live_server, zoom_lesson
):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)  # or inline_width is measured pre-load and the
    assert _natural_width(trigger) == 1400, "media route must serve the real image"
    inline_width = _box(trigger)["width"]  # "overlay is wider" passes for the wrong reason

    dialog = _open(page, trigger)
    img = page.locator(".imgzoom__img")
    box = _box(img)

    assert box["width"] > inline_width, "the overlay must actually enlarge"
    assert box["width"] <= _natural_width(img) + 0.5, "never upscaled past natural size"

    # Half-pixel tolerance is not decoration: for this fixture the vertical axis sits
    # EXACTLY at the 800px cap and the 0.888... scale factor rounds at device-pixel
    # resolution. Only the horizontal axis has real slack.
    assert box["x"] >= -0.5 and box["y"] >= -0.5
    assert box["x"] + box["width"] <= VIEWPORT["width"] + 0.5
    assert box["y"] + box["height"] <= VIEWPORT["height"] + 0.5

    # The dialog itself must fill the scrollbar-EXCLUDED ICB. This, not the image box,
    # is what a `100vw` regression violates: with width:100vw the dialog spans 1280
    # while the ICB is ~1265, yet the height-capped image still centres inside it and
    # every image-box assertion above stays green.
    client_width = page.evaluate("() => document.documentElement.clientWidth")
    assert abs(_box(dialog)["width"] - client_width) <= 0.5

    # Centred in the VIEWPORT, not merely inside the dialog: an in-dialog check is
    # invariant to a fit-content dialog (both of its internal bands are 0) sitting
    # flush left.
    right_band = client_width - box["x"] - box["width"]
    assert abs(box["x"] - right_band) <= 1

    # Aspect ratio survives, so a stretched image is caught however an engine treats
    # grid stretching of a replaced element.
    assert abs(box["width"] / box["height"] - 1400 / 900) < 0.01


def test_nothing_but_the_image_is_visible(
    page, live_server, zoom_lesson, tmp_path
):
    """checkVisibility() cannot express this -- a modal <dialog> makes the rest of the
    document inert, not unrendered, so the lesson article still reports visible. Assert
    occlusion two independent ways instead.
    """
    from PIL import Image

    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    img = page.locator(".imgzoom__img")
    box = _box(img)

    # (a) the resolved scrim colour, read from the token rather than hardcoded so a
    # design-pass retune cannot turn this red.
    token = page.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--scrim-solid').trim()"
    )
    expected = [int(n) for n in token.split("(")[1].split(")")[0].split(",")[:3]]
    alpha = float(token.split(",")[-1].strip(") "))
    assert alpha >= 0.95, f"scrim must be near-opaque, got {token}"

    resolved = dialog.evaluate("el => getComputedStyle(el).backgroundColor")
    got = [int(n) for n in resolved.split("(")[1].split(")")[0].split(",")[:3]]
    assert all(abs(a - b) <= 12 for a, b in zip(got, expected)), (resolved, token)
    # Relative luminance, the third spec invariant: it is what catches a retune to a
    # LIGHT scrim that still matches its own token.
    lum = (0.2126 * got[0] + 0.7152 * got[1] + 0.0722 * got[2]) / 255
    assert lum < 0.05, f"scrim must be dark, luminance {lum:.3f}"
    # Asserting alpha alone would be untestable: the UA gives dialog an OPAQUE
    # `background-color: Canvas`, so deleting the author background leaves alpha at 1.0
    # and renders an opaque WHITE panel. Hence the channel check.

    # (b) pixel sampling in the letterbox bands beside the measured image box -- NOT
    # where the article text sits, which at this viewport is entirely behind the image.
    # Pin the assumption the coordinate mapping rests on rather than trusting a default.
    assert page.evaluate("() => devicePixelRatio") == 1
    assert box["x"] >= 6, f"letterbox band too narrow to sample: x={box['x']}"
    shot = tmp_path / "imgzoom-occlusion.png"  # never the repo root
    dialog.screenshot(path=str(shot))
    frame = Image.open(shot).convert("RGB")
    xs = [2, int(box["x"] / 2), int(box["x"]) - 3]
    ys = [2, int(box["height"] / 2), int(box["height"]) - 3]
    for x in xs:
        for y in ys:
            px = frame.getpixel((x, y))
            assert all(abs(a - b) <= 12 for a, b in zip(px, expected)), (x, y, px)
```

Note: `device_scale_factor` defaults to 1 in Playwright's Chromium context (nothing in `conftest.py` overrides `browser_context_args`), so box coordinates map 1:1 onto screenshot pixels. That assumption is not left implicit — the occlusion test asserts `devicePixelRatio == 1` before it samples, so a future context change fails loudly here instead of skewing the sample coordinates silently.

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_e2e_imagezoom.py -m e2e -v`
Expected: 4 passed.

- [ ] **Step 3: Falsify each, one break per contract**

| Break (in `courses.css`) | Must go RED |
|---|---|
| Unscope `display: grid` **and** delete the `dialog.imgzoom:not([open])` rule (both — the guard at (0,2,1) outranks `.imgzoom` at (0,1,0), so unscoping alone stays green) | `test_closed_dialog_is_not_rendered` |
| Delete `max-height: 100%` from `.imgzoom__img` | the in-viewport assertion |
| `width: 100vw` on `.imgzoom[open]` | the **dialog-width** assertion (not the image-box one) |
| `place-items: start` instead of `center` | the centring assertion |
| Drop `width: auto` (UA `fit-content` returns) | the centring assertion |
| Re-point `background` at `var(--surface-overlay)` | occlusion (a) |
| Delete **both** the box `background` and the `::backdrop` rule (only `::backdrop` is individually unfalsifiable — the box background covers the sampled band, so deleting the box rule alone exposes the UA's opaque white `Canvas` and (b) goes red on its own) | occlusion (b) |

Restore after each.

- [ ] **Step 4: Commit**

```bash
git branch --show-current
git add tests/test_e2e_imagezoom.py
git commit -m "test(imagezoom): e2e closed state, geometry and occlusion"
```

---

## Task 8: e2e — close paths, keyboard, names, scroll lock (cases 4–8, 12–14)

**Files:**
- Modify: `tests/test_e2e_imagezoom.py`

**Interfaces:**
- Consumes: Task 6's fixtures and helpers.
- Produces: `tall_lesson` fixture.

- [ ] **Step 1: Write the tests**

Append to `tests/test_e2e_imagezoom.py`:

```python
@pytest.fixture
def tall_lesson(db, _isolated_media):
    """zoom_lesson plus enough text that the page scrolls at 1280x800."""
    from courses.models import TextElement

    course = CourseFactory()
    unit = _image_unit(course)
    for i in range(12):
        add_element(unit, TextElement.objects.create(body=f"<p>Filler paragraph {i}.</p>"))
    user = _student("tallstudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


def test_second_click_closes_and_restores_focus(page, live_server, zoom_lesson):
    """Smoke test of the close path.

    This case CANNOT falsify the explicit `trigger.focus()`, and no Chromium e2e can:
    Chromium focuses the trigger on mousedown -- after any blur, before the delegated
    handler runs showModal() -- so the recorded pre-open focus is the trigger and the
    native restore satisfies this even with our line deleted. The source-level assertion
    in tests/test_imagezoom_render.py is the sole guard on it.
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    dialog = _open(page, trigger)
    dialog.click()
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")
    assert trigger.evaluate("el => el === document.activeElement")


def test_escape_closes_the_overlay(page, live_server, zoom_lesson):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    _open(page, _trigger(page))
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")


def test_escape_does_not_also_close_the_unit_drawer(page, live_server, zoom_lesson):
    """The only guard on the stopImmediatePropagation decision.

    The gesture is spelled out because the obvious one is impossible: an open drawer is
    position:fixed; inset:0; z-index:50 with a full-viewport scrim carrying
    data-unit-drawer-close, so a real click on the image lands on the scrim and closes
    the drawer instead. Opening the overlay first is impossible too -- a modal <dialog>
    makes the document inert. So: focus the trigger (sanctioned setup) and press Enter.
    """
    unit, user = zoom_lesson
    page.set_viewport_size({"width": 390, "height": 844})  # drawer only exists <=640px
    _login(page, live_server, user)
    page.goto(_lesson_url(live_server, unit))

    page.click("[data-unit-drawer-open]")
    drawer = page.locator(".unit-drawer")
    assert drawer.evaluate("el => !el.hidden")

    _trigger(page).focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog.imgzoom[open]")

    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")
    assert drawer.evaluate("el => !el.hidden"), "one Escape closed the drawer too"


def test_double_click_opens_then_closes(page, live_server, zoom_lesson):
    """The accepted behaviour: the second click lands on the now-covering dialog."""
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)

    # Positive control first, or this test cannot tell "opened then closed" from "never
    # opened at all": a 404'd script, a bailed feature detect or a deleted click handler
    # would all leave the count at 0 and read as GREEN.
    box = _box(trigger)
    point = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    trigger.click()
    page.wait_for_selector("dialog.imgzoom[open]")  # proves the open really happens
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")

    page.mouse.dblclick(*point)
    assert page.locator("dialog.imgzoom[open]").count() == 0


def test_enter_opens_from_the_keyboard(page, live_server, zoom_lesson):
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    _trigger(page).focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog.imgzoom[open]")


def test_accessible_names(page, live_server, zoom_lesson):
    """Non-empty-alt branch here; the empty-alt branch is on the gallery fixture."""
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    page.get_by_role("button", name="A labelled diagram").wait_for()
    _open(page, _trigger(page))
    # The dialog is named for the CONTROL, never with the image's alt -- naming both
    # would make a screen reader read the description twice on entry.
    dialog = page.locator("dialog.imgzoom")
    assert dialog.get_attribute("aria-label") == "Enlarged image"


def test_focus_stays_inside_the_open_overlay(page, live_server, zoom_lesson):
    """UA focus trap. Non-obvious because the overlay contains no focusable element.

    Nothing of ours to delete, so the positive control carries the weight: the same two
    Tabs with the overlay CLOSED must move focus, proving the keypresses were dispatched
    and that a pass is not "focus never entered the dialog".
    """
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)

    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    moved = page.evaluate("() => document.activeElement !== document.body")
    assert moved, "positive control: Tab must move focus on the closed page"

    _open(page, _trigger(page))
    for _ in range(2):
        page.keyboard.press("Tab")
        inside = page.evaluate(
            "() => document.querySelector('dialog.imgzoom')"
            ".contains(document.activeElement)"
        )
        assert inside, "focus escaped the modal dialog"


def test_close_removes_the_src_attribute(page, live_server, zoom_lesson):
    """`img.src = ""` would resolve against the document URL and refetch the HTML page
    as an image on every close."""
    unit, user = zoom_lesson
    _goto(page, live_server, unit, user)
    dialog = _open(page, _trigger(page))
    dialog.click()
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")
    assert page.locator(".imgzoom__img").get_attribute("src") is None


def test_the_page_behind_does_not_scroll(page, live_server, tall_lesson):
    """Tests the platform claim rather than trusting it. The positive control IS the
    falsification: there is no line of ours to delete."""
    unit, user = tall_lesson
    _goto(page, live_server, unit, user)
    assert page.evaluate(
        "() => document.documentElement.scrollHeight > window.innerHeight"
    ), "fixture must be taller than the viewport or scrollY is 0 either way"

    _open(page, _trigger(page))
    before = page.evaluate("() => window.scrollY")
    page.mouse.move(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2)
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(150)
    assert page.evaluate("() => window.scrollY") == before

    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.imgzoom[open]", state="detached")
    page.mouse.wheel(0, 400)
    page.wait_for_timeout(150)
    assert page.evaluate("() => window.scrollY") > before, "positive control failed"
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_e2e_imagezoom.py -m e2e -v`
Expected: 13 passed.

- [ ] **Step 3: Falsify**

| Break | Must go RED |
|---|---|
| Add `e.preventDefault()` to the Escape branch in `imagezoom.js` (this is the only break that works — deleting the listener leaves the dialog closing) | `test_escape_closes_the_overlay` |
| Delete `e.stopImmediatePropagation()` | `test_escape_does_not_also_close_the_unit_drawer` |
| Add a timing window that swallows the second click | `test_double_click_opens_then_closes` |
| Delete the `keydown` delegation | `test_enter_opens_from_the_keyboard` |
| Replace `removeAttribute("src")` with `img.src = ""` | `test_close_removes_the_src_attribute` |
| Delete the dialog's `aria-label` write in `build()` | `test_accessible_names` (its dialog-name half) |

- [ ] **Step 4: Commit**

```bash
git branch --show-current
git add tests/test_e2e_imagezoom.py
git commit -m "test(imagezoom): e2e close paths, keyboard, names and scroll lock"
```

---

## Task 9: e2e — gallery and hidden containers (cases 9–11, 15–17)

**Files:**
- Modify: `tests/test_e2e_imagezoom.py`

**Interfaces:**
- Consumes: Task 6's helpers; `.imgzoom-trigger` and the `inert` behaviour from Tasks 3–4.
- Produces: `gallery_lesson`, `hidden_lesson` fixtures; `_tab_walk(page, n)` helper.

- [ ] **Step 1: Write the tests**

Append to `tests/test_e2e_imagezoom.py`:

```python
@pytest.fixture
def gallery_lesson(db, _isolated_media):
    """Anchor link, then a 3-figure gallery.

    Figure 1 is active on load and carries an EMPTY description -> empty alt: that is
    the decorative branch, and it must be the ACTIVE figure because inactive figures are
    aria-hidden and Playwright's role engine cannot see them at all.

    Gallery alt is NOT authorable: GalleryElement stores {media, desc} and render()
    derives alt = desc_to_alt(desc), substituting a generic "Image n of m" when a
    non-empty desc strips to nothing. So an empty alt requires an EMPTY desc, and a
    math-only desc must be avoided.

    No <a href> in any description: GalleryElement.save() sanitises each desc through
    sanitize_cell, whose allowlist is CELL_TAGS = {strong, b, em, i, u, br} with
    attributes={} (courses/sanitize.py:62) -- a link would be silently stripped to bare
    text, so a fixture "carrying a link" would document a case it does not have.
    """
    from courses.models import GalleryElement
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    add_element(
        unit, TextElement.objects.create(body='<p><a href="#">Anchor link</a></p>')
    )
    descs = ["", "Second figure", "Third figure"]
    colors = ["#FF00FF", "#00FF00", "#0000FF"]
    images = [
        {
            "media": make_image_asset(
                course, filename=f"gal{i}.png", size=(800, 600), color=colors[i]
            ).pk,
            "desc": desc,
        }
        for i, desc in enumerate(descs)
    ]
    add_element(
        unit,
        GalleryElement.objects.create(data={"images": images, "desc_pos": "below"}),
    )
    user = _student("gallerystudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


@pytest.fixture
def hidden_lesson(db, _isolated_media):
    """DOM order is LOAD-BEARING and fixed: anchor, tabs, spoiler, then the reveal gate
    with the gated image LAST.

    The gate's rule is `.slide > .lesson-block:has(...) ~ .lesson-block:not(.reveal-shown)
    { display: none }` -- a GENERAL SIBLING combinator over blocks that
    _lesson_article.html wraps in `.slide > .lesson-block`. So the gate hides EVERY later
    block in the unit, not just its own answer: anything placed after it would be
    display:none and its positive control would fail for a reason unrelated to this
    feature, while its negative half passed vacuously.

    NO STEPPER IMAGE, deliberately. StepperStep.content is a CharField of plain text +
    KaTeX (courses/models.py:503-508) -- a stepper step cannot contain an element at all,
    so no image can ever be hidden by the stepper mechanism and there is nothing for this
    feature to test there. The stepper row of the spec's hiding table stays true (it does
    hide steps) but is unreachable by an image, which is why no stepper case follows.
    """
    from courses.models import Element
    from courses.models import ImageElement
    from courses.models import RevealGateElement
    from courses.models import SpoilerElement
    from courses.models import TabsElement
    from courses.models import TextElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")

    def img(name):
        asset = make_image_asset(course, filename=name, size=(400, 300), color="#00FFFF")
        return ImageElement.objects.create(media=asset, alt=f"Hidden {name}")

    add_element(
        unit, TextElement.objects.create(body='<p><a href="#">Anchor link</a></p>')
    )

    # Tabs: default_data() MINTS its own tab ids (new_tab_id -> "t" + 6 hex), so read
    # them back rather than assuming literals, and key the child to the SECOND tab so it
    # lands in the panel that ships [hidden]. Nesting pattern: tests/test_e2e_tabs.py:110.
    tabs_obj = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = add_element(unit, tabs_obj)
    second_tab_id = tabs_obj.data["tabs"][1]["id"]
    Element.objects.create(
        unit=unit, content_object=img("tabbed.png"), parent=tabs_join, tab_id=second_tab_id
    )

    # Spoiler: `label`, not `summary` (courses/models.py:397-408), and its single child
    # slot id is SpoilerElement.SLOT_ID == "only".
    spoiler_join = add_element(unit, SpoilerElement.objects.create(label="Show"))
    Element.objects.create(
        unit=unit,
        content_object=img("spoilered.png"),
        parent=spoiler_join,
        tab_id=SpoilerElement.SLOT_ID,
    )

    # The gate hides every FOLLOWING sibling, so it goes second-to-last and its answer
    # image last.
    add_element(unit, RevealGateElement.objects.create(label="Show answer"))
    add_element(unit, img("gated.png"))

    # Ordering comes from creation sequence: Element.order is OrderField(for_fields=["unit"])
    # with Meta.ordering = ["order", "pk"], and nested child rows consume numbers from the
    # same per-unit counter -- which is why each container's child is created immediately
    # after the container above, keeping the top-level sequence monotonic.
    user = _student("hiddenstudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user



def _tab_walk(page, n=24):
    """Press Tab up to n times from the current focus, recording each activeElement.

    A single <body>/null observation is a WRAP, not an exit (Chromium passes through it),
    so continue; only two consecutive such observations terminate.

    `cls` reads getAttribute('class') rather than a.className, because on an SVG element
    className is an SVGAnimatedString and would not serialise as a string. It is only used
    for debugging output, but a silently-empty field is worse than none.
    """
    seen = []
    blanks = 0
    for _ in range(n):
        page.keyboard.press("Tab")
        info = page.evaluate(
            "() => { const a = document.activeElement;"
            " if (!a || a === document.body) return null;"
            " const item = a.closest('.gallery__item');"
            " return { tag: a.tagName, cls: a.getAttribute('class') || '',"
            "   alt: a.getAttribute('alt') || '',"
            "   inInactiveFigure: !!(item && !item.classList.contains('is-active')),"
            "   isTrigger: a.classList.contains('imgzoom-trigger'),"
            "   inHiddenPanel: !!a.closest('[hidden]') }; }"
        )
        if info is None:
            blanks += 1
            if blanks >= 2:
                break
            continue
        blanks = 0
        seen.append(info)
    return seen


def test_only_the_active_gallery_figure_is_a_tab_stop(
    page, live_server, gallery_lesson
):
    """A get_by_role("button") COUNT is not a valid test here: inactive figures already
    carry aria-hidden today and Playwright's role engine excludes ARIA-hidden elements,
    so that assertion is already green with `inert` removed. Real Tab traversal, with a
    positive control.

    The anchor precedes the gallery deliberately: the "Previous image" button is disabled
    at rest (idx 0), so it can be neither clicked nor focused, and gallery.js appends the
    bar AFTER the stage, so forward Tab from a bar control would only reach the figures
    after wrapping past the end of the document.
    """
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    page.get_by_role("link", name="Anchor link").click()

    seen = _tab_walk(page)
    assert any(s["isTrigger"] for s in seen), "traversal never reached a zoom trigger"
    assert not any(s["inInactiveFigure"] for s in seen), "focus entered an inactive figure"


def test_arrow_key_navigation_survives_inerting(
    page, live_server, gallery_lesson
):
    """Focus a zoom trigger, ArrowRight twice, assert the carousel advanced twice.

    Without the focus rescue, inerting the outgoing figure blurs focus to <body>, the
    arrow handler's `container.contains(t)` guard then fails, and navigation dies after
    exactly one step.
    """
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    page.locator(".gallery__item.is-active .imgzoom-trigger").focus()

    def active_index():
        return page.evaluate(
            "() => Array.from(document.querySelectorAll('.gallery__item'))"
            ".findIndex(el => el.classList.contains('is-active'))"
        )

    assert active_index() == 0
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)  # 320ms fade + slack
    assert active_index() == 1
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    assert active_index() == 2, "second ArrowRight ignored -- focus was lost to <body>"
    assert page.evaluate(
        "() => document.querySelector('[data-gallery]')"
        ".contains(document.activeElement)"
    )


def test_clicking_the_active_gallery_figure_opens_the_overlay(
    page, live_server, gallery_lesson
):
    """The gallery is the surface with all the pointer complications and the only one
    whose click-to-open path nothing else exercises."""
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    trigger = page.locator(".gallery__item.is-active .imgzoom-trigger")
    _open(page, trigger)


def test_decorative_gallery_figure_is_named_for_the_control(
    page, live_server, gallery_lesson
):
    """The empty-alt branch: figure 1 has an empty description, so its alt is empty and
    arming must give it an aria-label instead of leaving a nameless button."""
    unit, user = gallery_lesson
    _goto(page, live_server, unit, user)
    page.wait_for_selector(".gallery__item.is-active")
    page.get_by_role("button", name="Enlarge image").first.wait_for()


def test_inactive_tab_panel_keeps_its_image_out_of_the_tab_order(
    page, live_server, hidden_lesson
):
    unit, user = hidden_lesson
    _goto(page, live_server, unit, user)
    page.get_by_role("link", name="Anchor link").click()
    seen = _tab_walk(page, n=30)
    assert not any(s["inHiddenPanel"] for s in seen)

    # Positive control, and it must be able to fail: activate the second tab, walk
    # again, and require a trigger inside the now-visible panel to be REACHED.
    # `.tabs__tab`, NOT `[data-tab-btn]` -- that attribute exists nowhere in the repo.
    # tabselement.html emits only [data-tab-label] headings and [data-tab-panel] panels;
    # tabs.js:66-73 builds the strip buttons itself as button.tabs__tab[role=tab].
    # Walk order to expect: active tab button -> active panel (tabs.js:77 sets
    # panel.tabIndex = 0) -> the trigger inside it, with a roving tabindex on the
    # inactive tab buttons (tabs.js:94).
    page.get_by_role("tab").nth(1).click()
    page.wait_for_selector('[data-tab-panel]:not([hidden]) .imgzoom-trigger')
    page.get_by_role("link", name="Anchor link").click()
    seen_after = _tab_walk(page, n=30)
    assert any(s["isTrigger"] for s in seen_after), "tab image unreachable once revealed"

    # Falsify with `[data-tab-panel][hidden] { display: block }` in courses.css -- that
    # keeps the attribute while making the image focusable. REMOVING the hidden attribute
    # is not a valid break: this assertion keys on closest('[hidden]'), which would then
    # return null and leave inHiddenPanel false, and tabs.js:96-99 re-applies it anyway.


def test_closed_spoiler_keeps_its_image_out_of_the_tab_order(
    page, live_server, hidden_lesson
):
    """UNFALSIFIABLE SMOKE CHECK, stated as such: a closed <details> skips its contents
    via content-visibility and skipped contents are not focusable, so an author
    `display: block` on a child cannot restore focusability -- there is no break
    available. Its value is the positive control below.
    """
    unit, user = hidden_lesson
    _goto(page, live_server, unit, user)
    spoiler_img = page.locator("details .imgzoom-trigger")
    assert spoiler_img.evaluate_all("els => els.every(el => !el.checkVisibility())")
    page.locator("details > summary").first.click()
    assert spoiler_img.first.evaluate("el => el.checkVisibility()")


def test_gated_image_stays_out_of_the_tab_order(
    page, live_server, hidden_lesson
):
    """The highest-stakes row of the hiding table: a leaked tab stop would let a keyboard
    user open a gated ANSWER image before passing the gate.

    Gate only, no stepper half: StepperStep.content is a CharField of plain text + KaTeX
    (courses/models.py:503-508), so a stepper step cannot contain an element and no image
    can ever be hidden by that mechanism. The stepper row of the spec's hiding table stays
    true but is unreachable by this feature -- so there is deliberately no stepper
    assertion here, and no stepper falsification either.
    """
    unit, user = hidden_lesson
    _goto(page, live_server, unit, user)
    page.get_by_role("link", name="Anchor link").click()
    seen = _tab_walk(page, n=30)
    gated_reachable = page.evaluate(
        "() => Array.from(document.querySelectorAll('.imgzoom-trigger'))"
        ".some(el => el.checkVisibility() && el.alt.includes('gated'))"
    )
    assert not gated_reachable, "gated answer image is rendered before the gate is passed"
    # No inInactiveFigure assertion here: hidden_lesson has no gallery, so that flag is
    # False for every observation by construction and the check could never fail. What the
    # walk is for is this -- the gated trigger must never be reached before the gate:
    assert not any(
        s["isTrigger"] and "gated" in (s.get("alt") or "") for s in seen
    )
    # Positive control: pass the gate, the image becomes reachable.
    page.locator("[data-reveal-gate]").click()
    page.wait_for_timeout(200)
    assert page.evaluate(
        "() => Array.from(document.querySelectorAll('.imgzoom-trigger'))"
        ".some(el => el.checkVisibility() && el.alt.includes('gated'))"
    )
```

**Note for the implementer:** the `hidden_lesson` fixture's nested-element construction (image inside a tab panel and inside a spoiler — never a stepper step, which cannot hold an element) uses this repo's `Element.parent` nesting API, spelled out in the fixture above. The nesting call is `Element.objects.create(unit=unit, content_object=obj, parent=<container join row>, tab_id=<slot id>)`, verified at `tests/test_e2e_tabs.py:110`, and `"image"` is in `courses/builder.py`'s `NESTABLE_TYPE_KEYS`, so an image genuinely does nest in tabs and spoilers. Other real references: `tests/test_e2e_twocolumn.py`, `tests/test_e2e_reveal_gate.py`, `tests/test_context_stepper.py`. (`tests/test_nest_selfchecks.py` does **not** exist — do not go looking for it.)

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_e2e_imagezoom.py -m e2e -v`
Expected: 20 passed. Expect to iterate on the `hidden_lesson` fixture's nesting API and selectors — that is normal, and the assertions above are the contract to preserve while doing so.

- [ ] **Step 3: Falsify**

| Break | Must go RED |
|---|---|
| Remove the `inert` handling from `gallery.js` | `test_only_the_active_gallery_figure_is_a_tab_stop` |
| Drop the focus rescue, keep the inerting | `test_arrow_key_navigation_survives_inerting` |
| Remove `inn.removeAttribute("inert")` (`:119`) | `test_clicking_the_active_gallery_figure_opens_the_overlay` |
| Delete the `aria-label` branch in `armOne` | `test_decorative_gallery_figure_is_named_for_the_control` |
| Add `[data-tab-panel][hidden] { display: block }` to `courses.css` | `test_inactive_tab_panel_keeps_its_image_out_of_the_tab_order` |
| Delete the whole `display: none` declaration from the `{% if has_reveal_gate %}` `<style>` in `lesson_unit.html` — **not** the `:not(.reveal-shown)` clause, which would hide the block *unconditionally* and leave the test green | `test_gated_image_stays_out_of_the_tab_order` |

- [ ] **Step 4: Commit**

```bash
git branch --show-current
git add tests/test_e2e_imagezoom.py
git commit -m "test(imagezoom): e2e gallery tab order, arrow nav and hidden containers"
```

---

## Task 10: e2e — remaining surfaces (cases 18–20)

**Files:**
- Modify: `tests/test_e2e_imagezoom.py`

**Interfaces:**
- Consumes: Task 6's helpers.
- Produces: `filltable_lesson`, `tiny_lesson`, `editor_unit` fixtures.

- [ ] **Step 1: Write the tests**

Append to `tests/test_e2e_imagezoom.py`:

```python
@pytest.fixture
def filltable_lesson(db, _isolated_media):
    """A fill-in table whose one cell is an image cell."""
    from courses.models import FillTableElement

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="cell.png", size=(800, 600), color="#FFAA00")
    # Verified schema (courses/models.py:1007-1017): an image cell is
    # {"kind": "image", "media": <int pk>, "alt": str, "halign": ..., "valign": ...}.
    # `media` MUST be a real int -- normalize_data silently downgrades a non-int (or a
    # bool) to an empty STATIC cell, which renders no <img> at all and would make this
    # test fail for a reason unrelated to the feature.
    add_element(
        unit,
        FillTableElement.objects.create(
            data={
                "cells": [[{"kind": "image", "media": asset.pk, "alt": "Table image"}]],
                "header_row": False,
                "header_col": False,
                "border": "all",
            }
        ),
    )
    user = _student("filltablestudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


@pytest.fixture
def tiny_lesson(db, _isolated_media):
    course = CourseFactory()
    unit = _image_unit(course, size=(1, 1), color="black", alt="Tiny", name="tiny.png")
    user = _student("tinystudent")
    EnrollmentFactory(course=course, student=user)
    return unit, user


def test_filltable_image_cell_opens_the_overlay(
    page, live_server, filltable_lesson
):
    unit, user = filltable_lesson
    _goto(page, live_server, unit, user)
    _open(page, page.locator(".filltable__img"))


def test_tiny_image_opens_and_is_not_upscaled(page, live_server, tiny_lesson):
    unit, user = tiny_lesson
    _goto(page, live_server, unit, user)
    trigger = _trigger(page)
    _await_decoded(page, trigger)
    # Precondition: a mis-mapped media route must not hand this the 1400px fixture.
    assert _natural_width(trigger) == 1
    _open(page, trigger)
    box = _box(page.locator(".imgzoom__img"))
    assert box["width"] <= 1.5, f"1x1 image was upscaled to {box['width']}"


def _make_pa_user(username):
    """A Platform Admin, which is what actually opens the editor.

    NOT an is_staff user. `can_manage_course` is "the course owner, OR anyone holding the
    courses.change_course model perm (the Platform Admin group)" and its own docstring
    says it "Deliberately does NOT key on is_staff" (courses/access.py:36-42). is_staff
    widens accessible_courses -- STUDENT access -- which is a different gate entirely.
    And make_verified_user takes only (username, email, password): there is no is_staff
    parameter to pass it. Mirrors tests/test_e2e_editor.py:24-36.
    """
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def test_editor_preview_rearms_after_a_real_save(
    page, live_server, db, _isolated_media
):
    """A source grep proves the string exists in editor.js; it cannot prove the name
    matches what imagezoom.js exports or that arming survives a real fragment swap
    (applyFragments replaces the whole [data-scope="preview"] node).

    There is no per-element edit PAGE in this app -- `courses:element_edit` does not
    exist and `reverse` would raise NoReverseMatch. Element editing happens inside the
    unit editor (`courses:manage_editor`, manage/courses/<slug>/build/unit/<pk>/edit/)
    via fetched fragments that mount in [data-edit-slot]; the save gesture is that
    fragment's own submit button, exactly as tests/test_e2e_editor.py:99-107 drives it.
    """
    from django.urls import reverse

    from courses.models import ImageElement

    owner = _make_pa_user("zoompa")
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    asset = make_image_asset(course, filename="ed.png", size=BIG, color=MAGENTA)
    add_element(unit, ImageElement.objects.create(media=asset, alt="Editor image"))

    page.set_viewport_size(VIEWPORT)
    _login(page, live_server, owner)
    page.goto(
        f"{live_server.url}"
        f"{reverse('courses:manage_editor', kwargs={'slug': course.slug, 'pk': unit.pk})}"
    )

    # Open the existing element's edit fragment, change its alt, submit. The contract is
    # "a real save swaps [data-scope=preview] and the swapped-in image is armed".
    # [data-edit-slot] renders EMPTY on load: _element_row.html:42 only injects
    # open_form when open_form_pk == el.pk. So the fragment must be opened first, via
    # the row's edit button (_element_row.html:33 -- `button.iconbtn.el-select.el-act-edit`
    # carrying data-element-id and data-form-url). Note that tests/test_e2e_editor.py
    # never does this: every case there ADDS a new element via [data-add-toggle], so it
    # is not a usable reference for editing an existing one.
    page.locator(".el-act-edit").first.click()
    page.wait_for_selector("[data-edit-slot] form[data-op='element-save']")
    page.locator("[data-edit-slot] input[name='alt']").fill("Editor image v2")
    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_selector('[data-scope="preview"] [data-zoomable]')

    # Assert ARMING, not just that a click opens something. The click path is delegated on
    # document and matches e.target.closest("[data-zoomable]") by design, so an UNARMED
    # swapped-in image opens the overlay just the same -- meaning _open() alone stays green
    # with the editor.js re-arm line deleted, and would prove only that delegation
    # survives a fragment swap. These four attributes are what the re-arm line actually
    # produces, so removing it breaks this and nothing else does.
    swapped = page.locator('[data-scope="preview"] [data-zoomable]').first
    page.wait_for_function(
        "el => el.dataset.imgzoomReady === '1'", arg=swapped.element_handle()
    )
    assert swapped.get_attribute("role") == "button"
    assert swapped.get_attribute("tabindex") == "0"
    assert "imgzoom-trigger" in (swapped.get_attribute("class") or "")

    _open(page, swapped)  # smoke check on top of the arming assertions
```

**Note for the implementer:** the editor URL (`courses:manage_editor`), the save gesture (`[data-edit-slot] button[type='submit']`, asserting on `[data-scope="preview"]`) and the fill-table image-cell schema are all pinned above against the real code. The one thing still to copy from `tests/test_e2e_editor.py` is the selector that *opens* an existing element's edit fragment, which depends on the builder row markup. The assertions (overlay opens after a real save; image cell opens; 1×1 not upscaled) are the contract.

- [ ] **Step 2: Run the whole e2e module**

Run: `uv run pytest tests/test_e2e_imagezoom.py -m e2e -v`
Expected: 23 passed.

- [ ] **Step 3: Falsify**

- Remove the `libliInitImageZoom(preview)` line from `editor.js` → the editor case goes RED. Restore.
- Drop `data-zoomable` from `_filltable_cell.html` → the fill-table case goes RED. Restore.
- Give `.imgzoom__img` a `width: 100%` → the tiny-image case goes RED. Restore.

- [ ] **Step 4: Commit**

```bash
git branch --show-current
git add tests/test_e2e_imagezoom.py
git commit -m "test(imagezoom): e2e fill-table cell, tiny image and editor preview re-arm"
```

---

## Task 11: Visual review and full verification

**Files:**
- Create (throwaway, not committed): a screenshot script under the scratchpad
- Modify: `courses/static/courses/css/courses.css` or `core/static/core/css/tokens.css` **only if** the review calls for a scrim retune

**Interfaces:**
- Consumes: everything.
- Produces: the shipped visual result.

- [ ] **Step 1: Capture the overlay in both themes**

Do **not** write a standalone script. A bare script has no `_isolated_media` fixture, so
`MediaAsset.objects.create()` would write its PNGs through the `FileField` straight into
`BASE_DIR / "media" / "courses/media/"` — the developer's real media tree, the exact
file-lifetime hazard this plan cites — and Step 6's `--ignored` guard would then fail with
no remedy. It also has no answer for which database, how the app is served, or how the
student logs in.

Instead add a **temporary pytest module** in the scratchpad (or a temporary
`tests/test_zz_imgzoom_shots.py` deleted before the final commit), marked
`pytestmark = pytest.mark.e2e`, which reuses the real harness — `_isolated_media`, `_login`, `_goto` — so `MEDIA_ROOT` isolation, the `live_server`, the test
database and authentication all come for free. Set the theme with
`page.evaluate("document.documentElement.dataset.theme = 'dark'")`, and loop explicitly
over **2 viewports × 2 themes × 2 orientations = 8 shots**, writing them to the scratchpad
directory (never the repo). It opens the overlay and screenshots it:

- at 1280×800 and at 360×640,
- in light and dark theme (set `data-theme` on `<html>`),
- with a **landscape** 1400×900 image and a **portrait** 900×1400 image,
- using an image with **visible internal structure** — two contrasting `ImageDraw.rectangle` blocks, not a flat fill. A flat rectangle on a near-black field shows neither the fit nor the scrim boundary, which is exactly what is being judged. Build it with a module-local helper that creates a `MediaAsset` (so the route resolver has a row to map) and then overwrites *that asset's own* `file.path` with the structured PNG, under a filename unique to this module — never a bare write into `MEDIA_ROOT`, which maps to no row, and never an overwrite of another asset's file, which is the shared-file-lifetime trap. Because the module runs under `_isolated_media`, that path is inside `tmp_path` and nothing touches the real tree.

- [ ] **Step 2: Self-critique the screenshots**

Look at all eight. Check: is the image genuinely centred? Does anything of the page show through? Is the portrait case height-capped without clipping? Is the scrim's darkness right in the light theme (where the page behind is bright)? Does the 360px case look deliberate rather than cramped?

If the scrim value needs adjusting, change **only** the `--scrim-solid` value in `tokens.css`. The mechanism (single declaration, `:root` only, absent from the dark block) may not change — and the occlusion test reads the token rather than a literal, so a retune must not require a test edit. If it does, the test is wrong.

- [ ] **Step 3: Full non-e2e suite**

Run: `uv run pytest -q`
Expected: all pass. Watch specifically for `tests/test_gallery_*` (the `inert` change) and `tests/test_i18n_po_health.py`.

Note: pytest verdict lines do not survive a Bash pipe in this environment — check the exit code and grep for `FAILED` rather than trusting a piped summary.

- [ ] **Step 4: Existing gallery e2e**

Run: `uv run pytest tests/test_e2e_gallery.py -m e2e -v`
Expected: pass. This drives the carousel that now toggles `inert`.

- [ ] **Step 5: Lint and format**

Run: `uv run ruff check .` then `uv run ruff format --check .`
Expected: both clean. Fix anything reported.

- [ ] **Step 6: Confirm no stray media and the right branch**

```bash
git status --porcelain          # only intended files
git status --porcelain --ignored media/   # MUST be empty (--ignored: /media/ is gitignored)
git branch --show-current       # pipeline/click-to-enlarge-images
```

- [ ] **Step 7: Falsification audit**

Confirm every test in both new modules has been observed RED at least once, except the **four** explicitly labelled as having no available break, each of which carries its reason in its own docstring: the closed-spoiler smoke check (`content-visibility` cannot be re-enabled by an author `display`), `test_second_click_closes_and_restores_focus`'s focus half (Chromium's native restore satisfies it either way — the source assertion is its guard), `test_focus_stays_inside_the_open_overlay` and `test_the_page_behind_does_not_scroll` (both pin UA behaviour, and their positive controls stand in for a break). If any test has never been seen to fail, break it now or delete it — a test that cannot fail is worse than no test, because it reads as coverage.

- [ ] **Step 8: Commit any review-driven change**

```bash
git branch --show-current
git add core/static/core/css/tokens.css   # plus courses.css, if the review changed it too
git commit -m "style(imagezoom): scrim value from the light/dark visual review"
```

---

## Self-Review

**Spec coverage.** Walked each spec section against the tasks:

| Spec section | Task |
|---|---|
| Scope: three armed templates | 1 |
| Not-armed negatives | 1 (source guards) |
| `imagezoom.js` arm / open-close / delegate / Escape guard | 3 |
| Script order, `IMAGEZOOM_I18N`, three pages, `editor.js` re-arm | 3 |
| `gallery.js` `inert` + focus rescue | 4 |
| `--scrim-solid` token + mechanism + invariant test | 2 |
| Overlay CSS, `[open]` scoping, no `100vw`, sizing | 2 |
| i18n both catalogs, fuzzy trap | 5 |
| Media-serving problem, `MEDIA_ROOT`, factory `size`/`color` | 6 |
| e2e cases 1–3 | 7 |
| e2e cases 4–8, 12–14 | 8 |
| e2e cases 9–11, 15–17 | 9 |
| e2e cases 18–20 | 10 |
| Visual review, regression guard, ruff | 11 |
| Error-handling table (feature detect, missing i18n, `dialog.open` guard, double-arm, print) | 3 (all in the module's code and comments); print needs no code |

**Type/name consistency.** `armAll` / `armOne` / `open` / `build` / `label` / `trimmedAlt` are used consistently; `window.libliInitImageZoom = armAll` matches the `editor.js` call and the both-sides source test; `.imgzoom` / `.imgzoom__img` / `.imgzoom-trigger` match between Task 2's CSS, Task 3's JS, Task 4's `rescueFocus` query and every e2e selector; `data-imgzoom-ready` is written as `img.dataset.imgzoomReady`, which is the same attribute.

**Verified against the code, not guessed.** Every fixture API in Tasks 6–10 was checked against the worktree during plan review: the nesting call and `tab_id` slots (`tests/test_e2e_tabs.py:110`, `SpoilerElement.SLOT_ID`, `TabsElement.default_data()` minting its own ids), the fill-table image-cell schema and its int-`pk` requirement (`courses/models.py:1007-1017`), the editor gate (`can_manage_course` — owner or Platform Admin, **not** `is_staff`), the editor URL (`courses:manage_editor`), the scoped login form, and `make_verified_user`'s real signature.

**Two scope corrections the code forced, recorded rather than buried.** (1) A stepper step is a `CharField` of text + KaTeX, so it can never contain an image: the spec's case-17 stepper half is unreachable by this feature and no stepper assertion or falsification exists. (2) Gallery descriptions cannot contain `<a href>` — `sanitize_cell`'s allowlist is `{strong,b,em,i,u,br}` with `attributes={}` — so the spec's aside that they "permit `<a href>`" is wrong. The `.imgzoom-trigger` targeting it was used to justify is still correct, just for a simpler reason: with `imagezoom.js` absent, *nothing* inside a figure is focusable, so the rescue never fires at all.

**Nothing is left to look up.** The last open item — the selector that opens an existing element's edit fragment — is now pinned to `.el-act-edit` (`_element_row.html:33`), with the note that `tests/test_e2e_editor.py` is *not* a usable reference for it because every case there adds a new element rather than editing an existing one.
