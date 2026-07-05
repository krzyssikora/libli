# tests/test_transfer_media.py
import pytest

from courses.models import ContentNode
from courses.models import Course
from courses.models import Subject
from courses.transfer.importer import build_preview
from courses.transfer.importer import insertion_choices
from courses.transfer.importer import match_subjects
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.importer import validate_media_entries
from courses.transfer.schema import TransferError
from tests.test_transfer_archive import make_manifest
from tests.test_transfer_archive import make_zip

pytestmark = pytest.mark.django_db


def base_course(media=None, nodes=None, elements=None, subjects=None):
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
            "subjects": subjects or [],
        },
        "nodes": nodes or [],
        "elements": elements or [],
        "media": media or [],
    }


IMG_MEDIA = {
    "id": "m1",
    "kind": "image",
    "name": "",
    "original_filename": "a.png",
    "file": "media/m1.png",
}


def unit_node(nid="n1"):
    return {
        "id": nid,
        "parent": None,
        "kind": "unit",
        "title": "N",
        "unit_type": "lesson",
        "obligatory": True,
        "html_seed_js": "",
    }


def image_element(eid="e1", unit="n1", media_id="m1"):
    return {
        "id": eid,
        "unit": unit,
        "title": "",
        "type": "image",
        "data": {"media": media_id, "alt": "", "figcaption": ""},
    }


def text_element(eid="e1", unit="n1"):
    return {
        "id": eid,
        "unit": unit,
        "title": "",
        "type": "text",
        "data": {"body": "hi"},
    }


# --- validate_media_entries: correspondence ----------------------------------


def test_missing_media_entry_named_id_and_path():
    doc = base_course(media=[IMG_MEDIA])
    buf = make_zip(document=doc)  # no media/m1.png entry in the zip at all
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        with pytest.raises(TransferError) as exc:
            validate_media_entries(document, media)
    msg = exc.value.message
    assert "m1" in msg
    assert "media/m1.png" in msg


def test_extra_unlisted_media_entry_rejects():
    doc = base_course(media=[])
    buf = make_zip(document=doc, entries=[("media/orphan.png", b"x")])
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        with pytest.raises(TransferError) as exc:
            validate_media_entries(document, media)
    assert "orphan.png" in exc.value.message


def test_wrong_extension_media_names_file():
    bad = {**IMG_MEDIA, "original_filename": "a.exe", "file": "media/m1.exe"}
    doc = base_course(media=[bad])
    buf = make_zip(document=doc, entries=[("media/m1.exe", b"x" * 5)])
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        with pytest.raises(TransferError) as exc:
            validate_media_entries(document, media)
    assert "a.exe" in exc.value.message


def test_oversized_media_names_file(monkeypatch):
    monkeypatch.setattr(
        "courses.transfer.importer.effective_max_image_bytes", lambda: 10
    )
    doc = base_course(media=[IMG_MEDIA])
    buf = make_zip(document=doc, entries=[("media/m1.png", b"x" * 20)])
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        with pytest.raises(TransferError) as exc:
            validate_media_entries(document, media)
    assert "a.png" in exc.value.message


def test_valid_media_entry_passes():
    doc = base_course(media=[IMG_MEDIA])
    buf = make_zip(document=doc, entries=[("media/m1.png", b"x" * 20)])
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        validate_media_entries(document, media)  # no raise


# --- validate_archive_document: wiring ---------------------------------------


def test_validate_archive_document_happy_course():
    doc = base_course(
        media=[IMG_MEDIA], nodes=[unit_node()], elements=[image_element()]
    )
    buf = make_zip(document=doc, entries=[("media/m1.png", b"x" * 20)])
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        validate_archive_document(zf, mani, document, media, kind="course")


def test_validate_archive_document_surfaces_media_error():
    doc = base_course(
        media=[IMG_MEDIA], nodes=[unit_node()], elements=[image_element()]
    )
    buf = make_zip(document=doc)  # missing media/m1.png in the zip
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        with pytest.raises(TransferError) as exc:
            validate_archive_document(zf, mani, document, media, kind="course")
    assert "media/m1.png" in exc.value.message


# --- match_subjects -----------------------------------------------------------


def test_match_subjects_case_insensitive_either_language():
    Subject.objects.create(title_en="Math", title_pl="Matematyka", slug="math")
    subs = [
        {"title_en": "MATH", "title_pl": ""},
        {"title_en": "", "title_pl": "matematyka"},
    ]
    matched, dropped = match_subjects(subs)
    assert len(matched) == 2
    assert dropped == []


