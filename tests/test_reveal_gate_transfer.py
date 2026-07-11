"""Reveal-gate ('Show more') element course export/validate/import: registration
+ round-trip (Task 9). Mirrors tests/test_table_transfer.py and the tabs-nesting
round trip in tests/test_tabs_transfer.py."""

import io

import pytest

from courses.models import Element
from courses.models import RevealGateElement
from courses.models import TabsElement
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
from tests.factories import make_course_with_unit
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def test_reveal_gate_registered_in_all_three_registries():
    assert (
        "reveal_gate" in SERIALIZERS
        and "reveal_gate" in VALIDATORS
        and "reveal_gate" in BUILDERS
    )


def _round_trip(client, course, username):
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    owner = make_login(client, username)
    with open_archive(buf, expected_kind="course") as (zf, mani, doc, media):
        validate_archive_document(
            zf, mani, doc, media, kind="course", target_course=None
        )
        return import_course(zf, mani, doc, media, owner)


def test_reveal_gate_roundtrip(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    src = CourseFactory()
    unit = ContentNodeFactory(course=src, kind="unit", unit_type="lesson")
    add_element(unit, RevealGateElement.objects.create(label="Read more"))

    dest = _round_trip(client, src, "gate-importer")

    gates = [
        join.content_object
        for node in dest.nodes.all()
        for join in node.elements.all()
        if isinstance(join.content_object, RevealGateElement)
    ]
    assert len(gates) == 1
    assert gates[0].label == "Read more"


def test_reveal_gate_in_tab_roundtrip(client, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    src, unit = make_course_with_unit()
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=tabs)
    t1 = tabs.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=RevealGateElement.objects.create(label="Nested gate"),
        parent=join,
        tab_id=t1,
    )

    _round_trip(client, src, "gate-tab-importer")

    imported_tabs = TabsElement.objects.exclude(pk=tabs.pk).get()
    imported_join = imported_tabs.join_row()
    kids = list(imported_join.children.order_by("order", "pk"))
    assert len(kids) == 1
    gate = kids[0].content_object
    assert isinstance(gate, RevealGateElement)
    assert gate.label == "Nested gate"
    assert kids[0].tab_id == imported_tabs.data["tabs"][0]["id"]
