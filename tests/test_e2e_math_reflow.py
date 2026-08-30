"""End-to-end coverage for display-math authoring through REAL pages: a real PA
session, the real editor RTE (real keystrokes, real Enter-splits-into-<div>), a
real save round trip, and the real lesson page with katex.min.js +
auto-render.min.js + math_reflow.js + math.js wired exactly as the five
templates ship them.

`tests/test_e2e_math_reflow_dom.py` already proves the module's DOM mechanics in
isolation (170 cases). What that harness cannot see is wiring: does the script
actually load on the real page, in the real order, ahead of the real callers, and
does the real RTE actually produce the split shape the whole feature exists to
repair. That is this file's job, and only this file's.

Fixture shapes are pinned to what tests/test_e2e_editor.py and
tests/test_e2e_text_colour.py already established (confirmed by reading them
before writing this file), not invented:
  - _make_pa_user / _login / _seed_course_and_unit / _editor_url / _add_element
    (tests/test_e2e_editor.py)
  - tests.factories.add_element / TEST_PASSWORD / CourseFactory / ContentNodeFactory
"""

import os

import pytest
from django.urls import reverse

from courses.models import CalloutElement
from courses.models import Element
from courses.models import MathElement
from courses.models import TableElement
from courses.models import TabsElement
from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _add_element
from tests.test_e2e_editor import _editor_url
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

# MANDATORY. The MARKER selects, not the filename: without pytest.mark.e2e these
# tests land in the DEFAULT non-e2e run (pyproject.toml's addopts = "-q -m 'not
# e2e'") and break Task 10 Step 1's count. Without django_db(transaction=True)
# they fail for want of DB access, since every case uses live_server + the ORM.
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """ALSO MANDATORY, and needed MORE here than in the DOM file, because every
    case below uses live_server and the ORM in the test body itself.
    tests/conftest.py's autouse _enable_db_access(db) hits the ORM at setup while
    pytest-playwright's session loop is already running, so without this every
    test here errors with SynchronousOnlyOperation when the file is run alone.
    Same shape and name as the fixture in test_e2e_text_colour.py and
    test_e2e_math_reflow_dom.py."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _lesson_url(live_server, unit):
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _open_pa_session(page, live_server, username, slug):
    """Create + log in a Platform Admin, seed a PA-owned course+lesson unit, and
    return the unit. Thin wrapper over the three confirmed test_e2e_editor
    helpers, used by every case below."""
    _make_pa_user(username)
    _login(page, live_server, username)
    return _seed_course_and_unit(username, slug=slug)


BLOCK = (
    "\\[\\begin{align*}\n"
    "a^n\\cdot a^k&=a^{n+k}\\\\\n"
    "a^n: a^k&=a^{n-k}\\\\\n"
    "\\left(a^n\\right)^k&=a^{nk}\n"
    "\\end{align*}\\]"
)


# ---- Step 1: golden path -----------------------------------------------------


def test_multiline_align_block_authored_in_the_rte_renders(page, live_server):
    """Paste-equivalent gesture (one Enter per line, the real RTE surface) ->
    save -> open the lesson -> one .katex, three aligned rows, no error."""
    unit = _open_pa_session(page, live_server, "mr_golden", "mr-golden")

    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "text")

    surface = page.locator("[data-edit-slot] .rte-surface")
    surface.wait_for(state="visible")
    surface.click()
    lines = BLOCK.split("\n")
    for i, line in enumerate(lines):
        page.keyboard.type(line)
        if i < len(lines) - 1:
            page.keyboard.press("Enter")  # no trailing Enter

    page.locator("[data-edit-slot] button[type='submit']").click()
    # Child-scoped: _element_row.html renders the slot div unconditionally, so
    # the slot itself survives the save and only the form inside it detaches.
    page.wait_for_selector(
        "[data-edit-slot] form[data-op='element-save']", state="detached"
    )

    # THE SPLIT ASSERTION. Without this the test can pass vacuously: a paste
    # gesture (not exercised here, but a future refactor of this test could
    # switch to one) can land the whole block in a single text node, in which
    # case the render assertions below are green on master with none of this
    # work, and stay green if phase 1 regresses.
    stored = TextElement.objects.order_by("-id").first().body
    open_at, close_at = stored.index("\\["), stored.index("\\]")
    between = stored[open_at:close_at]
    assert any(b in between for b in ("</div><div>", "</p><p>", "<br>")), (
        "the authoring gesture did not split the span; this test would prove "
        f"nothing. Fix the gesture, do not relax the assertion. stored={stored!r}"
    )

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--text .katex")
    assert page.locator(".el--text .katex").count() == 1
    assert page.locator(".katex-error").count() == 0
    assert page.locator(".el--text .katex .vlist").count() >= 3


# ---- Step 2: the remaining cases ---------------------------------------------


def test_multiline_align_block_in_a_callout_body_renders(page, live_server):
    """2a: the same block, seeded straight into a CalloutElement body, split one
    line per <p> -- the ACTUAL stored shape of the one real CalloutElement in the
    corpus (spec: "the callout span is \\[-wrapped (\\[\\begin{align*}</p><p>...").
    MEASURED: seeding `body=BLOCK` verbatim (raw \\n, no tags) is a single intact
    text node that auto-render already parses correctly with the module disabled
    -- that fixture would be vacuous. Splitting per <p> is what actually exercises
    phase 1's merge."""
    unit = _open_pa_session(page, live_server, "mr_callout", "mr-callout")
    body = "".join(f"<p>{line}</p>" for line in BLOCK.split("\n"))
    callout = CalloutElement.objects.create(kind="note", body=body)
    add_element(unit, callout)

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".callout__body .katex")
    assert page.locator(".callout__body .katex").count() == 1
    assert page.locator(".katex-error").count() == 0


