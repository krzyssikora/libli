"""Playwright e2e for Phase 5a subjects: PA creates a subject, student filters catalog.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    """Seed a Platform Admin with a verified email so allauth lets them log in."""
    from accounts.emails import ensure_verified_primary_email
    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username,
        email=f"{username}@school.edu",
        password=TEST_PASSWORD,
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    """Log in via the real allauth login form. Waits for the form to detach."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    # Wait for the redirect to complete before the caller navigates further.
    page.wait_for_selector("form[action*='login']", state="detached")


def _logout(page, live_server):
    """Log out via the real allauth logout confirm page (real UI gesture)."""
    page.goto(f"{live_server.url}/accounts/logout/")
    # allauth renders a confirm page; click the main "Sign Out" submit button.
    page.get_by_role("button", name="Sign Out").click()
    # After logout allauth redirects to the login page.
    page.wait_for_url("**/login/**", timeout=5000)


def _seed_open_course(subject):
    """Create a non-staff student + an open course (with a unit) using the given
    subject. Returns (student_username, course_title).

    The course has visibility="open" and empty self_enroll_cohorts so that
    catalog_courses_for() surfaces it for any non-staff student regardless of
    cohort membership."""
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username="e2e_subj_student", email="e2esubjstudent@school.edu"
    )
    course = CourseFactory(
        slug="e2e-geography-course",
        title="World Geography",
        visibility="open",
        subjects=[subject],
        overview="Explore the world.",
    )
    # Unit is required: catalog_courses_for filters Exists(ContentNode kind="unit").
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="Lesson 1"
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>hello</p>"),
    )
    return student.username, course.title


@pytest.mark.django_db(transaction=True)
def test_pa_creates_subject_and_student_filters_catalog(page, live_server):
    """PA creates "Geography" via the manage UI; student filters the catalog by
    that subject and sees the course linked to it."""
    # ── PA: create the subject via the real UI ────────────────────────────────
    _make_pa_user("e2e_subj_pa")
    _login(page, live_server, "e2e_subj_pa")

    # Navigate to Subjects list via the nav link, opening the "Admin" dropdown
    # the Subjects link now lives in.
    page.get_by_role("button", name="Admin").click()
    page.get_by_role("link", name="Subjects").click()
    page.wait_for_url("**/subjects/")

    # Click "New subject" and fill in the English title only (slug is auto-derived).
    page.get_by_role("link", name="New subject").click()
    page.wait_for_url("**/subjects/new/")
    page.fill("input[name='title_en']", "Geography")
    page.get_by_role("button", name="Save").click()

    # After save, redirected back to the list; "Geography" must appear.
    page.wait_for_url("**/subjects/")
    assert "Geography" in page.content(), (
        f"Expected 'Geography' in subject list after create; "
        f"got: {page.content()[:500]}"
    )

    # ── ORM: attach the UI-created subject to an open course ─────────────────
    # We use Subject.objects.get so the pk matches what the catalog dropdown
    # references — NOT a fresh SubjectFactory which would produce a different row.
    from courses.models import Subject

    geography = Subject.objects.get(title_en="Geography")
    student_username, course_title = _seed_open_course(geography)

    # ── Switch actor: log PA out before logging in as the student ─────────────
    # An authenticated user is redirected away from the login form, so a second
    # _login without logging out would time out.
    _logout(page, live_server)

    # ── Student: filter catalog by Geography, assert the course is listed ─────
    _login(page, live_server, student_username)
    page.goto(f"{live_server.url}/catalog/")

    # The select option text is Subject.title (returns title_en here because the
    # session runs under the EN locale and Geography has no title_pl).
    page.select_option("select[name='subject']", label="Geography")
    page.get_by_role("button", name="Filter").click()
    page.wait_for_load_state("networkidle")

    assert course_title in page.content(), (
        f"Expected course '{course_title}' in catalog after Geography filter; "
        f"got: {page.content()[:600]}"
    )
