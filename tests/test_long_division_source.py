"""Scanning a directory of legacy lesson HTML for convertible tables."""

from pathlib import Path

import pytest

from courses.longdivision.source import scan

RULED = ' style="border-bottom: 1px solid black;"'

REAL_SOURCE = Path(r"C:\Users\krzys\Documents\teaching\LAL\html\045_wielomiany")


def _write(tmp_path, name, body):
    (tmp_path / name).write_text(body, encoding="utf-8")


def test_scan_selects_only_qualifying_tables(tmp_path):
    _write(
        tmp_path,
        "010_lesson.html",
        f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>'
        '<table class="my_table_border"><tr><td>x</td></tr></table>'
        '<table class="my_table_noborder"><tr><td>y</td></tr></table>',
    )
    found = scan(tmp_path)
    assert len(found) == 1
    assert found[0].file == "010_lesson"


def test_index_is_the_position_among_all_tables(tmp_path):
    # The index must count EVERY <table>, not just selected ones, so an id like
    # "130_wielomiany_dzielenie#9" refers to the same table a human counting
    # tables in the file would land on.
    _write(
        tmp_path,
        "020_lesson.html",
        '<table class="my_table_border"><tr><td>x</td></tr></table>'
        f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td></tr></table>',
    )
    assert scan(tmp_path)[0].index == 1


def test_files_are_scanned_in_sorted_order(tmp_path):
    for name in ("030_b.html", "010_a.html"):
        _write(
            tmp_path,
            name,
            f'<table class="my_table_noborder"><tr{RULED}><td>\\(1\\)</td>'
            "</tr></table>",
        )
    assert [s.file for s in scan(tmp_path)] == ["010_a", "030_b"]


@pytest.mark.skipif(not REAL_SOURCE.is_dir(), reason="legacy LAL source not present")
def test_real_directory_selects_exactly_73():
    found = scan(REAL_SOURCE)
    assert len(found) == 73
    excluded = {
        "330_wielomiany_wzory",
        "340_wielomiany_wzory",
        "350_wielomiany_wzory",
        "480_wielomiany_podsumowanie",
    }
    per_file = {}
    for s in found:
        per_file[s.file] = per_file.get(s.file, 0) + 1
    assert per_file["130_wielomiany_dzielenie"] == 10
    assert per_file["160_wielomiany_dzielenie"] == 40
    # The four wzór|nazwa tables are the ONLY table in their file that would
    # otherwise qualify, so those files must contribute nothing.
    for name in excluded:
        assert name not in per_file
