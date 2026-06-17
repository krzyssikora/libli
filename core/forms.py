"""Forms for the core surfaces."""

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from accounts.provisioning import verified_email_belongs_to_other
from core.services import get_site_config


class UserSettingsForm(forms.ModelForm):
    """Edit the current user's UI prefs + email. `username` is intentionally NOT a
    field (school-assigned, read-only). `language` choices are narrowed at init to
    the institution's enabled languages."""

    class Meta:
        model = User
        fields = ["theme", "language", "display_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(settings.LANGUAGES)
        enabled = get_site_config()["enabled_languages"]
        self.fields["language"].choices = [(c, labels.get(c, c)) for c in enabled]

    def clean_email(self):
        # EmailField has already stripped; treat falsy as blank -> None (matches the
        # model's NULL normalization, so changed_data vs initial=None is stable).
        email = self.cleaned_data.get("email")
        if not email:
            return None
        email = email.lower()
        # Path (b): a verified allauth EmailAddress for this address on another user.
        # Reuse the existing guard so ensure_verified_primary_email can never raise.
        if verified_email_belongs_to_other(email, self.instance):
            raise forms.ValidationError(
                _("This email is already in use by another account.")
            )
        return email
