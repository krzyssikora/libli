import pytest

from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.transfer.export import SERIALIZERS
from courses.transfer.export import _ser_multi_grid
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import _build_multi_grid
from courses.transfer.payloads import VALIDATORS
from courses.transfer.payloads import _val_multi_grid
from courses.transfer.schema import TransferError

pytestmark = pytest.mark.django_db


# --- _val_multi_grid unit tests ---------------------------------------------


def _payload(rows_correct):
    return {
        "stem": "s",
        "explanation": "",
        "marking_mode": "A",
        "max_attempts": 1,
        "max_marks": "1.00",
        "columns": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
        "rows": [{"statement": "r1", "correct": rc} for rc in rows_correct],
    }


def test_val_multi_grid_accepts_valid():
    assert _val_multi_grid(_payload([[0, 2], [1]]), "el1", {}) == set()


def test_val_multi_grid_rejects_scalar_correct():
    with pytest.raises(TransferError):
        _val_multi_grid(_payload([2]), "el1", {})  # correct must be a list


def test_val_multi_grid_rejects_out_of_range_ordinal():
    with pytest.raises(TransferError):
        _val_multi_grid(_payload([[5]]), "el1", {})


def test_val_multi_grid_rejects_empty_correct():
    with pytest.raises(TransferError):
        _val_multi_grid(_payload([[]]), "el1", {})


# --- registration + round-trip (mirrors tests/test_transfer_choicegrid.py) ---


def test_registered():
    assert SERIALIZERS["multi_grid"][0] is MultiGridQuestionElement
    assert SERIALIZERS["multi_grid"][1] is _ser_multi_grid
    assert VALIDATORS["multi_grid"] is _val_multi_grid
    assert BUILDERS["multi_grid"] is _build_multi_grid


def test_roundtrip_links_intact():
    q = MultiGridQuestionElement.objects.create(stem="s")
    a = MultiGridColumn.objects.create(question=q, label="A")
    b = MultiGridColumn.objects.create(question=q, label="B")
    c = MultiGridColumn.objects.create(question=q, label="C")
    r1 = MultiGridRow.objects.create(question=q, statement="a")
    r1.correct_columns.set([a, c])
    r2 = MultiGridRow.objects.create(question=q, statement="b")
    r2.correct_columns.set([b])
    data = _ser_multi_grid(q, None)
    assert data["rows"][0]["correct"] == [0, 2]  # sorted column ordinals
    assert data["rows"][1]["correct"] == [1]
    # _build_multi_grid saves columns AND rows AND the M2M internally, returning
    # (question, []) — nothing for the generic importer loop to process.
    q2, rows = _build_multi_grid(data, assets={})
    assert rows == []
    assert list(q2.columns.values_list("label", flat=True)) == ["A", "B", "C"]
    assert {col.label for col in q2.rows.get(statement="a").correct_columns.all()} == {
        "A",
        "C",
    }
    assert {col.label for col in q2.rows.get(statement="b").correct_columns.all()} == {
        "B"
    }
