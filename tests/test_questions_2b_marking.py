from decimal import Decimal
from fractions import Fraction

import pytest

from courses.marking import TOO_LONG
from courses.marking import blank_matches
from courses.marking import canonical_numeric_text
from courses.marking import canonical_tolerance_text
from courses.marking import normalize_text
from courses.marking import parse_number
from courses.marking import parse_numeric_value


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


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Plain decimals still parse — same grammar as parse_number, exact value.
        ("0.5", Fraction(1, 2)),
        ("0,5", Fraction(1, 2)),
        ("3.140", Fraction(157, 50)),
        ("42", Fraction(42)),
        # Fractions, the new form.
        ("1/2", Fraction(1, 2)),
        ("-1/2", Fraction(-1, 2)),
        ("+3/4", Fraction(3, 4)),
        ("2/4", Fraction(1, 2)),  # value equality, not simplest-form equality
        ("1 / 2", Fraction(1, 2)),  # spaces around the slash are an unambiguous token
        ("10/5", Fraction(2)),
        # Mixed numbers: the space is what separates the whole part.
        ("1 1/2", Fraction(3, 2)),
        ("1  1/2", Fraction(3, 2)),
        ("1 1 / 2", Fraction(3, 2)),
        ("-1 1/2", Fraction(-3, 2)),  # sign applies to the WHOLE quantity
        ("+2 3/4", Fraction(11, 4)),
        ("2 0/3", Fraction(2)),
        ("11/2", Fraction(11, 2)),  # NO space → eleven halves, never 1 + 1/2
        # Rejected forms.
        ("1/0", None),  # zero denominator must not raise
        ("0/0", None),
        ("1 1/0", None),
        ("1/", None),
        ("/2", None),
        ("1/2/3", None),
        ("1 1/2/3", None),
        ("1.5/2", None),  # decimal numerator out of scope
        ("1 1.5/2", None),
        ("1.5 1/2", None),  # decimal whole part out of scope
        ("1/-2", None),  # sign belongs in front, not on the denominator
        ("1 -1/2", None),  # ...nor in the middle of a mixed number
        ("1 2 1/2", None),
        ("a/b", None),
        ("and/or", None),
        ("", None),
    ],
)
def test_parse_numeric_value_grammar(raw, expected):
    assert parse_numeric_value(raw) == expected


def test_parse_number_still_rejects_fractions():
    # The Decimal-returning parser is the persistence path (short-numeric value,
    # guess-the-number target). It must stay lossless, so fractions stay out.
    assert parse_number("1/2") is None


def test_blank_matches_fraction_and_decimal_are_equal():
    # The unit-207 case: an authored "1/2" accepts a decimal entry, either separator.
    assert blank_matches("0.5", ["1/2"]) is True
    assert blank_matches("0,5", ["1/2"]) is True
    # ...and symmetrically, an authored decimal accepts a fraction.
    assert blank_matches("1/2", ["0.5"]) is True
    assert blank_matches("2/4", ["1/2"]) is True
    assert blank_matches("1/3", ["1/3"]) is True
    assert blank_matches("-1/2", ["-0.5"]) is True
    # Exact rational equality: a truncated decimal is NOT the fraction.
    assert blank_matches("0.333", ["1/3"]) is False
    assert blank_matches("1/3", ["1/2"]) is False


def test_blank_matches_mixed_numbers():
    # An authored mixed number accepts the decimal and the improper fraction...
    assert blank_matches("1,5", ["1 1/2"]) is True
    assert blank_matches("1.5", ["1 1/2"]) is True
    assert blank_matches("3/2", ["1 1/2"]) is True
    # ...and symmetrically a student may answer an authored decimal that way.
    assert blank_matches("1 1/2", ["1.5"]) is True
    assert blank_matches("-1 1/2", ["-1.5"]) is True
    assert blank_matches("1 1/2", ["2.5"]) is False


def test_blank_matches_fraction_does_not_cross_match_text():
    # A slash in a text answer must not drag it into the numeric branch.
    assert blank_matches("and/or", ["and/or"]) is True
    assert blank_matches("0.5", ["and/or"]) is False
    assert blank_matches("1/2", ["one half"]) is False
    assert blank_matches("1/0", ["1/0"]) is True  # unparseable both sides → text


