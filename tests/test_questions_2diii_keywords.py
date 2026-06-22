import math

from courses.keywords import mark_keywords


def _frac(answer, required, forbidden):
    return mark_keywords(answer, required, forbidden)[0]


def test_all_required_no_forbidden_is_full():
    assert _frac("alpha beta", ["alpha", "beta"], []) == 1.0


def test_partial_required():
    assert _frac("alpha only", ["alpha", "beta"], []) == 0.5


def test_only_forbidden_zero_guard_full_when_clean():
    # No required -> req factor 1.0; no forbidden present -> 1.0.
    assert _frac("nice clean text", [], ["banned"]) == 1.0


def test_only_required_zero_guard():
    assert _frac("alpha", ["alpha"], []) == 1.0


def test_forbidden_graduated_penalty():
    # all required + 1 of 4 forbidden -> 1 * (1 - 0.25) = 0.75
    frac = _frac("alpha w1", ["alpha"], ["w1", "w2", "w3", "w4"])
    assert math.isclose(frac, 0.75)


def test_single_forbidden_is_hard_fail():
    assert _frac("alpha banned", ["alpha"], ["banned"]) == 0.0


def test_correct_iff_fraction_one():
    _, _, correct = mark_keywords("alpha beta", ["alpha", "beta"], ["bad"])
    assert correct is True
    _, _, correct2 = mark_keywords("alpha", ["alpha", "beta"], [])
    assert correct2 is False


def test_whole_word_not_substring():
    # "ion" must NOT match inside "question"; "cat" must NOT match "category".
    assert _frac("this is a question about category", ["ion", "cat"], []) == 0.0


def test_phrase_matches_contiguous_and_whitespace_collapsed():
    assert _frac("the French   Revolution began", ["French Revolution"], []) == 1.0
    assert _frac("French armies and a Revolution", ["French Revolution"], []) == 0.0


def test_accent_case_fold_match_but_not_accent_strip():
    # same accent, different case -> match; accent mismatch -> no match (non-goal).
    assert _frac("the révolté crowd", ["Révolté"], []) == 1.0
    assert _frac("the revolte crowd", ["Révolté"], []) == 0.0


def test_duplicate_occurrence_counts_once():
    assert _frac("alpha alpha alpha", ["alpha"], []) == 1.0


def test_reveal_shape_required_then_forbidden_stripped():
    _, reveal, _ = mark_keywords("alpha", ["  alpha ", "beta"], ["bad"])
    assert reveal == (
        {"keyword": "alpha", "kind": "required", "found": True},
        {"keyword": "beta", "kind": "required", "found": False},
        {"keyword": "bad", "kind": "forbidden", "found": False},
    )
