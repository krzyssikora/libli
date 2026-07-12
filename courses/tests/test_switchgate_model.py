import pytest

from courses.models import ELEMENT_MODELS
from courses.models import SwitchGateElement

pytestmark = pytest.mark.django_db


def test_switchgate_registered_in_element_models():
    assert "switchgateelement" in ELEMENT_MODELS


def test_switchgate_defaults():
    el = SwitchGateElement.objects.create(stem="", options=[], answer=0)
    assert el.options == []
    assert el.answer == 0


def test_switchgate_save_sanitizes_options():
    el = SwitchGateElement.objects.create(
        stem="pick ﻿",  # arbitrary text
        options=["<b>ok</b>", "<script>x</script>bad", "\\(+\\)"],
        answer=0,
    )
    el.refresh_from_db()
    assert el.options[0] == "<b>ok</b>"  # allowed tag kept
    assert "<script>" not in el.options[1]  # script stripped
    assert "bad" in el.options[1]  # text preserved
    assert el.options[2] == "\\(+\\)"  # LaTeX preserved
