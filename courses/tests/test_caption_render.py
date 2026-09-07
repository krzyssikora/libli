"""imageelement.html renders the caption as HTML.

`|safe` is only defensible because ImageElement.save() is the boundary: every
write path runs sanitize_caption, so the column can never hold a tag outside
CAPTION_TAGS. These tests pin both halves -- the link reaches the page, and the
things the sanitiser drops never do.
"""

import pytest

from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db


def make_image(caption):
    course, _unit = make_course_with_unit()
    media = MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )
    return ImageElement.objects.create(media=media, alt="a", figcaption=caption)


def test_a_caption_link_reaches_the_page_as_an_anchor():
    html = make_image('Photo: <a href="https://example.org">NASA</a>').render()
    assert '<a href="https://example.org">NASA</a>' in html


def test_emphasis_reaches_the_page_as_a_tag():
    assert "<b>x</b>" in make_image("a <b>x</b> b").render()


def test_a_caption_that_is_plain_text_is_not_double_escaped():
    """The migration escaped legacy captions once. Rendering with `|safe` must
    not escape them a second time -- `{{ el.figcaption }}` here would put a
    literal `&amp;` on screen for every caption migrated from `&`."""
    html = make_image("Tom &amp; Jerry").render()
    assert "Tom &amp; Jerry" in html
    assert "&amp;amp;" not in html


def test_a_script_tag_never_reaches_the_page():
    html = make_image("a<script>alert(1)</script>b").render()
    assert "<script" not in html


def test_no_figcaption_element_when_the_caption_is_blank():
    assert "<figcaption" not in make_image("").render()


def test_a_caption_cleared_in_the_rte_leaves_no_empty_figcaption():
    # Ctrl+A + Delete on the surface leaves "<div><br></div>" behind. The guard
    # is truthiness, so an un-collapsed value would render an empty caption box
    # under every image it was cleared from.
    assert "<figcaption" not in make_image("<div><br></div>").render()
