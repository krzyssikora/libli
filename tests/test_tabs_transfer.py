import io

import pytest

from courses.models import Element
from courses.models import GalleryElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.transfer.export import build_export
from courses.transfer.export import write_archive
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.payloads import validate_element_data
from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document
from tests.factories import make_course_with_unit
from tests.factories import make_image_asset
from tests.factories import make_login

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


def test_format_version_is_5():
    assert FORMAT_VERSION == 5


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


# --- Task 10: import validation + two-pass nesting ---------------------------


def _els(*items):
    return list(items)


def _tabs_el(eid="e1", tabs=None):
    tabs = tabs or [{"id": "taaaaaa", "label": "A"}, {"id": "tbbbbbb", "label": "B"}]
    return {
        "id": eid,
        "type": "tabs",
        "data": {"tabs": tabs},
        "parent": None,
        "tab": "",
    }


def _child(eid="e2", parent="e1", tab="taaaaaa", type_="text"):
    return {"id": eid, "type": type_, "data": {}, "parent": parent, "tab": tab}


def test_nesting_validation_accepts_a_wellformed_document():
    validate_nesting(_els(_tabs_el(), _child()))  # must not raise


@pytest.mark.parametrize(
    "elements",
    [
        _els(_tabs_el(), _child(parent="e9")),  # unknown parent
        _els(_tabs_el(), _child(tab="tzzzzzz")),  # tab not in parent
        _els(_tabs_el(), _child(type_="choice")),  # non-nestable child
        _els(_tabs_el(), _child(type_="tabs")),  # tabs in tabs
        _els(_tabs_el(), _child(), _child("e3", parent="e2")),  # depth > 1
        _els(
            {
                "id": "e1",
                "type": "text",
                "data": {},
                "parent": None,
                "tab": "",
            },
            _child(parent="e1"),
        ),  # parent not tabs
    ],
)
def test_nesting_validation_rejects(elements):
    with pytest.raises(TransferError):
        validate_nesting(elements)


@pytest.mark.parametrize(
    "tabs",
    [
        [{"id": "taaaaaa", "label": "only"}],  # < MIN
        [{"id": f"t{i:06x}", "label": "x"} for i in range(11)],  # > MAX
        [{"id": "taaaaaa", "label": "A"}, {"id": "taaaaaa", "label": "B"}],  # duplicate
        [{"id": "NOPE", "label": "A"}, {"id": "tbbbbbb", "label": "B"}],  # bad format
        [
            {"id": "t" + "a" * 20, "label": "A"},
            {"id": "tbbbbbb", "label": "B"},
        ],  # too long
    ],
)
def test_tabs_validator_rejects_bad_tab_lists(tabs):
    with pytest.raises(TransferError):
        validate_element_data(_tabs_el(tabs=tabs), {})


def test_tabs_validator_accepts_a_wellformed_tab_list():
    assert validate_element_data(_tabs_el(), {}) == set()  # references no media


def test_registries_lockstep():
    from courses.transfer.export import SERIALIZERS
    from courses.transfer.importer import BUILDERS
    from courses.transfer.payloads import VALIDATORS

    assert "tabs" in SERIALIZERS
    assert "tabs" in VALIDATORS
    assert "tabs" in BUILDERS


def test_nestable_keys_agree_across_the_two_namespaces():
    from courses.builder import NESTABLE_TYPE_KEYS
    from courses.transfer.export import SERIALIZERS

    assert NESTABLE_TYPE_KEYS <= set(SERIALIZERS)


def _base_course_doc(nodes, elements):
    return {
        "course": {
            "title": "T",
            "language": "en",
            "overview": "",
            "html_css": "",
            "html_js": "",
            "uses_parts": True,
            "uses_chapters": True,
            "uses_sections": True,
            "color_bands": [],
            "subjects": [],
        },
        "nodes": nodes,
        "elements": elements,
        "media": [],
    }


def _unit_node(nid="n1"):
    return {
        "id": nid,
        "parent": None,
        "kind": "unit",
        "title": "U",
        "unit_type": "lesson",
        "obligatory": True,
        "html_seed_js": "",
    }


def test_v2_element_without_parent_or_tab_passes_exact_keys():
    """A legacy v2 element carries neither key; the shim adds them so it passes
    the element-level exact-keys check instead of being rejected as malformed."""
    el = {"id": "e1", "unit": "n1", "title": "", "type": "text", "data": {"body": ""}}
    validate_document(_base_course_doc([_unit_node()], [el]), kind="course")
    assert el["parent"] is None and el["tab"] == ""


def test_v2_archive_still_imports_with_everything_top_level():
    """No `parent`/`tab` keys at all -> `.get()` shim in the two-pass importer ->
    the element is created top-level (parent None, empty tab)."""
    from courses.transfer.importer import _create_elements

    course, unit = make_course_with_unit()
    el = {"id": "e1", "unit": "n1", "title": "", "type": "text", "data": {"body": "hi"}}
    _create_elements({"elements": [el]}, {"n1": unit}, {})
    created = Element.objects.get(unit=unit)
    assert created.parent_id is None and created.tab_id == ""


def _round_trip(client, course):
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    owner = make_login(client, "tabs-importer")
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="course", target_course=None
        )
        return import_course(zf, mani, doc, media, owner)


def test_round_trip_preserves_nesting_media_and_child_order(client, settings, tmp_path):
    """The spec's headline transfer test: a gallery nested in tab 2, with a sibling
    ahead of it, survives export -> import with nesting, media AND order intact."""
    settings.MEDIA_ROOT = tmp_path
    course, unit, join, t1, t2, first, second = _nested_course()
    _round_trip(client, course)
    imported_tabs = TabsElement.objects.exclude(pk=join.content_object.pk).get()
    imported_join = imported_tabs.join_row()
    kids = list(imported_join.children.order_by("order", "pk"))
    assert [type(k.content_object).__name__ for k in kids] == [
        "TextElement",
        "GalleryElement",
    ]
    assert {k.tab_id for k in kids} == {imported_tabs.data["tabs"][1]["id"]}
    assert imported_tabs.data["tabs"][1]["id"] == t2  # tab ids preserved VERBATIM
    # nested gallery media survived the boundary
    imported_gallery = kids[1].content_object
    assert len(imported_gallery.data["images"]) == 2
