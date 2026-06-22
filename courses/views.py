import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import prefetch_related_objects
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import JsonResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses.access import can_access_course
from courses.access import get_node_or_404
from courses.access import is_enrolled
from courses.htmlsandbox import has_math_delimiters
from courses.marking import MarkResult  # noqa: F401  (documents the return type)
from courses.models import Attempt  # noqa: F401
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import HtmlElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.quiz import answer_from_json
from courses.quiz import answer_is_empty  # noqa: F401
from courses.quiz import answer_to_json  # noqa: F401
from courses.quiz import quiz_feedback_context
from courses.quiz import rehydrate  # noqa: F401
from courses.rollups import build_outline
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def build_lesson_context(node, user):
    """Shared element/has_*/progress context for a LESSON unit. Used by both
    lesson_unit (GET) and check_answer (POST re-render) so the two cannot drift.
    Performs the same UnitProgress.get_or_create + seen-count as a normal view."""
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    dragimage_qs = [q for q in questions if isinstance(q, DragToImageQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
    if dragimage_qs:
        prefetch_related_objects(dragimage_qs, "zones")

    math_ct_id = ContentType.objects.get_for_model(MathElement).id
    html_ct_id = ContentType.objects.get_for_model(HtmlElement).id
    question_models = [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        FillBlankQuestionElement,
        DragFillBlankQuestionElement,
        MatchPairQuestionElement,
        DragToImageQuestionElement,
        ExtendedResponseQuestionElement,
    ]
    question_ct_ids = {ContentType.objects.get_for_model(m).id for m in question_models}

    def _question_has_math(q):
        if has_math_delimiters(q.stem):
            return True
        if isinstance(q, ChoiceQuestionElement):
            return any(has_math_delimiters(c.text) for c in q.choices.all())
        if isinstance(q, FillBlankQuestionElement):
            return any(has_math_delimiters(b.accepted) for b in q.blanks.all())
        if isinstance(q, DragFillBlankQuestionElement):
            return has_math_delimiters(q.distractors) or any(
                has_math_delimiters(b.correct_token) for b in q.dragblanks.all()
            )
        if isinstance(q, MatchPairQuestionElement):
            return has_math_delimiters(q.distractors) or any(
                has_math_delimiters(p.left) or has_math_delimiters(p.right)
                for p in q.pairs.all()
            )
        if isinstance(q, DragToImageQuestionElement):
            return has_math_delimiters(q.distractors) or any(
                has_math_delimiters(z.correct_label) for z in q.zones.all()
            )
        return False

    has_math = any(el.content_type_id == math_ct_id for el in elements) or any(
        isinstance(el.content_object, QuestionElement)
        and _question_has_math(el.content_object)
        for el in elements
    )
    has_html = any(el.content_type_id == html_ct_id for el in elements)
    has_questions = any(el.content_type_id in question_ct_ids for el in elements)

    progress = None
    seen_ids = set()
    if is_enrolled(user, node.course):
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
    current_ids = [el.pk for el in elements]
    seen_count = len(seen_ids.intersection(current_ids))
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": False,
        "elements": elements,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": has_questions,
        "submitted_values": None,
        "progress": progress,
        "element_count": len(current_ids),
        "seen_count": seen_count,
    }


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


@login_required
def lesson_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if node.unit_type == ContentNode.UnitType.QUIZ:
        return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
    ctx = build_lesson_context(node, request.user)
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    )
    return render(request, "courses/lesson_unit.html", ctx)


def _progress_json(progress):
    return {
        "seen_element_ids": list(progress.seen_element_ids),
        "completed": progress.completed,
        "completed_at": progress.completed_at.isoformat()
        if progress.completed_at
        else None,
    }


