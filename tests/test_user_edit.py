import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.emails import ensure_verified_primary_email
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
def test_edit_changes_role(client):
    make_pa(client, "pa_edit")
    target = User.objects.create_user(username="stu", display_name="Stu")
    set_user_role(target, STUDENT)
    resp = client.post(
        reverse("accounts:user_edit", args=[target.pk]),
        {"display_name": "Stu", "email": "", "role": TEACHER},
    )
    assert resp.status_code == 302
    target.refresh_from_db()
    assert list(target.groups.values_list("name", flat=True)) == [TEACHER]
    assert target.is_staff is True


@pytest.mark.django_db
def test_edit_role_less_user_keeps_blank_when_not_chosen(client):
    make_pa(client, "pa_blank")
    roleless = User.objects.create_user(username="root2", display_name="Root")
    resp = client.post(
        reverse("accounts:user_edit", args=[roleless.pk]),
        {"display_name": "Root", "email": "", "role": ""},  # blank "No role"
    )
    assert resp.status_code == 302
    roleless.refresh_from_db()
    assert roleless.groups.count() == 0  # no silent Student assignment


@pytest.mark.django_db
def test_cannot_demote_sole_platform_admin(client):
    seed_roles()
    # Editor is a superuser NOT in the PA group: holds all perms (so the view's
    # permission gate passes), isn't the target, and isn't counted as an active PA.
    editor = User.objects.create_superuser(username="root_ed", password="x")
    client.force_login(editor)
    pa = User.objects.create_user(username="sole_pa")
    set_user_role(pa, PLATFORM_ADMIN)  # the ONLY active Platform Admin
    resp = client.post(
        reverse("accounts:user_edit", args=[pa.pk]),
        {"display_name": "", "email": pa.email or "", "role": STUDENT},
    )
    assert resp.status_code == 200  # re-rendered with a non-field error
    pa.refresh_from_db()
    assert PLATFORM_ADMIN in list(pa.groups.values_list("name", flat=True))


@pytest.mark.django_db
def test_email_uniqueness_case_insensitive(client):
    make_pa(client, "pa_email")
    User.objects.create_user(username="owner", email="owner@school.edu")
    target = User.objects.create_user(username="other", display_name="Other")
    resp = client.post(
        reverse("accounts:user_edit", args=[target.pk]),
        {"display_name": "Other", "email": "Owner@School.edu", "role": ""},
    )
    assert resp.status_code == 200  # re-render with field error
    target.refresh_from_db()
    assert target.email is None or target.email.lower() != "owner@school.edu"


@pytest.mark.django_db
def test_self_role_change_blocked(client):
    pa = make_pa(client, "pa_self")
    client.post(
        reverse("accounts:user_edit", args=[pa.pk]),
        {"display_name": "", "email": pa.email, "role": STUDENT},
    )
    pa.refresh_from_db()
    # role unchanged — still Platform Admin (disabled field discards posted value)
    assert PLATFORM_ADMIN in list(pa.groups.values_list("name", flat=True))


@pytest.mark.django_db
def test_clearing_email_deletes_emailaddress_rows(client):
    make_pa(client, "pa_clear")
    target = User.objects.create_user(username="tgt_clear", display_name="Target")
    target.email = "old@school.edu"
    target.save()
    ensure_verified_primary_email(target, "old@school.edu")
    assert EmailAddress.objects.filter(user=target).count() == 1  # baseline
    resp = client.post(
        reverse("accounts:user_edit", args=[target.pk]),
        {"display_name": "Target", "email": "", "role": ""},
    )
    assert resp.status_code == 302
    target.refresh_from_db()
    assert target.email is None
    assert EmailAddress.objects.filter(user=target).count() == 0


@pytest.mark.django_db
def test_verified_email_belongs_to_other_blocks(client):
    make_pa(client, "pa_clash")
    # user_a: User.email differs, but owns a verified EmailAddress for shared@school.edu
    # so User.email uniqueness won't catch it — verified_email_belongs_to_other will.
    user_a = User.objects.create_user(username="user_a", email="a-different@school.edu")
    ensure_verified_primary_email(user_a, "shared@school.edu")
    # target_b: no email yet
    target_b = User.objects.create_user(username="user_b", display_name="B")
    resp = client.post(
        reverse("accounts:user_edit", args=[target_b.pk]),
        {"display_name": "B", "email": "shared@school.edu", "role": ""},
    )
    assert resp.status_code == 200  # re-render with form error, not 302
    assert resp.context["form"].errors  # some field error is present
    target_b.refresh_from_db()
    assert target_b.email is None or target_b.email.lower() != "shared@school.edu"
