import pytest
from django.core.exceptions import ValidationError

from grouping import services
from grouping.models import Cohort
from grouping.models import CohortMembership
from tests.factories import CohortFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_promote_default_demotes_old_default():
    old = Cohort.objects.get(is_default=True)
    new = CohortFactory(name="Year 8")
    services.promote_default(new)
    old.refresh_from_db()
    new.refresh_from_db()
    assert new.is_default is True
    assert old.is_default is False
    assert Cohort.objects.filter(is_default=True).count() == 1


def test_delete_cohort_reassigns_members_to_default():
    default = services.get_default_cohort()
    other = CohortFactory(name="Spanish")
    user = UserFactory()
    services.assign_student_to_cohort(user, other)
    services.delete_cohort(other)
    assert not Cohort.objects.filter(pk=other.pk).exists()
    assert CohortMembership.objects.get(user=user).cohort == default


def test_archive_cohort_reassigns_and_hides():
    default = services.get_default_cohort()
    other = CohortFactory(name="French")
    user = UserFactory()
    services.assign_student_to_cohort(user, other)
    services.archive_cohort(other)
    other.refresh_from_db()
    assert other.archived is True
    assert CohortMembership.objects.get(user=user).cohort == default


def test_cannot_delete_default_cohort():
    default = services.get_default_cohort()
    with pytest.raises(ValidationError):
        services.delete_cohort(default)


def test_cannot_archive_default_cohort():
    default = services.get_default_cohort()
    with pytest.raises(ValidationError):
        services.archive_cohort(default)
