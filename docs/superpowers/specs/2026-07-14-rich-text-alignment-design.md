# Per-paragraph text alignment in rich-text bodies

## Purpose

Authors editing rich-text bodies (the text element, the callout element, and any
other body driven by the shared RTE) currently have no way to control horizontal
alignment. The motivating case is centering a display equation between
left-aligned prose, e.g.:

```
Skoro \(5!=120\) to
\(6!=5!\cdot 6=120\cdot 6=720\)
```

where the author wants the equation line centered while the surrounding prose
stays left-aligned. The feature adds **per-paragraph** Left / Center / Right
alignment controls to the shared rich-text toolbar, applying to any block of
content (prose, math, headings, list items).

Non-goals: whole-body alignment toggles, justify, per-character alignment, or
alignment of non-rich-text surfaces (table cells, plain labels).

## Architecture / components

Alignment is stored as a single **allowlisted CSS class** on the block element —
`ta-left`, `ta-center`, or `ta-right` — never as an inline `style` attribute.
This preserves the sanitizer's deliberate "no `style` attribute" invariant
(`courses/sanitize.py`, `ALLOWED_ATTRIBUTES` currently permits only
`href`/`title`/`rel` on `<a>`). The contenteditable editing surface natively
speaks inline `text-align` styles (what `document.execCommand` emits); stored and
submitted HTML speaks the `ta-*` classes. Two small pure JS conversions bridge
the two representations.

Touched components:

1. **Sanitizer** — `courses/sanitize.py`, `sanitize_html` only.
   Use nh3's `tag_attribute_values` to permit the `class` attribute on the block
   tags `p, div, h2, h3, h4, blockquote, li`, restricted to exactly the value set
   `{ta-left, ta-center, ta-right}`. Any other class value (or class on any other
   tag) is dropped. `sanitize_cell` and `sanitize_label` are **not** changed —
   cells and labels remain class-free.
   - Verification note: confirm with a test whether nh3 0.3.5's
     `tag_attribute_values` alone allowlists the values, or whether `class` must
     additionally appear in `attributes` (with the value-restriction still
     applied). The docstring implies `tag_attribute_values` is sufficient; the
     test is the source of truth.

