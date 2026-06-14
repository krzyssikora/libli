import datetime

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from django.utils import timezone

from accounts.models import Invitation
from accounts.provisioning import Decision
from accounts.provisioning import email_domain
from accounts.provisioning import evaluate_sso_provisioning
from accounts.provisioning import resolve_user_for_email
from accounts.provisioning import verified_email_belongs_to_other


@pytest.fixture
def oidc_app(db):
    from tests._sso import make_oidc_app

    return make_oidc_app()


@pytest.fixture
def settings_invite_policy(db, oidc_app):
    from institution.models import Institution

    inst = Institution.load()
    inst.signup_policy = "invite"
    inst.allowed_email_domains = []
    inst.save()
    return inst


@pytest.fixture
def settings_open_policy_school_only(db, oidc_app):
    from institution.models import Institution

    inst = Institution.load()
    inst.signup_policy = "open"
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    return inst


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


@pytest.mark.django_db
def test_login_page_shows_provider_when_socialapp_configured(client):
    from allauth.socialaccount.models import SocialApp
    from django.contrib.sites.models import Site

    # No SocialApp yet -> no provider login link on the page.
    assert b"openid_connect" not in client.get("/accounts/login/").content

    app = SocialApp.objects.create(
        provider="openid_connect",
        provider_id="testidp",
        name="Test IdP",
        client_id="client-id",
        secret="secret",
        settings={"server_url": "https://idp.example.test"},
    )
    app.sites.add(Site.objects.get_current())

    # With a configured provider, allauth's bundled login template renders a
    # provider login link (no project login override needed — verified note #2).
    # The openid_connect provider URLs sit under its default prefix "oidc"
    # (SOCIALACCOUNT_OPENID_CONNECT_URL_PREFIX, default "oidc"), so the login URL
    # is /accounts/oidc/<provider_id>/login/.
    body = client.get("/accounts/login/").content
    assert b"/accounts/oidc/testidp/login/" in body


@pytest.mark.django_db
def test_not_provisioned_page_renders_generic_copy(client):
    response = client.get("/sso/not-provisioned/")
    assert response.status_code == 200
    body = response.content.lower()
    assert b"not provisioned" in body or b"contact your administrator" in body
    # Generic: does not reveal whether policy or domain caused the denial.
    assert b"domain" not in body and b"policy" not in body


@pytest.mark.django_db
def test_not_provisioned_route_name_resolves():
    from django.urls import reverse

    assert reverse("accounts:sso_not_provisioned") == "/sso/not-provisioned/"


def _adapter():
    from accounts.adapters import SocialAccountAdapter

    return SocialAccountAdapter()


def test_is_open_for_signup_always_true():
    # No DB needed: REQUIRED override — the default delegates to AccountAdapter
    # (False under invite policy). A dummy (None, None) call must still return True.
    assert _adapter().is_open_for_signup(None, None) is True


# NOTE ON THESE DIRECT-CALL TESTS (verified vs allauth 65.18): they invoke
# `adapter.pre_social_login(request, sl)` directly, which does NOT run allauth's
# `sociallogin.lookup()` (that happens in `flows.login.pre_social_login`, before the
# adapter hook, in the real flow). So the verified-EmailAddress auto-connect (tier 1,
# owned by allauth) is exercised only by the e2e tests in Task 7; here we drive the
# adapter-owned `User.email` link path and the gating branches. See Task 7's
# `test_e2e_links_open_signup_user_by_verified_emailaddress` for the
# lookup()-first path.


@pytest.mark.django_db
def test_pre_social_login_denies_under_invite_policy(oidc_app, settings_invite_policy):
    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    request = make_request()
    sl = make_sociallogin(oidc_app, request, "newkid@school.edu")
    with pytest.raises(ImmediateHttpResponse):
        _adapter().pre_social_login(request, sl)
    assert not User.objects.filter(username="ssouser").exists()


