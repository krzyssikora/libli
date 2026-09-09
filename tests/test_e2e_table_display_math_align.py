"""Display maths in a table cell must honour the cell's horizontal alignment.

`\\[…\\]` typesets into KaTeX's `.katex-display` wrapper, whose vendored
`text-align: center` (set at TWO levels) outranks the `.ta-*` class the cell
carries. The visible symptom, reported on a real unit: an author right-aligns a
split-formula cell so `\\[y=\\frac{3}{2}(x+3)(x\\]` hugs the answer input beside
it, and the student sees it centred instead.

MEASURED, with the courses.css override commented out, all three alignments
rendered IDENTICALLY (gap_left == gap_right == 45.4px) -- i.e. halign had no
effect whatever on display maths, not merely the wrong effect.

Measurement note: `.katex` is NOT a usable probe. Inside a `.katex-display`
wrapper the vendor sets it `display: block`, so its box fills the cell at every
alignment. The probe is the union of the `.katex-html > .base` runs -- the
shrink-to-fit inline-blocks of glyphs (KaTeX emits several per formula, breaking
at relations, so the FIRST one alone is also not a valid probe).

Marked e2e (excluded from the default run; use -m e2e)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e


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


def _new_unit(username):
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
    return student, unit


def _unit_url(live_server, unit):
    return f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"


def _slack(page, root_selector, row):
    """(gap_left, gap_right) between the cell's content box and the maths runs."""
    cell = page.locator(f"{root_selector} tr:nth-child({row}) td").first
    return cell.evaluate(
        """(td) => {
            const runs = [...td.querySelectorAll('.katex-html > .base')]
                .map(n => n.getBoundingClientRect());
            if (!runs.length) throw new Error('no .base runs -- maths did not typeset');
            const cb = td.getBoundingClientRect();
            const cs = getComputedStyle(td);
            const left = cb.left + parseFloat(cs.paddingLeft);
            const right = cb.right - parseFloat(cs.paddingRight);
            return {
                gap_left: Math.min(...runs.map(r => r.left)) - left,
                gap_right: right - Math.max(...runs.map(r => r.right)),
            };
        }"""
    )


# A narrow formula in a cell widened by its neighbour, so every alignment has
# room to move. Row order below is (right, left, center).
_FORMULA = r"\[y=2(x\]"
_WIDE = "wide filler text that widens the other column"


def _assert_alignments(page, root_selector):
    right = _slack(page, root_selector, 1)
    left = _slack(page, root_selector, 2)
    center = _slack(page, root_selector, 3)
    assert right["gap_right"] < right["gap_left"], f"ta-right not honoured: {right}"
    assert left["gap_left"] < left["gap_right"], f"ta-left not honoured: {left}"
    # Centring must SURVIVE the override (it is the vendor default and the most
    # common authored value): the two gaps stay within a pixel of each other.
    assert abs(center["gap_left"] - center["gap_right"]) < 1.0, (
        f"ta-center stopped centring: {center}"
    )


@pytest.mark.django_db(transaction=True)
def test_filltable_display_math_honours_cell_halign(page, live_server):
    from courses.models import FillTableElement

    _student, unit = _new_unit("ftbl_dmath_align")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": _FORMULA, "halign": "right"},
                    {"kind": "answer", "answer": "1"},
                ],
                [
                    {"kind": "static", "html": _FORMULA, "halign": "left"},
                    {"kind": "static", "html": _WIDE},
                ],
                [
                    {"kind": "static", "html": _FORMULA, "halign": "center"},
                    {"kind": "static", "html": ""},
                ],
            ]
        }
    )
    el.save()
    add_element(unit, el)
    _login(page, live_server, "ftbl_dmath_align")
    page.goto(_unit_url(live_server, unit))
    page.wait_for_selector(".filltable .katex-html > .base")
    _assert_alignments(page, ".el--filltable")


@pytest.mark.django_db(transaction=True)
def test_table_display_math_honours_cell_halign(page, live_server):
    """The plain table element shares the `.ta-*` classes and the same defect --
    math.js typesets `.el--table` with the SAME `\\[` -> display:true mapping."""
    from courses.models import TableElement

    _student, unit = _new_unit("tbl_dmath_align")
    el = TableElement(
        data={
            "cells": [
                [{"html": _FORMULA, "halign": "right"}, {"html": "x"}],
                [{"html": _FORMULA, "halign": "left"}, {"html": _WIDE}],
                [{"html": _FORMULA, "halign": "center"}, {"html": ""}],
            ]
        }
    )
    el.save()
    add_element(unit, el)
    _login(page, live_server, "tbl_dmath_align")
    page.goto(_unit_url(live_server, unit))
    page.wait_for_selector(".el--table .katex-html > .base")
    _assert_alignments(page, ".el--table")
