"""Playwright e2e for the "Fill-in table" self-check element (FillTableElement, plan
Task 9). Drives the REAL student gesture end-to-end — types into the actual answer
input and clicks the actual Check button — never a page.evaluate shortcut into the
grading endpoint or the JS internals (this repo's standing lesson: an e2e that
bypasses the real gesture ships broken UX green).

Covers the behaviour matrix from the task brief:
  1. A seeded table whose single answer cell sits at a NON-(0,0) position (row 1,
     col 1) — proving the 0-based data-r/data-c wiring is not accidentally right
     only for the trivial (0,0) case.
  2. Filling the correct value and clicking Check -> the input gets
     filltable__input--correct, the summary shows the success text/class, and the
     Check button (.filltable__confirm) becomes hidden (lock).
  3. Filling a wrong value and clicking Check -> the input gets
     filltable__input--incorrect, the summary shows the retry text/class, and the
     Check button stays visible (NOT locked).

The table is seeded via the ORM so the grid/answer are deterministic — but the
FILL/CHECK interaction is real browser gestures. Mirrors the login/seed/unit
harness of tests/test_e2e_switchgrid.py. Marked e2e (excluded from the default
run; run focused + foreground with -m e2e or by file)."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element

pytestmark = pytest.mark.e2e

_CORRECT = re.compile(r"\bfilltable__input--correct\b")
_INCORRECT = re.compile(r"\bfilltable__input--incorrect\b")
_SUCCESS = re.compile(r"\bfilltable__summary--success\b")
_RETRY = re.compile(r"\bfilltable__summary--retry\b")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Login / seed helpers (mirrored from tests/test_e2e_switchgrid.py)
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_student(username):
    from tests.factories import make_verified_user

    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _new_unit(username, unit_type="lesson"):
    """An enrolled student + a fresh lesson unit. Returns (student, unit)."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type=unit_type)
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _unit_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


def _seed_filltable(unit):
    """A 2x2 grid whose sole answer cell is at (row 1, col 1) — a deliberately
    NON-(0,0) position, exercising the 0-based data-r/data-c wiring end to end."""
    from courses.models import FillTableElement

    el = FillTableElement(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "czas"},
                    {"kind": "static", "html": "woda"},
                ],
                [
                    {"kind": "static", "html": "0"},
                    {"kind": "answer", "answer": "4"},
                ],
            ]
        }
    )
    el.save()
    add_element(unit, el)
    return el


# Shared locators (scoped to the first fill-table on the page).
def _table(page):
    return page.locator(".filltable").first


def _answer_input(page):
    return _table(page).locator('.filltable__input[data-r="1"][data-c="1"]')


def _confirm(page):
    return _table(page).locator(".filltable__confirm")


def _summary(page):
    return _table(page).locator(".filltable__summary")


# ---------------------------------------------------------------------------
# 1. Correct value -> Check -> success + correct class + lock (Check hidden)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_filltable_correct_value_locks_and_summarizes(page, live_server):
    """Fill the (1,1) answer cell with the correct value, Check, and assert:
    filltable__input--correct on that input, the success summary, and the Check
    button hidden (lock)."""
    _student, unit = _new_unit("ftbl_ok")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_ok")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    expect(inp).to_be_visible()
    expect(_confirm(page)).to_be_visible()
    expect(_summary(page)).to_be_hidden()

    inp.fill("4")
    _confirm(page).click()

    expect(inp).to_have_class(_CORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_SUCCESS)

    # Solved -> Check hidden (lock) and the input disabled.
    expect(_confirm(page)).to_be_hidden()
    expect(inp).to_be_disabled()


# ---------------------------------------------------------------------------
# 2. Wrong value -> Check -> retry summary + incorrect class; NOT locked
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_filltable_wrong_value_retry_not_locked(page, live_server):
    """Fill the (1,1) answer cell with a wrong value, Check, and assert:
    filltable__input--incorrect on that input, the retry summary, and the Check
    button stays visible (NOT locked)."""
    _student, unit = _new_unit("ftbl_bad")
    _seed_filltable(unit)
    _login(page, live_server, "ftbl_bad")
    page.goto(_unit_url(live_server, unit))

    inp = _answer_input(page)
    inp.fill("9")
    _confirm(page).click()

    expect(inp).to_have_class(_INCORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_RETRY)

    # NOT locked: Check still visible, input still enabled/editable.
    expect(_confirm(page)).to_be_visible()
    expect(inp).to_be_enabled()
