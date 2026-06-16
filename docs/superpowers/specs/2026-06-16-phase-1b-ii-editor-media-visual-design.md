# Phase 1b-ii — Editor & Media Visual Design (restyle)

**Status:** design accepted via visual-companion mockups (2026-06-16).
**Type:** visual-polish pass over the already-shipped Phase 1b-ii feature, plus two small additive features (media display-name field, library search/type filter).

## Goal

The Phase 1b-ii content editor, media manager, and picker shipped functional but
**unstyled** — they reuse `base.html` chrome but their interiors were token-driven
utility CSS, never designed against a mockup (no mockup existed for these screens).
This pass gives all three screens a proper design in libli's **warm-teal identity**
(see [design-language.md](../../design-language.md)) and folds in two requested
conveniences: human-readable media names and library search.

## Scope decision

- **Interaction model is unchanged** (confirmed): element list + click-to-edit form +
  live preview; media grid; kind-locked picker modal. No views/JS rearchitecture.
- **Additive features in scope** (each goes slightly beyond CSS):
  1. `MediaAsset` **display name** — a human label shown above the filename, editable.
     Requires a model field + migration + form/view changes.
  2. Media **search** (by display name + filename) on the manager and the picker.
  3. Media **type filter** (All / Images / Videos) on the **manager** page only.

## Accepted mockups

- `docs/mockups/content-editor_accepted-A.html` — editor ｜ preview (layout A).
- `docs/mockups/media-manager-and-picker_accepted.html` — manager page + picker modal.

Both are self-contained, in the final warm-teal identity, with a working light/dark
toggle. They are the visual source of truth for implementation.

## Design language (reused, not invented)

All color/spacing/radius/shadow/type come from the existing tokens in
`core/static/core/css/tokens.css` (mirrored in design-language.md): cream surfaces,
warm-teal `--primary`, amber `--accent` (brand dot + links), Inter, soft radii
(cards ~12px, controls ~7px), warm-tinted shadows. **Dark text** (`--text-primary`),
never low-opacity body text. Full light + dark support. No hardcoded colors.

---

## Screen 1 — Editor ｜ preview (layout A, balanced 50/50)

**Layout.** A two-column grid (`.editor-grid`, `1fr 1fr`, `--space-5` gap) that stacks
to one column at ≤860px. Each column is a **card** (`--surface-raised`, `--border-default`,
`--radius-lg`, `--shadow-xs`) with a small uppercase pane header (`--text-tertiary`):
"Editor" (left) and "Live preview" (right, with an "as students see it" hint). The
preview pane is **sticky** on desktop.

**Element rows.** Each element renders as a soft card (`--surface-sunken`, `--radius-md`):
a drag grip glyph, a teal **type chip** (`--primary` on `--primary-subtle`, pill), the
**summary** text (truncated), and a right-aligned **action cluster** (edit ✎ / move ↑ /
move ↓ / delete) that is dimmed at rest and fully shown on row hover/focus. Hover lifts
the border to `--border-strong` + `--shadow-xs`.

> **Reorder mechanism is unchanged:** the working controls are the ↑/↓ buttons (existing
> endpoints). The drag grip in the mockup is a visual affordance only — **drag-to-reorder
> is NOT in scope** for this pass. Implementation choice (see Open questions): either omit
> the grip, or render it clearly non-interactive, so we don't ship a dead control.

**Inline edit form.** Selecting a row (or adding) expands the host form **in place**:
the row becomes `--primary`-bordered, `--surface-raised`, `--shadow-sm`, and contains the
per-type fields. For **text**: the RTE toolbar (`.rte-toolbar` token buttons) over the
contenteditable surface. For **math**: the LaTeX textarea over a live-preview box
(KaTeX-rendered). Fields use `--surface-sunken` inputs with a `--primary` focus ring.
`.field-error` in `--danger`. Actions row (right-aligned): **Save** (primary) + **Cancel**
(ghost).

**Add element.** A full-width dashed **"＋ Add element"** button (`--primary` text,
`--border-strong` dashed → `--primary` + `--primary-subtle` on hover) that reveals a row
of **5 type cards** (Text / Image / Video / Iframe / Math), each an icon + label tile.

**Preview pane.** Renders elements as students see them (reusing the 1a `render_element`):
real heading/paragraph typography, centered math blocks (KaTeX), figures with captions,
responsive image placeholders. Empty state: muted italic "Nothing to preview yet."

---

## Screen 2 — Media manager page

**Upload card.** A raised card containing the upload toolbar — **Kind** select, **File**
input, and a new **Name (optional)** field (placeholder "defaults to filename") — plus a
dashed **drag-&-drop zone** (`--border-strong` dashed → `--primary` + `--primary-subtle`
on drag-over).

