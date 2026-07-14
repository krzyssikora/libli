import pytest

from courses.models import ChoiceGridQuestionElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.transfer.export import SERIALIZERS
from courses.transfer.export import _ser_choice_grid
from courses.transfer.importer import BUILDERS
from courses.transfer.importer import _build_choice_grid
from courses.transfer.payloads import VALIDATORS
from courses.transfer.payloads import _val_choice_grid

pytestmark = pytest.mark.django_db


def test_registered():
    assert SERIALIZERS["choice_grid"][0] is ChoiceGridQuestionElement
    assert SERIALIZERS["choice_grid"][1] is _ser_choice_grid
    assert VALIDATORS["choice_grid"] is _val_choice_grid
    assert BUILDERS["choice_grid"] is _build_choice_grid


def test_roundtrip_links_intact():
    q = ChoiceGridQuestionElement.objects.create(stem="s")
    t = GridColumn.objects.create(question=q, label="True")
    f = GridColumn.objects.create(question=q, label="False")
    GridRow.objects.create(question=q, statement="a", correct_column=t)
    GridRow.objects.create(question=q, statement="b", correct_column=f)
    data = _ser_choice_grid(q, None)
    assert data["rows"][0]["correct"] == 0
    assert data["rows"][1]["correct"] == 1
    q2, rows = _build_choice_grid(data, assets={})
    for r in rows:
        r.full_clean(exclude=["order"])
        r.save()
    assert list(q2.columns.values_list("label", flat=True)) == ["True", "False"]
    assert q2.rows.get(statement="b").correct_column.label == "False"


def test_validator_rejects_out_of_range_ordinal():
    from courses.transfer.schema import TransferError

    q = ChoiceGridQuestionElement.objects.create(stem="s")
    GridColumn.objects.create(question=q, label="True")
    data = _ser_choice_grid(q, None)
    data["rows"] = [{"statement": "a", "correct": 5}]  # out of range
    with pytest.raises(TransferError):
        _val_choice_grid(data, "el1", media_kinds={})
