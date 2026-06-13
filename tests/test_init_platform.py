import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import User
from institution.models import Institution
from institution.roles import PLATFORM_ADMIN
from tests.factories import TEST_PASSWORD


def _set_admin_env(monkeypatch, username="boss", email="boss@school.edu"):
    monkeypatch.setenv("INIT_ADMIN_USERNAME", username)
    monkeypatch.setenv("INIT_ADMIN_EMAIL", email)
    monkeypatch.setenv("INIT_ADMIN_PASSWORD", TEST_PASSWORD)


def test_creates_superuser_pa_with_verified_email(monkeypatch):
    from allauth.account.models import EmailAddress

    _set_admin_env(monkeypatch)
    call_command("init_platform")

    user = User.objects.get(username="boss")
    assert user.is_staff and user.is_superuser
    assert user.groups.filter(name=PLATFORM_ADMIN).exists()
    assert EmailAddress.objects.filter(
        user=user, email="boss@school.edu", verified=True, primary=True
    ).exists()
    # Roles + the singleton exist.
    assert Group.objects.filter(name=PLATFORM_ADMIN).exists()
    assert Institution.objects.count() == 1


def test_admin_can_log_in_via_allauth_front_door(client, monkeypatch):
    _set_admin_env(monkeypatch)
    call_command("init_platform")
    response = client.post(
        "/accounts/login/", {"login": "boss", "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
    assert client.session.get("_auth_user_id")


def test_second_run_is_idempotent_and_non_destructive(monkeypatch):
    _set_admin_env(monkeypatch)
    call_command("init_platform")
    # Simulate the admin rotating their password after first bootstrap.
    user = User.objects.get(username="boss")
    user.set_password("R0tated!pass12")
    user.save()
    call_command("init_platform")  # must not raise
    assert User.objects.filter(username="boss").count() == 1
    user.refresh_from_db()
    # Reconcile is non-destructive: the rotated password and email survive.
    assert user.check_password("R0tated!pass12")
    assert user.email == "boss@school.edu"
    # ...while flags + group remain asserted.
    assert user.is_staff and user.is_superuser
    assert user.groups.filter(name=PLATFORM_ADMIN).exists()


def test_reconciles_existing_non_superuser(monkeypatch):
    existing = User.objects.create_user(
        username="boss", email="boss@school.edu", password=TEST_PASSWORD
    )
    assert not existing.is_superuser
    _set_admin_env(monkeypatch)
    call_command("init_platform")
    existing.refresh_from_db()
    assert existing.is_staff and existing.is_superuser
    assert existing.groups.filter(name=PLATFORM_ADMIN).exists()


def test_missing_credentials_noninteractive_raises(monkeypatch):
    monkeypatch.delenv("INIT_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("INIT_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("INIT_ADMIN_PASSWORD", raising=False)
    # pytest's stdin is not a TTY, so missing env must fail fast.
    with pytest.raises(CommandError):
        call_command("init_platform")
    assert not User.objects.filter(is_superuser=True).exists()


def test_admin_email_already_used_by_another_account_raises(monkeypatch):
    # Bootstrapping a NEW admin username whose INIT_ADMIN_EMAIL is already another
    # account's email collides on User.email (unique). The command must surface this
    # as a clean CommandError, not an unhandled IntegrityError (spec §1: no crash).
    from tests.factories import make_verified_user

    make_verified_user(username="someone_else", email="boss@school.edu")
    _set_admin_env(
        monkeypatch
    )  # INIT_ADMIN_USERNAME=boss, INIT_ADMIN_EMAIL=boss@school.edu
    with pytest.raises(CommandError):
        call_command("init_platform")
    assert not User.objects.filter(username="boss").exists()


def test_weak_password_raises_command_error_without_creating_admin(monkeypatch):
    # The validate_password call exists specifically to reject weak/similar
    # passwords; a too-common password must surface as a CommandError and leave
    # no admin behind (roles/Institution may already be seeded — that's fine).
    monkeypatch.setenv("INIT_ADMIN_USERNAME", "boss")
    monkeypatch.setenv("INIT_ADMIN_EMAIL", "boss@school.edu")
    monkeypatch.setenv("INIT_ADMIN_PASSWORD", "password")  # too common
    with pytest.raises(CommandError):
        call_command("init_platform")
    assert not User.objects.filter(username="boss").exists()
