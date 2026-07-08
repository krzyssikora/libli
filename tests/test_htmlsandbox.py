# tests/test_htmlsandbox.py
from courses import htmlsandbox
from courses import htmlsandbox as hs
from courses.htmlsandbox import _theme_tokens
from courses.htmlsandbox import build_srcdoc

ORIGIN = "http://testserver"


def test_has_math_delimiters():
    assert hs.has_math_delimiters(r"x \( a+b \) y") is True
    assert hs.has_math_delimiters(r"x \[ a \] y") is True
    assert hs.has_math_delimiters("no math here") is False
    assert hs.has_math_delimiters("$$x$$") is False  # $$ unsupported


def test_build_srcdoc_core_structure_and_csp():
    doc = hs.build_srcdoc("<p>hi</p>", "", "", "", origin=ORIGIN)
    assert doc.startswith("<!doctype html>")
    assert "<p>hi</p>" in doc
    assert f'<base href="{ORIGIN}/">' in doc
    assert "default-src 'none'" in doc
    assert "connect-src 'none'" in doc
    assert f"img-src {ORIGIN} data:" in doc
    assert f"font-src {ORIGIN} data:" in doc
    # inline author/seed/KaTeX scripts + styles must be permitted to run/apply:
    assert "script-src 'unsafe-inline'" in doc
    assert "style-src 'unsafe-inline'" in doc
    # 'self' is inert under an opaque origin — assert it never appears IN THE CSP
    # (scope to the CSP meta, not the whole doc: inlined KaTeX JS may contain "'self'").
    import re as _re

    csp = _re.search(r'Content-Security-Policy" content="([^"]*)"', doc).group(1)
    assert "'self'" not in csp
    assert "libli:htmlel:height" in doc  # resize reporter always present


def test_build_srcdoc_block_order_seed_before_course_js():
    doc = hs.build_srcdoc("<p>x</p>", "", "COURSE_JS_MARK", "SEED_MARK", origin=ORIGIN)
    assert doc.index("SEED_MARK") < doc.index("COURSE_JS_MARK")


def test_build_srcdoc_omits_empty_blocks():
    doc = hs.build_srcdoc("<p>x</p>", "", "", "", origin=ORIGIN)
    assert "<style></style>" not in doc
    assert "<script></script>" not in doc


def test_build_srcdoc_injects_css():
    doc = hs.build_srcdoc("<p>x</p>", ".q{color:red}", "", "", origin=ORIGIN)
    assert "<style>.q{color:red}</style>" in doc


def test_katex_gated_on_delimiters():
    no_math = hs.build_srcdoc("<p>plain</p>", "", "", "", origin=ORIGIN)
    assert "renderMathInElement" not in no_math
    with_math = hs.build_srcdoc(r"<p>\( a \)</p>", "", "", "", origin=ORIGIN)
    assert "renderMathInElement" in with_math


def test_katex_fonts_inlined_as_data_uris():
    # The sandbox iframe is sandbox="allow-scripts" (NO allow-same-origin), so its
    # document has an opaque NULL origin. A font fetch from there to the sandbox
    # origin is therefore cross-origin and CORS-blocked (Django static serves no
    # Access-Control-Allow-Origin). Fonts must be INLINED as data: URIs (permitted by
    # the CSP's `font-src ... data:`), never referenced by URL.
    doc = hs.build_srcdoc(r"<p>\( a \)</p>", "", "", "", origin=ORIGIN)
    # No font URL refs survive — neither bare-relative nor absolute cross-origin.
    assert "url(fonts/" not in doc
    assert f"{ORIGIN}/static/courses/vendor/katex/fonts/" not in doc
    # woff2 is inlined (every browser that runs the sandbox supports it).
    assert "url(data:font/woff2;base64," in doc


def test_build_srcdoc_light_baseline_before_author_css():
    # Dark-mode fix: the sandbox gets an explicit light surface so light-designed
    # content is never dark-on-(transparent)-dark; author CSS can still override.
    doc = hs.build_srcdoc("<p>x</p>", ".q{color:red}", "", "", origin=ORIGIN)
    assert "html,body{background:#fff;color:#111}" in doc
    assert doc.index("html,body{background:#fff") < doc.index(".q{color:red}")


def test_build_srcdoc_wraps_seed_as_window_seed():
    # The seed field now holds a JS object literal; the server wraps it as window.SEED.
    doc = hs.build_srcdoc("<p>x</p>", "", "", "{a:1}", origin=ORIGIN)
    assert "window.SEED = ({a:1});" in doc
    # Empty seed -> no SEED script at all.
    assert "window.SEED" not in hs.build_srcdoc("<p>x</p>", "", "", "", origin=ORIGIN)


