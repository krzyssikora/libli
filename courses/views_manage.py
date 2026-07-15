from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from courses import builder as builder_svc
from courses.access import can_manage_course
from courses.access import get_node_or_404  # reuse 1a's IDOR-safe resolver
from courses.forms import CourseForm
from courses.forms import SubjectForm
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import Enrollment
from courses.models import QuestionElement
from courses.models import Subject
from courses.models import UnitProgress


@login_required
def course_list(request):
    """My courses (admin) — view 5.1. Owner sees their own; a holder of
    courses.change_course (Platform Admin) sees all. Ordered by title."""
    if request.user.has_perm("courses.change_course"):
        courses = Course.objects.all()
    else:
        courses = Course.objects.filter(owner=request.user)
    # Optional subject drill-through (?subject=<slug>) — the "used by N courses"
    # count on /manage/subjects/ links here. Filter applies on top of the
    # owner/all scoping above; an unknown slug yields an empty (not unfiltered)
    # list, and active_subject drives the banner + clear affordance.
    sel_subject = request.GET.get("subject") or ""
    active_subject = None
    if sel_subject:
        courses = courses.filter(subjects__slug=sel_subject).distinct()
        active_subject = Subject.objects.filter(slug=sel_subject).first()
    courses = courses.order_by("title")
    # select_related the owner; prefetch subjects (chip row) + self-enrol cohorts
    # (status badge) shown on each row — keeps the list N+1-free.
    courses = courses.select_related("owner").prefetch_related(
        "subjects", "self_enroll_cohorts"
    )
    return render(
        request,
        "courses/manage/course_list.html",
        {
            "courses": courses,
            "active_subject": active_subject,
            # All subjects feed the filter dropdown, active-language ordered.
            "subjects": Subject.objects.localized_order(),
        },
    )


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
            form.save_m2m()  # subjects + self_enroll_cohorts skipped by commit=False
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
        },
    )


