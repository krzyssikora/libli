"""Playwright e2e for the "Switch grid" self-check element (SwitchGridElement, plan
Task 10). Drives the REAL student gesture end-to-end — clicks the inline cyclers to
change the visible option and clicks the actual Check button — never a page.evaluate
shortcut into the grading endpoint or the JS internals (this repo's standing lesson: an
e2e that bypasses the real gesture ships broken UX green).

Covers the behaviour matrix from the task brief:
  1. A seeded grid whose correct options are reachable by cycling; open the lesson page.
  2. Clicking a cycler cycles its visible option; after enough clicks the correct
     option shows.
  3. Check -> per-cycler feedback classes (switchgrid--correct / switchgrid--incorrect)
     appear and the summary shows.
  4. A fully-correct grid -> success summary + cyclers locked (switchgrid--locked) +
     Check hidden (and a locked cycler no longer cycles).
  5. An incorrect grid -> "try again" (retry) summary AND cyclers stay interactive (NOT
     locked); re-cycling clears the stale feedback class; a corrected re-Check succeeds.

The grid is seeded via the ORM (a fixture-style helper) so the option lists + answer
indices are deterministic — but the CYCLE/CHECK interaction is real browser clicks.
Mirrors the login/seed/unit harness of tests/test_e2e_switchgate.py. Marked e2e
(excluded from the default run; run focused + foreground with -m e2e or by file)."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

_CORRECT = re.compile(r"\bswitchgrid--correct\b")
_INCORRECT = re.compile(r"\bswitchgrid--incorrect\b")
_LOCKED = re.compile(r"\bswitchgrid--locked\b")
_SUCCESS = re.compile(r"\bswitchgrid--success\b")
_RETRY = re.compile(r"\bswitchgrid--retry\b")


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Login / seed helpers (mirrored from tests/test_e2e_switchgate.py)
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_student(username):
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

    name = "courses:quiz_unit" if unit.unit_type == "quiz" else "courses:lesson_unit"
    path = reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})
    return f"{live_server.url}{path}"


def _switchgrid(prompt, lines):
    """Build a SwitchGridElement from author `{{choice}}` markup, as the form's
    clean()/save() would: parse each line's stem to its sentinel token-stem via
    parse_stem_multi (the raw sentinel is NEVER pasted here — file tools corrupt it).

    `lines` is a list of (author_stem, [(options, answer), ...]) where the k-th
    `{{choice}}` in the stem pairs with the k-th cycler tuple. Options are sanitised
    in the model's save()."""
    from courses import switchgrid
    from courses.models import SwitchGridElement

    built = []
    for stem, cyclers in lines:
        token_stem, _n = switchgrid.parse_stem_multi(stem)
        built.append(
            {
                "stem": token_stem,
                "cyclers": [
                    {"options": list(opts), "answer": ans} for opts, ans in cyclers
                ],
            }
        )
    return SwitchGridElement.objects.create(prompt=prompt, lines=built)


# Shared locators (scoped to the first grid on the page).
def _grid(page):
    return page.locator(".switchgrid").first


def _cycler(page, i):
    return _grid(page).locator("[data-switchgrid-cycler]").nth(i)


def _confirm(page):
    return _grid(page).locator(".switchgrid__confirm")


def _summary(page):
    return _grid(page).locator("[data-switchgrid-summary]")


def _option(cycler, i):
    return cycler.locator(".switchgrid__option").nth(i)


# The seeded grid used by both tests: ONE line, TWO cyclers.
#   cycler 0: options [A, B, C], answer index 2  (reach by 2 clicks from the default)
#   cycler 1: options [X, Y],    answer index 1  (reach by 1 click from the default)
def _seed_two_cycler_grid(unit):
    add_element(
        unit,
        _switchgrid(
            "Set both:",
            [
                (
                    "First {{choice}} then {{choice}}",
                    [(["A", "B", "C"], 2), (["X", "Y"], 1)],
                )
            ],
        ),
    )


