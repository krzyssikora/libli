import pytest
from django.urls import reverse

from tests.factories import make_login
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_student_sees_browse_link_on_dashboard(client):
    make_login(client, "n1")
    resp = client.get(reverse("home"))
    assert reverse("courses:catalog").encode() in resp.content


def test_staff_does_not_see_browse_link(client):
    make_pa(client, username="npa")
    resp = client.get(reverse("home"))
    assert reverse("courses:catalog").encode() not in resp.content
