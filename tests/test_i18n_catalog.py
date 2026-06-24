import pytest
from django.urls import reverse

from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_catalog_heading_translated_to_polish(client):
    make_login(client, "i1")
    # LocaleMiddleware re-activates the language per request from the session /
    # Accept-Language — translation.override() alone does NOT control what the test
    # client renders. Mirror the proven pattern in tests/test_i18n_results.py.
    session = client.session
    session["_language"] = "pl"
    session.save()
    resp = client.get(reverse("courses:catalog"), HTTP_ACCEPT_LANGUAGE="pl")
    # "Browse courses" must NOT appear untranslated; the PL strings must be present.
    assert b"Browse courses" not in resp.content
    assert "Przeglądaj kursy".encode() in resp.content
    # A second new string, so a single missed/typo'd extraction is caught.
    assert b"Filtruj" in resp.content
