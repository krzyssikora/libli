from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html
from courses.sanitize import sanitize_label

BLOCK_TAGS = ["p", "div", "h2", "h3", "h4", "blockquote", "li"]


def test_keeps_align_class_on_each_block_tag():
    for tag in BLOCK_TAGS:
        out = sanitize_html(f'<{tag} class="ta-center">x</{tag}>')
        assert 'class="ta-center"' in out, f"{tag} lost ta-center: {out!r}"


def test_keeps_ta_left_and_ta_right():
    assert 'class="ta-left"' in sanitize_html('<p class="ta-left">x</p>')
    assert 'class="ta-right"' in sanitize_html('<p class="ta-right">x</p>')


def test_reduces_combined_class_to_the_align_token():
    out = sanitize_html('<p class="ta-center foo">x</p>')
    assert "ta-center" in out
    assert "foo" not in out


def test_drops_unknown_class_value():
    assert "evil" not in sanitize_html('<p class="evil">x</p>')


def test_drops_align_class_on_non_block_tag():
    assert "ta-center" not in sanitize_html('<b class="ta-center">x</b>')


def test_cell_and_label_stay_class_free():
    assert "class" not in sanitize_cell('<b class="ta-center">x</b>')
    assert "ta-center" not in sanitize_label('<span class="ta-center">x</span>')
