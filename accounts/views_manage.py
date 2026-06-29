"""Platform-admin People surface: Users + Invitations tabs."""

from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render

from accounts.models import User
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


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def people_invitations(request):  # fleshed out in Task 8
    return render(
        request, "accounts/manage/people.html", {"tab": "invitations", "rows": []}
    )


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_edit(request, pk):  # fleshed out in Task 9
    return HttpResponse("")


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_deactivate(request, pk):  # fleshed out in Task 10
    return HttpResponse("")


@login_required
@permission_required("accounts.change_user", raise_exception=True)
def user_reactivate(request, pk):  # fleshed out in Task 10
    return HttpResponse("")
