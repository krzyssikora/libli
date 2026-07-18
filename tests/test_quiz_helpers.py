import pytest

from courses.models import ChoiceQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import ShortTextQuestionElement
from courses.quiz import answer_is_empty
from courses.quiz import answer_to_json
from courses.quiz import rehydrate


def test_answer_is_empty_across_shapes():
    assert answer_is_empty(set())
    assert answer_is_empty("")
    assert answer_is_empty("   ")
    assert answer_is_empty(["", "  "])
    assert not answer_is_empty({1})
    assert not answer_is_empty("x")
    assert not answer_is_empty(["", "a"])


def test_answer_to_json_set_becomes_sorted_list():
    assert answer_to_json({3, 1, 2}) == [1, 2, 3]
    assert answer_to_json("hi") == "hi"
    assert answer_to_json(["a", ""]) == ["a", ""]


def test_selected_ids_returns_set_only_for_choice_payloads():
    from courses.quiz import selected_ids

    assert selected_ids({3, 1}) == {3, 1}  # choice payload passes through
    assert selected_ids(frozenset({2})) == {2}
    assert selected_ids("Paris") == frozenset()  # text -> empty
    assert selected_ids(["x", "y"]) == frozenset()  # fill-blank list -> empty
    assert selected_ids(None) == frozenset()


@pytest.mark.django_db
def test_rehydrate_choice_returns_selected_ids():
    q = ChoiceQuestionElement.objects.create(stem="s", multiple=True)
    selected, submitted = rehydrate(q, [5, 7])
    assert selected == {5, 7} and submitted is None


@pytest.mark.django_db
def test_rehydrate_text_returns_submitted_values():
    q = ShortTextQuestionElement.objects.create(stem="s", accepted="a")
    selected, submitted = rehydrate(q, "Paris")
    assert selected == set() and submitted == "Paris"


@pytest.mark.django_db
def test_rehydrate_fillblank_returns_list():
    q = FillBlankQuestionElement.objects.create(stem="s {{a}}")
    selected, submitted = rehydrate(q, ["x", "y"])
    assert selected == set() and submitted == ["x", "y"]


@pytest.mark.django_db
def test_answer_from_json_inverts_to_json():
    from courses.quiz import answer_from_json

    cq = ChoiceQuestionElement.objects.create(stem="s")
    assert answer_from_json(cq, [1, 2]) == {1, 2}  # choice -> set
    tq = ShortTextQuestionElement.objects.create(stem="s", accepted="a")
    assert answer_from_json(tq, "Paris") == "Paris"  # text unchanged
