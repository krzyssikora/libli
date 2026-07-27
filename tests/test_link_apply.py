"""Unit tests for link_apply.js, run in a real browser.

There is no jsdom here (no package.json, no vitest/jest). The repo's one precedent for
unit-testing a JS module is Playwright as a JS runtime: add_script_tag the module into a
blank page and call its exports via evaluate. That is WHY the mutation logic lives in
link_apply.js rather than inside text_toolbar.js's IIFE -- logic private to that closure
would only be reachable by driving the whole editor.
"""

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # tests/conftest.py makes `db` autouse for EVERY test, and _django_db_helper
    # touches the ORM while Playwright's sync-API event loop is running. Without this
    # the whole file ERRORs at setup with SynchronousOnlyOperation -- even though these
    # tests never use the database themselves. Every e2e file in the repo carries it,
    # including the cited precedent tests/test_table_grid_algebra.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


MODULE = (
    Path(__file__).resolve().parent.parent
    / "courses"
    / "static"
    / "courses"
    / "js"
    / "link_apply.js"
)

SELECT_ALL = (
    "(s) => { const r = document.createRange(); r.selectNodeContents(s); return r; }"
)
CARET_IN_FIRST_LINK = (
    "(s) => { const a = s.querySelector('a');"
    " const r = document.createRange();"
    " r.setStart(a.firstChild, 1); r.collapse(true); return r; }"
)
SELECT_FIRST_LINK = (
    "(s) => { const r = document.createRange();"
    " r.selectNodeContents(s.querySelector('a')); return r; }"
)
CARET_AT_END = (
    "(s) => { const r = document.createRange();"
    " r.setStart(s.firstChild, s.firstChild.length);"
    " r.collapse(true); return r; }"
)


@pytest.fixture
def page_with_module(page):
    page.set_content("<div id='s' contenteditable='true'></div>")
    page.add_script_tag(path=str(MODULE))
    return page


def _apply(page, html, build_range_js, result):
    """Set the surface's HTML, build a Range with build_range_js, apply, return HTML."""
    return page.evaluate(
        """([html, buildRange, result]) => {
            const s = document.getElementById('s');
            s.innerHTML = html;
            const range = (new Function('s', 'return (' + buildRange + ')(s)'))(s);
            window.libliLinkApply.apply(s, range, result);
            return s.innerHTML;
        }""",
        [html, build_range_js, result],
    )


def _apply_then(page, html, build_range_js, result, probe_js):
    """Same, but return the value of probe_js evaluated against the surface after."""
    return page.evaluate(
        """([html, buildRange, result, probe]) => {
            const s = document.getElementById('s');
            s.innerHTML = html;
            const range = (new Function('s', 'return (' + buildRange + ')(s)'))(s);
            window.libliLinkApply.apply(s, range, result);
            return (new Function('s', 'return (' + probe + ')(s)'))(s);
        }""",
        [html, build_range_js, result, probe_js],
    )


# ---- URL contract: an ORDERED table, first match wins ----------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("//evil.com/x", {"reject": "protocol-relative"}),
        ("https://example.test/courses/n/12/", {"href": "/courses/n/12/"}),
        ("javascript:alert(1)", {"reject": "scheme"}),
        ("ftp://x.test/f", {"reject": "scheme"}),
        ("https://ok.test/a", {"href": "https://ok.test/a"}),
        ("mailto:a@b.test", {"href": "mailto:a@b.test"}),
        ("example.com", {"href": "https://example.com"}),
        ("example.com:8080/x", {"href": "https://example.com:8080/x"}),
        ("../foo", {"reject": "relative"}),
        ("/path", {"reject": "relative"}),
        ("#section", {"reject": "relative"}),
        ("example", {"reject": "relative"}),
    ],
)
def test_normalize_url(page_with_module, value, expected):
    got = page_with_module.evaluate(
        "([v, o]) => window.libliLinkApply.normalizeUrl(v, o)",
        [value, "https://example.test"],
    )
    assert got == expected


def test_permalink_on_a_different_origin_is_not_normalised(page_with_module):
    # Row 2 compares location.origin EXACTLY (scheme + host + port).
    got = page_with_module.evaluate(
        "([v, o]) => window.libliLinkApply.normalizeUrl(v, o)",
        ["https://other.test/courses/n/12/", "https://example.test"],
    )
    assert got == {"href": "https://other.test/courses/n/12/"}


