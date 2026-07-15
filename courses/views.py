import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.db.models import prefetch_related_objects
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses import quiz as quiz_svc
from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.access import is_enrolled
from courses.constants import COURSE_LANGUAGES
from courses.htmlsandbox import has_math_delimiters
from courses.marking import MarkResult  # noqa: F401  (documents the return type)
from courses.marking import blank_matches
from courses.models import Attempt  # noqa: F401
from courses.models import CalloutElement
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import HtmlElement
from courses.models import MarkDoneElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import MultiGridQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import StepperElement
from courses.models import Subject
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TextElement
from courses.models import UnitProgress
from courses.quiz import answer_from_json
from courses.quiz import answer_is_empty  # noqa: F401
from courses.quiz import answer_to_json  # noqa: F401
from courses.quiz import quiz_feedback_context
from courses.quiz import rehydrate  # noqa: F401
from courses.rollups import build_course_results
from courses.rollups import build_outline
from courses.rollups import build_unit_nav
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from courses.slideshow import partition_into_slides


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _question_has_math(q):
    """True if a question carries inline math in its stem or any of its parts —
    used to decide whether a consumption/results page must load KaTeX."""
    if has_math_delimiters(q.stem):
        return True
    if isinstance(q, ChoiceQuestionElement):
        return any(
            has_math_delimiters(c.text) or has_math_delimiters(c.feedback)
            for c in q.choices.all()
        )
    if isinstance(q, FillBlankQuestionElement):
        return any(has_math_delimiters(b.accepted) for b in q.blanks.all())
    if isinstance(q, DragFillBlankQuestionElement):
        return has_math_delimiters(q.distractors) or any(
            has_math_delimiters(b.correct_token) for b in q.dragblanks.all()
        )
    if isinstance(q, MatchPairQuestionElement):
        return has_math_delimiters(q.distractors) or any(
            has_math_delimiters(p.left) or has_math_delimiters(p.right)
            for p in q.pairs.all()
        )
    if isinstance(q, DragToImageQuestionElement):
        return has_math_delimiters(q.distractors) or any(
            has_math_delimiters(z.correct_label) for z in q.zones.all()
        )
    if isinstance(q, ChoiceGridQuestionElement):
        return any(has_math_delimiters(c.label) for c in q.columns.all()) or any(
            has_math_delimiters(r.statement) for r in q.rows.all()
        )
    if isinstance(q, MultiGridQuestionElement):
        return any(has_math_delimiters(c.label) for c in q.columns.all()) or any(
            has_math_delimiters(r.statement) for r in q.rows.all()
        )
    return False


def _table_has_math(el):
    from courses.models import TableElement

    if not isinstance(el, TableElement):
        return False
    data = el.normalize_data(el.data)
    return any(
        has_math_delimiters(cell.get("html", ""))
        for row in data["cells"]
        for cell in row
    )


def _fill_table_has_math(obj):
    """Math detection for a FillTableElement: any STATIC cell (never an answer cell —
    the accepted answer never reaches the client, so it can't drive KaTeX) carrying
    inline math delimiters is enough to arm KaTeX for the lesson."""
    if not isinstance(obj, FillTableElement):
        return False
    data = obj.normalize_data(obj.data)
    return any(
        cell.get("kind") != "answer" and has_math_delimiters(cell.get("html", ""))
        for row in data["cells"]
        for cell in row
    )


def _gallery_has_math(el):
    from courses.models import GalleryElement

    if not isinstance(el, GalleryElement):
        return False
    data = el.normalize_data(el.data)
    return any(has_math_delimiters(img.get("desc", "")) for img in data["images"])


def _switch_grid_has_math(obj):
    """Math detection for a SwitchGridElement: any line's stem or any cycler option
    carrying inline math delimiters is enough to arm KaTeX for the lesson."""
    for line in obj.lines or []:
        if has_math_delimiters(line.get("stem", "")):
            return True
        for cyc in line.get("cyclers", []) or []:
            if any(has_math_delimiters(o) for o in (cyc.get("options") or [])):
                return True
    return False


