from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from courses.models import Course


@login_required
def course_list(request):
    """My courses (admin) — view 5.1. Owner sees their own; a holder of
    courses.change_course (Platform Admin) sees all. Ordered by title."""
    if request.user.has_perm("courses.change_course"):
        courses = Course.objects.all().order_by("title")
    else:
        courses = Course.objects.filter(owner=request.user).order_by("title")
    return render(request, "courses/manage/course_list.html", {"courses": courses})


def course_create(request):
    return HttpResponse("stub")  # Task 3


def course_edit(request, slug):
    return HttpResponse("stub")  # Task 3


def course_delete(request, slug):
    return HttpResponse("stub")  # Task 4


def builder(request, slug):
    return HttpResponse("stub")  # Task 6
