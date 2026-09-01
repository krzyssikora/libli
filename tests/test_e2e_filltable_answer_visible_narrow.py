r"""A squeezed fill-in table must still SHOW its answers.

app.css's `input[type=text], …` rule gives `.filltable__input` `width: 100%`
(deliberately -- the answer input fills its cell), and in auto table layout a
PERCENTAGE width contributes NOTHING to a column's intrinsic width: the answer
column's entire width demand is the control's own padding + border, while every
static cell demands its text. So all of the squeeze -- a phone, the pinned TOC
narrowing the content column, or simply a table with many columns -- lands on
the answer columns first, and they are the cells the student needs to read.

Reported on unit 459 (15 columns, three answer cells): the answers were
invisible on a phone AND on the desktop with the course tree shown. MEASURED on
that table, with the min-width floor removed, the input's CONTENT box is:

    1280px viewport ->  3px, 3px, 0px      390px viewport ->  3px, 3px, 0px

i.e. the value is in the DOM, correct, and 0 pixels wide. With the floor:
35-41px, every value fully visible at both widths. The excess table width lands
in the element's own `overflow-x` scroller, which is what it is for -- the page
itself does not grow.

The state under test is the `mine.done` RESTORE path (seeded UnitProgress), the
one in the report: the canonical answers come back readonly, and they were the
answers nobody could read.

The probe is `scrollWidth <= clientWidth` on the input -- "the whole value fits
inside the box the student sees". A box measurement alone would pass on the
broken build (the box is placed correctly, it is just empty), and an ink probe
would too: at 0px of content there is no ink to find, so an ink test would have
to assert absence, which any empty input satisfies.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

# Unit 459's shape: one long row of static numbers with a few answer cells
# among them. The answers are the lengths that actually occur in the content
# (1-4 characters covers 96% of every answer cell in the corpus).
_ANSWERS = {2: "3", 9: "21", 12: "273", 14: "1170"}
_CELLS = [
    [
        (
            {"kind": "answer", "answer": _ANSWERS[i], "halign": "center"}
            if i in _ANSWERS
            else {"kind": "static", "html": str(100 + 37 * i), "halign": "center"}
        )
        for i in range(15)
    ]
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


def _seed_done_filltable(username):
    """A student who has finished a wide fill-in table -- the restore path."""
    from courses.models import FillTableElement
    from courses.models import UnitProgress
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    EnrollmentFactory(student=student, course=course)
    obj = FillTableElement(data={"cells": _CELLS})
    obj.save()
    row = add_element(unit, obj)
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"done": True}}
    )
    return unit


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("width", [1280, 390])
def test_restored_answers_are_readable_in_a_squeezed_table(page, live_server, width):
    unit = _seed_done_filltable(f"ftbl_narrow_{width}")
    # Set the viewport BEFORE the load: a phone never resizes into this.
    page.set_viewport_size({"width": width, "height": 844})
    _login(page, live_server, f"ftbl_narrow_{width}")
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".el--filltable .filltable__input")

    boxes = page.evaluate(
        """() => [...document.querySelectorAll('.filltable__input')].map(i => {
             const cs = getComputedStyle(i);
             return {
               value: i.value,
               content: i.clientWidth
                 - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
               fits: i.scrollWidth <= i.clientWidth,
             };
           })"""
    )
    assert [b["value"] for b in boxes] == list(_ANSWERS.values()), boxes
    clipped = [b for b in boxes if not b["fits"]]
    assert not clipped, (
        f"answer clipped at {width}px: {clipped} (all: {boxes}) -- the answer "
        "column collapsed to its padding"
    )

    # The table may scroll sideways inside its own scroller; the PAGE may not
    # grow because of it.
    scroller = page.evaluate(
        """() => {
             const sc = document.querySelector('.el--filltable__scroll');
             return {client: sc.clientWidth, scroll: sc.scrollWidth};
           }"""
    )
    assert scroller["scroll"] >= scroller["client"], scroller
