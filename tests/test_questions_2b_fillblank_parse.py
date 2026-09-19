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


def test_to_author_stem_round_trips_a_simple_stem():
    # Inverse of parse(): the ￿n￿ tokens become {{answer}} again for editing.
    original = "Stolica Polski to {{Warszawa}} a Francji to {{Paryż}}"
    token_stem, blanks = fillblank.parse(original)
    assert fillblank.to_author_stem(token_stem, blanks) == original


def test_to_author_stem_rejoins_alternatives_with_pipe():
    original = "The capital is {{Paris|paris}}."
    token_stem, blanks = fillblank.parse(original)
    assert fillblank.to_author_stem(token_stem, blanks) == original


def test_to_author_stem_preserves_literal_math_braces():
    # {{2}} inside \(...\) is LaTeX, never a token, so it survives untouched.
    original = r"\(x^{{2}}\) equals {{four}}"
    token_stem, blanks = fillblank.parse(original)
    assert fillblank.to_author_stem(token_stem, blanks) == original


def test_render_inputs_interleaves_and_escapes():
    html = fillblank.render_inputs("A ￿0￿ B ￿1￿", ["x", '"y"'])
    assert html.count("<input") == 2
    assert "A " in html and " B " in html
    assert "&quot;y&quot;" in html  # value escaped
    assert 'name="blank"' in html


def test_render_inputs_defensive_on_short_values():
    html = fillblank.render_inputs("￿0￿ ￿1￿", ["only"])
    assert html.count("<input") == 2  # missing index → empty value, no IndexError


# The form sanitises the stem BEFORE parse() (element_forms.py), so an answer typed
# as `{{<}}` reaches parse() as `{{&lt;}}`. Answers are compared as PLAIN TEXT with
# what the student types (marking.blank_matches), so parse() must decode them --
# otherwise `<` can never be marked correct.
@pytest.mark.parametrize(
    ("typed", "expected"),
    [("<", "<"), (">", ">"), ("a & b", "a & b"), ("x<1", "x<1")],
)
def test_parse_decodes_the_sanitisers_entities_in_answers(typed, expected):
    from courses.sanitize import sanitize_html

    _, blanks = fillblank.parse(sanitize_html(f"sin a {{{{{typed}}}}} 0"))
    assert blanks == [[expected]]


def test_to_author_stem_re_escapes_decoded_answers():
    # The editor's stem is HTML: a raw "<" handed back would be eaten by nh3 on the
    # next save (an unclosed tag), so the inverse must re-escape what parse decoded.
    from courses.sanitize import sanitize_html

    original = sanitize_html("x {{<|a &amp; b}} y")
    token_stem, blanks = fillblank.parse(original)
    assert blanks == [["<", "a & b"]]
    assert fillblank.to_author_stem(token_stem, blanks) == original
