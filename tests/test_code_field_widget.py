from courses.widgets import CodeTextarea


def test_code_textarea_wraps_in_code_field():
    html = CodeTextarea().render("html", "<b>x</b>", attrs={"id": "id_html"})
    assert 'class="code-field"' in html
    assert "data-code-field" in html
    assert "<textarea" in html
    # the user's content is preserved and HTML-escaped inside the textarea
    assert "&lt;b&gt;x&lt;/b&gt;" in html
