import pytest

from courses.models import RevealGateElement

pytestmark = pytest.mark.django_db


def test_render_button_hidden_with_marker():
    html = RevealGateElement.objects.create(label="").render()
    assert "data-reveal-gate" in html
    assert "hidden" in html
    assert "Show more" in html  # default label


def test_render_custom_label():
    html = RevealGateElement.objects.create(label="Reveal it").render()
    assert "Reveal it" in html
