import pytest
from django.core.exceptions import ValidationError

from courses.models import ImageElement

pytestmark = pytest.mark.django_db


def test_size_defaults_to_full():
    el = ImageElement()
    assert el.size == "full"


def test_size_choices_are_the_four_presets():
    assert list(ImageElement.Size.values) == ["small", "medium", "large", "full"]


def test_size_rejects_an_unknown_value():
    """`size` in error_dict, not a bare raises: full_clean aggregates errors across
    every field and the model's own clean(), so a bare pytest.raises passes if ANY
    field fails — including for reasons that have nothing to do with the choices."""
    el = ImageElement(size="enormous")
    with pytest.raises(ValidationError) as exc:
        el.full_clean(exclude=["media"])
    assert "size" in exc.value.error_dict
