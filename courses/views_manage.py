from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render

from courses.access import can_manage_course
from courses.forms import CourseForm
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


def builder(request, slug):
    return HttpResponse("stub")  # Task 6
