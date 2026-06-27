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


def is_obligatory_lesson(node):
    """A unit that counts toward Progress: an obligatory lesson unit. The SINGLE
    source for "counts toward required_total" — build_outline's rollup reuses it."""
    return (
        node.kind == ContentNode.Kind.UNIT
        and node.unit_type == ContentNode.UnitType.LESSON
        and node.obligatory
    )


def is_quiz_unit(node):
    """A quiz unit. The SINGLE source quiz_units_in_order and the matrix share."""
    return (
        node.kind == ContentNode.Kind.UNIT
        and node.unit_type == ContentNode.UnitType.QUIZ
    )


def quiz_units_in_order(course):
    """Quiz units in depth-first pre-order — units_in_order filtered to quizzes."""
    return [n for n in units_in_order(course) if is_quiz_unit(n)]


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
            obligatory = is_obligatory_lesson(node)
            is_lesson = node.unit_type == ContentNode.UnitType.LESSON
            d["required_total"] = 1 if obligatory else 0
            d["required_done"] = 1 if (obligatory and node.pk in completed) else 0
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


def _quiz_review_maps(unit_pks, submissions):
    """Batched maps over a set of quiz units + submissions (shared by
    build_course_results and build_results_matrix). Returns:
      has_auto[unit_id]        -> bool (unit has ≥1 AUTO question)
      total_review[unit_id]    -> int  (# of [R] elements)
      reviewed_counts[sub_id]  -> int  (# reviewed [R] responses)
    """
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS
    }
    has_auto, total_review = {}, {}
    elements = Element.objects.filter(
        unit_id__in=unit_pks, content_type_id__in=question_ct_ids
    ).prefetch_related("content_object")
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode == QuestionElement.MarkingMode.AUTO:
            has_auto[el.unit_id] = True
        elif q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            total_review[el.unit_id] = total_review.get(el.unit_id, 0) + 1
    reviewed_counts = dict(
        QuestionResponse.objects.filter(
            submission__in=submissions,
            reviewed_at__isnull=False,
            element__content_type_id__in=question_ct_ids,
        )
        .values_list("submission_id")
        .annotate(n=Count("id"))
    )
    return has_auto, total_review, reviewed_counts


