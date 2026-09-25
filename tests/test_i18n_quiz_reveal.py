from django.utils import translation
from django.utils.translation import gettext
from django.utils.translation import pgettext


def test_quiz_reveal_strings_translated_to_polish():
    with translation.override("pl"):
        for s in (
            "Show answer",
            "Correct answer",
            "Answer view",
            "Partly correct",
            "answer shown",
            "Your answer",
        ):
            assert gettext(s) != s, s
        assert pgettext("answer part verdict", "incorrect") != "incorrect"
        assert pgettext("answer part verdict", "correct") != "correct"
