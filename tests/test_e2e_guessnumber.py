"""Playwright e2e for the "Guess the number" element (plan Task 15). Drives the REAL
student gesture end-to-end — types into the actual input, clicks the actual Check
button, presses real Enter keys — never a page.evaluate shortcut into the check
endpoint or the JS internals (this repo's standing lesson: an e2e that bypasses the
real gesture ships broken UX green).

Covers the ten cases from the task brief, each its own test:
  1. Too big: "43" against target 42 -> hint shown ("too big"), input is-wrong.
  2. Too small: "41" against target 42 -> hint shown ("too small").
  3. Correct: "42" -> success shown; input is-correct + readOnly; container
     guessnumber--done; Check removed.
  4. Live region: [data-guess-live] carries the verdict text on every outcome.
  5. Typing after a wrong verdict hides the hint again (before any re-submit).
  6. Enter (not just the Check click) submits.
  7. Polish comma: typing "40401,5" into the REAL input against a 40401.5 target is
     correct. The one test that would catch a `type="number"` input silently
     returning "" for a comma — every other comma test in this build is server- or
     form-side and passes regardless.
  8. Post-lock inertness (behavioural, not just attributes): after a correct answer,
     Enter in the input causes no navigation and leaves the success state unchanged
     — the `done` guard is the only thing acting on Enter now that no implicit
     submission exists (the Check click path is gone with the button).
  9. Nesting smoke test ONLY: [text][reveal gate][guess element], "Show more"
     reveals it, a wrong guess does not re-hide it. This does NOT guard the
     no-<form> decision — it drives the ARMED path, which never navigated even
     with a form. The hazard was the UN-ARMED Enter, unreachable by an e2e with JS
     loaded; that decision is guarded structurally by `assert "<form" not in html`
     in tests/test_guessnumber_render.py.
  10. Nested in tabs: the element works and is fully interactive inside a tab panel.

Harness mirrors tests/test_e2e_switchgate.py (login/seed/unit helpers, tab seeding)
and tests/test_e2e_markdone.py. Marked e2e (excluded from the default run; run with
-m e2e)."""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


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
    """An enrolled student + a fresh unit of `unit_type`. Returns (student, unit)."""
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


def _text(body):
    from courses.models import TextElement

    return TextElement.objects.create(body=body)


def _gate(label):
    from courses.models import RevealGateElement

    return RevealGateElement.objects.create(label=label)


def _guessnumber(author_stem, tolerance=0, success_message=""):
    """Build a GuessNumberElement from author `{{n}}` markup, as the form's
    clean()/save() would: parse_stem tokenises the stem and lifts the raw target
    (the ￿0￿-sentinel token is never pasted here — file tools corrupt it; parse_stem
    builds it from fillblank's SENTINEL)."""
    from courses import guessnumber
    from courses.models import GuessNumberElement

    token_stem, raw = guessnumber.parse_stem(author_stem)
    return GuessNumberElement.objects.create(
        stem=token_stem,
        target=raw,
        tolerance=tolerance,
        success_message=success_message,
    )


def _seed_tab1_gn(unit, tab1_children):
    """One TabsElement on `unit` (tabs 'First'/'Second'); `tab1_children` is a list of
    concrete element objects placed, in order, nested under tab 1."""
    from courses.models import Element
    from courses.models import TabsElement

    obj = TabsElement.objects.create(
        data={
            "tabs": [
                {"id": "t000001", "label": "First"},
                {"id": "t000002", "label": "Second"},
            ]
        }
    )
    join = Element.objects.create(unit=unit, content_object=obj)
    for child in tab1_children:
        Element.objects.create(
            unit=unit, content_object=child, parent=join, tab_id="t000001"
        )
    return join


# Shared locators.
def _root(page):
    return page.locator("[data-guessnumber]").first


def _input(page):
    return page.locator("[data-guess-input]").first


def _check(page):
    return page.locator("[data-guess-check]").first


def _hint(page):
    return page.locator("[data-guess-hint]").first


