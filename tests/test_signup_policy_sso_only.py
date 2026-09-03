"""The `sso_only` signup policy, and the domain allowlist binding on local signup.

Why this file exists: `allowed_email_domains` used to be enforced in exactly ONE
place -- the SSO provisioning gate (accounts/provisioning.py). The local signup
form consulted `signup_policy` alone (accounts/adapters.py, is_open_for_signup),
so setting the policy to "open" -- which SSO auto-provisioning REQUIRED -- also
opened public password signup to every domain on the internet. `sso_only` gives
a school SSO auto-provisioning with the password door shut; the allowlist
binding closes the hole for any school that still wants "open".

The `sso_only` contract, and what each test pins:
  - the local signup form is CLOSED           (no password door at all)
  - SSO JIT provisioning is ALLOWED, domain-gated
  - invitations still work                    (the manual override survives)
  - existing password accounts can still LOG IN (the init_platform break-glass)

That last pair is what stops this change from locking a school out of its own
instance, so both are asserted positively rather than left implied.
"""

import pytest
from django.urls import reverse

from accounts.models import Invitation
from accounts.models import User
from accounts.provisioning import evaluate_sso_provisioning
from institution.models import Institution
from institution.roles import seed_roles
from tests.factories import TEST_PASSWORD


def _set_policy(policy, domains=None):
    # Institution.load() + .save() -- .save() fires invalidate_site_config, which
    # is what the login-page assertion below depends on (get_site_config is cached
    # and is NOT functools-memoized). Mirrors tests/test_auth_pages.py:75-83.
    inst = Institution.load()
    inst.signup_policy = policy
    inst.allowed_email_domains = domains if domains is not None else []
    inst.save()
    return inst


def _eval(email, policy, domains, invitation=None):
    return evaluate_sso_provisioning(
        email,
        signup_policy=policy,
        allowed_email_domains=domains,
        invitation=invitation,
    )


# --- the SSO provisioning gate ------------------------------------------------


def test_sso_only_provisions_a_new_identity_from_an_allowed_domain():
    # Mutant: revert provisioning.py's policy test to `!= "open"` -> denied.
    decision = _eval("ala@school.edu", "sso_only", ["school.edu"])
    assert decision.allow is True


def test_sso_only_denies_an_identity_from_a_foreign_domain():
    # Mutant: drop the allowlist branch (or let sso_only bypass it) -> allowed.
    # This is what stops sso_only from being "anyone with any Microsoft account".
    decision = _eval("stranger@gmail.com", "sso_only", ["school.edu"])
    assert decision.allow is False
    assert decision.reason == "domain"


def test_invite_policy_still_denies_uninvited_sso_identities():
    # Mutant: widen the policy test to `in ("open", "sso_only", "invite")`, or to
    # a truthiness check -> allowed. Pins that the DEFAULT policy is unchanged.
    decision = _eval("ala@school.edu", "invite", ["school.edu"])
    assert decision.allow is False
    assert decision.reason == "policy"


# --- the local signup form ----------------------------------------------------


