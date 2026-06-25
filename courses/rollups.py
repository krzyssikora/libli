from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count

from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import MatchPairQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
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


def _walk_preorder(course):
    """Yield every ContentNode of `course` in depth-first pre-order.

    The SINGLE shared traversal. One query (course.nodes.all(), Meta.ordering =
    ["order", "pk"]); parent_id-grouped recursion (sibling `order` is only locally
    monotonic, so a flat scan of nodes.all() is NOT pre-order). build_outline folds
    this stream into its nested tree; units_in_order / quiz_units_in_order filter it.
    """
    nodes = list(course.nodes.all())
    children = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)

    def walk(parent_id):
        for node in children.get(parent_id, []):
            yield node
            yield from walk(node.pk)

    yield from walk(None)


def units_in_order(course):
    """Flat list of all leaf units (lessons AND quizzes) in outline pre-order.

    Quizzes have required_total == 0 but are still navigable units — they are NOT
    dropped here. Crosses chapter/part boundaries.
    """
    return [n for n in _walk_preorder(course) if n.kind == ContentNode.Kind.UNIT]


def quiz_units_in_order(course):
    """Quiz units (kind=UNIT, unit_type=QUIZ) in depth-first pre-order — units_in_order
    filtered to quizzes, so it cannot diverge from the shared walk."""
    return [
        n for n in units_in_order(course) if n.unit_type == ContentNode.UnitType.QUIZ
    ]


def build_outline(course, user):
    """Return a nested list of node dicts with required/additional rollups.

    Folds the shared _walk_preorder stream into a tree (pre-order guarantees a parent
    is yielded before its children, so the parent dict exists when a child arrives),
    then a post-order pass sums the rollups. Two queries (nodes + the user's completed
    unit ids). `required` counts only obligatory lesson units; `additional_done` counts
    completed non-obligatory lesson units; quiz units are excluded from both.
    """
    completed = set()
    if user.is_authenticated:
        completed = set(
            UnitProgress.objects.filter(
                student=user, unit__course=course, completed=True
            ).values_list("unit_id", flat=True)
        )

    by_pk = {}
    roots = []
    for node in _walk_preorder(course):
        is_unit = node.kind == ContentNode.Kind.UNIT
        d = {
            "node": node,
            "children": [],
            "required_total": 0,
            "required_done": 0,
            "additional_done": 0,
            "is_unit": is_unit,
            "completed": is_unit and node.pk in completed,
        }
        by_pk[node.pk] = d
        if node.parent_id is None:
            roots.append(d)
        else:
            by_pk[node.parent_id]["children"].append(d)

    def rollup(d):
        node = d["node"]
        if d["is_unit"]:
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            d["required_total"] = 1 if (is_lesson and node.obligatory) else 0
            d["required_done"] = (
                1 if (d["required_total"] and node.pk in completed) else 0
            )
            d["additional_done"] = (
                1 if (is_lesson and not node.obligatory and node.pk in completed) else 0
            )
        else:
            for k in d["children"]:
                rollup(k)
            d["required_total"] = sum(k["required_total"] for k in d["children"])
            d["required_done"] = sum(k["required_done"] for k in d["children"])
            d["additional_done"] = sum(k["additional_done"] for k in d["children"])

    for r in roots:
        rollup(r)
    return roots


def build_course_results(course, student):
    """Per-course quiz summary for one student (the viewing user). Pure of side
    effects. Sums the headline over SUBMITTED quizzes only, excluding quizzes
    that are still awaiting review (i.e. have ≥1 unreviewed [R] element).

    A SUBMITTED quiz is `awaiting_review` only while reviewed_R_count <
    total_R_count for that submission; once all [R] responses carry
    `reviewed_at`, the status flips to `submitted` and the quiz's score enters
    the headline sums.  `done_count` still counts every SUBMITTED row
    regardless of pending state.

    Four fixed queries after the ContentType cache warms:
      1. quiz_units_in_order  (one query for course.nodes)
      2. QuizSubmission filter  (one query)
      3. Element filter + prefetch_related  (one query + one prefetch for questions)
      4. QuestionResponse reviewed-count aggregation  (one batched annotate query)
    """
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
    total_review = {}  # unit_id -> count of [R] elements
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
            total_review[el.unit_id] = total_review.get(el.unit_id, 0) + 1

    # ONE batched query: count reviewed [R] QuestionResponse rows per submission.
    # An unanswered [R] has no row, so missing entries in this dict mean 0 reviewed.
    # Filtering by question content-type (not marking_mode) is correct because only
    # [R] responses ever get reviewed_at set today; if an [A] path ever stamps
    # reviewed_at, add `element__object_id`/marking_mode scoping to avoid overcounting.
    reviewed_counts = dict(
        QuestionResponse.objects.filter(
            submission__in=submissions.values(),
            reviewed_at__isnull=False,
            element__content_type_id__in=question_ct_ids,
        )
        .values_list("submission_id")
        .annotate(n=Count("id"))
    )

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
        total_r = total_review.get(unit.pk, 0)
        reviewed_r = reviewed_counts.get(sub.pk, 0)
        pending = total_r > 0 and reviewed_r < total_r
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
        done_count += 1  # unchanged: pending still counts as submitted
        if not pending:
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


def _flatten_unit_leaves(tree):
    """The is_unit leaf dicts of a build_outline tree, in outline order (same order
    as units_in_order — both originate from _walk_preorder)."""
    leaves = []

    def collect(items):
        for d in items:
            if d["is_unit"]:
                leaves.append(d)
            else:
                collect(d["children"])

    collect(tree)
    return leaves


def _top_level_part(tree, current_pk):
    """The root dict whose subtree contains current_pk (the top-level ancestor), or
    None. If current_pk is itself a root, returns that root dict (its is_unit tells the
    caller it is a depth-1 unit with no enclosing part)."""

    def contains(d):
        return d["node"].pk == current_pk or any(contains(c) for c in d["children"])

    for root in tree:
        if contains(root):
            return root
    return None


def build_unit_nav(course, user, current_node):
    """Pure navigation context for a unit page (mirrors build_lesson_context's role:
    the single source both unit views call, so they cannot drift).

    Returns {tree, current_pk, prev, next, part_progress, course_progress}. Prev/Next
    are the immediate neighbours of current_node among the is_unit leaves of the
    already-computed build_outline tree, located by pk (the walk builds its own node
    instances, distinct from the view's current_node). No queries beyond
    build_outline's.

    """
    tree = build_outline(course, user)
    leaves = _flatten_unit_leaves(tree)
    units = [d["node"] for d in leaves]

    idx = next((i for i, n in enumerate(units) if n.pk == current_node.pk), None)
    prev_node = units[idx - 1] if (idx is not None and idx > 0) else None
    next_node = units[idx + 1] if (idx is not None and idx < len(units) - 1) else None

    course_progress = {
        "done": sum(d["required_done"] for d in tree),
        "total": sum(d["required_total"] for d in tree),
    }

    part_progress = None
    top = _top_level_part(tree, current_node.pk)
    if top is not None and not top["is_unit"] and top["required_total"] > 0:
        part_progress = {
            "done": top["required_done"],
            "total": top["required_total"],
            "title": top["node"].title,
        }

    return {
        "tree": tree,
        "current_pk": current_node.pk,
        "prev": prev_node,
        "next": next_node,
        "part_progress": part_progress,
        "course_progress": course_progress,
    }
