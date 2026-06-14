"""SSO/JIT provisioning logic. The gating policy is a pure, side-effect-free
function so every branch is unit-testable without allauth or the database; the
small DB-touching resolvers below are also pure of allauth-flow coupling."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Decision:
    """Outcome of the gating policy. `invitation_to_consume` is set only when the
    allow was *because of* a pending invite (so the adapter knows to consume it)."""

    allow: bool
    reason: str = ""
    invitation_to_consume: object | None = None


def email_domain(email):
    """The lowercased host part of an email, or "" when there is no '@'."""
    local, at, host = email.rpartition("@")
    return host.lower() if at else ""


def evaluate_sso_provisioning(
    email, *, signup_policy, allowed_email_domains, invitation
):
    """Decide whether a brand-new SSO identity may be provisioned.

    Order: a valid pending invitation overrides everything; otherwise an
    un-invited signup needs signup_policy == "open" and (when a domain allowlist
    is set) an allowed email domain. The caller passes an already-valid
    `invitation` (or None); this function does no clock/DB work itself."""
    if invitation is not None:
        return Decision(allow=True, invitation_to_consume=invitation)
    if signup_policy != "open":
        return Decision(allow=False, reason="policy")
    if allowed_email_domains:
        allowed = {entry.strip().lower().lstrip("@") for entry in allowed_email_domains}
        domain = email_domain(email)
        if not domain or domain not in allowed:
            return Decision(allow=False, reason="domain")
    return Decision(allow=True)


def resolve_user_for_email(email):
    """Return the local user that owns `email`, or None. Prefers the owner of a
    verified allauth EmailAddress, then any EmailAddress owner, then a User.email
    match (the last catches admin-created accounts with no EmailAddress row).
    Read-only; shared by the invite-accept flow and the SSO adapter so they agree."""
    from allauth.account.models import EmailAddress

    from accounts.models import User

    address = (
        EmailAddress.objects.filter(email__iexact=email)
        # -verified: a verified row wins (tier 1) over an unverified one (tier 2);
        # pk is a deterministic secondary key so collisions are not arbitrary.
        .order_by("-verified", "pk")
        .select_related("user")
        .first()
    )
    if address is not None:
        return address.user
    return User.objects.filter(email__iexact=email).first()


def verified_email_belongs_to_other(email, user):
    """True iff a *verified* EmailAddress for `email` is bound to a different user.
    Used as the pre-link clash guard so ensure_verified_primary_email cannot raise."""
    from allauth.account.models import EmailAddress

    return (
        EmailAddress.objects.filter(email__iexact=email, verified=True)
        .exclude(user=user)
        .exists()
    )
