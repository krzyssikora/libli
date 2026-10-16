from django import forms

from notifications.models import NotificationEmailPreference
from notifications.models import NotificationPushPreference


class NotificationEmailForm(forms.ModelForm):
    """Per-kind email opt-out checkboxes. Meta.fields is the three booleans ONLY —
    NOT "__all__", which would include the required editable `user` OneToOne field,
    making the form invalid and (because the settings view gates on both forms
    validating) silently blocking the entire POST. `user` is supplied via
    instance=pref."""

    class Meta:
        model = NotificationEmailPreference
        fields = ["quiz_needs_review", "quiz_graded", "enrolled"]


class NotificationPushForm(forms.ModelForm):
    """Per-kind PUSH opt-outs. ALWAYS built with prefix="push": the booleans share
    their names with NotificationEmailForm's (which has no prefix), so without it
    both rows would post name="quiz_graded" and ticking either box would set both."""

    class Meta:
        model = NotificationPushPreference
        fields = ["quiz_needs_review", "quiz_graded", "enrolled"]
