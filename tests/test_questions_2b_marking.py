from decimal import Decimal

import pytest

from courses.marking import normalize_text
from courses.marking import parse_number


def test_normalize_text_trims_collapses_and_casefolds():
    assert normalize_text("  Hello   World ") == "hello world"
    assert normalize_text("ŁÓDŹ") == "łódź"
    assert normalize_text("a\tb\nc") == "a b c"


def test_normalize_text_case_sensitive_keeps_case_but_still_trims():
    assert normalize_text("  Foo  Bar ", case_sensitive=True) == "Foo Bar"
    assert normalize_text("Foo", case_sensitive=True) != normalize_text("foo")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3,14", Decimal("3.14")),
        ("3.14", Decimal("3.14")),
        ("-3,14", Decimal("-3.14")),
        ("+5", Decimal("5")),
        (".5", Decimal("0.5")),
        (",5", Decimal("0.5")),
        ("-.5", Decimal("-0.5")),
        ("1,234", Decimal("1.234")),
        ("  42 ", Decimal("42")),
        ("5,", None),
        ("5.", None),
        (".", None),
        ("1 234", None),
        ("- 5", None),
        ("3 ,14", None),
        ("1,2,3", None),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_number_grammar(raw, expected):
    assert parse_number(raw) == expected