def _element_has_math(obj):
    """Per-type math detection for ONE concrete element. The SINGLE source of truth
    for "does this element carry math?", covering every top-level-capable type so the
    lesson/quiz context builders and the tabs recursion all agree -- adding a new
    math-bearing element type means adding exactly one clause here, not touching three
    inlined chains. A nested gallery description or table cell is found the same way a
    top-level one is.

    The trailing helpers (`_table_has_math`/`_gallery_has_math`/`_tabs_has_math`/
    `_fill_table_has_math`) each self-guard with their own isinstance check and return
    False for a non-matching type, so the final fallback dispatches those four kinds
    without an explicit isinstance ladder here."""
    if isinstance(obj, MathElement):
        return True
    if isinstance(obj, TextElement):
        return has_math_delimiters(obj.body)
    if isinstance(obj, QuestionElement):
        return _question_has_math(obj)
    if isinstance(obj, FillGateElement):
        return has_math_delimiters(obj.stem)
    if isinstance(obj, SwitchGateElement):
        return has_math_delimiters(obj.stem) or any(
            has_math_delimiters(o) for o in (obj.options or [])
        )
    if isinstance(obj, SpoilerElement):
        return has_math_delimiters(obj.body)
    if isinstance(obj, CalloutElement):
        return has_math_delimiters(obj.body)
    if isinstance(obj, SwitchGridElement):
        return _switch_grid_has_math(obj)
    if isinstance(obj, StepperElement):
        return has_math_delimiters(obj.prompt) or any(
            has_math_delimiters(s.content) for s in obj.steps.all()
        )
    return (
        _table_has_math(obj)
        or _gallery_has_math(obj)
        or _tabs_has_math(obj)
        or _fill_table_has_math(obj)
        or _twocolumn_has_math(obj)
    )


def _tabs_has_math(el):
    """COLLECT + MUST RECURSE. `has_math` consumes the element list AFTER the RENDER
    filter has removed nested children, so it has to walk into them itself. Dispatches
    each child through _element_has_math -- an isinstance(child, MathElement) shortcut
    would pass a bare-MathElement test while silently missing math inside a nested
    gallery description or table cell."""
    from courses.models import TabsElement

    if not isinstance(el, TabsElement):
        return False
    join = el.join_row()
    if join is None:
        return False
    return any(
        _element_has_math(child.content_object)
        for child in join.children.prefetch_related("content_object")
    )


