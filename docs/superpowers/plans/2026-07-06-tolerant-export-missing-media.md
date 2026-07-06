# Tolerant Export with Pre-flight Problem Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make course export tolerate missing media (placeholder for images, drop for videos) and broken elements, never hard-failing; show a pre-flight page listing exactly what was missing and in which units, with an "Export anyway" confirm.

**Architecture:** `build_export` (in `courses/transfer/export.py`) becomes tolerant, returning a 4th value `problems` and a 3-element `media_assets` shape `(mid, asset, is_placeholder)`. A two-pass build resolves each referenced asset's status (present / placeholder / dropped) before emitting elements/media. `write_archive` is split so the export view builds once and either renders a pre-flight page or streams from the already-built artifacts. A bundled placeholder PNG substitutes for missing images.

**Tech Stack:** Django (server-rendered), stdlib `os`/`zipfile`/`json`, Pillow (already a dep, `pillow>=12.2.0`) for generating the placeholder asset, pytest + pytest-django.

**Spec:** `docs/superpowers/specs/2026-07-06-tolerant-export-missing-media-design.md` — the authority for every rule below (references "§N" point at spec sections). This amends the course export/import feature on branch `course-export-import` / PR #68.

## Global Constraints

- Tooling: bash `ruff`/`pytest`/`python` are NOT on PATH — always `uv run pytest`, `uv run ruff`, `uv run python manage.py …`.
- Run `uv run ruff format <changed files>` AND `uv run ruff check --fix <changed files>` before every commit (CI runs `ruff format --check`).
- **Do NOT run the whole repo suite** (`uv run pytest` with no args) — the ~1800-test run trips a stream watchdog and stalls. Run only the focused test files named in each task. The controller runs the full-suite DoD at the end.
- Postgres test DB can collide with a lingering connection ("test_libli already exists / used by other users"). If a run fails ONLY with that DB-setup error (not a real assertion failure), re-run once with `--create-db`.
- Never hardcode a password literal in tests — use `tests.factories.TEST_PASSWORD` (GitGuardian CI).
- All user-facing strings `gettext`/`{% trans %}`-wrapped. Django `{# #}` comments are single-line only; use `{% comment %}` for multi-line. Every view ships styled (no bare HTML, no undefined CSS classes); icons are monochrome `currentColor` SVGs via the shared sprite.
- All archive-derived / problem-derived strings (filenames, unit titles) render through normal autoescaping — never `mark_safe`/unescaped `format_html`.
- When a step says "append" a code block that contains import lines, merge those imports into the file's existing top import block (dropping duplicates) — pasting them mid-file trips ruff E402. Snippets show them inline only for readability.

## File Structure

```
courses/transfer/assets/missing_image_placeholder.png   (NEW — bundled placeholder image, package data)
courses/transfer/export.py                              (MODIFY — placeholder helpers; tolerant build_export; write_archive split)
courses/views_transfer.py                               (MODIFY — build-once export flow + pre-flight render)
templates/courses/manage/export_preview.html            (NEW — pre-flight problem page)
locale/en|pl/LC_MESSAGES/django.po|.mo                  (MODIFY — new template strings)
tests/test_transfer_export.py                           (MODIFY — 4-tuple unpack migration + tolerance/ordering tests)
tests/test_transfer_import.py                           (MODIFY — 4-tuple + dict() unpack migration)
tests/test_transfer_subtree.py                          (MODIFY — 4-tuple + dict() unpack migration)
tests/test_transfer_views.py                            (MODIFY — pre-flight/confirm/subtree/healthy/error/round-trip tests)
```

Existing seams consumed (verified in code):
- `courses/transfer/export.py`: `build_export(course, node=None, source_host="")` (currently returns `(manifest, document, media_ids.items())`, raises `TransferError` on missing media / broken element); `write_archive(course, node, fileobj, source_host="")`; `MediaIdMap` (`.register(asset)->mid`, `.items()->[(mid, asset)]`); `serialize_element_data(concrete, media_ids)->(type_key, data)` where media-bearing types put a scalar `mid` (or `None`) in `data["media"]`.
- `courses/views_transfer.py`: `_stream_archive(request, course, node)` (lines 38-56) calls `write_archive` into a spool then `FileResponse`; `export_course`/`export_subtree` call it. `messages`, `redirect`, `FileResponse`, `tempfile`, `timezone`, `export_filename` already imported.
- `MediaAsset` fields: `.kind` ("image"/"video"), `.original_filename`, `.name`, `.file` (a `FieldFile`: `.name`, `.size` (raises `OSError` if gone), `.storage.exists(name)`, `.open("rb")`).
- Import media validation (for the placeholder-validity test): `courses.validators.effective_image_extensions()`, `effective_max_image_bytes()`.

---

### Task 1: Bundled placeholder asset + loader/name helpers

