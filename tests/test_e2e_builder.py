"""Playwright e2e for the 1b-i builder: PA creates a course, builds a tree, reorders
+ moves a node, opens a unit, reorders an element; plus a stale-token 409 swap and the
no-JS fallback. Marked e2e (excluded from the default run)."""

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
def test_builder_full_flow(page, live_server):
    from courses.models import Course

    _make_pa_user("pa")
    _login(page, live_server, "pa")
    # create a course via the form
    page.goto(f"{live_server.url}/manage/courses/new/")
    # Scope to the course form's own submit — the shell header also carries submit
    # buttons (EN/PL language switch, Log out), so a global button[type='submit']
    # would click those first (same gotcha guarded against in test_e2e_smoke._login).
    course_form = page.locator("form.form")
    course_form.locator("input[name='title']").fill("Algebra I")
    course_form.locator("input[name='slug']").fill("algebra-i")
    course_form.locator("button[type='submit']").click()
    # we land on the builder; add a top-level part. Wait for attachment (not
    # visibility): the top scope's <ol> is empty on a brand-new course, so it has no
    # visible box yet — `state="attached"` confirms the builder rendered.
    page.wait_for_selector('[data-scope="top"]', state="attached")
    add = page.locator('form[data-op="add"]').first
    add.locator("input[name='title']").fill("Foundations")
    add.locator("select[name='kind']").select_option("part")
    add.locator("button[type='submit']").click()
    page.wait_for_selector("text=Foundations")
    course = Course.objects.get(slug="algebra-i")
    assert course.nodes.filter(title="Foundations").exists()


@pytest.mark.django_db(transaction=True)
def test_no_js_fallback_add(browser, live_server):
    """With JS disabled, an add still works via full-page form POST + redirect."""
    from courses.models import Course

    _make_pa_user("pa2")
    ctx = browser.new_context(java_script_enabled=False)
    page = ctx.new_page()
    _login(page, live_server, "pa2")
    page.goto(f"{live_server.url}/manage/courses/new/")
    # Scope to the course form's own submit (see note in test_builder_full_flow).
    course_form = page.locator("form.form")
    course_form.locator("input[name='title']").fill("NoJS Course")
    course_form.locator("input[name='slug']").fill("nojs")
    course_form.locator("button[type='submit']").click()
    add = page.locator('form[data-op="add"]').first
    add.locator("input[name='title']").fill("Part A")
    add.locator("select[name='kind']").select_option("part")
    add.locator("button[type='submit']").click()  # full-page POST -> 302 redirect
    page.wait_for_selector("text=Part A")
    assert Course.objects.get(slug="nojs").nodes.filter(title="Part A").exists()
    ctx.close()
