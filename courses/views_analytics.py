from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from courses.access import can_manage_course
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.color_bands import legend_rows
from courses.models import Course
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from grouping import scoping


def _decorate(matrix, bands):
    """Attach band color + readable text color to every cell, overall, and
    average. None percents get color/text_color = None (template renders neutral)."""

    def paint(cell):
        style = band_style(cell["percent"], bands)
        cell["color"] = style["bg"]
        cell["text_color"] = style["fg"]

    for row in matrix["rows"]:
        for cell in row["cells"]:
            paint(cell)
        paint(row["overall"])
    for avg in matrix["averages"]:
        paint(avg)
    paint(matrix["overall_average"])


@login_required
def analytics_matrix(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    scope = request.GET.get("scope", "all")
    students = scoping.students_in_scope(request.user, course, scope).order_by(
        "username"
    )
    builder = build_results_matrix if mode == "results" else build_progress_matrix
    matrix = builder(course, students)
    bands = course_color_bands(course)
    _decorate(matrix, bands)
    return render(
        request,
        "courses/manage/analytics_matrix.html",
        {
            "course": course,
            "matrix": matrix,
            "mode": mode,
            "scope": scope,
            "scope_choices": scoping.analytics_scope_choices(request.user, course),
            "legend": legend_rows(bands),
            "can_edit_bands": can_manage_course(request.user, course),
        },
    )


@login_required
def analytics_bands(request, slug):  # replaced in Task 8
    raise Http404
