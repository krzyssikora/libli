"""Done-gate: every new Phase-4a notes msgid is translated to PL, and the
catalog is clean (no fuzzy / obsolete entries). Mirrors test_i18n_auth.py."""

from pathlib import Path

import pytest
from django.utils import translation

ROOT = Path(__file__).resolve().parent.parent
PO = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"

NOTES_MSGIDS = [
    "Add note",
    "Save",
    "Cancel",
    "Edit note",
    "Delete note",
    "Delete this note?",
    "Delete",
    "Saved.",
    "Deleted.",
    "Write a note",
    "Note text",
    "A note cannot be empty.",
    "Note",
    "This note is too long (max 5000 characters).",
]

# blocktrans phrase msgids carry placeholders; assert separately that they changed.
NOTES_PHRASE_MSGIDS = [
    "edited %(when)s ago",
    "added %(when)s ago",
    "on: %(blk)s",
]


@pytest.mark.parametrize("msgid", NOTES_MSGIDS)
def test_notes_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        assert str(translation.gettext(msgid)) != msgid, f"untranslated PL: {msgid!r}"


@pytest.mark.parametrize("msgid", NOTES_PHRASE_MSGIDS)
def test_notes_phrase_msgid_translated_to_pl(msgid):
    with translation.override("pl"):
        assert str(translation.gettext(msgid)) != msgid, f"untranslated PL: {msgid!r}"


def test_po_catalog_clean():
    text = PO.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"
