"""Guards for the generated favicon assets.

See docs/superpowers/specs/2026-07-28-favicon-design.md for the measurements
behind every literal here.
"""

from pathlib import Path

import pytest
from PIL import Image

from scripts.build_favicons import ACCENT
from scripts.build_favicons import CANVAS
from scripts.build_favicons import DOT_CX
from scripts.build_favicons import DOT_CY
from scripts.build_favicons import DOT_R
from scripts.build_favicons import PRIMARY
from scripts.build_favicons import STEM_X0
from scripts.build_favicons import STEM_Y0
from scripts.build_favicons import _threshold_white
from scripts.build_favicons import build

COMMITTED = Path(__file__).resolve().parent.parent / "core/static/core/img/favicon"

PRIMARY_RGBA = (20, 126, 120, 255)
ACCENT_RGB = (199, 123, 42)
WHITE_RGB = (255, 255, 255)


def test_artwork_bounding_box_is_centred():
    """The artwork must be centred by construction, not by luck."""
    x1 = DOT_CX + DOT_R
    y1 = DOT_CY + DOT_R
    assert STEM_X0 == CANVAS - x1
    assert STEM_Y0 == CANVAS - y1


def test_svg_geometry_matches_the_constants():
    """The SVG emits half-open extents verbatim — no -1 correction on the vector side.

    This is separate from the byte-compare: both sides of that comparison come out
    of the same formatter, so it cannot catch the SVG being geometrically wrong.
    """
    from scripts.build_favicons import _svg

    svg = _svg()
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg
    assert 'viewBox="0 0 512 512"' in svg
    assert '<rect x="0" y="0" width="512" height="512" rx="112" fill="#147E78"/>' in svg
    assert (
        '<rect x="172" y="129" width="64" height="254" rx="32" fill="#FFFFFF"/>' in svg
    )
    assert '<circle cx="298" cy="341" r="42" fill="#C77B2A"/>' in svg


def test_committed_svg_matches_a_fresh_render(tmp_path):
    """Drift guard: a geometry change without regenerating the assets goes RED here.

    Durable across Pillow releases (pure string formatting, no Pillow involved),
    unlike a raster byte-compare.
    """
    build(tmp_path)
    assert (COMMITTED / "favicon.svg").read_bytes() == (
        tmp_path / "favicon.svg"
    ).read_bytes()


def test_generator_palette_matches_the_service_defaults():
    """A default-palette change must be caught, not silently diverge from the mark."""
    from core.services import ACCENT_DEFAULT
    from core.services import PRIMARY_DEFAULT

    assert PRIMARY == PRIMARY_DEFAULT
    assert ACCENT == ACCENT_DEFAULT


def _sample(im, u, v):
    """Sample a canvas-unit coordinate on an output of im.width px."""
    size = im.width
    return im.getpixel((round(u * size / CANVAS), round(v * size / CANVAS)))


def _extent(im, predicate):
    """Inclusive (x0, x1, y0, y1) bounding box of pixels satisfying `predicate`."""
    px = im.load()
    xs, ys = [], []
    for y in range(im.height):
        for x in range(im.width):
            if predicate(px[x, y]):
                xs.append(x)
                ys.append(y)
    return min(xs), max(xs), min(ys), max(ys)


def _exact_white(p):
    return p[:3] == WHITE_RGB


def _ico_frame(path, size):
    """Load a specific ICO frame.

    Pillow's IcoImageFile has no n_frames; ImageSequence yields ONLY the largest
    frame without raising, and seek(1) raises EOFError. Setting .size is the
    documented way to pick a frame.
    """
    im = Image.open(path)
    im.size = (size, size)
    return im.convert("RGBA")


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("apple-touch-icon.png", 180),
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("icon-maskable-512.png", 512),
    ],
)
def test_committed_rasters_have_the_declared_size_and_mode(filename, expected):
    im = Image.open(COMMITTED / filename)
    assert im.size == (expected, expected)
    assert im.mode == "RGBA"


def test_committed_ico_contains_all_three_frames():
    """Guards the frame-order collapse: Pillow drops sizes larger than frames[0].

    Asserted as a SET -- .size reports only the largest frame, so it cannot tell
    {48} from {16,32,48} and would sail past a dropped middle frame.
    """
    assert Image.open(COMMITTED / "favicon.ico").ico.sizes() == {
        (16, 16),
        (32, 32),
        (48, 48),
    }


