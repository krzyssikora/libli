import pytest

from accounts.models import Invitation
from institution.roles import STUDENT
from institution.roles import TEACHER


@pytest.mark.django_db
def test_invitation_role_defaults_to_student():
    inv = Invitation.objects.create(email="a@school.edu")
    assert inv.role == STUDENT


@pytest.mark.django_db
def test_invitation_role_can_be_set():
    inv = Invitation.objects.create(email="t@school.edu", role=TEACHER)
    inv.refresh_from_db()
    assert inv.role == TEACHER
