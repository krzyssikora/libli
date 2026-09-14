"""courses.answer_summary (spec §4; tests T32, T33, T34)."""

import pytest

from courses.answer_summary import ANSWER
from courses.answer_summary import KEYWORD
from courses.answer_summary import Part
from courses.models import Choice
from courses.models import QuestionElement
from tests.answer_summary_fixtures import build_all_types
from tests.answer_summary_fixtures import summarise_stored

pytestmark = pytest.mark.django_db
REVIEW = QuestionElement.MarkingMode.REVIEW


def _answer(given, expected, ok, label=None, label_is_content=False):
    return Part(
        kind=ANSWER,
        label_is_content=label_is_content,
        label=label,
        given=given,
        expected=expected,
        ok=ok,
    )


def _pks(q, *texts):
    return sorted(c.pk for c in q.choices.all() if c.text in texts)


# --- choice ------------------------------------------------------------------
def test_choice_correct_wrong_unanswered():
    q = build_all_types()["choice"]
    assert summarise_stored(q, _pks(q, "2", "3")) == [_answer("2, 3", None, True)]
    assert summarise_stored(q, _pks(q, "2", "4")) == [_answer("2, 4", "2, 3", False)]
    assert summarise_stored(q, None, unanswered=True) == [_answer(None, "2, 3", False)]


def test_choice_single_select():
    q = build_all_types()["choice"]
    q.multiple = False
    q.save()
    assert summarise_stored(q, _pks(q, "4")) == [_answer("4", "2, 3", False)]


def test_choice_review_mode_has_no_expected_or_ok():
    q = build_all_types(mode=REVIEW)["choice"]
    assert summarise_stored(q, _pks(q, "4")) == [_answer("4", None, None)]


def test_choice_removed_option_appended_after_live_texts():
    q = build_all_types()["choice"]
    gone = Choice.objects.get(question=q, text="3")
    stored = sorted([gone.pk, *_pks(q, "2")])
    gone.delete()
    parts = summarise_stored(q, stored)
    assert parts[0].given == "2, (removed option)"


def test_choice_with_no_correct_option_expects_none_label():
    q = build_all_types()["choice"]
    Choice.objects.filter(question=q).update(is_correct=False)
    assert summarise_stored(q, _pks(q, "4")) == [_answer("4", "(none)", False)]


# --- shorttext / shortnumeric ------------------------------------------------
def test_shorttext_correct_wrong_unanswered_review():
    made = build_all_types()
    q = made["shorttext"]
    assert summarise_stored(q, "warsaw") == [_answer("warsaw", None, True)]
    assert summarise_stored(q, "Krakow") == [_answer("Krakow", "Warszawa", False)]
    assert summarise_stored(q, None, unanswered=True) == [
        _answer(None, "Warszawa", False)
    ]
    r = build_all_types(mode=REVIEW)["shorttext"]
    assert summarise_stored(r, "Krakow") == [_answer("Krakow", None, None)]


def test_shortnumeric_ok_is_read_from_mark_not_string_compare():
    q = build_all_types()["shortnumeric"]
    # "0,5" != "1/2" as strings, but mark() accepts it (spec T32 mutant).
    assert summarise_stored(q, "0,5") == [_answer("0,5", None, True)]
    assert summarise_stored(q, "3") == [_answer("3", "1/2", False)]


def test_shortnumeric_expected_carries_tolerance():
    q = build_all_types()["shortnumeric"]
    q.tolerance = "1/10"
    q.save()
    assert summarise_stored(q, "3")[0].expected == "1/2 ± 1/10"


# --- extendedresponse --------------------------------------------------------
def _kw(label, ok):
    return Part(
        kind=KEYWORD,
        label_is_content=False,
        label=label,
        given=None,
        expected=None,
        ok=ok,
    )


def test_extendedresponse_partial_text_part_is_not_ok():
    q = build_all_types()["extendedresponse"]
    parts = summarise_stored(q, "alpha only")
    assert parts == [
        _answer("alpha only", None, False),
        _kw("Required: alpha", True),
        _kw("Required: beta", False),
        _kw("Avoid: gamma", True),
    ]


def test_extendedresponse_unanswered_keyword_parts_are_unjudged():
    q = build_all_types()["extendedresponse"]
    assert summarise_stored(q, None, unanswered=True) == [
        _answer(None, None, False),
        _kw("Required: alpha", None),
        _kw("Required: beta", None),
        _kw("Avoid: gamma", None),
    ]


def test_extendedresponse_no_keywords_unanswered_is_still_not_ok():
    q = build_all_types()["extendedresponse"]
    q.required_keywords = ""
    q.forbidden_keywords = ""
    q.save()
    # mark_keywords("", [], []) is correct=True; rule 3 wins (spec §4.2).
    assert summarise_stored(q, None, unanswered=True) == [_answer(None, None, False)]


def test_extendedresponse_review_mode_keeps_keywords_but_emits_one_part():
    q = build_all_types(mode=REVIEW)["extendedresponse"]
    assert q.required_keywords  # stale keywords really are on the row
    assert summarise_stored(q, "some text") == [_answer("some text", None, None)]


# --- Part.mark: the glyph unit ----------------------------------------------
def test_part_mark_suppresses_tick_on_an_empty_answer_part():
    assert _answer(None, None, True).mark is None
    assert _answer(None, "x", False).mark == "incorrect"
    assert _answer("x", None, True).mark == "correct"
    assert _answer("x", None, None).mark is None
    assert _kw("Required: a", True).mark == "correct"
