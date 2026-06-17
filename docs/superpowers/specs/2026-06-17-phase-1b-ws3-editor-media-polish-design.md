# Phase 1b — WS3: Editor & media polish (design, 2026-06-17)

Workstream 3 of the Phase-1b UX-review-triage backlog
(`docs/superpowers/specs/2026-06-16-phase-1b-ux-review-triage.md`). Pure 1b-ii surface
work on an essentially unchanged backend, **except** one small media-model field + the
new embed-snippet parser. Builds to the already-accepted mockups:

- `docs/mockups/content-editor_accepted-A.html` (editor｜preview)
- `docs/mockups/media-manager-and-picker_accepted.html` (manager + picker)

Both mockup files are confirmed present (note the `-A` accepted-variant suffix on the editor
mockup). Fidelity bar: match layout + token usage; minor spacing latitude allowed.

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
   drop-to-absolute-position; keep ↑/↓ as the no-pointer/fallback path. **This requires a
   backend change** (detailed in §A): the current `element_move` endpoint is direction-only
   (up/down); it gains an absolute-`position` mode so a drag can land anywhere in one POST.
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
  pane sticky. Breadcrumb built from the unit's **actual ancestor chain** (variable depth —
  Course ▸ optional Part ▸ Chapter ▸ Section, whatever levels exist; not a fixed three), with
  **Back rendered as an icon button** spaced from the title (#14b). Page-head `<h1>` unit
  title + a type chip reading `Unit · <unit_type>`, where the second token is the unit's
  `get_unit_type_display` (a real `ContentNode.unit_type` field — "Lesson"/"Quiz" — not
  decorative text). The editor serves **any** unit regardless of `unit_type`; the
  element/preview pipeline is unit-type-agnostic (elements attach to any unit). `quiz` remains
  the inert Phase-2 placeholder from 1a — it reaches the same editor with no quiz-specific
  element semantics added in 1b.
- **Element rows** as cards: drag grip + type chip + summary + hover icon-action cluster
  (edit / ↑ / ↓ / delete), consistent with the WS2 builder cluster styling.
- **Editing = inline row-expansion**: clicking edit reveals the edit form inside a dedicated
  `[data-edit-slot]` container within that row (the grip/chip/summary header stays; the form is
  injected below it — the `<li>` row element itself is never replaced). **Single-open-editor
  invariant**: opening one edit (or the add-menu) closes any other. Because every element op
  re-renders the whole editor pane via `_render_editor_fragments` (see §D), the freshly
  re-rendered fragment shows the operated element **already expanded** as its post-op state; a
  Save/Cancel/DnD on a *different* element discards any open form (one editor at a time, by
  design). Save/Cancel live in the row.
- **Add**: dashed `+ Add element` button toggles a 5-card type menu; choosing a type opens
  a new inline editing row; **persist-on-first-save** (existing `element=new` sentinel flow
  in `save_element`).
- **Element drag-and-drop**: grip drag reorders within the unit's element list; insertion line
  marks the drop. **Backend change (stated scope expansion):** the current
  `element_move`→`reorder_element(course, element_pk, direction, unit_token)` is direction-only
  (up/down via `ordering.move_in_list`); add an **absolute-position mode** —
  `reorder_element(..., position=<0-based int>, unit_token=...)` that re-places the element via
  the existing `courses/ordering.py` helpers (mirrors how `reparent_node` accepts a `position`).
  The view reads `direction` (↑/↓) **or** `position` (DnD); **exactly one must be present** —
  both-present or neither is a **422** (not a silent reorder). `position` is parsed to int **at
  the view layer**; a non-integer/empty value is a 422 (the service only ever receives a clean
  int). **Index semantics:** the posted index is the target slot in the list **after the dragged
  element is removed**; the service algorithm is *remove the element from its sibling list, then
  insert at `position` clamped to `[0, len]`* (out-of-range clamps, never errors). When the
  resulting order is unchanged (e.g. dropped on its own slot), `reorder_element` returns
  `(unit, False)` — mirroring the direction no-op — and the view does **not** bump `updated`.
  Both paths obey 409-before-422 and bump `unit.updated` on a real change. No migration. JS
  mirrors `builder.js` DnD (`dragstart`/`dragover`/`drop`, insertion line, token-aware) but flat
  (no nesting/legality), POSTing the **post-removal** 0-based index + `unit_token`. **Drag
  handlers are (re)bound after every editor-fragment swap; a 409 swap also clears transient drag
  UI (insertion line, drag-over classes).** Keep ↑/↓ forms for no-pointer use.

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
as three labelled buttons**. **Active/pressed state**: bold/italic/underline reflect the
selection via `document.queryCommandState` (the reliable cases) and ARE asserted by the e2e;
the H2/H3/H4 active state is **best-effort and explicitly untested** (`queryCommandValue
("formatBlock")` returns inconsistent strings across browsers — never gate a test on it).
Link keeps `prompt()`. Restyle in `editor.css`. No change to the server-side `sanitize_html`
ALLOWED_TAGS contract.

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
  ("paste the embed's `<iframe …>` code or a direct URL"). The multi-iframe count is the
  **total** number of `<iframe>` elements anywhere in the parsed fragment (including inside
  `<noscript>` or duplicate wrappers): **any total > 1 rejects by design** ("paste a single
  embed"), so the user trims duplicated/`<noscript>` copies — chosen as strict and deterministic
  over a "first/outermost wins" rule.
- **Store only the validated `src`** in `IframeElement.url`; never the raw HTML. On render,
  rebuild the iframe from a fixed responsive template: the current
  `courses/elements/iframeelement.html` is a bare `<iframe src>` with no wrapper, so it **is
  updated** to a 16:9 `width:100%` responsive wrapper (added to the touched-templates list);
  existing iframe elements keep rendering since only `src` was ever stored. **Ignore pasted
  width/height**. `validate_embed_url` rejects any scheme `!= "https"`, so `javascript:`,
  `data:`, `http:`, and scheme-relative (`//host/…`, which `urlsplit` parses with `scheme=""`)
  all fail the https check before the host allow-list is consulted. The empty/whitespace-`src`
  short-circuit above means `""` is never handed to `validate_embed_url` (whose message would
  otherwise be the wrong "must use https" instead of the intended missing-`src` message).
- **On reject, nothing persists**: a `ValidationError` from `extract_embed_url` is raised in
  the iframe form's field clean, so `save_element` aborts with the standard 422 (the bound form
  re-renders with the offending input + the message); when **editing an existing** iframe
  element, its previously stored `url` is left untouched. The plain-URL path surfaces
  `validate_embed_url`'s own messages — the non-whitelisted case renders the existing "Embed
  domain is not on the allow-list."
- Build against the triage spec's seven fixtures (valid geogebra; non-whitelisted host;
  `<img onerror>` no-iframe; `javascript:` src; two iframes; `<script>` embed; empty `src`).

