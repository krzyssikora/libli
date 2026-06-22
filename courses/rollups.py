from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import QuestionElement
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress

# The 8 concrete QuestionElement subclasses (the roadmap's "9 types" — single+multi
# MCQ share ChoiceQuestionElement). Mirrors courses/views.py:91-100.
_QUESTION_MODELS = [
    ChoiceQuestionElement,
    ShortTextQuestionElement,
    ShortNumericQuestionElement,
    FillBlankQuestionElement,
    DragFillBlankQuestionElement,
    MatchPairQuestionElement,
    DragToImageQuestionElement,
    ExtendedResponseQuestionElement,
]


def quiz_units_in_order(course):
    """Quiz units (kind=UNIT, unit_type=QUIZ) in depth-first pre-order of the content
    tree — the order they appear walking the outline top to bottom. ONE query
    (course.nodes.all(), ordered by ContentNode.Meta.ordering = ["order","pk"]);
    parent_id-grouped recursion. A flat iteration of course.nodes.all() is NOT
    pre-order (sibling `order` is only locally monotonic) and must not be used.
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    result = []

    def walk(parent_id):
        for node in children.get(parent_id, []):
            if (
                node.kind == ContentNode.Kind.UNIT
                and node.unit_type == ContentNode.UnitType.QUIZ
            ):
                result.append(node)
            walk(node.pk)

    walk(None)
    return result


def build_outline(course, user):
    """Return a nested list of node dicts with required/additional rollups.

    Two queries (nodes + the user's completed unit ids). `required` counts only
    obligatory lesson units; `additional_done` counts completed non-obligatory lesson
    units; quiz units are excluded from both (uncompletable in 1a).
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    completed = set()
    if user.is_authenticated:
        completed = set(
            UnitProgress.objects.filter(
                student=user, unit__course=course, completed=True
            ).values_list("unit_id", flat=True)
        )

    def build(node):
        kids = [build(child) for child in children.get(node.pk, [])]
        if node.kind == ContentNode.Kind.UNIT:
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            required_total = 1 if (is_lesson and node.obligatory) else 0
            required_done = 1 if (required_total and node.pk in completed) else 0
            additional_done = (
                1 if (is_lesson and not node.obligatory and node.pk in completed) else 0
            )
        else:
            required_total = sum(k["required_total"] for k in kids)
            required_done = sum(k["required_done"] for k in kids)
            additional_done = sum(k["additional_done"] for k in kids)
        return {
            "node": node,
            "children": kids,
            "required_total": required_total,
            "required_done": required_done,
            "additional_done": additional_done,
            "is_unit": node.kind == ContentNode.Kind.UNIT,
            "completed": node.kind == ContentNode.Kind.UNIT and node.pk in completed,
        }

    return [build(node) for node in children.get(None, [])]


def build_course_results(course, student):
    """Per-course quiz summary for one student (the viewing user). Pure of side
    effects. Sums the headline over SUBMITTED quizzes only; awaiting_review is
    element-driven (the unit has an [R] question) — NOT a QuestionResponse scan,
    since responses are lazy and an unanswered [R] has no row."""
    units = quiz_units_in_order(course)
    unit_pks = [u.pk for u in units]

    submissions = {
        s.unit_id: s
        for s in QuizSubmission.objects.filter(student=student, unit__course=course)
    }

    # Per-unit marking-mode presence, resolved via the Element GFK. Filter to
    # question content-types so the GFK batch only pulls questions (Element can
    # point at Text/Image/Math too).
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS
    }
    has_auto = {}
    has_review = {}
    elements = Element.objects.filter(
        unit_id__in=unit_pks, content_type_id__in=question_ct_ids
    ).prefetch_related("content_object")
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):  # defensive parity with quiz_results
            continue
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            has_auto[el.unit_id] = True
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            has_review[el.unit_id] = True

    rows = []
    score_sum = Decimal("0")
    max_sum = Decimal("0")
    done_count = 0
    for unit in units:
        sub = submissions.get(unit.pk)
        if sub is None:
            rows.append(
                {
                    "unit": unit,
                    "status": "not_started",
                    "graded": False,
                    "score": None,
                    "max_score": None,
                    "pending": False,
                    "url_name": "courses:quiz_unit",
                }
            )
            continue
        if sub.status == QuizSubmission.Status.IN_PROGRESS:
            rows.append(
                {
                    "unit": unit,
                    "status": "in_progress",
                    "graded": False,
                    "score": None,
                    "max_score": None,
                    "pending": False,
                    "url_name": "courses:quiz_unit",
                }
            )
            continue
        # SUBMITTED
        graded = has_auto.get(unit.pk, False)  # ≡ max_score > 0 (max_marks >= 0.01)
        pending = has_review.get(unit.pk, False)
        rows.append(
            {
                "unit": unit,
                "status": "awaiting_review" if pending else "submitted",
                "graded": graded,
                "score": sub.score,
                "max_score": sub.max_score,
                "pending": pending,
                "url_name": "courses:quiz_results",
            }
        )
        done_count += 1
        score_sum += sub.score or Decimal("0")
        max_sum += sub.max_score or Decimal("0")

    percent = None
    if max_sum and max_sum > 0:
        percent = int(round(Decimal(100) * score_sum / max_sum))

    return {
        "course": course,
        "rows": rows,
        "done_count": done_count,
        "total_count": len(units),
        "score": score_sum if done_count else None,
        "max_score": max_sum if done_count else None,
        "percent": percent,
    }
