import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import ELEMENT_MODELS
from courses.models import RevealGateElement

pytestmark = pytest.mark.django_db


def test_reveal_gate_creates_with_label():
    el = RevealGateElement.objects.create(label="Reveal step 2")
    assert el.pk is not None
    assert el.label == "Reveal step 2"


def test_reveal_gate_label_optional():
    el = RevealGateElement.objects.create()
    assert el.label == ""


def test_reveal_gate_in_element_models():
    assert "revealgateelement" in ELEMENT_MODELS


def test_reveal_gate_content_type_registered():
    # ContentType row exists after migrate (contenttypes' post_migrate creates
    # one for every installed model). The limit_choices_to wiring is exercised
    # end-to-end by the editor add/save test in Task 2, not asserted here.
    ct = ContentType.objects.get(app_label="courses", model="revealgateelement")
    assert ct is not None
