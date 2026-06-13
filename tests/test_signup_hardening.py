from django.core import mail

from accounts.models import User
from institution.models import Institution


def _open_signup():
    inst = Institution.load()
    inst.signup_policy = "open"
    inst.save()


def test_open_signup_sends_verification_and_blocks_login_until_verified(client):
    _open_signup()
    mail.outbox.clear()
    response = client.post(
        "/accounts/signup/",
        {
            "username": "pending",
            "email": "pending@school.edu",
            "password1": "Sup3r!pass9",
            "password2": "Sup3r!pass9",
        },
    )
    # Successful signup redirects to the verification-sent page.
    assert response.status_code == 302
    # Account exists but a verification email was sent (mandatory verification).
    assert User.objects.filter(username="pending").exists()
    assert len(mail.outbox) == 1
    assert "pending@school.edu" in mail.outbox[0].to

    # Logging out then back in is blocked until the email is verified: allauth
    # sends the login into the "verification sent" flow and establishes no
    # authenticated session.
    client.post("/accounts/logout/")
    response = client.post(
        "/accounts/login/", {"login": "pending", "password": "Sup3r!pass9"}
    )
    assert response.status_code == 302
    # allauth's verification-sent page.
    assert "/confirm-email/" in response["Location"]
    # Positively: no authenticated session.
    assert not client.session.get("_auth_user_id")


def test_honeypot_filled_submission_creates_no_account(client):
    _open_signup()
    before = User.objects.count()
    response = client.post(
        "/accounts/signup/",
        {
            "username": "bot",
            "email": "bot@school.edu",
            "password1": "Sup3r!pass9",
            "password2": "Sup3r!pass9",
            "phone_number": "i-am-a-bot",  # the honeypot trap field
        },
    )
    # allauth fakes a *successful* signup (302 redirect) while creating nothing
    # — asserting the redirect distinguishes "bot trapped" from an unrelated 200
    # form rejection.
    assert response.status_code == 302
    assert User.objects.count() == before
    assert not User.objects.filter(username="bot").exists()


def test_open_signup_requires_email(client):
    # Spec §4: email is required (and confirmed) on the open self-signup form. A
    # blank-email POST must be rejected (form re-renders 200, no account) — this
    # pins the "email*" marker in ACCOUNT_SIGNUP_FIELDS that the bot-defense +
    # SSO-linkage story depends on.
    _open_signup()
    before = User.objects.count()
    response = client.post(
        "/accounts/signup/",
        {
            "username": "noemail",
            "email": "",
            "password1": "Sup3r!pass9",
            "password2": "Sup3r!pass9",
        },
    )
    # Form re-rendered with errors, not a 302 redirect.
    assert response.status_code == 200
    assert User.objects.count() == before
    assert not User.objects.filter(username="noemail").exists()


def test_password_reset_unknown_email_does_not_enumerate(client):
    # allauth defaults to ACCOUNT_PREVENT_ENUMERATION=True (and
    # ACCOUNT_EMAIL_UNKNOWN_ACCOUNTS=True): a reset for an address with NO
    # account returns the SAME generic 302 to the reset-done page AND still
    # sends a courtesy email — so known vs unknown are indistinguishable. The
    # non-enumeration contract is "identical observable behavior", not "no
    # email". (Both defaults are on without us setting anything; see Task 1.)
    mail.outbox.clear()
    response = client.post("/accounts/password/reset/", {"email": "nobody@nowhere.edu"})
    assert response.status_code == 302
    assert response["Location"].endswith("/password/reset/done/")
    # enumeration-prevention email; UX identical to a real account
    assert len(mail.outbox) == 1


def test_password_reset_known_email_sends_link(client):
    from tests.factories import make_verified_user

    make_verified_user(username="resetme", email="resetme@school.edu")
    mail.outbox.clear()
    response = client.post("/accounts/password/reset/", {"email": "resetme@school.edu"})
    # Identical observable behavior to the unknown-email case above (same 302,
    # same outbox count) — that symmetry is exactly what defeats enumeration.
    assert response.status_code == 302
    assert response["Location"].endswith("/password/reset/done/")
    assert len(mail.outbox) == 1
    assert "resetme@school.edu" in mail.outbox[0].to
