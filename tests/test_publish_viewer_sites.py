import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from courses.models import UnitProgress
from notes.models import Note
from tags.models import UnitTag
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import TagFactory
from tests.factories import UnitTagFactory
from tests.factories import add_element
from tests.factories import make_login

# (url name, payload, model the endpoint writes, lookup for that model)
# The model differs per endpoint, and that matters: a UnitProgress count is
# VACUOUSLY unchanged for note_add, tag_add, tag_remove and quiz_finish, which
# write Note / UnitTag / QuizSubmission. Those four are exactly the rows a
# courses/-scoped implementation misses, so a shared UnitProgress assertion
# would be green on every mutant for the endpoints the test exists to cover.
POST_ENDPOINTS = [
    ("courses:seen", {}, UnitProgress, lambda s, u: {"student": s, "unit": u}),
    ("courses:complete", {}, UnitProgress, lambda s, u: {"student": s, "unit": u}),
    (
        "courses:element_state_save",
        {"element": 0, "state": "{}"},
        UnitProgress,
        lambda s, u: {"student": s, "unit": u},
    ),
    ("notes:note_add", {"body": "x"}, Note, lambda s, u: {"author": s, "unit": u}),
    # tag_add reads request.POST.getlist("tag_pk") and .get("name") -- there is
    # NO "tag" parameter. Posting {"tag": "x"} falls through both branches and
    # writes nothing, so before == after == 0 and the write assertion is
    # vacuous on the mutant. Use "name".
    ("tags:tag_add", {"name": "x"}, UnitTag, lambda s, u: {"unit": u}),
]


@pytest.mark.django_db
@pytest.mark.parametrize("name,payload,model,lookup", POST_ENDPOINTS)
def test_draft_unit_rejects_every_student_post(client, name, payload, model, lookup):
    """ACC3. The three cross-app endpoints (notes, tags) are the ones a
    courses/-scoped implementation misses.

    Mutant: gate only the GET views -> the POSTs still write.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)

    url = reverse(name, kwargs={"slug": course.slug, "node_pk": unit.pk})
    before = model.objects.filter(**lookup(student, unit)).count()

    assert client.post(url, payload).status_code == 404
    # 404 alone is not enough: assert the write did not land either.
    assert model.objects.filter(**lookup(student, unit)).count() == before


@pytest.mark.django_db
def test_draft_unit_rejects_tag_remove_and_leaves_the_row(client):
    """tag_remove calls untag_unit(user, unit, tag_pk). With no pre-existing
    UnitTag, before == after == 0 regardless of the gate -- so this fixture
    seeds a real UnitTag on the draft unit and posts its tag's real pk.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)
    tag = TagFactory(author=student)
    UnitTagFactory(tag=tag, unit=unit)

    url = reverse("tags:tag_remove", kwargs={"slug": course.slug, "node_pk": unit.pk})
    before = UnitTag.objects.filter(unit=unit).count()

    resp = client.post(url, {"tag_pk": tag.pk})
    assert resp.status_code == 404
    assert UnitTag.objects.filter(unit=unit).count() == before


@pytest.mark.django_db
def test_draft_lesson_rejects_check_answer_and_writes_nothing(client):
    """check_answer takes an extra element_pk kwarg the shared parametrize
    list does not cover."""
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )
    question = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    )
    element = add_element(unit, question)

    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": element.pk},
    )
    before = UnitProgress.objects.filter(student=student, unit=unit).count()

    resp = client.post(url, {"answer": "Paris"})
    assert resp.status_code == 404
    assert UnitProgress.objects.filter(student=student, unit=unit).count() == before


@pytest.mark.django_db
def test_draft_quiz_rejects_quiz_answer_and_writes_nothing(client):
    """quiz_answer needs a quiz unit, not a lesson, and writes QuizSubmission."""
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", published=False
    )
    question = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    )
    element = add_element(unit, question)

    url = reverse(
        "courses:quiz_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": element.pk},
    )
    before = QuizSubmission.objects.filter(student=student, unit=unit).count()

    resp = client.post(url, {"answer": "Paris"})
    assert resp.status_code == 404
    assert QuizSubmission.objects.filter(student=student, unit=unit).count() == before


@pytest.mark.django_db
def test_draft_quiz_rejects_quiz_finish_and_writes_nothing(client):
    """quiz_finish needs a quiz unit and writes QuizSubmission."""
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", published=False
    )

    url = reverse(
        "courses:quiz_finish", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    before = QuizSubmission.objects.filter(student=student, unit=unit).count()

    resp = client.post(url, {})
    assert resp.status_code == 404
    assert QuizSubmission.objects.filter(student=student, unit=unit).count() == before
