from courses.widgets import CodeTextarea


def test_code_textarea_wraps_in_code_field():
    html = CodeTextarea().render("html", "<b>x</b>", attrs={"id": "id_html"})
    assert 'class="code-field"' in html
    assert "data-code-field" in html
    assert "<textarea" in html
    # the user's content is preserved and HTML-escaped inside the textarea
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_html_element_form_uses_code_field_widget():
    from courses.element_forms import HtmlElementForm

    form = HtmlElementForm()
    assert isinstance(form.fields["html"].widget, CodeTextarea)
    rendered = str(form["html"])
    assert "data-code-field" in rendered
    assert "code-field__gutter" in rendered
    assert 'rows="12"' in rendered


def test_course_form_code_fields_use_code_field_widget():
    from courses.forms import CourseForm

    form = CourseForm()
    for name in ("html_css", "html_js"):
        assert isinstance(form.fields[name].widget, CodeTextarea), name
        rendered = str(form[name])
        assert "data-code-field" in rendered, name
        assert "code-field__gutter" in rendered, name
        assert 'rows="10"' in rendered, name
