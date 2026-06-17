"""Done-gate: every WS4 settings string must be translated to PL.

Gates on the exact msgids introduced by Tasks 7-8 (NOT an aggregate empty-count
delta, which can mask a new untranslated string). Reused/pre-existing msgids
(Save changes / Cancel / Settings / Light / Dark / Auto / English / Polski) are
deliberately excluded — they were translated in earlier work.
"""

import pytest
from django.utils import translation

WS4_NEW_MSGIDS = [
    # user_settings.html
    "Manage your account and preferences.",
    "How you appear in libli, and the email we use for password resets.",
    "Display name",
    "Shown as the author on content you create.",
    "Set by your school — can’t be changed here.",
    "Used for password resets and notices. Optional for class accounts.",
    "Applies to your view of libli on this account.",
    "Interface language. Content stays in whatever language it was written.",
    "“Auto” follows your device’s light/dark setting.",
    "Keep your account safe. Passwords are hashed server-side.",
    "Change password…",
    "Set password…",
    "Not connected",
    # institution_settings.html
    "Defaults and policy for everyone at your institution.",
    "Your institution’s name and logo, shown across libli.",
    "Displayed on sign-in, invites, and the app header.",
    "PNG or SVG, square works best. Optional.",
    "Which interface languages people can choose, and the default for new accounts.",
    "Enabled languages",
    "At least one must stay enabled.",
    "Default language",
    "Used for new accounts and signed-out pages. Must be an enabled language.",
    "The starting theme for new accounts. Each person can still change their own.",
    "Default theme",
    "“Auto” follows each device’s light/dark setting.",
    "How new people get into libli.",
    "Sign-up policy",
    "Controls who can create an account.",
    "People join only via an invite link or code an admin sends.",
    "Anyone with a confirmed email can create their own account.",
    # form/model choice labels (institution/models.py + institution/forms.py)
    "Invite only",
    "Open self-signup",
    "Logo must be 2 MB or smaller.",
    "This email is already in use by another account.",
]


@pytest.mark.parametrize("msgid", WS4_NEW_MSGIDS)
def test_ws4_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        out = translation.gettext(msgid)
    assert out and out != msgid, f"WS4 msgid not translated to PL: {msgid!r}"