def test_permalink_with_query_suffix_is_an_ordinary_url(page_with_module):
    got = page_with_module.evaluate(
        "([v, o]) => window.libliLinkApply.normalizeUrl(v, o)",
        ["https://example.test/courses/n/12/?x=1", "https://example.test"],
    )
    assert got == {"href": "https://example.test/courses/n/12/?x=1"}


# ---- anchor enumeration ----------------------------------------------------


def test_touched_anchors_spans_links_wholly_inside_the_range(page_with_module):
    # closest() from the boundaries is NOT enough: with the selection starting in plain
    # text before link A and ending after link B, both boundary walks return null, so
    # Remove link would be disabled and rule 2 would unwrap nothing.
    n = page_with_module.evaluate(
        """(build) => {
            const s = document.getElementById('s');
            s.innerHTML = 'x <a href="/a/">A</a> y <a href="/b/">B</a> z';
            const r = (new Function('s', 'return (' + build + ')(s)'))(s);
            return window.libliLinkApply.anchorsFor(s, r).length;
        }""",
        SELECT_ALL,
    )
    assert n == 2


def test_collapsed_caret_inside_a_link_counts_one(page_with_module):
    # intersectsNode reports true for merely ADJACENT nodes in some engines, so the
    # collapsed case is decided by the enclosing predicate alone.
    n = page_with_module.evaluate(
        """(build) => {
            const s = document.getElementById('s');
            s.innerHTML = 'x <a href="/a/">A</a> y';
            const r = (new Function('s', 'return (' + build + ')(s)'))(s);
            return window.libliLinkApply.anchorsFor(s, r).length;
        }""",
        CARET_IN_FIRST_LINK,
    )
    assert n == 1


def test_collapsed_caret_outside_any_link_counts_zero(page_with_module):
    n = page_with_module.evaluate(
        """() => {
            const s = document.getElementById('s');
            s.innerHTML = 'plain text';
            const r = document.createRange();
            r.setStart(s.firstChild, 2); r.collapse(true);
            return window.libliLinkApply.anchorsFor(s, r).length;
        }"""
    )
    assert n == 0


# ---- insertion rules: ordered, first match wins, total over ranges ---------


def test_rule1_selection_coextensive_with_a_link_edits_it(page_with_module):
    # The most common re-link gesture (double-click a one-word link). A "strictly
    # inside" reading would leave this matching NO rule.
    out = _apply(
        page_with_module,
        '<a href="/old/">Word</a>',
        SELECT_FIRST_LINK,
        {"href": "/courses/n/9/", "text": "Word"},
    )
    assert out.count("<a") == 1
    assert 'href="/courses/n/9/"' in out


def test_rule1_unmodified_text_preserves_inline_markup(page_with_module):
    out = _apply(
        page_with_module,
        '<a href="/old/">the <b>vertex</b> unit</a>',
        CARET_IN_FIRST_LINK,
        {"href": "/courses/n/9/", "text": "the vertex unit"},
    )
    assert "<b>vertex</b>" in out
    assert 'href="/courses/n/9/"' in out


def test_rule1_edited_text_replaces_contents(page_with_module):
    out = _apply(
        page_with_module,
        '<a href="/old/">the <b>vertex</b> unit</a>',
        CARET_IN_FIRST_LINK,
        {"href": "/courses/n/9/", "text": "new label"},
    )
    assert "<b>" not in out
    assert "new label" in out


def test_partial_selection_inside_a_link_exposes_the_full_text(page_with_module):
    # The prefill-precedence hazard: existing.text must be the anchor's WHOLE
    # textContent, or an author shown "vertex" would silently lose "the ... form unit"
    # when they edit the field. text_toolbar.js reads exactly this.
    got = page_with_module.evaluate(
        """() => {
            const s = document.getElementById('s');
            s.innerHTML = '<a href="/old/">the vertex form unit</a>';
            const t = s.querySelector('a').firstChild;
            const r = document.createRange();
            r.setStart(t, 4); r.setEnd(t, 10);        // "vertex"
            const enc = window.libliLinkApply.enclosing(s, r);
            return [r.toString(), enc.textContent];
        }"""
    )
    assert got == ["vertex", "the vertex form unit"]