def _twocolumn_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. has_math consumes the element
    list AFTER the render filter strips nested children, so it walks into them here."""
    from courses.models import TwoColumnElement

    if not isinstance(el, TwoColumnElement):
        return False
    join = el.join_row()
    if join is None:
        return False
    return any(
        _element_has_math(child.content_object)
        for child in join.children.prefetch_related("content_object")
    )


def build_lesson_context(node, user):
    """Shared element/has_*/progress context for a LESSON unit. Used by both
    lesson_unit (GET) and check_answer (POST re-render) so the two cannot drift.
    Performs the same UnitProgress.get_or_create + seen-count as a normal view."""
    # RENDER: children render inside their tabs, not as top-level siblings.
    elements = list(
        node.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    dragimage_qs = [q for q in questions if isinstance(q, DragToImageQuestionElement)]
    choicegrid_qs = [q for q in questions if isinstance(q, ChoiceGridQuestionElement)]
    multigrid_qs = [q for q in questions if isinstance(q, MultiGridQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
    if dragimage_qs:
        prefetch_related_objects(dragimage_qs, "zones")
    if choicegrid_qs:
        prefetch_related_objects(choicegrid_qs, "columns", "rows")
    if multigrid_qs:
        prefetch_related_objects(
            multigrid_qs, "columns", "rows", "rows__correct_columns"
        )
    # ACCEPTED LIMITATION: `elements` is scoped to parent__isnull=True, so a tab-/
    # column-nested checklist's items aren't in this prefetch (bounded per-item N+1 on
    # the nested render path only; correctness unaffected, items <= 20).
    markdone_els = [
        e.content_object
        for e in elements
        if e.content_object.__class__.__name__ == "MarkDoneElement"
    ]
    if markdone_els:
        prefetch_related_objects(markdone_els, "items")

    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    question_models = [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        FillBlankQuestionElement,
        DragFillBlankQuestionElement,
        MatchPairQuestionElement,
        DragToImageQuestionElement,
        ChoiceGridQuestionElement,
        MultiGridQuestionElement,
        ExtendedResponseQuestionElement,
    ]
    question_ct_ids = {ContentType.objects.get_for_model(m).id for m in question_models}

    # Single source of truth: _element_has_math() knows every type. (Previously this
    # was a ~12-clause inlined OR-chain duplicated between here and build_quiz_context.)
    has_math = any(_element_has_math(el.content_object) for el in elements)
    has_html = any(el.content_type_id == html_ct_id for el in elements)
    has_questions = any(el.content_type_id in question_ct_ids for el in elements)
    # Flat query (NOT scoped to parent__isnull=True) so a gate nested inside a tab —
    # children keep their own `unit` FK — is still detected. Both gate types arm the
    # pre-hide + reveal.js; only fill-gates need fillgate.js.
    has_reveal_gate = node.elements.filter(
        content_type__model__in=[
            "revealgateelement",
            "fillgateelement",
            "switchgateelement",
        ]
    ).exists()
    has_fill_gate = node.elements.filter(content_type__model="fillgateelement").exists()
    has_switch_gate = node.elements.filter(
        content_type__model="switchgateelement"
    ).exists()
    has_switch_grid = node.elements.filter(
        content_type__model="switchgridelement"
    ).exists()
    has_fill_table = node.elements.filter(
        content_type__model="filltableelement"
    ).exists()
    has_stepper = node.elements.filter(content_type__model="stepperelement").exists()
    has_markdone = node.elements.filter(content_type__model="markdoneelement").exists()

    progress = None
    seen_ids = set()
    checklist = {}
    if is_enrolled(user, node.course):
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
        # int-keyed {content_pk: {item_pk, ...}} — render seam looks up by el.pk.
        checklist = {
            int(k): {int(v) for v in vals}
            for k, vals in (progress.checklist_state or {}).items()
        }
    # Slide-break join-rows are never "seen" (mirrors the `seen` view's exclusion) —
    # without this, element_count could never equal seen_count for a lesson with a
    # break.
    break_ct_id = ContentType.objects.get_for_model(SlideBreakElement).id
    current_ids = [el.pk for el in elements if el.content_type_id != break_ct_id]
    seen_count = len(seen_ids.intersection(current_ids))
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": False,
        "elements": elements,
        "slides": partition_into_slides(elements),
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": has_questions,
        "has_reveal_gate": has_reveal_gate,
        "has_fill_gate": has_fill_gate,
        "has_switch_gate": has_switch_gate,
        "has_switch_grid": has_switch_grid,
        "has_fill_table": has_fill_table,
        "has_stepper": has_stepper,
        "has_markdone": has_markdone,
        "checklist": checklist,
        "slug": node.course.slug,
        "node_pk": node.pk,
        "submitted_values": None,
        "progress": progress,
        "element_count": len(current_ids),
        "seen_count": seen_count,
    }


def full_lesson_render_context(node, user, *, notes_show=False, tags_panel=False):
    """Full context for rendering courses/lesson_unit.html: lesson context +
    unit nav + feedback defaults + the author's notes + tag panel. Single-sourced so
    every render site (lesson_unit GET, check_answer re-render, notes no-JS re-render)
    stays consistent."""
    from notes.rendering import lesson_notes_context  # lazy: avoid import cycle
    from tags.rendering import unit_tags_context

    ctx = build_lesson_context(node, user)
    ctx["unit_nav"] = build_unit_nav(node.course, user, node)
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    )
    ctx.update(lesson_notes_context(user, node, show=notes_show))
    ctx.update(unit_tags_context(user, node, panel_open=tags_panel))
    return ctx


@login_required
def my_courses(request):
    courses = Course.objects.filter(enrollments__student=request.user).order_by("title")
    return render(request, "courses/my_courses.html", {"courses": courses})


@login_required
def course_outline(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    from notes.services import note_counts_for_outline  # lazy: avoid cycle
    from tags import services as tag_services

    outline = build_outline(course, request.user)
    tags_by_unit, course_tags = tag_services.tags_for_outline(request.user, course)
    course_tag_ids = {t.pk for t in course_tags}
    active_tag_ids = [
        int(x)
        for x in request.GET.getlist("tags")
        if x.isdigit() and int(x) in course_tag_ids
    ]
    tag_services.outline_with_tags(outline, tags_by_unit, active_tag_ids)
    base = reverse("courses:course_outline", kwargs={"slug": course.slug})
    return render(
        request,
        "courses/outline.html",
        {
            "course": course,
            "outline": outline,
            "note_counts": note_counts_for_outline(request.user, course),
            "active_tag_ids": active_tag_ids,
            "filter_chips": tag_services.filter_chip_hrefs(
                base, course_tags, active_tag_ids
            ),
        },
    )


@login_required
def course_results(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    # student is always request.user — no IDOR surface. `course` is passed
    # top-level as the template's canonical source (summary also carries it).
    summary = build_course_results(course, request.user)
    return render(
        request,
        "courses/course_results.html",
        {"course": course, "summary": summary},
    )


@login_required
def lesson_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if node.unit_type == ContentNode.UnitType.QUIZ:
        return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
    ctx = full_lesson_render_context(
        node,
        request.user,
        notes_show=bool(request.GET.get("notes")),
        tags_panel=request.GET.get("panel") == "tags",
    )
    return render(request, "courses/lesson_unit.html", ctx)


def _progress_json(progress):
    return {
        "seen_element_ids": list(progress.seen_element_ids),
        "completed": progress.completed,
        "completed_at": progress.completed_at.isoformat()
        if progress.completed_at
        else None,
    }


def _seen_current_ids(node):
    """Element pks a student must see to complete `node`. Excludes slide breaks
    (never "seen") and nested children: the frontend only reports
    .lesson-block[data-element-id] ids, which _lesson_article.html emits for
    top-level elements only. A nested pk here could never be satisfied, so the
    unit would never complete."""
    break_ct = ContentType.objects.get_for_model(SlideBreakElement)
    return set(
        node.elements.filter(parent__isnull=True)
        .exclude(content_type=break_ct)
        .values_list("pk", flat=True)
    )


@require_POST
@login_required
def seen(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    try:
        data = json.loads(request.body or b"[]")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid JSON")
    if not isinstance(data, list):
        return HttpResponseBadRequest("expected a JSON array")
    if not is_enrolled(request.user, course):
        # untracked preview: no write, synthetic canonical response
        return JsonResponse(
            {"seen_element_ids": [], "completed": False, "completed_at": None}
        )
    current = _seen_current_ids(node)
    incoming = {
        x
        for x in data
        if isinstance(x, int) and not isinstance(x, bool) and x in current
    }
    progress, _ = UnitProgress.objects.get_or_create(student=request.user, unit=node)
    merged = set(progress.seen_element_ids) | incoming
    progress.seen_element_ids = sorted(merged)
    if not progress.completed and current and current.issubset(merged):
        progress.completed = True  # completed_at stamped in save()
    progress.save()
    return JsonResponse(_progress_json(progress))


@require_POST
@login_required
def complete(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if is_enrolled(request.user, course):
        progress, _ = UnitProgress.objects.get_or_create(
            student=request.user, unit=node
        )
        if not progress.completed:
            progress.completed = True
            progress.save()
    return redirect("courses:lesson_unit", slug=slug, node_pk=node_pk)


@require_POST
@login_required
def markdone_save(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied

    is_json = request.content_type == "application/json"
    if is_json:
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid JSON")
        if not isinstance(data, dict):
            return HttpResponseBadRequest("expected an object")
        raw_element = data.get("element")
        raw_items = data.get("items")
    else:
        raw_element = request.POST.get("element")
        raw_items = request.POST.getlist("item")

    try:
        element_pk = int(raw_element)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad element")

    if not isinstance(raw_items, list):
        raw_items = []
    incoming = set()
    for x in raw_items:
        try:
            incoming.add(int(x))
        except (TypeError, ValueError):
            continue  # skip garbage item, never 500

    # Ownership: element must be a MarkDoneElement in THIS unit (covers nested).
    element = MarkDoneElement.objects.filter(pk=element_pk, elements__unit=node).first()
    if element is None:
        return HttpResponseBadRequest("unknown element")
    valid = set(element.items.values_list("pk", flat=True))
    checked = sorted(incoming & valid)

    def _resp():
        if is_json:
            return JsonResponse({"element": element.pk, "items": checked})
        return redirect(
            reverse("courses:lesson_unit", args=[slug, node_pk])
            + f"#markdone-{element.pk}"
        )

    if not is_enrolled(request.user, course):
        # previewer: no write, synthetic response
        if is_json:
            return JsonResponse({"element": element.pk, "items": []})
        return redirect(
            reverse("courses:lesson_unit", args=[slug, node_pk])
            + f"#markdone-{element.pk}"
        )

    with transaction.atomic():
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        if checked:
            progress.checklist_state[str(element.pk)] = checked
        else:
            progress.checklist_state.pop(str(element.pk), None)
        progress.save()
    return _resp()


@require_POST
@login_required
def check_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    answer = question.build_answer(request.POST)
    result = question.mark(answer)  # NOTHING is persisted

    if _wants_fragment(request):
        if isinstance(question, ChoiceQuestionElement):
            # Choice: return the full re-rendered element so inline per-option feedback
            # lands in the choices list (question.js swaps the form body). render() sets
            # reveal_template=None for lesson mode -> no duplicate bottom reveal list.
            selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
            return HttpResponse(
                question.render(
                    element=element,
                    mode="lesson",
                    selected_ids=selected,
                    mark_result=result,
                    feedback_for_pk=element.pk,
                )
            )
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    ctx = full_lesson_render_context(node, request.user)
    selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)


@require_POST
@login_required
def fillgate_check(request, element_pk):
    """Server-side check for a Fill-in-&-confirm gate. Reports correctness only —
    NOTHING is persisted. Flat route (no slug/node_pk): the course is derived from
    the element's join row for the access gate."""
    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk
    )
    # Access check FIRST (before the type 404), so a user without course access
    # cannot distinguish a fill-gate from a non-fill-gate id by probing pks.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    concrete = element.content_object
    if not isinstance(concrete, FillGateElement):
        raise Http404("not a fill-gate element")
    answers = concrete.answers or []
    n = len(answers)
    values = (request.POST.getlist("blank") + [""] * n)[:n]
    results = [blank_matches(values[i], answers[i]) for i in range(n)]
    return JsonResponse({"correct": bool(results) and all(results), "blanks": results})


