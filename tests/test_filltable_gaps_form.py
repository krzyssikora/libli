import json

import pytest

from courses.element_forms import FillTableElementForm
from courses.models import FillTableElement

pytestmark = pytest.mark.django_db

S = "\uffff"


def _bind(cells, **kw):
    return FillTableElementForm(data={"data": json.dumps({"cells": cells, **kw})})


def _errors(f):
    assert not f.is_valid()
    return " ".join(str(e) for e in f.errors["data"])


def test_gaps_only_table_saves_with_tokens():
    f = _bind([[{"kind": "static", "html": r"{{9}} \(\pi\)"}]])
    assert f.is_valid(), f.errors
    cell = f.cleaned_data["data"]["cells"][0][0]
    assert cell["html"] == f"{S}0{S}" + r" \(\pi\)"
    assert cell["gaps"] == [["9"]]


def test_gate_survives_for_gaps_only_table_through_the_form():
    # §3: parse must run BEFORE normalize_data or the gate is silently dropped.
    f = _bind([[{"kind": "static", "html": "{{9}}"}]], gate=True)
    assert f.is_valid(), f.errors
    assert f.cleaned_data["data"]["gate"] is True


def test_posted_gaps_key_is_ignored():
    """The guarantee comes from strip_sentinel (posted html cannot carry a real
    token) + reconcile_gaps (gaps without tokens are dropped). The form's
    cell.pop("gaps") is defence in depth and is NOT separately falsifiable --
    this test pins the end result, not the pop."""
    f = _bind(
        [
            [
                {"kind": "static", "html": "plain", "gaps": [["evil"]]},
                {"kind": "answer", "answer": "1"},
            ]
        ]
    )
    assert f.is_valid(), f.errors
    assert "gaps" not in f.cleaned_data["data"]["cells"][0][0]


def test_markup_in_marker_is_stripped():
    f = _bind([[{"kind": "static", "html": "{{<b>9</b>}}"}]])
    assert f.is_valid(), f.errors
    assert f.cleaned_data["data"]["cells"][0][0]["gaps"] == [["9"]]


@pytest.mark.parametrize("html", ["{{}}", "x {{9"])
def test_empty_or_unclosed_marker_names_the_cell(html):
    f = _bind(
        [
            [{"kind": "answer", "answer": "1"}, {"kind": "static", "html": "ok"}],
            [{"kind": "static", "html": "ok"}, {"kind": "static", "html": html}],
        ]
    )
    msg = _errors(f)
    assert "Row 2, column 2" in msg
    assert "empty or not closed" in msg


def test_maths_in_marker_gets_maths_message():
    msg = _errors(_bind([[{"kind": "static", "html": r"{{9\(\pi\)}}"}]]))
    assert "Row 1, column 1" in msg
    assert "cannot contain maths" in msg


def test_cap_ten_saves_eleven_rejected():
    ok = _bind([[{"kind": "static", "html": "{{1}}" * 10}]])
    assert ok.is_valid(), ok.errors
    msg = _errors(_bind([[{"kind": "static", "html": "{{1}}" * 11}]]))
    assert "at most 10 answer boxes" in msg


def test_parse_error_wins_over_cap():
    msg = _errors(_bind([[{"kind": "static", "html": "{{1}}" * 11 + "{{}}"}]]))
    assert "empty or not closed" in msg


def test_no_answers_and_no_gaps_new_message():
    msg = _errors(_bind([[{"kind": "static", "html": "a"}]]))
    assert "Add at least one answer" in msg
    assert "{{answer}}" in msg


def test_resaving_stored_cells_keeps_gaps():
    # What the editor posts back after Task 6: author_html of the stored cells.
    first = _bind([[{"kind": "static", "html": "{{9|9,0}} x"}]], gate=True)
    assert first.is_valid(), first.errors
    el = FillTableElement(data=first.cleaned_data["data"])
    el.save()
    form = FillTableElementForm(instance=el)
    posted = [
        [{"kind": "static", "html": c["author_html"]} for c in row]
        for row in form.resolved_grid_cells
    ]
    again = _bind(posted, gate=True)
    assert again.is_valid(), again.errors
    assert again.cleaned_data["data"]["cells"] == el.normalize_data(el.data)["cells"]


def test_resave_marker_free_table_is_identical():
    cells = [
        [
            {"kind": "static", "html": "<b>czas</b> \\(x^2\\)"},
            {"kind": "answer", "answer": "4 | four"},
        ]
    ]
    el = FillTableElement(data={"cells": cells})
    el.save()
    before = el.normalize_data(el.data)["cells"]
    f = _bind(el.data["cells"])
    assert f.is_valid(), f.errors
    assert f.cleaned_data["data"]["cells"] == before


def test_resolved_grid_cells_author_html():
    el = FillTableElement(
        data={"cells": [[{"kind": "static", "html": f"{S}0{S}", "gaps": [["a<b"]]}]]}
    )
    cell = FillTableElementForm(instance=el).resolved_grid_cells[0][0]
    assert cell["author_html"] == "{{a&lt;b}}"
