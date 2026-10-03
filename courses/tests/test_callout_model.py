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
    assert str(CalloutElement(kind="warning").display_heading) == "Important"
    assert str(CalloutElement(kind="task").display_heading) == "Task"
    assert str(CalloutElement(kind="summary").display_heading) == "Key facts"


def test_display_heading_survives_stray_unsaved_kind():
    # Not-yet-saved instance carrying a stray value must not raise.
    assert str(CalloutElement(kind="bogus").display_heading) == "Example"


def test_a_summary_is_never_stored_numbered():
    """D5, the write-side guard. Mutant: remove the save() force -> True."""
    el = CalloutElement.objects.create(kind="summary", numbered=True, body="")
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False


def test_switching_to_summary_with_update_fields_still_unnumbers():
    """save(update_fields=["kind"]) would otherwise persist the kind and leave the
    stale True in the row. Mutant: drop the update_fields extension -> True."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    el.kind = "summary"
    el.save(update_fields=["kind"])
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False


def test_update_fields_generator_is_consumed_once():
    """Review Focus 5. Mutant: test membership on the raw iterable, then splat it
    -> the generator is already exhausted, only `numbered` is written, and the
    kind change is lost."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    el.kind = "summary"
    el.save(update_fields=(f for f in ["kind"]))
    el.refresh_from_db()
    assert el.kind == "summary"
    assert el.numbered is False


def test_the_callers_update_fields_list_is_not_mutated():
    """Review Focus 5. Mutant: `update_fields.append("numbered")` -> the caller's
    list grows behind its back."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    fields = ["kind"]
    el.kind = "summary"
    el.save(update_fields=fields)
    assert fields == ["kind"]


def test_empty_update_fields_stays_a_no_op():
    """Review Focus 5. Django treats an empty update_fields as "save nothing".
    Mutant: extend it even when empty -> {"numbered"} is written and the row
    flips to False."""
    el = CalloutElement.objects.create(kind="example", numbered=True, body="")
    el.kind = "summary"
    el.save(update_fields=[])
    el.refresh_from_db()
    assert el.kind == "example"
    assert el.numbered is True