@require_POST
@login_required
def seen(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    try:
        data = json.loads(request.body or b"[]")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("invalid JSON")
    if not isinstance(data, list):
        return HttpResponseBadRequest("expected a JSON array")
    if not is_enrolled(request.user, course):
        # untracked preview: no write, synthetic canonical response
        return JsonResponse(
            {"seen_element_ids": [], "completed": False, "completed_at": None}
        )
    current = set(node.elements.values_list("pk", flat=True))
    incoming = {
        x
        for x in data
        if isinstance(x, int) and not isinstance(x, bool) and x in current
    }
    progress, _ = UnitProgress.objects.get_or_create(student=request.user, unit=node)
    merged = set(progress.seen_element_ids) | incoming
    progress.seen_element_ids = sorted(merged)
    if not progress.completed and current and current.issubset(merged):
        progress.completed = True  # completed_at stamped in save()
    progress.save()
    return JsonResponse(_progress_json(progress))


@require_POST
@login_required
def complete(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if is_enrolled(request.user, course):
        progress, _ = UnitProgress.objects.get_or_create(
            student=request.user, unit=node
        )
        if not progress.completed:
            progress.completed = True
            progress.save()
    return redirect("courses:lesson_unit", slug=slug, node_pk=node_pk)


@require_POST
@login_required
def check_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_lesson=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    answer = question.build_answer(request.POST)
    result = question.mark(answer)  # NOTHING is persisted

    if _wants_fragment(request):
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    ctx = build_lesson_context(node, request.user)
    selected = answer if isinstance(answer, (set, frozenset)) else frozenset()
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
    )
    return render(request, "courses/lesson_unit.html", ctx)


def _stored_result(question, response):
    # MarkResult + answer_from_json imported at views.py top (M3, no local imports).
    reveal = question.mark(answer_from_json(question, response.latest_answer)).reveal
    return MarkResult(
        correct=(response.fraction == Decimal("1.0000")),
        fraction=float(response.fraction or 0),
        reveal=reveal,
    )


def build_quiz_context(node, user):
    """Element/render context for a QUIZ unit. Parallels build_lesson_context but
    threads per-question quiz state (responses, locked, attempts_left)."""
    elements = list(
        node.elements.order_by("order", "pk")
        .select_related("unit__course")
        .prefetch_related("content_object")
    )
    # Mirror build_lesson_context: the GFK prefetch does NOT fetch choices/blanks,
    # so prefetch them explicitly (avoids N+1 in render/scoring/results).
    questions = [
        el.content_object
        for el in elements
        if isinstance(el.content_object, QuestionElement)
    ]
    choice_qs = [q for q in questions if isinstance(q, ChoiceQuestionElement)]
    fill_qs = [q for q in questions if isinstance(q, FillBlankQuestionElement)]
    dragfill_qs = [q for q in questions if isinstance(q, DragFillBlankQuestionElement)]
    matchpair_qs = [q for q in questions if isinstance(q, MatchPairQuestionElement)]
    dragimage_qs = [q for q in questions if isinstance(q, DragToImageQuestionElement)]
    if choice_qs:
        prefetch_related_objects(choice_qs, "choices")
    if fill_qs:
        prefetch_related_objects(fill_qs, "blanks")
    if dragfill_qs:
        prefetch_related_objects(dragfill_qs, "dragblanks")
    if matchpair_qs:
        prefetch_related_objects(matchpair_qs, "pairs")
    if dragimage_qs:
        prefetch_related_objects(dragimage_qs, "zones")

    submission = None
    if is_enrolled(user, node.course):
        submission, _ = QuizSubmission.objects.get_or_create(student=user, unit=node)
    quiz_submitted = bool(
        submission and submission.status == QuizSubmission.Status.SUBMITTED
    )

    responses = {}
    if submission is not None:
        responses = {r.element_id: r for r in submission.responses.all()}

    # Per-element render state. Task 8 (fresh quiz) leaves feedback_html empty for
    # every question; the no-JS answer path (Task 9) and resume (Task 12) fill it.
    render_states = {}
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        state = {
            "selected_ids": frozenset(),
            "submitted_values": None,
            "locked": bool(r.locked) if r else False,
            "attempts_left": None,
            "feedback_html": "",
        }
        if r is not None and r.attempt_count > 0:
            selected, submitted = rehydrate(q, r.latest_answer)
            state["selected_ids"] = selected
            state["submitted_values"] = submitted
            result = (
                _stored_result(q, r)
                if q.marking_mode == QuestionElement.MarkingMode.AUTO
                else None  # [N]/[R] -> neutral branch in quiz_feedback_context
            )
            fb_ctx = quiz_feedback_context(q, r, result=result)
            state["attempts_left"] = fb_ctx.get("attempts_left")
            state["feedback_html"] = render_to_string(
                "courses/elements/_quiz_question_feedback.html", fb_ctx
            )
        render_states[el.pk] = state

    # Deliberately over-inclusive vs build_lesson_context's precise per-stem math
    # detection: load KaTeX whenever the quiz has any question. Accepted for 2c
    # (a few KB of unused assets); precise detection can be added later if needed.
    has_math = bool(questions)
    has_html = any(isinstance(el.content_object, HtmlElement) for el in elements)
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": True,
        "elements": elements,
        "responses": responses,
        "render_states": render_states,
        "submission": submission,
        "quiz_submitted": quiz_submitted,
        # Inputs are disabled + Finish hidden when the quiz is submitted OR the
        # accessor is a non-enrolled previewer (submission is None) — a previewer
        # gets a READ-ONLY quiz, never live forms that 403 on submit.
        "read_only": quiz_submitted or submission is None,
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": True,
    }


