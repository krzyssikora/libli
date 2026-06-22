import pytest

from courses.models import Enrollment
from courses.models import UnitProgress
from grouping import services
from grouping.models import GroupMembership
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def _enrollment(student, course):
    return Enrollment.objects.filter(student=student, course=course).first()


def test_add_creates_group_enrollment():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    e = _enrollment(student, course)
    assert e is not None and e.source == "group"


def test_remove_last_drops_enrollment():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    services.remove_students_from_group(group, [student])
    assert _enrollment(student, course) is None


def test_remove_with_second_group_keeps_enrollment():
    course = CourseFactory()
    g1 = GroupFactory(course=course)
    g2 = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(g1, [student])
    services.add_students_to_group(g2, [student])
    services.remove_students_from_group(g1, [student])
    assert _enrollment(student, course) is not None


def test_archive_drops_unarchive_restores():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    services.set_group_archived(group, True)
    assert _enrollment(student, course) is None
    services.set_group_archived(group, False)
    assert _enrollment(student, course) is not None


def test_archive_with_second_active_group_keeps_enrollment():
    # Student in group A (archived) and group B (active) of the SAME course
    # keeps the group-sourced enrollment after A is archived (parity with the
    # remove-with-second-group case).
    course = CourseFactory()
    g_a = GroupFactory(course=course)
    g_b = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(g_a, [student])
    services.add_students_to_group(g_b, [student])
    services.set_group_archived(g_a, True)
    assert _enrollment(student, course) is not None


def test_self_and_manual_enrollment_immune_to_group_changes():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    Enrollment.objects.create(student=student, course=course, source="manual")
    services.add_students_to_group(group, [student])
    # source not downgraded/overwritten
    assert _enrollment(student, course).source == "manual"
    services.remove_students_from_group(group, [student])
    # manual enrollment survives losing group membership
    assert _enrollment(student, course) is not None


def test_progress_preserved_across_drop_and_readd():
    course = CourseFactory()
    group = GroupFactory(course=course)
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    student = UserFactory()
    services.add_students_to_group(group, [student])
    UnitProgress.objects.create(student=student, unit=unit, completed=True)
    services.remove_students_from_group(group, [student])
    services.add_students_to_group(group, [student])
    assert UnitProgress.objects.get(student=student, unit=unit).completed is True


def test_delete_group_drops_enrollment_and_recomputes():
    course = CourseFactory()
    group = GroupFactory(course=course)
    student = UserFactory()
    services.add_students_to_group(group, [student])
    services.delete_group(group)
    assert _enrollment(student, course) is None
    assert not GroupMembership.objects.filter(student=student).exists()
