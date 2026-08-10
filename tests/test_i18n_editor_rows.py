"""Catalog guard for the strings the instant row add/remove work introduced.

Deliberately a separate file from tests/test_i18n_stepper.py: eight of these
eleven are not stepper strings. The `＋` on the add buttons sits OUTSIDE the
{% trans %} tag, so there is no "＋ Add step" msgid to assert — the add labels
already shipped and are covered elsewhere.
"""

import pytest
from django.utils import translation

EDITOR_ROW_MSGIDS = [
    # confirm prompts — choice and switchgate share "Remove this option?"
    "Remove this pair?",
    "Remove this step?",
    "Remove this item?",
    "Remove this option?",
    # at-minimum hints, worded per editor
    "A matching question needs at least one pair.",
    "A stepper needs at least one step.",
    "A checklist needs at least one item.",
    "A question needs at least two options.",
    "A choice needs at least two options.",
    # at-cap hints
    "No room for another step.",
    "No room for another item.",
]


@pytest.mark.parametrize("msgid", EDITOR_ROW_MSGIDS)
def test_pl_translation_present(msgid):
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid
