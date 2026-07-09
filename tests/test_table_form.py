import json

import pytest

from courses.element_forms import FORM_FOR_TYPE

pytestmark = pytest.mark.django_db

TableForm = FORM_FOR_TYPE["table"]


def _payload(rows=1, cols=1):
    cells = [
        [{"html": "x", "halign": "left", "valign": "top"} for _ in range(cols)]
        for _ in range(rows)
    ]
    return {"header_row": False, "header_col": False, "border": "grid", "cells": cells}


def _bound(data_obj):
    return TableForm(data={"data": json.dumps(data_obj)})


def test_valid_payload_is_valid():
    assert _bound(_payload()).is_valid()


def test_unparseable_json_is_form_error_not_crash():
    f = TableForm(data={"data": "{not json"})
    assert not f.is_valid()


def test_ragged_cells_rejected():
    p = _payload(2, 2)
    p["cells"][0] = p["cells"][0][:1]  # ragged
    assert not _bound(p).is_valid()


def test_over_cap_rejected():
    assert not _bound(_payload(rows=51, cols=1)).is_valid()
    assert not _bound(_payload(rows=1, cols=21)).is_valid()


def test_out_of_range_enums_coerced_to_defaults():
    p = _payload()
    p["border"] = "zigzag"
    p["cells"][0][0]["halign"] = "sideways"
    f = _bound(p)
    assert f.is_valid()
    assert f.cleaned_data["data"]["border"] == "grid"
    assert f.cleaned_data["data"]["cells"][0][0]["halign"] == "left"


def test_empty_data_object_normalises_to_default_2x2():
    f = _bound({})
    assert f.is_valid()
    assert len(f.cleaned_data["data"]["cells"]) == 2