@require_POST
@login_required
def switchgate_check(request, element_pk):
    """Server-side check for a Choose & confirm gate. Reports correctness only —
    NOTHING is persisted. Soft pk lookup: a missing or wrong-type pk is a 200
    {"correct": false}, NOT a 404 (deliberate deviation from fillgate_check's
    get_object_or_404)."""
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, SwitchGateElement):
        return JsonResponse({"correct": False})
    # Resolved element: apply the same access check fillgate_check uses.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    try:
        choice = int(request.POST.get("choice", ""))
    except (TypeError, ValueError):
        return JsonResponse({"correct": False})
    return JsonResponse({"correct": choice == concrete.answer})


@require_POST
@login_required
def switchgrid_check(request, element_pk):
    """Server-side check for a Switch grid self-check. Reports per-cycler and overall
    correctness only — NOTHING is persisted. Soft pk lookup (switchgate parity):
    a missing/wrong-type pk is a 200 {"correct": False, "cells": []}, not 404."""
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, SwitchGridElement):
        return JsonResponse({"correct": False, "cells": []})
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied

    try:
        indices = json.loads(request.POST.get("indices", ""))
    except (TypeError, ValueError):
        return JsonResponse({"correct": False, "cells": []})
    if not isinstance(indices, list):
        return JsonResponse({"correct": False, "cells": []})

    cells = []
    all_correct = True
    for i, line in enumerate(concrete.lines or []):
        row = []
        sub = indices[i] if (i < len(indices) and isinstance(indices[i], list)) else []
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            submitted = sub[j] if (j < len(sub) and isinstance(sub[j], int)) else None
            ok = submitted == cyc.get("answer")
            row.append(ok)
            all_correct = all_correct and ok
        cells.append(row)
    return JsonResponse({"correct": all_correct, "cells": cells})