def _success(page):
    return page.locator("[data-guess-success]").first


def _live(page):
    return page.locator("[data-guess-live]").first


# ---------------------------------------------------------------------------
# 1. Too big
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_too_big_shows_hint_and_marks_wrong(page, live_server):
    """Case 1: a too-high guess shows the "too big" hint and marks the input
    is-wrong."""
    _student, unit = _new_unit("gn_high")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_high")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()  # armed by JS
    _input(page).fill("43")
    _check(page).click()

    expect(_hint(page)).to_be_visible()
    expect(_hint(page)).to_contain_text("too big")
    expect(_input(page)).to_have_class(re.compile(r"\bis-wrong\b"))


# ---------------------------------------------------------------------------
# 2. Too small
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_too_small_shows_hint(page, live_server):
    """Case 2: a too-low guess shows the "too small" hint."""
    _student, unit = _new_unit("gn_low")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_low")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).fill("41")
    _check(page).click()

    expect(_hint(page)).to_be_visible()
    expect(_hint(page)).to_contain_text("too small")


# ---------------------------------------------------------------------------
# 3. Correct
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_correct_reveals_success_and_locks(page, live_server):
    """Case 3: a correct guess shows the success message, marks the input
    is-correct + readOnly, marks the container guessnumber--done and removes
    Check (as fillgate/switchgate do — the commit button is spent)."""
    _student, unit = _new_unit("gn_correct")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_correct")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).fill("42")
    _check(page).click()

    expect(_success(page)).to_be_visible()
    expect(_input(page)).to_have_class(re.compile(r"\bis-correct\b"))
    expect(_input(page)).to_have_js_property("readOnly", True)
    expect(_root(page)).to_have_class(re.compile(r"\bguessnumber--done\b"))
    expect(_check(page)).to_have_count(0)


# ---------------------------------------------------------------------------
# 4. Live region
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_live_region_carries_the_verdict_text(page, live_server):
    """Case 4: [data-guess-live] contains the verdict text on every outcome
    (too big, too small, correct)."""
    _student, unit = _new_unit("gn_live")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_live")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()

    _input(page).fill("43")
    _check(page).click()
    expect(_live(page)).to_contain_text("too big")

    _input(page).fill("41")
    _check(page).click()
    expect(_live(page)).to_contain_text("too small")

    _input(page).fill("42")
    _check(page).click()
    expect(_live(page)).to_contain_text("Correct!")


# ---------------------------------------------------------------------------
# 5. Typing clears
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_typing_after_wrong_hides_the_hint(page, live_server):
    """Case 5: after a wrong verdict, typing again hides the hint before any
    re-submit (a fresh attempt starts clean)."""
    _student, unit = _new_unit("gn_retype")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_retype")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).fill("43")
    _check(page).click()
    expect(_hint(page)).to_be_visible()
    expect(_input(page)).to_have_class(re.compile(r"\bis-wrong\b"))

    _input(page).fill("44")
    expect(_hint(page)).to_be_hidden()
    expect(_input(page)).not_to_have_class(re.compile(r"\bis-wrong\b"))


# ---------------------------------------------------------------------------
# 6. Enter submits
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_enter_key_submits(page, live_server):
    """Case 6: pressing Enter in the input submits the guess, not just clicking
    Check."""
    _student, unit = _new_unit("gn_enter")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_enter")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).fill("43")
    _input(page).press("Enter")

    expect(_hint(page)).to_be_visible()
    expect(_hint(page)).to_contain_text("too big")