def test_table_cell_math_with_escaped_br_renders(page, live_server):
    """2b: the shape sanitize_cell actually stores for a cell authored with a
    literal <br> inside a math span -- reinstated as escaped text, per
    courses/sanitize.py's _canon_math. Phase 1b converts it back to a real
    newline before KaTeX ever sees it."""
    unit = _open_pa_session(page, live_server, "mr_table", "mr-table")
    table = TableElement.objects.create(
        data={
            "cells": [
                [{"html": "\\[a&lt;br&gt;b\\]", "halign": "left", "valign": "top"}]
            ]
        }
    )
    add_element(unit, table)
    # Pin the stored shape the test claims to seed, per courses/sanitize.py's
    # stash/unstash round trip -- fail loudly here, not on a mystery katex-error.
    assert table.data["cells"][0][0]["html"] == "\\[a&lt;br&gt;b\\]", table.data

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--table .katex")
    assert page.locator(".el--table .katex").count() == 1
    assert "<br>" not in page.locator(".el--table").inner_text()


def test_math_element_with_display_wrapper_renders(page, live_server):
    """3a: a Math element whose `latex` carries the \\[...\\] wrapper renders
    instead of erroring -- pins Hook B stripping the wrapper before katex.render
    ever sees a bare \\[ control sequence."""
    unit = _open_pa_session(page, live_server, "mr_math_disp", "mr-math-disp")
    math_el = MathElement.objects.create(
        latex="\\[\\begin{align*}a&=b\\\\c&=d\\end{align*}\\]"
    )
    add_element(unit, math_el)

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--math .katex")
    assert page.locator(".el--math .katex").count() == 1
    assert page.locator(".katex-error").count() == 0


def test_math_element_with_inline_wrapper_still_renders_display(page, live_server):
    """3b: a Math element carrying \\(x\\) renders as display -- NOT a
    contradiction of Hook B. displayMode comes from math.js:6's hardcoded
    displayMode: true, not from the stripped delimiter, so a Math element is
    always a display element regardless of which wrapper the author typed."""
    unit = _open_pa_session(page, live_server, "mr_math_inline", "mr-math-inline")
    math_el = MathElement.objects.create(latex="\\(x\\)")
    add_element(unit, math_el)

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--math .katex")
    assert page.locator(".el--math .katex").count() == 1
    assert page.locator(".el--math .katex-display").count() == 1


