"""e2e for the reported defect. The add test is RED on master by construction:
the ＋ Add pair button has never had a handler.

Harness mirrors tests/test_e2e_switchgate.py — see the plan's Global Constraints."""

import os

import pytest
from playwright.sync_api import expect

from tests.helpers_editor_rows import reopen

pytestmark = pytest.mark.e2e

SAVE = "[data-edit-slot] button[type='submit']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_add_three_pairs_without_saving(page, live_server, open_matchpair_editor_e2e):
    """The whole point: three new pairs in ONE session, no save-and-reopen."""
    el = open_matchpair_editor_e2e(page, live_server, saved_pairs=2)
    add = page.locator("[data-fsrows-add]")
    for _ in range(3):
        add.click()
    rows = page.locator("[data-fsrows-list] [data-fsrow-item]")
    # Assert the count BEFORE filling. Without this, the Step 8 mutant leaves only 4
    # rows and the run dies on `rows.nth(4).fill(...)` with a 30s locator timeout —
    # exactly the failure mode Step 8 tells you to rule out. Here it fails on 7 != 4.
    expect(rows).to_have_count(7)
    # 2 saved + extra=2 blanks + 3 added = 7 rendered rows; fill the last three.
    for i, (left, right) in enumerate([("x", "9"), ("y", "8"), ("z", "7")], start=4):
        rows.nth(i).locator('input[name$="-left"]').fill(left)
        rows.nth(i).locator('input[name$="-right"]').fill(right)
    page.locator(SAVE).click()
    # Wait on the edit slot CLEARING, not on the preview: the element is pre-seeded,
    # so its preview node already exists and waiting on it would return instantly.
    # The slot emptying is what this save actually changes.
    page.locator("[data-edit-slot] form").wait_for(state="detached", timeout=8000)
    reopen(page, el.pk)
    # Exact count, not >= 5: after a correct run the reopened editor shows
    # 5 saved + extra=2 = 7 left-inputs, but >= 5 is ALSO satisfied when only one
    # of the three added pairs persisted (3 saved + 2 extra) — the assertion could
    # not distinguish three from one.
    assert page.locator("[data-fsrows-list] input[name$='-left']").count() == 7
    assert el.content_object.pairs.count() == 5


@pytest.mark.django_db(transaction=True)
def test_remove_a_filled_pair(page, live_server, open_matchpair_editor_e2e):
    el = open_matchpair_editor_e2e(page, live_server, saved_pairs=3)
    # Playwright AUTO-DISMISSES confirm: without this handler the removal takes
    # the cancel path and the test fails against a CORRECT build.
    page.on("dialog", lambda d: d.accept())
    row = page.locator("[data-fsrows-list] [data-fsrow-item]").nth(1)
    row.locator("[data-fsrow-remove]").click()
    # A hidden row is still matched by count() — assert on VISIBILITY, and wait
    # rather than asserting immediately after the click.
    row.wait_for(state="hidden", timeout=4000)
    page.locator(SAVE).click()
    page.locator("[data-edit-slot] form").wait_for(state="detached", timeout=8000)
    reopen(page, el.pk)
    assert page.locator("[data-fsrows-list] input[name$='-left']").count() == 4
