import pytest
from django.contrib.auth.models import Group as AuthGroup

from grouping.forms import CollectionForm
from grouping.forms import GroupForm
from institution.roles import TEACHER
from institution.roles import seed_roles
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_group_form_course_locked_on_edit():
    g = GroupFactory()
    form = GroupForm(instance=g)
    assert form.fields["course"].disabled is True


def test_group_form_course_editable_on_create():
    form = GroupForm()
    assert form.fields["course"].disabled is False


def test_collection_form_rejects_mismatched_group():
    course = CourseFactory()
    foreign = GroupFactory(course=CourseFactory())
    form = CollectionForm(
        data={"name": "Mix", "course": course.pk, "groups": [foreign.pk]},
        owner=UserFactory(),
    )
    assert not form.is_valid()
    assert "groups" in form.errors


def test_collection_form_accepts_same_course_group():
    course = CourseFactory()
    g = GroupFactory(course=course)
    form = CollectionForm(
        data={"name": "OK", "course": course.pk, "groups": [g.pk]},
        owner=UserFactory(),
    )
    assert form.is_valid(), form.errors


def test_group_form_teachers_queryset_staff_only():
    """GroupForm.fields['teachers'] must include staff/Teacher-role users and
    exclude plain non-staff students (incl. admin-created users with no role)."""
    seed_roles()
    # A teacher: has the Teacher auth group.
    teacher = UserFactory(username="gf_teacher")
    teacher.groups.add(AuthGroup.objects.get(name=TEACHER))

    # A staff user via Django is_staff flag.
    staff = UserFactory(username="gf_staff", is_staff=True)

    # A plain non-staff learner with no role.
    student = UserFactory(username="gf_student")

    form = GroupForm()
    qs = form.fields["teachers"].queryset
    qs_ids = set(qs.values_list("pk", flat=True))

    assert teacher.pk in qs_ids, "Teacher-role user must appear in teachers picker"
    assert staff.pk in qs_ids, "is_staff user must appear in teachers picker"
    assert student.pk not in qs_ids, (
        "Plain non-staff user must NOT appear in teachers picker"
    )
