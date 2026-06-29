import pytest
from django.urls import reverse

from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_nav_has_my_tags_link_when_authenticated(client):
    make_login(client, "taguser")
    resp = client.get(reverse("home"))
    assert reverse("tags:my_tags").encode() in resp.content


def test_nav_no_my_tags_link_when_anonymous(client):
    resp = client.get(reverse("home"))
    assert reverse("tags:my_tags").encode() not in resp.content
