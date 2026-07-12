import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import FillGateElementForm
from courses.fillblank import SENTINEL
from courses.models import FillGateElement


@pytest.mark.django_db
def test_form_parses_stem_and_persists_answers():
    form = FillGateElementForm(data={"stem": "2+2 = {{4|four}}"})
    assert form.is_valid(), form.errors
    obj = form.save()
    obj.refresh_from_db()
    assert obj.answers == [["4", "four"]]
    assert f"{SENTINEL}0{SENTINEL}" in obj.stem  # stored as token-stem, not {{...}}
    assert FORM_FOR_TYPE["fillgate"] is FillGateElementForm


@pytest.mark.django_db
def test_form_rejects_stem_without_blanks():
    form = FillGateElementForm(data={"stem": "no blanks here"})
    assert not form.is_valid()
    assert "stem" in form.errors


@pytest.mark.django_db
def test_edit_shows_author_markup():
    obj = FillGateElement.objects.create(
        stem=f"x {SENTINEL}0{SENTINEL}", answers=[["a", "b"]]
    )
    form = FillGateElementForm(instance=obj)
    assert form.initial["stem"] == "x {{a|b}}"
