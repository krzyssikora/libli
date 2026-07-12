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


def test_render_carries_both_show_and_hide_labels():
    # Two-way toggle: the collapsed ("show") and open ("Hide") labels both ship in
    # the DOM; CSS swaps which is visible on [open]. Guards the "still says Reveal
    # after opening" regression.
    el = SpoilerElement.objects.create(label="Show solution", body="<p>x</p>")
    html = el.render()
    assert "spoiler__label--show" in html and "Show solution" in html
    assert "spoiler__label--hide" in html and "Hide" in html
