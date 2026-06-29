from allauth.account.adapter import get_adapter
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from institution.roles import ROLE_CHOICES
from institution.roles import STUDENT


class SendInvitationForm(forms.Form):
    """Email + role for a new invite. The role select offers the 4 roles (default
    Student) with NO blank option — every invite carries a role."""

    email = forms.EmailField()
    role = forms.ChoiceField(choices=ROLE_CHOICES, initial=STUDENT)


class AcceptInviteForm(forms.Form):
    """Username + password for accepting an invite. Delegates validation to allauth's
    account adapter so invited accounts match open-signup accounts (same username
    case/uniqueness rules and the same password validators — including
    UserAttributeSimilarity against the username + invited email)."""

    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, invited_email=None, **kwargs):
        # The invited email is authoritative (from the Invitation, not the form);
        # it feeds password attribute-similarity validation, mirroring allauth signup.
        self.invited_email = invited_email
        super().__init__(*args, **kwargs)

    def clean_username(self):
        try:
            return get_adapter().clean_username(self.cleaned_data["username"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password:
            # Build a dummy unsaved user (username + invited email) so allauth's
            # clean_password runs UserAttributeSimilarityValidator exactly as the
            # open-signup form does (allauth.account.forms builds the same dummy_user).
            # Note: allauth's clean_password also re-runs the min-length check, so a
            # too-short password can show a duplicated message — expected, and identical
            # to open-signup; do not "fix" it by diverging from the adapter.
            dummy = get_user_model()(
                username=cleaned.get("username") or "", email=self.invited_email or ""
            )
            try:
                get_adapter().clean_password(password, user=dummy)
            except ValidationError as exc:
                self.add_error("password", forms.ValidationError(exc.messages))
        return cleaned
