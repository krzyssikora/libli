"""Pure helpers for Fill-in table inline gaps (spec §2, §4). No DB."""

import pytest

from courses.fillblank import FillBlankError
from courses.filltable import MAX_GAPS_PER_CELL
from courses.filltable import GapMathError
from courses.filltable import author_cell_html
from courses.filltable import gap_cells
from courses.filltable import parse_cell_gaps
from courses.filltable import reconcile_gaps

S = "￿"


def tok(n):
    return f"{S}{n}{S}"


# --- parse_cell_gaps ---------------------------------------------------------


def test_one_gap_before_maths():
    assert parse_cell_gaps(r"{{9}} \(\pi\)") == (tok(0) + r" \(\pi\)", [["9"]])


def test_two_gaps_between_maths():
    h, gaps = parse_cell_gaps(r"\((x+2)^2+(y\) {{-1}} \()^2=\) {{16}}")
    assert h == r"\((x+2)^2+(y\) " + tok(0) + r" \()^2=\) " + tok(1)
    assert gaps == [["-1"], ["16"]]


def test_braces_inside_maths_stay_literal():
    src = r"\(\frac{{a}}{b}\) and {{2}}"
    h, gaps = parse_cell_gaps(src)
    assert h == r"\(\frac{{a}}{b}\) and " + tok(0)
    assert gaps == [["2"]]


def test_alternatives_trimmed():
    assert parse_cell_gaps("{{ 9 | 9,0 }}") == (tok(0), [["9", "9,0"]])


def test_no_markers_is_not_an_error():
    assert parse_cell_gaps("plain <b>text</b>") == ("plain <b>text</b>", [])


def test_lt_in_answer_is_decoded():
    # sanitised html arrives with `<` escaped
    assert parse_cell_gaps("{{a&lt;b}}") == (tok(0), [["a<b"]])


@pytest.mark.parametrize(
    "src",
    [
        "{{<b>9</b>}}",
        '{{<span class="tc-red">9</span>}}',
        '{{<span title="a>b">9</span>}}',
    ],
)
def test_markup_inside_marker_is_stripped(src):
    assert parse_cell_gaps(src)[1] == [["9"]]


def test_straddling_tag_keeps_answer():
    h, gaps = parse_cell_gaps("<b>{{9</b>}}")
    assert gaps == [["9"]]
    assert h == "<b>" + tok(0)  # unbalanced; save() re-sanitises (Task 2)


def test_split_brace_pair_is_literal():
    assert parse_cell_gaps("{<b>{</b>9}}") == ("{<b>{</b>9}}", [])


@pytest.mark.parametrize("src", ["{{}}", "{{ | }}", "{{9", "a {{9 b"])
def test_empty_or_unclosed_raises_plain_error(src):
    with pytest.raises(FillBlankError) as exc:
        parse_cell_gaps(src)
    assert not isinstance(exc.value, GapMathError)


def test_maths_inside_marker_raises_gap_math_error():
    with pytest.raises(GapMathError):
        parse_cell_gaps(r"{{9\(\pi\)}}")


def test_maths_overlapping_marker_end_reports_unclosed():
    with pytest.raises(FillBlankError) as exc:
        parse_cell_gaps(r"{{9\(x}}\)")
    assert not isinstance(exc.value, GapMathError)


def test_existing_sentinel_is_stripped_before_parse():
    assert parse_cell_gaps("a" + tok(0) + "{{1}}") == ("a0" + tok(0), [["1"]])


# --- author_cell_html + idempotence -----------------------------------------


def test_author_html_restores_markers_and_escapes():
    cell = {"html": tok(0) + r" \(\pi\)", "gaps": [["9", "9,0"]]}
    assert author_cell_html(cell) == r"{{9|9,0}} \(\pi\)"
    assert author_cell_html({"html": tok(0), "gaps": [["a<b"]]}) == "{{a&lt;b}}"


def test_author_html_identity_without_gaps():
    assert author_cell_html({"html": "x" + tok(0)}) == "x" + tok(0)
    assert author_cell_html({"html": "x"}) == "x"


@pytest.mark.parametrize(
    "src",
    [
        "{{9}}",
        r"{{9}} \(\pi\)",
        r"\((x+2)^2+(y\) {{-1}} \()^2=\) {{16}}",
        r"\(\frac{{a}}{b}\) {{2}}",
        "{{ 9 | 9,0 }}",
        "{{a&lt;b}}",
        "no gaps",
    ],
)
def test_parse_author_parse_is_idempotent(src):
    h, gaps = parse_cell_gaps(src)
    again = parse_cell_gaps(author_cell_html({"html": h, "gaps": gaps}))
    assert again == (h, gaps)


# --- reconcile_gaps (§4) -----------------------------------------------------


def test_reconcile_clean_input_unchanged():
    assert reconcile_gaps(tok(0) + tok(1), [["a"], ["b"]]) == (
        tok(0) + tok(1),
        [["a"], ["b"]],
    )


def test_reconcile_entry_cleaning():
    h, g = reconcile_gaps(tok(0), [[" a ", "", 3, "b"]])
    assert (h, g) == (tok(0), [["a", "b"]])


def test_reconcile_non_list_entry_is_empty_and_token_removed():
    assert reconcile_gaps("x" + tok(0) + "y", ["nope"]) == ("xy", [])


def test_reconcile_duplicate_token_keeps_first():
    assert reconcile_gaps(tok(0) + "-" + tok(0), [["a"]]) == (tok(0) + "-", [["a"]])


def test_reconcile_orphan_token_removed():
    assert reconcile_gaps(tok(0) + tok(5), [["a"]]) == (tok(0), [["a"]])


def test_reconcile_orphan_entry_dropped():
    assert reconcile_gaps(tok(0), [["a"], ["b"]]) == (tok(0), [["a"]])


def test_reconcile_renumbers_in_document_order():
    assert reconcile_gaps(tok(1) + tok(0), [["a"], ["b"]]) == (
        tok(0) + tok(1),
        [["b"], ["a"]],
    )


def test_reconcile_truncates_to_cap():
    n = MAX_GAPS_PER_CELL + 2
    h, g = reconcile_gaps(
        "".join(tok(i) for i in range(n)), [[str(i)] for i in range(n)]
    )
    assert len(g) == MAX_GAPS_PER_CELL
    assert h == "".join(tok(i) for i in range(MAX_GAPS_PER_CELL))


def test_reconcile_all_removed_returns_empty_list():
    assert reconcile_gaps("x", [["a"]]) == ("x", [])


@pytest.mark.parametrize("bad", [None, "str", 5, {"a": 1}])
def test_reconcile_non_list_gaps(bad):
    assert reconcile_gaps("x" + tok(0), bad) == ("x", [])


def test_reconcile_non_string_html():
    assert reconcile_gaps(None, [["a"]]) == ("", [])


def test_reconcile_is_idempotent():
    once = reconcile_gaps(tok(2) + tok(0) + tok(0), [["a"], [" "], ["c"]])
    assert reconcile_gaps(*once) == once


# --- gap_cells ---------------------------------------------------------------


def test_gap_cells_yields_lists_for_static_cells_only():
    cells = [
        [{"kind": "static", "html": tok(0) + tok(1), "gaps": [["a"], ["b", "B"]]}],
        [{"kind": "answer", "answer": "x", "gaps": [["no"]]}, {"kind": "static"}],
    ]
    assert list(gap_cells(cells)) == [(0, 0, 0, ["a"]), (0, 0, 1, ["b", "B"])]
