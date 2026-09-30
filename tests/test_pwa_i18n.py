"""PWA C1: Polish renderings of the new strings."""

import json

import pytest
from django.urls import reverse

from institution.models import Institution

pytestmark = pytest.mark.django_db


def test_offline_page_in_polish(client):
    response = client.get(reverse("core:offline"), headers={"accept-language": "pl"})
    body = response.content.decode()
    assert "Jesteś offline" in body
    assert "Sprawdź połączenie z internetem i spróbuj ponownie." in body
    assert "Spróbuj ponownie" in body


def test_manifest_description_in_the_default_language_pl(client):
    inst = Institution.load()
    inst.enabled_languages = ["en", "pl"]
    inst.default_language = "pl"
    inst.save()
    data = json.loads(
        client.get(
            reverse("core:webmanifest"), headers={"accept-language": "en"}
        ).content
    )
    assert data["lang"] == "pl"
    assert data["description"] == "Lekcje i kursy Twojej szkoły"


def test_install_link_in_polish(client):
    # Anonymous surface (the public footer): a logged-in user's stored language
    # preference could outrank the Accept-Language header.
    url = reverse("core:privacy")
    body = client.get(url, headers={"accept-language": "pl"}).content.decode()
    assert "Zainstaluj aplikację" in body


def test_install_page_title_and_description_in_polish(client):
    # The composed <title> and the meta description come from the msgids; the
    # markdown's own "# Instalacja aplikacji" heading would pass a bare substring
    # check with no catalog at all.
    url = reverse("core:install_app")
    body = client.get(url, headers={"accept-language": "pl"}).content.decode()
    assert "<title>Instalacja aplikacji ·" in body
    assert (
        '<meta name="description" content="Jak dodać libli jako aplikację na '
        'telefonie, tablecie lub komputerze.">'
    ) in body
