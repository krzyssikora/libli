# Phase 1b — WS3: Editor & media polish (design, 2026-06-17)

Workstream 3 of the Phase-1b UX-review-triage backlog
(`docs/superpowers/specs/2026-06-16-phase-1b-ux-review-triage.md`). Pure 1b-ii surface
work on an essentially unchanged backend, **except** one small media-model field + the
new embed-snippet parser. Builds to the already-accepted mockups:

- `docs/mockups/content-editor_accepted-A.html` (editor｜preview)
- `docs/mockups/media-manager-and-picker_accepted.html` (manager + picker)

Fidelity bar: match layout + token usage; minor spacing latitude allowed.

## Triage items covered

| Item | Type | Summary |
|---|---|---|
| — | UX | Editor｜preview + media manager/picker restyle to accepted mockups |
| 12 | UX | Text toolbar → icon-only buttons with hover tooltips + active state |
| 13 | FEATURE | Iframe: accept a pasted `<iframe>` snippet, extract & whitelist-validate `src` |
| 14a | UX | Unit title shown in the preview (students must see it) |
| 14b | UX | "Back to builder" spaced from title; icon nav affordance |
| 9c-ish | UX | **Element drag-and-drop** reordering in the editor list (decided in brainstorming) |

i18n for all new strings folds into this workstream (PL), per the triage's sweep approach.

## Decisions locked in brainstorming (2026-06-17, visual-companion-assisted)

1. **Editor interaction model = full mockup fidelity (Option A).** Rows expand **inline**
   to their edit form (not a separate host area); "+ Add element" is a dashed full-width
   button revealing a **5-card type menu** (Text/Image/Video/Iframe/Math).
2. **Element drag-and-drop is in scope** (it does not exist today — `editor.js` has no drag
   handlers; rows only have ↑/↓ + delete). Port the builder tree's pointer DnD, simplified
   to a **single flat list** (no nesting, no kind-legality): grip handle, insertion line,
   server reorder; keep ↑/↓ as the no-pointer/fallback path.
3. **Toolbar = icon-only SVG buttons + `title=` tooltips + active/pressed state.** Heading
   levels stay as **three buttons H2 · H3 · H4** (no dropdown). Link keeps the current
   `prompt()` for v1 (no inline popover — scope control). Server still sanitizes on save;
   the toolbar is never the security boundary.
4. **Embed input = one smart field** (URL or pasted `<iframe>` snippet; dispatch on leading
   `<`). Algorithm per the triage spec (see §Embed below).
5. **Media manager = full mockup**: type filter + name/filename search + inline rename of a
   **display name** + optional name-on-upload, keeping the existing in-use badge & delete
   guard. Requires a new `MediaAsset.name` field (+ migration) and a rename endpoint.
6. **Picker modal is kind-locked to the element it was opened from** — its grid shows only
   that kind and its Upload tab uploads only that kind (no Image/Video selector inside the
   modal). The standalone manager page keeps its kind selector (general-purpose).

## Area designs

### A. Editor｜preview page

Current (`templates/courses/manage/editor/editor.html`, `_editor_scope.html`,
`_element_row.html`, `_preview.html`, `_host_form.html`; `editor.css`; `editor.js`):
single `.editor` section with a bare `← Back to builder` link, `.editor-grid` (1fr 1fr)
with `.editor-pane`/`.editor-preview` plain divs; elements as `<ol class="element-list">`
of `.el-row` (`.el-tag` chip + `.el-select` summary + `.tree__inline` ↑/↓/delete forms);
editing GETs a form into a separate `.editor-form-host` below the list; add = a row of
`.btn--small` `data-add-type` buttons.

