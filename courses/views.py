import json

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db.models import prefetch_related_objects
from django.http import Http404
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.access import is_enrolled
from courses.htmlsandbox import has_math_delimiters
from courses.marking import MarkResult  # noqa: F401  (documents the return type)
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import HtmlElement
from courses.models import MathElement
from courses.models import QuestionElement
from courses.models import UnitProgress
from courses.rollups import build_outline


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def build_lesson_context(node, user):
    """Shared element/has_*/progress context for a LESSON unit. Used by both
    lesson_unit (GET) and check_answer (POST re-render) so the two cannot drift.
    Performs the same UnitProgress.get_or_create + seen-count as a normal view."""
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    # Batch-load choices for any question elements so the math scan + feedback
    # render don't N+1 across questions.
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, ChoiceQuestionElement)
    ]
    if questions:
        prefetch_related_objects(questions, "choices")

    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    question_ct_ids = {ContentType.objects.get_for_model(ChoiceQuestionElement).id}

    def _question_has_math(q):
        if has_math_delimiters(q.stem):
            return True
        return any(has_math_delimiters(c.text) for c in q.choices.all())

    has_math = any(el.content_type_id == math_ct_id for el in elements) or any(
        isinstance(el.content_object, ChoiceQuestionElement)
        and _question_has_math(el.content_object)
        for el in elements
    )
    has_html = any(el.content_type_id == html_ct_id for el in elements)
    has_questions = any(el.content_type_id in question_ct_ids for el in elements)

    progress = None
    seen_ids = set()
    if is_enrolled(user, node.course):
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
    current_ids = [el.pk for el in elements]
    seen_count = len(seen_ids.intersection(current_ids))
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": False,
        "elements": elements,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": has_questions,
        "progress": progress,
        "element_count": len(current_ids),
        "seen_count": seen_count,
    }


@login_required
def my_courses(request):
    courses = Course.objects.filter(enrollments__student=request.user).order_by("title")
    return render(request, "courses/my_courses.html", {"courses": courses})


@login_required
def course_outline(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    outline = build_outline(course, request.user)
    return render(
        request, "courses/outline.html", {"course": course, "outline": outline}
    )


@login_required
def lesson_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if node.unit_type == ContentNode.UnitType.QUIZ:
        return render(
            request,
            "courses/lesson_unit.html",
            {"course": course, "unit": node, "is_quiz": True},
        )
    ctx = build_lesson_context(node, request.user)
    ctx.update(feedback_for_pk=None, selected_ids=frozenset(), mark_result=None)
    return render(request, "courses/lesson_unit.html", ctx)


def _progress_json(progress):
    return {
        "seen_element_ids": list(progress.seen_element_ids),
        "completed": progress.completed,
        "completed_at": progress.completed_at.isoformat()
        if progress.completed_at
        else None,
    }


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
    current = set(node.elements.values_list("pk", flat=True))
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

    choices = list(question.choices.order_by("order", "pk"))
    valid_ids = {c.pk for c in choices}
    submitted = set()
    for raw in request.POST.getlist("choice"):
        try:
            submitted.add(int(raw))
        except (TypeError, ValueError):
            continue
    answer = submitted & valid_ids  # drop foreign/forged ids; never error-leak
    result = question.mark(answer)  # NOTHING is persisted

    if _wants_fragment(request):
        return render(
            request,
            "courses/elements/_question_feedback.html",
            {"el": question, "mark_result": result, "choices": choices},
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    ctx = build_lesson_context(node, request.user)
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=frozenset(answer),
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)
