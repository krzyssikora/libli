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


ERROR_CSS = ROOT / "core" / "static" / "core" / "css" / "error.css"


def test_error_css_defines_the_error_page_vocabulary():
    css = ERROR_CSS.read_text(encoding="utf-8")
    for cls in (
        "body.error-page",
        ".error-page__main",
        ".error-page__inner",
        ".error-page__code",
        ".error-page__title",
        ".error-page__lead",
        ".error-page__path",
        ".error-page__note",
        ".error-page__actions",
    ):
        assert cls in css, f"error.css must style {cls}"


def test_error_css_guards_mask_support_and_prefixes_every_longhand():
    # The @supports arm deliberately admits prefix-only engines; those engines
    # ignore the UNPREFIXED longhands, so dropping a -webkit- form would let them
    # through the guard and paint the mask tiled at 1600x672, top-left.
    css = ERROR_CSS.read_text(encoding="utf-8")
    assert "@supports" in css
    for prop in (
        "-webkit-mask-image",
        "-webkit-mask-repeat",
        "-webkit-mask-position",
        "-webkit-mask-size",
    ):
        assert prop in css, f"{prop} missing -- prefix-only engines would misrender"
    # mask-mode is the documented exception: no -webkit- form exists in any engine.
    assert "mask-mode: alpha" in css
    assert "-webkit-mask-mode" not in css, "-webkit-mask-mode is not a real property"


def test_error_css_pins_the_asset_aspect_ratio():
    # Fails together with the 1600x672 assertion above if the PNG is re-derived
    # at another size -- the asset and the stylesheet must agree.
    css = ERROR_CSS.read_text(encoding="utf-8")
    assert "aspect-ratio: 1600 / 672" in css


def test_error_css_is_token_only_no_raw_hex():
    import re

    css = ERROR_CSS.read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "use tokens, not raw hex"
    assert "background-color: var(--text-primary)" in css


def test_error_css_stacking_invariant():
    """watermark 0 < .error-page__main 1 < .app-header 2.

    Inverting this reproduces a regression that has already shipped once (see the
    'Log out looks see-through and can't be tapped' comment in app.css).
    """
    import re

    css = ERROR_CSS.read_text(encoding="utf-8")
    assert ".app-main" not in css, (
        "keep .app-main out of error.css -- a global rule would make every <main> "
        "a stacking context and trap .modal / .unit-drawer / .math-modal"
    )

    def z(selector):
        block = re.search(re.escape(selector) + r"[^{]*\{[^}]*\}", css, re.S)
        assert block, f"no rule found for {selector}"
        m = re.search(r"z-index:\s*(-?\d+)", block.group(0))
        assert m, f"no z-index in the {selector} rule"
        return int(m.group(1))

    assert z("body.error-page::after") < z(".error-page__main")
    assert z(".error-page__main") < z("body.error-page .app-header")
