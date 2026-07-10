import pytest

from courses.models import Element
from courses.models import GalleryElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.export import build_export
from courses.transfer.schema import FORMAT_VERSION
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset

pytestmark = pytest.mark.django_db


def _document(course, node=None):
    """build_export returns a (manifest, document, media_assets, problems) tuple;
    the document (index 1) is the {course/context, nodes, elements, media} dict."""
    return build_export(course, node)[1]


def _nested_course():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    t1, t2 = [t["id"] for t in tabs.data["tabs"]]
    a = make_image_asset(course, "a.png")
    b = make_image_asset(course, "b.png")
    gal = GalleryElement.objects.create(
        data={
            "desc_pos": "below",
            "images": [{"media": a.pk, "desc": ""}, {"media": b.pk, "desc": ""}],
        }
    )
    first = Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="one"),
        parent=join,
        tab_id=t2,
    )
    second = Element.objects.create(
        unit=unit, content_object=gal, parent=join, tab_id=t2
    )
    return course, unit, join, t1, t2, first, second


def test_format_version_is_3():
    assert FORMAT_VERSION == 3


def test_export_emits_parent_before_child_with_parent_and_tab_refs(tmp_path):
    course, unit, join, t1, t2, first, second = _nested_course()
    doc = _document(course)
    els = doc["elements"]
    ids = [e["id"] for e in els]
    parent_el = next(e for e in els if e["type"] == "tabs")
    kids = [e for e in els if e.get("parent")]
    assert len(kids) == 2
    assert all(k["parent"] == parent_el["id"] for k in kids)
    assert all(k["tab"] == t2 for k in kids)
    # parents precede children
    assert ids.index(parent_el["id"]) < min(ids.index(k["id"]) for k in kids)
    # top-level element carries explicit nulls, not a missing key
    assert parent_el["parent"] is None and parent_el["tab"] == ""


def test_within_tab_child_order_is_preserved(tmp_path):
    course, unit, join, t1, t2, first, second = _nested_course()
    doc = _document(course)
    kids = [e for e in doc["elements"] if e.get("parent")]
    assert kids[0]["type"] == "text" and kids[1]["type"] == "gallery"


def test_nested_gallery_media_appear_exactly_once(tmp_path):
    """'The media survive' stays green under a double-count -- the duplicate manifest
    entry re-imports the same file and the gallery still references one asset. Count."""
    course, unit, join, t1, t2, first, second = _nested_course()
    doc = _document(course)
    mids = [m["id"] for m in doc["media"]]
    assert len(mids) == len(set(mids)) == 2


def test_empty_tabs_element_exports_its_labels():
    course, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    Element.objects.create(unit=unit, content_object=tabs)
    doc = _document(course)
    payload = next(e for e in doc["elements"] if e["type"] == "tabs")
    assert len(payload["data"]["tabs"]) == 2
