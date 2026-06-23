import pytest

from tests.factories import CohortFactory
from tests.factories import CourseFactory

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
