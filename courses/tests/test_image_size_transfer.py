import pytest

from courses.models import ImageElement
from courses.models import MediaAsset
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import make_course_with_unit

MEDIA_KINDS = {"m1": "image"}


class _Ids:
    """Stand-in for the export id registry: every asset serialises to "m1"."""

    def register(self, *a, **k):
        return "m1"


def _media(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return _media(course)


def _validate(data):
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)


def test_format_version_is_pinned():
    # Renamed from test_format_version_is_bumped: that name claimed ownership
    # of the number this feature bumped, but Task 9 (published on the node
    # payload) has since bumped it again to 10.
    assert FORMAT_VERSION == 11


@pytest.mark.django_db
@pytest.mark.parametrize("size", ["small", "medium", "large", "full"])
def test_round_trip_preserves_the_preset(size, image_media):
    el = ImageElement.objects.create(
        media=image_media, alt="a", figcaption="", size=size
    )
    _model, ser = SERIALIZERS["image"]
    data = ser(el, _Ids())
    assert data["size"] == size
    _validate(data)
    rebuilt, _refs = BUILDERS["image"](data, {"m1": image_media})
    assert rebuilt.size == size


@pytest.mark.django_db
def test_archive_without_a_size_key_imports_as_full(image_media):
    data = {"media": "m1", "alt": "a", "figcaption": ""}
    _validate(data)
    assert data["size"] == "full"
    rebuilt, _refs = BUILDERS["image"](data, {"m1": image_media})
    assert rebuilt.size == "full"


@pytest.mark.django_db
def test_a_junk_size_is_coerced_to_full(image_media):
    """Named for what it does: this one pins COERCION, not import — unlike its
    sibling above it never calls BUILDERS."""
    data = {"media": "m1", "alt": "a", "figcaption": "", "size": "enormous"}
    _validate(data)  # must NOT raise
    assert data["size"] == "full"


@pytest.mark.django_db
def test_duplicating_an_image_preserves_its_preset():
    """The hole Task 1 opened and this task closes, asserted rather than assumed."""
    from courses import builder
    from tests.factories import add_element

    course, unit = make_course_with_unit()
    el = ImageElement.objects.create(
        media=_media(course), alt="a", figcaption="", size="small"
    )
    join = add_element(unit, el)
    _unit, new_join = builder.duplicate_element(
        course, join.pk, unit.updated.isoformat()
    )
    assert new_join.content_object.size == "small"