@pytest.mark.django_db
def test_pre_social_login_denies_on_domain(oidc_app, settings_open_policy_school_only):
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    request = make_request()
    sl = make_sociallogin(oidc_app, request, "outsider@gmail.com")
    with pytest.raises(ImmediateHttpResponse):
        _adapter().pre_social_login(request, sl)


@pytest.mark.django_db
def test_pre_social_login_links_admin_created_user_by_email(oidc_app):
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount

    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import TEST_PASSWORD

    admin_made = User.objects.create_user(
        username="teacher", email="teacher@school.edu", password=TEST_PASSWORD
    )
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "teacher@school.edu", username="ignored")
    _adapter().pre_social_login(request, sl)
    # Linked to the existing user (no new account); email now verified+primary.
    assert SocialAccount.objects.filter(user=admin_made).exists()
    assert not User.objects.filter(username="ignored").exists()
    assert EmailAddress.objects.filter(
        user=admin_made, email="teacher@school.edu", verified=True, primary=True
    ).exists()


# The plan's original spelling of this test asserted the clash guard *denies* for a
# verified-on-A + bare-User.email-on-B layout. That is unreachable by construction:
# resolve_user_for_email returns the verified-EmailAddress owner (tier 1 = A), so the
# guard verified_email_belongs_to_other(email, A) is False (A owns the only verified
# row) and the link path connects to A. A second verified row is also barred at the DB
# (unique_verified_email), so the guard can never fire from inside pre_social_login --
# it is the documented-inert protection the adapter keeps for resolver drift. This test
# asserts the *real* behavior of that layout: link to the verified owner A, never B, and
# pre-verify A's email. The guard's denial contract itself is covered directly by
# test_verified_clash_detects_other_owner above.
@pytest.mark.django_db
def test_pre_social_login_links_to_verified_owner_not_email_twin(oidc_app):
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount

    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import TEST_PASSWORD
    from tests.factories import make_verified_user

    owner_a = make_verified_user(username="owner_a", email="clash@school.edu")
    User.objects.filter(username="owner_a").update(email="other@school.edu")
    # user A owns the verified EmailAddress clash@school.edu; user B has User.email
    # = clash@school.edu (no EmailAddress row).
    user_b = User.objects.create_user(
        username="owner_b", email="clash@school.edu", password=TEST_PASSWORD
    )
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "clash@school.edu", username="ignored")
    _adapter().pre_social_login(request, sl)
    # Linked to the verified owner A; B is untouched; no spurious denial.
    assert SocialAccount.objects.filter(user=owner_a).exists()
    assert not SocialAccount.objects.filter(user=user_b).exists()
    assert not User.objects.filter(username="ignored").exists()
    assert EmailAddress.objects.filter(
        user=owner_a, email="clash@school.edu", verified=True, primary=True
    ).exists()


@pytest.mark.django_db
def test_save_user_creates_verified_user_and_consumes_invite(oidc_app):
    from allauth.account.models import EmailAddress

    from accounts.models import Invitation
    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    inv = Invitation.objects.create(email="invitee@school.edu")
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "invitee@school.edu", username="invitee")
    sl._libli_invitation = inv
    user = _adapter().save_user(request, sl)
    assert User.objects.filter(username="invitee").exists()
    assert EmailAddress.objects.filter(
        user=user, email="invitee@school.edu", verified=True, primary=True
    ).exists()
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_save_user_fallback_consumes_invite_without_stash(oidc_app):
    from accounts.models import Invitation
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    inv = Invitation.objects.create(email="fallback@school.edu")
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "fallback@school.edu", username="fallback")
    # No _libli_invitation stashed -> fallback re-lookup by user.email.
    _adapter().save_user(request, sl)
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_save_user_does_not_consume_expired_invite(oidc_app):
    import datetime

    from django.utils import timezone

    from accounts.models import Invitation
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    inv = Invitation.objects.create(
        email="stale@school.edu",
        expires_at=timezone.now() - datetime.timedelta(days=1),
    )
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "stale@school.edu", username="stale")
    sl._libli_invitation = inv
    _adapter().save_user(request, sl)
    inv.refresh_from_db()
    assert inv.accepted_at is None  # re-validated as invalid -> not consumed


