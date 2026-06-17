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


def reconcile_primary_email(user):
    """Keep allauth's EmailAddress rows consistent with `user.email` after a change.

    Call AFTER user.save(). Two mutually-exclusive arms on emptiness so the demote
    query never sees a None email:
      - non-empty: demote every OTHER address, then ensure_verified_primary_email
        makes `user.email` the sole verified primary (it does not demote on its own).
      - cleared (NULL): delete all the user's rows (no canonical address — correct
        for an emailless class account).
    """
    if user.email:
        EmailAddress.objects.filter(user=user).exclude(
            email__iexact=user.email
        ).update(primary=False)
        ensure_verified_primary_email(user, user.email)
    else:
        EmailAddress.objects.filter(user=user).delete()
