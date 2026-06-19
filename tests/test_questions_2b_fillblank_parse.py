import pytest

from courses import fillblank
from courses.fillblank import FillBlankError


def test_parse_basic_and_alternates():
    token_stem, blanks = fillblank.parse("The capital is {{Paris|paris}}.")
    assert blanks == [["Paris", "paris"]]
    assert token_stem == "The capital is ￿0￿."


def test_parse_multiple_and_adjacent():
    _, blanks = fillblank.parse("{{a}} and {{b}}{{c}}")
    assert blanks == [["a"], ["b"], ["c"]]


def test_parse_drops_blank_pieces():
    _, blanks = fillblank.parse("x {{a|}}")
    assert blanks == [["a"]]


@pytest.mark.parametrize("stem", ["{{}}", "{{|}}", "no markers here", "open {{ only"])
def test_parse_rejects(stem):
    with pytest.raises(FillBlankError):
        fillblank.parse(stem)


def test_parse_skips_balanced_math_braces():
    # {{ inside balanced \(...\) is LaTeX, not a marker; a real blank still parses.
    token_stem, blanks = fillblank.parse(r"\(x^{{2}}\) equals {{four}}")
    assert blanks == [["four"]]
    assert r"\(x^{{2}}\)" in token_stem  # math restored verbatim
    assert "￿0￿" in token_stem


def test_parse_unbalanced_math_does_not_swallow_markers():
    # An unterminated \( stays literal; the marker after it is still found.
    _, blanks = fillblank.parse(r"open \( math {{gap}}")
    assert blanks == [["gap"]]


def test_parse_markers_are_single_line():
    with pytest.raises(FillBlankError):
        fillblank.parse("{{a\nb}}")  # newline inside marker → unterminated


def test_strip_sentinel_removes_uffff():
    assert fillblank.strip_sentinel("a￿0￿b") == "a0b"


def test_render_inputs_interleaves_and_escapes():
    html = fillblank.render_inputs("A ￿0￿ B ￿1￿", ["x", '"y"'])
    assert html.count("<input") == 2
    assert "A " in html and " B " in html
    assert "&quot;y&quot;" in html  # value escaped
    assert 'name="blank"' in html


def test_render_inputs_defensive_on_short_values():
    html = fillblank.render_inputs("￿0￿ ￿1￿", ["only"])
    assert html.count("<input") == 2  # missing index → empty value, no IndexError
