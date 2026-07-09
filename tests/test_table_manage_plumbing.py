import pytest
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse

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


def test_add_menu_exposes_table_card():
    html = render_to_string("courses/manage/editor/_add_menu.html")
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
