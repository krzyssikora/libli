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
        "Zones & labels",
        "Label for this zone",
        "Choose image",
        "Change image",
        (
            "Draw a box on the image for each target area, then type the label a"
            " student must drag onto it. Each row's number matches the badge on"
            " its box."
        ),
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
