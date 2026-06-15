import pytest

from tests.factories import CourseFactory


@pytest.mark.django_db
def test_course_str_and_defaults():
    course = CourseFactory(title="Algebra", language="pl")
    assert str(course) == "Algebra"
    assert course.visibility == "assigned"  # reserved hook, default
    assert course.language == "pl"
