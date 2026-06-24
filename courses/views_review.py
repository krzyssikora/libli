from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from courses import review as review_svc
from courses.models import Course
from grouping import scoping


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
def review_submission(request, slug, submission_pk):  # fleshed out in Task 10/11
    raise Http404


@login_required
def force_submit(request, slug, submission_pk):  # fleshed out in Task 11
    raise Http404
