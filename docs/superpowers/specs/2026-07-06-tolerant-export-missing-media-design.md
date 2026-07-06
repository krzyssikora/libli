# Tolerant Export with Pre-flight Problem Report — Design

**Date:** 2026-07-06
**Status:** Approved (brainstorm), pending plan
**Amends:** `docs/superpowers/specs/2026-07-05-course-export-import-design.md` §3 (export). Lands on branch `course-export-import` / PR #68.

## Problem

The export (`courses/transfer/export.py:build_export`) currently hard-fails with a `TransferError` when a referenced media file is missing from storage (`OSError` on `asset.file.size`) or when an `Element` join row's underlying concrete element record is gone (`content_object is None`). The view catches it, flashes a filename-only message ("Media file missing from storage: demo.png"), and redirects to the builder. A real course (e.g. seed "Demo Course", whose `MediaAsset` pk=1 → `courses/images/demo.png` was never on disk) then cannot be exported at all, and the message doesn't say *which unit* the file is used in.

## Goal

A data problem (missing media file, broken element) must **not** stop an export. The export proceeds, substituting/dropping the affected content, and the user is shown a **precise pre-flight report** of what was missing and where, with an explicit "Export anyway". Healthy courses are unaffected (still a one-click download, and — see §5 — no extra graph walk). This subsumes the earlier "name the unit in the error message" ask — the report replaces the filename-only error.

## Design

### 1. `build_export` becomes tolerant and returns a `problems` list

New return shape (was a 3-tuple `(manifest, document, media_assets)`):

```
build_export(course, node=None, source_host="") -> (manifest, document, media_assets, problems)
```

`media_assets` element shape changes from `(mid, asset)` to **`(mid, asset, is_placeholder)`** where `is_placeholder` is a bool. A placeholder entry still carries the **real** `MediaAsset` (its `original_filename`, `name`, `kind` are read from it) but signals `write_archive` to write the bundled placeholder bytes instead of `asset.file`. Dropped media are **absent** from `media_assets` (and from `document["media"]`).

`problems` is a list of dicts, each one of:

- `{"type": "missing_image", "filename": <original_filename>, "units": [<unit titles>]}` — one per distinct missing image asset; `units` = every unit whose exported element references that asset, de-duplicated **by unit pk**, first-seen order.
- `{"type": "dropped_video", "filename": <original_filename>, "units": [<unit titles>]}` — one per distinct missing non-image asset; `units` = every unit that referenced this asset via a now-dropped element, de-duplicated by unit pk, first-seen order (usually one).
- `{"type": "broken_element", "units": [<single unit title>]}` — **one problem per broken `Element` join row** (a broken element has no natural asset key), `units` = its single containing unit. Two broken elements in one unit → two problems; no cross-unit aggregation.

