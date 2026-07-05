# Course export / import — design

**Date:** 2026-07-05
**Status:** Approved in brainstorming; pending spec review
**Depends on:** nothing new — no model changes, no migration

## 1. Goal

Let a course author build and test a course on one instance (local, staging) and move it
to another (prod) as a file. Export a whole course — or a subtree of it (part / chapter /
section / unit) — to a zip archive; import that archive on the target instance.

Explicitly a **content** transfer: structure and elements travel; people and their data
(owner, enrollments, progress, results, notes, tags, groups, cohort scoping) never do.

### Decisions made during brainstorming

| Question | Decision |
| --- | --- |
| Re-import of an already-imported course | **Always create new** (slug suffixed on collision). No update-in-place in v1. |
| Where a partial (subtree) import lands | **Into an existing course**, at a user-chosen insertion point. |
| Permissions | **Same as course authoring**: export needs edit rights on the course; full import needs course-create rights; subtree import needs edit rights on the target course. No new permission concept. |
| Instance-local references (subjects, cohorts, owner) | **Match subjects by name, else drop** (reported in preview). Cohort scoping and visibility reset to defaults; importer becomes owner. |
| Mechanism | **Bespoke versioned JSON in a zip** (approach A). Not `dumpdata`/`loaddata`, not natural keys. |
| Media in a full-course export | **Referenced-only** — assets in the course library not referenced by any exported element do not travel. |
| Oversized archives | Caps are deployment settings, not product limits; fail early with the configured limit named. Future "without media files" export option is format-compatible but out of scope. |

## 2. Archive format

A `.zip` (suggested filename `<course-slug>-export-<date>.zip`, or
`<course-slug>-<node-segment>-export-<date>.zip` for subtrees, where
`<node-segment>` is `slugify(node.title)` with fallback `content` when the title
slugifies to empty — ContentNode has no slug field; via the existing
`build_filename` helper pattern; content-detected, never name-detected):

```
manifest.json      format_version, kind, exported_at, source info, display metadata
course.json        the content graph
media/<id>.<ext>   one file per referenced MediaAsset, named by internal id
```

### 2.1 `manifest.json`

```json
{
  "format_version": 1,
  "kind": "course",                       // or "subtree"
  "exported_at": "2026-07-05T12:00:00Z",
  "source": {"instance": "<institution name>", "app_version": "<informational>"},
  "course": {"title": "…", "slug": "…"},  // display-only, shown at preview
  "media_total_bytes": 123456789          // checked before extraction
}
```

`source` is informational only — import never trusts or branches on it.

### 2.2 `course.json` — internal ids, no pks

Every object gets an **internal string id** assigned at export (`"n1"`, `"e4"`, `"m2"`…).
Database pks and content-type ids never leave the instance. Cross-references inside the
document use these ids only.

```json
{
  "course": {
    "title": "…", "language": "en", "overview": "…",
    "html_css": "…", "html_js": "…",
    "uses_parts": true, "uses_chapters": true, "uses_sections": true,
    "color_bands": [...],
    "subjects": [{"title_en": "Mathematics", "title_pl": "Matematyka"}]
  },
  "nodes": [
    {"id": "n1", "parent": null, "kind": "part", "title": "…",
     "unit_type": null, "obligatory": null, "html_seed_js": ""}
  ],
  "elements": [
    {"id": "e1", "unit": "n7", "title": "", "type": "choice", "data": {…}}
  ],
  "media": [
    {"id": "m1", "kind": "image", "name": "…", "original_filename": "…",
     "file": "media/m1.png"}
  ]
}
```

- `nodes` and `elements` are listed **in tree/slot order**; import recreates them in
  sequence and lets `OrderField` re-seed order values (relative order preserved; exported
  `order` values are not carried — sequence position is the order).
- For `kind: "subtree"`, `course` is replaced by a `context` block:
  `{"source_course_title", "root_kind", "required_kinds": ["chapter","section","unit"],
  "html_css", "html_js"}`. The sandbox CSS/JS is **informational only** (shown at preview
  when the subtree contains HTML elements — they may depend on it) and is **never applied**
  to the target course; the target's own sandbox config governs rendering.
- Decimal fields (`max_marks`, numeric `value`, `tolerance`) serialize as **strings** to
  avoid float precision loss.

### 2.3 Element `type` registry and `data` payloads

