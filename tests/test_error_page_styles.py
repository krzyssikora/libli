"""Static-asset and stylesheet guards for the error pages.

Mirrors the convention in test_auth_styles.py / test_settings_styles.py: a new
per-page sheet ships with a regression guard for its vocabulary and its assets.
See docs/superpowers/specs/2026-07-23-illustrated-error-pages-design.md.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LEARNER = ROOT / "core" / "static" / "core" / "img" / "learner.png"


def test_learner_asset_exists_and_is_an_alpha_mask():
    # Not a nicety: production uses CompressedManifestStaticFilesStorage, whose
    # post-processing RAISES on a url() target that is missing -- so an absent
    # asset aborts collectstatic and stops the deploy.
    assert LEARNER.exists(), "learner.png missing -- collectstatic would abort"
    with Image.open(LEARNER) as im:
        assert im.mode == "LA", f"mask must be LA (alpha-only), got {im.mode}"
        assert im.size == (1600, 672), (
            "error.css hard-codes aspect-ratio: 1600 / 672; a re-derivation at a "
            f"different size would silently break the layout. Got {im.size}"
        )


def test_learner_asset_is_within_budget():
    size = LEARNER.stat().st_size
    assert size <= 60 * 1024, f"learner.png is {size} bytes; budget is 60 KB"