# ---------------------------------------------------------------------------
# 1. Cycle to the correct options -> Check -> success + per-cycler green + lock
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_switchgrid_correct_path_locks_and_summarizes(page, live_server):
    """Cycle both cyclers to their correct option, Check, and assert: per-cycler
    switchgrid--correct feedback, the success summary, cyclers locked, Check hidden,
    and that a locked cycler no longer cycles."""
    _student, unit = _new_unit("sgrid_ok")
    _seed_two_cycler_grid(unit)
    _login(page, live_server, "sgrid_ok")
    page.goto(_unit_url(live_server, unit))

    c0, c1 = _cycler(page, 0), _cycler(page, 1)
    # At rest: option 0 of each cycler is the visible one, others hidden.
    expect(_option(c0, 0)).to_be_visible()
    expect(_option(c0, 2)).to_be_hidden()
    expect(_confirm(page)).to_be_visible()
    expect(_summary(page)).to_be_hidden()

    # Cycle cycler 0 to index 2 ("C"): two clicks (0 -> 1 -> 2).
    c0.click()
    expect(_option(c0, 1)).to_be_visible()
    c0.click()
    expect(_option(c0, 2)).to_be_visible()
    expect(_option(c0, 0)).to_be_hidden()

    # Cycle cycler 1 to index 1 ("Y"): one click.
    c1.click()
    expect(_option(c1, 1)).to_be_visible()

    _confirm(page).click()

    # Per-cycler green feedback + success summary.
    expect(c0).to_have_class(_CORRECT)
    expect(c1).to_have_class(_CORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_SUCCESS)

    # Solved -> both cyclers locked and Check hidden.
    expect(c0).to_have_class(_LOCKED)
    expect(c1).to_have_class(_LOCKED)
    expect(_confirm(page)).to_be_hidden()

    # A locked cycler no longer cycles (advance() bails on the locked class).
    c0.click()
    expect(_option(c0, 2)).to_be_visible()


# ---------------------------------------------------------------------------
# 2. Incorrect -> retry summary + mixed feedback + still interactive; then recover
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_switchgrid_incorrect_retry_then_recover(page, live_server):
    """One cycler right, one wrong -> Check shows the retry summary with mixed
    per-cycler feedback (green + red), cyclers stay UNLOCKED and Check stays live.
    Re-cycling the wrong cycler clears its stale red class; correcting it and
    re-Checking then succeeds and locks."""
    _student, unit = _new_unit("sgrid_bad")
    _seed_two_cycler_grid(unit)
    _login(page, live_server, "sgrid_bad")
    page.goto(_unit_url(live_server, unit))

    c0, c1 = _cycler(page, 0), _cycler(page, 1)

    # cycler 0 -> correct ("C", index 2); cycler 1 left at index 0 ("X") = WRONG.
    c0.click()
    c0.click()
    expect(_option(c0, 2)).to_be_visible()
    expect(_option(c1, 0)).to_be_visible()

    _confirm(page).click()

    # Mixed feedback: cycler 0 green, cycler 1 red; retry summary; NOT locked.
    expect(c0).to_have_class(_CORRECT)
    expect(c1).to_have_class(_INCORRECT)
    expect(_summary(page)).to_be_visible()
    expect(_summary(page)).to_have_class(_RETRY)
    expect(c0).not_to_have_class(_LOCKED)
    expect(c1).not_to_have_class(_LOCKED)
    expect(_confirm(page)).to_be_visible()

    # Re-cycle the wrong cycler -> its stale red class clears + advances to "Y".
    c1.click()
    expect(c1).not_to_have_class(_INCORRECT)
    expect(_option(c1, 1)).to_be_visible()

    # Re-Check now that both are correct -> success + lock.
    _confirm(page).click()
    expect(c0).to_have_class(_CORRECT)
    expect(c1).to_have_class(_CORRECT)
    expect(_summary(page)).to_have_class(_SUCCESS)
    expect(c0).to_have_class(_LOCKED)
    expect(c1).to_have_class(_LOCKED)
    expect(_confirm(page)).to_be_hidden()
