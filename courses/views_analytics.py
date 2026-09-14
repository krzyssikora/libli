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
from courses.access import get_node_or_404
from courses.answer_summary import stem_html
from courses.answer_summary import summarise
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.color_bands import default_color_bands
from courses.color_bands import legend_rows
from courses.forms import ColorBandsForm
from courses.htmlsandbox import has_math_delimiters
from courses.htmlsandbox import titles_have_math
from courses.models import Course
from courses.models import DragToImageQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.models import UnitProgress
from courses.rollups import _course_results_row
from courses.rollups import _quiz_pill
from courses.rollups import _quiz_review_maps
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from courses.rollups import build_student_breakdown
from courses.rollups import tree_titles_have_math
from courses.views import _question_has_math
from courses.views import _results_row
from courses.views import prefetch_question_children
from grouping import scoping


def _with_data_for(course):
    """The set of unit pks holding student data for `course`: >=1 QuizSubmission
    of ANY status, or >=1 UnitProgress. Built ONCE per request by every
    teacher-facing analytics/gradebook/review caller (Task 8) — a draft unit
    pulled back for a typo fix must not blank a mid-term column. Two batched
    queries, never one per unit.

    has_submissions deliberately takes ANY status: a student who opened a quiz
    and stopped has left an interrupted attempt, which is data a teacher may
    need to see — especially on a quiz since pulled back, whose attempt is
    stranded until republication.

    Lives in the VIEW layer, not in rollups.py: folding this into a rollup
    helper (e.g. _quiz_review_maps) would batch only the quiz half and leave
    the lesson half issuing a query per unit — see rollups.build_course_results.
    """
    has_submissions = set(
        QuizSubmission.objects.filter(unit__course=course).values_list(
            "unit_id", flat=True
        )
    )
    has_progress = set(
        UnitProgress.objects.filter(unit__course=course).values_list(
            "unit_id", flat=True
        )
    )
    return frozenset(has_submissions | has_progress)


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
    values = "raw" if request.GET.get("values") == "raw" else "percent"
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
    with_data = _with_data_for(course)
    if mode == "results":
        matrix = build_results_matrix(
            course,
            students,
            expand_pks,
            values,
            drafts="keep-with-data",
            with_data=with_data,
        )
    else:
        matrix = build_progress_matrix(
            course, students, expand_pks, drafts="keep-with-data", with_data=with_data
        )
    bands = course_color_bands(course)
    _decorate(matrix, bands)
    reviewable_ids = set(
        scoping.reviewable_students(request.user, course).values_list("pk", flat=True)
    )
    base_pks = _decorate_links(
        matrix, course, scope, mode, reviewable_ids, subset_pks, values
    )
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    bands_path = reverse("courses:manage_analytics_bands", kwargs={"slug": course.slug})
    show_clear = bool(request.GET.getlist("student")) and not scope_changed
    clear_url = f"{matrix_path}?{_expand_qs(scope, mode, base_pks, set(), values)}"
    progress_qs = _expand_qs(scope, "progress", base_pks, subset_pks, values)
    results_qs = _expand_qs(scope, "results", base_pks, subset_pks, values)
    colours_qs = _expand_qs(scope, mode, base_pks, subset_pks, values)
    percent_qs = _expand_qs(scope, mode, base_pks, subset_pks, "percent")
    raw_qs = _expand_qs(scope, mode, base_pks, subset_pks, "raw")
    # header_rows, NOT columns: `columns` is _public_columns(...) and holds LEAF
    # columns only, so a scan over it silently misses every expanded GROUP cell
    # -- which is exactly what analytics_matrix.html:126 renders.
    has_math = titles_have_math(
        c["title"] for row in matrix["header_rows"] for c in row
    )
    return render(
        request,
        "courses/manage/analytics_matrix.html",
        {
            "course": course,
            "matrix": matrix,
            "mode": mode,
            "values": values,
            "scope": scope,
            "scope_choices": scoping.analytics_scope_choices(request.user, course),
            "legend": legend_rows(bands),
            "can_edit_bands": can_manage_course(request.user, course),
            "expand_pks": base_pks,
            "subset_pks": subset_pks,
            "subset_size": len(subset_pks),
            "show_clear": show_clear,
            "clear_url": clear_url,
            "progress_url": f"{matrix_path}?{progress_qs}",
            "results_url": f"{matrix_path}?{results_qs}",
            "colours_url": f"{bands_path}?{colours_qs}",
            "percent_url": f"{matrix_path}?{percent_qs}",
            "raw_url": f"{matrix_path}?{raw_qs}",
            "has_math": has_math,
        },
    )


