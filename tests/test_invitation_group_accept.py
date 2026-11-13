import pytest

from accounts.models import Invitation
from accounts.models import User
from courses.models import Enrollment
from grouping.models import GroupMembership
from institution.roles import TEACHER
from notifications.models import Notification
from tests.factories import TEST_PASSWORD
from tests.factories import GroupFactory


def _accept(client, inv, username="newkid"):
    return client.post(
        f"/invite/accept/{inv.token}/",
        {"username": username, "password": TEST_PASSWORD},
    )


@pytest.mark.django_db
def test_password_accept_with_group_enrols(client):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)
    response = _accept(client, inv)
    assert response.status_code == 302
    user = User.objects.get(username="newkid")
    assert GroupMembership.objects.filter(group=g, student=user).exists()
    assert Enrollment.objects.filter(
        student=user, course=g.course, source="group"
    ).exists()
    assert (
        Notification.objects.filter(
            recipient=user, kind=Notification.Kind.ENROLLED
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_password_accept_without_group_no_membership(client):
    inv = Invitation.objects.create(email="kid@school.edu")
    _accept(client, inv)
    user = User.objects.get(username="newkid")
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_password_accept_archived_group_creates_account_only(client):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)
    g.archived = True
    g.save()
    _accept(client, inv)
    user = User.objects.get(username="newkid")
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_password_accept_deleted_group_creates_account_only(client):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)
    g.delete()
    response = _accept(client, inv)
    assert response.status_code == 302
    user = User.objects.get(username="newkid")
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_password_accept_non_student_row_with_group_no_membership(client):
    g = GroupFactory()
    # objects.create bypasses clean(), so the invalid combination can exist.
    inv = Invitation.objects.create(email="t@school.edu", role=TEACHER, group=g)
    _accept(client, inv)
    user = User.objects.get(username="newkid")
    assert not GroupMembership.objects.filter(student=user).exists()


@pytest.mark.django_db
def test_password_accept_helper_failure_rolls_back(client, monkeypatch):
    g = GroupFactory()
    inv = Invitation.objects.create(email="kid@school.edu", group=g)

    def boom(invitation, user):
        raise RuntimeError("boom")

    monkeypatch.setattr("accounts.views.apply_invitation_group", boom)
    client.raise_request_exception = True
    with pytest.raises(RuntimeError):
        _accept(client, inv)
    assert not User.objects.filter(username="newkid").exists()
    inv.refresh_from_db()
    assert inv.accepted_at is None
