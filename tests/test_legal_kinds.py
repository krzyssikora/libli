from courses.ordering import PRIMARY_CHILD_KIND
from courses.ordering import legal_child_kinds


def test_legal_child_kinds_top_allows_all_in_rank_order():
    assert legal_child_kinds(None) == ["part", "chapter", "section", "unit"]


def test_legal_child_kinds_nested():
    assert legal_child_kinds("part") == ["chapter", "section", "unit"]
    assert legal_child_kinds("chapter") == ["section", "unit"]
    assert legal_child_kinds("section") == ["unit"]
    assert legal_child_kinds("unit") == []


def test_primary_child_kind_only_for_three_plus_legal():
    assert PRIMARY_CHILD_KIND.get(None) == "chapter"
    assert PRIMARY_CHILD_KIND.get("part") == "chapter"
    assert PRIMARY_CHILD_KIND.get("chapter") is None  # only 2 legal kinds -> no overflow
    assert PRIMARY_CHILD_KIND.get("section") is None
