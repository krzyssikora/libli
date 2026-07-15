"""Playwright e2e for the Multi-select grid question (multigrid).

One test, driving the REAL checkbox clicks (never page.evaluate shortcuts):
  LESSON: answer a multi-select grid — tick a *partially*-correct set in one row
  (all-or-nothing → wrong) and the *exact* set in another (→ correct) — and Check
  → immediate per-row feedback (one row answer-correct, one answer-wrong) whose
  reveal lists the wrong row's correct column set. One column label carries
  \\(x^2\\); a .katex node must render in the widget.

Marked e2e (excluded from the default run; run with -m e2e).
Harness mirrors test_e2e_choicegrid.py (fixtures, login, data-question locators).
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


def _seed_multigrid(username, slug, *, unit_type, max_attempts=0):
    """Seed a course + (lesson|quiz) unit holding one multi-select grid question.

    Two columns ("\\(x^2\\)" and "B") × two rows:
      row1 "r1" → correct = {x^2, B}   (both columns)
      row2 "r2" → correct = {B}        (single column)
    The author is enrolled so student answer POSTs are permitted.
    Returns (course, unit, element_join, col_x, col_b, row1, row2).
    """
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow
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
    q = MultiGridQuestionElement.objects.create(
        stem="<p>Tick every correct column</p>", max_attempts=max_attempts
    )
    col_x = MultiGridColumn.objects.create(question=q, label="\\(x^2\\)")
    col_b = MultiGridColumn.objects.create(question=q, label="B")
    row1 = MultiGridRow.objects.create(question=q, statement="r1")
    row1.correct_columns.set([col_x, col_b])
    row2 = MultiGridRow.objects.create(question=q, statement="r2")
    row2.correct_columns.set([col_b])
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el, col_x, col_b, row1, row2


@pytest.mark.django_db(transaction=True)
def test_multigrid_lesson_immediate_feedback(page, live_server):
    """LESSON: tick a partially-correct set (row1) and the exact set (row2), Check →
    immediate per-row all-or-nothing feedback.

    The verdict is .is-incorrect (row1 partial → wrong) and the reveal grid shows one
    correct row (✓) + one wrong row whose full correct column set is revealed. A
    \\(x^2\\) column label renders as a .katex node.
    """
    course, unit, el, col_x, col_b, row1, row2 = _seed_multigrid(
        "mg_lesson", "mg-lesson", unit_type="lesson"
    )
    _login(page, live_server, "mg_lesson")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first

    # The \(x^2\) column header must typeset to a .katex node (auto-render loaded via
    # _question_has_math scanning the column labels).
    q.locator(".katex").first.wait_for(timeout=6000)
    assert q.locator(".katex").count() >= 1, (
        "Expected the \\(x^2\\) column to render KaTeX"
    )

    # Row 1 → only x^2 (PARTIAL: correct set is {x^2, B}) → all-or-nothing wrong.
    # Row 2 → exactly B (correct). REAL checkbox clicks, never page.evaluate.
    q.locator(f"input[name='row_{row1.pk}'][value='{col_x.pk}']").check()
    q.locator(f"input[name='row_{row2.pk}'][value='{col_b.pk}']").check()
    assert q.locator(f"input[name='row_{row1.pk}'][value='{col_x.pk}']").is_checked()

    q.locator(".question__form button[type='submit']").click()

    # question.js fetches the feedback fragment into [data-question-feedback].
    feedback = q.locator("[data-question-feedback]")
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert feedback.locator(".is-incorrect").count() >= 1, (
        "Expected .is-incorrect verdict after a partially-correct multigrid row"
    )

    # Per-row reveal grid: one all-or-nothing correct row, one wrong row whose full
    # correct column set is revealed.
    reveal = feedback.locator(".question__reveal--grid")
    reveal.wait_for(timeout=6000)
    assert reveal.locator(".answer-correct").count() == 1, (
        "Expected exactly one correct row (r2 → exactly B)"
    )
    assert reveal.locator(".answer-wrong").count() == 1, (
        "Expected exactly one wrong row (r1 → only x^2 of {x^2, B})"
    )
    # The wrong row reveals its full correct column set (plain-text "B" is part of it).
    assert "B" in reveal.inner_text(), (
        "Expected the wrong row to reveal its correct column set (includes 'B')"
    )
