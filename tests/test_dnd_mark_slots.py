# tests/test_dnd_mark_slots.py
from courses import dnd


def test_mark_slots_full_partial_zero():
    expected = ["Paris", "Madrid"]
    pool = ["Madrid", "Paris", "Rome"]
    assert dnd.mark_slots(expected, pool, ["Paris", "Madrid"])[0] == 2
    assert dnd.mark_slots(expected, pool, ["Paris", "Rome"])[0] == 1
    assert dnd.mark_slots(expected, pool, ["Rome", "Rome"])[0] == 0


def test_mark_slots_unfilled_and_forged_are_wrong():
    expected = ["Paris"]
    pool = ["Paris", "Rome"]
    assert dnd.mark_slots(expected, pool, [""])[0] == 0  # unfilled
    assert dnd.mark_slots(expected, pool, ["Berlin"])[0] == 0  # not a pool member
    assert dnd.mark_slots(expected, pool, [])[0] == 0  # short list, no IndexError
    assert dnd.mark_slots(expected, pool, ["Paris", "x"])[0] == 1  # long list ok


def test_mark_slots_normalized_match_and_membership():
    # got differs only by case/space from expected AND from the pool's raw form.
    expected = ["Paris"]
    pool = ["Paris", "Rome"]
    assert dnd.mark_slots(expected, pool, ["  paris "])[0] == 1


def test_mark_slots_reveal_shape():
    n, reveal = dnd.mark_slots(["Paris", "Madrid"], ["Paris", "Madrid"], ["Paris", "X"])
    assert reveal == (
        {"index": 0, "correct": True, "accepted": "Paris"},
        {"index": 1, "correct": False, "accepted": "Madrid"},
    )