### E. Media manager (full mockup)

Current (`templates/courses/manage/media/manager.html`, `_asset_cell.html`,
`courses/static/courses/js/media_picker.js:wireManager`, `courses/views_media.py`,
`courses/media.py`): upload form (kind select + file + submit, no name field) +
drag-drop zone + `.asset-grid` of `.asset-cell` (thumb + `original_filename` + in-use badge
+ delete with disabled-when-in-use). No filter, search, or rename.

Target:
- **Model**: add `MediaAsset.name = CharField(max_length=255, blank=True, default="")` (display
  name; **not** `null=True` — exactly one empty state, `""`). Add a `display_name` property
  returning `self.name or self.original_filename`, and change `__str__` to
  `f"{self.get_kind_display()}: {self.display_name}"` (keeps the existing kind prefix). The
  `element_summary` filter in `courses_manage_extras.py` (its image alt-fallback branch and its
  video branch, which currently read `el.media.original_filename`) switches to `display_name`;
  the raw `original_filename` is still shown beneath the display name in the cell. Migration
  **0009** adds the field with `default=""`; no data backfill (existing rows get `""` → fall
  back to filename).
- **Upload card**: kind select + file + **optional Name** + Upload, plus the drag-drop zone.
  Optional name sets `MediaAsset.name`; blank keeps the filename fallback. **Name rule (shared
  by upload and the rename endpoint):** the submitted name is **trimmed**; empty/whitespace-only
  stores `""` (re-engaging the `original_filename` fallback — never an error); input exceeding
  `max_length=255` is a 422 (no silent truncation).
- **Grid head**: type-filter `<select>` (All / Images / Videos) + file **count** + **search**
  box. Filtering is **server-side** via `?kind=` and `?q=` (extend `views_media.py` + a
  `media.py` query helper): `q` is trimmed; empty `q` = no filter; non-empty `q` matches
  `name__icontains` **OR** `original_filename__icontains`; `kind` is exact (absent/"all" = no
  filter). Progressive-enhanced — the form submits no-JS, and **JS does the same `?q=`/`?kind=`
  server round-trip and swaps the grid** (no separate client-side filtering, so JS and no-JS
  results are identical). The live search is **debounced (~250 ms)** and drops superseded
  responses (ignore a reply whose query no longer matches the current input) so a slow earlier
  response can't overwrite a newer grid.
