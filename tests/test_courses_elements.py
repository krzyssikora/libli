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


@pytest.mark.django_db
def test_video_xor_rejects_neither_and_both():
    from django.core.exceptions import ValidationError

    from courses.models import VideoElement

    neither = VideoElement()
    with pytest.raises(ValidationError):
        neither.full_clean()
    both = VideoElement(url="https://www.youtube.com/watch?v=x", file="v.mp4")
    with pytest.raises(ValidationError):
        both.full_clean()


@pytest.mark.django_db
def test_embed_url_requires_https_and_whitelist():
    from django.core.exceptions import ValidationError

    from courses.models import IframeElement

    ok = IframeElement(url="https://www.geogebra.org/m/abc")
    ok.full_clean()  # allowed host
    sub = IframeElement(url="https://sub.geogebra.org/m/abc")
    sub.full_clean()  # subdomain allowed
    bad_scheme = IframeElement(url="http://www.geogebra.org/m/abc")
    with pytest.raises(ValidationError):
        bad_scheme.full_clean()
    bad_host = IframeElement(url="https://evil.example.com/m/abc")
    with pytest.raises(ValidationError):
        bad_host.full_clean()
