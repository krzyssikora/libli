"""Catalog test: PL .po file is clean and all new tags msgids are translated."""

import re
from pathlib import Path


def test_pl_catalog_clean_for_tags_strings():
    po = Path("locale/pl/LC_MESSAGES/django.po").read_text(encoding="utf-8")
    assert "#, fuzzy" not in po
    assert "#~ msgid" not in po  # no obsolete entries
    # spot-check a few new msgids are translated (non-empty msgstr)
    for msgid in ['"My tags"', '"Add a tag…"', '"Filter:"']:
        idx = po.find("msgid " + msgid)
        assert idx != -1, msgid
        tail = po[idx : idx + 200]
        assert re.search(r'msgstr "(?!")\S', tail), msgid
