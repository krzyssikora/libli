import pytest

from accounts.models import User
from accounts.services import is_last_active_platform_admin
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles


@pytest.fixture
def roles(db):
    seed_roles()


@pytest.mark.django_db
def test_sole_active_pa_is_last(roles):
    pa = User.objects.create_user(username="pa")
    set_user_role(pa, PLATFORM_ADMIN)
    assert is_last_active_platform_admin(pa) is True


@pytest.mark.django_db
def test_two_pas_neither_is_last(roles):
    pa1 = User.objects.create_user(username="pa1")
    pa2 = User.objects.create_user(username="pa2")
    set_user_role(pa1, PLATFORM_ADMIN)
    set_user_role(pa2, PLATFORM_ADMIN)
    assert is_last_active_platform_admin(pa1) is False


@pytest.mark.django_db
def test_inactive_pa_does_not_count(roles):
    active = User.objects.create_user(username="pa_a")
    inactive = User.objects.create_user(username="pa_i", is_active=False)
    set_user_role(active, PLATFORM_ADMIN)
    set_user_role(inactive, PLATFORM_ADMIN)
    assert is_last_active_platform_admin(active) is True
