"""Playwright e2e for Phase 5c: brand colour applied, upload extension narrowing,
and out-of-domain invite warning.

Marked `e2e` (excluded by default; run with -m e2e).
"""

import os

import pytest
from django.contrib.auth.models import Group as AuthGroup

from tests.factories import TEST_PASSWORD

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
    page.wait_for_selector("form[action*='login']", state="detached")


def _logout(page, live_server):
    """Log out via the real allauth logout confirm page (real UI gesture)."""
    page.goto(f"{live_server.url}/accounts/logout/")
    page.get_by_role("button", name="Sign Out").click()
    page.wait_for_url("**/login/**", timeout=5000)


@pytest.mark.django_db(transaction=True)
def test_brand_colour_upload_narrowing_invite_warning(page, live_server):
    """PA drives three sub-flows via the real /manage/settings/ UI:

    1. Sets primary brand colour to #ff0000; asserts --brand-primary CSS var is
       emitted by the {% brand_vars %} tag in <head>.
    2. Removes gif from allowed image types; proves MediaAsset.full_clean()
       rejects a gif (same path create_asset/media_upload takes). The
       media-manager JS flashes generic "Upload failed." for ANY error rather
       than surfacing the specific 422 body, so ORM full_clean() is the smallest
       reliable proof of extension rejection. (UI gap: media_picker.js line 246
       discards the server error — follow-up to expose it to the user.)
    3. Sets allowed domain to school.edu; invites someone@outside.com via the
       Invitations UI; asserts the non-blocking domain-mismatch warning appears.
    """
    _make_pa_user("e2e_5c_pa")
    _login(page, live_server, "e2e_5c_pa")

    # ── Sub-flow 1: Set primary brand colour to #ff0000 ──────────────────────
    page.goto(f"{live_server.url}/manage/settings/?tab=branding")
    # Wait until the branding tab panel is present and NOT hidden.
    page.wait_for_selector("[data-tab='branding']:not([hidden])")

    # The primary hex text field has data-hex="1" (set by _hex_field in forms.py).
    # Two colour pairs in order: primary, then accent. Fill the first one.
    primary_hex_input = page.locator("input[data-hex='1']").first
    primary_hex_input.fill("#ff0000")

    page.get_by_role("button", name="Save branding").click()
    page.wait_for_load_state("networkidle")

    # Reload to get a fresh server render so the {% brand_vars %} tag in <head>
    # reflects the newly-cached site config.
    page.goto(f"{live_server.url}/manage/settings/?tab=branding")
    content = page.content()
    assert "--brand-primary: #ff0000" in content, (
        "Expected '--brand-primary: #ff0000' in <style> from {% brand_vars %} after "
        f"saving primary colour; got (first 600 chars): {content[:600]}"
    )

    # ── Sub-flow 2: Narrow allowed image types (remove gif) ──────────────────
    page.goto(f"{live_server.url}/manage/settings/?tab=uploads")
    page.wait_for_selector("[data-tab='uploads']:not([hidden])")

    gif_checkbox = page.locator("input[name='allowed_image_extensions'][value='gif']")
    if gif_checkbox.is_checked():
        gif_checkbox.uncheck()

    page.get_by_role("button", name="Save upload settings").click()
    page.wait_for_load_state("networkidle")

    # Proof of extension rejection via ORM (see docstring for why, not browser upload).
    from django.core.exceptions import ValidationError
    from django.core.files.uploadedfile import SimpleUploadedFile

    from core.services import invalidate_site_config
    from courses.models import MediaAsset
    from tests.factories import CourseFactory

    # Ensure the test thread sees the fresh config (not a stale LocMemCache entry).
    invalidate_site_config()
    course = CourseFactory(slug="e2e-5c-gif-reject-course")
    # Minimal valid GIF89a header — just enough bytes for an UploadedFile.
    gif_bytes = (
        b"GIF89a\x01\x00\x01\x00\x00\xff\x00,"
        b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x00;"
    )
    gif_file = SimpleUploadedFile("test.gif", gif_bytes, content_type="image/gif")
    asset = MediaAsset(course=course, kind="image", file=gif_file)
    with pytest.raises(ValidationError, match="gif"):
        asset.full_clean()

    # ── Sub-flow 3: Access tab — domain allowlist + out-of-domain invite warning
    page.goto(f"{live_server.url}/manage/settings/?tab=access")
    page.wait_for_selector("[data-tab='access']:not([hidden])")

    domains_textarea = page.locator("textarea[name='allowed_email_domains']")
    domains_textarea.fill("school.edu")

    page.get_by_role("button", name="Save access settings").click()
    page.wait_for_load_state("networkidle")

    # Send an invitation to an address outside the allowed domain.
    page.goto(f"{live_server.url}/manage/people/invitations/")
    page.wait_for_selector("form.invite-form")

    page.locator("input[name='email']").fill("someone@outside.com")
    page.select_option("select[name='role']", value="Student")
    page.get_by_role("button", name="Send invitation").click()
    # invitation_send redirects to people_invitations on success; messages render there.
    page.wait_for_load_state("networkidle")

    content = page.content()
    assert "outside.com" in content, (
        "Expected out-of-domain warning mentioning 'outside.com' after inviting "
        f"someone@outside.com with school.edu allowlist; "
        f"got (first 600 chars): {content[:600]}"
    )
    assert "not in your allowed" in content, (
        "Expected 'not in your allowed' warning text after out-of-domain invite; "
        f"got (first 600 chars): {content[:600]}"
    )
