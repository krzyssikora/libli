"""Display maths typed as `\\[…\\]` into PROSE must be reachable, the way a math
element's is.

THE DEFECT. KaTeX's vendored `katex.min.css` sets `.katex-display > .katex
{ white-space: nowrap }`, so display maths can never wrap. The horizontal
scroller that rescues a too-wide formula lives on `.el--math` ALONE
(courses.css), so a `\\[…\\]` typed into a text element, a callout body or a
question stem gets display mode's nowrap with none of the scrolling: it simply
runs off the page with no way to reach it. It is the one combination with no
escape hatch.

SIZED against the local `mat-pp`: 1,551 such blocks in 1,192 text elements over
323 units, plus 123 more objects (callout bodies, choice/short-numeric/gate
stems, a figcaption) that could never become math elements at all -- there is no
join row to repoint. MEASURED, ink extent against the column: 7 blocks overflow
the 648px desktop column (worst by 438px), 80 at 390px, 236 at 280px. Zero put
ink LEFT of the column at any of the three widths, which is what makes a
right-only scroller a complete fix here -- centred content in an LTR scroller
otherwise parks ink at a negative offset `scrollLeft` can never reach.

THE FIX is `.katex-display` becoming its own scroller, with three surfaces
opting out because each already solves this its own way: `.el--math` (the
scroller is on the element), `.el--table` and `.el--filltable` (their own
`.scroll-x` + inner-scroller shape, measured separately).

Every assertion below is an A/B against the SAME element with the rule's own
declarations neutralised. Measuring only the shipped state would prove nothing:
each of the four declarations is pinned by the leg that shows what it prevents.

Marked e2e (excluded from the default run; use -m e2e)."""

import io
import os

import pytest
from django.urls import reverse
from PIL import Image

from courses.models import TextElement
from tests.factories import add_element
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

# The real worst offender in the corpus (unit 487), trimmed to three of its six
# products: 438px past the 648px column as stored, and still far past it here.
# A row of relations, so KaTeX emits several `.base` runs -- the union of those
# is the ink probe, since `.katex` inside a display wrapper is `display: block`
# and its box is the column width whatever the formula does.
WIDE_BODY = (
    r"<p>\[\frac{x+2}{x-3}-\frac{x^2-4}{x}=0,\quad\quad"
    r"\frac{3x^5+x+2}{x^4-1}=\frac{-2x^2-x-1}{x^4+2x^2+1},\quad\quad"
    r"\frac{4x^2+4}{x^2-x+3}-2x=\frac{1}{2-x}\]</p>"
)

# Narrow enough to fit the column, so the vertical legs below isolate the
# vertical axis. Same formula the math-element file uses, and for the same
# reason: its ink leaves its own box top and bottom, so a clip has something to
# destroy. See tests/test_e2e_math_element_overflow.py.
TALL_BODY = r"<p>\[\frac{k}{m}=\frac{4\pi^2}{T^2}\]</p>"

DISP = ".el--text .katex-display"

# Room for the escaping ink and no more; see the math-element file's note.
BAND = 6


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """live_server + the ORM in the test body, under pytest-playwright's session
    loop. Same shape and name as the fixture in test_e2e_math_reflow.py."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open_lesson(page, live_server, username, slug, body):
    _make_pa_user(username)
    _login(page, live_server, username)
    unit = _seed_course_and_unit(username, slug=slug)
    add_element(unit, TextElement.objects.create(body=body))
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(f"{DISP} .katex-html > .base")
    return unit


def _neutralise(page, declarations, selector=DISP):
    """Turn part of the shipped rule off, in place, for the A/B leg."""
    page.add_style_tag(content=f"{selector}{{{declarations}}}")


def _computed(page, prop, selector=DISP):
    return page.evaluate(
        "([sel, prop]) => getComputedStyle(document.querySelector(sel))[prop]",
        [selector, prop],
    )


def _ink(page):
    """Ink rows in a band around the display wrapper, and how far they escape it.

    THE CROP IS RE-DERIVED PER A/B LEG -- neutralising `padding-block` makes the
    wrapper shorter, so a crop frozen in page coordinates would swallow page
    chrome on one leg only. "Ink" is anything that differs from the crop's OWN
    modal colour: the lesson page paints a themed surface, not white, so a fixed
    luminance threshold counts every row of the background as ink. Both notes
    are the math-element file's, learned there."""
    box = page.evaluate(
        """(sel) => {
             const r = document.querySelector(sel).getBoundingClientRect();
             return {x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height};
           }""",
        DISP,
    )
    crop = {
        "x": box["x"],
        "y": box["y"] - BAND,
        "width": box["w"],
        "height": box["h"] + 2 * BAND,
    }
    img = Image.open(io.BytesIO(page.screenshot(full_page=True, clip=crop))).convert(
        "L"
    )
    w, h = img.size
    px = img.tobytes()  # one byte per pixel for an "L" image, row-major
    background = max(set(px), key=px.count)
    inked = [
        y
        for y in range(h)
        if any(abs(v - background) > 24 for v in px[y * w : (y + 1) * w])
    ]
    assert inked, "no ink in the crop -- the formula did not typeset"
    # Row BAND of the crop is the wrapper's border-box top.
    return {
        "rows": len(inked),
        "above": BAND - inked[0],
        "below": inked[-1] - (BAND + round(box["h"]) - 1),
    }


