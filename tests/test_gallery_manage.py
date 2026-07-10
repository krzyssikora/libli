import json

import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from courses.models import Element
from courses.models import GalleryElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_menu_has_gallery_card():
    # Partial-independent: the add-menu card is what routes to element_add.
    html = render_to_string("courses/manage/editor/_add_menu.html")
    assert 'data-add-type="gallery"' in html
    assert "#el-gallery" in html


def test_element_add_accepts_gallery_type():
    # element_add fully renders the open-form host, which auto-includes
    # courses/manage/editor/_edit_gallery.html (already built in Task 5) — so
    # what THIS task owns is the dispatch allow-tuple: "gallery" must clear the
    # "bad type" 400 gate.
    client = Client(raise_request_exception=False)
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "gallery", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code != 400


def test_save_persists_gallery(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    a1, a2 = make_image_asset(course), make_image_asset(course)
    payload = {
        "type": "gallery",
        "element": "new",
        "unit": unit.pk,
        "unit_token": unit.updated.isoformat(),
        "el_title": "My gallery",
        "data": json.dumps(
            {
                "desc_pos": "below",
                "images": [
                    {"media": a1.pk, "desc": "x"},
                    {"media": a2.pk, "desc": ""},
                ],
            }
        ),
    }
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        payload,
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    el = Element.objects.get(unit=unit)
    assert isinstance(el.content_object, GalleryElement)
    assert len(el.content_object.data["images"]) == 2


def test_element_row_label_and_type_chip_are_human_readable():
    """The element row is the author's main handle on a gallery. Without these,
    it falls back to the model's class name ("GalleryElement" / the
    "galleryelement" chip) rather than a summary of what's in it.
    """
    from django.contrib.contenttypes.models import ContentType

    from courses.templatetags.courses_manage_extras import element_summary
    from courses.templatetags.courses_manage_extras import element_type_label

    el = GalleryElement(
        data=GalleryElement.normalize_data(
            {"images": [{"media": 1, "desc": ""}, {"media": 2, "desc": ""}]}
        )
    )
    assert element_summary(el) == "2 images"

    ct = ContentType.objects.get_for_model(GalleryElement)
    assert str(element_type_label(ct)) == "Gallery"


def test_element_summary_pluralises_a_single_image():
    from courses.templatetags.courses_manage_extras import element_summary

    el = GalleryElement(
        data=GalleryElement.normalize_data({"images": [{"media": 1, "desc": ""}]})
    )
    assert element_summary(el) == "1 image"
