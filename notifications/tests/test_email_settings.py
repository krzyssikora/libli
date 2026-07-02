import pytest
from django.urls import reverse

from notifications.models import NotificationEmailPreference
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_get_shows_section_without_creating_row(client):
    user = make_verified_user(username="prefu", email="prefu@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert b"Email notifications" in resp.content
    # GET is side-effect-free: no preference row written.
    assert NotificationEmailPreference.objects.filter(user=user).count() == 0


def test_post_persists_prefs_and_primary_form(client):
    user = make_verified_user(username="prefu2", email="prefu2@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            # primary UserSettingsForm fields (must be valid)
            "theme": "dark",
            "language": "en",
            "display_name": "Pat",
            "email": "prefu2@school.edu",
            # notification prefs: quiz_graded unchecked (absent), others on
            "quiz_needs_review": "on",
            "enrolled": "on",
        },
    )
    assert resp.status_code == 302
    pref = NotificationEmailPreference.objects.get(user=user)
    assert pref.quiz_graded is False  # unchecked → absent → False
    assert pref.enrolled is True
    assert pref.quiz_needs_review is True
    user.refresh_from_db()
    assert user.display_name == "Pat"  # primary form still saved


def test_post_invalid_primary_rerenders_with_notif_form(client):
    user = make_verified_user(username="prefu3", email="prefu3@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            "theme": "dark",
            "language": "zz",  # not an enabled language → invalid
            "display_name": "Pat",
            "email": "prefu3@school.edu",
            "quiz_graded": "on",
        },
    )
    assert resp.status_code == 200  # re-render, no crash
    assert b"Email notifications" in resp.content
    # nothing saved on the invalid path
    assert NotificationEmailPreference.objects.filter(user=user).count() == 0