def test_prose_display_math_scrolls_to_reach_the_formula(page, live_server):
    """The headline behaviour: a formula wider than the column can be scrolled to.

    `scrollWidth > clientWidth` is NOT the probe -- Chromium reports that for a
    plain overflowing block too, so it says the same thing on the broken build.
    What separates them is whether `scrollLeft` MOVES, and whether moving it
    brings the far end of the ink inside the box."""
    _open_lesson(page, live_server, "pdm_scroll", "pdm-scroll", WIDE_BODY)

    before = page.evaluate(
        """(sel) => {
             const el = document.querySelector(sel);
             const runs = [...el.querySelectorAll('.katex-html > .base')]
                 .map(n => n.getBoundingClientRect());
             const cs = getComputedStyle(el);
             const r = el.getBoundingClientRect();
             return {
               right: r.right - parseFloat(cs.paddingRight)
                              - parseFloat(cs.borderRightWidth),
               inkRight: Math.max(...runs.map(n => n.right)),
             };
           }""",
        DISP,
    )
    # Not vacuous: the formula really does run past the column, so there IS
    # something out there for the scroller to reach.
    assert before["inkRight"] - before["right"] > 1, before

    after = page.evaluate(
        """(sel) => {
             const el = document.querySelector(sel);
             el.scrollLeft = el.scrollWidth;
             const runs = [...el.querySelectorAll('.katex-html > .base')]
                 .map(n => n.getBoundingClientRect());
             const cs = getComputedStyle(el);
             const r = el.getBoundingClientRect();
             return {
               scrollLeft: el.scrollLeft,
               right: r.right - parseFloat(cs.paddingRight)
                              - parseFloat(cs.borderRightWidth),
               inkRight: Math.max(...runs.map(n => n.right)),
             };
           }""",
        DISP,
    )
    assert after["scrollLeft"] > 0, "the wrapper did not scroll at all"
    assert after["inkRight"] - after["right"] <= 1, after


def test_prose_display_math_is_not_a_vertical_scroll_container(page, live_server):
    """CSS Overflow 3 §3.3: with one axis not `visible`, a `visible` value on the
    OTHER computes to `auto`. So `overflow-x: auto` alone silently makes every
    formula a VERTICAL scroll container too -- the exact defect the math element
    shipped with, on 44.9% of its corpus.

    The second assertion keeps the first from being vacuous: the wrapper really
    does overflow vertically once the rule's own padding is taken away."""
    _open_lesson(page, live_server, "pdm_vert", "pdm-vert", TALL_BODY)

    assert _computed(page, "overflowY") == "hidden"

    _neutralise(page, "padding-block:0 !important")
    overflow = page.evaluate(
        "(sel) => { const e = document.querySelector(sel);"
        " return e.scrollHeight - e.clientHeight; }",
        DISP,
    )
    assert overflow > 0, overflow


