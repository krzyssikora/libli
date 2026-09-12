import random

import pytest


def test_lists_meet_the_minimum_length():
    """The assertion is on the LIST LENGTHS, not their product: 40 given names x
    1 surname satisfies a product bound while making the 40th distinct pair a
    1-in-40 draw, so the retry limit would fire during ordinary provisioning."""
    from demo import names
    from demo.constants import MIN_NAMES_PER_LIST

    for lst in (
        names.FEMININE_GIVEN,
        names.MASCULINE_GIVEN,
        names.FEMININE_SURNAMES,
        names.MASCULINE_SURNAMES,
    ):
        assert len(lst) >= MIN_NAMES_PER_LIST
        assert len(set(lst)) == len(lst)


def test_the_pools_cover_the_maximum_class():
    """MAX_PUPILS and MIN_NAMES_PER_LIST are BOTH 40 today, which makes
    `--pupils 40` the exact boundary — and nothing else relates them. Raise
    MAX_PUPILS (an obvious operator tweak; it sits under "operator bounds") and
    every provisioning at the new ceiling raises NamePoolExhausted AFTER the
    kit, group, teacher and student rows are written. The check above stays green
    throughout, because it compares the lists against the wrong constant.

    Derived, never a `== 40` pin on either side."""
    from demo import names
    from demo.constants import MAX_PUPILS

    shortest = min(
        len(names.FEMININE_GIVEN),
        len(names.MASCULINE_GIVEN),
        len(names.FEMININE_SURNAMES),
        len(names.MASCULINE_SURNAMES),
    )
    assert shortest >= MAX_PUPILS, (
        f"the name pools ({shortest}) cannot fill a class of MAX_PUPILS "
        f"({MAX_PUPILS}) — extend the lists or lower the bound"
    )


def test_draw_names_returns_distinct_gender_consistent_pairs():
    from demo import names

    drawn = names.draw_names(random.Random(7), 40)
    assert len(drawn) == 40
    assert len(set(drawn)) == 40
    for first, last in drawn:
        if first in names.FEMININE_GIVEN:
            assert last in names.FEMININE_SURNAMES
        else:
            assert first in names.MASCULINE_GIVEN
            assert last in names.MASCULINE_SURNAMES


def test_draw_names_is_deterministic_for_a_seed():
    from demo import names

    assert names.draw_names(random.Random(3), 20) == names.draw_names(
        random.Random(3), 20
    )


def test_draw_names_raises_rather_than_spinning_on_a_short_pool(monkeypatch):
    """The PRE-CHECK half: count exceeds the shortest list, so draw_names refuses
    before the loop."""
    from demo import errors
    from demo import names

    monkeypatch.setattr(names, "FEMININE_SURNAMES", ("Kowalska",))
    monkeypatch.setattr(names, "MASCULINE_SURNAMES", ("Kowalski",))
    monkeypatch.setattr(names, "FEMININE_GIVEN", ("Anna",))
    monkeypatch.setattr(names, "MASCULINE_GIVEN", ("Jan",))
    with pytest.raises(errors.NamePoolExhausted):
        names.draw_names(random.Random(1), 10)


def test_the_retry_limit_itself_raises_rather_than_spinning(monkeypatch):
    """The RETRY half. The test above never reaches the `while` loop — it trips
    the pre-check and returns — so without this case NAME_RETRY_LIMIT is dead
    code and a live spin ships untested.

    ⚠️ THE POOL CANNOT BE SHAPED TO REACH THIS BRANCH. Any pool short enough to
    exhaust distinct pairs also satisfies `min(len(...)) < count`, so the
    pre-check fires first and raises the OTHER message. (An earlier draft of this
    test claimed four 2-element lists with count=4 would pass the pre-check;
    2 < 4, so it does not — the test was red on correct code.) The only way in is
    to drop the retry budget to zero and force one collision.
    """
    from demo import errors
    from demo import names

    monkeypatch.setattr(names, "NAME_RETRY_LIMIT", 0)
    monkeypatch.setattr(names, "FEMININE_GIVEN", ("Anna", "Maria"))
    monkeypatch.setattr(names, "MASCULINE_GIVEN", ("Jan", "Piotr"))
    monkeypatch.setattr(names, "FEMININE_SURNAMES", ("Kowalska", "Nowak"))
    monkeypatch.setattr(names, "MASCULINE_SURNAMES", ("Kowalski", "Nowak"))

    class _FixedRng:
        """Every draw returns the same value, so pupil 2 collides with pupil 1."""

        def random(self):
            return 0.0  # < 0.5 -> feminine, every time

        def randrange(self, n):
            return 0  # "Anna", "Kowalska", every time

    with pytest.raises(errors.NamePoolExhausted) as exc:
        names.draw_names(_FixedRng(), 2)  # 2 <= 2, so the pre-check passes
    assert "retries" in str(exc.value), "the RETRY branch, not the pre-check"


def test_pairs_are_distinct_on_a_pool_where_collisions_are_forced(monkeypatch):
    """The distinctness mutant is only visible on a CRAMPED pool AND A SEED THAT
    ACTUALLY COLLIDES.

    ⚠️ THE SEED IS LOAD-BEARING — re-verify it if these pools change. `count` has
    to be 4, not 40, because the pre-check `min(len(...)) < count` fires first;
    and at count=4 only about a third of seeds collide at all (98 of the first
    300). `Random(5)` is one of the two-thirds that do NOT: with and without the
    retry loop it yields the identical
    [('C','W'), ('B','W'), ('A','Y'), ('B','Z')], so the mutant would be a
    guaranteed false green.

    `Random(1)` is verified to collide: with the loop it draws four distinct
    pairs; without it, ('D','Z') twice.
    """
    from demo import names

    for attr in ("FEMININE_GIVEN", "MASCULINE_GIVEN"):
        monkeypatch.setattr(names, attr, ("A", "B", "C", "D"))
    for attr in ("FEMININE_SURNAMES", "MASCULINE_SURNAMES"):
        monkeypatch.setattr(names, attr, ("W", "X", "Y", "Z"))

    drawn = names.draw_names(random.Random(1), 4)  # 4 <= 4: pre-check passes
    assert len(set(drawn)) == 4
