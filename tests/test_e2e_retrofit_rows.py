"""No-regression e2e for the stepper/checklist retrofit onto formset_rows.js.

The ADD half is GREEN on master AND after the retrofit — that is the whole point:
it is what proves rewiring two WORKING editors onto the shared module did not
break them. The REMOVE half is a normal RED-first test: master renders no per-row
remove button at all, only a DELETE checkbox.

Harness mirrors tests/test_e2e_switchgate.py — see the plan's Global Constraints.
"""

import os

import pytest

from tests.helpers_editor_rows import reopen

pytestmark = pytest.mark.e2e  # NOT [django_db, e2e] — django_db goes per-test

SAVE = "[data-edit-slot] button[type='submit']"
ROWS = {"stepper": ".stepper-rows li", "markdone": ".markdone-rows li"}


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _values(page, kind):
    """Playwright has NO get_by_display_value (that is a Testing Library API — the
    real roster is get_by_alt_text/label/placeholder/role/test_id/text/title). Read
    input_value() off the located rows instead: for JS-filled fields the `value`
    PROPERTY is what changed, while the `value` ATTRIBUTE selector would still match
    the server-rendered original."""
    inputs = page.locator(f'{ROWS[kind]} input[type="text"]')
    return [inputs.nth(i).input_value() for i in range(inputs.count())]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "kind,label", [("stepper", "Add step"), ("markdone", "Add item")]
)
def test_add_row_still_works_after_retrofit(
    page, live_server, open_element_editor, kind, label
):
    """GREEN on master AND after: proves the rewiring did not break a working editor.

    EVERY selector here must survive the retrofit, not just the button. The button is
    found by visible label because data-stepper-add-row becomes data-fsrows-add; the
    row list is found by its CLASS (.stepper-rows / .markdone-rows, unchanged by this
    change) because data-stepper-rows becomes data-fsrows-list. Selecting the list by
    the NEW hook would make this red on master, and the no-regression guarantee — the
    riskiest part of this change — would not actually be established."""
    el = open_element_editor(page, live_server, kind)
    page.get_by_role("button", name=label).click()
    rows = page.locator(ROWS[kind])
    rows.last.locator('input[type="text"]').fill("retrofit row")
    page.locator(SAVE).click()
    page.locator("[data-edit-slot] form").wait_for(state="detached", timeout=8000)
    reopen(page, el.pk, ready=ROWS[kind])
    assert "retrofit row" in _values(page, kind)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", ["stepper", "markdone"])
def test_remove_row_after_retrofit(page, live_server, open_element_editor, kind):
    """RED on master: there is no per-row remove BUTTON there, only a checkbox."""
    el = open_element_editor(page, live_server, kind, rows=["one", "two", "three"])
    page.on("dialog", lambda d: d.accept())  # persisted rows are non-blank
    row = page.locator(ROWS[kind]).nth(1)
    row.locator("[data-fsrow-remove]").click()
    row.wait_for(state="hidden", timeout=4000)
    page.locator(SAVE).click()
    page.locator("[data-edit-slot] form").wait_for(state="detached", timeout=8000)
    reopen(page, el.pk, ready=ROWS[kind])
    assert "two" not in _values(page, kind)