def test_prose_display_math_does_not_clip_the_formula(page, live_server):
    """The clipping half, as an A/B on INK. Box geometry cannot see this: the
    clipped rows are painted by boxes that lie outside the wrapper either way.
    `overflow: visible` is the reference render, and the shipped rule must match
    it row for row."""
    _open_lesson(page, live_server, "pdm_clip", "pdm-clip", TALL_BODY)

    shipped = _ink(page)

    _neutralise(page, "overflow:visible !important; padding-block:0 !important")
    reference = _ink(page)

    # Not vacuous: unclipped, this formula's ink really does leave its own box.
    assert reference["above"] > 0 or reference["below"] > 0, reference

    assert shipped["rows"] == reference["rows"], (shipped, reference)


def test_prose_display_math_does_not_widen_the_page(page, live_server):
    """A formula wider than a phone viewport must not drag the whole lesson
    sideways -- every other block on the page slides with it, into empty space.

    This one was ALREADY BROKEN before the scroller existed: measured 746px of
    scrollWidth against a 390px client. The A/B leg reproduces that on demand, so
    the assertion above is anchored to a defect this fixture really does provoke.

    ⚠️ An earlier draft neutralised `position` here instead, on the fill-in
    table's precedent -- there, the abs-pos `.katex-mathml` took a positioned
    ancestor OUTSIDE the scroller as its containing block and escaped. That leg
    measured 390/390: `.katex-mathml` is a clipped 1x1px box whose static
    position is the formula's LEFT edge, so it never escapes here, and
    `position: relative` was deleted from the rule rather than shipped unearned.
    Do not reintroduce either."""
    page.set_viewport_size({"width": 390, "height": 800})
    _open_lesson(page, live_server, "pdm_page", "pdm-page", WIDE_BODY)

    def page_width():
        return page.evaluate(
            "() => ({scroll: document.documentElement.scrollWidth,"
            " client: document.documentElement.clientWidth})"
        )

    shipped = page_width()
    assert shipped["scroll"] == shipped["client"], shipped

    # BOTH axes, and that is not belt-and-braces: `overflow-x: visible` alone
    # computes straight back to `auto` while `overflow-y: hidden` still stands
    # (CSS Overflow 3 §3.3 -- the same rule the fix leans on). Measured: that leg
    # reported 390/390, i.e. it neutralised nothing at all.
    _neutralise(page, "overflow:visible !important")
    reference = page_width()
    assert reference["scroll"] > reference["client"], reference


@pytest.mark.parametrize(
    "surface,selector",
    [
        # The scroller is on the ELEMENT here; a second one on the wrapper inside
        # it would be a scroller within a scroller, and `.el--math`'s geometry was
        # measured over all 788 stored formulas exactly as it ships.
        ("math", ".el--math .katex-display"),
        # Table cells carry their own `.scroll-x` + inner-scroller shape and their
        # own display-maths alignment override; both were measured separately.
        ("table", ".el--table .katex-display"),
        # The fill-in table is a THIRD selector in that opt-out block, not a
        # synonym for the one above -- without its own leg, deleting just that
        # line of the rule would go unnoticed by the whole suite.
        ("filltable", ".el--filltable .katex-display"),
    ],
)
def test_surfaces_that_solve_this_their_own_way_opt_out(
    page, live_server, surface, selector
):
    """A drift guard. Without the opt-out these two silently acquire a nested
    scroller, and nothing else in the suite would say so."""
    from courses.models import FillTableElement
    from courses.models import MathElement
    from courses.models import TableElement

    username = f"pdm_optout_{surface}"
    _make_pa_user(username)
    _login(page, live_server, username)
    unit = _seed_course_and_unit(username, slug=f"pdm-optout-{surface}")
    if surface == "math":
        add_element(unit, MathElement.objects.create(latex=r"\frac{k}{m}"))
    elif surface == "table":
        el = TableElement(data={"cells": [[{"html": r"\[\frac{k}{m}\]"}]]})
        el.save()
        add_element(unit, el)
    else:
        # A `static` cell: an `answer` cell holds an input, not typeset maths.
        el = FillTableElement(
            data={"cells": [[{"kind": "static", "html": r"\[\frac{k}{m}\]"}]]}
        )
        el.save()
        add_element(unit, el)
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(f"{selector} .katex-html > .base")

    assert _computed(page, "overflowX", selector) == "visible"
    assert _computed(page, "paddingBlockStart", selector) == "0px"
