import pytest
from django.db import IntegrityError

from accounts.models import User


def test_user_with_username_only_has_no_email():
    user = User.objects.create_user(username="young.student", password="x")
    assert user.username == "young.student"
    assert not user.email  # empty input is normalized to NULL
    assert user.language == "en"
    assert user.theme == "auto"


def test_user_str_prefers_display_name():
    user = User.objects.create_user(
        username="jan", display_name="Jan Kowalski", password="x"
    )
    assert str(user) == "Jan Kowalski"


def test_user_str_falls_back_to_username():
    user = User.objects.create_user(username="jan", password="x")
    assert str(user) == "jan"


def test_email_is_unique_when_present():
    User.objects.create_user(username="a", email="dup@x.edu", password="x")
    # On Postgres the IntegrityError aborts the surrounding transaction, so the
    # pytest.raises block must be the LAST statement in this test.
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="b", email="dup@x.edu", password="x")


def test_blank_emails_do_not_collide():
    # Invariant: no migration may seed Users, so this absolute count stays valid.
    User.objects.create_user(username="a", password="x")
    User.objects.create_user(
        username="b", password="x"
    )  # both have no email -> NULL, allowed
    assert User.objects.count() == 2


def test_auth_user_model_is_custom():
    # Guards the spec's one non-reversible risk: the swappable user model must be
    # accounts.User from the first migration on.
    from django.conf import settings
    from django.contrib.auth import get_user_model

    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model() is User


def test_user_factory_builds_usable_user():
    from tests.factories import UserFactory

    user = UserFactory()
    assert user.pk is not None
    assert user.check_password("password123")
    assert not user.email  # factory sets no email -> NULL
