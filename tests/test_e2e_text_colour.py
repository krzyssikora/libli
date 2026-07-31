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

from tests.factories import add_element
from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

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


def test_map_colours_preserves_a_selection_it_mutates(page):
    """Caret and undo (spec): mapColours saves and restores the Range only when it
    actually mutates AND the current selection is inside root. MEASURED without the
    fix: selecting 'cd' inside <p style="color: rgb(178,55,42)">abcdef</p> and running
    a mutating mapColours leaves the selection collapsed and empty, because
    wrapChildren moves the text node out from under the Range -- this fires on the
    paste-of-inline-coloured-content path."""
    _page_with_module(page)
    page.evaluate(
        """() => {
        document.getElementById('root').innerHTML =
            '<p style="color: rgb(178, 55, 42)">abcdef</p>';
    }"""
    )
    assert _select_text(page, "root", "cd")
    result = page.evaluate(
        """() => {
        const r = document.getElementById('root');
        libliColour.mapColours(r, {dropUnmapped: true});
        const sel = window.getSelection();
        return {collapsed: sel.isCollapsed, text: sel.toString()};
    }"""
    )
    assert result["collapsed"] is False, "a mutating mapColours must not drop the caret"
    assert result["text"] == "cd"


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
    r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    expected = f"rgb({r}, {g}, {b})"
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


@pytest.mark.django_db(transaction=True)
def test_colour_survives_save_and_reload(page, live_server):
    """The whole point, driven through the real gesture: type into the editor, select,
    click the red swatch, save, reload, and find the class still stored."""
    from courses.models import TextElement

    _make_pa_user("tc_save")
    _login(page, live_server, "tc_save")
    unit = _seed_course_and_unit("tc_save", slug="tc-save")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("alpha beta")
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-red"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()
    # Wait on a CHILD, not the slot itself: _element_row.html renders
    # <div class="el-edit-slot" data-edit-slot> unconditionally on every row, so the
    # slot survives the save (empty but present) and state="detached" on the bare
    # selector times out. Every shipped e2e scopes to a child for this reason.
    page.wait_for_selector(
        "[data-edit-slot] form[data-op='element-save']", state="detached"
    )

    body = TextElement.objects.order_by("-id").first().body
    assert "tc-red" in body, body
    assert "style" not in body, "colour must be stored as a class, never inline"

    # Reload and reopen — the round-trip half of the claim. classToStyle runs on
    # mount, and this is what proves it leaves tc-* alone.
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    page.locator("[data-element] .el-act-edit").first.click()
    page.wait_for_selector("[data-edit-slot] .rte-surface")
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 1


@pytest.mark.django_db(transaction=True)
def test_clear_through_the_wired_toolbar_removes_the_class(page, live_server):
    """Regression for a re-entrancy defect: text_toolbar.js's own `input` listener
    calls mapColours({dropUnmapped: true}), and Chromium fires `input` SYNCHRONOUSLY
    from inside execCommand. apply(root, null) marks its range with a SENTINEL colour
    via execCommand and only AFTERWARDS looks for it -- but SENTINEL is deliberately
    unmapped, so without apply()'s isApplying() guard the toolbar's own listener
    strips it first, and apply() finds nothing to clear. The unwired tests above
    (test_clear_over_an_enclosing_selection_removes_stored_colour and friends) call
    libliColour.apply() directly on a raw div and never exercise text_toolbar.js's
    listener at all, which is why this defect shipped unnoticed."""
    _make_pa_user("tc_clear")
    _login(page, live_server, "tc_clear")
    unit = _seed_course_and_unit("tc_clear", slug="tc-clear")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    page.keyboard.type("alpha beta")
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-red"]').click()
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 1

    # Re-focus the surface: the swatch click above moved focus to the button.
    surface.click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-none"]').click()

    remaining = page.locator(
        "[data-edit-slot] .rte-surface .tc-red, "
        "[data-edit-slot] .rte-surface .tc-blue, "
        "[data-edit-slot] .rte-surface .tc-green, "
        "[data-edit-slot] .rte-surface .tc-orange"
    )
    assert remaining.count() == 0, "colour-none through the real toolbar must clear"

    value = page.evaluate(
        "() => document.querySelector('[data-edit-slot] [data-rte-source]').value"
    )
    assert "tc-" not in value, value


