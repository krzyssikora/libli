# Media Image Derivatives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve appropriately-sized WebP derivatives instead of full-resolution originals on every media surface except `cell-full`, so the media library stops taking minutes to paint previews.

**Architecture:** Two lossless-WebP derivatives (`thumb` 512px, `web` 896px) are generated synchronously into new `MediaAsset` fields at every asset-creation site, with blank as the always-safe fallback state. A single `simple_tag` owns all `<img>` emission across eight sites using three strategies (fixed-box `src`=thumb, fluid `w`+`sizes`, and `cell-full` original-only). Two JavaScript modules that reconstruct a "big image" from the rendered element's effective source are repointed at explicit full-resolution URLs *before* any template starts emitting derivatives.

**Tech Stack:** Django 5.2, Pillow 12.2 (already a dependency — no new packages), PostgreSQL, Playwright/pytest for e2e, vanilla JS (no framework).

**Spec:** `docs/superpowers/specs/2026-08-17-media-image-derivatives-design.md` — read it alongside this plan. The plan argues from the spec and does not restate its reasoning.

## Global Constraints

- **`THUMB_WIDTH = 512`, `WEB_WIDTH = 896`** — module-level constants in `courses/derivatives.py`, imported by the template tag. Never duplicated as literals.
- **Encoder kwargs, pinned:** `format="WEBP", lossless=True, method=4, exact=True`.
- **Migration `0059`** — schema-only, five `AddField`, no data migration, reversible. `0058_shortnumeric_text_value` is current head.
- **No `width` or `height` attribute is emitted on any preset.** Measured: they distort every portrait image by 100–260px and make grid cells 8.6x too tall.
- **`generate_derivatives` never raises.** One broad `except Exception` around the whole body including both storage writes.
- **Ordering is a hard requirement:** Tasks 8–9 (JS) land and are verified before Task 11 (first template conversion). No commit may exist in which zoom or hover preview is degraded.
- **Every test fixture that depends on a derivative existing must pass `derivatives=True`.** Width alone generates nothing — `make_image_asset` never routes through `create_asset`.
- **Rounding for every `sizes` value is upward, always.**
- **Test-DB container must be running before any pytest run** (`docker ps` should show `libli-test-db`), and this worktree has its own `.env` already copied in.
- **Commands run via `uv run`** — `pytest`/`ruff`/`python` are not on PATH. E2E needs `-m e2e` or it silently deselects (exit 5).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `courses/derivatives.py` | **new** — `THUMB_WIDTH`/`WEB_WIDTH`, `generate_derivatives`, `delete_derivative_files`. All image processing lives here and nowhere else. |
| `courses/models.py` | `DerivativesState` TextChoices + five new `MediaAsset` fields + `GalleryElement.render()` figure-dict change. |
| `courses/migrations/0059_mediaasset_derivatives.py` | **new** — schema-only. |
| `courses/media.py` | `create_asset(generate=True)`, `replace_asset` resequencing. |
| `courses/lal_loader/media.py` | `get_or_create_asset` generates on the create branch only. |
| `courses/signals.py` | `post_delete` also removes derivative files. |
| `courses/transfer/importer.py` | passes `generate=False`. |
| `courses/management/commands/backfill_media_derivatives.py` | **new** — the backfill. |
| `courses/templatetags/courses_media_extras.py` | **new** — `media_img` tag; the only place `srcset`/`sizes`/preset logic exists. |
| `courses/static/courses/js/imagezoom.js` | reads `data-zoom-src`; gains `load`/`error` handlers + loading state. |
| `courses/static/courses/js/media_preview.js` | reads the cell's `data-url`; guard split. |
| 7 templates (see Task 11–12) | converted to `{% media_img %}`. |
| `docs/superpowers/plans/2026-08-17-media-image-derivatives-measurements.md` | **new** — the recorded measurement table Task 1 produces; every `sizes` value cites it. |

---

## Task 1: Measure the real surfaces and record the numbers

Everything downstream that carries a `sizes` value or a fixture threshold depends on this. The spec deliberately contains **no** derived geometry — two prior attempts to hand-derive these numbers were wrong (a missing `.el { margin: 1rem 0 }`, then a missing `.app-main` mobile-padding override).

**Files:**
- Create: `docs/superpowers/plans/2026-08-17-media-image-derivatives-measurements.md`
- Create (throwaway, not committed): `scripts/measure_boxes.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the measurement table. Tasks 10 and 14 read `sizes` values and fixture widths from it by name.

- [ ] **Step 1: Write the measurement script**

Create `scripts/measure_boxes.py`. It drives the **real** app (not a CSS harness) via Playwright against a live server, so every stylesheet rule participates.

```python
"""Measure the boxes the media-derivatives sizes values are derived from.

Run against a live dev server with a seeded course. Emits a markdown table.
Headless Chromium, DPR 1, overlay scrollbars — see the spec's measurement
conditions note.
"""
import json
import sys

from playwright.sync_api import sync_playwright

VIEWPORTS = [(640, 800), (641, 800), (900, 800), (1039, 800), (1040, 800), (1280, 720)]

# (label, url_path, selector, needs_collapsed_toc, wait_for)
BOXES = [
    ("el-full expanded",   "/courses/{slug}/unit/{unit}/", ".el--image--full img", False, None),
    ("el-full collapsed",  "/courses/{slug}/unit/{unit}/", ".el--image--full img", True,  None),
    ("editor preview",     "/manage/courses/{slug}/editor/{unit}/", ".prev-inner .el--image--full img", False, None),
    ("gallery frame",      "/courses/{slug}/unit/{unit}/", ".el--gallery .gallery__frame", False, ".el--gallery.gallery--js .gallery__stage"),
    ("gallery collapsed",  "/courses/{slug}/unit/{unit}/", ".el--gallery .gallery__frame", True,  ".el--gallery.gallery--js .gallery__stage"),
    ("dragimage stage",    "/courses/{slug}/unit/{unit}/", ".dragimage__stage", False, None),
    ("td 2col",            "/courses/{slug}/unit/{unit}/", "table.t2 td:first-child", False, None),
    ("td 3col",            "/courses/{slug}/unit/{unit}/", "table.t3 td:first-child", False, None),
    ("td 4col",            "/courses/{slug}/unit/{unit}/", "table.t4 td:first-child", False, None),
    ("asset-thumb manager", "/manage/courses/{slug}/media/", ".asset-thumb", False, None),
    ("asset-thumb picker",  "/manage/courses/{slug}/editor/{unit}/", ".picker .asset-thumb", False, None),
]


def main(base, slug, unit):
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vw, vh in VIEWPORTS:
            page = browser.new_page(viewport={"width": vw, "height": vh},
                                    device_scale_factor=1)
            # Confirm overlay scrollbars: clientWidth must equal the viewport width.
            page.goto(base + "/")
            assert page.evaluate("document.documentElement.clientWidth") == vw, (
                f"scrollbar consumes layout at {vw}px; measurements would be off"
            )
            for label, path, sel, collapsed, wait_for in BOXES:
                url = base + path.format(slug=slug, unit=unit)
                page.goto(url)
                if collapsed:
                    page.evaluate("document.documentElement.classList.add('unit-tree-collapsed')")
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=5000)
                loc = page.locator(sel).first
                if loc.count() == 0:
                    rows.append((vw, label, None))
                    continue
                box = loc.bounding_box()
                rows.append((vw, label, round(box["width"], 2) if box else None))
            page.close()
        browser.close()

    print("| Box | " + " | ".join(f"{v}px" for v, _ in VIEWPORTS) + " |")
    print("| --- |" + " --- |" * len(VIEWPORTS))
    for _, label, _ in [r for r in rows if r[0] == VIEWPORTS[0][0]]:
        cells = [next((str(w) for v, l, w in rows if v == vp and l == label), "-")
                 for vp, _ in VIEWPORTS]
        print(f"| {label} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
```

- [ ] **Step 2: Seed a course with the shapes the script needs**

The measurement page must contain: an `el-full` image, a gallery, a drag-to-image element, and 2-/3-/4-column tables with `cell-full` images. Use the existing `seed_demo_course` command as a base and add what is missing:

```bash
uv run python manage.py seed_demo_course --slug measure-tmp
```

If the seeded course lacks a gallery or drag-to-image element, add them through the editor UI or a short shell script — the script asserts `loc.count() == 0` produces a `-` row, so any missing box shows up as a gap rather than a wrong number.

- [ ] **Step 3: Run the measurements**

```bash
uv run python manage.py runserver 8009 &
uv run python scripts/measure_boxes.py http://127.0.0.1:8009 measure-tmp 1
```

Expected: a markdown table with 11 rows x 6 viewport columns, no `-` cells for the in-scope boxes.

- [ ] **Step 4: Record the table and derive every value**

Create `docs/superpowers/plans/2026-08-17-media-image-derivatives-measurements.md` containing:

1. The raw table from Step 3.
2. **Derived `sizes` values**, each showing its arithmetic:
   - `el-full` desktop clause = `max(el-full expanded, el-full collapsed, editor preview)` across all viewports, **rounded up**.
   - `el-large`/`el-medium`/`el-small` = 75/50/25% of that, rounded up.
   - Middle clause (641–1039) = a `vw`/`calc()` form **fitted to both the 641 and 1039 measurements** — not a bare px value from 900. Show the fit.
   - Mobile clause (≤640) = fitted to the 640 measurement.
   - `gallery` and `dragimage` = same three-clause treatment from their own rows.
3. **Raise-condition check:** does any of `el-full`, gallery, dragimage exceed `WEB_WIDTH` (896) at any viewport? If yes, raise `WEB_WIDTH`, re-run the byte-cost measurement, and record both.
4. **Thumb check:** `asset-thumb manager` and `asset-thumb picker` — does `box x 3 > 512` at either viewport? If yes, raise `THUMB_WIDTH` and record.
5. **Band-fixture widths per preset:** wider than 512, narrower than that preset's measured box at the widest viewport. State the chosen width per preset.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-08-17-media-image-derivatives-measurements.md
git commit -m "docs(media-derivatives): record measured box geometry and derived sizes values"
```

Do **not** commit `scripts/measure_boxes.py` — it is throwaway. Delete it.

---

## Task 2: Model fields, DerivativesState, migration 0059

**Files:**
- Modify: `courses/models.py` (near `MediaAsset`, ~line 730)
- Create: `courses/migrations/0059_mediaasset_derivatives.py`
- Test: `tests/test_media_derivatives_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `DerivativesState` (TextChoices with `.OK`, `.SKIPPED`, `.FAILED`; blank `""` is "pending" and is *not* a choice member), and `MediaAsset.width`, `.height`, `.thumb`, `.web`, `.derivatives_state`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_media_derivatives_model.py`:

```python
import pytest

from courses.models import DerivativesState, MediaAsset
from tests.factories import CourseFactory, make_image_asset


@pytest.mark.django_db
def test_new_fields_default_to_the_pending_state():
    """Blank-is-safe: a freshly created asset carries no derivative claims.

    width/height are PositiveIntegerField(null=True) so their untouched value is
    None, NOT "" — a test written as "all five stay ''" asserts the wrong thing
    for two of them.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "x.png", size=(1000, 800))
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert asset.width is None
    assert asset.height is None
    assert asset.derivatives_state == ""


@pytest.mark.django_db
def test_derivatives_state_choices_are_the_three_terminal_values():
    """The four values are load-bearing for backfill idempotency, so a typo'd
    literal must be a hard error rather than a row silently reprocessed forever."""
    assert DerivativesState.OK == "ok"
    assert DerivativesState.SKIPPED == "skipped"
    assert DerivativesState.FAILED == "failed"
    assert set(DerivativesState.values) == {"ok", "skipped", "failed"}


@pytest.mark.django_db
def test_derivative_fields_accept_a_long_name():
    """max_length=200, not Django's default 100: the derivatives/ prefix is 12
    chars longer than courses/media/, plus a -896.webp suffix and any storage
    collision suffix. At 100, get_available_name silently truncates stems for the
    long-named assets the LAL import produced."""
    course = CourseFactory()
    asset = make_image_asset(course, "x.png", size=(1000, 800))
    long_name = "courses/media/derivatives/" + ("a" * 150) + "-896.webp"
    assert len(long_name) > 100
    asset.web.name = long_name
    asset.save(update_fields=["web"])
    asset.refresh_from_db()
    assert asset.web.name == long_name
```

- [ ] **Step 2: Run it to verify it fails**

```bash
uv run pytest tests/test_media_derivatives_model.py -v
```

Expected: FAIL — `ImportError: cannot import name 'DerivativesState'`.

- [ ] **Step 3: Add the TextChoices and the fields**

In `courses/models.py`, above `class MediaAsset`:

```python
class DerivativesState(models.TextChoices):
    """Terminal outcomes of a derivative-generation attempt.

    Blank ("") is deliberately NOT a member: it is the "never attempted"
    sentinel the backfill uses to pick a row up, and making it a choice would
    invite writing it as a terminal value. Lives here rather than in
    courses/derivatives.py because models.py needs it at module scope for
    `choices=`; the import runs models -> derivatives, never the reverse.
    """

    OK = "ok", _("Generated")
    SKIPPED = "skipped", _("Skipped")
    FAILED = "failed", _("Failed")
```

Inside `MediaAsset`, after `content_hash`:

```python
    # Intrinsic pixel size of the ORIGINAL. `file` stays a FileField rather than
    # becoming an ImageField with width_field/height_field: the same column
    # carries the 232 video assets, which ImageField validation would reject.
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    # max_length=200, not the default 100 -- see the migration's docstring.
    thumb = models.FileField(
        upload_to="courses/media/derivatives/", max_length=200, blank=True
    )
    web = models.FileField(
        upload_to="courses/media/derivatives/", max_length=200, blank=True
    )
    derivatives_state = models.CharField(
        max_length=10, choices=DerivativesState.choices, blank=True, default=""
    )
```

- [ ] **Step 4: Generate and inspect the migration**

```bash
uv run python manage.py makemigrations courses --name mediaasset_derivatives
```

Open `courses/migrations/0059_mediaasset_derivatives.py` and confirm it is **five `AddField` operations and nothing else** — no `RunPython`, no `AlterField`. Add a module docstring:

```python
"""Schema-only: five AddField for the media-derivative pipeline.

No data migration. Populating the new fields for the ~953 existing mat-pp
images is the job of `backfill_media_derivatives`, which is resumable and
re-runnable; doing it here would make the migration long-running and
irreversible in practice. Fully reversible as written.
"""
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_media_derivatives_model.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Verify the migration is reversible**

```bash
uv run python manage.py migrate courses 0059
uv run python manage.py migrate courses 0058
uv run python manage.py migrate courses 0059
```

Expected: all three succeed. (A migration that cannot unapply is a known trap in this repo.)

- [ ] **Step 7: Commit**

```bash
git add courses/models.py courses/migrations/0059_mediaasset_derivatives.py tests/test_media_derivatives_model.py
git commit -m "feat(media): add derivative fields and DerivativesState to MediaAsset"
```

---

## Task 3: `courses/derivatives.py` — generation

The single most defect-dense unit in this change. Four of its rules exist because executed probes falsified the obvious implementation.

**Files:**
- Create: `courses/derivatives.py`
- Test: `tests/test_derivatives_generate.py`

**Interfaces:**
- Consumes: `DerivativesState`, `MediaAsset` (Task 2).
- Produces: `THUMB_WIDTH: int`, `WEB_WIDTH: int`, `generate_derivatives(asset) -> str` (assigns `asset.derivatives_state` **and** returns it), `delete_derivative_files(names: Iterable[str], storage) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_derivatives_generate.py`. Every fixture passes an explicit `size=` — `make_image_asset` defaults to a **1x1** PNG, which is narrower than both targets, so a default fixture returns `skipped` with blank fields and is indistinguishable from `failed`.

```python
import io

import pytest
from PIL import Image

from courses.derivatives import THUMB_WIDTH, WEB_WIDTH, generate_derivatives
from courses.models import DerivativesState
from tests.factories import CourseFactory, make_image_asset, make_video_asset


def _open(fieldfile):
    fieldfile.open("rb")
    try:
        return Image.open(io.BytesIO(fieldfile.read()))
    finally:
        fieldfile.close()


@pytest.mark.django_db
def test_generates_both_derivatives_at_exact_widths(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500))

    assert generate_derivatives(asset) == DerivativesState.OK

    assert asset.width == 2000 and asset.height == 1500
    assert _open(asset.thumb).size[0] == THUMB_WIDTH
    assert _open(asset.web).size[0] == WEB_WIDTH
    assert _open(asset.thumb).format == "WEBP"