def submission_is_counted(sub, total_review, reviewed_counts):
    """SUBMITTED ∧ not pending (every [R] reviewed). The single rule the matrix
    and build_course_results share for "this submission's score counts"."""
    if sub.status != QuizSubmission.Status.SUBMITTED:
        return False
    total_r = total_review.get(sub.unit_id, 0)
    reviewed_r = reviewed_counts.get(sub.pk, 0)
    return not (total_r > 0 and reviewed_r < total_r)


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

    has_auto, total_review, reviewed_counts = _quiz_review_maps(
        unit_pks, submissions.values()
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
                    "submission_pk": None,
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
                    "submission_pk": sub.pk,
                    "url_name": "courses:quiz_unit",
                }
            )
            continue
        # SUBMITTED
        graded = has_auto.get(unit.pk, False)  # ≡ max_score > 0 (max_marks >= 0.01)
        pending = not submission_is_counted(sub, total_review, reviewed_counts)
        rows.append(
            {
                "unit": unit,
                "status": "awaiting_review" if pending else "submitted",
                "graded": graded,
                "score": sub.score,
                "max_score": sub.max_score,
                "pending": pending,
                "submission_pk": sub.pk,
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


def _quiz_pill(row):
    """Map a build_course_results row to a single-sourced status pill (spec §6)."""
    status = row["status"]
    if status == "submitted":
        if row["graded"] and row["max_score"]:
            # reuse the single-source percent rule (_pct guarantees b > 0, met here)
            return {
                "kind": "scored",
                "score": row["score"],
                "max_score": row["max_score"],
                "percent": _pct(row["score"], row["max_score"]),
            }
        # submitted but ungraded (max_score == 0): no percent
        return {"kind": "submitted"}
    if status == "awaiting_review":
        return {"kind": "awaiting", "submission_pk": row["submission_pk"]}
    if status == "in_progress":
        return {"kind": "in_progress"}
    return {"kind": "not_started"}


def build_student_breakdown(course, student):
    """Compose build_outline + build_course_results into one teacher-facing tree
    (spec §3). NOT pure — calls two query-backed builders. Quiz units gain `pill`."""
    tree = build_outline(course, student)
    results = build_course_results(course, student)
    pill_by_unit = {r["unit"].pk: _quiz_pill(r) for r in results["rows"]}

    def attach(nodes):
        for d in nodes:
            node = d["node"]
            if d["is_unit"] and node.unit_type == ContentNode.UnitType.QUIZ:
                d["pill"] = pill_by_unit.get(node.pk)
            attach(d["children"])

    attach(tree)
    return {"student": student, "tree": tree}


def frontier_columns(course, expanded_pks):
    """Recursive drill-down columns + a nested header structure (spec §1).

    One `course.nodes` query + a parent_id-grouped recursion. A node whose pk is
    in `expanded_pks` AND has children is recursed THROUGH (it becomes a spanning
    header cell, never a leaf column); every other node is a leaf column. Returns:
      columns        -- flat leaf-frontier list, pre-order; drives the body cells.
                        Each carries lesson_pks/quiz_pks/expandable/depth + own title.
      expanded_nodes -- the pks recursed through (the view's round-tripped expand set).
      header_rows    -- one list of header cells per depth level, for a nested
                        <thead>: a leaf cell rowspans down to the bottom row; an
                        expanded (internal) cell colspans its leaf descendants. Each
                        cell carries its OWN title (the nesting supplies context, so
                        no breadcrumb), is_leaf, expandable, depth, colspan, rowspan.
      total_rows     -- number of header rows (= max leaf depth + 1, or 0 if empty).
    Pure: no `user`, no DB beyond the one nodes query.
    """
    nodes = list(course.nodes.all())
    children = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)

    def subtree_pks(root):
        lesson_pks, quiz_pks = set(), set()
        stack = [root]
        while stack:
            n = stack.pop()
            if is_obligatory_lesson(n):
                lesson_pks.add(n.pk)
            elif is_quiz_unit(n):
                quiz_pks.add(n.pk)
            stack.extend(children.get(n.pk, []))
        return lesson_pks, quiz_pks

    columns = []
    expanded_nodes = []
    cells_by_depth = {}

    def walk(parent_id, depth):
        """Append leaf columns + header cells (pre-order); return the leaf count
        produced under parent_id (= the colspan of an expanded ancestor)."""
        leaves = 0
        for node in children.get(parent_id, []):
            kids = children.get(node.pk, [])
            if node.pk in expanded_pks and kids:
                expanded_nodes.append({"node": node, "pk": node.pk})
                cell = {
                    "node": node,
                    "title": node.title,
                    "is_leaf": False,
                    "expandable": False,
                    "depth": depth,
                }
                cells_by_depth.setdefault(depth, []).append(cell)
                cell["colspan"] = walk(node.pk, depth + 1)
                leaves += cell["colspan"]
            else:
                lesson_pks, quiz_pks = subtree_pks(node)
                columns.append(
                    {
                        "node": node,
                        "title": node.title,
                        "lesson_pks": lesson_pks,
                        "quiz_pks": quiz_pks,
                        "expandable": bool(kids),
                        "depth": depth,
                    }
                )
                cells_by_depth.setdefault(depth, []).append(
                    {
                        "node": node,
                        "title": node.title,
                        "is_leaf": True,
                        "expandable": bool(kids),
                        "depth": depth,
                        "colspan": 1,
                    }
                )
                leaves += 1
        return leaves

    walk(None, 0)

    total_rows = (max(cells_by_depth) + 1) if cells_by_depth else 0
    for depth, cells in cells_by_depth.items():
        for cell in cells:
            # leaves span down to the bottom row; expanded cells span only their row
            cell["rowspan"] = (total_rows - depth) if cell["is_leaf"] else 1
    header_rows = [cells_by_depth[d] for d in range(total_rows)]

    return {
        "columns": columns,
        "expanded_nodes": expanded_nodes,
        "header_rows": header_rows,
        "total_rows": total_rows,
    }


def build_matrix_columns(course):
    """Depth-1 roots as analytics columns (the un-expanded frontier). Thin alias
    over frontier_columns so the single walk stays single-source (spec §2)."""
    return frontier_columns(course, frozenset())["columns"]


def _pct(a, b):
    """Whole-number percent, rounded once (ROUND_HALF_EVEN). Caller guarantees b>0."""
    return int(round(Decimal(100) * Decimal(a) / Decimal(b)))


def _cell(percent):
    return {"percent": percent, "label": f"{percent}%" if percent is not None else "—"}


def _avg_cell(percents):
    defined = [p for p in percents if p is not None]
    if not defined:
        return _cell(None)
    return _cell(int(round(Decimal(sum(defined)) / Decimal(len(defined)))))


def _public_columns(columns):
    return [
        {"node": c["node"], "title": c["title"], "expandable": c["expandable"]}
        for c in columns
    ]


def build_progress_matrix(course, students, expanded=frozenset()):
    """Required-lesson completion %, students × frontier columns. No N+1. See spec."""
    students = list(students)
    fc = frontier_columns(course, expanded)
    columns = fc["columns"]
    all_lesson_pks = set()
    for c in columns:
        all_lesson_pks |= c["lesson_pks"]
    completed = {}
    if all_lesson_pks and students:
        for sid, uid in UnitProgress.objects.filter(
            unit_id__in=all_lesson_pks, completed=True, student__in=students
        ).values_list("student_id", "unit_id"):
            completed.setdefault(sid, set()).add(uid)
    rows = []
    for s in students:
        done_set = completed.get(s.id, set())
        cells = []
        tot_done = tot_total = 0
        for c in columns:
            total = len(c["lesson_pks"])
            if total == 0:
                cells.append(_cell(None))
                continue
            done = len(done_set & c["lesson_pks"])
            tot_done += done
            tot_total += total
            cells.append(_cell(_pct(done, total)))
        overall = _cell(_pct(tot_done, tot_total) if tot_total else None)
        rows.append({"student": s, "cells": cells, "overall": overall})
    averages = [
        _avg_cell([r["cells"][i]["percent"] for r in rows]) for i in range(len(columns))
    ]
    overall_average = _avg_cell([r["overall"]["percent"] for r in rows])
    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "has_quizzes": any(c["quiz_pks"] for c in columns),
        "expanded_nodes": fc["expanded_nodes"],
        "header_rows": fc["header_rows"],
        "total_rows": fc["total_rows"],
        "mode": "progress",
    }


