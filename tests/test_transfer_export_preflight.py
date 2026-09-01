"""Export-side cap pre-flight.

The caps are enforced on IMPORT, which means an oversize archive is diagnosed
only after it has been built, downloaded and uploaded again. `build_export`
already knows every count before it writes a byte, so it reports them here
against the LOCAL caps.

The reporting is advisory and must stay that way: the caps that actually decide
belong to the IMPORTING deployment, which the exporting instance cannot see. An
archive over this instance's caps may be perfectly importable elsewhere, so
nothing in this module may cause an export to be refused.
"""

import pytest
from django.test import override_settings

from courses.transfer.export import build_export
from tests.factories import ElementFactory
from tests.factories import make_course_with_unit


def _measure(report, key):
    for m in report["limits"]:
        if m["key"] == key:
            return m
    raise AssertionError(f"no {key!r} measure in {[m['key'] for m in report['limits']]}")


@pytest.mark.django_db
def test_build_export_reports_every_cap_it_knows_about():
    """One measure per cap the archive can trip, always -- not only on breach.

    Reporting every measure unconditionally is what lets the CLI print the
    per-part table an operator plans a migration from. A report that listed only
    breaches would show an empty table for a healthy course, which is the case
    the operator most wants numbers for.
    """
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)

    report = {}
    build_export(course, report=report)

    assert {m["key"] for m in report["limits"]} == {
        "nodes",
        "elements",
        "media_entries",
        "course_json_bytes",
        "archive_bytes",
    }


@pytest.mark.django_db
def test_a_course_inside_every_cap_reports_nothing_over():
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)

    report = {}
    build_export(course, report=report)

    assert [m["key"] for m in report["limits"] if m["over"]] == []


@pytest.mark.django_db
@override_settings(TRANSFER_MAX_ELEMENTS=1)
def test_an_element_count_over_the_cap_is_reported_over():
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)
    ElementFactory(unit=unit)

    report = {}
    build_export(course, report=report)

    m = _measure(report, "elements")
    assert m["value"] == 2
    assert m["cap"] == 1
    assert m["over"] is True


@pytest.mark.django_db
@override_settings(TRANSFER_MAX_ELEMENTS=2)
def test_a_count_exactly_at_the_cap_is_not_over():
    """The import check is `len(elements) > cap`, so equality passes there. An
    off-by-one here would warn about an archive that imports perfectly.
    """
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)
    ElementFactory(unit=unit)

    report = {}
    build_export(course, report=report)

    assert _measure(report, "elements")["value"] == 2
    assert _measure(report, "elements")["over"] is False


@pytest.mark.django_db
def test_course_json_bytes_is_measured_not_estimated():
    """The document is serialised to measure it, because this is the one count
    cap whose value cannot be derived from a length. A guess here would be the
    only measure an operator could not act on.
    """
    import json

    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)

    report = {}
    _manifest, document, _media, _problems = build_export(course, report=report)

    exact = len(json.dumps(document, ensure_ascii=False).encode("utf-8"))
    assert _measure(report, "course_json_bytes")["value"] == exact


@pytest.mark.django_db
@override_settings(
    TRANSFER_MAX_COMPRESSED_BYTES=500,
    TRANSFER_MAX_UNCOMPRESSED_BYTES=100,
)
def test_archive_bytes_is_capped_by_whichever_byte_limit_binds_first():
    """Both byte caps apply to the same archive, so the one that binds is the
    SMALLER. Reporting against the compressed cap alone would clear an archive
    that the uncompressed cap rejects -- and on this payload class (mp4/png,
    already compressed) the two numbers are within a few percent of each other,
    so the smaller one is the honest ceiling.
    """
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)

    report = {}
    build_export(course, report=report)

    assert _measure(report, "archive_bytes")["cap"] == 100


@pytest.mark.django_db
@override_settings(TRANSFER_MAX_ELEMENTS=1)
def test_being_over_a_cap_never_refuses_the_export():
    """The importing deployment's caps are the ones that decide and are
    unknowable from here, so an over-cap measure is a diagnosis, never a
    rejection. If this ever raises, an operator can no longer produce an archive
    for a deployment that legitimately raised its own limits.
    """
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)
    ElementFactory(unit=unit)

    report = {}
    manifest, document, _media, problems = build_export(course, report=report)

    assert len(document["elements"]) == 2
    assert manifest["kind"] == "course"
    # And it must not leak into `problems`: migrate_course_content aborts a
    # whole bundle export on any problem, and a cap finding must never do that.
    assert problems == []


@pytest.mark.django_db
def test_limits_are_reported_for_a_subtree_export_too():
    """A node export is the path a big course actually travels, so it is the
    path whose numbers matter most.
    """
    course, unit = make_course_with_unit()
    ElementFactory(unit=unit)

    report = {}
    build_export(course, node=unit, report=report)

    assert _measure(report, "elements")["value"] == 1