def test_split_inline_align_promotes_and_renders(page, live_server):
    """4: \\(\\begin{align*}...\\)  renders as display -- phase 2's own
    regression coverage, through a text element."""
    unit = _open_pa_session(page, live_server, "mr_promote", "mr-promote")
    text_el = TextElement.objects.create(
        body="<p>\\(\\begin{align*}a&=b\\\\c&=d\\end{align*}\\)</p>"
    )
    add_element(unit, text_el)

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--text .katex")
    assert page.locator(".el--text .katex").count() == 1
    assert page.locator(".katex-error").count() == 0
    assert page.locator(".el--text .katex-display").count() == 1


def test_two_adjacent_display_spans_in_a_math_element_are_left_alone(page, live_server):
    """5: \\[a\\] + \\[b\\] in a Math element is refused by the ported closer
    search (it stops at the FIRST \\], which is not the expression's end), so
    KaTeX rejects the literal \\[ control sequence -- today's behaviour, which
    must not change."""
    unit = _open_pa_session(page, live_server, "mr_refuse", "mr-refuse")
    math_el = MathElement.objects.create(latex="\\[a\\] + \\[b\\]")
    add_element(unit, math_el)

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--math .katex-error")
    assert page.locator(".el--math .katex-error").count() == 1


def test_row_spacing_macro_inside_a_display_block_reflows(page, live_server):
    """6: a display block containing \\\\[2ex] (LaTeX row-spacing) reflows and
    strips correctly -- pins the ported findEndOfMath (a backslash skips the
    next character, so the second backslash of \\\\ is consumed and the
    following literal [2ex] is never mistaken for a delimiter), not a parity
    rule of our own."""
    unit = _open_pa_session(page, live_server, "mr_rowspace", "mr-rowspace")
    math_el = MathElement.objects.create(
        latex="\\[\\begin{matrix}a & b \\\\[2ex] c & d\\end{matrix}\\]"
    )
    add_element(unit, math_el)

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--math .katex")
    assert page.locator(".el--math .katex").count() == 1
    assert page.locator(".katex-error").count() == 0


def test_single_line_inline_and_display_math_render_unchanged(page, live_server):
    """7: regression. A single-line \\(x^2\\) and a single-line \\[y\\], each
    already intact in one text node, must render identically before and after
    this module ships -- an intact span is never entered by rule 4."""
    unit = _open_pa_session(page, live_server, "mr_regress", "mr-regress")
    add_element(unit, TextElement.objects.create(body="<p>\\(x^2\\)</p>"))
    add_element(unit, TextElement.objects.create(body="<p>\\[y\\]</p>"))

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--text .katex")
    assert page.locator(".el--text .katex").count() == 2
    assert page.locator(".katex-error").count() == 0
    assert page.locator(".el--text .katex-display").count() == 1


def test_katex_stays_idempotent_across_nested_tabs_and_text_selectors(
    page, live_server
):
    """8: idempotence on a real re-rendering surface. math.js's inline-math
    selector list ('.el--text, .el--table, ..., .el--tabs, ...') NESTS: a
    TabsElement panel holding a TextElement matches BOTH '.el--tabs' and
    '.el--text', so renderMathInElement runs a second time over the same
    subtree within one page load (spec's Cost section). '.katex' sits in
    IGNORE_SELECTOR, so the second pass must be a no-op. Switching tabs (a real
    reveal gesture) must not change the count either."""
    unit = _open_pa_session(page, live_server, "mr_idem", "mr-idem")

    tabs_obj = TabsElement.objects.create(data=TabsElement.default_data())
    tabs_join = add_element(unit, tabs_obj)
    first_tab_id = tabs_obj.data["tabs"][0]["id"]
    text_el = TextElement.objects.create(body="<p>\\(x^2\\)</p>")
    Element.objects.create(
        unit=unit, parent=tabs_join, tab_id=first_tab_id, content_object=text_el
    )

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--tabs .katex")
    assert page.locator(".el--tabs .katex").count() == 1

    # Reveal gesture: switch away and back. Content is typeset once at load
    # regardless of which panel is visible, so the count must not move.
    tabs = page.locator(".tabs__strip .tabs__tab")
    tabs.nth(1).click()
    tabs.nth(0).click()
    assert page.locator(".el--tabs .katex").count() == 1


# ---- Step 3: centred display math ---------------------------------------------


