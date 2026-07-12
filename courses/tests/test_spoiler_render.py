import pytest

from courses.models import SpoilerElement

pytestmark = pytest.mark.django_db


def test_render_shows_label_and_body():
    el = SpoilerElement.objects.create(label="Show solution", body="<p>answer</p>")
    html = el.render()
    assert "<details" in html and 'class="spoiler"' in html
    assert "<summary" in html and "Show solution" in html
    assert 'class="el el--text spoiler__body"' in html
    assert "<p>answer</p>" in html


def test_render_default_label_when_blank():
    el = SpoilerElement.objects.create(label="", body="<p>x</p>")
    html = el.render()
    assert "Reveal" in html  # {% trans "Reveal" %} default under the EN catalog
