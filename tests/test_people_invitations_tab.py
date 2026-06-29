import pytest
from django.contrib.auth.models import Group as AuthGroup
from django.urls import reverse

from accounts.models import Invitation
from accounts.models import User
from institution.roles import PLATFORM_ADMIN
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user


def make_pa(client, username="pa"):
    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@school.edu", password=TEST_PASSWORD
    )
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    client.force_login(user)
    return user


@pytest.mark.django_db
def test_send_creates_invitation_with_role(
    client, django_capture_on_commit_callbacks, mailoutbox
):
    pa = make_pa(client, "pa_send")
    # The new-invite email is sent by the post_save signal via transaction.on_commit,
    # so capture+execute on_commit callbacks to observe the email under the test.
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            reverse("accounts:invitation_send"),
            {"email": "invitee@school.edu", "role": TEACHER},
        )
    assert resp.status_code == 302
    inv = Invitation.objects.get(email="invitee@school.edu")
    assert inv.role == TEACHER
    assert inv.invited_by == pa
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_send_to_existing_account_shows_error(client, mailoutbox):
    make_pa(client, "pa_dup")
    User.objects.create_user(username="taken", email="taken@school.edu")
    resp = client.post(
        reverse("accounts:invitation_send"),
        {"email": "taken@school.edu", "role": "Student"},
    )
    assert resp.status_code == 200  # re-renders with form error
    assert not Invitation.objects.filter(email="taken@school.edu").exists()
    assert len(mailoutbox) == 0


@pytest.mark.django_db
def test_revoke_deletes_pending(client):
    make_pa(client, "pa_rev")
    inv = Invitation.objects.create(email="rev@school.edu")
    resp = client.post(reverse("accounts:invitation_revoke", args=[inv.pk]))
    assert resp.status_code == 302
    assert not Invitation.objects.filter(pk=inv.pk).exists()


@pytest.mark.django_db
def test_list_shows_pending_invite_with_role(client):
    make_pa(client, "pa_listinv")
    Invitation.objects.create(email="pend@school.edu", role=TEACHER)
    resp = client.get(reverse("accounts:people_invitations"))
    assert resp.status_code == 200
    assert "pend@school.edu" in resp.content.decode()
