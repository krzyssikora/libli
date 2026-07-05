# Tolerant Export with Pre-flight Problem Report — Design

**Date:** 2026-07-06
**Status:** Approved (brainstorm), pending plan
**Amends:** `docs/superpowers/specs/2026-07-05-course-export-import-design.md` §3 (export). Lands on branch `course-export-import` / PR #68.

## Problem

The export (`courses/transfer/export.py:build_export`) currently hard-fails with a `TransferError` when a referenced media file is missing from storage (`OSError` on `asset.file.size`) or when an `Element` join row's underlying concrete element record is gone (`content_object is None`). The view catches it, flashes a filename-only message ("Media file missing from storage: demo.png"), and redirects to the builder. A real course (e.g. seed "Demo Course", whose `MediaAsset` pk=1 → `courses/images/demo.png` was never on disk) then cannot be exported at all, and the message doesn't say *which unit* the file is used in.

## Goal

A data problem (missing media file, broken element) must **not** stop an export. The export proceeds, substituting/dropping the affected content, and the user is shown a **precise pre-flight report** of what was missing and where, with an explicit "Export anyway". Healthy courses are unaffected (still a one-click download). This subsumes the earlier "name the unit in the error message" ask — the report replaces the filename-only error.

## Design

### 1. `build_export` becomes tolerant and returns a `problems` list

New return shape:

```
build_export(course, node=None, source_host="") -> (manifest, document, media_assets, problems)
```

`problems` is a list of dicts, each one of:

- `{"type": "missing_image", "filename": <original_filename>, "units": [<unit titles, de-duplicated, in first-seen order>]}`
- `{"type": "dropped_video", "filename": <original_filename>, "units": [<unit titles>]}`
- `{"type": "broken_element", "units": [<unit titles>]}`

Detection during the graph walk (all decisions made **before** `write_archive` copies bytes):

- **Missing media file** — determined by an existence check: `asset.file.storage.exists(asset.file.name)` is the authority for the missing/present decision (so a genuinely-present file is never misclassified by an unrelated error). For present files, `.size` is still read for `media_total_bytes` and is itself guarded — a present-but-unreadable file is treated as missing. Branch on `asset.kind` (in practice media kinds are only `image` and `video`):
  - `kind == "image"` (covers image elements and drag-to-image, both of which register `kind="image"` media): keep the media entry, but flag its `mid` as **placeholder** — the archive ships the bundled placeholder PNG bytes for that entry, and the element that references it is **unchanged** (block preserved). Record one `missing_image` problem per distinct missing asset, `units` = every unit whose exported element references that asset.
  - **any non-image kind** (`video`, or any other): flag its `mid` as **dropped**. Every element referencing that `mid` is removed from `document["elements"]`, and the media entry is omitted. Record a `dropped_video` problem (the label reflects the only non-image kind that exists today; the drop rule is general so no missing file can ever fall through to a placeholder for a non-image kind).
- **Broken element** (`join.content_object is None`) — the element is skipped (not added to `document["elements"]`). Record a `broken_element` problem with the containing unit.

The element walk already visits each `Element` join in unit order, so unit attribution is available at detection time. A missing asset referenced by several units lists **all** of them (e.g. demo.png in two "Bonus lesson" units → `units: ["Bonus lesson", "Bonus lesson"]` de-duplicated appropriately — see Open decision below).

`media_assets` (the value `write_archive` consumes) must now carry, per `mid`, whether to write the **real** asset bytes or the **placeholder** bytes. Dropped video `mid`s are absent from `media_assets` and from `document["media"]`.

When `problems == []`, the produced `manifest`/`document`/`media_assets` are byte-for-byte what the current implementation produces (no behavioral change for healthy courses).

`media_total_bytes` counts placeholder size for placeholder entries and excludes dropped entries.

### 2. Bundled placeholder asset

A small, valid PNG committed at `courses/transfer/assets/missing_image_placeholder.png` (a neutral "missing image" graphic; kept tiny). It must satisfy import media validation: `.png` extension (allowed), size well under the image cap, `kind="image"`. For a placeholder-substituted media entry:

