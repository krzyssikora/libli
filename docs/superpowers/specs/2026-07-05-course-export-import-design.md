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

For `kind: "subtree"`, the manifest's `course` block still carries the **source** course's
title/slug, plus a `node: {"title", "kind"}` display block for the exported root; the
preview's title comes from the manifest (display-only — the document is authoritative).

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
     "unit_type": null, "obligatory": true, "html_seed_js": ""}
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
- Fill-blank / drag-fill `data.stem` carries the **stored sentinel token-stem verbatim**
  (`￿0￿`, `￿1￿`… — `courses/fillblank.py` SENTINEL), not the `{{answer}}` authoring
  markup. §5 validates token exactness.
- `obligatory` is a **required boolean** on every node (meaningful only for units, but
  always a bool — the model field is non-nullable `BooleanField(default=True)`).
- `context.required_kinds` is written by export as the distinct kinds present in `nodes`
  and is **informational only** at import — validation always recomputes from `nodes`.

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
  `uses_parts/chapters/sections` flags. The insertion node is **looked up scoped to the
  target course** (`course=target`) — a forged node id from another course is rejected,
  never written to. If the subtree requires a kind the target does not use, the preview
  **rejects with a clear message** — content is never silently reshaped. The subtree is
  appended at the end of the chosen parent's children.

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
ownership checked on confirm). Order is **stage → validate**: a failed preview deletes
the staged file immediately (a rejected 1 GiB archive must not sit until the sweep).
Confirm **claims the staged file atomically** (rename/move-on-claim, then import from
the claimed handle) so two simultaneous confirm POSTs with the same token cannot both
proceed — exactly one imports, the other gets the expired/not-found message. Deleted on
confirm or cancel; stale files older than
`TRANSFER_STAGING_MAX_AGE_HOURS` (settings constant, default **6**) are swept
opportunistically when the next staging write happens — no cron needed.

Confirming with an expired, swept, or unknown token fails with a specific message
("staged upload expired or not found — upload again"). **Deployment note:** the staging
directory must be on storage shared by all app processes/hosts (multi-host deployments
behind a load balancer would otherwise stage on one host and confirm on another).

### 4.4 Commit semantics

One **database transaction**.

**Full course:**

- Create the Course with reset instance-local fields (§2.4). The **slug is regenerated
  from the imported title via the existing `unique_course_slug` helper**
  (`slugify(title)` + smallest free `-2`, `-3`… suffix) — never taken from the archive;
  the manifest slug is display-only.
- Recreate ContentNode tree, Element join-rows (resolving the GFK by `type` string), and
  question sub-rows, in exported sequence.
- Save each media file via `courses.media.create_asset` (or equivalent: `full_clean`
  runs on the **not-yet-committed** file object before save — `_validate_file` skips
  committed FieldFiles, so a write-first-validate-later order would silently bypass the
  extension/size gates). The stored filename is the archive's `original_filename`
  (path-stripped/truncated), and validation runs against that name; the `media/m1.png`
  entry name is an id-keyed locator only. Django storage de-duplicates stored names
  itself — no collision handling needed.
- Attach matched subjects. Matching is **language-aligned, exact, case-insensitive**:
  exported `title_en` against target `title_en`, exported `title_pl` against target
  `title_pl`; a match on either language attaches — but a language leg participates
  **only when both sides are non-empty** (`title_pl` is optional; empty-vs-empty is
  never a match, else every blank-PL subject would cross-match). If more than one target
  Subject matches, attach the first ordered by `("title_en", "pk")` — the model's
  default ordering alone (`["title_en"]`) is database-arbitrary among case-variant ties;
  unmatched are dropped (both already reported at preview).
- **Every created row passes `full_clean()` before save** — Course, ContentNode,
  Element join-row, each concrete element, every question child row
  (Choice/Blank/DragBlank/MatchPair/DragZone), and MediaAsset. The builder reaches
  these via `ModelForm._post_clean` per row; several security-relevant invariants live
  **only** there: DragZone bounds (0..1, no overflow), VideoElement url-XOR-media +
  embed check, ContentNode unit_type/kind rules, FK `limit_choices_to` (media kind per
  element type; `Element.content_type` in `ELEMENT_MODELS`), `max_marks`
  MinValueValidator, field max_lengths. Bulk-create without `full_clean` would silently
  skip all of them. Sanitizers run on save as usual (see §6).

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
- `course.json` size cap: **10 MiB**; `manifest.json` size cap: **64 KiB** (both parsed
  into memory in one piece; both settings constants).
- Duplicate entry names inside the zip → reject (zipfile surfaces the last duplicate,
  enabling parse-one-validate-the-other tricks).
- Entry allowlist: only `manifest.json`, `course.json`, and flat `media/*` names; any
  path traversal (`../`, absolute paths, nested dirs) → reject.
- `format_version` known (§2.5).
- `kind` matches the entry point (§4.1): `course` at Import course, `subtree` at Import
  content; mismatch → reject, pointing at the correct entry point.

**Document level:**