`problems` is ordered **first-seen in the unit/element walk**, achieved by a final stable sort rather than append order: each problem records the walk index of the element that first surfaced it (`broken_element` → the skipped element; `dropped_video` → the first dropped element referencing the asset; `missing_image` → the first emitted element referencing the missing asset), and after all passes `problems` is **stably sorted by that index**. This is necessary because the passes append out of walk order — `broken_element` in step 2, `missing_image`/`dropped_video` in steps 4–5 — so append order alone would be step-ordered, not walk-ordered. (`missing_image` problems are recorded during step 5 asset emission, positioned by their first-referencing element's index.) Two genuinely distinct missing assets that happen to share an `original_filename` (e.g. two different `photo.png` uploads) produce **two** distinct problems that render identically — accepted; `filename` is not a dedupe key (mirrors the same-titled-units case in §6).

#### Build sequencing (two passes — this is a real restructuring)

Existence is only knowable once, and a dropped video must retroactively remove an already-serialized element, so the current "serialize elements, then check media in a later loop" order cannot stay. Restructure into:

1. **Nodes** → `node_dicts` (unchanged).
2. **Element pass** — walk each `Element` join in unit order, tracking a monotonic `walk_index` that increments for **every** join visited (including skipped broken ones), so all three problem types index into one consistent space. If `join.content_object is None` → **skip** it and record a `broken_element` problem (its unit and `walk_index`). Otherwise serialize it (which registers any media `mid` via `MediaIdMap`), and remember a tuple `(walk_index, serialized_element_dict, referenced_mids, unit)`, where **`referenced_mids` = the non-`None` `data["media"]` value(s) read from the just-serialized element dict** (image / video / drag-to-image are the only media-bearing types, each carrying at most one scalar `mid` in `data["media"]`). Reading it from the emitted `data` — rather than snapshotting `MediaIdMap` growth — correctly captures a *re-reference* of an already-registered asset (same asset used in two units). **Invariant/guardrail:** `data["media"]` is a single scalar mid; if a future media-bearing type ever carries a list of mids, `referenced_mids` extraction here and the "references a dropped `mid`" test in step 4 must be revisited.
3. **Resolve assets** — for each distinct registered asset, compute its **final** status *here* (before any element or media emission) by combining `storage.exists()` with a guarded `.size` read: an asset that is absent **or** present-but-unreadable (`.size` raises `OSError`) counts as **missing**. Then classify: **present & readable** → real (its `.size` feeds `media_total_bytes`); **missing + `kind=="image"`** → placeholder; **missing + any non-image kind** → dropped. No later pass reclassifies an asset — the guarded `.size` read lives in this step, not in the emit steps.
4. **Emit elements** — build `document["elements"]` from the pass-2 list, **excluding** any element that references a dropped `mid` (for each such exclusion, record a `dropped_video` problem for the asset, aggregating units). Assign element ids `e{i}` **sequentially over the emitted (kept) elements only** — skipped/dropped elements do not consume an id, so there are no id gaps. (The step-2 `serialized_element_dict` holds only `unit`/`title`/`type`/`data` — **not** `id`; the `id` is assigned here in step 4 over the kept sequence, never at serialization time, so it is never walk-index-based.) (Element ids are opaque and unreferenced elsewhere; tests must not assert on skipped-element numbering.)
5. **Emit media** — build `document["media"]` and `media_assets` from the registered assets **excluding dropped ones**; placeholder assets get `is_placeholder=True` and their media-dict fields per §2. A dropped asset still consumed an `m{n}` at registration, so the kept mids may be **non-contiguous** (e.g. `m1, m3`). Mids are opaque and **must NOT be renumbered** — element `data["media"]` values are already bound to the original mids, and renumbering would desync those references. (This differs from element ids in step 4, which *are* assigned fresh over kept elements because nothing references them.)

`media_total_bytes` counts the placeholder file's size for placeholder entries and excludes dropped entries.

When `problems == []`, the produced `manifest`/`document`/`media_assets` (ignoring the added bool, always `False`) are equivalent to the current implementation — no behavioral change for healthy courses.

#### Caller migration (the 4-tuple + 3-element `media_assets` break every current unpack)

The following sites unpack the old shapes and MUST be updated in lockstep (the suite is otherwise left red):

- `courses/transfer/export.py` — `write_archive` (unpacks `build_export`; iterates `for mid, asset in media_assets`).
- `tests/test_transfer_export.py` — the `build_export(...)`/`write_archive` assertions (`manifest, doc, media = build_export(...)`, media-shape asserts).
- `tests/test_transfer_subtree.py`, `tests/test_transfer_import.py` — their `build_export(...)` unpack sites.

Sites that don't care about `problems` unpack it as `*_`/a discarded 4th value. Every `for mid, asset in media_assets` becomes `for mid, asset, is_placeholder in media_assets`. **`dict(media_assets)` construction sites** — e.g. `dict(src_media_items)` in `tests/test_transfer_import.py` and `tests/test_transfer_subtree.py` — must become `{mid: asset for mid, asset, _ in media_assets}`; a bare `dict()` over 3-tuples raises `ValueError` (a different failure mode than the `for`-loop unpacks, so grep for both).

### 2. Bundled placeholder asset

A small, valid PNG committed at `courses/transfer/assets/missing_image_placeholder.png` (a neutral "missing image" graphic; kept tiny). It is **package data**, not a static asset: it is read from the module directory (`os.path.dirname(__file__)/"assets/missing_image_placeholder.png"`), read for its size (in `build_export`, for `media_total_bytes`) and its bytes (in `write_archive`). It is not served by `collectstatic`/`MEDIA`.

**Existence-check mechanism:** `asset.file.storage.exists(asset.file.name)` is the authority for the missing/present decision (so a genuinely-present file is never misclassified by an unrelated error). For present files, `.size` is still read for `media_total_bytes`, itself guarded — a present-but-unreadable file is treated as missing.

**Import-validity of a placeholder entry.** The importer validates the extension of `m["original_filename"]` (not the archive `file` path) and stores the asset under `name = original_filename`. Therefore the placeholder entry's `original_filename` extension governs importability, and it must be one the target allows for images. Resolution: for a placeholder entry, **keep the original filename stem but force a `.png` extension**, computed exactly as `original_filename = (os.path.splitext(original)[0] or "image") + ".png"` — using the same `os.path.splitext` the export already uses for extensions in `export.py` (do NOT use an `rsplit('.',1)` variant; the two diverge on leading-dot names). Examples: `"photo.jpg"` → `"photo.png"`, `"demo.png"` → `"demo.png"`, `"pic"` → `"pic.png"`, `".foo"` → `".foo.png"` (valid — `splitext(".foo")` gives stem `".foo"`, and `.foo.png` has a real `.png` extension). Only a genuinely empty stem — `original == ""` or `"."`, where `splitext` yields stem `""` and the raw result `".png"` would read as *no* extension to `FileExtensionValidator` — triggers the `or "image"` guard → `"image.png"`. This keeps the name recognizable, matches the actual placeholder bytes, and uses `.png` — the near-universal default image extension. The importability guarantee is thus: *an exported archive imports on any instance whose image allow-set includes `.png` **and** whose `effective_max_image_bytes()` ceiling admits the placeholder bytes*. The placeholder is kept to **a few KB** (well under any plausible size ceiling), so in practice only the `.png` allow-set condition matters (both hold on the default config). Placeholder media-dict fields:

- `original_filename` — original stem + forced `.png`.
- `file` — `media/<mid>.png`.
- `kind` — `"image"`.
- `id`, `name` — **unchanged** from the normal media dict.
- archive bytes — the placeholder file's bytes.

On import this is an ordinary image asset with placeholder content; the import side needs **no** changes (given a `.png`-allowing target).

Image-kind media covers both `ImageElement` and `DragToImageQuestionElement` backgrounds. A drag-to-image whose background is placeholdered keeps its original zone coordinates, which will no longer align with the neutral placeholder graphic — the imported question is valid but visually nonsensical. Accepted degradation (exportability over fidelity); it is still reported as a `missing_image` problem so the user knows.

### 3. `write_archive` split so the view can build once (no double walk)

To let the view scan for problems and stream **without walking the graph twice**, separate building from writing:

- `build_export(course, node, source_host="") -> (manifest, document, media_assets, problems)` — builds, as above.
- `write_archive_from(manifest, document, media_assets, fileobj) -> None` — writes a **pre-built** result into `fileobj`; for a `mid` whose `media_assets` entry has `is_placeholder=True` it streams the bundled placeholder bytes into `media/<mid>.png`, else streams `asset.file`. Dropped mids are already absent.
- `write_archive(course, node, fileobj, source_host="") -> None` — thin convenience wrapper (`build_export` then `write_archive_from`) retained for existing callers/tests that want one-shot behavior and don't care about `problems`.

A present-at-build asset that vanishes before `write_archive_from` streams it raises `OSError` (not `TransferError`) — a pre-existing narrow TOCTOU window (today's `write_archive` has the same check→stream gap; the phase split does not meaningfully widen it). **Accepted as out of scope** for this amendment; `write_archive_from` does not specially guard the per-asset stream.

There is no separate `scan_export_problems` helper — the view (and tests) obtain `problems` directly from the single `build_export` call. (`build_export`'s `problems` element is the only "scan" surface needed.)

### 4. Placeholder byte writing

Covered by `write_archive_from` above: the placeholder file is opened from the package `assets/` directory and its bytes streamed into the entry, in place of `asset.file`, for `is_placeholder` entries.

### 5. View flow (`export_course` / `export_subtree`)

Both views, after resolving+authorizing course/node, build **once** and branch:

```
try:
    manifest, document, media_assets, problems = build_export(course, node, source_host=request.get_host())
except TransferError as exc:               # residual/unexpected export failure (e.g. unserializable model)
    messages.error(request, exc.message)
    return redirect("courses:manage_builder", slug=course.slug)

if problems and request.GET.get("confirm") != "1":
    return render("courses/manage/export_preview.html",
                  {"problems": problems, "course": course})   # HTTP 200

# no problems, OR confirmed: stream from the ALREADY-BUILT artifacts
spool = SpooledTemporaryFile(...)
write_archive_from(manifest, document, media_assets, spool)
spool.seek(0)
return FileResponse(spool, as_attachment=True, filename=export_filename(...), content_type="application/zip")
```

Key points this resolves:

- **Single build per request.** Healthy course → one `build_export` + stream (no extra graph walk vs. today). Problems + no confirm → one `build_export` + render page. Confirm → one `build_export` + stream. The only case with two builds is the page→confirm round-trip, and that is one build **per HTTP request** (unavoidable in a stateless GET flow without staging, which we deliberately avoid) and only when problems exist. (Note: every referenced asset now incurs one `storage.exists()` stat even on healthy exports — negligible on local-FS storage, an added round-trip on remote backends like S3.)
- **Preview links are flow-agnostic.** The template's **Export anyway** link is `{{ request.path }}?confirm=1` — it targets whichever endpoint rendered the page (course `…/export/` or subtree `…/build/node/<pk>/export/`) without the view computing a URL. **Cancel** links to `courses:manage_builder` via `course.slug`. Both `export_course` and `export_subtree` render the **same** template with the **same** `{problems, course}` context (so the shared `_stream_archive`/build helper does not need per-flow URL logic).
- **Scan-time errors are handled.** The `build_export` call is wrapped in the same `TransferError` → redirect-to-builder handling, so a residual raise is a friendly redirect, not a 500. (The missing-media / broken-element paths no longer raise; this backstop covers only genuinely unexpected export failures.)
- The confirm link is an idempotent GET (`?confirm=1`), deterministic build → no CSRF/staging token needed.
- The existing `_stream_archive` helper is refactored (or replaced) so its `build_export`+stream is expressed as `build_export` (guarded) + `write_archive_from`; do not leave a second, separate `build_export` call in the stream path.

### 6. Template `templates/courses/manage/export_preview.html`

Styled per the repo's token CSS + `.icon` sprite (no bare HTML, no undefined classes), EN/PL. Renders:

- A heading + short explanation ("This course can be exported, but some media is missing. Review below, then Export anyway.").
- A list, one row per problem:
  - `missing_image`: "Image **demo.png** is missing — it will be exported as a placeholder. Used in: Bonus lesson."
  - `dropped_video`: "Video **clip.mp4** is missing — this video block will be left out of the export. In: Lesson 3."
  - `broken_element`: "A broken content block will be left out of the export. In: Lesson 3."
- **Export anyway** (`.btn .btn--primary`, GET link to `{{ request.path }}?confirm=1` — flow-agnostic, works for both the course and subtree endpoints) + **Cancel** (`.btn .btn--ghost`, → `courses:manage_builder` via `course.slug`).

Two distinct units that happen to share a title render their title twice in a `units` list (e.g. "Used in: Bonus lesson, Bonus lesson") — this is the reported Demo-Course shape and is **accepted** (they are genuinely two different units); disambiguating by parent path is a possible future refinement, not required. All problem-derived strings (filenames, unit titles) render through normal autoescaping (never `mark_safe`).

## Testing

- `build_export` (tests/test_transfer_export.py):
  - missing image file → media entry kept with `is_placeholder=True`, element unchanged, one `missing_image` problem; a missing image referenced by **two distinct units** lists both (dedupe-by-pk verified — two same-titled units both appear).
  - missing video (non-image) file → referencing element(s) removed from `document["elements"]`, media entry omitted from `media_assets`/`document["media"]`, `dropped_video` problem.
  - broken GFK (`content_object None`) → element skipped, one `broken_element` problem per broken join (two broken in one unit → two problems).
  - kept-element ids are contiguous (`e1, e2, …`) with a broken/dropped element interleaved (no gaps).
  - **cross-type problem ordering**: a single walk containing a broken element, then a missing-image element, then a dropped-video element (deliberately surfaced across steps 2 / 5 / 4) → `[p["type"] for p in problems]` is in **walk order** (`["broken_element", "missing_image", "dropped_video"]`), NOT step/append order — pins the walk-index stable-sort machinery so a regression to append order can't ship green.
  - all-present course → `problems == []` and document/media equivalent to pre-change (regression guard); `media_assets` bools all `False`.
  - `media_total_bytes` reflects placeholder size / excludes dropped.
  - placeholder `original_filename` extension forced to `.png` when the original was e.g. `.jpg` (and stem preserved).
- `write_archive_from` / `write_archive` → for a missing-image course the zip's `media/<mid>.png` equals the bundled placeholder bytes; dropped video mid absent from `namelist()`.
- Placeholder asset → passes the import media validators for an image (extension `.png`, size, kind) — a small direct test.
- Views (tests/test_transfer_views.py):
  - export a course with a missing media file, no `confirm` → 200, page names the file and unit; not a download (no `Content-Disposition: attachment`).
  - same with `?confirm=1` → 200 streaming zip (attachment).
  - export a fully-healthy course → streams directly, no pre-flight page (one request, single build).
  - export a **subtree** (`export_subtree`) whose subtree contains a missing-media unit, no `confirm` → preview 200; with `?confirm=1` → streams the **subtree** zip (exercises the flow-agnostic `{{ request.path }}?confirm=1` link, so a wrong subtree confirm URL can't ship green).
  - a residual `build_export` `TransferError` at scan/build time → redirect to builder with a flashed message (not a 500).
  - round-trip: export (with placeholder) → confirm → import → the placeholder image asset exists on the imported course.
- The reported real case (Demo Course / demo.png, two "Bonus lesson" units) exports via the confirm path.

## Non-goals / not changing

- Import side — placeholders import as normal `.png` images (given a `.png`-allowing target); dropped blocks simply aren't in the archive. A unit whose only element was dropped/broken exports as an **empty** unit, which imports unchanged (units are independent of elements) — accepted, not surfaced as a problem.
- No new settings, no DB migration.
- Video placeholder substitution (rejected in brainstorm — a placeholder video isn't sensible; missing non-image files are dropped instead).
