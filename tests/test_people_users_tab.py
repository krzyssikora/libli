import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import User
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user


def make_pa(client, username="pa"):
    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_pa_can_list_users(client):
    make_pa(client, "pa_list")
    target = User.objects.create_user(username="alice", display_name="Alice Liddell")
    set_user_role(target, STUDENT)
    resp = client.get(reverse("accounts:people"))
    assert resp.status_code == 200
    assert "Alice Liddell" in resp.content.decode()


@pytest.mark.django_db
def test_non_pa_is_forbidden(client):
    make_verified_user(username="stu", email="stu@school.edu", password=TEST_PASSWORD)
    client.login(username="stu", password=TEST_PASSWORD)
    resp = client.get(reverse("accounts:people"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_search_filters_by_name(client):
    make_pa(client, "pa_search")
    User.objects.create_user(username="findme", display_name="Findme Smith")
    User.objects.create_user(username="hidden", display_name="Other Person")
    resp = client.get(reverse("accounts:people"), {"q": "Findme"})
    body = resp.content.decode()
    assert "Findme Smith" in body
    assert "Other Person" not in body


@pytest.mark.django_db
def test_role_filter_no_role_bucket(client):
    make_pa(client, "pa_norole")
    User.objects.create_user(username="roleless", display_name="No Role Ned")
    teacher = User.objects.create_user(username="teach", display_name="Teach Tess")
    set_user_role(teacher, TEACHER)
    resp = client.get(reverse("accounts:people"), {"role": "__none__"})
    body = resp.content.decode()
    assert "No Role Ned" in body
    assert "Teach Tess" not in body


@pytest.mark.django_db
def test_email_has_its_own_column(client):
    # Email shows even when the user HAS a display name — proving it's a separate
    # column now, not just a fallback behind a missing display_name.
    make_pa(client, "pa_cols")
    User.objects.create_user(
        username="hasname", email="has@school.edu", display_name="Has Name"
    )
    resp = client.get(reverse("accounts:people"))
    body = resp.content.decode()
    assert "Has Name" in body
    assert "has@school.edu" in body
