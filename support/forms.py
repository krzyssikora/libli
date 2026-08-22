"""Forms for the report dialog and the PA settings surfaces."""

from django import forms
from django.utils.translation import gettext_lazy as _

from support.constants import DESCRIPTION_MAX_LENGTH
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import PAGE_URL_MAX_LENGTH
from support.models import IssueReport


class IssueReportForm(forms.ModelForm):
    """Only the four reporter-supplied columns.

    NEVER fields = "__all__": that would let any permitted reporter POST
    status=resolved, reporter=<someone else's pk>, emailed_at, resolved_by or a
    hand-built telemetry blob, defeating both the sanitiser (which deliberately
    routes around this form) and the triage audit trail. Every other column is
    assigned by the view.
    """

    description = forms.CharField(
        max_length=DESCRIPTION_MAX_LENGTH,
        widget=forms.Textarea,
        label=_("What went wrong?"),
    )
    # Declared explicitly with NO max_length. A ModelForm-derived page_title would
    # carry MaxLengthValidator, which runs inside _clean_fields before
    # clean_page_title — and Django skips a clean_<field> hook when the field
    # itself raised — so an over-long title would 400 instead of being truncated.
    page_title = forms.CharField(required=False, widget=forms.HiddenInput)
    page_url = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = IssueReport
        fields = ["description", "page_url", "page_title", "screenshot"]

    def clean_description(self):
        value = (self.cleaned_data.get("description") or "").strip()
        if not value:
            raise forms.ValidationError(_("Please describe what went wrong."))
        return value

    def clean_page_url(self):
        return (self.cleaned_data.get("page_url") or "")[:PAGE_URL_MAX_LENGTH]

    def clean_page_title(self):
        return (self.cleaned_data.get("page_title") or "")[:PAGE_TITLE_MAX_LENGTH]