@pytest.mark.parametrize(
    "filename", ["icon-512.png", "icon-192.png", "apple-touch-icon.png"]
)
def test_committed_rasters_carry_the_expected_colours(filename):
    """Exact equality holds only at outputs >= 48 px (see the spec for the 16/32 px
    measurements that do NOT hold)."""
    im = Image.open(COMMITTED / filename)
    assert _sample(im, 100, 256)[:3] == PRIMARY_RGBA[:3]  # tile, outside the artwork
    assert _sample(im, 204, 256)[:3] == WHITE_RGB  # stem interior centre line
    assert _sample(im, 298, 341)[:3] == ACCENT_RGB  # dot centre


def test_committed_icon_512_stem_extents():
    """The endpoint-convention guard.

    Both predicates are needed and this was measured: the >=200 threshold does NOT
    move when the -1 correction is deleted (it only catches OVER-correction), while
    the exact-white scan shifts from 173-234/130-381 to 173-235/130-382.
    """
    im = Image.open(COMMITTED / "icon-512.png")
    assert _extent(im, _threshold_white) == (172, 235, 129, 382)
    assert _extent(im, _exact_white) == (173, 234, 130, 381)


def test_committed_icon_192_stem_extent():
    im = Image.open(COMMITTED / "icon-192.png")
    assert _extent(im, _threshold_white) == (65, 87, 49, 142)


def test_committed_maskable_artwork_bbox():
    """Measured from the render, not computed from the constants -- a constants-only
    check is a tautology and cannot see a rendering-path bug."""
    im = Image.open(COMMITTED / "icon-maskable-512.png")

    def not_tile(p):
        return max(abs(p[i] - PRIMARY_RGBA[i]) for i in range(3)) > 24

    x0, x1, y0, y1 = _extent(im, not_tile)
    assert (x0, x1, y0, y1) == (172, 339, 129, 382)
    half_diagonal = (((x1 - x0) / 2) ** 2 + ((y1 - y0) / 2) ** 2) ** 0.5
    assert half_diagonal < 204.8


def test_corner_alpha_distinguishes_the_variants():
    """Rounded variants have transparent corners; iOS/maskable ones are fully opaque."""
    assert Image.open(COMMITTED / "icon-512.png").getpixel((0, 0)) == (0, 0, 0, 0)
    assert _ico_frame(COMMITTED / "favicon.ico", 48).getpixel((0, 0)) == (0, 0, 0, 0)
    for filename in ("apple-touch-icon.png", "icon-maskable-512.png"):
        im = Image.open(COMMITTED / filename)
        w, h = im.size
        for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            assert im.getpixel(xy)[3] == 255, f"{filename} corner {xy} is not opaque"


def test_corner_radius_probes():
    """The raster-side r*s scaling is otherwise unguarded: corner alpha at (0,0) reads
    transparent for any radius above ~2, and no colour sample sits near a corner.

    The pair brackets the diagonal boundary at R(1 - 1/sqrt2) ~= 32.8 without landing
    ON it -- (32,32) straddles the arc and reads (15,120,120,17), which is the most
    resampling-fragile point on the tile.
    """
    im = Image.open(COMMITTED / "icon-512.png")
    assert im.getpixel((30, 30)) == (0, 0, 0, 0)
    assert im.getpixel((34, 34)) == PRIMARY_RGBA


def test_stem_cap_radius_probe():
    """The tile probe does NOT cover STEM_R: rendering with STEM_R=16 leaves both
    tile-probe pixels unchanged (measured). Without this, the stem's radius scaling
    is guarded by nothing in the entire raster set.

    Derive the pair the way the tile pair is derived -- bracket the stem cap's arc
    at R(1 - 1/sqrt2) ~= 9.4 for R=32, at the stem's top-left corner (x0=172,
    y0=129) -- then MEASURE both endpoints at STEM_R=32 and again at STEM_R=16 and
    pin the two that flip. Start from (180, 137) and (183, 140) and adjust: the
    pair must be saturated (never a straddling pixel) and must flip between the
    two radii.
    """
    im = Image.open(COMMITTED / "icon-512.png")
    assert im.getpixel((180, 137)) == PRIMARY_RGBA  # cut away by the r=32 cap
    assert im.getpixel((183, 140))[:3] == WHITE_RGB  # inside the stem either way


