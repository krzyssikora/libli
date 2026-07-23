"""Catalog test: PL/EN .po files are clean and every new spanning-table-editor
msgid has a real Polish translation.

Covers the msgids introduced by the cell merge/split UI (Task 17): the three
toolbar button labels, the header-lock title, the two live-region strings,
the merge confirm, the too-big-selection title, the two span-range messages
(Task 2), and the reworded table-size cap message."""

from pathlib import Path

import pytest
from django.utils import translation

ROOT = Path(__file__).resolve().parent.parent
EN_PO = ROOT / "locale" / "en" / "LC_MESSAGES" / "django.po"
PL_PO = ROOT / "locale" / "pl" / "LC_MESSAGES" / "django.po"

SPANNING_TABLE_MSGIDS = [
    "Merge cells",
    "Split cell",
    "Header cell",
    "Unavailable while the row or column header option covers this cell.",
    "Merging will discard the content of the other selected cells.",
    "The selection is larger than a table may be.",
    "Range selected",
    "Range cleared",
    "A merged cell may not span more than %(n)d columns.",
    "A merged cell may not span more than %(n)d rows.",
    "A table cannot be made larger than %(r)d rows by %(c)d columns.",
]


@pytest.mark.parametrize("msgid", SPANNING_TABLE_MSGIDS)
def test_pl_translation_present(msgid):
    with translation.override("pl"):
        # untranslated/fuzzy would return the msgid unchanged
        assert translation.gettext(msgid) != msgid, f"untranslated PL: {msgid!r}"


def test_old_caps_msgid_retired():
    for po in (EN_PO, PL_PO):
        text = po.read_text(encoding="utf-8")
        assert "Tables are limited to %(r)d rows by %(c)d columns." not in text, (
            f"the old caps msgid must be removed from {po}"
        )


def test_en_po_catalog_clean():
    text = EN_PO.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"


def test_pl_po_catalog_clean():
    text = PL_PO.read_text(encoding="utf-8")
    assert "#, fuzzy" not in text, "fuzzy entries present — review and clear"
    assert "#~" not in text, "obsolete entries present — drop them"
