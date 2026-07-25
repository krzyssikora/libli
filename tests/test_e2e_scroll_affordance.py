"""Playwright e2e: horizontally scrollable boxes signal that there is more sideways.

A clipped table gave no hint that content continued past its edge. The scrollbar
cannot carry that signal — this app runs under overlay scrollbars, which paint
nothing when idle and reserve no layout space (measured: offsetHeight ==
clientHeight on a scrolling box). So .scroll-x shades the edge that has content
beyond it, driven by scroll_affordance.js toggling is-scroll-start/is-scroll-end.

Assertions are on the toggled state and on real computed opacity, never on a
screenshot, so a silently dead listener fails the run.
"""

import os

import pytest

from tests.test_e2e_wide_content_scroll import _login
from tests.test_e2e_wide_content_scroll import _seed_wide_unit

pytestmark = pytest.mark.e2e

PHONE = {"width": 390, "height": 800}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


STATE = """
(sel) => {
  const wrap = document.querySelector(sel);
  const box = wrap.firstElementChild;
  const after = getComputedStyle(wrap, '::after').opacity;
  const before = getComputedStyle(wrap, '::before').opacity;
  return {
    start: wrap.classList.contains('is-scroll-start'),
    end: wrap.classList.contains('is-scroll-end'),
    before_opacity: Number(before),
    after_opacity: Number(after),
    scrollable: box.scrollWidth > box.clientWidth,
    max: box.scrollWidth - box.clientWidth,
  };
}
"""


# The gradients fade over .15s; sample only once that has settled, or a reading
# lands mid-transition (0.85 rather than 1) and the test is flaky by construction.
SETTLE_MS = 400


def _scroll_to(page, sel, x):
    page.evaluate(
        "([sel, x]) => {"
        " document.querySelector(sel).firstElementChild.scrollLeft = x; }",
        [sel, x],
    )
    page.wait_for_timeout(SETTLE_MS)


def _narrow_table_unit(username, slug):
    """A unit whose table comfortably fits — the negative case."""
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import TableElement
    from tests.factories import TEST_PASSWORD
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_verified_user

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    cells = [
        [{"html": f"r{r}c{c}", "halign": "left", "valign": "top"} for c in range(2)]
        for r in range(2)
    ]
    Element.objects.create(
        unit=unit,
        content_object=TableElement.objects.create(
            data={"cells": cells, "border": "grid"}
        ),
    )
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_edge_shading_tracks_scroll_position(page, live_server):
    """At rest only the trailing edge is lit; scrolled fully right, only the
    leading one; in between, both."""
    course, unit = _seed_wide_unit("aff_state", "aff-state")
    _login(page, live_server, "aff_state")
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".scroll-x")
    page.wait_for_timeout(SETTLE_MS)

    sel = ".el--multigrid .scroll-x"
    at_start = page.evaluate(STATE, sel)
    assert at_start["scrollable"], "seed is not wide enough to exercise the affordance"

    # At rest: content only to the RIGHT.
    assert at_start["end"] and not at_start["start"], at_start
    assert at_start["after_opacity"] == 1 and at_start["before_opacity"] == 0, at_start

    # Fully right: content only to the LEFT.
    _scroll_to(page, sel, at_start["max"])
    at_end = page.evaluate(STATE, sel)
    assert at_end["start"] and not at_end["end"], at_end
    assert at_end["before_opacity"] == 1 and at_end["after_opacity"] == 0, at_end

    # Midway: both edges have content beyond them.
    _scroll_to(page, sel, at_start["max"] // 2)
    mid = page.evaluate(STATE, sel)
    assert mid["start"] and mid["end"], mid
    assert mid["before_opacity"] == 1 and mid["after_opacity"] == 1, mid


@pytest.mark.django_db(transaction=True)
def test_a_box_that_fits_is_never_shaded(page, live_server):
    """The affordance must claim scrollability only when it exists.

    Uses a genuinely narrow 2-column table rather than a wide viewport: the lesson
    column is capped at 46rem, so widening the window never makes the seeded grid fit.
    """
    course, unit = _narrow_table_unit("aff_fits", "aff-fits")
    _login(page, live_server, "aff_fits")
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".scroll-x")
    page.wait_for_timeout(SETTLE_MS)

    state = page.evaluate(STATE, ".el--table .scroll-x")
    assert not state["scrollable"], "the 2-column table should fit; widen the column"
    assert not state["start"] and not state["end"], state
    assert state["before_opacity"] == 0 and state["after_opacity"] == 0, state


@pytest.mark.django_db(transaction=True)
def test_shading_never_intercepts_clicks(page, live_server):
    """pointer-events must stay off: the gradients sit over real controls."""
    course, unit = _seed_wide_unit("aff_click", "aff-click")
    _login(page, live_server, "aff_click")
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".scroll-x")
    page.wait_for_timeout(SETTLE_MS)

    for pseudo in ("::before", "::after"):
        pe = page.evaluate(
            "(p) => getComputedStyle("
            " document.querySelector('.scroll-x'), p).pointerEvents",
            pseudo,
        )
        assert pe == "none", f"{pseudo} would swallow clicks (pointer-events: {pe})"

    # Drive a real checkbox under the lit trailing edge.
    box = page.locator(".multigrid tbody input[type='checkbox']").first
    box.check()
    assert box.is_checked()


@pytest.mark.django_db(transaction=True)
def test_table_element_also_gets_the_affordance(page, live_server):
    """Not just the grids — the plain table element shares the wrapper."""
    course, unit = _seed_wide_unit("aff_table", "aff-table")
    _login(page, live_server, "aff_table")
    page.set_viewport_size(PHONE)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".el--table .scroll-x")
    page.wait_for_timeout(SETTLE_MS)

    state = page.evaluate(STATE, ".el--table .scroll-x")
    assert state["scrollable"]
    assert state["end"] and state["after_opacity"] == 1, state
