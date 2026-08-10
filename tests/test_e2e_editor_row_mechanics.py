"""Mechanisms that only appear when the pieces interact.

EVERY test below carries the full harness written out — no abbreviation. The
per-test @pytest.mark.django_db(transaction=True) is load-bearing: conftest's
autouse _enable_db_access(db) otherwise supplies a NON-transactional db, and the
live_server thread then sees none of the seeded rows. That is the single most
common way this repo's e2e fail."""

import os

import pytest

pytestmark = pytest.mark.e2e

SAVE = "[data-edit-slot] button[type='submit']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_post_init_state(page, live_server, open_matchpair_editor_e2e):
    """The JS half of the progressive-enhancement guarantee."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=2)
    row = page.locator("[data-fsrow-item]").first
    assert not row.locator("[data-fsrow-del]").is_visible()
    assert row.locator("[data-fsrow-remove]").is_visible()


@pytest.mark.django_db(transaction=True)
def test_focus_after_removal_formset(page, live_server, open_matchpair_editor_e2e):
    """Blank row on purpose: no confirm fires, so NO dialog handler. A filled row
    would need one, and getting that wrong makes this RED on a correct build."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=4)
    rows = page.locator("[data-fsrow-item]")
    rows.nth(4).locator("[data-fsrow-remove]").click()  # an extra=2 blank
    # Assert IDENTITY, not just "not body". `!= "BODY"` cannot tell candidate 1 from
    # candidate 3, cannot catch focus landing on the add button (explicitly rejected
    # as a fallback), and cannot catch the after/before chain being reversed — and
    # these two tests are the ONLY coverage of the focus chain.
    assert page.evaluate("document.activeElement.matches('[data-fsrow-remove]')")
    assert page.evaluate(
        "document.activeElement.closest('[data-fsrow-item]')"
        " === document.querySelectorAll('[data-fsrow-item]')[5]"
    )


@pytest.mark.django_db(transaction=True)
def test_focus_after_removal_switchgate(page, live_server, open_switchgate_editor):
    """The variant that covers capture-before-detach: module 2 removes the row from
    the DOM, so neighbours resolved afterwards would all be null."""
    open_switchgate_editor(page, live_server, options=[])
    page.locator("[data-sgate-row]").nth(2).locator("[data-sgate-remove]").click()
    # After detaching row 2, the row that WAS index 3 is now index 2 — its remove
    # button is the expected target. Identity, not "not body": this is the only
    # coverage of the capture-before-detach rule, whose failure mode is focus
    # silently falling to <body>.
    assert page.evaluate("document.activeElement.matches('[data-sgate-remove]')")
    assert page.evaluate(
        "document.activeElement.closest('[data-sgate-row]')"
        " === document.querySelectorAll('[data-sgate-row]')[2]"
    )


@pytest.mark.django_db(transaction=True)
def test_at_minimum_hint(page, live_server, open_choice_editor):
    """A fresh choice question renders exactly extra=2 rows = data-fsrows-min."""
    open_choice_editor(page, live_server, options=[])
    assert page.locator("[data-fsrow-remove]").first.is_disabled()
    assert page.locator("[data-fsrows-hint]").is_visible()


@pytest.mark.django_db(transaction=True)
def test_maximum_cap_and_its_residual_hole(page, live_server, open_stepper_editor_e2e):
    open_stepper_editor_e2e(page, live_server, steps=[f"step {i}" for i in range(20)])
    assert page.locator("[data-fsrows-add]").is_disabled()
    assert page.locator("[data-fsrows-hint]").is_visible()
    # The accepted residual hole: extra=1 renders a 21st row the author can type
    # into without touching Add. Pinned so the limitation is documented, not assumed.
    page.locator("[data-fsrows-list] li").last.locator('input[type="text"]').fill(
        "21st"
    )
    page.locator(SAVE).click()
    # wait_for BEFORE count(): the save is a fetch + fragment swap, so counting
    # immediately after the click reads the pre-save DOM and returns 0.
    page.locator("text=at most 20").first.wait_for(timeout=8000)
    assert page.locator("text=at most 20").count() == 1