**Grid header.** A row with, on the left, an **All types / Images / Videos** filter select
+ the file count; on the right, a **search** box (magnifier affordance, placeholder
"Search by name or filename…").

**Asset cards.** Responsive grid (`repeat(auto-fill, minmax(170px, 1fr))`). Each card:
- **Thumbnail** (4:3) — image preview, or a ▶ glyph tile for video.
- **Display name** (bold `--text-primary`) with a hover **✎ rename** that swaps it for an
  inline input; **filename** below in muted `--text-tertiary`.
- **Footer:** usage state — amber **"in use ×N"** badge with the delete button **disabled**
  (guarded), or "unused" with an active delete (hover → `--danger`).

---

## Screen 3 — Picker modal (editor-only)

Opened from the editor's "Choose media" button for an image/video element. **Kind-locked**
to the element (title "Choose media — Image/Video"; **no type switcher** — the element
accepts exactly one kind, and the server enforces it). Centered card overlay
(`--surface-overlay` backdrop, `--shadow-lg`), full-screen on mobile.

- **Tabs:** Library / Upload.
- **Library:** a **search** box, then a grid of pickable asset cards (display name +
  filename). Course-scoped + kind-scoped.
- **Upload:** file input (optional name) that uploads and **auto-selects** the new asset —
  no trip to the manager.

---

## Functional additions — backend impact

**`MediaAsset` display name.**
- New field, e.g. `title = models.CharField(max_length=255, blank=True)`. Migration
  (additive, nullable/blank — no data backfill required; blank renders as the filename).
- On upload, if the optional Name field is blank, default `title` to the filename **stem**
  (basename without extension). The upload form gains an optional `title` field.
- **Inline rename** on the manager: a small endpoint (e.g. `media_rename`) or extend the
  existing media views; updates `title` only; course-scoped + permission-gated like the
  other media routes; returns the refreshed cell fragment (no-JS: redirect to manager).
- `element_summary` for image/video prefers `title` when present, else filename/alt
  (existing behavior) — a one-line tweak.

**Search (`?q=`).** `media_manager` and `media_picker` querysets filter on
`Q(title__icontains=q) | Q(original_filename__icontains=q)` when `q` is present.

**Type filter (`?type=`).** `media_manager` only: `all` (default) / `image` / `video`,
applied to the queryset. (The picker already filters by kind.)

Both filters degrade with JS off (plain GET form submits). With JS on, they refine the
grid via the existing fetch/fragment swap.

## Implementation surface (for the plan)

- `courses/static/courses/css/editor.css` — the bulk: restyle to the mockups (panes,
  element cards, chips, action clusters, add-button + type cards, asset cards, name/rename,
  search + filter header, picker modal). Tokens only.
- Templates — `editor/_editor_scope.html`, `_element_row.html`, `_host_form.html`,
  `_preview.html`, the `_edit_*` partials; `media/manager.html`, `_asset_cell.html`,
  `_picker.html` (markup classes to match the mockups; add name/rename, search box,
  type filter).
- `courses/models.py` (+ migration) — `MediaAsset.title`.
- `courses/media.py` / `views_media.py` — search + type filter; rename endpoint; default
  title-from-filename on create.
- `courses/element_forms.py` — `MediaAssetForm` gains optional `title`.
- `courses/urls.py` — rename route.
- `courses/templatetags/courses_manage_extras.py` — `element_summary` prefers `title`.
- JS — `media_picker.js` (search wiring, optional name on upload); `editor.js`/manager
  wiring for inline rename + type filter. Progressive-enhancement only.
- i18n — new strings ("Name", "Search…", "All types", "Images", "Videos", "Rename").
- Tests — search/type-filter filtering, title default-from-filename, rename endpoint
  (incl. course scoping), `element_summary` title preference; update any asset-cell
  assertions; e2e: rename + search happy paths.

## Out of scope / deferred

- **Drag-to-reorder** elements (keep ↑/↓). Future enhancement; would make the grip live.
- Inline-edit-directly-in-preview, multi-select bulk media actions, asset folders/tags.

## Open questions

1. **Drag grip:** omit it for now, or keep it as a non-interactive visual handle until
   drag-reorder lands? (Recommendation: omit, to avoid a dead control.)
2. **Display-name field name:** `title` vs `display_name`? (Recommendation: `title` —
   shorter, matches `IframeElement.title`.)
3. **Rename UX:** inline-on-card (mockup) vs a tiny modal? (Recommendation: inline.)
