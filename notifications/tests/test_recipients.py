import pytest

from notifications.recipients import review_recipients
from notifications.recipients import teachers_for
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _grouped_student(course, teachers, *, archived=False):
    student = UserFactory()
    group = GroupFactory(course=course, archived=archived)
    for t in teachers:
        group.teachers.add(t)
    GroupMembershipFactory(group=group, student=student)
    return student, group


def test_teachers_for_single_group():
    course = CourseFactory()
    t1 = UserFactory()
    student, _ = _grouped_student(course, [t1])
    assert teachers_for(student, course) == [t1]


def test_teachers_for_unions_multiple_groups_and_dedupes():
    course = CourseFactory()
    t1, t2, shared = UserFactory(), UserFactory(), UserFactory()
    student = UserFactory()
    g1 = GroupFactory(course=course)
    g1.teachers.add(t1, shared)
    GroupMembershipFactory(group=g1, student=student)
    g2 = GroupFactory(course=course)
    g2.teachers.add(t2, shared)
    GroupMembershipFactory(group=g2, student=student)
    result = set(teachers_for(student, course))
    assert result == {t1, t2, shared}
    assert len(teachers_for(student, course)) == 3  # shared not duplicated


def test_teachers_for_excludes_archived_group():
    course = CourseFactory()
    t1 = UserFactory()
    student, _ = _grouped_student(course, [t1], archived=True)
    assert teachers_for(student, course) == []


def test_teachers_for_empty_when_group_has_no_teachers():
    course = CourseFactory()
    student, _ = _grouped_student(course, [])
    assert teachers_for(student, course) == []


def test_review_recipients_uses_teachers_when_present():
    course = CourseFactory()
    t1 = UserFactory()
    student, _ = _grouped_student(course, [t1])
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    assert review_recipients(sub) == [t1]


def test_review_recipients_falls_back_to_owner_when_no_teachers():
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    student, _ = _grouped_student(course, [])  # teacher-less group → empty set
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    assert review_recipients(sub) == [owner]


def test_review_recipients_empty_when_no_teachers_and_no_owner():
    course = CourseFactory(owner=None)
    student = UserFactory()  # no group at all
    sub = QuizSubmissionFactory(student=student, unit=make_quiz_unit(course=course))
    assert review_recipients(sub) == []
