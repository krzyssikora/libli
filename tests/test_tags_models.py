import pytest
from django.db import IntegrityError

from tags.models import TAG_PALETTE
from tags.models import Tag
from tags.models import UnitTag
from tags.models import default_color_for
from tests.factories import ContentNodeFactory
from tests.factories import TagFactory
from tests.factories import UnitTagFactory
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_default_color_is_stable_and_in_palette():
    c1 = default_color_for("exam")
    c2 = default_color_for("exam")
    assert c1 == c2
    assert c1 in TAG_PALETTE


def test_case_insensitive_unique_per_author():
    user = UserFactory()
    TagFactory(author=user, name="Exam")
    with pytest.raises(IntegrityError):
        Tag.objects.create(author=user, name="exam", color="teal")


def test_same_name_different_authors_ok():
    TagFactory(author=UserFactory(), name="Exam")
    TagFactory(author=UserFactory(), name="Exam")  # no error


def test_unittag_unique_per_tag_unit():
    tag = TagFactory()
    unit = ContentNodeFactory()
    UnitTagFactory(tag=tag, unit=unit)
    with pytest.raises(IntegrityError):
        UnitTag.objects.create(tag=tag, unit=unit)


def test_tag_ordering_is_case_insensitive():
    user = UserFactory()
    TagFactory(author=user, name="Zebra")
    TagFactory(author=user, name="apple")
    names = list(Tag.objects.filter(author=user).values_list("name", flat=True))
    assert names == ["apple", "Zebra"]
