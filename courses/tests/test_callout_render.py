import pytest

from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_render_carries_kind_modifier_class_and_heading_default():
    html = CalloutElement(kind="warning", body="<p>hi</p>").render()
    assert "callout--warning" in html
    assert "Warning" in html  # default heading
    assert "hi" in html


def test_render_uses_heading_override():
    html = CalloutElement(kind="tip", heading="Pro tip", body="").render()
    assert "Pro tip" in html
    assert "callout--tip" in html


def test_render_selects_correct_icon_per_kind():
    # The four kinds emit four distinct icon markers; assert the book-open path
    # (Example) is present only for example, and the triangle (warning) for warning.
    example = CalloutElement(kind="example", body="").render()
    warning = CalloutElement(kind="warning", body="").render()
    assert "callout__icon" in example
    # book-open has a distinctive M12 7v14 spine; warning has the triangle path.
    assert "M12 7v14" in example
    assert "M12 7v14" not in warning


def test_render_sanitizes_body_on_output():
    el = CalloutElement.objects.create(kind="note", body="<script>x</script><p>ok</p>")
    html = el.render()
    assert "<script>" not in html
    assert "ok" in html
