"""e2e for the Choose & confirm (switchgate) option list — module 2's behaviour.

Switchgate is NOT a formset: options are repeated name="option" inputs read
positionally and the correct answer is a radio whose value is the option's INDEX,
so a removed row must be DETACHED and every survivor renumbered.

Harness mirrors tests/test_e2e_switchgate.py — see the plan's Global Constraints.
"""

import os

import pytest

pytestmark = pytest.mark.e2e

SAVE = "[data-edit-slot] button[type='submit']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_add_option_beyond_the_padded_blanks(page, live_server, open_switchgate_editor):
    open_switchgate_editor(page, live_server, options=["two", "three", "four"])
    before = page.locator("[data-sgate-row]").count()
    page.locator("[data-sgate-add]").click()
    assert page.locator("[data-sgate-row]").count() == before + 1


@pytest.mark.django_db(transaction=True)
def test_removing_a_middle_option_keeps_the_right_answer(
    page, live_server, open_switchgate_editor
):
    """The renumbering test: if the radio values are not rewritten, `answer` points
    at the wrong option and the question silently marks the wrong choice correct."""
    el = open_switchgate_editor(
        page, live_server, options=["alpha", "beta", "gamma"], answer=2
    )
    page.on("dialog", lambda d: d.accept())  # filled row -> confirm fires
    page.locator("[data-sgate-row]").nth(1).locator("[data-sgate-remove]").click()
    # Pin the renumbering IN THE DOM, before saving. Without this the Step 7 mutant
    # is caught only indirectly: an un-renumbered radio still reads value="2" while
    # the option list shrinks to two, so clean() adds "Select the correct option.",
    # the save 422s, the slot is re-rendered instead of cleared, and the test dies on
    # an 8s detach timeout that proves nothing about renumbering.
    assert (
        page.locator("[data-sgate-row]")
        .nth(1)
        .locator('input[name="answer"]')
        .get_attribute("value")
        == "1"
    )
    page.locator(SAVE).click()
    page.locator("[data-edit-slot] form").wait_for(state="detached", timeout=8000)
    obj = el.content_object
    obj.refresh_from_db()
    assert obj.options[obj.answer] == "gamma"


@pytest.mark.django_db(transaction=True)
def test_removing_an_interior_blank_lets_the_save_succeed(
    page, live_server, open_switchgate_editor
):
    """Today this is a dead end: clean() rejects interior blanks and there is no
    remove control, so an author who fills rows 1, 2 and 6 cannot save at all."""
    open_switchgate_editor(page, live_server, options=[])
    rows = page.locator("[data-sgate-row]")
    rows.nth(0).locator('input[name="option"]').fill("first")
    rows.nth(1).locator('input[name="option"]').fill("second")
    rows.nth(5).locator('input[name="option"]').fill("sixth")
    rows.nth(0).locator('input[name="answer"]').check()
    # Blank rows are removed WITHOUT a confirm — no dialog handler on purpose.
    # Descending order: each removal renumbers, so ascending indices would shift.
    for i in (4, 3, 2):
        rows.nth(i).locator("[data-sgate-remove]").click()
    page.locator(SAVE).click()
    page.locator("[data-edit-slot] form").wait_for(state="detached", timeout=8000)
    assert page.locator("text=Options cannot be empty").count() == 0
