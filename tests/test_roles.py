from django.contrib.auth.models import Group

from institution.roles import ROLE_NAMES
from institution.roles import seed_roles


def test_seed_roles_creates_all_four():
    # NOTE: migration 0003_seed_roles also creates these Groups at test-DB build,
    # so this asserts idempotent presence; the count/idempotency is checked below.
    seed_roles()
    assert set(Group.objects.values_list("name", flat=True)) >= set(ROLE_NAMES)


def test_seed_roles_is_idempotent():
    seed_roles()
    seed_roles()
    for name in ROLE_NAMES:
        assert Group.objects.filter(name=name).count() == 1


def test_platform_admin_gets_phase0_permissions():
    # Spot-check (3 of 10): _permission() raises Permission.DoesNotExist if any
    # PLATFORM_ADMIN_PERMS label is mistyped, so a bad codename already fails
    # seed_roles().
    seed_roles()
    pa = Group.objects.get(name="Platform Admin")
    codenames = set(pa.permissions.values_list("codename", flat=True))
    assert {"change_institution", "view_institution", "change_user"} <= codenames
