import json

import pytest

from courses.element_forms import FillTableElementForm
from courses.filltable import answer_cells
from courses.filltable import is_blank_answer
from courses.filltable import split_alternatives

pytestmark = pytest.mark.django_db


def test_split_alternatives_trims_and_drops_empties():
    assert split_alternatives("0,5 | 0.5") == ["0,5", "0.5"]
    assert split_alternatives("  a  ") == ["a"]
    assert split_alternatives("") == []
    assert split_alternatives("|") == []  # pipe-only -> no alternatives
    assert split_alternatives("  |  ") == []


def test_is_blank_answer():
    assert is_blank_answer("") is True
    assert is_blank_answer("|") is True
    assert is_blank_answer("x") is False


def _data(cells, **kw):
    d = {"cells": cells}
    d.update(kw)
    return d


def _bind(data_dict):
    return FillTableElementForm(data={"data": json.dumps(data_dict)})


def test_form_accepts_grid_with_answer_cell():
    f = _bind(
        _data([[{"kind": "static", "html": "t"}, {"kind": "answer", "answer": "4"}]])
    )
    assert f.is_valid(), f.errors
    nd = f.cleaned_data["data"]
    assert nd["cells"][0][1]["kind"] == "answer"


def test_form_rejects_no_answer_cell_with_distinct_message():
    f = _bind(
        _data([[{"kind": "static", "html": "a"}, {"kind": "static", "html": "b"}]])
    )
    assert not f.is_valid()
    assert any("at least one answer cell" in str(e).lower() for e in f.errors["data"])


def test_form_rejects_blank_answer_cell_with_distinct_message():
    f = _bind(
        _data([[{"kind": "answer", "answer": "|"}, {"kind": "static", "html": "b"}]])
    )
    assert not f.is_valid()
    assert any("blank" in str(e).lower() for e in f.errors["data"])


def test_form_rejects_over_cap_grid():
    from courses.models import FillTableElement

    n_rows = FillTableElement.MAX_ROWS + 1
    big = [[{"kind": "answer", "answer": "1"}] for _ in range(n_rows)]
    f = _bind(_data(big))
    assert not f.is_valid()
    assert any("limited to" in str(e).lower() for e in f.errors["data"])


def test_answer_cells_iterates_positions():
    cells = [
        [{"kind": "static"}, {"kind": "answer", "answer": "x"}],
        [{"kind": "answer", "answer": "y"}, {"kind": "static"}],
    ]
    assert list(answer_cells(cells)) == [(0, 1, "x"), (1, 0, "y")]
