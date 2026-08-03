from dataclasses import dataclass

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
from django.utils.http import urlencode
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from courses import builder as builder_svc
from courses import builder_filter
from courses import builder_open  # for builder_open.CEILING -- see below
from courses.access import can_manage_course
from courses.access import get_node_or_404  # reuse 1a's IDOR-safe resolver
from courses.builder_open import LAST_NODE_KEY
from courses.builder_open import OPEN_KEY
from courses.builder_open import SESSION_SLUG_LIMIT
from courses.builder_open import container_pks
from courses.builder_open import open_ids as _open_ids
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
from courses.richtext import count_inbound_links
from courses.transfer.schema import TransferError


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


def _open_descendants(cmap, ids):
    """pk -> the OPEN container pks beneath it, in one bottom-up pass.

    Per row this would be a subtree walk; computed once per render it is a
    single pass, which is what keeps toggle_href off the render's critical
    path under a fully expanded tree.
    """
    out = {}

    def walk(pk):
        if pk in out:
            return out[pk]
        acc = set()
        for child in cmap.get(pk, []):
            if child.kind == ContentNode.Kind.UNIT:
                continue
            if child.pk in ids:
                acc.add(child.pk)
            acc |= walk(child.pk)
        out[pk] = acc
        return acc

    # Only OPEN containers need an entry: a collapsed row's toggle is an
    # EXPAND href, which uses the open_joined fast path and never consults
    # this map. Walking every container instead would add a full-cmap pass to
    # the toggle endpoint, whose budget is < 300 ms.
    for pk in ids:
        walk(pk)
    return out


def _raw_q(request):
    """POST then GET. Named because TEN non-rendering sites need their own
    read: the six _redirect_to_builder mutation sites, node_delete's GET,
    node_delete's bespoke `?open=` redirect branch, _move_picker (NOT
    node_move's GET, which only delegates to it), and node_move's
    mode=="reorder" guard. Without one helper the resolution rule is
    re-expressed eleven times.

    Mutation forms carry a hidden `q` in the body; toggles, manage_node_scope
    and manage_tree carry it in the query string. The body wins because the
    JS collector sets it there.
    """
    if "q" in request.POST:
        return request.POST["q"]
    return request.GET.get("q", "")


@dataclass(frozen=True)
class FilterContext:
    """A record, not a tuple: it carries seven things and two of them are
    easy to leave out and expensive to leave out.

    q_raw -- if this is not handed back, all three renderers re-do the
    POST-then-GET read to populate the `q` context key, reinstating the
    resolution rule in three places. It is the RAW value, not the normalized
    one, because a half-typed ?q=a must survive into the input and every href.

    opened AND open_ids -- _tree_context must render from the union with
    effect 1, while _remember_open must read `opened` untouched, or builder()
    persists forced-open pks as though the author had chosen them.
    """

    # The RESTRICTED children-map (post-filter). Every caller also has a
    # local `cmap` holding the FULL map -- do not confuse the two.
    restricted: dict
    opened: builder_open.OpenSet
    open_ids: frozenset
    shown: int
    total: int
    q_active: bool
    q_raw: str


def _filter_context(request, course, cmap, *, mode, extra_open=()):
    """The one owner of q resolution, the restricted map, effect 2 and the
    open set.

    `mode` is required and has no default: the three callers need "page",
    "notice" and "fragment", and open_ids's own default is "fragment" -- so a
    mode-less helper would silently put builder() on the fragment row and
    destroy both the session seed and the <=150-node rule, on the one path
    where they matter.
    """
    q_raw = _raw_q(request)
    restricted, chains, shown, total, q_active = builder_filter.filtered_map(
        cmap, q_raw
    )
    # The chain set when q is ACTIVE, not when it is non-empty: a filter that
    # matches nothing yields an EMPTY chain set, and passing None there would
    # fall through to steps 4-6 (spec 3b).
    opened = _open_ids(
        request, course, cmap, mode=mode, q_chain=chains if q_active else None
    )
    ids = set(opened.ids) | _extra_container_pks(extra_open, cmap)
    _apply_effect_two(restricted, extra_open, cmap)
    return FilterContext(
        restricted=restricted,
        opened=opened,
        open_ids=frozenset(ids),
        shown=shown,
        total=total,
        q_active=q_active,
        q_raw=q_raw,
    )