@pytest.mark.django_db
def test_palette_source_produces_a_non_palette_derivative(course_with_image_media_root):
    """THE mode-P test. Image.resize downgrades resample to NEAREST for modes
    "1" and "P", silently ignoring LANCZOS -- verified against Pillow 12.2.0,
    where Image.new("P",(1000,800)).resize((320,256), LANCZOS) returns mode P,
    nearest-neighbour aliased, i.e. WORSE than the browser's own downscale.

    MUTANT: remove the convert() before resize. This test must go red.
    """
    course = CourseFactory()
    buf = io.BytesIO()
    Image.new("P", (2000, 1500)).save(buf, "PNG")
    asset = make_image_asset(course, "pal.png", raw=buf.getvalue())

    assert generate_derivatives(asset) == DerivativesState.OK
    assert _open(asset.thumb).mode != "P"


@pytest.mark.django_db
def test_animated_gif_is_skipped_and_produces_no_derivative(course_with_image_media_root):
    """ImageOps.exif_transpose returns a BASE Image, not the format subclass, so
    is_animated is ABSENT on the result and getattr(..., False) is always False
    -- verified on a real mat-pp asset (fibonacci_spiral.gif, 22 frames).
    Probing after the transpose flattens every animated GIF to a static WebP.

    Asserting "source still animated afterwards" is NOT sufficient: the source
    file on disk is never rewritten, so that clause passes on the broken build.
    The discriminating assertion is that no derivative was produced.

    MUTANT: move the is_animated probe to after exif_transpose. Must go red.
    """
    course = CourseFactory()
    buf = io.BytesIO()
    frames = [Image.new("P", (2000, 1500), c) for c in (0, 1, 2)]
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], duration=100)
    asset = make_image_asset(course, "anim.gif", raw=buf.getvalue())

    assert generate_derivatives(asset) == DerivativesState.SKIPPED
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert asset.width == 2000 and asset.height == 1500


@pytest.mark.django_db
def test_video_declines(course_with_image_media_root):
    course = CourseFactory()
    asset = make_video_asset(course, "v.mp4")
    assert generate_derivatives(asset) == DerivativesState.SKIPPED


@pytest.mark.django_db
def test_narrow_original_skips_the_wider_target(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "mid.png", size=(700, 500))
    assert generate_derivatives(asset) == DerivativesState.OK
    assert asset.thumb.name          # 700 > 512
    assert asset.web.name in ("", None)   # 700 <= 896


@pytest.mark.django_db
def test_original_narrower_than_both_targets_is_skipped(course_with_image_media_root):
    """The deliberate narrow case. Asserts SKIPPED *specifically*, not merely
    blank fields, because blank fields are also what `failed` looks like."""
    course = CourseFactory()
    asset = make_image_asset(course, "tiny.png", size=(300, 200))
    assert generate_derivatives(asset) == DerivativesState.SKIPPED


@pytest.mark.django_db
def test_zero_height_and_webp_cap_are_skipped_not_failed(course_with_image_media_root):
    """Verified against Pillow 12.2.0: a 3000x1 source rounds to height 0 ->
    ValueError("height and width must be > 0"); a 600x20000 source scales to
    (512, 17067) -> ValueError("encoding error 5: Image size exceeds WebP limit
    of 16383 pixels"). Both must land in `skipped`, not `failed`, because the
    backfill retries `failed` on EVERY run -- forever, for a structurally
    impossible image."""
    course = CourseFactory()
    flat = make_image_asset(course, "flat.png", size=(3000, 1))
    assert generate_derivatives(flat) == DerivativesState.SKIPPED

    tall = make_image_asset(course, "tall.png", size=(600, 20000))
    assert generate_derivatives(tall) == DerivativesState.SKIPPED


@pytest.mark.django_db
def test_rule_zero_clears_stale_fields(course_with_image_media_root):
    """Every early-return path must not leave the PREVIOUS image's values in
    place. Regenerating from a narrower source must blank `web`, not leave it
    pointing at the old picture's -896.webp.

    MUTANT: delete the rule-0 reset. Must go red.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500))
    generate_derivatives(asset)
    assert asset.web.name

    # Swap in a narrower original and regenerate.
    narrow = make_image_asset(course, "narrow.png", size=(700, 500))
    asset.file = narrow.file
    assert generate_derivatives(asset) == DerivativesState.OK
    assert asset.web.name in ("", None)


@pytest.mark.django_db
def test_corrupt_file_returns_failed_without_raising(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "bad.png", raw=b"not a png at all")
    assert generate_derivatives(asset) == DerivativesState.FAILED
    assert asset.thumb.name in ("", None)


@pytest.mark.django_db
def test_storage_failure_leaves_no_file_and_no_field(course_with_image_media_root, monkeypatch):
    """FieldFile.save ends by writing the name back onto the instance
    (setattr(self.instance, self.field.attname, name)), so a successful thumb
    write RE-POPULATES asset.thumb after rule 0 cleared it. Without an explicit
    re-blank, the handler deletes the bytes and the caller then persists a field
    pointing at nothing.

    MUTANT: drop the re-blank from the rule-9 handler. Must go red on the field
    assertion even though the file assertion still passes.
    """
    from django.core.files.storage import default_storage

    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500))

    calls = {"n": 0}
    real_save = default_storage.save

    def flaky_save(name, content, max_length=None):
        calls["n"] += 1
        if calls["n"] == 2:            # succeed on thumb, fail on web
            raise OSError("disk full")
        return real_save(name, content, max_length=max_length)

    monkeypatch.setattr(default_storage, "save", flaky_save)

    assert generate_derivatives(asset) == DerivativesState.FAILED
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert not default_storage.exists(f"courses/media/derivatives/wide-{THUMB_WIDTH}.webp")


@pytest.mark.django_db
def test_derivative_no_smaller_than_source_is_discarded_without_writing(
    course_with_image_media_root, monkeypatch
):
    """Asserted on the STORAGE backend, not just the field: encoding straight to
    storage and 'discarding' by blanking the field would leave orphaned bytes
    and burn a collision-suffix slot against the max_length budget."""
    from django.core.files.storage import default_storage

    course = CourseFactory()
    asset = make_image_asset(course, "noise.png", size=(2000, 1500), noise=True)
    # Force the discard branch by making the source appear enormous... instead,
    # assert the branch directly:
    monkeypatch.setattr("courses.derivatives._encode", lambda *a, **k: b"x" * 10**9)

    written = []
    real_save = default_storage.save
    monkeypatch.setattr(
        default_storage, "save",
        lambda n, c, max_length=None: (written.append(n), real_save(n, c, max_length=max_length))[1],
    )

    assert generate_derivatives(asset) == DerivativesState.SKIPPED
    assert written == []


@pytest.mark.django_db
def test_state_is_assigned_on_the_instance_not_only_returned(course_with_image_media_root):
    """Callers list derivatives_state in update_fields, so a version that only
    returned the value would persist the stale one while the correct one was
    discarded as an unused return."""
    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500))
    returned = generate_derivatives(asset)
    assert asset.derivatives_state == returned == DerivativesState.OK


@pytest.mark.django_db
def test_exif_orientation_is_applied(course_with_image_media_root):
    course = CourseFactory()
    buf = io.BytesIO()
    im = Image.new("RGB", (2000, 1000), "red")
    exif = im.getexif()
    exif[274] = 6                      # rotate 90 CW
    im.save(buf, "JPEG", exif=exif)
    asset = make_image_asset(course, "rot.jpg", raw=buf.getvalue())

    generate_derivatives(asset)
    assert asset.width == 1000 and asset.height == 2000
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_derivatives_generate.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'courses.derivatives'`.

- [ ] **Step 3: Add the fixtures the tests need**

In `tests/factories.py`, extend `make_image_asset` with `raw=` and `noise=` and the `derivatives=` flag (Task 5 uses the last one). **Explicit named parameters, never via `**kw`** — the factory splats `**kw` straight into `MediaAsset.objects.create()` and an unknown key raises on a model field:

```python
def make_image_asset(course, filename="x.png", size=(1, 1), color="black",
                     raw=None, noise=False, derivatives=False, **kw):
    """...existing docstring...

    `raw` supplies exact bytes (corrupt files, palette/animated GIFs, EXIF).
    `noise` fills with random pixels so the encoded size is realistic.
    `derivatives=True` runs generate_derivatives + persists -- REQUIRED for any
    assertion that depends on a derivative existing, because this factory calls
    MediaAsset.objects.create() directly and never routes through create_asset,
    so width alone generates nothing.
    """
    from io import BytesIO

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    if raw is None:
        buf = BytesIO()
        img = Image.new("RGB", size, color)
        if noise:
            import os
            img = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
        img.save(buf, "PNG")
        raw = buf.getvalue()
    kw.setdefault("kind", "image")
    kw.setdefault("original_filename", filename)
    kw.setdefault("file", SimpleUploadedFile(filename, raw))
    asset = MediaAsset.objects.create(course=course, **kw)
    if derivatives:
        from courses.derivatives import generate_derivatives

        generate_derivatives(asset)
        asset.save(update_fields=["width", "height", "thumb", "web", "derivatives_state"])
    return asset


def make_video_asset(course, filename="v.mp4", **kw):
    from django.core.files.uploadedfile import SimpleUploadedFile

    kw.setdefault("kind", "video")
    kw.setdefault("original_filename", filename)
    kw.setdefault("file", SimpleUploadedFile(filename, b"\x00" * 32))
    return MediaAsset.objects.create(course=course, **kw)
```

Add a `course_with_image_media_root` fixture in `tests/conftest.py` that redirects `MEDIA_ROOT` to `tmp_path` (mirroring the existing `course_with_image`).

- [ ] **Step 4: Write `courses/derivatives.py`**

```python
"""Image derivatives for MediaAsset: a 512px thumb and an 896px web copy.

