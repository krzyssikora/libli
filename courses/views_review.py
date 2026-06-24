from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from courses import quiz as quiz_svc
from courses import review as review_svc
from courses.forms import ReviewResponseForm
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
        if r is not None and r.latest_answer is not None:
            selected_ids, submitted_values = quiz_svc.rehydrate(q, r.latest_answer)
        else:
            selected_ids, submitted_values = set(), None
        answer_html = q.render(
            element=el,
            feedback_for_pk=el.pk,
            selected_ids=selected_ids,
            submitted_values=submitted_values,
            mode="quiz",
            quiz_submitted=True,
            locked=True,
        )
        rows.append(
            {
                "element": el,
                "question": q,
                "response": r,
                "answer_html": answer_html,
                "max_marks": q.max_marks,
                "reviewed": r is not None and r.reviewed_at is not None,
                "earned_marks": r.earned_marks if r else None,
                "feedback": r.review_feedback if r else "",
                "form": ReviewResponseForm(max_marks=q.max_marks),
            }
        )
    return rows


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
    state = review_svc.submission_review_state(submission)
    return render(
        request,
        "courses/manage/review_submission.html",
        {
            "course": course,
            "submission": submission,
            "rows": _review_rows(submission),
            "state": state,
        },
    )


@login_required
def force_submit(request, slug, submission_pk):  # fleshed out in Task 11
    raise Http404


def _review_submission_post(request, course, submission):  # Task 11 replaces this
    raise Http404