def _complete(request, sociallogin):
    # Enter allauth's request context (its middleware normally does this), so the
    # `allauth.core.context.request` ContextVar is populated for any code path that
    # reads it (e.g. _accept_login -> connect(context.request, user)).
    from allauth.core import context
    from allauth.socialaccount.helpers import complete_social_login

    with context.request_context(request):
        return complete_social_login(request, sociallogin)


@pytest.mark.django_db
def test_e2e_new_allowed_identity_becomes_logged_in_student(
    oidc_app, settings_open_policy_school_only
):
    from allauth.account.models import EmailAddress

    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    request = make_request()
    sl = make_sociallogin(oidc_app, request, "kid@school.edu", username="kid")
    response = _complete(request, sl)
    assert response.status_code == 302  # logged in, redirected to LOGIN_REDIRECT_URL
    user = User.objects.get(username="kid")
    assert user.groups.filter(name="Student").exists()
    assert EmailAddress.objects.filter(
        user=user, email="kid@school.edu", verified=True, primary=True
    ).exists()
    assert request.user == user or request.session.get("_auth_user_id")


@pytest.mark.django_db
def test_e2e_denied_identity_renders_not_provisioned_no_account(
    oidc_app, settings_invite_policy
):
    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    request = make_request()
    sl = make_sociallogin(oidc_app, request, "stranger@school.edu", username="stranger")
    response = _complete(request, sl)
    # ImmediateHttpResponse(redirect(...)) is caught by complete_login and returned
    # as the redirect verbatim — a deterministic 302 to the not-provisioned page.
    assert response.status_code == 302
    assert response["Location"] == "/sso/not-provisioned/"
    assert not User.objects.filter(username="stranger").exists()


@pytest.mark.django_db
def test_e2e_invited_identity_provisions_and_consumes_invite(
    oidc_app, settings_invite_policy
):
    from accounts.models import Invitation
    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin

    inv = Invitation.objects.create(email="welcome@school.edu")
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "welcome@school.edu", username="welcome")
    response = _complete(request, sl)
    assert response.status_code == 302
    assert User.objects.filter(username="welcome").exists()
    inv.refresh_from_db()
    assert inv.accepted_at is not None


@pytest.mark.django_db
def test_e2e_links_open_signup_user_by_verified_emailaddress(
    oidc_app, settings_open_policy_school_only
):
    # The tier-1 link path that allauth owns: lookup() runs first (in the real flow)
    # and auto-connects to the user owning a *verified* EmailAddress. No duplicate.
    from allauth.socialaccount.models import SocialAccount

    from accounts.models import User
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import make_verified_user

    existing = make_verified_user(username="alice", email="alice@school.edu")
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "alice@school.edu", username="ignored")
    response = _complete(request, sl)
    assert response.status_code == 302
    assert not User.objects.filter(username="ignored").exists()  # linked, not created
    assert SocialAccount.objects.filter(user=existing).exists()


@pytest.mark.django_db
def test_e2e_link_does_not_add_student_to_existing_role(
    oidc_app, settings_open_policy_school_only
):
    from django.contrib.auth.models import Group

    from accounts.models import User
    from institution.roles import PLATFORM_ADMIN
    from tests._sso import make_request
    from tests._sso import make_sociallogin
    from tests.factories import TEST_PASSWORD

    # An existing admin-created PA (no Student group, no EmailAddress row).
    pa = User.objects.create_user(
        username="boss", email="boss@school.edu", password=TEST_PASSWORD
    )
    pa.groups.add(Group.objects.get_or_create(name=PLATFORM_ADMIN)[0])
    request = make_request()
    sl = make_sociallogin(oidc_app, request, "boss@school.edu", username="ignored")
    _complete(request, sl)
    pa.refresh_from_db()
    assert pa.groups.filter(name=PLATFORM_ADMIN).exists()
    assert not pa.groups.filter(name="Student").exists()  # linking != signup
    assert not User.objects.filter(username="ignored").exists()
