"""courses.answer_summary (spec §4; tests T32, T33, T34)."""

from types import SimpleNamespace

import pytest
from django.apps import apps

from courses import answer_summary
from courses.answer_summary import ANSWER
from courses.answer_summary import KEYWORD
from courses.answer_summary import Part
from courses.models import Choice
from courses.models import QuestionElement
from courses.quiz import answer_from_json
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


# --- choice (spec §5.1: T17, T17b, T17c, T18, T32) ---------------------------------
def _options(parts):
    assert len(parts) == 1 and parts[0].kind == answer_summary.OPTIONS
    return [(o.text, o.picked, o.correct, o.mark) for o in parts[0].options]


def test_t17_choice_picked_correct_and_wrong_and_missed():
    q = build_all_types()["choice"]
    assert _options(summarise_stored(q, _pks(q, "2", "3"))) == [
        ("2", True, True, "correct"),
        ("3", True, True, "correct"),
        ("4", False, False, None),
    ]
    parts = summarise_stored(q, _pks(q, "2", "4"))
    assert _options(parts) == [
        ("2", True, True, "correct"),
        ("3", False, True, "missed"),
        ("4", True, False, "wrong"),
    ]
    assert parts[0].options_auto is True
    assert parts[0].options_empty_key is False
    assert parts[0].mark is None  # no part-level glyph for a choice question


def test_t17_choice_not_answered_with_no_response_row():
    q = build_all_types()["choice"]
    assert _options(summarise_stored(q, None, unanswered=True)) == [
        ("2", False, True, "missed"),
        ("3", False, True, "missed"),
        ("4", False, False, None),
    ]


def test_t17_choice_single_select_renders_the_same_shape():
    q = build_all_types()["choice"]
    q.multiple = False
    q.save()
    assert _options(summarise_stored(q, _pks(q, "4"))) == [
        ("2", False, True, "missed"),
        ("3", False, True, "missed"),
        ("4", True, False, "wrong"),
    ]


def test_t17b_each_deleted_pick_is_its_own_row_last_and_unmarked():
    q = build_all_types()["choice"]
    gone = list(Choice.objects.filter(question=q, text__in=["3", "4"]))
    stored = sorted([*_pks(q, "2"), *(c.pk for c in gone)])
    for choice in gone:
        choice.delete()
    assert _options(summarise_stored(q, stored)) == [
        ("2", True, True, "correct"),
        ("(removed option)", True, None, None),
        ("(removed option)", True, None, None),
    ]


def test_t17c_summarise_demands_option_marks_for_a_choice_question():
    q = build_all_types(mode=REVIEW)["choice"]
    with pytest.raises(TypeError):
        answer_summary.summarise(q, None, None)
    parts = answer_summary.summarise(q, None, None, option_marks={})
    assert parts[0].kind == answer_summary.OPTIONS


def test_t18_non_auto_choice_has_no_key_and_no_verdicts():
    q = build_all_types(mode=REVIEW)["choice"]
    parts = summarise_stored(q, _pks(q, "4"))
    assert _options(parts) == [
        ("2", False, None, None),
        ("3", False, None, None),
        ("4", True, None, None),
    ]
    assert parts[0].options_auto is False
    assert parts[0].options_empty_key is False


def test_t32_auto_choice_with_an_empty_key_marks_every_pick_wrong():
    q = build_all_types()["choice"]
    Choice.objects.filter(question=q).update(is_correct=False)
    parts = summarise_stored(q, _pks(q, "4"))
    assert _options(parts) == [
        ("2", False, False, None),
        ("3", False, False, None),
        ("4", True, False, "wrong"),
    ]
    assert parts[0].options_empty_key is True


def test_t19b_choice_marks_come_from_the_caller_never_the_builder():
    q = build_all_types()["choice"]
    stored = _pks(q, "2")
    mark_result = q.mark(answer_from_json(q, stored))
    doctored = {c.pk: {"kind": "wrong"} for c in q.choices.all()}
    parts = answer_summary.summarise(
        q, SimpleNamespace(latest_answer=stored), mark_result, option_marks=doctored
    )
    assert [o.mark for o in parts[0].options] == ["wrong", "wrong", "wrong"]


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


