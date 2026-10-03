import pytest

from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import CalloutElementForm

pytestmark = pytest.mark.django_db


def test_registered_in_form_for_type():
    assert FORM_FOR_TYPE["callout"] is CalloutElementForm


def test_valid_full_save():
    form = CalloutElementForm(
        data={"kind": "warning", "heading": "Careful", "body": "<p>x</p>"}
    )
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.kind == "warning"
    assert el.heading == "Careful"
    # No `numbered` key was posted: an unchecked checkbox transmits nothing, so
    # this is indistinguishable from a deliberate untick. Pin the deliberate
    # False, don't let it drift silently.
    assert el.numbered is False


def test_blank_heading_and_body_are_valid():
    form = CalloutElementForm(data={"kind": "tip", "heading": "", "body": ""})
    assert form.is_valid(), form.errors
    el = form.save()
    assert el.heading == ""
    assert el.display_heading  # falls back to the kind default


def _summary():
    from courses.models import CalloutElement

    return CalloutElement.objects.create(kind="summary", heading="", body="")


def test_leaving_summary_restores_the_new_kinds_numbered_default():
    """T7c. Mutant: remove the clean() restore -> False (no key was sent)."""
    form = CalloutElementForm(
        data={"kind": "example", "heading": "", "body": ""}, instance=_summary()
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["numbered"] is True


def test_a_sent_false_is_never_overridden():
    """T7c. Mutant: drop the key-presence check -> True."""
    form = CalloutElementForm(
        data={"kind": "example", "numbered": "false", "heading": "", "body": ""},
        instance=_summary(),
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["numbered"] is False


def test_the_key_presence_check_is_prefix_safe():
    """A prefixed form's data key is "p-numbered". Mutant: test the bare
    "numbered" in self.data -> the sent False is overridden to True."""
    form = CalloutElementForm(
        data={
            "p-kind": "example",
            "p-numbered": "false",
            "p-heading": "",
            "p-body": "",
        },
        instance=_summary(),
        prefix="p",
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["numbered"] is False


def test_original_kind_is_read_before_validation_mutates_the_instance():
    """T7c. kind is VALID (so construct_instance copies it) and the heading is
    not, so the form fails AND the two attributes diverge. With an unchanged kind
    the lazy mutant could never go red. Mutant: derive original_kind lazily from
    self.instance (e.g. a property) -> "example"."""
    form = CalloutElementForm(
        data={"kind": "example", "heading": "z" * 121, "body": ""},
        instance=_summary(),
    )
    assert not form.is_valid()
    assert form.original_kind == "summary"
    assert form.instance.kind == "example"


def test_an_invalid_kind_skips_the_restore_and_reports_the_field():
    """kind failed choice validation -> no cleaned kind; the restore must not
    KeyError, and the normal field error must come back."""
    form = CalloutElementForm(
        data={"kind": "bogus", "heading": "", "body": ""}, instance=_summary()
    )
    assert not form.is_valid()
    assert "kind" in form.errors


def test_the_create_path_original_kind_is_the_default():
    assert CalloutElementForm().original_kind == "example"
