from django import forms

from notifications.models import NotificationEmailPreference


class NotificationEmailForm(forms.ModelForm):
    """Per-kind email opt-out checkboxes. Meta.fields is the three booleans ONLY —
    NOT "__all__", which would include the required editable `user` OneToOne field,
    making the form invalid and (because the settings view gates on both forms
    validating) silently blocking the entire POST. `user` is supplied via
    instance=pref."""

    class Meta:
        model = NotificationEmailPreference
        fields = ["quiz_needs_review", "quiz_graded", "enrolled"]
