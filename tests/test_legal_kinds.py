from courses.ordering import kinds_for_flags
from courses.ordering import kinds_for_preset
from courses.ordering import legal_child_kinds
from courses.ordering import preset_for_flags
from courses.ordering import primary_child_kind

ALL = ["part", "chapter", "section", "unit"]


def test_legal_child_kinds_top_allows_all_in_rank_order():
    assert legal_child_kinds(None, ALL) == ["part", "chapter", "section", "unit"]


def test_legal_child_kinds_nested():
    assert legal_child_kinds("part", ALL) == ["chapter", "section", "unit"]
    assert legal_child_kinds("chapter", ALL) == ["section", "unit"]
    assert legal_child_kinds("section", ALL) == ["unit"]
    assert legal_child_kinds("unit", ALL) == []


def test_legal_child_kinds_restricted_by_course_set():
    assert legal_child_kinds(None, ["chapter", "unit"]) == ["chapter", "unit"]
    assert legal_child_kinds(None, ["unit"]) == ["unit"]
    custom = ["part", "section", "unit"]  # no chapter
    assert legal_child_kinds(None, custom) == ["part", "section", "unit"]
    assert legal_child_kinds("part", custom) == ["section", "unit"]


def test_primary_child_kind():
    assert primary_child_kind(None, ALL) == "chapter"
    assert primary_child_kind("part", ALL) == "chapter"
    assert primary_child_kind("chapter", ALL) is None  # only 2 legal
    assert primary_child_kind("section", ALL) is None
    assert primary_child_kind(None, ["chapter", "unit"]) is None  # 2 legal
    assert primary_child_kind(None, ["part", "section", "unit"]) == "part"  # no chapter


def test_kinds_for_flags_and_presets():
    assert kinds_for_flags(False, False, False) == ["unit"]
    assert kinds_for_flags(False, True, False) == ["chapter", "unit"]
    assert kinds_for_flags(True, True, False) == ["part", "chapter", "unit"]
    assert kinds_for_flags(True, True, True) == ALL
    assert kinds_for_preset("flat") == ["unit"]
    assert kinds_for_preset("full") == ALL


def test_preset_for_flags_reverse_lookup():
    assert preset_for_flags(False, False, False) == "flat"
    assert preset_for_flags(False, True, False) == "chapters"
    assert preset_for_flags(True, True, False) == "parts"
    assert preset_for_flags(True, True, True) == "full"
    assert preset_for_flags(True, False, True) is None  # custom
