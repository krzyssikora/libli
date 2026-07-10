"""Gallery element course export/import round-trip: registration + shape
survival across the archive boundary (Task 9). Modeled on
tests/test_table_transfer.py's real export->zip->import path; there is no
existing `export_import_helper` fixture in this codebase, so this file defines
a small local one with only the gallery-specific construction needed here."""

import io

import pytest

from courses.models import GalleryElement
from courses.transfer.export import SERIALIZERS
from courses.transfer.export import write_archive
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.payloads import VALIDATORS
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_image_asset
from tests.factories import make_login

pytestmark = pytest.mark.django_db


class _ExportImportHelper:
    """Real export (write_archive) -> zip -> real import (import_course) path,
    plus gallery-specific course/element construction."""

    def __init__(self, client):
        self.client = client

    def make_course_with_gallery(self, desc_pos="below", descs=None):
        descs = list(descs) if descs is not None else ["a", "b"]
        course = CourseFactory()
        unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
        images = [
            {"media": make_image_asset(course, filename=f"img{i}.png").pk, "desc": d}
            for i, d in enumerate(descs)
        ]
        el = GalleryElement(data={"desc_pos": desc_pos, "images": images})
        el.full_clean()
        el.save()
        add_element(unit, el)
        return course

    def round_trip(self, src_course):
        buf = io.BytesIO()
        write_archive(src_course, None, buf)
        buf.seek(0)
        owner = make_login(self.client, "gallery-importer")
        with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
            validate_archive_document(
                zf, mani, doc, media, kind="course", target_course=None
            )
            return import_course(zf, mani, doc, media, owner)

    def only_gallery(self, course):
        galleries = [
            join.content_object
            for node in course.nodes.all()
            for join in node.elements.all()
            if isinstance(join.content_object, GalleryElement)
        ]
        assert len(galleries) == 1
        return galleries[0]

    def round_trip_with_missing_image_gallery(self):
        """A 2-image gallery whose first image's underlying file bytes are
        missing (mirrors tests/test_transfer_export.py's
        _delete_asset_file trick): export turns that asset into a placeholder
        (never dropped, unlike a video), so the gallery element survives with
        both image slots intact."""
        course = CourseFactory()
        unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
        missing = make_image_asset(course, filename="missing.png")
        present = make_image_asset(course, filename="present.png")
        missing.file.storage.delete(missing.file.name)  # simulate lost bytes
        el = GalleryElement(
            data={
                "desc_pos": "below",
                "images": [
                    {"media": missing.pk, "desc": "gone"},
                    {"media": present.pk, "desc": "here"},
                ],
            }
        )
        el.full_clean()
        el.save()
        add_element(unit, el)
        return self.round_trip(course)


@pytest.fixture
def export_import_helper(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return _ExportImportHelper(client)


def test_registries_lockstep():
    assert "gallery" in SERIALIZERS
    assert "gallery" in VALIDATORS
    assert "gallery" in BUILDERS


def test_round_trip_preserves_order_desc_pos_and_descs(export_import_helper):
    """Build a 2-image gallery, export the course, import into a fresh course,
    assert the gallery survived with order, descriptions, and desc_pos."""
    src = export_import_helper.make_course_with_gallery(
        desc_pos="above", descs=["<b>one</b>", r"two \(x\)"]
    )
    dst = export_import_helper.round_trip(src)
    gal = export_import_helper.only_gallery(dst)
    assert gal.data["desc_pos"] == "above"
    assert [i["desc"] for i in gal.data["images"]] == ["<b>one</b>", r"two \(x\)"]
    assert len(gal.data["images"]) == 2


def test_missing_image_round_trips_to_placeholder(export_import_helper):
    """An exported gallery whose image bytes are missing imports with a
    placeholder asset (element kept, not dropped)."""
    dst = export_import_helper.round_trip_with_missing_image_gallery()
    gal = export_import_helper.only_gallery(dst)
    assert len(gal.data["images"]) == 2  # both slots kept