Everything image-processing lives here. The rules below are ordered, and four
of them exist because the obvious implementation was measured to be wrong --
each carries the measurement in a comment. Do not reorder without re-reading
them.
"""
import io
import logging
import os

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from courses.models import DerivativesState

logger = logging.getLogger(__name__)

# Imported by courses/templatetags/courses_media_extras.py. These appear in the
# generator, the filenames and the `w` descriptors, so a future width change
# must not be able to drift the tag away from the bytes on disk.
THUMB_WIDTH = 512
WEB_WIDTH = 896

# WebP refuses either dimension above this.
_WEBP_MAX_DIMENSION = 16383

_ENCODER_KWARGS = {
    # method (0-6) swings lossless encode time several-fold, and generation runs
    # synchronously inside an upload request and in a loop over ~950 images.
    # exact=True preserves RGB values under fully-transparent pixels.
    "format": "WEBP",
    "lossless": True,
    "method": 4,
    "exact": True,
}


def _encode(img):
    """Encode to bytes in memory. Separate function so tests can force the
    discard branch without a pathological fixture."""
    buf = io.BytesIO()
    img.save(buf, **_ENCODER_KWARGS)
    return buf.getvalue()


def delete_derivative_files(names, storage):
    """Delete derivative files by NAME, immediately.

    Names, not an asset: every caller needs to delete files that are no longer
    the asset's -- replace_asset and backfill --force delete SUPERSEDED names
    captured before regeneration, and post_delete runs when the row is gone.

    Deletes IMMEDIATELY and does not defer. Stated because the neighbouring
    _delete_file_if_unshared in courses/media.py DOES call transaction.on_commit
    itself, so local precedent points the wrong way -- and the replace_asset
    failure handler needs an immediate delete, since an on_commit callback
    registered on a transaction that is about to roll back never runs.

    The falsy guard belongs here, not at the call sites: post_delete passes
    [thumb.name, web.name], both blank for every video and every skipped/failed
    row, and FileSystemStorage.delete("") raises ValueError while
    storage.exists("") is TRUTHY (it stats MEDIA_ROOT).
    """
    for name in names:
        if not name:
            continue
        try:
            if storage.exists(name):
                storage.delete(name)
        except Exception:  # noqa: BLE001 - cleanup must never mask the real error
            logger.exception("could not delete derivative %s", name)


def generate_derivatives(asset):
    """Populate width/height/thumb/web/derivatives_state. Never raises.

    Assigns asset.derivatives_state on the instance AND returns it: callers list
    that field in update_fields, so a version that only returned the value would
    persist the stale one while the correct one was discarded as an unused
    return.
    """
    # --- Rule 0: reset before any branch can return -------------------------
    # Every early-return path would otherwise leave the PREVIOUS image's values
    # in place -- on a replace where the new original is 500px wide, step 6
    # skips `web` and asset.web would still point at the old picture.
    asset.thumb = ""
    asset.web = ""
    asset.width = None
    asset.height = None
    asset.derivatives_state = ""

    if asset.kind != "image":
        asset.derivatives_state = DerivativesState.SKIPPED
        return asset.derivatives_state

    written = []
    storage = asset.thumb.storage
    try:
        asset.file.open("rb")
        try:
            raw = asset.file.read()
        finally:
            asset.file.close()

        with Image.open(io.BytesIO(raw)) as opened:
            # --- Rule 2: probe animation BEFORE any transpose ---------------
            # ImageOps.exif_transpose returns a BASE Image, not the format
            # subclass, so is_animated is ABSENT on the result and
            # getattr(..., False) is unconditionally False. Verified on a real
            # mat-pp asset: fibonacci_spiral.gif opens as GifImageFile with
            # is_animated=True, n_frames=22; after transpose the attribute is
            # gone. Probing after would flatten all 18 animated GIFs.
            is_animated = bool(getattr(opened, "is_animated", False))
            img = ImageOps.exif_transpose(opened)

            asset.width, asset.height = img.width, img.height

            if is_animated:
                asset.derivatives_state = DerivativesState.SKIPPED
                return asset.derivatives_state

            # --- Rule 5: normalise mode BEFORE resizing ---------------------
            # Image.resize downgrades resample to NEAREST for modes "1" and
            # "P", silently ignoring LANCZOS. Verified on Pillow 12.2.0.
            has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")

            source_size = asset.file.size
            stem = os.path.splitext(os.path.basename(asset.file.name))[0]

            for target, field in ((THUMB_WIDTH, "thumb"), (WEB_WIDTH, "web")):
                if img.width <= target:
                    continue
                height = max(1, round(img.height * target / img.width))
                if height > _WEBP_MAX_DIMENSION:
                    continue
                payload = _encode(img.resize((target, height), Image.LANCZOS))
                if len(payload) >= source_size:
                    continue          # a lossless WebP can exceed a JPEG source
                name = f"{stem}-{target}.webp"
                getattr(asset, field).save(name, ContentFile(payload), save=False)
                written.append(getattr(asset, field).name)

        asset.derivatives_state = (
            DerivativesState.OK if written else DerivativesState.SKIPPED
        )
        return asset.derivatives_state

    except Exception:  # noqa: BLE001 - the contract is "never raises"
        # Broad, and around the storage writes too: FieldFile.save can raise
        # SuspiciousFileOperation, permission/quota errors, or backend-specific
        # exceptions that are not Pillow exceptions.
        logger.exception("derivative generation failed for asset %s", asset.pk)
        delete_derivative_files(written, storage)
        # Re-blank explicitly. Rule 0 ran BEFORE the writes, and
        # FieldFile.save ends by writing the name back onto the instance, so a
        # successful thumb write re-populated the field after rule 0 cleared it.
        asset.thumb = ""
        asset.web = ""
        asset.derivatives_state = DerivativesState.FAILED
        return asset.derivatives_state
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_derivatives_generate.py -v
```

Expected: 13 passed.

- [ ] **Step 6: Falsify — run the four named mutants**

Apply each mutant **by hand** (never `git checkout` to revert — that destroys uncommitted work), confirm the named test goes RED, then edit it back out:

| Mutant | Must turn red |
| --- | --- |
| Move the `is_animated` probe to after `exif_transpose` | `test_animated_gif_is_skipped_and_produces_no_derivative` |
| Delete the `img.convert(...)` before resize | `test_palette_source_produces_a_non_palette_derivative` |
| Delete the rule-0 reset block | `test_rule_zero_clears_stale_fields` |
| Delete the re-blank in the `except` handler | `test_storage_failure_leaves_no_file_and_no_field` |

Record the four RED confirmations in the commit message.

- [ ] **Step 7: Commit**

```bash
git add courses/derivatives.py tests/test_derivatives_generate.py tests/factories.py tests/conftest.py
git commit -m "feat(media): add derivative generation with measured Pillow guards"
```

---

## Task 4: Deletion — `post_delete` removes derivative files

**Files:**
- Modify: `courses/signals.py`
- Test: `tests/test_derivatives_delete.py`

**Interfaces:**
- Consumes: `delete_derivative_files` (Task 3).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from django.core.files.storage import default_storage

from tests.factories import CourseFactory, make_image_asset, make_video_asset


@pytest.mark.django_db(transaction=True)
def test_deleting_an_asset_removes_both_derivative_files(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500), derivatives=True)
    thumb, web = asset.thumb.name, asset.web.name
    assert default_storage.exists(thumb) and default_storage.exists(web)

    asset.delete()

    assert not default_storage.exists(thumb)
    assert not default_storage.exists(web)


@pytest.mark.django_db(transaction=True)
def test_deleting_a_video_does_not_raise(course_with_image_media_root):
    """Both derivative fields are blank for every video (232 in mat-pp).
    FileSystemStorage.delete("") raises ValueError, and storage.exists("") is
    truthy because it stats MEDIA_ROOT -- so an unguarded implementation breaks
    ordinary video deletion."""
    course = CourseFactory()
    asset = make_video_asset(course, "v.mp4")
    asset.delete()          # must not raise


@pytest.mark.django_db(transaction=True)
def test_two_rows_sharing_one_file_name_keep_their_own_derivatives(
    course_with_image_media_root,
):
    """Migration 0008 copied storage references verbatim, so two MediaAsset rows
    can share one file.name -- the hazard _delete_file_if_unshared guards.
    Derivatives are generated per row and never shared, so deleting one must
    leave the other's intact. Requires REAL BYTES in storage."""
    course = CourseFactory()
    a = make_image_asset(course, "shared.png", size=(2000, 1500), derivatives=True)
    b = make_image_asset(course, "other.png", size=(2000, 1500))
    b.file.name = a.file.name          # the 0008 shape
    b.save(update_fields=["file"])
    from courses.derivatives import generate_derivatives

    generate_derivatives(b)
    b.save(update_fields=["width", "height", "thumb", "web", "derivatives_state"])

    assert a.thumb.name != b.thumb.name
    a.delete()

    assert default_storage.exists(b.thumb.name)
    assert default_storage.exists(b.web.name)
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_derivatives_delete.py -v
```

Expected: FAIL on the first test — derivative files survive.

- [ ] **Step 3: Extend the receiver**

In `courses/signals.py`, inside `_delete_mediaasset_file`, after the existing `storage = file.storage`:

```python
    # Derivative fields carry their OWN storage (a different field's storage
    # from instance.file.storage, even though both currently resolve to the
    # default backend). Available on a blank FieldFile, so reading it is safe.
    derivative_names = [instance.thumb.name, instance.web.name]
    derivative_storage = instance.thumb.storage
```

and inside `_remove`:

```python
    def _remove():
        if name and storage.exists(name):
            storage.delete(name)
        delete_derivative_files(derivative_names, derivative_storage)
```

Leave the `if not file: return` guard as it is — a derivative cannot exist without an original, since generation reads `asset.file`.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_derivatives_delete.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add courses/signals.py tests/test_derivatives_delete.py
git commit -m "feat(media): remove derivative files on asset delete"
```

---

## Task 5: `create_asset` and `get_or_create_asset` wiring

**Files:**
- Modify: `courses/media.py` (`create_asset`, ~line 106)
- Modify: `courses/lal_loader/media.py` (`get_or_create_asset`, ~line 35)
- Modify: `courses/transfer/importer.py:887`
- Test: `tests/test_derivatives_creation.py`

**Interfaces:**
- Consumes: `generate_derivatives` (Task 3).
- Produces: `create_asset(course, kind, uploaded_file, user, name="", generate=True)`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.media import create_asset
from courses.models import DerivativesState
from tests.factories import CourseFactory


def _png(size=(2000, 1500)):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return SimpleUploadedFile("up.png", buf.getvalue(), content_type="image/png")


