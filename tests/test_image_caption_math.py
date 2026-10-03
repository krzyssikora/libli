import pytest

from courses.models import ImageElement
from courses.views import _element_has_math
from tests.factories import make_course
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _image(figcaption):
    asset = make_image_asset(make_course())
    return ImageElement.objects.create(media=asset, alt="a", figcaption=figcaption)


def test_image_caption_math_arms_katex():
    # A caption is the only math on a page often enough (a labelled diagram) that
    # missing it leaves the lesson without KaTeX and the caption as raw \(...\).
    assert _element_has_math(_image(r"Wykres \(y=x^2\)")) is True


def test_image_plain_caption_does_not_arm_katex():
    assert _element_has_math(_image("plain caption")) is False
