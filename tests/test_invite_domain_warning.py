import pytest
from django.contrib.messages import get_messages
from django.urls import reverse

from accounts.provisioning import normalized_allowlist
from institution.models import Institution
from tests.factories import make_pa


def test_normalized_allowlist():
    assert normalized_allowlist([" @School.EDU ", "b.com"]) == {"school.edu", "b.com"}


def _send(client, email):
    return client.post(
        reverse("accounts:invitation_send"),
        {"email": email, "role": "Student"},
        follow=True,
    )


@pytest.mark.django_db
def test_warns_on_out_of_domain_invite(client):
    make_pa(client, "pa")
    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    resp = _send(client, "new@outside.com")
    texts = [m.message for m in get_messages(resp.wsgi_request)]
    assert any("outside.com" in t for t in texts)


@pytest.mark.django_db
def test_no_warning_for_in_domain_invite(client):
    make_pa(client, "pa")
    inst = Institution.load()
    inst.allowed_email_domains = ["school.edu"]
    inst.save()
    resp = _send(client, "new@school.edu")
    texts = " ".join(m.message for m in get_messages(resp.wsgi_request))
    assert "not in your allowed" not in texts


@pytest.mark.django_db
def test_no_warning_when_allowlist_empty(client):
    make_pa(client, "pa")  # default allowlist is empty
    resp = _send(client, "new@anywhere.com")
    texts = " ".join(m.message for m in get_messages(resp.wsgi_request))
    assert "not in your allowed" not in texts