# ---------------------------------------------------------------------------
# 7. Polish comma decimal
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_polish_comma_decimal_is_accepted_from_the_real_input(page, live_server):
    """Case 7: typing a Polish-locale comma decimal into the REAL input, key by
    key, is accepted against a decimal target. This is the one test that would
    catch a `type="number"` input silently returning "" for a comma — every
    other comma test in this build is server- or form-side and passes
    regardless."""
    _student, unit = _new_unit("gn_comma")
    add_element(unit, _guessnumber("<p>Guess: {{40401.5}}</p>"))
    _login(page, live_server, "gn_comma")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).click()
    _input(page).press_sequentially("40401,5")
    # The comma survives real keystrokes into the real input (not silently
    # sanitised away, as a type="number" field would do).
    expect(_input(page)).to_have_value("40401,5")
    _check(page).click()

    expect(_success(page)).to_be_visible()
    expect(_input(page)).to_have_class(re.compile(r"\bis-correct\b"))


# ---------------------------------------------------------------------------
# 8. Post-lock inertness
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_enter_after_correct_does_not_navigate_or_change_state(page, live_server):
    """Case 8: post-lock inertness is behavioural, not just attributes. After a
    correct answer, Enter in the (readonly) input causes no navigation and
    leaves the success state unchanged — the `done` guard is the only thing
    still acting on Enter now that no implicit submission exists (the Check
    click path is gone with the button)."""
    _student, unit = _new_unit("gn_lock")
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_lock")
    page.goto(_unit_url(live_server, unit))

    expect(_check(page)).to_be_visible()
    _input(page).fill("42")
    _check(page).click()
    expect(_success(page)).to_be_visible()

    url_before = page.url
    _input(page).press("Enter")

    assert page.url == url_before
    expect(_success(page)).to_be_visible()
    expect(_input(page)).to_have_class(re.compile(r"\bis-correct\b"))
    expect(_input(page)).to_have_js_property("readOnly", True)
    expect(_root(page)).to_have_class(re.compile(r"\bguessnumber--done\b"))


# ---------------------------------------------------------------------------
# 9. Behind a reveal gate: a wrong guess does not re-hide it (nesting smoke test)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_guess_element_survives_a_wrong_guess_behind_a_reveal_gate(page, live_server):
    """Case 9: [text][reveal gate][guess element]; "Show more" reveals the guess
    element, and a wrong guess does not re-hide it. NESTING SMOKE TEST ONLY — this
    does not guard the no-<form> decision. It drives the ARMED path, which never
    navigated even with a form; the hazard was the UN-ARMED Enter, which an e2e
    with JS loaded cannot reach. That decision is guarded structurally by
    `assert "<form" not in html` in tests/test_guessnumber_render.py."""
    _student, unit = _new_unit("gn_gate")
    add_element(unit, _text("<p>intro block</p>"))
    add_element(unit, _gate("Show more"))
    add_element(unit, _guessnumber("<p>Guess: {{42}}</p>"))
    _login(page, live_server, "gn_gate")
    page.goto(_unit_url(live_server, unit))

    gate = page.get_by_role("button", name="Show more")
    expect(gate).to_be_visible()
    expect(_input(page)).to_be_hidden()

    gate.click()

    expect(_input(page)).to_be_visible()
    expect(_check(page)).to_be_visible()

    _input(page).fill("43")
    _check(page).click()

    expect(_hint(page)).to_be_visible()
    # Still revealed: the wrong guess did not re-hide the gated element.
    expect(_input(page)).to_be_visible()
    expect(_root(page)).to_be_visible()


# ---------------------------------------------------------------------------
# 10. Nested inside a tab panel
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_guessnumber_nested_in_tab_panel(page, live_server):
    """Case 10: the element works inside a tab panel — visible in the active tab
    and fully interactive there (a correct guess reveals success)."""
    _student, unit = _new_unit("gn_tabs")
    _seed_tab1_gn(unit, [_guessnumber("<p>Guess: {{42}}</p>")])
    _login(page, live_server, "gn_tabs")
    page.goto(_unit_url(live_server, unit))

    page.wait_for_selector("[data-tabs].tabs--js")
    expect(_input(page)).to_be_visible()
    expect(_check(page)).to_be_visible()

    _input(page).fill("42")
    _check(page).click()

    expect(_success(page)).to_be_visible()
    expect(_root(page)).to_have_class(re.compile(r"\bguessnumber--done\b"))
