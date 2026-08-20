import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import transaction

from grouping.models import Allocation
from grouping.models import Group
from grouping.models import GroupMembership
from tests.factories import AllocationFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory

pytestmark = pytest.mark.django_db


def test_allocation_str_is_its_name():
    a = AllocationFactory(name="matematyka 2026")
    assert str(a) == "matematyka 2026"


def test_group_rejects_allocation_from_another_course():
    """Spec: the course-scoping invariant, enforced in Group.save."""
    group = GroupFactory()
    foreign = AllocationFactory(course=CourseFactory())
    group.allocation = foreign
    with pytest.raises(ValidationError):
        group.save()


def test_group_accepts_allocation_on_its_own_course():
    group = GroupFactory()
    a = AllocationFactory(course=group.course)
    group.allocation = a
    group.save()
    group.refresh_from_db()
    assert group.allocation_id == a.pk


def test_allocation_course_frozen_once_groups_attached():
    a = AllocationFactory()
    GroupFactory(course=a.course, allocation=a)
    a.course = CourseFactory()
    with pytest.raises(ValidationError):
        a.save()


def test_allocation_course_editable_while_no_groups_attached():
    a = AllocationFactory()
    other = CourseFactory()
    a.course = other
    a.save()
    a.refresh_from_db()
    assert a.course_id == other.pk


def test_allocation_name_unique_per_course():
    a = AllocationFactory(name="Klasy")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Allocation.objects.create(course=a.course, name="Klasy")


def test_the_constraint_is_case_sensitive_so_the_form_must_dedup():
    """Pins WHY AllocationForm.clean() does an iexact lookup: the DB constraint
    does not catch "klasy" beside "Klasy"."""
    a = AllocationFactory(name="Klasy")
    other = Allocation.objects.create(course=a.course, name="klasy")
    assert other.pk != a.pk


def test_allocation_name_may_repeat_across_courses():
    a = AllocationFactory(name="Klasy")
    other = Allocation.objects.create(course=CourseFactory(), name="Klasy")
    assert other.pk != a.pk


def test_deleting_allocation_nulls_the_fk_and_keeps_memberships():
    a = AllocationFactory()
    group = GroupFactory(course=a.course, allocation=a)
    GroupMembershipFactory(group=group)
    a.delete()
    group.refresh_from_db()
    assert group.allocation_id is None
    assert Group.objects.filter(pk=group.pk).exists()
    assert GroupMembership.objects.filter(group=group).count() == 1


def test_archiving_allocation_leaves_groups_and_memberships_alone():
    a = AllocationFactory()
    group = GroupFactory(course=a.course, allocation=a)
    GroupMembershipFactory(group=group)
    a.archived = True
    a.save(update_fields=["archived"])
    group.refresh_from_db()
    assert group.allocation_id == a.pk
    assert group.archived is False
    assert GroupMembership.objects.filter(group=group).count() == 1
