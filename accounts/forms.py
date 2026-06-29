from allauth.account.adapter import get_adapter
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from accounts.emails import reconcile_primary_email
from accounts.provisioning import verified_email_belongs_to_other
from accounts.services import is_last_active_platform_admin
from accounts.services import set_user_role
from institution.roles import PLATFORM_ADMIN
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
    display_name = forms.CharField(
        max_length=150, required=False, label=_("Display name")
    )
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


class UserEditForm(forms.Form):
    """PA edit of role / display_name / email. is_active is NOT here (button-only).

    Role select has an explicit blank "— No role —" with no implicit default, so a
    role-less/multi-role user is never silently assigned Student. When `editing_self`,
    the role field is disabled server-side (Django disabled=True discards any posted
    value, defeating a forged POST). Email is optional and validated only when
    non-blank (case-insensitive uniqueness + verified-elsewhere guard).
    """

    display_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(required=False)

    def __init__(self, *args, instance, editing_self, **kwargs):
        self.instance = instance
        self.editing_self = editing_self
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [("", _("— No role —"))] + list(ROLE_CHOICES)
        if editing_self:
            self.fields["role"].disabled = True  # discards posted data

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            return ""
        clash = (
            get_user_model()
            .objects.filter(email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if clash:
            raise forms.ValidationError(_("Another user already uses this email."))
        if verified_email_belongs_to_other(email, self.instance):
            raise forms.ValidationError(
                _("A verified account elsewhere already owns this email.")
            )
        return email

    def save(self):
        """Apply role + name + email atomically. Demote of the last active PA is
        re-checked under select_for_update inside this transaction; failure raises
        forms.ValidationError (caught by the view -> re-render)."""
        user = self.instance
        new_role = self.cleaned_data.get("role")
        new_email = self.cleaned_data.get("email") or None
        email_changed = (new_email or "") != (user.email or "")
        with transaction.atomic():
            if new_role and not self.editing_self:
                demoting = (
                    PLATFORM_ADMIN in user.groups.values_list("name", flat=True)
                    and new_role != PLATFORM_ADMIN
                )
                if demoting and is_last_active_platform_admin(user, lock=True):
                    raise forms.ValidationError(
                        _("Cannot demote the last active Platform Admin.")
                    )
                set_user_role(user, new_role)
            user.display_name = self.cleaned_data.get("display_name", "")
            user.email = new_email
            user.save(update_fields=["display_name", "email"])
            if email_changed:
                reconcile_primary_email(user)
        return user
