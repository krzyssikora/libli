import pytest

from courses.models import ELEMENT_MODELS
from courses.models import SpoilerElement

pytestmark = pytest.mark.django_db


def test_registered_in_element_models():
    assert "spoilerelement" in ELEMENT_MODELS


def test_body_is_sanitized_on_save():
    el = SpoilerElement.objects.create(
        label="Hint", body="<p>ok</p><script>alert(1)</script>"
    )
    el.refresh_from_db()
    assert "<script>" not in el.body
    assert "<p>ok</p>" in el.body


def test_label_and_body_may_be_blank():
    el = SpoilerElement.objects.create()
    assert el.label == ""
    assert el.body == ""
