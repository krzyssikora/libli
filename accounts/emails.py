"""Account email helpers shared by production code (init_platform, the invite
accept view) and the test factory. Kept out of test modules so production code
never imports test helpers."""

from allauth.account.models import EmailAddress


def ensure_verified_primary_email(user, email):
    """Ensure `user` owns a verified, primary allauth EmailAddress for `email`.

    Get-or-creates keyed on (user, email); forces verified=True + primary=True.
    Raises ValueError only if a *verified* row for the same address is already
    bound to a different user (so a caller can never silently re-point another
    account's confirmed email; an unverified row on another user does not block).
    Precondition: callers pass a user without a conflicting existing primary
    address (true for the 0c-1 callers — a fresh invited user and the bootstrap
    admin); this helper does not demote another primary."""
    # Normalize to lowercase so the get-or-create lookup key matches the casing
    # allauth itself stores (its EmailAddressManager lowercases before persisting),
    # avoiding a duplicate row when a caller passes a mixed-case address.
    email = email.lower()
    clash = (
        EmailAddress.objects.filter(email__iexact=email, verified=True)
        .exclude(user=user)
        .first()
    )
    if clash is not None:
        raise ValueError(
            f"Email {email!r} is already bound to a different user"
            f" (id={clash.user_id})."
        )
    address, _ = EmailAddress.objects.get_or_create(
        user=user, email=email, defaults={"verified": True, "primary": True}
    )
    if not (address.verified and address.primary):
        address.verified = True
        address.primary = True
        address.save()
    return address