@login_required
def node_panel(request, slug, pk):
    node = get_node_or_404(pk, slug)  # 404 on missing / slug-mismatch, BEFORE access
    if not can_manage_course(request.user, node.course):
        raise PermissionDenied
    if node.kind == ContentNode.Kind.UNIT:
        elements = list(
            node.elements.filter(parent__isnull=True)
            .select_related("content_type")
            .order_by("order", "pk")
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
        nodes, updated, parent_kind = (
            cmap.get(None, []),
            course.updated.isoformat(),
            None,
        )
    else:
        parent = ContentNode.objects.filter(pk=scope_ref, course=course).first()
        nodes = cmap.get(int(scope_ref), [])
        updated = parent.updated.isoformat() if parent else course.updated.isoformat()
        parent_kind = parent.kind if parent else None
    return render(
        request,
        "courses/manage/_scope.html",
        {
            "scope_id": scope_ref,
            "scope_updated": updated,
            "parent_kind": parent_kind,
            "nodes": nodes,
            "children_map": cmap,
            "course": course,
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
    # The two unit chips submit name=unit_type (lesson|quiz) and NO kind; every other
    # chip submits name=kind. An explicit kind WINS — a stray unit_type on a non-unit is
    # ignored, never promoted to a unit (keeps the no-JS / forged-request contract and
    # test_add_non_unit_ignores_submitted_unit_type). Only when no kind is present do we
    # infer a unit from the unit_type the Lesson/Quiz chip carried.
    kind = request.POST.get("kind", "")
    if kind:
        unit_type = (
            request.POST.get("unit_type") if kind == ContentNode.Kind.UNIT else None
        )
    elif request.POST.get("unit_type"):
        kind = ContentNode.Kind.UNIT
        unit_type = request.POST.get("unit_type")
    else:
        unit_type = None
    try:
        if kind in ContentNode.RANK and kind not in course.allowed_kinds:
            # Course-policy exclusion: reuse the existing ValidationError -> 422
            # path below. Empty/unknown kinds are NOT caught here — they fall
            # through to add_node/full_clean unchanged.
            raise ValidationError(
                _("You can't add the %(kind)s level to this course.")
                % {"kind": ContentNode.Kind(kind).label}
            )
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
    is_type_only = "type_only" in request.POST
    # Unit settings live on the editor page now; that form posts ctx=editor and is a
    # plain full-page POST, so success/conflict/error route back to the editor.
    to_editor = request.POST.get("ctx") == "editor"
    node_pk = request.POST.get("node")
    try:
        node = builder_svc.rename_node(
            course,
            node_pk,
            # type-only toggle leaves the title untouched (never blanks it)
            builder_svc._UNSET if is_type_only else request.POST.get("title", ""),
            request.POST.get("token"),
            # Only steer unit_type when the POST actually carries it (the header
            # type-only toggle does; the editor settings form does NOT). Absent it
            # stays _UNSET so rename_node preserves the existing type instead of
            # blanking it — else full_clean() 422s "Units require a unit_type."
            unit_type=request.POST["unit_type"]
            if "unit_type" in request.POST
            else builder_svc._UNSET,
            obligatory=("obligatory" in request.POST)
            if is_settings
            else builder_svc._UNSET,
            html_seed_js=request.POST.get("html_seed_js", "")
            if is_settings
            else builder_svc._UNSET,
        )
    except builder_svc.ConflictError:
        if to_editor:
            url = reverse("courses:manage_editor", kwargs={"slug": slug, "pk": node_pk})
            return redirect(f"{url}?changed=1")
        if not _wants_fragment(request):
            return _builder_with_notice(
                request,
                course,
                _("This changed elsewhere — reloaded to the latest."),
                status=409,
            )
        return _conflict_scope(request, course, node_pk)
    except ValidationError as e:
        msg = "; ".join(e.messages)
        if to_editor:
            unit = get_node_or_404(node_pk, slug, require_unit=True)
            return _editor_page(request, unit, error=msg, status=422)
        if not _wants_fragment(request):
            return _builder_with_notice(request, course, msg, status=422)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if to_editor:
        return redirect("courses:manage_editor", slug=slug, pk=node.pk)
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
        try:
            node_pk = int(request.GET["node"])
        except (KeyError, ValueError, TypeError):
            raise Http404("Missing or invalid node parameter.") from None
        node = get_node_or_404(node_pk, slug)
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
    try:
        node_pk = int(request.GET["node"])
    except (KeyError, ValueError, TypeError):
        raise Http404("Missing or invalid node parameter.") from None
    node = get_node_or_404(node_pk, course.slug)
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
    cmap = _children_map(course)
    return render(
        request,
        "courses/manage/_move_picker.html",
        {
            "course": course,
            "node": node,
            "candidates": candidates,
            "children_map": cmap,
            "nodes_top": cmap.get(None, []),
        },
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
        unit.elements.filter(parent__isnull=True)
        .select_related("content_type")
        .order_by("order", "pk")
    )
    return render(
        request,
        "courses/manage/_unit_panel.html",
        {"course": unit.course, "node": unit, "elements": elements},
    )


@login_required
def element_move(request, slug):
    course = _require_manage(request, slug)
    direction = request.POST.get("direction")
    position_raw = request.POST.get("position")
    has_dir = direction in ("up", "down")
    has_pos = position_raw not in (None, "")
    if has_dir == has_pos:  # both present, or neither -> ambiguous
        return _op_error(request, _("Provide exactly one of direction or position."))
    position = None
    if has_pos:
        try:
            position = int(position_raw)
        except (TypeError, ValueError):
            return _op_error(request, _("Invalid position."))
    try:
        unit, _changed = builder_svc.reorder_element(
            course,
            request.POST.get("element"),
            request.POST.get("unit_token"),
            direction=direction if has_dir else None,
            position=position,
        )
    except builder_svc.ConflictError:
        return _element_conflict(request, course)
    if _editor_ctx(request):
        return _render_editor_fragments(request, unit)
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
    if _editor_ctx(request):
        return _render_editor_fragments(request, unit)
    if not _wants_fragment(request):
        return redirect("courses:manage_builder", slug=course.slug)
    return _render_unit_panel(request, unit)


def _editor_ctx(request):
    return request.POST.get("ctx") == "editor"


def _op_error(request, message):
    return render(
        request, "courses/manage/_op_error.html", {"message": message}, status=422
    )


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
    if _editor_ctx(request):
        if not _wants_fragment(request):  # no-JS editor conflict -> reload editor page
            return redirect(f"{_editor_path(course, unit)}?changed=1")
        return _render_editor_fragments(request, unit, status=409)
    resp = _render_unit_panel(request, unit)
    resp.status_code = 409
    return resp


# --- editor｜preview page (Task 4) ---
def _unit_ancestors(unit):
    """Root→parent chain (excluding the unit), for the breadcrumb. Variable depth."""
    chain, cur = [], unit.parent
    while cur is not None:
        chain.append(cur)
        cur = cur.parent
    chain.reverse()
    return chain


def _editor_rows(unit):
    """Return (join_rows, rows) for a unit's elements, shared by the editor view and the
    fragment renderer so they cannot drift. `join_rows` are Element instances (what
    render_element expects); `rows` are (join_row, concrete_obj) for the list template.
    Accessing .content_object caches it on the Element, so passing join_rows to the
    preview re-uses that cached object (no extra query in render_element)."""
    join_rows = list(
        unit.elements.filter(parent__isnull=True)
        .select_related("content_type", "unit__course")
        .order_by("order", "pk")
    )
    rows = [(e, e.content_object) for e in join_rows]
    return join_rows, rows


def _render_editor_fragments(
    request, unit, status=200, open_form="", open_form_pk="", refresh=True
):
    """Render editor pane + preview as two data-scope fragments (the single source for
    every editor-context 200/409/422 response). Serialises data-updated from the
    freshly-read unit row so the token never desyncs. `refresh=False` lets a caller that
    already refreshed avoid a redundant second refresh."""
    if refresh:
        unit.refresh_from_db(fields=["updated"])
    join_rows, rows = _editor_rows(unit)
    resp = render(
        request,
        "courses/manage/editor/_editor_scope.html",
        {
            "course": unit.course,
            "unit": unit,
            "rows": rows,
            "open_form": open_form,
            "open_form_pk": open_form_pk,
            "ancestors": _unit_ancestors(unit),
            # JOIN-ROWS — render_element takes an Element
            "preview_elements": join_rows,
            # gates the add-menu's "Interactive" (revealgate) group — quiz units
            # don't offer it. _add_menu.html is included without `only`, so this
            # flows straight through the same context to the nested add-menu too.
            "unit_is_quiz": unit.unit_type == ContentNode.UnitType.QUIZ,
        },
    )
    resp.status_code = status
    return resp


def _editor_page(request, unit, *, error="", changed=False, status=200):
    """Render the full editor page (not just the swappable scope). Shared by the
    editor view and the unit-settings save path so a 422 can re-render with an
    error banner."""
    join_rows, rows = _editor_rows(unit)
    resp = render(
        request,
        "courses/manage/editor/editor.html",
        {
            "course": unit.course,
            "unit": unit,
            "rows": rows,
            "ancestors": _unit_ancestors(unit),
            # JOIN-ROWS — render_element takes an Element
            "preview_elements": join_rows,
            "changed": changed,
            "error": error,
            # gates the add-menu's "Interactive" (revealgate) group — see the
            # matching comment in _render_editor_fragments.
            "unit_is_quiz": unit.unit_type == ContentNode.UnitType.QUIZ,
        },
    )
    resp.status_code = status
    return resp


@login_required
def editor(request, slug, pk):
    unit = get_node_or_404(pk, slug, require_unit=True)  # 404-before-403
    if not can_manage_course(request.user, unit.course):
        raise PermissionDenied
    return _editor_page(request, unit, changed=request.GET.get("changed") == "1")


# type_key -> human label for the editor heading. Choice questions are special-cased
# in _render_open_form (single vs multiple), so they are deliberately absent here.
# gettext_lazy (not eager _): this dict is built once at import, so eager strings
# would freeze to the import-time locale and never translate per request. The lazy
# proxies resolve to the active language when the template renders them.
_EDITOR_TYPE_LABELS = {
    "text": gettext_lazy("Text"),
    "image": gettext_lazy("Image"),
    "video": gettext_lazy("Video"),
    "iframe": gettext_lazy("Iframe"),
    "math": gettext_lazy("Math"),
    "html": gettext_lazy("HTML"),
    "table": gettext_lazy("Table"),
    "gallery": gettext_lazy("Gallery"),
    "tabs": gettext_lazy("Tabs"),
    "slidebreak": gettext_lazy("Slide break"),
    "revealgate": gettext_lazy("Show more"),
    "spoiler": gettext_lazy("Spoiler"),
    "fillgate": gettext_lazy("Fill in & confirm"),
    "switchgate": gettext_lazy("Choose & confirm"),
    "switchgrid": gettext_lazy("Switch grid"),
    "filltable": gettext_lazy("Fill-in table"),
    "callout": gettext_lazy("Callout"),
    "stepper": gettext_lazy("Step-by-step"),
    "shorttextquestion": gettext_lazy("Short text"),
    "shortnumericquestion": gettext_lazy("Short numeric"),
    "fillblankquestion": gettext_lazy("Fill in the blanks"),
    "dragfillblankquestion": gettext_lazy("Drag the words"),
    "matchpairquestion": gettext_lazy("Match pairs"),
    "choicegridquestion": gettext_lazy("Matrix question"),
    "multigridquestion": gettext_lazy("Multi-select grid"),
    "dragtoimagequestion": gettext_lazy("Drag to image"),
    "extendedresponsequestion": gettext_lazy("Extended response"),
}


# --- element add (render-only) + save (create-on-first-save / update) (Task 6) ---
def _render_open_form(
    request,
    unit,
    type_key,
    element_pk="new",
    form=None,
    formset=None,
    formset2=None,
    initial=None,
    status=200,
    parent="",
    tab="",
):
    """Render the host <form> wrapping a per-type editor partial, then the full editor
    scope with that form embedded in the form host.

    `parent`/`tab` are only meaningful on a nested CREATE: they round-trip as hidden
    fields so scope survives the two-hop element_add -> element_save create, and
    survives an ElementFormInvalid 422 re-render. The edit-an-existing-element path
    (element_form) leaves both at their "" default -- an update never reads them."""
    from courses.element_forms import _SG_SEED_STEM
    from courses.element_forms import FORM_FOR_TYPE
    from courses.element_forms import build_choice_formset

    if form is None:
        extra = (
            {"course": unit.course}
            if type_key in ("image", "video", "dragtoimagequestion", "gallery")
            else {}
        )
        form = FORM_FOR_TYPE[type_key](initial=initial or {}, **extra)
    # Compute a SINGLE authoritative is_multiple for the template (radio vs checkbox),
    # rather than letting the template derive it from bound/unbound form attrs
    # (fragile).
    is_multiple = False
    if type_key == "choicequestion":
        if form.instance.pk:
            is_multiple = form.instance.multiple  # edit: the stored value
        elif initial:
            is_multiple = bool(initial.get("multiple"))  # fresh add: the card's seed
        elif form.is_bound and "multiple" in form.fields:
            # 422 re-render of a create: coerce via the BooleanField, NOT bool(POST
            # string). HiddenInput posts "False" and bool("False") is True — the same
            # round-4 trap.
            is_multiple = form.fields["multiple"].to_python(form.data.get("multiple"))
        if formset is None:
            instance = form.instance if form.instance.pk else None
            formset = build_choice_formset(instance=instance)
    elif type_key == "matchpairquestion" and formset is None:
        from courses.element_forms import build_matchpair_formset

        instance = form.instance if form.instance.pk else None
        formset = build_matchpair_formset(instance=instance)
    elif type_key == "dragtoimagequestion" and formset is None:
        from courses.element_forms import build_dragzone_formset

        instance = form.instance if form.instance.pk else None
        formset = build_dragzone_formset(instance=instance)
    elif type_key == "choicegridquestion" and formset is None:
        # Fresh-render path: build BOTH formsets. On the 422 re-render they arrive
        # already-bound (non-None) and must NOT be rebuilt.
        from courses.element_forms import build_choicegrid_columns_formset
        from courses.element_forms import build_choicegrid_rows_formset

        instance = form.instance if form.instance.pk else None
        formset = build_choicegrid_columns_formset(instance=instance)
        formset2 = build_choicegrid_rows_formset(instance=instance)
    elif type_key == "multigridquestion" and formset is None:
        from courses.element_forms import build_multigrid_columns_formset
        from courses.element_forms import build_multigrid_rows_formset

        instance = form.instance if form.instance.pk else None
        formset = build_multigrid_columns_formset(instance=instance)
        formset2 = build_multigrid_rows_formset(instance=instance)
    elif type_key == "stepper" and formset is None:
        from courses.element_forms import build_stepper_formset

        instance = form.instance if form.instance.pk else None
        formset = build_stepper_formset(instance=instance)
    # Human label of the element type being edited, shown at the top of the editor so
    # the author always knows what they are editing (a choice question has no other
    # visible type cue, and single vs multiple is otherwise invisible).
    if type_key == "choicequestion":
        editor_title = _("Multiple choice") if is_multiple else _("Single choice")
    else:
        editor_title = _EDITOR_TYPE_LABELS.get(type_key, type_key)
    # current author label for an existing element (blank for a new one)
    el_title = ""
    if element_pk != "new":
        el_title = (
            Element.objects.filter(pk=element_pk, unit=unit)
            .values_list("title", flat=True)
            .first()
            or ""
        )
    unit.refresh_from_db(fields=["updated"])
    form_html = render(
        request,
        "courses/manage/editor/_host_form.html",
        {
            "course": unit.course,
            "unit": unit,
            "type_key": type_key,
            "editor_title": editor_title,
            "element_pk": element_pk,
            "form": form,
            "formset": formset,
            # Matrix (choicegrid) reads two named formsets; set UNCONDITIONALLY so the
            # 422 re-render (bound, non-None from e.formset/e.formset2) keeps the
            # author's invalid input instead of rendering empty.
            "columns_formset": formset,
            "rows_formset": formset2,
            "is_multiple": is_multiple,
            "el_title": el_title,
            "is_quiz": unit.unit_type == ContentNode.UnitType.QUIZ,
            "parent": parent,
            "tab": tab,
            "sg_seed_stem": _SG_SEED_STEM,
        },
    ).content.decode()
    return _render_editor_fragments(
        request,
        unit,
        status=status,
        open_form=form_html,
        open_form_pk=str(element_pk),
        refresh=False,
    )


@login_required
def element_add(request, slug):
    course = _require_manage(request, slug)
    raw = request.POST.get("type")
    initial = None
    if raw in ("choice-single", "choice-multi"):
        initial = {"multiple": raw == "choice-multi"}
        type_key = "choicequestion"
    else:
        type_key = raw
    if type_key not in (
        "text",
        "image",
        "video",
        "iframe",
        "math",
        "html",
        "table",
        "gallery",
        "tabs",
        "revealgate",
        "fillgate",
        "switchgate",
        "switchgrid",
        "filltable",
        "spoiler",
        "callout",
        "stepper",
        "choicequestion",
        "shorttextquestion",
        "shortnumericquestion",
        "fillblankquestion",
        "dragfillblankquestion",
        "matchpairquestion",
        "choicegridquestion",
        "multigridquestion",
        "dragtoimagequestion",
        "extendedresponsequestion",
    ):
        return HttpResponseBadRequest("bad type")
    unit = get_object_or_404(
        ContentNode,
        pk=request.POST.get("unit"),
        course=course,
        kind=ContentNode.Kind.UNIT,
    )
    # Validate the scope now (render-only), so a blocked nested type 400s on the click
    # rather than at save. resolve_scope raises NestingError on any violation.
    # Note: "slidebreak" isn't in this allow-tuple at all, so a nested slidebreak 400s
    # at the "bad type" check above, before resolve_scope ever runs -- it does NOT
    # exercise the nesting gate. "choicequestion" and "tabs" are the cases here that
    # actually reach resolve_scope and prove nesting is blocked.
    try:
        parent_join, tab_id = builder_svc.resolve_scope(
            unit, request.POST.get("parent"), request.POST.get("tab"), type_key
        )
    except builder_svc.NestingError:
        return HttpResponseBadRequest("bad nesting")
    return _render_open_form(
        request,
        unit,
        type_key,
        element_pk="new",
        initial=initial,
        parent=str(parent_join.pk) if parent_join else "",
        tab=tab_id,
    )


@login_required
def element_save(request, slug):
    course = _require_manage(request, slug)
    type_key = request.POST.get("type")
    if type_key not in (
        "text",
        "image",
        "video",
        "iframe",
        "math",
        "html",
        "table",
        "gallery",
        "tabs",
        "slidebreak",
        "revealgate",
        "fillgate",
        "switchgate",
        "switchgrid",
        "filltable",
        "spoiler",
        "callout",
        "stepper",
        "choicequestion",
        "shorttextquestion",
        "shortnumericquestion",
        "fillblankquestion",
        "dragfillblankquestion",
        "matchpairquestion",
        "choicegridquestion",
        "multigridquestion",
        "dragtoimagequestion",
        "extendedresponsequestion",
    ):
        return HttpResponseBadRequest("bad type")
    element_ref = request.POST.get("element", "new")
    unit_pk = request.POST.get("unit")
    try:
        unit = builder_svc.save_element(
            course, unit_pk, type_key, element_ref, request.POST, request.FILES
        )
    except builder_svc.ConflictError:
        unit = ContentNode.objects.filter(
            pk=unit_pk, course=course, kind=ContentNode.Kind.UNIT
        ).first()
        if unit is None:
            return _render_tree(request, course, status=409)
        if not _wants_fragment(request):
            return redirect(f"{_editor_path(course, unit)}?changed=1")
        return _render_editor_fragments(request, unit, status=409)
    except builder_svc.NestingError:
        return HttpResponseBadRequest("bad nesting")
    except builder_svc.ElementFormInvalid as e:
        unit = ContentNode.objects.filter(
            pk=unit_pk, course=course, kind=ContentNode.Kind.UNIT
        ).first()
        if unit is None:
            return _render_tree(request, course, status=409)
        # A nested CREATE's 422 re-render must carry the scope forward, or the
        # corrected resubmit lands the child at top level. An update never reads
        # parent/tab.
        is_create = element_ref == "new"
        return _render_open_form(
            request,
            unit,
            type_key,
            element_pk=element_ref,
            form=e.form,
            formset=e.formset,
            formset2=e.formset2,
            status=422,
            parent=request.POST.get("parent", "") if is_create else "",
            tab=request.POST.get("tab", "") if is_create else "",
        )
    if not _wants_fragment(request):
        return redirect(_editor_path(course, unit))
    return _render_editor_fragments(request, unit)


def _editor_path(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@login_required
def element_form(request, slug, pk):
    """GET the editor host-form for an EXISTING element (the .el-select edit flow).
    Render-only (no token check, no write); reuses _render_open_form with instance."""
    course = _require_manage(request, slug)
    el = get_object_or_404(Element, pk=pk, unit__course=course)
    type_key = el.content_object.__class__.__name__.lower().replace("element", "")
    from courses.element_forms import FORM_FOR_TYPE
    from courses.element_forms import build_choice_formset

    extra = (
        {"course": course}
        if type_key in ("image", "video", "dragtoimagequestion", "gallery")
        else {}
    )
    form = FORM_FOR_TYPE[type_key](instance=el.content_object, **extra)
    formset = None
    formset2 = None
    if type_key == "choicequestion":
        formset = build_choice_formset(instance=el.content_object)
    elif type_key == "matchpairquestion":
        from courses.element_forms import build_matchpair_formset

        formset = build_matchpair_formset(instance=el.content_object)
    elif type_key == "dragtoimagequestion":
        from courses.element_forms import build_dragzone_formset

        formset = build_dragzone_formset(instance=el.content_object)
    elif type_key == "choicegridquestion":
        from courses.element_forms import build_choicegrid_columns_formset
        from courses.element_forms import build_choicegrid_rows_formset

        formset = build_choicegrid_columns_formset(instance=el.content_object)
        formset2 = build_choicegrid_rows_formset(instance=el.content_object)
    elif type_key == "multigridquestion":
        from courses.element_forms import build_multigrid_columns_formset
        from courses.element_forms import build_multigrid_rows_formset

        formset = build_multigrid_columns_formset(instance=el.content_object)
        formset2 = build_multigrid_rows_formset(instance=el.content_object)
    return _render_open_form(
        request,
        el.unit,
        type_key,
        element_pk=pk,
        form=form,
        formset=formset,
        formset2=formset2,
    )


@login_required
@require_POST
def element_try(request, slug, pk):
    """Authoring 'try-it' for the live preview: grade a question answer and return the
    same feedback partial students get, WITHOUT persisting anything. Manage-gated so
    an author (who is not an enrolled student) can test a question in the preview.
    Reuses the exact grading path as the student lesson check (build_answer + mark)."""
    course = _require_manage(request, slug)
    el = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=pk, unit__course=course
    )
    question = el.content_object
    if not isinstance(question, QuestionElement):
        return HttpResponseBadRequest("not a question element")
    answer = question.build_answer(request.POST)

    # Lesson: immediate feedback, exactly like the student lesson check.
    if el.unit.unit_type != ContentNode.UnitType.QUIZ:
        result = question.mark(answer)  # NOTHING is persisted
        if isinstance(question, ChoiceQuestionElement):
            selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
            return HttpResponse(
                question.render(
                    element=el,
                    mode="lesson",
                    selected_ids=selected,
                    mark_result=result,
                    feedback_for_pk=el.pk,
                )
            )
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )

    # Quiz: mirror the reveal-gated student experience ephemerally — the correct
    # answer is withheld until the question locks (correct, or wrong on the last
    # attempt). The client tracks the attempt number; we synthesise the per-question
    # response state. NOTHING is persisted (no QuizSubmission/QuestionResponse).
    from types import SimpleNamespace

    from courses.quiz import answer_is_empty
    from courses.quiz import quiz_feedback_context

    try:
        attempt = max(1, int(request.POST.get("attempt", "1")))
    except (TypeError, ValueError):
        attempt = 1

    if answer_is_empty(answer):
        fake = SimpleNamespace(locked=False, attempt_count=attempt - 1)
        ctx = quiz_feedback_context(question, fake, validation=True)
        return render(request, "courses/elements/_quiz_question_feedback.html", ctx)

    is_auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
    result = question.mark(answer) if is_auto else None
    if is_auto:
        locked = bool(result.correct) or (
            question.max_attempts is not None and attempt >= question.max_attempts
        )
    else:
        locked = True  # [N]/[R]: single submission
    fake = SimpleNamespace(locked=locked, attempt_count=attempt)
    ctx = quiz_feedback_context(question, fake, result=result)
    return render(request, "courses/elements/_quiz_question_feedback.html", ctx)


# --- subject CRUD (Phase 5a, Task 6) ---


@login_required
@permission_required("courses.change_subject", raise_exception=True)
def subject_list(request):
    # localized_order(): Polish-name order under PL so the list reads alphabetically
    # to a Polish admin; English order otherwise (see Subject.localized_order).
    subjects = Subject.objects.annotate(
        course_count=Count("courses", distinct=True)
    ).localized_order()
    return render(request, "courses/manage/subject_list.html", {"subjects": subjects})


@login_required
@permission_required("courses.add_subject", raise_exception=True)
def subject_create(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("courses:manage_subject_list")
    else:
        form = SubjectForm()
    return render(
        request, "courses/manage/subject_form.html", {"form": form, "creating": True}
    )


@login_required
@permission_required("courses.change_subject", raise_exception=True)
def subject_edit(request, slug):
    subject = get_object_or_404(Subject, slug=slug)
    if request.method == "POST":
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            return redirect("courses:manage_subject_list")
    else:
        form = SubjectForm(instance=subject)
    return render(
        request,
        "courses/manage/subject_form.html",
        {"form": form, "creating": False, "subject": subject},
    )


@login_required
@permission_required("courses.delete_subject", raise_exception=True)
def subject_delete(request, slug):
    subject = get_object_or_404(Subject, slug=slug)
    if request.method == "POST":
        subject.delete()  # M2M: just unlinks from courses, no orphaned data
        return redirect("courses:manage_subject_list")
    course_count = subject.courses.count()
    return render(
        request,
        "courses/manage/subject_confirm_delete.html",
        {"subject": subject, "course_count": course_count},
    )
