import pytest

from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

S = "\uffff"


def tok(n):
    return f"{S}{n}{S}"


def _norm(cells, **kw):
    return FillTableElement.normalize_data({"cells": cells, **kw})


def test_static_cell_without_gaps_is_unchanged_even_with_literal_token():
    # §1: the live, hand-edited course must be byte-identical on read.
    raw = {"kind": "static", "html": "a" + tok(0) + "b"}
    assert _norm([[raw]])["cells"][0][0] == {
        "kind": "static",
        "html": "a" + tok(0) + "b",
        "halign": "left",
        "valign": "top",
    }


def test_gaps_carried_and_reconciled():
    raw = {"kind": "static", "html": tok(1) + tok(0), "gaps": [["a"], [" b "]]}
    cell = _norm([[raw]])["cells"][0][0]
    assert cell["html"] == tok(0) + tok(1)
    assert cell["gaps"] == [["b"], ["a"]]


def test_all_gaps_removed_omits_key():
    cell = _norm([[{"kind": "static", "html": "x", "gaps": [["a"]]}]])["cells"][0][0]
    assert "gaps" not in cell


def test_non_list_gaps_drops_key_and_tokens():
    cell = _norm([[{"kind": "static", "html": "x" + tok(0), "gaps": "bad"}]])
    assert cell["cells"][0][0] == {
        "kind": "static",
        "html": "x",
        "halign": "left",
        "valign": "top",
    }


def test_answer_and_image_cells_ignore_gaps():
    cell = _norm([[{"kind": "answer", "answer": "1", "gaps": [["x"]]}]])
    assert "gaps" not in cell["cells"][0][0]


def test_gate_kept_for_gaps_only_table():
    nd = _norm([[{"kind": "static", "html": tok(0), "gaps": [["9"]]}]], gate=True)
    assert nd["gate"] is True


def test_gate_still_off_with_no_answers_and_no_gaps():
    nd = _norm([[{"kind": "static", "html": "x"}]], gate=True)
    assert nd["gate"] is False


def test_save_rebalances_straddling_tag():
    el = FillTableElement(
        data={"cells": [[{"kind": "static", "html": "<b>" + tok(0), "gaps": [["9"]]}]]}
    )
    el.save()
    h = el.data["cells"][0][0]["html"]
    assert h.count("<b>") == h.count("</b>") == 1
    assert tok(0) in h


def test_canonical_cells_adds_gaps_display_without_mutating_data():
    el = FillTableElement(
        data={
            "cells": [
                [
                    {
                        "kind": "static",
                        "html": tok(0) + tok(1),
                        "gaps": [["9", "9,0"], ["x"]],
                    }
                ]
            ]
        }
    )
    before = repr(el.data)
    cell = el.canonical_cells[0][0]
    assert cell["gaps_display"] == ["9", "x"]
    assert cell["gaps"] == [["9", "9,0"], ["x"]]
    assert repr(el.data) == before
