"""Captions across the archive boundary.

The meaning of the `figcaption` key CHANGED at FORMAT_VERSION 14: before it, the
value is plain text; from it, HTML. The shape did not change, so nothing in the
schema notices -- which is exactly why the version gate has to do it. Importing
a v13 archive without escaping would drop everything after the first `<` (nh3
reads it as a tag that never closes) and render a bare `&` wrong.
"""

import pytest

from courses.models import ImageElement
from courses.models import MediaAsset
from courses.sanitize import CAPTION_MAX_LENGTH
from courses.transfer.export import SERIALIZERS
from courses.transfer.importer import BUILDERS
from courses.transfer.payloads import validate_element_data
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from tests.factories import make_course_with_unit

MEDIA_KINDS = {"m1": "image"}


class _Ids:
    def register(self, *a, **k):
        return "m1"


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def _el(caption):
    return {
        "id": "e1",
        "type": "image",
        "data": {"media": "m1", "alt": "a", "figcaption": caption, "size": "full"},
    }


def _validate(caption, *, format_version):
    el = _el(caption)
    validate_element_data(el, MEDIA_KINDS, format_version=format_version)
    return el["data"]["figcaption"]


def test_format_version_is_bumped_for_the_caption_meaning_change():
    assert FORMAT_VERSION == 14


def test_a_v13_caption_is_escaped_because_it_is_plain_text():
    assert _validate("Tom & Jerry", format_version=13) == "Tom &amp; Jerry"


def test_a_v13_caption_that_looks_like_markup_is_escaped_not_eaten():
    """The failure this prevents: nh3 reads `<` followed by a letter as a tag
    that never closes and drops everything after it, so an unescaped legacy
    caption arrives truncated at its first `<` -- silently, on import."""
    assert _validate("\\(a<b\\)", format_version=13) == "\\(a&lt;b\\)"


def test_a_v14_caption_is_left_alone_because_it_is_already_html():
    caption = 'Photo: <a href="https://example.org">NASA</a>'
    assert _validate(caption, format_version=14) == caption


def test_a_v14_caption_is_not_double_escaped():
    # The mutant: escaping unconditionally. It survives every round-trip test
    # (export then import re-escapes symmetrically), and only shows up as a
    # literal "&amp;" creeping onto the page one import at a time.
    assert _validate("Tom &amp; Jerry", format_version=14) == "Tom &amp; Jerry"


def test_an_unknown_version_is_treated_as_modern():
    """Deliberately the opposite default from the v12 quiz rule, which enforces
    when the version is None. That rule REJECTS on doubt, which is safe; this one
    TRANSFORMS on doubt, and transforming a modern caption corrupts it visibly
    and permanently. No import path reaches here without a manifest anyway."""
    assert _validate("Tom &amp; Jerry", format_version=None) == "Tom &amp; Jerry"


def test_a_caption_longer_than_the_cap_is_rejected():
    with pytest.raises(TransferError):
        _validate("x" * (CAPTION_MAX_LENGTH + 1), format_version=FORMAT_VERSION)


def test_the_cap_leaves_room_for_markup_the_old_255_did_not():
    """Regression on the number itself: 255 was the plain-text CharField bound,
    and one anchor costs ~30 characters before any visible text."""
    assert CAPTION_MAX_LENGTH == 1000
    assert _validate("x" * CAPTION_MAX_LENGTH, format_version=FORMAT_VERSION)


@pytest.mark.django_db
def test_round_trip_preserves_a_caption_link(image_media):
    caption = 'Photo: <a href="https://example.org">NASA</a>'
    el = ImageElement.objects.create(media=image_media, alt="a", figcaption=caption)
    _model, ser = SERIALIZERS["image"]
    data = ser(el, _Ids())
    assert data["figcaption"] == caption

    wrapper = {"id": "e1", "type": "image", "data": data}
    validate_element_data(wrapper, MEDIA_KINDS, format_version=FORMAT_VERSION)
    rebuilt, _refs = BUILDERS["image"](wrapper["data"], {"m1": image_media})
    rebuilt.save()
    rebuilt.refresh_from_db()
    assert rebuilt.figcaption == caption


@pytest.mark.django_db
def test_importing_a_v13_plain_text_caption_stores_escaped_html(image_media):
    """End to end: the escaped value must also survive the model's sanitiser, or
    the gain is undone one line later."""
    el = _el("Tom & Jerry <b>x</b>")
    validate_element_data(el, MEDIA_KINDS, format_version=13)
    rebuilt, _refs = BUILDERS["image"](el["data"], {"m1": image_media})
    rebuilt.save()
    rebuilt.refresh_from_db()
    assert rebuilt.figcaption == "Tom &amp; Jerry &lt;b&gt;x&lt;/b&gt;"
