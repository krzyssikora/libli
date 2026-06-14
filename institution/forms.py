"""Minimal operational institution settings (branding admin is Phase 5)."""

from django import forms
from django.conf import settings

from institution.models import Institution


class InstitutionSettingsForm(forms.ModelForm):
    # enabled_languages is a JSONField; a plain ModelForm renders a raw-JSON
    # textarea. Override with a multi-select so it round-trips to a list.
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES, widget=forms.CheckboxSelectMultiple
    )
    # default_language has no model choices; constrain it to the supported set.
    default_language = forms.ChoiceField(choices=settings.LANGUAGES)

    class Meta:
        model = Institution
        fields = [
            "enabled_languages",
            "default_language",
            "default_theme",
            "signup_policy",
        ]

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError("Enable at least one language.")
        return value  # a list -> stored in the JSONField

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error(
                "default_language",
                "Default language must be an enabled language.",
            )
        return cleaned