@login_required
def quiz_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    ctx = build_quiz_context(node, request.user)
    sub = ctx["submission"]
    if sub is not None and sub.status == QuizSubmission.Status.SUBMITTED:
        return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)
    return render(request, "courses/quiz_unit.html", ctx)


# ---------------------------------------------------------------------------
# Quiz answer path (Task 9): per-question [A] submit, withhold state machine,
# concurrency locks, empty-answer guard, and no-leak invariant.
# ---------------------------------------------------------------------------


def _quiz_locked_response(request, slug, node_pk):
    if _wants_fragment(request):
        return HttpResponse(_("This quiz has already been submitted."), status=409)
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


def _quiz_render_feedback(
    request, node, element, question, response, *, result=None, validation=False
):
    fb_ctx = quiz_feedback_context(
        question, response, result=result, validation=validation
    )
    if _wants_fragment(request):
        return render(request, "courses/elements/_quiz_question_feedback.html", fb_ctx)
    # No-JS: full quiz_unit re-render. Inject THIS question's fragment into its
    # single feedback box (render_states[pk]["feedback_html"]) and rehydrate its
    # inputs — the same render path resume (Task 12) uses, so no double container.
    ctx = build_quiz_context(node, request.user)
    fragment = render_to_string("courses/elements/_quiz_question_feedback.html", fb_ctx)
    st = ctx["render_states"].get(element.pk)
    if st is not None:
        st["feedback_html"] = fragment
        selected, submitted = rehydrate(question, response.latest_answer)
        st["selected_ids"] = selected
        st["submitted_values"] = submitted
    return render(request, "courses/quiz_unit.html", ctx)


@require_POST
@login_required
def quiz_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied  # previewers cannot persist

    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    with transaction.atomic():
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=request.user, unit=node
        )
        if submission.status == QuizSubmission.Status.SUBMITTED:
            return _quiz_locked_response(request, slug, node_pk)

        response, _ = QuestionResponse.objects.select_for_update().get_or_create(
            submission=submission, element=element
        )
        if response.locked or (
            question.max_attempts is not None
            and response.attempt_count >= question.max_attempts
        ):
            return _quiz_locked_response(request, slug, node_pk)

        answer = question.build_answer(request.POST)
        if answer_is_empty(answer):
            # No attempt recorded. On the no-JS validation re-render the offending
            # question's inputs show its PRIOR latest_answer (if any) or blank on a
            # first attempt — there is nothing new to rehydrate. Intentional boundary.
            return _quiz_render_feedback(
                request, node, element, question, response, validation=True
            )

        is_auto = question.marking_mode == QuestionElement.MarkingMode.AUTO
        result = None
        if is_auto:
            result = question.mark(answer)
            f = to_stored_fraction(result.fraction)
            response.fraction = f
            response.earned_marks = earned_marks(f, question.max_marks)
            attempt_fraction = f
            attempt_correct = result.correct
        else:
            attempt_fraction = None
            attempt_correct = None

        response.attempt_count += 1
        response.latest_answer = answer_to_json(answer)
        response.last_attempt_at = timezone.now()
        if is_auto:
            response.locked = bool(result.correct) or (
                question.max_attempts is not None
                and response.attempt_count >= question.max_attempts
            )
        else:
            response.locked = True  # [N]/[R]: single submission
        response.save()
        Attempt.objects.create(
            response=response,
            n=response.attempt_count,
            answer=response.latest_answer,
            fraction=attempt_fraction,
            correct=attempt_correct,
        )

    return _quiz_render_feedback(
        request, node, element, question, response, result=result
    )


