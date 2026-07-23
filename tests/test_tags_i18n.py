"""Catalog test: all new tags msgids have a real Polish translation."""

import re
from pathlib import Path


def test_tags_msgids_are_translated():
    po = Path("locale/pl/LC_MESSAGES/django.po").read_text(encoding="utf-8")
    # spot-check a few new msgids are translated (non-empty msgstr)
    for msgid in ['"My tags"', '"Add a tag…"', '"Filter:"']:
        idx = po.find("msgid " + msgid)
        assert idx != -1, msgid
        tail = po[idx : idx + 200]
        assert re.search(r'msgstr "(?!")\S', tail), msgid
