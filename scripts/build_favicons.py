"""Generate libli's favicon assets from a single source of geometry.

Re-run after ANY change to the geometry constants or the palette below:

    uv run python scripts/build_favicons.py

A deliberate stem-geometry change also requires updating the expected extent
literal in `build()`.

Writes to core/static/core/img/favicon/ by default; --out redirects it (the
tests render into tmp_path that way). Never runs at request or deploy time --
the outputs are committed.

Pillow cannot rasterize SVG, so rather than add a renderer dependency the
geometry lives here once and both the vector and the rasters are emitted from
it. The two media do NOT share a coordinate convention: SVG's rect covers
exactly `width` units, while Pillow's shape boxes are endpoint-INCLUSIVE. Every
Pillow call therefore passes (x0*s, y0*s, x1*s - 1, y1*s - 1) where
s = SUPERSAMPLE * size / CANVAS is the supersampled scale, so the -1 removes
exactly one supersample pixel. Radii scale but are never decremented.
"""

import argparse
from pathlib import Path

from PIL import Image
from PIL import ImageDraw

# ── Geometry (canvas units, half-open extents) ─────────────────────────────
CANVAS = 512
TILE_R = 112
STEM_X0, STEM_X1 = 172, 236
STEM_Y0, STEM_Y1 = 129, 383
STEM_R = 32
DOT_CX, DOT_CY, DOT_R = 298, 341, 42

# ── Palette (literals; see tests/test_favicon_build.py for the equality guard)
PRIMARY = "#147E78"
ACCENT = "#C77B2A"
STEM_FILL = "#FFFFFF"

SUPERSAMPLE = 4  # ImageDraw does not antialias; draw big, downsample with LANCZOS

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "core/static/core/img/favicon"

# The maskable safe zone is the inscribed circle of radius 0.4 * CANVAS.
SAFE_RADIUS = 0.4 * CANVAS


def _scale(size):
    """The supersampled scale for an output of `size` px."""
    return SUPERSAMPLE * size / CANVAS


def _box(x0, y0, x1, y1, s):
    """A half-open extent as an endpoint-inclusive Pillow box, unrounded."""
    return (x0 * s, y0 * s, x1 * s - 1, y1 * s - 1)


def _svg():
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {CANVAS} {CANVAS}" width="{CANVAS}" height="{CANVAS}">\n'
        f'  <rect x="0" y="0" width="{CANVAS}" height="{CANVAS}" '
        f'rx="{TILE_R}" fill="{PRIMARY}"/>\n'
        f'  <rect x="{STEM_X0}" y="{STEM_Y0}" width="{STEM_X1 - STEM_X0}" '
        f'height="{STEM_Y1 - STEM_Y0}" rx="{STEM_R}" fill="{STEM_FILL}"/>\n'
        f'  <circle cx="{DOT_CX}" cy="{DOT_CY}" r="{DOT_R}" fill="{ACCENT}"/>\n'
        "</svg>\n"
    )


def _threshold_white(p):
    """A pixel counts as stem iff all three RGB channels are >= 200.

    Also imported by tests/test_favicon_build.py -- one predicate, one home.
    """
    return p[0] >= 200 and p[1] >= 200 and p[2] >= 200


def _measure_stem(im):
    """Inclusive (x0, x1, y0, y1) of the stem, measured in pixels."""
    px = im.load()
    xs, ys = [], []
    for y in range(im.height):
        for x in range(im.width):
            if _threshold_white(px[x, y]):
                xs.append(x)
                ys.append(y)
    return min(xs), max(xs), min(ys), max(ys)


def _assert_centred():
    """The artwork bounding box is centred by construction."""
    x1, y1 = DOT_CX + DOT_R, DOT_CY + DOT_R
    if STEM_X0 != CANVAS - x1 or STEM_Y0 != CANVAS - y1:
        raise AssertionError(
            f"artwork not centred: x {STEM_X0}/{CANVAS - x1}, y {STEM_Y0}/{CANVAS - y1}"
        )