**Files:**
- Create: `courses/transfer/assets/missing_image_placeholder.png` (generated once, committed)
- Modify: `courses/transfer/export.py` (append helper functions)
- Test: `tests/test_transfer_export.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces (in `courses/transfer/export.py`):
  - `_placeholder_bytes() -> bytes` — the placeholder file's bytes.
  - `_placeholder_size() -> int` — the placeholder file's size in bytes.
  - `_placeholder_filename(original: str) -> str` — `(os.path.splitext(original or "")[0] or "image") + ".png"` (§2).

- [ ] **Step 1: Generate and commit the placeholder PNG**

Run this one-off generator (Pillow is a dep) to create the committed asset:

```bash
uv run python - <<'PY'
import os
from PIL import Image, ImageDraw

os.makedirs("courses/transfer/assets", exist_ok=True)
img = Image.new("RGB", (480, 270), (233, 233, 233))
d = ImageDraw.Draw(img)
d.rectangle([0, 0, 479, 269], outline=(176, 176, 176), width=3)
d.line([0, 0, 479, 269], fill=(198, 198, 198), width=3)
d.line([0, 269, 479, 0], fill=(198, 198, 198), width=3)
img.save("courses/transfer/assets/missing_image_placeholder.png", optimize=True)
print("wrote", os.path.getsize("courses/transfer/assets/missing_image_placeholder.png"), "bytes")
PY
```

Expected: a small PNG (a light-gray box with an X, a few KB — well under any `effective_max_image_bytes()` ceiling). It's **package data** (read from the module directory), not a static asset.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_transfer_export.py`)

```python
# --- Task 1: placeholder asset + helpers ---
from courses.transfer.export import _placeholder_bytes
from courses.transfer.export import _placeholder_filename
from courses.transfer.export import _placeholder_size


def test_placeholder_filename_forces_png_stem():
    assert _placeholder_filename("photo.jpg") == "photo.png"
    assert _placeholder_filename("demo.png") == "demo.png"
    assert _placeholder_filename("pic") == "pic.png"
    assert _placeholder_filename(".foo") == ".foo.png"  # splitext(".foo") -> stem ".foo"
    assert _placeholder_filename("") == "image.png"  # empty stem falls back
    assert _placeholder_filename(".") == "image.png"


def test_placeholder_asset_is_a_valid_importable_image():
    import io

    from PIL import Image

    from courses.validators import effective_image_extensions
    from courses.validators import effective_max_image_bytes

    data = _placeholder_bytes()
    assert _placeholder_size() == len(data)
    # a real, openable PNG
    Image.open(io.BytesIO(data)).verify()
    # passes the import media gates for an image entry named "*.png"
    assert "png" in {e.lower().lstrip(".") for e in effective_image_extensions()}
    assert _placeholder_size() < effective_max_image_bytes()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_export.py -k "placeholder" -v`
