from courses.sanitize import sanitize_cell


def test_keeps_bold_italic_underline_tags():
    # execCommand emits <b>/<i>; strong/em/u also allowed. All survive.
    for tag in ("strong", "b", "em", "i", "u"):
        assert f"<{tag}>x</{tag}>" in sanitize_cell(f"<{tag}>x</{tag}>")
    assert "<br>" in sanitize_cell("a<br>b")


def test_strips_disallowed_markup():
    assert "<script>" not in sanitize_cell("<script>alert(1)</script>")
    assert "onclick" not in sanitize_cell('<b onclick="x">y</b>')
    assert "<div>" not in sanitize_cell("<div>x</div>")


def test_editor_path_lt_entity_converges_single_escaped():
    # Editor serialises via innerHTML, so a typed < arrives as the entity &lt;.
    assert sanitize_cell(r"\(a&lt;b\)") == r"\(a&lt;b\)"


def test_import_path_literal_lt_converges_single_escaped():
    # Import payload can carry a literal <. Canonicalises to the SAME stored value.
    assert sanitize_cell(r"\(a<b\)") == r"\(a&lt;b\)"


def test_idempotent_no_double_escape_on_reedit():
    once = sanitize_cell(r"\(a<b\)")
    assert sanitize_cell(once) == once  # re-edit adds no &amp; layer


def test_math_span_cannot_smuggle_live_markup():
    out = sanitize_cell(r"\(<img src=x onerror=alert(1)>\)")
    assert "onerror" in out  # preserved as inert text for KaTeX
    assert "<img" not in out  # but not as a live tag
    assert "&lt;img" in out


def test_unmatched_delimiter_left_as_literal_text():
    # A lone \( has no closing \) — not protected; sanitised as ordinary text.
    out = sanitize_cell(r"a \( b < c")  # literal < outside a balanced pair
    assert "<c" not in out  # ordinary < is dropped/escaped by nh3


def test_display_math_protected_too():
    assert sanitize_cell(r"\[a<b\]") == r"\[a&lt;b\]"