def _apply_effect_two(restricted, extra_open, full_cmap):
    """Re-insert each forced pk's node into the RESTRICTED map.

    `setdefault`, not `restricted[...]`: _children_map only creates a key for
    a parent that HAS children (views_manage.py:139-141), and the restricted
    map is built by regrouping the kept nodes -- so a matched container with
    no matching descendants has no key of its own, and a filter that matched
    nothing has no None key. Spec 1d ships an add affordance into exactly
    those empty scopes, so "filter for a chapter, add a unit inside it" would
    raise KeyError -> 500.

    Applies to EVERY pk regardless of kind, units included; effect 1 keeps
    the container-only filter. Splitting the kind test across the two effects
    is what makes both pinned requirements satisfiable at once.
    """
    if not extra_open:
        return
    index = builder_open.nodes_by_pk(full_cmap)
    for pk in extra_open:
        node = index.get(pk)
        if node is None:
            continue
        rows = restricted.setdefault(node.parent_id, [])
        if any(existing.pk == node.pk for existing in rows):
            continue  # idempotent: a duplicate row breaks the DOM collector
        rows.append(node)
        rows.sort(key=lambda n: (n.order, n.pk))


def _tree_context(course, cmap, ids, *, q, filtered, expand_all_disabled, q_min):
    """`cmap` here is the FULL map: _open_descendants builds the descendant
    sets a COLLAPSE href subtracts, and over the restricted map an open
    descendant the filter excluded would survive in the emitted `open` and
    spring back the moment the filter is cleared.
    """
    return {
        "open_ids": ids,
        "open_joined": ",".join(str(p) for p in sorted(ids)),
        "open_descendants": _open_descendants(cmap, ids),
        "builder_url": reverse("courses:manage_builder", kwargs={"slug": course.slug}),
        "q": q,
        "filtered": filtered,
        "expand_all_disabled": expand_all_disabled,
        "q_min": q_min,
    }


def _expand_all_disabled(cmap):
    """Read CEILING THROUGH the module: tests monkeypatch
    courses.builder_open.CEILING, and a by-value import desyncs this guard
    from the patched number -- the same trap _info_entries documents.
    """
    return len(builder_open.container_pks(cmap)) > builder_open.CEILING


def remember_node(request, slug, pk, key=LAST_NODE_KEY):
    """Store a per-course pk (or pk list) in the session, most-recent last.

    Skips the write when the value is unchanged: with a DB-backed session an
    unconditional write means a session save on EVERY row focus.
    """
    store = request.session.get(key) or {}
    if store.get(slug) == pk:
        return
    # pop before re-inserting: a dict preserves INSERTION order and
    # re-assigning an existing key does not move it to the end, so without
    # this the eviction below drops recently-used slugs first.
    store.pop(slug, None)
    store[slug] = pk
    while len(store) > SESSION_SLUG_LIMIT:
        store.pop(next(iter(store)))
    request.session[key] = store
    request.session.modified = True


def _ancestor_chain(node):
    """The node's own pk plus every ancestor pk. One query per level, and the
    chain is at most 4 deep, so this is bounded."""
    out, cur = {node.pk}, node.parent
    while cur is not None:
        out.add(cur.pk)
        cur = cur.parent
    return out


def _remember_open(request, course, opened, *, q_active):
    """Persist ONLY an author-chosen open set (precedence steps 1-2).

    The `q_active` gate is the half slice 1 could not write, and the parent
    spec pins it: without it a no-JS author filters, clicks a toggle whose
    href carries `open = <the filter's chains> +- pk`, that arrives via step 2
    as explicit=True, and the DERIVED chains are written over their real
    pre-filter expansion -- permanently, since the no-JS path has no stash.

    Gated on q_active, NOT on `"q" in request.GET`: a below-floor `?q=a`
    renders unfiltered, so its `open` is a genuine author-chosen set and
    suppressing the write would lose it.
    """
    if q_active or not opened.explicit:
        return
    # Bound the PAYLOAD, not just the slug count. Without this an author who
    # opens 20 large courses with ?open=all stores up to 20 x CEILING = 10,000
    # integers in a DB-backed session that is decoded on every subsequent
    # request -- a new per-request cost, on a PR whose premise is request cost.
    remember_node(
        request,
        course.slug,
        sorted(opened.ids)[: builder_open.SESSION_OPEN_LIMIT],
        key=OPEN_KEY,
    )


