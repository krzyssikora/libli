"""Playwright e2e for the lesson consumption path.

Marked `e2e` (excluded by default).
"""

import os

import pytest

from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _seed_enrolled_lesson():
    """Build a verified, enrolled student + a one-element lesson.

    Returns (username, slug, node_pk, el_pk).
    """
    from courses.models import Element
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import make_verified_user

    user = make_verified_user(username="e2elearner", email="e2el@school.edu")
    course = CourseFactory(slug="e2e-course", language="en")
    EnrollmentFactory(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", title="E2E Lesson"
    )
    text = TextElement.objects.create(body="<p>read me</p>")
    el = Element.objects.create(unit=unit, content_object=text)
    return "e2elearner", course.slug, unit.pk, el.pk


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_lesson_autocompletes_on_view(page, live_server):
    username, slug, node_pk, el_pk = _seed_enrolled_lesson()
    _login(page, live_server, username)
    failures = []
    page.on("response", lambda r: failures.append(r.url) if r.status >= 400 else None)
    page.goto(f"{live_server.url}/courses/{slug}/u/{node_pk}/")
    assert page.locator(f'[data-element-id="{el_pk}"]').is_visible()
    # The single element is on-screen at load -> progress.js flushes -> auto-complete.
    page.wait_for_timeout(1200)  # > 500ms debounce + request
    from courses.models import UnitProgress

    assert UnitProgress.objects.get(unit_id=node_pk).completed is True
    asset_failures = [
        u for u in failures if any(u.endswith(x) for x in (".css", ".js", ".woff2"))
    ]
    assert asset_failures == [], asset_failures


@pytest.mark.django_db(transaction=True)
def test_mark_done_fallback_completes(page, live_server):
    username, slug, node_pk, el_pk = _seed_enrolled_lesson()
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/courses/{slug}/u/{node_pk}/")
    page.locator("form.unit-progress button[type='submit']").click()
    from courses.models import UnitProgress

    assert UnitProgress.objects.get(unit_id=node_pk).completed is True
