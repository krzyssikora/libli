"""Playwright e2e for Phase-2b auto-markable question types.

Tests:
  1. JS path (fragment swap): answer short-text wrong then right, fill-blank right.
  2. No-JS path (full-page POST): answer short-numeric wrong then right; assert
     is-correct verdict + that the answered input repopulates.

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in test_e2e_questions.py verbatim (fixtures, helpers,
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
# Helpers (verbatim from test_e2e_questions.py)
# ---------------------------------------------------------------------------


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    """Log in via the allauth HTML form (works with JS enabled or disabled)."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _enroll(user, course):
    from courses.models import Enrollment

    Enrollment.objects.get_or_create(student=user, course=course)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_all_types(username, slug):
    """Create a course + lesson with one of each new question type; return (course, unit,
    short-text join-row, short-numeric join-row, fill-blank join-row)."""
    from django.contrib.auth import get_user_model

    from courses.models import Blank
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import FillBlankQuestionElement
    from courses.models import ShortNumericQuestionElement
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    Enrollment.objects.get_or_create(student=owner, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="L"
    )

    # 1) short-text: capital of France
    st = ShortTextQuestionElement.objects.create(
        stem="<p>Cap?</p>", accepted="Paris"
    )
    st_join = Element.objects.create(unit=unit, content_object=st)

    # 2) short-numeric: value of Pi to 2 d.p., tolerance 0.01
    sn = ShortNumericQuestionElement.objects.create(
        stem="<p>Pi?</p>", value="3.14", tolerance="0.01"
    )
    sn_join = Element.objects.create(unit=unit, content_object=sn)

    # 3) fill-blank: "On the ___." → blank accepted "Seine"
    fb = FillBlankQuestionElement.objects.create(stem="On the ￿0￿.")
    Blank.objects.create(question=fb, accepted="Seine")
    fb_join = Element.objects.create(unit=unit, content_object=fb)

    return course, unit, st_join, sn_join, fb_join


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_answer_all_types_js_path(browser, live_server):
    """JS path (fragment swap via question.js fetch):

    - short-text: submit wrong ("London") → .is-incorrect; submit correct ("paris")
      → .is-correct.
    - short-numeric: submit wrong ("9") → .is-incorrect; submit correct ("3.14")
      → .is-correct.
    - fill-blank: submit correct ("Seine") → .is-correct.

    Uses a separate browser context so the fixture `page` isn't consumed.
    """
    _make_pa_user("pa2b_js")
    course, unit, st_join, sn_join, fb_join = _seed_all_types("pa2b_js", "e2e-2b-js")

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "pa2b_js")
    lesson_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)
    page.wait_for_selector("[data-question]")

    questions = page.locator("[data-question]")

    # ── 1) Short-text ────────────────────────────────────────────────────────
    st_q = questions.nth(0)
    st_feedback = st_q.locator("[data-question-feedback]")

    # Wrong answer → .is-incorrect
    st_q.locator("input[name='answer']").fill("London")
    st_q.locator("button[type='submit']").click()
    st_feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert st_feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect after wrong short-text answer"
    )

    # Correct answer (lowercase) → .is-correct
    st_q.locator("input[name='answer']").fill("paris")
    st_q.locator("button[type='submit']").click()
    st_feedback.locator(".is-correct").wait_for(timeout=6000)
    assert st_feedback.locator(".is-correct").count() >= 1, (
        "Expected .is-correct after correct short-text answer"
    )

    # ── 2) Short-numeric ─────────────────────────────────────────────────────
    sn_q = questions.nth(1)
    sn_feedback = sn_q.locator("[data-question-feedback]")

    # Wrong answer → .is-incorrect
    sn_q.locator("input[name='answer']").fill("9")
    sn_q.locator("button[type='submit']").click()
    sn_feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert sn_feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect after wrong short-numeric answer"
    )

    # Correct answer → .is-correct
    sn_q.locator("input[name='answer']").fill("3.14")
    sn_q.locator("button[type='submit']").click()
    sn_feedback.locator(".is-correct").wait_for(timeout=6000)
    assert sn_feedback.locator(".is-correct").count() >= 1, (
        "Expected .is-correct after correct short-numeric answer"
    )

    # ── 3) Fill-blank ─────────────────────────────────────────────────────────
    fb_q = questions.nth(2)
    fb_feedback = fb_q.locator("[data-question-feedback]")

    # Correct answer → .is-correct
    fb_q.locator("input[name='blank']").fill("Seine")
    fb_q.locator("button[type='submit']").click()
    fb_feedback.locator(".is-correct").wait_for(timeout=6000)
    assert fb_feedback.locator(".is-correct").count() >= 1, (
        "Expected .is-correct after correct fill-blank answer"
    )

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_answer_all_types_no_js(browser, live_server):
    """No-JS path (full-page POST via page.request.post()):

    Uses browser.new_context(java_script_enabled=False) — same mechanism as
    test_answer_multiple_choice_no_js in test_e2e_questions.py.

    For each type, POST directly with the CSRF cookie, load the response HTML into a
    fresh page, and assert:
      - the answered question shows .is-incorrect or .is-correct as expected;
      - the answered input repopulates with the submitted value.
    """
    _make_pa_user("pa2b_nojs")
    course, unit, st_join, sn_join, fb_join = _seed_all_types(
        "pa2b_nojs", "e2e-2b-nojs"
    )

    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "pa2b_nojs")

    lesson_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)

    # Read CSRF token from cookie (login + lesson GET have both set it).
    cookies = ctx.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set after navigating to lesson page"

    def check_url(element_pk):
        return (
            f"{live_server.url}/courses/{course.slug}"
            f"/u/{unit.pk}/q/{element_pk}/check/"
        )

    def post_answer(element_pk, fields):
        """POST fields dict to check_answer; return response text (full-page HTML)."""
        body_parts = [("csrfmiddlewaretoken", csrf_token)] + list(fields.items())
        encoded_body = urllib.parse.urlencode(body_parts)
        resp = page.request.post(
            check_url(element_pk),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": lesson_url,
            },
            data=encoded_body,
        )
        assert resp.ok, (
            f"check_answer POST failed with status {resp.status}; "
            "check CSRF cookie, login state, and enrollment"
        )
        return resp.text()

    def load_html(html_text):
        """Load raw HTML into a fresh page in the same context; return that page."""
        result_page = ctx.new_page()
        result_page.set_content(html_text)
        return result_page

    # ── 1) Short-text: wrong answer → .is-incorrect ──────────────────────────
    html = post_answer(st_join.pk, {"answer": "London"})
    result = load_html(html)
    questions = result.locator("[data-question]")
    st_q = questions.nth(0)
    assert st_q.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect for wrong short-text answer (no-JS)"
    )
    # Repopulation: input value should be the submitted text
    assert st_q.locator("input[name='answer']").input_value() == "London", (
        "Expected answered short-text input to repopulate with 'London'"
    )
    result.close()

    # ── 2) Short-numeric: correct answer → .is-correct + repopulation ────────
    # Use comma-decimal to test the parse_number normaliser (3,15 is within tolerance
    # 0.01 of 3.14).
    html = post_answer(sn_join.pk, {"answer": "3,15"})
    result = load_html(html)
    questions = result.locator("[data-question]")
    sn_q = questions.nth(1)
    assert sn_q.locator(".is-correct").count() >= 1, (
        "Expected .is-correct for correct short-numeric answer (no-JS)"
    )
    # Repopulation: the answered numeric input keeps the typed value
    assert sn_q.locator("input[name='answer']").input_value() == "3,15", (
        "Expected answered short-numeric input to repopulate with '3,15'"
    )
    result.close()

    # ── 3) Fill-blank: correct answer → .is-correct + repopulation ───────────
    html = post_answer(fb_join.pk, {"blank": "Seine"})
    result = load_html(html)
    questions = result.locator("[data-question]")
    fb_q = questions.nth(2)
    assert fb_q.locator(".is-correct").count() >= 1, (
        "Expected .is-correct for correct fill-blank answer (no-JS)"
    )
    # Repopulation: the blank input keeps the typed value
    assert fb_q.locator("input[name='blank']").input_value() == "Seine", (
        "Expected answered fill-blank input to repopulate with 'Seine'"
    )
    result.close()

    ctx.close()