def test_match_subjects_blank_pl_never_cross_matches():
    # A Subject with a blank Polish title must not be matched by an exported
    # subject whose PL leg is also blank (that would be a false-positive
    # iexact("") == "" collision, not a real match).
    Subject.objects.create(title_en="Biology", title_pl="", slug="bio")
    subs = [{"title_en": "NotBiology", "title_pl": ""}]
    matched, dropped = match_subjects(subs)
    assert matched == []
    assert dropped == subs


def test_match_subjects_tiebreak_by_title_en_then_pk():
    first = Subject.objects.create(title_en="Dup", title_pl="", slug="dup-1")
    Subject.objects.create(title_en="Dup", title_pl="", slug="dup-2")
    matched, dropped = match_subjects([{"title_en": "DUP", "title_pl": ""}])
    assert matched == [first]
    assert dropped == []


def test_match_subjects_no_match_dropped():
    subs = [{"title_en": "Nonexistent", "title_pl": ""}]
    matched, dropped = match_subjects(subs)
    assert matched == []
    assert dropped == subs


# --- insertion_choices ---------------------------------------------------------


def test_insertion_choices_chapters_only_target():
    course = Course.objects.create(
        title="C", slug="c", uses_parts=False, uses_chapters=True, uses_sections=False
    )
    assert insertion_choices(course, "chapter") == [{"value": "", "label": "Top level"}]
    assert insertion_choices(course, "part") == []


# --- build_preview --------------------------------------------------------------


def test_build_preview_course_counts_and_subjects():
    Subject.objects.create(title_en="Math", title_pl="", slug="math")
    manifest = make_manifest()
    doc = base_course(
        media=[IMG_MEDIA],
        nodes=[unit_node()],
        elements=[text_element()],
        subjects=[
            {"title_en": "Math", "title_pl": ""},
            {"title_en": "Unknown", "title_pl": ""},
        ],
    )
    buf = make_zip(
        document=doc, manifest=manifest, entries=[("media/m1.png", b"x" * 50)]
    )
    with open_archive(buf, expected_kind="course") as (zf, mani, document, media):
        preview = build_preview(mani, document, media)
    assert preview["kind"] == "course"
    assert preview["title"] == manifest["course"]["title"]
    assert preview["source"] == manifest["source"]
    assert preview["node_count"] == 1
    assert preview["element_count"] == 1
    assert preview["media_count"] == 1
    assert preview["media_total_bytes"] == 50
    assert preview["subjects_matched"] == ["Math"]
    assert preview["subjects_dropped"] == ["Unknown"]
    assert preview["has_html_elements"] is False
    assert preview["context_css_js"] is None
    assert preview["insertion_choices"] is None


def test_build_preview_subtree_context_and_insertion_choices():
    course = Course.objects.create(
        title="C2",
        slug="c2",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    ContentNode.objects.create(course=course, kind="chapter", title="Existing")
    manifest = make_manifest(kind="subtree", node={"title": "Root", "kind": "chapter"})
    doc = {
        "context": {
            "source_course_title": "S",
            "root_kind": "chapter",
            "required_kinds": ["chapter", "unit"],
            "html_css": "body{}",
            "html_js": "",
        },
        "nodes": [
            {
                "id": "n1",
                "parent": None,
                "kind": "chapter",
                "title": "R",
                "unit_type": None,
                "obligatory": True,
                "html_seed_js": "",
            }
        ],
        "elements": [
            {
                "id": "e1",
                "unit": "n1",
                "title": "",
                "type": "html",
                "data": {"html": "<p>x</p>"},
            }
        ],
        "media": [],
    }
    buf = make_zip(document=doc, manifest=manifest)
    with open_archive(buf, expected_kind="subtree") as (zf, mani, document, media):
        preview = build_preview(mani, document, media, target_course=course)
    assert preview["kind"] == "subtree"
    assert preview["title"] == "Root"
    assert preview["has_html_elements"] is True
    assert preview["context_css_js"] == {"html_css": "body{}", "html_js": ""}
    # root_kind="chapter" on a chapters-only course: top level only (an
    # existing chapter cannot legally contain another chapter).
    assert preview["insertion_choices"] == [{"value": "", "label": "Top level"}]
    assert preview["subjects_matched"] == []
    assert preview["subjects_dropped"] == []
