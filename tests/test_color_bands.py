import pytest

from tests.factories import CourseFactory


@pytest.mark.django_db
def test_new_course_color_bands_defaults_to_empty_list():
    course = CourseFactory()
    course.refresh_from_db()
    assert course.color_bands == []
