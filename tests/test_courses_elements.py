import pytest

from tests.factories import ContentNodeFactory


@pytest.mark.django_db
def test_textelement_sanitised_on_save():
    from courses.models import TextElement

    el = TextElement.objects.create(body="<p>hi</p><script>alert(1)</script>")
    assert "<script>" not in el.body
    assert "<p>hi</p>" in el.body


@pytest.mark.django_db
def test_element_render_dispatches_to_template_and_join_row():
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    text = TextElement.objects.create(body="<p>lesson body</p>")
    el = Element.objects.create(unit=unit, content_object=text)
    html = el.content_object.render()
    assert "lesson body" in html


@pytest.mark.django_db
def test_deleting_concrete_element_cascades_join_row():
    from courses.models import Element
    from courses.models import TextElement

    unit = ContentNodeFactory(kind="unit", unit_type="lesson")
    text = TextElement.objects.create(body="<p>x</p>")
    Element.objects.create(unit=unit, content_object=text)
    assert Element.objects.count() == 1
    text.delete()
    assert Element.objects.count() == 0  # GenericRelation cascade


@pytest.mark.django_db
def test_textelement_strips_disallowed_url_scheme():
    from courses.models import TextElement

    el = TextElement.objects.create(
        body='<a href="ftp://x/y">f</a><a href="https://ok.example/">ok</a>'
    )
    assert "ftp://" not in el.body
    assert "https://ok.example/" in el.body
