# Switch grid editor UX redesign (stem-driven cyclers)

Rework the **authoring editor** for the existing `SwitchGridElement` so creators are not confused. The data model, student render, check endpoint, and transfer are all shipped and **unchanged** — this touches only the edit-form partial, the editor JS, the CSS, and the tests that cover them.

## Purpose

The shipped editor (`_edit_switchgrid.html` + `switchgrid_editor.js`) presents cyclers as a padded, add-only list only loosely tied to the `{{choice}}` markers in each line's stem. Observed problems (from a creator using it):

1. Every line auto-shows **one extra blank cycler** (padding) — the creator sees phantom "Option 1/2/3" blocks with no explanation.
2. An extra blank **line** is auto-appended at the bottom, with its own blank cycler — looks unintentionally created, and there is **no way to remove it**.
3. Each cycler shows **3 blank option inputs** even though the minimum is 2 — confusing for a 2-option cycler.
4. **No remove affordance** anywhere: the only way to "delete" a row is to leave it blank and rely on silent drop-on-save (undiscoverable).
5. **Add option / Add cycler buttons overlap** (CSS/layout bug).

Root cause: the editor was built by mechanically mirroring the switchgate editor's "padded rows + blank-dropping" pattern with **no design pass** over the authoring interaction.

Goal: an editor where the relationship *marker → cycler* is obvious, nothing appears that the creator didn't ask for, everything shown can be removed, and the layout reads as a clear nested hierarchy.

## Design overview

### Cyclers are stem-driven (the core change)

The stem is the single source of truth. The editor counts the `{{choice}}` markers in a line's stem and renders **exactly that many** cycler blocks — no more, no fewer. There is **no "Add cycler" button**, no padding, and a stem/cycler count mismatch is now **impossible to author** (so that whole error class disappears).

- Cycler blocks are labeled "Cycler 1", "Cycler 2", … matching the markers **left-to-right** (1st marker → block 1). The i-th block maps to the i-th marker.
- A stem with **zero** markers → a **static line** with no cycler blocks (valid; renders as static text in the student view).
- The JS re-derives blocks from the stem on `input` (debounced ~150 ms) so blocks appear/disappear as the creator types or deletes markers.

**Preserving work across marker edits (no accidental data loss):**
- On a marker-count change, blocks are grown/shrunk **from the end**, preserving the data of blocks `0 .. min(old,new)-1` by index.
- A removed block's entered options + answer are **stashed in an in-memory (session) map keyed by block index**; if the creator re-adds a marker (count goes back up), the stashed data repopulates that block. This makes transient deletes (retyping the line) non-destructive within the editing session. The stash is JS-only; it never persists.
- Middle-insertion of a marker is an accepted edge case: blocks are index-aligned, so inserting a marker in the middle shifts subsequent blocks by one (their data moves with the index). This is rare in practice (lines are authored left-to-right) and always visible to the creator, who can correct it.

### Options within a cycler

- A cycler block starts with **2** option inputs (the enforced minimum, not 3).
- Each option row: a **correct-answer radio** (one radio group per cycler) + the option text input + a **remove (×)** button.
- An **"Add option"** button appends a row.
- Removing is blocked below **2** options (the × is disabled/hidden when only 2 remain), so a cycler can never be authored invalid.
- No auto-padded blank option row.

### Lines

- An **"Add line"** button appends a new line (seeded like the first — see create default).
- Each line is a **card** with a **remove (×)** control.
- **No auto-appended blank line.** Minimum one line (the × is disabled/hidden when only one line remains).

### Create default (new empty element)

A brand-new Switch grid opens with **one line, its stem pre-seeded with a short worked example containing one `{{choice}}` marker**, and therefore **one cycler block with two empty option inputs**. The creator immediately sees the pattern (marker → cycler → options) without reading docs, and edits the example in place. The seed stem is a short illustrative string (e.g. `2 {{choice}} 2 = 4`); the option inputs are empty. "Add line" seeds new lines the same way (one marker + one 2-option cycler) so the pattern stays visible.

### Visual / layout (executed with the frontend-design skill)

- A line renders as a **card**: the stem textarea on top, then its cycler blocks **indented** beneath it, each option row indented within its block — so the line → cycler → option hierarchy is visually unambiguous.
- Add/Remove controls are **grouped and labeled per level** and laid out so nothing overlaps (fixes the button-collision bug). Remove (×) controls are small, right-aligned, and clearly secondary.
- Consistent with the app's token-driven design system in **both light and dark themes** (reuse existing `--` tokens; no invented colors). Follow the frontend-design skill for typography, spacing, and hierarchy so it does not read as a templated default.
- Verified by screenshots (light + dark) with a self-critique pass before shipping, per the project's "every view ships styled" / screenshot-verification practice.

## Architecture / components

Files touched (all under `courses/`, `templates/`, `core/`):

