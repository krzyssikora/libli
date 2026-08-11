# Media asset replace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third action to the media manager's asset cell — **replace** — that swaps the bytes behind an existing `MediaAsset` while preserving its primary key, so every unit referencing it keeps working with no re-pointing.

**Architecture:** Every consumer of a media asset addresses it by pk (three `PROTECT` FKs, three JSON-pk resolvers); none stores the file path. So the whole feature is one row update plus the disk hygiene that implies: a new `replace_asset` service, a `media_replace` view mirroring `media_upload`, a ⇄ button and hidden file input in the cell template, an inline confirm strip built in JS, and the CSS those need. No model change, therefore **no migration**.

**Tech Stack:** Django (server-rendered templates, no SPA), vanilla ES5-style JS in `media_picker.js`, token-driven CSS in `editor.css`, pytest + pytest-django, Playwright for e2e.

**Spec:** `docs/superpowers/specs/2026-08-11-media-asset-replace-design.md` (977 lines, 8 review rounds). The spec is the authority on *why*; this plan sequences it into verifiable tasks. When the two disagree, the spec wins — but flag the disagreement rather than silently diverging.

---

## Global Constraints

These apply to **every** task. They are not repeated per-task.

**Working directory.** All work happens in the worktree `C:/Users/krzys/Documents/Python/own/.pipeline-worktrees/media-asset-replace`, on branch `pipeline/media-asset-replace` (based on `origin/master`). Never edit the main checkout.

**Tooling is behind `uv run`.** `ruff`, `pytest` and `python` are **not** on PATH. Always `uv run pytest …`, `uv run ruff …`, `uv run python …`.

**Start the test database before the first pytest run of the session:**

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
```

Skipping this makes the suite look **hung for about 4 minutes** before it errors. This is the single most common lost hour in this repo.

**Two test selections.** `pyproject.toml` pins `addopts = "-q -m 'not e2e'"`. So:
- unit/integration: `uv run pytest <paths>`
- e2e: `uv run pytest -m e2e <paths>` — **`-m e2e` is mandatory**; without it every e2e test is deselected and pytest exits **5**, which means "nothing selected", *not* "green".

**Scope every per-task run narrowly** to the files that task touched. A whole-repo sweep is a branch-level gate (Task 7), never a per-task step.

**Falsify tests before trusting them.** For each test the plan marks **FALSIFY**, break the implementation deliberately, confirm the test goes RED for the stated reason, then **edit the mutation back out** — never `git checkout` the file, which would destroy the test you just wrote. A test that has never been RED has not been shown to test anything.

**Never `git add -A` or `git add .`** — always explicit paths. The worktree carries a `pipeline-state.json` in its git dir (not the working tree, so it cannot be staged) but the habit matters anyway.

**Line length is 88** (ruff default here). `# noqa` is parsed anywhere in a comment, and ruff **caches** its warnings — use `--no-cache` when re-checking a fix. `uv run ruff format --check` is a **separate CI gate** from `uv run ruff check`; both must pass.

**Commit after every task**, with the message given in the task's final step. End every commit message with:

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

**No new migration.** This feature changes no model field. If you find yourself running `makemigrations`, stop — something has gone wrong.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `courses/media.py` | modify | `replace_asset` (the swap + all guards) and `_delete_file_if_unshared` (disk hygiene) |
| `courses/views_media.py` | modify | `media_replace` — auth, 404 scoping, key guard, 422/redirect branches |
| `courses/urls.py` | modify | `manage_media_replace` route |
| `templates/courses/manage/media/_asset_cell.html` | modify | ⇄ button, hidden input, `.asset-actions` wrapper, `data-replace-url` / `data-di-uses` |
| `templates/courses/manage/media/manager.html` | modify | the six `data-msg-*` attributes |
| `courses/static/courses/css/editor.css` | modify | foot shrink/truncation, `.asset-actions`, the confirm strip |
| `courses/static/courses/js/media_picker.js` | modify | the fourth op; `flash()` gains `role="alert"` and inserts-then-fills |
| `locale/pl/LC_MESSAGES/django.po` | modify | Polish for the new strings |
| `tests/test_media_replace.py` | **create** | service-level: swap mechanics, disk hygiene, rejections, consumer survival |
| `tests/test_media_manager.py` | modify | view-level: status codes, key guard, kind-ignored, render assertions |
| `tests/test_e2e_media_manager.py` | **create** | browser-level: the strip, cancel, 422, catch-all, mid-flight filter, screenshots |

Task order follows the dependency chain: service → view → template/CSS → JS → e2e → i18n/gate. Each task's tests pass on its own.

---

### Task 1: The `replace_asset` service and its disk hygiene

**Files:**
- Modify: `courses/media.py` (add an import; append two functions after `rename_asset`, before `delete_asset`)
- Test: `tests/test_media_replace.py` (create)

**Interfaces:**
- Consumes: `truncate_filename(name, limit=255)` and the module's `MediaAsset` import, both already in `courses/media.py`.
- Produces:
  - `replace_asset(asset, uploaded_file) -> MediaAsset` — mutates and saves `asset`, returns it. Raises `django.core.exceptions.ValidationError` on an empty file, a wrong-kind extension, or an over-limit size. Task 3's view calls this and catches that exception.
  - `_delete_file_if_unshared(name, storage) -> None` — private; no other module calls it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_media_replace.py`:

```python
"""Service-level tests for replacing a MediaAsset's file in place.

Every test that asserts on a file being deleted or kept builds the asset under
replacement with `make_image_asset` (real PNG bytes through storage). The bare
`MediaAssetFactory` writes a *name* with no bytes behind it, which would make
"the old file is gone" pass on a build where the deletion never ran at all.
Two tests deliberately use a byte-less row, and say so where they do.

`django_capture_on_commit_callbacks(execute=True)` wraps the `replace_asset`
CALL, not the assertion: the deletion is registered via `transaction.on_commit`
during the call, and those callbacks never fire under the plain `db` fixture.
"""

from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from courses import media as media_svc
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import CourseFactory
from tests.factories import MediaAssetFactory
from tests.factories import make_image_asset


def _png(name="new.png", size=(2, 2), color="red"):
    """An uncommitted upload with real PNG bytes.

    Uncommitted matters: `_validate_file` short-circuits on a committed
    FieldFile (courses/validators.py:91), so handing replace_asset an existing
    asset's `.file` would skip BOTH the extension and the size check.
    """
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_replace_preserves_identity_and_swaps_the_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="old.png", name="Cover art")
    asset.content_hash = "deadbeef"
    asset.save(update_fields=["content_hash"])
    element = ImageElement.objects.create(media=asset, alt="a")
    old_name = asset.file.name
    storage = asset.file.storage
    created_before = asset.created
    assert storage.exists(old_name)

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    fresh = MediaAsset.objects.get(pk=asset.pk)
    assert fresh.kind == "image"           # kind is never assigned
    assert fresh.name == "Cover art"       # a custom display name survives
    assert fresh.original_filename == "new.png"
    assert fresh.content_hash == ""        # stale hash cleared, never left wrong
    assert fresh.uploaded_by_id is None    # provenance untouched
    assert fresh.created == created_before
    assert fresh.file.name != old_name
    assert storage.exists(fresh.file.name)
    assert not storage.exists(old_name)    # superseded bytes reclaimed

    element.refresh_from_db()
    assert element.media_id == asset.pk    # the FK never moved


