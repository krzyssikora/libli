"""Behaviour of the illustrated 404 / 403 pages.

Django forces DEBUG=False under test, so client.get() renders the REAL
templates -- no override_settings needed.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_404_renders_the_illustrated_page(client):
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404
    body = resp.content
    assert b"Nothing here" in body
    # b"..." not "...".encode() -- this string is ASCII, and ruff's UP012 rejects
    # a redundant encode. Reserve .encode() for the Polish assertions in Task 5.
    assert b"We appreciate your eagerness to discover" in body
    assert b"report it to your administrator" in body
    assert b"couldn" not in body.split(b"<main")[1], "old copy still present"
    # The action row -- label AND target in ONE assertion, because neither half
    # stands alone: base.html's brand link is already href="/" (a bare href
    # assertion is vacuous), and a bare label assertion would happily tolerate a
    # button that points nowhere. `landing` reverses to "/".
    assert b'<a class="btn" href="/">Back to main page</a>' in body


def test_404_echoes_the_attempted_path_in_a_code_element(client):
    resp = client.get("/no-such-page/")
    # Deliberately NOT a bare substring check: base.html's language-switch form
    # renders <input type="hidden" name="next" value="{{ request.path }}"> on
    # every page, so "/no-such-page/" is already in the body whether or not the
    # path line exists. Assert the element.
    assert b"<code>/no-such-page/</code>" in resp.content


def test_404_never_emits_a_raw_tag_from_the_attempted_path(client):
    # quote() in Django's page_not_found percent-encodes < > " ' & ( ) BEFORE the
    # template sees the value, so this cannot catch a stray |safe (the bytes are
    # identical either way). What it DOES catch is someone swapping
    # {{ request_path }} for the un-quoted {{ request.path }}.
    # Note: a bare b"<script>" assertion would be vacuous -- base.html emits
    # three literal <script> tags of its own.
    resp = client.get("/x/<script>alert(1)</script>/")
    assert resp.status_code == 404
    assert b"<script>alert" not in resp.content
    assert b"%3Cscript%3Ealert" in resp.content


def test_404_is_wired_to_the_error_page_stylesheet_and_classes(client):
    # All THREE block overrides, because none is implied by the prose assertions
    # above -- delete any one of them and every other test in this file still
    # passes while the page breaks visibly. Verified by deletion:
    #   extra_css   -> no stylesheet at all
    #   body_class  -> no watermark, no body flex column
    #   main_class  -> content pinned to the top instead of centred, AND painted
    #                  OVER by the fixed watermark (main loses z-index: 1)
    resp = client.get("/no-such-page/")
    assert b"core/css/error.css" in resp.content
    assert b'class="error-page"' in resp.content
    assert b'class="app-main error-page__main"' in resp.content


def _no_access(client, username="outsider"):
    """A logged-in user with NO access to a course, plus that course.

    courses/access.py grants access on is_staff OR owner OR enrolled OR
    teaching a non-archived group on the course -- "no access" is four
    negatives. Three are asserted below; the fourth (teaches no group attached
    to this course) is structurally impossible here because make_course()
    creates no groups at all, so there is nothing to assert against.

    Note `owner=UserFactory()` is explicit and load-bearing: CourseFactory
    declares no owner and Course.owner is null=True, so a bare make_course()
    yields course.owner IS NONE -- an *unowned* course, not one owned by
    somebody else, and `course.owner != user` would then pass trivially.
    """
    from tests.factories import UserFactory
    from tests.factories import make_course
    from tests.factories import make_login

    user = make_login(client, username)
    course = make_course(owner=UserFactory())
    assert not user.is_staff and not user.is_superuser
    assert course.owner is not None and course.owner != user
    assert not course.enrollments.filter(student=user).exists()
    return user, course


def test_403_renders_the_illustrated_page(client):
    from django.urls import reverse

    _, course = _no_access(client)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    assert resp.status_code == 403
    assert b"Not for you" in resp.content
    assert b"have permission to open it" in resp.content
    # Same three-block wiring guard as the 404 -- prose assertions imply none of
    # them, and dropping main_class silently paints content under the watermark.
    assert b"core/css/error.css" in resp.content
    assert b'class="error-page"' in resp.content
    assert b'class="app-main error-page__main"' in resp.content


def test_403_hides_the_login_action_from_an_authenticated_user(client):
    from django.urls import reverse

    _, course = _no_access(client)
    resp = client.get(reverse("courses:course_outline", args=[course.slug]))
    # The status + positive marker are what make this falsifiable. With only the
    # negative assertion the test would also pass on a 302 to login, on a 200
    # because the fixture accidentally granted access, and -- worst -- against
    # the OLD template, which has no login link either.
    assert resp.status_code == 403
    assert b"Not for you" in resp.content
    assert b"/accounts/login/?next=" not in resp.content
    # ...and the arm still offers a way out. This is the arm essentially every
    # real 403 hits, yet only the anonymous arm was covered. The exact
    # `class="btn"` (not `btn btn--ghost`) is what pins it to the authenticated
    # branch -- the anonymous branch renders its own ghost-styled copy.
    assert b'<a class="btn" href="/">Back to main page</a>' in resp.content


def test_403_offers_a_login_action_to_an_anonymous_visitor(rf):
    """Rendered directly, not via a request.

    Every first-party `raise PermissionDenied` sits behind @login_required, so
    no first-party URL can produce an anonymous 403 -- a live request would get
    a 302 to login instead. (allauth can reach it, which is why the branch is
    kept.)
    """
    from django.contrib.auth.models import AnonymousUser
    from django.template.loader import render_to_string

    request = rf.get("/courses/secret/?tab=notes")
    request.user = AnonymousUser()
    html = render_to_string("403.html", {}, request=request)

    assert "/accounts/login/?next=" in html
    # get_full_path, not path -- the query string must survive the round trip.
    # |urlencode defaults to safe="/", so this form is deterministic; asserting
    # `... or "tab=notes" in html` would silently tolerate a dropped |urlencode.
    assert "tab%3Dnotes" in html
    # Exactly once: base.html renders its OWN "Log in" CTA for anonymous
    # visitors, so this is what pins the hide_auth_cta header suppression.
    # (RequestFactory leaves resolver_match None -> hide_auth_cta is False from
    # the context processor, so only the template's {% with %} can suppress it.)
    assert html.count("Log in") == 1, "header CTA not suppressed -- duplicate label"
