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


@pytest.mark.xfail(reason="merge lands in Task 4", strict=True)
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
