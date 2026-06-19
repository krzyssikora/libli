import json

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.views.decorators.http import require_POST

from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.access import is_enrolled
from courses.models import ContentNode
from courses.models import Course
from courses.models import HtmlElement
from courses.models import MathElement
from courses.models import UnitProgress
from courses.rollups import build_outline


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
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    has_math = any(el.content_type_id == math_ct_id for el in elements)
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    has_html = any(el.content_type_id == html_ct_id for el in elements)
    progress = None
    seen_ids = set()
    if is_enrolled(request.user, course):
        progress, _ = UnitProgress.objects.get_or_create(
            student=request.user, unit=node
        )
        seen_ids = set(progress.seen_element_ids)
    current_ids = [el.pk for el in elements]
    seen_count = len(seen_ids.intersection(current_ids))
    return render(
        request,
        "courses/lesson_unit.html",
        {
            "course": course,
            "unit": node,
            "is_quiz": False,
            "elements": elements,
            "has_math": has_math,
            "has_html": has_html,
            "progress": progress,
            "element_count": len(current_ids),
            "seen_count": seen_count,
        },
    )


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
