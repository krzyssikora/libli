import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from grouping import services
from tests.factories import CollectionFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory

pytestmark = pytest.mark.django_db


def test_adding_same_course_group_is_allowed():
    course = CourseFactory()
    coll = CollectionFactory(course=course)
    g = GroupFactory(course=course)
    services.set_collection_groups(coll, [g.pk])
    assert list(coll.groups.values_list("pk", flat=True)) == [g.pk]


def test_adding_mismatched_course_group_is_rejected():
    coll = CollectionFactory(course=CourseFactory())
    foreign = GroupFactory(course=CourseFactory())
    with pytest.raises(ValidationError):
        with transaction.atomic():
            services.set_collection_groups(coll, [foreign.pk])
    coll.refresh_from_db()
    assert coll.groups.count() == 0


def test_empty_collection_is_allowed():
    coll = CollectionFactory()
    services.set_collection_groups(coll, [])
    assert coll.groups.count() == 0