def test_rule2_selection_starting_at_an_anchors_first_character(page_with_module):
    # The marker-node ordering case: a boundary container that IS the anchor would be
    # detached by the unwrap, leaving the range pointing at nothing.
    out = _apply(
        page_with_module,
        '<a href="/a/">AB</a>CD',
        (
            "(s) => { const a = s.querySelector('a');"
            " const r = document.createRange();"
            " r.setStart(a.firstChild, 0); r.setEnd(s.lastChild, 2); return r; }"
        ),
        {"href": "/courses/n/9/", "text": "linked"},
    )
    assert out.count("<a") == 1
    assert 'href="/courses/n/9/"' in out


def test_rule2_leaves_no_marker_or_split_text_node(page_with_module):
    # The stated point of the marker sequence: markers removed, text nodes merged.
    kids = _apply_then(
        page_with_module,
        'before <a href="/a/">AB</a> after',
        SELECT_ALL,
        {"href": "/courses/n/9/", "text": "L"},
        "(s) => Array.from(s.childNodes).map(n => n.nodeName)",
    )
    assert kids == ["A"], kids


def test_rule2_overlap_unlinks_the_unselected_remainder(page_with_module):
    # Stated loss: a selection covering the tail of A and the head of B leaves BOTH
    # fully unlinked, including the parts never selected. The alternative (splitting
    # A and B) would produce three anchors from one gesture.
    out = _apply(
        page_with_module,
        '<a href="/a/">AAA</a> mid <a href="/b/">BBB</a>',
        (
            "(s) => { const as = s.querySelectorAll('a');"
            " const r = document.createRange();"
            " r.setStart(as[0].firstChild, 2);"
            " r.setEnd(as[1].firstChild, 1); return r; }"
        ),
        {"href": "/courses/n/9/", "text": "L"},
    )
    assert out.count("<a") == 1
    assert "/a/" not in out
    assert "/b/" not in out


def test_rule3_collapsed_caret_inserts_a_new_anchor(page_with_module):
    out = _apply(
        page_with_module,
        "plain",
        CARET_AT_END,
        {"href": "/courses/n/9/", "text": "New"},
    )
    assert 'href="/courses/n/9/"' in out
    assert ">New<" in out


def test_caret_after_an_insert_sits_outside_the_anchor(page_with_module):
    # This is what makes collapseAfter load-bearing: without it the caret stays INSIDE
    # the new link and every subsequent keystroke silently extends the link text.
    inside = _apply_then(
        page_with_module,
        "plain",
        CARET_AT_END,
        {"href": "/courses/n/9/", "text": "New"},
        (
            "(s) => { const r = window.getSelection().getRangeAt(0);"
            " const a = s.querySelector('a');"
            " return a.contains(r.startContainer) && r.startContainer !== s; }"
        ),
    )
    assert inside is False


def test_remove_unwraps_all_touched_anchors(page_with_module):
    out = _apply(
        page_with_module,
        'x <a href="/a/">A</a> y <a href="/b/">B</a> z',
        SELECT_ALL,
        {"remove": True},
    )
    assert "<a" not in out
    assert "A" in out
    assert "B" in out


def test_remove_leaves_the_caret_at_the_end_of_the_recovered_text(page_with_module):
    # Spec: "the caret is collapsed at the end of the recovered text". Also guards the
    # normalize() hazard: merging text nodes DETACHES all but the first, so a caret
    # anchored to a pre-normalise node would make setStartAfter throw.
    got = _apply_then(
        page_with_module,
        'x <a href="/a/">AAA</a> y',
        CARET_IN_FIRST_LINK,
        {"remove": True},
        (
            "(s) => { const r = window.getSelection().getRangeAt(0);"
            " const before = r.startContainer.textContent.slice(0, r.startOffset);"
            " return [r.collapsed, before]; }"
        ),
    )
    assert got[0] is True
    assert got[1].endswith("AAA")


def test_link_text_is_written_as_a_text_node(page_with_module):
    # Node titles are author-supplied and may contain markup characters.
    out = _apply(
        page_with_module,
        "plain",
        CARET_AT_END,
        {"href": "/courses/n/9/", "text": "<b>bold</b>"},
    )
    assert "&lt;b&gt;bold&lt;/b&gt;" in out
    assert "<b>bold</b>" not in out
