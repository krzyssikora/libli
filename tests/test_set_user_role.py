import pytest

from accounts.models import User
from accounts.services import set_user_role
from grouping.models import Cohort
from grouping.models import CohortMembership
from institution.roles import PLATFORM_ADMIN
from institution.roles import STUDENT
from institution.roles import TEACHER
from institution.roles import seed_roles


@pytest.fixture
def roles(db):
    seed_roles()


@pytest.mark.django_db
def test_set_role_makes_user_hold_exactly_one_group(roles):
    user = User.objects.create_user(username="u1")
    set_user_role(user, TEACHER)
    assert list(user.groups.values_list("name", flat=True)) == [TEACHER]
    set_user_role(user, PLATFORM_ADMIN)
    assert list(user.groups.values_list("name", flat=True)) == [PLATFORM_ADMIN]


@pytest.mark.django_db
def test_set_role_sets_is_staff_from_role(roles):
    user = User.objects.create_user(username="u2")
    set_user_role(user, TEACHER)
    user.refresh_from_db()
    assert user.is_staff is True
    set_user_role(user, STUDENT)
    user.refresh_from_db()
    assert user.is_staff is False


@pytest.mark.django_db
def test_superuser_keeps_is_staff_even_as_student(roles):
    su = User.objects.create_superuser(username="root", password="x")
    set_user_role(su, STUDENT)
    su.refresh_from_db()
    assert su.is_staff is True  # admin recovery path preserved
    assert su.is_superuser is True  # never modified


@pytest.mark.django_db
def test_demotion_to_student_rejoins_default_cohort(roles):
    # Guards the is_staff-before-groups.set ordering: the Phase-3a cohort signal
    # reads is_staff during groups.set. A Teacher (staff, no cohort) demoted to
    # Student (non-staff) must be (re)joined to the Default cohort. Use the REAL
    # default cohort (migration grouping/0002 creates one) — keying on the literal
    # name "Default" could collide with the partial-unique is_default index.
    if not Cohort.objects.filter(is_default=True).exists():
        Cohort.objects.create(name="Default", is_default=True)
    user = User.objects.create_user(username="u3")
    set_user_role(user, TEACHER)
    assert not CohortMembership.objects.filter(user=user).exists()
    set_user_role(user, STUDENT)
    assert CohortMembership.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_blank_role_is_rejected(roles):
    user = User.objects.create_user(username="u4")
    with pytest.raises(ValueError):
        set_user_role(user, "")
