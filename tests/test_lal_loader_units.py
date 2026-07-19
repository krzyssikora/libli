import pytest

from courses.models import MediaAsset
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def test_mediaasset_has_content_hash_field():
    course = CourseFactory()
    a = MediaAsset.objects.create(
        course=course,
        kind="image",
        original_filename="x.png",
        content_hash="a" * 64,
    )
    a.refresh_from_db()
    assert a.content_hash == "a" * 64


def test_content_hash_is_indexed():
    field = MediaAsset._meta.get_field("content_hash")
    assert field.db_index is True
