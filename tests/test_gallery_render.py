import pytest

from courses.models import GalleryElement
from courses.views import _gallery_has_math
from tests.factories import make_course
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _gallery(desc_pos, descs):
    course = make_course()
    imgs = []
    for d in descs:
        a = make_image_asset(course)
        imgs.append({"media": a.pk, "desc": d})
    return GalleryElement.objects.create(data={"desc_pos": desc_pos, "images": imgs})


def test_render_two_images_emits_figures_and_root_class():
    html = _gallery("below", ["<b>one</b>", ""]).render()
    assert "el el--gallery" in html
    assert "data-gallery" in html
    assert html.count("gallery__item") == 2
    assert html.count("gallery__frame") == 2
    # a .gallery__desc is emitted for EVERY figure (empty for the 2nd)
    assert html.count("gallery__desc") == 2
    assert "<b>one</b>" in html


def test_render_alt_fallback_for_math_only_desc():
    html = _gallery("below", [r"\(x^2\)", "plain"]).render()
    assert 'alt="Image 1 of 2"' in html  # math-only -> generic fallback
    assert 'alt="plain"' in html


def test_render_empty_desc_is_decorative():
    # A genuinely EMPTY description is intentionally decorative: alt="" (no
    # generic fallback). Only non-empty-but-strips-to-empty gets the fallback.
    html = _gallery("below", ["", "plain"]).render()
    assert 'alt=""' in html


def test_render_zero_resolvable_omits_container():
    el = GalleryElement.objects.create(
        data={"desc_pos": "below", "images": [{"media": 999999, "desc": "x"}]}
    )
    assert el.render().strip() == ""  # nothing rendered


def test_render_desc_pos_above_orders_desc_before_frame():
    html = _gallery("above", ["cap", "cap2"]).render()
    assert html.index("gallery__desc") < html.index("gallery__frame")


def test_gallery_has_math():
    assert _gallery_has_math(_gallery("below", [r"\(a\)", ""])) is True
    assert _gallery_has_math(_gallery("below", ["plain", ""])) is False
