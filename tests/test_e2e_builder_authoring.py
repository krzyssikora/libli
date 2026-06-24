"""Playwright e2e for builder-authoring-UX Task 1: + Lesson / + Quiz chips.
The test creates a chapter first (at top scope the unit chips are chip--overflow,
hidden until the +… toggle is clicked), then adds a unit INSIDE the chapter where
primary=None so + Lesson / + Quiz render as plain visible chips.
Marked e2e (excluded from the default run)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


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
    # Selectors mirror the proven helper in tests/test_e2e_smoke.py (allauth's login
    # field is name="login"); reuse that known-good pattern rather than guessing.
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_add_quiz_unit_via_chip(page, live_server):
    """Click '+ Quiz' chip inside a chapter scope and confirm a quiz unit is created."""
    from courses.models import ContentNode

    _make_pa_user("pa_authoring")
    _login(page, live_server, "pa_authoring")

    # Create a course via the form.
    page.goto(f"{live_server.url}/manage/courses/new/")
    course_form = page.locator("form.form")
    course_form.locator("input[name='title']").fill("Authoring Test Course")
    course_form.locator("input[name='slug']").fill("authoring-test")
    course_form.locator("button[type='submit']").click()

    # Wait for builder to load.
    page.wait_for_selector('[data-scope="top"]', state="attached")

    # Step 1: add a chapter at top scope via the primary chip (always visible).
    top_add = page.locator('[data-add-scope="top"]').first
    top_add.locator('button[data-add-kind="chapter"]').click()
    top_add.locator("input[data-add-title]").fill("Chapter One")
    top_add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector("text=Chapter One")

    # Step 2: add a Quiz unit INSIDE the chapter.
    # After the chapter row appears, the builder renders its child add-row with
    # data-add-scope=<chapter_pk>. Under a chapter, primary=None so + Lesson / + Quiz
    # are plain visible chips (no chip--overflow hiding).
    # The chapter's add-row is the first add-row that is NOT the top-scope add-row.
    chapter_add = (
        page.locator('form[data-op="add"]')
        .filter(has_not=page.locator('[data-add-scope="top"]'))
        .first
    )
    chapter_add.locator('button[data-add-kind="quiz"]').click()
    chapter_add.locator("input[data-add-title]").fill("Quiz One")
    chapter_add.locator("input[data-add-title]").press("Enter")
    page.wait_for_selector("text=Quiz One")

    # Verify the node was created with the correct kind and unit_type.
    from courses.models import Course

    course = Course.objects.get(slug="authoring-test")
    quiz_node = ContentNode.objects.get(course=course, title="Quiz One")
    assert quiz_node.kind == "unit"
    assert quiz_node.unit_type == "quiz"
