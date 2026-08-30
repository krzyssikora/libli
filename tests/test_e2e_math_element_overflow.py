"""A math element must never paint a vertical scrollbar, and must never shave
the formula it typesets.

REPORTED on a real unit: every `.el--math` on the page carried a vertical
scrollbar, and "in some cases a part of the expression is hidden".

ROOT CAUSE, and it is one cause with two symptoms. `.el--math` carries
`overflow-x: auto` so a long-division array can scroll sideways. CSS Overflow 3
§3.3 then computes the OTHER axis' `visible` to `auto`, so the element became a
vertical scroll container as well -- and KaTeX's inline-blocks routinely sit a
couple of pixels outside the block they typeset into (`.vlist` children carry
`position: relative` offsets and negative margins). MEASURED over all 788 stored
MathElement.latex values at the 648px column: 354 of them (44.9%) had
`scrollHeight > clientHeight`, i.e. painted a scrollbar; ink escaped the element
box by up to 1px above and 2px below, and that ink was clipped away.

`overflow-y: hidden` removes the scrollbar; `padding-block: 4px` (2x the
measured worst case) keeps the ink. Both halves are pinned below, each by an
A/B against the SAME element with the rule's own declarations neutralised.
Measuring only the shipped state would prove nothing: a CSS confirmation needs
an A/B, and this file's fixture is chosen so that BOTH legs say something.

FIXTURE, and it is not arbitrary: `\\frac{k}{m}=\\frac{4\\pi^2}{T^2}` is the
shape of one of those 788 stored formulas, picked because it exhibits BOTH
symptoms. MEASURED on the real lesson page, ink rows in the band below:
  overflow: visible, no padding     -> 35 rows, ink reaching 1px ABOVE the box
  the defect, ROLLED BACK by hand   -> 34 rows  <- that row of ink destroyed
  the shipped rule                  -> 35 rows
and, with `padding-block` neutralised, `scrollHeight - clientHeight` is positive
-- the overflow that the defect's computed `overflow-y: auto` painted as the
scrollbar.

Marked e2e (excluded from the default run; use -m e2e)."""

import io
import os

import pytest
from django.urls import reverse
from PIL import Image

from courses.models import MathElement
from tests.factories import add_element
from tests.test_e2e_editor import _login
from tests.test_e2e_editor import _make_pa_user
from tests.test_e2e_editor import _seed_course_and_unit

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

# Both symptoms in one formula; see the module docstring for the measurement.
FIXTURE_LATEX = r"\frac{k}{m}=\frac{4\pi^2}{T^2}"

# Room for the escaping ink (measured at most 1px above and 2px below across all
# 788 stored formulas) and no more: at 12 the crop reached the page chrome below
# the element and counted its rows as ink in both legs.
BAND = 6


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """live_server + the ORM in the test body, under pytest-playwright's session
    loop. Same shape and name as the fixture in test_e2e_math_reflow.py."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _open_lesson(page, live_server, username, slug, latex):
    _make_pa_user(username)
    _login(page, live_server, username)
    unit = _seed_course_and_unit(username, slug=slug)
    add_element(unit, MathElement.objects.create(latex=latex))
    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector(".el--math .katex")
    return unit


def _box(page):
    return page.evaluate(
        """() => {
             const el = document.querySelector('.el--math');
             const r = el.getBoundingClientRect();
             return {x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height};
           }"""
    )


def _ink(page):
    """Ink rows in a band around `.el--math`, and how far they escape its box.

    THE CROP IS RE-DERIVED PER A/B LEG, and must be: neutralising the rule makes
    the element 8px shorter, so everything below it moves UP by 8px. A crop
    frozen in PAGE coordinates then swallows page chrome on one leg only --
    measured 41 rows against 35 that way, a difference six times the defect's.
    Anchored to the element instead, the surrounding gap is `.el`'s own
    `margin: 1rem 0` in both legs, so nothing foreign is ever in range.

    "Ink" is anything that differs from the crop's OWN modal colour, not
    anything below a fixed luminance: the lesson page paints a themed surface,
    not white, and a fixed threshold counted every row of it as ink (measured 74
    rows of a 74px band before this was made relative)."""
    box = _box(page)
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
    # Row BAND of the crop is the element's border-box top.
    return {
        "rows": len(inked),
        "above": BAND - inked[0],
        "below": inked[-1] - (BAND + round(box["h"]) - 1),
    }


def _neutralise(page, declarations):
    """Turn one half of the shipped rule off, in place, for the A/B leg."""
    page.add_style_tag(content=f".el--math{{{declarations}}}")


def test_math_element_is_not_a_vertical_scroll_container(page, live_server):
    """The scrollbar half.

    Two assertions, and the second is what keeps the first from being vacuous:
    `overflow-y: hidden` is only worth pinning because the element DOES overflow
    vertically -- with the rule's own `padding-block` neutralised it overflows by
    5px, which under the defect's computed `auto` is exactly a scrollbar."""
    _open_lesson(page, live_server, "mo_scroll", "mo-scroll", FIXTURE_LATEX)

    assert (
        page.evaluate(
            "() => getComputedStyle(document.querySelector('.el--math')).overflowY"
        )
        == "hidden"
    )

    # A/B: the overflow the browser would have scrolled is real, not hypothetical.
    _neutralise(page, "padding-block:0 !important")
    overflow = page.evaluate(
        """() => {
             const el = document.querySelector('.el--math');
             return el.scrollHeight - el.clientHeight;
           }"""
    )
    assert overflow > 0, overflow


def test_math_element_does_not_clip_the_formula(page, live_server):
    """The clipping half, as an A/B on INK -- box geometry cannot see this, since
    the clipped rows are painted by boxes that lie outside the element either
    way. `overflow: visible` is the reference render; the shipped rule must
    match it row for row."""
    _open_lesson(page, live_server, "mo_clip", "mo-clip", FIXTURE_LATEX)

    shipped = _ink(page)

    _neutralise(page, "overflow:visible !important; padding-block:0 !important")
    reference = _ink(page)

    # Not vacuous: unclipped, this formula's ink really does leave its own box,
    # which is the only reason the clip has anything to destroy.
    assert reference["above"] > 0 or reference["below"] > 0, reference

    assert shipped["rows"] == reference["rows"], (shipped, reference)