@pytest.mark.django_db(transaction=True)
def test_paste_normalises_in_the_surface_and_the_textarea(page, live_server):
    """styleToClass is a pure STRING function and never touches the live surface, and
    sync is already registered on `input` — so the colour pass must run BEFORE it, or
    the textarea is written from un-normalised DOM and the sanitiser strips the colour
    on any save path that does not go through the form's submit handler."""
    _make_pa_user("tc_paste")
    _login(page, live_server, "tc_paste")
    unit = _seed_course_and_unit("tc_paste", slug="tc-paste")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")
    page.locator("[data-edit-slot] .rte-surface").wait_for(state="visible")

    page.evaluate(
        """() => {
        const s = document.querySelector('[data-edit-slot] .rte-surface');
        s.focus();
        s.innerHTML = '<span style="color: red">x</span>';
        s.dispatchEvent(new InputEvent('input', {inputType: 'insertFromPaste'}));
    }"""
    )
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 1
    value = page.evaluate(
        "() => document.querySelector('[data-edit-slot] [data-rte-source]').value"
    )
    assert "tc-red" in value, (
        "the textarea must carry the class immediately after paste"
    )
    assert "style" not in value


@pytest.mark.django_db(transaction=True)
def test_refusal_shows_the_translated_message(page, live_server):
    _make_pa_user("tc_refuse")
    _login(page, live_server, "tc_refuse")
    unit = _seed_course_and_unit("tc_refuse", slug="tc-refuse")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")
    page.locator("[data-edit-slot] .rte-surface").wait_for(state="visible")

    page.evaluate(
        """() => {
        const s = document.querySelector('[data-edit-slot] .rte-surface');
        s.innerHTML = 'a \\\\(x + y\\\\) b';
        const t = s.firstChild;
        const r = document.createRange();
        r.setStart(t, 3); r.setEnd(t, 4);          // selects just the '(' delimiter
                                                    // itself (offset 3-4 of the text
                                                    // "a \\(x + y\\) b"), not the
                                                    // region's interior -- still
                                                    // refused, same as wholly-inside
                                                    // or straddling
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    }"""
    )
    page.locator('[data-edit-slot] [data-cmd="colour-red"]').click()
    assert page.locator("[data-colour-refusal]").count() == 1
    assert page.locator("[data-edit-slot] .rte-surface .tc-red").count() == 0


@pytest.mark.django_db(transaction=True)
def test_cell_colour_reaches_the_saved_json(page, live_server):
    """Colour applied in a table cell must reach the stored JSON, not just the DOM.

    MEASURED: TableElement.save() calls _sanitized_data, NOT normalize_data, so the
    1x1 grid is stored with exactly the keys authored here.
    """
    from courses.models import Element
    from courses.models import TableElement

    _make_pa_user("tc_cell")
    _login(page, live_server, "tc_cell")
    unit = _seed_course_and_unit("tc_cell", slug="tc-cell")

    table = TableElement.objects.create(
        data={"cells": [[{"html": "abc", "halign": "left", "valign": "top"}]]}
    )
    add_element(unit, table)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    join = Element.objects.get(unit=unit, object_id=table.pk)
    page.locator(f"[data-element='{join.pk}'] .el-act-edit").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")
    cell = page.locator("[data-edit-slot] [data-table-grid] td[contenteditable]").first
    cell.wait_for(state="visible")
    cell.click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-blue"]').click()
    page.locator("[data-edit-slot] button[type='submit']").click()
    # Child-scoped, per the note in Task 9 — the slot div itself never detaches.
    page.wait_for_selector("[data-edit-slot] [data-table-editor]", state="detached")

    table.refresh_from_db()
    assert "tc-blue" in table.data["cells"][0][0]["html"], table.data


