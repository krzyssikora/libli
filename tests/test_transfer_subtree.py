# tests/test_transfer_subtree.py
"""Task 10: import_subtree — grafting an exported content subtree into an
existing target course at a chosen insertion point (or top level)."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import ImageElement
from courses.models import MediaAsset
from courses.models import TextElement
from courses.transfer.export import build_export
from courses.transfer.export import write_archive
from courses.transfer.importer import _create_nodes
from courses.transfer.importer import import_subtree
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import TransferError
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # The import path writes real files through default_storage. Without this
    # redirect, tests would pollute the repo's media/ dir and the orphan-file
    # assertions would scan pre-existing files instead of a clean sandbox.
    settings.MEDIA_ROOT = tmp_path


def _attach_text_and_image(unit, course, filename="pic.png"):
    asset = MediaAsset.objects.create(
        course=course,
        kind="image",
        file=SimpleUploadedFile(filename, b"\x89PNG fake image bytes"),
        original_filename=filename,
        name="Picture",
    )
    Element.objects.create(
        unit=unit,
        title="Text",
        content_object=TextElement.objects.create(body="<p>hi</p>"),
    )
    Element.objects.create(
        unit=unit,
        title="",
        content_object=ImageElement.objects.create(
            media=asset, alt="alt", figcaption="cap"
        ),
    )
    return asset


def _mk_full_source_with_chapter():
    """Full-depth course A: part -> chapter -> section -> unit, unit has a
    text + an image element. Returns (course, chapter_node)."""
    course = Course.objects.create(
        title="Source A",
        slug="source-a",
        uses_parts=True,
        uses_chapters=True,
        uses_sections=True,
    )
    part = ContentNode.objects.create(course=course, kind="part", title="P1")
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", title="Chapter Root", parent=part
    )
    section = ContentNode.objects.create(
        course=course, kind="section", title="Sect", parent=chapter
    )
    unit = ContentNode.objects.create(
        course=course,
        kind="unit",
        title="Unit",
        parent=section,
        unit_type="lesson",
    )
    _attach_text_and_image(unit, course)
    return course, chapter


def _mk_chapters_only_source_with_chapter():
    """Chapters-only course: chapter -> unit (no section), unit has a text +
    an image element. Returns (course, chapter_node)."""
    course = Course.objects.create(
        title="Source B",
        slug="source-b",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    chapter = ContentNode.objects.create(
        course=course, kind="chapter", title="Chap Root"
    )
    unit = ContentNode.objects.create(
        course=course,
        kind="unit",
        title="Unit",
        parent=chapter,
        unit_type="lesson",
    )
    _attach_text_and_image(unit, course, filename="pic2.png")
    return course, chapter


def _archive_of(course, node):
    buf = io.BytesIO()
    write_archive(course, node, buf)
    buf.seek(0)
    return buf


def _assert_subtree_graphs_equal(
    source_course, source_root, target_course, target_root
):
    _m1, src_doc, src_media_items = build_export(source_course, node=source_root)
    _m2, tgt_doc, tgt_media_items = build_export(target_course, node=target_root)

    def node_fields(n):
        return {
            k: n[k]
            for k in ("kind", "title", "unit_type", "obligatory", "html_seed_js")
        }

    assert [node_fields(n) for n in src_doc["nodes"]] == [
        node_fields(n) for n in tgt_doc["nodes"]
    ]
    assert [(e["type"], e["title"]) for e in src_doc["elements"]] == [
        (e["type"], e["title"]) for e in tgt_doc["elements"]
    ]
    for se, te in zip(src_doc["elements"], tgt_doc["elements"], strict=True):
        assert se["data"] == te["data"]

    assert len(src_doc["media"]) == len(tgt_doc["media"])
    src_by_id = dict(src_media_items)
    tgt_by_id = dict(tgt_media_items)
    for sm, tm in zip(src_doc["media"], tgt_doc["media"], strict=True):
        assert sm["kind"] == tm["kind"]
        assert sm["name"] == tm["name"]
        assert sm["original_filename"] == tm["original_filename"]
        src_asset = src_by_id[sm["id"]]
        tgt_asset = tgt_by_id[tm["id"]]
        with src_asset.file.open("rb") as sf, tgt_asset.file.open("rb") as tf:
            assert sf.read() == tf.read()


def _import_subtree_zip(buf, target, insertion_node, user):
    with open_archive(buf, expected_kind="subtree") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="subtree", target_course=target
        )
        return import_subtree(zf, mani, doc, media, target, insertion_node, user)


# --- round trip: graft under an existing node, appended after siblings -------


def test_subtree_grafted_under_insertion_node_appends_after_siblings():
    source, chapter = _mk_full_source_with_chapter()
    buf = _archive_of(source, chapter)

    target = Course.objects.create(
        title="Target A",
        slug="target-a",
        uses_parts=True,
        uses_chapters=True,
        uses_sections=True,
        html_css="body{color:blue}",
        html_js="console.log('sentinel')",
    )
    insertion_part = ContentNode.objects.create(
        course=target, kind="part", title="Existing Part"
    )
    existing_sibling = ContentNode.objects.create(
        course=target, kind="chapter", title="Existing Chapter", parent=insertion_part
    )
    importer = UserFactory()

    grafted = _import_subtree_zip(buf, target, insertion_part, importer)

    # Parent is the chosen insertion point, not null and not a stale archive id.
    assert grafted.parent_id == insertion_part.pk
    assert grafted.course_id == target.pk

    # Ordering: appended AFTER the pre-existing sibling under the same parent.
    siblings = list(
        ContentNode.objects.filter(course=target, parent=insertion_part).order_by(
            "order", "pk"
        )
    )
    assert [n.pk for n in siblings] == [existing_sibling.pk, grafted.pk]

    _assert_subtree_graphs_equal(source, chapter, target, grafted)

    asset = target.media_assets.get(original_filename="pic.png")
    assert asset.uploaded_by == importer

    # §2.2: context CSS/JS is never applied to the target course.
    target.refresh_from_db()
    assert target.html_css == "body{color:blue}"
    assert target.html_js == "console.log('sentinel')"


# --- round trip: top-level import (insertion_node=None) ----------------------


def test_subtree_grafted_at_top_level_when_insertion_node_is_none():
    source, chapter = _mk_chapters_only_source_with_chapter()
    buf = _archive_of(source, chapter)

    target = Course.objects.create(
        title="Target B",
        slug="target-b",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )
    existing_top = ContentNode.objects.create(
        course=target, kind="chapter", title="Existing Top Chapter"
    )
    importer = UserFactory()

    grafted = _import_subtree_zip(buf, target, None, importer)

    assert grafted.parent_id is None
    assert grafted.course_id == target.pk

    siblings = list(
        ContentNode.objects.filter(course=target, parent=None).order_by("order", "pk")
    )
    assert [n.pk for n in siblings] == [existing_top.pk, grafted.pk]

    _assert_subtree_graphs_equal(source, chapter, target, grafted)

    asset = target.media_assets.get(original_filename="pic2.png")
    assert asset.uploaded_by == importer


# --- depth-flag rejection: caught at validate_archive_document, not commit ---


def test_subtree_depth_flag_rejection_names_the_offending_kind():
    source = Course.objects.create(
        title="Parts Source",
        slug="parts-source",
        uses_parts=True,
        uses_chapters=True,
        uses_sections=True,
    )
    part = ContentNode.objects.create(course=source, kind="part", title="Lone Part")
    buf = _archive_of(source, part)

    target = Course.objects.create(
        title="Chapters Only Target",
        slug="chapters-only-target",
        uses_parts=False,
        uses_chapters=True,
        uses_sections=False,
    )

    with open_archive(buf, expected_kind="subtree") as (zf, mani, doc, media):
        with pytest.raises(TransferError) as excinfo:
            validate_archive_document(
                zf, mani, doc, media, kind="subtree", target_course=target
            )
    assert "part" in str(excinfo.value).lower()


# --- rollback: same all-or-nothing guarantee as import_course ----------------


def test_subtree_import_failure_rolls_back_and_cleans_up(monkeypatch):
    source, chapter = _mk_full_source_with_chapter()
    buf = _archive_of(source, chapter)

    target = Course.objects.create(
        title="Target C",
        slug="target-c",
        uses_parts=True,
        uses_chapters=True,
        uses_sections=True,
    )
    insertion_part = ContentNode.objects.create(
        course=target, kind="part", title="Existing Part"
    )
    importer = UserFactory()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("courses.transfer.importer._create_nodes", _boom)

    with open_archive(buf, expected_kind="subtree") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="subtree", target_course=target
        )
        with pytest.raises(TransferError):
            import_subtree(zf, mani, doc, media, target, insertion_part, importer)

    # No partial nodes grafted under the insertion point.
    assert not ContentNode.objects.filter(course=target, parent=insertion_part).exists()
    # No orphan MediaAsset row survives in the target's library.
    assert target.media_assets.count() == 0


def test_create_nodes_still_importable_directly():
    # Sanity: _create_nodes is a real, still-imported symbol (guards against a
    # rename in Task 9 breaking this test file's monkeypatch target silently).
    assert callable(_create_nodes)