def _matrix_redirect(course, request):
    scope = request.POST.get("scope", "all")
    mode = "results" if request.POST.get("mode") == "results" else "progress"
    values = "raw" if request.POST.get("values") == "raw" else "percent"
    expand_pks = _clean_expand(request.POST.getlist("expand"))
    subset_pks = _clean_expand(request.POST.getlist("student"))
    url = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    return redirect(f"{url}?{_expand_qs(scope, mode, expand_pks, subset_pks, values)}")


def _clean_expand(values):
    """Parse repeatable expand params into a list of ints, dropping junk."""
    pks = []
    for raw in values:
        try:
            pks.append(int(raw))
        except (TypeError, ValueError):
            pass
    return pks


def _expand_qs(scope, mode, expand_pks, subset_pks, values):
    """Querystring preserving scope/mode/values + expand pks + the student subset
    (all repeatable). subset_pks is emitted sorted ascending so links are stable;
    an empty subset emits no `student` param. `values` is required (not optional)
    so every call site must thread it and fails loudly until it does, and is
    emitted ONLY when "raw" (percent is the default, kept off the querystring)."""
    data = {
        "scope": scope,
        "mode": mode,
        "expand": list(expand_pks),
        "student": sorted(subset_pks),
    }
    if values == "raw":
        data["values"] = "raw"
    return urlencode(data, doseq=True)


def _drill_params(request):
    """(scope, mode, expand_pks, subset_pks, values) from a drill-down page's GET:
    the breakdown and the per-question page round-trip the matrix's state with it.
    analytics_matrix parses its own (it also reads scope_rendered)."""
    scope = request.GET.get("scope", "all")
    mode = "results" if request.GET.get("mode") == "results" else "progress"
    values = "raw" if request.GET.get("values") == "raw" else "percent"
    expand_pks = _clean_expand(request.GET.getlist("expand"))
    subset_pks = _clean_expand(request.GET.getlist("student"))
    return scope, mode, expand_pks, subset_pks, values


def _decorate_links(matrix, course, scope, mode, reviewable_ids, subset_pks, values):
    """Attach pre-built hrefs (spec §4): on each header cell an expand_url (a
    not-yet-expanded leaf with children) or a collapse_url (an expanded spanning
    cell); a breakdown_url per drillable row. Every href carries the round-tripped
    expand set (the REACHED expanded_nodes pks, self-cleaning) and the student
    subset."""
    base_pks = [en["pk"] for en in matrix["expanded_nodes"]]
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    for hrow in matrix["header_rows"]:
        for cell in hrow:
            if cell["is_leaf"]:
                if cell["expandable"]:
                    expand_pks = base_pks + [cell["node"].pk]
                    expand_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
                    cell["expand_url"] = f"{matrix_path}?{expand_qs}"
            else:  # an expanded spanning cell -> collapse removes its pk
                rest = [p for p in base_pks if p != cell["node"].pk]
                cell["collapse_url"] = (
                    f"{matrix_path}?{_expand_qs(scope, mode, rest, subset_pks, values)}"
                )
    for row in matrix["rows"]:
        if row["student"].pk in reviewable_ids:
            student_path = reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": row["student"].pk},
            )
            breakdown_qs = _expand_qs(scope, mode, base_pks, subset_pks, values)
            row["breakdown_url"] = f"{student_path}?{breakdown_qs}"
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
    with_data = _with_data_for(course)
    breakdown = build_student_breakdown(
        course, student, drafts="keep-with-data", with_data=with_data
    )
    scope, mode, expand_pks, subset_pks, values = _drill_params(request)
    matrix_path = reverse("courses:manage_analytics", kwargs={"slug": course.slug})
    back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
    # build_student_breakdown returns a DICT WRAPPER, {"student": …, "tree": …};
    # passing `breakdown` itself would iterate the dict's keys and raise
    # TypeError -- a 500 on this page.
    has_math = tree_titles_have_math(breakdown["tree"])
    return render(
        request,
        "courses/manage/analytics_student.html",
        {
            "course": course,
            "student": student,
            "breakdown": breakdown,
            "back_url": f"{matrix_path}?{back_qs}",
            "has_math": has_math,
        },
    )