@login_required
def builder(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    cmap = _children_map(course)
    force = _take_builder_force(request, course.slug)
    fc = _filter_context(request, course, cmap, mode="page", extra_open=force)
    _remember_open(request, course, fc.opened, q_active=fc.q_active)
    context = {
        "course": course,
        "children_map": fc.restricted,
        "top_nodes": fc.restricted.get(None, []),
        "info": _info_entries(
            fc.opened, q_active=fc.q_active, shown=fc.shown, total=fc.total
        ),
    }
    context.update(
        _tree_context(
            course,
            cmap,
            fc.open_ids,
            q=fc.q_raw,
            filtered=fc.q_active,
            expand_all_disabled=_expand_all_disabled(cmap),
            q_min=builder_filter.MIN_QUERY,
        )
    )
    return render(request, "courses/manage/builder.html", context)


@login_required
def link_picker(request, slug):
    """The course tree, as a bare partial, for the rich-text link dialog.

    Rendered standalone (no base.html) because the dialog fetches it and injects the
    markup directly. Like `builder`, passes children_map PLUS top_nodes: _children_map
    keys roots under None, which a template cannot index.
    """
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    cmap = _children_map(course)
    return render(
        request,
        "courses/manage/editor/_link_picker.html",
        {"course": course, "children_map": cmap, "top_nodes": cmap.get(None, [])},
    )


@login_required
def node_panel(request, slug, pk):
    node = get_node_or_404(pk, slug)  # 404 on missing / slug-mismatch, BEFORE access
    if not can_manage_course(request.user, node.course):
        raise PermissionDenied
    remember_node(request, node.course.slug, node.pk)
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


@login_required
def manage_tree(request, slug):
    """The whole top scope, as a fragment, for the filter and expand-all.

    builder() returns a full page and is the only builder view with no
    _wants_fragment branch; manage_node_scope is declared <int:pk> so it
    cannot serve the top scope. Adding a fragment branch to builder() would
    silently change its contract for every existing test that sends
    X-Requested-With: fetch.
    """
    course = _require_manage(request, slug)
    return _render_tree(request, course)


@login_required
def node_scope(request, slug, pk):
    """One scope <ol>, for the JS expand path.

    _require_manage alone is NOT enough: it validates the COURSE, and
    _render_scope resolves a missing/foreign pk to parent=None and returns 200
    with an empty scope. Resolve the node first, mirroring node_panel.
    """
    node = get_node_or_404(pk, slug)
    if node.kind == ContentNode.Kind.UNIT:
        raise Http404("Units own no scope.")
    course = _require_manage(request, slug)
    return _render_scope(request, course, node.pk)


# --- node-op endpoints (Task 7) ---
def _require_manage(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise PermissionDenied
    return course


def _render_scope(request, course, scope_ref, *, extra_open=()):
    """Re-render a single scope <ol> (root carries data-scope). scope_ref is a parent
    pk or 'top'. Used for 200 success and 409 fresh-fragment on single-scope ops."""
    cmap = _children_map(course)
    fc = _filter_context(request, course, cmap, mode="fragment", extra_open=extra_open)
    if scope_ref == "top":
        nodes, updated, parent_kind = (
            fc.restricted.get(None, []),
            course.updated.isoformat(),
            None,
        )
    else:
        parent = ContentNode.objects.filter(pk=scope_ref, course=course).first()
        nodes = fc.restricted.get(int(scope_ref), [])
        updated = parent.updated.isoformat() if parent else course.updated.isoformat()
        parent_kind = parent.kind if parent else None
    context = {
        "scope_id": scope_ref,
        "scope_updated": updated,
        "parent_kind": parent_kind,
        "nodes": nodes,
        "children_map": fc.restricted,  # the recursive descent walks this
        "course": course,  # and _tree_toggle's counts read this
    }
    context.update(
        _tree_context(
            course,
            cmap,  # the FULL map, always
            fc.open_ids,
            q=fc.q_raw,
            filtered=fc.q_active,
            expand_all_disabled=_expand_all_disabled(cmap),
            q_min=builder_filter.MIN_QUERY,
        )
    )
    resp = render(request, "courses/manage/_scope.html", context)
    entries = _info_entries(
        fc.opened, q_active=fc.q_active, shown=fc.shown, total=fc.total
    )
    # ALWAYS set, and FULL STATE: every entry that applies to this response,
    # so the client can remove a key this header omits (Task 12). `none` when
    # nothing applies. The parent spec pairs "absent when none apply" with
    # "an absent header clears all keys", and the client cannot implement
    # that pair: the submit handler serves both a rename
    # (_rename_result.html, no header, must NOT clear) and an add (a scope, no
    # codes, MUST clear), and those are byte-identical from its side.
    resp["X-Builder-Info"] = ", ".join(e["code"] for e in entries) or "none"
    return resp


def _info_entries(opened, *, q_active, shown, total):
    """Keyed, so an incoming entry REPLACES rather than stacks.

    The truncation entry below reads `builder_open.CEILING` THROUGH the
    module, not via a `from ... import CEILING`: tests monkeypatch
    `courses.builder_open.CEILING`, and a by-value import would bind the
    original number at import time and desync this text from the patched
    guard.

    ONE WORD PER CONCEPT: the info key, the header code prefix and the
    data-msg-* suffix are the same token. Three near-synonyms would force the
    JS to carry a prefix->key map that lives nowhere, and a registry keyed off
    the code prefix would never match the server-rendered
    data-info-key="truncation" entry -- appending a second copy, which is the
    bug the read-on-init rule exists to close.

    SAME LITERAL per notice, here and in the data-msg-<key> attribute,
    deliberately -- but they do NOT collapse to one catalog entry. Django's
    {% trans %} looks up a msgid with every literal "%" doubled, while this
    _() call looks up the single-% form; a "%"-bearing literal therefore
    always occupies TWO msgids that must be kept in translation-sync by
    hand (see the paired entries in locale/*/LC_MESSAGES/django.po). The
    property this buys is not "one entry" but "the page and the fragment
    route agree" -- verified by test_both_notice_routes_agree_in_polish.
    """
    entries = []
    if opened.truncated:
        entries.append(
            {
                "key": "truncation",
                "code": f"truncation;limit={builder_open.CEILING}",
                "text": _("Only the first %(limit)s scopes were opened.")
                % {"limit": builder_open.CEILING},
            }
        )
    if q_active:
        # Emitted whenever q is active, INCLUDING shown == total == 0:
        # "Filtered: 0 / 0" over an empty tree is the only explanation the
        # author gets.
        entries.append(
            {
                "key": "filter",
                "code": f"filter;shown={shown};total={total}",
                "text": _("Filtered: %(shown)s / %(total)s")
                % {"shown": shown, "total": total},
            }
        )
    return entries


def _extra_container_pks(extra_open, cmap):
    """Effect 1 of extra_open: union into the open set, unit pks dropped.

    Effect 2 (re-inserting into a filtered map) is slice 2 -- see spec
    section 9. Callers pass EVERY created/moved pk whatever its kind; the kind
    filter lives here, not at the call site.
    """
    return set(extra_open) & container_pks(cmap)


def _render_tree(request, course, status=200, *, extra_open=()):
    """Whole tree pane (root data-scope='top').

    Used for re-parent + top-scope ops + their 409s."""
    resp = _render_scope(request, course, "top", extra_open=extra_open)
    resp.status_code = status
    return resp


def _scope_ref(parent_id):
    return "top" if parent_id is None else parent_id


def _redirect_to_builder(course, q=""):
    """The ONLY places allowed to emit the open=session sentinel.

    `q` is passed IN, not read from the request: this helper has EIGHT
    callers, and element_move/element_delete are excluded from the q rule by
    the parent spec. Reading `request` here would silently extend the rule to
    two editor-originated redirects nobody asked to change.
    """
    url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
    params = {"open": "session"}
    if q:
        params["q"] = q
    return redirect(f"{url}?{urlencode(params)}")


def _persist_chain(request, course, node):
    """Union a created/moved node's chain into the no-JS carrier.

    The CHAIN, not the bare pk: if builder_open happens to be missing, a bare
    [new_pk] is non-empty, so the open=session read would NOT fall through and
    the tree would render with every ancestor collapsed -- hiding the node the
    author just created.
    """
    cmap = _children_map(course)
    # `or []` is fine HERE and nowhere else: we are about to union a chain in,
    # so a stored-empty and a missing key both mean "start from nothing". The
    # deliberate consequence is that a mutation re-opens the chain over an
    # author's fully-collapsed state -- correct, since the node they just
    # created must be visible.
    stored = request.session.get(OPEN_KEY, {}).get(course.slug) or []
    chain = _ancestor_chain(node) & container_pks(cmap)
    merged = set(stored) | chain
    # Same payload cap as _remember_open -- this writer unions and never
    # trims, so without it repeated no-JS adds/moves push one slug's list well
    # past the budget. Keep the NEW chain preferentially.
    capped = sorted(chain) + sorted(merged - chain)
    remember_node(
        request,
        course.slug,
        sorted(capped[: builder_open.SESSION_OPEN_LIMIT]),
        key=OPEN_KEY,
    )


FORCE_KEY = "builder_force"


def _stash_builder_force(request, slug, node):
    """Stash a created/moved node's chain for EXACTLY the next page render.

    extra_open exists only on FRAGMENT renders, but a no-JS add, duplicate or
    reparent REDIRECTS -- and the following page GET re-derives the restricted
    map from `q` alone, knows nothing of the new pk, and that node's title
    will rarely match. The author would land on a filtered tree with their new
    node ABSENT, indistinguishable from failure, on the path with the least
    feedback.

    Stores a sorted list[int]: no SESSION_SERIALIZER is configured, so
    Django 5.2 uses JSONSerializer and a set raises
    "TypeError: Object of type set is not JSON serializable".

    Stores the UNFILTERED chain -- do NOT copy _persist_chain's
    `& container_pks(cmap)` intersection. That one deliberately drops a unit's
    own pk because it feeds the OPEN set; this one feeds extra_open, whose
    effect 2 applies to every pk regardless of kind. Copying the intersection
    makes a no-JS unit add under a filter return a tree without the row the
    author just created.
    """
    remember_node(
        request,
        slug,
        sorted(_ancestor_chain(node))[: builder_open.SESSION_OPEN_LIMIT],
        key=FORCE_KEY,
    )


def _take_builder_force(request, slug):
    """Read and CLEAR. builder() is the sole reader and the sole clearer:
    _builder_with_notice follows a FAILED mutation, so there is nothing
    created to force-include, and letting it read would leave the clear site
    undefined."""
    store = request.session.get(FORCE_KEY) or {}
    pks = tuple(store.pop(slug, ()))
    if pks:
        request.session[FORCE_KEY] = store
        request.session.modified = True
    return pks


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
        _persist_chain(request, course, node)
        _stash_builder_force(request, course.slug, node)
        return _redirect_to_builder(course, _raw_q(request))
    # top-level add touches the top scope -> whole tree pane; nested add -> that scope
    if node.parent_id is None:
        return _render_tree(request, course, extra_open=_ancestor_chain(node))
    return _render_scope(
        request, course, _scope_ref(node.parent_id), extra_open=_ancestor_chain(node)
    )


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
        return _redirect_to_builder(course, _raw_q(request))
    # a unit-settings change re-renders the unit panel
    if is_settings and node.kind == ContentNode.Kind.UNIT:
        return _render_unit_panel(request, node)
    # A plain rename now has exactly one fragment caller: a builder tree row. It changes
    # no structure, so it returns the new title + token for that row and builder.js
    # patches in place -- re-rendering the scope would destroy the focused input.
    return render(request, "courses/manage/_rename_result.html", {"node": node})


@login_required
def node_move(request, slug):
    course = _require_manage(request, slug)
    mode = request.POST.get("mode")
    if mode == "reorder":
        # Every position-based op computes against the FULL sibling list while
        # a filtered scope renders a SUBSET (spec 3m): reorder_node swaps
        # full-list neighbours, so "Move down" mutates the course with NO
        # visible change and the author clicks again, and again.
        #
        # is_active, not `request.POST.get("q")`: this branch runs before any
        # children-map is loaded, so no FilterContext exists -- and a
        # truthiness gate would refuse under a below-floor ?q=a, where the
        # tree renders unfiltered and the arrows render ENABLED.
        #
        # Scoped to mode=="reorder" ONLY. A drop posts mode=reparent with a
        # position, indistinguishable from the Move picker's form -- and the
        # picker's slot indices are computed against the FULL child list, so
        # they are correct by construction. Widening this guard would break
        # the one route left for moving while filtered.
        if builder_filter.is_active(_raw_q(request)):
            msg = _("Clear the filter to reorder.")
            if not _wants_fragment(request):
                return _builder_with_notice(request, course, msg, status=422)
            return render(
                request, "courses/manage/_op_error.html", {"message": msg}, status=422
            )
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
            return _redirect_to_builder(course, _raw_q(request))
        if node.parent_id is None:
            return _render_tree(request, course)
        return _render_scope(request, course, _scope_ref(node.parent_id))
    elif mode == "reparent":
        position = request.POST.get("position")
        position = int(position) if position not in (None, "") else None
        try:
            node, _old = builder_svc.reparent_node(
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
            _persist_chain(request, course, node)
            _stash_builder_force(request, course.slug, node)
            return _redirect_to_builder(course, _raw_q(request))
        return _render_tree(
            request, course, extra_open=_ancestor_chain(node)
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
            "inbound_links": count_inbound_links(course, node),
        }
        return render(
            request,
            "courses/manage/node_confirm_delete.html",
            {
                "course": course,
                "node": node,
                "counts": counts,
                "open_present": "open" in request.GET,
                "open": request.GET.get("open", ""),
                "q": _raw_q(request),
            },
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
        if "open" in request.POST:
            url = reverse("courses:manage_builder", kwargs={"slug": course.slug})
            params = {"open": request.POST["open"]}
            q = _raw_q(request)
            if q:
                params["q"] = q
            return redirect(f"{url}?{urlencode(params)}")
        return _redirect_to_builder(course, _raw_q(request))
    if parent_id is None:
        return _render_tree(request, course)
    return _render_scope(request, course, _scope_ref(parent_id))


@login_required
def node_duplicate(request, slug):
    course = _require_manage(request, slug)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    try:
        node_pk = int(request.POST.get("node"))
    except (TypeError, ValueError):
        raise Http404("Missing or invalid node parameter.") from None
    node = get_node_or_404(node_pk, slug)
    if node.kind != "unit":
        raise Http404("Only units can be duplicated.")
    try:
        new_node = builder_svc.duplicate_unit(
            course, node_pk, token=request.POST.get("token")
        )
    except builder_svc.ConflictError:
        if not _wants_fragment(request):
            return _builder_with_notice(
                request,
                course,
                _("This changed elsewhere — reloaded to the latest."),
                status=409,
            )
        return _conflict_scope(request, course, node_pk)
    except TransferError as exc:
        msg = str(exc)
        if not _wants_fragment(request):
            return _builder_with_notice(request, course, msg, status=422)
        return render(
            request, "courses/manage/_op_error.html", {"message": msg}, status=422
        )
    if not _wants_fragment(request):
        _persist_chain(request, course, new_node)
        _stash_builder_force(request, course.slug, new_node)
        return _redirect_to_builder(course, _raw_q(request))
    if new_node.parent_id is None:
        return _render_tree(request, course, extra_open=_ancestor_chain(new_node))
    return _render_scope(
        request,
        course,
        _scope_ref(new_node.parent_id),
        extra_open=_ancestor_chain(new_node),
    )


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _builder_with_notice(request, course, message, status):
    """No-JS error response: re-render the WHOLE builder page with a notice (spec
    §No-JS fallback: 'stale token re-renders the full builder page with the notice')."""
    cmap = _children_map(course)
    fc = _filter_context(request, course, cmap, mode="notice")
    context = {
        "course": course,
        "children_map": fc.restricted,
        "top_nodes": fc.restricted.get(None, []),
        "notice": message,
        "info": _info_entries(
            fc.opened, q_active=fc.q_active, shown=fc.shown, total=fc.total
        ),
    }
    context.update(
        _tree_context(
            course,
            cmap,  # the FULL map, always
            fc.open_ids,
            q=fc.q_raw,
            filtered=fc.q_active,
            expand_all_disabled=_expand_all_disabled(cmap),
            q_min=builder_filter.MIN_QUERY,
        )
    )
    return render(request, "courses/manage/builder.html", context, status=status)


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
            # children_map/nodes_top stay the FULL map: this is a DESTINATION
            # chooser, and the numeric `position` field indexes into these
            # slot lists. A restricted map would both compute positions
            # against a filtered child list and leave a filtered author unable
            # to move anything OUT of the match set.
            "children_map": cmap,
            "nodes_top": cmap.get(None, []),
            "q": _raw_q(request),
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
        return _redirect_to_builder(course)
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
        return _redirect_to_builder(course)
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
# Twin of courses.rollups._current_ancestors, which serves the STUDENT breadcrumb.
# Deliberately separate: that one reads an already-materialised outline tree for free,
# this one walks node.parent because the builder has no such tree. Keep both.
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
            # The nesting cap the row/add-menu depth guards compare against. Read as a
            # MODULE ATTRIBUTE, never `from courses.builder import MAX_NEST_DEPTH` — a
            # from-import freezes the value at import time and the cap-agreement tests
            # would then fail against a correct implementation. Must be set HERE as
            # well as in _editor_page: every add/save/move/delete returns through this
            # renderer, so if the key landed only on the page path the first load would
            # look perfect and every later fragment swap would silently drop both the
            # nested add-menu and its container cards.
            "max_nest_depth": builder_svc.MAX_NEST_DEPTH,
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
            # nesting cap for the depth guards — module attribute, see the matching
            # comment in _render_editor_fragments.
            "max_nest_depth": builder_svc.MAX_NEST_DEPTH,
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
    "twocolumn": gettext_lazy("Columns"),
    "slidebreak": gettext_lazy("Slide break"),
    "revealgate": gettext_lazy("Show more"),
    "spoiler": gettext_lazy("Spoiler"),
    "fillgate": gettext_lazy("Fill in & confirm"),
    "switchgate": gettext_lazy("Choose & confirm"),
    "switchgrid": gettext_lazy("Switch grid"),
    "filltable": gettext_lazy("Fill-in table"),
    "callout": gettext_lazy("Callout"),
    "stepper": gettext_lazy("Step-by-step"),
    "markdone": gettext_lazy("Checklist"),
    "guessnumber": gettext_lazy("Guess the number"),
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
    elif type_key == "markdone" and formset is None:
        from courses.element_forms import build_markdone_formset

        instance = form.instance if form.instance.pk else None
        formset = build_markdone_formset(instance=instance)
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
        "twocolumn",
        "revealgate",
        "fillgate",
        "switchgate",
        "switchgrid",
        "filltable",
        "spoiler",
        "callout",
        "stepper",
        "markdone",
        "guessnumber",
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
    # exercise the nesting gate. "choicequestion" is the case here that reliably
    # reaches resolve_scope and proves nesting is blocked: it is not in
    # NESTABLE_TYPE_KEYS, so clause 1 rejects it as a nested child at any depth.
    # "tabs" also reaches resolve_scope, but as a nestable container (depth-3 slice)
    # it is accepted or rejected depending on depth -- clauses 3/4 -- not a fixed
    # block.
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
        "twocolumn",
        "slidebreak",
        "revealgate",
        "fillgate",
        "switchgate",
        "switchgrid",
        "filltable",
        "spoiler",
        "callout",
        "stepper",
        "markdone",
        "guessnumber",
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
        from courses.quiz import selected_ids

        result = question.mark(answer)  # NOTHING is persisted
        if isinstance(question, ChoiceQuestionElement):
            selected = selected_ids(answer)
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
    from courses.quiz import ephemeral_quiz_feedback
    from courses.quiz import parse_attempt
    from courses.quiz import quiz_feedback_context

    attempt = parse_attempt(request.POST)
    stand_in, result, validation = ephemeral_quiz_feedback(question, answer, attempt)
    ctx = quiz_feedback_context(
        question, stand_in, result=result, validation=validation
    )
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
