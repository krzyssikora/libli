from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import TwoColumnElementForm
from courses.models import TwoColumnElement


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["twocolumn"] is TwoColumnElementForm


def test_form_has_no_data_field():
    f = TwoColumnElementForm()
    assert "data" not in f.fields
    assert "column_count" in f.fields


def test_form_column_count_coerces_int_and_bounds():
    f = TwoColumnElementForm(data={"column_count": "3"})
    assert f.is_valid()
    assert f.cleaned_data["column_count"] == 3
    bad = TwoColumnElementForm(data={"column_count": "5"})
    assert not bad.is_valid()


def test_form_initializes_count_to_persisted_on_edit():
    inst = TwoColumnElement(
        data={
            "columns": [
                {"id": "c000001"},
                {"id": "c000002"},
                {"id": "c000003"},
            ]
        }
    )
    f = TwoColumnElementForm(instance=inst)
    assert f.fields["column_count"].initial == 3


def test_form_initializes_count_to_two_on_create():
    f = TwoColumnElementForm()
    assert f.fields["column_count"].initial == 2
