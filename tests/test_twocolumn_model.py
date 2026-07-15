import re
import pytest
from courses.models import TwoColumnElement, ELEMENT_MODELS

def test_registered_in_element_models():
    assert "twocolumnelement" in ELEMENT_MODELS

def test_default_data_two_unique_ids():
    d = TwoColumnElement.default_data()
    ids = [c["id"] for c in d["columns"]]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert all(re.fullmatch(r"c[0-9a-f]{6}", i) for i in ids)

def test_normalize_ids_keeps_valid_ids():
    data = {"columns": [{"id": "c000abc"}, {"id": "c111def"}]}
    assert TwoColumnElement.normalize_ids(data) == data

def test_normalize_ids_mints_missing_malformed_duplicate():
    data = {"columns": [{"id": "BAD"}, {"id": "c111def"}, {"id": "c111def"}]}
    out = TwoColumnElement.normalize_ids(data)["columns"]
    ids = [c["id"] for c in out]
    assert len(ids) == 3
    assert len(set(ids)) == 3            # duplicate regenerated
    assert ids[1] == "c111def"           # first of a dup pair kept
    assert all(re.fullmatch(r"c[0-9a-f]{6}", i) for i in ids)

def test_normalize_ids_never_creates_columns():
    assert TwoColumnElement.normalize_ids({})["columns"] == []
    assert TwoColumnElement.normalize_ids({"columns": []})["columns"] == []

def test_normalize_data_pads_to_min_and_truncates_to_max():
    assert len(TwoColumnElement.normalize_data({"columns": []})["columns"]) == 2
    five = {"columns": [{"id": f"c00000{n}"} for n in range(5)]}
    assert len(TwoColumnElement.normalize_data(five)["columns"]) == 4

@pytest.mark.django_db
def test_save_runs_normalize_ids_not_normalize_data():
    el = TwoColumnElement(data={"columns": [{"id": "c000abc"}]})
    el.save()
    # save() is non-destructive: it does NOT pad the single column up to 2.
    assert el.data == {"columns": [{"id": "c000abc"}]}