def test_centred_display_math_is_reflowed(page, live_server):
    """The limitation PR #206 pinned deliberately, now closed. Every line div carries
    class="ta-center", so each was a barrier and the formula never reflowed; sibling
    blocks sharing an align token now merge into one wrapper that keeps the class."""
    unit = _open_pa_session(page, live_server, "mr_centred", "mr-centred")
    body = (
        '<div class="ta-center">\\[\\begin{align*}</div>'
        '<div class="ta-center">a&amp;=b\\\\</div>'
        '<div class="ta-center">\\end{align*}\\]</div>'
    )
    add_element(unit, TextElement.objects.create(body=body))

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--text")
    assert page.locator(".el--text .katex").count() == 1
    assert page.locator(".katex-error").count() == 0
    html = page.locator(".el--text").inner_html()
    assert 'class="ta-center"' in html  # the alignment survived the merge
    assert "</div><div" not in html  # and the three lines became one block


# ---- Step 4: the long-division highlight -------------------------------------


def test_marked_array_cell_renders_highlighted(page, live_server):
    """The whole \\htmlClass chain on the REAL render path, in one assertion set.

    Three independent things must hold for `.el--math .mk-amber` to exist and be
    painted: math.js's `trust` option must admit `\\htmlClass{mk mk-amber}` (both
    the command AND the class value), KaTeX must put the class on a node it
    builds, and courses.css must define the rule. Each is source-guarded in
    tests/test_long_division_render_static.py; this is the test that makes those
    guards redundant rather than load-bearing.

    Dropping the trust option is NOT a silent no-op: KaTeX routes an untrusted
    command to `formatUnsupportedCmd`, which drops the argument and renders the
    command NAME in `errorColor` -- the digit vanishes behind a red \\htmlClass.
    """
    unit = _open_pa_session(page, live_server, "mr_mark", "mr-mark")
    add_element(
        unit,
        MathElement.objects.create(
            latex="\\begin{array}{r}\\htmlClass{mk mk-amber}{2}\\end{array}"
        ),
    )

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--math .katex")
    mark = page.locator(".el--math .mk-amber")
    assert mark.count() == 1
    assert mark.first.inner_text().strip() == "2"

    painted = page.evaluate(
        "() => getComputedStyle(document.querySelector('.el--math .mk-amber'))"
        ".backgroundColor"
    )
    assert painted not in ("transparent", "rgba(0, 0, 0, 0)"), painted


def test_math_element_adds_no_block_space_around_the_formula(page, live_server):
    """`.el--math { overflow-x: auto }` makes the element a block formatting
    context root, so KaTeX's `.katex-display { margin: 1em 0 }` stops collapsing
    out through it -- for EVERY math element in the app, not just the 71.

    A/B MEASURED at 1280px on a math-heavy lesson (overflow-x: auto against
    overflow-x: visible, same page, same render): 60.78px of whitespace above and
    below each formula against 44.78px, and 76.78px against 44.78px between two
    adjacent math elements; the page grew 96px over three math elements.
    `.el--math > .katex-display { margin-block: 0 }` restores the old layout
    exactly (re-measured: byte-identical geometry to the overflow-x: visible
    run). This pins that restoration -- without it each offset below is one 1em
    margin instead of the padding.

    The offsets are measured against `.el--math`'s own `padding-block`, not
    against zero: the rule deliberately carries 4px a side so that KaTeX's ink,
    which escapes the block by up to 2px, survives the clip that `overflow-x`
    forces on both axes (see the rule's note in courses.css). A 1em margin is
    16px, four times the padding, so the assertion still fails loudly if the
    `margin-block: 0` is dropped.
    """
    unit = _open_pa_session(page, live_server, "mr_space", "mr-space")
    add_element(unit, MathElement.objects.create(latex="a^2+b^2=c^2"))

    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector(".el--math .katex")
    offsets = page.evaluate(
        """() => {
             const el = document.querySelector('.el--math');
             const d = el.querySelector('.katex-display');
             const a = el.getBoundingClientRect(), b = d.getBoundingClientRect();
             const cs = getComputedStyle(el);
             return { top: b.top - a.top - parseFloat(cs.paddingTop),
                      bottom: a.bottom - b.bottom - parseFloat(cs.paddingBottom) };
           }"""
    )
    assert abs(offsets["top"]) < 1, offsets
    assert abs(offsets["bottom"]) < 1, offsets
