"""Task 9: `published` joins the transfer archive format (§8/FORMAT_VERSION 10).

Covers: the round trip (both values), the v9-archive optional-key default
(every unit imports live), container normalization (imported containers land
unpublished, matching natively-created ones), and forcing a duplicated unit to
land as a draft rather than inheriting the source's live state (TR1-TR4,
KEEP1)."""

import io

import pytest
from django.urls import reverse

from courses.builder import duplicate_unit
from courses.models import ContentNode
from courses.transfer.export import build_export
from courses.transfer.export import write_archive_from
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.test_transfer_archive import make_manifest
from tests.test_transfer_archive import make_zip
from tests.test_transfer_validation import base_course_doc
from tests.test_transfer_validation import node

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # The import path writes real files through default_storage.
    settings.MEDIA_ROOT = tmp_path


def _round_trip(course, user, *, document_hook=None):
    """Export `course` and import it back as a brand-new course.

    import_course takes (zf, manifest, document, media_entries, user), not a
    file -- mirrors tests/test_link_transfer.py::_round_trip and
    tests/test_transfer_import.py::_import_zip.
    """
    manifest, document, assets, _problems = build_export(course)
    if document_hook:
        document_hook(document)
    buf = io.BytesIO()
    write_archive_from(manifest, document, assets, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course")
        return import_course(zf, mani, doc, media, user)


def test_tr1_published_round_trips_both_values():
    course = CourseFactory()
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Pub",
        published=True,
    )
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Draft",
        published=False,
    )

    imported = _round_trip(course, UserFactory())

    by_title = {n.title: n.published for n in imported.nodes.all()}
    assert by_title == {"Pub": True, "Draft": False}


def test_tr2_v9_archive_imports_every_unit_published():
    # Mutant: setdefault("published", False) -> everything imports hidden.
    # The source row is a DRAFT (published=False) precisely so the assertion
    # can't be satisfied by accident -- a v9 archive predates the concept of
    # drafts entirely, so what the DB row happened to hold is irrelevant; every
    # unit in it was live by construction.
    course = CourseFactory()
    ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="U",
        published=False,
    )

    def _strip_published(doc):
        # .pop(..., None): stays safe to run before Step 3 adds the key too.
        for nd in doc["nodes"]:
            nd.pop("published", None)

    imported = _round_trip(course, UserFactory(), document_hook=_strip_published)

    unit = imported.nodes.get(kind="unit")
    assert unit.published is True


def test_tr3_imported_containers_normalize_to_unpublished():
    doc = base_course_doc(
        nodes=[
            node("n1", kind="part", published=True),
            node("n2", kind="unit", parent="n1", published=True),
        ]
    )
    buf = make_zip(document=doc, manifest=make_manifest(format_version=FORMAT_VERSION))
    with open_archive(buf, expected_kind="course") as (zf, mani, parsed, media):
        validate_archive_document(zf, mani, parsed, media, kind="course")
        course = import_course(zf, mani, parsed, media, UserFactory())

    assert course.nodes.get(kind="part").published is False
    assert course.nodes.get(kind="unit").published is True


def test_container_bad_published_type_is_rejected():
    # Pins the ordering comment in schema.py: check_bool runs BEFORE the
    # container normalisation overwrites the value, so a hostile/malformed
    # "published": "yes" on a container is a validation error, not silently
    # coerced to False.
    from courses.transfer.schema import validate_document

    doc = base_course_doc(nodes=[node("n1", kind="part", published="yes")])
    with pytest.raises(TransferError):
        validate_document(doc, kind="course")


def test_tr4_duplicating_a_published_unit_yields_a_draft():
    # Mutant: let materialize_duplicate honour the payload like archive import
    # does -> the duplicate is live to students the instant it is created.
    course, unit = make_course_with_unit()
    unit.published = True
    unit.save(update_fields=["published"])

    copy = duplicate_unit(course, unit.pk, token=unit.updated.isoformat())

    assert copy.published is False
    assert ContentNode.objects.get(pk=copy.pk).published is False


def test_keep1_draft_units_export_and_appear_in_link_picker(client):
    # Mutant: filter inside export._ordered_nodes or _children_map -- a draft
    # unit silently dropped from an export, or hidden from the link picker, is
    # data loss / a broken authoring surface, not a publish-gate feature.
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    draft = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=None,
        title="Draft Unit",
        published=False,
    )

    _manifest, doc, _assets, _problems = build_export(course)
    assert any(n["title"] == "Draft Unit" for n in doc["nodes"])

    html = client.get(
        reverse("courses:manage_link_picker", kwargs={"slug": course.slug})
    ).content.decode()
    assert f'data-node="{draft.pk}"' in html
