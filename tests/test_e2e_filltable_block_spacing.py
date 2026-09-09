"""Measured browser test: a fill-in table does not collide with the block below it.

Reported from prod (unit "Procent prosty"): the fill-in table's Check button sat
flush against the "wskazówki i odpowiedzi" spoiler pill directly beneath it, with
the two appearing to overlap.

The cause is a CSS comment in courses.css that closed early -- it described the
fill-in table as a twin of `.el--table` and wrote the shared alignment class
stems as a glob pair, putting a comment terminator inside the prose. The parser
then read the remaining prose as a selector up to the next `{` and discarded that
rule whole, so `.filltable { margin: var(--space-4) 0; }` never applied and the
widget had NO vertical margins.

That alone would only have closed the gap to zero. What made it a collision is
the notes rail: `.block-notes` carries a deliberate `margin-top: -1rem` so an
empty aside costs no flow row, which ASSUMES each block's content ends with a
1rem bottom margin collapsing out to the section. With `.filltable`'s margin
discarded that assumption failed, the section measured 16px SHORTER than its own
content, and the next block's 16px `margin-top` cancelled exactly against the
deficit. Measured before the fix: gap 0.0px, section short by 16px.

Only a browser can see this. The rule is present in the stylesheet SOURCE, so
every source-scanning test stays green -- it is absent only from the parsed
CSSOM. tests/test_css_comments_are_terminated_once.py guards the cause; this
guards the consequence.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

PA_USERNAME = "pa-ftspacing"

# The block rhythm every element carries (`--space-4`). The fill-in table is
# entitled to the same separation from its neighbour as any other block.
BLOCK_RHYTHM = 16.0
# Generous floor rather than an equality: what the report is about is a
# COLLISION, and pinning 16.0 exactly would also fail if the rhythm token were
# deliberately retuned. Anything at or below this is the defect returning.
MIN_GAP = 12.0


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


def _seed(username, slug):
    """The reported shape: a fill-in table, then a spoiler."""
    from django.contrib.auth import get_user_model

    from courses.models import FillTableElement
    from courses.models import SpoilerElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )

    table = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "kapitał"},
                    {"kind": "answer", "answer": "1000"},
                ],
                [
                    {"kind": "static", "html": "odsetki"},
                    {"kind": "answer", "answer": "50"},
                ],
            ]
        }
    )
    table.save()
    add_element(unit, table)

    spoiler = SpoilerElement(label="wskazówki i odpowiedzi")
    spoiler.save()
    add_element(unit, spoiler)
    join = unit.elements.order_by("-order").first()

    body = TextElement(body="<p>odpowiedź</p>")
    body.save()
    add_element(unit, body)
    child = unit.elements.order_by("-order").first()
    child.parent = join
    child.tab_id = "only"
    child.save()

    return unit


def _lesson_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _geometry(page):
    page.wait_for_selector(".filltable__confirm")
    return page.evaluate(
        """() => {
             const btn = document.querySelector('.filltable__confirm');
             const tog = document.querySelector('.spoiler__toggle');
             const sec = btn.closest('.lesson-block');
             const body = sec.querySelector('.lesson-block__body');
             const b = btn.getBoundingClientRect();
             return {
               gap: tog.getBoundingClientRect().top - b.bottom,
               section_short_by: body.getBoundingClientRect().bottom
                                 - sec.getBoundingClientRect().bottom,
               filltable_margin_bottom:
                 getComputedStyle(document.querySelector('.filltable')).marginBottom,
             };
           }"""
    )


def test_check_button_does_not_collide_with_the_next_block(page, live_server):
    """The report itself, measured on the two boxes that touched."""
    _make_pa_user(PA_USERNAME)
    unit = _seed(PA_USERNAME, "ftspacing-gap")

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    geo = _geometry(page)

    assert geo["gap"] >= MIN_GAP, (
        f"Check button sits {geo['gap']:.1f}px from the spoiler below it "
        f"(want >= {MIN_GAP}); .filltable margin-bottom is "
        f"{geo['filltable_margin_bottom']}"
    )


def test_the_filltable_block_is_as_tall_as_its_own_content(page, live_server):
    """Pin the MECHANISM, not just the symptom.

    A gap can be restored by padding the neighbour, which would leave the section
    still under-reporting its height -- and the notes rail positions the notes
    handle against that same section box, so a short section is wrong
    independently of what sits beneath it. Assert the section actually contains
    its content.
    """
    _make_pa_user(PA_USERNAME)
    unit = _seed(PA_USERNAME, "ftspacing-height")

    _login(page, live_server, PA_USERNAME)
    page.goto(_lesson_url(live_server, unit))
    geo = _geometry(page)

    assert geo["section_short_by"] <= 0.5, (
        f".lesson-block is {geo['section_short_by']:.1f}px shorter than its own "
        f".lesson-block__body -- the Check button overflows the section"
    )
    assert geo["filltable_margin_bottom"] == f"{int(BLOCK_RHYTHM)}px", (
        f".filltable margin-bottom is {geo['filltable_margin_bottom']}, so its "
        f"rule is not reaching the CSSOM"
    )