@pytest.mark.django_db
def test_create_asset_populates_all_five_fields(course_with_image_media_root, admin_user):
    course = CourseFactory()
    asset = create_asset(course, "image", _png(), admin_user)
    assert asset.width == 2000 and asset.height == 1500
    assert asset.thumb.name and asset.web.name
    assert asset.derivatives_state == DerivativesState.OK
    asset.refresh_from_db()
    assert asset.thumb.name, "update_fields must include the derivative fields"


@pytest.mark.django_db
def test_generate_false_leaves_the_pending_state(course_with_image_media_root, admin_user):
    """width/height are None, not "" -- they are PositiveIntegerField(null=True),
    so a test written as 'all five stay ""' asserts the wrong thing for two."""
    course = CourseFactory()
    asset = create_asset(course, "image", _png(), admin_user, generate=False)
    assert asset.derivatives_state == ""
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert asset.width is None and asset.height is None


@pytest.mark.django_db
def test_lal_loader_generates_on_create_and_not_on_dedup(
    course_with_image_media_root, tmp_path
):
    """get_or_create_asset does NOT call create_asset -- it constructs
    MediaAsset(...) directly, so the `generate` keyword never reaches it.
    Generation goes before its existing asset.save(), which is a full save with
    no update_fields and therefore persists the new fields unchanged.

    The content_hash dedup early-return must NOT regenerate.
    """
    import io

    from PIL import Image

    from courses.lal_loader.media import get_or_create_asset

    course = CourseFactory()
    src = tmp_path / "d.png"
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), "blue").save(buf, "PNG")
    src.write_bytes(buf.getvalue())

    first = get_or_create_asset(course, "image", src)
    assert first.thumb.name
    first_thumb = first.thumb.name

    second = get_or_create_asset(course, "image", src)
    assert second.pk == first.pk
    assert second.thumb.name == first_thumb      # not regenerated
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_derivatives_creation.py -v
```

Expected: FAIL — `create_asset() got an unexpected keyword argument 'generate'`.

- [ ] **Step 3: Wire `create_asset`**

```python
def create_asset(course, kind, uploaded_file, user, name="", generate=True):
    asset = MediaAsset(...)          # unchanged
    asset.full_clean()
    asset.save()
    if generate:
        from courses.derivatives import generate_derivatives

        generate_derivatives(asset)
        asset.save(
            update_fields=["width", "height", "thumb", "web", "derivatives_state"]
        )
    return asset
```

- [ ] **Step 4: Wire `get_or_create_asset`**

In `courses/lal_loader/media.py`, between the `asset.file.save(...)` at `:45` and the `asset.save()` at `:46`:

```python
    asset.file.save(path.name, ContentFile(data), save=False)
    # Generate BEFORE the save below. Safe here -- and only here -- because the
    # line above already wrote the bytes to storage and set _committed=True, so
    # asset.file is a committed FieldFile. replace_asset differs: its file is
    # still an uncommitted UploadedFile until its own step 3, which is why
    # generate-before-save is forbidden there. The rule is "generate only
    # against a committed file", not "generate after Model.save()".
    from courses.derivatives import generate_derivatives

    generate_derivatives(asset)
    asset.save()          # full save, no update_fields -- persists everything
    return asset
```

- [ ] **Step 5: Make the transfer importer opt out**

At `courses/transfer/importer.py:887`:

```python
            asset = create_asset(
                course, m["kind"], wrapped, user, name=m["name"], generate=False
            )
```

Add above it:

```python
            # generate=False: _create_media loops over up to
            # TRANSFER_MAX_MEDIA_ENTRIES (1000) entries inside _run_import's
            # transaction.atomic(). At tens of ms per image that is 20-60s of
            # CPU added to one request holding an open write transaction.
            # Imported assets serve originals until the operator runs
            # `backfill_media_derivatives --course <slug>`, which blank-is-safe
            # makes correct rather than broken.
```

- [ ] **Step 6: Surface the follow-up in the import result**

Find where the import view builds its completion message and append:

```python
        _("Run `backfill_media_derivatives --course %(slug)s` to generate image "
          "derivatives for the imported media.") % {"slug": course.slug}
```

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/test_derivatives_creation.py tests/test_transfer_import.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add courses/media.py courses/lal_loader/media.py courses/transfer/importer.py tests/test_derivatives_creation.py
git commit -m "feat(media): generate derivatives at create_asset and the LAL loader"
```

---

## Task 6: `replace_asset` — the exact sequence

Both plausible orderings are broken. This task exists to pin one.

**Files:**
- Modify: `courses/media.py:150-184`
- Test: `tests/test_derivatives_replace.py`

**Interfaces:**
- Consumes: `generate_derivatives`, `delete_derivative_files` (Task 3).
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.media import replace_asset
from tests.factories import CourseFactory, make_image_asset


