"""Playwright e2e for Phase-2c quiz flow: answer / finish / results.

Tests:
  1. JS path (fetch fragment swap): short-text wrong → .is-incorrect + no-leak;
     correct on 2nd attempt → .is-correct + input disabled (lock); Finish (confirm
     dialog accepted) → /quiz/results/ URL.
  2. No-JS path (java_script_enabled=False + page.request.post()): POST wrong
     answer WITHOUT X-Requested-With → full-page HTML, "Paris" absent (withheld);
     POST finish → 302 to /results/.

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in test_e2e_questions_2b.py verbatim (fixtures, helpers,
no-JS mechanism: browser.new_context(java_script_enabled=False) + page.request.post()).
"""

import os
import urllib.parse

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_e2e_questions_2b.py)
# ---------------------------------------------------------------------------


def _make_student(username):
    """Create a verified user (regular student, no special group)."""
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    """Log in via the allauth HTML form (works with JS enabled or disabled)."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# ---------------------------------------------------------------------------
# Seeding helper
# ---------------------------------------------------------------------------


def _seed_quiz(username, slug):
    """Create a course + quiz unit with one short-text question (max_attempts=2).

    Returns (course, unit, element_join_row).
    The student is enrolled so quiz_answer POSTs are permitted.
    """
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    from django.contrib.auth import get_user_model

    User = get_user_model()
    student = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    st = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of France?</p>",
        accepted="Paris",
        max_attempts=2,
    )
    el_join = Element.objects.create(unit=unit, content_object=st)
    return course, unit, el_join


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_quiz_answer_finish_results_js(browser, live_server):
    """JS path (fetch fragment swap via quiz.js):

    - Load the quiz page.
    - Wrong answer "London" → .is-incorrect appears; "Paris" NOT in page content
      (no-leak while attempts remain).
    - Correct answer "Paris" on 2nd attempt → .is-correct appears; input is
      disabled (lock sentinel [data-quiz-locked] triggers JS disable).
    - Finish button click → accept confirm dialog → wait for /quiz/results/ URL.
    """
    _make_student("e2e_quiz_js")
    course, unit, el_join = _seed_quiz("e2e_quiz_js", "e2e-quiz-js")

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "e2e_quiz_js")

    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first
    feedback = q.locator("[data-question-feedback]")

    # ── Wrong answer: withhold (no-leak) ─────────────────────────────────────
    q.locator("input[name='answer']").fill("London")
    q.locator("button[type='submit']").click()
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect after wrong short-text answer"
    )
    # No-leak: the correct answer must NOT appear in the page while attempts remain.
    assert "Paris" not in page.content(), (
        "Correct answer 'Paris' must not be revealed before attempts are exhausted"
    )

    # ── Correct answer on 2nd attempt: reveal + lock ──────────────────────────
    q.locator("input[name='answer']").fill("Paris")
    q.locator("button[type='submit']").click()
    feedback.locator(".is-correct").wait_for(timeout=6000)
    assert feedback.locator(".is-correct").count() >= 1, (
        "Expected .is-correct after correct short-text answer"
    )
    # Lock: quiz.js disables all inputs/buttons inside the form when [data-quiz-locked]
    # is present in the feedback HTML.
    assert q.locator("input[name='answer']").is_disabled(), (
        "Answer input must be disabled (locked) after a correct answer"
    )

    # ── Finish: accept confirm dialog → results ───────────────────────────────
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)
    assert "/results/" in page.url, (
        f"Expected /results/ in URL after finishing quiz, got: {page.url}"
    )

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_quiz_no_js_full_flow(browser, live_server):
    """No-JS path (java_script_enabled=False + page.request.post()):

    - POST wrong answer without X-Requested-With header → full-page HTML 200;
      "Paris" absent (withheld while attempts remain).
    - POST finish → 302 to /results/ (follow_redirects=False so we read status).
    """
    _make_student("e2e_quiz_nojs")
    course, unit, el_join = _seed_quiz("e2e_quiz_nojs", "e2e-quiz-nojs")

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "e2e_quiz_nojs")

    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)

    # Read CSRF token from cookie.
    cookies = ctx.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set after navigating to quiz page"

    answer_url = (
        f"{live_server.url}/courses/{course.slug}/u/{unit.pk}"
        f"/quiz/q/{el_join.pk}/answer/"
    )
    finish_url = (
        f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/finish/"
    )

    def post_form(url, fields, *, follow_redirects=True):
        """POST url-encoded form data; return APIResponse."""
        parts = [("csrfmiddlewaretoken", csrf_token)] + list(fields.items())
        encoded = urllib.parse.urlencode(parts)
        return page.request.post(
            url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": quiz_url,
            },
            data=encoded,
            # Playwright's APIRequestContext follows redirects by default.
            # Pass max_redirects=0 to detect the 302 status for the finish POST.
            max_redirects=0 if not follow_redirects else 10,
        )

    # ── Wrong answer: full-page re-render, "Paris" withheld ──────────────────
    # No X-Requested-With header → view returns full-page HTML (not a fragment).
    resp = post_form(answer_url, {"answer": "London"})
    assert resp.ok, (
        f"quiz_answer POST failed with status {resp.status}"
    )
    html = resp.text()
    assert "Paris" not in html, (
        "Correct answer 'Paris' must not appear in full-page re-render while "
        "attempts remain (no-JS no-leak)"
    )

    # ── Finish: POST → 302 to /results/ ──────────────────────────────────────
    resp_finish = post_form(finish_url, {}, follow_redirects=False)
    assert resp_finish.status == 302, (
        f"quiz_finish POST should return 302, got {resp_finish.status}"
    )
    location = resp_finish.headers.get("location", "")
    assert "/results/" in location, (
        f"quiz_finish should redirect to /results/, got Location: {location}"
    )

    ctx.close()
