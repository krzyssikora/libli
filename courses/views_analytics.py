from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from courses.access import can_manage_course
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.color_bands import default_color_bands
from courses.color_bands import legend_rows
from courses.forms import ColorBandsForm
from courses.models import Course
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from courses.rollups import build_student_breakdown
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
    scope_rendered = request.GET.get("scope_rendered")
    scope_changed = scope_rendered is not None and scope_rendered != scope
    expand_pks = set(_clean_expand(request.GET.getlist("expand")))
    pool = scoping.students_in_scope(request.user, course, scope)
    raw_subset = (
        set() if scope_changed else set(_clean_expand(request.GET.getlist("student")))
    )
    # Only materialize the pool's pks when there's actually a subset to intersect,
    # so the common no-subset path keeps its single query.
    subset_pks = (
        (raw_subset & set(pool.values_list("pk", flat=True))) if raw_subset else set()
    )
    if subset_pks:
        students = pool.filter(pk__in=subset_pks).order_by("username")
    else:
        students = pool.order_by("username")
    builder = build_results_matrix if mode == "results" else build_progress_matrix
    matrix = builder(course, students, expand_pks)
    bands = course_color_bands(course)
    _decorate(matrix, bands)
    reviewable_ids = set(
        scoping.reviewable_students(request.user, course).values_list("pk", flat=True)
    )
    base_pks = _decorate_links(matrix, course, scope, mode, reviewable_ids)
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    bands_path = reverse("courses:manage_analytics_bands", kwargs={"slug": course.slug})
    show_clear = bool(request.GET.getlist("student")) and not scope_changed
    clear_url = f"{matrix_path}?{_expand_qs(scope, mode, base_pks)}"
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
            "expand_pks": base_pks,
            "subset_pks": subset_pks,
            "subset_size": len(subset_pks),
            "show_clear": show_clear,
            "clear_url": clear_url,
            "progress_url": f"{matrix_path}?{_expand_qs(scope, 'progress', base_pks)}",
            "results_url": f"{matrix_path}?{_expand_qs(scope, 'results', base_pks)}",
            "colours_url": f"{bands_path}?{_expand_qs(scope, mode, base_pks)}",
        },
    )


def _matrix_redirect(course, request):
    scope = request.POST.get("scope", "all")
    mode = "results" if request.POST.get("mode") == "results" else "progress"
    expand_pks = _clean_expand(request.POST.getlist("expand"))
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return redirect(f"{url}?{_expand_qs(scope, mode, expand_pks)}")


def _clean_expand(values):
    """Parse repeatable expand params into a list of ints, dropping junk."""
    pks = []
    for raw in values:
        try:
            pks.append(int(raw))
        except (TypeError, ValueError):
            pass
    return pks


def _expand_qs(scope, mode, expand_pks):
    """Querystring preserving scope/mode + the given expand pks (repeatable)."""
    return urlencode(
        {"scope": scope, "mode": mode, "expand": list(expand_pks)}, doseq=True
    )


def _decorate_links(matrix, course, scope, mode, reviewable_ids):
    """Attach pre-built hrefs (spec §4): on each header cell an expand_url (a
    not-yet-expanded leaf with children) or a collapse_url (an expanded spanning
    cell); a breakdown_url per drillable row. The round-tripped expand set is the
    REACHED expanded_nodes pks (self-cleaning)."""
    base_pks = [en["pk"] for en in matrix["expanded_nodes"]]
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    for hrow in matrix["header_rows"]:
        for cell in hrow:
            if cell["is_leaf"]:
                if cell["expandable"]:
                    cell["expand_url"] = (
                        f"{matrix_path}?"
                        f"{_expand_qs(scope, mode, base_pks + [cell['node'].pk])}"
                    )
            else:  # an expanded spanning cell -> collapse removes its pk
                rest = [p for p in base_pks if p != cell["node"].pk]
                cell["collapse_url"] = f"{matrix_path}?{_expand_qs(scope, mode, rest)}"
    for row in matrix["rows"]:
        if row["student"].pk in reviewable_ids:
            student_path = reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": row["student"].pk},
            )
            row["breakdown_url"] = f"{student_path}?{_expand_qs(scope, mode, base_pks)}"
    return base_pks


@login_required
def analytics_student(request, slug, student_pk):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    student = (
        scoping.reviewable_students(request.user, course).filter(pk=student_pk).first()
    )
    if student is None:
        # non-existent OR out-of-reach -> 404, never 403 (manage convention)
        raise Http404
    breakdown = build_student_breakdown(course, student)
    scope = request.GET.get("scope", "all")
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    expand_pks = _clean_expand(request.GET.getlist("expand"))
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return render(
        request,
        "courses/manage/analytics_student.html",
        {
            "course": course,
            "student": student,
            "breakdown": breakdown,
            "back_url": f"{matrix_path}?{_expand_qs(scope, mode, expand_pks)}",
        },
    )


@login_required
def analytics_bands(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_manage_course(request.user, course):
        raise Http404
    if request.method == "POST":
        if "reset" in request.POST:
            course.color_bands = []
            course.save(update_fields=["color_bands"])
            messages.success(request, _("Colours reset to defaults."))
            return _matrix_redirect(course, request)
        form = ColorBandsForm(request.POST)
        if form.is_valid():
            course.color_bands = form.to_bands()
            course.save(update_fields=["color_bands"])
            messages.success(request, _("Colours saved."))
            return _matrix_redirect(course, request)
    else:
        form = ColorBandsForm(
            initial=ColorBandsForm.initial_from(course_color_bands(course))
        )
    default_bands = default_color_bands()
    src = request.POST if request.method == "POST" else request.GET
    return render(
        request,
        "courses/manage/analytics_bands.html",
        {
            "course": course,
            "form": form,
            "default_bands": default_bands,
            # band_rows: label + the two BOUND fields for bands 1–4 (band 0's min
            # is pinned at 0; only its colour, form.color_0, is editable). Built
            # here so the single shared render() (GET + invalid-POST) always has it.
            "band_rows": [
                {
                    "label": default_bands[i]["label"],
                    "min_field": form[f"min_{i}"],
                    "color_field": form[f"color_{i}"],
                }
                for i in range(1, 5)
            ],
            "scope": src.get("scope", "all"),
            "mode": "results" if src.get("mode") == "results" else "progress",
            "expand_pks": _clean_expand(src.getlist("expand")),
        },
    )
