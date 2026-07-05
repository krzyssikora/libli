# tests/test_transfer_validation.py
import pytest

from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document


def base_course_doc(**over):
    doc = {
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
        "nodes": [],
        "elements": [],
        "media": [],
    }
    doc.update(over)
    return doc


def node(nid, kind="unit", parent=None, **over):
    d = {
        "id": nid,
        "parent": parent,
        "kind": kind,
        "title": "N",
        "unit_type": "lesson" if kind == "unit" else None,
        "obligatory": True,
        "html_seed_js": "",
    }
    d.update(over)
    return d


def text_el(eid, unit, body="hi"):
    return {
        "id": eid,
        "unit": unit,
        "title": "",
        "type": "text",
        "data": {"body": body},
    }


def _reject(doc, needle, kind="course", target_allowed_kinds=None):
    with pytest.raises(TransferError) as exc:
        validate_document(doc, kind=kind, target_allowed_kinds=target_allowed_kinds)
    assert needle.lower() in exc.value.message.lower()


def test_happy_minimal():
    doc = base_course_doc(nodes=[node("n1")], elements=[text_el("e1", "n1")])
    validate_document(doc, kind="course")


def test_unknown_top_key():
    _reject(base_course_doc(extra=1), "extra")


def test_unknown_node_key():
    doc = base_course_doc(nodes=[node("n1", owner="hax")])
    _reject(doc, "owner")


def test_blank_course_title():
    doc = base_course_doc()
    doc["course"]["title"] = "  "
    _reject(doc, "title")


def test_bad_language():
    doc = base_course_doc()
    doc["course"]["language"] = "xx"
    _reject(doc, "language")


def test_nonempty_color_bands_must_validate():
    doc = base_course_doc()
    doc["course"]["color_bands"] = [{"key": "junk"}]
    _reject(doc, "color")
    doc["course"]["color_bands"] = []
    validate_document(doc, kind="course")  # empty is valid


def test_duplicate_ids_reject():
    doc = base_course_doc(nodes=[node("n1"), node("n1", kind="part")])
    _reject(doc, "n1")


def test_dangling_parent_and_forward_parent_reject():
    _reject(base_course_doc(nodes=[node("n1", parent="nope")]), "parent")
    doc = base_course_doc(
        nodes=[node("n1", kind="unit", parent="n2"), node("n2", kind="part")]
    )
    _reject(doc, "parent")  # forward ref: parent must be earlier


def test_illegal_nesting_rejects():
    doc = base_course_doc(
        nodes=[node("n1", kind="unit"), node("n2", kind="part", parent="n1")]
    )
    _reject(doc, "kind")


def test_depth_flags_own_consistency():
    doc = base_course_doc(
        nodes=[
            node("n1", kind="part"),
        ]
    )
    doc["course"]["uses_parts"] = False
    _reject(doc, "part")


def test_nonpreset_flags_accepted():
    doc = base_course_doc(
        nodes=[
            node("n1", kind="part"),
            node("n2", kind="section", parent="n1"),
            node("n3", parent="n2"),
        ]
    )
    doc["course"]["uses_chapters"] = False  # (True, False, True) = Custom
    validate_document(doc, kind="course")


def test_subtree_target_flags():
    doc = {
        "context": {
            "source_course_title": "S",
            "root_kind": "part",
            "required_kinds": ["part"],
            "html_css": "",
            "html_js": "",
        },
        "nodes": [node("n1", kind="part")],
        "elements": [],
        "media": [],
    }
    _reject(
        doc, "part", kind="subtree", target_allowed_kinds=["chapter", "unit"]
    )  # chapters-only course


def test_subtree_exactly_one_root():
    ctx = {
        "source_course_title": "S",
        "root_kind": "unit",
        "required_kinds": ["unit"],
        "html_css": "",
        "html_js": "",
    }
    doc = {
        "context": ctx,
        "nodes": [node("n1"), node("n2")],
        "elements": [],
        "media": [],
    }
    _reject(
        doc,
        "root",
        kind="subtree",
        target_allowed_kinds=["part", "chapter", "section", "unit"],
    )


def test_element_unit_must_be_unit_kind():
    doc = base_course_doc(
        nodes=[node("n1", kind="part")], elements=[text_el("e1", "n1")]
    )
    _reject(doc, "unit")


def test_unknown_element_type_named():
    doc = base_course_doc(
        nodes=[node("n1")],
        elements=[
            {"id": "e1", "unit": "n1", "title": "", "type": "hologram", "data": {}}
        ],
    )
    _reject(doc, "hologram")


def test_count_caps(settings):
    settings.TRANSFER_MAX_NODES = 1
    doc = base_course_doc(nodes=[node("n1", kind="part"), node("n2", parent="n1")])
    _reject(doc, "node")


def test_obligatory_must_be_bool():
    doc = base_course_doc(nodes=[node("n1", obligatory="yes")])
    _reject(doc, "obligatory")


def test_media_entry_shape_and_uniqueness():
    m = {
        "id": "m1",
        "kind": "image",
        "name": "",
        "original_filename": "a.png",
        "file": "media/m1.png",
    }
    doc = base_course_doc(media=[m, {**m, "id": "m2"}])  # same file → reject
    doc["nodes"] = [node("n1")]
    doc["elements"] = [
        {
            "id": "e1",
            "unit": "n1",
            "title": "",
            "type": "image",
            "data": {"media": "m1", "alt": "", "figcaption": ""},
        },
        {
            "id": "e2",
            "unit": "n1",
            "title": "",
            "type": "image",
            "data": {"media": "m2", "alt": "", "figcaption": ""},
        },
    ]
    _reject(doc, "media/m1.png")


def test_unreferenced_media_item_rejects():
    m = {
        "id": "m1",
        "kind": "image",
        "name": "",
        "original_filename": "a.png",
        "file": "media/m1.png",
    }
    doc = base_course_doc(media=[m], nodes=[node("n1")], elements=[text_el("e1", "n1")])
    _reject(doc, "referenced")


def test_bad_media_kind():
    m = {
        "id": "m1",
        "kind": "audio",
        "name": "",
        "original_filename": "a.mp3",
        "file": "media/m1.mp3",
    }
    doc = base_course_doc(media=[m])
    _reject(doc, "kind")


def test_unhashable_values_reject_not_500():
    # list/dict where a hashable is expected must reject, never TypeError.
    _reject(base_course_doc(nodes=[node("n1", parent=["x"])]), "parent")
    doc = base_course_doc()
    doc["course"]["language"] = []
    _reject(doc, "language")
    _reject(base_course_doc(nodes=[node("n1", kind=["part"], unit_type=None)]), "kind")
    doc3 = base_course_doc(
        nodes=[node("n1")],
        elements=[
            {"id": "e1", "unit": [], "title": "", "type": "text", "data": {"body": "x"}}
        ],
    )
    _reject(doc3, "unit")
    doc4 = base_course_doc(
        nodes=[node("n1")],
        elements=[
            {
                "id": "e1",
                "unit": "n1",
                "title": "",
                "type": ["text"],
                "data": {"body": "x"},
            }
        ],
    )
    _reject(doc4, "type")