Target:
- **Layout**: two `.pane` cards (Editor | Live preview) with uppercase pane-heads; preview
  pane sticky. Breadcrumb `← Back to builder · Course / Chapter / Section`; **Back rendered
  as an icon button**, spaced from the title (#14b). Page-head `<h1>` unit title + a
  `Unit · Lesson` type chip.
- **Element rows** as cards: drag grip + type chip + summary + hover icon-action cluster
  (edit / ↑ / ↓ / delete), consistent with the WS2 builder cluster styling.
- **Editing = inline row-expansion**: clicking edit swaps the row into its edit form in
  place (the fragment-swap already exists; retarget it from the host area to the row).
  Save/Cancel in the row.
- **Add**: dashed `+ Add element` button toggles a 5-card type menu; choosing a type opens
  a new inline editing row; **persist-on-first-save** (existing `element=new` sentinel flow
  in `save_element`).
- **Element drag-and-drop**: grip drag reorders within the unit's element list; insertion
  line marks the drop; reuse the existing `manage_element_move` endpoint (POST element +
  position/token). Mirror `builder.js` DnD (`dragstart`/`dragover`/`drop`, insertion line,
  token-aware) but flat. Keep ↑/↓ forms for no-pointer use.

### B. Preview & unit title (#14a)

The live-preview pane (and the real student lesson render, `templates/courses/lesson_unit.html`)
shows the **unit title** at the top of the rendered content so students see it. Preview pane
reuses the 1a `courses/elements/*.html` renderers (re-render on save, unchanged).

### C. Text toolbar (#12)

Current (`_edit_text.html`, `text_toolbar.js`): `.rte-toolbar` of text-labelled buttons
(`data-cmd`: bold/italic/underline/h2/h3/h4/ul/ol/link/blockquote/code) over a
contenteditable surface via `document.execCommand`; link via `window.prompt`; no active
state.

Target: same commands and the same ALLOWED set, but **icon-only SVG buttons** (an editor
sprite, mirroring the builder sprite pattern) each with a `title=` tooltip; **H2/H3/H4 stay
as three labelled buttons**; **active/pressed state** reflects the current selection format
(via `document.queryCommandState`/`queryCommandValue`, best-effort). Link keeps `prompt()`.
Restyle in `editor.css`. No change to the server-side `sanitize_html` ALLOWED_TAGS contract.

### D. Embed paste (#13)

Current: `IframeElement.url = URLField(validators=[validate_embed_url])`;
`_edit_iframe.html` is a plain `<input type="url" name="url">` + title; validation is the
existing `courses/validators.py:validate_embed_url` (https + host equals/subdomain of
`settings.ALLOWED_EMBED_DOMAINS`). No snippet parsing exists.

Target — a new pure parser (e.g. `courses/embed.py:extract_embed_url(raw) -> str`,
raising `ValidationError` with item-specific messages), wired into the iframe form's field
cleaning:
- Dispatch on the **trimmed** input: if it starts with `<`, treat as a snippet (parse with
  stdlib `html.parser` — **never regex over HTML**); else feed straight to
  `validate_embed_url`.
- Snippet path: collect `<iframe>` elements. **First-match-wins error precedence** (one
  deterministic message per fixture): malformed-parse → multi-iframe (>1) → no-iframe (0) →
  missing-`src` (absent **or** empty/whitespace `src` — never pass `""` to the validator) →
  non-whitelisted-domain (delegated to `validate_embed_url`). A wrapper `<div>` containing a
  single `<iframe>` is valid; a `<script>`-based embed hits no-iframe with a guiding message
  ("paste the embed's `<iframe …>` code or a direct URL").
- **Store only the validated `src`** in `IframeElement.url`; never the raw HTML. On render,
  rebuild the iframe from a fixed responsive template (16:9 wrapper, `width:100%`); **ignore
  pasted width/height**. `validate_embed_url` already rejects non-https (`javascript:`,
  `data:`, `http:`).
- Build against the triage spec's seven fixtures (valid geogebra; non-whitelisted host;
  `<img onerror>` no-iframe; `javascript:` src; two iframes; `<script>` embed; empty `src`).

### E. Media manager (full mockup)

Current (`media/manager.html`, `_asset_cell.html`, `media_picker.js:wireManager`,
`views_media.py`, `media.py`): upload form (kind select + file + submit, no name field) +
drag-drop zone + `.asset-grid` of `.asset-cell` (thumb + `original_filename` + in-use badge
+ delete with disabled-when-in-use). No filter, search, or rename.

Target:
- **Model**: add `MediaAsset.name = CharField(max_length=255, blank=True)` (display name;
  blank → falls back to `original_filename` for display/`__str__`). Migration **0009**
  (add nullable/blank field; no data backfill needed — blank renders as the filename).
- **Upload card**: kind select + file + **optional Name** + Upload, plus the drag-drop zone.
  Optional name sets `MediaAsset.name`; blank keeps the filename fallback.
