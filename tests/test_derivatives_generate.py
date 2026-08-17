import io
import os

import pytest
from PIL import Image

from courses.derivatives import THUMB_WIDTH
from courses.derivatives import WEB_WIDTH
from courses.derivatives import generate_derivatives
from courses.models import DerivativesState
from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_video_asset


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
    # The naming scheme itself: <stem>-<target>.webp under upload_to. The only
    # other test that names a file (test_storage_failure_leaves_no_file_and_no_field)
    # asserts NON-existence, so it would pass vacuously if the two derivatives
    # collided and storage appended a random suffix instead.
    assert asset.thumb.name == f"courses/media/derivatives/wide-{THUMB_WIDTH}.webp"
    assert asset.web.name == f"courses/media/derivatives/wide-{WEB_WIDTH}.webp"


@pytest.mark.django_db
def test_palette_source_is_resampled_not_nearest_neighboured(
    course_with_image_media_root,
):
    """THE mode-P test. Image.resize downgrades resample to NEAREST for modes
    "1" and "P", silently ignoring LANCZOS -- verified against Pillow 12.2.0.

    ASSERTING ON THE DERIVATIVE'S MODE DOES NOT WORK, and the obvious version of
    this test is vacuous. WebP has no palette mode, so Pillow converts on save
    and the derivative decodes as RGB *whether or not* the convert() ran --
    measured: mutant RGB, correct RGB. A flat Image.new("P", ...) fixture is
    vacuous a second time over, having no structure for resampling to affect.

    So: a fixture with a real palette and a per-column index ramp, and an
    assertion on resampling EVIDENCE. The bound is principled rather than
    magic -- a NEAREST resample of a palette image can only emit colours already
    present in the 256-entry palette, while LANCZOS averages neighbours and
    creates new ones. Measured on this exact fixture: mutant 255 distinct
    colours, correct 506.

    MUTANT: remove the img.convert(...) before resize. Must go red.
    """
    course = CourseFactory()
    w, h = 2000, 1500
    src = Image.new("P", (w, h))
    src.putpalette([v for i in range(256) for v in (i, 255 - i, (i * 7) % 256)])
    src.putdata([(x * 255) // w for _y in range(h) for x in range(w)])
    buf = io.BytesIO()
    src.save(buf, "PNG")
    asset = make_image_asset(course, "pal.png", raw=buf.getvalue())

    assert generate_derivatives(asset) == DerivativesState.OK
    distinct = len(_open(asset.thumb).convert("RGB").getcolors(maxcolors=1 << 20))
    assert distinct > 256, (
        f"only {distinct} distinct colours: a NEAREST resample cannot exceed the "
        f"256-entry palette, so LANCZOS was silently downgraded"
    )


@pytest.mark.django_db
def test_animated_gif_is_skipped_and_produces_no_derivative(
    course_with_image_media_root,
):
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
    assert asset.thumb.name  # 700 > 512
    assert asset.web.name in ("", None)  # 700 <= 896


@pytest.mark.django_db
def test_original_narrower_than_both_targets_is_skipped(course_with_image_media_root):
    """The deliberate narrow case. Asserts SKIPPED *specifically*, not merely
    blank fields, because blank fields are also what `failed` looks like."""
    course = CourseFactory()
    asset = make_image_asset(course, "tiny.png", size=(300, 200))
    assert generate_derivatives(asset) == DerivativesState.SKIPPED


@pytest.mark.django_db
def test_an_extremely_wide_source_survives_the_height_clamp(
    course_with_image_media_root,
):
    """A 3000x1 source rounds to height 0, which Pillow rejects with
    ValueError("height and width must be > 0"). The max(1, ...) clamp in rule 6
    is what prevents that -- so with the clamp in place this source succeeds
    (measured: (512,1) and (896,1) both encode, 34 bytes each) rather than being
    skipped. Asserting SKIPPED here would contradict the clamp.

    MUTANT: remove the max(1, ...). This goes red with FAILED.
    """
    course = CourseFactory()
    flat = make_image_asset(course, "flat.png", size=(3000, 1))
    assert generate_derivatives(flat) == DerivativesState.OK
    assert flat.thumb.name and flat.web.name


@pytest.mark.django_db
def test_a_source_exceeding_the_webp_dimension_cap_is_skipped_not_failed(
    course_with_image_media_root,
):
    """A 600x20000 source scales to (512, 17067) -> ValueError("encoding error 5:
    Image size exceeds WebP limit of 16383 pixels"). It must land in `skipped`,
    not `failed`, because the backfill retries `failed` on EVERY run -- forever,
    for a structurally impossible image.

    MUTANT: remove the `height > _WEBP_MAX_DIMENSION` check. Goes red with
    FAILED.
    """
    course = CourseFactory()
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
def test_storage_failure_leaves_no_file_and_no_field(
    course_with_image_media_root, monkeypatch
):
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
        if calls["n"] == 2:  # succeed on thumb, fail on web
            raise OSError("disk full")
        return real_save(name, content, max_length=max_length)

    monkeypatch.setattr(default_storage, "save", flaky_save)

    assert generate_derivatives(asset) == DerivativesState.FAILED
    assert asset.thumb.name in ("", None)
    assert asset.web.name in ("", None)
    assert asset.width is None and asset.height is None
    assert not default_storage.exists(
        f"courses/media/derivatives/wide-{THUMB_WIDTH}.webp"
    )


@pytest.mark.django_db
def test_derivative_no_smaller_than_source_is_discarded_without_writing(
    course_with_image_media_root, monkeypatch
):
    """Asserted on the STORAGE backend, not just the field: encoding straight to
    storage and 'discarding' by blanking the field would leave orphaned bytes
    and burn a collision-suffix slot against the max_length budget."""
    from django.core.files.storage import default_storage

    course = CourseFactory()
    # noise=True isn't load-bearing here (_encode is monkeypatched below, so
    # the actual pixel content never reaches the encoder) -- kept only so this
    # fixture matches the realistic-size convention used elsewhere in this file.
    asset = make_image_asset(course, "noise.png", size=(2000, 1500), noise=True)
    # Force the discard branch directly, rather than via a pathological
    # fixture: monkeypatch _encode to return a payload guaranteed >= source_size.
    monkeypatch.setattr("courses.derivatives._encode", lambda *a, **k: b"x" * 10**7)

    written = []
    real_save = default_storage.save
    monkeypatch.setattr(
        default_storage,
        "save",
        lambda n, c, max_length=None: (
            written.append(n),
            real_save(n, c, max_length=max_length),
        )[1],
    )

    assert generate_derivatives(asset) == DerivativesState.SKIPPED
    assert written == []


@pytest.mark.django_db
def test_state_is_assigned_on_the_instance_not_only_returned(
    course_with_image_media_root,
):
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
    exif[274] = 6  # rotate 90 CW
    im.save(buf, "JPEG", exif=exif)
    asset = make_image_asset(course, "rot.jpg", raw=buf.getvalue())

    assert generate_derivatives(asset) == DerivativesState.OK
    assert asset.width == 1000 and asset.height == 2000


@pytest.mark.django_db
def test_lossless_encoding_is_pixel_identical_to_the_resize(
    course_with_image_media_root,
):
    """The pinned encoder kwargs (lossless=True, method=4, exact=True) had zero
    coverage: setting lossless=False, method=0, and dropping exact=True in one
    edit leaves the other 14 tests green. That breakage is not cosmetic --
    lossy WebP also silently defeats the rule-7 discard, because a lossy 896px
    derivative essentially always beats a JPEG source, changing which library
    rows end up `ok` vs `skipped` and therefore Task 7 backfill's work set.

    Asserted on EVIDENCE, not by restating the literal kwargs back at
    themselves: decode the thumb derivative and compare it pixel-for-pixel
    against Image.resize(...) run directly on the (already RGB, un-rotated,
    alpha-free) source. Pixel identity is exactly what lossless means -- a
    lossy build introduces compression artifacts and fails this.

    MUTANT: set lossless=False, method=0, remove exact=True. Must go red.
    """
    course = CourseFactory()
    w, h = 2000, 1500
    src = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3))
    buf = io.BytesIO()
    src.save(buf, "PNG")
    png_bytes = buf.getvalue()
    asset = make_image_asset(course, "noise.png", raw=png_bytes)

    assert generate_derivatives(asset) == DerivativesState.OK

    source = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    target_height = round(source.height * THUMB_WIDTH / source.width)
    expected = source.resize((THUMB_WIDTH, target_height), Image.LANCZOS)

    got = _open(asset.thumb).convert("RGB")
    assert got.get_flattened_data() == expected.get_flattened_data()