@pytest.mark.django_db(transaction=True)
def test_cell_clear_through_the_wired_toolbar_removes_the_class(page, live_server):
    """Regression for the same re-entrancy defect covered above for the RTE, but
    driven through a table cell editor: the grid's own `input` listener calls
    mapColours({dropUnmapped: true}), and Chromium fires `input` SYNCHRONOUSLY from
    inside execCommand. apply(cell, null) marks its range with a SENTINEL colour via
    execCommand and only AFTERWARDS looks for it -- so without apply()'s
    isApplying() guard mirrored in the grid's `input` listener, that listener strips
    the marker first and colour-none becomes a silent no-op. No unwired test (which
    calls libliColour.apply() directly on a raw div) catches this."""
    from courses.models import Element
    from courses.models import TableElement

    _make_pa_user("tc_cell_clear")
    _login(page, live_server, "tc_cell_clear")
    unit = _seed_course_and_unit("tc_cell_clear", slug="tc-cell-clear")

    table = TableElement.objects.create(
        data={"cells": [[{"html": "abc", "halign": "left", "valign": "top"}]]}
    )
    add_element(unit, table)

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    join = Element.objects.get(unit=unit, object_id=table.pk)
    page.locator(f"[data-element='{join.pk}'] .el-act-edit").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]")
    cell = page.locator("[data-edit-slot] [data-table-grid] td[contenteditable]").first
    cell.wait_for(state="visible")
    cell.click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-red"]').click()
    assert page.locator("[data-edit-slot] [data-table-grid] .tc-red").count() == 1

    # Re-focus the cell: the swatch click above moved focus to the button.
    cell.click()
    page.keyboard.press("Control+A")
    page.locator('[data-edit-slot] [data-cmd="colour-none"]').click()

    remaining = page.locator(
        "[data-edit-slot] [data-table-grid] .tc-red, "
        "[data-edit-slot] [data-table-grid] .tc-blue, "
        "[data-edit-slot] [data-table-grid] .tc-green, "
        "[data-edit-slot] [data-table-grid] .tc-orange"
    )
    assert remaining.count() == 0, "colour-none through the wired grid must clear"

    page.locator("[data-edit-slot] button[type='submit']").click()
    page.wait_for_selector("[data-edit-slot] [data-table-editor]", state="detached")

    table.refresh_from_db()
    assert "tc-" not in table.data["cells"][0][0]["html"], table.data


@pytest.mark.django_db(transaction=True)
def test_inline_prose_maths_colour_resolves_to_the_palette_token(page, live_server):
    """FIX 3: wrapRenderMathInElement -- the hook for INLINE PROSE maths, the exact
    case in the spec's Problem statement -- had zero coverage before this test. Its
    correctness depends on math.js:30,33 resolving `window.renderMathInElement` at
    CALL time (`renderInlineText`); if that global were ever captured into a local at
    load time, colour normalisation would silently stop firing and the rest of the
    suite (which drives katex.render display maths, not prose auto-render) would stay
    green regardless.

    Modelled on test_katex_colour_resolves_to_the_palette_token, but through a real
    lesson page rather than a bare page.evaluate: seeds a TextElement whose body is
    prose containing \\(\\color{red}{x}\\), loads it as the owning PA user (real
    gesture, real script load order -- see test_text_colour_script_order.py), and
    asserts the rendered element's computed colour equals --tc-red read from
    tokens.css, not a repeated literal.
    """
    import re

    from django.urls import reverse

    from courses.models import TextElement

    _make_pa_user("tc_prose_math")
    _login(page, live_server, "tc_prose_math")
    unit = _seed_course_and_unit("tc_prose_math", slug="tc-prose-math")
    add_element(
        unit,
        TextElement.objects.create(body=r"<p>Colour the term \(\color{red}{x}\).</p>"),
    )

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")

    mapped = page.locator(".el--text .tc-red")
    mapped.first.wait_for(state="attached", timeout=5000)
    assert mapped.count() >= 1
    # The raw LaTeX source must no longer be visible as text.
    assert "\\color" not in page.locator(".el--text").inner_text()

    computed = mapped.first.evaluate("(el) => getComputedStyle(el).color")

    tokens_text = Path(TOKENS_CSS).read_text(encoding="utf-8")
    light = re.search(r":root\s*\{(.*?)\n\}", tokens_text, re.DOTALL).group(1)
    digits = re.search(r"--tc-red:\s*#([0-9A-Fa-f]{6})", light).group(1)
    r, g, b = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    expected = f"rgb({r}, {g}, {b})"
    assert computed == expected, (
        f"prose maths resolved to {computed}, the --tc-red token is {expected}"
    )
