import pytest
from django.utils import translation

MSGIDS = [
    "Guess the number",
    "Correct!",
    "The number is too big, try again.",
    "The number is too small, try again.",
    "Write the answer in double braces, e.g. {{42}}.",
    "The answer must be a number (e.g. 42 or 3,14).",
    "Prompt with the answer",
    "Success message",
    "Your answer",
]


@pytest.mark.parametrize("msgid", MSGIDS)
def test_polish_translation_exists(msgid):
    with translation.override("pl"):
        # untranslated/fuzzy would return the msgid unchanged
        assert translation.gettext(msgid) != msgid
