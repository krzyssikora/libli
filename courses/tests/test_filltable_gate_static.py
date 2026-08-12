"""Source guards for the fill-table gate's client side.

A boot flag that is never assigned makes lesson_unit.html's watchdog disarm the
pre-hide on EVERY load, quietly defeating it -- with no visible symptom, because
the content is merely revealed early.
"""

from pathlib import Path

SRC = Path("courses/static/courses/js/filltable.js").read_text(encoding="utf-8")


def test_boot_flag_is_assigned():
    assert "window.__fillTableBooted = true" in SRC