One `type` string per concrete element model — **enumerated from the actual `ElementBase`
subclasses, not the stale `ELEMENT_MODELS` list** (which is missing the 4 newest types).
14 types.

The stale `ELEMENT_MODELS` list is **extended to all 14 models** as part of this work:
`Element.content_type` carries `limit_choices_to={"model__in": ELEMENT_MODELS}`, which
`full_clean()` enforces — without the fix, importing (or admin-editing) the 4 newest
types would fail validation. This changes only `limit_choices_to`, producing a
**state-only no-op migration** (no schema change).

| `type` | Model | `data` fields (child rows inline, in order) |
| --- | --- | --- |
| `text` | TextElement | `body` |
| `image` | ImageElement | `media` (id), `alt`, `figcaption` |
| `video` | VideoElement | `url` XOR `media` (id) |
| `iframe` | IframeElement | `url`, `title` |
| `math` | MathElement | `latex` |
| `html` | HtmlElement | `html` (raw by design — see §6) |
| `choice` | ChoiceQuestionElement | shared question fields + `multiple`, `choices: [{text, is_correct}]` |
| `short_text` | ShortTextQuestionElement | + `accepted`, `case_sensitive` |
| `extended_response` | ExtendedResponseQuestionElement | + `required_keywords`, `forbidden_keywords` |
| `short_numeric` | ShortNumericQuestionElement | + `value`, `tolerance` |
| `fill_blank` | FillBlankQuestionElement | + `blanks: [{accepted, case_sensitive}]` |
| `drag_fill_blank` | DragFillBlankQuestionElement | + `distractors`, `blanks: [{correct_token}]` |
| `match_pair` | MatchPairQuestionElement | + `distractors`, `pairs: [{left, right}]` |
| `drag_to_image` | DragToImageQuestionElement | + `media` (id), `alt`, `distractors`, `zones: [{correct_label, x, y, w, h}]` |

Shared question fields: `stem`, `explanation`, `marking_mode`, `max_attempts`, `max_marks`.

