from courses.sanitize import sanitize_cell
from courses.sanitize import sanitize_html


def test_keeps_s():
    assert sanitize_html("<p><s>old</s> new</p>") == "<p><s>old</s> new</p>"


def test_strike_is_not_kept_server_side():
    # The toolbar renames <strike> to <s> before save; the server keeps only <s>.
    assert sanitize_html("<p><strike>old</strike></p>") == "<p>old</p>"


def test_cells_do_not_gain_s():
    # Strikethrough ships in the prose toolbar only; table cells stay unchanged.
    assert "<s>" not in sanitize_cell("<s>old</s>")
