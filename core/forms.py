"""Forms for the core surfaces."""

from django import forms
from django.conf import settings

from accounts.models import User
from core.services import get_site_config


class UserSettingsForm(forms.ModelForm):
    """Edit the current user's UI prefs. `username` is intentionally NOT a field
    (school-assigned, read-only). `language` choices are narrowed at init to the
    institution's enabled languages."""

    class Meta:
        model = User
        fields = ["theme", "language", "display_name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = dict(settings.LANGUAGES)
        enabled = get_site_config()["enabled_languages"]
        self.fields["language"].choices = [(c, labels.get(c, c)) for c in enabled]
