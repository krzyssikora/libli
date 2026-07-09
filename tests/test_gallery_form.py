import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import GalleryElementForm
from tests.factories import make_course
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _post(images, desc_pos="below"):
    import json

    return {"data": json.dumps({"desc_pos": desc_pos, "images": images})}


def test_registered():
    assert FORM_FOR_TYPE["gallery"] is GalleryElementForm


def test_valid_two_images():
    course = make_course()
    a1, a2 = make_image_asset(course), make_image_asset(course)
    form = GalleryElementForm(
        data=_post([{"media": a1.pk, "desc": "x"}, {"media": a2.pk, "desc": ""}]),
        course=course,
    )
    assert form.is_valid(), form.errors
    assert len(form.cleaned_data["data"]["images"]) == 2


def test_rejects_fewer_than_two():
    course = make_course()
    a1 = make_image_asset(course)
    form = GalleryElementForm(
        data=_post([{"media": a1.pk, "desc": "x"}]), course=course
    )
    assert not form.is_valid()


def test_rejects_more_than_twenty():
    course = make_course()
    imgs = [{"media": make_image_asset(course).pk, "desc": ""} for _ in range(21)]
    form = GalleryElementForm(data=_post(imgs), course=course)
    assert not form.is_valid()


def test_rejects_foreign_or_non_image_media():
    course, other = make_course(), make_course()
    a1 = make_image_asset(course)
    foreign = make_image_asset(other)
    form = GalleryElementForm(
        data=_post([{"media": a1.pk, "desc": ""}, {"media": foreign.pk, "desc": ""}]),
        course=course,
    )
    assert not form.is_valid()


def test_rejects_non_list_images():
    course = make_course()
    import json

    form = GalleryElementForm(
        data={"data": json.dumps({"desc_pos": "below", "images": "nope"})},
        course=course,
    )
    assert not form.is_valid()


def test_duplicates_allowed():
    course = make_course()
    a1 = make_image_asset(course)
    form = GalleryElementForm(
        data=_post([{"media": a1.pk, "desc": ""}, {"media": a1.pk, "desc": ""}]),
        course=course,
    )
    assert form.is_valid(), form.errors


def test_editor_rows_from_instance():
    from courses.models import GalleryElement

    course = make_course()
    a1 = make_image_asset(course)
    el = GalleryElement.objects.create(
        data={"desc_pos": "below", "images": [{"media": a1.pk, "desc": "cap"}]}
    )
    rows = GalleryElementForm(instance=el, course=course).editor_rows
    assert rows == [{"id": a1.pk, "thumb_url": a1.file.url, "desc": "cap"}]
