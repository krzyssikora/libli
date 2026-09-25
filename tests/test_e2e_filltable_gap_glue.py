r"""An inline box keeps its unit on the same line in a squeezed fill-in table.

Reported on a phone: cells typed "{{20}} \(\pi\)" and "{{75}}°" rendered the π
and the ° on the line BELOW the box. Auto table layout shrinks a squeezed column
to its min-content width, and a line may break on either side of an inline-block
input, so the column's min-content is just the box. filltable.glue_gaps wraps each
box with its neighbouring word in a `white-space: nowrap` span.

The probe is geometric: the unit's ink must sit beside the box (its vertical
centre inside the box's top..bottom) AND to its right. On the broken build the
unit's top is at or below the box's bottom.

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

S = "￿"
# The reported table's shape: long-ish Polish headers, four columns, every data
# cell a box followed by its unit -- typed WITH a space, as the author does.
_HEAD = ["pole koła", "obwód koła", "kąt środkowy", "pole wycinka"]
_UNITS = [r" \(\pi\)", r" \(\pi\)", "°", r" \(\pi\)"]


def _cells():
    head = [{"kind": "static", "html": h, "halign": "center"} for h in _HEAD]
    rows = [
        [
            {
                "kind": "static",
                "html": f"{S}0{S}{u}",
                "gaps": [[str(10 * r + c + 1)]],
                "halign": "center",
            }
            for c, u in enumerate(_UNITS)
        ]
        for r in range(2)
    ]
    return [head, *rows]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username):
    from courses.models import FillTableElement
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
    obj = FillTableElement(data={"cells": _cells(), "header_row": True})
    obj.save()
    add_element(unit, obj)
    return unit


@pytest.mark.django_db(transaction=True)
def test_unit_stays_beside_its_box_on_a_phone(page, live_server):
    unit = _seed("ftglue_phone")
    page.set_viewport_size({"width": 390, "height": 844})
    _login(page, live_server, "ftglue_phone")
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".el--filltable .filltable__input--inline")
    page.wait_for_function(
        "document.querySelectorAll('.el--filltable .katex').length === 6"
    )

    probes = page.evaluate(
        """() => [...document.querySelectorAll('.filltable__input--inline')].map(i => {
             // The unit's ink: the KaTeX box if the cell has one, else the text
             // after the input (the degree sign).
             const td = i.closest('td');
             const k = td.querySelector('.katex');
             let u;
             if (k) { u = k.getBoundingClientRect(); }
             else {
               const r = document.createRange();
               r.setStartAfter(i);
               r.setEndAfter(td.lastChild);
               u = r.getBoundingClientRect();
             }
             const b = i.getBoundingClientRect();
             const mid = (u.top + u.bottom) / 2;
             return {
               cell: i.dataset.r + ',' + i.dataset.c,
               beside: mid > b.top && mid < b.bottom && u.left >= b.right - 1,
               box: [b.left, b.top, b.right, b.bottom].map(Math.round),
               unit: [u.left, u.top, u.right, u.bottom].map(Math.round),
             };
           })"""
    )
    assert len(probes) == 8, probes
    stranded = [p for p in probes if not p["beside"]]
    assert not stranded, f"unit wrapped away from its box: {stranded}"

    # The fix costs width, never the page: the table scrolls in its own scroller.
    page_scroll = page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert page_scroll
