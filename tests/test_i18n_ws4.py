"""Done-gate: every WS4 settings string must be translated to PL.

Gates on the exact msgids introduced by Tasks 3–8 (NOT an aggregate empty-count
delta, which can mask a new untranslated string). The list spans the user-settings
template (user_settings.html) and the still-live form/model strings in
institution/forms.py, institution/models.py, and core/forms.py.

The 5c cutover retired the old core institution-settings template; its strings moved
to the new /manage/settings/ surface (templates/institution/manage/) and their PL
translation is gated by the Phase-5c i18n done-check, not by this WS4 list.

Intentionally excluded because already translated (not part of this gate):
"Save changes" (added by WS4 but translated in the same commit), "Light",
"Dark", "Auto" (institution/models theme choices), and the truly pre-existing
"Cancel" / "Settings" / "English" / "Polski".
"""

import pytest
from django.utils import translation

# MAINTENANCE: this list must mirror every WS4 msgid character-for-character
# (curly quotes “ ” ’, em-dash —, trailing ellipsis …). If you rename a string
# in a template/form, update the msgid in locale/pl/LC_MESSAGES/django.po AND
# this list together, then recompile the .mo.
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
