import pytest

from grouping.models import CohortMembership
from grouping.services import catalog_courses_for
from grouping.services import get_default_cohort
from tests.factories import CohortFactory
from tests.factories import CohortMembershipFactory
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def test_course_has_self_enroll_cohorts_m2m():
    course = CourseFactory()
    cohort = CohortFactory(name="Year 9")
    course.self_enroll_cohorts.add(cohort)
    assert list(course.self_enroll_cohorts.all()) == [cohort]
    # reverse accessor
    assert list(cohort.self_enroll_courses.all()) == [course]


def test_self_enroll_cohorts_is_optional():
    course = CourseFactory()
    assert course.self_enroll_cohorts.count() == 0


def _open_course_with_unit(**kw):
    course = CourseFactory(visibility="open", **kw)
    ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    return course


def test_open_course_no_cohorts_visible_to_any_student():
    student = make_verified_user(username="s1", email="s1@t.example.com")
    course = _open_course_with_unit()
    assert course in catalog_courses_for(student)


def test_assigned_course_never_in_catalog():
    student = make_verified_user(username="s2", email="s2@t.example.com")
    course = CourseFactory(visibility="assigned")
    ContentNodeFactory(course=course, kind="unit")
    assert course not in catalog_courses_for(student)


def test_open_course_with_no_units_excluded():
    student = make_verified_user(username="s3", email="s3@t.example.com")
    course = CourseFactory(visibility="open")  # no units
    assert course not in catalog_courses_for(student)


def test_cohort_restricted_course_excluded_for_student_not_in_set():
    student = make_verified_user(username="s4", email="s4@t.example.com")  # in Default
    other = CohortFactory(name="Spanish")
    course = _open_course_with_unit()
    course.self_enroll_cohorts.add(other)
    assert course not in catalog_courses_for(student)


def test_cohort_restricted_course_visible_to_member():
    student = make_verified_user(username="s5", email="s5@t.example.com")
    cohort = CohortFactory(name="Year 10")
    CohortMembershipFactory(user=student, cohort=cohort)  # reassigns from Default
    course = _open_course_with_unit()
    course.self_enroll_cohorts.add(cohort)
    assert course in catalog_courses_for(student)


def test_student_with_no_membership_sees_only_empty_set_courses():
    student = make_verified_user(username="s6", email="s6@t.example.com")
    CohortMembership.objects.filter(user=student).delete()  # no cohort at all
    open_all = _open_course_with_unit()
    restricted = _open_course_with_unit()
    restricted.self_enroll_cohorts.add(CohortFactory(name="X"))
    visible = catalog_courses_for(student)
    assert open_all in visible
    assert restricted not in visible


def test_course_appears_exactly_once_despite_many_units_and_cohorts():
    student = make_verified_user(username="s7", email="s7@t.example.com")
    default = get_default_cohort()
    course = _open_course_with_unit()
    ContentNodeFactory(course=course, kind="unit")  # 2nd unit
    ContentNodeFactory(course=course, kind="unit")  # 3rd unit
    course.self_enroll_cohorts.add(default, CohortFactory(name="Y"))
    assert list(catalog_courses_for(student)).count(course) == 1