def _upload(size=(2400, 1800), name="new.png"):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "green").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.mark.django_db(transaction=True)
def test_replace_regenerates_and_deletes_the_superseded_files(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_thumb, old_web = asset.thumb.name, asset.web.name

    replace_asset(asset, _upload())

    assert asset.thumb.name != old_thumb
    assert not default_storage.exists(old_thumb)
    assert not default_storage.exists(old_web)
    asset.refresh_from_db()
    assert asset.width == 2400, "the five new fields must survive update_fields"


@pytest.mark.django_db(transaction=True)
def test_replace_does_not_delete_when_the_name_is_reused(course_with_image_media_root):
    """Storage hands back the SAME name when the old file was already missing,
    in which case the 'old' file is the one just written. Mirrors the guard the
    module already applies to the original at courses/media.py:180-183.

    MUTANT: drop the `!=` comparison. Must go red.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    default_storage.delete(asset.thumb.name)      # make the old derivative absent

    replace_asset(asset, _upload(name="old.png"))

    assert asset.thumb.name
    assert default_storage.exists(asset.thumb.name), (
        "the file written by this call must not be deleted as if it were the old one"
    )


@pytest.mark.django_db(transaction=True)
def test_a_raise_at_the_persist_step_leaves_no_new_bytes(
    course_with_image_media_root, monkeypatch
):
    """The only real raiser inside the try is step 5's save -- a DB write this
    change INTRODUCES; today's replace_asset has no DB write after step 3. When
    it raises, atomic() rolls the row back to the old file, but the NEW
    original's bytes were written at step 3 and nothing references them.

    The new original's delete goes through _delete_file_if_unshared's logic with
    .exclude(pk=asset.pk) -- NOT delete_derivative_files, and not the plain
    helper, which would be a guaranteed no-op: it defers via on_commit (never
    runs on a rolling-back transaction) and early-returns because
    filter(file=name).exists() sees the row's own uncommitted write.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_file = asset.file.name

    calls = {"n": 0}
    from django.db.models import Model

    real_save = Model.save

    def flaky(self, *a, **k):
        if isinstance(self, type(asset)) and k.get("update_fields") and \
           "derivatives_state" in k["update_fields"]:
            raise RuntimeError("boom")
        return real_save(self, *a, **k)

    monkeypatch.setattr(Model, "save", flaky)

    with pytest.raises(RuntimeError):
        replace_asset(asset, _upload())

    asset.refresh_from_db()
    assert asset.file.name == old_file
    orphans = [n for n in default_storage.listdir("courses/media")[1] if "new" in n]
    assert orphans == [], f"new original orphaned: {orphans}"


@pytest.mark.django_db(transaction=True)
def test_a_raise_before_generation_leaves_the_old_derivatives_intact(
    course_with_image_media_root,
):
    """replace_asset raises before step 4 on the empty-file path. At that point
    asset.thumb.name still holds the OLD, LIVE name -- a handler wrapping the
    whole body would destroy the surviving row's derivatives. The try must begin
    at step 4."""
    from django.core.exceptions import ValidationError

    course = CourseFactory()
    asset = make_image_asset(course, "old.png", size=(2000, 1500), derivatives=True)
    old_thumb = asset.thumb.name

    with pytest.raises(ValidationError):
        replace_asset(asset, SimpleUploadedFile("empty.png", b""))

    assert default_storage.exists(old_thumb)
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_derivatives_replace.py -v
```

Expected: FAIL — derivatives are not regenerated.

- [ ] **Step 3: Resequence `replace_asset`**

```python
@transaction.atomic
def replace_asset(asset, uploaded_file):
    """...existing docstring...

    ORDERING IS PINNED. Generating derivatives AFTER the step-3 save without
    extending update_fields silently drops the five new fields. Generating them
    BEFORE it reads asset.file while it is still an uncommitted UploadedFile:
    Pillow advances the stream and Django then writes to storage from the
    current position, truncating the stored original.
    """
    if not uploaded_file.size:
        raise ValidationError(_("The submitted file is empty."))

    # --- Step 1: capture, before any reassignment --------------------------
    old_name = asset.file.name
    old_storage = asset.file.storage
    old_thumb_name = asset.thumb.name
    old_web_name = asset.web.name
    derivative_storage = asset.thumb.storage

    # --- Step 2 + 3: assign, validate, commit the original -----------------
    asset.file = uploaded_file
    asset.original_filename = truncate_filename(uploaded_file.name)
    asset.content_hash = ""
    asset.full_clean(exclude=["course", "kind", "name", "uploaded_by"])
    asset.save(update_fields=["file", "original_filename", "content_hash"])

    # --- Steps 4 + 5, guarded ----------------------------------------------
    # The try begins HERE, not at the top: everything above can raise while
    # asset.thumb.name still holds the OLD, LIVE name, and a handler reading it
    # off the instance would destroy the surviving row's derivatives.
    try:
        from courses.derivatives import generate_derivatives

        generate_derivatives(asset)      # reads a COMMITTED FieldFile
        asset.save(
            update_fields=["width", "height", "thumb", "web", "derivatives_state"]
        )
    except Exception:
        # Django 5.2 has transaction.on_commit but NO on_rollback, and the
        # rollback happens at the @atomic decorator boundary after control has
        # left this function -- so cleanup must be immediate and inline.
        new_derivatives = [
            n for n in (asset.thumb.name, asset.web.name)
            if n and n not in (old_thumb_name, old_web_name)
        ]
        delete_derivative_files(new_derivatives, derivative_storage)
        # The new ORIGINAL goes through a share check that EXCLUDES this row --
        # _delete_file_if_unshared would be a no-op here, because it defers via
        # on_commit and because filter(file=name).exists() sees this row's own
        # uncommitted step-3 write and early-returns.
        if asset.file.name and asset.file.name != old_name:
            shared = (
                MediaAsset.objects.filter(file=asset.file.name)
                .exclude(pk=asset.pk)
                .exists()
            )
            if not shared and old_storage.exists(asset.file.name):
                old_storage.delete(asset.file.name)
        raise

    # --- Step 6: retire the superseded files, deferred ---------------------
    def _retire():
        stale = []
        if asset.thumb.name != old_thumb_name:
            stale.append(old_thumb_name)
        if asset.web.name != old_web_name:
            stale.append(old_web_name)
        delete_derivative_files(stale, derivative_storage)

    transaction.on_commit(_retire)
    if asset.file.name != old_name:
        _delete_file_if_unshared(old_name, old_storage)
    return asset
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_derivatives_replace.py tests/test_media_replace.py -v
```

Expected: all pass.

- [ ] **Step 5: Falsify the `!=` guard**

Remove the `if asset.thumb.name != old_thumb_name:` comparison by hand, confirm `test_replace_does_not_delete_when_the_name_is_reused` goes RED, then edit it back.

- [ ] **Step 6: Commit**

```bash
git add courses/media.py tests/test_derivatives_replace.py
git commit -m "feat(media): pin the replace_asset derivative sequence"
```

---

## Task 7: `backfill_media_derivatives` management command

**Files:**
- Create: `courses/management/commands/backfill_media_derivatives.py`
- Test: `tests/test_backfill_media_derivatives.py`

**Interfaces:**
- Consumes: `generate_derivatives`, `delete_derivative_files`, `DerivativesState`.
- Produces: the command.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django.core.files.storage import default_storage
from django.core.management import call_command

from courses.models import DerivativesState, MediaAsset
from tests.factories import CourseFactory, make_image_asset


@pytest.mark.django_db
def test_populates_pending_rows(course_with_image_media_root, capsys):
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug)
    a.refresh_from_db()
    assert a.derivatives_state == DerivativesState.OK
    assert a.thumb.name and a.web.name


@pytest.mark.django_db
def test_dry_run_writes_nothing_and_reports_counts(course_with_image_media_root, capsys):
    """--dry-run cannot report per-row outcomes: whether a row would produce
    derivatives, be skipped, or fail is only knowable by DECODING it. So the
    report is counts per derivatives_state, and the test asserts the counts --
    not merely the absence of writes, which would leave the output undefined."""
    course = CourseFactory()
    make_image_asset(course, "a.png", size=(2000, 1500))
    make_image_asset(course, "b.png", size=(2000, 1500))

    call_command("backfill_media_derivatives", course=course.slug, dry_run=True)

    out = capsys.readouterr().out
    assert "would process 2" in out
    assert MediaAsset.objects.filter(derivatives_state="").count() == 2


@pytest.mark.django_db
def test_second_run_is_a_no_op(course_with_image_media_root):
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug)
    a.refresh_from_db()
    first = a.thumb.name
    call_command("backfill_media_derivatives", course=course.slug)
    a.refresh_from_db()
    assert a.thumb.name == first


@pytest.mark.django_db
def test_skipped_rows_are_not_retried_but_failed_rows_are(course_with_image_media_root):
    course = CourseFactory()
    skipped = make_image_asset(course, "tiny.png", size=(300, 200))
    failed = make_image_asset(course, "bad.png", raw=b"nope")
    call_command("backfill_media_derivatives", course=course.slug)
    skipped.refresh_from_db(); failed.refresh_from_db()
    assert skipped.derivatives_state == DerivativesState.SKIPPED
    assert failed.derivatives_state == DerivativesState.FAILED

    # A second pass must reconsider `failed` and leave `skipped` alone.
    processed = call_command("backfill_media_derivatives", course=course.slug)
    skipped.refresh_from_db()
    assert skipped.derivatives_state == DerivativesState.SKIPPED


@pytest.mark.django_db
def test_force_regenerates_and_leaves_no_orphans(course_with_image_media_root):
    """FieldFile.save hands back a collision-suffixed name, the field repoints,
    and the previous file would be orphaned -- with repeated --force runs
    multiplying orphans and lengthening names against max_length=200."""
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500), derivatives=True)
    old_thumb = a.thumb.name

    call_command("backfill_media_derivatives", course=course.slug, force=True)

    a.refresh_from_db()
    if a.thumb.name != old_thumb:
        assert not default_storage.exists(old_thumb)


@pytest.mark.django_db
def test_start_at_skips_lower_pks(course_with_image_media_root):
    course = CourseFactory()
    a = make_image_asset(course, "a.png", size=(2000, 1500))
    b = make_image_asset(course, "b.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug, start_at=b.pk)
    a.refresh_from_db(); b.refresh_from_db()
    assert a.derivatives_state == ""
    assert b.derivatives_state == DerivativesState.OK


@pytest.mark.django_db
def test_one_corrupt_asset_does_not_abort_the_run(course_with_image_media_root):
    course = CourseFactory()
    bad = make_image_asset(course, "bad.png", raw=b"nope")
    good = make_image_asset(course, "good.png", size=(2000, 1500))
    call_command("backfill_media_derivatives", course=course.slug)
    good.refresh_from_db()
    assert good.derivatives_state == DerivativesState.OK
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_backfill_media_derivatives.py -v
```

Expected: FAIL — `Unknown command: 'backfill_media_derivatives'`.

- [ ] **Step 3: Write the command**

```python
"""Populate MediaAsset image derivatives.

Blank is the safe state, so this command may be interrupted, re-run, or never
run: the only consequence is that un-backfilled assets keep serving originals.
"""
from django.core.management.base import BaseCommand

from courses.derivatives import delete_derivative_files, generate_derivatives
from courses.models import DerivativesState, MediaAsset

_FIELDS = ["width", "height", "thumb", "web", "derivatives_state"]
# "" (never attempted) and failed are reprocessed; ok and skipped are left alone
# unless --force. Filtering against the TextChoices rather than string literals
# is what makes a typo'd state a hard error instead of a row silently
# reprocessed forever.
_PENDING = ["", DerivativesState.FAILED]


class Command(BaseCommand):
    help = "Generate thumb/web derivatives for MediaAsset images."

    def add_arguments(self, parser):
        parser.add_argument("--course", dest="course", default=None)
        parser.add_argument("--start-at", dest="start_at", type=int, default=None)
        parser.add_argument("--dry-run", dest="dry_run", action="store_true")
        parser.add_argument("--force", dest="force", action="store_true")

    def handle(self, *args, **opts):
        qs = MediaAsset.objects.filter(kind="image").order_by("pk")
        if opts["course"]:
            qs = qs.filter(course__slug=opts["course"])
        if opts["start_at"]:
            qs = qs.filter(pk__gte=opts["start_at"])
        if not opts["force"]:
            qs = qs.filter(derivatives_state__in=_PENDING)

        if opts["dry_run"]:
            # Counts only -- no per-row decode, and nothing written to storage
            # or the DB. Whether a given row WOULD produce derivatives is only
            # knowable by decoding it, so a richer report would reintroduce
            # exactly the work this flag exists to avoid.
            by_state = {}
            for state in ["", DerivativesState.OK, DerivativesState.SKIPPED,
                          DerivativesState.FAILED]:
                by_state[state or "(pending)"] = qs.filter(
                    derivatives_state=state
                ).count()
            self.stdout.write(f"would process {qs.count()} asset(s): {by_state}")
            return

        tally = {DerivativesState.OK: 0, DerivativesState.SKIPPED: 0,
                 DerivativesState.FAILED: 0}
        for i, asset in enumerate(qs.iterator(), start=1):
            old_thumb, old_web = asset.thumb.name, asset.web.name
            storage = asset.thumb.storage
            state = generate_derivatives(asset)      # never raises
            asset.save(update_fields=_FIELDS)
            # --force regenerates over non-blank fields, so retire whatever it
            # superseded -- same != guard as replace_asset step 6.
            stale = [n for n, new in ((old_thumb, asset.thumb.name),
                                      (old_web, asset.web.name))
                     if n and n != new]
            delete_derivative_files(stale, storage)
            tally[state] = tally.get(state, 0) + 1
            if i % 50 == 0:
                self.stdout.write(f"  {i} processed…")

        self.stdout.write(
            self.style.SUCCESS(
                f"done: {tally[DerivativesState.OK]} generated, "
                f"{tally[DerivativesState.SKIPPED]} skipped, "
                f"{tally[DerivativesState.FAILED]} failed"
            )
        )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_backfill_media_derivatives.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add courses/management/commands/backfill_media_derivatives.py tests/test_backfill_media_derivatives.py
git commit -m "feat(media): add backfill_media_derivatives command"
```

---

## Task 8: Repoint `imagezoom.js` (MUST land before any template converts)

`imagezoom.js:74` is `dialogImg.src = img.currentSrc || img.src`. Once a `srcset` exists, `currentSrc` resolves to the `web` derivative and **click-to-enlarge stops enlarging** — it shows the size already on screen. It does not fail loudly.

**Files:**
- Modify: `courses/static/courses/js/imagezoom.js`
- Modify: `templates/courses/lesson_unit.html:84`, `templates/courses/manage/editor/editor.html:206`, `templates/courses/quiz_unit.html:38`
- Modify: `courses/static/courses/css/courses.css`
- Modify: `locale/pl/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`
- Test: `tests/test_e2e_imagezoom_derivatives.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the `data-zoom-src` contract that Task 10's tag emits.

- [ ] **Step 1: Write the failing e2e test**

**Synthetic markup, not a converted template.** The ordering rule puts this commit *before* any template emits a derivative, so until then the rendered `src` **is** the original and "the dialog opens the original" passes identically on the un-repointed JS — the required A/B cannot go red.

```python
import pytest

pytestmark = pytest.mark.e2e

_INJECT = """
(() => {
  const img = document.querySelector('img[data-zoomable]');
  img.setAttribute('data-zoom-src', '/media/ORIGINAL.png');
  img.setAttribute('srcset', '/media/SMALL.png 512w, /media/ORIGINAL.png 2000w');
  img.setAttribute('sizes', '512px');
})()
"""


@pytest.mark.django_db(transaction=True)
def test_zoom_opens_the_original_not_the_selected_candidate(page, live_server, unit_with_image):
    page.goto(f"{live_server.url}{unit_with_image}")
    page.wait_for_selector("img[data-zoomable]")
    page.evaluate(_INJECT)

    selected = page.locator("img[data-zoomable]").evaluate("e => e.currentSrc")
    assert "SMALL" in selected, "fixture must make currentSrc differ from the original"

    page.locator(".imgzoom-trigger").first.click()
    opened = page.locator("dialog.imgzoom img").get_attribute("src")
    assert "ORIGINAL" in opened, (
        "the dialog must read data-zoom-src, not currentSrc — otherwise "
        "click-to-enlarge silently shows the size already on screen"
    )


@pytest.mark.django_db(transaction=True)
def test_zoom_shows_a_loading_state_then_the_image(page, live_server, unit_with_image):
    page.goto(f"{live_server.url}{unit_with_image}")
    page.route("**/slow.png", lambda route: page.wait_for_timeout(400) or route.continue_())
    page.evaluate(
        "document.querySelector('img[data-zoomable]')"
        ".setAttribute('data-zoom-src', '/media/slow.png')"
    )
    page.locator(".imgzoom-trigger").first.click()
    assert page.locator("dialog.imgzoom.is-loading").count() == 1


@pytest.mark.django_db(transaction=True)
def test_zoom_error_keeps_the_dialog_open_with_a_message(page, live_server, unit_with_image):
    page.goto(f"{live_server.url}{unit_with_image}")
    page.route("**/gone.png", lambda route: route.abort())
    page.evaluate(
        "document.querySelector('img[data-zoomable]')"
        ".setAttribute('data-zoom-src', '/media/gone.png')"
    )
    page.locator(".imgzoom-trigger").first.click()
    assert page.locator("dialog.imgzoom[open]").count() == 1
    assert page.locator(".imgzoom__error").is_visible()


@pytest.mark.django_db(transaction=True)
def test_a_failed_open_leaves_no_residue_on_the_next_open(page, live_server, unit_with_image):
    """close() currently resets only src, focus and the body class. The new
    loading/error state and the expectedSrc guard are additional visible state
    that nothing clears, so a broken image followed by a good one would leave
    the error message painted."""
    page.goto(f"{live_server.url}{unit_with_image}")
    page.route("**/gone.png", lambda route: route.abort())
    img = page.locator("img[data-zoomable]").first
    img.evaluate("e => e.setAttribute('data-zoom-src', '/media/gone.png')")
    page.locator(".imgzoom-trigger").first.click()
    page.keyboard.press("Escape")

    img.evaluate("e => e.setAttribute('data-zoom-src', e.src)")
    page.locator(".imgzoom-trigger").first.click()
    assert page.locator(".imgzoom__error").count() == 0 or \
        not page.locator(".imgzoom__error").is_visible()
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_e2e_imagezoom_derivatives.py -m e2e -v
```

Expected: FAIL — the dialog opens `SMALL.png`.

- [ ] **Step 3: Repoint the source and add the handlers**

In `imagezoom.js`, replace line 74 and add handlers next to the dialog's existing listeners:

```javascript
  // data-zoom-src, NOT currentSrc: once a srcset is present currentSrc resolves
  // to whichever candidate the browser picked for the on-page box, so reading it
  // would make "enlarge" show the size already on screen. Falls back to
  // currentSrc || src so non-tag <img data-zoomable> markup keeps working.
  var full = img.getAttribute("data-zoom-src") || img.currentSrc || img.src;
  expectedSrc = full;
  dialog.classList.add("is-loading");
  dialogImg.src = full;          // a GENUINE network fetch now, not a cache hit
```

Add, once, at dialog construction (mirroring `media_preview.js:49-58`'s `expectedSrc` pattern):

```javascript
  dialogImg.addEventListener("load", function () {
    if (dialogImg.getAttribute("src") !== expectedSrc) return;   // stale source
    dialog.classList.remove("is-loading");
  });
  dialogImg.addEventListener("error", function () {
    if (dialogImg.getAttribute("src") !== expectedSrc) return;
    dialog.classList.remove("is-loading");
    dialog.classList.add("is-errored");
    errorEl.textContent = label("loadFailed", "Could not load the full image.");
  });
```

Extend the existing `close` handler to reset the new state:

```javascript
    dialog.classList.remove("is-loading", "is-errored");
    errorEl.textContent = "";
    expectedSrc = null;
```

- [ ] **Step 4: Add the i18n keys to all three blobs**

`imagezoom.js` holds no inline strings — every user-visible string goes through `label(key, fallback)` off `window.IMAGEZOOM_I18N`, and that blob is declared **three times**. Update each of `lesson_unit.html:84`, `editor.html:206`, `quiz_unit.html:38`:

```html
<script>window.IMAGEZOOM_I18N = { enlarge: "{% trans 'Enlarge image' %}", dialog: "{% trans 'Enlarged image' %}", loading: "{% trans 'Loading…' %}", loadFailed: "{% trans 'Could not load the full image.' %}" };</script>
```

Then regenerate catalogs:

```bash
uv run python manage.py makemessages -l pl -l en
```

Review the diff for **fuzzy** entries — a fuzzy pre-fill silently ships a wrong translation, and clearing one means deleting both the `#, fuzzy` marker and the wrong `msgstr`. Fill the Polish strings, then:

```bash
uv run python manage.py compilemessages
```

- [ ] **Step 5: Add the CSS, respecting three existing source-level invariants**

`tests/test_imagezoom_render.py` pins that box rules are `.imgzoom[open]`-scoped, that **no unscoped `^\.imgzoom\s*\{` rule exists**, and (in `test_overlay_image_can_only_shrink`) that the slice from `.imgzoom-trigger` to EOF contains **no `100vw`** — a natural choice for a full-bleed overlay.

```css
.imgzoom[open].is-loading .imgzoom__img { opacity: 0; }
.imgzoom[open].is-loading::after {
  content: ""; position: absolute; inset-block-start: 50%; inset-inline-start: 50%;
  width: 2rem; height: 2rem; margin: -1rem 0 0 -1rem;
  border: 2px solid var(--border-default); border-top-color: var(--primary);
  border-radius: 50%; animation: imgzoom-spin .8s linear infinite;
}
.imgzoom[open] .imgzoom__error { display: none; color: var(--text-primary); padding: var(--space-4); }
.imgzoom[open].is-errored .imgzoom__error { display: block; }
@keyframes imgzoom-spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/test_e2e_imagezoom_derivatives.py -m e2e -v
uv run pytest tests/test_imagezoom_render.py -v
```

Expected: all pass, including the three source-level invariants.

- [ ] **Step 7: Falsify**

Revert the `data-zoom-src` read to `img.currentSrc || img.src` by hand; confirm `test_zoom_opens_the_original_not_the_selected_candidate` goes RED; edit it back.

- [ ] **Step 8: Commit**

```bash
git add courses/static/courses/js/imagezoom.js courses/static/courses/css/courses.css templates/courses/lesson_unit.html templates/courses/manage/editor/editor.html templates/courses/quiz_unit.html locale tests/test_e2e_imagezoom_derivatives.py
git commit -m "fix(imagezoom): read data-zoom-src so enlarge survives srcset"
```

---

## Task 9: Repoint `media_preview.js` (also before any template converts)

**Files:**
- Modify: `courses/static/courses/js/media_preview.js`
- Test: `tests/test_e2e_media_preview_derivatives.py`

**Interfaces:**
- Consumes: `.asset-cell[data-url]`, which `_asset_cell.html:3` already emits.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```python
import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.django_db(transaction=True)
def test_hover_preview_loads_the_original_not_the_thumb(page, live_server, media_manager_url):
    """Synthetic markup for the same ordering reason as the zoom test: until
    _asset_cell.html converts, the thumb's src IS the original and this
    assertion passes on the un-repointed JS."""
    page.goto(f"{live_server.url}{media_manager_url}")
    page.wait_for_selector(".asset-cell")
    page.evaluate(
        """() => {
             const cell = document.querySelector('.asset-cell');
             cell.setAttribute('data-url', '/media/ORIGINAL.png');
             cell.querySelector('[data-asset-preview]').setAttribute('src', '/media/THUMB.png');
           }"""
    )
    page.hover(".asset-cell [data-asset-preview]")
    page.wait_for_selector(".asset-preview [data-asset-preview-img]")
    src = page.locator("[data-asset-preview-img]").get_attribute("src")
    assert "ORIGINAL" in src


@pytest.mark.django_db(transaction=True)
def test_broken_original_shows_caption_only_via_the_error_handler(
    page, live_server, media_manager_url
):
    """After the repoint, `anchor.complete && anchor.naturalWidth === 0`
    interrogates the THUMB while a different URL is loading, so a broken
    original would yield a silently empty overlay. That branch moves to the
    overlay image's own error handler (which already exists at :54-58)."""
    page.route("**/broken-original.png", lambda route: route.abort())
    page.goto(f"{live_server.url}{media_manager_url}")
    page.evaluate(
        "document.querySelector('.asset-cell')"
        ".setAttribute('data-url', '/media/broken-original.png')"
    )
    page.hover(".asset-cell [data-asset-preview]")
    page.wait_for_selector(".asset-preview")
    assert not page.locator("[data-asset-preview-img]").is_visible()
    assert page.locator(".asset-preview__caption").is_visible()


@pytest.mark.django_db(transaction=True)
def test_the_caption_paints_before_the_image(page, live_server, media_manager_url):
    """Accepted consequence: today the overlay copies the grid img's
    already-loaded original and paints instantly; after the repoint it fetches
    an uncached original on every hover, so it degrades to caption-first."""
    page.goto(f"{live_server.url}{media_manager_url}")
    page.hover(".asset-cell [data-asset-preview]")
    page.wait_for_selector(".asset-preview__caption")
    assert page.locator(".asset-preview__caption").inner_text() != ""
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_e2e_media_preview_derivatives.py -m e2e -v
```

Expected: FAIL — the overlay loads `THUMB.png`.

- [ ] **Step 3: Repoint, and split the guard**

Replace line 171-172:

```javascript
    // data-url off the CELL, not the thumb's own src: once the grid serves a
    // derivative, the thumb's src is no longer the full-resolution image.
    var cell = anchor.closest(".asset-cell");
    var src = (cell && cell.getAttribute("data-url")) || "";
    // Only the !src half of the old guard survives here. Its own comment
    // explains why it cannot be delegated: assigning "" does not reliably fire
    // error and can leave the PREVIOUS image showing. The
    // `complete && naturalWidth === 0` half moves to the overlay's own error
    // handler (:54-58) -- after the repoint it would be interrogating the thumb
    // while a different URL loads.
    if (!src) {
      captionOnly();
      return;
    }
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_e2e_media_preview_derivatives.py -m e2e -v
uv run pytest tests/test_e2e_media_manager.py -m e2e -v
```

Expected: all pass. `test_a_thumbnail_that_never_loaded_shows_the_caption_only` (`:1226-1237`) now passes for a *different* reason — its `page.route(abort)` also kills the overlay's own fetch, so it exercises the `error` handler and duplicates `test_a_404_source_shows_the_caption_and_no_image_box` (`:1200`). Merge the two, recording the reason in the commit message.

- [ ] **Step 5: Commit**

```bash
git add courses/static/courses/js/media_preview.js tests/test_e2e_media_preview_derivatives.py tests/test_e2e_media_manager.py
git commit -m "fix(media-preview): read the cell data-url so hover survives derivatives"
```

---

## Task 10: The `media_img` template tag

**Files:**
- Create: `courses/templatetags/courses_media_extras.py`
- Test: `tests/test_media_img_tag.py`

**Interfaces:**
- Consumes: `THUMB_WIDTH`, `WEB_WIDTH` (Task 3); the measurement table (Task 1).
- Produces: `{% media_img asset preset=… alt=… css_class=… extra=… %}`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from django.template import Context, Template

from courses.models import ImageElement, TableElement
from tests.factories import CourseFactory, make_image_asset, make_video_asset


def render(**ctx):
    tpl = Template(
        "{% load courses_media_extras %}"
        "{% media_img asset preset=preset alt=alt css_class=css_class extra=extra %}"
    )
    ctx.setdefault("alt", "")
    ctx.setdefault("css_class", "")
    ctx.setdefault("extra", "")
    return tpl.render(Context(ctx))


@pytest.mark.django_db
def test_fixed_box_presets_use_the_thumb_as_src_and_emit_no_srcset(
    course_with_image_media_root,
):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="grid")
    assert asset.thumb.url in html
    assert "srcset" not in html


