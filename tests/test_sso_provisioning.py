import datetime

import pytest
from django.utils import timezone

from accounts.models import Invitation
from accounts.provisioning import Decision
from accounts.provisioning import email_domain
from accounts.provisioning import evaluate_sso_provisioning
from accounts.provisioning import resolve_user_for_email
from accounts.provisioning import verified_email_belongs_to_other


class _Inv:
    """Stand-in for an Invitation (the decision fn treats it as already-valid)."""


def _eval(email, policy, domains, invitation=None):
    return evaluate_sso_provisioning(
        email,
        signup_policy=policy,
        allowed_email_domains=domains,
        invitation=invitation,
    )


def test_email_domain_extraction_lowercases():
    assert email_domain("Alice@Example.COM") == "example.com"
    assert email_domain("no-at-sign") == ""


def test_pre_invited_overrides_policy_and_domain():
    inv = _Inv()
    d = _eval("x@other.org", "invite", ["school.edu"], invitation=inv)
    assert d.allow and d.invitation_to_consume is inv


def test_open_policy_empty_domains_allows_any():
    d = _eval("anyone@anywhere.io", "open", [])
    assert d.allow and d.invitation_to_consume is None


def test_open_policy_matching_domain_allows():
    assert _eval("kid@school.edu", "open", ["school.edu"]).allow


def test_open_policy_nonmatching_domain_denies():
    d = _eval("kid@gmail.com", "open", ["school.edu"])
    assert not d.allow and d.reason == "domain"


def test_invite_policy_without_invite_denies():
    d = _eval("kid@school.edu", "invite", [])
    assert not d.allow and d.reason == "policy"


def test_domain_match_normalizes_stored_entries():
    # Stored entries may be messy: leading @, mixed case, surrounding spaces.
    assert _eval("kid@school.edu", "open", [" School.EDU "]).allow
    assert _eval("kid@school.edu", "open", ["@school.edu"]).allow


def test_domain_match_is_exact_not_subdomain():
    d = _eval("kid@sub.school.edu", "open", ["school.edu"])
    assert not d.allow and d.reason == "domain"


def test_no_at_email_denied_only_in_domain_branch():
    # With a domain allowlist a no-@ email is denied...
    assert not _eval("garbage", "open", ["school.edu"]).allow
    # ...but with no allowlist, open policy admits it (deny lives in the domain branch).
    assert _eval("garbage", "open", []).allow


def test_decision_is_a_dataclass_with_defaults():
    d = Decision(allow=True)
    assert d.reason == "" and d.invitation_to_consume is None


@pytest.mark.django_db
def test_find_pending_returns_most_recent_valid():
    Invitation.objects.create(email="a@school.edu")  # older
    newer = Invitation.objects.create(email="a@school.edu")  # newer, same email
    assert Invitation.find_pending("a@school.edu") == newer


@pytest.mark.django_db
def test_find_pending_is_case_insensitive():
    inv = Invitation.objects.create(email="Mixed@School.edu")
    assert Invitation.find_pending("mixed@school.edu") == inv


@pytest.mark.django_db
def test_find_pending_ignores_accepted_and_expired():
    Invitation.objects.create(email="b@school.edu", accepted_at=timezone.now())
    Invitation.objects.create(
        email="b@school.edu",
        expires_at=timezone.now() - datetime.timedelta(days=1),
    )
    assert Invitation.find_pending("b@school.edu") is None


@pytest.mark.django_db
def test_find_pending_none_when_absent():
    assert Invitation.find_pending("nobody@school.edu") is None


@pytest.mark.django_db
def test_resolve_prefers_verified_emailaddress_owner():
    from tests.factories import make_verified_user

    user = make_verified_user(username="verif", email="dup@school.edu")
    assert resolve_user_for_email("DUP@school.edu") == user


@pytest.mark.django_db
def test_resolve_prefers_verified_over_unverified_emailaddress_owner():
    # Two EmailAddress rows for one address: verified on A, unverified on B -> A wins.
    from allauth.account.models import EmailAddress

    from accounts.models import User
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    a = make_verified_user(username="ver_a", email="tie@school.edu")
    b = User.objects.create_user(
        username="unver_b", email="b@school.edu", password=TEST_PASSWORD
    )
    EmailAddress.objects.create(
        user=b, email="tie@school.edu", verified=False, primary=False
    )
    assert resolve_user_for_email("tie@school.edu") == a


@pytest.mark.django_db
def test_resolve_finds_admin_created_user_by_user_email_only():
    # An admin-created user has a User.email but no EmailAddress row.
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    admin_made = User.objects.create_user(
        username="adm", email="adm@school.edu", password=TEST_PASSWORD
    )
    assert resolve_user_for_email("adm@school.edu") == admin_made


@pytest.mark.django_db
def test_resolve_none_when_absent_or_emailless():
    from accounts.models import User
    from tests.factories import TEST_PASSWORD

    User.objects.create_user(username="noemail", password=TEST_PASSWORD)  # email NULL
    assert resolve_user_for_email("ghost@school.edu") is None


@pytest.mark.django_db
def test_verified_clash_detects_other_owner():
    from tests.factories import make_verified_user

    owner = make_verified_user(username="owner", email="shared@school.edu")
    other = make_verified_user(username="other", email="other@school.edu")
    assert verified_email_belongs_to_other("shared@school.edu", other) is True
    assert verified_email_belongs_to_other("shared@school.edu", owner) is False


@pytest.mark.django_db
def test_email_is_registered_still_boolean():
    from accounts.views import _email_is_registered
    from tests.factories import make_verified_user

    make_verified_user(username="reg", email="reg@school.edu")
    assert _email_is_registered("reg@school.edu") is True
    assert _email_is_registered("absent@school.edu") is False
