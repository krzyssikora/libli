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
from courses.models import Attempt  # noqa: F401
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import MathElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.quiz import answer_is_empty  # noqa: F401
from courses.quiz import answer_to_json  # noqa: F401
from courses.quiz import rehydrate  # noqa: F401
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
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")

    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    question_models = [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        FillBlankQuestionElement,
    ]
    question_ct_ids = {ContentType.objects.get_for_model(m).id for m in question_models}

    def _question_has_math(q):
        if has_math_delimiters(q.stem):
            return True
        if isinstance(q, ChoiceQuestionElement):
            return any(has_math_delimiters(c.text) for c in q.choices.all())
        if isinstance(q, FillBlankQuestionElement):
            return any(has_math_delimiters(b.accepted) for b in q.blanks.all())
        return False

    has_math = any(el.content_type_id == math_ct_id for el in elements) or any(
        isinstance(el.content_object, QuestionElement)
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
        "submitted_values": None,
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
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
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

    answer = question.build_answer(request.POST)
    result = question.mark(answer)  # NOTHING is persisted

    if _wants_fragment(request):
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    ctx = build_lesson_context(node, request.user)
    selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)


def build_quiz_context(node, user):
    """Element/render context for a QUIZ unit. Parallels build_lesson_context but
    threads per-question quiz state (responses, locked, attempts_left)."""
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    # Mirror build_lesson_context: the GFK prefetch does NOT fetch choices/blanks,
    # so prefetch them explicitly (avoids N+1 in render/scoring/results).
    questions = [
        el.content_object for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")

    submission = None
    if is_enrolled(user, node.course):
        submission, _ = QuizSubmission.objects.get_or_create(student=user, unit=node)
    quiz_submitted = bool(submission and submission.status == QuizSubmission.Status.SUBMITTED)

    responses = {}
    if submission is not None:
        responses = {r.element_id: r for r in submission.responses.all()}

    # Per-element render state. Task 8 (fresh quiz) leaves feedback_html empty for
    # every question; the no-JS answer path (Task 9) and resume (Task 12) fill it.
    render_states = {}
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        render_states[el.pk] = {
            "selected_ids": frozenset(),
            "submitted_values": None,
            "locked": bool(r.locked) if r else False,
            "attempts_left": None,
            "feedback_html": "",
        }

    # Deliberately over-inclusive vs build_lesson_context's precise per-stem math
    # detection: load KaTeX whenever the quiz has any question. Accepted for 2c
    # (a few KB of unused assets); precise detection can be added later if needed.
    has_math = bool(questions)
    has_html = any(isinstance(el.content_object, HtmlElement) for el in elements)
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": True,
        "elements": elements,
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


@login_required
def quiz_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    ctx = build_quiz_context(node, request.user)
    sub = ctx["submission"]
    if sub is not None and sub.status == QuizSubmission.Status.SUBMITTED:
        return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)
    return render(request, "courses/quiz_unit.html", ctx)


# ---------------------------------------------------------------------------
# Placeholder stubs for quiz views added in later tasks (Tasks 9 & 11).
# The URL routes for these are registered now so all four quiz URL names resolve.
# ---------------------------------------------------------------------------

@require_POST
@login_required
def quiz_answer(request, slug, node_pk, element_pk):
    raise Http404("not implemented yet")


@require_POST
@login_required
def quiz_finish(request, slug, node_pk):
    raise Http404("not implemented yet")


@login_required
def quiz_results(request, slug, node_pk):
    raise Http404("not implemented yet")
