# Per-paragraph text alignment in rich-text bodies

## Purpose

Authors editing the block-level rich-text bodies (the **text**, **callout**, and
**spoiler** elements) currently have no way to control horizontal alignment. The
motivating case is centering a display equation between left-aligned prose, e.g.:

```
Skoro \(5!=120\) to
\(6!=5!\cdot 6=120\cdot 6=720\)
```

where the author wants the equation line centered while the surrounding prose
stays left-aligned. The feature adds **per-block** Left / Center / Right alignment
controls to the toolbars of those three elements, applying to any block of
content (prose, math, headings, list items).

**Scope (which surfaces get alignment).** Exactly the three elements whose bodies
are block-level rich text sanitized by `sanitize_html` **and** rendered inside an
`.el--text` container: text, callout, spoiler. Explicitly **out of scope**:

- **Quiz / interactive stems** (choice, fill-blank, short-text/numeric, match-pair,
  drag-*, extended-response, fillgate, switchgate). These include the *shared*
  `_rte_toolbar.html` and render in `.question__stem` / gate-stem containers, not
  `.el--text`. Adding buttons there would store the class (their stems also pass
  through `sanitize_html`) yet the alignment CSS would never apply — a button that
  works in the editor but no-ops on render. We therefore do **not** touch the
  shared partial.
- **Table / fill-in-table cells and gallery descriptions** (`_edit_table`,
  `_edit_filltable`, `_edit_gallery`). These use `sanitize_cell` /
  description sanitizers, which are **inline-only** (no block tags), so block-level
  alignment is inapplicable.

Other non-goals: whole-body alignment toggles, `justify`, and per-character
alignment.

## Architecture / components

Alignment is stored as a single **allowlisted CSS class** on the block element —
`ta-left`, `ta-center`, or `ta-right` — never as an inline `style` attribute.
This preserves the sanitizer's deliberate "no `style` attribute" invariant
(`courses/sanitize.py`, `ALLOWED_ATTRIBUTES` permits only `href`/`title`/`rel` on
`<a>`). The contenteditable editing surface natively speaks inline `text-align`
styles (what `document.execCommand` emits); stored and submitted HTML speaks the
`ta-*` classes. Two small pure JS conversions bridge the two representations.

Touched components:

1. **Sanitizer** — `courses/sanitize.py`, `sanitize_html` only.
   Use nh3's **`allowed_classes`** parameter (token-level, per-tag class-name
   allowlist) to permit only `{ta-left, ta-center, ta-right}` on the block tags
   `p, div, h2, h3, h4, blockquote, li`. `class` is **NOT** added to
   `ALLOWED_ATTRIBUTES` — doing so would bypass the value restriction and allow
   arbitrary classes. `allowed_classes` was verified empirically against nh3 0.3.5:
   it keeps `ta-center` (including when co-occurring, e.g. `class="ta-center foo"`
   → `class="ta-center"`), drops unknown class names (`class="evil"` → `class=""`),
   and drops the class entirely on non-allowlisted tags. `sanitize_cell` and
   `sanitize_label` are **not** changed — cells and labels remain class-free. Note
   that quiz stems also flow through `sanitize_html`, so the class becomes storable
   there too; this is harmless (no buttons produce it, no CSS renders it) and is
   the reason the allowlist lives at the shared `sanitize_html` layer rather than
   per-element.