def test_blank_matches_text_and_whitespace():
    # Redundant surrounding/internal whitespace is collapsed on both sides.
    assert blank_matches("  paris ", ["Paris"]) is True
    assert blank_matches("hello   world", ["hello world"]) is True
    assert blank_matches("Rhine", ["Seine", "seine"]) is False
    assert blank_matches("", ["Paris"]) is False  # empty never matches


def test_blank_matches_case_sensitive():
    assert blank_matches("na", ["Na"], case_sensitive=True) is False
    assert blank_matches("Na", ["Na"], case_sensitive=True) is True


def test_blank_matches_numeric_value_equality():
    # Comma/dot interchangeable, trailing zeros and sign irrelevant — value equality.
    assert blank_matches("3,14", ["3.14"]) is True
    assert blank_matches("3.14", ["3,14"]) is True
    assert blank_matches("3.140", ["3.14"]) is True
    assert blank_matches("+5", ["5"]) is True
    assert blank_matches(",5", ["0.5"]) is True
    assert blank_matches("3,15", ["3.14"]) is False  # different values


def test_blank_matches_numeric_branch_only_when_both_parse():
    # A number must not cross-match a text answer that merely starts with digits.
    assert blank_matches("5", ["5 apples"]) is False
    assert blank_matches("five", ["5"]) is False
    # Mixed accepted list: numeric input matches the numeric alternative.
    assert blank_matches("2,0", ["two", "2"]) is True


@pytest.mark.django_db
def test_fillblank_mark_accepts_comma_for_dot_authored_number():
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    q = FillBlankQuestionElement.objects.create(stem="ignored-for-mark")
    Blank.objects.create(question=q, accepted="3.14")
    Blank.objects.create(question=q, accepted="Paris")

    result = q.mark(["3,14", "  paris "])
    assert result.correct is True and result.fraction == pytest.approx(1.0)


@pytest.mark.django_db
def test_fillblank_mark_accepts_decimal_for_fraction_authored_answer():
    # Mirrors unit 207's log_9 3 blank, authored as "1/2".
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    q = FillBlankQuestionElement.objects.create(stem="ignored-for-mark")
    Blank.objects.create(question=q, accepted="1/2")

    assert q.mark(["0.5"]).correct is True
    assert q.mark(["0,5"]).correct is True
    assert q.mark(["1/2"]).correct is True
    assert q.mark(["0.6"]).correct is False


@pytest.mark.django_db
def test_shorttext_mark_multi_answer_normalized():
    from courses.models import ShortTextQuestionElement

    q = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of France?</p>", accepted="Paris\nParyż"
    )
    assert q.mark("  paris ").correct is True
    assert q.mark("PARYŻ").correct is True
    assert q.mark("London").correct is False
    assert q.mark("London").fraction == 0.0
    assert q.mark("").correct is False  # empty → incorrect
    assert q.mark("Paris").reveal  # representative answer present on both verdicts


@pytest.mark.django_db
def test_shorttext_case_sensitive():
    from courses.models import ShortTextQuestionElement

    q = ShortTextQuestionElement.objects.create(accepted="Na", case_sensitive=True)
    assert q.mark("Na").correct is True
    assert q.mark("na").correct is False


@pytest.mark.django_db
def test_shortnumeric_mark_tolerance_and_decimal_comma():
    from decimal import Decimal

    from courses.models import ShortNumericQuestionElement

    q = ShortNumericQuestionElement.objects.create(
        value=Decimal("3.14"), tolerance=Decimal("0.01")
    )
    assert q.mark("3,15").correct is True  # within tolerance, comma decimal
    assert q.mark("3.13").correct is True  # at the boundary
    assert q.mark("3.20").correct is False
    assert q.mark("abc").correct is False  # unparseable → incorrect
    assert q.mark("").correct is False
    exact = ShortNumericQuestionElement.objects.create(value=Decimal("2"))
    assert exact.mark("2").correct is True and exact.mark("2.0001").correct is False


