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


def _select_text(page, root_id, needle):
    """Select `needle` inside `root_id` by walking text nodes — the same offset
    mapping apply() uses, so the test exercises the real path."""
    return page.evaluate(
        """([rootId, needle]) => {
        const root = document.getElementById(rootId);
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let acc = '', nodes = [];
        while (walker.nextNode()) { nodes.push([walker.currentNode, acc.length]);
                                    acc += walker.currentNode.nodeValue; }
        const at = acc.indexOf(needle);
        if (at < 0) return false;
        const end = at + needle.length;
        let sN, sO, eN, eO;
        for (const [node, base] of nodes) {
            const len = node.nodeValue.length;
            if (sN === undefined && at >= base && at <= base + len) {
                sN = node; sO = at - base;
            }
            if (end >= base && end <= base + len) { eN = node; eO = end - base; }
        }
        const range = document.createRange();
        range.setStart(sN, sO); range.setEnd(eN, eO);
        const sel = window.getSelection();
        sel.removeAllRanges(); sel.addRange(range);
        return true;
    }""",
        [root_id, needle],
    )


def test_refuses_a_selection_wholly_inside_a_maths_region(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + y\\\\) b</div>'; }"""
    )
    assert _select_text(page, "root", "x")
    outcome = page.evaluate(
        "() => libliColour.apply(document.getElementById('root'), 'red')"
    )
    assert outcome == "refused"
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert "tc-red" not in html, "a refusal must not mutate the DOM"


def test_refuses_a_selection_straddling_a_maths_boundary(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + y\\\\) b</div>'; }"""
    )
    assert _select_text(page, "root", "a \\(x")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_allows_a_selection_enclosing_a_whole_maths_region(page):
    """The one ALLOWED branch. Without this case an implementation that refuses every
    intersection passes the whole suite and the falsification rule catches nothing."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x+y\\\\) b</div>'; }"""
    )
    assert _select_text(page, "root", "a \\(x+y\\) b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "ok"
    )
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert "tc-red" in html
    assert "\\(x+y\\)" in html, "the delimiters must survive intact"


def test_refuses_enclosing_a_region_that_contains_an_element_boundary(page):
    """The carve-out on the ALLOWED branch. Such a region already round-trips lossily
    through sanitize_cell with or without colour, so a span there is not a gesture the
    storage layer can support. Without this case, an implementation that ignores
    element boundaries entirely passes every other D8 test."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + <b>y</b>\\\\) b</div>'; }"""
    )
    # Pin the delimiters BEFORE selecting. With single backslashes Python emits a
    # SyntaxWarning, the JS literal collapses \( to (, and the DOM text becomes
    # "a (x + y) b" with no delimiters at all -- _select_text then returns False and
    # the test dies on the wrong assertion while the carve-out goes unexercised.
    assert "\\(" in page.evaluate("() => document.getElementById('root').textContent")
    assert _select_text(page, "root", "a \\(x + y\\) b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_refuses_inside_a_marker(page):
    """D10: markers are parsed AFTER sanitisation, so a coloured marker becomes the
    stored answer. The test runs on every surface, so no opt-in attribute is needed."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">pick {{a|b}} now</div>'; }"""
    )
    assert _select_text(page, "root", "a")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_fails_closed_on_an_unclosed_delimiter(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">a \\\\(x + y b</div>'; }"""
    )
    assert _select_text(page, "root", "y b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), 'red')")
        == "refused"
    )


def test_clear_over_an_enclosing_selection_removes_stored_colour(page):
    """The primary clear path. Stored colour is class-carried with NO inline colour,
    and an enclosing selection nests the sentinel span OUTSIDE it — so the surviving
    tc-* is a DESCENDANT. An ancestors-only rule leaves Clear a silent no-op here."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">'
        + '<span class="tc-red">abc</span>def</div>'; }"""
    )
    assert _select_text(page, "root", "abcdef")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), null)")
        == "ok"
    )
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert "tc-red" not in html
    assert "abcdef" in page.evaluate(
        "() => document.getElementById('root').textContent"
    )


