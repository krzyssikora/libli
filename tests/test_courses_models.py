import pytest
from django.core.exceptions import ValidationError

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_course_str_and_defaults():
    course = CourseFactory(title="Algebra", language="pl")
    assert str(course) == "Algebra"
    assert course.visibility == "assigned"  # reserved hook, default
    assert course.language == "pl"


@pytest.mark.django_db
def test_kind_depth_invariant_rejects_shallow_child():
    course = CourseFactory()
    section = ContentNodeFactory(
        course=course, kind="section", parent=None, unit_type=None
    )
    bad = ContentNodeFactory.build(
        course=course, kind="part", parent=section, unit_type=None
    )
    with pytest.raises(ValidationError):
        bad.full_clean()


@pytest.mark.django_db
def test_root_level_unit_is_allowed():
    course = CourseFactory()
    unit = ContentNodeFactory.build(
        course=course, kind="unit", parent=None, unit_type="lesson"
    )
    unit.full_clean()  # must not raise


@pytest.mark.django_db
def test_unit_requires_unit_type_and_container_forbids_it():
    course = CourseFactory()
    bad_unit = ContentNodeFactory.build(
        course=course, kind="unit", parent=None, unit_type=None
    )
    with pytest.raises(ValidationError):
        bad_unit.full_clean()
    bad_part = ContentNodeFactory.build(
        course=course, kind="part", parent=None, unit_type="lesson"
    )
    with pytest.raises(ValidationError):
        bad_part.full_clean()


@pytest.mark.django_db
def test_clean_rejects_unit_conversion_when_node_has_children():
    course = CourseFactory()
    section = ContentNodeFactory(
        course=course, kind="section", parent=None, unit_type=None
    )
    ContentNodeFactory(course=course, kind="unit", parent=section, unit_type="lesson")
    section.kind = "unit"
    section.unit_type = "lesson"
    with pytest.raises(ValidationError):
        section.full_clean()


@pytest.mark.django_db
def test_orderfield_scopes_to_parent_including_null():
    course = CourseFactory()
    a = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    b = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    assert [a.order, b.order] == [0, 1]
    parent = ContentNodeFactory(course=course, parent=None, kind="part", unit_type=None)
    child = ContentNodeFactory(
        course=course, parent=parent, kind="unit", unit_type="lesson"
    )
    assert child.order == 0  # new scope restarts ordering


@pytest.mark.django_db
def test_enrollment_unique_per_student_course():
    from django.db import IntegrityError

    from courses.models import Enrollment
    from tests.factories import UserFactory

    course = CourseFactory()
    user = UserFactory()
    Enrollment.objects.create(student=user, course=course)
    with pytest.raises(IntegrityError):
        Enrollment.objects.create(student=user, course=course)


@pytest.mark.django_db
def test_unitprogress_save_stamps_completed_at():
    from courses.models import UnitProgress
    from tests.factories import UserFactory

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    user = UserFactory()
    progress = UnitProgress.objects.create(student=user, unit=unit)
    assert progress.completed_at is None
    progress.completed = True
    progress.save()  # invariant: completed => completed_at set (admin path too)
    assert progress.completed_at is not None
