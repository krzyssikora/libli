import pytest
from django.urls import reverse

from tests.factories import make_verified_user


@pytest.mark.django_db
def test_site_config_includes_signup_policy_default():
    from core.services import get_site_config

    assert get_site_config()["signup_policy"] == "invite"


@pytest.mark.django_db
def test_site_config_signup_policy_reflects_save():
    from core.services import get_site_config
    from institution.models import Institution

    assert get_site_config()["signup_policy"] == "invite"
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()  # fires invalidate_site_config
    assert get_site_config()["signup_policy"] == "open"


@pytest.mark.django_db
def test_user_roles_anonymous_all_false(rf):
    from django.contrib.auth.models import AnonymousUser

    from core.context_processors import user_roles

    request = rf.get("/")
    request.user = AnonymousUser()
    assert user_roles(request) == {
        "is_student": False,
        "is_teacher": False,
        "is_course_admin": False,
        "is_platform_admin": False,
    }


@pytest.mark.django_db
def test_user_roles_reflects_group_membership(rf):
    from django.contrib.auth.models import Group

    from core.context_processors import user_roles
    from institution.roles import PLATFORM_ADMIN

    user = make_verified_user(username="pa", email="pa@school.edu")
    user.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    request = rf.get("/")
    request.user = user
    ctx = user_roles(request)
    assert ctx["is_platform_admin"] is True
    assert ctx["is_student"] is False


@pytest.mark.django_db
def test_user_settings_requires_login(client):
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_user_settings_get_renders(client):
    user = make_verified_user(username="settingsuser", email="setu@school.edu")
    client.force_login(user)
    resp = client.get(reverse("core:user_settings"))
    assert resp.status_code == 200
    assert b"settingsuser" in resp.content  # read-only username shown (distinctive)


@pytest.mark.django_db
def test_user_settings_post_persists_and_resyncs(client):
    user = make_verified_user(username="su2", email="su2@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {
            "theme": "dark",
            "language": "pl",
            "display_name": "Sue",
            "username": "hacker",
        },
    )
    assert resp.status_code == 302
    user.refresh_from_db()
    assert user.theme == "dark"
    assert user.language == "pl"
    assert user.display_name == "Sue"
    assert user.username == "su2"  # username NOT editable (absent from the form)
    assert client.session["_language"] == "pl"
    assert resp.cookies["libli_theme"].value == "dark"


@pytest.mark.django_db
def test_user_settings_rejects_disabled_language(client):
    from institution.models import Institution

    inst = Institution.load()
    inst.enabled_languages = ["en"]  # pl disabled
    inst.save()
    user = make_verified_user(username="su3", email="su3@school.edu")
    client.force_login(user)
    resp = client.post(
        reverse("core:user_settings"),
        {"theme": "auto", "language": "pl", "display_name": ""},
    )
    assert resp.status_code == 200  # re-render with errors, no redirect
    user.refresh_from_db()
    assert user.language == "en"  # unchanged (default)
