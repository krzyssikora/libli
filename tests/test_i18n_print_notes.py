"""The three new msgids must land translated, non-empty and non-fuzzy.

This is not a hypothetical. Running makemessages for this feature pre-filled all
three from near-identical entries -- `My note` from "My notes", `edited %(date)s`
from "Updated %(d)s", and `added %(date)s` from "added %(when)s ago"
(django.po:3210) -- each marked `#, fuzzy`. A fuzzy entry ships the WRONG Polish
string with no error anywhere, so prose warnings in a plan are not enough.

Clearing one means deleting BOTH the `#, fuzzy` marker and the `#| msgid`
previous-message line, then replacing the bogus msgstr.
"""

import re
from pathlib import Path

PO = (
    Path(__file__).resolve().parent.parent / "locale/pl/LC_MESSAGES/django.po"
).read_text(encoding="utf-8")

EXPECTED = {
    "My note": "Moja notatka",
    "added %(date)s": "dodano %(date)s",
    "edited %(date)s": "edytowano %(date)s",
}


def _entry(msgid):
    """The full entry block for one msgid, leading comment lines included."""
    pattern = (
        r"((?:^#.*\n)*)"  # leading comments, incl. any `#, fuzzy`
        r'^msgid "' + re.escape(msgid) + r'"\n'
        r'^msgstr "([^"]*)"'
    )
    return re.search(pattern, PO, re.M)


def test_the_three_new_msgids_are_translated_and_not_fuzzy():
    for msgid, expected in EXPECTED.items():
        m = _entry(msgid)
        assert m, f"msgid {msgid!r} is missing from the pl catalogue"
        comments, msgstr = m.group(1), m.group(2)
        assert "#, fuzzy" not in comments, (
            f"{msgid!r} is marked fuzzy -- makemessages pre-filled it from a "
            "near-identical entry. Delete BOTH the marker and the bogus msgstr."
        )
        assert msgstr == expected, (
            f"{msgid!r} translates to {msgstr!r}, expected {expected!r}"
        )


def test_print_is_reused_not_redefined():
    """`Print` already exists (django.po, "Drukuj"). makemessages should add a
    source reference to that entry, not a second definition."""
    assert PO.count('msgid "Print"\n') == 1, (
        'msgid "Print" is defined more than once -- the template should reuse '
        "the existing entry"
    )
    m = _entry("Print")
    assert m and m.group(2) == "Drukuj"
    assert "_unit_strip.html" in m.group(1), (
        'the new {% trans "Print" %} did not add a source reference to the '
        "existing entry -- did makemessages run?"
    )