- **`templates/courses/manage/editor/_edit_switchgrid.html`** — rewritten. Emits: the label + instruction fields (unchanged), a `[data-switchgrid-editor]` root, a `[data-lines]` container of line cards, and the `<template>` node(s) the JS clones (a line template + an option-row template). Server-rendered initial state comes from `SwitchGridElementForm.line_rows()` but **without padding** — the partial now renders only the rows that exist. Field names stay exactly `line-{i}-stem` / `line-{i}-c{j}-opt` / `line-{i}-c{j}-ans` (the form parse and the append-only + gap/blank compaction backend are unchanged).
- **`courses/static/courses/js/switchgrid_editor.js`** — reworked from "add-line/add-cycler/add-option button cloning" to: (a) **stem-driven cycler derivation** (count markers on debounced input, add/remove cycler blocks from the end, with the in-session stash), (b) **remove (×)** handlers for options and lines, (c) **Add option** and **Add line** handlers, (d) min-guards (≥2 options, ≥1 line). Still a single document-level delegated listener plus a delegated stem-`input` listener (robust to AJAX-injected partials). The `{{choice}}`-counting helper counts the literal `{{choice}}` in the author-facing stem (mirroring the marker convention in `courses/switchgrid.py`; the stored sentinel token is a server concern).
- **`core/static/core/css/app.css`** — the `.el-editor--switchgrid` block reworked for the nested-card layout, indentation, and non-overlapping grouped buttons; light + dark.
- **Form (`courses/element_forms.py` `SwitchGridElementForm`)** — `clean()` and the `line-{i}-c{j}-*` parsing are **unchanged** (they already compact blanks/gaps and remap the answer, which the new JS relies on). `line_rows()` is adjusted so padding minimums no longer inflate the editor: on an unbound (create) form it returns the single seeded line; on a bound/edit form it returns exactly the posted/stored lines and cyclers (no `+1` blank line, no `+1` blank cycler, options default 2 not 3). The `_SG_MIN_*` constants are repurposed/retired accordingly. This is the only Python change; it is behavior-preserving for the *parse* (still tolerant), changing only what the editor initially shows.

No changes to: the model, migration, `render_switch_grid` (student view), `switchgrid_check`, transfer, or `switchgrid.js` (the student enhancer).

## Data flow

1. **Create:** `manage_element_add?type=switchgrid` → `SwitchGridElementForm()` unbound → `line_rows()` returns one seeded line (stem = short example with one marker; one cycler; two empty options). The partial renders it; `switchgrid_editor.js` initializes, sees one marker → one cycler block already present.
2. **Author edits stem:** on debounced `input`, the JS counts `{{choice}}` in that line's stem and reconciles the visible cycler blocks (grow/shrink from end; restore from stash on grow). Answer radios and option inputs carry the correct `line-{i}-c{j}-*` names (indices assigned append-only; the form compacts any gaps on save).
3. **Author adds/removes options or lines** via the ×/Add controls; min-guards keep it valid.
4. **Save (POST):** the form parses the indexed fields exactly as today — drops blank options, drops wholly-blank lines, compacts gaps, remaps answers, validates marker==cycler count (which the stem-driven UI now guarantees) — and persists `lines`.
5. **Validation-error re-render (422):** `line_rows()` mirrors the POSTed data (already implemented) so the creator's grid survives; the partial re-renders it, JS re-derives cyclers from the posted stems.

## Error handling

- **≥2 options / ≥1 line** enforced in the JS (disable/hide × at the minimum) *and* still enforced server-side in `clean()` (unchanged) as the backstop — the UI makes the invalid states unreachable, the server stays authoritative.
- **Marker/cycler mismatch** is now unreachable via the UI (cyclers are derived from markers), but the server `clean()` check stays as the backstop for direct POSTs / imports.
- **Debounce / rapid typing:** block reconciliation is idempotent and keyed by index; a partial marker (e.g. half-typed `{{choi`) counts as zero until the full literal `{{choice}}` is present — no crash, blocks settle once typing stops.
- **AJAX-injected partial:** the JS uses document-level delegation (click + input), so a partial injected after page load works with no re-init (as today).
- **No-JS fallback:** with JS off, the server-rendered `line_rows()` state is still a submittable plain form (stem textareas + option inputs + radios); the stem-driven reconciliation is a progressive enhancement.

## Testing

- **Form (`courses/tests/test_switchgrid_form.py`)** — keep all existing parse/compaction/remap/edit-repopulate tests green (the parse is unchanged). Update the `line_rows()` tests to assert the **no-padding** initial shape: unbound create returns exactly one seeded line with one cycler and two option inputs (not the old padded minimums); bound re-render returns exactly the posted lines/cyclers.
- **Authoring (`courses/tests/test_switchgrid_authoring.py`)** — GET `manage_element_add?type=switchgrid` returns 200 and contains the seeded example + `data-switchgrid-editor`; a valid POST still creates a `SwitchGridElement` (field-name contract unchanged).
- **e2e (`tests/test_e2e_switchgrid.py`, focused + foreground)** — extend with editor-driving cases: (a) typing a second `{{choice}}` into a line's stem makes a second cycler block appear; deleting it removes the block and re-adding restores stashed options; (b) the × removes an option / a line; (c) min-guards prevent removing below 2 options / 1 line; (d) authoring a full grid via the redesigned editor and saving produces the correct stored `lines`. Drive real gestures (no `page.evaluate` shortcuts). Keep the existing student-side cycle/confirm e2e green.
- **Visual QA** — frontend-design screenshots in light + dark of: the create-default state, a multi-cycler line, a static line, and a validation-error re-render; self-critique before shipping.

## Scope / execution constraints

- Done in a **dedicated worktree** (`switch-grid-editor-ux`, branch off `master`) because another pipeline is running on libli concurrently.
- Tests run with an **isolated test database** (unique `DATABASE_URL` for this worktree) to avoid the known Postgres `test_libli` contention across concurrent worktrees.
- Ships as its **own PR** (the element itself is already merged).
