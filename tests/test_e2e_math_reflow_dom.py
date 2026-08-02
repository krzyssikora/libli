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
    the env var too late and all 170 cases ERROR with SynchronousOnlyOperation at
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
    text-node boundary would be unfounded.

    The trailing "\\n" (kept, not dropped, per the textFragment fix) sits right
    before the surviving `<div>b</div>` and collapses away with identical rendered
    output — a block element's own layout already suppresses adjacent inter-block
    whitespace — but the exact innerHTML gains that literal character."""
    out = _reflow_html(page, "<div>a</div><div>\\[x</div><div>y\\]</div><div>b</div>")
    assert out == "<div>a</div>\\[x\ny\\]\n<div>b</div>"


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
    """MEASURED: the boundary newline between the two spans is synthetic and is
    kept as a literal "\\n" character (not dropped), so the two replacement groups
    come out separated by a bare newline rather than glued together. HTML collapses
    that "\\n" to a single space when rendered, so innerText reads
    "\\[a b\\] \\[c d\\]" -- stays visually separated, unlike pre-fix
    "\\[a b\\]\\[c d\\]"."""
    out = _reflow_html(
        page, "<div>\\[a</div><div>b\\]</div><div>\\[c</div><div>d\\]</div>"
    )
    assert out == "\\[a\nb\\]\n\\[c\nd\\]"


def test_prose_survives_on_both_sides_of_a_group_boundary(page):
    """Regression for the round-final review fix. The math-only fixture above
    (test_two_spans_in_one_run) cannot catch this: with no prose around either
    span, dropping the boundary newline is invisible. Here it is not: BEFORE the
    fix this produced "\\[a\nb\\] tailhead \\[c\nd\\]", silently concatenating the
    author's "tail" and "head" into one word, because the synthetic newline
    between the two groups was dropped instead of kept. The kept literal "\\n"
    keeps them apart; HTML collapses it to a single space on render."""
    out = _reflow_html(
        page,
        "<div>\\[a</div><div>b\\] tail</div><div>head \\[c</div><div>d\\]</div>",
    )
    assert out == "\\[a\nb\\] tail\nhead \\[c\nd\\]"
    assert "tailhead" not in out


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
    extraSelector is threaded into classifyChild and isMergeableBlock. The non-div
    root is mandatory."""
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


def test_phase_2_promotes_an_inline_display_only_environment(page):
    out = _reflow_html(page, "\\(\\begin{align*}a&=1\\end{align*}\\)")
    assert out.startswith("\\[") and out.endswith("\\]")


def test_phase_2_tests_contains_not_begins_with(page):
    r"""All five repairable question stems are \(-wrapped and OPEN with
    \begin{cases}, with \begin{align} nested inside. Measured: inline FAILS with
    '{align} can be used only in display mode'; display renders."""
    out = _reflow_html(
        page, "\\(\\begin{cases}\\begin{align}a&=1\\end{align}\\end{cases}\\)"
    )
    assert out.startswith("\\[") and out.endswith("\\]")


def test_phase_2_does_not_promote_a_both_modes_environment(page):
    r"""A prefix match on \begin{align} would also match \begin{aligned}, which
    works in BOTH modes — promoting it would convert correct inline math to a
    display block.

    NO `&` IN THE FIXTURE: innerHTML serialises `&` as `&amp;`, so an
    `out == html` equality over a fixture containing `a&=1` can never hold — both
    of these assertions failed for exactly that reason before it was removed. The
    promotion decision does not depend on the alignment marker."""
    html = "\\(\\begin{aligned}a=1\\end{aligned}\\)"
    assert _reflow_html(page, html) == html


def test_phase_2_respects_the_effective_span_partition(page):
    r"""A \(...\) sequence INSIDE a $$...$$ span is not a span at all; a raw scan
    would rewrite its delimiters and corrupt the enclosing formula. (Again no `&`
    in the fixture — see the note above.)"""
    html = "$$x \\(\\begin{align}a=1\\end{align}\\) y$$"
    assert _reflow_html(page, html) == html


def test_split_inline_align_comes_out_merged_and_promoted(page):
    """Pins the phase ordering: promote-then-merge would leave this unpromoted."""
    out = _reflow_html(
        page, "<div>\\(\\begin{align*}a&=1</div><div>\\end{align*}\\)</div>"
    )
    assert out.startswith("\\[") and out.endswith("\\]")
    assert "\n" in out


