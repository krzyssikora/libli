import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

from courses.models import FillTableElement
from courses.models import TableElement
from courses.templatetags.courses_manage_extras import element_summary
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_element_summary_reports_dimensions():
    el = TableElement(
        data=TableElement.normalize_data({"cells": [[{}, {}, {}], [{}, {}, {}]]})
    )
    assert element_summary(el) == "2×3 table"


def _filltable(gate):
    # One answer cell, non-blank: normalize_data suppresses `gate` on a grid that
    # cannot satisfy it, so a static-only grid would silently test nothing.
    return FillTableElement(
        data=FillTableElement.normalize_data(
            {"cells": [[{"kind": "answer", "answer": "4"}]], "gate": gate}
        )
    )


def test_ungated_filltable_summary_is_byte_identical_to_todays():
    """The marker must not disturb the row every existing fill-table renders."""
    assert element_summary(_filltable(False)) == "1×1 fill-in table, 1 answer(s)"


def test_a_gated_filltable_summary_names_the_gate():
    # Without this the builder tree shows the same "1×1 fill-in table, 1 answer(s)"
    # for a gating table as for an inert one, and the gate changes what the REST
    # of the section does -- a larger blast radius than tabs' carousel display,
    # which already carries a marker for exactly this reason.
    gated = element_summary(_filltable(True))
    assert gated != element_summary(_filltable(False))
    assert "gate" in gated.lower()


def test_the_gate_marker_translates():
    from django.utils import translation

    with translation.override("pl"):
        gated = element_summary(_filltable(True))
        # "bramka" is the term the help pages already use for the reveal-gate
        # families (interactive-elements.pl.md), not a new coinage.
        assert "bramka" in gated.lower()
        # The base summary must still resolve under pl -- the marker wraps a lazy
        # proxy, and a broken wrap would swallow the dimensions.
        assert "1×1" in gated


def test_add_menu_exposes_table_card():
    # Both keys are INTEGERS -- see the matching note in tests/test_gallery_manage.py.
    html = render_to_string(
        "courses/manage/editor/_add_menu.html", {"depth": 0, "max_nest_depth": 4}
    )
    assert 'data-add-type="table"' in html
    assert "#el-table" in html


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_element_add_accepts_table_type():
    # element_add fully renders the open-form host, which auto-includes
    # courses/manage/editor/_edit_table.html (Task 6, not yet built here) —
    # so a plain `client` fixture would surface that as a raised
    # TemplateDoesNotExist rather than a response. What THIS task owns is the
    # dispatch allow-tuple: "table" must clear the "bad type" 400 gate.
    # raise_request_exception=False turns any downstream error into an
    # ordinary 500 response so we can assert on status code alone.
    client = Client(raise_request_exception=False)
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "table", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code != 400


def test_element_save_accepts_table_type(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "table",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "data": "",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code != 400
