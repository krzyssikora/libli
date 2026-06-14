from allauth.account.utils import perform_login
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.db import transaction
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.emails import ensure_verified_primary_email
from accounts.forms import AcceptInviteForm
from accounts.models import Invitation
from accounts.models import User
from accounts.provisioning import resolve_user_for_email
from institution.roles import STUDENT


def _email_is_registered(email):
    # Delegates to the shared resolver so the invite-accept flow and the SSO
    # adapter agree on "who owns this email". Call sites use only truthiness.
    return resolve_user_for_email(email) is not None


class _InvitationNoLongerValid(Exception):
    """Raised inside the atomic block when a re-check fails between GET and POST."""


@require_http_methods(["GET", "POST"])
def accept_invite(request, token):
    # An already-authenticated user has no business accepting an invite; send them
    # to their landing page and consume nothing. (Out of the normal invite flow.)
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    invitation = Invitation.objects.filter(token=token).first()
    if invitation is None or not invitation.is_valid():
        return render(request, "accounts/invite_invalid.html", {"reason": "invalid"})
    if _email_is_registered(invitation.email):
        return render(request, "accounts/invite_invalid.html", {"reason": "registered"})

    if request.method == "POST":
        form = AcceptInviteForm(request.POST, invited_email=invitation.email)
        if form.is_valid():
            try:
                user = _consume_and_create(invitation, form)
            except _InvitationNoLongerValid:
                return render(
                    request, "accounts/invite_invalid.html", {"reason": "invalid"}
                )
            except IntegrityError:
                # A concurrent accept may have registered the email or taken the
                # username between our re-check and INSERT. Distinguish the two:
                # an email clash routes to the "already registered" page; otherwise
                # the username is the culprit.
                if _email_is_registered(invitation.email):
                    return render(
                        request,
                        "accounts/invite_invalid.html",
                        {"reason": "registered"},
                    )
                form.add_error("username", "That username is already taken.")
            else:
                # email is sourced server-side from invitation.email, never the POST.
                return perform_login(request, user, email=invitation.email)
    else:
        form = AcceptInviteForm(invited_email=invitation.email)

    return render(
        request,
        "accounts/accept_invite.html",
        {"form": form, "email": invitation.email},
    )


def _consume_and_create(invitation, form):
    """Create the account and consume the token atomically. The invited email is
    authoritative (taken from the locked invitation, never the form)."""
    with transaction.atomic():
        locked = Invitation.objects.select_for_update().get(pk=invitation.pk)
        if not locked.is_valid() or _email_is_registered(locked.email):
            raise _InvitationNoLongerValid
        user = User.objects.create_user(
            username=form.cleaned_data["username"],
            email=locked.email,
            password=form.cleaned_data["password"],
        )
        ensure_verified_primary_email(user, locked.email)
        group, _ = Group.objects.get_or_create(name=STUDENT)
        user.groups.add(group)
        locked.accepted_at = timezone.now()
        locked.save(update_fields=["accepted_at"])
    return user
