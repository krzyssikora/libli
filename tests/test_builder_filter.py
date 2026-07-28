import re
import unicodedata

from courses.builder_filter import MATCH_CAP
from courses.builder_filter import filtered_map
from courses.builder_filter import fold
from courses.builder_filter import is_active


class FakeNode:
    """Structural stand-in: filtered_map must never touch the ORM."""

    def __init__(self, pk, parent_id, title, order=0, kind="unit"):
        self.pk = pk
        self.parent_id = parent_id
        self.title = title
        self.order = order
        self.kind = kind


def _map(nodes):
    cmap = {}
    for n in nodes:
        cmap.setdefault(n.parent_id, []).append(n)
    return cmap


def test_fold_maps_every_polish_letter_to_ascii():
    assert fold("ĄĆĘŁŃÓŚŹŻ ąćęłńóśźż") == "acelnoszz acelnoszz"


def test_fold_handles_l_stroke_in_both_directions():
    # The one letter NFKD cannot reach: U+0142 has no decomposition, so a
    # generic "NFKD then drop combining marks" fold leaves it in place.
    assert fold("Łąka") == "laka"
    # The containment the filter actually performs, in both directions --
    # `fold(x) in fold(x)` would be true whatever fold did.
    assert fold("laka") in fold("Rozdział: Łąka i las")
    assert fold("ŁĄKA") in fold("rozdzial: laka i las")


def test_fold_handles_decomposed_input():
    # Imported HTML arrives NFD; without U+0300-U+036F in the table this
    # returns "ka\u0328ty" -- base `a` followed by a DANGLING combining
    # ogonek. Written ESCAPED on purpose: the precomposed "k\u0105ty" is a
    # DIFFERENT string, indistinguishable from it in a terminal and in a
    # diff, and that difference is the whole point of this row. An ASCII
    # query misses the node entirely.
    assert fold(unicodedata.normalize("NFD", "Kąty")) == "katy"


def test_is_active_applies_the_floor_to_the_FOLDED_length():
    assert is_active("ab") is True
    assert is_active("a") is False
    assert is_active(" a ") is False
    assert is_active("") is False
    assert is_active(None) is False
    # Two code points, one folded character: a raw-length floor lets it through.
    assert is_active(unicodedata.normalize("NFD", "ą")) is False


def test_below_floor_returns_the_map_unchanged_and_inactive():
    nodes = [FakeNode(1, None, "Trygonometria", kind="chapter")]
    cmap = _map(nodes)
    restricted, chains, shown, total, active = filtered_map(cmap, "a")
    assert active is False
    assert chains == set()
    assert (shown, total) == (0, 0)
    assert restricted == cmap


def test_the_returned_map_is_never_the_argument_even_when_blank():
    # Effect 2 (spec 3e) mutates the restricted map. Aliasing it to the full
    # map on the blank path corrupts what _open_ids and _open_descendants read
    # in the same request, and no filtered test can catch that.
    nodes = [FakeNode(1, None, "A", kind="chapter")]
    cmap = _map(nodes)
    restricted, *_ = filtered_map(cmap, "")
    assert restricted is not cmap
    assert restricted[None] is not cmap[None]


def test_active_with_zero_matches_is_still_active():
    nodes = [FakeNode(1, None, "Trygonometria", kind="chapter")]
    restricted, chains, shown, total, active = filtered_map(_map(nodes), "zzzz")
    assert active is True
    assert (shown, total) == (0, 0)
    assert restricted == {}


def test_walk_includes_a_matched_container_itself_and_every_ancestor():
    part = FakeNode(1, None, "Część", kind="part")
    chap = FakeNode(2, 1, "Trygonometria", kind="chapter")
    unit = FakeNode(3, 2, "Sinus", kind="unit")
    restricted, chains, shown, total, active = filtered_map(
        _map([part, chap, unit]), "sinus"
    )
    assert chains == {1, 2}  # ancestors; the unit owns no scope
    assert restricted[2] == [unit]
    assert restricted[1] == [chap]
    assert (shown, total) == (1, 1)

    _, chains2, *_ = filtered_map(_map([part, chap, unit]), "trygo")
    assert chains2 == {1, 2}  # the matched CONTAINER is in its own chain


def test_cap_keeps_the_first_MATCH_CAP_in_order_pk_with_scattered_pks():
    # Scattered, non-sequential pks: CPython iterates small sequential ints
    # ascending, so a sorted->list mutation would stay green on tidy pks.
    # DISTINCT pks: filtered_map indexes by pk, so a repeated list collapses
    # 240 nodes to 6 and every count assertion below becomes unreachable.
    nodes = [
        FakeNode(9001 + i * 7919, None, f"Zadanie {i}", order=i % 7) for i in range(240)
    ]
    restricted, chains, shown, total, active = filtered_map(_map(nodes), "zadanie")
    assert total == len(nodes)
    assert shown == MATCH_CAP
    kept = restricted[None]
    assert len(kept) == MATCH_CAP
    # The cap is applied to the (order, pk)-sorted match list, so the kept SET
    # is the 100 lowest (order, pk) pairs. The emitted ROW order is the input
    # order of cmap[parent] -- see the sibling-order test.
    lowest = sorted((n.order, n.pk) for n in nodes)[:MATCH_CAP]
    assert sorted((n.order, n.pk) for n in kept) == lowest


def test_restricted_map_groups_roots_under_none_in_cmap_order():
    """What this row ACTUALLY guards: roots land under the None key, in the
    order cmap gave them.

    It does NOT guard "never re-sorts", despite the temptation to name it
    that. `_children_map` already emits each parent's children in (order, pk)
    order (views_manage.py:140), so the fixture below is built that way -- and
    an implementation that re-sorted `rows` by (order, pk) would produce the
    identical [b, a]. Constructing a fixture whose cmap order DIFFERS from
    (order, pk) order would catch the re-sort, but it would also be a shape
    _children_map can never produce, so the row would guard a case that cannot
    occur. Naming the row honestly is the better trade.
    """
    b = FakeNode(11, None, "Alfabet", order=0, kind="chapter")
    a = FakeNode(10, None, "Alfa", order=1, kind="chapter")
    restricted, *_ = filtered_map(_map([b, a]), "alfa")  # cmap order
    assert restricted[None] == [b, a]


def test_client_floor_never_exceeds_the_server_floor_on_latin_input():
    # The dangerous direction (spec 5c): client above the floor while the
    # server is below it sends a filter fetch that omits `open`, and the
    # server's blank `q` collapses the tree. Measured Latin count: 0.
    def client_measure(s):
        """A mirror of builder.js's effectiveQ. The UTF-16 half must be
        EXPLICIT: Python has no `.length`, so spelling this `len(stripped)`
        makes the astral falsification unreachable -- both spellings agree on
        every BMP input, so the test could not tell the two measures apart.
        """
        t = re.sub(r"^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$", "", s)
        stripped = "".join(
            c
            for c in unicodedata.normalize("NFC", t)
            if not (0x0300 <= ord(c) <= 0x036F)
        )
        return len(stripped.encode("utf-16-le")) // 2  # what .length counts

    for ch in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻß" + "Ĳǆǉǌǳ" + "a\u0085":
        assert client_measure(ch) <= len(fold(ch)), ch
    # The two inputs that catch a bare trim() and a .length count.
    assert client_measure("a\u0085") == 1
    assert client_measure("𝐀") == 2 > len(fold("𝐀"))