- Schema check: required keys, **per-field JSON type checks** (strings/numbers/booleans/
  lists as the schema demands, including child-row shapes; decimal strings must parse
  within the field's `max_digits`/`decimal_places` envelope) — a wrong-typed value
  rejects with a named message, never a 500. Internal ids must be **unique
  document-wide**; references resolve (element→unit, element→media, node→parent),
  element `unit` refs must point at a node with `kind: "unit"`, node kinds nest legally
  (strictly deeper than parent).
- Count caps (settings constants, generous): max nodes, max elements, max media entries
  per document — byte caps alone don't bound row counts, and import is in-request.
- Depth-flag consistency: for `kind: "course"`, every node's kind must be in the set
  allowed by the **archive's own** `uses_*` flags (via `kinds_for_flags`) — a crafted
  document must not create a course the builder could never author. For `kind:
  "subtree"`, every node's kind must fit the **target course's** depth flags.
- Subtree shape: exactly **one** node with `parent: null`, whose kind equals
  `context.root_kind`; zero or multiple roots → reject. (Course documents may have any
  number of top-level nodes.)
- `color_bands`: an empty/absent value is **valid** and imports as `[]` (the model
  default — platform defaults apply); a **non-empty** value must pass the existing
  stored-shape validator in `courses/color_bands.py` (currently private
  `_is_valid_stored` — the plan exposes or wraps it), else reject.
- Per-type element invariants: the builder enforces authoring rules at **form** level
  only (`courses/element_forms.py`, incl. formset-level rules), so document validation
  must mirror them — choice: ≥2 choices, ≥1 correct, exactly one correct when
  single-choice (a zero-correct choice question would mark any empty submission fully
  correct); short-text: ≥1 accepted answer; extended-response with `marking_mode: "A"`:
  ≥1 non-blank required or forbidden keyword line (keyword-less auto-marking scores
  **any** answer fully correct); fill-blank/drag-fill: **≥1 blank/gap row**, and the
  stem's sentinel tokens are **exactly indices 0..n-1, each exactly once** where n =
  number of blank rows (count-match alone admits `￿0￿￿0￿` or `￿99￿`, which render/mark
  incoherently; n = 0 is unauthorable and permanently unanswerable), with **no other
  occurrence of the sentinel character** outside those tokens (stored stems can never
  legitimately contain a bare `￿` or math placeholder); each fill-blank blank row has
  ≥1 non-blank accepted line; drag-fill gaps hold exactly one token within the length
  cap; match-pair: ≥1 pair with non-empty `left` and `right`; drag-to-image: ≥1 zone
  with a non-empty `correct_label`. Violation → reject naming the element and rule.
- Node `parent` references must point at an **earlier node in the list** (well-formed
  exports always satisfy this; frees the importer to create strictly in sequence).
- Media correspondence, both directions: every `media[].file` must name an entry present
  in the archive (reject naming the id/path otherwise); `media/*` zip entries absent
  from the media list → reject; media list entries referenced by **no element** →
  reject (symmetric with referenced-only export).
- Embed URLs (`video.url`, `iframe.url`) re-validated against the **target's**
  `ALLOWED_EMBED_DOMAINS`; a URL allowed at the source but not the target rejects the
  import, naming the URL. `video.url` additionally runs through `canonicalize_video_url`
  before the check (idempotent on canonical URLs — well-formed exports already carry
  canonical values; this mirrors the builder's paste-normalization gate, PR #31), and
  `iframe.url` through its `extract_embed_url` equivalent.

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
domain rejection (URL), staged upload expired/not found (upload again). Export's only failure mode is a clean error response
(archive spooled before streaming).

## 9. Testing

- **Round-trip:** build a course exercising **all 14 element types** (incl. every question
  sub-table and media on image/video/drag-to-image), export → import into the same test DB,
  assert the new course's content graph is field-for-field equal (excluding pks, owner,
  slug suffix, order re-seeding, `created`/`updated` timestamps, `uploaded_by`, and
  media storage paths — compare file **bytes**, not names). A default-band course
  (`color_bands = []`) must round-trip. The §2.4 resets get their own assertion: a
  source course with `visibility="open"`, self-enrol cohorts, and an `external_id`
  imports with all three reset. Same for a subtree round-trip into a target course.
- **Sanitizer/validator re-entry:** crafted zip with a script tag in a text body imports
  with it stripped; oversized / wrong-extension media rejects the whole import.
- **Hostile zips:** path traversal entries, lying uncompressed sizes (bomb), oversized
  `course.json`, unknown element type, dangling internal ids, illegal nesting,
  duplicate zip entry names, duplicate internal ids, media/file correspondence
  violations (missing entry, extra entry, unreferenced media item), zero-correct choice
  question, keyword-less auto-marked extended response, duplicate/out-of-range sentinel
  token, zero blank rows, stray sentinel characters, empty `pairs`/`zones`, wrong-typed
  field values and malformed decimal strings — each rejected with the right message,
  never a 500, nothing written (assert no Course/ContentNode/media rows or files
  created).
- **Collision & matching:** slug `-2` suffixing; subject match by either-language title,
  case-insensitive; unmatched reported at preview and dropped.
- **Permissions:** export requires course edit; full import requires course create;
  subtree import requires edit on the target course; a forged insertion-point node id
  belonging to a different course → rejected (scoped lookup), nothing written.
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
