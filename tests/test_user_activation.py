import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import User
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
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
def test_deactivate_a_student(client):
    make_pa(client, "pa_de")
    stu = User.objects.create_user(username="stu")
    set_user_role(stu, STUDENT)
    resp = client.post(reverse("accounts:user_deactivate", args=[stu.pk]))
    assert resp.status_code == 302
    stu.refresh_from_db()
    assert stu.is_active is False


@pytest.mark.django_db
def test_cannot_deactivate_self(client):
    pa = make_pa(client, "pa_self_de")
    client.post(reverse("accounts:user_deactivate", args=[pa.pk]))
    pa.refresh_from_db()
    assert pa.is_active is True  # blocked


@pytest.mark.django_db
def test_cannot_deactivate_sole_platform_admin(client):
    seed_roles()
    # Editor is a superuser NOT in the PA group (has all perms; not the target; not
    # counted as a PA). The target is the only active Platform Admin.
    editor = User.objects.create_superuser(username="root_ed2", password="x")
    client.force_login(editor)
    pa = User.objects.create_user(username="sole_pa2")
    set_user_role(pa, PLATFORM_ADMIN)
    client.post(reverse("accounts:user_deactivate", args=[pa.pk]))
    pa.refresh_from_db()
    assert pa.is_active is True  # blocked: last active Platform Admin


@pytest.mark.django_db
def test_reactivate(client):
    make_pa(client, "pa_re")
    gone = User.objects.create_user(username="gone", is_active=False)
    resp = client.post(reverse("accounts:user_reactivate", args=[gone.pk]))
    assert resp.status_code == 302
    gone.refresh_from_db()
    assert gone.is_active is True
