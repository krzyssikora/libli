"""Platform-admin People surface: Users + Invitations tabs."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from accounts.forms import SendInvitationForm
from accounts.forms import UserEditForm
from accounts.models import Invitation
from accounts.models import User
from accounts.services import InvitationError
from accounts.services import create_or_refresh_invitation
from accounts.services import is_last_active_platform_admin
from accounts.services import resend_invitation
from accounts.services import revoke_invitation
from institution.roles import ROLE_LABELS
from institution.roles import ROLE_NAMES

PAGE_SIZE = 25
NO_ROLE = "__none__"


def _role_labels_for(user):
    """The translatable labels for the role Groups a user holds (0, 1, or more)."""
    return [ROLE_LABELS[g.name] for g in user.groups.all() if g.name in ROLE_NAMES]


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def people(request):
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    active = request.GET.get("active", "all")

    users = User.objects.prefetch_related("groups").order_by(
        "display_name", "email", "username"
    )
    if q:
        users = users.filter(
            Q(display_name__icontains=q)
            | Q(email__icontains=q)
            | Q(username__icontains=q)
        )
    if active == "active":
        users = users.filter(is_active=True)
    elif active == "inactive":
        users = users.filter(is_active=False)
    if role == NO_ROLE:
        users = users.exclude(groups__name__in=ROLE_NAMES)
    elif role in ROLE_NAMES:
        users = users.filter(groups__name=role)
    users = users.distinct()

    page_obj = Paginator(users, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [{"user": u, "role_labels": _role_labels_for(u)} for u in page_obj]

    return render(
        request,
        "accounts/manage/people.html",
        {
            "tab": "users",
            "page_obj": page_obj,
            "rows": rows,
            "q": q,
            "role": role,
            "active": active,
            "role_choices": [(name, ROLE_LABELS[name]) for name in ROLE_NAMES],
            "no_role_value": NO_ROLE,
        },
    )


# Localized labels for Invitation.status (the model property returns raw strings).
# gettext_lazy so this module-level dict is not frozen to the import-time language.
STATUS_LABELS = {
    "pending": gettext_lazy("Pending"),
    "accepted": gettext_lazy("Accepted"),
    "expired": gettext_lazy("Expired"),
}


def _render_invitations(request, form):
    qs = Invitation.objects.order_by("-created_at")
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [{"inv": inv, "status_label": STATUS_LABELS[inv.status]} for inv in page_obj]
    return render(
        request,
        "accounts/manage/invitations.html",
        {"tab": "invitations", "rows": rows, "page_obj": page_obj, "form": form},
    )


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def people_invitations(request):
    return _render_invitations(request, SendInvitationForm())


@require_POST
@login_required
@permission_required("accounts.add_user", raise_exception=True)
def invitation_send(request):
    form = SendInvitationForm(request.POST)
    if form.is_valid():
        try:
            create_or_refresh_invitation(
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                invited_by=request.user,
            )
            messages.success(request, _("Invitation sent."))
            from accounts.provisioning import email_domain
            from accounts.provisioning import normalized_allowlist
            from institution.models import Institution

            allowed = normalized_allowlist(Institution.load().allowed_email_domains)
            domain = email_domain(form.cleaned_data["email"])
            if allowed and domain not in allowed:
                messages.warning(
                    request,
                    _("Note: %(domain)s is not in your allowed email domains.")
                    % {"domain": domain},
                )
            return redirect("accounts:people_invitations")
        except InvitationError as exc:
            form.add_error("email", str(exc))
    return _render_invitations(request, form)


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def invitation_revoke(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status == "pending":
        revoke_invitation(invitation)
        messages.success(request, _("Invitation revoked."))
    return redirect("accounts:people_invitations")


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def invitation_resend(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status == "pending":
        resend_invitation(invitation)
        messages.success(request, _("Invitation re-sent."))
    return redirect("accounts:people_invitations")


def _current_role(user):
    """The single role name if the user holds exactly one, else "" (role-less/multi)."""
    names = [g.name for g in user.groups.all() if g.name in ROLE_NAMES]
    return names[0] if len(names) == 1 else ""


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    editing_self = target.pk == request.user.pk
    if request.method == "POST":
        form = UserEditForm(request.POST, instance=target, editing_self=editing_self)
        if form.is_valid():
            try:
                form.save()
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, _("User updated."))
                return redirect("accounts:people")
    else:
        initial = {
            "display_name": target.display_name,
            "email": target.email or "",
            "role": _current_role(target),
        }
        form = UserEditForm(initial=initial, instance=target, editing_self=editing_self)
    return render(
        request,
        "accounts/manage/user_form.html",
        {"form": form, "target": target, "editing_self": editing_self},
    )


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_deactivate(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.pk == request.user.pk:
        messages.error(request, _("You cannot deactivate your own account."))
        return redirect("accounts:user_edit", pk=pk)
    with transaction.atomic():
        if is_last_active_platform_admin(target, lock=True):
            messages.error(
                request, _("Cannot deactivate the last active Platform Admin.")
            )
            return redirect("accounts:user_edit", pk=pk)
        target.is_active = False
        target.save(update_fields=["is_active"])
    messages.success(request, _("User deactivated."))
    return redirect("accounts:people")


@require_POST
@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_reactivate(request, pk):
    target = get_object_or_404(User, pk=pk)
    target.is_active = True
    target.save(update_fields=["is_active"])
    messages.success(request, _("User reactivated."))
    return redirect("accounts:people")
