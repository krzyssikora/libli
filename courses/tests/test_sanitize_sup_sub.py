"""Superscript and subscript: which sanitisers keep them, and which must not."""

import pytest

from courses import fillblank
from courses.recolour.replay import SHAPE_CELL
from courses.recolour.replay import SHAPE_COMPOSED
from courses.recolour.replay import SHAPE_HTML
from courses.recolour.replay import SHAPE_STEM
from courses.recolour.replay import key_for
from courses.sanitize import sanitize_caption
from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html

TAGS = ("sup", "sub")


@pytest.mark.parametrize("tag", TAGS)
def test_prose_keeps_the_tag(tag):
    value = f"<p>H<{tag}>2</{tag}>O</p>"
    assert sanitize_html(value) == value


@pytest.mark.parametrize("tag", TAGS)
def test_cells_keep_the_tag(tag):
    value = f"H<{tag}>2</{tag}>O"
    assert sanitize_cell(value) == value


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("sanitiser", [sanitize_html, sanitize_cell])
def test_the_tag_carries_no_attributes(sanitiser, tag):
    cleaned = sanitiser(
        f'<{tag} onclick="x()" style="color:red" class="tc-red">2</{tag}>'
    )
    assert cleaned == f"<{tag}>2</{tag}>"


@pytest.mark.parametrize("tag", TAGS)
def test_captions_do_not_gain_the_tag(tag):
    # Captions have their own deliberately small toolbar, which has no such button.
    assert f"<{tag}>" not in sanitize_caption(f"m<{tag}>2</{tag}>")


@pytest.mark.parametrize("shape", [SHAPE_HTML, SHAPE_CELL, SHAPE_STEM, SHAPE_COMPOSED])
@pytest.mark.parametrize("tag", TAGS)
def test_recolour_key_still_replays_the_import_time_sanitiser(shape, tag):
    # The loader stored these sources with the tag stripped. A key built with the
    # widened allowlist keeps it and can never match the stored row.
    assert key_for(f"5cm<{tag}>3</{tag}>", shape) == "5cm3"


@pytest.mark.parametrize("tag", TAGS)
def test_fillblank_answer_is_plain_text_even_when_formatted(tag):
    # Answers are compared with what the student types. Formatting the 2 inside a
    # {{m2}} marker must not turn the tags into part of the accepted answer.
    _stem, blanks = fillblank.parse(f"<p>{{{{m<{tag}>2</{tag}>|m2 kw}}}}</p>")
    assert blanks == [["m2", "m2 kw"]]


def test_fillblank_answer_still_decodes_a_literal_less_than():
    _stem, blanks = fillblank.parse("<p>{{a &lt; b}}</p>")
    assert blanks == [["a < b"]]
