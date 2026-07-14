from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import ChoiceGridQuestionElementForm
from courses.element_forms import build_choicegrid_columns_formset
from courses.element_forms import build_choicegrid_rows_formset


def test_registered():
    assert FORM_FOR_TYPE["choicegridquestion"] is ChoiceGridQuestionElementForm


def test_column_form_has_temp_id_field():
    fs = build_choicegrid_columns_formset(data=None, files=None, instance=None)
    assert "temp_id" in fs.empty_form.fields


def test_row_form_has_correct_temp_id_field_not_fk():
    fs = build_choicegrid_rows_formset(data=None, files=None, instance=None)
    assert "correct_temp_id" in fs.empty_form.fields
    assert "correct_column" not in fs.empty_form.fields
