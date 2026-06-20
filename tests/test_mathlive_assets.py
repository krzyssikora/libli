from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "courses" / "static" / "courses" / "vendor" / "mathlive"


def test_mathlive_library_vendored():
    lib = VENDOR / "mathlive.min.js"
    assert lib.exists() and lib.stat().st_size > 100_000


def test_mathlive_fonts_vendored():
    fonts = list((VENDOR / "fonts").glob("*.woff2"))
    assert len(fonts) >= 15
