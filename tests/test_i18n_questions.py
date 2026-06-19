from django.utils import translation

REQUIRED_MSGIDS = [
    "Check",
    "Correct",
    "Incorrect",
    "Single choice",
    "Multiple choice",
    "Question",
    "Choices",
    "Explanation (optional)",
    "Remove",
    "Add at least two choices.",
    "Mark at least one choice correct.",
    "A single-choice question needs exactly one correct choice.",
]


def test_question_strings_have_polish_translations():
    # Robust against fuzzy flags / multiline msgids: gettext at runtime ignores fuzzy
    # entries (returns the msgid) and uses the COMPILED catalog, so this asserts a real,
    # non-fuzzy Polish translation exists for each string. Requires compilemessages
    # (Step 5).
    with translation.override("pl"):
        for msgid in REQUIRED_MSGIDS:
            translated = translation.gettext(msgid)
            assert translated != msgid, f"missing/fuzzy Polish translation for: {msgid}"