Expected: FAIL — `ImportError: cannot import name '_placeholder_bytes'` (the helpers don't exist yet).

- [ ] **Step 4: Implement the helpers** (append to `courses/transfer/export.py`; `os` is already imported at the top)

```python
_PLACEHOLDER_PATH = os.path.join(
    os.path.dirname(__file__), "assets", "missing_image_placeholder.png"
)


def _placeholder_bytes():
    """Bytes of the bundled 'missing image' placeholder (package data, §2)."""
    with open(_PLACEHOLDER_PATH, "rb") as f:
        return f.read()


def _placeholder_size():
    return os.path.getsize(_PLACEHOLDER_PATH)


def _placeholder_filename(original):
    """Original filename stem forced to a `.png` extension, falling back to
    `image.png` for an empty stem (§2). Uses os.path.splitext (consistent with
    the extension handling elsewhere in this module)."""
    stem = os.path.splitext(original or "")[0] or "image"
    return f"{stem}.png"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_export.py -k "placeholder" -v`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_transfer_export.py
uv run ruff check --fix courses/transfer/export.py tests/test_transfer_export.py
git add -A
git commit -m "feat(transfer): bundled missing-image placeholder + loader/name helpers"
```

---

### Task 2: Tolerant `build_export` (problems, two-pass, placeholder flag) + unpack migration

**Files:**
- Modify: `courses/transfer/export.py:225-354` (`build_export` rewrite; `write_archive` updated for the new shapes + placeholder bytes)
- Modify: `tests/test_transfer_export.py` (migrate 3-tuple unpacks; add tolerance/ordering tests)
- Modify: `tests/test_transfer_import.py`, `tests/test_transfer_subtree.py` (migrate `build_export` unpack + `dict(...)` sites)
- Test: `tests/test_transfer_export.py`

**Interfaces:**
- Consumes: Task 1's `_placeholder_size`, `_placeholder_filename`, `_placeholder_bytes`; `MediaIdMap`, `serialize_element_data`.
- Produces:
  - `build_export(course, node=None, source_host="") -> (manifest, document, media_assets, problems)`.
  - `media_assets` = list of `(mid, asset, is_placeholder: bool)`; dropped assets absent.
  - `problems` = list of dicts (`missing_image` / `dropped_video` / `broken_element`) ordered first-seen in the unit/element walk (§1).
  - `write_archive(course, node, fileobj, source_host="")` unchanged signature; now writes placeholder bytes for `is_placeholder` entries.

- [ ] **Step 1: Migrate existing 3-tuple unpack sites** (so the suite compiles under the new shape)

In `tests/test_transfer_export.py` change the four `build_export` unpacks:
- line ~215 `manifest, doc, media = build_export(course)` → `manifest, doc, media, _problems = build_export(course)`
- line ~242 `_manifest, doc, media = build_export(course)` → `_manifest, doc, media, _problems = build_export(course)`
- line ~251 `_manifest, doc, _media = build_export(course)` → `_manifest, doc, _media, _problems = build_export(course)`
- line ~257 `manifest, doc, _media = build_export(course, node=chap)` → `manifest, doc, _media, _problems = build_export(course, node=chap)`
- Any assertion that iterates `media` as `(mid, asset)` pairs (e.g. `media[0][1] == image_asset`) still works — `media_assets[i]` is now a 3-tuple, so `media[0][1]` is still the asset. Leave those. If any test does `for mid, asset in media:` change it to `for mid, asset, _ in media:`.

In `tests/test_transfer_import.py`:
- lines ~216-217 `_mani1, src_doc, src_media_items = build_export(source_course)` → `_mani1, src_doc, src_media_items, _p = build_export(source_course)` (same for the `imported_course` line).
- lines ~237-238 `src_by_id = dict(src_media_items)` → `src_by_id = {mid: asset for mid, asset, _ in src_media_items}` (same for `imp_by_id`). A bare `dict()` over 3-tuples raises `ValueError`.

In `tests/test_transfer_subtree.py`:
- lines ~121-122 `build_export(...)` unpacks → add `, _p` 4th value.
- lines ~140-141 `dict(src_media_items)` / `dict(tgt_media_items)` → `{mid: asset for mid, asset, _ in <items>}`.

- [ ] **Step 2: Write the failing tolerance tests** (append to `tests/test_transfer_export.py`)

Reuse the file's existing fixtures (`course`, `image_asset`, `_mk_tree`, `_attach`) and the element imports already at the top of this file (`ImageElement`, `VideoElement`, `TextElement`, `MediaAsset`, `ContentNode`, `Element`, `SimpleUploadedFile` are all imported from the main-feature tests — do NOT re-import them; ruff `--fix` flags duplicates/unused). Note `image_asset` writes to `settings.MEDIA_ROOT = tmp_path` (an existing fixture) — to simulate a *missing* file, delete it from storage after creation.

```python
# --- Task 2: tolerant build_export ---
def _delete_asset_file(asset):
    """Remove the backing file but keep the MediaAsset row (orphaned FileField)."""
    asset.file.storage.delete(asset.file.name)


def test_missing_image_becomes_placeholder_with_problem(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset, alt="a"))
    _delete_asset_file(image_asset)
    _manifest, doc, media_assets, problems = build_export(course)
    # element kept, still references the media
    assert [e["type"] for e in doc["elements"]] == ["image"]
    assert doc["elements"][0]["data"]["media"] == "m1"
    # media entry kept, flagged placeholder, forced .png name
    assert len(doc["media"]) == 1
    assert doc["media"][0]["file"] == "media/m1.png"
    assert doc["media"][0]["original_filename"].endswith(".png")
    assert media_assets == [("m1", image_asset, True)]
    assert problems == [
        {"type": "missing_image", "filename": image_asset.original_filename, "units": ["U1"]}
    ]