@require_POST
@login_required
def filltable_check(request, element_pk):
    """Server-side self-check for a Fill-in table. Per-cell correctness only —
    NOTHING is persisted, no marks. Soft pk lookup (a missing/wrong-type pk is a
    200 empty-set body, not 404) BEFORE any access dereference, mirroring
    switchgrid_check. Response shape deliberately differs: flat r/c dicts + a
    top-level `all_correct` (not switchgrid's nested `correct`)."""
    from courses.filltable import answer_cells
    from courses.filltable import split_alternatives

    empty = {"cells": [], "all_correct": False}
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, FillTableElement):
        return JsonResponse(empty)
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    nd = concrete.normalize_data(concrete.data)
    case_sensitive = nd["case_sensitive"]
    cells = []
    all_correct = True
    for r, c, answer in answer_cells(nd["cells"]):
        got = request.POST.get(f"r{r}c{c}", "")
        alts = split_alternatives(answer)
        ok = blank_matches(got, alts, case_sensitive=case_sensitive)
        cells.append({"r": r, "c": c, "correct": ok})
        all_correct = all_correct and ok
    if not cells:
        return JsonResponse(empty)  # zero answer cells: never a vacuous True
    return JsonResponse({"cells": cells, "all_correct": all_correct})


def _stored_result(question, response):
    # MarkResult + answer_from_json imported at views.py top.
    m = question.mark(answer_from_json(question, response.latest_answer))
    return MarkResult(
        correct=(response.fraction == Decimal("1.0000")),
        fraction=float(response.fraction or 0),
        reveal=m.reveal,
        annotated=m.annotated,
    )