def test_clear_over_a_partial_selection_leaves_the_remainder_coloured(page):
    """execCommand does NOT split class-carried colour (there is no inline colour to
    split), so apply() must split explicitly or Clear wipes the whole run."""
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">'
        + '<span class="tc-red">abc</span></div>'; }"""
    )
    assert _select_text(page, "root", "b")
    assert (
        page.evaluate("() => libliColour.apply(document.getElementById('root'), null)")
        == "ok"
    )
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert html.count("tc-red") == 2, f"a and c must stay coloured, b cleared: {html}"


def test_clearing_a_link_keeps_the_link(page):
    _page_with_module(page)
    page.evaluate(
        """() => { document.getElementById('root').outerHTML =
        '<div id="root" contenteditable="true">'
        + '<a href="/courses/n/12/" class="tc-red">link</a></div>'; }"""
    )
    assert _select_text(page, "root", "link")
    page.evaluate("() => libliColour.apply(document.getElementById('root'), null)")
    html = page.evaluate("() => document.getElementById('root').innerHTML")
    assert 'href="/courses/n/12/"' in html, "clearing must never unwrap a link"
    assert "tc-red" not in html


def test_katex_colour_resolves_to_the_palette_token(page):
    """D4: prose tc-red and \\color{red} must be the SAME colour. Asserting 'a colour
    is present' would pass even if the class were added while the inline colour stayed,
    which is the failure mode — inline style always beats a class."""
    # Load the REAL stylesheets. An inline `.tc-red{color:#B2372A}` stub makes the
    # computed value a foregone conclusion and proves nothing about palette identity
    # — it is a fourth unguarded copy of the literal. (katex.min.css sets no color.)
    page.set_content("<!DOCTYPE html><div id='m'></div>")
    page.add_style_tag(path=TOKENS_CSS)
    page.add_style_tag(path=COURSES_CSS)
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    computed = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{red}{x}', m, {throwOnError: false});
        const el = m.querySelector('.tc-red');
        return el ? getComputedStyle(el).color : null;
    }"""
    )
    # Compare against the token itself, never a repeated literal.
    import re

    tokens = Path(TOKENS_CSS).read_text(encoding="utf-8")
    light = re.search(r":root\s*\{(.*?)\n\}", tokens, re.DOTALL).group(1)
    digits = re.search(r"--tc-red:\s*#([0-9A-Fa-f]{6})", light).group(1)
    expected = (
        "rgb(%d, %d, %d)"
        % tuple(  # noqa: UP031
            int(digits[i : i + 2], 16) for i in (0, 2, 4)
        )
    )
    assert computed == expected, (
        f"maths resolved to {computed}, prose token is {expected} — the mapped "
        "element must carry the class AND have its inline colour cleared"
    )


def test_katex_layout_style_survives_the_wrapper(page):
    """Clear the color LONGHAND, not the style attribute: KaTeX packs height and
    vertical-align into the same attribute and removing it destroys the layout."""
    page.set_content("<!DOCTYPE html><div id='m'></div>")
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    heights = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{red}{\\\\frac{1}{2}}', m, {throwOnError: false});
        return [...m.querySelectorAll('[style]')].map(e => e.getAttribute('style'))
            .filter(s => /height|vertical-align/.test(s)).length;
    }"""
    )
    assert heights > 0, "layout declarations must survive"


def test_unmapped_katex_colour_is_left_untouched(page):
    page.set_content("<!DOCTYPE html><div id='m'></div>")
    page.add_script_tag(path=KATEX)
    page.add_script_tag(path=SCRIPT)
    html = page.evaluate(
        """() => {
        const m = document.getElementById('m');
        katex.render('\\\\color{purple}{x}', m, {throwOnError: false});
        return m.innerHTML;
    }"""
    )
    assert "purple" in html
