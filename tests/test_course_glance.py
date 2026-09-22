"""Course glance bars (spec 2026-09-22-course-glance-bars-design.md)."""

from decimal import Decimal

import pytest

from courses.rollups import _course_required_totals
from courses.rollups import _pct
from courses.rollups import _progress_width
from courses.rollups import _results_width


@pytest.mark.parametrize(
    ("done", "total", "expected"),
    [
        (0, 0, None),  # no required lessons: track only (D4)
        (0, 5, None),  # nothing done: track only, NO dot (D4)
        (1, 250, 1),  # rounds to 0 but must still draw a sliver
        (199, 200, 99),  # rounds to 100 but the course is not finished
        (1, 2, 50),
        (5, 5, 100),
        (6, 5, 100),  # defensive: done > total is still full, never 99
    ],
)
def test_progress_width(done, total, expected):
    assert _progress_width(done, total) == expected


@pytest.mark.parametrize(
    ("score", "max_score", "percent", "expected"),
    [
        (None, None, None, None),  # nothing submitted
        (Decimal("0"), Decimal("0"), None, None),  # pending-only / max 0: NOT the dot
        (Decimal("0"), Decimal("10"), 0, 0),  # scored zero: the dot (D3)
        (Decimal("1"), Decimal("300"), 0, 1),  # branches on score, not rounded pct
        (Decimal("299"), Decimal("300"), 100, 99),  # not full while short of max
        (Decimal("16"), Decimal("20"), 80, 80),  # D1 example
        (Decimal("10"), Decimal("10"), 100, 100),
        (Decimal("11"), Decimal("10"), 110, 100),  # score > max stays full
    ],
)
def test_results_width(score, max_score, percent, expected):
    assert _results_width(score, max_score, percent) == expected


def test_results_width_half_boundary_matches_pct():
    # 1/8 = 12.5 -> ROUND_HALF_EVEN -> 12, the same rounding as the spoken percent
    assert _results_width(Decimal("1"), Decimal("8"), _pct(1, 8)) == 12 == _pct(1, 8)


def test_course_required_totals_sums_top_level_items():
    tree = [
        {"required_done": 1, "required_total": 3},
        {"required_done": 2, "required_total": 2},
    ]
    assert _course_required_totals(tree) == (3, 5)
    assert _course_required_totals([]) == (0, 0)
