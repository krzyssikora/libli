# tests/test_e2e_questions_2diii.py
"""Playwright e2e for Phase-2d-iii extended-response question type.

Tests:
  1. Lesson [A]: a PARTIAL answer ("alpha" present, "beta" missing) → incorrect
     verdict + reveal shows the ✓/✗ keyword breakdown. (A fully-correct answer
     suppresses the per-item reveal since PR #41, so this drives the partial path.)
  2. Quiz [R]: student submits → per-question card shows "Submitted for review";
     finish quiz → results page shows "Awaiting review" + pending-review footer;
     no keyword leak ([R] rows reveal nothing).
  3. Quiz [A] max_attempts=1: wrong submit exhausts attempts → reveal appears;
     required keyword absent before submit, present in reveal after last attempt.

Harness mirrors test_e2e_questions_2d.py / test_e2e_quiz.py:
  - _login() is identical.
  - All seeds create user + course + Enrollment + unit + element via the ORM
    (same pattern as _seed_dragfill_lesson / _seed_quiz).
  - JS path throughout: real textarea.fill() + button.click() drives the actual
    question.js fetch → [data-question-feedback] slot swap. No page.evaluate()
    bypasses.
  - Quiz finish: page.once("dialog", ...) + [data-finish-btn].click() (matches
    test_quiz_answer_finish_results_js).
"""

import os

import pytest

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db]


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(page, live_server, username):
    """Log in via the allauth HTML form (works with JS enabled or disabled)."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_extended_lesson(username):
    """User + LESSON unit with one [A] extended-response (required: alpha, beta)."""
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=f"c-{username}", language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem="<p>Describe alpha and beta.</p>",
        required_keywords="alpha\nbeta",
        marking_mode="A",
    )
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


def _seed_extended_quiz(username, slug, *, marking_mode, max_attempts=None):
    """User + QUIZ unit with one extended-response question.

    The stem uses "mitosis" as its topic; the required keyword is "prophase" —
    a word that appears only in the reveal, never in the stem. This lets the
    no-leak assertions check that "prophase" is absent from the page (before
    a correct submit or in [R] mode) without the stem itself triggering the check.
    """
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Q"
    )
    kwargs = dict(
        stem="<p>Explain the stages of mitosis.</p>",
        required_keywords="prophase",
        marking_mode=marking_mode,
    )
    if max_attempts is not None:
        kwargs["max_attempts"] = max_attempts
    q = ExtendedResponseQuestionElement.objects.create(**kwargs)
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_author_then_answer_extended_response_in_lesson(live_server, page):
    """Lesson [A]: a PARTIAL answer (one required keyword present, one missing) →
    incorrect verdict + the reveal shows the per-keyword ✓/✗ breakdown.

    A fully-correct answer now suppresses the per-item reveal (PR #41), so this
    drives the reveal branch via a partial answer — the breakdown only renders
    when the answer is not fully correct.

    Gesture: real textarea.fill() + button.click() — question.js intercepts the
    submit event, sends a fetch with X-Requested-With: fetch, and swaps the
    [data-question-feedback] slot with the fragment HTML.
    """
    course, unit, el = _seed_extended_lesson("er_lesson_a")
    _login(page, live_server, "er_lesson_a")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")

    q = page.locator("[data-question]").first
    feedback = q.locator("[data-question-feedback]")

    # Type a PARTIAL answer: "alpha" present, "beta" missing → incorrect, so the
    # keyword breakdown still renders.
    q.locator("textarea[name='answer']").fill("alpha only")

    # Click the real submit button — question.js fires the fetch.
    q.locator(".question__form button[type='submit']").click()

    # Wait for the async feedback swap to settle (incorrect verdict).
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect verdict after an answer missing a required keyword"
    )

    # The reveal template (_reveal_extendedresponse.html) renders the per-keyword
    # breakdown: "alpha" found (✓), "beta" missing (✗).
    assert feedback.locator(".kw--required.is-found").count() >= 1, (
        "Expected the present required keyword 'alpha' marked is-found"
    )
    assert feedback.locator(".kw--required.is-missing").count() >= 1, (
        "Expected the absent required keyword 'beta' marked is-missing"
    )


@pytest.mark.django_db(transaction=True)
def test_quiz_review_mode_shows_awaiting_review_and_footer(live_server, browser):
    """Quiz [R]: submit → "Submitted for review"; finish → results page shows
    "Awaiting review" badge + pending footer; no keyword leak in [R] rows.
    """
    course, unit, el = _seed_extended_quiz("er_quiz_r", "er-quiz-r", marking_mode="R")
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "er_quiz_r")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first
    feedback = q.locator("[data-question-feedback]")

    # Type any answer and submit via the real button — drives quiz.js / question.js.
    q.locator("textarea[name='answer']").fill("Some answer for review")
    q.locator(".question__form button[type='submit']").click()

    # [R] mode: verdict is "Submitted for review" (neutral/recorded sentinel).
    feedback.locator(".is-recorded").wait_for(timeout=6000)
    assert "Submitted for review" in page.content(), (
        "Expected 'Submitted for review' in per-question feedback for [R] mode"
    )

    # No keyword leak while in the quiz view.
    assert "prophase" not in page.content(), (
        "Required keyword 'prophase' must NOT appear in the quiz view ([R] no-leak)"
    )

    # Finish quiz: accept the confirm dialog, wait for results page.
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)
    assert "/results/" in page.url, (
        f"Expected /results/ in URL after finishing quiz, got: {page.url}"
    )

    results_content = page.content()

    # Results page: "Awaiting review" badge on the per-question row.
    assert "Awaiting review" in results_content, (
        "Expected 'Awaiting review' badge on results page for [R] question"
    )

    # Pending-review footer: "question awaiting review" (singular).
    assert "awaiting review" in results_content, (
        "Expected pending-review footer text on results page"
    )

    # No keyword leak: [R] rows expose no required-keyword reveal.
    assert "prophase" not in results_content, (
        "Required keyword 'prophase' must NOT appear on the results page for [R] mode"
    )

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_quiz_auto_mode_no_leak_then_reveal(live_server, page):
    """Quiz [A] max_attempts=1: wrong answer exhausts attempts → reveal appears.

    Asserts:
    - Required keyword does NOT appear in page content before submit.
    - After the (only) wrong submit, the reveal shows the required keyword.
    """
    course, unit, el = _seed_extended_quiz(
        "er_quiz_a1", "er-quiz-a1", marking_mode="A", max_attempts=1
    )
    _login(page, live_server, "er_quiz_a1")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first
    feedback = q.locator("[data-question-feedback]")

    # Pre-submit: required keyword must NOT appear (no-leak before any answer).
    assert "prophase" not in page.content(), (
        "Required keyword 'prophase' must NOT appear in the quiz page before any answer"
    )

    # Submit a wrong answer (does not contain "prophase") — exhausts the single attempt.
    q.locator("textarea[name='answer']").fill("wrong answer without the keyword")
    q.locator(".question__form button[type='submit']").click()

    # Wrong on last attempt → .is-incorrect verdict + reveal (locked).
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect verdict after wrong answer on last attempt"
    )

    # Wait briefly for the DOM to settle after the fetch swap.
    page.wait_for_timeout(500)

    # Post-reveal: required keyword MUST now appear (reveal template rendered).
    assert "prophase" in page.content(), (
        "'prophase' must appear in the reveal after exhausting attempts"
    )

    # The reveal shows the keyword as a required item (not found: answer was wrong).
    assert feedback.locator(".kw--required").count() >= 1, (
        "Expected .kw--required item in the reveal after last wrong attempt"
    )
