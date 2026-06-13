import pytest

from accounts.emails import ensure_verified_primary_email
from accounts.models import User
from tests.factories import TEST_PASSWORD


def test_creates_verified_primary_email_row():
    from allauth.account.models import EmailAddress

    user = User.objects.create_user(
        username="amy", email="amy@school.edu", password=TEST_PASSWORD
    )
    addr = ensure_verified_primary_email(user, "amy@school.edu")
    assert addr.verified and addr.primary
    assert EmailAddress.objects.filter(user=user, email="amy@school.edu").count() == 1


def test_forces_verified_primary_on_existing_unverified_row():
    from allauth.account.models import EmailAddress

    user = User.objects.create_user(
        username="bee", email="bee@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(
        user=user, email="bee@school.edu", verified=False, primary=False
    )
    addr = ensure_verified_primary_email(user, "bee@school.edu")
    assert addr.verified and addr.primary


def test_raises_when_email_bound_to_a_different_user():
    other = User.objects.create_user(
        username="cas", email="shared@school.edu", password=TEST_PASSWORD
    )
    ensure_verified_primary_email(other, "shared@school.edu")
    intruder = User.objects.create_user(
        username="dan", email="dan@school.edu", password=TEST_PASSWORD
    )
    with pytest.raises(ValueError):
        ensure_verified_primary_email(intruder, "shared@school.edu")


def test_does_not_raise_for_unverified_row_on_a_different_user():
    from allauth.account.models import EmailAddress

    other = User.objects.create_user(
        username="eve", email="eve@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(
        user=other, email="shared2@school.edu", verified=False, primary=False
    )
    user = User.objects.create_user(
        username="fox", email="fox@school.edu", password=TEST_PASSWORD
    )
    # An *unverified* row on another user must NOT block (only verified rows do).
    addr = ensure_verified_primary_email(user, "shared2@school.edu")
    assert addr.verified and addr.primary
