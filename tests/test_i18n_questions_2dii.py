import pytest
from django.utils import translation


@pytest.mark.parametrize(
    "english",
    [
        "Drag to image",
        "Add at least one zone.",
        "Zone position must be within the image.",
        "Zone must have a positive size.",
        "Zone must not extend past the image.",
        "Drag on the image to draw a zone, then name its label.",
        "No alt text — recommended so screen-reader users have context.",
        (
            "Describe the image — screen-reader users answer via the"
            " numbered dropdowns below it"
        ),
        "Extra labels (distractors, one per line)",
        "Correct label:",
    ],
)
def test_pl_translation_present(english):
    with translation.override("pl"):
        translated = translation.gettext(english)
    assert translated and translated != english  # a real Polish string was provided
