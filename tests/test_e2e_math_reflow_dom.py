"""DOM-in/DOM-out cases against window.libliMathReflow.

Harness mirrors tests/test_e2e_text_colour.py:46-47,143-145 — set_content plus
add_script_tag. Do NOT use live_server + staticfiles: static() no-ops under
DEBUG=False in this repo. The module's export is unconditional precisely so this
page needs no KaTeX."""

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = str(ROOT / "courses/static/courses/js/math_reflow.js")

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Playwright's sync API runs an event loop, which trips Django's async-safety
    guard on every ORM call.

    MUST be session-scoped. tests/conftest.py has an autouse `_enable_db_access(db)`
    giving EVERY test under tests/ DB access, and conftest-level autouse fixtures run
    before module-level ones of the same scope -- so a function-scoped version sets
    the env var too late and all 63 cases ERROR with SynchronousOnlyOperation at
    setup (measured). As a fixture rather than a module global it activates only when
    an e2e test is actually selected, so the default `-m 'not e2e'` run keeps the
    guard intact. Same shape and name as the one in tests/test_e2e_text_colour.py."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _page(page, html):
    page.set_content(f"<!DOCTYPE html><div id='root'>{html}</div>")
    page.add_script_tag(path=SCRIPT)
    return page


def _reflow_html(page, html, options="undefined"):
    """Return #root.innerHTML after reflowing #root."""
    _page(page, html)
    return page.evaluate(
        "(o) => { const r = document.getElementById('root');"
        "         window.libliMathReflow(r, o); return r.innerHTML; }",
        None if options == "undefined" else options,
    )


def _reflow_text(page, text):
    """Inject `text` as a TEXT NODE, so a literal <br> stays literal.

    MEASURED TRAP: `_reflow_html(page, "\\[a<br>b\\]")` sets innerHTML, so the
    browser PARSES the <br> into a real BR element — which phase 1's isBareBr
    handles, meaning LITERAL_BR is never consulted. All five cases still pass with
    the entire phase1b pass deleted from reflow, and all four parametrised forms
    still pass with LITERAL_BR degraded to /<br>/g, so Step 5's falsification
    cannot fire. The stored cell shape is escaped TEXT (`&lt;br&gt;`), never an
    element — that is exactly why phase 1b exists."""
    _page(page, "")
    return page.evaluate(
        "(t) => { const r = document.getElementById('root');"
        "         r.appendChild(document.createTextNode(t));"
        "         window.libliMathReflow(r); return r.textContent; }",
        text,
    )


# Every case uses the NESTED <div>…</div> shape so the walk must actually DESCEND
# for a merge to be possible. MEASURED: with the flat shape
# (<pre>\[a</pre><pre>b\]</pre>) the outer tags are barriers at the parent level
# anyway — isMergeableBlock accepts only DIV/P — so those cases still pass with
# `textarea,pre,code` removed from IGNORE_SELECTOR entirely, and prove nothing.
IGNORED = [
    ("pre", "<pre><div>\\[a</div><div>b\\]</div></pre>"),
    ("code", "<code><div>\\[a</div><div>b\\]</div></code>"),
    # NOT a <textarea>: its content is RCDATA, so the parser stores it as one text
    # node and the serializer escapes it back out — `_reflow_html(html) == html`
    # FAILS for parsing reasons that have nothing to do with the reflow, and the
    # markup never becomes elements so the case would pass with `textarea` deleted
    # from IGNORE_SELECTOR anyway. `pre` and `code` do redden; `textarea` is covered
    # by its own assertion below.
    (
        "contenteditable",
        '<div contenteditable="true"><div>\\[a</div><div>b\\]</div></div>',
    ),
    ("katex", '<span class="katex"><div>\\[a</div><div>b\\]</div></span>'),
    ("katex-error", '<span class="katex-error">\\(a<br>b\\)</span>'),
    # option: RCDATA-ish like textarea, so use the escaped-<br> payload that makes
    # PHASE 1B the thing being suppressed, not the merge.
    ("option", "<select><option>\\[a&lt;br&gt;b\\]</option></select>"),
]

# script, noscript and style are in IGNORE_SELECTOR too, copied verbatim from
# auto-render's defaults. They are deliberately untested: none can hold authored
# prose in this app, and a fixture for them would assert on markup the sanitiser
# never emits. Named here so the omission is a decision, not an oversight.


@pytest.mark.parametrize("name,html", IGNORED, ids=[n for n, _ in IGNORED])
def test_ignored_subtrees_are_untouched(page, name, html):
    assert _reflow_html(page, html) == html