- `original_filename` — **keep the original** (e.g. `"demo.png"`) so the imported asset is recognizable as "this was demo.png, now a placeholder".
- `file` — `media/<mid>.png` (placeholder's extension).
- `kind` — `"image"`.
- archive bytes — the placeholder file's bytes.

On import this is an ordinary image asset with placeholder content; the import side needs **no** changes.

### 3. `scan_export_problems(course, node=None) -> problems`

A thin wrapper that runs the same detection and returns just the `problems` list without writing a zip:

```
def scan_export_problems(course, node=None):
    return build_export(course, node)[3]
```

Single source of truth (no duplicated detection). Cost is bounded — `build_export` does existence/`.size` checks (a `stat`, not a full read) and no byte copying; `write_archive` is the only thing that copies bytes.

### 4. `write_archive` writes placeholder bytes / omits dropped media

`write_archive` consumes `media_assets`; for a `mid` flagged **placeholder** it streams the bundled placeholder file's bytes into `media/<mid>.png`; for real entries, unchanged. Dropped `mid`s are already absent.

### 5. View flow (`export_course` / `export_subtree`)

Both views, after resolving+authorizing course/node:

1. `problems = scan_export_problems(course, node)`.
2. If `problems` **and** `request.GET.get("confirm") != "1"` → render the pre-flight page (HTTP 200) listing the problems, with:
   - **Export anyway** → a GET link to the same URL with `?confirm=1`.
   - **Cancel** → back to the builder (`manage_builder`).
3. Otherwise (no problems, or `confirm=1`) → `_stream_archive(...)` exactly as today (which now tolerates + substitutes).

Healthy course → step 1 finds nothing → step 3 streams in the same request → **unchanged one-click download**. Problematic course → the page appears once; "Export anyway" re-requests with `?confirm=1` and downloads. The confirm link is an idempotent GET (deterministic scan), so no CSRF/staging token is needed.

The current `_stream_archive` `except TransferError` (redirect-to-builder) stays as a backstop for any *other* export failure, but the missing-media / broken-element paths no longer raise, so in practice it only fires on genuinely unexpected errors.

### 6. Template `templates/courses/manage/export_preview.html`

Styled per the repo's token CSS + `.icon` sprite (no bare HTML, no undefined classes), EN/PL. Renders:

- A heading + short explanation ("This course can be exported, but some media is missing. Review below, then Export anyway.").
- A list, one row per problem:
  - `missing_image`: "Image **demo.png** is missing — it will be exported as a placeholder. Used in: Bonus lesson."
  - `dropped_video`: "Video **clip.mp4** is missing — this video block will be left out of the export. In: Lesson 3."
  - `broken_element`: "A broken content block will be left out of the export. In: Lesson 3."
- **Export anyway** (`.btn .btn--primary`) + **Cancel** (`.btn .btn--ghost`).

All problem-derived strings (filenames, unit titles) render through normal autoescaping (never `mark_safe`).

## Testing

- `build_export` (tests/test_transfer_export.py):
  - missing image file → media entry kept + flagged placeholder, element unchanged, one `missing_image` problem; a missing image referenced by **two** units lists both.
  - missing video file → referencing element(s) dropped from `document["elements"]`, media entry omitted, `dropped_video` problem.
  - broken GFK (`content_object None`) → element skipped, `broken_element` problem.
  - all-present course → `problems == []` and document/media identical to pre-change (regression guard).
  - `media_total_bytes` reflects placeholder size / excludes dropped.
- `write_archive` → for a missing-image course the zip's `media/<mid>.png` equals the bundled placeholder bytes; dropped video mid absent from `namelist()`.
- `scan_export_problems` → returns the problems list, writes no zip.
- Placeholder asset → passes the import media validators (extension/size/kind) — a small direct test.
- Views (tests/test_transfer_views.py):
  - export a course with a missing media file, no `confirm` → 200, page names the file and unit; not a download.
  - same with `?confirm=1` → 200 streaming zip (attachment).
  - export a fully-healthy course → streams directly, no pre-flight page (one request).
  - round-trip: export (with placeholder) → confirm → import → the placeholder image asset exists on the imported course.
- The reported real case (Demo Course / demo.png) exports via the confirm path.

## Non-goals / not changing

- Import side — placeholders import as normal images; dropped blocks simply aren't in the archive.
- No new settings, no DB migration.
- Video placeholder substitution (rejected in brainstorm — a placeholder video isn't sensible; missing video files are dropped instead).

## Open decision (resolve in plan, default chosen)

- **Unit list de-duplication:** a missing asset used twice in the *same* unit, or in two units with the *same title*, should list each unit **once by identity** (dedupe on unit pk, display title). Default: dedupe on unit pk, preserve first-seen order.
