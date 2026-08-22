import pytest
from django.test import override_settings
from django.urls import reverse

from courses import media_fetch
from courses.models import MediaAsset
from courses.tests.test_media_fetch_transport import FakeResponse
from courses.tests.test_media_fetch_transport import png_bytes
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

WIKI = ["upload.wikimedia.org"]
URL = "https://upload.wikimedia.org/Foo.png"


@pytest.fixture(autouse=True)
def _isolated_media(settings, tmp_path):
    # This module drives the REAL fetch_image_asset -> create_asset, which writes the
    # original plus derivatives. Without this they land in the working tree's media/.
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def course_and_manager(client):
    """A logged-in course manager, via the repo's make_pa helper.

    Do NOT build this as UserFactory(...) + client.force_login(). UserFactory sets
    skip_postgeneration_save = True with password as a PostGenerationMethodCall, so
    set_password is NEVER PERSISTED -- the row's password stays "" while force_login
    stores the session hash of the in-memory hash. The next request's
    session-auth-hash check fails, the client is anonymous, and every test 302s to
    /accounts/login/. tests/test_notes_views.py:24-28 documents this exact trap.

    Access is owner-or-`courses.change_course` (courses/access.py:37-43, which says
    verbatim it does NOT key on is_staff), and make_pa supplies the Platform Admin
    group that carries the perm.
    """
    pa = make_pa(client, "pa")
    return CourseFactory(owner=pa), pa


def url_for(course):
    return reverse("courses:manage_media_fetch", kwargs={"slug": course.slug})


def patch_transport(monkeypatch):
    monkeypatch.setattr(media_fetch, "_open", lambda req, t: FakeResponse(png_bytes()))


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_success_returns_the_asset_cell(client, course_and_manager, monkeypatch):
    course, _ = course_and_manager
    patch_transport(monkeypatch)
    resp = client.post(url_for(course), {"url": URL}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200
    assert b"asset-cell" in resp.content
    assert MediaAsset.objects.filter(course=course).count() == 1


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_rejection_is_422_with_the_message(client, course_and_manager):
    course, _ = course_and_manager
    resp = client.post(
        url_for(course),
        {"url": "https://evil.com/x.png"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    assert b"That image host is not on the allow-list." in resp.content
    # str(ValidationError(...)) renders "['That image host is not...']" -- the list
    # repr also contains "allow-list", so a substring-only assertion passes on the
    # str(e) mutant. Pin the absence of the repr markers.
    assert b"[&#x27;" not in resp.content


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_missing_url_key_is_422_not_500(client, course_and_manager):
    """Bracket access on request.POST would raise MultiValueDictKeyError, which the
    view does not catch -- a 500 -- and it would make the error table's first row
    unreachable through any client."""
    course, _ = course_and_manager
    resp = client.post(url_for(course), {}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 422
    assert b"Enter an image URL" in resp.content


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_missing_name_key_succeeds(client, course_and_manager, monkeypatch):
    """The picker's shape: it sends no `name` key at all."""
    course, _ = course_and_manager
    patch_transport(monkeypatch)
    resp = client.post(url_for(course), {"url": URL}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 200


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_no_js_failure_redirects_with_a_message(client, course_and_manager):
    course, _ = course_and_manager
    resp = client.post(url_for(course), {"url": "https://evil.com/x.png"}, follow=True)
    assert resp.redirect_chain
    assert any("allow-list" in str(m) for m in resp.context["messages"])


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_no_js_success_redirects_to_manage_media(
    client, course_and_manager, monkeypatch
):
    """The success mirror of test_no_js_failure_redirects_with_a_message: a plain
    (no X-Requested-With) POST that succeeds redirects to manage_media rather than
    rendering the _asset_cell fragment, and still creates the asset."""
    course, _ = course_and_manager
    patch_transport(monkeypatch)
    resp = client.post(url_for(course), {"url": URL}, follow=True)
    assert resp.redirect_chain
    assert resp.redirect_chain[-1][0] == reverse(
        "courses:manage_media", kwargs={"slug": course.slug}
    )
    assert MediaAsset.objects.filter(course=course).count() == 1


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_authenticated_get_is_405(client, course_and_manager):
    """Falsifies "drop @require_POST entirely" -- NOT the decorator ORDER.

    With the order swapped, an authenticated GET still passes login_required and is
    then rejected by require_POST with 405, so this assertion holds on both builds.
    Only an anonymous GET distinguishes them; see the next test.
    """
    course, _ = course_and_manager
    assert client.get(url_for(course)).status_code == 405


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_anonymous_get_is_405_not_a_login_redirect(course_and_manager):
    """THIS is what pins @require_POST above @login_required.

    Correct order -> require_POST runs first -> 405 regardless of auth.
    Swapped      -> login_required runs first -> 302 to /accounts/login/.
    A fresh Client(), because the fixture logged the shared one in.
    """
    from django.test import Client

    course, _ = course_and_manager
    assert Client().get(url_for(course)).status_code == 405


@override_settings(ALLOWED_IMAGE_FETCH_DOMAINS=WIKI, ALLOW_HTTP_IMAGE_FETCH=False)
def test_non_manager_is_refused(client, course_and_manager):
    course, _ = course_and_manager
    # A SECOND client: `client` is already logged in as the PA by the fixture.
    # make_login(client, username) is the helper that creates a verified user AND
    # force_logins the given client (tests/factories.py:229). make_verified_user takes
    # (username, email, password) and NO client -- passing a Client as `username`
    # reaches create_user() and dies in normalize_username with a TypeError, and the
    # request would then be anonymous, giving a 302 to /accounts/login/ rather than
    # the 403 that _require_manage raises for an authenticated non-manager.
    from django.test import Client

    other = Client()
    make_login(other, "nobody")
    resp = other.post(url_for(course), {"url": URL})
    assert resp.status_code in (403, 404)
