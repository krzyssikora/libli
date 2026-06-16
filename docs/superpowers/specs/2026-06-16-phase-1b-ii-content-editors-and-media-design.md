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
   **"Reused" means *extended, not unchanged*:** the existing `element_move`/`element_delete` views (routes
   `courses:manage_element_move` / `courses:manage_element_delete`, both `POST … slug`) keep their unit-panel
   response path **and gain an editor-context branch** (selected by a posted `ctx=editor` flag) that returns
   the editor+preview fragments instead of `_render_unit_panel` (see Mechanics). The URL patterns themselves
   are unchanged; only the view bodies grow a response branch.

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
   **read-only summary** (no reorder/delete controls there). **Per-element summary label** (used in both the
   panel summary and the editor list, since elements have **no common title field**): **iframe** → its `title`
   (else url host); **image** → `alt` (else asset `original_filename`); **video** → asset `original_filename`
   (else url host); **text** → the body with **tags stripped, HTML entities decoded, whitespace collapsed**, then
   first ~60 chars; **math** → first ~60 chars of `latex`. Each falls back to the type name (e.g. "Text") when
   its source is empty. The label is **display chrome only** (truncation is cosmetic; never persisted).

2. **Add element** (`POST …/build/element/add/`, manage predicate, CSRF): a type picker offers the
   **5 types** (text/image/video/iframe/math). Choosing a type returns a **pending (unsaved) editor form** for
   that type — **no row is persisted yet**. The `add` route is therefore a **pure render**: no token check, no
   write, no atomic block. **All** concurrency and atomicity for a new element live in the *save* route (DoD #3,
   *Add transaction sequence*); wherever the plan says "token across add/save/move/delete," `add` is render-only
   and the token is checked at its first *save*. The pending form is identified by a **`new` sentinel** in place of
   an element pk and carries the chosen `type`; the editor list shows it as a transient "(unsaved <type>)" row
   with the inline form open. The transient `new` row shows **no ↑/↓/✕ controls** (it has no pk to reorder or
   delete server-side) — only a **client-only "discard"** that removes the pending form. **The add response
   embeds the unit's current `updated` token into the form's `unit_token` field** — the **same field name the
   reused 1b-i services and `_element_conflict` read** (and the same `updated.isoformat()` value emitted as
   `data-updated`); the pending-add JS serialises that `data-updated` into `unit_token` on submit. Without a
   correctly-named token field `_check_token` would treat it as `None` and spuriously `409`. The **first successful save**
   (DoD #3) materialises the concrete element **and** its 1a `Element` join-row (see *Add transaction sequence*
   in Mechanics), after which the row gains a real pk and behaves like any other. **Lifecycle of the pending
   form:** selecting a *different* list row, or reloading, **discards** the unsaved pending add (no row was
   created); a `422` validation failure **re-renders the pending form in place** (still keyed by `new`, fields
   echoed) so the author can fix and retry; a `409` (stale unit token) at save returns the **fresh editor
   fragment** with the pending form re-applied client-side by its `new` key, no write. **No-JS pending-add on
   `409`:** the full-page reload shows saved state and **drops the pending add's unsaved typed content** (no row
   existed) — an accepted, rare loss, not a correctness gap. (See Data model: *blank-create rule* for the
   persist-on-first-save rationale and the `is_incomplete`-marker fallback.)

3. **Edit / create element body** (`POST …/build/element/save/`, manage predicate, CSRF, atomic): saves an
   element's fields through a per-type Django `ModelForm` + `full_clean()`/`save()`. **Create-vs-update
   discriminator:** the POST carries `type` (one of the 5) and an `element` field that is either a real
   `Element` join-row pk (**update**) or the literal `new` sentinel (**create**, materialising the row per the
   *Add transaction sequence*). On success returns the re-rendered **editor pane + preview** fragments (`200`).
   Validation failure → **`422`** with the form re-rendered **in place** showing field errors (no write,
   preview unchanged; a pending `new` form re-renders still keyed `new`). Stale unit token → **`409`** + fresh
   editor fragment (no write). An **update** whose `element` pk no longer exists / no longer belongs to this
   unit → **`409`** (vanished). **Text** bodies pass through `sanitize_html` on save (model `save()` already
   does this); the returned preview shows the **sanitised** result.

