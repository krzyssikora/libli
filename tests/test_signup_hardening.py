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
