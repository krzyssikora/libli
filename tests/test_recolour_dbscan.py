"""Candidate scoping, the fail-closed multi-owner guard, and the read-back."""

import pytest

from courses.models import ContentNode
from courses.models import Element
from courses.models import TableElement
from courses.models import TextElement
from courses.recolour.dbscan import MultiOwnerError
from courses.recolour.dbscan import ReadBackError
from courses.recolour.dbscan import apply_matches
from courses.recolour.dbscan import excluded_node_ids
from courses.recolour.dbscan import find_matches
from tests.factories import CourseFactory

pytestmark = pytest.mark.django_db


def _unit(course, part_title="P"):
    part = ContentNode.objects.create(
        course=course, parent=None, order=0, kind="part", title=part_title
    )
    ch = ContentNode.objects.create(
        course=course, parent=part, order=0, kind="chapter", title="C"
    )
    unit = ContentNode.objects.create(
        course=course, parent=ch, order=0, kind="unit", title="U", unit_type="lesson"
    )
    return part, unit


def _text(unit, body):
    el = TextElement.objects.create(body=body)
    Element.objects.create(unit=unit, content_object=el)
    return el


def test_a_matching_body_is_found():
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie")
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    assert len(matches) == 1
    assert matches[0].field == "body"


def test_a_non_matching_body_is_not_found():
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie (edited)")
    assert find_matches(course, {"założenie": "x"}, set()) == []


def test_another_courses_content_is_out_of_scope():
    other = CourseFactory(slug="other")
    _part, unit = _unit(other)
    _text(unit, "założenie")
    mine = CourseFactory(slug="mine")
    assert find_matches(mine, {"założenie": "x"}, set()) == []


def test_an_excluded_subtree_is_filtered_out():
    course = CourseFactory()
    part, unit = _unit(course)
    _text(unit, "założenie")
    excluded = excluded_node_ids(course, [part.pk])
    assert unit.pk in excluded  # the DESCENDANT walk is the whole correctness
    assert find_matches(course, {"założenie": "x"}, excluded) == []


def test_an_orphaned_row_with_no_element_is_never_a_candidate():
    # .exclude() on a reverse relation KEEPS rows with no Element at all; the
    # course-scoped base filter is what removes them.
    course = CourseFactory()
    _unit(course)
    TextElement.objects.create(body="założenie")
    assert find_matches(course, {"założenie": "x"}, set()) == []


def test_a_row_owned_by_two_elements_fails_closed():
    course = CourseFactory()
    _part, unit = _unit(course)
    el = _text(unit, "założenie")
    Element.objects.create(unit=unit, content_object=el)  # a second owner
    with pytest.raises(MultiOwnerError):
        find_matches(course, {"założenie": "x"}, set())


def test_a_table_matches_per_cell_and_rewrites_partially():
    course = CourseFactory()
    _part, unit = _unit(course)
    tbl = TableElement.objects.create(
        data=TableElement.normalize_data(
            {"cells": [[{"html": "a"}, {"html": "b"}], [{"html": "c"}, {"html": "d"}]]}
        )
    )
    Element.objects.create(unit=unit, content_object=tbl)
    matches = find_matches(
        course,
        {"a": '<span class="tc-red">a</span>', "d": '<span class="tc-blue">d</span>'},
        set(),
    )
    assert sorted(m.cell for m in matches) == [(0, 0), (1, 1)]
    assert apply_matches(matches) == 1  # one CHANGED FIELD, two cells
    tbl.refresh_from_db()
    cells = tbl.data["cells"]
    assert cells[0][0]["html"] == '<span class="tc-red">a</span>'
    assert cells[1][1]["html"] == '<span class="tc-blue">d</span>'
    assert cells[0][1]["html"] == "b"  # untouched
    assert cells[1][0]["html"] == "c"


