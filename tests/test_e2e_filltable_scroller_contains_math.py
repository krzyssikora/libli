r"""A wide fill-in table must scroll INSIDE its scroller, not drag the page.

`.el--filltable__scroll` clips a too-wide table with `overflow-x: auto` -- but
overflow clipping does NOT apply to an absolutely positioned descendant whose
containing block lies OUTSIDE the scroller, and the scroller is
`position: static`, so it is nobody's containing block. KaTeX renders a hidden
MathML copy of every formula into `.katex-mathml`, which its own stylesheet
declares `position: absolute` -- so those boxes take `.scroll-x` (the
`position: relative` edge-shading wrapper, one level UP) as their containing
block, sit unclipped at their static position out at the table's full width,
and extend the PAGE's scrollable area to reach them.

MEASURED on unit 459's table (15 columns, every static cell a `\(number\)`) at a
390px viewport: `documentElement.scrollWidth` is 795px against a 390px client --
the whole lesson slides ~400px sideways, past the end of every other block, into
empty space. Deleting the `.katex-mathml` nodes at runtime takes it straight
back to 390. So does one declaration: make the scroller its own containing
block. A/B, same page, same load: 390/795 -> 390/390.

A table of PLAIN cells never showed this -- no math, no absolutely positioned
descendant -- which is why a wide table has looked contained until now.

The second assertion is the point of the first: the table must still overflow
its scroller. A "fix" that stopped the drag by making the table narrower (or by
hiding it) would satisfy the page assertion alone.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

# Unit 459's shape: math in every static cell is what makes the difference.
_CELLS = [
    [
        {"kind": "static", "html": rf"\({100 + 37 * i}\)", "halign": "center"}
        for i in range(15)
    ],
    [
        (
            {"kind": "answer", "answer": "273", "halign": "center"}
            if i == 6
            else {"kind": "static", "html": rf"\({200 + 41 * i}\)", "halign": "center"}
        )
        for i in range(15)
    ],
]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_wide_math_table_does_not_widen_the_page(page, live_server):
    from courses.models import FillTableElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    student = make_verified_user(
        username="ftbl_drag", email="ftbl_drag@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(student=student, course=course)
    obj = FillTableElement(data={"cells": _CELLS})
    obj.save()
    add_element(unit, obj)

    page.set_viewport_size({"width": 390, "height": 844})
    _login(page, live_server, "ftbl_drag")
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".el--filltable .katex")

    m = page.evaluate(
        """() => {
             const de = document.documentElement;
             const sc = document.querySelector('.el--filltable__scroll');
             return {
               pageClient: de.clientWidth, pageScroll: de.scrollWidth,
               scrollerClient: sc.clientWidth, scrollerScroll: sc.scrollWidth,
             };
           }"""
    )
    assert m["scrollerScroll"] > m["scrollerClient"], (
        f"the table no longer overflows its scroller ({m}) -- this test proves "
        "nothing unless it does"
    )
    assert m["pageScroll"] <= m["pageClient"] + 1, (
        f"the page scrolls sideways by {m['pageScroll'] - m['pageClient']}px ({m}) "
        "-- the table's overflow escaped its scroller"
    )
