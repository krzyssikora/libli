"""Pins the Polish label and the English catalog entry for the Callout Task kind.

No django_db mark: the CalloutElement is never saved.
"""

from django.utils import translation

from courses.models import CalloutElement
from tests.test_i18n_po_health import EN_PO
from tests.test_i18n_po_health import _entries


def test_task_kind_renders_zadanie_in_polish():
    # override(), NOT activate(): a bare activate leaks the language into every
    # later test in this xdist worker.
    with translation.override("pl"):
        assert str(CalloutElement(kind="task").display_heading) == "Zadanie"


def test_en_catalog_has_the_task_msgid():
    # _entries() returns dicts, and it RETAINS obsolete entries with a flag rather
    # than dropping them -- so the `not e["obsolete"]` filter is what makes "live"
    # in the message below actually true. Without it a commented-out
    # `#~ msgid "Task"` block would count, exactly like a raw substring search.
    matches = [
        e for e in _entries(EN_PO) if e["msgid"] == "Task" and not e["obsolete"]
    ]
    assert len(matches) == 1, "expected exactly one live `Task` entry in locale/en"
    assert matches[0]["msgstrs"] == [""], "the en catalog entry must stay empty"
