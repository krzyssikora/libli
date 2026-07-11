import pytest
from django.urls import reverse


def _pa_client(client):
    from django.contrib.auth.models import Group

    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from tests.factories import TEST_PASSWORD

    pa = User.objects.create_user(
        username="pa", email="pa@school.edu", password=TEST_PASSWORD, is_staff=True
    )
    pa.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    from django.contrib.auth.models import Permission

    pa.user_permissions.add(Permission.objects.get(codename="change_user"))
    client.force_login(pa)
    return pa


@pytest.mark.django_db
def test_edit_page_shows_name_inputs(client):
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    _pa_client(client)
    target = User.objects.create_user(username="target", password=TEST_PASSWORD)
    body = client.get(reverse("accounts:user_edit", args=[target.pk])).content
    assert b'name="first_name"' in body
    assert b'name="last_name"' in body


@pytest.mark.django_db
def test_sync_checkbox_visibility_follows_sso_config(client):
    from accounts.models import User
    from tests._sso import make_oidc_app
    from tests.factories import TEST_PASSWORD

    _pa_client(client)
    target = User.objects.create_user(username="target2", password=TEST_PASSWORD)
    url = reverse("accounts:user_edit", args=[target.pk])
    assert b'name="sync_name_from_sso"' not in client.get(url).content
    make_oidc_app()
    assert b'name="sync_name_from_sso"' in client.get(url).content