2. **RTE JS** — `courses/static/courses/js/text_toolbar.js`.
   - New `applyCmd` cases `alignleft` / `aligncenter` / `alignright`. Each calls
     `document.execCommand("styleWithCSS", false, true)` (forces inline
     `text-align` cross-browser instead of Firefox's legacy `align` attribute)
     then the matching `justifyLeft` / `justifyCenter` / `justifyRight`.
   - `styleToClass(html)` — pure function, applied when syncing surface → hidden
     textarea. For each element carrying `style.text-align` in
     `{left, center, right}`, remove the inline `text-align` and add the matching
     `ta-*` class (replacing any pre-existing `ta-*`). Operates on a detached
     container; returns `innerHTML`.
   - `classToStyle(html)` — the inverse, applied when loading stored content into
     the surface (`wireRte` init). For each element carrying a `ta-*` class, set
     the matching inline `text-align` and strip the `ta-*` class, so stored
     alignment shows in the editor and `queryCommandState` keeps working.
   - Extend `refreshActive` so the active alignment button highlights (via
     `queryCommandState("justifyCenter")` etc.).
   - Rationale for keeping the surface on inline styles: `execCommand` block
     detection/wrapping and `queryCommandState` both rely on the browser's native
     `text-align`; converting only at the storage boundary avoids fighting
     contenteditable.

3. **Toolbars** — add three buttons (`data-cmd="alignleft|aligncenter|alignright"`)
   to **both**:
   - `templates/courses/manage/editor/_rte_toolbar.html` (shared partial), and
   - `templates/courses/manage/editor/_edit_callout.html` (the callout's own
     inline toolbar, a near-duplicate of the shared partial).
   Unifying those two toolbars into one partial is explicitly **out of scope** —
   noted as future cleanup.

4. **Icons** — add three `<symbol>` definitions `ed-align-left`,
   `ed-align-center`, `ed-align-right` to the inline SVG sprite in
   `templates/courses/manage/editor/editor.html`, as `currentColor` line SVGs
   matching the visual style of the existing `ed-*` icons.

5. **CSS** — `courses/static/courses/css/courses.css`, near the existing callout /
   rich-text rules. Define alignment utilities scoped to rendered rich text:
   `.el--text .ta-center { text-align: center; }` and the left/right variants.
   `.el--text` already applies to `.callout__body`, so callouts are covered. No
   editor-surface CSS is needed — the surface renders alignment via the inline
   styles produced by `classToStyle` on load and `execCommand` during editing.

6. **i18n** — new source strings `"Align left"`, `"Align center"`,
   `"Align right"` (button `title`/`aria-label`), with Polish translations
   `"Wyrównaj do lewej"`, `"Wyśrodkuj"`, `"Wyrównaj do prawej"`. Run
   `makemessages` + `compilemessages` per the project's i18n flow.

## Data flow

**Authoring (JS on):**
`wireRte` loads stored HTML → `classToStyle` → surface shows inline `text-align`.
Author clicks an align button → `styleWithCSS` + `justify*` sets inline
`text-align` on the current block. On `input`/toolbar/submit, `sync` runs
`styleToClass(surface.innerHTML)` → hidden textarea holds `ta-*` classes → form
POSTs class-based HTML.

**Server:** `sanitize_html` keeps only allowlisted `ta-*` classes on allowlisted
block tags; everything else stripped. Stored body is class-based HTML.

**Rendering (taking view):** the body renders inside an `.el--text` container
(text element and `.callout__body` alike); the `.ta-*` utility CSS applies the
horizontal alignment. Math auto-render is unaffected — inline `\(...\)` and
display `\[...\]` still render as today.

**JS off (progressive enhancement):** the plain textarea submits raw HTML; the
author can type/paste `class="ta-center"` manually and the server sanitizer
keeps it. No alignment buttons, but the storage/render path is identical.

## Error handling

- **Unknown / disallowed class values** are silently dropped by the sanitizer
  (existing nh3 behavior) — no error surfaced, matching how the sanitizer already
  treats disallowed tags/attributes.
- **`execCommand` failures** are already swallowed by the existing `exec()`
  wrapper's `try/catch`; the new align cases reuse it.
- **Alignment inside a list**: the class lands on `<li>` (allowlisted) and
  persists; aligning at the `<ul>`/`<ol>` level does not persist (those tags are
  not in the class allowlist). This is an accepted limitation, documented in the
  spec, not an error path.
- **Content with no block wrapper** (e.g. a first line before any Enter in some
  browsers): `execCommand("justify*")` wraps/creates a block as the browser sees
  fit; if no element results, no class is stored — alignment simply no-ops for
  that fragment, consistent with contenteditable behavior.
- **Round-trip idempotence**: `styleToClass`/`classToStyle` only touch the three
  known alignment values and leave all other markup untouched, so repeated
  save/load cycles are stable.

## Testing

1. **Sanitizer (Python):** `sanitize_html` keeps `class="ta-center"` (and
   `ta-left`/`ta-right`) on each allowlisted block tag; drops a non-allowlisted
   class value (e.g. `class="evil"`); drops `ta-*` on a non-block tag; leaves
   `sanitize_cell`/`sanitize_label` output class-free. This test also resolves the
   `tag_attribute_values` vs `attributes` verification question.
2. **Render (Python/template):** a callout (and a text element) whose body
   contains a `ta-center` paragraph renders that class through to the DOM, and the
   alignment CSS class is present on the block.
3. **CSS presence (Python, matching the existing `tests/test_callout_css.py`
   pattern):** the `.ta-center` / `.ta-left` / `.ta-right` rules exist in
   `courses.css`.
4. **e2e (Playwright, drives the real UI per project convention):** in the editor,
   place the caret in a paragraph, click the Center button, save, and assert both
   (a) the stored body carries `class="ta-center"` and (b) the rendered taking
   view shows the paragraph centered. The gesture must be a real toolbar click,
   not `page.evaluate`.
5. **i18n catalog:** the new strings appear in the EN/PL catalogs with the Polish
   translations filled (no fuzzy/empty), and `compilemessages` succeeds.
