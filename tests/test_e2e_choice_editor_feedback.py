import os

import pytest

from tests.test_e2e_questions import _add_element
from tests.test_e2e_questions import _editor_url
from tests.test_e2e_questions import _login
from tests.test_e2e_questions import _make_pa_user
from tests.test_e2e_questions import _seed_course_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread (mirrors test_e2e_questions).
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _rows(page):
    return page.evaluate(
        """() => Array.from(document.querySelectorAll(
             '[data-edit-slot] [data-choice-row]')).map(r => {
               const t = r.querySelector('[data-choice-correct]');
               const b = r.querySelector('textarea[name$="-feedback"]');
               return {checked: !!(t && t.checked),
                       ph: b ? b.getAttribute('placeholder') : null};
             })"""
    )


def test_feedback_placeholder_adapts_to_correct_toggle(page, live_server):
    # The per-option feedback prompt must reflect whether the option is marked Correct,
    # teaching that feedback applies to a missed-correct option, not only a distractor.
    _make_pa_user("cf")
    unit = _seed_course_unit("cf", slug="cf-ed")
    _login(page, live_server, "cf")
    page.goto(_editor_url(live_server, unit))
    page.wait_for_selector('[data-scope="editor"]')
    _add_element(page, "choice-single")
    page.locator("[data-edit-slot] input[name='choices-0-text']").fill("A")
    page.locator("[data-edit-slot] input[name='choices-1-text']").fill("B")

    grp = "[data-edit-slot] [data-choice-rows]"
    ok = page.get_attribute(grp, "data-fb-correct")  # locale-independent
    bad = page.get_attribute(grp, "data-fb-distractor")
    assert ok and bad and ok != bad

    rows = _rows(page)
    assert rows[0]["ph"] == bad and rows[1]["ph"] == bad  # both distractors initially

    # Tick row 1 correct -> its prompt flips to correct framing; row 0 stays distractor.
    page.locator("[data-edit-slot] input[name='choices-1-is_correct']").check()
    rows = _rows(page)
    assert rows[1]["checked"] and rows[1]["ph"] == ok
    assert rows[0]["ph"] == bad

    # Tick row 0 correct (single-choice radio) -> row 1 demotes back to distractor.
    page.locator("[data-edit-slot] input[name='choices-0-is_correct']").check()
    rows = _rows(page)
    assert rows[0]["ph"] == ok and rows[1]["ph"] == bad
