import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import SpoilerElementForm

pytestmark = pytest.mark.django_db


def test_form_registered():
    assert FORM_FOR_TYPE["spoiler"] is SpoilerElementForm


def test_form_valid_with_label_and_body():
    f = SpoilerElementForm(data={"label": "Show solution", "body": "<p>x</p>"})
    assert f.is_valid(), f.errors
    assert f.cleaned_data["label"] == "Show solution"


def test_form_valid_blank_label_and_body():
    f = SpoilerElementForm(data={"label": "", "body": ""})
    assert f.is_valid(), f.errors


def test_form_rejects_overlong_label():
    f = SpoilerElementForm(data={"label": "x" * 121, "body": ""})
    assert not f.is_valid()
    assert "label" in f.errors