def _hookb(page, expr):
    """Install a fake katex BEFORE the module loads, then read what it received."""
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.evaluate(
        "() => { window.__seen = null;"
        "        window.katex = { render: (e) => { window.__seen = e; } };"
        "        window.renderMathInElement = () => {}; }"
    )
    page.add_script_tag(path=SCRIPT)
    page.evaluate("(e) => window.katex.render(e, null, {})", expr)
    return page.evaluate("() => window.__seen")


def test_hook_b_strips_a_display_wrapper(page):
    assert (
        _hookb(page, "\\[\\begin{align*}a&=1\\end{align*}\\]")
        == "\\begin{align*}a&=1\\end{align*}"
    )


def test_hook_b_strips_an_inline_wrapper(page):
    assert _hookb(page, "\\(x\\)") == "x"


def test_hook_b_skips_leading_whitespace(page):
    assert _hookb(page, "  \\[x\\]  ") == "x"


def test_hook_b_refuses_two_adjacent_spans(page):
    r"""findEndOfMath stops at the first \], which is not the expression's end."""
    assert _hookb(page, "\\[a\\] + \\[b\\]") == "\\[a\\] + \\[b\\]"


def test_hook_b_tolerates_row_spacing(page):
    r"""A legitimate \\[2ex] in the body neither opens nor closes anything."""
    expr = "\\[\\begin{align*}a&=1\\\\[2ex]b&=2\\end{align*}\\]"
    assert _hookb(page, expr) == "\\begin{align*}a&=1\\\\[2ex]b&=2\\end{align*}"


def test_hook_b_passes_a_non_string_through_untouched(page):
    """expr is not guaranteed to be a string at every call site, and an exception
    here is swallowed by math.js renderOne's catch, leaving no diagnostic."""
    page.set_content("<!DOCTYPE html><div id='root'></div>")
    page.evaluate(
        "() => { window.__seen = 'unset';"
        "        window.katex = { render: (e) => { window.__seen = e; } };"
        "        window.renderMathInElement = () => {}; }"
    )
    page.add_script_tag(path=SCRIPT)
    page.evaluate("() => window.katex.render(42, null, {})")
    assert page.evaluate("() => window.__seen") == 42


# ---- failure containment: the try/catch is the only safety net for an
# implementation bug, and an untested catch is exactly what falsification exists
# to prevent. Atomicity here is PER-ELEMENT, not per-subtree: a throw after an
# earlier element's rewrites leaves the DOM partially rewritten. What must hold
# is that no IGNORED subtree was ever entered.


def test_a_poisoned_delimiter_set_does_not_throw(page):
    _page(page, "<div>\\[x</div><div>y\\]</div>")
    ok = page.evaluate(
        "() => { try { window.libliMathReflow("
        "          document.getElementById('root'), {delimiters: 'not-an-array'});"
        "        return true; } catch (e) { return false; } }"
    )
    assert ok


def test_a_mid_walk_throw_leaves_ignored_subtrees_untouched(page):
    """Atomicity is PER-ELEMENT, not per-subtree: a try/catch gives no rollback,
    so a throw after an earlier element's rewrites leaves the DOM partially
    rewritten. What must hold is that no ignored subtree was entered."""
    html = (
        '<div id="a"><div>\\[x</div><div>y\\]</div></div>'
        '<pre id="b"><div>\\[x</div><div>y\\]</div></pre>'
    )
    _page(page, html)
    before_pre = page.evaluate("() => document.getElementById('b').innerHTML")
    page.evaluate(
        "() => { const orig = Node.prototype.removeChild; let n = 0;"
        "        Node.prototype.removeChild = function () {"
        "          if (++n > 1) { Node.prototype.removeChild = orig;"
        "                         throw new Error('boom'); }"
        "          return orig.apply(this, arguments); };"
        "        try { window.libliMathReflow(document.getElementById('root')); }"
        "        catch (e) {} finally { Node.prototype.removeChild = orig; } }"
    )
    assert page.evaluate("() => document.getElementById('b').innerHTML") == before_pre