def test_textarea_is_ignored(page):
    """Asserted against the PARSED baseline, not the source string: <textarea> holds
    RCDATA, so innerHTML does not round-trip it.

    The payload is an ESCAPED <br> inside a span, so PHASE 1B is the thing being
    suppressed. MEASURED: with a plain <div>-split payload this case stays GREEN even
    with `textarea` deleted from IGNORE_SELECTOR — RCDATA makes it one text node, rule 4
    skips it, and there is nothing for phase 1b to touch. With this payload, deleting
    `textarea` rewrites the POSTed value, turning the escaped br into a real
    newline -- exactly the data-mutation class the ignore list exists to prevent."""
    page.set_content(
        "<!DOCTYPE html><section id='root'>"
        "<textarea>\\[a&lt;br&gt;b\\]</textarea></section>"
    )
    page.add_script_tag(path=SCRIPT)
    before = page.evaluate("() => document.getElementById('root').innerHTML")
    after = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); return r.innerHTML; }"
    )
    assert after == before


def test_contenteditable_false_is_not_ignored(page):
    """The bare [contenteditable] selector would also match contenteditable="false",
    which is not editable and carries no data-mutation risk."""
    html = '<div contenteditable="false"><div>\\[a</div><div>b\\]</div></div>'
    assert _reflow_html(page, html) != html


def test_falsy_root_is_a_no_op(page):
    _page(page, "")
    assert page.evaluate("() => { window.libliMathReflow(null); return true; }")


def test_document_root_does_not_throw(page):
    _page(page, "<div>\\[a</div><div>b\\]</div>")
    assert page.evaluate("() => { window.libliMathReflow(document); return true; }")


def test_root_inside_an_ignored_subtree_is_a_no_op(page):
    """The third of three shapes — root-is-ignored, root-is-an-ancestor,
    root-is-a-descendant. Only the first two were handled in an earlier draft."""
    _page(page, '<pre><span id="inner"><div>\\[a</div><div>b\\]</div></span></pre>')
    before = page.evaluate("() => document.getElementById('inner').innerHTML")
    after = page.evaluate(
        "() => { const n = document.getElementById('inner');"
        "        window.libliMathReflow(n); return n.innerHTML; }"
    )
    assert after == before


def test_basic_split_span_merges(page):
    out = _reflow_html(page, "<div>\\[x</div><div>y\\]</div>")
    assert out == "\\[x\ny\\]"


@pytest.mark.parametrize(
    "lead",
    [
        "<span>hi</span>",
        "<h3>Title</h3>",
        "<strong>lead</strong>",
        "<img src='x'>",
    ],
)
def test_content_before_the_run_is_not_destroyed(page, lead):
    """REGRESSION, measured: buildRun's offset->child map is RUN-LOCAL, so indexing
    the element's FULL children array with it diverges the moment a run does not
    start at child 0. The buggy form returned '\\[a\nb\\]<div>b\\]</div>' — the lead
    element destroyed, a stale <div> left behind. A heading or image above a split
    display block is the ordinary shape of this.

    Every other Task 4 fixture has a mergeable child at index 0 or a barrier that
    suppresses the rewrite, so nothing else in the table catches it."""
    page.set_content(
        "<!DOCTYPE html><section id='root'>"
        f"{lead}<div>\\[a</div><div>b\\]</div></section>"
    )
    page.add_script_tag(path=SCRIPT)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); return r.innerHTML; }"
    )
    assert out.startswith(lead.replace("'", '"'))
    assert out.endswith("\\[a\nb\\]")


def test_non_covered_siblings_survive_as_elements(page):
    """Three CHILDREN, of which only the middle is a text node — not three text
    nodes. auto-render re-joins adjacent text nodes, so an argument resting on a
    text-node boundary would be unfounded."""
    out = _reflow_html(page, "<div>a</div><div>\\[x</div><div>y\\]</div><div>b</div>")
    assert out == "<div>a</div>\\[x\ny\\]<div>b</div>"


def test_empty_class_attribute_still_merges(page):
    """nh3 emits an EMPTY class on div/p when every class value is rejected, so a
    formula pasted from Word/Docs carries class="" on every line. Treating that as
    'attributed' would make the whole feature a no-op on the dominant paste path."""
    out = _reflow_html(page, '<div class="">\\[x</div><div class="">y\\]</div>')
    assert out == "\\[x\ny\\]"
    out = _reflow_html(page, '<div style="">\\[x</div><div style="">y\\]</div>')
    assert out == "\\[x\ny\\]"


@pytest.mark.parametrize(
    "html",
    [
        '<div class="ta-center">\\[x</div><div class="ta-center">y\\]</div>',
        '<div data-x="1">\\[x</div><div data-x="1">y\\]</div>',
        "<div>\\[a</div><strong>x</strong><div>b\\]</div>",
        '<div>\\[a</div><span class="tc-red">x</span><div>b\\]</div>',
        "<div>\\[a</div><div><em>x</em></div><div>b\\]</div>",
    ],
)
def test_barriers_are_not_merged_across(page, html):
    assert _reflow_html(page, html) == html


