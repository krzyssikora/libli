"""The per-question drill-down page (spec §3, §5; T30, T31, T31b, T33, T35-T39, T41).

Every PA/owner-viewed pupil gets an Enrollment row: reviewable_students serves
PA and owner from Enrollment alone, and GroupMembershipFactory creates none."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.urls import reverse

from courses.models import Element
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _url(course, student_pk, node_pk, qs=""):
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student_pk, "node_pk": node_pk},
    )
    return f"{path}{qs}"


def _quiz_with_question(course, *, published=True, title="Quiz"):
    quiz = ContentNodeFactory(
        course=course,
        parent=None,
        kind="unit",
        unit_type="quiz",
        published=published,
        title=title,
    )
    q = ShortTextQuestionElement.objects.create(
        stem="<p>Capital?</p>", accepted="Warsaw", max_marks=Decimal("1")
    )
    Element.objects.create(unit=quiz, content_object=q)
    return quiz


def _submitted(student, quiz, **kw):
    kw.setdefault("status", QuizSubmission.Status.SUBMITTED)
    return QuizSubmission.objects.create(student=student, unit=quiz, **kw)


def _soup(response):
    return BeautifulSoup(response.content.decode(), "html.parser")


# --- T30 access --------------------------------------------------------------
def test_t30_access_matrix(client):
    pa = make_pa(client, "pa")
    owner = make_verified_user(username="owner", email="owner@test.example.com")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    pupil_a = make_verified_user(username="pupila", email="pupila@test.example.com")
    pupil_b = UserFactory()
    for pupil in (pupil_a, pupil_b):
        EnrollmentFactory(student=pupil, course=course)
        _submitted(pupil, quiz)
    group_a = GroupFactory(course=course)
    group_b = GroupFactory(course=course)
    GroupMembershipFactory(group=group_a, student=pupil_a)
    GroupMembershipFactory(group=group_b, student=pupil_b)
    teacher_a = make_teacher(client, "teachera")
    group_a.teachers.add(teacher_a)
    teacher_b = make_teacher(client, "teacherb")
    group_b.teachers.add(teacher_b)
    archived_teacher = make_teacher(client, "archivedteacher")
    group_b.teachers.add(archived_teacher)  # active group, so step 2 passes
    old_group = GroupFactory(course=course, archived=True)
    old_group.teachers.add(archived_teacher)
    GroupMembershipFactory(group=old_group, student=pupil_a)
    staff = make_teacher(client, "staffnogroup")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    # Pinned up front so every mutant's flip is real (spec T30).
    assert not pa.is_staff and not owner.is_staff and not teacher_a.is_staff
    assert staff.is_staff

    url = _url(course, pupil_a.pk, quiz.pk)
    expected = [
        (pa, 200),
        (owner, 200),
        (teacher_a, 200),
        (teacher_b, 404),
        (archived_teacher, 404),
        (staff, 404),
        (pupil_a, 404),
    ]
    actual = {}
    for viewer, _status in expected:
        client.force_login(viewer)
        actual[viewer.username] = client.get(url).status_code
    # ONE dict comparison, so a failure lists EVERY flipped row (spec T30).
    assert actual == {viewer.username: status for viewer, status in expected}
    client.logout()
    anonymous = client.get(url)
    assert anonymous.status_code == 302
    assert "/accounts/login/" in anonymous.url


# --- T31 resolution ----------------------------------------------------------
def test_t31_each_path_segment_404s_on_its_own(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    _submitted(pupil, quiz)
    assert client.get(_url(course, pupil.pk, quiz.pk)).status_code == 200

    # Submissions exist on these nodes, so step 5 cannot be what 404s them.
    other = CourseFactory(owner=owner)
    other_quiz = _quiz_with_question(other)
    _submitted(pupil, other_quiz)
    assert client.get(_url(course, pupil.pk, other_quiz.pk)).status_code == 404
    lesson = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _submitted(pupil, lesson)
    assert client.get(_url(course, pupil.pk, lesson.pk)).status_code == 404

    missing = get_user_model().objects.order_by("-pk").first().pk + 1000
    assert client.get(_url(course, missing, quiz.pk)).status_code == 404

    no_submission = UserFactory()
    EnrollmentFactory(student=no_submission, course=course)
    assert client.get(_url(course, no_submission.pk, quiz.pk)).status_code == 404


def test_t31b_group_teacher_opens_a_draft_quiz_the_pupil_has_data_on(client):
    teacher = make_teacher(client, "draftteacher")
    course = CourseFactory(owner=UserFactory())
    quiz = _quiz_with_question(course, published=False)
    pupil = UserFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    GroupMembershipFactory(group=group, student=pupil)
    _submitted(pupil, quiz)
    client.force_login(teacher)
    assert client.get(_url(course, pupil.pk, quiz.pk)).status_code == 200


# --- header pill + Review link (full parity is T36, Task 7) -------------------
def test_awaiting_header_has_one_review_link(client):
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement

    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("1"),
    )
    Element.objects.create(unit=quiz, content_object=q)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    status = soup.select_one(".answers__status")
    assert status.select_one(".pill--awaiting") is not None
    links = status.select("a.answers__review")
    assert [a["href"] for a in links] == [
        reverse(
            "courses:manage_review_submission",
            kwargs={"slug": course.slug, "submission_pk": sub.pk},
        )
    ]