def test_a_throw_mid_walk_does_not_abort_the_rest_of_the_traversal(page):
    """Pins the per-element try/catch inside walk. The first element's visit throws;
    the SECOND element must still be merged. Falsify by removing that try/catch —
    this must go RED while test_a_mid_walk_throw_leaves_ignored_subtrees_untouched
    stays green, which is why that one is not sufficient on its own."""
    page.set_content(
        "<!DOCTYPE html><section id='root'>"
        "<section id='a'><div>\\[x</div><div>y\\]</div></section>"
        "<section id='b'><div>\\[p</div><div>q\\]</div></section></section>"
    )
    page.add_script_tag(path=SCRIPT)
    out = page.evaluate(
        "() => { const orig = Element.prototype.insertBefore; let n = 0;"
        "        Element.prototype.insertBefore = function () {"
        "          if (++n === 1) { throw new Error('boom'); }"
        "          return orig.apply(this, arguments); };"
        "        try { window.libliMathReflow(document.getElementById('root')); }"
        "        finally { Element.prototype.insertBefore = orig; }"
        "        return document.getElementById('b').innerHTML; }"
    )
    assert out == "\\[p\nq\\]"


def test_a_malformed_delimiter_entry_falls_back_to_the_defaults(page):
    """Pins the delimitersFor type guard. [1, 2] is a non-empty array of non-objects;
    without the guard `delimiters[i].left` throws, and the reflow is swallowed by its
    own catch, so nothing merges. Falsify by reverting to
    `(options && options.delimiters) || DEFAULT_DELIMITERS`."""
    out = _reflow_html(
        page, "<div>\\[x</div><div>y\\]</div>", options={"delimiters": [1, 2]}
    )
    assert out == "\\[x\ny\\]"


def _hooka(page, html):
    """Install a recording fake renderMathInElement BEFORE the module loads."""
    page.set_content(f"<!DOCTYPE html><section id='root'>{html}</section>")
    page.evaluate(
        "() => { window.__calls = [];"
        "        window.renderMathInElement = function (r, o) {"
        "          window.__calls.push(r.innerHTML); return 'sentinel'; };"
        "        window.katex = { render: () => {} }; }"
    )
    page.add_script_tag(path=SCRIPT)
    ret = page.evaluate(
        "() => window.renderMathInElement(document.getElementById('root'), undefined)"
    )
    return page.evaluate("() => window.__calls"), ret


def test_hook_a_reflows_before_delegating_and_forwards_the_return(page):
    calls, ret = _hooka(page, "<div>\\[x</div><div>y\\]</div>")
    assert calls == ["\\[x\ny\\]"]  # the original saw the MERGED dom
    assert ret == "sentinel"  # and its return value came back


def test_hook_a_still_delegates_when_the_reflow_throws(page):
    page.set_content("<!DOCTYPE html><section id='root'><div>\\[x</div></section>")
    page.evaluate(
        "() => { window.__ran = false;"
        "        window.renderMathInElement = () => { window.__ran = true; };"
        "        window.katex = { render: () => {} }; }"
    )
    page.add_script_tag(path=SCRIPT)
    # MEASURED: {ignoredTags: {bad: 1}} does NOT throw — extraIgnoreSelector reads
    # .length, which is undefined on a plain object, so the loop never runs and it
    # returns null. An invalid CSS selector does throw: node.matches("[") raises
    # SyntaxError inside the walk.
    page.evaluate(
        "() => window.renderMathInElement(document.getElementById('root'),"
        "                                 {ignoredTags: ['[']})"
    )
    assert page.evaluate("() => window.__ran") is True


def test_double_include_installs_only_one_wrapper(page):
    """MEASURED: asserting `len(calls) == 1` CANNOT redden. __calls records the
    innermost fake, and a double wrap is wrapper2 -> reflow -> wrapper1 -> reflow
    -> fake, so the fake is still called exactly once even with the guard deleted.
    Assert on the wrapper IDENTITY instead, which is what a second install changes."""
    page.set_content("<!DOCTYPE html><section id='root'></section>")
    page.evaluate(
        "() => { window.renderMathInElement = function () {};"
        "        window.katex = { render: () => {} }; }"
    )
    page.add_script_tag(path=SCRIPT)
    page.evaluate("() => { window.__first = window.renderMathInElement; }")
    page.add_script_tag(path=SCRIPT)
    assert page.evaluate("() => window.renderMathInElement === window.__first")
    assert page.evaluate("() => window.__libliMathReflowWrapped") is True