@pytest.mark.django_db
def test_alpha_is_preserved_for_rgba_sources(course_with_image_media_root):
    """Replacing the mode-P conditional (`img.convert("RGBA" if has_alpha else
    "RGB")`) with an unconditional `img.convert("RGB")` leaves all 14 original
    tests green, yet flattens transparency on every PNG diagram in the library.

    Noise, not a flat fill: a flat RGBA source compresses so well as PNG that
    the lossless WebP derivative can fail the rule-7 discard check and never
    get written at all, making the state assertion below fail for the wrong
    reason.

    MUTANT: replace the has_alpha-conditional convert with an unconditional
    img.convert("RGB"). Must go red.
    """
    course = CourseFactory()
    w, h = 2000, 1500
    im = Image.frombytes("RGBA", (w, h), os.urandom(w * h * 4))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    asset = make_image_asset(course, "alpha.png", raw=buf.getvalue())

    assert generate_derivatives(asset) == DerivativesState.OK
    assert _open(asset.thumb).mode == "RGBA"


@pytest.mark.django_db
def test_decompression_bomb_is_skipped_not_failed(
    course_with_image_media_root, monkeypatch
):
    """Pillow raises Image.DecompressionBombError at Image.open() above 2x
    MAX_IMAGE_PIXELS (~178.9 MP at the default). Not one of the spec's
    enumerated rules -- added by review: this is the same category as rule 6's
    WebP dimension cap, a structurally impossible image rather than a
    transient failure, so it must land in SKIPPED, not FAILED (the backfill
    retries FAILED forever, paying the full decode cost each time).

    Lowering MAX_IMAGE_PIXELS reaches the branch without needing an actual
    179 MP fixture -- the reviewer confirmed this is a legitimate way to reach
    it.

    MUTANT: drop the `except Image.DecompressionBombError` clause (or fold it
    into the general except, which returns FAILED). Must go red.
    """
    course = CourseFactory()
    asset = make_image_asset(course, "wide.png", size=(2000, 1500))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    assert generate_derivatives(asset) == DerivativesState.SKIPPED


