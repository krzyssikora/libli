"""D5 says colour reaches production inside a #68 export bundle, with no prod-side
migration. That is the single load-bearing claim for how this work ships, and nothing
tested it. Colour rides inside strings that already round-trip, so this should pass on
the first run — which is exactly why it must exist: if it ever stops passing, the
delivery plan is broken.

Drives the REAL transfer engine through the same sequence tests/test_transfer_import.py
uses. The public API is write_archive(course, node, fileobj) into a file object, then
open_archive(...) as a context manager yielding (zf, mani, doc, media) — there is no
export_course()/import_course(path) pair.
"""

import io

import pytest

from courses.models import Element
from courses.models import TableElement
from courses.models import TextElement
from courses.transfer.export import write_archive
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from tests.factories import add_element
from tests.factories import make_course_with_unit

pytestmark = pytest.mark.django_db

BODY = '<p>plain <span class="tc-red">red</span> tail</p>'
CELL = '<b class="tc-blue">cell</b>'


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    """The import path writes real files through default_storage. Copied from
    tests/test_transfer_import.py:48 — without it the import writes into the repo."""
    settings.MEDIA_ROOT = str(tmp_path / "media")
    yield


def test_colour_survives_export_and_import():
    course, unit = make_course_with_unit()
    user = course.owner
    body = TextElement.objects.create(body=BODY)
    table = TableElement.objects.create(
        data={
            "header_row": False,
            "header_col": False,
            "border": "none",
            "cells": [[{"html": CELL, "halign": "left", "valign": "top"}]],
        }
    )
    add_element(unit, body)
    add_element(unit, table)

    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(zf, mani, doc, media, kind="course")
        imported = import_course(zf, mani, doc, media, user)

    bodies = [
        e.content_object.body
        for e in Element.objects.filter(unit__course=imported)
        if isinstance(e.content_object, TextElement)
    ]
    assert bodies == [BODY], "tc-* must survive export/import byte-identically"

    tables = [
        e.content_object.data
        for e in Element.objects.filter(unit__course=imported)
        if isinstance(e.content_object, TableElement)
    ]
    assert tables[0]["cells"][0][0]["html"] == CELL
