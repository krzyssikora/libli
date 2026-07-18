"""Playwright e2e: a restored-correct question hides its Check button on load.

`question.js` runs a boot pass, after the submit-wiring loop, that hides the
Check/Submit button for any question WITH a live form whose form already shows
`.question__verdict.is-correct` on load (a server-side restore of a
previously-correct answer, or a fresh-page re-render). Form-less blocks
(results/review pages) are untouched by construction (the `if (!form) return;`
guard).

Drives the REAL student gesture end-to-end: types into the answer input and
clicks the actual Check button (never page.evaluate to fake the answer -- this
repo's standing lesson is that an e2e bypassing the real gesture ships broken
UX green). Awaits the check POST response before reloading so the fire-and-
forget persistence (courses/views.py:check_answer -> save_element_state) lands
before the page reloads.

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in tests/test_e2e_fillgate.py / tests/test_e2e_questions_2b.py
(login helper, ContentNodeFactory/CourseFactory/EnrollmentFactory unit setup).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    """Log in via the allauth HTML form (works with JS enabled or disabled)."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _new_shorttext_unit(username):
    """An enrolled student + a lesson unit with one ShortTextQuestionElement
    (accepted="paris"). Returns (student, unit)."""
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import add_element

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Lesson"
    )
    obj = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of France?</p>", accepted="paris"
    )
    add_element(unit, obj)
    EnrollmentFactory(student=student, course=course)
    return student, unit


def _unit_url(live_server, unit):
    from django.urls import reverse

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    return f"{live_server.url}{path}"


@pytest.mark.django_db(transaction=True)
def test_correct_answer_hides_check_after_reload(page, live_server):
    """Case A: answer correctly, check, reload -> answer shown, is-correct verdict,
    AND the Check button is hidden (the boot pass)."""
    student, unit = _new_shorttext_unit("qr_correct")
    _login(page, live_server, "qr_correct")
    page.goto(_unit_url(live_server, unit))
    page.wait_for_selector("[data-question]")

    question_el = page.locator("[data-question]").first
    answer_input = question_el.locator("input[name='answer']")
    check_btn = question_el.locator("button[type='submit']")

    answer_input.fill("paris")
    with page.expect_response(lambda r: "/check/" in r.url):
        check_btn.click()

    expect(question_el.locator(".question__verdict.is-correct")).to_be_visible()

    page.reload()
    page.wait_for_selector("[data-question]")
    question_el = page.locator("[data-question]").first
    expect(question_el.locator("input[name='answer']")).to_have_value("paris")
    expect(question_el.locator(".question__verdict.is-correct")).to_be_visible()
    expect(question_el.locator("button[type='submit']")).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_incorrect_answer_keeps_check_visible_after_reload(page, live_server):
    """Case B: answer incorrectly, reload -> answer shown, is-incorrect verdict,
    Check button STILL visible (no restored-correct verdict to hide it)."""
    student, unit = _new_shorttext_unit("qr_wrong")
    _login(page, live_server, "qr_wrong")
    page.goto(_unit_url(live_server, unit))
    page.wait_for_selector("[data-question]")

    question_el = page.locator("[data-question]").first
    answer_input = question_el.locator("input[name='answer']")
    check_btn = question_el.locator("button[type='submit']")

    answer_input.fill("london")
    with page.expect_response(lambda r: "/check/" in r.url):
        check_btn.click()

    expect(question_el.locator(".question__verdict.is-incorrect")).to_be_visible()

    page.reload()
    page.wait_for_selector("[data-question]")
    question_el = page.locator("[data-question]").first
    expect(question_el.locator("input[name='answer']")).to_have_value("london")
    expect(question_el.locator(".question__verdict.is-incorrect")).to_be_visible()
    expect(question_el.locator("button[type='submit']")).to_be_visible()
