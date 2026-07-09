# tests/test_sanitize_gallery.py
from courses.sanitize import desc_to_alt


def test_desc_to_alt_strips_tags_and_math():
    assert desc_to_alt("<strong>Cell</strong> shape") == "Cell shape"
    assert desc_to_alt(r"A \(x^2\) curve") == "A curve"  # math removed
    assert desc_to_alt(r"\(x^2\)") == ""  # math-only -> empty
    assert desc_to_alt("") == ""
    assert desc_to_alt("   ") == ""
    assert desc_to_alt("<b>bold</b>&amp;<i>it</i>") == "bold&it"  # unescaped, tags gone
    assert desc_to_alt("line<br>two") == "line two"  # br -> space, collapsed
