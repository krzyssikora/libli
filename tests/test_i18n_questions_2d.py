import pytest
from django.utils import translation


@pytest.mark.parametrize(
    "english",
    [
        "Drag the words",
        "Match pairs",
        "Add at least one pair.",
        "— choose —",
    ],
)
def test_pl_translation_present(english):
    with translation.override("pl"):
        translated = translation.gettext(english)
    assert translated and translated != english  # a real Polish string was provided
