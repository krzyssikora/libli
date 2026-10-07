"""The die-face font (U+2680-2685) is wired into the UI font stack.

Source-level guards only; tests/test_e2e_dice_glyph_font.py measures the rendered
glyph, which is the only test that can fail when the rule is present but the browser
ignores it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "core/static/core/css/tokens.css"
FONT_DIR = ROOT / "core/static/core/fonts/dice"

CSS = re.sub(r"/\*.*?\*/", "", TOKENS.read_text(encoding="utf-8"), flags=re.S)


def _dice_face():
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", CSS)
    dice = [f for f in faces if re.search(r'font-family:\s*"libli-dice"', f)]
    assert len(dice) == 1, faces
    return dice[0]


def test_the_face_covers_only_the_six_die_faces():
    assert re.search(r"unicode-range:\s*U\+2680-2685\s*;", _dice_face())


def test_the_face_is_scaled_to_the_owner_approved_size():
    assert re.search(r"size-adjust:\s*170%\s*;", _dice_face())


def test_the_face_points_at_a_shipped_file_with_its_licence():
    url = re.search(r'url\("\.\./fonts/dice/([^"]+)"\)', _dice_face())
    assert url, _dice_face()
    font = FONT_DIR / url.group(1)
    assert font.is_file(), font
    # A subset of six glyphs; a full symbol font here means the subsetting was lost.
    assert font.stat().st_size < 4096, font.stat().st_size
    assert "SIL Open Font License" in (FONT_DIR / "OFL.txt").read_text(encoding="utf-8")


def test_the_ui_stack_tries_the_die_face_first():
    # A family is consulted only for characters every EARLIER family lacks, and the
    # system fonts after Inter (Segoe UI Symbol and friends) DO have U+2680-2685 -- the
    # tiny glyphs this replaces. Right after Inter would also work today (MEASURED: the
    # e2e stays green there, Inter has no die faces), but FIRST does not depend on
    # Inter's coverage staying that way.
    stack = re.search(r"--font-ui:\s*([^;]+);", CSS).group(1)
    assert stack.split(",")[0].strip() == '"libli-dice"', stack
