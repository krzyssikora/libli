import pytest
from django.urls import reverse

from courses.rendering import unit_edit_context
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_student
from tests.factories import make_teacher


def _lesson_unit(course):
    """A top-level lesson unit. Factored out to keep every call under 88 chars."""
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


@pytest.mark.django_db
def test_owner_without_change_course_perm_gets_the_link(client):
    """Ownership ALONE must grant the link. The actor deliberately holds no
    courses.change_course: built with make_pa this row would pass via the
    permission branch and never exercise `owner_id == user.id`, so deleting the
    ownership check outright would leave it green."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    ctx = unit_edit_context(owner, unit)

    assert ctx["can_edit_unit"] is True
    assert ctx["unit_editor_url"] == reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    # The predicate identity, TESTED rather than merely asserted in a docstring:
    # follow the URL. `can_edit_unit` is only a safe gate while it stays exactly
    # what views_manage.editor enforces; if a future change adds a gate there,
    # this is the row that notices instead of shipping a link that 403s.
    assert client.get(ctx["unit_editor_url"]).status_code == 200


@pytest.mark.django_db
def test_platform_admin_non_owner_gets_the_link(client):
    """A PA holds courses.change_course, so the permission branch grants it on
    every course — including one they do not own."""
    pa = make_pa(client, "pa")
    # is_staff deliberately NOT set here, unlike the CA and teacher rows below.
    # Production PAs are is_staff too, but this row is asserting the
    # courses.change_course branch: setting is_staff would make it indistinguishable
    # under Step 5b's is_staff-broadening mutation, which expects this row GREEN.
    course = CourseFactory()  # owner is None
    unit = _lesson_unit(course)

    ctx = unit_edit_context(pa, unit)

    assert ctx["can_edit_unit"] is True


@pytest.mark.django_db
def test_course_admin_non_owner_does_not_get_the_link(client):
    """THE row this design rests on. The Course Admin role group holds
    grouping.change_group, NOT courses.change_course — so a CA who does not own
    the course gets nothing. Adding courses.change_course to the CA role, or
    broadening the predicate to is_staff, must break here."""
    ca = make_ca(client, "ca")
    # is_staff must be set BY HAND. _make_role is only make_login + groups.add;
    # it never calls accounts.services.set_user_role, which is the sole place
    # is_staff is synced — so make_ca() alone yields is_staff=False while the
    # production Course Admin has role_is_staff(COURSE_ADMIN) is True. Without
    # this line the fixture does not model the actor the docstring claims, and
    # Step 5's is_staff mutation would leave this row GREEN.
    ca.is_staff = True
    ca.save(update_fields=["is_staff"])
    course = CourseFactory()
    unit = _lesson_unit(course)
    # Inert here, and deliberately kept: unit_edit_context is request-free and
    # consults only can_manage_course (owner_id + courses.change_course), so no
    # enrollment can change this row's outcome. It mirrors the spec's matrix row,
    # where enrollment IS load-bearing (it keeps the page-level actor off a 403).
    EnrollmentFactory(student=ca, course=course)

    ctx = unit_edit_context(ca, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None
    # The other half of the predicate identity (see the owner row): the URL this
    # actor is NOT given must genuinely refuse them.
    editor_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    assert client.get(editor_url).status_code == 403


@pytest.mark.django_db
def test_course_admin_who_owns_the_course_gets_the_link(client):
    """The other half of the pair: a CA reaches this link through OWNERSHIP
    alone, which is also how they come to see the course under Groups at all."""
    ca = make_ca(client, "ca2")
    course = CourseFactory(owner=ca)
    unit = _lesson_unit(course)

    ctx = unit_edit_context(ca, unit)

    assert ctx["can_edit_unit"] is True


@pytest.mark.django_db
def test_group_teacher_with_read_access_does_not_get_the_link(client):
    """A read-access actor who must NOT get the link.

    Two things make this row work, and neither is the one you would guess:

    - `is_staff = True` is LOAD-BEARING, for Step 5b's mutation. It also means the
      actor passes can_access_course on the STAFF branch: accessible_courses
      short-circuits with `if user.is_staff: return Course.objects.all()` before
      the groups__teachers clause is ever evaluated.
    - Because of that short-circuit the group scaffolding below does NOT drive the
      outcome. It is kept to mirror the spec's matrix row (a real group teacher on
      a non-archived group of THIS course), not to grant access.

    Do not "simplify" by deleting `is_staff = True` to restore the group as the
    access route — that is precisely what Step 5b's mutation depends on.
    """
    teacher = make_teacher(client, "teach")
    teacher.is_staff = True  # load-bearing; see the docstring
    teacher.save(update_fields=["is_staff"])
    course = CourseFactory()
    unit = _lesson_unit(course)
    group = GroupFactory(course=course, archived=False)
    group.teachers.add(teacher)

    ctx = unit_edit_context(teacher, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None


@pytest.mark.django_db
def test_enrolled_student_does_not_get_the_link(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    unit = _lesson_unit(course)
    EnrollmentFactory(student=student, course=course)

    ctx = unit_edit_context(student, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None