4. **Element reorder / delete on the editor page** (reusing 1b-i `…/build/element/move/` +
   `…/build/element/delete/`): the editor pane's ↑/↓/✕ controls drive the **existing** endpoints; responses
   re-render the **editor pane + preview** (the editor page supplies its own fragment template; the endpoints
   gain an editor-context response path, see Mechanics). Delete cascades the concrete element + join-row (1a
   `GenericRelation`) and **gap-compacts** the unit's element scope. A **boundary reorder no-op** (top item "up"
   / bottom "down") writes nothing and bumps no token (per 1b-i rules) but in editor context still returns
   **`200` with the re-rendered editor+preview fragments carrying the *unchanged* `data-updated`** — so the
   client swap stays well-defined and the token does not desync. An op on a **vanished** element row → `409` +
   fresh editor fragment.

5. **The 5 element editors** (per-type forms, all server-validated):
   - **Text (5.6):** a bespoke vanilla-JS toolbar over `contenteditable` — Bold / Italic / Underline /
     H2 / H3 / H4 / bullet list / numbered list / Link / Blockquote / Code. These map to the
     `sanitize_html` `ALLOWED_TAGS` set; **"Code" emits inline `<code>`**. The sanitiser **also allows
     `<pre>`** (block preformatted), but the toolbar offers **no dedicated `<pre>` button** (deliberate
     minimalism) — a hand-authored / pasted `<pre>` block survives sanitisation and renders in the preview, so
     the no-JS textarea path is strictly a superset of the toolbar's capability, never a subset. Submits HTML;
     **server sanitises** via `sanitize_html`. With JS off, degrades to a plain `<textarea>` of the raw HTML
     (still sanitised on save).
   - **Image (5.7):** **"Choose media"** opens the picker (pick existing / upload) → sets the element's
     `media` FK; plus `alt` (blank = decorative, valid) and `figcaption`. **`media` is required** (the form
     marks it `required`; a save with no media selected — incl. the no-JS empty `<select>` — is rejected at the
     form layer as **`422`** *before* any DB write, never an `IntegrityError`/500). Preview renders
     `imageelement.html`.
   - **Video (5.8):** a radio choice — **Embed URL** (whitelisted, `validate_embed_url`) **or** **Uploaded
     video** (picker → `media` FK); the model's **XOR** (`url` ⊕ `media`) enforced in `clean()` → `422` on
     violation. Preview renders `videoelement.html`.
   - **Iframe (5.9):** whitelisted `url` (`validate_embed_url`) + optional `title`. Preview renders
     `iframeelement.html`.
   - **Math (5.10):** `latex` textarea. The **unit preview pane** follows the server-on-save rule (decision #4)
     via `mathelement.html`. The math editor *additionally* shows an **inline KaTeX preview that updates
     client-side as the author types** (debounced on `input`) — this is an **explicitly-permitted exception** to
     decision #4's "no client-side live render": KaTeX renders math notation, not author HTML, so there is **no
     sanitisation concern** and no risk of diverging from a server render (the same KaTeX runs in both). It is a
     pure typing convenience, not the source of truth.

6. **`MediaAsset` model + migration:** a new per-course asset model (image|video file + metadata);
   `ImageElement.image` → `media` FK; `VideoElement.file` → `media` FK (nullable; XOR with `url`); a **data
   migration** ports any existing embedded *image* file into a `MediaAsset` and re-points the FK (the
   `seed_demo_course` video is **url-only**, so no video file is ported — see Migration). The migration copies
   the storage *reference*, not bytes, so it is safe even when the seed image is absent on disk.
   `makemigrations --check` clean after (the new migrations are committed). `IframeElement`, `MathElement`,
   `TextElement` unchanged.

7. **Media manager page (5.13)** (`GET /manage/courses/<slug>/media/`, manage predicate): a grid of the
   course's `MediaAsset`s (thumbnail/type + filename + **usage count**), an **Upload** action and a
   **drag-and-drop** drop zone (JS; no-JS uses the file input), and **delete**. **Delete is guarded:** an
   in-use asset (referenced by ≥1 element) **cannot** be deleted — the server rejects it with **`409`** and a
   message naming the using units; only unused assets delete. The view first re-counts usage in-txn and refuses
   on >0; the `PROTECT` FK is the DB backstop, and the view **catches `django.db.models.ProtectedError` and maps
   it to the same `409`** so a concurrent attach can never surface as a 500. Uploads validate
   type/extension/size via the existing `FileExtensionValidator` + `validate_image_size`/`validate_video_size`.

8. **Picker modal (7.4)** (served as a fragment, invoked from image/video editors): the **same per-course
   library** as a modal with two tabs — **Library** (browse + pick an existing asset → returns its id/preview
   to the element form) and **Upload** (drag-drop/file input → creates a `MediaAsset` → auto-selects it). The
   picked asset id + its preview snippet populate the element form's hidden `media` field; **a subsequent `422`
   on the element save re-renders the form with the posted `media` id echoed back and its preview re-rendered**,
   so a validation error never drops the author's pick. No-JS fallback: the image/video editor offers a direct
   `<input type="file">` and a plain `<select>` of existing assets, so picking/uploading works without the modal.

9. **Access control & object scoping:** every `/manage/…` route here is `@login_required` + the canonical
   **manage predicate** (`course.owner_id == user.id OR user.has_perm("courses.change_course")`, `owner_id is
   not None` guard; no `is_staff`) — identical to 1b-i. Element/asset routes use the `<int:pk>` converter and
   check, in order: object exists (→404), **belongs to the URL's course** (→404, IDOR guard, before any 403),
   then the manage predicate (→403). A `MediaAsset` from another course can never be referenced by an element
   (the picker lists only this course's assets; the save view re-validates the posted `media` id resolves to an
   asset of **this** course **and of the matching `kind`** — an image element accepts only a `kind="image"`
   asset, video only `kind="video"`). A posted `media` id that is **cross-course, wrong-kind, or no longer
   exists** (e.g. a no-JS author on a stale page, or a crafted POST) is a **`422` form error on the `media`
   field** — the single chosen status for a bad posted FK value (404 is reserved for URL-addressed objects, not
   posted form values). `limit_choices_to={"kind":…}` is the no-JS `<select>` backstop for the same constraint.
   CSRF on every mutating endpoint.

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
    clobbering). **Migrate 1b-i element tests:** the existing `tests/test_manage_element_ops.py` and the 1b-i
    Playwright e2e assert the unit panel renders interactive ↑/↓/✕ and accepts POSTs *from the panel*; since the
    panel is now a **read-only summary** (decision #2), those assertions must be **retargeted** — the panel test
    now asserts a non-interactive summary, and the element reorder/delete endpoint coverage moves to the
    **editor context** (`ctx=editor` responses). The element-op endpoints themselves still pass their existing
    unit-panel-path tests (the path is retained), so this is a re-point of UI assertions, not a deletion of
    endpoint coverage.

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
  original_filename CharField(max_length=255)  (display-only; path-stripped basename of the upload)
  uploaded_by      FK(AUTH_USER_MODEL, null=True, on_delete=SET_NULL)
  created          DateTimeField(auto_now_add=True)
```

- **Per-course scope** = the owner/PA authoring boundary; the picker and manager only ever query
  `course.media_assets`. SVG remains **excluded** (XSS), consistent with 1a's image allowlist.
- **`kind`** lets the picker filter (image editor shows image assets; video editor shows video assets) and
  lets `validate_image_size` vs `validate_video_size` apply correctly. The `image`/`video` extension allowlists
  and size caps are the **existing** 1a validators, reused. The **no-JS `<select>`** queryset is
  `course.media_assets.filter(kind=…)` — the **same** filter `limit_choices_to={"kind":…}` enforces on the
  ModelForm, so the two cannot drift.
- **`original_filename`** is **non-blank, always populated**: the upload view/service sets it to the
  **path-stripped basename** of the client-supplied `uploaded_file.name` (untrusted → strip any path separators)
  **truncated to `max_length`**; the data migration sets it to the storage basename (see Migration). It is
  display-only.
- **Usage count** = the FK-equality predicate
  `ImageElement.objects.filter(media=asset).count() + VideoElement.objects.filter(media=asset).count()`
  (FK-equality inherently skips `media`-null / url-only videos — it is **not** "elements in the course"). The
  **in-txn guarded-delete re-check** uses exactly this predicate; the **manager grid aggregates the counts in
  bulk** (an annotated `Count` per asset, not a per-asset query) to avoid a 2N-query render — same predicate,
  batched for display.

### Altered: `ImageElement`

- `image = ImageField(...)` → **`media = FK(MediaAsset, on_delete=PROTECT, limit_choices_to={"kind":"image"})`**.
  `PROTECT` is the DB-level twin of the guarded delete (an in-use asset can't be deleted). `alt` + `figcaption`
  **unchanged** (stay on the element). The 1a `imageelement.html` renderer updates to read **`el.media.file.url`**
  (which does **not** hit disk), so an asset whose physical file is absent (a migrated fixture path) renders a
  broken `<img>` rather than raising — acceptable; the editor preview must not error on a missing-file asset.

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
  Instead it opens a **blank editor form** for the chosen type with **no element yet** (the pending `new` form,
  DoD #2); the **first successful save** creates the concrete element **and** the `Element` join-row together.
  Cancelling adds nothing. This removes the "incomplete row" state entirely and keeps every persisted element
  valid by construction.
- **Add transaction sequence (exact, load-bearing).** Because `Element.unit` and `Element.order` are both
  NOT NULL and `order` is computed at `save()` time within the `for_fields=["unit"]` scope, a `new`-save runs
  **inside one `transaction.atomic()` with `select_for_update()` on the unit**, in this order: (1) re-read the
  unit + **token check** (stale → `409`, no write); (2) build the concrete element from the validated form and
  `full_clean()` → `save()` it (now it has a pk / `object_id`); (3) `Element.objects.create(unit=unit,
  content_object=obj)` — the `OrderField` appends it at the end of the unit's scope; (4) bump the unit
  (`unit.save(update_fields=["updated"])`). **Atomicity guarantee:** any validation failure (step 2's
  `full_clean`) raises **before** step 3, and the surrounding transaction rolls back, so a failed create leaves
  **zero rows** — never an orphan concrete element without a join-row. *(The DoD's "add then edit" holds
  end-to-end; the row simply materialises on first save. The plan picks this realisation unless a blocker
  emerges, in which case the `is_incomplete`-marker fallback above applies.)*

### Migration

A schema migration (the field swaps + new model) **plus** a **data migration**. **What actually exists to
port (verified against `seed_demo_course`):** the only `VideoElement` is created with **`url=` (an embed, no
uploaded file)** — so **no video file is ported**; its `url` stays on the element and `media` is left null.
The only `ImageElement` carries **`image="courses/images/demo.png"` — a storage *path string*, which may not
correspond to a real file on disk** in a fresh checkout / CI. The data migration therefore:

- For each `ImageElement` whose old `image` field is non-empty: create a `MediaAsset` (`course` = the owning
  unit's course, `kind="image"`, **`file` set to the existing FieldFile's stored `name`/path — it copies the
  reference, not the bytes**, so a physically-absent file does **not** break the migration), `original_filename`
  = the **storage basename** (no true "uploaded name" exists for migrated rows — acceptable for display, see
  below), then set the new `media` FK and clear the old column.
- `VideoElement` rows with a `url` are untouched (no `media`); a `VideoElement` with an uploaded `file` would be
  ported the same way as images, but **none exists in the seed** (documented so the DoD does not overstate).

Old file columns are removed after the copy. The migration **does not read file bytes** (so it is CI-safe even
when the referenced file is absent). **It is explicitly one-way / irreversible:** the schema migration drops
`ImageElement.image` / `VideoElement.file`, so the original column values are gone — the data migration's
`RunPython` uses **`reverse_code=migrations.RunPython.noop`** (the forward data copy is not undone; reversing
the *schema* would re-add empty file columns, accepted as a dev-only escape hatch, not a true round-trip).
Committed so `makemigrations --check` stays clean. **`original_filename` semantics:** for migrated rows it is
the storage-path basename (e.g. `demo.png`), a display-only label, since no genuine upload name is recoverable.

---

## Views, routes & layout

All under the existing `app_name = "courses"`, `/manage/` prefix, in `courses/views_manage.py` (editor +
element ops) and a new **`courses/views_media.py`** (asset manager + picker + upload), keeping files focused.
Element-op **services** extend `courses/builder.py`; asset services live in a new **`courses/media.py`**.
*(The parenthesised view numbers — 5.5/5.6–5.10, 5.13, 7.4 — are from [view-inventory.md](../../view-inventory.md);
the plan should re-confirm each label against the inventory before building, in case the inventory has drifted.)*

| View (inv. #) | Route | Method | Access | Behaviour |
|---|---|---|---|---|
| Editor ｜ preview (5.5/5.6–5.10) | `…/build/unit/<int:pk>/edit/` | GET | owner+PA | Two-pane editor for a unit; element list + live preview. |
| Element add | `…/build/element/add/` | POST | owner+PA | **Render-only** (no token check, no write): returns the pending `new` editor form for the chosen type. |
| Element save | `…/build/element/save/` | POST | owner+PA | Validate + persist the selected element (create-on-first-save or update); returns editor + preview fragments. |
| Element move | `…/build/element/move/` (`courses:manage_element_move`) | POST | owner+PA | **1b-i route, view extended**: `ctx=editor` branch returns editor + preview fragments; unit-panel path retained. |
| Element delete | `…/build/element/delete/` (`courses:manage_element_delete`) | POST | owner+PA | **1b-i route, view extended**: `ctx=editor` branch returns editor + preview fragments; unit-panel path retained. |
| Media manager (5.13) | `…/media/` | GET | owner+PA | Asset grid + upload + drop zone + guarded delete. |
| Media upload | `…/media/upload/` | POST | owner+PA | Create a `MediaAsset`; returns an **HTML asset-cell fragment** whose root carries `data-asset-id` + a thumbnail/preview. Single format for both callers: the manager appends the cell to its grid; the picker JS reads `data-asset-id` to fill the element form's hidden `media` field and auto-select. |
| Media delete | `…/media/<int:pk>/delete/` | POST | owner+PA | Guarded: refuse if in use; else delete. |
| Picker (7.4) | `…/media/picker/` | GET | owner+PA | Library+Upload modal fragment, filtered by `?kind=`. |

**Editor page** = master (element list) ｜ detail-as-preview. Selecting a list row opens that element's
**inline form** (one at a time). **Switching rows away from an open form with unsaved edits** (an existing
element's dirty form, or the pending `new` form) **silently discards** those edits — consistent with the
per-operation atomic model (nothing is persisted until an explicit save); `editor.js` **may** show a client
"discard unsaved changes?" confirm when it detects a dirty form (a nice-to-have, not required for correctness).
The **"+ Add element"** control offers the 5-type picker. Every mutation returns the re-rendered **editor
pane** (`data-scope="editor"`) **and** the **preview** (`data-scope="preview"`) so the JS swaps both. The student outline/lesson views from 1a are **untouched**; the editor reuses their
element templates for the preview.

---

## Editor & media mechanics

### Fragment protocol

- Element ops on the editor page return **two fragments**: `data-scope="editor"` (the list + any open inline
  form) and `data-scope="preview"` (the rendered unit). The JS swaps both by `data-scope` (the same
  `data-scope`-keyed swap idiom as 1b-i). The **unit's `updated`** rides on the editor fragment root as
  `data-updated` (the concurrency token for every element op). **Swap contract (mirrors `builder.js`
  verbatim):** the client `fetch`es the route with `X-Requested-With` / a `ctx=editor` field and
  `X-CSRFToken` from the form's hidden CSRF input, reads the response status, and on `200`/`409`/`422` replaces
  the in-DOM element whose `data-scope` matches each returned fragment root (a `200` swaps both editor+preview;
  a `409`/`422` swaps the editor fragment and surfaces the notice/errors). `editor.js` reuses this exact idiom
  — selector = `[data-scope="…"]`, status routing, CSRF header — rather than re-inventing it.
- **Shared editor-fragment renderer.** A new helper — call it `_render_editor_fragments(unit, …)`, built in
  task 4 — renders the `data-scope="editor"` + `data-scope="preview"` pair and is the **single source** for the
  editor-context `200`/`409`/`422` responses of **every** element op (add, save, move, delete, and the conflict
  path). It always serialises `data-updated` from the **freshly in-txn-read `unit.updated`** (not a value
  carried from the request), so even a no-op reorder (which doesn't bump the token) ships the *live* current
  token, and an applied op ships the bumped one — the token can never desync from the row. Concretely: the
  editor-context views **re-read the unit row in-txn** before calling the helper (the existing
  `reorder_element`/`delete_element` services return a `unit`, but the no-op branch may return the pre-read
  object, so the view re-reads `unit.updated` to guarantee the emitted token is the committed one).
- **Two independent routing axes (resolve the `ctx=editor` vs `_wants_fragment` collision explicitly).** 1b-i's
  element views decide JS-vs-no-JS on `_wants_fragment(request)` (the `X-Requested-With: fetch` header) and, when
  it is absent, `redirect("courses:manage_builder")`. This slice adds an **orthogonal** `ctx=editor` POST flag
  that selects the *renderer* (editor vs unit-panel). The two axes are **independent and both honored**:
  (a) **`X-Requested-With: fetch`** (set by `editor.js`) → fragment response; **absent** (no-JS full-page POST)
  → a redirect; (b) **`ctx=editor`** → use `_render_editor_fragments` (fragment path) **or** redirect to the
  **editor route `…/unit/<pk>/edit/`** (no-JS path) — **not** the builder. So the existing
  `redirect(manage_builder)` branch becomes ctx-aware: `ctx=editor` redirects back to the editor page, otherwise
  the 1b-i builder redirect stands. This makes the spec's "no-JS … reloads the editor page" reachable.
- **Token field name.** Every editor element form (add's pending form, save, move, delete) posts the unit token
  under the field name **`unit_token`** — the exact name the reused 1b-i services and `_element_conflict`
  already read — and posts the unit id under **`unit`**. (Stated once here so all four ops agree; a differently
  named token field would make `_check_token` see `None` and spuriously `409`.)
- The **1b-i element-move/delete views** detect editor context via `ctx=editor` and call
  `_render_editor_fragments` instead of `_render_unit_panel`. The unit-panel path is **retained but its template
  is now the read-only summary** (decision #2) — so that path returns the *summary* fragment, not the old
  interactive one; its only real remaining caller is the no-JS/legacy redirect, and its tests assert the summary
  (matching the DoD #14 retarget — there is no "still-interactive panel" path). **The conflict path is
  editor-context-aware too:** the existing `_element_conflict` (which today returns the unit-panel fragment)
  branches on `ctx=editor` to call `_render_editor_fragments`, recovering the unit from the **`unit` POST
  field** (every editor element form posts `unit`) so a `409`/vanished-row response swaps in editor fragments —
  never a stray unit-panel fragment.

### Concurrency (reuse 1b-i verbatim)

- Every element mutation carries the **parent unit's** `updated` token. **Token serialisation/compare reuses
  1b-i's exact helper verbatim** — the value is `unit.updated.isoformat()` emitted into `data-updated`, and the
  view compares via `builder.py`'s existing `_check_token` (`django.utils.dateparse.parse_datetime` of the
  posted token vs the re-read row's `updated`). This slice **does not re-derive its own ISO-8601 formatting**,
  so there is no microsecond/timezone-suffix drift that could spuriously `409`. The view re-reads the unit
  in-txn; **token check first** → `409` (no write, no `clean()`, body = fresh editor+preview fragments, client
  swaps with a "this changed — refreshed" cue) on mismatch; else `clean()`/form validation → **`422`**
  (in-place form errors, no write); else **apply → `200`**. Every applied element op bumps the unit's
  `updated` (`save(update_fields=["updated"])`), so it is the conflict boundary. A **vanished element** (pk
  gone / not in this unit) → `409` + fresh fragment.
- **`MediaAsset` ops are outside the unit-token protocol** (they are course-library rows). **Upload** simply
  creates a row. **Delete** runs in a transaction that re-counts usage; **in-use → refused with `409`** (the
  single chosen status for an in-use delete) and a message naming the using units. The `PROTECT` FK is the DB
  backstop for the narrow window where an element save attaches the asset concurrently; the delete view
  **catches `django.db.models.ProtectedError` and maps it to the same `409`**, so the backstop never surfaces
  as a 500. Attaching an asset to an element is an **element save**, governed by the unit token as above; the
  save re-validates the posted `media` id resolves to an asset of this course (→ **`422`** form error on a
  cross-course or vanished id, per DoD #9 — the single chosen status for a bad posted FK value).

### Live preview

The preview fragment renders the unit's elements **in order** through the **1a `courses/elements/*.html`
templates** — the identical code path students hit — so sanitisation, embed-whitelist, and KaTeX rendering
are reflected exactly. Preview refreshes **on every applied mutation** (`200`). KaTeX in the swapped-in
preview must be re-initialised by the swap handler. **Concrete refactor (1a's `math.js` today does a
whole-document `document.querySelectorAll("[data-katex]")` on load):** parameterise its renderer to **accept a
root element (default `document`)** and query `root.querySelectorAll("[data-katex]")`; the swap handler calls
it with **only the just-swapped preview subtree**. This avoids re-rendering already-rendered nodes elsewhere on
the page — in particular the math editor's *own* inline live-KaTeX preview must **not** be re-scanned by a
preview swap (double-`katex.render` into an already-rendered element double-wraps). **The exclusion is
structural, not just asserted:** the math editor's inline KaTeX element lives **inside the
`data-scope="editor"` fragment** (the editor pane), which is a sibling of — never nested within — the
`data-scope="preview"` subtree; since the preview-swap re-scan is rooted at the preview subtree, it
**structurally cannot reach** the editor's inline KaTeX. This `math.js` refactor is an explicit task; the 1a
lesson-page call site passes no root and keeps its whole-document behaviour.

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
