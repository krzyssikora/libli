from decimal import Decimal

import pytest

from courses import fillblank
from courses import guessnumber
from courses.guessnumber import GuessNumberError


def test_parse_stem_extracts_target_and_tokenises():
    token_stem, raw = guessnumber.parse_stem(r"\(201^2=\){{40401}}")
    assert raw == "40401"
    assert token_stem == r"\(201^2=\)" + guessnumber.SENTINEL_TOKEN


def test_parse_stem_rejects_zero_tokens():
    with pytest.raises(GuessNumberError) as e:
        guessnumber.parse_stem("no token here")
    assert e.value.code == "token_count"


def test_parse_stem_rejects_two_tokens():
    with pytest.raises(GuessNumberError) as e:
        guessnumber.parse_stem("{{1}} and {{2}}")
    assert e.value.code == "token_count"


def test_parse_stem_rejects_alternatives_pipe():
    with pytest.raises(GuessNumberError) as e:
        guessnumber.parse_stem("{{40401|40402}}")
    assert e.value.code == "alternatives"


def test_parse_stem_masks_math_so_katex_braces_are_not_tokens():
    # \text{{x}} must NOT be read as a token; the real token is {{5}}.
    token_stem, raw = guessnumber.parse_stem(r"\(\text{{x}}\){{5}}")
    assert raw == "5"
    assert token_stem.count(guessnumber.SENTINEL_TOKEN) == 1


def test_error_code_is_positional_not_kwarg():
    # ValueError accepts no kwargs; the code must be a positional param.
    assert GuessNumberError("token_count").code == "token_count"


@pytest.mark.parametrize(
    "stored,expected",
    [
        (Decimal("40401.00000000"), "40401"),  # trailing zeros dropped
        (Decimal("40401.50000000"), "40401.5"),
        (Decimal("0.00000000"), "0"),
        (Decimal("40401"), "40401"),  # would normalize to 4.0401E+4
        (Decimal("-5"), "-5"),  # sign preserved
        (Decimal("0.12345678"), "0.12345678"),  # 8 dp survive
    ],
)
def test_format_target_is_fixed_point_never_exponent(stored, expected):
    assert guessnumber.format_target(stored) == expected


def test_to_author_stem_round_trips_the_token():
    token_stem, _ = guessnumber.parse_stem(r"\(201^2=\){{40401}}")
    assert guessnumber.to_author_stem(token_stem, Decimal("40401.00000000")) == (
        r"\(201^2=\){{40401}}"
    )


def test_sentinel_token_matches_fillblanks_sentinel():
    assert guessnumber.SENTINEL_TOKEN == fillblank.SENTINEL + "0" + fillblank.SENTINEL
