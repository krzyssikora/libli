import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.utils.translation import ngettext
from django.views.decorators.http import require_POST

from accounts.models import User
from core.collation import polish_sort_key
from grouping import scoping
from grouping import services
from grouping.forms import AllocationForm
from grouping.forms import CohortForm
from grouping.forms import CollectionForm
from grouping.forms import GroupForm
from grouping.models import Cohort
from grouping.models import CohortMembership
from grouping.models import GroupMembership


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
    groups = (
        scoping.groups_manageable_by(request.user)
        .filter(archived=show_archived)
        .select_related("course", "allocation")
    )
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
        form = GroupForm(request.POST, user=request.user)
        if form.is_valid():
            course = form.cleaned_data["course"]
            # A CA may only create groups on courses they own; PA may use any.
            if not (
                request.user.has_perm("courses.change_course")
                or course.owner_id == request.user.id
            ):
                raise PermissionDenied
            with transaction.atomic():
                group = form.save()
            services.set_group_members(
                group, _student_ids_from_post(request), added_by=request.user
            )
            return redirect("grouping:group_edit", pk=group.pk)
    else:
        form = GroupForm(user=request.user)
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
        form = GroupForm(request.POST, instance=group, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                group = form.save()
            services.set_group_members(
                group, _student_ids_from_post(request), added_by=request.user
            )
            return redirect("grouping:group_edit", pk=group.pk)
    else:
        form = GroupForm(instance=group, user=request.user)
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
@permission_required("grouping.view_allocation", raise_exception=True)
def allocation_list(request):
    show_archived = request.GET.get("archived") == "1"
    allocations = (
        scoping.allocations_manageable_by(request.user)
        .filter(archived=show_archived)
        .select_related("course")
        .prefetch_related("cohorts")
        .annotate(group_count=Count("groups", filter=Q(groups__archived=False)))
        .order_by("course__title", "name")
    )
    return render(
        request,
        "grouping/allocation_list.html",
        {
            "allocations": allocations,
            "show_archived": show_archived,
            "hub_tab": "allocations",
        },
    )


@login_required
@permission_required("grouping.add_allocation", raise_exception=True)
def allocation_create(request):
    # NOTE: no PermissionDenied check here — AllocationForm restricts `course` to
    # manageable_courses(user), so an unowned pk fails invalid_choice and any
    # check placed after is_valid() would be unreachable dead code.
    if request.method == "POST":
        form = AllocationForm(request.POST, user=request.user)
        if form.is_valid():
            allocation = form.save()
            return redirect("grouping:allocation_edit", pk=allocation.pk)
    else:
        form = AllocationForm(user=request.user)
    return render(
        request, "grouping/allocation_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("grouping.change_allocation", raise_exception=True)
def allocation_edit(request, pk):
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        form = AllocationForm(request.POST, instance=allocation, user=request.user)
        if form.is_valid():
            form.save()
            return redirect("grouping:allocation_list")
    else:
        form = AllocationForm(instance=allocation, user=request.user)
    return render(
        request,
        "grouping/allocation_form.html",
        {"form": form, "creating": False, "allocation": allocation},
    )


@login_required
@permission_required("grouping.change_allocation", raise_exception=True)
@require_POST
def allocation_archive(request, pk):
    """Toggles, exactly as group_archive does. Archiving leaves groups and
    memberships untouched — deliberately unlike archive_cohort."""
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    allocation.archived = not allocation.archived
    allocation.save(update_fields=["archived"])
    return redirect("grouping:allocation_list")


@login_required
@permission_required("grouping.delete_allocation", raise_exception=True)
def allocation_delete(request, pk):
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        allocation.delete()  # SET_NULL on Group.allocation; memberships untouched
        return redirect("grouping:allocation_list")
    return render(
        request,
        "grouping/allocation_confirm_delete.html",
        {"allocation": allocation, "group_count": allocation.groups.count()},
    )


# Both token strings (the `columns` field and each row's `-was`) obey one
# grammar: empty, or digits strictly ascending, comma-joined. An absent or
# non-conforming `columns` value must abort the save unconditionally — it is
# never coerced to "", which would compare equal to a groups-less allocation's
# token.
COLUMNS_TOKEN_RE = re.compile(r"^$|^\d+(,\d+)*$")


def _allocation_grid_context(allocation):
    """Built in one place so the GET render and the POST's stale-column
    re-render can never silently disagree on shape."""
    columns = list(services.allocation_columns(allocation))
    students = list(services.allocation_row_students(allocation).order_by("username"))
    student_ids = [s.pk for s in students]
    # ONE bucketed membership query for row states AND the "also in" notes.
    memberships = {}
    also_in = {}
    column_ids = {c.pk for c in columns}
    membership_rows = GroupMembership.objects.filter(
        student_id__in=student_ids, group__course=allocation.course
    ).select_related("group")
    for m in membership_rows:
        memberships.setdefault(m.student_id, set()).add(m.group_id)
        if m.group_id not in column_ids:
            also_in.setdefault(m.student_id, []).append(m.group.name)
    tokens = services.allocation_state_tokens(columns, student_ids, memberships)
    # The cohort bucket comes from an explicit id map: user.cohort_membership
    # raises RelatedObjectDoesNotExist in Python when absent (templates silence
    # it, which is why group_form.html's dereference looks safe).
    cohort_of = dict(
        CohortMembership.objects.filter(user_id__in=student_ids).values_list(
            "user_id", "cohort_id"
        )
    )
    # id -> Cohort for the ATTACHED cohorts only, already in display order. A
    # student whose cohort id is absent from cohort_of (no membership at all)
    # OR present but not attached to this allocation both go to "outside these
    # cohorts" with data_cohort="".
    attached = {
        c.pk: c for c in allocation.cohorts.all().order_by("-is_default", "name")
    }
    buckets = {cohort_pk: [] for cohort_pk in attached}
    outside = []
    for student in students:
        cohort_id = cohort_of.get(student.pk)
        if cohort_id in attached:
            buckets[cohort_id].append(student)
        else:
            outside.append(student)

    def sort_key(student):
        return (polish_sort_key(student.sort_name), student.username)

    def build_row(student, cohort_slug):
        ids = memberships.get(student.pk, set()) & column_ids
        if len(ids) == 1:
            state, selected_id = "assigned", next(iter(ids))
        elif not ids:
            state, selected_id = "unassigned", None
        else:
            state, selected_id = "conflict", None
        return {
            "student": student,
            "state": state,
            "selected_id": selected_id,
            "check_none": state == "unassigned",
            "token": tokens[student.pk],
            "also_in": also_in.get(student.pk, []),
            "data_name": student.sort_name.lower(),
            "data_cohort": cohort_slug,
        }

    sections = [
        {
            "label": cohort.display_name,
            "cohort_slug": cohort.slug,
            "rows": [
                build_row(s, cohort.slug)
                for s in sorted(buckets[cohort.pk], key=sort_key)
            ],
        }
        for cohort in attached.values()
    ]
    sections.append(
        {
            "label": None,  # template renders "Outside these cohorts"
            "cohort_slug": "",
            "rows": [build_row(s, "") for s in sorted(outside, key=sort_key)],
        }
    )

    # Whole-allocation counts, computed over every row above — never a
    # filtered subset, since "who is still unplaced" is the number the admin
    # came for.
    summary = {"total": len(students), "assigned": 0, "unassigned": 0, "conflict": 0}
    for section in sections:
        for row in section["rows"]:
            summary[row["state"]] += 1

    return {
        "allocation": allocation,
        "columns": columns,
        "columns_token": services.allocation_columns_token(columns),
        "sections": sections,
        "summary": summary,
        "hub_tab": "allocations",
    }


def _abort_stale(request, allocation):
    """Re-renders from FRESH server state, discarding the posted choices —
    every -was in them is stale against a column set that no longer exists."""
    messages.error(
        request,
        _(
            "The allocation's groups changed while you were editing, so "
            "nothing was saved — please redo your changes."
        ),
    )
    return render(
        request, "grouping/allocation_assign.html", _allocation_grid_context(allocation)
    )


def _allocation_assign_post(request, allocation):
    with transaction.atomic():
        # 1. Column-set check first, inside the transaction: this is exactly
        # the window the check exists to close.
        columns = list(services.allocation_columns(allocation))
        raw_columns = request.POST.get("columns")  # None when absent
        if raw_columns is None or not COLUMNS_TOKEN_RE.match(raw_columns):
            return _abort_stale(request, allocation)
        if raw_columns != services.allocation_columns_token(columns):
            return _abort_stale(request, allocation)

        # 2. The server's own row set — the request body is never trusted to
        # define which students are editable.
        row_students = list(services.allocation_row_students(allocation))

        # 3. Build assignments. `request.POST.get` returns None for an absent
        # field and "" for the none-radio — those must not collapse.
        assignments = {}
        for student in row_students:
            key = f"student-{student.pk}"
            if key not in request.POST:
                continue  # absent -> omit entirely
            raw = request.POST.get(key)
            was = request.POST.get(f"{key}-was")  # missing -> None -> mismatch
            if raw == "":
                target_id = None  # the "— none —" radio
            else:
                try:
                    target_id = int(raw)  # column_by_id is keyed on int pks
                except (TypeError, ValueError):
                    continue  # non-integer -> omit, not unassign
            assignments[student.pk] = (target_id, was)

        # 4. The service owns the optimistic guard end to end.
        skipped = services.set_allocation_assignments(
            columns, assignments, added_by=request.user
        )

        # 5. Report any guard mismatches, named in polish_sort_key order.
        if skipped:
            names = sorted(
                User.objects.filter(pk__in=skipped),
                key=lambda u: (polish_sort_key(u.sort_name), u.username),
            )
            messages.warning(
                request,
                ngettext(
                    "%(count)d row was changed by someone else and was not "
                    "overwritten: %(names)s.",
                    "%(count)d rows were changed by someone else and were "
                    "not overwritten: %(names)s.",
                    len(names),
                )
                % {
                    "count": len(names),
                    "names": ", ".join(u.list_display_name for u in names),
                },
            )
    return redirect("grouping:allocation_assign", pk=allocation.pk)


@login_required
@permission_required("grouping.change_group", raise_exception=True)
def allocation_assign(request, pk):
    """The assignment grid. Gated on change_group — it writes GroupMembership,
    not Allocation — and scoped through allocations_manageable_by, so a
    change_group-only holder (no change_allocation) 404s from the scoped
    lookup rather than 403ing from the decorator."""
    allocation = get_object_or_404(
        scoping.allocations_manageable_by(request.user), pk=pk
    )
    if request.method == "POST":
        return _allocation_assign_post(request, allocation)
    return render(
        request, "grouping/allocation_assign.html", _allocation_grid_context(allocation)
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
