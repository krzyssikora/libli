import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_guide_is_public_and_renders(client):
    resp = client.get(reverse("integrations:webhook_guide"))
    assert resp.status_code == 200  # no login required
    body = resp.content.decode()
    assert "Verifying the signature" in body
    assert "<pre>" in body  # a rendered fenced code block
