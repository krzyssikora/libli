"""Generate libli's favicon assets from a single source of geometry.

Re-run after ANY change to the geometry constants or the palette below:

    uv run python scripts/build_favicons.py

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
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT, type=Path)
    args = parser.parse_args()
    for path in build(args.out):
        print(path)


if __name__ == "__main__":
    main()