@pytest.mark.django_db
def test_an_80px_cell_loads_the_thumb_not_the_original(course_with_image_media_root):
    """The single-candidate presets are where a broken implementation would
    otherwise be invisible: no srcset to inspect, so only what `src` points at
    discriminates."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="cell-small")
    assert asset.thumb.url in html
    assert asset.file.url not in html


@pytest.mark.django_db
def test_fluid_presets_emit_srcset_sizes_and_an_original_src(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="el-full")
    assert f'src="{asset.file.url}"' in html
    assert "srcset=" in html and "sizes=" in html
    assert f"{asset.thumb.url} 512w" in html
    assert f"{asset.web.url} 896w" in html
    assert f"{asset.file.url} 2000w" in html


@pytest.mark.django_db
def test_sizes_is_present_on_every_w_descriptor_preset(course_with_image_media_root):
    """MUTANT: delete the sizes attribute. A srcset WITHOUT sizes defaults to
    100vw and makes the browser pick the LARGEST candidate — the exact silent
    no-op this design exists to prevent."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    for preset in ("el-small", "el-medium", "el-large", "el-full",
                   "cell-large", "gallery", "dragimage"):
        assert "sizes=" in render(asset=asset, preset=preset), preset


@pytest.mark.django_db
def test_cell_full_emits_the_original_and_no_srcset(course_with_image_media_root):
    """cell-full sits in an auto-layout table whose column width derives from
    the image's intrinsic contribution, so ANY change to what it loads moves the
    column: measured, srcset moved the td 580.28 -> 498.72 and a thumb src moved
    it to 574.25. data-zoom-src is the only tag-emitted marker that
    distinguishes a converted cell-full from an unconverted one."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="cell-full", extra="data-zoomable")
    assert f'src="{asset.file.url}"' in html
    assert "srcset" not in html and "sizes" not in html
    assert "data-zoom-src" in html


@pytest.mark.django_db
def test_no_preset_emits_width_or_height(course_with_image_media_root):
    """Measured: with a binding max-height, a definite width makes the axes
    clamp independently and portrait images distort 100-260px; on the grid,
    attributes make the cell 130x841 instead of 130x98."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    for preset in ("grid", "cell-small", "cell-medium", "cell-large", "cell-full",
                   "el-small", "el-medium", "el-large", "el-full",
                   "gallery", "dragimage"):
        html = render(asset=asset, preset=preset)
        assert "width=" not in html and "height=" not in html, preset


@pytest.mark.django_db
def test_omission_rule_fires_when_the_asset_is_narrower_than_the_declared_sizes(
    course_with_image_media_root,
):
    """MUTANT: remove the width comparison, leaving only the no-derivative
    check. This is the SOLE layout protection and the mutant that matters most —
    a build that deletes it passes every other mutant."""
    course = CourseFactory()
    # Wider than THUMB_WIDTH so a thumb exists, narrower than el-full's declared
    # sizes width (see the measurements doc for the chosen value).
    narrow = make_image_asset(course, "n.png", size=(600, 400), derivatives=True)
    html = render(asset=narrow, preset="el-full")
    assert "srcset" not in html and "sizes" not in html


@pytest.mark.django_db
def test_omission_rule_fires_when_no_derivative_exists(course_with_image_media_root):
    """Independent of the width comparison: cell-large declares sizes=240px,
    which is BELOW THUMB_WIDTH (512), so a 400px original is narrower than both
    targets (no derivative) yet WIDER than 240 — the width comparison does not
    fire and only this check catches it. Neither may be dropped as redundant."""
    course = CourseFactory()
    tiny = make_image_asset(course, "t.png", size=(400, 300), derivatives=True)
    html = render(asset=tiny, preset="cell-large")
    assert "srcset" not in html


@pytest.mark.django_db
def test_degenerate_inputs_render_nothing(course_with_image_media_root):
    course = CourseFactory()
    assert render(asset=None, preset="el-full").strip() == ""
    blank = make_image_asset(course, "b.png", size=(2000, 1500))
    blank.file.name = ""
    assert render(asset=blank, preset="el-full").strip() == ""
    video = make_video_asset(course, "v.mp4")
    assert render(asset=video, preset="el-full").strip() == ""


