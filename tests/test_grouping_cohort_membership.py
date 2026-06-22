import pytest

from grouping.models import Cohort
from grouping.models import CohortMembership
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
