from decimal import Decimal

import pytest

from courses import guessnumber
from courses.element_forms import GuessNumberElementForm
from courses.models import GuessNumberElement  # noqa: F401 — brief's import surface


def _data(stem=r"\(201^2=\){{40401}}", tolerance="", success_message=""):
    return {"stem": stem, "tolerance": tolerance, "success_message": success_message}


@pytest.mark.django_db
def test_valid_form_assigns_target_from_the_token():
    form = GuessNumberElementForm(_data())
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.target == Decimal("40401")
    assert el.stem.count(guessnumber.SENTINEL_TOKEN) == 1


@pytest.mark.django_db
def test_blank_tolerance_saves_as_zero():
    form = GuessNumberElementForm(_data(tolerance=""))
    assert form.is_valid(), form.errors
    assert form.save().tolerance == Decimal("0")


@pytest.mark.django_db
def test_polish_comma_tolerance_is_accepted():
    # The same form accepts {{40401,5}} in the token; rejecting "0,5" here
    # would be incoherent. Plain ModelForm over a DecimalField does reject it.
    form = GuessNumberElementForm(_data(tolerance="0,5"))
    assert form.is_valid(), form.errors
    assert form.save().tolerance == Decimal("0.5")


@pytest.mark.django_db
def test_negative_tolerance_rejected():
    form = GuessNumberElementForm(_data(tolerance="-1"))
    assert not form.is_valid()
    assert "tolerance" in form.errors


@pytest.mark.django_db
def test_comma_token_parses_and_canonicalises_on_re_edit():
    form = GuessNumberElementForm(_data(stem="{{40401,5}}"))
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.target == Decimal("40401.5")
    assert GuessNumberElementForm(instance=el).initial["stem"] == "{{40401.5}}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "typed,re_rendered", [("{{+5}}", "{{5}}"), ("{{-5}}", "{{-5}}")]
)
def test_sign_round_trip_through_the_form(typed, re_rendered):
    # §2.6's sign policy end-to-end: parse_number's _NUM_RE accepts a leading
    # sign, so a redundant + is dropped and - is preserved. Task 2 only unit-tests
    # format_target; this crosses the whole form path.
    el = GuessNumberElementForm(_data(stem=typed)).save()
    el.refresh_from_db()
    assert GuessNumberElementForm(instance=el).initial["stem"] == re_rendered


@pytest.mark.django_db
def test_editing_shows_author_token_not_the_raw_sentinel_stem():
    el = GuessNumberElementForm(_data()).save()
    initial = GuessNumberElementForm(instance=el).initial["stem"]
    assert initial == r"\(201^2=\){{40401}}"


@pytest.mark.django_db
def test_editing_formats_tolerance_initial_not_raw_decimal():
    el = GuessNumberElementForm(_data(tolerance="0,5")).save()
    el.refresh_from_db()
    assert GuessNumberElementForm(instance=el).initial["tolerance"] == "0.5"


@pytest.mark.django_db
@pytest.mark.parametrize("stem", ["no token", "{{1}} {{2}}"])
def test_token_count_errors(stem):
    form = GuessNumberElementForm(_data(stem=stem))
    assert not form.is_valid()
    assert "stem" in form.errors


@pytest.mark.django_db
def test_pipe_alternatives_error_is_distinct_from_token_count_error():
    pipe = GuessNumberElementForm(_data(stem="{{40401|40402}}"))
    none = GuessNumberElementForm(_data(stem="no token"))
    assert not pipe.is_valid() and not none.is_valid()
    # list(...): ErrorList's `!=` is unreliable — it inherits from both UserList
    # (which holds messages in .data) and list (whose real storage UserList never
    # populates), so `list.__ne__` wins in the MRO and always compares two empty
    # sequences, making `a != b` False for ANY two ErrorLists regardless of
    # content. Converting to plain lists first compares the actual messages.
    assert list(pipe.errors["stem"]) != list(none.errors["stem"])  # distinct per code


@pytest.mark.django_db
def test_non_numeric_token_rejected():
    form = GuessNumberElementForm(_data(stem="{{abc}}"))
    assert not form.is_valid()


@pytest.mark.django_db
def test_twelve_integer_digits_ok_thirteen_rejected():
    # check_decimal_str's real bound is max_digits - decimal_places = 12.
    assert GuessNumberElementForm(_data(stem="{{" + "1" * 12 + "}}")).is_valid()
    form = GuessNumberElementForm(_data(stem="{{" + "1" * 13 + "}}"))
    assert not form.is_valid()  # a form error, NOT a DB DataError
    assert "stem" in form.errors


@pytest.mark.django_db
def test_nine_decimal_places_rejected_not_silently_rounded():
    form = GuessNumberElementForm(_data(stem="{{0.123456789}}"))
    assert not form.is_valid()


@pytest.mark.django_db
def test_sentinel_in_prose_is_stripped_before_parse():
    form = GuessNumberElementForm(_data(stem=guessnumber.SENTINEL_TOKEN + " {{5}}"))
    assert form.is_valid(), form.errors
    # exactly one token survives — the forged one was stripped
    assert form.save().stem.count(guessnumber.SENTINEL_TOKEN) == 1
