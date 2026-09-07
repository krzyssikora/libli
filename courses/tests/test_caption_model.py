"""`ImageElement.figcaption` is rich text, sanitised on every write path.

The save() override is defence in depth, mirroring TextElement.save() and
GalleryElement.save(): the editor form is not the only way a caption reaches
the column (the transfer importer, the LAL loader and the admin all write it),
and `{{ el.figcaption|safe }}` in imageelement.html trusts whatever is stored.
"""

import pytest
from django.db import models

from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def test_figcaption_is_a_textfield_so_markup_has_room():
    """A CharField(255) cannot hold the field's own content any more: escaping
    the legacy plain text can already grow it past 255 (`&` -> `&amp;`), and one
    anchor costs a further ~30 characters before any visible text."""
    field = ImageElement._meta.get_field("figcaption")
    assert isinstance(field, models.TextField)
    assert not isinstance(field, models.CharField)


def test_save_keeps_a_link(image_media):
    el = ImageElement.objects.create(
        media=image_media,
        alt="a",
        figcaption='Photo: <a href="https://example.org">NASA</a>',
    )
    el.refresh_from_db()
    assert '<a href="https://example.org">NASA</a>' in el.figcaption


def test_save_strips_a_javascript_href(image_media):
    el = ImageElement.objects.create(
        media=image_media,
        alt="a",
        figcaption='<a href="javascript:alert(1)">x</a>',
    )
    el.refresh_from_db()
    assert "javascript" not in el.figcaption


def test_save_strips_a_script_tag(image_media):
    el = ImageElement.objects.create(
        media=image_media, alt="a", figcaption="a<script>alert(1)</script>b"
    )
    el.refresh_from_db()
    assert "script" not in el.figcaption


def test_a_later_save_sanitises_too(image_media):
    """Not just create: the editor's every subsequent save goes through the same
    override, so an update that smuggles markup must be cleaned as well."""
    el = ImageElement.objects.create(media=image_media, alt="a", figcaption="ok")
    el.figcaption = "<h2>big</h2>"
    el.save()
    el.refresh_from_db()
    assert "<h2" not in el.figcaption
    assert "big" in el.figcaption


def test_a_blank_caption_stays_falsy(image_media):
    """imageelement.html guards the whole <figcaption> element on truthiness, so
    an RTE surface cleared with Ctrl+A + Delete (which leaves markup behind)
    must not start rendering an empty caption box."""
    el = ImageElement.objects.create(
        media=image_media, alt="a", figcaption="<div><br></div>"
    )
    el.refresh_from_db()
    assert el.figcaption == ""
