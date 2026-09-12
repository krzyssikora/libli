"""The class: who is in which band, how far each pupil got, and what they did.

DETERMINISM (spec R5). All content randomness comes from one
random.Random(kit.seed), consumed in this fixed order:

  1. per pupil in creation order: gender, given name, surname (+1 per rejected
     duplicate)                                        -- demo.names.draw_names
  2. the band partition and its single shuffle         -- assign_bands
  3. per pupil in order: jitter, then per unit in PRE-ORDER: the lesson
     completion draw, or per question in element order (one draw, or two for a
     partial-capable type, plus one variant pick when the answer came out wrong
     and more than one variant survives); then, as item 3a, that pupil's
     reach-forward rows
  4. the IN_PROGRESS pass

A NOT_MARKED question, a sentinel question, an R3-skipped quiz, an
all-NOT_MARKED quiz and a non-lesson non-quiz unit consume NO draws.
"""

import math

from demo.constants import AVERAGE
from demo.constants import BANDS
from demo.constants import FRONTIER_FRACTION
from demo.constants import JITTER
from demo.constants import STRONG
from demo.constants import STRONG_PCT
from demo.constants import STRUGGLING
from demo.constants import STRUGGLING_PCT
from demo.errors import InvalidFrontierPart


def assign_bands(rng, pupil_count):
    """A fixed partition, shuffled once, zipped with the pupils in creation order."""
    strong = pupil_count * STRONG_PCT // 100
    struggling = pupil_count * STRUGGLING_PCT // 100
    bands = (
        [STRONG] * strong
        + [STRUGGLING] * struggling
        + [AVERAGE] * (pupil_count - strong - struggling)
    )
    rng.shuffle(bands)
    return bands


def frontier_index(plan, frontier_part, course):
    """The published-unit index the class is working around.

    `course` is REQUIRED (no default): the frontier_part branch dereferences it,
    and a default of None turns a wiring mistake into an AttributeError deep in
    the body instead of a TypeError at the call.

    `frontier_part` is tested with `is not None`: part 0 is a legal AND falsy
    value, and `if frontier_part:` would silently turn --frontier-part 0 into
    the fraction.
    """
    total = len(plan.units)
    if frontier_part is not None:
        parts = list(course.nodes.filter(parent__isnull=True).order_by("order", "pk"))
        # BOTH ends. `>= len(parts)` alone lets -1 through: it passes the
        # `is not None` branch, passes this check, and `parts[-1]` then silently
        # selects the LAST part — the opposite of what the operator typed. The
        # run reaches DemoKit.objects.create(frontier_part=-1), where
        # PositiveSmallIntegerField raises a DB error that the command's
        # `except (DemoKitError, ImproperlyConfigured)` deliberately does not
        # catch, so the operator gets a raw traceback.
        if not 0 <= frontier_part < len(parts):
            raise InvalidFrontierPart(
                f"part {frontier_part} does not exist (0..{len(parts) - 1})"
            )
        wanted = parts[frontier_part]
        ids = set(wanted._subtree_node_ids())
        positions = [i for i, u in enumerate(plan.units) if u.pk in ids]
        if not positions:
            raise InvalidFrontierPart(
                f"part {frontier_part} contains no published unit"
            )
        return positions[-1]
    return math.floor(FRONTIER_FRACTION * total)


def pupil_depth(rng, band, frontier, unit_count=None):
    """Consumes exactly one draw (the jitter). `round` is Python's banker's
    rounding, NOT int(x + 0.5) — the two disagree at exact halves.

    `unit_count is not None`, NOT truthiness: this is the same falsy-zero trap
    the frontier_part docstring spends a paragraph on, and writing it the other
    way here would let `unit_count=0` silently fall through to the UNCLAMPED
    branch. provision_kit raises EmptyCourse before that can happen today, but
    this is a public interface Task 15's boundary test calls directly.
    """
    if unit_count is not None and unit_count < 1:
        raise ValueError("unit_count must be >= 1 when given")
    jitter = rng.uniform(-JITTER, JITTER)
    depth = round(frontier * BANDS[band]["depth"] * (1 + jitter))
    top = (unit_count - 1) if unit_count is not None else max(depth, 0)
    return max(0, min(depth, top))
