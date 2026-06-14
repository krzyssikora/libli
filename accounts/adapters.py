from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from accounts.emails import ensure_verified_primary_email
from accounts.models import Invitation
from accounts.provisioning import evaluate_sso_provisioning
from accounts.provisioning import resolve_user_for_email
from accounts.provisioning import verified_email_belongs_to_other
from institution.models import Institution


class AccountAdapter(DefaultAccountAdapter):
    """Gate self-signup on the institution's runtime signup policy (spec §4).

    `open`  -> self-signup enabled (email required + confirmed; honeypot active).
    `invite` (or anything else) -> self-signup disabled; accounts arrive via the
    Django admin (Plan 0a) and, later, invite tokens (Plan 0c).
    """

    def is_open_for_signup(self, request):
        return Institution.load().signup_policy == "open"


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """JIT provisioning + link-by-email for SSO logins. Thin shell over the pure
    helpers in accounts.provisioning; see Plan 0c-2 / spec §2."""

    def pre_social_login(self, request, sociallogin):
        # Already linked to a local user (incl. allauth's verified-EmailAddress
        # auto-connect, which ran in lookup() before this hook) -> log them in.
        if sociallogin.is_existing:
            return
        # Normalize once. (All downstream lookups are iexact / rpartition+lower, so
        # this is belt-and-suspenders for consistent stash-vs-fallback selection.)
        email = (sociallogin.user.email or "").strip().lower()
        if email:
            target = resolve_user_for_email(email)
            if target is not None:
                # Clash guard for the data-drift case only: when tier-3 (User.email)
                # resolves a different user than the verified-EmailAddress owner.
                # In the normal tier-1 path `target` already owns the verified row,
                # so this is inert (NOT dead code — keep it). connect() is NOT
                # transactional and notifies, so deny BEFORE connecting.
                if verified_email_belongs_to_other(email, target):
                    raise ImmediateHttpResponse(self._not_provisioned())
                sociallogin.connect(request, target)
                ensure_verified_primary_email(target, email)
                return
        # Brand-new identity: gate it.
        invitation = Invitation.find_pending(email) if email else None
        decision = self._evaluate(email, invitation)
        if not decision.allow:
            raise ImmediateHttpResponse(self._not_provisioned())
        # Stash the exact invite the allow was made on; save_user consumes it.
        sociallogin._libli_invitation = decision.invitation_to_consume

    def is_open_for_signup(self, request, sociallogin):
        # REQUIRED override: the default delegates to AccountAdapter, which is
        # False under invite policy. pre_social_login already gated, so allow.
        return True

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        if user.email:
            ensure_verified_primary_email(user, user.email)
        self._consume_invitation(sociallogin, user)
        return user

    # --- helpers ---

    def _evaluate(self, email, invitation):
        inst = Institution.load()
        return evaluate_sso_provisioning(
            email,
            signup_policy=inst.signup_policy,
            allowed_email_domains=inst.allowed_email_domains,
            invitation=invitation,
        )

    def _consume_invitation(self, sociallogin, user):
        invitation = getattr(sociallogin, "_libli_invitation", None)
        if invitation is None and user.email:
            invitation = Invitation.find_pending(user.email)
        if invitation is None:
            return
        with transaction.atomic():
            locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
            if locked.is_valid():
                locked.accepted_at = timezone.now()
                locked.save(update_fields=["accepted_at"])

    def _not_provisioned(self):
        return redirect(reverse("accounts:sso_not_provisioned"))