def _assert_maskable_fits():
    """The artwork fits the maskable safe zone (inscribed circle) at scale 1.0."""
    half_w = (DOT_CX + DOT_R - STEM_X0) / 2
    half_h = (DOT_CY + DOT_R - STEM_Y0) / 2
    half_diagonal = (half_w**2 + half_h**2) ** 0.5
    if half_diagonal >= SAFE_RADIUS:
        raise AssertionError(
            f"artwork half-diagonal {half_diagonal:.2f} outgrew the "
            f"safe-zone radius {SAFE_RADIUS}"
        )


def _render(size, tile_radius=TILE_R):
    """Draw the mark at `size` px, supersampled and LANCZOS-downsampled.

    tile_radius=0 makes the tile full-bleed, which also makes every pixel opaque --
    that is how the apple-touch and maskable variants get their alpha 255 (iOS
    composites transparency onto black and applies its own corner mask).
    """
    s = _scale(size)
    canvas = size * SUPERSAMPLE
    im = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle(
        _box(0, 0, CANVAS, CANVAS, s), radius=tile_radius * s, fill=PRIMARY
    )
    draw.rounded_rectangle(
        _box(STEM_X0, STEM_Y0, STEM_X1, STEM_Y1, s), radius=STEM_R * s, fill=STEM_FILL
    )
    draw.ellipse(
        _box(DOT_CX - DOT_R, DOT_CY - DOT_R, DOT_CX + DOT_R, DOT_CY + DOT_R, s),
        fill=ACCENT,
    )
    return im.resize((size, size), Image.LANCZOS)


def build(out_dir):
    """Write every favicon asset into `out_dir`; return the written paths.

    Creates the directory if missing and overwrites unconditionally.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _assert_centred()
    _assert_maskable_fits()

    written = []
    svg_path = out_dir / "favicon.svg"
    # write_bytes, never write_text: text mode emits CRLF on Windows and LF on
    # Linux, and this file is byte-compared by tests/test_favicon_build.py.
    svg_path.write_bytes(_svg().encode("utf-8"))
    written.append(svg_path)

    for name, size, radius in (
        ("icon-192.png", 192, TILE_R),
        ("icon-512.png", 512, TILE_R),
        # Squared and full-bleed: iOS masks corners itself, so a pre-rounded tile
        # would show background wedges inside the mask.
        ("apple-touch-icon.png", 180, 0),
        ("icon-maskable-512.png", 512, 0),
    ):
        image = _render(size, tile_radius=radius)
        if name == "icon-512.png":
            # Catches OVER-correction (subtracting a whole final pixel instead of
            # one supersample pixel) -> (172, 234, 129, 381). It does NOT catch a
            # MISSING correction: measured, deleting the -1 leaves this extent
            # unchanged. That case is caught by the exact-white extent and the
            # maskable bbox in tests/test_favicon_build.py.
            #
            # This literal is part of the geometry contract: a DELIBERATE change to
            # STEM_X0/STEM_X1/STEM_Y0/STEM_Y1 must update it here, or the documented
            # regeneration command fails. The module docstring says so too.
            measured = _measure_stem(image)
            if measured != (172, 235, 129, 382):
                raise AssertionError(f"icon-512 stem extent drifted: {measured}")
        path = out_dir / name
        image.save(path, format="PNG")
        written.append(path)

    # Largest-first is load-bearing: IcoImagePlugin takes its ceiling from
    # frames[0].size and SILENTLY drops every requested size larger than it, so an
    # ascending list yields a one-frame ICO. The sizes= order is irrelevant
    # (it is consumed as sorted(set(...))); only frames[0] matters.
    frames = [_render(n) for n in (48, 32, 16)]
    ico_path = out_dir / "favicon.ico"
    frames[0].save(
        ico_path,
        format="ICO",
        sizes=[(48, 48), (32, 32), (16, 16)],
        append_images=frames[1:],
    )
    written.append(ico_path)
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT, type=Path)
    args = parser.parse_args()
    for path in build(args.out):
        print(path)


if __name__ == "__main__":
    main()
