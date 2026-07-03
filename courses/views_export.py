from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _

from courses.exporters import build_filename
from courses.exporters import render_gradebook_print
from courses.exporters import to_csv
from courses.exporters import to_xlsx
from courses.gradebook import build_matrix_table
from courses.gradebook import build_quiz_gradebook
from courses.models import Course
from courses.views_analytics import _clean_expand  # shared param parser (see note)
from grouping import scoping

_SHAPES = {"matrix", "quiz"}
_FORMATS = {"csv", "xlsx", "html"}


def _scope_label(user, course, scope):
    for choice in scoping.analytics_scope_choices(user, course):
        if choice["value"] == scope:
            return choice["label"]
    return _("All my students")


@login_required
def gradebook_export(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404

    shape = request.GET.get("shape")
    shape = shape if shape in _SHAPES else "matrix"
    fmt = request.GET.get("format")
    fmt = fmt if fmt in _FORMATS else "csv"
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    scope = request.GET.get("scope", "all")
    expanded = set(_clean_expand(request.GET.getlist("expand")))
    numbers_only = request.GET.get("numbers_only") == "1" and shape == "quiz"

    # scope ∩ subset — identical resolution to analytics_matrix (no scope_changed).
    pool = scoping.students_in_scope(request.user, course, scope)
    raw_subset = set(_clean_expand(request.GET.getlist("student")))
    subset_pks = (
        (raw_subset & set(pool.values_list("pk", flat=True))) if raw_subset else set()
    )
    students = (
        pool.filter(pk__in=subset_pks).order_by("username")
        if subset_pks
        else pool.order_by("username")
    )

    if shape == "quiz":
        table = build_quiz_gradebook(course, students, numbers_only)
        shape_label = _("Quiz gradebook")
    else:
        table = build_matrix_table(course, students, mode, expanded)
        shape_label = _("Results") if mode == "results" else _("Progress")

    label = _scope_label(request.user, course, scope)
    today = timezone.localdate()
    table["title"] = f"{course.title} — {label} — {shape_label}"
    table["subtitle"] = _("Generated %(date)s · Scope: %(scope)s") % {
        "date": today.isoformat(),
        "scope": label,
    }

    if fmt == "html":
        return render_gradebook_print(request, table)
    ext = "csv" if fmt == "csv" else "xlsx"
    filename = build_filename(course.slug, shape, mode, numbers_only, today, ext)
    return (to_csv if fmt == "csv" else to_xlsx)(table, filename)