ORIGIN = "https://sandbox.example"


def _doc(**kw):
    return build_srcdoc("<p>x</p>", "", "", "", origin=ORIGIN, **kw)


def test_base_style_unchanged_light_locked():
    # The shared base must NOT theme html/body — that would regress other courses.
    assert htmlsandbox._BASE_STYLE == "html,body{background:#fff;color:#111}"


def test_theme_tokens_four_part_and_colour_only():
    block = _theme_tokens()
    # light on :root, dark under @media and [data-theme="dark"], light restored
    # under [data-theme="light"]
    assert ":root{" in block
    assert "@media(prefers-color-scheme:dark){:root{" in block
    assert ':root[data-theme="dark"]{' in block
    assert ':root[data-theme="light"]{' in block
    # a representative colour token appears with both its light and dark values
    assert "--surface-raised:#FFFFFF" in block or "--surface-raised: #FFFFFF" in block
    assert "--surface-raised:#2C2925" in block or "--surface-raised: #2C2925" in block
    # non-colour tokens are excluded
    assert "--radius-" not in block
    assert "--shadow-" not in block
    assert "--space-" not in block
    assert "--heading-letter-spacing" not in block
    # no color-scheme *property* in the shared block (it belongs to the opting-in
    # course); scope out "prefers-color-scheme" (the media-feature name), which
    # legitimately contains this substring and is asserted present just above.
    assert "color-scheme" not in block.replace("prefers-color-scheme", "")


def test_theme_tokens_brand_inputs_light_only():
    block = _theme_tokens()
    # --brand-primary/--brand-accent are declared only under :root in tokens.css (no
    # dark override). The four-part emitter puts the light set in BOTH light arms
    # (:root and :root[data-theme="light"]) -> count 2, and NEVER in the dark arms
    # (built from tokens.css's [data-theme="dark"] set, which omits brand inputs), so
    # they correctly inherit their light value in dark mode.
    assert block.count("--brand-primary:") == 2
    dark_attr = block.split(':root[data-theme="dark"]{', 1)[1].split("}", 1)[0]
    assert "--brand-primary:" not in dark_attr


def test_build_srcdoc_bakes_data_theme_for_explicit_theme():
    assert '<html data-theme="dark">' in _doc(theme="dark")
    assert '<html data-theme="light">' in _doc(theme="light")


def test_build_srcdoc_no_data_theme_when_none():
    assert "data-theme" not in _doc(theme=None).split("<head>")[0]


def test_token_block_inserted_after_base_before_base_style():
    doc = _doc(theme="dark")
    i_base = doc.index("<base ")
    i_tokens = doc.index(":root[data-theme=")
    i_basestyle = doc.index(htmlsandbox._BASE_STYLE)
    assert i_base < i_tokens < i_basestyle


def test_theme_listener_present():
    assert "libli:htmlel:theme" in _doc()


def test_theme_tokens_match_tokens_css_full_set():
    # Anti-drift (spec-mandated): the sandbox block must define the SAME colour token
    # set as tokens.css, with equal values, for both themes — no missing/extra token.
    # A set-equality test (not spot-checks) is what catches a dropped token.
    import re as _re
    from pathlib import Path

    from django.contrib.staticfiles import finders

    from courses.htmlsandbox import _colour_decls  # shares the exclusion constant

    src = Path(finders.find("core/css/tokens.css")).read_text(encoding="utf-8")

    def _pairs(selector_re):
        m = _re.search(selector_re + r"\s*\{([^}]*)\}", src)
        decls = _colour_decls(m.group(1)) if m else ""
        return dict(
            (d.split(":", 1)[0].strip(), d.split(":", 1)[1].strip())
            for d in decls.split(";")
            if d.strip()
        )

    light = _pairs(r":root")
    dark = _pairs(r'\[data-theme="dark"\]')
    block = _theme_tokens()
    # every light token appears with its light value
    for name, val in light.items():
        assert f"{name}:{val}" in block, f"missing light {name}"
    # every dark token appears with its dark value (brand inputs are light-only,
    # so they are absent from `dark` and correctly not required here)
    for name, val in dark.items():
        assert f"{name}:{val}" in block, f"missing dark {name}"
    # representative tokens that a comment-swallowing bug would have dropped
    for name in ("--brand-primary", "--primary", "--surface-base", "--success"):
        assert name in light


def test_html_element_js_has_theme_bridge():
    from pathlib import Path

    from django.contrib.staticfiles import finders

    src = Path(finders.find("courses/js/html_element.js")).read_text(encoding="utf-8")
    assert "libli:htmlel:theme" in src
    assert "MutationObserver" in src
    assert "data-theme" in src
