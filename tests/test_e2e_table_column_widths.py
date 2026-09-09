"""Measured browser test: two tables with the SAME first column render it at the
same width.

Reported on the live site (unit "Procent prosty i składany"): two consecutive 2x2
tables, each whose first column reads "Przykład 1" / "Przykład 2", rendered that
column at visibly different widths. Root cause is not a bug in any one table — it
is `.el--table table { width: 100% }` plus Chromium's default auto table layout.
Each table is stretched to the full content column, and the surplus over the
columns' min-content demands is shared out in proportion to how much MORE each
column could still use. A table whose second column is a long sentence gives that
column nearly all the surplus; a table whose second column is two words dumps the
surplus onto column 1 instead. Measured at a 648px content column, before the fix:

    long-neighbour table:   col1 = 114.4px
    short-neighbour table:  col1 = 254.8px

Only a browser can see this. Every source-scanning table test stays green through
the entire failure -- see the CSS-layout precedent in
tests/test_e2e_table_cell_images.py.
"""

import os

import pytest

from courses.models import TableElement
from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

# BOTH markers, module-wide. transaction=True is mandatory, not hygiene: without it
# the live_server thread uses a different connection and cannot see the rows this
# test creates, so the seeded unit and its elements are simply absent.
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PA_USERNAME = "pa-colwidth"

# The reported content, verbatim from the two TableElement rows behind the report.
# The lengths are the whole point: 52 characters against 14 is what moves the
# surplus off column 1 in one table and onto it in the other.
LONG_NEIGHBOUR = "odsetki każdorazowo przelewane na konto pana Michała"
SHORT_NEIGHBOUR = "procent prosty"

# Sub-pixel tolerance. The two first columns hold byte-identical text in the same
# font, so with shrink-to-fit they resolve to the same used width; this absorbs
# nothing but float noise, NOT a real layout difference (the defect is ~140px).
EPS = 0.5


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _unit(username, slug):
    from django.contrib.auth import get_user_model

    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _seed_pair(unit):
    """Attach the reported pair: two 2x2 tables sharing a first column, differing
    only in how much text the second column demands."""
    for neighbour in (LONG_NEIGHBOUR, SHORT_NEIGHBOUR):
        el = TableElement.objects.create(
            data=TableElement.normalize_data(
                {
                    "header_row": False,
                    "header_col": False,
                    "border": "grid",
                    "cells": [
                        [
                            {"html": "Przykład 1", "halign": "left", "valign": "top"},
                            {"html": neighbour, "halign": "left", "valign": "top"},
                        ],
                        [
                            {"html": "Przykład 2", "halign": "left", "valign": "top"},
                            {"html": neighbour, "halign": "left", "valign": "top"},
                        ],
                    ],
                }
            )
        )
        add_element(unit, el)


def _geometry(page):
    """First-column width of each rendered table, plus each table's own width and
    the width of the scroller it sits in.

    Measured on the <td> border box (reset.css sets box-sizing: border-box
    globally) of the first row, which is the cell the report is about.
    """
    page.wait_for_selector(".el--table table")
    return page.evaluate(
        """() => [...document.querySelectorAll('.el--table')].map(el => {
             const td = el.querySelector('tr:first-child td:first-child');
             const scroller = el.querySelector('.el--table__scroll');
             return {
               col1: td.getBoundingClientRect().width,
               table: el.querySelector('table').getBoundingClientRect().width,
               scroll: scroller.getBoundingClientRect().width,
             };
           })"""
    )


def test_same_first_column_renders_at_the_same_width(page, live_server):
    """The report itself: identical first columns, identical rendered width."""
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "colwidth-same")
    _seed_pair(unit)

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    boxes = _geometry(page)

    assert len(boxes) == 2, f"expected both tables to render, got {len(boxes)}"
    long_col1, short_col1 = boxes[0]["col1"], boxes[1]["col1"]
    assert abs(long_col1 - short_col1) < EPS, (
        f"first column differs between the two tables: {long_col1:.1f}px next to a "
        f"long neighbour vs {short_col1:.1f}px next to a short one"
    )


def test_a_narrow_table_is_not_stretched_to_the_content_column(page, live_server):
    """Pin the MECHANISM, not just the symptom.

    Equal first columns is also what `table-layout: fixed` would produce (it splits
    the stretched width evenly), and that fix is ruled out elsewhere -- it flattens
    the Large and Full cell-image presets down to Medium. So assert the property
    that only shrink-to-fit gives: a table whose content does not fill the content
    column stops at its content instead of being stretched to 100% of it.

    Asserted on the SHORT table only. The long one legitimately reaches (or exceeds)
    the scroller width on a narrow viewport, so the same assertion there would be a
    viewport-width coin flip.
    """
    _make_pa_user(PA_USERNAME)
    unit = _unit(PA_USERNAME, "colwidth-shrink")
    _seed_pair(unit)

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    short = _geometry(page)[1]

    assert short["table"] < short["scroll"] - EPS, (
        f"short table is stretched: {short['table']:.1f}px in a "
        f"{short['scroll']:.1f}px scroller"
    )
