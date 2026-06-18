"""Done-gate: every NEW auth-redesign msgid is translated to PL, and the catalog
is clean (no untranslated / fuzzy / obsolete). Mirrors test_i18n_ws4.py."""

from pathlib import Path

import pytest
from django.utils import translation

ROOT = Path(__file__).resolve().parent.parent
POFILE = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"

AUTH_NEW_MSGIDS = [
    # login.html
    "Sign in · %(site_name)s",
    "Sign in to %(site_name)s",
    "Welcome back — pick up where you left off.",
    "Username or email",
    "Remember me",
    "Sign in",
    "or",
    "Continue with %(provider_name)s",
    "No account?",
    "Sign up",
    "No account? Ask your administrator.",
    # signup.html
    "Create your account",
    "Already have an account?",
    # password_reset.html
    "Reset your password",
    "Enter your email and we'll send you a reset link.",
    "Send reset link",
    "Back to sign in",
    # password_reset_done.html
    "Check your email",
    "If an account matches, a password reset link is on its way.",
    # password_reset_from_key.html
    "Set a new password",
    "This reset link is invalid or expired.",
    "Request a new link",
    "Set password",
    # password_reset_from_key_done.html
    "Password changed",
    "Your password has been updated.",
    # accept_invite.html
    "Accept invitation",
    "Accept your invitation",
    "Creating an account for %(email)s.",
    "Create account",
    # sso_not_provisioned.html
    "Account not provisioned",
    (
        "Your account isn't provisioned for this platform"
        " — please contact your administrator."
    ),
    # password_change.html
    "Change password",
]


@pytest.mark.parametrize("msgid", AUTH_NEW_MSGIDS)
def test_auth_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        translated = str(translation.gettext(msgid))
        assert translated != msgid, f"untranslated PL msgid: {msgid!r}"


def test_po_catalog_clean():
    text = POFILE.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"


def test_old_refreshed_msgid_retired():
    text = POFILE.read_text(encoding="utf-8")
    assert "refreshed to the latest." not in text, (
        "the duplicate JS msgid must be removed"
    )
    assert "reloaded to the latest." in text, "the canonical msgid must remain"
