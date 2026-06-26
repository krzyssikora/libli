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


def test_editor_type_labels_translate_per_request():
    # The editor's type heading is built from a module-level dict; it must hold lazy
    # strings so it translates per-request, not freeze to the import-time locale.
    from courses.views_manage import _EDITOR_TYPE_LABELS

    with translation.override("pl"):
        label = str(_EDITOR_TYPE_LABELS["fillblankquestion"])
        assert label == translation.gettext("Fill in the blanks")
        assert label != "Fill in the blanks"  # actually Polish, not frozen English
