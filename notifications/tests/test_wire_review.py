from decimal import Decimal

import pytest

from courses import review as review_svc
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from notifications.models import Notification
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _review_q(unit):
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("5"),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _setup(course=None, teachers=()):
    course = course or CourseFactory()
    student = UserFactory()
    group = GroupFactory(course=course)
    for t in teachers:
        group.teachers.add(t)
    GroupMembershipFactory(group=group, student=student)
    sub = QuizSubmissionFactory(
        student=student,
        unit=make_quiz_unit(course=course),
        status=QuizSubmission.Status.IN_PROGRESS,
    )
    _review_q(sub.unit)
    return course, student, sub


def test_force_submit_quiz_emits_needs_review():
    t1 = UserFactory()
    outsider = UserFactory()
    _, student, sub = _setup(teachers=[t1])
    review_svc.force_submit_quiz(sub, by=outsider)
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
        ).count()
        == 1
    )


def test_force_submit_already_submitted_does_not_renotify():
    t1 = UserFactory()
    outsider = UserFactory()
    _, student, sub = _setup(teachers=[t1])
    review_svc.force_submit_quiz(sub, by=outsider)
    review_svc.force_submit_quiz(sub, by=outsider)  # now SUBMITTED → early return
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
        ).count()
        == 1
    )


def test_force_submit_all_covers_each_student(client):
    from django.contrib.auth.models import Group as AuthGroup
    from django.urls import reverse

    from courses.models import Enrollment
    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles
    from tests.factories import make_verified_user

    seed_roles()
    course = CourseFactory()
    t1 = UserFactory()
    _, s1, sub1 = _setup(course=course, teachers=[t1])
    # second student in the same course/group set
    _, s2, sub2 = _setup(course=course, teachers=[t1])
    # force_submit_all filters candidates to reviewable_students, which for a PA
    # is Enrollment.objects.filter(course=...). GroupMembershipFactory creates NO
    # enrollment row, so the students must be enrolled explicitly or the view
    # force-submits nothing.
    Enrollment.objects.create(student=s1, course=course, source="group")
    Enrollment.objects.create(student=s2, course=course, source="group")
    pa = make_verified_user(username="pa_force", email="pa_force@test.example.com")
    pa.groups.add(AuthGroup.objects.get(name=PLATFORM_ADMIN))
    client.force_login(pa)
    # Route name is `manage_review_force_submit_all` (courses/urls.py). Each _setup
    # built its own unit, so force-submit per unit.
    client.post(
        reverse(
            "courses:manage_review_force_submit_all",
            kwargs={"slug": course.slug, "unit_pk": sub1.unit_id},
        )
    )
    client.post(
        reverse(
            "courses:manage_review_force_submit_all",
            kwargs={"slug": course.slug, "unit_pk": sub2.unit_id},
        )
    )
    # kind-filtered, so the `enrolled` rows above don't interfere.
    assert (
        Notification.objects.filter(kind=Notification.Kind.QUIZ_NEEDS_REVIEW).count()
        == 2
    )


def test_quiz_finish_by_student_emits_needs_review(client):
    """The spec's PRIMARY trigger: a student finishing a quiz with an [R] question
    notifies their group teacher(s), through the real quiz_finish view."""
    from django.contrib.auth.models import Group as AuthGroup
    from django.urls import reverse

    from courses.models import Enrollment
    from institution.roles import STUDENT
    from institution.roles import seed_roles
    from tests.factories import make_login

    seed_roles()
    course = CourseFactory()
    t1 = UserFactory()
    unit = make_quiz_unit(course=course)
    _review_q(unit)
    group = GroupFactory(course=course)
    group.teachers.add(t1)
    student = make_login(client, "qf_student")  # verified user + logged in
    student.groups.add(AuthGroup.objects.get(name=STUDENT))
    GroupMembershipFactory(group=group, student=student)
    # quiz_finish guards on is_enrolled(student, course) (courses/views.py:625).
    Enrollment.objects.create(student=student, course=course, source="group")

    url = reverse(
        "courses:quiz_finish", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    # IN_PROGRESS -> SUBMITTED transition (get_or_create makes the submission)
    client.post(url)
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
        ).count()
        == 1
    )
    client.post(url)  # already SUBMITTED -> no re-notify
    assert (
        Notification.objects.filter(
            kind=Notification.Kind.QUIZ_NEEDS_REVIEW, recipient=t1
        ).count()
        == 1
    )