- **Cell**: thumb + **display name with inline rename pencil** + filename + in-use badge +
  delete (guarded). Rename = new endpoint `manage_media_rename` (POST asset id + name) +
  `media.py:rename_asset`; inline-edit pencil swaps the name to an input, Enter saves / Esc
  cancels (vanilla JS in `media_picker.js:wireManager`). On success the endpoint returns the
  **re-rendered `_asset_cell.html` fragment**, which JS swaps into that cell; no-JS posts the
  form and the page reloads with the new name. (`display_name` shown in editor alt/summary
  readers refreshes on their next render, not live.) **Concurrency: media rename is NOT under
  the unit `updated`-token regime** (`MediaAsset` carries no `updated` token) — it is
  last-write-wins; the only guards are course-scoped manage permission + asset-belongs-to-course.

### F. Media picker modal

Current (`_picker.html`, `media_picker.js:wireEditorPicker`, `views_media.py`): overlay +
card with Library/Upload tabs; assets filtered server-side by `?kind=`; no search; Upload
tab has a bare file input.

Target: keep tabs; add a **search** box that uses the **same server `?q=` round-trip** as the
manager (I1) — not separate client-side filtering — so picker and manager results match;
**kind-locked** to the element — the grid and the Upload tab both operate on the element's
single kind (no kind selector in the modal). The element's kind reaches the picker via a
`data-kind` (image/video) on the opening control, passed to the picker endpoint as `?kind=`;
**the server enforces it** — the picker's grid query, its upload, and its select all validate
the kind server-side (a crafted POST cannot place a video into an image element), not merely a
client filter. Picking sets the element form's `media` value (existing `selectAsset`); uploading
auto-selects the returned asset (existing flow), now carrying the optional name if provided.

### G. Element editors restyle

`_edit_image / _edit_video / _edit_iframe / _edit_math.html` and `_host_form.html` restyle
to sit cleanly inside the inline editing row (consistent field/label/`btn`/`btn--small`
styling). No form-field changes except the iframe field switching to the smart embed input
(D). `element_forms.py` field lists unchanged except iframe cleaning calls the new parser.

## Model / endpoint / file changes (summary)

- **Model**: `MediaAsset.name` + `display_name` property (+ migration 0009). `display_name` =
  `name or original_filename`; `__str__` and the `courses_manage_extras.py` label readers use it.
- **New module**: `courses/embed.py` (`extract_embed_url`).
- **New endpoint**: `manage_media_rename` (+ url + `media.py:rename_asset`).
- **Extended**: `views_media.py` manager + picker read `?kind=`/`?q=`; `element_forms.py`
  iframe field cleaning; `media.py` search/query helper.
- **Templates**: editor `editor.html`, `_editor_scope.html`, `_element_row.html`,
  `_preview.html`, `_host_form.html`, `_edit_*.html`; media `manager.html`, `_picker.html`,
  `_asset_cell.html`; student `lesson_unit.html` (unit title); element render
  `courses/elements/iframeelement.html` (responsive 16:9 wrapper). 
- **JS/CSS**: `editor.js` (inline-expansion retarget + add-menu + element DnD),
  `text_toolbar.js` (icons + active state), `media_picker.js` (manager search/filter/rename
  + picker search/kind-lock), `editor.css` + an inline `<svg>` icon-symbol sprite in the editor
  template, referenced via `<use href="#ed-…">` (matching the builder's `builder__sprite`
  pattern — no new static file).

Concurrency unchanged: reuse 1b-i/1b-ii optimistic `updated`-token (every element op bumps
the unit's `updated`; 409-before-422). Element DnD reuses the element-move endpoint's token.

## Testing & Done-gate

- **Unit**: `extract_embed_url` against all seven fixtures (one deterministic message each);
  `MediaAsset.name` display fallback; `rename_asset`; manager/picker `?kind=`/`?q=` filtering;
  iframe form accepts a snippet and stores only the `src`.
- **e2e (Playwright, `-m e2e`)**: inline add (type-card → new row → first-save persists);
  inline edit + save; **element drag-drop reorder** asserts DOM order; embed-paste happy path
  (snippet → stored `src` → preview renders) + a reject path (non-whitelisted snippet → 422 +
  message, **asserts `IframeElement` count/`url` unchanged**); toolbar bold/italic active-state
  toggle (heading active-state untested, per §C); media rename; picker kind-lock (image element
  shows only images).
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
