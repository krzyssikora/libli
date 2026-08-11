"""Unit tests for builder.ancestor_pks -- NO database.

The cycle case is a BOUND assertion, not a behavioural one. The mutant it guards
against (bounding the walk by len(ancestors) instead of a monotone hop counter)
does not fail, it HANGS: a set stops growing on a cycle, so the guard stays true
forever with a DB fetch per iteration. A hung pytest run also orphans the test DB
for the next run. So the fixture raises once the walk reads .parent too many
times, which is RED in milliseconds instead.
"""

from courses.builder import MAX_NEST_DEPTH
from courses.builder import ancestor_pks


class _Node:
    """Anything with .pk and .parent satisfies ancestor_pks."""

    def __init__(self, pk):
        self.pk = pk
        self._parent = None
        self.reads = 0

    @property
    def parent(self):
        self.reads += 1
        # `reads` is PER NODE. The correct walk performs six .parent reads on a
        # cycle in total (one initializer + five iterations, since `hops <= 4`
        # admits 0,1,2,3,4), and a two-node cycle splits those 3/3 -- so any one
        # instance sees at most 3. The tripwire at MAX_NEST_DEPTH * 3 == 12 leaves
        # a 4x margin, which a correct implementation can never reach.
        if self.reads > MAX_NEST_DEPTH * 3:
            raise AssertionError("ancestor_pks did not terminate on a cycle")
        return self._parent


def test_ancestor_pks_walks_the_whole_chain():
    a, b, c = _Node(1), _Node(2), _Node(3)
    c._parent = b
    b._parent = a
    assert ancestor_pks(c) == {1, 2}


def test_ancestor_pks_is_empty_for_a_top_level_element():
    assert ancestor_pks(_Node(1)) == set()


def test_ancestor_pks_terminates_on_a_cycle():
    a, b = _Node(1), _Node(2)
    a._parent = b
    b._parent = a
    ancestor_pks(a)  # must RETURN; the fixture raises if it loops