@pytest.mark.django_db
def test_sso_only_closes_the_local_signup_form(client):
    # Mutant: make is_open_for_signup `!= "invite"` -> the form renders and the
    # POST creates an account. sso_only must leave NO password door.
    _set_policy("sso_only", ["school.edu"])
    response = client.get("/accounts/signup/")
    assert response.status_code == 200
    # allauth renders account/signup_closed.html at 200; discriminate on the
    # absence of the form's username input, as tests/test_signup_policy.py does.
    assert b'name="username"' not in response.content

    client.post(
        "/accounts/signup/",
        {
            "username": "sneaky",
            "email": "sneaky@school.edu",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    assert not User.objects.filter(username="sneaky").exists()


@pytest.mark.django_db
def test_open_signup_rejects_an_email_outside_the_allowlist(client):
    # THE SECURITY FIX. Mutant: delete PolicySignupForm.clean_email -> the account
    # is created. Before this change the allowlist guarded the SSO door only, so
    # "open" (which SSO auto-provisioning required) admitted any domain here.
    _set_policy("open", ["school.edu"])
    before = User.objects.count()
    response = client.post(
        "/accounts/signup/",
        {
            "username": "stranger",
            "email": "stranger@gmail.com",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    # Form re-rendered with errors, not a 302 redirect.
    assert response.status_code == 200
    assert User.objects.count() == before
    assert not User.objects.filter(username="stranger").exists()


@pytest.mark.django_db
def test_open_signup_accepts_an_email_inside_the_allowlist(client):
    # The converse of the test above -- without it, `clean_email` raising
    # unconditionally would pass the security test and break every real signup.
    _set_policy("open", ["school.edu"])
    response = client.post(
        "/accounts/signup/",
        {
            "username": "ala",
            "email": "ala@school.edu",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    assert response.status_code == 302
    assert User.objects.filter(username="ala").exists()


@pytest.mark.django_db
def test_open_signup_with_no_allowlist_accepts_any_domain(client):
    # An EMPTY allowlist must stay permissive -- it is the shipped default, and
    # evaluate_sso_provisioning already treats it that way (`if allowed_email_
    # domains:`). Mutant: check membership against an empty set -> every signup
    # on a default install breaks.
    _set_policy("open", [])
    response = client.post(
        "/accounts/signup/",
        {
            "username": "anyone",
            "email": "anyone@wherever.com",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        },
    )
    assert response.status_code == 302
    assert User.objects.filter(username="anyone").exists()


# --- the Access settings form -------------------------------------------------


@pytest.mark.django_db
def test_access_form_offers_and_saves_sso_only(client):
    # Drives the SIGNUP_CHOICES entry itself: without it the ModelForm rejects
    # "sso_only" as an invalid choice and re-renders at 200, so a school could
    # never select the policy the SSO gate now honours. (Model .save() bypasses
    # choice validation, which is why every other test here could set it directly
    # -- only the form path proves the choice actually exists.)
    # Mutant: remove the choice from institution/models.py -> 200 and unchanged.
    from tests.factories import make_pa

    make_pa(client)
    response = client.post(
        reverse("institution:settings_access"),
        {"signup_policy": "sso_only", "allowed_email_domains": "school.edu"},
    )
    assert response.status_code == 302
    assert Institution.load().signup_policy == "sso_only"


@pytest.mark.django_db
def test_saving_sso_only_without_sso_enabled_warns_but_still_saves(client):
    # sso_only with no working IdP is not a lockout -- invitations and existing
    # password logins both survive -- so this WARNS rather than refusing. A hard
    # guard is impossible anyway: the wizard's Access step runs BEFORE its SSO
    # step, so refusing would make the policy unselectable where it is offered.
    # Mutant: turn the warning into a ValidationError -> the save 200s and the
    # policy never changes.
    from tests.factories import make_pa

    make_pa(client)
    response = client.post(
        reverse("institution:settings_access"),
        {"signup_policy": "sso_only", "allowed_email_domains": "school.edu"},
        follow=True,
    )
    assert Institution.load().signup_policy == "sso_only"  # saved regardless
    assert b"SSO is not enabled" in response.content


@pytest.mark.django_db
def test_saving_sso_only_with_sso_enabled_does_not_warn(client):
    # The converse: an unconditional warning would be noise on every save and
    # would train admins to ignore it. Mutant: drop the is_enabled() check.
    from tests._sso import make_oidc_app
    from tests.factories import make_pa

    make_oidc_app()  # creates the SocialApp AND attaches it to the current Site
    make_pa(client)
    response = client.post(
        reverse("institution:settings_access"),
        {"signup_policy": "sso_only", "allowed_email_domains": "school.edu"},
        follow=True,
    )
    assert Institution.load().signup_policy == "sso_only"
    assert b"SSO is not enabled" not in response.content


# --- what sso_only must NOT break --------------------------------------------


@pytest.mark.django_db
def test_invitations_still_work_under_sso_only(client):
    # accounts/views.py:accept_invite never consults signup_policy, and
    # AcceptInviteForm calls the adapter's clean_username/clean_password but NOT
    # clean_email -- so an invite is the manual override under every policy,
    # including for an address OUTSIDE the allowlist (an external examiner).
    # Mutant: bind the allowlist adapter-wide instead of on the signup form ->
    # this invite is refused.
    seed_roles()
    _set_policy("sso_only", ["school.edu"])
    invitation = Invitation.objects.create(email="examiner@elsewhere.org")
    response = client.post(
        reverse("accounts:accept_invite", args=[invitation.token]),
        {"username": "examiner", "password": TEST_PASSWORD},
    )
    assert response.status_code == 302
    assert User.objects.filter(username="examiner").exists()


@pytest.mark.django_db
def test_existing_password_user_can_still_log_in_under_sso_only(client):
    # The break-glass path: init_platform creates a Platform Admin WITH a
    # password, and sso_only must gate SIGNUP only, never AUTHENTICATION. Mutant:
    # route the policy into the login view or the auth backend -> a school locks
    # itself out of its own instance the moment it enables SSO.
    from tests.factories import make_verified_user

    make_verified_user(username="admin", email="admin@school.edu")
    _set_policy("sso_only", ["school.edu"])
    response = client.post(
        "/accounts/login/", {"login": "admin", "password": TEST_PASSWORD}
    )
    assert response.status_code == 302
    assert client.session.get("_auth_user_id")


@pytest.mark.django_db
def test_login_page_tells_sso_only_users_to_ask_an_administrator(client):
    # login.html branches on `institution.signup_policy == "open"`. Mutant: a
    # truthiness check, or adding sso_only to the "open" branch -> a Sign up link
    # is offered that leads to a closed form.
    _set_policy("sso_only", ["school.edu"])
    response = client.get("/accounts/login/")
    assert response.status_code == 200
    assert b'href="/accounts/signup/"' not in response.content
