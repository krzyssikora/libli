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


@pytest.mark.django_db
def test_seed_creates_verified_ca_owner_and_students():
    from allauth.account.models import EmailAddress
    from django.contrib.auth import get_user_model

    from courses.models import Course

    call_command("seed_demo_course")
    User = get_user_model()

    teacher = User.objects.get(username="demo_teacher")
    assert teacher.is_staff is True
    assert teacher.theme == "light"
    assert teacher.language == "en"
    assert EmailAddress.objects.filter(
        user=teacher, verified=True, primary=True
    ).exists()

    course = Course.objects.get(slug="demo-course")
    assert course.owner_id == teacher.id  # builder access = can_manage_course(owner)

    for name in ("demo_student", "demo_s1", "demo_s2", "demo_s3"):
        u = User.objects.get(username=name)
        assert EmailAddress.objects.filter(user=u, verified=True).exists()


@pytest.mark.django_db
def test_seed_has_diverse_leaf_elements():
    from courses.models import CalloutElement
    from courses.models import SpoilerElement
    from courses.models import TableElement

    call_command("seed_demo_course")
    assert CalloutElement.objects.count() == 1
    assert SpoilerElement.objects.count() == 1
    assert TableElement.objects.count() == 1

    call_command("seed_demo_course")  # idempotent: still one of each
    assert CalloutElement.objects.count() == 1
    assert SpoilerElement.objects.count() == 1
    assert TableElement.objects.count() == 1


@pytest.mark.django_db
def test_seeded_ca_can_open_builder(client):
    # The whole PoC rests on the seeded CA being able to open the demo-course
    # builder. Pin it here (200, not 302/403) so a missing owner relationship
    # fails fast in CI instead of only as a capture selector timeout.
    from django.contrib.auth import get_user_model

    call_command("seed_demo_course")
    teacher = get_user_model().objects.get(username="demo_teacher")
    client.force_login(teacher)
    resp = client.get("/manage/courses/demo-course/build/")
    assert resp.status_code == 200
