from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from courses.access import can_access_course
from courses.models import Course
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
