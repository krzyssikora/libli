from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.models import User
from grouping import services
from grouping.forms import CohortForm
from grouping.models import Cohort


# Cohort management is PA-only. The list is gated on `change_cohort` (a PA-only
# perm), NOT `view_cohort` — per spec §4, the CA `view_cohort` grant exists ONLY
# to read cohort names in the group student-picker, not to reach this screen.
@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
def cohort_list(request):
    cohorts = Cohort.objects.order_by("-is_default", "name")
    return render(request, "grouping/cohort_list.html", {"cohorts": cohorts})


@login_required
@permission_required("grouping.add_cohort", raise_exception=True)
def cohort_create(request):
    if request.method == "POST":
        form = CohortForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("grouping:cohort_list")
    else:
        form = CohortForm()
    return render(
        request, "grouping/cohort_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
def cohort_edit(request, slug):
    cohort = get_object_or_404(Cohort, slug=slug)
    if request.method == "POST":
        form = CohortForm(request.POST, instance=cohort)
        if form.is_valid():
            # NOTE: slugs are frozen after creation for ALL cohorts (Cohort.save
            # only generates a slug when blank) — a rename does NOT re-slug, so
            # cohort URLs are stable. This is intentional, not an oversight.
            form.save()
            return redirect("grouping:cohort_list")
    else:
        form = CohortForm(instance=cohort)
    members = User.objects.filter(cohort_membership__cohort=cohort).order_by("username")
    return render(
        request,
        "grouping/cohort_form.html",
        {
            "form": form,
            "creating": False,
            "cohort": cohort,
            "members": members,
            "all_students": User.objects.order_by("username"),
        },
    )


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
@require_POST
def cohort_promote(request, slug):
    cohort = get_object_or_404(Cohort, slug=slug)
    services.promote_default(cohort)
    return redirect("grouping:cohort_list")


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
@require_POST
def cohort_archive(request, slug):
    """Toggle a cohort's archived state through the SERVICE (not the form), so
    archiving reassigns members to Default and refuses to archive the Default
    cohort (spec §3 lifecycle). The archive button is rendered for non-default
    cohorts only; the ValidationError catch is a defense-in-depth backstop."""
    cohort = get_object_or_404(Cohort, slug=slug)
    if cohort.archived:
        cohort.archived = False  # un-archive: just make it active again (it is empty)
        cohort.save(update_fields=["archived"])
    else:
        try:
            services.archive_cohort(
                cohort
            )  # reassigns members to Default + guards default
        except ValidationError:
            pass  # cannot archive the Default cohort; no-op
    return redirect("grouping:cohort_list")


@login_required
@permission_required("grouping.change_cohort", raise_exception=True)
@require_POST
def cohort_assign_students(request, slug):
    """View 6.4 'assign & reassign students': move each selected student INTO
    this cohort (exactly-one cohort => assignment is a reassignment from wherever
    they are). Non-integer / unknown ids are skipped."""
    cohort = get_object_or_404(Cohort, slug=slug)
    for raw in request.POST.getlist("students"):
        try:
            student = User.objects.get(pk=int(raw))
        except (TypeError, ValueError, User.DoesNotExist):
            continue
        services.assign_student_to_cohort(student, cohort, assigned_by=request.user)
    return redirect("grouping:cohort_edit", slug=cohort.slug)


@login_required
@permission_required("grouping.delete_cohort", raise_exception=True)
def cohort_delete(request, slug):
    cohort = get_object_or_404(Cohort, slug=slug)
    error = None
    if request.method == "POST":
        try:
            services.delete_cohort(cohort)
            return redirect("grouping:cohort_list")
        except ValidationError as exc:
            error = exc.messages[0]
    member_count = cohort.memberships.count()
    return render(
        request,
        "grouping/cohort_confirm_delete.html",
        {"cohort": cohort, "member_count": member_count, "error": error},
    )