@pytest.mark.django_db
def test_fillblank_mark_per_blank_and_fraction():
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    q = FillBlankQuestionElement.objects.create(stem="ignored-for-mark")
    Blank.objects.create(question=q, accepted="Paris")
    Blank.objects.create(question=q, accepted="Seine\nseine")

    full = q.mark(["paris", "Seine"])
    assert full.correct is True and full.fraction == pytest.approx(1.0)
    partial = q.mark(["paris", "Rhine"])
    assert partial.correct is False and partial.fraction == pytest.approx(0.5)
    # short list padded with "" → those blanks wrong
    assert q.mark(["paris"]).correct is False
    # long list truncated to n_blanks (extra entries ignored, still all-correct)
    assert q.mark(["paris", "Seine", "extra"]).correct is True
    # reveal is an ordered per-blank summary with the first accepted piece
    rev = list(partial.reveal)
    assert rev[0]["index"] == 0 and rev[0]["correct"] is True
    assert rev[1]["correct"] is False and rev[1]["accepted"] == "Seine"


@pytest.mark.django_db
def test_build_answer_shapes():
    from django.http import QueryDict

    from courses.models import Blank
    from courses.models import FillBlankQuestionElement
    from courses.models import ShortNumericQuestionElement
    from courses.models import ShortTextQuestionElement

    post = QueryDict(mutable=True)
    post["answer"] = "  foo "
    post.setlist("blank", ["a", "b"])
    assert ShortTextQuestionElement().build_answer(post) == "  foo "
    assert ShortNumericQuestionElement().build_answer(post) == "  foo "
    fb = FillBlankQuestionElement.objects.create(stem="x")
    Blank.objects.create(question=fb, accepted="a")
    assert fb.build_answer(post) == ["a", "b"]


@pytest.mark.django_db
def test_new_types_in_element_models():
    from courses.models import ELEMENT_MODELS

    for name in (
        "shorttextquestionelement",
        "shortnumericquestionelement",
        "fillblankquestionelement",
    ):
        assert name in ELEMENT_MODELS


def test_parse_numeric_value_rejects_over_long_input_instead_of_raising():
    # Pre-existing crash: int() on >4300 digits raises ValueError under CPython >=3.11,
    # and this parser runs on student input via blank_matches.
    from courses.marking import parse_numeric_value

    assert parse_numeric_value("1" * 5000 + "/2") is None


def test_parse_numeric_value_accepts_100_chars_so_fill_blank_is_not_narrowed():
    # Pins the 256 comparison cap, NOT the 64 storage cap. Collapsing the two
    # constants would silently stop 65-4300 char numbers matching in fill-blank.
    from fractions import Fraction

    from courses.marking import parse_numeric_value

    assert parse_numeric_value("1" * 100) == Fraction(int("1" * 100))


def test_parse_numeric_value_coerces_decimal_without_e_notation():
    from decimal import Decimal
    from fractions import Fraction

    from courses.marking import parse_numeric_value

    assert parse_numeric_value(Decimal("1.5")) == Fraction(3, 2)
    # str(Decimal("0.00000000")) is '0E-8', which no grammar matches.
    assert parse_numeric_value(Decimal("0.00000000")) == Fraction(0)


def test_parse_numeric_value_coerces_json_floats_without_e_notation():
    from fractions import Fraction

    from courses.marking import parse_numeric_value

    assert parse_numeric_value(2.5) == Fraction(5, 2)
    # str(0.00001) is '1e-05'.
    assert parse_numeric_value(0.00001) == Fraction(1, 100000)
    # Decimal(0.1) is 55 digits of binary noise; Decimal(str(0.1)) is not.
    assert parse_numeric_value(0.1) == Fraction(1, 10)


def test_parse_numeric_value_rejects_bool_without_raising():
    # isinstance(True, int) is True; Decimal("True") raises InvalidOperation.
    from courses.marking import parse_numeric_value

    assert parse_numeric_value(True) is None


def test_parse_number_did_not_get_a_length_guard():
    # PINNING TEST — green before and after, and that is the point: it must stay
    # green while parse_numeric_value gains its guard. Its mutant is not a change
    # to this task's diff but a plausible FUTURE one: adding the same length guard
    # to parse_number would regress views.py:1162 and element_forms.py:314/338.
    from decimal import Decimal

    from courses.marking import parse_number

    assert parse_number("9" * 5000) == Decimal("9" * 5000)


def test_format_decimal_plain_keeps_precision_and_avoids_exponent():
    from decimal import Decimal

    from courses.marking import format_decimal_plain

    assert format_decimal_plain(Decimal("40401.00000000")) == "40401"
    assert format_decimal_plain(Decimal("0.10000000")) == "0.1"
    assert format_decimal_plain(Decimal("0.00000000")) == "0"
    # Default context precision is 28; without localcontext this returns "0.1".
    long_value = "0.1000000000000000000000000000000001"
    assert format_decimal_plain(Decimal(long_value)) == long_value


