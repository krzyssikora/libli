"""PWA C1: manifest identity fields and the iOS head tags (spec §5)."""

import json

import pytest
from django.urls import reverse

from core.services import short_name
from institution.models import Institution

pytestmark = pytest.mark.django_db


def _manifest(client, **headers):
    return json.loads(client.get(reverse("core:webmanifest"), headers=headers).content)


def test_manifest_identity_fields(client):
    data = _manifest(client)
    assert data["id"] == "/"
    assert data["scope"] == "/"
    assert data["lang"] == "en"
    assert data["description"] == "Lessons and courses from your school"


def test_manifest_description_follows_default_language_not_the_session(client):
    inst = Institution.load()
    inst.default_language = "en"
    inst.save()
    data = _manifest(client, **{"accept-language": "pl"})
    assert data["lang"] == "en"
    assert data["description"] == "Lessons and courses from your school"


def test_head_carries_the_ios_app_title_and_capable_tags(client):
    inst = Institution.load()
    inst.name = "Liceum Ogólnokształcące nr 5"
    inst.save()
    body = client.get(reverse("account_login")).content.decode()
    assert (
        f'<meta name="apple-mobile-web-app-title" content="{short_name(inst.name)}">'
        in body
    )
    assert '<meta name="mobile-web-app-capable" content="yes">' in body
