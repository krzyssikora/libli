import pytest

from courses.models import RevealGateElement
from courses.templatetags.courses_manage_extras import element_summary

pytestmark = pytest.mark.django_db


def test_summary_uses_label():
    el = RevealGateElement.objects.create(label="Reveal hint")
    assert "Reveal hint" in element_summary(el)


def test_summary_default_when_blank():
    el = RevealGateElement.objects.create(label="")
    assert element_summary(el)  # non-empty default, e.g. "Show more"
