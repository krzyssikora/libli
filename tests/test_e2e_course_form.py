"""Playwright e2e: the course form reveals the self-enrolment cohorts field only
when Visibility = Open (progressive enhancement). Without JS the field stays
visible (inert when Assigned). Marked e2e (excluded from the default run)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import CohortFactory
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
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_self_enroll_cohorts_visible_only_when_open(page, live_server):
    _make_pa_user("pa")
    CohortFactory(name="Class A")  # ensure the cohorts field renders ≥1 checkbox
    _login(page, live_server, "pa")
    page.goto(f"{live_server.url}/manage/courses/new/")
    page.wait_for_selector("#id_visibility")

    # Assert on the actual checkbox (not just the row wrapper) so a regression
    # where only the label hides — e.g. a block widget breaking out of its
    # wrapper — is caught.
    checkbox = page.locator('[name="self_enroll_cohorts"]').first
    # Visibility defaults to "Assigned" → the cohorts field starts hidden.
    assert checkbox.is_hidden()
    # Switch to Open → the field appears.
    page.select_option("#id_visibility", "open")
    assert checkbox.is_visible()
    # Switch back to Assigned → hidden again.
    page.select_option("#id_visibility", "assigned")
    assert checkbox.is_hidden()
