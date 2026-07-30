import os

import pytest

from courses.models import Attempt
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import TEST_PASSWORD
from tests.factories import ShortTextQuestionElement
from tests.factories import add_element
from tests.factories import make_quiz_unit
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    """Mandatory: all 75 sibling e2e modules define this and no conftest does.
    Without it, ORM calls under Playwright's sync API raise
    SynchronousOnlyOperation."""
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def test_previewer_answers_quiz_and_nothing_persists(live_server, page):
    """Drives the REAL gesture (type + click), never page.evaluate -- an e2e that
    bypasses the gesture ships broken UX green."""
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    add_element(unit, q)  # not bound: ruff F841 flags an unused local

    # Non-enrolled but access-bearing: is_staff is what makes can_access_course
    # pass without an Enrollment. No existing e2e helper yields this combination.
    user = make_verified_user(username="e2e_qprev", email="e2e_qprev@test.example.com")
    user.is_staff = True
    user.save()

    # Log in through the real form. The locators MUST be scoped to the login form:
    # templates/allauth/layouts/entrance.html renders a `lang-switch` form with one
    # <button type="submit"> per language, so the page has THREE submit buttons and
    # page.click('button[type="submit"]') (legacy, non-strict) clicks the FIRST --
    # the "EN" language button -- which POSTs set_ui_language, reloads, and wipes the
    # filled fields. The failure then surfaces misleadingly at the banner assertion.
    # Block copied verbatim from tests/test_e2e_editor.py:44-48.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("e2e_qprev")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()

    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/quiz/")
    assert page.locator("[data-quiz-preview-notice]").is_visible()

    page.fill('input[name="answer"]', "London")
    page.click('form.question__form button[type="submit"]')
    page.wait_for_selector("[data-question-feedback] .is-incorrect")

    assert QuizSubmission.objects.count() == 0
    assert QuestionResponse.objects.count() == 0
    assert Attempt.objects.count() == 0


def test_previewer_client_attempt_counter_reaches_terminal_reveal(live_server, page):
    """Proves quiz.js's client-owned attempt counter (quiz.js:37-42) actually
    reaches the server: without `body.append("attempt", ...)`, parse_attempt
    floors the absent value to 1 forever, so a previewer would NEVER see the
    wrong-on-last-attempt reveal no matter how many times they submit.

    max_attempts=2 is mandatory: at the default of 1 the first wrong answer is
    already terminal, so there is no withhold state to observe first.

    Drives the REAL gesture (fill + click) for BOTH submissions. Waits on
    [data-question][data-attempts-made="1"] between them -- quiz.js swaps the
    whole feedback box atomically, so re-waiting on a selector the FIRST
    response already satisfied (e.g. [data-question-feedback] .is-incorrect)
    would be satisfied instantly by stale DOM and not actually wait for the
    second response.
    """
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=2
    )
    add_element(unit, q)  # not bound: ruff F841 flags an unused local

    user = make_verified_user(
        username="e2e_qprev2", email="e2e_qprev2@test.example.com"
    )
    user.is_staff = True
    user.save()

    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill("e2e_qprev2")
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()

    page.goto(f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/quiz/")
    assert page.locator("[data-quiz-preview-notice]").is_visible()

    # First wrong answer: withhold state -- attempts remain, nothing revealed.
    page.fill('input[name="answer"]', "London")
    page.click('form.question__form button[type="submit"]')
    page.wait_for_selector('[data-question][data-attempts-made="1"]')
    assert page.locator("[data-question-feedback] .is-incorrect").is_visible()
    assert page.locator(".question__reveal-text").count() == 0
    assert page.locator("[data-question]").get_attribute("data-attempts-made") == "1"

    # Second wrong answer: terminal state -- only reached if attempt=2 made it
    # to the server, which only happens if quiz.js's counter appended it.
    page.fill('input[name="answer"]', "London")
    page.click('form.question__form button[type="submit"]')
    page.wait_for_selector('[data-question][data-attempts-made="2"]')
    assert page.locator(".question__reveal-text").is_visible()
    assert "Paris" in page.locator(".question__reveal-text").inner_text()

    assert QuizSubmission.objects.count() == 0
    assert QuestionResponse.objects.count() == 0
    assert Attempt.objects.count() == 0
