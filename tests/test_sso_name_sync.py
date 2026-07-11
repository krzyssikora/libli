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
    from accounts.models import User
    from accounts.provisioning import apply_sso_names
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(username="a", password=TEST_PASSWORD)
    apply_sso_names(u, _sl(_nested("Ada", "Lovelace")))
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Ada", "Lovelace")


@pytest.mark.django_db
def test_locked_user_is_never_modified():
    from accounts.models import User
    from accounts.provisioning import apply_sso_names
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
    from accounts.models import User
    from accounts.provisioning import apply_sso_names
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="c", password=TEST_PASSWORD, first_name="Old", last_name="Value"
    )
    apply_sso_names(u, _sl(_nested(given="  ", family=None)))  # blank + absent
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Old", "Value")


@pytest.mark.django_db
def test_partial_claim_updates_only_that_field():
    from accounts.models import User
    from accounts.provisioning import apply_sso_names
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="d", password=TEST_PASSWORD, first_name="F", last_name="Stay"
    )
    apply_sso_names(u, _sl(_nested(given="Grace")))  # only given_name
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Grace", "Stay")


@pytest.mark.django_db
def test_noop_when_claims_match_and_tolerates_none_extra_data():
    from accounts.models import User
    from accounts.provisioning import _claims
    from accounts.provisioning import apply_sso_names
    from tests.factories import TEST_PASSWORD

    assert _claims(None) == {}  # None-tolerant unwrap
    u = User.objects.create_user(
        username="e", password=TEST_PASSWORD, first_name="Same", last_name="Same"
    )
    apply_sso_names(u, _sl(None))  # no claims at all -> no error, no change
    apply_sso_names(u, _sl(_nested("Same", "Same")))  # equal -> no change
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Same", "Same")


def _complete(request, sociallogin):
    from allauth.core import context
    from allauth.socialaccount.helpers import complete_social_login

    with context.request_context(request):
        return complete_social_login(request, sociallogin)


@pytest.fixture
def oidc_app(db):
    from tests._sso import make_oidc_app

    return make_oidc_app()


@pytest.mark.django_db
def test_link_by_email_first_login_syncs_names(oidc_app):
    # An admin-created local account, linked on first SSO login via connect(),
    # which emits social_account_added -> receiver -> apply_sso_names.
    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import TEST_PASSWORD

    User.objects.create_user(
        username="teacher", email="teacher@school.edu", password=TEST_PASSWORD
    )
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "teacher@school.edu", username="ignored")
    sl.account.extra_data = {"userinfo": {"given_name": "Tea", "family_name": "Cher"}}
    _complete(request, sl)
    linked = User.objects.get(username="teacher")
    assert (linked.first_name, linked.last_name) == ("Tea", "Cher")


@pytest.mark.django_db
def test_returning_login_updates_names_via_updated_signal(oidc_app):
    from allauth.socialaccount.models import SocialAccount

    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import TEST_PASSWORD

    User.objects.create_user(
        username="ret", email="ret@school.edu", password=TEST_PASSWORD
    )
    # First login: link + initial names.
    r1 = make_request()
    sl1 = make_sociallogin(
        oidc_app, r1, "ret@school.edu", username="ignored", uid="sub-ret"
    )
    sl1.account.extra_data = {"userinfo": {"given_name": "First", "family_name": "One"}}
    _complete(r1, sl1)
    # Second login (same uid): lookup refreshes extra_data + emits update signal
    r2 = make_request()
    sl2 = make_sociallogin(
        oidc_app, r2, "ret@school.edu", username="ignored", uid="sub-ret"
    )
    sl2.account.extra_data = {
        "userinfo": {"given_name": "Second", "family_name": "Two"}
    }
    _complete(r2, sl2)
    u = User.objects.get(username="ret")
    assert (u.first_name, u.last_name) == ("Second", "Two")
    assert SocialAccount.objects.filter(user=u).count() == 1


@pytest.mark.django_db
def test_locked_user_names_untouched_on_login(oidc_app):
    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import TEST_PASSWORD

    u = User.objects.create_user(
        username="pin",
        email="pin@school.edu",
        password=TEST_PASSWORD,
        first_name="Pinned",
        last_name="Name",
    )
    u.names_locked = True
    u.save(update_fields=["names_locked"])
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "pin@school.edu", username="ignored")
    sl.account.extra_data = {"userinfo": {"given_name": "Nope", "family_name": "Nope"}}
    _complete(request, sl)
    u.refresh_from_db()
    assert (u.first_name, u.last_name) == ("Pinned", "Name")


@pytest.mark.django_db
def test_net_new_jit_signup_persists_names(oidc_app):
    # Net-new JIT signup path. allauth's built-in populate_user/extract_common_fields
    # sets the names on sociallogin.user from the OIDC claims BEFORE our flow runs, and
    # social_account_added does NOT fire here — so no receiver of ours runs. The test
    # harness (make_sociallogin) builds sociallogin.user by hand rather than via the
    # provider response, so we set the names directly to simulate populate_user's
    # output, then assert the created account keeps them (i.e. the JIT path is not
    # broken and our receiver does not clobber it).
    from accounts.models import User
    from institution.models import Institution
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    inst = Institution.load()
    inst.signup_policy = "open"
    inst.allowed_email_domains = []
    inst.save()

    request = make_request()
    sl = make_sociallogin(oidc_app, request, "newkid@school.edu", username="newkid")
    sl.user.first_name = "New"  # as populate_user would set from given_name
    sl.user.last_name = "Kid"  # as populate_user would set from family_name
    sl.account.extra_data = {"userinfo": {"given_name": "New", "family_name": "Kid"}}
    _complete(request, sl)
    created = User.objects.get(username="newkid")
    assert (created.first_name, created.last_name) == ("New", "Kid")