def build_results_matrix(course, students, expanded=frozenset()):
    """Quiz score %, students × frontier columns. Excludes not-started /
    in-progress / awaiting-review from the ratio (neutral, not 0). No N+1."""
    students = list(students)
    fc = frontier_columns(course, expanded)
    columns = fc["columns"]
    all_quiz_pks = set()
    for c in columns:
        all_quiz_pks |= c["quiz_pks"]
    subs = list(
        QuizSubmission.objects.filter(unit_id__in=all_quiz_pks, student__in=students)
    )
    _, total_review, reviewed_counts = _quiz_review_maps(all_quiz_pks, subs)
    counted = {}  # (student_id, unit_id) -> (score, max)
    for sub in subs:
        if submission_is_counted(sub, total_review, reviewed_counts):
            counted[(sub.student_id, sub.unit_id)] = (
                sub.score or Decimal("0"),
                sub.max_score or Decimal("0"),
            )
    rows = []
    for s in students:
        cells = []
        tot_e = tot_m = Decimal("0")
        for c in columns:
            earned = Decimal("0")
            mx = Decimal("0")
            for uid in c["quiz_pks"]:
                pair = counted.get((s.id, uid))
                if pair is not None:
                    earned += pair[0]
                    mx += pair[1]
            if mx > 0:
                tot_e += earned
                tot_m += mx
                cells.append(_cell(_pct(earned, mx)))
            else:
                cells.append(_cell(None))
        overall = _cell(_pct(tot_e, tot_m) if tot_m > 0 else None)
        rows.append({"student": s, "cells": cells, "overall": overall})
    averages = [
        _avg_cell([r["cells"][i]["percent"] for r in rows]) for i in range(len(columns))
    ]
    overall_average = _avg_cell([r["overall"]["percent"] for r in rows])
    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "has_quizzes": bool(all_quiz_pks),
        "expanded_nodes": fc["expanded_nodes"],
        "header_rows": fc["header_rows"],
        "total_rows": fc["total_rows"],
        "mode": "results",
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
