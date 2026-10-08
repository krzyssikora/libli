import pytest

from courses.builder import duplicate_element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import VALIDATORS
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db
MEDIA_KINDS = {"m1": "image"}


class _Ids:
    def register(self, *a, **k):
        return "m1"


def _media(course):
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def _data(**over):
    d = {"media": "m1", "alt": "a", "figcaption": "", "size": "small"}
    d.update(over)
    return d


def test_version_is_17():
    assert FORMAT_VERSION == 17


def test_round_trip_keeps_the_flag():
    course, _u = make_course_with_unit()
    media = _media(course)
    el = ImageElement.objects.create(media=media, size="small", float_right=True)
    _model, ser = SERIALIZERS["image"]  # (model, fn) tuple, export.py
    data = ser(el, _Ids())
    assert data["float_right"] is True
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)
    built, _ = BUILDERS["image"](data, {"m1": media})
    assert built.float_right is True


def test_missing_key_imports_as_false():
    data = _data()
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)
    assert data["float_right"] is False


@pytest.mark.parametrize("junk", ["yes", 1, None, []])
def test_non_bool_is_coerced_to_false_not_rejected(junk):
    data = _data(float_right=junk)
    VALIDATORS["image"](data, "e1", MEDIA_KINDS)  # must not raise
    assert data["float_right"] is False


def test_duplicate_keeps_the_flag():
    course, unit = make_course_with_unit()
    el = ImageElement.objects.create(
        media=_media(course), size="small", float_right=True
    )
    join = add_element(unit, el)
    _unit, new_join = duplicate_element(course, join.pk, unit.updated.isoformat())
    assert new_join.content_object.float_right is True
