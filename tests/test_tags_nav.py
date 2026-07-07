import pytest
from django.urls import reverse

from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_nav_has_tags_and_notes_link_when_authenticated(client):
    make_login(client, "taguser")
    resp = client.get(reverse("home"))
    # The personal tags/notes surface is reached via the "Tags & notes" hub; the nav
    # link was renamed from "My tags"/tags:my_tags in the tags-and-notes-hub slice.
    assert reverse("notes:overview").encode() in resp.content


def test_nav_no_tags_and_notes_link_when_anonymous(client):
    resp = client.get(reverse("home"))
    assert reverse("notes:overview").encode() not in resp.content
