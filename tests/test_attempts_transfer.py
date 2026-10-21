"""Archive format 18: attempts at all three levels (spec 2026-10-20 §6)."""

import io

import pytest

from courses.models import ShortTextQuestionElement
from courses.quiz import effective_max_attempts
from courses.transfer.export import build_export
from courses.transfer.export import write_archive
from courses.transfer.export import write_archive_from
from courses.transfer.payloads import validate_element_data
from courses.transfer.schema import FORMAT_VERSION
from courses.transfer.schema import TransferError
from courses.transfer.schema import validate_document
from tests.factories import CourseFactory
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_quiz_unit
from tests.test_transfer_import import _import_zip
from tests.test_transfer_subtree import _import_subtree_zip
from tests.test_transfer_validation import base_course_doc
from tests.test_transfer_validation import node
from tests.test_transfer_validation import q_fields

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


def _short_text_el(eid, unit, **data_over):
    data = {**q_fields(), "accepted": "Paris", "case_sensitive": False}
    data.update(data_over)
    return {
        "id": eid,
        "unit": unit,
        "title": "",
        "type": "short_text",
        "data": data,
        "parent": None,
        "tab": "",
    }


def test_version_is_18():
    assert FORMAT_VERSION == 18


def test_round_trip_keeps_all_three_levels():
    course = CourseFactory(attempts_mode="limited", attempts_limit=3)
    unit = make_quiz_unit(course=course, attempts_mode="unlimited", attempts_limit=None)
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(stem="a", accepted="x", **attempts(5)),
    )
    add_element(unit, ShortTextQuestionElement.objects.create(stem="b", accepted="x"))
    buf = io.BytesIO()
    write_archive(course, None, buf)
    buf.seek(0)
    new = _import_zip(buf, UserFactory())
    assert (new.attempts_mode, new.attempts_limit) == ("limited", 3)
    nu = new.nodes.get(kind="unit")
    assert (nu.attempts_mode, nu.attempts_limit) == ("unlimited", None)
    got = sorted(
        (
            e.content_object.stem,
            e.content_object.attempts_mode,
            e.content_object.attempts_limit,
        )
        for e in nu.elements.all()
    )
    assert got == [("a", "limited", 5), ("b", "inherit", None)]


@pytest.mark.parametrize(
    "old,want",
    [
        (1, ("inherit", None)),
        (0, ("inherit", None)),
        (None, ("unlimited", None)),
        (5, ("limited", 5)),
    ],
)
def test_legacy_question_mapping(old, want):
    el = _short_text_el("e1", "u1")
    del el["data"]["attempts_mode"], el["data"]["attempts_limit"]
    el["data"]["max_attempts"] = old
    validate_element_data(el, {}, format_version=17)
    assert (el["data"]["attempts_mode"], el["data"]["attempts_limit"]) == want
    assert "max_attempts" not in el["data"]  # mutated in place for the commit


@pytest.mark.parametrize("bad", [True, "3", -1])
def test_hostile_legacy_value_is_a_transfer_error(bad):
    el = _short_text_el("e1", "u1")
    del el["data"]["attempts_mode"], el["data"]["attempts_limit"]
    el["data"]["max_attempts"] = bad
    with pytest.raises(TransferError):
        validate_element_data(el, {}, format_version=17)


def test_modern_version_none_is_not_remapped():
    el = _short_text_el("e1", "u1")
    el["data"]["max_attempts"] = 3  # a stray legacy key in a modern payload
    with pytest.raises(TransferError):
        validate_element_data(el, {}, format_version=None)


def test_legacy_nodes_and_course_get_defaults():
    doc = base_course_doc(nodes=[node("u1", unit_type="quiz")])
    validate_document(doc, kind="course", format_version=17)
    assert (doc["nodes"][0]["attempts_mode"], doc["nodes"][0]["attempts_limit"]) == (
        "inherit",
        None,
    )
    assert (doc["course"]["attempts_mode"], doc["course"]["attempts_limit"]) == (
        "limited",
        1,
    )


@pytest.mark.parametrize(
    "mode,limit",
    [
        ("bogus", None),
        ("limited", None),
        ("limited", 0),
        ("limited", 32768),
        ("limited", True),
        ("inherit", 3),
        ("unlimited", 3),
    ],
)
def test_invalid_question_pairs_rejected(mode, limit):
    el = _short_text_el("e1", "u1", attempts_mode=mode, attempts_limit=limit)
    with pytest.raises(TransferError):
        validate_element_data(el, {}, format_version=18)


def test_course_cannot_inherit():
    doc = base_course_doc()
    doc["course"].update(attempts_mode="inherit", attempts_limit=None)
    with pytest.raises(TransferError):
        validate_document(doc, kind="course", format_version=18)


def test_exporter_writes_null_for_non_limited():
    course = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    _manifest, document, _media, _problems = build_export(course)
    assert document["course"]["attempts_limit"] is None


def _unit_archive(unit, *, legacy):
    manifest, document, media, _problems = build_export(unit.course, unit)
    if legacy:  # rewrite to the v17 shape: the pair becomes max_attempts 1
        manifest["format_version"] = 17
        for el in document["elements"]:
            d = el["data"]
            if "attempts_mode" in d:
                del d["attempts_mode"], d["attempts_limit"]
                d["max_attempts"] = 1
        for nd in document["nodes"]:
            del nd["attempts_mode"], nd["attempts_limit"]
    buf = io.BytesIO()
    write_archive_from(manifest, document, media, buf)
    buf.seek(0)
    return buf


@pytest.mark.parametrize("legacy", [True, False])
def test_subtree_import_inherits_from_the_target_course(legacy):
    """P10/P11: an inheriting question (a v17 `max_attempts: 1`, or a modern
    inherit) resolves against the TARGET course, not the source."""
    src = CourseFactory(attempts_mode="limited", attempts_limit=4)
    unit = make_quiz_unit(course=src)
    add_element(unit, ShortTextQuestionElement.objects.create(stem="a", accepted="x"))
    target = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    grafted = _import_subtree_zip(
        _unit_archive(unit, legacy=legacy), target, None, UserFactory()
    )
    q = grafted.elements.get().content_object
    assert (q.attempts_mode, q.attempts_limit) == ("inherit", None)
    assert effective_max_attempts(q, grafted) is None  # target's unlimited


def test_subtree_import_keeps_own_modes():
    src = CourseFactory()
    unit = make_quiz_unit(course=src, attempts_mode="limited", attempts_limit=2)
    add_element(
        unit,
        ShortTextQuestionElement.objects.create(
            stem="own", accepted="x", **attempts(5)
        ),
    )
    add_element(unit, ShortTextQuestionElement.objects.create(stem="inh", accepted="x"))
    target = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    grafted = _import_subtree_zip(
        _unit_archive(unit, legacy=False), target, None, UserFactory()
    )
    assert (grafted.attempts_mode, grafted.attempts_limit) == ("limited", 2)
    by_stem = {e.content_object.stem: e.content_object for e in grafted.elements.all()}
    assert (by_stem["own"].attempts_mode, by_stem["own"].attempts_limit) == (
        "limited",
        5,
    )
    assert (
        effective_max_attempts(by_stem["inh"], grafted) == 2
    )  # the copied quiz's own 2
