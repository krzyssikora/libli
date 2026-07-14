"""Playwright e2e for the Matrix question (choicegrid).

Two tests, driving the REAL radio clicks (never page.evaluate shortcuts):
  1. LESSON: answer a matrix (one row right, one wrong) and Check → immediate
     per-row feedback + the reveal grid shows the wrong row's correct column.
  2. QUIZ: a wrong answer with attempts remaining WITHHOLDS the correct columns;
     Finish → the per-quiz results page reveals the correct columns.

Marked e2e (excluded from the default run; run with -m e2e).
Harness mirrors test_e2e_quiz.py / test_e2e_questions_2d.py (fixtures, login,
data-question locators, [data-finish-btn] + confirm dialog on finish).
"""

import os

import pytest

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


def _seed_matrix(username, slug, *, unit_type, max_attempts=0):
    """Seed a course + (lesson|quiz) unit holding one True/False matrix question.

    Two statements: "2+2=4" (correct = True), "5 is even" (correct = False).
    The author is enrolled so student answer POSTs are permitted.
    Returns (course, unit, element_join, col_true, col_false, row1, row2).
    """
    from courses.models import ChoiceGridQuestionElement
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import GridColumn
    from courses.models import GridRow
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="U"
    )
    q = ChoiceGridQuestionElement.objects.create(
        stem="<p>Classify each statement</p>", max_attempts=max_attempts
    )
    col_true = GridColumn.objects.create(question=q, label="True")
    col_false = GridColumn.objects.create(question=q, label="False")
    row1 = GridRow.objects.create(
        question=q, statement="2+2=4", correct_column=col_true
    )
    row2 = GridRow.objects.create(
        question=q, statement="5 is even", correct_column=col_false
    )
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el, col_true, col_false, row1, row2


@pytest.mark.django_db(transaction=True)
def test_matrix_lesson_immediate_feedback(page, live_server):
    """LESSON: click radios (row1 correct, row2 wrong), Check → immediate feedback.

    The verdict is .is-incorrect (one row wrong) and the reveal grid shows one
    correct row (✓) + one wrong row whose correct column ("False") is revealed.
    """
    course, unit, el, col_true, col_false, row1, row2 = _seed_matrix(
        "cg_lesson", "cg-lesson", unit_type="lesson"
    )
    _login(page, live_server, "cg_lesson")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first
    # Row 1 → True (correct); Row 2 → True (wrong; correct is False). REAL radio clicks.
    q.locator(f"input[name='row_{row1.pk}'][value='{col_true.pk}']").check()
    q.locator(f"input[name='row_{row2.pk}'][value='{col_true.pk}']").check()
    assert q.locator(f"input[name='row_{row1.pk}'][value='{col_true.pk}']").is_checked()

    q.locator(".question__form button[type='submit']").click()

    # question.js fetches the feedback fragment into [data-question-feedback].
    feedback = q.locator("[data-question-feedback]")
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect verdict after a partially-wrong matrix answer"
    )

    # Per-row reveal grid: one correct row, one wrong row with its correct column shown.
    reveal = feedback.locator(".question__reveal--grid")
    reveal.wait_for(timeout=6000)
    assert reveal.locator(".answer-correct").count() == 1, (
        "Expected exactly one correct row (2+2=4 → True)"
    )
    assert reveal.locator(".answer-wrong").count() == 1, (
        "Expected exactly one wrong row (5 is even → chose True)"
    )
    # The wrong row reveals its correct column label.
    assert "False" in reveal.inner_text(), (
        "Expected the wrong row to reveal its correct column ('False')"
    )


@pytest.mark.django_db(transaction=True)
def test_matrix_quiz_withhold_then_results(browser, live_server):
    """QUIZ: a wrong answer (attempts remaining) withholds the correct columns;
    finishing the quiz reveals them on the per-quiz results page."""
    # max_attempts=2 so a single wrong answer leaves an attempt in hand: the quiz
    # withholds the correct columns (not locked) until the student finishes.
    course, unit, el, col_true, col_false, row1, row2 = _seed_matrix(
        "cg_quiz", "cg-quiz", unit_type="quiz", max_attempts=2
    )
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "cg_quiz")

    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first
    # Both rows wrong: row1 → False (correct True), row2 → True (correct False).
    q.locator(f"input[name='row_{row1.pk}'][value='{col_false.pk}']").check()
    q.locator(f"input[name='row_{row2.pk}'][value='{col_true.pk}']").check()
    q.locator(".question__form button[type='submit']").click()

    # Wrong on a quiz with attempts remaining → incorrect verdict, correct columns
    # WITHHELD (the reveal grid must not render inside the feedback panel).
    feedback = q.locator("[data-question-feedback]")
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".question__reveal--grid").count() == 0, (
        "Correct columns must be withheld while quiz attempts remain"
    )

    # Finish the quiz (confirm dialog) → per-quiz results page.
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)

    # The results page reveals the correct columns for the incorrectly-answered matrix.
    reveal = page.locator(".question__reveal--grid")
    reveal.wait_for(timeout=6000)
    reveal_text = reveal.inner_text()
    assert "True" in reveal_text and "False" in reveal_text, (
        "Results page must reveal both rows' correct columns (True / False)"
    )
    assert reveal.locator(".answer-wrong").count() == 2, (
        "Both rows were answered wrong → two revealed correct columns"
    )

    ctx.close()
