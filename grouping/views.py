from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from accounts.models import User
from core.collation import polish_sort_key
from grouping import scoping
from grouping import services
from grouping.forms import CohortForm
from grouping.forms import CollectionForm
from grouping.forms import GroupForm
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
            "all_students": services.student_users()
            .exclude(cohort_membership__cohort=cohort)
            .order_by("username"),
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


def _student_ids_from_post(request):
    """Parse the roster <select name='students'> POST list. Silently drops
    non-integer values so a malformed/forged field can't 500 the view; foreign
    pks are harmless — set_group_members filters to real User rows."""
    ids = []
    for raw in request.POST.getlist("students"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return ids


def _student_choices(request):
    """All roster-eligible students, ordered by username. The picker filters by
    cohort and name client-side (see grouping/js/roster_filter.js) so every student
    stays in the DOM — a checked student outside the active filter is never dropped
    on save. select_related pulls each student's cohort for the per-label
    data-cohort attribute without an N+1."""
    return (
        services.student_users()
        .select_related("cohort_membership__cohort")
        .order_by("username")
    )


def _cohort_choices():
    return Cohort.objects.filter(archived=False).order_by("-is_default", "name")


@login_required
@permission_required("grouping.view_group", raise_exception=True)
def group_list(request):
    show_archived = request.GET.get("archived") == "1"
    groups = scoping.groups_manageable_by(request.user).filter(archived=show_archived)
    return render(
        request,
        "grouping/group_list.html",
        {
            "groups": groups.order_by("course__title", "name"),
            "show_archived": show_archived,
            "hub_tab": "manage",
        },
    )


@login_required
@permission_required("grouping.add_group", raise_exception=True)
def group_create(request):
    if request.method == "POST":
        form = GroupForm(request.POST)
        if form.is_valid():
            course = form.cleaned_data["course"]
            # A CA may only create groups on courses they own; PA may use any.
            if not (
                request.user.has_perm("courses.change_course")
                or course.owner_id == request.user.id
            ):
                raise PermissionDenied
            group = form.save()
            services.set_group_members(
                group, _student_ids_from_post(request), added_by=request.user
            )
            return redirect("grouping:group_edit", pk=group.pk)
    else:
        form = GroupForm()
    return render(
        request,
        "grouping/group_form.html",
        {
            "form": form,
            "creating": True,
            "all_students": _student_choices(request),
            "cohorts": _cohort_choices(),
            "current_ids": set(),
            "current_teacher_ids": set(),
        },
    )


@login_required
@permission_required("grouping.change_group", raise_exception=True)
def group_edit(request, pk):
    group = get_object_or_404(scoping.groups_manageable_by(request.user), pk=pk)
    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            group = form.save()
            services.set_group_members(
                group, _student_ids_from_post(request), added_by=request.user
            )
            return redirect("grouping:group_edit", pk=group.pk)
    else:
        form = GroupForm(instance=group)
    current_ids = set(group.memberships.values_list("student_id", flat=True))
    return render(
        request,
        "grouping/group_form.html",
        {
            "form": form,
            "creating": False,
            "group": group,
            "current_ids": current_ids,
            "current_teacher_ids": set(group.teachers.values_list("id", flat=True)),
            "all_students": _student_choices(request),
            "cohorts": _cohort_choices(),
        },
    )


@login_required
@permission_required("grouping.change_group", raise_exception=True)
@require_POST
def group_archive(request, pk):
    group = get_object_or_404(scoping.groups_manageable_by(request.user), pk=pk)
    services.set_group_archived(group, not group.archived)
    return redirect("grouping:group_list")


@login_required
@permission_required("grouping.delete_group", raise_exception=True)
def group_delete(request, pk):
    group = get_object_or_404(scoping.groups_manageable_by(request.user), pk=pk)
    if request.method == "POST":
        services.delete_group(group)
        return redirect("grouping:group_list")
    return render(
        request,
        "grouping/group_confirm_delete.html",
        {"group": group, "member_count": group.memberships.count()},
    )


@login_required
@permission_required("grouping.view_group", raise_exception=True)
def group_detail(request, pk):
    group = get_object_or_404(scoping.groups_visible_to(request.user), pk=pk)
    # Roster sorted by family name (falls back to display_name/username) — see
    # User.sort_name; a class-sized list, so sort in Python like the review roster.
    students = sorted(
        group.memberships.select_related("student"),
        key=lambda m: (polish_sort_key(m.student.sort_name), m.student.username),
    )
    owner = group.course.owner  # surfaced separately, labeled "(owner)", non-removable
    # Exclude the owner from the teachers list: a course owner who also teaches
    # the group must not appear twice.
    teachers = sorted(
        (t for t in group.teachers.all() if t != owner),
        key=lambda t: (polish_sort_key(t.sort_name), t.username),
    )
    can_review = scoping.can_review_course(request.user, group.course)
    return render(
        request,
        "grouping/group_detail.html",
        {
            "group": group,
            "students": students,
            "teachers": teachers,
            "owner": owner,
            "student_count": len(students),
            "can_review": can_review,
        },
    )


@login_required  # intentionally login-only (no perm gate): scoping yields an empty
# list for a user who manages/teaches nothing, so a plain student simply sees an
# empty "My groups & collections" page. The nav link is perm-gated so they never
# see the entry point. This is a deliberate exception to the gate-then-scope rule.
def my_groups(request):
    groups = (
        scoping.groups_visible_to(request.user)
        .filter(archived=False)
        .select_related("course")
        .order_by("course__title", "name")
    )
    collections = list(
        scoping.collections_manageable_by(request.user)
        .filter(archived=False)
        .select_related("course")
        .order_by("name")
    )
    for c in collections:
        # can_review_course is course-wide and does NOT consult collection
        # ownership, so an owned collection on a course the user cannot review
        # must not offer a (dead) analytics link.
        c.can_review = scoping.can_review_course(request.user, c.course)
    return render(
        request,
        "grouping/my_groups.html",
        {"groups": groups, "collections": collections, "hub_tab": "my_groups"},
    )


@login_required
@permission_required("grouping.add_collection", raise_exception=True)
def collection_create(request):
    if request.method == "POST":
        form = CollectionForm(request.POST, owner=request.user)
        if form.is_valid():
            # Bootstrap gate: the creator must be allowed to add each selected group.
            for group in form.cleaned_data["groups"]:
                if not scoping.can_add_collection_group(request.user, group):
                    raise PermissionDenied
            collection = form.save()
            return redirect("grouping:collection_detail", pk=collection.pk)
    else:
        form = CollectionForm(owner=request.user)
    return render(
        request, "grouping/collection_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("grouping.change_collection", raise_exception=True)
def collection_edit(request, pk):
    collection = get_object_or_404(
        scoping.collections_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        form = CollectionForm(request.POST, instance=collection, owner=request.user)
        if form.is_valid():
            for group in form.cleaned_data["groups"]:
                if not scoping.can_add_collection_group(request.user, group):
                    raise PermissionDenied
            collection = form.save()
            return redirect("grouping:collection_detail", pk=collection.pk)
    else:
        form = CollectionForm(instance=collection, owner=request.user)
    return render(
        request,
        "grouping/collection_form.html",
        {"form": form, "creating": False, "collection": collection},
    )


@login_required
@permission_required("grouping.view_collection", raise_exception=True)
def collection_detail(request, pk):
    collection = get_object_or_404(
        scoping.collections_manageable_by(request.user), pk=pk
    )
    # Union roster across NON-archived member groups only, sorted by family name
    # (falls back to display_name/username — see User.sort_name).
    students = sorted(
        User.objects.filter(
            group_memberships__group__in=collection.groups.filter(archived=False)
        ).distinct(),
        key=lambda u: (polish_sort_key(u.sort_name), u.username),
    )
    can_review = scoping.can_review_course(request.user, collection.course)
    return render(
        request,
        "grouping/collection_detail.html",
        {
            "collection": collection,
            "students": students,
            "student_count": len(students),
            "can_review": can_review,
        },
    )


@login_required
@permission_required("grouping.delete_collection", raise_exception=True)
@require_POST
def collection_delete(request, pk):
    collection = get_object_or_404(
        scoping.collections_manageable_by(request.user), pk=pk
    )
    collection.delete()
    return redirect("grouping:my_groups")
