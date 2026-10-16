"""§6/§7: page context, settings form independence, dark-box behaviour."""

import json

import pytest
from django.urls import reverse

from notifications.models import NotificationEmailPreference
from notifications.models import NotificationPushPreference
from notifications.tests.push_helpers import logged_in_user
from notifications.tests.push_helpers import make_sub
from notifications.tests.push_helpers import push_settings

pytestmark = pytest.mark.django_db

KINDS = ("quiz_needs_review", "quiz_graded", "enrolled")


def _settings_post(client, user, *, email=(), push=()):
    data = {"display_name": "X", "email": user.email, "language": "en", "theme": "auto"}
    for k in email:
        data[k] = "on"
    for k in push:
        data[f"push-{k}"] = "on"
    r = client.post(reverse("core:user_settings"), data)
    assert r.status_code == 302, (
        "settings POST was invalid -- the test would prove nothing"
    )
    return r


@pytest.fixture
def logged_in(client):
    return logged_in_user(client), client


def test_dark_box_page_has_no_push_markup(logged_in):
    _, client = logged_in
    html = client.get(reverse("core:user_settings")).content.decode()
    for hook in ("libli-push", "data-push-device", "push.js", "push-quiz_graded"):
        assert hook not in html
    assert "Email notifications" in html


def test_configured_page_carries_meta_switch_and_columns(logged_in, settings):
    push_settings(settings)
    _, client = logged_in
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'name="libli-push"' in html
    assert f'data-vapid-key="{settings.PUSH_VAPID_PUBLIC_KEY}"' in html
    assert 'data-remembered="1"' in html
    assert "data-push-device" in html
    assert 'name="push-quiz_graded"' in html and 'name="quiz_graded"' in html
    assert "core/js/push.js" in html
    assert "data-logout-form" in html


def _input_tag(html, name):
    import re

    for tag in re.findall(r"<input[^>]*>", html):
        if f'name="{name}"' in tag:
            return tag
    raise AssertionError(f"no input named {name}")


def test_push_checkbox_reflects_push_prefs_not_email_prefs(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    NotificationPushPreference.objects.create(user=user, quiz_graded=False)
    html = client.get(reverse("core:user_settings")).content.decode()
    assert "checked" not in _input_tag(html, "push-quiz_graded")
    assert "checked" in _input_tag(html, "quiz_graded")


def test_not_remembered_session_renders_remembered_0(logged_in, settings):
    push_settings(settings)
    _, client = logged_in
    session = client.session
    session.set_expiry(0)
    session.save()
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-remembered="0"' in html


def test_session_endpoint_rendered_only_for_this_sessions_row(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    session = client.session
    session["push_endpoint"] = "https://fcm.googleapis.com/fcm/send/me"
    session.save()
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-session-endpoint=""' in html  # no row yet
    make_sub(
        user,
        client.session.session_key,
        endpoint="https://fcm.googleapis.com/fcm/send/me",
    )
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-session-endpoint="https://fcm.googleapis.com/fcm/send/me"' in html


def test_session_endpoint_empty_after_a_key_rotation(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    old_key = client.session.session_key
    make_sub(user, old_key, endpoint="https://fcm.googleapis.com/fcm/send/me")
    session = client.session
    session["push_endpoint"] = "https://fcm.googleapis.com/fcm/send/me"
    session.cycle_key()
    session.save()
    client.cookies["sessionid"] = session.session_key
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-session-endpoint=""' in html


def test_columns_save_independently(logged_in, settings):
    # mutant: prefix="push" removed from NotificationPushForm
    push_settings(settings)
    user, client = logged_in
    _settings_post(client, user, email=("quiz_graded",), push=("enrolled",))
    e = NotificationEmailPreference.objects.get(user=user)
    p = NotificationPushPreference.objects.get(user=user)
    assert (e.quiz_graded, e.enrolled) == (True, False)
    assert (p.quiz_graded, p.enrolled) == (False, True)


def test_get_does_not_create_a_push_row(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    client.get(reverse("core:user_settings"))
    assert not NotificationPushPreference.objects.filter(user=user).exists()


def test_dark_box_post_leaves_the_push_row_alone(logged_in):
    user, client = logged_in
    NotificationPushPreference.objects.create(
        user=user, quiz_graded=False, enrolled=False
    )
    _settings_post(client, user, email=KINDS)
    p = NotificationPushPreference.objects.get(user=user)
    assert (p.quiz_graded, p.enrolled, p.quiz_needs_review) == (False, False, True)


def test_dark_box_post_creates_no_push_row(logged_in):
    user, client = logged_in
    _settings_post(client, user, email=KINDS)
    assert not NotificationPushPreference.objects.filter(user=user).exists()


def test_post_without_push_fields_turns_push_off_but_leaves_email(logged_in, settings):
    push_settings(settings)
    user, client = logged_in
    _settings_post(client, user, email=KINDS)  # a page rendered before push existed
    p = NotificationPushPreference.objects.get(user=user)
    e = NotificationEmailPreference.objects.get(user=user)
    assert not any(getattr(p, k) for k in KINDS)
    assert all(getattr(e, k) for k in KINDS)


def test_real_unticked_login_is_not_remembered_and_cannot_subscribe(client, settings):
    """D8 through allauth's REAL login form: an unticked 'Remember me' must yield
    data-remembered="0" and a 403 from subscribe."""
    from notifications.tests.test_push_endpoints import body
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    push_settings(settings)
    make_verified_user(username="unticked", email="unticked@example.com")
    r = client.post(
        reverse("account_login"), {"login": "unticked", "password": TEST_PASSWORD}
    )
    assert r.status_code == 302
    html = client.get(reverse("core:user_settings")).content.decode()
    assert 'data-remembered="0"' in html
    r = client.post(
        reverse("notifications:push_subscribe"),
        data=json.dumps(body()),
        content_type="application/json",
    )
    assert r.status_code == 403


def test_anonymous_pages_carry_no_push_meta(client, settings):
    push_settings(settings)
    html = client.get(reverse("account_login")).content.decode()
    assert "libli-push" not in html