# --- T34 drift guard ---------------------------------------------------------
def _derived_question_models():
    # issubclass only -- NOT also filtering _meta.abstract (spec §4.4, T34).
    return {m for m in apps.get_models() if issubclass(m, QuestionElement)}


def test_registry_covers_every_concrete_question_model():
    assert _derived_question_models() == set(answer_summary._ADAPTERS)


# --- fillblank ---------------------------------------------------------------
def _gap(i, given, expected, ok):
    return _answer(given, expected, ok, label=f"Gap {i}")


def test_fillblank_correct_partial_unanswered_review():
    q = build_all_types()["fillblank"]
    assert summarise_stored(q, ["2", "4"]) == [
        _gap(1, "2", None, True),
        _gap(2, "4", None, True),
    ]
    assert summarise_stored(q, ["2", "5"]) == [
        _gap(1, "2", None, True),
        _gap(2, "5", "4", False),
    ]
    assert summarise_stored(q, None, unanswered=True) == [
        _gap(1, None, "2", False),
        _gap(2, None, "4", False),
    ]
    r = build_all_types(mode=REVIEW)["fillblank"]
    assert summarise_stored(r, ["2", "5"]) == [
        _gap(1, "2", None, None),
        _gap(2, "5", None, None),
    ]


def test_fillblank_whitespace_gap_is_empty():
    q = build_all_types()["fillblank"]
    assert summarise_stored(q, ["2", "  "])[1] == _gap(2, None, "4", False)


def test_fillblank_fewer_and_more_stored_values_follow_current_blanks():
    q = build_all_types()["fillblank"]
    assert summarise_stored(q, ["2"]) == [
        _gap(1, "2", None, True),
        _gap(2, None, "4", False),
    ]
    assert len(summarise_stored(q, ["2", "4", "9"])) == 2


def test_fillblank_with_no_blanks_left_yields_no_parts():
    q = build_all_types()["fillblank"]
    q.blanks.all().delete()
    assert summarise_stored(q, ["2", "4"]) == []


# --- drag types --------------------------------------------------------------
def test_dragfill_parts():
    q = build_all_types()["dragfill"]
    assert summarise_stored(q, ["dog", "dog"]) == [
        _gap(1, "dog", "cat", False),
        _gap(2, "dog", None, True),
    ]


def test_dragimage_parts_are_labelled_by_zone():
    q = build_all_types()["dragimage"]
    assert summarise_stored(q, ["Heart", "Heart"]) == [
        _answer("Heart", None, True, label="Zone 1"),
        _answer("Heart", "Liver", False, label="Zone 2"),
    ]


def test_matchpair_labels_are_course_content():
    q = build_all_types()["matchpair"]
    parts = summarise_stored(q, ["1", "3", "2"])
    assert parts == [
        _answer("1", None, True, label="a", label_is_content=True),
        _answer("3", "2", False, label="b", label_is_content=True),
        _answer("2", "3", False, label="c", label_is_content=True),
    ]


# --- grids -------------------------------------------------------------------
def _cols(q):
    return {c.label: c.pk for c in q.columns.all()}


def test_choicegrid_parts_empty_row_and_removed_column():
    q = build_all_types()["choicegrid"]
    cols = _cols(q)
    assert summarise_stored(q, [cols["yes"], ""]) == [
        _answer("yes", None, True, label="r1", label_is_content=True),
        _answer(None, "no", False, label="r2", label_is_content=True),
    ]
    missing = max(cols.values()) + 1000
    parts = summarise_stored(q, [missing, cols["no"]])
    # reveal["chosen_label"] is None for BOTH "" and a removed pk (spec §4.3):
    assert parts[0] == _answer(
        "(removed option)", "yes", False, label="r1", label_is_content=True
    )


def test_multigrid_parts_removed_pk_and_empty_set():
    q = build_all_types()["multigrid"]
    cols = _cols(q)
    missing = max(cols.values()) + 1000
    assert summarise_stored(q, [[cols["a"], cols["b"]], [cols["c"]]]) == [
        _answer("a, b", None, True, label="r1", label_is_content=True),
        _answer("c", None, True, label="r2", label_is_content=True),
    ]
    assert summarise_stored(q, [[cols["a"], missing], []]) == [
        _answer(
            "a, (removed option)", "a, b", False, label="r1", label_is_content=True
        ),
        _answer(None, "c", False, label="r2", label_is_content=True),
    ]


