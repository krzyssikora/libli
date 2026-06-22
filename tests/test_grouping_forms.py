import pytest

from grouping.forms import CollectionForm
from grouping.forms import GroupForm
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
