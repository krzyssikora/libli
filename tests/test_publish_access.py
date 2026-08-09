import pytest
from django.contrib.auth.models import Permission
from django.http import Http404
from django.urls import reverse

from courses.access import can_see_drafts
from courses.access import get_node_or_404
from courses.access import manageable_courses
from courses.models import ContentNode
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory
from tests.factories import make_login


@pytest.mark.django_db
def test_draft_unit_404s_for_student_and_resolves_for_owner():
    """ACC1."""
    owner = UserFactory()
    student = UserFactory()
    course = CourseFactory(owner=owner)
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)

    with pytest.raises(Http404):
        get_node_or_404(unit.pk, course.slug, viewer=student, require_unit=True)
    assert (
        get_node_or_404(unit.pk, course.slug, viewer=owner, require_unit=True) == unit
    )


@pytest.mark.django_db
def test_is_staff_and_group_teacher_cannot_see_drafts():
    """ACC2. The gate is can_manage_course, NOT can_access_course.

    Mutant: implement can_see_drafts as can_access_course -> both resolve.
    """
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", published=False)
    staff = UserFactory(is_staff=True)
    teacher = UserFactory()
    GroupFactory(course=course).teachers.add(teacher)

    assert can_see_drafts(staff, course) is False
    assert can_see_drafts(teacher, course) is False
    for user in (staff, teacher):
        with pytest.raises(Http404):
            get_node_or_404(unit.pk, course.slug, viewer=user, require_unit=True)


@pytest.mark.django_db
def test_container_created_after_migration_stays_reachable():
    """ACC5 half A. A container carries published=False from the model
    default, and its own flag must NEVER decide visibility.

    Mutant: drop the `kind == UNIT` conjunct from the chokepoint -> a
    student 404s on every chapter created after the migration.

    Note this uses ContentNode.objects.create, NOT the factory: the factory
    sets published=True (Task 1 Step 9), which would mask the very default
    this test is about.
    """
    course = CourseFactory()
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", title="Ch", parent=None
    )
    assert chapter.published is False  # the model default, as designed

    resolved = get_node_or_404(
        chapter.pk, course.slug, viewer=student, require_unit=False
    )
    assert resolved == chapter


@pytest.mark.django_db
def test_manageable_courses_has_two_branches():
    """WR15c. A courses.change_course holder gets EVERY course; an owner
    gets only theirs.

    Mutant: implement as filter(owner=user) alone -> the PA branch is
    missing and a Platform Admin loses drafts everywhere.
    """
    owner = UserFactory()
    mine = CourseFactory(owner=owner)
    theirs = CourseFactory()
    pa = UserFactory()
    pa.user_permissions.add(
        Permission.objects.get(
            codename="change_course", content_type__app_label="courses"
        )
    )
    pa = type(pa).objects.get(pk=pa.pk)  # drop the cached permission set

    assert set(manageable_courses(owner)) == {mine}
    assert set(manageable_courses(pa)) == {mine, theirs}


@pytest.mark.django_db
def test_permalink_to_draft_unit_404s_for_student(client):
    """ACC4. Mutant: omit the inline published check in node_permalink ->
    the student is redirected into a draft unit.

    Uses make_login, NOT UserFactory + client.force_login: a plain
    UserFactory user has no verified email, and allauth's AccountMiddleware
    (mandatory email verification) intercepts the session and redirects to
    login before the view ever runs -- the same pattern every other
    client-driven test of this view (tests/test_node_permalink.py) follows.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    unit = ContentNodeFactory(course=course, kind="unit", published=False)

    url = reverse("courses:node_permalink", kwargs={"node_pk": unit.pk})
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_permalink_to_container_still_redirects(client):
    """ACC5 half B. A SEPARATE guard from the chokepoint's — node_permalink
    never calls get_node_or_404.

    Mutant: drop the kind == UNIT conjunct from the INLINE check -> a
    student 404s on every chapter permalink.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    chapter = ContentNode.objects.create(course=course, kind="chapter", title="Ch")

    url = reverse("courses:node_permalink", kwargs={"node_pk": chapter.pk})
    assert client.get(url).status_code == 302