def test_missing_image_lists_all_referencing_units(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    # two DIFFERENT units, both referencing the same (missing) image asset
    part = ContentNode.objects.create(course=course, kind="part", title="P")
    u1 = ContentNode.objects.create(course=course, kind="unit", title="Bonus", parent=part, unit_type="lesson")
    u2 = ContentNode.objects.create(course=course, kind="unit", title="Bonus", parent=part, unit_type="lesson")
    Element.objects.create(unit=u1, title="", content_object=ImageElement.objects.create(media=image_asset))
    Element.objects.create(unit=u2, title="", content_object=ImageElement.objects.create(media=image_asset))
    _delete_asset_file(image_asset)
    _m, _doc, _ma, problems = build_export(course)
    assert len(problems) == 1
    assert problems[0]["type"] == "missing_image"
    # two distinct units both listed (dedupe is by pk; same title appears twice — accepted)
    assert problems[0]["units"] == ["Bonus", "Bonus"]


def test_missing_video_file_drops_element_with_problem(course, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    vid = MediaAsset.objects.create(
        course=course, kind="video",
        file=SimpleUploadedFile("clip.mp4", b"\x00\x00\x00\x18ftyp"),
        original_filename="clip.mp4",
    )
    part, chap, unit = _mk_tree(course)
    _attach(unit, VideoElement.objects.create(media=vid))
    _delete_asset_file(vid)
    _m, doc, media_assets, problems = build_export(course)
    # element dropped, media omitted
    assert doc["elements"] == []
    assert doc["media"] == []
    assert media_assets == []
    assert problems == [
        {"type": "dropped_video", "filename": "clip.mp4", "units": ["U1"]}
    ]


def test_broken_element_dropped_with_problem(course):
    part, chap, unit = _mk_tree(course)
    concrete = TextElement.objects.create(body="hi")
    join = _attach(unit, concrete)
    # sever the GFK: delete the concrete row, leaving the join dangling
    TextElement.objects.filter(pk=concrete.pk).delete()
    _m, doc, media_assets, problems = build_export(course)
    assert doc["elements"] == []
    assert problems == [{"type": "broken_element", "units": ["U1"]}]


def test_cross_type_problem_ordering_is_walk_order(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    # order in the unit: broken text, then missing image, then missing video
    t = TextElement.objects.create(body="x")
    _attach(unit, t)
    TextElement.objects.filter(pk=t.pk).delete()  # -> broken (walk 1)
    _attach(unit, ImageElement.objects.create(media=image_asset))  # -> missing_image (walk 2)
    vid = MediaAsset.objects.create(
        course=course, kind="video",
        file=SimpleUploadedFile("clip.mp4", b"x"), original_filename="clip.mp4",
    )
    _attach(unit, VideoElement.objects.create(media=vid))  # -> dropped_video (walk 3)
    _delete_asset_file(image_asset)
    _delete_asset_file(vid)
    _m, _doc, _ma, problems = build_export(course)
    assert [p["type"] for p in problems] == ["broken_element", "missing_image", "dropped_video"]


def test_kept_element_ids_contiguous_despite_skips(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    t = TextElement.objects.create(body="x")
    _attach(unit, t)
    TextElement.objects.filter(pk=t.pk).delete()  # broken -> skipped
    _attach(unit, TextElement.objects.create(body="keep1"))
    _attach(unit, TextElement.objects.create(body="keep2"))
    _m, doc, _ma, _p = build_export(course)
    assert [e["id"] for e in doc["elements"]] == ["e1", "e2"]  # no gap from the skipped one


def test_healthy_course_has_no_problems_and_false_placeholder_flags(course, image_asset):
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    _m, doc, media_assets, problems = build_export(course)
    assert problems == []
    assert media_assets == [("m1", image_asset, False)]
    assert doc["media"][0]["file"] == "media/m1.png"  # real .png asset keeps its ext
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_export.py -v`
Expected: the new tolerance tests FAIL (current `build_export` returns a 3-tuple and raises on missing media); some may error on the 4-value unpack until Step 4.

- [ ] **Step 4: Rewrite `build_export`** — replace the body of `build_export` (export.py:225-339) with the two-pass, tolerant version:

```python
def build_export(course, node=None, source_host=""):
    with transaction.atomic():
        nodes = _ordered_nodes(course, root=node)
        node_ids = {}
        node_dicts = []
        for i, n in enumerate(nodes, start=1):
            nid = f"n{i}"
            node_ids[n.pk] = nid
            parent_internal = (
                None
                if (node is not None and n.pk == node.pk)
                else node_ids.get(n.parent_id)
            )
            node_dicts.append(_node_dict(n, nid, parent_internal))

        media_ids = MediaIdMap()
        unit_pks = [n.pk for n in nodes if n.kind == "unit"]
        joins_by_unit = {}
        for join in (
            Element.objects.filter(unit_id__in=unit_pks)
            .order_by("unit_id", "order", "pk")
            .prefetch_related("content_object")
        ):
            joins_by_unit.setdefault(join.unit_id, []).append(join)

        # Pass 2: walk elements. walk_index counts EVERY join (incl. skipped
        # broken ones) so all problem types share one ordering space (§1).
        pending = []  # (walk_index, element_dict_without_id, ref_mid_or_None)
        broken = []  # (walk_index, unit_title)
        mid_refs = {}  # mid -> [(walk_index, unit_pk, unit_title), ...] first-seen
        walk_index = 0
        for n in nodes:
            for join in joins_by_unit.get(n.pk, []):
                walk_index += 1
                if join.content_object is None:  # dangling GFK: concrete row gone
                    broken.append((walk_index, n.title))
                    continue
                type_key, data = serialize_element_data(join.content_object, media_ids)
                ref_mid = data.get("media")  # scalar mid or None (url video / non-media types)
                if ref_mid is not None:
                    mid_refs.setdefault(ref_mid, []).append(
                        (walk_index, n.pk, n.title)
                    )
                pending.append(
                    (
                        walk_index,
                        {
                            "unit": node_ids[n.pk],
                            "title": join.title,
                            "type": type_key,
                            "data": data,
                        },
                        ref_mid,
                    )
                )

        # Pass 3: resolve each distinct registered asset's FINAL status here,
        # combining storage.exists() with a guarded .size (§1 step 3).
        status = {}  # mid -> "real" | "placeholder" | "dropped"
        total_bytes = 0
        for mid, asset in media_ids.items():
            present = bool(asset.file.name) and asset.file.storage.exists(
                asset.file.name
            )
            if present:
                try:
                    total_bytes += asset.file.size
                    status[mid] = "real"
                except OSError:  # present-but-unreadable -> treat as missing
                    present = False
            if not present:
                if asset.kind == "image":
                    status[mid] = "placeholder"
                    total_bytes += _placeholder_size()
                else:
                    status[mid] = "dropped"

        # Pass 4: emit elements (exclude those referencing a dropped mid);
        # assign e-ids over kept elements only (no gaps, §1 step 4).
        element_dicts = []
        eidx = 0
        for _wi, edict, ref_mid in pending:
            if ref_mid is not None and status.get(ref_mid) == "dropped":
                continue
            eidx += 1
            element_dicts.append({"id": f"e{eidx}", **edict})

        # Pass 5: emit media (exclude dropped); flag placeholders. Mids may be
        # non-contiguous after a drop and are NOT renumbered (§1 step 5).
        media_dicts = []
        media_assets = []
        for mid, asset in media_ids.items():
            if status[mid] == "dropped":
                continue
            is_placeholder = status[mid] == "placeholder"
            if is_placeholder:
                ofn = _placeholder_filename(asset.original_filename)
                ext = ".png"
            else:
                ofn = asset.original_filename
                ext = os.path.splitext(asset.original_filename)[1].lower()
            media_dicts.append(
                {
                    "id": mid,
                    "kind": "image" if is_placeholder else asset.kind,
                    "name": asset.name,
                    "original_filename": ofn,
                    "file": f"media/{mid}{ext}",
                }
            )
            media_assets.append((mid, asset, is_placeholder))

        # Build the problems list, then stable-sort by walk index (§1 ordering).
        def _units_for(mid):
            seen = set()
            out = []
            for _wi, upk, ut in mid_refs[mid]:
                if upk not in seen:
                    seen.add(upk)
                    out.append(ut)
            return out

        asset_by_mid = dict(media_ids.items())
        problems = []
        for wi, unit_title in broken:
            problems.append({"__wi": wi, "type": "broken_element", "units": [unit_title]})
        for mid, refs in mid_refs.items():
            if status[mid] == "placeholder":
                ptype = "missing_image"
            elif status[mid] == "dropped":
                ptype = "dropped_video"
            else:
                continue
            asset = asset_by_mid[mid]
            problems.append(
                {
                    "__wi": refs[0][0],
                    "type": ptype,
                    "filename": asset.original_filename,
                    "units": _units_for(mid),
                }
            )
        problems.sort(key=lambda p: p["__wi"])  # stable; walk-order across types
        problems = [{k: v for k, v in p.items() if k != "__wi"} for p in problems]

        if node is None:
            head = {
                "course": {
                    "title": course.title,
                    "language": course.language,
                    "overview": course.overview,
                    "html_css": course.html_css,
                    "html_js": course.html_js,
                    "uses_parts": course.uses_parts,
                    "uses_chapters": course.uses_chapters,
                    "uses_sections": course.uses_sections,
                    "color_bands": course.color_bands,
                    "subjects": [
                        {"title_en": s.title_en, "title_pl": s.title_pl}
                        for s in course.subjects.all().order_by("title_en", "pk")
                    ],
                }
            }
        else:
            head = {
                "context": {
                    "source_course_title": course.title,
                    "root_kind": node.kind,
                    "required_kinds": sorted({n["kind"] for n in node_dicts}),
                    "html_css": course.html_css,
                    "html_js": course.html_js,
                }
            }

        document = {
            **head,
            "nodes": node_dicts,
            "elements": element_dicts,
            "media": media_dicts,
        }
        manifest = {
            "format_version": FORMAT_VERSION,
            "kind": KIND_COURSE if node is None else KIND_SUBTREE,
            "exported_at": timezone.now().isoformat(),
            "source": {"instance": source_host, "app_version": ""},
            "course": {"title": course.title, "slug": course.slug},
            "media_total_bytes": total_bytes,
        }
        if node is not None:
            manifest["node"] = {"title": node.title, "kind": node.kind}
        return manifest, document, media_assets, problems
```

Note: `dict(media_ids.items())[mid]` re-looks-up the asset for the problem's filename; `media_ids.items()` is a small list, so this is fine. The `TransferError`/`_` import stays (still used elsewhere in the module); the old `raise TransferError(...)` blocks are gone.

- [ ] **Step 5: Update `write_archive`** for the 4-tuple + placeholder bytes (export.py:342-354):

```python
def write_archive(course, node, fileobj, source_host=""):
    manifest, document, media_assets, _problems = build_export(course, node, source_host)
    entry_by_mid = {m["id"]: m["file"] for m in document["media"]}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("course.json", json.dumps(document, ensure_ascii=False))
        for mid, asset, is_placeholder in media_assets:
            if is_placeholder:
                zf.writestr(entry_by_mid[mid], _placeholder_bytes())
                continue
            with asset.file.open("rb") as src, zf.open(entry_by_mid[mid], "w") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_export.py -v` — PASS (existing + new).
Then the migrated files: `uv run pytest tests/test_transfer_import.py tests/test_transfer_subtree.py -v` — PASS (unpack migration didn't break them).

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_transfer_export.py tests/test_transfer_import.py tests/test_transfer_subtree.py
uv run ruff check --fix courses/transfer/export.py tests/test_transfer_export.py tests/test_transfer_import.py tests/test_transfer_subtree.py
git add -A
git commit -m "feat(transfer): tolerant build_export (placeholder images, drop videos/broken, problems report)"
```

---

### Task 3: Split `write_archive` into `write_archive_from` + wrapper

**Files:**
- Modify: `courses/transfer/export.py` (`write_archive` refactor)
- Test: `tests/test_transfer_export.py` (append)

**Interfaces:**
- Consumes: Task 2's `build_export`, `_placeholder_bytes`.
- Produces: `write_archive_from(manifest, document, media_assets, fileobj) -> None` — writes a pre-built archive; `write_archive(course, node, fileobj, source_host="") -> None` becomes `build_export` + `write_archive_from` (so callers/tests are unaffected).

- [ ] **Step 1: Write the failing test** (append to `tests/test_transfer_export.py`)

```python
# --- Task 3: write_archive_from ---
import io
import zipfile

from courses.transfer.export import write_archive_from


def test_write_archive_from_writes_placeholder_and_omits_dropped(course, image_asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    part, chap, unit = _mk_tree(course)
    _attach(unit, ImageElement.objects.create(media=image_asset))
    vid = MediaAsset.objects.create(
        course=course, kind="video",
        file=SimpleUploadedFile("clip.mp4", b"x"), original_filename="clip.mp4",
    )
    _attach(unit, VideoElement.objects.create(media=vid))
    _delete_asset_file(image_asset)  # -> placeholder
    _delete_asset_file(vid)  # -> dropped
    manifest, document, media_assets, _problems = build_export(course)
    buf = io.BytesIO()
    write_archive_from(manifest, document, media_assets, buf)
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
        assert "media/m1.png" in names  # placeholder image
        assert not any(n.endswith(".mp4") for n in names)  # dropped video absent
        assert zf.read("media/m1.png") == _placeholder_bytes()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_transfer_export.py -k "write_archive_from" -v`
Expected: FAIL — `ImportError: cannot import name 'write_archive_from'`.

- [ ] **Step 3: Refactor `write_archive`** — replace the `write_archive` from Task 2 with the split:

```python
def write_archive_from(manifest, document, media_assets, fileobj):
    """Write a pre-built archive (from build_export) into fileobj."""
    entry_by_mid = {m["id"]: m["file"] for m in document["media"]}
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("course.json", json.dumps(document, ensure_ascii=False))
        for mid, asset, is_placeholder in media_assets:
            if is_placeholder:
                zf.writestr(entry_by_mid[mid], _placeholder_bytes())
                continue
            with asset.file.open("rb") as src, zf.open(entry_by_mid[mid], "w") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)


def write_archive(course, node, fileobj, source_host=""):
    manifest, document, media_assets, _problems = build_export(course, node, source_host)
    write_archive_from(manifest, document, media_assets, fileobj)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_export.py -v` — PASS (the `write_archive` round-trip tests still pass via the wrapper; the new `write_archive_from` test passes).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format courses/transfer/export.py tests/test_transfer_export.py
uv run ruff check --fix courses/transfer/export.py tests/test_transfer_export.py
git add -A
git commit -m "refactor(transfer): split write_archive into write_archive_from + build wrapper"
```

---

### Task 4: Build-once export view + pre-flight page + i18n

**Files:**
- Modify: `courses/views_transfer.py:38-56` (replace `_stream_archive`)
- Create: `templates/courses/manage/export_preview.html`
- Modify: `locale/en/LC_MESSAGES/django.po`, `locale/pl/LC_MESSAGES/django.po` (+ compile `.mo`)
- Test: `tests/test_transfer_views.py` (append)

**Interfaces:**
- Consumes: Task 2 `build_export`, Task 3 `write_archive_from`; `export_filename`, `TransferError`, `can_manage_course` (all already imported in `views_transfer.py`).
- Produces: `export_course`/`export_subtree` unchanged signatures; both now scan-and-branch via a rewritten `_stream_archive`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_transfer_views.py`)

Reuse the file's existing `owner`/`outsider`/`course` fixtures and its `settings.MEDIA_ROOT`/`TRANSFER_STAGING_DIR` autouse fixture. Add a helper to seed a missing-media image in the course's unit.

```python
# --- Task 4: tolerant export views ---
from courses.models import Element as JoinElement
from courses.models import ImageElement
from courses.models import MediaAsset


def _seed_missing_image(course):
    from django.core.files.uploadedfile import SimpleUploadedFile

    unit = course.nodes.filter(kind="unit").first()
    asset = MediaAsset.objects.create(
        course=course, kind="image",
        file=SimpleUploadedFile("demo.png", b"\x89PNG fake"),
        original_filename="demo.png",
    )
    JoinElement.objects.create(
        unit=unit, title="", content_object=ImageElement.objects.create(media=asset)
    )
    asset.file.storage.delete(asset.file.name)  # orphan the file
    return asset


def test_export_with_missing_media_shows_preflight_page(client, owner, course):
    _seed_missing_image(course)
    client.force_login(owner)
    resp = client.get(reverse("courses:manage_course_export", args=[course.slug]))
    assert resp.status_code == 200
    assert "attachment" not in resp.get("Content-Disposition", "")
    assert b"demo.png" in resp.content  # names the missing file


def test_export_confirm_streams_zip_with_placeholder(client, owner, course):
    _seed_missing_image(course)
    client.force_login(owner)
    url = reverse("courses:manage_course_export", args=[course.slug])
    resp = client.get(url, {"confirm": "1"})
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment;")
    body = b"".join(resp.streaming_content)
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        assert "media/m1.png" in zf.namelist()


def test_healthy_export_streams_directly_no_page(client, owner, course):
    # course fixture has a unit but no media -> no problems
    client.force_login(owner)
    resp = client.get(reverse("courses:manage_course_export", args=[course.slug]))
    assert resp.status_code == 200
    assert resp["Content-Disposition"].startswith("attachment;")


def test_subtree_export_with_missing_media_preflight_then_confirm(client, owner, course):
    node = course.nodes.filter(kind="unit").first()
    _seed_missing_image(course)
    client.force_login(owner)
    url = reverse("courses:manage_node_export", args=[course.slug, node.pk])
    # preview
    resp = client.get(url)
    assert resp.status_code == 200
    assert "attachment" not in resp.get("Content-Disposition", "")
    # confirm streams the subtree zip (flow-agnostic ?confirm=1 link)
    resp2 = client.get(url, {"confirm": "1"})
    assert resp2["Content-Disposition"].startswith("attachment;")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transfer_views.py -k "preflight or confirm or healthy or subtree_export_with" -v`
Expected: FAIL — the current `_stream_archive` streams unconditionally (no preview page; missing media currently redirects), and `export_preview.html` doesn't exist.

- [ ] **Step 3: Replace `_stream_archive`** (views_transfer.py:38-56) with the build-once flow:

```python
def _stream_archive(request, course, node):
    # Build ONCE: a residual TransferError -> friendly redirect (never a 500);
    # problems -> pre-flight page (unless confirmed); else stream from the
    # already-built artifacts — no second graph walk (§5).
    try:
        manifest, document, media_assets, problems = build_export(
            course, node, source_host=request.get_host()
        )
    except TransferError as exc:  # residual/unexpected export failure
        messages.error(request, exc.message)
        return redirect("courses:manage_builder", slug=course.slug)

    if problems and request.GET.get("confirm") != "1":
        return render(
            request,
            "courses/manage/export_preview.html",
            {"problems": problems, "course": course},
        )

    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    write_archive_from(manifest, document, media_assets, spool)
    spool.seek(0)
    return FileResponse(
        spool,
        as_attachment=True,
        filename=export_filename(course, node, timezone.localdate()),
        content_type="application/zip",
    )
```

Update the imports at the top of `views_transfer.py` (merge into the existing block): replace `from courses.transfer.export import write_archive` with:

```python
from courses.transfer.export import build_export
from courses.transfer.export import export_filename
from courses.transfer.export import write_archive_from
```

and add `from django.shortcuts import render` if not already imported.

- [ ] **Step 4: Create the pre-flight template** `templates/courses/manage/export_preview.html`

Match the sibling manage templates' structure (`{% extends %}` the same base as `import_preview.html`, `.manage`/`.manage__head`/`.alert`/`.btn` classes — confirm the exact base/classes by opening `templates/courses/manage/import_preview.html` first and mirroring it). Example body:

```django
{% extends "base.html" %}
{% load i18n %}
{% block content %}
<section class="manage">
  <div class="manage__head">
    <h1>{% trans "Export — missing media" %}</h1>
  </div>
  <p class="helptext">
    {% trans "This course can be exported, but some media is missing. Review the items below, then export anyway." %}
  </p>
  <ul class="card-list">
    {% for p in problems %}
      <li class="card">
        {% if p.type == "missing_image" %}
          {% blocktrans with name=p.filename units=p.units|join:", " %}Image “{{ name }}” is missing — it will be exported as a placeholder. Used in: {{ units }}.{% endblocktrans %}
        {% elif p.type == "dropped_video" %}
          {% blocktrans with name=p.filename units=p.units|join:", " %}Video “{{ name }}” is missing — this video block will be left out of the export. In: {{ units }}.{% endblocktrans %}
        {% else %}
          {% blocktrans with units=p.units|join:", " %}A broken content block will be left out of the export. In: {{ units }}.{% endblocktrans %}
        {% endif %}
      </li>
    {% endfor %}
  </ul>
  <div class="row-actions">
    <a class="btn btn--primary" href="{{ request.path }}?confirm=1">{% trans "Export anyway" %}</a>
    <a class="btn btn--ghost" href="{% url 'courses:manage_builder' slug=course.slug %}">{% trans "Cancel" %}</a>
  </div>
</section>
{% endblock %}
```

(If `.card-list`/`.card`/`.row-actions` aren't the classes the sibling manage pages use, substitute the ones they DO use — do not invent new CSS. `{{ p.filename }}`/`{{ units }}` autoescape.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_transfer_views.py -k "preflight or confirm or healthy or subtree_export_with" -v` — PASS.
Then the whole view file (export half must stay green): `uv run pytest tests/test_transfer_views.py -v` — PASS.

- [ ] **Step 6: EN/PL i18n**

```bash
uv run python manage.py makemessages -l en -l pl
```
Then in `locale/pl/LC_MESSAGES/django.po`, translate the new msgids (the export_preview strings), e.g.:
- "Export — missing media" → "Eksport — brakujące multimedia"
- "This course can be exported, but some media is missing. Review the items below, then export anyway." → "Ten kurs można wyeksportować, ale brakuje niektórych multimediów. Przejrzyj poniższe pozycje, a następnie eksportuj mimo to."
- the `Image “{{ name }}” is missing …` blocktrans → the Polish equivalent
- the `Video …` blocktrans → Polish
- the broken-block blocktrans → Polish
- "Export anyway" → "Eksportuj mimo to"
- "Cancel" → "Anuluj"

**WATCH the makemessages `#, fuzzy` gotcha:** makemessages may mark copied translations `#, fuzzy` (ignored at runtime) and can mis-guess a `msgstr`. After editing, `grep -n "fuzzy" locale/pl/LC_MESSAGES/django.po` for any NEW fuzzy flags on these msgids, clear them, and eyeball each new `msgstr`. Also fill the EN `.po` msgids if the repo keeps English translations. Then compile:

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 7: UI verification (light + dark)**

Per house rules, verify the pre-flight page renders correctly in BOTH light and dark themes with a THROWAWAY Playwright screenshot script (log in, seed a missing-media course, GET the export URL, screenshot), then DELETE the script (save screenshots to the scratchpad, not the repo). Confirm no undefined/broken classes.

- [ ] **Step 8: Round-trip test through the import ENGINE** (append to `tests/test_transfer_views.py`)

Drive the import **engine** directly rather than the view's staging/confirm flow (the view's import path is already covered by its own tests; here we only need to prove the exported placeholder archive is importable and yields a real image asset). Signatures: `open_archive(fileobj, *, expected_kind)` (context manager yielding `(zf, manifest, document, media_entries)`), `validate_archive_document(zf, manifest, document, media_entries, *, kind, target_course=None)`, `import_course(zf, manifest, document, media_entries, user)`.

```python
def test_export_placeholder_round_trips_via_import_engine(course, owner, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    _seed_missing_image(course)

    from courses.transfer.export import build_export
    from courses.transfer.export import write_archive_from

    manifest, document, media_assets, problems = build_export(course)
    assert problems  # sanity: this course has a missing-media problem
    buf = io.BytesIO()
    write_archive_from(manifest, document, media_assets, buf)
    buf.seek(0)

    from courses.models import MediaAsset as Asset
    from courses.transfer.importer import import_course
    from courses.transfer.importer import open_archive
    from courses.transfer.importer import validate_archive_document

    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media_entries):
        validate_archive_document(zf, mani, doc, media_entries, kind="course")
        new_course = import_course(zf, mani, doc, media_entries, owner)

    # the placeholder image imported as a real .png image asset on the new course
    assert Asset.objects.filter(course=new_course, kind="image").exists()
```

Run: `uv run pytest tests/test_transfer_views.py -k "round_trips_via_import_engine" -v` — PASS. (If `validate_archive_document`/`import_course` keyword/positional forms differ from the above, confirm against `courses/transfer/importer.py` and an existing import test — do not guess.)

- [ ] **Step 9: Format, lint, commit**

```bash
uv run ruff format courses/views_transfer.py tests/test_transfer_views.py
uv run ruff check --fix courses/views_transfer.py tests/test_transfer_views.py
git add -A
git commit -m "feat(transfer): tolerant export view + pre-flight missing-media page (EN/PL)"
```

---

## Definition of Done (controller runs after Task 4)

- Full suite: `uv run pytest` — exit 0 (controller-run; implementers must NOT run it — watchdog stall).
- `uv run ruff format --check .` and `uv run ruff check .` — clean.
- `uv run python manage.py makemigrations --check --dry-run` — no changes (this feature adds NO model/migration).
- `.mo` compiled; new PL strings verified non-fuzzy.
- Manual/e2e sanity: the reported case — Demo Course (`demo-course`, two "Bonus lesson" units referencing `demo.png`) — GET export → pre-flight page names demo.png + both units → "Export anyway" → downloads a zip whose `media/<mid>.png` is the placeholder.
