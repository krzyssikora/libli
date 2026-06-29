import pytest

from accounts.forms import AcceptInviteForm
from accounts.models import Invitation
from accounts.models import User
from accounts.services import set_user_role
from accounts.views import _consume_and_create
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import TEST_PASSWORD


@pytest.mark.django_db
def test_local_accept_assigns_invited_role():
    seed_roles()
    inv = Invitation.objects.create(email="newteacher@school.edu", role=TEACHER)
    form = AcceptInviteForm(
        {"username": "newteacher", "password": TEST_PASSWORD},
        invited_email=inv.email,
    )
    assert form.is_valid(), form.errors
    user = _consume_and_create(inv, form)
    assert list(user.groups.values_list("name", flat=True)) == [TEACHER]
    assert user.is_staff is True


@pytest.mark.django_db
def test_signal_skips_when_role_already_assigned():
    # Simulates the SSO order: set_user_role ran in save_user, THEN user_signed_up
    # fires. The signal must NOT add Student on top of the already-assigned role.
    from accounts.signals import assign_default_student_group

    seed_roles()
    user = User.objects.create_user(username="ssoteacher")
    set_user_role(user, TEACHER)
    assign_default_student_group(sender=None, request=None, user=user)
    assert list(user.groups.values_list("name", flat=True)) == [TEACHER]


@pytest.mark.django_db
def test_accept_sets_display_name():
    seed_roles()
    inv = Invitation.objects.create(email="named@school.edu", role=TEACHER)
    form = AcceptInviteForm(
        {
            "username": "nameduser",
            "display_name": "Named User",
            "password": TEST_PASSWORD,
        },
        invited_email=inv.email,
    )
    assert form.is_valid(), form.errors
    user = _consume_and_create(inv, form)
    assert user.display_name == "Named User"