def _score_submission(node, submission):
    """Recompute score/max_score from CURRENT max_marks/marking_mode, lock all
    responses, mark submitted. Caller holds select_for_update on the submission.
    Reads only scalar fields (max_marks/marking_mode/fraction) — no choices/blanks
    prefetch needed here, unlike the render path."""
    responses = {r.element_id: r for r in submission.responses.all()}
    total = Decimal("0.00")
    possible = Decimal("0.00")
    for el in node.elements.all().prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode != QuestionElement.MarkingMode.AUTO:
            continue
        possible += q.max_marks
        r = responses.get(el.pk)
        if r is not None and r.fraction is not None:
            total += earned_marks(r.fraction, q.max_marks)
    # The ONLY writer of `locked` here; the in-memory `responses` dict objects are
    # never re-saved, so this bulk update is not clobbered.
    submission.responses.update(locked=True)
    submission.score = total
    submission.max_score = possible
    submission.status = QuizSubmission.Status.SUBMITTED
    submission.save()  # stamps submitted_at


@require_POST
@login_required
def quiz_finish(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if not is_enrolled(request.user, course):
        raise PermissionDenied
    with transaction.atomic():
        submission, _ = QuizSubmission.objects.select_for_update().get_or_create(
            student=request.user, unit=node
        )
        if submission.status != QuizSubmission.Status.SUBMITTED:
            _score_submission(node, submission)
            progress, _ = UnitProgress.objects.get_or_create(
                student=request.user, unit=node
            )
            if not progress.completed:
                progress.completed = True
                progress.save()
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


@login_required
def quiz_results(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, require_unit=True, require_quiz=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    submission = QuizSubmission.objects.filter(
        student=request.user, unit=node, status=QuizSubmission.Status.SUBMITTED
    ).first()
    if submission is None:
        return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
    responses = {r.element_id: r for r in submission.responses.all()}
    rows = []
    # One-time post-submit render; the per-question choices/blanks access in
    # _results_row is an accepted N+1 here (not worth a prefetch pass for 2c).
    for el in node.elements.order_by("order", "pk").prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        r = responses.get(el.pk)
        rows.append(_results_row(q, r))
    return render(
        request,
        "courses/quiz_results.html",
        {
            "course": course,
            "unit": node,
            "submission": submission,
            "rows": rows,
        },
    )


def _results_row(question, response):
    """Outcome classification keyed on CURRENT marking_mode (stale fraction ignored
    for [N]). For [A], attach a `reveal_result` (a MarkResult whose `.reveal` is the
    correct-answer payload) + `choices`, so the per-type reveal partial renders the
    correct answer for EVERY [A] row — including unanswered ones (§3.4 'reveal all').
    Returns a dict the results template renders."""
    mode = question.marking_mode
    row = {
        "question": question,
        "response": response,
        "outcome": None,
        "earned": None,
        "possible": question.max_marks,
        "reveal_result": None,
        "reveal_template": None,
        "choices": None,
        "answered": response is not None and response.latest_answer is not None,
    }
    if mode == QuestionElement.MarkingMode.NOT_MARKED:
        row["outcome"] = "recorded" if response else "not_answered"
    elif mode == QuestionElement.MarkingMode.REVIEW:
        row["outcome"] = "review"
    else:  # [A]
        if response is None or response.fraction is None:
            row["outcome"] = "not_answered"
            row["earned"] = Decimal("0.00")
        else:
            earned = earned_marks(response.fraction, question.max_marks)
            row["earned"] = earned
            if earned == question.max_marks:
                row["outcome"] = "correct"
            elif earned > 0:
                row["outcome"] = "partial"
            else:
                row["outcome"] = "incorrect"
        # `reveal` is the correct-answer payload. Mark the STUDENT'S answer when one
        # exists so the per-blank ✓/✗ in _reveal_fillblank reflects what they entered
        # (marking an empty answer would show every blank wrong even when correct);
        # for an unanswered question, mark an empty answer (shows the correct answers,
        # all blanks ✗ — acceptable, it was not answered).
        if response is not None and response.latest_answer is not None:
            row["reveal_result"] = question.mark(
                answer_from_json(question, response.latest_answer)
            )
        else:
            row["reveal_result"] = question.mark(question.build_answer(QueryDict()))
        row["reveal_template"] = question.REVEAL_TEMPLATE
        if isinstance(question, ChoiceQuestionElement):
            row["choices"] = list(question.choices.all())
    return row
