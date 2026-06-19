import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import ChoiceQuestionElementForm
from courses.element_forms import build_choice_formset


def _formset_data(rows, *, prefix="choices"):
    """rows: list of (text, is_correct_bool). Builds management-form + row POST data."""
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": "0",
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for i, (text, correct) in enumerate(rows):
        data[f"{prefix}-{i}-text"] = text
        if correct:
            data[f"{prefix}-{i}-is_correct"] = "on"
    return data


@pytest.mark.django_db
def test_form_in_registry_and_has_multiple_on_create():
    assert FORM_FOR_TYPE["choicequestion"] is ChoiceQuestionElementForm
    form = ChoiceQuestionElementForm(initial={"multiple": True})
    assert "multiple" in form.fields


@pytest.mark.django_db
def test_form_drops_multiple_field_on_edit():
    from courses.models import ChoiceQuestionElement

    q = ChoiceQuestionElement.objects.create(stem="x", multiple=True)
    form = ChoiceQuestionElementForm(instance=q)
    assert "multiple" not in form.fields  # pinned: a bound POST cannot flip it


@pytest.mark.django_db
def test_formset_requires_two_choices():
    fs = build_choice_formset(data=_formset_data([("only one", True)]))
    assert not fs.is_valid()


@pytest.mark.django_db
def test_formset_requires_at_least_one_correct():
    fs = build_choice_formset(data=_formset_data([("a", False), ("b", False)]))
    assert not fs.is_valid()


@pytest.mark.django_db
def test_single_choice_requires_exactly_one_correct():
    # multiple=False context: two correct is invalid
    fs = build_choice_formset(
        data=_formset_data([("a", True), ("b", True)]), multiple=False
    )
    assert not fs.is_valid()


@pytest.mark.django_db
def test_multiple_choice_allows_two_correct():
    fs = build_choice_formset(
        data=_formset_data([("a", True), ("b", True)]), multiple=True
    )
    assert fs.is_valid(), fs.non_form_errors()
