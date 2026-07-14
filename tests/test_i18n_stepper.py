import pytest
from django.utils import translation

STEPPER_MSGIDS = [
    "Step-by-step",
    "Steps",
    "Show next",
    "Intro prompt (optional)",
    "Add step",
    "Add at least one step.",
]


@pytest.mark.parametrize("msgid", STEPPER_MSGIDS)
def test_pl_translation_present(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid
