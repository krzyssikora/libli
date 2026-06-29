"""Operational institution settings (branding colours admin is Phase 5)."""

import re

from django import forms
from django.conf import settings
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from core.services import ACCENT_DEFAULT
from core.services import PRIMARY_DEFAULT
from institution.models import BrandColor
from institution.models import Institution

MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB

_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_HEX3 = re.compile(r"^#[0-9a-fA-F]{3}$")


def normalize_hex(value):
    """Return a lowercased #rrggbb hex, expanding #rgb; None if not coercible."""
    v = (value or "").strip()
    if _HEX3.match(v):
        return "#" + "".join(c * 2 for c in v[1:]).lower()
    if _HEX6.match(v):
        return v.lower()
    return None


def _hex_field(label):
    field = forms.RegexField(
        regex=_HEX6,
        label=label,
        error_messages={"invalid": _("Enter a 6-digit hex colour like #147E78.")},
    )
    field.widget.attrs["data-hex"] = "1"  # JS hook to mirror the <input type=color>
    return field


class BrandingForm(forms.ModelForm):
    enabled_languages = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,
        widget=forms.CheckboxSelectMultiple,
        label=_("Enabled languages"),
    )
    default_language = forms.ChoiceField(
        choices=settings.LANGUAGES, label=_("Default language")
    )
    primary = _hex_field(_("Primary colour"))
    accent = _hex_field(_("Accent colour"))

    class Meta:
        model = Institution
        fields = [
            "name",
            "logo",
            "enabled_languages",
            "default_language",
            "default_theme",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Seed the colour fields from existing BrandColor rows, normalized to
        # 6-digit lowercase hex so a pre-existing #fff / #AABBCC / rgb() value can
        # never start the field in a state that rejects an unrelated save.
        rows = (
            {c.key: c.value for c in self.instance.brand_colors.all()}
            if self.instance.pk
            else {}
        )
        self.initial.setdefault(
            "primary", normalize_hex(rows.get("primary")) or PRIMARY_DEFAULT.lower()
        )
        self.initial.setdefault(
            "accent", normalize_hex(rows.get("accent")) or ACCENT_DEFAULT.lower()
        )

    def clean_enabled_languages(self):
        value = self.cleaned_data["enabled_languages"]
        if not value:
            raise forms.ValidationError(_("Enable at least one language."))
        return value

    def clean_logo(self):
        value = self.cleaned_data.get("logo")
        if not value:
            return value
        if getattr(value, "size", 0) > MAX_LOGO_BYTES:
            raise forms.ValidationError(_("Logo must be 2 MB or smaller."))
        return value

    def clean_primary(self):
        return self.cleaned_data["primary"].lower()

    def clean_accent(self):
        return self.cleaned_data["accent"].lower()

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled_languages") or []
        default = cleaned.get("default_language")
        if default and default not in enabled:
            self.add_error(
                "default_language", _("Default language must be an enabled language.")
            )
        return cleaned

    def save(self, commit=True):
        with transaction.atomic():
            inst = super().save(commit=commit)
            for key in ("primary", "accent"):
                BrandColor.objects.update_or_create(
                    institution=inst,
                    key=key,
                    defaults={"value": self.cleaned_data[key]},
                )
        return inst


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