2. **RTE JS** — `courses/static/courses/js/text_toolbar.js`.
   - New `applyCmd` cases `alignleft` / `aligncenter` / `alignright`. Each:
     - calls `document.execCommand("styleWithCSS", false, true)` (forces inline
       `text-align` cross-browser instead of Firefox's legacy `align` attribute),
     - calls the matching `justifyLeft` / `justifyCenter` / `justifyRight`,
     - then **immediately resets** `document.execCommand("styleWithCSS", false,
       false)`. Resetting is mandatory: `styleWithCSS` is a persistent
       document-global flag, and leaving it `true` makes the existing
       `bold`/`italic`/`underline` handlers emit `<span style="font-weight:bold">`
       instead of `<b>`/`<i>`/`<u>`; the sanitizer allows neither `span` nor
       `style`, so formatting applied after an alignment click would be silently
       stripped on save. (Belt-and-braces: also set `styleWithCSS` false at the
       start of the bold/italic/underline cases.)
   - `styleToClass(html)` — pure function, applied when syncing surface → hidden
     textarea. For each element carrying `style.text-align` in
     `{left, center, right}`, remove the inline `text-align` and set the class list
     to exactly the single matching `ta-*` class (replacing any pre-existing
     `ta-*` and, per the single-class invariant below, not accumulating others).
     Operates on a detached container; returns `innerHTML`.
   - `classToStyle(html)` — the inverse, applied when loading stored content into
     the surface (`wireRte` init). For each element carrying a `ta-*` class, set
     the matching inline `text-align` and strip the `ta-*` class, so stored
     alignment shows in the editor and `queryCommandState` keeps working.
   - **Single-class invariant:** `styleToClass` emits at most one `ta-*` class and
     no other classes on the blocks it touches (the RTE never authors other block
     classes). This keeps storage simple; `allowed_classes` is nonetheless
     token-level, so a stray co-occurring class from a paste degrades gracefully
     (alignment survives) rather than dropping the whole attribute.
   - Extend `refreshActive` for alignment active-state, respecting mutual
     exclusivity: highlight **Center** when `queryCommandState("justifyCenter")`
     and **Right** when `queryCommandState("justifyRight")`. Do **NOT** highlight
     Left from `queryCommandState("justifyLeft")` — it returns `true` for ordinary
     default/unaligned content and would keep Left perpetually lit. Left is the
     "clear alignment" action; it shows active only when neither Center nor Right
     is active.

3. **Toolbars** — add three buttons (`data-cmd="alignleft|aligncenter|alignright"`)
   to the three in-scope elements' **own inline** toolbars:
   - `templates/courses/manage/editor/_edit_text.html`,
   - `templates/courses/manage/editor/_edit_callout.html`,
   - `templates/courses/manage/editor/_edit_spoiler.html`.
   The shared `_rte_toolbar.html` is deliberately **not** edited (see Scope).
   Unifying these inline toolbars into one partial is out of scope (future
   cleanup).

4. **Icons** — add three `<symbol>` definitions `ed-align-left`,
   `ed-align-center`, `ed-align-right` to the inline SVG sprite in
   `templates/courses/manage/editor/editor.html`, as `currentColor` line SVGs
   matching the visual style of the existing `ed-*` icons.

5. **CSS** — `courses/static/courses/css/courses.css`, near the existing callout /
   rich-text rules. Define alignment utilities scoped to rendered rich text:
   `.el--text .ta-center { text-align: center; }` and the left/right variants.
   `.el--text` already applies to all three in-scope render containers
   (`textelement.html`, `.callout__body`, `.spoiler__body`), so one scoped rule set
   covers them. No editor-surface CSS is needed — the surface renders alignment via
   the inline styles produced by `classToStyle` on load and `execCommand` during
   editing.

6. **i18n** — new source strings `"Align left"`, `"Align center"`,
   `"Align right"` (button `title`/`aria-label`), with Polish translations
   `"Wyrównaj do lewej"`, `"Wyśrodkuj"`, `"Wyrównaj do prawej"`. Run
   `makemessages` + `compilemessages`. **Fuzzy-flag gotcha:** `makemessages` may
   mark near-match strings fuzzy, which drops them from the compiled catalog and
   fails the Testing §5 check — explicitly clear any fuzzy flag on the three new PL
   strings before `compilemessages`.

## Data flow

**Authoring (JS on):**
`wireRte` loads stored HTML → `classToStyle` → surface shows inline `text-align`.
Author clicks an align button → `styleWithCSS(true)` + `justify*` sets inline
`text-align` on the current block → `styleWithCSS(false)` reset. On
`input`/toolbar/submit, `sync` runs `styleToClass(surface.innerHTML)` → hidden
textarea holds `ta-*` classes → form POSTs class-based HTML.

**Block granularity (motivating case):** alignment is per-block. In this RTE,
pressing **Enter** produces a new block element (contenteditable wraps
ENTER-separated lines in a `<div>`; the existing `sanitize_cell` comment in
`courses/sanitize.py` documents this behavior), so two lines entered with Enter are
two independently-alignable blocks — exactly what the motivating example needs
(prose left, equation block centered). A **Shift+Enter** soft break inserts a
`<br>` *within* one block; aligning that block centers **both** lines together.
Authors who want independent alignment must separate lines into distinct blocks
(Enter, not Shift+Enter). The e2e test uses two distinct blocks to mirror the
motivating layout.

**Server:** `sanitize_html` keeps only allowlisted `ta-*` classes on allowlisted
block tags; everything else stripped. Stored body is class-based HTML.

**Rendering (taking view):** the body renders inside an `.el--text` container
(text element, `.callout__body`, `.spoiler__body`); the `.ta-*` utility CSS applies
the horizontal alignment. Math auto-render is unaffected — inline `\(...\)` and
display `\[...\]` still render as today.

**JS off (progressive enhancement):** the plain textarea submits raw HTML; the
author can type/paste `class="ta-center"` manually and the server sanitizer keeps
it. No alignment buttons, but the storage/render path is identical.

## Error handling

- **Unknown / disallowed class values** are silently dropped by the sanitizer
  (existing nh3 behavior) — no error surfaced, matching how the sanitizer already
  treats disallowed tags/attributes.
- **`execCommand` failures** are already swallowed by the existing `exec()`
  wrapper's `try/catch`; the new align cases reuse it. The `styleWithCSS` reset is
  likewise wrapped so a failure cannot leave the flag stuck true.
- **Alignment on non-allowlisted block tags does not persist.** The class lands on
  the block, but if that block is a `<ul>`/`<ol>` or a `<pre>` (the Code button's
  `formatBlock` target), the class is stripped on save because those tags are not
  in the allowlist. Aligning a **list item** (`<li>`, allowlisted) *does* persist.
  These are accepted, documented limitations, not error paths.
- **Content with no block wrapper** (e.g. a first line before any Enter in some
  browsers): `execCommand("justify*")` wraps/creates a block as the browser sees
  fit; if no element results, no class is stored — alignment simply no-ops for that
  fragment.
- **Alignment applied at the surface root:** if the caret sits directly in the
  `.rte-surface` root with no inner block, `justify*` may set `text-align` on the
  root element itself. Because `sync` serializes `surface.innerHTML` (which excludes
  the root element's own attributes), that root-level alignment is dropped on save.
  Expected, not a bug — noted so testing does not mistake it for one.
- **Round-trip idempotence**: `styleToClass`/`classToStyle` only touch the three
  known alignment values and leave all other markup untouched, so repeated
  save/load cycles are stable.

## Testing

1. **Sanitizer (Python):** `sanitize_html` keeps `class="ta-center"` (and
   `ta-left`/`ta-right`) on each allowlisted block tag; reduces
   `class="ta-center foo"` to `class="ta-center"` (token-level); drops a
   non-allowlisted class value (`class="evil"` → empty); drops `ta-*` on a
   non-block tag (e.g. `<b>`); leaves `sanitize_cell`/`sanitize_label` output
   class-free. This test pins the `allowed_classes` mechanism (class NOT in
   `ALLOWED_ATTRIBUTES`).
2. **Formatting survives alignment (JS-behavior, exercised via e2e or a
   serialization test):** after an alignment action, applying bold emits
   `<b>`/`<strong>` (not a `<span style>`), so bold survives `sanitize_html` on
   reload. This guards the `styleWithCSS` reset (C2 regression).
3. **Render (Python/template):** a callout, a text element, and a spoiler whose
   body contains a `ta-center` block render that class through to the DOM on the
   `.el--text` container's child block.
4. **CSS presence (Python, matching the existing `tests/test_callout_css.py`
   pattern):** the `.el--text .ta-center` / `.ta-left` / `.ta-right` rules exist in
   `courses.css`.
5. **e2e (Playwright, drives the real UI per project convention):** in the **text
   element** editor (the flagship/motivating case), create two distinct blocks
   (Enter between them), place the caret in the second, click the Center button via
   a real toolbar click (not `page.evaluate`), save, and assert both (a) the stored
   body carries `class="ta-center"` on the second block only and (b) the rendered
   taking view shows the second block centered and the first left-aligned.
6. **i18n catalog:** the three new strings appear in the EN/PL catalogs with the
   Polish translations filled (no fuzzy/empty), and `compilemessages` succeeds.