def test_centred_siblings_merge_into_one_wrapper(page):
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_centred_paragraphs_merge_and_keep_the_p_tag(page):
    """Tag equality is load-bearing in the compatibility table, and the only other
    <p> case is a barrier — without this, restricting the reuse path to DIV would
    pass every other test."""
    out = _reflow_html(
        page,
        '<p class="ta-center">\\[a</p><p class="ta-center">b\\]</p>',
    )
    assert out == '<p class="ta-center">\\[a\nb\\]</p>'


@pytest.mark.parametrize("token", ["ta-left", "ta-right"])
def test_other_align_tokens_merge_too(page, token):
    """Nothing may be hardcoded to centre."""
    out = _reflow_html(
        page, f'<div class="{token}">\\[a</div><div class="{token}">b\\]</div>'
    )
    assert out == f'<div class="{token}">\\[a\nb\\]</div>'


def test_unsigned_mixed_tag_run_still_merges(page):
    """<p>…</p><div>…</div> is ordinary Chromium contenteditable output (courses.css
    :24-25): Enter emits a <div> while the first block may be a <p>. It is also the
    ONLY shape that distinguishes "tag equality when signed" from "tag equality
    always" — the </p><p> repairs that motivate the rule are same-tag."""
    assert _reflow_html(page, "<p>\\[a</p><div>b\\]</div>") == "\\[a\nb\\]"