@pytest.mark.django_db
def test_delete_derivative_files_skips_blank_names_without_touching_storage(
    course_with_image_media_root, monkeypatch
):
    """The blank-name guard has no direct coverage at all -- it is exercised
    only incidentally, via the failure handler, always with a non-blank name.
    post_delete passes blank names for every video and every skipped/failed
    row, and FileSystemStorage.delete("") raises ValueError while
    storage.exists("") is TRUTHY (it stats MEDIA_ROOT) -- but that ValueError
    would land inside this function's own try/except and be swallowed either
    way, so "does not raise" cannot discriminate the mutant. Assert instead
    that storage is never even touched for a blank name.

    MUTANT: delete the `if not name: continue` guard. Must go red.
    """
    from django.core.files.storage import default_storage

    from courses.derivatives import delete_derivative_files

    calls = []

    def spy_exists(name):
        calls.append(name)
        return False

    monkeypatch.setattr(default_storage, "exists", spy_exists)

    delete_derivative_files(["", None, ""], default_storage)

    assert calls == []


@pytest.mark.django_db
def test_delete_derivative_files_deletes_a_real_file(course_with_image_media_root):
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    from courses.derivatives import delete_derivative_files

    name = default_storage.save(
        "courses/media/derivatives/probe.webp", ContentFile(b"x")
    )
    assert default_storage.exists(name)

    delete_derivative_files([name], default_storage)

    assert not default_storage.exists(name)


@pytest.mark.django_db
def test_delete_derivative_files_missing_name_is_harmless(
    course_with_image_media_root,
):
    from django.core.files.storage import default_storage

    from courses.derivatives import delete_derivative_files

    delete_derivative_files(
        ["courses/media/derivatives/never-existed.webp"], default_storage
    )  # must not raise


@pytest.mark.django_db
def test_delete_derivative_files_swallows_storage_errors(
    course_with_image_media_root, monkeypatch
):
    """The except Exception around storage.exists/.delete must swallow, not
    propagate, a storage error -- callers invoke this function from within
    their OWN exception handlers (generate_derivatives' FAILED path,
    replace_asset's failure handler), and a secondary exception escaping here
    would mask the caller's real error rather than merely failing to clean up.

    MUTANT: remove the try/except around storage.exists/.delete. Must go red.
    """
    from django.core.files.storage import default_storage

    from courses.derivatives import delete_derivative_files

    def boom(name):
        raise OSError("disk full")

    monkeypatch.setattr(default_storage, "exists", boom)

    delete_derivative_files(["some-name.webp"], default_storage)  # must not raise
