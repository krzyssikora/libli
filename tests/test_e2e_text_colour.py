"""Browser-level behaviour of window.libliColour.

EVERY set_content string here starts with <!DOCTYPE html>. Playwright's set_content
emits no doctype, which leaves the document in quirks mode, and katex.render then
throws "KaTeX doesn't work in quirks mode" — the assertion never runs and the test
errors instead of failing. Do not "tidy" the doctype away.

The pure helpers (normaliseColour, and the two DOM passes over fixed markup) are
exercised via page.evaluate — they are functions, not gestures. Everything involving
a selection or a toolbar click is driven through the real UI in later tasks, because
an e2e that bypasses the real gesture ships broken UX green.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "courses/static/courses/js/text_colour.js")
KATEX = str(ROOT / "courses/static/courses/vendor/katex/katex.min.js")
TOKENS_CSS = str(ROOT / "core/static/core/css/tokens.css")
COURSES_CSS = str(ROOT / "courses/static/courses/css/courses.css")


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Playwright's sync API runs an event loop, which trips Django's async-safety
    guard on every ORM call. Enable the escape hatch for the browser suite only --
    as a fixture (not a module/conftest global) it activates solely when an e2e test
    is actually selected, so the default `-m 'not e2e'` run keeps the guard intact."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _page_with_module(page):
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.add_script_tag(path=SCRIPT)
    return page


def test_normalise_colour_accepts_every_input_form(page):
    _page_with_module(page)
    assert page.evaluate("() => libliColour.normaliseColour('#B2372A')") == [
        178,
        55,
        42,
    ]
    assert page.evaluate("() => libliColour.normaliseColour('rgb(178, 55, 42)')") == [
        178,
        55,
        42,
    ]
    assert page.evaluate("() => libliColour.slotFor('red')") == "red"
    assert page.evaluate("() => libliColour.slotFor('purple')") is None
    assert page.evaluate("() => libliColour.slotFor(libliColour.SENTINEL)") is None


def test_map_colours_moves_a_class_off_a_block_tag(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<p style="color: rgb(178, 55, 42)">x</p>';
        libliColour.mapColours(r, {dropUnmapped: true});
        return r.innerHTML;
    }"""
    )
    assert 'class="tc-red"' in html
    assert "<span" in html, "a block tag may not carry tc-*; wrap its children instead"
    assert "style" not in html


def test_map_colours_leaves_unmapped_colour_on_the_render_path(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span style="color: purple">x</span>';
        libliColour.mapColours(r, {dropUnmapped: false});
        return r.innerHTML;
    }"""
    )
    assert "purple" in html, "render path must not destroy existing \\color{purple}"


def test_map_colours_is_a_noop_on_second_call(page):
    _page_with_module(page)
    first, second = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span style="color: rgb(31, 97, 173)">x</span>';
        libliColour.mapColours(r, {dropUnmapped: true});
        const a = r.innerHTML;
        libliColour.mapColours(r, {dropUnmapped: true});
        return [a, r.innerHTML];
    }"""
    )
    assert first == second


def test_nested_colour_spans_collapse_innermost_wins(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span class="tc-red"> <span class="tc-blue">x</span> </span>';
        libliColour.mapColours(r, {dropUnmapped: true});
        return r.innerHTML;
    }"""
    )
    assert "tc-blue" in html
    assert "tc-red" not in html, "whitespace text nodes must not defeat the collapse"


def test_tidy_unwraps_a_bare_span_but_keeps_semantic_ones(page):
    _page_with_module(page)
    html = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        r.innerHTML = '<span>a</span><span class="tc-red">b</span>'
                    + '<b>c</b><span data-x="1">d</span>';
        libliColour.tidyPastedSpans(r);
        return r.innerHTML;
    }"""
    )
    assert html.startswith("a"), "a bare span must be unwrapped"
    assert 'class="tc-red"' in html
    assert "<b>c</b>" in html
    assert "data-x" in html, "a span with another attribute is not paste litter"


def test_pasted_katex_becomes_its_latex_source(page):
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    text = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        const host = document.createElement('div');
        katex.render('x^2', host, {throwOnError: false});
        r.innerHTML = host.innerHTML;
        libliColour.tidyPastedSpans(r);
        return r.textContent;
    }"""
    )
    assert text.strip() == "\\(x^2\\)", (
        "rule (a) must run before rule (b); a .katex wrapper matches (b)'s predicate, "
        "so a (b)-first pass destroys the subtree before its annotation is read"
    )
    assert "<span" not in text
