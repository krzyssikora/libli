import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping.models import Cohort
from grouping.models import CohortMembership
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_default_cohort_exists_from_migration():
    assert Cohort.objects.filter(is_default=True, slug="default").count() == 1


def test_new_user_auto_joins_default_cohort():
    user = UserFactory()
    membership = CohortMembership.objects.get(user=user)
    assert membership.cohort.is_default is True
    assert membership.assigned_by is None


def test_membership_creation_is_idempotent():
    user = UserFactory()
    # Saving the user again must not create a second membership (OneToOne).
    user.save()
    assert CohortMembership.objects.filter(user=user).count() == 1


# --- Staff-exclusion invariant tests ---


def test_staff_user_created_gets_no_cohort_membership():
    """A user created with is_staff=True must NOT receive a Default cohort
    membership."""
    from accounts.models import User

    staff = User.objects.create_user(username="staffonly", is_staff=True)
    assert not CohortMembership.objects.filter(user=staff).exists()


def test_student_user_created_gets_default_cohort_membership():
    """A plain student (UserFactory) HAS a Default cohort membership (unchanged)."""
    student = UserFactory()
    assert CohortMembership.objects.filter(user=student).exists()
    assert CohortMembership.objects.get(user=student).cohort.is_default is True


def test_promotion_to_teacher_removes_cohort_membership():
    """A plain student promoted to the Teacher role loses their cohort membership."""
    seed_roles()
    student = UserFactory()
    assert CohortMembership.objects.filter(user=student).exists()

    teacher_group = AuthGroup.objects.get(name=TEACHER)
    student.groups.add(teacher_group)

    assert not CohortMembership.objects.filter(user=student).exists()


def test_demotion_from_teacher_restores_cohort_membership():
    """A Teacher (no cohort membership) demoted back to student gets Default
    membership."""
    seed_roles()
    from accounts.models import User

    teacher = User.objects.create_user(username="exteacher")
    teacher_group = AuthGroup.objects.get(name=TEACHER)
    teacher.groups.add(teacher_group)
    # After add, should have no membership (they were never in Default)
    assert not CohortMembership.objects.filter(user=teacher).exists()

    teacher.groups.remove(teacher_group)
    assert CohortMembership.objects.filter(user=teacher).exists()
    assert CohortMembership.objects.get(user=teacher).cohort.is_default is True
