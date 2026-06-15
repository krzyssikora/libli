import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_seed_is_idempotent_and_builds_demo():
    from courses.models import Course
    from courses.models import Element
    from courses.models import Enrollment

    call_command("seed_demo_course")
    courses_after_first = Course.objects.count()
    elements_after_first = Element.objects.count()
    enrollments_after_first = Enrollment.objects.count()
    assert courses_after_first == 1
    assert elements_after_first >= 5  # all five element types at least once
    # rerun: no duplicates, no IntegrityError
    call_command("seed_demo_course")
    assert Course.objects.count() == courses_after_first
    assert Element.objects.count() == elements_after_first
    assert Enrollment.objects.count() == enrollments_after_first