def test_whitespace_between_centred_blocks_is_transparent(page):
    """The corpus shape: nh3 preserves inter-tag newlines, and scripts/lal_import/out
    has 505 of them between sibling divs. Anchored to the SIGNED shape deliberately —
    an unsigned whitespace fixture passes on master and under every mutant."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div>\n<div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_empty_centred_line_between_the_lines_collapses(page):
    """<div><br></div> is Chromium's empty line, and centring a multi-line selection
    aligns it too. It contributes zero characters to run.text, so it appears in
    `nodes` and in the group range but never in run.map — the index-based removal
    loop is what takes it out."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div>'
        '<div class="ta-center"><br></div>'
        '<div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_leading_br_inside_the_wrapper_is_dropped(page):
    """Spec Sec5 step 2 decides this ON PURPOSE: a leading (or collapsed) <br> INSIDE
    the block that becomes the wrapper contributes zero characters to run.text (same
    reasoning as test_br_leading_a_signed_run_is_untouched), so it is represented
    nowhere in the replacement -- and mergeChildren's signed-branch removal loop
    takes it out unconditionally, exactly as the unsigned path drops a whole matching
    block. This is the one place the signed rewrite DELETES authored markup rather
    than relocating it. Not a defect; pinned so the decision reads as deliberate
    rather than undecided."""
    out = _reflow_html(
        page,
        '<div class="ta-center"><br>\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div>'


def test_whitespace_only_class_merges(page):
    """alignToken parses a token SET, so class=" " yields "" and is mergeable, where
    noEffectiveAttributes (value === "") called it a barrier. Deliberate widening."""
    assert _reflow_html(page, '<div class=" ">\\[a</div><div class=" ">b\\]</div>') == (
        "\\[a\nb\\]"
    )


def test_padded_align_class_matches_the_unpadded_one(page):
    """The OTHER half of parsing a token set rather than the raw attribute string:
    class=" ta-center " and class="ta-center" must compare equal. The surviving
    wrapper keeps its own original, un-normalised class string — the reuse path
    never re-serialises the attribute."""
    out = _reflow_html(
        page,
        '<div class=" ta-center ">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '<div class=" ta-center ">\\[a\nb\\]</div>'


def test_partial_coverage_leaves_the_uncovered_block(page):
    out = _reflow_html(
        page,
        '<div class="ta-center">x</div>'
        '<div class="ta-center">\\[a</div>'
        '<div class="ta-center">b\\]</div>',
    )
    assert out == (
        '<div class="ta-center">x</div><div class="ta-center">\\[a\nb\\]</div>'
    )


def test_two_spans_in_one_signed_run_keep_the_boundary_newline(page):
    """Group 1's endOffset extends past the span to include the synthetic boundary
    newline mapping to child 1, so on the reuse path that newline lands INSIDE the
    first wrapper rather than staying a bare text node between the groups. It is
    deliberately not trimmed: dropping a synthetic newline is what glued author
    prose together in the predecessor's "tailhead" defect."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>'
        '<div class="ta-center">\\[c</div><div class="ta-center">d\\]</div>',
    )
    assert out == (
        '<div class="ta-center">\\[a\nb\\]\n</div>'
        '<div class="ta-center">\\[c\nd\\]</div>'
    )


def test_nested_signed_run_preserves_one_nesting_level(page):
    """The unsigned rewrite hoists content into the parent, so one nesting level
    disappears; the reuse path keeps the wrapper, so the level count is preserved.
    The wrapper MUST survive to carry the alignment — this is the price of the
    feature, and it is asserted so it stays a decision."""
    out = _reflow_html(
        page,
        '<div><div class="ta-center">\\[a</div><div class="ta-center">b\\]</div></div>',
    )
    assert out == '<div><div class="ta-center">\\[a\nb\\]</div></div>'


@pytest.mark.parametrize(
    "html",
    [
        # 1. signed + unsigned
        '<div class="ta-center">\\[a</div><div>b\\]</div>',
        # 2. two different tokens
        '<div class="ta-center">\\[a</div><div class="ta-right">b\\]</div>',
        # 3. same token, different tag
        '<p class="ta-center">\\[a</p><div class="ta-center">b\\]</div>',
        # 4. signed run interrupted by NON-whitespace text
        '<div class="ta-center">\\[a</div>stray<div class="ta-center">b\\]</div>',
        # 5. signed run interrupted by a bare <br>
        '<div class="ta-center">\\[a</div><br><div class="ta-center">b\\]</div>',
        # 6. ineligible multi-token class (nh3 keeps BOTH tokens -- measured)
        '<div class="ta-center ta-left">\\[a</div>'
        '<div class="ta-center ta-left">b\\]</div>',
        # 7. signed block holding an element child -- the child-shape check
        '<div class="ta-center">\\[a<em>x</em></div><div class="ta-center">b\\]</div>',
        # 8. NON-EMPTY style -- blockAttributesOk's one novel clause, and the RTE's
        #    own representation of alignment (text_toolbar.js converts ta-* back to
        #    style="text-align:…" on load). Without this case, weakening the clause
        #    to `if (attr.name === "style") continue;` is invisible to the entire
        #    suite once Task 3 deletes the old ta-center barrier entry -- measured.
        '<div style="text-align:center">\\[a</div>'
        '<div style="text-align:center">b\\]</div>',
    ],
)
def test_signed_barriers_are_not_merged_across(page, html):
    assert _reflow_html(page, html) == html


def test_ignored_tag_suppresses_a_signed_block(page):
    """Barrier 9 (the parametrize list above holds 1-8). The root must be <section>,
    not <div>: reflow's root guard
    (`root.closest(extra)`) would make a <div> root pass for the wrong reason — the
    same trap test_caller_ignored_tags_are_unioned_in records."""
    html = '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>'
    page.set_content(f"<!DOCTYPE html><section id='root'>{html}</section>")
    page.add_script_tag(path=SCRIPT)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r, {ignoredTags: ['div']});"
        "        return r.innerHTML; }"
    )
    assert out == html


def test_ignored_br_still_breaks_a_run(page):
    """Barrier 10 — the ONLY case that reaches the classifier's isIgnored guard. A
    bare <br> is classified via isBareBr and never reaches isMergeableBlock, so that
    guard is the sole thing keeping an ignored <br> out of a run; case 9's <div> is
    still caught by isMergeableBlock's own check. Deleting isMergeable removed the
    line that used to enforce this, so without this test the regression ships with
    every other case green."""
    html = "<div>\\[a</div><br><div>b\\]</div>"
    page.set_content(f"<!DOCTYPE html><section id='root'>{html}</section>")
    page.add_script_tag(path=SCRIPT)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r, {ignoredTags: ['br']});"
        "        return r.innerHTML; }"
    )
    assert out == html


def test_text_after_a_signed_run_starts_a_new_run(page):
    """M3: a TEXT that ends a signed run becomes the first member of a NEW run
    rather than being excluded from every run. Excluding it regresses a shape that
    merges on master."""
    out = _reflow_html(page, '<div class="ta-center">x</div>\\[a<div>b\\]</div>')
    assert out == '<div class="ta-center">x</div>\\[a\nb\\]'


def test_text_leading_a_signed_run_is_untouched(page):
    """M5's only coverage. An M5 violation moves the synthetic boundary newline
    INSIDE the wrapper — a single whitespace character, which a startswith/endswith
    assertion would not catch. Hence exact equality."""
    out = _reflow_html(
        page,
        'lead <div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == 'lead <div class="ta-center">\\[a\nb\\]</div>'


def test_text_trailing_a_signed_run_is_untouched(page):
    """Pinned by a DIFFERENT mutant from the leading case: here the run is already
    signed when the text arrives, so the text is ended by M3, not M5. Discriminating
    against "signed runs admit TEXT and BR members"."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div> trail',
    )
    assert out == '<div class="ta-center">\\[a\nb\\]</div> trail'


def test_br_leading_a_signed_run_is_untouched(page):
    """M5's condition is "TEXT and BR members" and sawTextOrBr covers both — but a
    leading BR is NOT observable, so this is a REGRESSION GUARD, not a falsifiable
    fixture. Measured: a leading bare <br> contributes zero characters (buildRun's
    `text.length && …` is false at position 0), so it never enters run.map,
    group.first is still the first block, and the wrapper is byte-identical whether
    or not M5 fired. Mutant L leaves it green; only mutant A (revert) reddens it."""
    out = _reflow_html(
        page,
        '<br><div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '<br><div class="ta-center">\\[a\nb\\]</div>'


def test_whitespace_leading_a_signed_run_does_not_break_it(page):
    """M5's WS_TEXT carve-out. REGRESSION GUARD ONLY — no mutant of the PARTITION
    RULES can redden it, because every reading of a leading WS_TEXT yields identical
    DOM; only mutant A (reverting the feature) does. Listed here so its
    unfalsifiability is a recorded decision rather than an oversight."""
    out = _reflow_html(
        page,
        '\n<div class="ta-center">\\[a</div><div class="ta-center">b\\]</div>',
    )
    assert out == '\n<div class="ta-center">\\[a\nb\\]</div>'


def test_centred_inline_align_comes_out_merged_and_promoted(page):
    """Phase 2 interaction. Uses align*, NOT cases: DISPLAY_ONLY_ENVS is ten exact
    literals and `cases` is deliberately not among them, so a \\(\\begin{align*}…\\)
    span merges but never promotes."""
    out = _reflow_html(
        page,
        '<div class="ta-center">\\(\\begin{align*}a&amp;=1</div>'
        '<div class="ta-center">\\end{align*}\\)</div>',
    )
    assert out.startswith('<div class="ta-center">\\[')
    assert out.endswith("\\]</div>")


@pytest.mark.parametrize(
    "html",
    [
        # 1. LITERAL markup, not "a signed block with an intra-block <br>-split
        #    span". The trailing `prose \[a` AND the second signed block are what
        #    make the textFragment leaf guard fire -- the guard only executes from an
        #    enclosing merge's covered-but-unspanned range. Reduced to
        #    <div class="ta-center">\(x<br>y\)</div> both textFragment calls are
        #    empty, the outer span is a leaf skip, and the fixture stays green under
        #    its own mutant while still looking like it merged.
        '<div class="ta-center">\\(x<br>y\\) prose \\[a</div>'
        '<div class="ta-center">b\\]</div>',
        # 2. two spans with prose between them AND an intra-block <br>. The <br> is
        #    load-bearing, not decoration: without it no earlier nested merge ever
        #    plants a \n inside a Text node, the leaf guard never fires, and the
        #    fixture is green under its own mutant -- measured. The predecessor's
        #    fixture 2 has the <br> for exactly this reason.
        '<div class="ta-center">p \\[a<br>b\\] q \\[c</div>'
        '<div class="ta-center">d\\]</div>',
        # 3. the signed analogue of the map-vs-leaf discriminating shape recorded in
        #    math_reflow.js's rule-4 comment
        '<div class="ta-center">c<br>z$$x</div>'
        '<div class="ta-center">$$c<br><br>$$x<br> x$$c</div>',
    ],
)
def test_signed_reflow_is_idempotent(page, html):
    _page(page, html)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); const a = r.innerHTML;"
        "        window.libliMathReflow(r); return [r.innerHTML === a, a]; }"
    )
    assert out[0], f"pass 2 diverged from pass 1: {out[1]!r}"
    # Positive precondition: without this a no-op satisfies the test trivially,
    # which is exactly how a suppress-the-merge mutant would pass.
    assert out[1] != html, "pass 1 did not change the markup"