@pytest.mark.django_db
def test_replace_succeeds_when_uploaded_by_is_null(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """The LAL-import shape. A bare full_clean() would 422 the whole imported
    catalogue: uploaded_by is null=True WITHOUT blank=True, so clean_fields()
    raises "This field cannot be blank." on a NULL uploader."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="imported.png")
    assert asset.uploaded_by_id is None  # the condition under test

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    assert MediaAsset.objects.get(pk=asset.pk).original_filename == "new.png"


@pytest.mark.django_db
def test_a_row_sharing_the_old_filename_keeps_the_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """Shared names are reachable in real data: migration 0008 copied storage
    REFERENCES off ImageElement.image, so two elements pointing at one stored
    file produced two rows sharing a name. The decoy must be a literal file=
    row -- make_image_asset always saves through storage, which guarantees a
    UNIQUE name, so two rows sharing one are unconstructible that way."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="shared.png")
    old_name = asset.file.name
    storage = asset.file.storage
    decoy = MediaAssetFactory(course=course, kind="image", file=old_name)

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    assert storage.exists(old_name)  # the decoy still needs it
    assert MediaAsset.objects.get(pk=decoy.pk).file.name == old_name


@pytest.mark.django_db
def test_identical_storage_name_keeps_the_newly_written_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """When the old file is ALREADY missing, get_available_name hands back the
    same name -- so the "old" file IS the one just written. Deleting it would
    leave the row pointing at nothing. This is the second deliberate byte-less
    fixture: a row whose file is absent is the whole subject."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = MediaAssetFactory(
        course=course, kind="image", file="courses/media/same.png"
    )
    storage = asset.file.storage
    assert not storage.exists("courses/media/same.png")

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("same.png"))

    fresh = MediaAsset.objects.get(pk=asset.pk)
    assert fresh.file.name == "courses/media/same.png"
    assert storage.exists(fresh.file.name)  # NOT deleted by its own cleanup


@pytest.mark.django_db
def test_missing_old_file_does_not_raise(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="lost.png")
    old_name = asset.file.name
    asset.file.storage.delete(old_name)  # bytes lost after the row was made

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("new.png"))

    assert MediaAsset.objects.get(pk=asset.pk).original_filename == "new.png"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_media_replace.py -v
```

Expected: 5 FAILED with `AttributeError: module 'courses.media' has no attribute 'replace_asset'`.

- [ ] **Step 3: Write the implementation**

In `courses/media.py`, add to the imports (keep the one-import-per-line style already in the file, and the alphabetical grouping — this goes above `from django.db import transaction`):

```python
from django.core.exceptions import ValidationError
```

Then append these two functions **after** `rename_asset` and **before** `delete_asset`:

```python
def _delete_file_if_unshared(name, storage):
    """Drop a superseded file from storage, unless another MediaAsset row still
    points at the same name.

    courses/signals.py's post_delete receiver has no such guard: it keys on
    file.name alone, so two rows sharing a name share a lifetime. Migration
    0008 copied storage references verbatim, so shared names exist in real data.
    Deferred via on_commit for the same reason the signal defers -- a
    rolled-back replace must not strand a live row whose file is already gone.
    """
    if not name:
        return
    if MediaAsset.objects.filter(file=name).exists():
        return

    def _remove():
        if storage.exists(name):
            storage.delete(name)

    transaction.on_commit(_remove)


@transaction.atomic
def replace_asset(asset, uploaded_file):
    """Swap the bytes behind an existing asset, preserving pk, kind and name so
    every element referencing it is untouched. The superseded file is removed.

    `uploaded_file` MUST be an uncommitted upload (an InMemory/TemporaryUploaded
    File). _validate_file short-circuits on a committed FieldFile, so passing
    one would skip BOTH the extension and the size check.
    """
    if not uploaded_file.size:
        # MediaAsset.clean() has no LOWER size bound -- only the upload FORM
        # rejects an empty file. Without this a 0-byte upload would validate,
        # commit, and destroy the old bytes with no undo.
        raise ValidationError(_("The submitted file is empty."))
    old_name = asset.file.name
    old_storage = asset.file.storage
    asset.file = uploaded_file
    asset.original_filename = truncate_filename(uploaded_file.name)
    asset.content_hash = ""  # a STALE hash would mis-dedup a later LAL import
    # Validate exactly what this writes. `uploaded_by` is the load-bearing
    # exclusion: null=True WITHOUT blank=True, so clean_fields() raises "This
    # field cannot be blank." for every LAL-imported / migrated / seeded row.
    # course/kind/name would pass anyway and are listed to express the rule.
    # `created` is deliberately NOT listed: auto_now_add makes it
    # editable=False, so Field.validate() early-returns and excluding it would
    # be a no-op that reads as load-bearing. clean() runs regardless of
    # `exclude` and still branches on the untouched self.kind, which is where
    # the per-kind extension/size validation lives.
    asset.full_clean(exclude=["course", "kind", "name", "uploaded_by"])
    asset.save(update_fields=["file", "original_filename", "content_hash"])
    # Storage hands back the SAME name when the old file was already missing,
    # in which case the "old" file is the one just written.
    if asset.file.name != old_name:
        _delete_file_if_unshared(old_name, old_storage)
    return asset
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_media_replace.py -v
```

Expected: 5 passed.

- [ ] **Step 5: FALSIFY the two disk-hygiene guards**

These two are the tests most likely to pass for the wrong reason, so prove each one RED.

1. **Shared-filename guard.** In `_delete_file_if_unshared`, comment out the two `MediaAsset.objects.filter(...)` lines (the early return). Run
   `uv run pytest tests/test_media_replace.py::test_a_row_sharing_the_old_filename_keeps_the_file -v`.
   Expected: **FAILS** on `assert storage.exists(old_name)` — the decoy's file was destroyed. Now **edit the lines back in** (do not `git checkout`).

2. **Identical-name guard.** In `replace_asset`, change `if asset.file.name != old_name:` to `if True:`. Run
   `uv run pytest tests/test_media_replace.py::test_identical_storage_name_keeps_the_newly_written_file -v`.
   Expected: **FAILS** on `assert storage.exists(fresh.file.name)` — the row now points at a file its own cleanup deleted. **Edit it back.**

3. Re-run the whole file to confirm you restored both:
   `uv run pytest tests/test_media_replace.py -v` → 5 passed.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check --no-cache courses/media.py tests/test_media_replace.py
uv run ruff format --check courses/media.py tests/test_media_replace.py
git add courses/media.py tests/test_media_replace.py
git commit -m "feat(media): replace an asset's file in place, preserving its pk

Swap the bytes behind a MediaAsset while keeping the row, so every element
referencing it keeps working. Guards the superseded-file deletion against a
shared filename and against storage handing back the same name.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Rejections and consumer survival

Pure test task — no implementation change is expected. If any test here fails, you have found a real defect in Task 1; fix it there rather than weakening the assertion.

**Files:**
- Test: `tests/test_media_replace.py` (append)

**Interfaces:**
- Consumes: `replace_asset` and the `_png` helper from Task 1.
- Produces: nothing new.

- [ ] **Step 1: Write the rejection tests**

Append to `tests/test_media_replace.py`. Add these imports at the top of the file alongside the existing ones:

```python
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import GalleryElement
from courses.models import TableElement
from courses.models import VideoElement
```

Then:

```python
def _video_asset(course, filename="v.mp4"):
    """A kind="video" asset with real bytes.

    make_image_asset cannot build this -- it hard-codes a PNG and splats **kw
    into create() -- and MediaAssetFactory(kind="video") would still name its
    file courses/media/test-N.png with no bytes behind it.
    """
    return MediaAsset.objects.create(
        course=course,
        kind="video",
        file=SimpleUploadedFile(filename, b"\x00" * 256, content_type="video/mp4"),
        original_filename=filename,
    )


def _assert_untouched(asset, old_name, old_original, old_hash):
    """Re-FETCH: the service leaves the in-memory instance mutated, so asserting
    on the object we just passed in would test nothing."""
    fresh = MediaAsset.objects.get(pk=asset.pk)
    assert fresh.file.name == old_name
    assert fresh.original_filename == old_original
    assert fresh.content_hash == old_hash
    assert fresh.file.storage.exists(old_name)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad,reason",
    [
        (lambda: SimpleUploadedFile("e.png", b"", content_type="image/png"), "empty"),
        (
            lambda: SimpleUploadedFile(
                "v.mp4", b"\x00" * 256, content_type="video/mp4"
            ),
            "wrong extension for kind=image",
        ),
    ],
)
def test_rejected_upload_leaves_the_row_and_the_old_file_untouched(
    settings, tmp_path, bad, reason
):
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="keep.png")
    asset.content_hash = "abc123"
    asset.save(update_fields=["content_hash"])
    old_name = asset.file.name

    with pytest.raises(ValidationError):
        media_svc.replace_asset(asset, bad())

    _assert_untouched(asset, old_name, "keep.png", "abc123")


@pytest.mark.django_db
def test_png_onto_a_video_asset_is_rejected(settings, tmp_path):
    """The mirror of the .mp4-onto-image case. kind is never assigned, so
    MediaAsset.clean() still branches on "video" and runs validate_video_file."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = _video_asset(course)
    old_name = asset.file.name

    with pytest.raises(ValidationError):
        media_svc.replace_asset(asset, _png("still.png"))

    _assert_untouched(asset, old_name, "v.mp4", "")


@pytest.mark.django_db
def test_oversize_upload_is_rejected(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    from courses.validators import effective_max_image_bytes

    course = CourseFactory()
    asset = make_image_asset(course, filename="keep.png")
    old_name = asset.file.name
    huge = SimpleUploadedFile(
        "huge.png",
        b"\x89PNG\r\n\x1a\n" + b"0" * (effective_max_image_bytes() + 1),
        content_type="image/png",
    )

    with pytest.raises(ValidationError):
        media_svc.replace_asset(asset, huge)

    _assert_untouched(asset, old_name, "keep.png", "")
```

- [ ] **Step 2: Run them**

```bash
uv run pytest tests/test_media_replace.py -v
```

Expected: all pass. If the oversize test errors on `effective_max_image_bytes` being large enough to exhaust memory, reduce it by overriding the admin-configured limit in the test instead of allocating the real size — but check the current effective value first; it is a few MiB, not gigabytes.

- [ ] **Step 3: FALSIFY the "untouched" assertions**

`_assert_untouched` is the classic assertion that passes for the wrong reason. In `replace_asset`, move the `asset.save(...)` line to **above** `asset.full_clean(...)`. Run
`uv run pytest tests/test_media_replace.py -k rejected -v`.
Expected: **FAILS** — the row was written before validation rejected it. **Edit the order back.**

- [ ] **Step 4: Write the consumer-survival tests**

```python
@pytest.mark.django_db
def test_video_replace_preserves_kind_and_the_fk(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = _video_asset(course)
    element = VideoElement.objects.create(media=asset)

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(
            asset,
            SimpleUploadedFile("new.mp4", b"\x00" * 512, content_type="video/mp4"),
        )

    fresh = MediaAsset.objects.get(pk=asset.pk)
    assert fresh.kind == "video"
    assert fresh.original_filename == "new.mp4"
    element.refresh_from_db()
    assert element.media_id == asset.pk


@pytest.mark.django_db
def test_drag_to_image_keeps_its_media_and_all_its_zones(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """The one consumer a replace can silently DEGRADE: DragZone x/y/w/h are
    fractions 0..1 of the image, so a different aspect ratio moves the zones.
    The rows must at least survive intact -- warn-and-allow, never mangle."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="diagram.png")
    question = DragToImageQuestionElement.objects.create(
        media=asset, alt="Diagram", distractors=""
    )
    DragZone.objects.create(
        question=question, correct_label="A", x=0.1, y=0.2, w=0.3, h=0.4, order=0
    )
    DragZone.objects.create(
        question=question, correct_label="B", x=0.6, y=0.6, w=0.2, h=0.2, order=1
    )

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("redrawn.png", size=(8, 4)))

    question.refresh_from_db()
    assert question.media_id == asset.pk
    zones = list(question.zones.all())
    assert [z.correct_label for z in zones] == ["A", "B"]
    assert (zones[0].x, zones[0].y, zones[0].w, zones[0].h) == (0.1, 0.2, 0.3, 0.4)


@pytest.mark.django_db
def test_json_pk_consumers_resolve_to_the_new_file(
    settings, tmp_path, django_capture_on_commit_callbacks
):
    """Gallery and table cells store the PK inside JSON `data` and resolve it at
    render time -- no FK, so they appear in no usage count. Both are asserted:
    they are separate code paths. Note the asymmetry -- TableElement
    .resolved_cells is a @property but GalleryElement.resolved_images is a
    METHOD, so `el.resolved_images` without () is a truthy bound method and
    would assert nothing."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="shown.png")
    gallery = GalleryElement.objects.create(
        data={"images": [{"media": asset.pk, "desc": ""}], "desc_pos": "below"}
    )
    table = TableElement.objects.create(
        data={"cells": [[{"kind": "image", "media": asset.pk, "alt": "a"}]]}
    )

    with django_capture_on_commit_callbacks(execute=True):
        media_svc.replace_asset(asset, _png("swapped.png"))

    new_name = MediaAsset.objects.get(pk=asset.pk).file.name
    gallery.refresh_from_db()
    table.refresh_from_db()
    assert gallery.resolved_images()[0]["media"].file.name == new_name
    assert table.resolved_cells[0][0]["media"].file.name == new_name
```

- [ ] **Step 5: Run and lint**

```bash
uv run pytest tests/test_media_replace.py -v
uv run ruff check --no-cache tests/test_media_replace.py
uv run ruff format --check tests/test_media_replace.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_media_replace.py
git commit -m "test(media): cover replace rejections and every consumer's survival

Rejections (empty, wrong kind both ways, oversize) assert the RE-FETCHED row
and the old file are untouched. Survival covers all six consumers: the three
PROTECT FKs plus the three JSON-pk resolvers, including DragZone coordinates.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The view and its URL

**Files:**
- Modify: `courses/views_media.py` (add an import; append `media_replace` after `media_delete`)
- Modify: `courses/urls.py` (add a route inside the media block, currently lines 271-296)
- Test: `tests/test_media_manager.py` (append)

**Interfaces:**
- Consumes: `media_svc.replace_asset` (Task 1); the module's existing `_require_manage`, `_wants_fragment`, `media_svc.attach_usage`.
- Produces: URL name `courses:manage_media_replace`, kwargs `{slug, pk}`, path `manage/courses/<slug>/media/<pk>/replace/`. Tasks 4 and 6 reverse this name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_media_manager.py`. Add to that file's existing imports:

```python
from tests.factories import make_image_asset
```

Then:

```python
# ---------------------------------------------------------------------------
# Replace endpoint
# ---------------------------------------------------------------------------


def _replace_url(course, asset):
    return reverse(
        "courses:manage_media_replace",
        kwargs={"slug": course.slug, "pk": asset.pk},
    )


def _upload_png(name="new.png"):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (2, 2), "red").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_replace_rejects_get_before_authentication(client, settings, tmp_path):
    """@require_POST sits ABOVE @login_required, so a non-POST is a 405 whether
    or not anyone is logged in. An ANONYMOUS get is the only case that can
    falsify the ordering -- a logged-in GET is 405 under either order."""
    settings.MEDIA_ROOT = str(tmp_path)
    course = CourseFactory()
    asset = make_image_asset(course, filename="x.png")
    r = client.get(_replace_url(course, asset))
    assert r.status_code == 405  # NOT a 302 to the login page


@pytest.mark.django_db
def test_replace_requires_manage_rights(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    make_pa(client, "pa-repl-owner")
    course = CourseFactory()  # owned by someone else
    asset = make_image_asset(course, filename="x.png")
    r = client.post(
        _replace_url(course, asset),
        {"file": _upload_png()},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert r.status_code in (403, 302)


@pytest.mark.django_db
def test_replace_404s_for_an_asset_in_another_course(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-404")
    mine = CourseFactory(owner=pa, slug="mine-repl")
    theirs = CourseFactory(slug="theirs-repl")
    stranger = make_image_asset(theirs, filename="x.png")
    url = reverse(
        "courses:manage_media_replace",
        kwargs={"slug": mine.slug, "pk": stranger.pk},
    )
    r = client.post(url, {"file": _upload_png()}, HTTP_X_REQUESTED_WITH="fetch")
    assert r.status_code == 404


@pytest.mark.django_db
def test_replace_without_a_file_key_is_422_not_500(client, settings, tmp_path):
    """The guard tests the KEY, not request.FILES emptiness: a multipart POST
    under a different field name would pass an emptiness check and then raise
    MultiValueDictKeyError -- a 500 -- on the access."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-nofile")
    course = CourseFactory(owner=pa, slug="nofile-repl")
    asset = make_image_asset(course, filename="x.png")
    url = _replace_url(course, asset)

    assert client.post(url, {}, HTTP_X_REQUESTED_WITH="fetch").status_code == 422
    wrong_key = client.post(
        url, {"upload": _upload_png()}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert wrong_key.status_code == 422


@pytest.mark.django_db
def test_replace_returns_the_rerendered_cell(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-ok")
    course = CourseFactory(owner=pa, slug="ok-repl")
    asset = make_image_asset(course, filename="old.png", name="Cover art")

    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(
            _replace_url(course, asset),
            {"file": _upload_png("brand-new.png")},
            HTTP_X_REQUESTED_WITH="fetch",
        )

    assert r.status_code == 200
    body = r.content.decode()
    assert "brand-new.png" in body       # original_filename followed the file
    assert "Cover art" in body           # the custom display name survived
    assert 'data-replace-url="' in body  # the cell can be replaced again


@pytest.mark.django_db
def test_replace_ignores_a_client_supplied_kind(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    """The single reason the view does NOT reuse MediaAssetForm (fields are
    ["kind", "file"]). Without this test a future refactor could reintroduce a
    client-controlled kind -- flipping an in-use image asset to video and
    breaking limit_choices_to for three FK models -- with the suite green."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-kind")
    course = CourseFactory(owner=pa, slug="kind-repl")
    asset = make_image_asset(course, filename="old.png")

    with django_capture_on_commit_callbacks(execute=True):
        r = client.post(
            _replace_url(course, asset),
            {"file": _upload_png(), "kind": "video"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

    assert r.status_code == 200
    asset.refresh_from_db()
    assert asset.kind == "image"


@pytest.mark.django_db
def test_replace_with_a_rejected_file_is_422_with_the_validator_message(
    client, settings, tmp_path
):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-bad")
    course = CourseFactory(owner=pa, slug="bad-repl")
    asset = make_image_asset(course, filename="old.png")
    mp4 = SimpleUploadedFile("v.mp4", b"\x00" * 256, content_type="video/mp4")

    r = client.post(
        _replace_url(course, asset), {"file": mp4}, HTTP_X_REQUESTED_WITH="fetch"
    )

    assert r.status_code == 422
    assert "mp4" in r.content.decode().lower()
    asset.refresh_from_db()
    assert asset.original_filename == "old.png"


@pytest.mark.django_db
def test_replace_without_the_fetch_header_redirects(
    client, settings, tmp_path, django_capture_on_commit_callbacks
):
    """The no-JS path. Every branch carries its own _wants_fragment check, so a
    header-less POST redirects whichever branch it lands in."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-nojs")
    course = CourseFactory(owner=pa, slug="nojs-repl")
    asset = make_image_asset(course, filename="old.png")
    target = reverse("courses:manage_media", kwargs={"slug": course.slug})

    with django_capture_on_commit_callbacks(execute=True):
        ok = client.post(_replace_url(course, asset), {"file": _upload_png()})
    assert ok.status_code == 302 and ok["Location"] == target

    missing = client.post(_replace_url(course, asset), {})
    assert missing.status_code == 302 and missing["Location"] == target
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_media_manager.py -k replace -v
```

Expected: FAIL with `NoReverseMatch: Reverse for 'manage_media_replace' not found`.

- [ ] **Step 3: Add the URL**

In `courses/urls.py`, inside the media block, after the `manage_media_delete` entry:

```python
    path(
        "manage/courses/<slug:slug>/media/<int:pk>/replace/",
        views_media.media_replace,
        name="manage_media_replace",
    ),
```

- [ ] **Step 4: Write the view**

In `courses/views_media.py`, add to the imports:

```python
from django.views.decorators.http import require_POST
```

Append after `media_delete`:

```python
@require_POST  # above @login_required: a non-POST is a 405 regardless of auth
@login_required
def media_replace(request, slug, pk):
    course = _require_manage(request, slug)
    asset = get_object_or_404(MediaAsset, pk=pk, course=course)
    # The KEY, not request.FILES emptiness: a multipart POST under another
    # field name would pass an emptiness check and then 500 on the access.
    if "file" not in request.FILES:
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request,
            "courses/manage/_op_error.html",
            {"message": "No file was submitted."},
            status=422,
        )
    try:
        # MediaAssetForm is deliberately NOT reused: its fields are
        # ["kind", "file"], and `kind` is exactly what a replace must not
        # accept from the client.
        media_svc.replace_asset(asset, request.FILES["file"])
    except ValidationError as e:
        msg = "; ".join(e.messages)
        if not _wants_fragment(request):
            return redirect("courses:manage_media", slug=course.slug)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_media", slug=course.slug)
    media_svc.attach_usage(asset)
    return render(
        request,
        "courses/manage/media/_asset_cell.html",
        {"course": course, "asset": asset},
    )
```

`ValidationError` is already imported in this module. Error messages are plain literals, **not** `gettext` — matching `views_media.py:80` and `:126`, which ship untranslated English for the same class of message.

- [ ] **Step 5: Run to verify they pass**

```bash
uv run pytest tests/test_media_manager.py -k replace -v
```

Expected: 8 passed.

Note: `test_replace_returns_the_rerendered_cell` asserts `data-replace-url` appears in the cell, which Task 4 adds. **Until Task 4 lands this one assertion fails.** That is deliberate — it is the interface contract between the two tasks. If you are running Task 3 standalone, expect 7 passed / 1 failed on exactly that assertion, and let Task 4 turn it green. Do not delete the assertion.

- [ ] **Step 6: FALSIFY the decorator order**

Swap the two decorators so `@login_required` is outermost. Run
`uv run pytest tests/test_media_manager.py::test_replace_rejects_get_before_authentication -v`.
Expected: **FAILS** with 302 instead of 405. **Edit the order back** and re-run.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check --no-cache courses/views_media.py courses/urls.py tests/test_media_manager.py
uv run ruff format --check courses/views_media.py courses/urls.py tests/test_media_manager.py
git add courses/views_media.py courses/urls.py tests/test_media_manager.py
git commit -m "feat(media): add the media_replace view and route

POST-only above @login_required, scoped to the course so a cross-course pk is
a 404, guarding on the file KEY so a mis-keyed multipart is a 422 not a 500.
Does not reuse MediaAssetForm, whose kind field a replace must never accept.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Template and CSS

**Files:**
- Modify: `templates/courses/manage/media/_asset_cell.html`
- Modify: `templates/courses/manage/media/manager.html:6-10` (the `.media-manager` attribute block)
- Modify: `courses/static/courses/css/editor.css` (beside the other `.asset-*` rules, ~lines 721-733)
- Test: `tests/test_media_manager.py` (append)

**Interfaces:**
- Consumes: `courses:manage_media_replace` (Task 3); `asset.di_uses`, set by both `attach_usage` and `assets_with_usage`, so every render path has it.
- Produces: the DOM contract Task 6's JS selects on — `[data-replace-asset]`, `[data-replace-input]`, `data-replace-url` and `data-di-uses` on `.asset-cell`, and the six `data-msg-*` attributes on `.media-manager`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_media_manager.py`:

```python
@pytest.mark.django_db
def test_replace_control_is_enabled_even_when_the_asset_is_in_use(
    client, settings, tmp_path
):
    """The likeliest implementation slip: the trash button in the SAME
    {% with uses %} block is `{% if uses %}disabled{% endif %}`, and copying
    that line would disable replace on exactly the assets it exists for."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-inuse")
    course = CourseFactory(owner=pa, slug="inuse-repl")
    asset = make_image_asset(course, filename="x.png")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, ImageElement.objects.create(media=asset, alt="a"))

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    marker = f'data-replace-asset="{asset.pk}"'
    assert marker in body
    button = body[body.index(marker) - 200 : body.index(marker) + 200]
    assert "disabled" not in button          # replace stays live...
    assert "In use — cannot delete" in body  # ...while delete is refused


@pytest.mark.django_db
def test_cell_carries_di_uses_for_the_drag_warning(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-di")
    course = CourseFactory(owner=pa, slug="di-repl")
    plain = make_image_asset(course, filename="plain.png")
    dragged = make_image_asset(course, filename="dragged.png")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    from courses.models import DragToImageQuestionElement

    add_element(
        unit,
        DragToImageQuestionElement.objects.create(
            media=dragged, alt="Diagram", distractors=""
        ),
    )

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    for pk, expected in ((dragged.pk, "1"), (plain.pk, "0")):
        cell = body[body.index(f'data-asset-id="{pk}"') :][:400]
        assert f'data-di-uses="{expected}"' in cell


@pytest.mark.django_db
def test_manager_renders_all_six_replace_message_attributes(
    client, settings, tmp_path
):
    """The ONLY assertion that can fail if manager.html is never touched.
    msg(host, key, fallback) returns the English fallback when an attribute is
    missing, and the suite runs in English -- so every other test in this plan,
    including the e2e ones, passes byte-identically against a manager.html that
    was never edited, and the Polish translations would ship dead."""
    settings.MEDIA_ROOT = str(tmp_path)
    pa = make_pa(client, "pa-repl-msgs")
    course = CourseFactory(owner=pa, slug="msgs-repl")
    make_image_asset(course, filename="x.png")

    body = client.get(
        reverse("courses:manage_media", kwargs={"slug": course.slug})
    ).content.decode()

    head = body[: body.index("</section>")] if "</section>" in body else body
    for key in (
        "replace-confirm",
        "replace-drag-warning",
        "replace-commit",
        "replace-cancel",
        "replace-failed",
        "replace-aria",
    ):
        marker = f'data-msg-{key}="'
        assert marker in head, key
        value = head[head.index(marker) + len(marker) :]
        assert value[: value.index('"')].strip(), f"{key} is empty"
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_media_manager.py -k "in_use or di_uses or six_replace" -v
```

Expected: 3 FAILED on the missing markers.

- [ ] **Step 3: Edit `_asset_cell.html`**

Two changes. First, the root element gains two attributes and one child. Replace the opening `<div class="asset-cell" …>` with:

```html
<div class="asset-cell" data-asset-id="{{ asset.pk }}" data-kind="{{ asset.kind }}"
     data-url="{{ asset.file.url }}" data-name="{{ asset.display_name }}"
     data-replace-url="{% url 'courses:manage_media_replace' slug=course.slug pk=asset.pk %}"
     data-di-uses="{{ asset.di_uses|default:0 }}">
  {# Outside .asset-foot on purpose: the confirm strip is added and removed
     inside the cell, and an input living in a region the JS manipulates could
     be detached while a reference to it is still held. #}
  <input type="file" name="file" hidden data-replace-input
         accept="{% if asset.kind == 'image' %}image/*{% else %}video/*{% endif %}">
```

Second, inside the `{% with uses=… %}` block, wrap the two action controls. Replace the `<form class="asset-del" …>…</form>` element with:

```html
      <div class="asset-actions">
        <button type="button" class="iconbtn" data-replace-asset="{{ asset.pk }}"
                aria-label="{% trans 'Replace file' %}" title="{% trans 'Replace file' %}">⇄</button>
        <form class="asset-del" method="post"
              action="{% url 'courses:manage_media_delete' slug=course.slug pk=asset.pk %}" data-op="asset-delete">
          {% csrf_token %}
          <button type="submit" class="iconbtn iconbtn--danger"
                  {% if uses %}disabled title="{% trans 'In use — cannot delete' %}"{% else %}title="{% trans 'Delete' %}"{% endif %}>🗑</button>
        </form>
      </div>
```

The ⇄ button carries **no** `{% if uses %}disabled` — that is the point of the feature. `.asset-foot` keeps exactly two flex children, so its `space-between` still pins the uses summary left and the actions right.

A text glyph, not an SVG: the repo's icon convention is monochrome SVG, but this control sits between the text glyphs `✎` and `🗑`, and a lone SVG among them would read as a mistake. Converting all three is out of scope.

- [ ] **Step 4: Edit `manager.html`**

Extend the `.media-manager` attribute block (currently lines 6-10) with six more:

```html
         data-msg-replace-confirm="{% trans 'Replace with:' %}"
         data-msg-replace-drag-warning="{% trans 'Used by a drag-to-image question. Drop zones are stored as fractions of the image, so a file with a different shape will move them.' %}"
         data-msg-replace-commit="{% trans 'Replace' %}"
         data-msg-replace-cancel="{% trans 'Cancel' %}"
         data-msg-replace-failed="{% trans 'Could not replace the file.' %}"
         data-msg-replace-aria="{% trans 'Confirm file replacement' %}"
```

None carries an interpolation placeholder — the filename is a separate DOM node — so no translation, fuzzy pre-fill included, can break the strip by dropping a token.

- [ ] **Step 5: Add the CSS**

In `courses/static/courses/css/editor.css`, beside the other `.asset-*` rules:

```css
/* Replace: the ⇄ button shares a row with the delete form, so the foot keeps
   exactly two flex children and its space-between still holds. The form's
   display:contents (below) now resolves against .asset-actions, not .asset-foot. */
.asset-actions { display: flex; gap: var(--space-1); }

/* A third control leaves ~33px for the foot's left-hand label at the grid's 8rem
   minimum. Flex items default to min-width:auto and refuse to shrink, so without
   this they push out of the cell. :not([open]) is load-bearing in BOTH
   directions: it matches the unused <span> and a CLOSED <details> (which should
   shrink), and deliberately not an OPEN one -- an unfloored open details would be
   squeezed to ~30px and wrap every unit title to a few characters per line. */
.asset-foot > :first-child:not([open]) { min-width: 0; }

/* Shrink without clipping is a worse-looking bug: with overflow visible the
   glyphs are still painted at full width, straight across the buttons. Both
   branches of the foot need it -- NOT .asset-uses-detail, which is the <details>
   box, where nowrap would inherit into every <li> and overflow:hidden would clip
   the expanded list (text-overflow does not inherit, so not even an ellipsis). */
.asset-uses, .asset-foot > .muted {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.asset-uses-list { white-space: normal; }

.asset-replace-confirm {
  display: flex; flex-direction: column; gap: var(--space-1);
  margin-top: var(--space-1); padding-top: var(--space-1);
  border-top: 1px solid var(--border-default);
  font-size: .78rem; text-align: left;
}
.asset-replace-confirm__file {
  font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* --text-secondary, not --text-tertiary, which fails AA at body size.
   overflow-wrap because this is the longest string in the strip and a long
   unbreakable Polish compound would otherwise push the cell wider. */
.asset-replace-confirm__warn {
  color: var(--text-secondary); overflow-wrap: anywhere;
}
/* "Replace" + "Cancel" need ~160px against the ~112px an 8rem column offers, and
   the Polish labels are no shorter -- so they wrap at the narrow end and sit on
   one line where there is room. */
.asset-replace-confirm__actions { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.asset-replace-confirm__actions .btn { flex: 1 1 auto; }
```

Also update the existing comment above `.asset-del { display: contents; }` (editor.css:729-731) so it names `.asset-actions` rather than `.asset-foot` — it currently describes a structure this task changes.

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_media_manager.py -k replace -v
```

Expected: all pass, including `test_replace_returns_the_rerendered_cell` from Task 3, which was waiting on `data-replace-url`.

- [ ] **Step 7: FALSIFY the enabled-when-in-use assertion**

Add `{% if uses %}disabled{% endif %}` to the ⇄ button. Run
`uv run pytest tests/test_media_manager.py::test_replace_control_is_enabled_even_when_the_asset_is_in_use -v`.
Expected: **FAILS**. **Edit the attribute back out.**

- [ ] **Step 8: Commit**

```bash
uv run ruff check --no-cache tests/test_media_manager.py
uv run ruff format --check tests/test_media_manager.py
git add templates/courses/manage/media/_asset_cell.html templates/courses/manage/media/manager.html courses/static/courses/css/editor.css tests/test_media_manager.py
git commit -m "feat(media): add the replace control, its data contract and CSS

⇄ sits beside the trash in a new .asset-actions wrapper so .asset-foot keeps
two flex children. Adds the shrink/truncation rules a third control forces on
both foot branches, and the confirm strip's styling.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The JS — the fourth op

**Files:**
- Modify: `courses/static/courses/js/media_picker.js` (`flash` at :6-9; new code inside `wireManager`, after the rename handler)

**Interfaces:**
- Consumes: the DOM contract from Task 4; the endpoint from Task 3; the file's existing `csrf()`, `msg(host, key, fallback)` and `flash(host, msg)`.
- Produces: the behaviour Task 6's e2e drives. No exported symbols.

- [ ] **Step 1: Update `flash`**

Replace the function at the top of the file:

```js
  function flash(host, msg) {
    var bar = document.createElement("div"); bar.className = "op-error";
    // role=alert: the server's _op_error.html has it, this one did not, so a
    // flashed message was never announced. Insert EMPTY then fill -- a live
    // region that arrives already populated is the case screen readers announce
    // least reliably.
    bar.setAttribute("role", "alert");
    host.prepend(bar); bar.textContent = msg;
    setTimeout(function () { bar.remove(); }, 6000);
  }
```

- [ ] **Step 2: Add the replace op**

Inside `wireManager`, after the inline-rename handler, before the filter block:

```js
    // ----------------------------------------------------------------------
    // Replace: ⇄ opens the file dialog; a chosen file raises a confirm strip.
    // ----------------------------------------------------------------------
    // wireManager scope, unlike the per-strip `done` below. Its whole job is to
    // stop a ⇄ click on ANOTHER cell mid-request, which per-strip state cannot
    // see. It MUST be lowered in every exit, or replace works exactly once per
    // page load.
    var replaceBusy = false;

    function closeStrip(strip, clearInput) {
      var cell = strip.closest(".asset-cell");
      strip.remove();
      if (clearInput && cell) {
        var input = cell.querySelector("[data-replace-input]");
        if (input) input.value = "";
      }
    }

    root.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-replace-asset]");
      if (!btn || replaceBusy) return;
      var cell = btn.closest(".asset-cell");
      if (!cell) return;
      var input = cell.querySelector("[data-replace-input]");
      // Tear NOTHING down here. The dialog may be dismissed (which fires no
      // change at all), and destroying an open strip first would silently lose
      // the author's pending selection. Teardown belongs to the change handler.
      if (input) input.click();
    });

    root.addEventListener("change", function (e) {
      // Filter on the attribute, not on input.type: root is .media-manager,
      // which also holds the upload form's <input type="file" name="file">,
      // and change bubbles.
      var input = e.target.closest("[data-replace-input]");
      if (!input || !input.files || !input.files.length) return;
      var cell = input.closest(".asset-cell");
      if (!cell) return;
      // Capture BEFORE any teardown: in the re-pick flow the open strip is this
      // cell's, and clearing this cell's input would wipe the selection we are
      // about to show. input.files cannot be restored programmatically.
      var file = input.files[0];
      var open = root.querySelector("[data-replace-strip]");
      if (open) closeStrip(open, open.closest(".asset-cell") !== cell);
      cell.appendChild(buildReplaceStrip(cell, input, file));
    });

    function buildReplaceStrip(cell, input, file) {
      var strip = document.createElement("div");
      strip.className = "asset-replace-confirm";
      strip.setAttribute("data-replace-strip", "");
      strip.setAttribute("role", "group");
      strip.setAttribute("aria-label", msg(root, "replace-aria", "Confirm file replacement"));

      var label = document.createElement("span");
      label.className = "asset-replace-confirm__label";
      label.textContent = msg(root, "replace-confirm", "Replace with:");
      strip.appendChild(label);

      var fname = document.createElement("span");
      fname.className = "asset-replace-confirm__file";
      fname.setAttribute("data-replace-filename", "");
      fname.textContent = file.name;  // textContent: a crafted name cannot inject
      strip.appendChild(fname);

      // getAttribute yields a STRING: `if (cell.dataset.diUses)` is truthy for
      // "0" and would show the caution on every asset in the library.
      if (Number(cell.getAttribute("data-di-uses") || 0) > 0) {
        var warn = document.createElement("span");
        warn.className = "asset-replace-confirm__warn";
        warn.textContent = msg(root, "replace-drag-warning",
          "Used by a drag-to-image question. Drop zones are stored as fractions of the image, so a file with a different shape will move them.");
        strip.appendChild(warn);
      }

      var actions = document.createElement("div");
      actions.className = "asset-replace-confirm__actions";
      var commit = document.createElement("button");
      commit.type = "button"; commit.className = "btn btn--small";
      commit.setAttribute("data-replace-commit", "");
      commit.textContent = msg(root, "replace-commit", "Replace");
      var cancel = document.createElement("button");
      cancel.type = "button"; cancel.className = "btn btn--small btn--ghost";
      cancel.setAttribute("data-replace-cancel", "");
      cancel.textContent = msg(root, "replace-cancel", "Cancel");
      actions.appendChild(commit); actions.appendChild(cancel);
      strip.appendChild(actions);

      // Bound HERE, not delegated: `done` must be a per-strip closure, exactly
      // like the rename handler's. Hoisted to wireManager scope it would be set
      // by the first replace and silently swallow every one after it.
      var done = false;

      function focusTrigger(host) {
        var btn = (host || cell).querySelector("[data-replace-asset]");
        if (btn) btn.focus();
      }

      function fail(text) {
        if (strip.isConnected) { closeStrip(strip, true); focusTrigger(); }
        flash(root, text);
      }

      cancel.addEventListener("click", function () {
        if (done) return;
        closeStrip(strip, true);  // clear, so re-picking the same file re-fires
        focusTrigger();
      });

      commit.addEventListener("click", function () {
        if (done) return;  // the READ is the guard; disabling is the complement
        done = true;
        replaceBusy = true;
        commit.disabled = true;
        // Cancel is disabled too: the POST is unabortable server-side, so a
        // mid-flight cancel would say "nothing happened" and then land a 200.
        cancel.disabled = true;
        var pk = cell.getAttribute("data-asset-id");
        var fd = new FormData();
        fd.append("file", file);
        fetch(cell.getAttribute("data-replace-url"), {
          method: "POST",
          headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
          body: fd,
        })
          .then(function (r) { return r.text().then(function (t) { return { status: r.status, text: t }; }); })
          .then(function (res) {
            var tmp = document.createElement("div"); tmp.innerHTML = res.text.trim();
            var fresh = res.status === 200 ? tmp.querySelector(".asset-cell") : null;
            if (fresh) {
              if (strip.isConnected) {
                cell.replaceWith(fresh);
                focusTrigger(fresh);
              } else {
                // A filter swap landed mid-flight and detached us. The replace
                // COMMITTED, but the refetched grid was rendered pre-commit, so
                // a no-op would leave a stale thumbnail. Query from root:
                // wireManager's `grid` local is the node the filter replaced.
                var live = root.querySelector('.asset-cell[data-asset-id="' + pk + '"]');
                if (live) live.replaceWith(fresh);
              }
              return;
            }
            // Anything else -- other statuses, a rejected promise, AND a 200
            // whose body has no cell. fetch follows redirects, so a POST after
            // the session expires resolves as 200 carrying the login page: not
            // 422, not an error status, not a rejection. Without this branch
            // the strip stays open with both buttons disabled, unrecoverable.
            var text = "";
            if (res.status === 422) {
              var box = tmp.querySelector(".op-error");
              if (box) text = (box.textContent || "").trim();
            }
            fail(text || msg(root, "replace-failed", "Could not replace the file."));
          })
          .catch(function () {
            fail(msg(root, "replace-failed", "Could not replace the file."));
          })
          .then(function () { replaceBusy = false; });  // finally-equivalent
      });

      return strip;
    }
```

`input` is a parameter of `buildReplaceStrip` for symmetry with `closeStrip`'s lookup; if ruff-equivalent JS linting flags it as unused, drop the parameter and the corresponding argument rather than adding a suppression.

- [ ] **Step 3: Verify nothing regressed in the existing manager JS**

```bash
uv run pytest tests/test_media_manager.py tests/test_media_picker.py -v
```

Expected: all pass. (These are server-side; they prove the templates and endpoints still render. The JS itself is proven in Task 6.)

- [ ] **Step 4: Commit**

```bash
git add courses/static/courses/js/media_picker.js
git commit -m "feat(media): wire the replace confirm strip in the media manager

⇄ opens the file dialog; a chosen file raises an inline strip below the foot so
the in-use list stays visible. Per-strip `done` closure plus a wireManager-scoped
in-flight flag lowered in every exit. The catch-all also absorbs a 200 with no
cell, which is what a followed login redirect looks like.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: End-to-end tests

**Files:**
- Test: `tests/test_e2e_media_manager.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: nothing.

These do **not** go in `tests/test_e2e_media_picker.py`. That module is scoped to the in-editor "Choose media" picker — every helper ends on the editor page — it has no `MEDIA_ROOT` fixture, and its `_setup` builds the asset as `MediaAssetFactory(file="courses/media/x.png")` with **no bytes**. Reusing it would break the central assertion twice over: with the old file absent, storage reuses the name, so `asset.file.url` never changes and "the src is the new file" passes on a build that replaced nothing; and without the redirect the run would write into, and **delete from**, the working tree's real `media/`.

- [ ] **Step 1: Write the module skeleton and the happy path**

Create `tests/test_e2e_media_manager.py`:

```python
"""Playwright e2e for the media manager's replace action.

Separate from test_e2e_media_picker.py, which drives the in-editor picker, has
no MEDIA_ROOT isolation, and seeds byte-less assets. Both of those would make
the central assertion here -- that the rendered src actually changes -- pass on
a build that replaced nothing.
"""

import os
import re
from io import BytesIO

import pytest
from PIL import Image

from courses.models import Element
from courses.models import ImageElement
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    """Redirect MEDIA_ROOT before any asset exists.

    autouse deliberately: a fixture defined in a test module is scoped to that
    module and cannot leak, whereas an opt-in redirect that a future test forgets
    would DELETE from the working tree's real media/ directory -- the one hazard
    this feature uniquely creates. live_server's _MediaFilesHandler reads
    MEDIA_ROOT per request, so the ordering is what makes fixture images resolve.
    """
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _png_bytes(size=(4, 4), color="blue"):
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _upload_payload(name="replacement.png", color="green"):
    return {"name": name, "mimeType": "image/png", "buffer": _png_bytes(color=color)}


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, *, with_element=True):
    """A course whose asset has REAL bytes and a storage-assigned name, so the
    replacement genuinely lands on a different URL."""
    owner = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    asset = make_image_asset(course, filename="original.png", color="red")
    if with_element:
        Element.objects.create(
            unit=unit, content_object=ImageElement.objects.create(media=asset, alt="a")
        )
    return owner, course, unit, asset


def _open_manager(page, live_server, username, course):
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/media/")
    page.wait_for_selector(".asset-cell")


def test_replace_swaps_the_cell_and_the_rendered_image(page, live_server):
    _, course, unit, asset = _seed("pa-repl-e2e", "repl-e2e")
    _open_manager(page, live_server, "pa-repl-e2e", course)
    original_src = asset.file.url

    page.set_input_files("[data-replace-input]", _upload_payload())

    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    assert "replacement.png" in strip.locator("[data-replace-filename]").inner_text()
    # The confirm must not destroy the context the author decides against.
    assert page.locator(".asset-uses").is_visible()

    strip.locator("[data-replace-commit]").click()
    page.wait_for_selector('.asset-cell:has-text("replacement.png")')
    assert page.locator("[data-replace-strip]").count() == 0

    page.goto(f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/")
    page.wait_for_selector('[data-scope="editor"]')
    new_src = page.locator(".editor img").first.get_attribute("src")
    assert new_src and new_src != original_src  # the whole point
```

- [ ] **Step 2: Run it**

```bash
uv run pytest -m e2e tests/test_e2e_media_manager.py -v
```

Expected: PASS. If the editor-page image selector misses, print `page.content()` and adjust the selector to whatever wraps the `ImageElement` render — do not weaken the `!=` assertion.

- [ ] **Step 3: FALSIFY the src assertion**

In `courses/media.py`, temporarily make `replace_asset` return before `asset.save(...)`. Run the test.
Expected: **FAILS** on the cell never showing `replacement.png`. **Edit the early return back out.**

This is the assertion the byte-less fixture would have made unfalsifiable, so it is worth proving explicitly.

- [ ] **Step 4: Add cancel, 422, catch-all and the mid-flight filter**

```python
def test_cancel_changes_nothing_and_sends_no_request(page, live_server):
    _, course, _unit, asset = _seed("pa-repl-cancel", "repl-cancel")
    _open_manager(page, live_server, "pa-repl-cancel", course)

    # Recorded BEFORE the click, so the negative is asserted rather than slept on.
    seen = []
    page.on("request", lambda r: seen.append(r.url) if "/replace/" in r.url else None)

    page.set_input_files("[data-replace-input]", _upload_payload())
    strip = page.locator("[data-replace-strip]")
    strip.wait_for(state="visible")
    strip.locator("[data-replace-cancel]").click()
    # The strip's removal provably post-dates any request the handler would make.
    page.wait_for_selector("[data-replace-strip]", state="detached")

    assert seen == []
    asset.refresh_from_db()
    assert asset.original_filename == "original.png"


def test_a_422_flashes_the_validator_message(page, live_server):
    _, course, _unit, _asset = _seed("pa-repl-422", "repl-422")
    _open_manager(page, live_server, "pa-repl-422", course)

    page.set_input_files(
        "[data-replace-input]",
        {"name": "clip.mp4", "mimeType": "video/mp4", "buffer": b"\x00" * 256},
    )
    page.locator("[data-replace-commit]").click()

    bar = page.locator(".op-error")
    bar.wait_for(state="visible")
    text = bar.inner_text()
    # CONTAINMENT, not equality: _op_error.html renders
    # "Couldn't apply that change: {{ message }}", so the extracted textContent
    # always carries that prefix. An equality assertion would be red against a
    # correct build. Nobody should "fix" that by stripping the prefix in JS.
    assert "mp4" in text.lower()
    assert "<" not in text                        # the fragment was parsed, not dumped
    assert bar.get_attribute("role") == "alert"   # announced, not silent
    assert page.locator("[data-replace-strip]").count() == 0


def test_a_server_error_removes_the_strip_and_flashes(page, live_server):
    """Every other e2e here passes with the catch-all branch deleted."""
    _, course, _unit, _asset = _seed("pa-repl-500", "repl-500")
    _open_manager(page, live_server, "pa-repl-500", course)
    page.route(
        "**/replace/", lambda route: route.fulfill(status=500, body="boom")
    )

    page.set_input_files("[data-replace-input]", _upload_payload())
    page.locator("[data-replace-commit]").click()

    page.wait_for_selector("[data-replace-strip]", state="detached")
    assert page.locator(".op-error").is_visible()
    focused = page.evaluate("document.activeElement.hasAttribute('data-replace-asset')")
    assert focused  # focus restored, not dropped to <body>


def test_two_consecutive_replaces_both_succeed(page, live_server):
    """Carries two regressions at once.

    The per-strip `done` closure: hoisted, the second replace is a silent no-op.
    The in-flight flag's LOWERING: it is read in exactly one place, the ⇄ click
    handler -- so the second pass must go through an actual CLICK. A test that
    only ever calls set_input_files never executes that handler, and a flag that
    is raised and never lowered would pass every other test in this module.
    """
    _, course, _unit, _asset = _seed("pa-repl-twice", "repl-twice")
    _open_manager(page, live_server, "pa-repl-twice", course)

    page.set_input_files("[data-replace-input]", _upload_payload("first.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_selector('.asset-cell:has-text("first.png")')

    # Second pass THROUGH the button. input.click() raises a file chooser that
    # must be intercepted, or it hangs.
    with page.expect_file_chooser() as fc:
        page.click("[data-replace-asset]")
    fc.value.set_files(_upload_payload("second.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_selector('.asset-cell:has-text("second.png")')


def test_a_filter_swap_mid_flight_still_updates_the_cell(page, live_server):
    _, course, _unit, asset = _seed("pa-repl-filter", "repl-filter")
    _open_manager(page, live_server, "pa-repl-filter", course)

    held = []
    page.route("**/replace/", lambda route: held.append(route))
    page.set_input_files("[data-replace-input]", _upload_payload("late.png"))
    page.locator("[data-replace-commit]").click()
    page.wait_for_function("window.__held === undefined")  # give the POST a tick

    page.fill("[data-filter-q]", "original")  # forces oldGrid.replaceWith(newGrid)
    page.wait_for_timeout(400)                # past the 250ms debounce
    held[0].continue_()

    page.wait_for_selector('.asset-cell:has-text("late.png")')
    asset.refresh_from_db()
    assert asset.original_filename == "late.png"


def test_the_drag_warning_appears_only_for_a_drag_to_image_asset(page, live_server):
    from courses.models import DragToImageQuestionElement

    _, course, unit, plain = _seed("pa-repl-warn", "repl-warn", with_element=False)
    dragged = make_image_asset(course, filename="diagram.png", color="green")
    Element.objects.create(
        unit=unit,
        content_object=DragToImageQuestionElement.objects.create(
            media=dragged, alt="Diagram", distractors=""
        ),
    )
    _open_manager(page, live_server, "pa-repl-warn", course)

    for pk, expect_warning in ((dragged.pk, True), (plain.pk, False)):
        cell = page.locator(f'.asset-cell[data-asset-id="{pk}"]')
        cell.locator("[data-replace-input]").set_input_files(_upload_payload())
        cell.locator("[data-replace-strip]").wait_for(state="visible")
        shown = cell.locator(".asset-replace-confirm__warn").count() > 0
        assert shown is expect_warning, pk
        cell.locator("[data-replace-cancel]").click()
        page.wait_for_selector("[data-replace-strip]", state="detached")
```

The `page.wait_for_function("window.__held === undefined")` line in the filter test is a placeholder for "let the click's fetch actually dispatch" — replace it with whatever deterministic wait the codebase already uses for an in-flight route, or simply assert `len(held) == 1` in a short poll loop. Do **not** leave a bare `wait_for_timeout` as the only synchronisation for the POST dispatch.

- [ ] **Step 5: Run the module**

```bash
uv run pytest -m e2e tests/test_e2e_media_manager.py -v
```

Expected: 7 passed. E2e flakes under parallel load — if one fails, re-run it alone before blaming the diff.

- [ ] **Step 6: Screenshots — four states, both themes**

Capture the manager at a viewport narrow enough that `.asset-grid` columns sit at their `8rem` minimum, in **light and dark**, and judge the dark rendering on its own rather than assuming it from the light one:

1. an **unused** cell — the majority case, and what the `.muted` truncation rule exists for;
2. an in-use cell with its `<details>` **closed** — the only state the `:not([open])` shrink rule targets. Expect the summary to truncate and the `▸` marker to be eaten by the ellipsis; that is the accepted cost, but look at it;
3. an in-use cell with its `<details>` **open** — deliberately left at its min-content floor;
4. a cell with the confirm strip open, in a **multi-cell row**, so the row-height reflow is visible.

Attach them to the PR. If any looks wrong, fix the CSS in Task 4's files and re-run Task 4's tests.

- [ ] **Step 7: Commit**

```bash
uv run ruff check --no-cache tests/test_e2e_media_manager.py
uv run ruff format --check tests/test_e2e_media_manager.py
git add tests/test_e2e_media_manager.py
git commit -m "test(media): e2e for the replace flow in the media manager

New module rather than an addition to the picker e2es, which drive the editor
page and seed byte-less assets -- either would make the src assertion pass on a
build that replaced nothing. Covers the strip, cancel, 422, the catch-all, two
consecutive replaces through a real ⇄ click, and a mid-flight filter swap.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Polish translations and the branch gate

**Files:**
- Modify: `locale/pl/LC_MESSAGES/django.po` (+ the compiled `.mo`)

**Interfaces:** none.

- [ ] **Step 1: Regenerate the catalog**

```bash
uv run python manage.py makemessages -l pl
```

- [ ] **Step 2: Translate the new entries**

Seven new msgids: `Replace file`, `Replace with:`, the drag-to-image warning sentence, `Replace`, `Cancel`, `Could not replace the file.`, `Confirm file replacement`.

For each, write the Polish msgstr **and delete any `#, fuzzy` line** `makemessages` pre-filled. A fuzzy entry is not used at runtime *and* carries a translation lifted from a different string — so clearing it is two separate deletions: the flag line and the wrong msgstr. Check that `Cancel` and `Replace` did not pick up an unrelated existing translation.

Verify no fuzzy entries survive among the new ones:

```bash
grep -n -B 2 -A 4 "fuzzy" locale/pl/LC_MESSAGES/django.po
```

- [ ] **Step 3: Compile**

```bash
uv run python manage.py compilemessages -l pl
```

- [ ] **Step 4: The branch gate — full suite, both selections**

This is the one place a whole-repo run belongs.

```bash
docker compose -p libli-test -f docker-compose.test.yml up -d --wait
uv run pytest
uv run pytest -m e2e
```

Both must be green. `-m e2e` is mandatory for the second — without it pytest exits **5**, which is "nothing selected", not "passing".

- [ ] **Step 5: The lint gate — both, they are separate CI checks**

```bash
uv run ruff check --no-cache .
uv run ruff format --check .
```

- [ ] **Step 6: Confirm no migration was created**

```bash
git status --porcelain courses/migrations/
```

Expected: empty. This feature changes no model field; a migration here means something went wrong.

- [ ] **Step 7: Commit**

```bash
git add locale/pl/LC_MESSAGES/django.po locale/pl/LC_MESSAGES/django.mo
git commit -m "i18n(media): Polish strings for the replace control

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: §Architecture 1-2 → Task 1; §3 (view + URL) → Task 3; §4 (template) and §7 (CSS) → Task 4; §5 (strip DOM contract) → Tasks 4 and 5; §6 (JS) → Task 5; §Data flow and §Error handling → asserted across Tasks 2, 3 and 6; §i18n → Tasks 4 and 7; §Testing → Tasks 1, 2, 3, 4 and 6. The spec's accepted limitations (rollback orphans, concurrent replace, the mirror filter ordering, the stale-cache edge) are deliberately **not** tasks — they are documented non-goals.

**Known cross-task dependency.** `test_replace_returns_the_rerendered_cell` (Task 3) asserts `data-replace-url`, which Task 4 adds. Task 3 therefore ends 7/8 green when run standalone. This is called out in Task 3 Step 5 rather than hidden, and Task 4 Step 6 re-runs it.

**Naming consistency.** `replace_asset` / `_delete_file_if_unshared` / `media_replace` / `manage_media_replace` / `buildReplaceStrip` / `closeStrip` / `replaceBusy` / `done` are used identically wherever they appear. DOM hooks are `data-replace-asset`, `data-replace-input`, `data-replace-url`, `data-di-uses`, `data-replace-strip`, `data-replace-filename`, `data-replace-commit`, `data-replace-cancel`. Message keys are `replace-confirm`, `replace-drag-warning`, `replace-commit`, `replace-cancel`, `replace-failed`, `replace-aria` — six, matching Task 4's assertion.

**Two soft spots, flagged rather than papered over.** The oversize test (Task 2) allocates a buffer from the live admin-configured limit; check that value before running it. The mid-flight filter test (Task 6) needs a deterministic wait for the POST to dispatch, and the placeholder given must be replaced with a real condition, not a bare sleep.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-11-media-asset-replace.md`. Two execution options:

**1. Subagent-Driven (recommended)** — a fresh subagent per task, reviewed between tasks, fast iteration.

**2. Inline Execution** — tasks executed in this session via executing-plans, batched with checkpoints.

Which approach?
