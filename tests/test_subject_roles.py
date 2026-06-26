import pytest
from django.contrib.auth.models import Group

from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles

pytestmark = pytest.mark.django_db

SUBJECT_PERMS = {"add_subject", "change_subject", "delete_subject"}


def test_platform_admin_holds_subject_perms():
    seed_roles()
    pa = Group.objects.get(name=PLATFORM_ADMIN)
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert SUBJECT_PERMS <= codenames


def test_platform_admin_does_not_hold_view_subject():
    seed_roles()
    pa = Group.objects.get(name=PLATFORM_ADMIN)
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert "view_subject" not in codenames