_TEMPLATES = {
    "whole": "<{t}{c}>\\[a</{t}>{sep}<{t}{c}>b\\]</{t}>",
    "trailing": "<{t}{c}>\\[a</{t}>{sep}<{t}{c}>b\\] tail</{t}>",
    "intra_br": "<{t}{c}>\\[a<br>b\\]</{t}>{sep}<{t}{c}>c</{t}>",
}
_SEPARATORS = {"none": "", "ws": "\n", "br": "<br>", "text": "sep"}


@pytest.mark.parametrize("placement", sorted(_TEMPLATES))
@pytest.mark.parametrize("sep_name", sorted(_SEPARATORS))
@pytest.mark.parametrize("token", ["", "ta-center", "ta-right"])
@pytest.mark.parametrize("tag", ["div", "p"])
def test_idempotent_across_the_cross_product(page, tag, token, sep_name, placement):
    """The merge-expected predicate is DATA, stated in the spec, not derived from the
    implementation's output -- deriving it from what the code does would make the
    anti-vacuity assertion circular, which is the whole reason it exists."""
    cls = f' class="{token}"' if token else ""
    html = _TEMPLATES[placement].format(t=tag, c=cls, sep=_SEPARATORS[sep_name])
    merge_expected = (
        placement == "intra_br" or token == "" or sep_name in ("none", "ws")
    )

    _page(page, html)
    out = page.evaluate(
        "() => { const r = document.getElementById('root');"
        "        window.libliMathReflow(r); const a = r.innerHTML;"
        "        window.libliMathReflow(r);"
        "        return [r.innerHTML === a, a, r.textContent]; }"
    )
    assert out[0], f"pass 2 diverged from pass 1: {out[1]!r}"

    # "All whitespace removed", NOT "normalised". A merge legitimately INTRODUCES
    # characters that were never in textContent -- buildRun's synthetic boundary
    # newlines -- so collapse-runs-to-one-space would redden every merging shape
    # against a correct implementation.
    def squash(s):
        return "".join(s.split())

    _page(page, html)
    before = page.evaluate("() => document.getElementById('root').textContent")
    assert squash(out[2]) == squash(before), "text loss"

    if merge_expected:
        assert out[1] != html, "expected a merge, markup unchanged"
    else:
        # The NEGATIVE half of the normative predicate. Without it the 16 signed x
        # {br, text}-separator cells assert only idempotence and no-text-loss, so a
        # merge that should have been refused goes unnoticed -- and those cells are
        # the only place <p> and ta-right non-merge are pinned at all (Task 3's
        # barriers 4-5 cover div/ta-center only). Measured: exact equality holds for
        # all 16 on the built module, so the assertion is free.
        assert out[1] == html, "expected no merge, markup changed"


@pytest.mark.parametrize(
    "html",
    [
        # The stored shape of CalloutElement 86: a display span split at </p><p>.
        "<p>\\[\\begin{align*}</p><p>a&amp;=b\\\\</p><p>\\end{align*}\\]</p>",
        # The stored shape of the five question stems: \( … \) split at </p><p>,
        # opening with \begin{cases} and nesting \begin{align} inside.
        "<p>\\(\\begin{cases}\\begin{align}</p>"
        "<p>a&amp;=1\\end{align}\\end{cases}\\)</p>",
    ],
)
def test_predecessor_repaired_shapes_still_merge(page, html):
    """Unsigned runs, so this slice must not touch them: the content is hoisted into
    the parent and BOTH <p> elements are removed.

    `"<p>" not in out` is the load-bearing assertion. Asserting only that
    "</p><p>" is gone leaves an inverted reuse gate (`if (!runToken)`) green —
    measured — because the first <p> would survive as a wrapper holding the merged
    text, which contains no </p><p> either."""
    out = _reflow_html(page, html)
    assert "<p>" not in out
    assert "\n" in out
