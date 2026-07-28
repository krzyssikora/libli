"""Guards for the generated favicon assets.

See docs/superpowers/specs/2026-07-28-favicon-design.md for the measurements
behind every literal here.
"""

from pathlib import Path

from scripts.build_favicons import ACCENT
from scripts.build_favicons import CANVAS
from scripts.build_favicons import DOT_CX
from scripts.build_favicons import DOT_CY
from scripts.build_favicons import DOT_R
from scripts.build_favicons import PRIMARY
from scripts.build_favicons import STEM_X0
from scripts.build_favicons import STEM_Y0
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
