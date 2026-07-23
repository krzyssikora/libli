"""Polish rendering of the error pages + catalog hygiene.

Mirrors tests/test_i18n_catalog.py (render) and
tests/test_i18n_auth.py::test_po_catalog_clean (hygiene).
"""

from pathlib import Path

import pytest
from django.utils import translation

from tests.factories import make_course
from tests.factories import make_login

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent

# All seven msgids this change introduces. Parametrized below so EVERY one is
# proven to resolve -- the two render tests alone would leave `Back to main
# page` and the 404 report line unasserted, and `Back to main page` is exactly
# the entry predicted to come back `#, fuzzy` (a fuzzy entry is ignored at
# runtime, so it would ship untranslated with a correct msgstr in the file).
ERROR_NEW_MSGIDS = [
    "Nothing here",
    (
        "We appreciate your eagerness to discover, but there's nothing at this "
        "address. Check the address you entered, or go back to the main page."
    ),
    (
        "If a link inside the app brought you here, please report it to your "
        "administrator, describing the steps that led to this page."
    ),
    "You tried:",
    "Back to main page",
    "Not for you",
    (
        "This page exists, but your account doesn't have permission to open it. "
        "If you think you should have access, ask your administrator."
    ),
]


def _speak_polish(client):
    # LocaleMiddleware re-activates the language per request from the session /
    # Accept-Language; translation.override() alone does NOT control what the
    # test client renders. The session write must come AFTER any login, because
    # logging in cycles the session and would discard it.
    session = client.session
    session["_language"] = "pl"
    session.save()


def test_404_renders_in_polish(client):
    _speak_polish(client)
    resp = client.get("/no-such-page/", HTTP_ACCEPT_LANGUAGE="pl")
    body = resp.content
    # b"..." for the ASCII string (ruff UP012); .encode() only where there are
    # Polish diacritics.
    assert b"Nic tu nie ma" in body
    assert "Doceniamy zapał do odkrywania".encode() in body
    assert "Próbowano otworzyć:".encode() in body
    assert b"Nothing here" not in body
    assert b"We appreciate your eagerness" not in body


def test_403_renders_in_polish(client):
    from django.urls import reverse

    from tests.factories import UserFactory

    user = make_login(client, "outsider")  # login first...
    _speak_polish(client)  # ...then set the language (login cycles the session)
    # Same no-access shape as tests/test_error_pages.py::_no_access -- a bare
    # make_course() is UNOWNED, which pins none of the four negatives.
    course = make_course(owner=UserFactory())
    assert not user.is_staff and not user.is_superuser
    assert course.owner is not None and course.owner != user

    resp = client.get(
        reverse("courses:course_outline", args=[course.slug]),
        HTTP_ACCEPT_LANGUAGE="pl",
    )
    assert resp.status_code == 403
    body = resp.content
    assert b"Nie dla ciebie" in body
    assert "nie ma uprawnień".encode() in body
    assert b"Not for you" not in body


@pytest.mark.parametrize("msgid", ERROR_NEW_MSGIDS)
def test_every_new_msgid_has_a_polish_translation(msgid):
    # Mirrors test_i18n_auth.py's AUTH_NEW_MSGIDS check. Catches a msgid that
    # was extracted but left untranslated OR left `#, fuzzy` -- gettext returns
    # the msgid unchanged in both cases.
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid, f"no PL translation for {msgid!r}"


@pytest.mark.parametrize("locale", ["pl", "en"])
def test_po_catalog_clean(locale):
    # The three existing guards (test_i18n_auth / test_i18n_notes / test_tags_i18n)
    # read locale/pl ONLY, so without the "en" case here half of this change's
    # catalog churn would ship unguarded.
    text = (ROOT / "locale" / locale / "LC_MESSAGES" / "django.po").read_text(
        encoding="utf-8"
    )
    assert "#, fuzzy" not in text, f"{locale}: fuzzy entries are ignored at runtime"
    assert "#~" not in text, f"{locale}: obsolete entries present -- drop them"


@pytest.mark.parametrize("locale", ["pl", "en"])
def test_retired_msgids_are_gone(locale):
    text = (ROOT / "locale" / locale / "LC_MESSAGES" / "django.po").read_text(
        encoding="utf-8"
    )
    for retired in (
        'msgid "Back to home"',
        'msgid "We couldn\'t find that page."',
        'msgid "You don\'t have permission to view this page."',
    ):
        assert retired not in text, f"{locale}: {retired} is no longer referenced"
