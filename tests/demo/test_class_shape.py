import random

import pytest

from demo import generator
from demo.constants import AVERAGE
from demo.constants import STRONG
from demo.constants import STRUGGLING


def test_bands_are_a_fixed_partition_not_a_weighted_draw():
    """A per-pupil weighted draw could legitimately give a 20-pupil class with no
    strugglers, which makes the acceptance criterion non-deterministic."""
    bands = generator.assign_bands(random.Random(1), 20)
    assert len(bands) == 20
    assert bands.count(STRONG) == 4
    assert bands.count(STRUGGLING) == 4
    assert bands.count(AVERAGE) == 12


@pytest.mark.parametrize(
    "pupils,strong,struggling,average",
    [(15, 3, 3, 9), (18, 3, 3, 12)],
)
def test_the_partition_is_integer_arithmetic_off_the_share_constants(
    pupils, strong, struggling, average
):
    """FLOOR, not half-up rounding. 18 is the load-bearing case: `18 * 20 // 100`
    is 3 while `round(18 * 20 / 100)` is 4, so it separates the integer form from
    the rounding mutant. 15 alone does not — see Step 5."""
    bands = generator.assign_bands(random.Random(1), pupils)
    assert bands.count(STRONG) == strong
    assert bands.count(STRUGGLING) == struggling
    assert bands.count(AVERAGE) == average


def test_every_band_is_populated_at_the_minimum_pupil_count():
    from demo.constants import MIN_PUPILS

    bands = generator.assign_bands(random.Random(1), MIN_PUPILS)
    assert set(bands) == {STRONG, AVERAGE, STRUGGLING}


def test_bands_are_deterministic_for_a_seed():
    assert generator.assign_bands(random.Random(9), 20) == generator.assign_bands(
        random.Random(9), 20
    )


@pytest.mark.parametrize("band", [STRONG, AVERAGE, STRUGGLING])
def test_depth_scales_with_the_band(band):
    """Bounds are DERIVED from the constants, never hard-coded.

    ⚠️ The hard-coded version of this test (70-90 / 61-78 / 42-55) failed on
    correct code: with frontier=75 the true ceilings are round(75*1.15*1.08)=93,
    round(75*1.00*1.08)=81 and round(75*0.70*1.08)=57. Deriving them also means a
    JITTER or multiplier change cannot leave the test asserting a stale window.
    """
    from demo.constants import BANDS
    from demo.constants import JITTER

    frontier = 75
    centre = frontier * BANDS[band]["depth"]
    lo, hi = round(centre * (1 - JITTER)), round(centre * (1 + JITTER))
    depths = [
        generator.pupil_depth(random.Random(s), band, frontier) for s in range(50)
    ]
    assert all(lo <= d <= hi for d in depths), (min(depths), max(depths), lo, hi)
    # A guard: 50 seeds must actually spread, or the bounds check is vacuous.
    assert len(set(depths)) > 1


def test_the_bands_are_separated_at_the_same_frontier():
    """What the parametrised test above CANNOT see: it checks each band against
    its own window, so a build where every band used the AVERAGE multiplier
    passes all three. This pins the ordering between them."""
    from demo.constants import BANDS

    frontier = 75
    centres = {
        b: round(frontier * BANDS[b]["depth"]) for b in (STRONG, AVERAGE, STRUGGLING)
    }
    assert centres[STRUGGLING] < centres[AVERAGE] < centres[STRONG]


def test_depth_is_clamped_into_the_unit_range():
    assert generator.pupil_depth(random.Random(1), STRONG, 0) == 0
    # The unit_count clamp: a frontier near the end must not index past the list.
    assert generator.pupil_depth(random.Random(1), STRONG, 13, 14) <= 13
    # is-not-None, not truthiness: 0 is rejected loudly rather than falling
    # through to the unclamped branch.
    with pytest.raises(ValueError):
        generator.pupil_depth(random.Random(1), STRONG, 5, 0)
