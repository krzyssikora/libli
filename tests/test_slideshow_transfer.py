"""Export/import round-trip: a slide break must survive a full-course transfer."""

import io

import pytest

from courses.models import SlideBreakElement
from courses.transfer.export import write_archive
from courses.transfer.importer import import_course
from courses.transfer.importer import open_archive
from courses.transfer.importer import validate_archive_document
from tests.factories import CourseFactory
from tests.factories import make_login
from tests.factories import seed_slideshow_unit

pytestmark = pytest.mark.django_db


def test_export_import_preserves_slide_break(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    seed_slideshow_unit(src, "lesson", layout=["t", "brk", "t"])

    buf = io.BytesIO()
    write_archive(src, None, buf)
    buf.seek(0)

    owner = make_login(client, "importer")
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="course", target_course=None
        )
        dest = import_course(zf, mani, doc, media, owner)

    assert any(
        isinstance(join.content_object, SlideBreakElement)
        for node in dest.nodes.all()
        for join in node.elements.all()
    )