An unknown `type` at import → reject, naming the type (the "export from a newer app
version" case).

### 2.4 What never travels

`owner`, `uploaded_by`, `visibility`, `self_enroll_cohorts`, `external_id`, and all
student-side data (Enrollment, UnitProgress, QuizSubmission, QuestionResponse, Attempt,
notes, tags, groups, collections). Import always resets: `visibility="assigned"`, no
cohorts, no `external_id`, owner = importer, `uploaded_by` = importer.

### 2.5 Versioning

`format_version` starts at 1. Import refuses versions **newer** than it knows; older
versions are upgraded in code as the format evolves. A future "media omitted" export sets
`omitted: true` on media entries under a bumped version.

## 3. Export flow

- **Full course:** an **Export** action on the course's builder/manage page, gated by the
  same permission predicate as course editing.
- **Subtree:** an "Export subtree" action on each part/chapter/section/unit row in the
  builder (a unit is just the smallest subtree).
- Plain GET; the archive is **built fully in a temp spool, then streamed** — a mid-build
  failure returns an error response, never a truncated zip. No background jobs in v1
  (same in-request model as the gradebook export).
- Serialization walks the tree in order and collects **only MediaAssets referenced by an
  exported element** (via `courses/media.py:_MEDIA_REF_MODELS` relations: ImageElement,
  VideoElement, DragToImageQuestionElement).

## 4. Import flow

### 4.1 Entry points

- **Full course:** **Import course** button on `/manage/courses/`, visible with
  course-create rights.
- **Each entry point accepts only its matching `kind`** (`course` at Import course,
  `subtree` at Import content); the other is rejected with a specific, translated message
  pointing at the correct entry point.
- **Subtree:** **Import content** action on the target course's builder page, requiring
  edit rights on that course. The user picks an **insertion point** on the
  **preview/confirm page** (it can only be computed after parsing — legal choices depend
  on the subtree's `root_kind`): a parent node (or top level) whose kind may legally
  contain the subtree's root kind under the target course's
  `uses_parts/chapters/sections` flags. If the subtree requires a kind the target does not
  use, the preview **rejects with a clear message** — content is never silently reshaped.
  The subtree is appended at the end of the chosen parent's children.

### 4.2 Two-step: preview, then confirm

1. **Upload & preview** — parse and fully validate (see §5) **without writing any model
   rows**; show: course/subtree title, node/element/media counts, total media size, source
   info, subjects matched vs. dropped, and (for subtrees containing HTML elements) the
   source sandbox CSS/JS note.
2. **Confirm** — the import proper (§4.4). Confirm **re-runs the full §5 validation, the
   permission predicate, and (for subtrees) insertion-point existence/legality against
   the current database state** before committing — the staged file can sit for hours,
   during which the insertion node may be deleted, depth flags or embed/media limits may
   change, or the user may lose rights. A now-invalid staged import fails with the same
   specific messages as at preview.

### 4.3 Staging between preview and confirm

The uploaded zip is staged server-side under a dedicated directory
(`transfer_staging/<random-token>.zip`) that is **not web-served** (outside
`MEDIA_ROOT`/any public storage — a leaked token must not make the archive fetchable),
keyed by a random token bound to the uploading user (token in the confirm form;
ownership checked on confirm). Deleted on confirm or cancel; stale files older than
`TRANSFER_STAGING_MAX_AGE_HOURS` (settings constant, default **6**) are swept
opportunistically when the next staging write happens — no cron needed.

### 4.4 Commit semantics

One **database transaction**.

**Full course:**

- Create the Course with reset instance-local fields (§2.4). The **slug is regenerated
  from the imported title via the existing `unique_course_slug` helper**
  (`slugify(title)` + smallest free `-2`, `-3`… suffix) — never taken from the archive;
  the manifest slug is display-only.
- Recreate ContentNode tree, Element join-rows (resolving the GFK by `type` string), and
  question sub-rows, in exported sequence.
- Save each media file **through the existing upload validators** into MediaAsset
  (Django storage de-duplicates filenames itself — no collision handling needed).
- Attach matched subjects. Matching is **language-aligned, exact, case-insensitive**:
  exported `title_en` against target `title_en`, exported `title_pl` against target
  `title_pl`; a match on either language attaches. If more than one target Subject
  matches, attach the first by the model's default ordering (deterministic); unmatched
  are dropped (both already reported at preview).
- Re-run model validation/sanitizers on save exactly as if authored in the builder
  (see §6).

**Subtree (differences):** no Course row and no subject/slug/visibility steps (subtree
documents carry none of those); the root node's `parent` is remapped to the chosen
insertion point (or top level) and appended at the end of its children; descendant nodes,
elements, and question sub-rows recreate exactly as above; MediaAssets are created **in
the target course's library** with `uploaded_by` = importer.

Files are written to storage during the transaction; on rollback, the error handler
**best-effort deletes** any media files already written (orphan cleanup).

All-or-nothing: any failure aborts the whole import; no partial course ever exists.

## 5. Validation (all before any model write)

**Archive level:**

- Compressed size cap: **1 GiB** (settings constant).
- Uncompressed total cap: **1.5 GiB** (settings constant) — checked against declared
  entry sizes **before extraction**; extraction then reads every entry through a
  **counting wrapper** that aborts if actual bytes exceed the declared size (zip-bomb
  guard; lying headers cannot bypass the cap). `media_total_bytes` from the manifest gives
  an even earlier, friendlier rejection.
- `course.json` size cap: **10 MiB** (parsed into memory in one piece).
- Entry allowlist: only `manifest.json`, `course.json`, and flat `media/*` names; any
  path traversal (`../`, absolute paths, nested dirs) → reject.
- `format_version` known (§2.5).
- `kind` matches the entry point (§4.1): `course` at Import course, `subtree` at Import
  content; mismatch → reject, pointing at the correct entry point.

**Document level:**

- Schema check: required keys, known `type` values, internal id references resolve
  (element→unit, element→media, node→parent), element `unit` refs must point at a node
  with `kind: "unit"`, node kinds nest legally (strictly deeper than parent).
- Depth-flag consistency: for `kind: "course"`, every node's kind must be in the set
  allowed by the **archive's own** `uses_*` flags (via `kinds_for_flags`) — a crafted
  document must not create a course the builder could never author. For `kind:
  "subtree"`, every node's kind must fit the **target course's** depth flags.
- Subtree shape: exactly **one** node with `parent: null`, whose kind equals
  `context.root_kind`; zero or multiple roots → reject. (Course documents may have any
  number of top-level nodes.)
- `color_bands` validated with the existing stored-shape validator
  (`courses/color_bands.py`); invalid shape → reject (consistent with fail-early — no
  silent normalization).
- Embed URLs (`video.url`, `iframe.url`) re-validated against the **target's**
  `ALLOWED_EMBED_DOMAINS`; a URL allowed at the source but not the target rejects the
  import, naming the URL.

**Media level:**

- Each file re-validated with the existing extension/size validators (5 MiB image /
  200 MiB video, admin-narrowable via platform settings). Any failure rejects the whole
  import, naming the file and rule.

All rejection messages are specific and translated (EN/PL).

**Deployment note:** a 1 GiB multipart upload hits web-server/proxy body limits (e.g.
nginx `client_max_body_size`) before the app-level cap. Deployment docs must state that
the proxy limit on the import endpoint must admit the configured compressed cap; where
feasible, a body-too-large failure gets a friendly error rather than a bare proxy page.

## 6. Security posture

- Importing requires course-authoring rights — the same people who can already type raw
  HTML into the builder. Import therefore grants **no new capability**, provided every
  input passes the same gates as the builder:
  - sanitized fields (`body`, `stem`, `explanation`) re-run through the existing
    sanitizers on save;
  - `HtmlElement.html` stays raw **by design** (sandboxed at render, same trust level as
    authoring);
  - media through the existing upload validators; embeds through the embed whitelist.
- No pickle, no code execution, no trusting manifest metadata. JSON parsing only.
- Zip handling hardened per §5 (traversal, bombs, caps).
- Staged archives live outside any web-served directory and are token+owner gated (§4.3).

## 7. Code layout (proposed; plan finalizes)

- `courses/transfer/` package: `schema.py` (format constants, type registry, document
  validation), `export.py` (graph walk → zip), `importer.py` (validate → preview data →
  commit).
- Views in `courses/views_transfer.py` (pattern of `views_export.py`), URLs under the
  existing manage/builder namespaces:
  `…/export/` (course), `…/nodes/<id>/export/` (subtree),
  `/manage/courses/import/` (full), `…/import-content/` (subtree).
- Templates: import upload form + preview/confirm page, styled per house rules (no bare
  HTML), EN/PL strings.
- **No schema changes.** The one model-file touch is extending `ELEMENT_MODELS` to all
  14 element models (§2.3), which yields a state-only no-op migration
  (`limit_choices_to` only — no DB change).

## 8. Error handling summary

Fail early (preview) wherever possible; commit failures roll back the DB and best-effort
clean written files. Every error names its reason: bad zip structure, unsupported
format version, unknown element type (with name), size cap (with configured limit),
archive kind at the wrong entry point (pointing at the right one), structure-depth
incompatibility (with offending kind), media validation failure (file + rule), embed
domain rejection (URL). Export's only failure mode is a clean error response
(archive spooled before streaming).

## 9. Testing

- **Round-trip:** build a course exercising **all 14 element types** (incl. every question
  sub-table and media on image/video/drag-to-image), export → import into the same test DB,
  assert the new course's content graph is field-for-field equal (excluding pks, owner,
  slug suffix, order re-seeding). Same for a subtree round-trip into a target course.
- **Sanitizer/validator re-entry:** crafted zip with a script tag in a text body imports
  with it stripped; oversized / wrong-extension media rejects the whole import.
- **Hostile zips:** path traversal entries, lying uncompressed sizes (bomb), oversized
  `course.json`, unknown element type, dangling internal ids, illegal nesting — each
  rejected with the right message, nothing written (assert no Course/ContentNode/media
  rows or files created).
- **Collision & matching:** slug `-2` suffixing; subject match by either-language title,
  case-insensitive; unmatched reported at preview and dropped.
- **Permissions:** export requires course edit; full import requires course create;
  subtree import requires edit on the target course.
- **Structure compatibility:** subtree requiring `part` into a chapters-only course →
  rejected at preview; full-course archive whose nodes contradict its own `uses_*` flags
  → rejected; wrong `kind` at each entry point → rejected with the pointer message.
- **Staging lifecycle:** confirm with another user's token → rejected; second confirm
  with a consumed token → clean failure, no double import; stale staged files swept on
  the next staging write; confirm re-validation catches a deleted insertion node /
  changed depth flags between preview and confirm.
- **e2e (Playwright, real gestures):** export a seeded course via the real button; import
  the downloaded zip through the real upload → preview → confirm flow; the new course
  appears in the manage list.

## 10. Out of scope (v1)

- Update-in-place / re-import merging.
- "Without media files" export (format-compatible future option).
- Background/async export or import jobs.
- Transferring student data, enrollments, groups, notes, tags, results.
- UI-configurable size caps (settings constants only).
