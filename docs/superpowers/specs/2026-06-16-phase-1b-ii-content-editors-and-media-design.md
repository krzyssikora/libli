# Phase 1b-ii — Content Editors & Media Manager: Design Spec

*Spec date: 2026-06-16. Second slice of Phase 1b (the bespoke authoring UI), itself the second major
slice of [Phase 1](../../roadmap.md#phase-1--content-model-authoring--lesson-consumption). Builds directly
on [Phase 1a](2026-06-15-phase-1a-content-model-and-consumption-design.md) (content schema, `ContentNode`
tree, `Element` GFK + 5 concrete models, `OrderField`, the `courses/elements/*.html` renderers) and on
[Phase 1b-i](2026-06-15-phase-1b-i-course-crud-and-builder-design.md) (the `/manage/` surface, the
master-detail course builder, the unit panel with its element list + reorder/delete, the optimistic-token
concurrency model), both merged (PRs #6, #7). Views numbered per [view-inventory.md](../../view-inventory.md)
§5/§7. Stack per [the 0d UI foundation](2026-06-14-phase-0d1-ui-foundation-design.md): server-rendered
Django, token-driven bespoke CSS, no Bootstrap/React/HTMX.*

## Goal

Ship a **demonstrable content-authoring vertical slice**: from the 1b-i unit panel, an owner (or PA) opens a
**per-unit editor ｜ preview page** and **adds, edits, reorders, and deletes** a unit's elements — text,
image, video, iframe, math — seeing a **live student-faithful preview** update on every save. Uploaded
images/videos become reusable **`MediaAsset`s** in a per-course library, managed through a **media manager**
page and chosen through a **picker modal**. This replaces the element-authoring half of `seed_demo_course`
and the "use Django admin to write element bodies" scaffolding, completing the authoring story for the
5 safe element types. The arbitrary-HTML element (5.11) and the full Preview-as-student walk-through (5.14)
are deferred (see Out of scope).

## Phase 1b slice split (recap + this slice)

Phase 1b (the authoring UI) is split into vertical slices, each its own spec → plan → build:

- **1b-i (merged) — Course CRUD + builder.** Course create/edit/delete; the master-detail builder (tree of
  part/chapter/section/unit); the unit-settings panel; element **list + reorder + delete**.
- **1b-ii (this spec) — Content editors + media manager.** The per-unit **editor ｜ preview** page; the
  5 element editors (text/image/video/iframe/math); element **add + edit**, with reorder/delete **folded onto
  the editor page**; the **`MediaAsset`** model + per-course **media manager** (5.13) + **picker modal** (7.4).
- **1b-iii — HTML element slice.** The arbitrary-HTML element (course-wide CSS/JS, per-unit JS,
  MathJax/LaTeX) with its dedicated **security design**, rendering into this slice's preview pane. Carved out
  because it executes author-supplied JavaScript and warrants a focused security spec.

## Layout decision (recap from 1b-i, realised here)

1b-i locked a **hybrid split by level**: structure work stays in the builder's master-detail panel; **deep
content editing gets its own full page with a live preview alongside (editor ｜ preview)**. 1b-i built only
the **seam** — two disabled buttons on the unit panel ("+ Add element", "Open editor →") labelled "Coming in
Phase 1b-ii". This slice **lights up that seam**: both buttons navigate to the editor ｜ preview page, which
becomes the **single home for all of a unit's element work**.

## Foundational decisions (locked in brainstorming 2026-06-16)

1. **HTML element deferred to its own slice (1b-iii).** This slice ships the **5 safe element types**
   (text/image/video/iframe/math) only. The 6th type — arbitrary HTML with course-wide CSS/JS + per-unit JS +
   MathJax/LaTeX — executes author-supplied JavaScript and is carved out with its own security spec. The
   editor ｜ preview page is built so the HTML editor and its preview slot into the **same panes** later with
   no layout change.

2. **The editor ｜ preview page owns all element work; the unit panel becomes a read-only summary.** Add,
   edit-body, reorder, and delete for a unit's elements **all** happen on the editor page, with live preview.
   The 1b-i unit panel's interactive element list **collapses to a read-only summary** (type + title, in
   order) whose **"+ Add element"** and **"Open editor →"** both **deep-link into the editor page** (add
   carries an intent to open the type picker). This is a single coherent surface rather than element ops split
   across two places. The reorder/delete **endpoints** built in 1b-i (`manage_element_move`,
   `manage_element_delete`) are **reused unchanged** by the editor page; only their *caller* moves. **The unit
   panel's own reorder/delete controls are removed** (the summary is non-interactive) so there is exactly one
   interactive surface for element ops — no duplicated controls, no two concurrency surfaces for the same list.

3. **Editor layout — element list with one inline editor open at a time (Layout A).** The editor pane is a
   compact, ordered, selectable list of the unit's elements (type tag + summary + ↑/↓/✕). Selecting a row
   opens **its** editor form **inline**; other rows stay collapsed (**one editor open at a time**). The
   preview pane (right on desktop, stacked below on mobile) renders the **whole unit** as a student sees it.
   Rejected: an all-forms-open "stacked document" with a batch "Save all" — it needs multi-element dirty
   tracking and a batch save, diverging from 1b-i's **per-operation atomic POST** model.

4. **Live preview — server re-render on save (single source of truth).** After any element mutation
   (add/save-body/reorder/delete) the server returns **two fragments** — the re-rendered **editor pane** and
   the re-rendered **preview** (built by **reusing the 1a `courses/elements/*.html` templates**) — swapped by
   vanilla JS (the same `fetch`-and-swap idiom as `builder.js`/`progress.js`). Preview therefore **equals
   exactly what students see**, including server-side sanitisation and embed-whitelist enforcement. Updates
   land **on save, not per keystroke**. **No-JS fallback:** the same POST routes do a full-page reload showing
   saved state. Rejected: client-side live-as-you-type (duplicates rendering + sanitisation in the browser,
   risks drift and previewing unsanitised HTML) and an iframe of the real student view (heavier; its value
   arrives with the deferred course-CSS/JS slice).

5. **Media — a per-course `MediaAsset` library; elements reference assets by FK.** Uploaded images/videos
   become **`MediaAsset`** rows scoped to a `Course` (the owner/PA boundary). `ImageElement` and the uploaded
   side of `VideoElement` reference a `MediaAsset` by **FK** instead of embedding the file — enabling reuse
   (one diagram in many units) and a real **browse** surface. **`alt`/`figcaption` stay on the element** (the
   same asset can carry different captions per use); **embed URLs stay on the element** (`MediaAsset` is for
   *uploaded* files only, never embed URLs). A schema + **data migration** moves the handful of existing
   `seed_demo_course` embedded files into assets. Rejected: keeping files on elements with only a thin file
   browser (no real reuse) and deferring the media manager entirely.

6. **Styled text — a minimal bespoke rich-text toolbar.** The text editor is a small vanilla-JS toolbar over
   a `contenteditable` region offering **exactly the formatting `sanitize_html` already allows**: Bold,
   Italic, Underline, Heading (H2/H3/H4), bullet list, numbered list, Link, Blockquote, Code. Output is HTML,
   **sanitised server-side via the existing `sanitize_html`** on save (the browser toolbar is a convenience,
   **never** the security boundary). No third-party RTE dependency. Rejected: a raw-HTML textarea (rough for
   non-technical teachers) and a Markdown textarea (adds a dependency, can't express the styled subset).

7. **Concurrency — reuse 1b-i's optimistic `updated`-token model verbatim.** Every element mutation re-reads
   its row(s) inside `transaction.atomic()`, compares the carried `updated` token first, returns **`409` +
   fresh fragment** on mismatch (no write), **`422` + in-panel error** on validation failure, **`200` +
   updated fragments** otherwise. Because 1a `Element` join-rows have no `updated`, **every element op bumps
   the parent unit's `updated`** (`unit.save(update_fields=["updated"])`) — exactly as 1b-i established — so
   the unit row is the concurrency boundary for element ops. A new concrete-element edit (e.g. saving a text
   body) **also** bumps the unit token, so two authors editing the same unit's elements see `409`s, not silent
   clobbering. No new version column.

## Success criteria (Definition of Done)

1. **Editor ｜ preview page** (`GET /manage/courses/<slug>/build/unit/<int:pk>/edit/`, `@login_required` +
   manage predicate): renders a two-pane editor for a **unit** node — left an ordered, selectable element
   list; right a live preview of the whole unit via the **1a element renderers**. Reached from the unit
   panel's now-active **"Open editor →"** (and **"+ Add element"**, which additionally opens the type picker).
   A **non-unit** pk → 404; a unit in another course (slug mismatch) → 404 (IDOR guard, before 403); a unit
   with **no elements** renders an empty-state in both panes. The 1b-i unit panel's element list is now a
   **read-only summary** (no reorder/delete controls there).

2. **Add element** (`POST …/build/element/add/`, manage predicate, CSRF, atomic): a type picker offers the
   **5 types** (text/image/video/iframe/math). Choosing a type opens a **blank inline editor** for it on the
   editor page **without yet persisting a row**; the **first successful save** (DoD #3) materialises the
   concrete element **and** its 1a `Element` join-row together, appended at the end of the unit's `Element`
   `OrderField` scope, via `full_clean()`/`save()` (so every persisted element is valid by construction — no
   "incomplete" state — and 1a invariants + `TextElement` sanitisation hold). Cancelling adds nothing. This
   carries + bumps the **unit token**; a stale token at save → `409` + fresh editor fragment, no write. (See
   Data model: *blank-create rule* — including the `is_incomplete`-marker fallback should persist-on-first-save
   prove impractical.)

3. **Edit element body** (`POST …/build/element/save/`, manage predicate, CSRF, atomic): saves the selected
   element's fields through a per-type Django `ModelForm` + `full_clean()`/`save()`. On success returns the
   re-rendered **editor pane + preview** fragments (`200`). Validation failure → **`422`** with the form
   re-rendered **in place** showing field errors (no write, preview unchanged). Stale unit token → **`409`** +
   fresh editor fragment. **Text** bodies pass through `sanitize_html` on save (model `save()` already does
   this); the returned preview shows the **sanitised** result.

4. **Element reorder / delete on the editor page** (reusing 1b-i `…/build/element/move/` +
   `…/build/element/delete/`): the editor pane's ↑/↓/✕ controls drive the **existing** endpoints; responses
   re-render the **editor pane + preview** (the editor page supplies its own fragment template; the endpoints
   gain an editor-context response path, see Mechanics). Delete cascades the concrete element + join-row (1a
   `GenericRelation`) and **gap-compacts** the unit's element scope. Boundary reorder no-ops bump no token
   (per 1b-i rules). An op on a **vanished** element row → `409` + fresh editor fragment.

5. **The 5 element editors** (per-type forms, all server-validated):
   - **Text (5.6):** a bespoke vanilla-JS toolbar over `contenteditable` — Bold / Italic / Underline /
     H2 / H3 / H4 / bullet list / numbered list / Link / Blockquote / Code (the `ALLOWED_TAGS` set). Submits
     HTML; **server sanitises** via `sanitize_html`. With JS off, degrades to a plain `<textarea>` of the raw
     HTML (still sanitised on save).
   - **Image (5.7):** **"Choose media"** opens the picker (pick existing / upload) → sets the element's
     `media` FK; plus `alt` (blank = decorative, valid) and `figcaption`. Preview renders `imageelement.html`.
   - **Video (5.8):** a radio choice — **Embed URL** (whitelisted, `validate_embed_url`) **or** **Uploaded
     video** (picker → `media` FK); the model's **XOR** (`url` ⊕ `media`) enforced in `clean()` → `422` on
     violation. Preview renders `videoelement.html`.
   - **Iframe (5.9):** whitelisted `url` (`validate_embed_url`) + optional `title`. Preview renders
     `iframeelement.html`.
   - **Math (5.10):** `latex` textarea with a **KaTeX live preview** (the KaTeX assets wired in 1a) in the
     editor *and* in the unit preview via `mathelement.html`.

6. **`MediaAsset` model + migration:** a new per-course asset model (image|video file + metadata);
   `ImageElement.image` → `media` FK; `VideoElement.file` → `media` FK (nullable; XOR with `url`); a **data
   migration** ports existing `seed_demo_course` embedded files into `MediaAsset` rows and re-points the FKs.
   `makemigrations --check` clean after (the new migrations are committed). `IframeElement`, `MathElement`,
   `TextElement` unchanged.

7. **Media manager page (5.13)** (`GET /manage/courses/<slug>/media/`, manage predicate): a grid of the
   course's `MediaAsset`s (thumbnail/type + filename + **usage count**), an **Upload** action and a
   **drag-and-drop** drop zone (JS; no-JS uses the file input), and **delete**. **Delete is guarded:** an
   in-use asset (referenced by ≥1 element) **cannot** be deleted — the server rejects it (→ `409`/`422` with a
   message naming the using units); only unused assets delete. Uploads validate type/extension/size via the
   existing `FileExtensionValidator` + `validate_image_size`/`validate_video_size`.

8. **Picker modal (7.4)** (served as a fragment, invoked from image/video editors): the **same per-course
   library** as a modal with two tabs — **Library** (browse + pick an existing asset → returns its id/preview
   to the element form) and **Upload** (drag-drop/file input → creates a `MediaAsset` → auto-selects it).
   No-JS fallback: the image/video editor offers a direct `<input type="file">` and a plain `<select>` of
   existing assets, so picking/uploading works without the modal.

9. **Access control & object scoping:** every `/manage/…` route here is `@login_required` + the canonical
   **manage predicate** (`course.owner_id == user.id OR user.has_perm("courses.change_course")`, `owner_id is
   not None` guard; no `is_staff`) — identical to 1b-i. Element/asset routes use the `<int:pk>` converter and
   check, in order: object exists (→404), **belongs to the URL's course** (→404, IDOR guard, before any 403),
   then the manage predicate (→403). A `MediaAsset` from another course can never be referenced by an element
   (the picker lists only this course's assets; the save view re-validates the asset's `course` matches →
   `422`/404 on mismatch). CSRF on every mutating endpoint.

10. **Validation & safety:** all writes via `full_clean()`/`save()` (no `bulk_create`/`QuerySet.update()` that
    would bypass `TextElement` sanitisation or model `clean()`); `sanitize_html` on text save; embed-URL
    whitelist on video/iframe save; upload validators on `MediaAsset`; per-type `clean()` is the **authority**
    (the toolbar/picker only *offer* legal input). The browser toolbar is **never** the security boundary —
    server sanitisation is.

11. **Optimistic concurrency:** every element mutation carries the **parent unit's** `updated` token; the view
    re-reads in-txn, **token check first** → `409` (no write, fresh fragment) on mismatch, then
    `clean()`/validation → `422`, else apply → `200`. `MediaAsset` ops (upload/delete) are **not** part of the
    unit-token protocol (assets are course-library rows, not unit content); a delete re-checks usage in-txn so
    a concurrently-attached asset is safely refused. Exact contract under Mechanics.

12. **i18n:** all new UI strings via `gettext`, EN + real Polish, compiled (same flow as 0d/1a/1b-i). Editor
    chrome (toolbar labels/tooltips, picker tabs, type-picker, media manager) in the **UI** language;
    author-entered content (text bodies, captions, titles, LaTeX) is **content** and untranslated.

13. **Responsive & theming:** editor ｜ preview is side-by-side on desktop, **stacked** (editor above
    preview) on mobile; the picker modal is full-screen on mobile; light/dark + branding inherited from the 0d
    shell.

14. **Tests** (pytest + factory_boy vs real PostgreSQL): the `MediaAsset` model + **data-migration** (existing
    embedded files become assets, FKs re-pointed); the editor page render (unit-only, IDOR 404, empty state);
    **add** each of the 5 types (a cancelled add persists nothing; the first save materialises the row); **edit/save** each type incl.
    **`422` validation paths** (iframe bad domain, video XOR violation, math empty, image missing media);
    **text sanitisation** (a `<script>`/disallowed tag is stripped and the preview reflects it); reorder/delete
    via the editor page incl. **vanished-element `409`**; **stale-unit-token `409`** on add/save; media
    upload + type/size rejection; **guarded delete** (in-use refused, unused succeeds); picker library/upload;
    cross-course asset rejection. A **Playwright e2e**: log in as PA → open a unit's editor → add a text
    element and format it with the toolbar → add an image via the picker (upload) → add a math element and see
    the KaTeX preview → reorder two elements → delete one → assert the preview matches throughout; plus the
    **no-JS fallback** (add + save an element via full-page POST with scripting disabled) and a **stale-token
    `409`** path (mutate the unit out of band, confirm the next save swaps in the fresh fragment rather than
    clobbering).

15. Full `pytest` green; `ruff` check + format clean; `manage.py check` clean; `makemigrations --check`
    clean (new migrations committed); `collectstatic` clean.

---

## Data model

This slice **adds one model and alters two**; a schema migration **is** expected (unlike 1b-i).

### New: `MediaAsset`

```
MediaAsset
  course           FK(Course, on_delete=CASCADE, related_name="media_assets")
  kind             CharField(choices=image|video)
  file             FileField(upload_to="courses/media/<course>/…")
                     validators per kind: image → FileExtensionValidator([png,jpg,jpeg,gif,webp]) +
                     validate_image_size; video → FileExtensionValidator([mp4,webm,ogg,mov]) +
                     validate_video_size  (enforced in clean()/form by kind)
  original_filename CharField  (the uploaded name, for display)
  uploaded_by      FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL)
  created          DateTimeField(auto_now_add=True)
```

- **Per-course scope** = the owner/PA authoring boundary; the picker and manager only ever query
  `course.media_assets`. SVG remains **excluded** (XSS), consistent with 1a's image allowlist.
- **`kind`** lets the picker filter (image editor shows image assets; video editor shows video assets) and
  lets `validate_image_size` vs `validate_video_size` apply correctly. The `image`/`video` extension allowlists
  and size caps are the **existing** 1a validators, reused.
- **Usage count** = number of `ImageElement` + `VideoElement` rows whose `media` FK points at the asset
  (a small aggregate query); drives the manager's "in use ×N" badge and the **guarded delete**.

### Altered: `ImageElement`

- `image = ImageField(...)` → **`media = FK(MediaAsset, on_delete=PROTECT, limit_choices_to={"kind":"image"})`**.
  `PROTECT` is the DB-level twin of the guarded delete (an in-use asset can't be deleted). `alt` + `figcaption`
  **unchanged** (stay on the element). The 1a `imageelement.html` renderer updates to read `el.media.file`.

### Altered: `VideoElement`

- `file = FileField(...)` → **`media = FK(MediaAsset, null=True, blank=True, on_delete=PROTECT,
  limit_choices_to={"kind":"video"})`**. `url` (whitelisted embed) **unchanged**. `clean()`'s XOR becomes
  **`url` ⊕ `media`** (exactly one set). `videoelement.html` updates to read `el.media.file` when `media` is
  set, else the embed `url`.

### Unchanged

- `TextElement` (`body`, sanitised on save), `IframeElement` (`url` + `title`), `MathElement` (`latex`),
  and the `Element` GFK join-row + `OrderField` — all **as in 1a**.

### Blank-create rule (for "Add element")

"Add element" creates an **empty** element so its editor can open immediately, but three types have
DB-/`clean()`-required content (`IframeElement.url`, `MathElement.latex`, `VideoElement` XOR; `ImageElement`
needs a `media`). To avoid persisting a row that violates `clean()`:

- The concrete element is created with its required fields **blank** and is **never `full_clean()`-rejected at
  creation** because creation uses a **minimal valid skeleton** — for `MathElement`/`IframeElement` a single
  empty-string placeholder is allowed only transiently and the element carries an **`is_incomplete`** marker
  (a derived/queried state: "required fields not yet filled"), surfaced in the editor list ("⚠ unfinished")
  and **excluded from the student render** (the 1a unit view skips incomplete elements; or — simpler and
  preferred — **the join-row is created on first valid save, not on add**).
- **Preferred realisation (decided in plan):** *Add* does **not** persist an empty concrete row at all.
  Instead it opens a **blank editor form** for the chosen type with **no element yet**; the **first successful
  save** creates the concrete element **and** the `Element` join-row together (append to scope), through
  `full_clean()`. Cancelling adds nothing. This removes the "incomplete row" state entirely and keeps every
  persisted element valid by construction. *(The DoD's "add then edit" still holds end-to-end; the row simply
  materialises on first save. The plan picks this realisation unless a blocker emerges, in which case the
  `is_incomplete`-marker fallback above applies.)*

### Migration

A schema migration (the field swaps + new model) **plus** a **data migration**: for each existing
`ImageElement`/`VideoElement` with an embedded file (only `seed_demo_course` rows exist), create a
`MediaAsset` (same `course` as the owning unit's course, `kind` by type, `file` = the existing file,
`original_filename` from the basename) and set the new `media` FK. Old file columns are removed after the data
copy. Reversible where practical; the migration is committed so `makemigrations --check` stays clean.

---

## Views, routes & layout

All under the existing `app_name = "courses"`, `/manage/` prefix, in `courses/views_manage.py` (editor +
element ops) and a new **`courses/views_media.py`** (asset manager + picker + upload), keeping files focused.
Element-op **services** extend `courses/builder.py`; asset services live in a new **`courses/media.py`**.

| View (inv. #) | Route | Method | Access | Behaviour |
|---|---|---|---|---|
| Editor ｜ preview (5.5/5.6–5.10) | `…/build/unit/<int:pk>/edit/` | GET | owner+PA | Two-pane editor for a unit; element list + live preview. |
| Element add | `…/build/element/add/` | POST | owner+PA | Open blank editor for a chosen type (materialise on first save). Returns editor fragment. |
| Element save | `…/build/element/save/` | POST | owner+PA | Validate + persist the selected element (create-on-first-save or update); returns editor + preview fragments. |
| Element move | `…/build/element/move/` | POST | owner+PA | **1b-i route, reused**; editor-context response = editor + preview fragments. |
| Element delete | `…/build/element/delete/` | POST | owner+PA | **1b-i route, reused**; editor-context response = editor + preview fragments. |
| Media manager (5.13) | `…/media/` | GET | owner+PA | Asset grid + upload + drop zone + guarded delete. |
| Media upload | `…/media/upload/` | POST | owner+PA | Create a `MediaAsset` (manager or picker); returns the new asset cell/JSON-ish fragment. |
| Media delete | `…/media/<int:pk>/delete/` | POST | owner+PA | Guarded: refuse if in use; else delete. |
| Picker (7.4) | `…/media/picker/` | GET | owner+PA | Library+Upload modal fragment, filtered by `?kind=`. |

**Editor page** = master (element list) ｜ detail-as-preview. Selecting a list row opens that element's
**inline form** (one at a time). The **"+ Add element"** control offers the 5-type picker. Every mutation
returns the re-rendered **editor pane** (`data-scope="editor"`) **and** the **preview** (`data-scope="preview"`)
so the JS swaps both. The student outline/lesson views from 1a are **untouched**; the editor reuses their
element templates for the preview.

---

## Editor & media mechanics

### Fragment protocol

- Element ops on the editor page return **two fragments**: `data-scope="editor"` (the list + any open inline
  form) and `data-scope="preview"` (the rendered unit). The JS swaps both by `data-scope` (the same
  `data-scope`-keyed swap idiom as 1b-i). The **unit's `updated`** rides on the editor fragment root as
  `data-updated` (the concurrency token for every element op).
- The **1b-i element-move/delete endpoints** detect editor context (a form field, e.g. `ctx=editor`, or a
  dedicated path) and return the editor+preview fragments instead of the unit-panel fragment; the **builder
  panel** path is retained for any remaining caller but the unit panel no longer renders interactive element
  controls, so in practice the editor context is the live one.

### Concurrency (reuse 1b-i verbatim)

- Every element mutation carries the **parent unit's** `updated` (ISO-8601). The view re-reads the unit
  in-txn; **token check first** → `409` (no write, no `clean()`, body = fresh editor+preview fragments, client
  swaps with a "this changed — refreshed" cue) on mismatch; else `clean()`/form validation → **`422`**
  (in-place form errors, no write); else **apply → `200`**. Every applied element op bumps the unit's
  `updated` (`save(update_fields=["updated"])`), so it is the conflict boundary. A **vanished element** (pk
  gone / not in this unit) → `409` + fresh fragment.
- **`MediaAsset` ops are outside the unit-token protocol** (they are course-library rows). **Upload** simply
  creates a row. **Delete** runs in a transaction that re-counts usage; **in-use → refused** (`409`/`422` with
  a message + the `PROTECT` FK as the DB backstop). Attaching an asset to an element is an **element save**,
  governed by the unit token as above; the save re-validates the asset's `course` matches the unit's course
  (→ `422`/404 on mismatch — cross-course guard).

### Live preview

The preview fragment renders the unit's elements **in order** through the **1a `courses/elements/*.html`
templates** — the identical code path students hit — so sanitisation, embed-whitelist, and KaTeX rendering
are reflected exactly. Preview refreshes **on every applied mutation** (`200`). KaTeX/JS in the preview is
(re-)initialised by the swap handler (same pattern 1a uses on the lesson page).

### The text toolbar (client convenience only)

A small vanilla-JS module wires toolbar buttons to formatting commands over a `contenteditable` region,
emitting HTML constrained to the `ALLOWED_TAGS`/`ALLOWED_ATTRIBUTES` set. On submit the HTML posts to
`element/save/` and the model's `save()` runs `sanitize_html` — **the server is the authority**; the toolbar
never gates security. No-JS: the field degrades to a `<textarea>` of raw HTML, still sanitised on save.

### Media picker & manager

- **Manager** (`…/media/`): grid of `course.media_assets`, each with thumbnail (image) or type glyph (video),
  filename, and **usage count**; an **Upload** button + **drop zone** (JS drag-drop posts to `…/media/upload/`,
  no-JS uses the file input); **delete** per unused asset (in-use shows a disabled/guarded control with the
  using-units tooltip).
- **Picker** (`…/media/picker/?kind=image|video`): the same library as a modal fragment with **Library** and
  **Upload** tabs. Library pick returns the asset id + a preview snippet into the element form's hidden
  `media` field; Upload creates the asset and auto-selects it. No-JS image/video editors fall back to a direct
  `<input type="file">` (upload-on-save) plus a `<select>` of existing `kind`-matched assets.

### No-JS fallback

Every route works as a full-page form POST: add opens the type form (full page), save persists + reloads the
editor page, reorder/delete are real submit buttons, the picker degrades to file-input + select, the manager's
drop zone degrades to the file input. The same token/precedence rules apply; a stale token re-renders the full
editor page with the "this changed" notice and discards the stale POST.

---

## Security, validation & i18n

- **Access:** `@login_required` + the canonical manage predicate on every route; object scoping mirrors 1a/1b-i
  (pk → exists 404 → course/slug pairing 404 IDOR guard → manage predicate 403). CSRF on all mutating
  endpoints. The editor route additionally requires the pk to be a **unit** (else 404).
- **Sanitisation & whitelists:** `sanitize_html` on text save (server authority); `validate_embed_url` on
  video/iframe save; `MediaAsset` uploads run the extension allowlist + size cap by `kind`; SVG excluded.
- **Cross-course / IDOR:** the picker lists only the current course's assets; element save re-validates the
  chosen asset's `course`; `PROTECT` FKs prevent deleting an in-use asset at the DB layer.
- **Invariants:** per-type `clean()` is the authority (image needs `media`; video XOR; iframe/math required
  fields). All writes via `full_clean()`/`save()`; no `bulk_create`/`update()`.
- **i18n:** new strings via `gettext`, EN + real Polish, compiled. Editor/manager/picker chrome in the UI
  language; author content untranslated.

---

## Out of scope (explicit)

- **HTML element / course-wide CSS/JS / per-unit JS / MathJax** — Phase **1b-iii** (own security spec; renders
  into this slice's preview pane unchanged).
- **Preview-as-student (5.14)** — the full untracked course walk-through; the editor's inline preview covers
  the authoring need. Deferred.
- **Quiz / question editors (5.12)** — Phase 2 (`quiz` unit_type selectable but inert, per 1a/1b-i).
- **Drag-and-drop element reordering** — button-based ↑/↓ ships now; DnD is later polish (DnD *for media
  upload* is in scope as a convenience over the file input).
- **Cross-course / global media library, asset folders/tags, image cropping/transforms** — per-course flat
  library only; richer media management deferred (YAGNI).
- **Course settings page (CSS/JS files, colour-band config)** — HTML slice / Phase 3.
- **DRF API for authoring** — server-rendered fragments only.

---

## Likely task decomposition (for the plan)

1. **`MediaAsset` model + schema migration + data migration** (port `seed_demo_course` embedded files; swap
   `ImageElement`/`VideoElement` to `media` FKs; update the two renderers) + model tests.
2. **Media services + manager page (5.13):** `courses/media.py` (create/usage-count/guarded-delete), the
   manager grid, upload, drop zone, guarded delete + tests.
3. **Picker modal (7.4):** library+upload fragment, `?kind=` filter, returns-to-form wiring, no-JS fallback +
   tests.
4. **Editor ｜ preview page shell:** route (unit-only, IDOR), two-pane layout, element-list render, preview via
   1a renderers, empty states; collapse the 1b-i unit panel list to read-only + activate the seam links.
5. **Element add + save services + the 5 per-type forms/editors** (text toolbar; image/video picker
   integration; iframe; math+KaTeX), the blank-create-on-first-save rule, `422` validation paths.
6. **Reuse + extend element reorder/delete** for the editor context (editor+preview fragment responses);
   vanished-element `409`.
7. **Optimistic-concurrency wiring** (unit token across add/save/move/delete; `409`/`422` contract; fresh
   fragments) + the asset-delete usage re-check.
8. **i18n** extraction + Polish + compile.
9. **`editor.js` + `media_picker.js`** (fragment swap, inline-editor selection, toolbar, drag-drop, KaTeX
   re-init) + no-JS fallbacks.
10. **Playwright e2e** + final DoD pass (`pytest`/`ruff`/`check`/`makemigrations --check`/`collectstatic`).