def test_small_ico_frames_have_real_content():
    """The 16/32 px frames are drawn independently, so they fail independently --
    blank, transparent or tile-only all pass the frame-set and size assertions.
    They are excluded from exact colour sampling, not from checking."""
    for size in (16, 32):
        im = _ico_frame(COMMITTED / "favicon.ico", size)
        # get_flattened_data, not getdata: the latter is deprecated for removal in
        # Pillow 14 and warns on every run.
        assert len(set(im.get_flattened_data())) >= 3
        assert im.getpixel((size // 2, size // 2))[3] == 255
        dot = _sample(im, DOT_CX, DOT_CY)[:3]
        to_accent = sum((dot[i] - ACCENT_RGB[i]) ** 2 for i in range(3)) ** 0.5
        to_primary = sum((dot[i] - PRIMARY_RGBA[i]) ** 2 for i in range(3)) ** 0.5
        assert to_accent < to_primary


def _fingerprint(im):
    """The spec's enumerated, resampling-tolerant fingerprint of one image.

    NOT full-pixel equality: comparing every pixel of a committed file against a
    fresh render reintroduces exactly the "a routine lock bump turns it RED with
    no code change" failure the spec rejected byte-comparison for -- LANCZOS
    output is no more contracted across Pillow releases than the PNG encoder is.
    """
    fp = {
        "size": im.size,
        "mode": im.mode,
        "corners": tuple(
            im.getpixel(xy)
            for xy in (
                (0, 0),
                (im.width - 1, 0),
                (0, im.height - 1),
                (im.width - 1, im.height - 1),
            )
        ),
        "samples": tuple(
            _sample(im, u, v) for u, v in ((100, 256), (204, 256), (298, 341))
        ),
    }
    if im.width >= 192:
        fp["threshold_extent"] = _extent(im, _threshold_white)
        fp["exact_extent"] = _extent(im, _exact_white)
    return fp


def test_fresh_build_reproduces_the_committed_fingerprint(tmp_path):
    """Raster drift guard, using the spec's enumerated comparison.

    Coverage, measured, so nobody mistakes its reach: geometry mutations
    (STEM_X*, STEM_Y1, DOT_R, DOT_CY) never actually reach the raster
    comparison -- build() raises first, via _assert_centred or the in-build stem
    check. What the raster legs catch is drift build() cannot see: a palette
    change, a SUPERSAMPLE change, or a new/renamed output.

    TILE_R 112->128 passes every RASTER leg here and reddens only the .svg
    byte-compare leg above; STEM_R 32->16 reddens that same leg plus a
    one-channel shift in the 16px ICO sample. Neither is what the corner probes
    exist for, so the probes must NOT be dropped as redundant with this test.
    (Full getdata() equality would redden more -- and would also redden on a
    routine Pillow bump, which is why it is not used.)
    """
    written = build(tmp_path)
    assert {p.name for p in written} == {p.name for p in COMMITTED.iterdir()}

    for path in written:
        committed = COMMITTED / path.name
        if path.suffix == ".svg":
            assert committed.read_bytes() == path.read_bytes()
        elif path.suffix == ".ico":
            for size in (16, 32, 48):
                assert _fingerprint(_ico_frame(committed, size)) == _fingerprint(
                    _ico_frame(path, size)
                )
        elif path.suffix == ".png":
            assert _fingerprint(Image.open(committed)) == _fingerprint(Image.open(path))
        else:
            raise AssertionError(f"unrecognised output {path.name}")


def test_fresh_build_reproduces_the_committed_maskable_bbox(tmp_path):
    """The maskable bbox is part of the drift comparison too (it is what catches a
    DOT_R change), but it needs its own predicate, so it lives in its own test."""
    build(tmp_path)

    def not_tile(p):
        return max(abs(p[i] - PRIMARY_RGBA[i]) for i in range(3)) > 24

    fresh = _extent(Image.open(tmp_path / "icon-maskable-512.png"), not_tile)
    committed = _extent(Image.open(COMMITTED / "icon-maskable-512.png"), not_tile)
    assert fresh == committed
