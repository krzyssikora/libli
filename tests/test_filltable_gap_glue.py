r"""An inline box and the word beside it ("{{20}} \(\pi\)", "{{75}}°") render inside
one no-wrap span, so a squeezed column cannot put the unit on the line below the
box. glue_gaps is pure string work; these pin exactly what gets glued, and that
nothing but the spans is ever added (the rest of the cell is byte-identical)."""

import re

from courses.filltable import cell_parts
from courses.filltable import glue_gaps

OPEN = '<span class="filltable__gapglue">'
CLOSE = "</span>"


def _glue(*parts):
    """glue_gaps over alternating text/"#" markers, each "#" standing for a box."""
    segments, inputs = [""], []
    for p in parts:
        if p == "#":
            inputs.append(f"[{len(inputs)}]")
            segments.append("")
        else:
            segments[-1] += p
    return "".join(glue_gaps(segments, inputs))


def test_box_space_math_is_one_group():
    # The reported cell: typed with a space, as the author prefers.
    assert _glue("#", r" \(\pi\)") == OPEN + r"[0] \(\pi\)" + CLOSE


def test_box_then_symbol_with_no_space():
    assert _glue("#", "°") == OPEN + "[0]°" + CLOSE


def test_only_the_adjacent_word_is_glued_so_long_text_still_wraps():
    got = _glue("the area is ", "#", r" \(\pi\) square units")
    assert got == "the area " + OPEN + r"is [0] \(\pi\)" + CLOSE + " square units"


def test_math_containing_spaces_is_glued_whole_never_split():
    assert _glue(r"\(2 \pi r\) ", "#") == OPEN + r"\(2 \pi r\) [0]" + CLOSE
    assert (
        _glue("#", r" \(2 \cdot \pi\) m")
        == OPEN + r"[0] \(2 \cdot \pi\)" + CLOSE + " m"
    )


def test_display_math_is_never_glued():
    assert _glue("#", r" \[x^2\]") == OPEN + "[0]" + CLOSE + r" \[x^2\]"


def test_a_tag_stops_the_word_so_markup_stays_well_formed():
    assert _glue("#", " <em>cm</em>") == OPEN + "[0]" + CLOSE + " <em>cm</em>"
    assert _glue("<b>x</b>", "#") == "<b>x</b>" + OPEN + "[0]" + CLOSE
    assert _glue("x<b>y", "#", "z</b>") == "x<b>" + OPEN + "y[0]z" + CLOSE + "</b>"


def test_nbsp_is_whitespace_not_a_word():
    assert _glue("#", r"&nbsp;\(\pi\)") == OPEN + r"[0]&nbsp;\(\pi\)" + CLOSE
    assert _glue("#", "&nbsp;") == OPEN + "[0]" + CLOSE + "&nbsp;"


def test_two_boxes_split_at_the_space_between_them():
    got = _glue("#", r" \(\pi\) ", "#", "°")
    assert got == OPEN + r"[0] \(\pi\)" + CLOSE + " " + OPEN + "[1]°" + CLOSE


def test_boxes_touching_with_no_space_share_one_group():
    assert _glue("#", "+", "#") == OPEN + "[0]+[1]" + CLOSE
    assert _glue("#", "#") == OPEN + "[0][1]" + CLOSE


def test_whitespace_only_neighbours_glue_nothing():
    assert _glue("a ", "#", " b") == OPEN + "a [0] b" + CLOSE
    assert _glue("   ", "#", "  ") == "   " + OPEN + "[0]" + CLOSE + "  "


def test_cell_parts_wraps_the_real_input_and_adds_nothing_else():
    S = "￿"
    html = r"x = " + f"{S}0{S}" + r" \(\pi\), then " + f"{S}1{S}°"
    cell = {"kind": "static", "html": html, "gaps": [["20"], ["75"]]}
    out = str(cell_parts(cell, 0, 0, done=False))
    groups = re.findall(r'<span class="filltable__gapglue">(.*?)</span>', out)
    assert len(groups) == 2
    assert groups[0].startswith("= <input") and groups[0].endswith(r'"> \(\pi\),')
    assert groups[1].startswith("then <input") and groups[1].endswith('">°')
    unglued = out.replace(OPEN, "").replace(CLOSE, "")
    assert re.sub(r"<input[^>]*>", "#", unglued) == r"x = # \(\pi\), then #°"