def test_single_child_span_is_never_rewritten(page):
    """A span inside ONE mergeable <p> must keep its paragraph. Stating rule 4 in
    text-node terms instead of child-node terms would unwrap every authored
    paragraph containing math, on every render."""
    html = "<p>Let \\(x\\) be, so \\[y\\] holds</p>"
    assert _reflow_html(page, html) == html


def test_walk_descends_into_barriers(page):
    """MEASURED TRAP: a bare <td> outside a table is DROPPED by the HTML parser,
    leaving the two divs as direct children of #root — so the unwrapped version of
    this test passes for entirely the wrong reason. The table wrapper is mandatory."""
    html = (
        '<table><tbody><tr><td class="ta-center">'
        "<div>\\[x</div><div>y\\]</div></td></tr></tbody></table>"
    )
    assert _reflow_html(page, html) == (
        '<table><tbody><tr><td class="ta-center">\\[x\ny\\]</td></tr></tbody></table>'
    )


def test_real_br_outside_the_span_survives_as_an_element(page):
    out = _reflow_html(page, "<div>a<br>b \\[x</div><div>y\\]</div>")
    assert "<br>" in out
    assert "\\[x\ny\\]" in out


def test_empty_line_div_collapses_to_one_newline(page):
    """<div><br></div> is Chrome's empty line. Without collapsing it would emit a
    blank line, which in real LaTeX is a \\par and an error inside align*."""
    out = _reflow_html(page, "<div>\\[a</div><div><br></div><div>b\\]</div>")
    assert out == "\\[a\nb\\]"


def test_div_then_text_node_boundary_gets_a_newline(page):
    """A leading-only newline rule would concatenate the two tokens into
    \\alphax and KaTeX would report an undefined control sequence."""
    out = _reflow_html(page, "<div>\\[\\alpha</div>x\\]")
    assert out == "\\[\\alpha\nx\\]"


def test_escaped_closer_is_not_accepted(page):
    """Ported findEndOfMath: a backslash skips the following character."""
    out = _reflow_html(page, "<div>\\[a \\\\] b</div><div>c\\]</div>")
    assert out.count("\\]") == 2  # the escaped one survives inside the span
    assert "\n" in out  # and the span did merge


def test_closer_inside_braces_is_not_accepted(page):
    out = _reflow_html(page, "<div>\\[\\text{a\\]b}</div><div>c\\]</div>")
    assert out == "\\[\\text{a\\]b}\nc\\]"


def test_scanning_stops_at_an_unclosed_opener(page):
    """auto-render breaks out of its whole loop on an unclosed opener, so nothing
    after one is a candidate.

    MEASURED: the break is only observable with MIXED delimiters. In
    `\\[oops … \\[a … b\\]` the first `\\[` simply pairs with the only `\\]` — correct,
    and what auto-render does too — so that input tests nothing. A `\\(` with no
    `\\)` anywhere is a genuine unclosed opener, and it must suppress the complete
    `$$…$$` span that follows."""
    html = "<div>\\(oops</div><div>$$a</div><div>b$$</div>"
    assert _reflow_html(page, html) == html


def test_two_spans_in_one_run(page):
    """MEASURED: the two spans come out ADJACENT with no separator, because the
    boundary newline between them is synthetic, belongs to the second replacement
    group, and textFragment drops it there. Harmless — auto-render re-joins
    adjacent text nodes and parses both spans — but the assertion must match
    reality rather than the tidier-looking value."""
    out = _reflow_html(
        page, "<div>\\[a</div><div>b\\]</div><div>\\[c</div><div>d\\]</div>"
    )
    assert out == "\\[a\nb\\]\\[c\nd\\]"


def test_overlapping_covered_ranges_coalesce(page):
    """Child 2 holds the end of span 1 AND the start of span 2, so the ranges are
    not disjoint and no application order alone can work."""
    out = _reflow_html(page, "<div>\\[a</div><div>b\\] \\(c</div>d\\)")
    assert out == "\\[a\nb\\] \\(c\nd\\)"


def test_inline_span_merges_and_collapses_the_line(page):
    """Accepted consequence: the alternative leaves split inline math permanently
    broken, the same silent failure class this change removes."""
    out = _reflow_html(page, "<div>Prose \\(x</div><div>y\\) more</div>")
    assert out == "Prose \\(x\ny\\) more"


def test_bystander_intact_span_is_relocated_but_survives(page):
    out = _reflow_html(page, "<div>\\(x\\) prose \\[a</div><div>b\\]</div>")
    assert "\\(x\\)" in out
    assert "\\[a\nb\\]" in out


