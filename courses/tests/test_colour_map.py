from courses.colour import SENTINEL_RGB
from courses.colour import SLOTS
from courses.colour import normalise_colour
from courses.colour import parse_style_colour


def test_accepts_all_four_input_forms():
    assert normalise_colour("#B2372A") == (178, 55, 42)
    assert normalise_colour("#f00") == (255, 0, 0)
    assert normalise_colour("rgb(178, 55, 42)") == (178, 55, 42)
    assert normalise_colour("rgba(178, 55, 42, 0.5)") == (178, 55, 42)
    assert normalise_colour("red") == (255, 0, 0)


def test_slot_lookup_covers_light_dark_and_keyword_for_every_slot():
    for slot, values in {
        "red": ("#B2372A", "#EA8A82", "red"),
        "blue": ("#1F61AD", "#8FBCE8", "blue"),
        "green": ("#3F6B24", "#9FBF7B", "green"),
        "orange": ("#8A5514", "#E8B761", "orange"),
    }.items():
        for value in values:
            assert SLOTS[normalise_colour(value)] == slot, f"{value} -> {slot}"


def test_unmapped_colour_has_no_slot():
    assert normalise_colour("purple") not in SLOTS
    assert normalise_colour("#123456") not in SLOTS


def test_sentinel_is_unmapped():
    """Clearing colour applies the sentinel, then drops it. If it ever gained a slot,
    Clear would silently recolour instead of clearing."""
    assert SENTINEL_RGB not in SLOTS
    assert normalise_colour("rgb(1, 2, 3)") == SENTINEL_RGB


def test_garbage_returns_none():
    for value in ("", "   ", "not-a-colour", "rgb(1,2)", None):
        assert normalise_colour(value) is None


def test_parse_style_requires_the_exact_color_property():
    """background-color is the trap: an unanchored `color:` search matches it and
    invents a text colour that does not exist. Measured on the LAL corpus."""
    assert parse_style_colour("color: red") == (255, 0, 0)
    assert parse_style_colour("color:red") == (255, 0, 0)  # no space
    assert parse_style_colour("COLOR : red ;") == (255, 0, 0)  # case + spaces
    assert parse_style_colour("background-color: red") is None
    assert parse_style_colour("border-color: red") is None
    assert parse_style_colour("height: 1em; color: blue;") == (0, 0, 255)
    assert parse_style_colour("height: 1em") is None
    assert parse_style_colour("") is None
