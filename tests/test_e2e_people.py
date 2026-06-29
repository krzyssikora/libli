"""Playwright e2e for Phase 5b: PA invites a Teacher, accepts, changes role,
deactivates. Marked `e2e` (run with -m e2e)."""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from accounts.models import Invitation
from accounts.models import User
from tests.factories import TEST_PASSWORD

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from accounts.emails import ensure_verified_primary_email
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = User.objects.create_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(user, f"{username}@school.edu")
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_selector("form[action*='login']", state="detached")


def _logout(page, live_server):
    """Log out via the real allauth logout confirm page (real UI gesture)."""
    page.goto(f"{live_server.url}/accounts/logout/")
    page.get_by_role("button", name="Sign Out").click()
    page.wait_for_url("**/login/**", timeout=5000)


@pytest.mark.django_db(transaction=True)
def test_pa_invites_teacher_then_changes_role_and_deactivates(page, live_server):
    _make_pa_user("e2e_people_pa")
    _login(page, live_server, "e2e_people_pa")

    # Go to People -> Invitations, send a Teacher invite via the real form.
    page.get_by_role("link", name="People").click()
    page.wait_for_url("**/manage/people/")
    page.get_by_role("link", name="Invitations").click()
    page.wait_for_url("**/manage/people/invitations/")
    page.fill("input[name='email']", "newteacher@school.edu")
    page.select_option("select[name='role']", value="Teacher")
    page.get_by_role("button", name="Send invitation").click()
    page.wait_for_load_state("networkidle")
    assert "newteacher@school.edu" in page.content()

    # Log the PA out first: accept_invite redirects an AUTHENTICATED user away and
    # consumes nothing, so the accept form would never render otherwise.
    _logout(page, live_server)

    # Accept the invite as the invitee via the real accept page.
    inv = Invitation.objects.get(email="newteacher@school.edu")
    page.goto(f"{live_server.url}/invite/accept/{inv.token}/")
    page.fill("input[name='username']", "newteacher")
    page.fill("input[name='password']", "Sufficiently-long-pw-9")
    page.get_by_role(
        "button", name="Create account"
    ).click()  # accept_invite submit label
    page.wait_for_load_state("networkidle")

    newteacher = User.objects.get(username="newteacher")
    assert list(newteacher.groups.values_list("name", flat=True)) == ["Teacher"]

    # The invitee is now logged in; log them out before re-logging in as the PA.
    _logout(page, live_server)

    # Back as PA: change the user's role to Student via the edit form.
    _login(page, live_server, "e2e_people_pa")
    page.goto(f"{live_server.url}/manage/people/users/{newteacher.pk}/edit/")
    page.select_option("select[name='role']", value="Student")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url("**/manage/people/")
    newteacher.refresh_from_db()
    assert list(newteacher.groups.values_list("name", flat=True)) == ["Student"]

    # Deactivate the user via the edit page button.
    page.goto(f"{live_server.url}/manage/people/users/{newteacher.pk}/edit/")
    page.get_by_role("button", name="Deactivate").click()
    page.wait_for_load_state("networkidle")
    newteacher.refresh_from_db()
    assert newteacher.is_active is False