def test_format_target_inherits_the_raised_precision():
    # NOT a delegation test: format_target on master is ALREADY
    # format(Decimal(target).normalize(), "f"), so asserting on 40401 passes with
    # or without the delegation and could never fail. The >28-digit value is the
    # only assertion that distinguishes the two, because it needs the localcontext
    # that only the shared helper has.
    from decimal import Decimal

    from courses.guessnumber import format_target

    long_value = "0.1000000000000000000000000000000001"
    assert format_target(Decimal(long_value)) == long_value


# Every row of the spec's canonicalisation table. Do not trim this list.
CANONICAL_ROWS = [
    ("1,5", "1.5"),
    ("1.50", "1.5"),
    ("0.10000000", "0.1"),
    ("40401.00000000", "40401"),
    (" 3 / 2 ", "3/2"),
    ("1  1/2", "1 1/2"),
    ("+7", "7"),
    ("+3/2", "3/2"),
    ("-0.50", "-0.5"),
    ("06/4", "6/4"),
    ("-06/4", "-6/4"),
    ("1 0/2", "1 0/2"),
    ("-1 1/2", "-1 1/2"),
    ("+1 1/2", "1 1/2"),
    (".5", "0.5"),
    (",5", "0.5"),
    ("-.5", "-0.5"),
    ("+,5", "0.5"),
    ("-0 1/2", "-0 1/2"),
    ("0", "0"),
    ("00", "0"),
    ("-0", "0"),
    ("-0.0", "0"),
    ("0/4", "0"),
    ("00/4", "0"),
    ("-0/4", "0"),
    ("0 0/4", "0"),
    ("-0 0/4", "0"),
]

REJECTED_ROWS = ["1/0", "1 1/0", "abc", "", "1" * 65]


@pytest.mark.parametrize("raw,expected", CANONICAL_ROWS)
def test_canonical_numeric_text_table(raw, expected):
    assert canonical_numeric_text(raw) == expected


@pytest.mark.parametrize("raw", REJECTED_ROWS)
def test_canonical_numeric_text_rejects(raw):
    assert canonical_numeric_text(raw) is None


@pytest.mark.parametrize("raw", ["." + "1" * 63, "," + "1" * 63, "-." + "1" * 62])
def test_canonical_numeric_text_rejects_output_overflow(raw):
    # 64 chars in, 65 chars out. Only reachable because format_decimal_plain
    # raises the precision; in the default 28-digit context this canonicalises
    # to 30 chars and fits.
    assert len(raw) == 64
    assert canonical_numeric_text(raw) is TOO_LONG


def test_canonical_numeric_text_preserves_long_precision():
    long_value = "0.1000000000000000000000000000000001"
    assert canonical_numeric_text(long_value) == long_value


@pytest.mark.parametrize("raw,expected", CANONICAL_ROWS)
def test_canonical_numeric_text_round_trips_and_is_idempotent(raw, expected):
    # Excludes the None/TOO_LONG rows by construction: feeding a sentinel back
    # in is not a meaningful round-trip.
    assert parse_numeric_value(expected) == parse_numeric_value(raw)
    assert canonical_numeric_text(expected) == expected


def test_canonical_numeric_text_accepts_json_numbers():
    # The LAL manifest is json.loads'd, so these reach the canonicaliser directly.
    assert canonical_numeric_text(2.5) == "2.5"
    assert canonical_numeric_text(0.00001) == "0.00001"
    assert canonical_numeric_text(True) is None


def test_canonical_tolerance_text_collapses_every_zero_to_empty():
    for raw in ["", "0", "0.00000000", "0/5", "-0", 0, 0.0]:
        assert canonical_tolerance_text(raw) == ""


def test_canonical_tolerance_text_keeps_positive_and_rejects_negative():
    assert canonical_tolerance_text("1/100") == "1/100"
    assert canonical_tolerance_text("0,01") == "0.01"
    assert canonical_tolerance_text(0.00001) == "0.00001"
    assert canonical_tolerance_text("-1") is None
    assert canonical_tolerance_text("abc") is None
    assert canonical_tolerance_text("." + "1" * 63) is TOO_LONG
