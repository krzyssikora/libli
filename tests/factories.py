import factory
from django.contrib.auth.models import Group as AuthGroup

from accounts.models import User
from courses.models import Attempt  # noqa: F401
from courses.models import ChoiceQuestionElement  # noqa: F401
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragBlank  # noqa: F401
from courses.models import DragFillBlankQuestionElement  # noqa: F401
from courses.models import DragToImageQuestionElement  # noqa: F401
from courses.models import DragZone  # noqa: F401
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement  # noqa: F401
from courses.models import MatchPair  # noqa: F401
from courses.models import MatchPairQuestionElement  # noqa: F401
from courses.models import MediaAsset
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement  # noqa: F401
from courses.models import ShortTextQuestionElement
from courses.models import Subject
from courses.models import TextElement
from courses.models import UnitProgress
from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.models import Collection
from grouping.models import Group
from grouping.models import GroupMembership
from institution.roles import PLATFORM_ADMIN
from institution.roles import seed_roles
from notes.models import Note

# NOTE: ChoiceQuestionElement, FillBlankQuestionElement, ShortNumericQuestionElement,
# and Attempt are imported above so tests can do:
#   from tests.factories import ChoiceQuestionElement
# factories.py is the tests' single import surface; the noqa: F401 suppresses the
# "imported but unused" warning for names that are re-exported but not used locally.
# Grouping factories (CohortFactory, CohortMembershipFactory, GroupFactory,
# GroupMembershipFactory, CollectionFactory) are defined below and also re-exported
# from this module.

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

    title_en = factory.Sequence(lambda n: f"Subject {n}")
    slug = factory.Sequence(lambda n: f"subject-{n}")


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    title = factory.Sequence(lambda n: f"Course {n}")
    slug = factory.Sequence(lambda n: f"course-{n}")
    language = "en"

    @factory.post_generation
    def subjects(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.subjects.add(*extracted)


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


class MediaAssetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MediaAsset

    course = factory.SubFactory(CourseFactory)
    kind = "image"
    file = factory.Sequence(lambda n: f"courses/media/test-{n}.png")
    original_filename = factory.Sequence(lambda n: f"test-{n}.png")


def add_element(unit, obj):
    """Attach a saved concrete element `obj` to `unit` via a new Element join-row."""
    return Element.objects.create(unit=unit, content_object=obj)


def make_login(client, username):
    """Create a user with a verified email, log the test client in, return the user.

    Uses make_verified_user so allauth's AccountMiddleware (mandatory email
    verification) does not intercept the session and redirect to verify-email.
    """
    user = make_verified_user(
        username=username, email=f"{username}@test.example.com", password=TEST_PASSWORD
    )
    client.force_login(user)
    return user


def make_pa(client, username="pa"):
    """Log in a user who is a Platform Admin (group holds courses.* perms).

    Views load request.user fresh from the session, so they always see the group.
    For the returned in-memory object, drop any cached perm sets so a direct
    `user.has_perm(...)` in a test reflects the just-added group."""
    seed_roles()
    user = make_login(client, username)
    user.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    for attr in ("_perm_cache", "_user_perm_cache", "_group_perm_cache"):
        user.__dict__.pop(attr, None)
    return user


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


def make_quiz_unit(course=None, **kw):
    """A quiz unit ContentNode (kind=unit, unit_type=quiz)."""
    kw.setdefault("kind", "unit")
    kw.setdefault("unit_type", "quiz")
    if course is not None:
        kw["course"] = course
    return ContentNodeFactory(**kw)


class QuizSubmissionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QuizSubmission

    student = factory.SubFactory(UserFactory)
    # LazyFunction (not SubFactory) so the unit is a real quiz unit with a
    # slug-bearing course — standard for all quiz tests.
    unit = factory.LazyFunction(make_quiz_unit)


class QuestionResponseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = QuestionResponse

    submission = factory.SubFactory(QuizSubmissionFactory)
    # An Element join-row pointing at a freshly created short-text question.
    element = factory.LazyAttribute(
        lambda o: Element.objects.create(
            unit=o.submission.unit,
            content_object=ShortTextQuestionElement.objects.create(
                stem="q", accepted="a"
            ),
        )
    )


class AttemptFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attempt

    response = factory.SubFactory(QuestionResponseFactory)
    n = factory.Sequence(lambda n: n + 1)
    answer = factory.LazyFunction(lambda: ["a"])
    fraction = None
    correct = None


class DragFillBlankQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragFillBlankQuestionElement

    stem = "￿0￿"
    distractors = ""


class DragBlankFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragBlank

    question = factory.SubFactory(DragFillBlankQuestionElementFactory)
    correct_token = factory.Sequence(lambda n: f"tok{n}")


class MatchPairQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MatchPairQuestionElement

    distractors = ""


class MatchPairFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MatchPair

    question = factory.SubFactory(MatchPairQuestionElementFactory)
    left = factory.Sequence(lambda n: f"L{n}")
    right = factory.Sequence(lambda n: f"R{n}")


class DragToImageQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragToImageQuestionElement

    media = factory.SubFactory(MediaAssetFactory)
    alt = "Diagram"
    distractors = ""


class DragZoneFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DragZone

    question = factory.SubFactory(DragToImageQuestionElementFactory)
    correct_label = factory.Sequence(lambda n: f"label{n}")
    x = 0.1
    y = 0.1
    w = 0.2
    h = 0.2


class ExtendedResponseQuestionElementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ExtendedResponseQuestionElement

    stem = "Discuss the causes."
    required_keywords = "alpha"
    forbidden_keywords = ""


class CohortFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cohort

    name = factory.Sequence(lambda n: f"Cohort {n}")


class CohortMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CohortMembership

    user = factory.SubFactory(UserFactory)
    cohort = factory.SubFactory(CohortFactory)

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """Use update_or_create so that when a post_save signal has already placed
        the user in Default, calling CohortMembershipFactory(user=u, cohort=c)
        reassigns the membership rather than colliding on the OneToOne constraint."""
        user = kwargs.pop("user")
        obj, _ = model_class.objects.update_or_create(user=user, defaults=kwargs)
        return obj


class GroupFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Group

    name = factory.Sequence(lambda n: f"Group {n}")
    course = factory.SubFactory(CourseFactory)


class GroupMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = GroupMembership

    group = factory.SubFactory(GroupFactory)
    student = factory.SubFactory(UserFactory)


class ElementFactory(factory.django.DjangoModelFactory):
    """An Element join-row in a (lesson) unit, backed by a fresh TextElement.
    Mirrors the proven QuestionResponseFactory pattern of creating the concrete
    content object then attaching it via the GFK."""

    class Meta:
        model = Element

    unit = factory.SubFactory(ContentNodeFactory)  # lesson unit by default
    content_object = factory.LazyFunction(
        lambda: TextElement.objects.create(body="<p>block</p>")
    )


class NoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Note

    author = factory.SubFactory(UserFactory)
    unit = factory.SubFactory(ContentNodeFactory)  # lesson unit by default
    body = factory.Sequence(lambda n: f"note body {n}")

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Spec §4: the factory must not be a backdoor past the 5000-char cap.
        from notes.models import NOTE_MAX_LEN

        body = kwargs.get("body", "")
        if len(body) > NOTE_MAX_LEN:
            raise ValueError("NoteFactory body exceeds NOTE_MAX_LEN")
        return super()._create(model_class, *args, **kwargs)


class CollectionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Collection

    name = factory.Sequence(lambda n: f"Collection {n}")
    course = factory.SubFactory(CourseFactory)
    owner = factory.SubFactory(UserFactory)
