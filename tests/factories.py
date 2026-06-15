import factory

from accounts.models import User
from courses.models import ContentNode
from courses.models import Course
from courses.models import Enrollment
from courses.models import Subject
from courses.models import UnitProgress

# Shared fixture password for auth tests. Defined once so the literal lives in a
# single place (not a real credential — chosen to satisfy AUTH_PASSWORD_VALIDATORS).
TEST_PASSWORD = "Sup3r!pass9"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n}")
    display_name = factory.Faker("name")
    password = factory.PostGenerationMethodCall("set_password", "password123")


class SubjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subject

    title = factory.Sequence(lambda n: f"Subject {n}")
    slug = factory.Sequence(lambda n: f"subject-{n}")


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    title = factory.Sequence(lambda n: f"Course {n}")
    slug = factory.Sequence(lambda n: f"course-{n}")
    language = "en"


class ContentNodeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ContentNode

    course = factory.SubFactory(CourseFactory)
    parent = None
    kind = "unit"
    title = factory.Sequence(lambda n: f"Node {n}")
    unit_type = "lesson"


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    student = factory.SubFactory(UserFactory)
    course = factory.SubFactory(CourseFactory)


class UnitProgressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UnitProgress

    student = factory.SubFactory(UserFactory)
    unit = factory.SubFactory(ContentNodeFactory)


def make_verified_user(
    username="member", email="member@school.edu", password=TEST_PASSWORD
):
    """Create a user with a *verified, primary* allauth EmailAddress so that, under
    mandatory email verification, they can log in via username OR email. Delegates the
    EmailAddress reconciliation to the shared production helper."""
    from accounts.emails import ensure_verified_primary_email

    user = User.objects.create_user(username=username, email=email, password=password)
    ensure_verified_primary_email(user, email)
    return user
