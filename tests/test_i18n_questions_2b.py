import pytest
from django.utils import translation


@pytest.mark.parametrize(
    "msgid",
    [
        "Short text",
        "Short numeric",
        "Fill in the blanks",
        "Accepted answers (one per line)",
        "Correct value",
        "Correct answer:",
        "Expected:",
    ],
)
def test_pl_translation_present(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid  # a non-identity PL string exists
