# tests/test_htmlsandbox.py
from courses import htmlsandbox as hs

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


def test_katex_font_urls_rewritten_absolute():
    doc = hs.build_srcdoc(r"<p>\( a \)</p>", "", "", "", origin=ORIGIN)
    # No bare relative font refs survive; all point at the absolute static path.
    assert "url(fonts/" not in doc
    assert f"{ORIGIN}/static/courses/vendor/katex/fonts/" in doc


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
