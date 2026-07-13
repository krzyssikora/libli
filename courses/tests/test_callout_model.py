import pytest

from courses.models import ELEMENT_MODELS
from courses.models import CalloutElement

pytestmark = pytest.mark.django_db


def test_registered_in_element_models():
    assert "calloutelement" in ELEMENT_MODELS


def test_body_is_sanitized_on_save():
    el = CalloutElement.objects.create(
        kind="note", body="<script>alert(1)</script><p>ok</p>"
    )
    el.refresh_from_db()
    assert "<script>" not in el.body
    assert "ok" in el.body


def test_unknown_kind_coerced_to_example():
    el = CalloutElement.objects.create(kind="bogus", body="")
    el.refresh_from_db()
    assert el.kind == "example"


def test_blank_kind_coerced_to_example():
    el = CalloutElement.objects.create(kind="", body="")
    el.refresh_from_db()
    assert el.kind == "example"


def test_display_heading_uses_override_when_set():
    el = CalloutElement(kind="tip", heading="Pro tip")
    assert el.display_heading == "Pro tip"


def test_display_heading_falls_back_to_kind_default():
    # gettext_lazy under the EN catalog renders the English label.
    assert str(CalloutElement(kind="example").display_heading) == "Example"
    assert str(CalloutElement(kind="note").display_heading) == "Note"
    assert str(CalloutElement(kind="tip").display_heading) == "Tip"
    assert str(CalloutElement(kind="warning").display_heading) == "Warning"


def test_display_heading_survives_stray_unsaved_kind():
    # Not-yet-saved instance carrying a stray value must not raise.
    assert str(CalloutElement(kind="bogus").display_heading) == "Example"
