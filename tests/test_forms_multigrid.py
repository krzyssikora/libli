# tests/test_forms_multigrid.py
import pytest

from courses.element_forms import build_multigrid_columns_formset
from courses.element_forms import build_multigrid_rows_formset


def _mgmt(prefix, total):
    return {
        f"{prefix}-TOTAL_FORMS": str(total),
        f"{prefix}-INITIAL_FORMS": "0",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }


@pytest.mark.django_db
def test_rows_formset_requires_at_least_one_correct_temp_id():
    data = {}
    data.update(_mgmt("columns", 1))
    data.update({"columns-0-label": "A", "columns-0-temp_id": "t1"})
    data.update(_mgmt("rows", 1))
    data.update({"rows-0-statement": "r1", "rows-0-correct_temp_ids": ""})  # empty
    rows = build_multigrid_rows_formset(data=data, instance=None)
    assert not rows.is_valid()


@pytest.mark.django_db
def test_rows_formset_accepts_comma_joined_ids():
    data = {}
    data.update(_mgmt("rows", 1))
    data.update({"rows-0-statement": "r1", "rows-0-correct_temp_ids": "t1,t2"})
    rows = build_multigrid_rows_formset(data=data, instance=None)
    assert rows.is_valid(), rows.errors


@pytest.mark.django_db
def test_columns_formset_requires_one_column():
    data = {}
    data.update(_mgmt("columns", 0))
    cols = build_multigrid_columns_formset(data=data, instance=None)
    assert not cols.is_valid()