def test_multigrid_row_with_empty_correct_set_expects_none_label():
    q = build_all_types()["multigrid"]
    cols = _cols(q)
    r2 = q.rows.get(statement="r2")
    r2.correct_columns.set([])
    parts = summarise_stored(q, [[cols["a"], cols["b"]], [cols["c"]]])
    assert parts[1] == _answer("c", "(none)", False, label="r2", label_is_content=True)


def test_review_matchpair_and_choicegrid_take_labels_from_child_rows():
    made = build_all_types(mode=REVIEW)
    mp = summarise_stored(made["matchpair"], ["1", "3", "2"])
    assert [p.label for p in mp] == ["a", "b", "c"]
    assert all(p.ok is None and p.expected is None for p in mp)
    cg = made["choicegrid"]
    parts = summarise_stored(cg, [_cols(cg)["no"], ""])
    assert [(p.label, p.given, p.ok) for p in parts] == [
        ("r1", "no", None),
        ("r2", None, None),
    ]


# --- T32 matrix: the remaining unanswered-AUTO, REVIEW-copy and partial cases -----
def test_unanswered_auto_parts_for_every_remaining_type():
    made = build_all_types()

    def run(key):
        return summarise_stored(made[key], None, unanswered=True)

    assert run("shortnumeric") == [_answer(None, "1/2", False)]
    assert run("dragfill") == [_gap(1, None, "cat", False), _gap(2, None, "dog", False)]
    assert run("dragimage") == [
        _answer(None, "Heart", False, label="Zone 1"),
        _answer(None, "Liver", False, label="Zone 2"),
    ]
    assert run("matchpair") == [
        _answer(None, right, False, label=left, label_is_content=True)
        for left, right in (("a", "1"), ("b", "2"), ("c", "3"))
    ]
    assert run("choicegrid") == [
        _answer(None, "yes", False, label="r1", label_is_content=True),
        _answer(None, "no", False, label="r2", label_is_content=True),
    ]
    assert run("multigrid") == [
        _answer(None, "a, b", False, label="r1", label_is_content=True),
        _answer(None, "c", False, label="r2", label_is_content=True),
    ]


def test_review_copies_of_every_remaining_type_carry_given_only():
    made = build_all_types(mode=REVIEW)
    assert summarise_stored(made["shortnumeric"], "3") == [_answer("3", None, None)]
    assert summarise_stored(made["dragfill"], ["dog", "cat"]) == [
        _gap(1, "dog", None, None),
        _gap(2, "cat", None, None),
    ]
    assert summarise_stored(made["dragimage"], ["Liver", "Heart"]) == [
        _answer("Liver", None, None, label="Zone 1"),
        _answer("Heart", None, None, label="Zone 2"),
    ]
    mg = made["multigrid"]
    cols = _cols(mg)
    assert summarise_stored(mg, [[cols["a"]], []]) == [
        _answer("a", None, None, label="r1", label_is_content=True),
        _answer(None, None, None, label="r2", label_is_content=True),
    ]


def test_multigrid_partial_one_row_right_one_wrong():
    q = build_all_types()["multigrid"]
    cols = _cols(q)
    assert summarise_stored(q, [[cols["a"], cols["b"]], [cols["a"]]]) == [
        _answer("a, b", None, True, label="r1", label_is_content=True),
        _answer("a", "c", False, label="r2", label_is_content=True),
    ]


# --- token stems --------------------------------------------------------------
def test_token_stems_are_gap_marked_like_the_part_labels():
    from courses.answer_summary import stem_html
    from courses.fillblank import SENTINEL

    made = build_all_types()
    for key in ("fillblank", "dragfill"):
        html = str(stem_html(made[key]))
        assert SENTINEL in made[key].stem  # the fixture really holds tokens
        assert SENTINEL not in html
        assert html.index("[1]") < html.index("[2]")
        assert '<span class="answers__gap">[1]</span>' in html


def test_other_stems_render_unchanged():
    from courses.answer_summary import stem_html

    q = build_all_types()["shorttext"]
    assert str(stem_html(q)) == q.stem