def test_nested_split_merges_after_post_order_folding(page):
    """The outer div is a barrier until post-order processing folds its nested
    divs into a text node — and only when the rewrite covered ALL of its element
    children."""
    out = _reflow_html(page, "<div><div>\\[a</div><div>b\\]</div></div>")
    assert out == "<div>\\[a\nb\\]</div>"


@pytest.mark.parametrize(
    "html",
    [
        "<div>\\(x<br>y\\) prose \\[a</div><div>b\\]</div>",
        "<div>p \\[a<br>b\\] q \\[c</div><div>d\\]</div>",
        "<div>c<br>z$$x</div><div>$$c<br><br>$$x<br> x$$c</div>",
    ],
)
def test_reflow_is_idempotent(page, html):
    """REGRESSION, measured by review. The old fixture `<div>\\[x</div><div>y\\]</div>`
    cannot catch any of this: it is a no-op on pass 2 BY CONSTRUCTION, so it can never
    exercise a first pass whose output differs from its second.

    The first two fixtures pin `textFragment`: post-order walk merges an intra-block
    `<br>`-split span at its OWN element's mergeChildren call first, embedding a real
    `\\n` inside a Text node; an ENCLOSING mergeChildren call's covered-but-unspanned
    range used to re-split that already-good `\\n` back into text/<br>/text, because
    the old `textFragment` only checked whether a `\\n` was synthetic, not whether it
    already lived inside an existing Text node. MEASURED: these two do NOT pin rule 4
    itself — a `map`-based (run-child) rule 4 already agrees with the `leaf`-based one
    at every call site these two fixtures exercise, because the `<br>` there splits a
    span within one element's OWN direct children, where `map` already distinguishes
    them regardless of leaf.

    The third fixture pins rule 4. MEASURED discriminating: with rule 4 reverted to
    `if (first !== last)` (comparing `map`) and `textFragment` left at HEAD, pass 1
    gives `...$$x<br> x$$c` (a live, unconverted `<br>`) while pass 2 gives
    `...$$x\\n x$$c` — non-idempotent. Fuzzed at 500 structured random documents:
    `map`-based rule 4 alone (`textFragment` fixed) was non-idempotent on 14/500
    shapes; `leaf`-based rule 4 fixed all of them."""
    _page(page, html)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); const a = r.innerHTML;"
        "        window.libliMathReflow(r); return [a, r.innerHTML]; }"
    )
    assert out[0] == out[1]


def test_delimiter_set_is_derived_from_options(page):
    """Three callers pass no delimiters and run on auto-render's defaults, which
    include $$ and the \\begin{...} pairs."""
    out = _reflow_html(page, "<div>$$x</div><div>y$$</div>")
    assert out == "$$x\ny$$"
    out = _reflow_html(
        page,
        "<div>$$x</div><div>y$$</div>",
        options={"delimiters": [{"left": "\\[", "right": "\\]", "display": True}]},
    )
    assert out == "<div>$$x</div><div>y$$</div>"


def test_caller_ignored_tags_are_unioned_in(page):
    """MEASURED: with the default <div id="root"> harness this passes for the WRONG
    reason — root.closest("div") matches the root itself and reflow bails before the
    walk ever runs. Verified against a <section> root, the divs merge unless
    extraSelector is threaded into isMergeable. The non-div root is mandatory."""
    page.set_content(
        "<!DOCTYPE html><section id='root'><div>\\[x</div><div>y\\]</div></section>"
    )
    page.add_script_tag(path=SCRIPT)
    before = page.evaluate("() => document.getElementById('root').innerHTML")
    after = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r, {ignoredTags: ['div']});"
        "        return r.innerHTML; }"
    )
    assert after == before


def test_phase_1b_converts_literal_br_inside_a_span(page):
    """The cell case is a RULE-4 SKIP — the span already sits in one text node.
    Hanging phase 1b off the rule-5 rewrite path would make it never fire."""
    assert _reflow_text(page, "\\[a<br>b\\]") == "\\[a\nb\\]"


@pytest.mark.parametrize("form", ["<br>", "<br/>", "<br />", "<BR>"])
def test_phase_1b_matches_every_br_form(page, form):
    """sanitize_cell stashes the span BEFORE nh3.clean, so what survives inside it
    is un-normalised author/browser markup."""
    assert _reflow_text(page, f"\\[a{form}b\\]") == "\\[a\nb\\]"


def test_phase_1b_leaves_p_alone(page):
    r"""CELL_TAGS has no p, and \(a<p>b\) is a plausible chain of inequalities."""
    assert _reflow_text(page, "\\(a<p>b\\)") == "\\(a<p>b\\)"
