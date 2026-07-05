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
    external_id = forms.CharField(
        max_length=64,
        required=False,
        label=_("Register student id"),
        help_text=_("Student number in your external register."),
    )

    def __init__(self, *args, instance, editing_self, **kwargs):
        self.instance = instance
        self.editing_self = editing_self
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [("", _("— No role —"))] + list(ROLE_CHOICES)
        self.fields["external_id"].initial = self.instance.external_id
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
            user.external_id = self.cleaned_data.get("external_id", "")
            user.save(update_fields=["display_name", "email", "external_id"])
            if email_changed:
                reconcile_primary_email(user)
        return user


class SsoForm(forms.Form):
    """Platform-admin OIDC SSO config. Plain Form (settings is JSON, sites is M2M,
    secret is write-only). The `app` kwarg (loaded SocialApp or None) lets `clean`
    check the stored-secret case for the enable-completeness rule."""

    enabled = forms.BooleanField(required=False, label=_("Enable SSO"))
    name = forms.CharField(
        required=False,
        max_length=40,
        label=_("Display name"),
        help_text=_("Shown on the sign-in button, e.g. 'Continue with Acme'."),
    )
    server_url = forms.URLField(
        required=False,
        assume_scheme="https",
        label=_("Issuer / discovery URL"),
        help_text=_(
            "Your IdP's issuer base URL, e.g. https://idp.example.com. The "
            "/.well-known/openid-configuration discovery path is added automatically "
            "(you may also paste a full discovery URL)."
        ),
    )
    client_id = forms.CharField(required=False, max_length=191, label=_("Client ID"))
    client_secret = forms.CharField(
        required=False,
        max_length=191,
        widget=forms.PasswordInput(render_value=False),
        label=_("Client secret"),
    )

    def __init__(self, *args, app=None, **kwargs):
        self.app = app  # stored before super() so clean() can read self.app.secret
        # Distinct auto_id: settings.html renders all four tab forms at once, and
        # BrandingForm also has a `name` field -> a default "id_%s" would emit two
        # id="id_name" inputs and the SSO label's `for` would target the wrong one.
        kwargs.setdefault("auto_id", "id_sso_%s")
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        server_url = cleaned.get("server_url", "")
        if server_url:
            if not server_url.lower().startswith("https://"):
                self.add_error("server_url", _("The issuer URL must use https."))
            else:
                # Write the normalized value back so form.cleaned_data (which the
                # view hands to the service) carries the rstrip'd issuer.
                cleaned["server_url"] = server_url.rstrip("/")
        if cleaned.get("enabled"):
            # Skip a field already carrying an error: add_error() pops it from
            # cleaned_data, so a filled-but-invalid issuer must not also draw a
            # spurious "required to enable SSO".
            for field in ("name", "server_url", "client_id"):
                if not cleaned.get(field) and field not in self.errors:
                    self.add_error(field, _("Required to enable SSO."))
            has_secret = bool(cleaned.get("client_secret")) or bool(
                self.app and self.app.secret
            )
            if not has_secret and "client_secret" not in self.errors:
                self.add_error(
                    "client_secret", _("Enter the client secret to enable SSO.")
                )
        return cleaned
