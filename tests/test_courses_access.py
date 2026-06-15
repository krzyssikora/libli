import pytest
from django.http import Http404

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UserFactory


@pytest.mark.django_db
def test_can_access_enrolled_staff_owner_and_deny():
    from courses.access import can_access_course

    course = CourseFactory()
    enrolled = UserFactory()
    EnrollmentFactory(student=enrolled, course=course)
    staff = UserFactory(is_staff=True)
    owner = UserFactory()
    course.owner = owner
    course.save()
    stranger = UserFactory()
    assert can_access_course(enrolled, course) is True
    assert can_access_course(staff, course) is True
    assert can_access_course(owner, course) is True
    assert can_access_course(stranger, course) is False


@pytest.mark.django_db
def test_null_owner_never_matches():
    from courses.access import can_access_course

    course = CourseFactory()  # owner is None
    user = UserFactory()  # user.id is set, owner_id is None
    assert can_access_course(user, course) is False


@pytest.mark.django_db
def test_get_node_or_404_slug_mismatch_and_kind():
    from courses.access import get_node_or_404

    course = CourseFactory(slug="real")
    # A second real course owns the "other" slug; the IDOR guard must still 404
    # because `unit` belongs to "real" (not because "other" is a missing course).
    CourseFactory(slug="other")
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    # right slug, right kind -> ok
    assert get_node_or_404(unit.pk, "real", require_unit=True).pk == unit.pk
    # wrong slug -> 404 (IDOR guard)
    with pytest.raises(Http404):
        get_node_or_404(unit.pk, "other", require_unit=True)
    # container under lesson route -> 404
    part = ContentNodeFactory(course=course, kind="part", unit_type=None)
    with pytest.raises(Http404):
        get_node_or_404(part.pk, "real", require_unit=True)
    # quiz unit under a lesson-only endpoint -> 404
    quiz = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    with pytest.raises(Http404):
        get_node_or_404(quiz.pk, "real", require_unit=True, require_lesson=True)
