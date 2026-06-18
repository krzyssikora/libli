"""Operational institution settings (branding colours admin is Phase 5)."""

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from institution.models import Institution

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB


class InstitutionSettingsForm(forms.ModelForm):
    # enabled_languages is a JSONField; a plain ModelForm renders a raw-JSON
    # textarea. Override with a multi-select so it round-trips to a list.
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,
        widget=forms.CheckboxSelectMultiple,
        label=_("Enabled languages"),
    )
    # default_language has no model choices; constrain it to the supported set.
    default_language = forms.ChoiceField(
        choices=settings.LANGUAGES, label=_("Default language")
    )

    class Meta:
        model = Institution
        fields = [
            "name",
            "logo",
            "enabled_languages",
            "default_language",
            "default_theme",
            "signup_policy",
        ]

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError(_("Enable at least one language."))
        return value  # a list -> stored in the JSONField

    def clean_logo(self):
        # ClearableFileInput yields False (clear), the unchanged stored file, or
        # None when no new upload. Only an actual upload has .size — short-circuit
        # the rest, or False.size raises AttributeError. ImageField+Pillow already
        # gate non-images by decoding; clean_logo is size-only.
        value = self.cleaned_data.get("logo")
        if (
            not value
        ):  # False (clear), None/"" (no upload) are all falsy -> nothing to size-check
            return value
        if getattr(value, "size", 0) > MAX_LOGO_BYTES:
            raise forms.ValidationError(_("Logo must be 2 MB or smaller."))
        return value

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error(
                "default_language",
                _("Default language must be an enabled language."),
            )
        return cleaned
