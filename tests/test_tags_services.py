import pytest
from django.core.exceptions import ValidationError
from django.http import Http404

from courses.models import Enrollment
from tags import services
from tags.models import TAG_NAME_MAX_LEN
from tags.models import Tag
from tags.models import UnitTag
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import TagFactory
from tests.factories import UnitTagFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_normalize_name_collapses_whitespace():
    assert services.normalize_name("  to   do \n") == "to do"


def test_clean_name_rejects_empty():
    with pytest.raises(ValidationError):
        services._clean_name("   ")


def test_clean_name_rejects_over_length():
    with pytest.raises(ValidationError):
        services._clean_name("x" * (TAG_NAME_MAX_LEN + 1))


def test_reuse_or_create_is_case_insensitive():
    user = UserFactory()
    a = services._reuse_or_create_tag(user, "Exam")
    b = services._reuse_or_create_tag(user, "  exam ")
    assert a.pk == b.pk
    assert Tag.objects.filter(author=user).count() == 1


def test_rename_allows_recasing_own_name():
    tag = TagFactory(name="exam")
    services.rename_tag(tag.author, tag.pk, "Exam")
    tag.refresh_from_db()
    assert tag.name == "Exam"


def test_rename_rejects_collision_with_other_tag():
    user = UserFactory()
    TagFactory(author=user, name="exam")
    other = TagFactory(author=user, name="hard")
    with pytest.raises(ValidationError):
        services.rename_tag(user, other.pk, "EXAM")


def test_rename_preserves_colour():
    tag = TagFactory(name="exam", color="rose")
    services.rename_tag(tag.author, tag.pk, "exams")
    tag.refresh_from_db()
    assert tag.color == "rose"


def test_rename_foreign_tag_404():
    tag = TagFactory()
    with pytest.raises(Http404):
        services.rename_tag(UserFactory(), tag.pk, "x")


def test_recolor_rejects_invalid_key():
    tag = TagFactory()
    with pytest.raises(ValidationError):
        services.recolor_tag(tag.author, tag.pk, "not-a-colour")


def test_delete_tag_returns_accessible_count_then_cascades():
    user = UserFactory()
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course)
    tag = TagFactory(author=user)
    UnitTagFactory(tag=tag, unit=unit)
    n = services.delete_tag(user, tag.pk)
    assert n == 1
    assert not Tag.objects.filter(pk=tag.pk).exists()
    assert not UnitTag.objects.filter(tag_id=tag.pk).exists()


def test_list_tags_unit_count_excludes_inaccessible():
    user = UserFactory()
    reachable = CourseFactory()
    Enrollment.objects.create(student=user, course=reachable)
    unreachable = CourseFactory()
    tag = TagFactory(author=user, name="exam")
    UnitTagFactory(tag=tag, unit=ContentNodeFactory(course=reachable))
    UnitTagFactory(tag=tag, unit=ContentNodeFactory(course=unreachable))
    [t] = services.list_tags(user)
    assert t.unit_count == 1  # the inaccessible one is not counted
