"""Playwright e2e for the self-enroll catalog. Marked `e2e` (excluded by default)."""

import os

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed_open_course():
    """Verified student (in Default cohort) + open course with a unit, no enrollment."""
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import SubjectFactory
    from tests.factories import make_verified_user

    make_verified_user(username="e2ecat", email="e2ecat@school.edu")
    course = CourseFactory(
        slug="e2e-open",
        title="E2E Open Course",
        visibility="open",
        subjects=[SubjectFactory(title_en="Science")],
        overview="A great course.",
    )
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="U1"
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="<p>hi</p>"),
    )
    return "e2ecat", course.slug


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    # Wait for the login POST/redirect to finish before navigating on, else the
    # next page.goto can race the redirect and land back on the login page.
    page.wait_for_selector("form[action*='login']", state="detached")


@pytest.mark.django_db(transaction=True)
def test_browse_open_modal_enroll_lands_on_outline(page, live_server):
    username, slug = _seed_open_course()
    _login(page, live_server, username)

    # Browse the catalog and open the overview modal via the real Details click.
    page.goto(f"{live_server.url}/catalog/")
    page.get_by_role("link", name="Details").first.click()

    # Modal shows the overview with a live Enroll button; click it (real gesture).
    modal = page.locator("[data-catalog-modal]")
    modal.get_by_role("button", name="Enroll").click()

    # Lands on the course outline; the course is now in "My courses".
    page.wait_for_url(f"**/courses/{slug}/")
    assert "E2E Open Course" in page.content()