def test_a_filltable_answer_cell_is_never_matched():
    # FillTableElement._sanitized_data re-sanitises cell["html"] ONLY for cells whose
    # kind is neither `answer` nor `image` (models.py:1120-1134), so a match landing on
    # an answer cell would be written UNSANITISED and the read-back would not notice --
    # it compares against what we wrote. The corpus produces zero fill-table matches,
    # so without this test the guard would ship having never executed.
    #
    # The row is built from RAW data, deliberately NOT through normalize_data. MEASURED:
    # normalize_data DROPS the html key from an answer cell (it emits `answer` instead),
    # so a normalised fixture has no html for find_matches to see and the test would
    # pass with the guard deleted -- vacuous. save() -> _sanitized_data does NOT delete
    # a stray html key, so this shape is what a legacy or hand-edited row looks like,
    # and it is the shape the guard exists for.
    from courses.models import FillTableElement

    course = CourseFactory()
    _part, unit = _unit(course)
    ft = FillTableElement.objects.create(
        data={
            "cells": [
                [
                    {"kind": "static", "html": "a", "halign": "left"},
                    {"kind": "answer", "html": "a", "answer": "a"},
                ]
            ]
        }
    )
    Element.objects.create(unit=unit, content_object=ft)
    ft.refresh_from_db()
    # Precondition: the answer cell really does still carry an html key, or the test
    # below proves nothing.
    assert ft.data["cells"][0][1]["html"] == "a"
    matches = find_matches(course, {"a": '<span class="tc-red">a</span>'}, set())
    ft_matches = [m for m in matches if m.model is FillTableElement]
    assert [m.cell for m in ft_matches] == [(0, 0)]  # the STATIC cell only


def test_apply_reads_every_rewritten_field_back():
    course = CourseFactory()
    _part, unit = _unit(course)
    el = _text(unit, "założenie")
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    assert apply_matches(matches) == 1
    el.refresh_from_db()
    assert el.body == '<span class="tc-red">założenie</span>'


def test_titles_are_never_read_or_written():
    course = CourseFactory()
    part, unit = _unit(course)
    _text(unit, "założenie")
    before = dict(ContentNode.objects.values_list("pk", "title"))
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    apply_matches(matches)
    assert dict(ContentNode.objects.values_list("pk", "title")) == before


def test_a_field_the_write_path_alters_raises_ReadBackError(monkeypatch):
    # The read-back is the ONLY safety net for the three gate stems, whose save()
    # explicitly declines to touch `stem` (models.py:776-779). Exercising it only
    # inside a falsification step would leave the committed suite with no guard on
    # the one check standing between a mangled write and the database.
    #
    # The mangling is "X", NOT an HTML comment: TextElement.save runs sanitize_html
    # and nh3 defaults to strip_comments=True, so a comment is erased before the row
    # is written, the read-back matches, and the test can never fire. MEASURED.
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie")
    original = TextElement.save

    def _mangling_save(self, *a, **kw):
        self.body = self.body + "X"
        return original(self, *a, **kw)

    monkeypatch.setattr(TextElement, "save", _mangling_save)
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    with pytest.raises(ReadBackError):
        apply_matches(matches)


def test_a_read_back_failure_inside_a_transaction_leaves_the_row_untouched(monkeypatch):
    # apply_matches is called inside transaction.atomic() by the command, so the
    # raise must roll the write back rather than leave a half-applied course.
    from django.db import transaction

    course = CourseFactory()
    _part, unit = _unit(course)
    el = _text(unit, "założenie")
    original = TextElement.save

    def _mangling_save(self, *a, **kw):
        self.body = self.body + "X"
        return original(self, *a, **kw)

    monkeypatch.setattr(TextElement, "save", _mangling_save)
    matches = find_matches(
        course, {"założenie": '<span class="tc-red">założenie</span>'}, set()
    )
    with pytest.raises(ReadBackError), transaction.atomic():
        apply_matches(matches)
    el.refresh_from_db()
    assert el.body == "założenie"


def test_a_second_apply_matches_nothing():
    course = CourseFactory()
    _part, unit = _unit(course)
    _text(unit, "założenie")
    entries = {"założenie": '<span class="tc-red">założenie</span>'}
    apply_matches(find_matches(course, entries, set()))
    assert find_matches(course, entries, set()) == []
