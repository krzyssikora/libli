"""Forms for the report dialog and the PA settings surfaces."""

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import EmailValidator
from django.db.models import Q
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _

from institution.roles import PLATFORM_ADMIN
from support.constants import DESCRIPTION_MAX_LENGTH
from support.constants import EXTRA_EMAILS_MAX
from support.constants import PAGE_TITLE_MAX_LENGTH
from support.constants import PAGE_URL_MAX_LENGTH
from support.models import IssueReport
from support.models import SupportSettings


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


class OutOfRosterCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    """Marks grants that appear only because of the roster union.

    The spec requires already-selected users outside the base roster to render
    "checked, with a muted note explaining why they are listed", and a plain
    CheckboxSelectMultiple has no per-option affordance. create_option is a
    WIDGET hook — putting it on the form would be dead code that never runs.
    """

    out_of_roster = frozenset()

    def create_option(self, name, value, label, *args, **kwargs):
        # Django passes a ModelChoiceIteratorValue here, so unwrap it.
        pk = getattr(value, "value", value)
        if pk in self.out_of_roster:
            label = format_lazy(
                "{label} — {note}",
                label=label,
                note=_("no longer in the roster; still allowed to report"),
            )
        option = super().create_option(name, value, label, *args, **kwargs)
        if pk in self.out_of_roster:
            option["attrs"]["data-out-of-roster"] = "1"
        return option


class ReporterPickerForm(forms.ModelForm):
    """The roster of individually-granted reporters.

    The queryset is active non-PA users UNIONED with whoever is currently
    selected. Scoped to active non-PA users alone, an already-granted user who
    has since been deactivated or promoted to PA would be absent from the
    rendered list, and the next save_m2m() would silently REVOKE them — a PA
    opening the page to add one person would drop an unrelated grant.
    """

    class Meta:
        model = SupportSettings
        fields = ["extra_reporters"]
        widgets = {"extra_reporters": OutOfRosterCheckboxSelectMultiple}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        selected = list(self.instance.extra_reporters.values_list("pk", flat=True))
        base = User.objects.filter(is_active=True).exclude(groups__name=PLATFORM_ADMIN)
        self.fields["extra_reporters"].queryset = (
            User.objects.filter(Q(pk__in=base.values("pk")) | Q(pk__in=selected))
            .distinct()
            .order_by("display_name", "username")
        )
        self.fields["extra_reporters"].required = False
        # Hand the widget the pks that survive only because of the union, so it
        # can mark them. Django calls create_option on the WIDGET, never the form.
        self.fields["extra_reporters"].widget.out_of_roster = set(selected) - set(
            base.values_list("pk", flat=True)
        )


class SupportSettingsForm(forms.ModelForm):
    """Audience + recipient addresses. Carries NO M2M field: _settings_context
    renders every panel on every settings render, so a per-user roster here would
    materialise one checkbox per active user on every GET of the Branding tab.
    The roster lives on its own page (support:reporters)."""

    audience = forms.ChoiceField(
        choices=SupportSettings.Audience.choices,
        widget=forms.RadioSelect,
        label=_("Who can report an issue"),
    )
    # Overridden explicitly: left to the ModelForm default a JSONField yields
    # forms.JSONField, whose textarea expects literal JSON — a field that looks
    # right and rejects everything a PA types.
    extra_emails = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("Also send reports to"),
        help_text=_(
            "One address per line. These addresses receive the full report, "
            "including any attached screenshot, which may contain student data."
        ),
    )

    class Meta:
        model = SupportSettings
        fields = ["audience", "extra_emails"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            stored = (self.instance.extra_emails or []) if self.instance else []
            self.initial["extra_emails"] = "\n".join(stored)

    def clean_extra_emails(self):
        raw = self.cleaned_data.get("extra_emails") or ""
        validate = EmailValidator()
        seen, addresses = set(), []
        for line in raw.splitlines():
            address = line.strip().lower()
            if not address:
                continue
            validate(address)
            if address not in seen:
                seen.add(address)
                addresses.append(address)
        if len(addresses) > EXTRA_EMAILS_MAX:
            raise forms.ValidationError(
                _("At most %(count)d addresses.") % {"count": EXTRA_EMAILS_MAX}
            )
        return addresses
