"""Playwright e2e for Phase-3c-i: the teacher quiz-review journey.

A student submits a quiz containing an UNANSWERED [R] question; the teacher
(course owner) opens the review queue, opens the submission, grades the [R]
with marks + a comment (real form submit) → quiz finalizes; the student then
sees the score and the comment on their results page.
Exercises the subtle unanswered-[R] finalization path with real gestures.
"""

import os
from decimal import Decimal

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_pa
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _logout(page, live_server):
    """Log out via the real allauth logout confirm page (real UI gesture)."""
    page.goto(f"{live_server.url}/accounts/logout/")
    # allauth renders a confirm page; click the main "Sign Out" submit button.
    # The navbar also has a logout form, so be specific: use the role + name.
    page.get_by_role("button", name="Sign Out").click()
    # After logout, allauth redirects to ACCOUNT_LOGOUT_REDIRECT_URL (account_login).
    page.wait_for_url("**/login/**", timeout=5000)


def _build_course_with_review_quiz(owner):
    from courses.models import Element
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    course = CourseFactory(owner=owner)
    student = make_verified_user(
        username="e2erevstu", email="e2erevstu@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=None,
        title="Essay quiz",
    )
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss the causes.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    Element.objects.create(unit=unit, content_object=q)
    return course, unit, student


@pytest.mark.django_db(transaction=True)
def test_teacher_reviews_unanswered_review_question(page, live_server, client):
    # Owner is a Platform Admin (make_pa wires the role); also set as course owner.
    owner = make_pa(client, "e2erevowner")
    course, unit, student = _build_course_with_review_quiz(owner)

    # 1) Student opens the quiz and finishes WITHOUT answering the [R] question.
    _login(page, live_server, "e2erevstu")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    page.wait_for_selector("[data-question]")
    # Register the confirm-dialog handler BEFORE the click so it fires immediately.
    # Mirrors the exact pattern from test_e2e_quiz.py and test_e2e_results.py.
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=8000)

    # 2) Teacher logs in, opens the review queue, opens the submission.
    from courses.models import QuizSubmission

    sub = QuizSubmission.objects.get(student=student, unit=unit)
    _logout(page, live_server)
    _login(page, live_server, "e2erevowner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review-queue/")
    assert "Essay quiz" in page.content(), (
        f"Expected 'Essay quiz' in review queue page; got: {page.content()[:500]}"
    )
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review/{sub.pk}/")

    # 3) Grade the unanswered [R]: enter marks + a comment, save (real form submit).
    # The template renders one <article> per [R] question with a form containing
    # hidden element_pk, earned_marks input, and feedback textarea.
    # Submitting exercises the full review_submission POST path.
    page.locator("input[name='earned_marks']").fill("4")
    page.locator("textarea[name='feedback']").fill("Solid, expand the second point.")
    # The review form has a "Save" submit button (btn--primary). Use role+name to
    # distinguish it from the navbar logout and language-switcher submit buttons.
    page.get_by_role("button", name="Save").click()
    # The view redirects back to the same review/<pk>/ URL on success.
    page.wait_for_url(f"**/review/{sub.pk}/", timeout=8000)

    # 4) Student sees the score + comment on their results page.
    _logout(page, live_server)
    _login(page, live_server, "e2erevstu")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/results/")
    body = page.content()
    assert "Solid, expand the second point." in body, (
        f"Expected teacher feedback comment in student results page; got: {body[:500]}"
    )


@pytest.mark.django_db(transaction=True)
def test_roster_switch_and_force_submit_all(page, live_server, client):
    """Roster shows, Next-to-review link navigates to the correct submission,
    Force-submit-all (with real confirm dialog) submits every in-progress quiz."""
    from courses.models import QuizSubmission
    from tests.factories import EnrollmentFactory

    owner = make_pa(client, "rosterowner")
    # _build_course_with_review_quiz creates the course, quiz unit (with one [R]
    # question), and an initial student (e2erevstu, enrolled but no submission).
    course, unit, _ = _build_course_with_review_quiz(owner)

    # Seed three students by display_name order so the roster sorts deterministically:
    #   "alpha"   -> SUBMITTED, unreviewed (to_review)  <- the page we open
    #   "bravo"   -> SUBMITTED, unreviewed (to_review)  <- Next-to-review target
    #   "charlie" -> IN_PROGRESS                        <- Force-submit target
    alpha = make_verified_user(
        username="rosteralpha", email="rosteralpha@t.example.com"
    )
    alpha.display_name = "alpha"
    alpha.save()
    EnrollmentFactory(student=alpha, course=course)
    alpha_sub = QuizSubmission.objects.create(
        student=alpha, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )

    bravo = make_verified_user(
        username="rosterbravo", email="rosterbravo@t.example.com"
    )
    bravo.display_name = "bravo"
    bravo.save()
    EnrollmentFactory(student=bravo, course=course)
    bravo_sub = QuizSubmission.objects.create(
        student=bravo, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )

    charlie = make_verified_user(
        username="rostercharlie", email="rostercharlie@t.example.com"
    )
    charlie.display_name = "charlie"
    charlie.save()
    EnrollmentFactory(student=charlie, course=course)
    charlie_sub = QuizSubmission.objects.create(
        student=charlie, unit=unit, status=QuizSubmission.Status.IN_PROGRESS
    )

    _login(page, live_server, "rosterowner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review/{alpha_sub.pk}/")

    # Roster renders.
    assert page.locator(".review-roster").is_visible()
    page.locator("text=Submissions").wait_for(timeout=4000)

    # "Next to review" is an <a> (not the disabled <span> end-state); click it.
    # bravo is the next to_review after alpha in name order.
    next_link = page.locator(".review-foot a.btn--primary")
    assert next_link.count() == 1
    next_link.click()
    page.wait_for_load_state("networkidle")
    assert f"/review/{bravo_sub.pk}/" in page.url

    # Force-submit all: register the confirm handler BEFORE the click so it fires
    # synchronously, then click the real button (real browser gesture, not evaluate).
    page.once("dialog", lambda d: d.accept())
    page.locator(".review-topbar button[type='submit']").click()
    page.wait_for_load_state("networkidle")
    charlie_sub.refresh_from_db()
    assert charlie_sub.status == QuizSubmission.Status.SUBMITTED
    # After force-submit, no in-progress submissions remain -> group heading gone.
    assert page.locator("text=In progress").count() == 0


@pytest.mark.django_db(transaction=True)
def test_roster_collapse_persists_and_can_reexpand(page, live_server, client):
    """Collapse toggle adds html.review-roster-collapsed; the class persists
    across a full page reload via localStorage + pre-paint script; clicking again
    removes it (re-expand)."""
    from courses.models import QuizSubmission

    owner = make_pa(client, "collapseowner")
    course, unit, student = _build_course_with_review_quiz(owner)
    # One submitted student so the review page opens and the roster renders.
    some_sub = QuizSubmission.objects.create(
        student=student, unit=unit, status=QuizSubmission.Status.SUBMITTED
    )
    _login(page, live_server, "collapseowner")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/review/{some_sub.pk}/")

    toggle = page.locator("[data-roster-toggle]")
    toggle.click()  # collapse — real gesture, no page.evaluate shortcut
    assert page.locator("html.review-roster-collapsed").count() == 1
    # The toggle must stay visible in the sliver rail so the user can re-expand.
    assert toggle.is_visible()

    page.reload()  # localStorage + pre-paint script restores the collapsed state
    assert page.locator("html.review-roster-collapsed").count() == 1
    assert toggle.is_visible()

    toggle.click()  # re-expand
    assert page.locator("html.review-roster-collapsed").count() == 0