@pytest.mark.django_db
def test_unknown_preset_raises(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    with pytest.raises(ValueError):
        render(asset=asset, preset="nope")


@pytest.mark.django_db
def test_every_stored_size_value_maps_to_a_preset_key():
    """Stated PER VALUE deliberately: the preset keys are prefixed, so the raw
    key set is NOT literally a superset of {small,medium,large,full}, and a test
    written from that looser wording fails and then gets weakened."""
    from courses.templatetags.courses_media_extras import PRESETS

    for v in ImageElement.Size.values:
        assert f"el-{v}" in PRESETS
    for v in TableElement.CellImageSize.values:
        assert f"cell-{v}" in PRESETS


@pytest.mark.django_db
def test_loading_lazy_is_grid_only(course_with_image_media_root):
    """Student element templates do NOT get lazy: a unit page carries tens of
    images rather than ~950, and printed lessons are an intended surface that a
    below-the-fold deferral would break."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    assert 'loading="lazy"' in render(asset=asset, preset="grid")
    for preset in ("el-full", "cell-small", "gallery", "dragimage"):
        assert 'loading="lazy"' not in render(asset=asset, preset=preset), preset


@pytest.mark.django_db
def test_data_zoom_src_only_where_data_zoomable(course_with_image_media_root):
    """data-zoom-src is consumed only by imagezoom.js, armed off [data-zoomable].
    Emitting a full media URL into each of ~950 grid cells would inflate the
    2.1MB HTML figure this change makes a required before/after measurement."""
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    assert "data-zoom-src" not in render(asset=asset, preset="grid")
    html = render(asset=asset, preset="el-full", extra="data-zoomable")
    assert f'data-zoom-src="{asset.file.url}"' in html


@pytest.mark.django_db
def test_extra_rejects_anything_outside_the_allow_list(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    with pytest.raises(ValueError):
        render(asset=asset, preset="el-full", extra="onclick")
    with pytest.raises(ValueError):
        render(asset=asset, preset="el-full", extra='data-x="1"')


@pytest.mark.django_db
def test_alt_round_trips_and_is_escaped(course_with_image_media_root):
    course = CourseFactory()
    asset = make_image_asset(course, "w.png", size=(2000, 1500), derivatives=True)
    html = render(asset=asset, preset="el-full", alt='A "quoted" <diagram>')
    assert "&quot;quoted&quot;" in html or "&#x27;" in html or "&lt;diagram&gt;" in html
    assert 'alt=""' in render(asset=asset, preset="grid")
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_media_img_tag.py -v
```

Expected: FAIL — `'courses_media_extras' is not a registered tag library`.

- [ ] **Step 3: Write the tag**

Fill `SIZES` from the committed measurements document — **do not invent values**.

```python
"""The single <img> emitter for MediaAsset images.

A simple_tag returning format_html, NOT an inclusion_tag: an inclusion_tag
performs a full template load-and-render per invocation, i.e. ~950 nested
renders on the manager grid where there are currently zero.

DELIBERATE COUPLING: the SIZES values below are derived from measured box
geometry recorded in
docs/superpowers/plans/2026-08-17-media-image-derivatives-measurements.md.
A change to .cell-img--large, .el--image--*, .gallery__frame or
.dragimage__stage in courses.css must be accompanied by re-measuring and
updating the matching entry here.
"""
from django import template
from django.utils.html import format_html

from courses.derivatives import THUMB_WIDTH, WEB_WIDTH

register = template.Library()

# Only boolean attribute NAMES. format_html escapes interpolated arguments, so a
# valued attribute would be escaped into visible text, and marking the argument
# safe would make this tag an HTML injection sink.
_ALLOWED_EXTRA = frozenset({"data-asset-preview", "data-zoomable"})

FIXED = "fixed"      # src = thumb, no srcset
FLUID = "fluid"      # src = original + w-descriptor srcset + sizes
ORIGINAL = "original"  # src = original, nothing else

# sizes strings: THREE clauses. The middle one is fitted to BOTH the 641 and
# 1039 measurements -- sourcing it at 900 under-declares by ~60px, and a bare px
# value at 1039 over-declares by ~2.5x at the bottom of the band.
PRESETS = {
    "grid":        (FIXED, None),
    "cell-small":  (FIXED, None),
    "cell-medium": (FIXED, None),
    "cell-large":  (FLUID, "240px"),
    "cell-full":   (ORIGINAL, None),
    "el-small":    (FLUID, "<<FROM MEASUREMENTS DOC: el-small>>"),
    "el-medium":   (FLUID, "<<FROM MEASUREMENTS DOC: el-medium>>"),
    "el-large":    (FLUID, "<<FROM MEASUREMENTS DOC: el-large>>"),
    "el-full":     (FLUID, "<<FROM MEASUREMENTS DOC: el-full>>"),
    "gallery":     (FLUID, "<<FROM MEASUREMENTS DOC: gallery>>"),
    "dragimage":   (FLUID, "<<FROM MEASUREMENTS DOC: dragimage>>"),
}

# The largest width each preset's sizes can resolve to at the measurement
# viewports -- the omission threshold. Filled from the same document.
_DECLARED_MAX = {
    "cell-large": 240,
    "el-small": None, "el-medium": None, "el-large": None, "el-full": None,
    "gallery": None, "dragimage": None,
}


@register.simple_tag
def media_img(asset, preset, alt="", css_class="", extra=""):
    if preset not in PRESETS:
        raise ValueError(f"unknown media_img preset: {preset!r}")
    strategy, sizes = PRESETS[preset]

    if asset is None or not asset.file.name or asset.kind != "image":
        return ""

    names = [n for n in extra.split() if n]
    bad = [n for n in names if n not in _ALLOWED_EXTRA]
    if bad:
        raise ValueError(f"media_img extra must be boolean attribute names: {bad}")

    thumb = asset.thumb.url if asset.thumb.name else None
    web = asset.web.url if asset.web.name else None
    original = asset.file.url

    if strategy == FIXED:
        src = thumb or original
        srcset = sizes_attr = ""
    elif strategy == ORIGINAL:
        src = original
        srcset = sizes_attr = ""
    else:
        src = original
        candidates = []
        if thumb:
            candidates.append(f"{thumb} {THUMB_WIDTH}w")
        if web:
            candidates.append(f"{web} {WEB_WIDTH}w")
        # A w descriptor without a real pixel width is a lie the browser acts on.
        emit = bool(candidates) and asset.width is not None and asset.height is not None
        # The omission rule: the SOLE layout protection. Independent of the
        # no-derivative check above -- cell-large's declared width (240) is below
        # THUMB_WIDTH, so neither subsumes the other.
        declared = _DECLARED_MAX.get(preset)
        if declared is not None and asset.width is not None and asset.width <= declared:
            emit = False
        if emit:
            candidates.append(f"{original} {asset.width}w")
            srcset = " ".join(['srcset="' + ", ".join(candidates) + '"'])
            sizes_attr = f'sizes="{sizes}"'
        else:
            srcset = sizes_attr = ""

    bits = [f'src="{src}"']
    if srcset:
        bits.append(srcset)
    if sizes_attr:
        bits.append(sizes_attr)
    if preset == "grid":
        bits.append('loading="lazy"')
    if "data-zoomable" in names:
        bits.append(f'data-zoom-src="{original}"')
    bits.extend(names)

    return format_html(
        '<img class="{}" alt="{}" {}>',
        css_class, alt, format_html(" ".join("{}" for _ in bits), *bits),
    )
```

> **Note for the implementer:** the `format_html` composition above must escape
> `css_class` and `alt` while leaving the attribute fragments intact. If the
> nested-`format_html` form proves awkward, use
> `django.forms.utils.flatatt` over a dict instead — but the escaping contract
> (values escaped, attribute names allow-listed) is not negotiable.

- [ ] **Step 4: Fill the `SIZES` and `_DECLARED_MAX` placeholders**

Replace every `<<FROM MEASUREMENTS DOC: …>>` with the value derived in Task 1, and fill `_DECLARED_MAX` with each preset's largest resolvable width. **The plan is not complete until no placeholder remains in this file** — a placeholder here is a `sizes` value invented rather than measured, which is the failure the whole measurement protocol exists to prevent.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_media_img_tag.py -v
```

Expected: 15 passed.

- [ ] **Step 6: Falsify the two omission mutants**

| Mutant | Must turn red |
| --- | --- |
| Delete the `declared is not None and asset.width <= declared` comparison | `test_omission_rule_fires_when_the_asset_is_narrower_than_the_declared_sizes` |
| Delete the `bool(candidates)` check | `test_omission_rule_fires_when_no_derivative_exists` |
| Delete `sizes_attr` | `test_sizes_is_present_on_every_w_descriptor_preset` |

- [ ] **Step 7: Commit**

```bash
git add courses/templatetags/courses_media_extras.py tests/test_media_img_tag.py
git commit -m "feat(media): add the media_img tag with measured sizes values"
```

---

## Task 11: Convert the two grid templates

Only after Tasks 8 and 9 are committed and green.

**Files:**
- Modify: `templates/courses/manage/media/_asset_cell.html:7`
- Modify: `templates/courses/manage/media/_picker_grid.html:6`
- Test: `tests/test_media_manager.py` (extend)

**Interfaces:**
- Consumes: `media_img` (Task 10).
- Produces: nothing.

- [ ] **Step 1: Write the failing conversion assertions**

```python
@pytest.mark.django_db
def test_manager_grid_renders_the_thumb_and_keeps_its_hooks(client, admin_user, ...):
    """A forgotten template must be RED, not invisible: the tag unit tests pass
    and the geometry tests pass trivially if a template was never converted."""
    ...
    html = response.content.decode()
    assert asset.thumb.url in html
    assert 'class="asset-thumb"' in html
    assert "data-asset-preview" in html      # media_preview.js is armed off this
    assert 'loading="lazy"' in html


@pytest.mark.django_db
def test_picker_grid_renders_the_thumb_and_does_not_arm_the_preview(client, ...):
    html = ...
    assert asset.thumb.url in html
    assert "data-asset-preview" not in html
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_media_manager.py -k "grid_renders" -v
```

Expected: FAIL — the original URL is rendered.

- [ ] **Step 3: Convert `_asset_cell.html`**

Line 1 becomes `{% load i18n courses_manage_extras courses_media_extras %}` (append to the existing tag). Line 7 becomes:

```html
    {% media_img asset preset="grid" css_class="asset-thumb" extra="data-asset-preview" %}
```

- [ ] **Step 4: Convert `_picker_grid.html`**

Line 1 becomes `{% load i18n courses_media_extras %}`. Line 6's image branch becomes:

```html
      {% if asset.kind == "image" %}{% media_img asset preset="grid" css_class="asset-thumb" %}
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_media_manager.py -v
uv run pytest tests/test_e2e_media_manager.py -m e2e -v
```

Expected: pass, **except** `test_hover_opens_the_overlay_with_the_thumbnails_source` (`:866`), which asserts `img.currentSrc === thumb.currentSrc` and is now false **by construction**.

- [ ] **Step 6: Invert the hover test**

Its fixture must be recreated with `derivatives=True` — width alone generates nothing. Rename and invert:

```python
@pytest.mark.django_db(transaction=True)
def test_hover_opens_the_overlay_with_the_full_resolution_source(page, live_server):
    """Renamed and inverted deliberately: the old name encoded the contract this
    change reverses. Lands HERE, in the template-conversion commit, not in the
    JS commit — through the JS commit the thumb's src is still the original, so
    the old assertion stayed green there and the ordering rule could not
    surface it."""
    user, course = _seed_assets("hov-pa", "hov", ("wide_0_1.png", (800, 200)),
                                derivatives=True)
    _open_manager(page, live_server, "hov-pa", course)
    page.hover(".asset-cell [data-asset-preview]")
    page.wait_for_selector("[data-asset-preview-img]")
    overlay = page.locator("[data-asset-preview-img]").evaluate("e => e.currentSrc")
    thumb = page.locator("[data-asset-preview]").evaluate("e => e.currentSrc")
    cell_url = page.locator(".asset-cell").get_attribute("data-url")
    assert overlay.endswith(cell_url)
    assert overlay != thumb
```

- [ ] **Step 7: Commit**

```bash
git add templates/courses/manage/media/_asset_cell.html templates/courses/manage/media/_picker_grid.html tests/test_media_manager.py tests/test_e2e_media_manager.py
git commit -m "feat(media): serve thumbnails in the manager and picker grids"
```

---

## Task 12: Convert the five student templates

**Files:**
- Modify: `templates/courses/elements/imageelement.html`
- Modify: `templates/courses/elements/_table_cell.html`
- Modify: `templates/courses/elements/_filltable_cell.html`
- Modify: `templates/courses/elements/dragtoimagequestionelement.html` (**two** `<img>`, lines 9 and 32)
- Modify: `templates/courses/elements/galleryelement.html` + its docblock
- Modify: `courses/models.py` — `GalleryElement.render()` figure dict
- Test: per-template assertions

**Interfaces:**
- Consumes: `media_img` (Task 10).
- Produces: `figures` entries of shape `{"asset": MediaAsset, "alt": str, "desc": str}`.

- [ ] **Step 1: Write one conversion assertion per template**

For the two cell partials, assert against a **`small`/`medium`/`large`** cell — `full` emits neither a derivative nor a `srcset`, so a generic assertion would fail on a *correct* build and get weakened.

```python
@pytest.mark.django_db
def test_image_element_renders_a_srcset(course_with_image_media_root):
    ...
    assert "srcset=" in html and asset.web.url in html

@pytest.mark.django_db
def test_table_cell_medium_renders_the_thumb(course_with_image_media_root):
    ...
    assert asset.thumb.url in html

@pytest.mark.django_db
def test_table_cell_full_renders_the_original_and_no_srcset(course_with_image_media_root):
    ...
    assert asset.file.url in html
    assert "srcset" not in html
    assert "data-zoom-src" in html      # the only converted-vs-not marker here

@pytest.mark.django_db
def test_filltable_cell_medium_renders_the_thumb(course_with_image_media_root): ...

@pytest.mark.django_db
def test_dragtoimage_renders_a_srcset_in_both_branches(course_with_image_media_root):
    """Two <img>, not one: the interactive {% if element %} branch at :9 and the
    {% else %} fallback at :32."""
    ...

@pytest.mark.django_db
def test_gallery_renders_a_srcset(course_with_image_media_root): ...
```

- [ ] **Step 2: Run to verify they fail**

Expected: FAIL — originals are rendered.

- [ ] **Step 3: Change `GalleryElement.render()`**

At `courses/models.py:1649-1651`:

```python
            figures.append(
                {"asset": img["media"], "desc": img["desc"], "alt": alt}
            )
```

`url` is dropped entirely. Update the template docblock (lines 1–7 of `galleryelement.html`) from `({url, alt, desc})` to `({asset, alt, desc})` — it is load-bearing documentation that would otherwise go stale.

- [ ] **Step 4: Convert the templates**

`imageelement.html` — line 1 gains `{% load courses_media_extras %}` on its own line (safe: a block-level `<figure>` collapses a leading newline). Line 2:

```html
  {% with sz=el.size|default:"full" %}{% media_img el.media preset="el-"|add:sz alt=el.alt extra="data-zoomable" %}{% endwith %}
```

**The `{% with %}` wraps the `<img>` line only — line 1 is untouched.** Line 1 is `class="el el--image el--image--{{ el.size }}"` with no `|default:`, and extending the `{% with %}` over it would look like a tidy-up while silently changing rendered bytes on a `size`-less context.

`_table_cell.html` and `_filltable_cell.html` — the load tag and the whole `{% with %}…{% endwith %}` go **inline on the existing first line**, with no newline or indentation between tags. `tableelement.html` wraps its includes in `{% spaceless %}`, but `filltableelement.html` has **none** (stated at `tableelement.html:19-21`), so an expanded form would change bytes for every fill-table image cell, and the existing byte-guard (`test_table_render.py:122`) covers only a *text* cell.

```html
{% load i18n courses_media_extras %}{% if cell.kind == "image" %}{% with sz=cell.size|default:"full" %}{% media_img cell.media preset="cell-"|add:sz alt=cell.alt css_class="cell-img cell-img--"|add:sz extra="data-zoomable" %}{% endwith %}{% else %}…
```

`dragtoimagequestionelement.html` — line 1 appends to the existing `{% load i18n l10n courses_extras %}`. Both `<img>` (`:9`, `:32`) become:

```html
        {% media_img el.media preset="dragimage" alt=el.alt css_class="dragimage__img" %}
```

`galleryelement.html` — line 14:

```html
      <div class="gallery__frame">{% media_img f.asset preset="gallery" alt=f.alt extra="data-zoomable" %}</div>
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_table_render.py tests/test_gallery_render.py tests/test_imagezoom_render.py courses/tests/test_image_size_render.py tests/test_table_cell_images.py -v
```

Expected: the six new assertions pass; `test_table_render.py:94` fails (it asserts `src="{asset.file.url}"`, which contradicts the new `cell-*` rule).

- [ ] **Step 6: Audit the existing assertions**

Grep by **template path across both `tests/` and `courses/tests/`**, and also for `ImageElement`, `GalleryElement`, `TableElement`, `resolved_cells`, `naturalWidth`, `data-zoomable`, `asset-thumb` — a path-only grep misses the e2e suites entirely.

```bash
grep -rn "imageelement\|_table_cell\|_filltable_cell\|galleryelement\|dragtoimage\|_asset_cell\|_picker_grid" tests/ courses/tests/
grep -rln "ImageElement\|GalleryElement\|TableElement\|naturalWidth\|data-zoomable\|asset-thumb" tests/ courses/tests/
```

Record every hit and its disposition in the commit message. Known:

| Test | Disposition |
| --- | --- |
| `tests/test_table_render.py:94` | Update to expect the thumb |
| `tests/test_table_render.py:99-119` | Keeps working via the retained `|default:'full'`; fixture must be a real asset |
| `tests/test_imagezoom_render.py:52,58,69` | **Fixtures break** — duck-typed `SimpleNamespace(file=SimpleNamespace(url=…))` is no longer viable. Replace `_media()` with a DB-backed factory asset, add `@pytest.mark.django_db` and a course fixture (these are currently deliberate DB-free template unit tests). Assets stay **narrow** (no `derivatives=True`) — they assert only that the `data-zoomable` hook is present, so the fallback path is the right one and a wide fixture adds cost without discrimination. |
| `tests/test_e2e_image_size.py`, `test_e2e_imagezoom.py`, `test_e2e_table_cell_images.py` | **Unchanged, still green** — their fixtures use plain `make_image_asset` with `derivatives` defaulting to `False`, so no derivative exists, `srcset`/`sizes` are omitted, `src` falls back to the original and `naturalWidth` is unchanged. Do **not** "fix" them by substituting `el.width`/`el.height` for `naturalWidth`: those return the **rendered** size (measured: 130 vs `getAttribute('width')` 1100), which collapses the 16-combination box matrix into a tautology. |

- [ ] **Step 7: Commit**

```bash
git add templates/courses/elements/ courses/models.py tests/ courses/tests/
git commit -m "feat(media): serve derivatives on the student surfaces"
```

---

## Task 13: Geometry, acceptance and the PR figures

**Files:**
- Create: `tests/test_e2e_media_derivatives_geometry.py`
- Test: as above

**Interfaces:**
- Consumes: everything.
- Produces: the numbers the PR body quotes.

- [ ] **Step 1: Capture the pre-change baseline**

Check out `origin/master` in a scratch worktree, run the geometry probe, and record per-template, per-axis constants at **both TOC states** and at **640, 641, 1280**. "Unchanged" is relative to something: a test that measures the post-change page and compares it to itself is unfalsifiable.

- [ ] **Step 2: Write the geometry suite**

Every asset uses `derivatives=True` and `size=` wider than 896 — **except** the omission-rule band fixtures, which must be wider than 512 and *narrower than that preset's measured box*, and are asserted at the viewport and DOM state where the box is widest (1280 + collapsed TOC for `el-*`). At 641px the rule is inert by construction, so a band test written there is green on the mutant.

Both a **landscape and a portrait** fixture per preset — the attribute distortion this design avoids is invisible on landscape sources.

```python
@pytest.mark.parametrize("shape", [(2000, 1500), (600, 1800)])   # landscape + portrait
@pytest.mark.parametrize("collapsed", [False, True])
@pytest.mark.parametrize("viewport", [(640, 800), (641, 800), (1280, 720)])
def test_layout_is_unchanged(page, live_server, shape, collapsed, viewport, baseline):
    ...
    box = page.locator(".el--image--full img").bounding_box()
    want = baseline[(shape, collapsed, viewport)]
    assert abs(box["width"] - want[0]) <= 1
    assert abs(box["height"] - want[1]) <= 1
```

The ±1px tolerance is required, not slack: a derivative's height is a rounded proportional scale, so the intrinsic ratios differ in the fourth decimal and a height cap can shift the used width sub-pixel.

- [ ] **Step 3: Write the three acceptance checks**

```python
def test_grid_selects_the_thumb_at_dpr_1_and_3(...):
    """One fixed-box candidate is what makes this assertion identical at both
    densities."""

def test_a_student_el_full_selects_the_web_derivative_at_dpr_1(...):
    """Without this, the ~21MB web set — 58% of the added disk — has no
    measurement anywhere: the other two criteria exercise the grid, which uses
    thumb only, and the tag tests assert the PRESENCE of a candidate list, which
    is not selection."""

def test_grid_initial_viewport_bytes_are_under_the_measured_threshold(...):
    """The threshold derives from a MEASURED baseline, not the 58.6MB library
    total. With lazy loading alone and no derivatives the initial viewport is
    ~24 originals at a 38KB median — under 1MB — so a 'under 2MB' threshold
    passes with derivatives entirely absent."""
```

- [ ] **Step 4: Record the before/after server figures**

```bash
uv run python manage.py shell -c "<time the manager view; print HTML size>"
```

Record HTML size (was 2.1 MB) and server render time (was 2.2 s) for the PR body — this change pushes on the metric against which pagination is being deferred.

- [ ] **Step 5: Run everything**

```bash
uv run pytest tests/ courses/tests/ -q
uv run pytest tests/ -m e2e -n 2 -q
```

`-n 2`, not `-n 8` — the e2e bottleneck is TRUNCATE teardown and higher parallelism is slower. Grep the summary line rather than trusting the exit code.

- [ ] **Step 6: Screenshots**

Media manager, picker, and a student unit, in light **and** dark, judged separately.

- [ ] **Step 7: Run the real backfill against mat-pp**

```bash
uv run python manage.py backfill_media_derivatives --course mat-pp --dry-run
uv run python manage.py backfill_media_derivatives --course mat-pp
```

Expected: ~953 processed, ~36 MB added on disk. Record the actual tally.

- [ ] **Step 8: Commit**

```bash
git add tests/test_e2e_media_derivatives_geometry.py
git commit -m "test(media): geometry baselines and measured acceptance criteria"
```

---

## Self-Review

**Spec coverage.** Walked the spec section by section: Purpose/measured cost → Task 1 + 13; Scope inventory → Tasks 11–12 (8 `<img>`, 7 templates, gallery `render()`); storage model + migration → Task 2; derivative widths + measurement protocol → Task 1; generation rules 0–9 → Task 3; render path/tag/presets/strategies → Task 10; layout invariants (no attributes, omission rule) → Task 10 tests + Task 13 geometry; lazy loading → Task 10; print → covered by lazy being grid-only; server cost → Task 13 step 4; client audit → Tasks 8–9; data flow (create/replace/LAL/importer) → Tasks 5–6; orphan handling → Tasks 3, 6; deletion → Task 4; transfer → Task 5 step 5; backfill → Task 7; error handling table → Task 3 tests; testing/falsification → mutants named in Tasks 3, 6, 10.

**Gap found and closed:** the spec's requirement that the import completion message tell the operator to run the backfill had no task — added as Task 5 step 6.

**Placeholder scan.** One intentional placeholder class remains: `<<FROM MEASUREMENTS DOC: …>>` in Task 10 step 3, closed by Task 10 step 4, which states the plan is incomplete while any remains. This is deliberate — the alternative is inventing `sizes` values, which is the exact failure the measurement protocol exists to prevent.

**Type consistency.** `generate_derivatives(asset) -> str` assigns and returns; `delete_derivative_files(names, storage)` takes names and deletes immediately; `THUMB_WIDTH`/`WEB_WIDTH` are imported from `courses.derivatives` in both the generator and the tag; `create_asset(..., generate=True)` matches its two call sites; `DerivativesState.OK/SKIPPED/FAILED` used consistently; the five-field `update_fields` list is identical in Tasks 5, 6 and 7.
