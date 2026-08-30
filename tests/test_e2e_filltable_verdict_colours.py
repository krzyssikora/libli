r"""After a Check, a correct answer cell must not look like an incorrect one.

`.filltable__input--correct` / `--incorrect` are (0,1,0) and LOSE to app.css's
`input[type=text], … { background: var(--surface-sunken); border: 1px solid
var(--border-strong) }`, which is (0,1,1) -- an attribute selector PLUS a type
selector. Source order cannot help: specificity is compared first. So the
green/red verdict paint never happened and the two verdicts rendered
IDENTICALLY; only the summary line and the read-only lock distinguished them.

MEASURED before the fix, on a real Check: correct AND incorrect both computed
background rgb(250, 248, 243) (#FAF8F3 = --surface-sunken) and border-colour
rgb(214, 207, 193) (#D6CFC1 = --border-strong).

The assertions are TOKEN-RELATIVE (a probe element painted with each token in
the live page), not hard-coded hexes, so a re-cut of the colour ramp cannot make
this test lie -- but they still pin the exact token each state must resolve to,
which a bare "correct != incorrect" would not: app.css's own values differ per
state for no reason a reader could rely on.

The sibling family is NOT affected and is the model this should have followed:
`[data-fillgate] .question__blank-input.is-correct` is (0,3,0).

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


def _token(page, name):
    """The rgb() a `var(--name)` actually paints in THIS page's live theme."""
    return page.evaluate(
        """(name) => {
            const probe = document.createElement('div');
            probe.style.color = `var(${name})`;
            document.body.appendChild(probe);
            const v = getComputedStyle(probe).color;
            probe.remove();
            return v;
        }""",
        name,
    )


def _paint(page, row):
    inp = page.locator(f".el--filltable tr:nth-child({row}) .filltable__input")
    return inp.evaluate(
        """(el) => {
            const cs = getComputedStyle(el);
            return {bg: cs.backgroundColor, border: cs.borderTopColor};
        }"""
    )


@pytest.mark.django_db(transaction=True)
def test_check_paints_the_correct_and_incorrect_verdicts(page, live_server):
    from courses.models import FillTableElement

    _student, unit = _new_unit("ftbl_verdict")
    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "right"},
                    {"kind": "answer", "answer": "42"},
                ],
                [
                    {"kind": "static", "html": "wrong"},
                    {"kind": "answer", "answer": "42"},
                ],
            ]
        }
    )
    el.save()
    add_element(unit, el)
    _login(page, live_server, "ftbl_verdict")
    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/")
    page.wait_for_selector(".el--filltable .filltable__input")

    page.locator(".el--filltable tr:nth-child(1) .filltable__input").fill("42")
    page.locator(".el--filltable tr:nth-child(2) .filltable__input").fill("nope")
    page.locator(".filltable__confirm").click()
    page.wait_for_selector(".filltable__input--incorrect")

    correct = _paint(page, 1)
    incorrect = _paint(page, 2)

    assert correct["bg"] == _token(page, "--success-subtle"), correct
    assert correct["border"] == _token(page, "--success"), correct
    assert incorrect["bg"] == _token(page, "--danger-subtle"), incorrect
    assert incorrect["border"] == _token(page, "--danger"), incorrect
    # The symptom in one line: the two verdicts must not be the same picture.
    assert correct != incorrect
