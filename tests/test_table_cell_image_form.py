"""Form-layer tests for table cell images: course scoping and re-render."""

import json

import pytest

from courses.element_forms import TableElementForm
from courses.models import MediaAsset
from courses.models import TableElement


def _payload(media_pk, **cell):
    return {"data": json.dumps({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image", "media": media_pk,
                    "alt": "", "size": "medium", **cell}]],
    })}


@pytest.fixture
def other_course_image(db, tmp_path, settings):
    """An image asset belonging to a DIFFERENT course — the crafted-POST case."""
    from tests.factories import make_course
    from tests.factories import make_image_asset

    settings.MEDIA_ROOT = str(tmp_path)
    return make_image_asset(make_course(), filename="foreign.png")


@pytest.mark.django_db
def test_foreign_course_pk_is_rejected(course_with_image, other_course_image):
    course, _asset = course_with_image
    form = TableElementForm(data=_payload(other_course_image.pk), course=course)
    assert not form.is_valid()
    assert "not an image in this course" in str(form.errors)


@pytest.mark.django_db
def test_in_course_non_image_asset_is_rejected(course_with_image):
    course, _asset = course_with_image
    video = MediaAsset.objects.create(course=course, kind="video")
    form = TableElementForm(data=_payload(video.pk), course=course)
    assert not form.is_valid()


@pytest.mark.django_db
def test_in_course_image_is_accepted(course_with_image):
    course, asset = course_with_image
    form = TableElementForm(data=_payload(asset.pk), course=course)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["data"]["cells"][0][0]["media"] == asset.pk


@pytest.mark.django_db
def test_image_cell_with_no_media_never_500s(course_with_image):
    """clean_data must normalize BEFORE scoping.

    The fill table's `{c["media"] for ...}` expression is only safe because it runs over
    the NORMALIZED grid (FillTableElementForm.clean_data already binds nd first);
    copying it above the normalise, where TableElementForm still has raw `rows`, would
    KeyError on a crafted POST and 500 the save.
    """
    course, _asset = course_with_image
    payload = {"data": json.dumps({
        "header_row": False, "header_col": False, "border": "grid",
        "cells": [[{"kind": "image"}]],
    })}
    form = TableElementForm(data=payload, course=course)
    form.is_valid()  # must not raise


@pytest.mark.django_db
def test_resolved_grid_cells_resolves_a_rejected_save(course_with_image):
    course, asset = course_with_image
    # colspan 99 is out of range -> the form rejects, and the editor re-renders
    # the SUBMITTED grid through resolved_grid_cells.
    form = TableElementForm(data=_payload(asset.pk, colspan=99), course=course)
    assert not form.is_valid()
    cell = form.resolved_grid_cells[0][0]
    assert cell["media"] == asset


@pytest.mark.django_db
def test_resolved_grid_cells_scopes_by_course(course_with_image, other_course_image):
    """A foreign pk resolves to nothing and takes the fallback, NOT a foreign URL.

    Do NOT assert exact cell equality here, and do NOT invalidate via colspan: the
    span is what makes the form invalid, _grid_data then normalizes and CLAMPS it to
    MAX_COLS=20, and Task 2's resolver deliberately CARRIES spans onto the fallback —
    so the real cell is {..., "colspan": 20} and an exact match fails.
    """
    course, _asset = course_with_image
    form = TableElementForm(data=_payload(other_course_image.pk, colspan=99),
                            course=course)
    assert not form.is_valid()
    cell = form.resolved_grid_cells[0][0]
    assert cell["html"] == ""
    assert "kind" not in cell
    # clamped by normalize_data, carried by the resolver
    assert cell["colspan"] == 20


def test_form_exposes_the_ordered_size_choices():
    assert TableElementForm().cell_image_sizes == TableElement.CellImageSize.choices


def test_builder_threads_course_for_table():
    """Without "table" in the tuple, self.course stays None on the SAVE path, the
    guard `if img_ids and self.course is not None` becomes a check that NEVER fires,
    and a crafted POST can attach a foreign course's asset with every test green."""
    from courses.builder import COURSE_SCOPED_TYPE_KEYS

    assert "table" in COURSE_SCOPED_TYPE_KEYS
    # filltable is deliberately absent from views_manage's two tuples; table
    # follows it, so this constant is the ONLY place "table" is added.
    assert "filltable" in COURSE_SCOPED_TYPE_KEYS