@pytest.mark.django_db(transaction=True)
def test_422_reconciliation(page, live_server, open_matchpair_editor_e2e):
    """Remove a row, fail validation, and the removed row must come back NOT
    VISIBLE with its DELETE still ticked — the server re-renders from the POST and
    knows nothing about row.hidden."""
    open_matchpair_editor_e2e(page, live_server, saved_pairs=3)
    page.on("dialog", lambda d: d.accept())
    row = page.locator("[data-fsrow-item]").nth(1)
    row.locator("[data-fsrow-remove]").click()
    # The failure MUST be a NON-FORM error, and every form must stay INDIVIDUALLY
    # valid to get one. _edit_matchpairquestion.html renders only
    # `{% for e in formset.non_form_errors %}`, and BaseMatchPairFormSet.clean()
    # returns early on `any(self.errors)`. left/right are required CharFields with no
    # blank=True, so BLANKING a saved row raises a per-form error the template never
    # displays — no .field-error would exist to wait on. Removing the remaining saved
    # rows instead marks them DELETE: deleted initial forms and untouched blank extras
    # both produce no per-form errors, so clean() reaches len(kept) < 1 and renders
    # "Add at least one pair."
    for i in (2, 0):
        page.locator("[data-fsrow-item]").nth(i).locator("[data-fsrow-remove]").click()
    page.locator(SAVE).click()
    # Wait on the ERROR, not the preview: this save is expected to fail, so the
    # preview never changes — and [data-scope="preview"] already exists, so waiting
    # on it returns instantly and the assertions below would read the pre-swap DOM.
    page.locator("[data-edit-slot] .field-error").first.wait_for(timeout=8000)
    back = page.locator("[data-fsrow-item]").nth(1)
    assert not back.is_visible()
    assert back.locator('input[name$="-DELETE"]').is_checked()


@pytest.mark.django_db(transaction=True)
def test_minimum_floor_is_an_invariant(page, live_server, open_choice_editor):
    """The dead-end guard, asserted DIRECTLY as an invariant rather than staged
    through a 422 — because no 422 can reach it.

    Both formsets render extra=2, so a re-render always carries at least two
    un-ticked blank rows: `rows - ticked >= 2 == data-fsrows-min` ALWAYS, and the
    floor branch never executes on any real server response. (Ticking the blanks too
    does not help: each then has_changed(), the required `text` errors, clean()
    returns early on any(self.errors), BaseFormSet skips DELETE-marked forms when
    computing validity — so the save returns 200 and silently deletes everything,
    never a 422.)

    The floor is therefore a defensive invariant of init job 2, not a reachable
    path. Testing it means driving job 2 directly: tick every DELETE, re-run the
    init pass, and assert it refuses to hide below the minimum and un-ticks what it
    left visible, so the checkbox state and the display never disagree."""
    open_choice_editor(page, live_server, options=["a", "b"])
    # Double quotes INSIDE the selector: quoting it with the same single quotes that
    # delimit the JS string produces `querySelectorAll('[name$='-DELETE']')`, a
    # SyntaxError that kills the test against a CORRECT build — and would make the
    # Step 3 falsification unable to tell the mutant from the baseline.
    page.evaluate(
        """document.querySelectorAll('[name$="-DELETE"]')"""
        """.forEach(function (d) { d.checked = true; });"""
        """window.libliInitFormsetRows(document.querySelector('[data-fsrows]'));"""
    )
    visible = page.locator("[data-fsrow-item]:visible")
    assert visible.count() == 2, "init job 2 must not hide below data-fsrows-min"
    for i in range(visible.count()):
        assert not visible.nth(i).locator('input[name$="-DELETE"]').is_checked(), (
            "a row left visible by the floor must be un-ticked, or the checkbox "
            "state and what the author sees disagree"
        )
