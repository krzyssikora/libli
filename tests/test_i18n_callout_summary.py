"""Pins the Polish label and the English catalog entry for the summary callout kind
("Key facts" / "W skrócie"). Sibling of test_i18n_callout_task.py.

No django_db mark: the CalloutElement is never saved.
"""

from django.utils import translation

from courses.models import CalloutElement
from tests.test_i18n_po_health import EN_PO
from tests.test_i18n_po_health import PL_PO
from tests.test_i18n_po_health import _entries


def test_summary_kind_renders_w_skrocie_in_polish():
    # override(), NOT activate(): a bare activate leaks the language into every
    # later test in this xdist worker. Reads the COMPILED .mo, so a fuzzy or empty
    # msgstr falls back to "Key facts" here.
    with translation.override("pl"):
        assert str(CalloutElement(kind="summary").display_heading) == "W skrócie"


def test_pl_catalog_entry_is_live_and_translated():
    matches = [
        e for e in _entries(PL_PO) if e["msgid"] == "Key facts" and not e["obsolete"]
    ]
    assert len(matches) == 1, "expected exactly one live `Key facts` entry in pl"
    assert not matches[0]["fuzzy"], "the pl `Key facts` entry is fuzzy"
    assert matches[0]["msgstrs"] == ["W skrócie"]


def test_en_catalog_has_the_key_facts_msgid():
    # _entries() RETAINS obsolete entries with a flag, so the filter is what makes
    # "live" true; a commented-out `#~ msgid "Key facts"` must not count.
    matches = [
        e for e in _entries(EN_PO) if e["msgid"] == "Key facts" and not e["obsolete"]
    ]
    assert len(matches) == 1, "expected exactly one live `Key facts` entry in locale/en"
    assert matches[0]["msgstrs"] == [""], "the en catalog entry must stay empty"
