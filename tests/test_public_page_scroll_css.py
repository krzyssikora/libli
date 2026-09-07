"""The scroller rule must come AFTER .public-page table, not merely exist.

.public-page table and .public-page__scroll table are BOTH (0,1,1) -- a
specificity TIE, decided by source order. A block placed above the existing rule
is completely inert while reading exactly like the design, and this repo has
shipped that failure before.
"""

from pathlib import Path

from django.conf import settings

CSS = Path(settings.BASE_DIR, "core", "static", "core", "css", "app.css").read_text(
    encoding="utf-8"
)


def test_the_scroller_rule_exists():
    assert ".public-page__scroll" in CSS
    assert "overflow-x: auto" in CSS.split(".public-page__scroll", 1)[1][:200]


def test_the_table_rule_defeats_the_width_100_percent_rule_by_SOURCE_ORDER():
    """The A in the A/B: without this ordering the scroller never engages,
    because the table shrinks to the wrapper and every column wraps instead."""
    base = CSS.index(".public-page table")
    scoped = CSS.index(".public-page__scroll table")
    assert scoped > base, "the scoped rule must come after .public-page table"


def test_the_table_is_allowed_to_exceed_the_wrapper():
    scoped = CSS.split(".public-page__scroll table", 1)[1][:200]
    assert "max-content" in scoped
    assert "min-width" in scoped
