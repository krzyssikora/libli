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
        "Enter a number or fraction (e.g. 3.14, 3,14 or 3/2).",
        "That number is too long (at most 64 characters once normalised).",
        "3.14, 3/2 or 1 1/2",
        "Enter a number or fraction.",
        "Enter a non-negative number or fraction.",
    ],
)
def test_pl_translation_present(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid  # a non-identity PL string exists


def test_editor_type_labels_translate_per_request():
    # The editor's type heading is built from a module-level dict; it must hold lazy
    # strings so it translates per-request, not freeze to the import-time locale.
    from courses.views_manage import _EDITOR_TYPE_LABELS

    with translation.override("pl"):
        label = str(_EDITOR_TYPE_LABELS["fillblankquestion"])
        assert label == translation.gettext("Fill in the blanks")
        assert label != "Fill in the blanks"  # actually Polish, not frozen English
