from types import SimpleNamespace

import pytest


def _sl(extra_data):
    """A minimal stand-in for a SocialLogin: apply_sso_names only reads
    sociallogin.account.extra_data."""
    return SimpleNamespace(account=SimpleNamespace(extra_data=extra_data))


def _nested(given=None, family=None):
    ui = {}
    if given is not None:
        ui["given_name"] = given
    if family is not None:
        ui["family_name"] = family
    return {"userinfo": ui, "id_token": {}}


@pytest.mark.django_db
def test_unlocked_user_gets_names_from_nested_claims():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="a", password=TEST_PASSWORD)
    apply_sso_names(u, _sl(_nested("Ada", "Lovelace")))
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Ada", "Lovelace")


@pytest.mark.django_db
def test_locked_user_is_never_modified():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="b", password=TEST_PASSWORD, first_name="Keep", last_name="Me"
    )
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    apply_sso_names(u, _sl(_nested("New", "Name")))
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Keep", "Me")


@pytest.mark.django_db
def test_blank_or_missing_claims_never_overwrite():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="c", password=TEST_PASSWORD, first_name="Old", last_name="Value"
    )
    apply_sso_names(u, _sl(_nested(given="  ", family=None)))  # blank + absent
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Old", "Value")


@pytest.mark.django_db
def test_partial_claim_updates_only_that_field():
    from accounts.provisioning import apply_sso_names
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="d", password=TEST_PASSWORD, first_name="F", last_name="Stay"
    )
    apply_sso_names(u, _sl(_nested(given="Grace")))  # only given_name
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Grace", "Stay")


@pytest.mark.django_db
def test_noop_when_claims_match_and_tolerates_none_extra_data():
    from accounts.provisioning import apply_sso_names, _claims
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    assert _claims(None) == {}  # None-tolerant unwrap
    u = User.objects.create_user(
        username="e", password=TEST_PASSWORD, first_name="Same", last_name="Same"
    )
    apply_sso_names(u, _sl(None))  # no claims at all -> no error, no change
    apply_sso_names(u, _sl(_nested("Same", "Same")))  # equal -> no change
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Same", "Same")