def build_quiz_context(node, user):
    """Element/render context for a QUIZ unit. Parallels build_lesson_context but
    threads per-question quiz state (responses, locked, attempts_left)."""
    # RENDER: children render inside their tabs, not as top-level siblings.
    elements = list(
        node.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    # Mirror build_lesson_context: the GFK prefetch does NOT fetch choices/blanks,
    # so prefetch them explicitly (avoids N+1 in render/scoring/results).
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    dragimage_qs = [q for q in questions if isinstance(q, DragToImageQuestionElement)]
    choicegrid_qs = [q for q in questions if isinstance(q, ChoiceGridQuestionElement)]
    multigrid_qs = [q for q in questions if isinstance(q, MultiGridQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
    if dragimage_qs:
        prefetch_related_objects(dragimage_qs, "zones")
    if choicegrid_qs:
        prefetch_related_objects(choicegrid_qs, "columns", "rows")
    if multigrid_qs:
        prefetch_related_objects(
            multigrid_qs, "columns", "rows", "rows__correct_columns"
        )

    submission = None
    if is_enrolled(user, node.course):
        submission, _ = QuizSubmission.objects.get_or_create(student=user, unit=node)
    quiz_submitted = bool(
        submission and submission.status == QuizSubmission.Status.SUBMITTED
    )

    responses = {}
    if submission is not None:
        responses = {r.element_id: r for r in submission.responses.all()}

    # Per-element render state. Task 8 (fresh quiz) leaves feedback_html empty for
    # every question; the no-JS answer path (Task 9) and resume (Task 12) fill it.
    # Also carries server-side question numbering (Task 5, slideshow-mode): a
    # 1-based counter over question join-rows in document order, contiguous
    # across slide breaks. Quiz-only — the lesson builder never sets qnum, so
    # lessons never number their questions.
    render_states = {}
    qnum = 0
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        qnum += 1
        r = responses.get(el.pk)
        state = {
            "qnum": qnum,
            "selected_ids": frozenset(),
            "submitted_values": None,
            "locked": bool(r.locked) if r else False,
            "attempts_left": None,
            "feedback_html": "",
        }
        if r is not None and r.attempt_count > 0:
            selected, submitted = rehydrate(q, r.latest_answer)
            state["selected_ids"] = selected
            state["submitted_values"] = submitted
            result = (
                _stored_result(q, r)
                if q.marking_mode == QuestionElement.MarkingMode.AUTO
                else None  # [N]/[R] -> neutral branch in quiz_feedback_context
            )
            fb_ctx = quiz_feedback_context(q, r, result=result)
            state["attempts_left"] = fb_ctx.get("attempts_left")
            state["feedback_html"] = render_to_string(
                "courses/elements/_quiz_question_feedback.html", fb_ctx
            )
        render_states[el.pk] = state

    # Over-inclusive vs build_lesson_context's precise per-stem detection: load
    # KaTeX whenever the quiz has any question (a question may carry math in its
    # stem/choices) regardless of whether _element_has_math would detect it. A few
    # KB of unused assets is an accepted tradeoff. The non-question types defer to
    # the shared _element_has_math() so this stays in lockstep with the lesson path.
    has_math = bool(questions) or any(
        _element_has_math(el.content_object) for el in elements
    )
    has_html = any(isinstance(el.content_object, HtmlElement) for el in elements)
    ctx = {
        "course": node.course,
        "unit": node,
        "is_quiz": True,
        "elements": elements,
        "slides": partition_into_slides(elements),
        "responses": responses,
        "render_states": render_states,
        "submission": submission,
        "quiz_submitted": quiz_submitted,
        # Inputs are disabled + Finish hidden when the quiz is submitted OR the
        # accessor is a non-enrolled previewer (submission is None) — a previewer
        # gets a READ-ONLY quiz, never live forms that 403 on submit.
        "read_only": quiz_submitted or submission is None,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": True,
    }
    from tags.rendering import unit_tags_context

    ctx.update(unit_tags_context(user, node, panel_open=False))
    return ctx


@login_required
def quiz_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    ctx = build_quiz_context(node, request.user)
    sub = ctx["submission"]
    if sub is not None and sub.status == QuizSubmission.Status.SUBMITTED:
        target = reverse(
            "courses:quiz_results", kwargs={"slug": slug, "node_pk": node_pk}
        )
        if request.GET.get("panel") == "tags":
            target += "?panel=tags"
        return redirect(target)
    ctx["unit_nav"] = build_unit_nav(course, request.user, node)
    ctx["tags_panel_open"] = request.GET.get("panel") == "tags"
    return render(request, "courses/quiz_unit.html", ctx)


# ---------------------------------------------------------------------------
# Quiz answer path (Task 9): per-question [A] submit, withhold state machine,
# concurrency locks, empty-answer guard, and no-leak invariant.
# ---------------------------------------------------------------------------


def _quiz_locked_response(request, slug, node_pk):
    if _wants_fragment(request):
        return HttpResponse(_("This quiz has already been submitted."), status=409)
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


def _quiz_render_feedback(
    request, node, element, question, response, *, result=None, validation=False
):
    fb_ctx = quiz_feedback_context(
        question, response, result=result, validation=validation
    )
    if _wants_fragment(request):
        return render(request, "courses/elements/_quiz_question_feedback.html", fb_ctx)
    # No-JS: full quiz_unit re-render. Inject THIS question's fragment into its
    # single feedback box (render_states[pk]["feedback_html"]) and rehydrate its
    # inputs — the same render path resume (Task 12) uses, so no double container.
    ctx = build_quiz_context(node, request.user)
    ctx["unit_nav"] = build_unit_nav(node.course, request.user, node)
    fragment = render_to_string("courses/elements/_quiz_question_feedback.html", fb_ctx)
    st = ctx["render_states"].get(element.pk)
    if st is not None:
        st["feedback_html"] = fragment
        selected, submitted = rehydrate(question, response.latest_answer)
        st["selected_ids"] = selected
        st["submitted_values"] = submitted
    return render(request, "courses/quiz_unit.html", ctx)


@require_POST
@login_required
def quiz_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied  # previewers cannot persist

    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    with transaction.atomic():
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=request.user, unit=node
        )
        if submission.status == QuizSubmission.Status.SUBMITTED:
            return _quiz_locked_response(request, slug, node_pk)

        response, _ = QuestionResponse.objects.select_for_update().get_or_create(
            submission=submission, element=element
        )
        if response.locked or (
            question.max_attempts is not None
            and response.attempt_count >= question.max_attempts
        ):
            return _quiz_locked_response(request, slug, node_pk)

        answer = question.build_answer(request.POST)
        if answer_is_empty(answer):
            # No attempt recorded. On the no-JS validation re-render the offending
            # question's inputs show its PRIOR latest_answer (if any) or blank on a
            # first attempt — there is nothing new to rehydrate. Intentional boundary.
            return _quiz_render_feedback(
                request, node, element, question, response, validation=True
            )

        is_auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
        result = None
        if is_auto:
            result = question.mark(answer)
            f = to_stored_fraction(result.fraction)
            response.fraction = f
            response.earned_marks = earned_marks(f, question.max_marks)
            attempt_fraction = f
            attempt_correct = result.correct
        else:
            attempt_fraction = None
            attempt_correct = None

        response.attempt_count += 1
        response.latest_answer = answer_to_json(answer)
        response.last_attempt_at = timezone.now()
        if is_auto:
            response.locked = bool(result.correct) or (
                question.max_attempts is not None
                and response.attempt_count >= question.max_attempts
            )
        else:
            response.locked = True  # [N]/[R]: single submission
        response.save()
        Attempt.objects.create(
            response=response,
            n=response.attempt_count,
            answer=response.latest_answer,
            fraction=attempt_fraction,
            correct=attempt_correct,
        )

    return _quiz_render_feedback(
        request, node, element, question, response, result=result
    )


@require_POST
@login_required
def quiz_finish(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied
    with transaction.atomic():
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=request.user, unit=node
        )
        if submission.status != QuizSubmission.Status.SUBMITTED:
            quiz_svc.finalize_submission(node, submission)
            progress, _ = UnitProgress.objects.get_or_create(
                student=request.user, unit=node
            )
            if not progress.completed:
                progress.completed = True
                progress.save()
            from notifications.services import notify_needs_review

            notify_needs_review(submission, actor=request.user)

            from integrations.services import emit_result_finalized

            emit_result_finalized(submission)
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


@login_required
def quiz_results(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    submission = QuizSubmission.objects.filter(
        student=request.user, unit=node, status=QuizSubmission.Status.SUBMITTED
    ).first()
    if submission is None:
        return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
    responses = {r.element_id: r for r in submission.responses.all()}
    rows = []
    pending_count = 0
    pending_marks = Decimal("0.00")
    has_math = False
    # One-time post-submit render; the per-question choices/blanks access in
    # _results_row is an accepted N+1 here (not worth a prefetch pass for 2c).
    for el in node.elements.order_by("order", "pk").prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            pending_count += 1
            pending_marks += q.max_marks
        if not has_math:
            has_math = _question_has_math(q)
        r = responses.get(el.pk)
        rows.append(_results_row(q, r))
    ctx = {
        "course": course,
        "unit": node,
        "submission": submission,
        "rows": rows,
        "pending_count": pending_count,
        "pending_marks": pending_marks,
        "has_math": has_math,
    }
    from tags.rendering import unit_tags_context

    ctx.update(
        unit_tags_context(
            request.user, node, panel_open=request.GET.get("panel") == "tags"
        )
    )
    return render(request, "courses/quiz_results.html", ctx)


def _results_row(question, response):
    """Outcome classification keyed on CURRENT marking_mode (stale fraction ignored
    for [N]). For [A], attach a `reveal_result` (a MarkResult whose `.reveal` is the
    correct-answer payload) + `choices`, so the per-type reveal partial renders the
    correct answer for EVERY [A] row — including unanswered ones (§3.4 'reveal all').
    Returns a dict the results template renders."""
    mode = question.marking_mode
    row = {
        "question": question,
        "response": response,
        "outcome": None,
        "earned": None,
        "possible": question.max_marks,
        "reveal_result": None,
        "reveal_template": None,
        "choices": None,
        "answered": response is not None and response.latest_answer is not None,
        "review_feedback": (response.review_feedback if response else ""),
        "review_earned": (response.earned_marks if response else None),
    }
    if mode == QuestionElement.MarkingMode.NOT_MARKED:
        row["outcome"] = "recorded" if response else "not_answered"
    elif mode == QuestionElement.MarkingMode.REVIEW:
        if response is not None and response.reviewed_at is not None:
            row["outcome"] = "reviewed"
            row["earned"] = response.earned_marks
        else:
            row["outcome"] = "review"
    else:  # [A]
        if response is None or response.fraction is None:
            row["outcome"] = "not_answered"
            row["earned"] = Decimal("0.00")
        else:
            earned = earned_marks(response.fraction, question.max_marks)
            row["earned"] = earned
            if earned == question.max_marks:
                row["outcome"] = "correct"
            elif earned > 0:
                row["outcome"] = "partial"
            else:
                row["outcome"] = "incorrect"
        # `reveal` is the correct-answer payload. Mark the STUDENT'S answer when one
        # exists so the per-blank ✓/✗ in _reveal_fillblank reflects what they entered
        # (marking an empty answer would show every blank wrong even when correct);
        # for an unanswered question, mark an empty answer (shows the correct answers,
        # all blanks ✗ — acceptable, it was not answered).
        if response is not None and response.latest_answer is not None:
            row["reveal_result"] = question.mark(
                answer_from_json(question, response.latest_answer)
            )
        else:
            row["reveal_result"] = question.mark(question.build_answer(QueryDict()))
        row["reveal_template"] = question.REVEAL_TEMPLATE
        if isinstance(question, ChoiceQuestionElement):
            row["choices"] = list(question.choices.all())
    return row


@login_required
def catalog(request):
    """Browse open courses the student may self-enroll in. Filters are GET params
    composed on the (unfiltered) eligible set; option lists derive from that
    unfiltered set so picking one filter never erases the others' options."""
    from grouping.services import catalog_courses_for

    eligible = catalog_courses_for(request.user)

    subjects = (
        Subject.objects.filter(courses__in=eligible.values("pk"))
        .distinct()
        .localized_order()
    )
    lang_labels = dict(COURSE_LANGUAGES)
    languages = [
        {"code": code, "label": lang_labels.get(code, code)}
        for code in eligible.values_list("language", flat=True).distinct()
    ]

    sel_subject = request.GET.get("subject") or ""
    sel_language = request.GET.get("language") or ""
    q = (request.GET.get("q") or "").strip()

    qs = eligible
    if sel_subject:
        qs = qs.filter(subjects__id=sel_subject).distinct()
    if sel_language:
        qs = qs.filter(language=sel_language)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(overview__icontains=q))
    qs = qs.order_by("title")
    qs = qs.prefetch_related("subjects")

    enrolled_ids = set(
        Enrollment.objects.filter(
            student=request.user, course__in=qs.values("pk")
        ).values_list("course_id", flat=True)
    )
    return render(
        request,
        "courses/catalog.html",
        {
            "courses": qs,
            "enrolled_ids": enrolled_ids,
            "subjects": subjects,
            "languages": languages,
            "sel_subject": sel_subject,
            "sel_language": sel_language,
            "q": q,
        },
    )


@login_required
def catalog_detail(request, slug):
    """Pre-enroll overview: modal fragment (XHR) or full-page fallback. Gated by
    can_self_enroll OR is_enrolled (NOT can_access_course). The body branches on
    is_enrolled so an already-enrolled user never sees an Enroll button."""
    from grouping.services import can_self_enroll

    course = get_object_or_404(Course, slug=slug)
    enrolled = is_enrolled(request.user, course)
    if not (enrolled or can_self_enroll(request.user, course)):
        raise Http404
    ctx = {
        "course": course,
        "enrolled": enrolled,
        "unit_count": course.nodes.filter(kind="unit").count(),
    }
    if _wants_fragment(request):
        return render(request, "courses/_catalog_detail.html", ctx)
    return render(request, "courses/catalog_detail.html", ctx)


@login_required
@require_POST
def self_enroll(request, slug):
    """Self-enroll the student in an open course. Re-checks eligibility server-side
    (the button is never trusted); ineligible -> 404. Calls the enroll_self service."""
    from grouping.services import can_self_enroll
    from grouping.services import enroll_self

    course = get_object_or_404(Course, slug=slug)
    if not can_self_enroll(request.user, course):
        raise Http404
    enroll_self(request.user, course)
    messages.success(
        request, _("You're now enrolled in %(course)s.") % {"course": course.title}
    )
    return redirect("courses:course_outline", slug=course.slug)