def _override_outcome(question, response, row, in_progress):
    """_results_row's outcome vocabulary is post-submit; fix the three cases it
    misreports on this page (spec §3.3). Never applied inside _results_row: the
    pupil's own results page is out of scope."""
    mode = question.marking_mode
    answered = row["answered"]
    if mode == QuestionElement.MarkingMode.NOT_MARKED and not answered:
        return "not_answered"
    if mode == QuestionElement.MarkingMode.REVIEW and in_progress:
        # Nobody can review it until the submission is finished (by the pupil or
        # a teacher's force-submit): the review page opens SUBMITTED work only.
        return "recorded" if answered else "not_answered"
    if (
        mode == QuestionElement.MarkingMode.AUTO
        and answered
        and response.fraction is None
    ):
        # answered while REVIEW/NOT_MARKED, never reviewed, then switched to AUTO
        return "recorded"
    return row["outcome"]


def _quiz_answer_rows(unit, submission):
    """One display row per top-level question, in element order (spec §3.3)."""
    elements = [
        el
        for el in unit.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
        .prefetch_related("content_object")
        if isinstance(el.content_object, QuestionElement)
    ]
    prefetch_question_children([el.content_object for el in elements])
    responses = {r.element_id: r for r in submission.responses.all()}
    in_progress = submission.status == QuizSubmission.Status.IN_PROGRESS
    rows = []
    for qnum, el in enumerate(elements, start=1):
        question = el.content_object
        response = responses.get(el.pk)
        row = _results_row(question, response)
        row["outcome"] = _override_outcome(question, response, row, in_progress)
        row["parts"] = summarise(question, response, row["reveal_result"])
        row["qnum"] = qnum
        row["stem_html"] = stem_html(question)
        attempts = response.attempt_count if response is not None else 0
        limit = question.max_attempts
        row["attempt_count"] = attempts
        row["attempt_max"] = limit if limit is not None and attempts <= limit else None
        row["dragimage"] = (
            question if isinstance(question, DragToImageQuestionElement) else None
        )
        rows.append(row)
    return rows


def _answers_have_math(unit, rows):
    """KaTeX is needed if the title, any question, any review feedback or any
    displayed part text carries delimiters -- a pupil can type \\(x\\) (spec §5.2)."""
    if titles_have_math([unit.title]):
        return True
    for row in rows:
        if _question_has_math(row["question"]):
            return True
        if has_math_delimiters(row["review_feedback"] or ""):
            return True
        for part in row["parts"]:
            for text in (part.given, part.expected, part.label):
                if text and has_math_delimiters(text):
                    return True
    return False


@login_required
def analytics_student_quiz(request, slug, student_pk, node_pk):
    """One pupil's answers to one quiz (spec §3). Every failure is 404."""
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    student = (
        scoping.reviewable_students(request.user, course).filter(pk=student_pk).first()
    )
    if student is None:
        raise Http404
    # No viewer=: an author-facing surface keeps drafts that carry data (a
    # submission IS data), exactly as the breakdown does.
    unit = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    submission = QuizSubmission.objects.filter(student=student, unit=unit).first()
    if submission is None:
        raise Http404
    has_auto, total_review, reviewed_counts = _quiz_review_maps([unit.pk], [submission])
    pill = _quiz_pill(
        _course_results_row(unit, submission, has_auto, total_review, reviewed_counts)
    )
    scope, mode, expand_pks, subset_pks, values = _drill_params(request)
    student_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    back_qs = _expand_qs(scope, mode, expand_pks, subset_pks, values)
    rows = _quiz_answer_rows(unit, submission)
    return render(
        request,
        "courses/manage/analytics_student_quiz.html",
        {
            "course": course,
            "student": student,
            "unit": unit,
            "submission": submission,
            "pill": pill,
            "back_url": f"{student_path}?{back_qs}",
            "has_math": _answers_have_math(unit, rows),
            "rows": rows,
            "answered_count": sum(1 for row in rows if row["answered"]),
            "question_count": len(rows),
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
            "subset": _clean_expand(src.getlist("student")),
            "values": src.get("values", ""),
        },
    )
