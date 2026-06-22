"""Playwright e2e for Phase-2e: the per-course quiz summary page.

Student in a 2-quiz course finishes ONE quiz, opens "My results" from the
outline, and sees: "Done 1 of 2", the taken quiz's score with a working
drill-down to its /quiz/results/ page, and the untaken quiz as "not started".

Marked e2e (run with -m e2e). Harness mirrors test_e2e_quiz.py.
"""

import os
from decimal import Decimal

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _build_two_quiz_course(student):
    from courses.models import Element
    from courses.models import ShortTextQuestionElement
    from tests.factories import CourseFactory
    from tests.factories import ContentNodeFactory
    from tests.factories import EnrollmentFactory

    course = CourseFactory()
    EnrollmentFactory(student=student, course=course)
    units = []
    for i in range(2):
        unit = ContentNodeFactory(
            course=course, kind="unit", unit_type="quiz", parent=None,
            title=f"Quiz {i + 1}",
        )
        q = ShortTextQuestionElement.objects.create(
            stem="2+2?", accepted="4", marking_mode="A", max_marks=Decimal("1")
        )
        Element.objects.create(unit=unit, content_object=q)
        units.append(unit)
    return course, units


@pytest.mark.django_db(transaction=True)
def test_results_summary_after_one_quiz(page, live_server):
    student = _make_student("e2eresults")
    course, units = _build_two_quiz_course(student)
    first = units[0]

    _login(page, live_server, "e2eresults")

    # Take the first quiz: answer correctly, then finish (accept the confirm dialog).
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{first.pk}/quiz/")
    # Wait for the question element to render before interacting.
    page.wait_for_selector("[data-question]")
    q = page.locator("[data-question]").first
    q.locator("input[name='answer']").fill("4")
    q.locator("button[type='submit']").click()
    # Wait for the answer to be processed (feedback appears) before finishing.
    # The finish button uses [data-finish-btn] as the authoritative selector
    # (mirrors test_e2e_quiz.py; the brief's form[action*='finish'] selector is
    # equivalent but less precise — use the data-attribute for robustness).
    # Register the confirm-dialog handler BEFORE the click so it fires immediately.
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)

    # Open My results from the outline.
    page.goto(f"{live_server.url}/courses/{course.slug}/")
    # The outline renders: <a href="/courses/<slug>/results/">📊 My results</a>
    page.locator("a[href$='/results/']").first.click()
    page.wait_for_url(f"**/courses/{course.slug}/results/")

    body = page.content()
    # The template renders: "Done 1 of 2 quizzes" — "Done 1 of 2" is a substring.
    assert "Done 1 of 2" in body, f"Expected 'Done 1 of 2' headline in: {body[:500]}"
    # The taken quiz drills down to its per-quiz results page.
    details = page.locator(f"a[href='/courses/{course.slug}/u/{first.pk}/quiz/results/']")
    assert details.count() == 1, (
        f"Expected exactly 1 drill-down link for quiz {first.pk}; got {details.count()}"
    )
    # The untaken quiz shows the not-started cue.
    assert "not started" in body, f"Expected 'not started' for untaken quiz in: {body[:500]}"
