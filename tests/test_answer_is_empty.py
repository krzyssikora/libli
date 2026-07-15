from courses.quiz import answer_is_empty


def test_answer_is_empty_nested_lists():
    assert answer_is_empty([[], [], []]) is True
    assert answer_is_empty([[3], []]) is False


def test_answer_is_empty_flat_preserved():
    assert answer_is_empty(["", ""]) is True
    assert answer_is_empty(["", 3]) is False


def test_answer_is_empty_set_preserved():
    # ChoiceQuestionElement.build_answer returns a set — must not regress
    assert answer_is_empty(set()) is True
    assert answer_is_empty({3}) is False


def test_answer_is_empty_scalars_preserved():
    assert answer_is_empty("") is True
    assert answer_is_empty("x") is False
    assert answer_is_empty(None) is True
