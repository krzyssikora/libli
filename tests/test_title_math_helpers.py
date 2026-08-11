"""titles_have_math / tree_titles_have_math -- the scan half of the gate (spec §2).

No `import pytest`: this file has no pytestmark, no marks and no pytest.raises,
and `monkeypatch` is a fixture that needs no import -- ruff's F401 would strip
the line and leave the committed file differing from this listing.
"""

from courses import htmlsandbox
from courses import rollups
from courses.htmlsandbox import titles_have_math
from courses.rollups import tree_titles_have_math


def _node(title, children=None):
    """A build_outline-shaped node dict with only the keys the scan reads."""

    class _N:
        def __init__(self, t):
            self.title = t

    return {"node": _N(title), "children": children or []}


def test_titles_have_math_finds_an_inline_delimiter():
    assert titles_have_math(["plain", r"has \(x\)"]) is True


def test_titles_have_math_finds_a_display_delimiter():
    assert titles_have_math([r"has \[x\]"]) is True


def test_titles_have_math_is_false_when_nothing_carries_maths():
    assert titles_have_math(["plain", "also plain"]) is False


def test_titles_have_math_is_false_on_an_empty_iterable():
    assert titles_have_math([]) is False


def test_titles_have_math_accepts_a_generator():
    """Every call site in views.py passes a generator expression, not a list."""
    assert titles_have_math(t for t in ["plain", r"\(x\)"]) is True


def test_titles_have_math_tolerates_a_none_title():
    """Inherited free from has_math_delimiters' `html or ""` guard."""
    assert titles_have_math([None]) is False


def test_titles_have_math_delegates_to_has_math_delimiters(monkeypatch):
    """PIN: an independent copy of the "\\(" test satisfies every assertion above
    while forking the delimiter definition the moment has_math_delimiters changes.
    Patch the shared predicate to a sentinel and require the helper to follow it."""
    monkeypatch.setattr(htmlsandbox, "has_math_delimiters", lambda t: t == "SENTINEL")
    assert htmlsandbox.titles_have_math(["SENTINEL"]) is True
    assert htmlsandbox.titles_have_math([r"\(x\)"]) is False


def test_tree_titles_have_math_finds_a_root_title():
    assert tree_titles_have_math([_node(r"\(x\)")]) is True


def test_tree_titles_have_math_recurses_into_grandchildren():
    """MUST RECURSE: the unit page renders the WHOLE course outline into the DOM,
    so a maths title three levels down is on screen. A one-level scan passes every
    other test in this file."""
    tree = [_node("part", [_node("chapter", [_node(r"deep \(x\)")])])]
    assert tree_titles_have_math(tree) is True


def test_tree_titles_have_math_is_false_on_a_maths_free_tree():
    tree = [_node("part", [_node("chapter", [_node("unit")])])]
    assert tree_titles_have_math(tree) is False


def test_tree_titles_have_math_is_false_on_an_empty_tree():
    assert tree_titles_have_math([]) is False


def test_tree_titles_have_math_tolerates_a_missing_children_key():
    """Cheap defensiveness, not a response to a known producer: build_outline
    unconditionally sets "children": [] and prunes by rebuilding the list."""
    assert tree_titles_have_math([{"node": _node("plain")["node"]}]) is False


def test_tree_titles_have_math_delegates_its_leaf_test(monkeypatch):
    """PIN, and with more force than the one above: this helper is written by hand
    against a tree walk, so it is the likeliest place for an inlined
    `"\\(" in title` copy to appear -- and nothing else here would go red."""
    monkeypatch.setattr(
        rollups, "titles_have_math", lambda ts: any(t == "SENTINEL" for t in ts)
    )
    assert rollups.tree_titles_have_math([_node("SENTINEL")]) is True
    assert rollups.tree_titles_have_math([_node(r"\(x\)")]) is False
