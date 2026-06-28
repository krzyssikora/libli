from django import forms
from django.utils.translation import gettext_lazy as _

from notes import services
from notes.models import NOTE_MAX_LEN


class NoteForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": NOTE_MAX_LEN}),
        label=_("Note"),
        strip=False,  # we normalize ourselves; do not let Django pre-strip
    )

    def clean_body(self):
        body = services.normalize_body(self.cleaned_data.get("body", ""))
        if not body:
            raise forms.ValidationError(_("A note cannot be empty."))
        if len(body) > NOTE_MAX_LEN:
            raise forms.ValidationError(
                _("This note is too long (max 5000 characters).")
            )
        return body
