from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _

from courses import builder as builder_svc
from courses.access import can_manage_course
from courses.access import get_node_or_404  # reuse 1a's IDOR-safe resolver
from courses.forms import CourseForm
from courses.models import ContentNode
from courses.models import Course
from courses.models import Enrollment
from courses.models import UnitProgress


@login_required
def course_list(request):
    """My courses (admin) — view 5.1. Owner sees their own; a holder of
    courses.change_course (Platform Admin) sees all. Ordered by title."""
    if request.user.has_perm("courses.change_course"):
        courses = Course.objects.all().order_by("title")
    else:
        courses = Course.objects.filter(owner=request.user).order_by("title")
    return render(request, "courses/manage/course_list.html", {"courses": courses})


@login_required
@permission_required("courses.add_course", raise_exception=True)
def course_create(request):
    if request.method == "POST":
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save(commit=False)
            if course.owner_id is None:
                course.owner = request.user  # default owner = creating PA
            course.save()
            return redirect("courses:manage_builder", slug=course.slug)
    else:
        form = CourseForm(initial={"owner": request.user.pk})
    return render(
        request, "courses/manage/course_form.html", {"form": form, "creating": True}
    )


@login_required
def course_edit(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    can_assign_owner = request.user.has_perm("courses.change_course")  # PA only
    if request.method == "POST":
        form = CourseForm(
            request.POST, instance=course, can_assign_owner=can_assign_owner
        )
        if form.is_valid():
            course = form.save()
            return redirect("courses:manage_course_edit", slug=course.slug)  # new slug
    else:
        form = CourseForm(instance=course, can_assign_owner=can_assign_owner)
    return render(
        request,
        "courses/manage/course_form.html",
        {"form": form, "creating": False, "course": course},
    )


@login_required
@permission_required("courses.delete_course", raise_exception=True)
def course_delete(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if request.method == "POST":
        course.delete()  # cascades nodes -> elements (GenericRelation) + learner state
        return redirect("courses:manage_course_list")
    counts = {
        "nodes": course.nodes.count(),
        "enrollments": Enrollment.objects.filter(course=course).count(),
        "progress": UnitProgress.objects.filter(unit__course=course).count(),
    }
    counts["has_learner_state"] = counts["enrollments"] > 0 or counts["progress"] > 0
    return render(
        request,
        "courses/manage/course_confirm_delete.html",
        {"course": course, "counts": counts},
    )


def _children_map(course):
    """parent_id -> [child nodes] (single query), for recursive tree rendering."""
    cmap = {}
    for node in course.nodes.all().order_by("order", "pk"):
        cmap.setdefault(node.parent_id, []).append(node)
    return cmap


@login_required
def builder(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    cmap = _children_map(course)
    return render(
        request,
        "courses/manage/builder.html",
        {
            "course": course,
            "children_map": cmap,
            "top_nodes": cmap.get(None, []),
            "kind_choices": ContentNode.Kind.choices,
        },
    )


@login_required
def node_panel(request, slug, pk):
    node = get_node_or_404(pk, slug)  # 404 on missing / slug-mismatch, BEFORE access
    if not can_manage_course(request.user, node.course):
        raise PermissionDenied
    if node.kind == ContentNode.Kind.UNIT:
        elements = list(
            node.elements.select_related("content_type").order_by("order", "pk")
        )
        return render(
            request,
            "courses/manage/_unit_panel.html",
            {"course": node.course, "node": node, "elements": elements},
        )
    return render(
        request,
        "courses/manage/_node_panel.html",
        {"course": node.course, "node": node},
    )


# --- node-op endpoints (Task 7) ---
def _require_manage(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    return course


def _render_scope(request, course, scope_ref):
    """Re-render a single scope <ol> (root carries data-scope). scope_ref is a parent
    pk or 'top'. Used for 200 success and 409 fresh-fragment on single-scope ops."""
    cmap = _children_map(course)
    if scope_ref == "top":
        nodes, updated = cmap.get(None, []), course.updated.isoformat()
    else:
        parent = ContentNode.objects.filter(pk=scope_ref, course=course).first()
        nodes = cmap.get(int(scope_ref), [])
        updated = parent.updated.isoformat() if parent else course.updated.isoformat()
    return render(
        request,
        "courses/manage/_scope.html",
        {
            "scope_id": scope_ref,
            "scope_updated": updated,
            "nodes": nodes,
            "children_map": cmap,
            "course": course,
            "kind_choices": ContentNode.Kind.choices,
        },
    )


def _render_tree(request, course, status=200):
    """Whole tree pane (root data-scope='top').

    Used for re-parent + top-scope ops + their 409s."""
    resp = _render_scope(request, course, "top")
    resp.status_code = status
    return resp


def _scope_ref(parent_id):
    return "top" if parent_id is None else parent_id


@login_required
def node_add(request, slug):
    course = _require_manage(request, slug)
    parent = request.POST.get("parent", "top")
    kind = request.POST.get("kind", "")
    # The add form's `unit_type` <select> always submits a value (it is only visually
    # hidden, not disabled, with JS off — and FormData includes it with JS on). The
    # model's clean() forbids a unit_type on a non-unit, so honour the field only for
    # units; otherwise a "part" carrying the default "lesson" would 422 spuriously.
    unit_type = request.POST.get("unit_type") if kind == ContentNode.Kind.UNIT else None
    try:
        node = builder_svc.add_node(
            course,
            parent,
            kind,
            request.POST.get("title", ""),
            unit_type,
            request.POST.get("parent_token"),
        )
    except builder_svc.ConflictError:
        # parent-gone or stale parent token -> whole tree pane
        # (the destination scope may be gone)
        if not _wants_fragment(request):
            return _builder_with_notice(
                request,
                course,
                _("This changed elsewhere — reloaded to the latest."),
                status=409,
            )
        return _render_tree(request, course, status=409)
    except ValidationError as e:
        msg = "; ".join(e.messages)
        if not _wants_fragment(request):
            return _builder_with_notice(request, course, msg, status=422)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    # top-level add touches the top scope -> whole tree pane; nested add -> that scope
    if node.parent_id is None:
        return _render_tree(request, course)
    return _render_scope(request, course, _scope_ref(node.parent_id))


@login_required
def node_rename(request, slug):
    course = _require_manage(request, slug)
    is_settings = "has_settings" in request.POST
    try:
        node = builder_svc.rename_node(
            course,
            request.POST.get("node"),
            request.POST.get("title", ""),
            request.POST.get("token"),
            unit_type=request.POST.get("unit_type")
            if is_settings
            else builder_svc._UNSET,
            obligatory=("obligatory" in request.POST)
            if is_settings
            else builder_svc._UNSET,
        )
    except builder_svc.ConflictError:
        if not _wants_fragment(request):
            return _builder_with_notice(
                request,
                course,
                _("This changed elsewhere — reloaded to the latest."),
                status=409,
            )
        return _conflict_scope(request, course, request.POST.get("node"))
    except ValidationError as e:
        msg = "; ".join(e.messages)
        if not _wants_fragment(request):
            return _builder_with_notice(request, course, msg, status=422)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    # a unit-settings change re-renders the unit panel; a plain rename re-renders scope
    if is_settings and node.kind == ContentNode.Kind.UNIT:
        return _render_unit_panel(request, node)
    # rename changes only the node row; re-render its parent scope so the label updates
    return _render_scope(request, course, _scope_ref(node.parent_id))


@login_required
def node_move(request, slug):
    course = _require_manage(request, slug)
    mode = request.POST.get("mode")
    if mode == "reorder":
        try:
            node, changed = builder_svc.reorder_node(
                course,
                request.POST.get("node"),
                request.POST.get("direction"),
                request.POST.get("token"),
            )
        except builder_svc.ConflictError:
            if not _wants_fragment(request):
                return _builder_with_notice(
                    request,
                    course,
                    _("This changed elsewhere — reloaded to the latest."),
                    status=409,
                )
            return _conflict_scope(request, course, request.POST.get("node"))
        if not _wants_fragment(request):
            return redirect("courses:manage_builder", slug=course.slug)
        if node.parent_id is None:
            return _render_tree(request, course)
        return _render_scope(request, course, _scope_ref(node.parent_id))
    elif mode == "reparent":
        position = request.POST.get("position")
        position = int(position) if position not in (None, "") else None
        try:
            builder_svc.reparent_node(
                course,
                request.POST.get("node"),
                request.POST.get("new_parent"),
                position,
                request.POST.get("node_token"),
                request.POST.get("parent_token"),
            )
        except builder_svc.ConflictError:
            if not _wants_fragment(request):
                return _builder_with_notice(
                    request,
                    course,
                    _("This changed elsewhere — reloaded to the latest."),
                    status=409,
                )
            return _render_tree(
                request, course, status=409
            )  # re-parent 409 -> whole tree
        except ValidationError as e:
            msg = "; ".join(e.messages)
            if not _wants_fragment(request):
                return _builder_with_notice(request, course, msg, status=422)
            return render(
                request, "courses/manage/_op_error.html", {"message": msg}, status=422
            )
        if not _wants_fragment(request):
            return redirect("courses:manage_builder", slug=course.slug)
        return _render_tree(
            request, course
        )  # re-parent touches two scopes -> whole tree
    elif request.method == "GET":
        # no-JS / JS picker: render the legal-destination picker for ?node=
        return _move_picker(request, course)
    return HttpResponseBadRequest("unknown mode")


@login_required
def node_delete(request, slug):
    course = _require_manage(request, slug)
    if request.method == "GET":
        node = get_node_or_404(int(request.GET["node"]), slug)
        if not can_manage_course(request.user, node.course):
            raise PermissionDenied
        counts = {
            "descendants": _descendant_count(node),
            "elements": _element_count(node),
        }
        return render(
            request,
            "courses/manage/node_confirm_delete.html",
            {"course": course, "node": node, "counts": counts},
        )
    try:
        parent_id = builder_svc.delete_node(
            course, request.POST.get("node"), request.POST.get("token")
        )
    except builder_svc.ConflictError:
        if not _wants_fragment(request):
            return _builder_with_notice(
                request,
                course,
                _("This changed elsewhere — reloaded to the latest."),
                status=409,
            )
        return _render_tree(request, course, status=409)
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    if parent_id is None:
        return _render_tree(request, course)
    return _render_scope(request, course, _scope_ref(parent_id))


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _builder_with_notice(request, course, message, status):
    """No-JS error response: re-render the WHOLE builder page with a notice (spec
    §No-JS fallback: 'stale token re-renders the full builder page with the notice')."""
    cmap = _children_map(course)
    return render(
        request,
        "courses/manage/builder.html",
        {
            "course": course,
            "children_map": cmap,
            "top_nodes": cmap.get(None, []),
            "kind_choices": ContentNode.Kind.choices,
            "notice": message,
        },
        status=status,
    )


def _conflict_scope(request, course, node_pk):
    node = (
        ContentNode.objects.filter(pk=node_pk, course=course)
        .select_related("parent")
        .first()
    )
    parent_id = node.parent_id if node else None
    resp = _render_scope(request, course, _scope_ref(parent_id))
    resp.status_code = 409
    return resp


def _descendant_count(node):
    total, stack = 0, list(node.children.all())
    while stack:
        cur = stack.pop()
        total += 1
        stack.extend(cur.children.all())
    return total


def _element_count(node):
    total, stack = 0, [node]
    while stack:
        cur = stack.pop()
        if cur.kind == ContentNode.Kind.UNIT:
            total += cur.elements.count()
        stack.extend(cur.children.all())
    return total


def _move_picker(request, course):
    node = get_node_or_404(int(request.GET["node"]), course.slug)
    if not can_manage_course(request.user, node.course):
        raise PermissionDenied
    # legal destinations: nodes whose kind is strictly shallower than node.kind,
    # excluding node and its descendants, plus 'top'.
    descendants = _descendant_ids(node)
    candidates = [
        n
        for n in course.nodes.all()
        if n.pk not in descendants
        and n.pk != node.pk
        and n.kind != ContentNode.Kind.UNIT
        and ContentNode.RANK[n.kind] < ContentNode.RANK[node.kind]
    ]
    return render(
        request,
        "courses/manage/_move_picker.html",
        {"course": course, "node": node, "candidates": candidates},
    )


def _descendant_ids(node):
    ids, stack = set(), list(node.children.all())
    while stack:
        cur = stack.pop()
        ids.add(cur.pk)
        stack.extend(cur.children.all())
    return ids


# --- element-op endpoints (Task 8) ---
def _render_unit_panel(request, unit):
    elements = list(
        unit.elements.select_related("content_type").order_by("order", "pk")
    )
    return render(
        request,
        "courses/manage/_unit_panel.html",
        {"course": unit.course, "node": unit, "elements": elements},
    )


@login_required
def element_move(request, slug):
    course = _require_manage(request, slug)
    try:
        unit, _changed = builder_svc.reorder_element(
            course,
            request.POST.get("element"),
            request.POST.get("direction"),
            request.POST.get("unit_token"),
        )
    except builder_svc.ConflictError:
        return _element_conflict(request, course)
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    return _render_unit_panel(request, unit)


@login_required
def element_delete(request, slug):
    course = _require_manage(request, slug)
    try:
        unit = builder_svc.delete_element(
            course, request.POST.get("element"), request.POST.get("unit_token")
        )
    except builder_svc.ConflictError:
        return _element_conflict(request, course)
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    return _render_unit_panel(request, unit)


def _element_conflict(request, course):
    """409 with a fresh element-list (unit) fragment, per spec §Element reorder/delete.
    Recover the unit from the `unit` payload field (the element forms send it), so a
    vanished element row still returns the unit panel rather than the whole tree pane.
    Only if the unit itself is gone do we fall back to the tree pane."""
    unit = ContentNode.objects.filter(
        pk=request.POST.get("unit"), course=course, kind=ContentNode.Kind.UNIT
    ).first()
    if unit is None:
        return _render_tree(request, course, status=409)
    resp = _render_unit_panel(request, unit)
    resp.status_code = 409
    return resp
