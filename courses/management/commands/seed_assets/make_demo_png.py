"""Regenerate the demo course's shared illustration, ``demo.png``.

Run on demand (NOT in CI) to rebuild the committed asset:

    uv run python courses/management/commands/seed_assets/make_demo_png.py

Draws a labelled right-triangle "Worked example" (legs a, b; hypotenuse c;
caption a2 + b2 = c2) at ~1200x800 on a light brand-palette card, then writes
``demo.png`` beside this file. The PNG is committed too — the repo is the
deployment artifact — so this script exists to keep the asset reproducible and
license-clean, not because anything imports it.

Deterministic and font-portable: uses Pillow's bundled scalable default font
(``ImageFont.load_default(size=...)``), never a system font that might be
absent on another machine.
"""

from pathlib import Path

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont

# Brand palette (light), mirrored from core/static/core/css/tokens.css.
SURFACE_BASE = "#F4F1EA"  # page
CARD = "#FFFFFF"  # surface-raised
BORDER = "#D6CFC1"  # border-strong
TEAL = "#147E78"  # brand-primary
AMBER = "#C77B2A"  # brand-accent
TEAL_FILL = "#DBEAE8"  # ~primary-subtle: teal mixed into white
INK = "#1E1C18"  # text-primary
INK_SOFT = "#5A544A"  # text-secondary

W, H = 1200, 800
OUT = Path(__file__).resolve().parent / "demo.png"


def _font(size):
    return ImageFont.load_default(size=size)


def _centered(draw, xy, text, font, fill):
    x, y = xy
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(
        (x - (box[2] - box[0]) / 2 - box[0], y - (box[3] - box[1]) / 2 - box[1]),
        text,
        font=font,
        fill=fill,
    )


def _formula(draw, center_y, base_font, sup_font, fill):
    """Draw ``a² + b² = c²`` centred horizontally, composing the superscripts by
    hand — the bundled default font has no U+00B2 glyph (renders as tofu)."""
    ascent = base_font.getbbox("A")[3]
    # (text, is_superscript)
    parts = [
        ("a", False),
        ("2", True),
        (" + ", False),
        ("b", False),
        ("2", True),
        (" = ", False),
        ("c", False),
        ("2", True),
    ]

    def width_of(font, s):
        b = draw.textbbox((0, 0), s, font=font)
        return b[2] - b[0]

    total = sum(width_of(sup_font if sup else base_font, s) for s, sup in parts)
    x = (W - total) / 2
    for s, sup in parts:
        font = sup_font if sup else base_font
        y = center_y - ascent / 2 - (ascent * 0.45 if sup else 0)
        draw.text((x, y), s, font=font, fill=fill)
        x += width_of(font, s)


def make():
    img = Image.new("RGB", (W, H), SURFACE_BASE)
    d = ImageDraw.Draw(img)

    # Card
    d.rounded_rectangle(
        (48, 48, W - 48, H - 48), radius=28, fill=CARD, outline=BORDER, width=3
    )

    # Title
    d.text((96, 92), "Worked example", font=_font(52), fill=TEAL)

    # Right triangle: right angle at bottom-left vertex A.
    ax, ay = 360, 500  # right-angle vertex
    bx, by = 840, 500  # end of horizontal leg b
    cx, cy = 360, 210  # end of vertical leg a
    d.polygon([(ax, ay), (bx, by), (cx, cy)], fill=TEAL_FILL, outline=TEAL)
    for p, q in (((ax, ay), (bx, by)), ((ax, ay), (cx, cy)), ((cx, cy), (bx, by))):
        d.line([p, q], fill=TEAL, width=6)

    # Right-angle marker at A.
    m = 30
    d.line([(ax + m, ay), (ax + m, ay - m), (ax, ay - m)], fill=TEAL, width=4)

    leg = _font(48)
    # a — left of the vertical leg midpoint.
    _centered(d, ((ax + cx) / 2 - 44, (ay + cy) / 2), "a", leg, AMBER)
    # b — below the horizontal leg midpoint.
    _centered(d, ((ax + bx) / 2, ay + 34), "b", leg, AMBER)
    # c — above-right of the hypotenuse midpoint.
    _centered(d, ((cx + bx) / 2 + 52, (cy + by) / 2 - 34), "c", leg, AMBER)

    # Caption: formula then subtitle, stacked below the triangle.
    _formula(d, H - 164, _font(64), _font(36), INK)
    _centered(d, (W / 2, H - 100), "The Pythagorean theorem", _font(30), INK_SOFT)

    img.save(OUT)
    return OUT


if __name__ == "__main__":
    print(f"wrote {make()} ({W}x{H})")
