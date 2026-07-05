from urllib.parse import urlparse

from django import forms
from django.utils.translation import gettext_lazy as _

from integrations.models import WebhookEndpoint


class IntegrationsForm(forms.ModelForm):
    # required=False + preserve-on-blank: a blank submit keeps the stored secret.
    secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label=_("Signing secret"),
        help_text=_("Leave blank to keep the current secret."),
    )

    class Meta:
        model = WebhookEndpoint
        fields = ["enabled", "url", "secret"]
        labels = {"enabled": _("Enable result sync"), "url": _("Endpoint URL")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Snapshot the stored secret BEFORE _post_clean overwrites self.instance.
        self._existing_secret = self.instance.secret

    def clean_url(self):
        url = self.cleaned_data.get("url", "")
        if url and urlparse(url).scheme not in ("http", "https"):
            raise forms.ValidationError(_("URL must use http or https."))
        return url

    def clean(self):
        cleaned = super().clean()
        enabled = cleaned.get("enabled")
        url = cleaned.get("url")
        has_secret = bool(cleaned.get("secret")) or bool(self._existing_secret)
        if enabled and not url:
            self.add_error("url", _("A URL is required to enable result sync."))
        if enabled and not has_secret:
            self.add_error(
                "secret", _("A signing secret is required to enable result sync.")
            )
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not self.cleaned_data.get("secret"):
            obj.secret = self._existing_secret  # preserve when blank
        if commit:
            obj.save()
        return obj
