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
