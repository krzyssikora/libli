import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import CalloutElementForm

pytestmark = pytest.mark.django_db


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["callout"] is CalloutElementForm


def test_valid_full_save():
    form = CalloutElementForm(
        data={"kind": "warning", "heading": "Careful", "body": "<p>x</p>"}
    )
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.kind == "warning"
    assert el.heading == "Careful"


def test_blank_heading_and_body_are_valid():
    form = CalloutElementForm(data={"kind": "tip", "heading": "", "body": ""})
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.heading == ""
    assert el.display_heading  # falls back to the kind default
