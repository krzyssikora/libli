from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses import quiz as quiz_svc
from courses import review as review_svc
from courses.forms import ReviewResponseForm
from courses.htmlsandbox import has_math_delimiters
from courses.models import Course
from courses.models import QuestionElement
from courses.models import QuizSubmission
from grouping import scoping


def _resolve_for_review(request, slug, submission_pk):
    course = get_object_or_404(Course, slug=slug)
    submission = get_object_or_404(QuizSubmission, pk=submission_pk)
    if submission.unit.course_id != course.id:
        raise Http404
    if (
        not scoping.reviewable_students(request.user, course)
        .filter(pk=submission.student_id)
        .exists()
    ):
        raise Http404
    return course, submission


def _answer_display(question, response):
    """The student's submitted answer as plain read-only text (not the live
    question widget). [R] questions are free-text in practice, but handle the
    other shapes too: choice -> selected choice texts; list -> joined; string
    (short-text / numeric / extended) -> as typed. None when unanswered."""
    if response is None or response.latest_answer is None:
        return None
    selected_ids, submitted = quiz_svc.rehydrate(question, response.latest_answer)
    if selected_ids:
        texts = [c.text for c in question.choices.all() if c.pk in selected_ids]
        return ", ".join(texts) or None
    if isinstance(submitted, (list, tuple)):
        parts = [str(v) for v in submitted if v not in (None, "")]
        return ", ".join(parts) or None
    if submitted in (None, ""):
        return None
    return str(submitted).strip() or None


def _review_rows(submission):
    rows = []
    responses = {r.element_id: r for r in submission.responses.all()}
    for el in submission.unit.elements.all().prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode != QuestionElement.MarkingMode.REVIEW:
            continue
        r = responses.get(el.pk)
        rows.append(
            {
                "element": el,
                "question": q,
                "response": r,
                "answer_text": _answer_display(q, r),
                "max_marks": q.max_marks,
                "reviewed": r is not None and r.reviewed_at is not None,
                "earned_marks": r.earned_marks if r else None,
                "feedback": r.review_feedback if r else "",
            }
        )
    return rows


def _review_context(course, submission):
    rows = _review_rows(submission)
    return {
        "course": course,
        "submission": submission,
        "rows": rows,
        "state": review_svc.submission_review_state(submission),
        # KaTeX is needed if the stem or the student's answer carries math.
        "has_math": any(
            has_math_delimiters(row["question"].stem)
            or has_math_delimiters(row["answer_text"] or "")
            for row in rows
        ),
    }


@login_required
def review_queue(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not scoping.can_review_course(request.user, course):
        raise Http404
    data = review_svc.pending_reviews_for(request.user, course)
    return render(
        request,
        "courses/manage/review_queue.html",
        {
            "course": course,
            "awaiting": data["awaiting"],
            "in_progress": data["in_progress"],
        },
    )


@login_required
def review_submission(request, slug, submission_pk):
    course, submission = _resolve_for_review(request, slug, submission_pk)
    if request.method == "POST":
        return _review_submission_post(request, course, submission)  # Task 11
    return render(
        request,
        "courses/manage/review_submission.html",
        _review_context(course, submission),
    )


@login_required
@require_POST
def force_submit(request, slug, submission_pk):
    course, submission = _resolve_for_review(request, slug, submission_pk)
    review_svc.force_submit_quiz(submission, by=request.user)
    messages.success(
        request,
        _("Quiz submitted for %(student)s.")
        % {"student": submission.student.display_name or submission.student.username},
    )
    return redirect("courses:manage_review_queue", slug=course.slug)


def _review_submission_post(request, course, submission):
    element_pk = request.POST.get("element_pk")
    el = submission.unit.elements.filter(pk=element_pk).first()
    if el is None:
        raise Http404
    question = el.content_object
    if (
        not isinstance(question, QuestionElement)
        or question.marking_mode != QuestionElement.MarkingMode.REVIEW
    ):
        raise Http404
    form = ReviewResponseForm(request.POST, max_marks=question.max_marks)
    if not form.is_valid():
        return render(
            request,
            "courses/manage/review_submission.html",
            _review_context(course, submission),
            status=422,
        )
    review_svc.review_response(
        submission=submission,
        element=el,
        earned_marks=form.cleaned_data["earned_marks"],
        feedback=form.cleaned_data["feedback"],
        reviewer=request.user,
    )
    return redirect(
        "courses:manage_review_submission",
        slug=course.slug,
        submission_pk=submission.pk,
    )
