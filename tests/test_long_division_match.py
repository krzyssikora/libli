"""Pairing a unit's stored tables with their legacy source, including the six
tables that cell text alone cannot tell apart."""

from collections import Counter

from courses.longdivision.match import index_by_key
from courses.longdivision.match import plan_unit
from courses.longdivision.match import resolve
from courses.longdivision.source import SourceTable

PLAIN = "\\begin{array}{r}\n1\n\\end{array}"
MARKED = "\\begin{array}{r}\n\\htmlClass{mk mk-amber}{1}\n\\end{array}"


def _s(file, index, key, latex):
    return SourceTable(file, index, key, latex)


def test_single_candidate_resolves_to_itself():
    c = [_s("130_x", 0, "K", PLAIN)]
    assert resolve(c, Counter()) is c[0]


def test_identical_latex_from_several_files_is_not_ambiguous():
    # 150#0 and 155#0 are byte-identical; either is a correct answer.
    c = [_s("150_x", 0, "K", PLAIN), _s("155_x", 0, "K", PLAIN)]
    assert resolve(c, Counter()).latex == PLAIN


def test_sibling_majority_picks_the_marked_variant():
    # Unit 423: nine unambiguous siblings all came from 130, so its ambiguous
    # table is 130#9 -- the HIGHLIGHTED one.
    c = [_s("130_x", 9, "K", MARKED), _s("150_x", 0, "K", PLAIN)]
    got = resolve(c, Counter({"130_x": 9}))
    assert got.file == "130_x"
    assert got.latex == MARKED


def test_sibling_majority_is_ignored_when_it_has_no_candidate():
    c = [_s("150_x", 0, "K", PLAIN), _s("155_x", 0, "K", PLAIN)]
    got = resolve(c, Counter({"999_other": 4}))
    assert got.latex == PLAIN


def test_no_unambiguous_sibling_falls_back_to_the_plain_variant():
    # Units 425/426: both their tables are ambiguous, so there is no sibling to
    # vote. The conservative answer is the variant with no highlight markup --
    # never invent emphasis.
    c = [_s("130_x", 9, "K", MARKED), _s("150_x", 0, "K", PLAIN)]
    got = resolve(c, Counter())
    assert got.latex == PLAIN


def test_refuses_when_the_plain_variant_is_not_unique():
    c = [
        _s("a", 0, "K", "\\begin{array}{r}\n1\n\\end{array}"),
        _s("b", 0, "K", "\\begin{array}{r}\n2\n\\end{array}"),
    ]
    assert resolve(c, Counter()) is None


def test_plan_unit_splits_matched_ambiguous_and_unmatched():
    index = index_by_key(
        [
            _s("130_x", 0, "K1", PLAIN),
            _s("130_x", 9, "K2", MARKED),
            _s("150_x", 0, "K2", PLAIN),
        ]
    )
    matched, ambiguous, unmatched = plan_unit(
        [(1, "K1"), (2, "K2"), (3, "K_absent")], index
    )
    assert [d for d, _ in matched] == [1, 2]
    assert ambiguous == []
    assert unmatched == [3]
    # db 2 was ambiguous but resolved via db 1's file
    assert dict(matched)[2].file == "130_x"


def test_plan_unit_reports_a_table_it_cannot_resolve():
    index = index_by_key(
        [
            _s("a", 0, "K", "\\begin{array}{r}\n1\n\\end{array}"),
            _s("b", 0, "K", "\\begin{array}{r}\n2\n\\end{array}"),
        ]
    )
    matched, ambiguous, unmatched = plan_unit([(1, "K")], index)
    assert matched == []
    assert ambiguous == [1]
    assert unmatched == []
