from scripts.lal_import.mathsafe import escape_math_delimited


def test_escapes_inside_inline_span():
    assert escape_math_delimited(r"gdy \(y<z\) koniec") == r"gdy \(y&lt;z\) koniec"


def test_escapes_inside_display_span():
    assert escape_math_delimited(r"\[a<b>c\]") == r"\[a&lt;b&gt;c\]"


def test_leaves_text_outside_spans_untouched():
    # A real HTML tag outside math must survive verbatim.
    assert escape_math_delimited(r"<p>x</p> \(a<b\)") == r"<p>x</p> \(a&lt;b\)"


def test_no_math_is_identity():
    assert escape_math_delimited("<strong>plain</strong>") == "<strong>plain</strong>"


def test_survives_nh3_roundtrip():
    import nh3

    body = escape_math_delimited(r"<p>gdy \(y<z\) tak</p>")
    cleaned = nh3.clean(body)
    assert r"\(y&lt;z\)" in cleaned  # the whole span survives sanitization


def test_escape_before_bs4_yields_wellformed_dom():
    # THE ordering guarantee (see Global Constraints): escaping the RAW string
    # first lets BeautifulSoup build a correct DOM. Escaping AFTER BS4 cannot —
    # this test locks in the escape-then-parse order the parser tasks rely on.
    from bs4 import BeautifulSoup

    raw = r"<p>gdy \(y<z\) tak</p>"
    good = BeautifulSoup(escape_math_delimited(raw), "html.parser")
    assert good.p is not None and good.p.get_text() == r"gdy \(y<z\) tak"
    # And the broken order mangles it (documents WHY the order matters):
    bad = BeautifulSoup(raw, "html.parser")
    assert bad.get_text() != r"gdy \(y<z\) tak"