- **Grid head**: type-filter `<select>` (All / Images / Videos) + file **count** + **search**
  box (matches `name` or `original_filename`). Server reads `?kind=` and `?q=` query params
  (extend `views_media.py` + a `media.py` query helper); progressive-enhanced (form submit
  works no-JS; JS can fetch-and-swap the grid).
- **Cell**: thumb + **display name with inline rename pencil** + filename + in-use badge +
  delete (guarded). Rename = new endpoint `manage_media_rename` (POST asset + name) +
  `media.py:rename_asset`; inline-edit pencil swaps the name to an input, Enter saves / Esc
  cancels (vanilla JS in `media_picker.js:wireManager`).

### F. Media picker modal

Current (`_picker.html`, `media_picker.js:wireEditorPicker`, `views_media.py`): overlay +
card with Library/Upload tabs; assets filtered server-side by `?kind=`; no search; Upload
tab has a bare file input.

Target: keep tabs; add a **search** box (filters the library grid client-side or via `?q=`);
**kind-locked** to the element — the grid and the Upload tab both operate on the element's
single kind (no kind selector in the modal). Picking sets the element form's `media` value
(existing `selectAsset`); uploading auto-selects the returned asset (existing flow), now
carrying the optional name if provided.

### G. Element editors restyle

`_edit_image / _edit_video / _edit_iframe / _edit_math.html` and `_host_form.html` restyle
to sit cleanly inside the inline editing row (consistent field/label/`btn`/`btn--small`
styling). No form-field changes except the iframe field switching to the smart embed input
(D). `element_forms.py` field lists unchanged except iframe cleaning calls the new parser.

## Model / endpoint / file changes (summary)

- **Model**: `MediaAsset.name` (+ migration 0009). Display falls back to `original_filename`.
- **New module**: `courses/embed.py` (`extract_embed_url`).
- **New endpoint**: `manage_media_rename` (+ url + `media.py:rename_asset`).
- **Extended**: `views_media.py` manager + picker read `?kind=`/`?q=`; `element_forms.py`
  iframe field cleaning; `media.py` search/query helper.
- **Templates**: editor `editor.html`, `_editor_scope.html`, `_element_row.html`,
  `_preview.html`, `_host_form.html`, `_edit_*.html`; media `manager.html`, `_picker.html`,
  `_asset_cell.html`; student `lesson_unit.html` (unit title). 
- **JS/CSS**: `editor.js` (inline-expansion retarget + add-menu + element DnD),
  `text_toolbar.js` (icons + active state), `media_picker.js` (manager search/filter/rename
  + picker search/kind-lock), `editor.css` (+ an editor SVG sprite).

Concurrency unchanged: reuse 1b-i/1b-ii optimistic `updated`-token (every element op bumps
the unit's `updated`; 409-before-422). Element DnD reuses the element-move endpoint's token.

## Testing & Done-gate

- **Unit**: `extract_embed_url` against all seven fixtures (one deterministic message each);
  `MediaAsset.name` display fallback; `rename_asset`; manager/picker `?kind=`/`?q=` filtering;
  iframe form accepts a snippet and stores only the `src`.
- **e2e (Playwright, `-m e2e`)**: inline add (type-card → new row → first-save persists);
  inline edit + save; **element drag-drop reorder** asserts DOM order; embed-paste happy path
  (snippet → stored src → preview renders) + a reject path (non-whitelisted → error, nothing
  stored); media rename; picker kind-lock (image element shows only images).
- **Gate**: ruff check/format, `manage.py check`, `makemigrations --check` (only 0009),
  collectstatic clean. Visual dark/light eyeball pass owed by the user (per triage vocabulary).

## i18n

Wrap every new template/JS/form string in `{% trans %}`/`gettext`; JS notices via `data-*`
attrs (the WS2 pattern). Add + compile Polish for the touched screens. This is the
per-workstream fold of the triage's i18n sweep, not the final catch-all pass.

## Out of scope

- HTML element (5.11) — its own later slice 1b-iii.
- Preview-as-student (5.14).
- Inline link popover (link stays `prompt()`).
- Per-embed custom sizing (responsive 16:9 only; revisit later if needed).
- The cross-cutting final i18n catch-all (`django.po` whole-catalog gate) — WS-level only here.

## Sequencing hint (for the plan)

Editor page restyle + inline-expansion → add-menu → element DnD → toolbar icons → embed
parser+field → media model/migration+manager → picker → i18n → e2e/DoD. Order so each commit
stays green; the embed parser is independently unit-testable and can land early.
