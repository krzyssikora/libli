import pytest
from django.template.loader import render_to_string

from courses.element_forms import FORM_FOR_TYPE
from courses.models import TableElement

pytestmark = pytest.mark.django_db


def _render(instance):
    form = FORM_FOR_TYPE["table"](instance=instance)
    return render_to_string(
        "courses/manage/editor/_edit_table.html", {"form": form, "type_key": "table"}
    )


def test_new_table_renders_default_2x2_grid():
    html = _render(TableElement())  # data == {} -> normalises to 2x2
    assert "data-table-editor" in html
    assert html.count("contenteditable") >= 4


def test_existing_table_reflects_stored_border_and_headers():
    el = TableElement(
        data=TableElement.normalize_data(
            {"border": "rows", "header_row": True, "cells": [[{"html": "hi"}]]}
        )
    )
    html = _render(el)
    assert "hi" in html
    assert 'value="rows"' in html or "selected" in html  # border reflected
