import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from courses.element_forms import ImageElementForm
from courses.models import ImageElement
from courses.models import MediaAsset
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

PO = Path(__file__).resolve().parents[2] / "locale/pl/LC_MESSAGES/django.po"


@pytest.fixture
def image_media():
    course, _unit = make_course_with_unit()
    return MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )


def _post(media, **extra):
    data = {"media": media.pk, "alt": "a", "figcaption": "", "size": "small"}
    data.update(extra)
    return ImageElementForm(data=data, course=media.course)


def test_form_saves_the_flag_on_small(image_media):
    form = _post(image_media, float_right="on")
    assert form.is_valid(), form.errors
    assert form.save().float_right is True


@pytest.mark.parametrize("size", ["medium", "large", "full"])
def test_a_non_small_post_with_the_flag_stores_false(image_media, size):
    form = _post(image_media, size=size, float_right="on")
    assert form.is_valid(), form.errors
    assert form.save().float_right is False


def test_an_edit_without_the_key_stores_false(image_media):
    el = ImageElement.objects.create(media=image_media, size="small", float_right=True)
    form = ImageElementForm(
        data={"media": image_media.pk, "alt": "b", "figcaption": "", "size": "small"},
        instance=el,
        course=image_media.course,
    )
    assert form.is_valid(), form.errors
    assert form.save().float_right is False  # an unchecked checkbox submits nothing


def _box(form):
    html = render_to_string("courses/manage/editor/_edit_image.html", {"form": form})
    m = re.search(r"<input[^>]*data-float-right[^>]*>", html)
    assert m, "no float-right checkbox rendered"
    return m.group(0)


def test_a_stored_true_on_medium_renders_unchecked_and_disabled(image_media):
    el = ImageElement.objects.create(media=image_media, size="medium", float_right=True)
    tag = _box(ImageElementForm(instance=el, course=image_media.course))
    assert " checked" not in tag and " disabled" in tag


def test_a_flagged_small_renders_checked_and_enabled(image_media):
    el = ImageElement.objects.create(media=image_media, size="small", float_right=True)
    tag = _box(ImageElementForm(instance=el, course=image_media.course))
    assert " checked" in tag and " disabled" not in tag


def test_the_create_flow_renders_the_box_disabled(image_media):
    # A new image defaults to Full.
    tag = _box(ImageElementForm(course=image_media.course))
    assert " disabled" in tag and 'data-for-element=""' in tag


def test_an_invalid_post_keeps_the_authors_size_and_tick(image_media):
    form = _post(image_media, float_right="on", figcaption="x" * 100_000)
    assert not form.is_valid()
    tag = _box(form)
    assert " checked" in tag and " disabled" not in tag


def test_polish_label_exists_and_is_not_fuzzy():
    text = PO.read_text(encoding="utf-8")
    block = re.search(r'((?:#[^\n]*\n)*)msgid "Float right"\nmsgstr "([^"]*)"', text)
    assert block, "msgid missing"
    assert "fuzzy" not in block.group(1) and block.group(2)
