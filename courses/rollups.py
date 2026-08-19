"""Pre-order tree walks: units into outlines, quiz lists, and result rollups."""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count
from django.utils.translation import gettext_lazy

from courses.htmlsandbox import titles_have_math
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

# The separator used in hidden_path, which is READ ALOUD (it is the ellipsis crumb's
# accessible name). Deliberately NOT the visible "›": the visible separators are
# aria-hidden precisely so AT never announces the glyph's Unicode name, and joining
# hidden_path with it would put the glyph straight back into the accessibility tree.
# The visible glyph is authored only in templates/courses/_unit_crumbs.html.
HIDDEN_PATH_SEP = ", "

# The three draft-filtering modes. `with_data` is the set of unit pks that hold
# data (>=1 QuizSubmission or >=1 UnitProgress); it is REQUIRED when
# drafts == "keep-with-data" and ignored otherwise.
DRAFTS_MODES = ("hide", "keep", "keep-with-data")


def _check_drafts(drafts, with_data):
    """Validate at the TOP of every public helper, before any traversal.

    NOT a bare `assert`: those are stripped under python -O and raise
    AssertionError, which no caller catches.

    NOT a check inside unit_is_visible: that runs per node, so a course with
    ZERO units would never reach it and the guard would be absent exactly
    where a brand-new course is concerned.

    None is the sentinel, NOT emptiness: an empty with_data is the ordinary
    state of a course no student has touched and must never raise.
    """
    if drafts not in DRAFTS_MODES:
        raise ValueError(f"unknown drafts mode {drafts!r}")
    if drafts == "keep-with-data" and with_data is None:
        raise ValueError("drafts='keep-with-data' requires with_data")


def unit_is_visible(node, *, drafts, with_data):
    """Whether this unit gets a dict in the outline tree at all. The ONE gate.

    In all three modes "appears in the tree" and "counts toward the totals"
    are the SAME condition, so there is no second, counter-level gate to
    write. Do not add a publish check to the rollup expressions: with the
    dict already gone those checks can never fire, and any test written
    against them passes vacuously on every mutant.
    """
    if drafts == "keep" or node.published:
        return True
    if drafts == "keep-with-data":
        return node.pk in (with_data or frozenset())
    return False


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


def units_in_order(course, *, drafts="keep", with_data=None):
    """Flat list of all leaf units (lessons AND quizzes) in outline pre-order.

    Quizzes have required_total == 0 but are still navigable units — they are NOT
    dropped here. Crosses chapter/part boundaries.

    Defaults to "keep" — its existing callers include the builder, the link
    picker and the exporter, where dropping drafts is data loss on transfer.
    Student-facing callers must opt in to "hide" explicitly.
    """
    _check_drafts(drafts, with_data)
    return [
        n
        for n in _walk_preorder(course)
        if n.kind == ContentNode.Kind.UNIT
        and unit_is_visible(n, drafts=drafts, with_data=with_data)
    ]


def units_under(node, *, drafts="keep", with_data=None):
    """Every unit ContentNode in the subtree rooted at `node`, inclusive.

    A SET, not an ordered list: reset does not care about order, so the pre-order
    subtlety _walk_preorder warns about (sibling `order` is only locally monotonic)
    is irrelevant here and must not be cargo-culted in. _walk_preorder itself cannot
    serve: it walks from parent_id=None over a WHOLE course and cannot start from an
    arbitrary node.
    """
    _check_drafts(drafts, with_data)
    if node.kind == ContentNode.Kind.UNIT:
        return (
            {node}
            if unit_is_visible(node, drafts=drafts, with_data=with_data)
            else set()
        )
    children = {}
    for n in node.course.nodes.all():
        children.setdefault(n.parent_id, []).append(n)
    out = set()
    stack = list(children.get(node.pk, []))
    while stack:
        cur = stack.pop()
        if cur.kind == ContentNode.Kind.UNIT:
            if unit_is_visible(cur, drafts=drafts, with_data=with_data):
                out.add(cur)
        else:
            stack.extend(children.get(cur.pk, []))
    return out


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


MARKER_NONE = ""
MARKER_QUIZ = "quiz"
MARKER_ADDITIONAL = "additional"

UNIT_MARKER_LABELS = {
    MARKER_QUIZ: gettext_lazy("Quiz"),
    MARKER_ADDITIONAL: gettext_lazy("Additional"),
}


def unit_marker(node):
    """MARKER_QUIZ | MARKER_ADDITIONAL | MARKER_NONE — the ONE student-facing kind rule.

    MARKER_NONE for a required lesson (the unmarked default), for any non-unit
    node, for a unit whose unit_type is unset, AND for anything that is not a
    node at all. A quiz is never 'additional': is_obligatory_lesson already
    excludes quizzes from required_total, so `obligatory` on a quiz node has no
    student meaning.

    The `additional` branch is written out rather than composed from the two
    existing predicates: is_quiz_unit and is_obligatory_lesson BOTH return False
    for an additional lesson, a non-unit node, and an unset unit_type, so a
    function built only from those two cannot tell the three apart. Do not
    "simplify" it to `not is_obligatory_lesson(node)`.
    """
    # getattr, not node.kind: a template that includes a marker partial without
    # `with node=...` resolves the variable to string_if_invalid (default ''),
    # and a bare attribute access — or handing '' straight to is_quiz_unit —
    # raises AttributeError and 500s the course outline. Fail quiet instead.
    if getattr(node, "kind", None) != ContentNode.Kind.UNIT:
        return MARKER_NONE
    if is_quiz_unit(node):
        return MARKER_QUIZ
    if node.unit_type == ContentNode.UnitType.LESSON and not node.obligatory:
        return MARKER_ADDITIONAL
    return MARKER_NONE


def marker_label(marker):
    """Marker key -> translated word; "" for MARKER_NONE or any unknown key.

    Keyed on the marker, not the node: both partials already hold `m` from their
    own {% with %}, so this avoids deriving the marker a second time.
    """
    return UNIT_MARKER_LABELS.get(marker, "")


def quiz_units_in_order(course, *, drafts="keep", with_data=None):
    """Quiz units in depth-first pre-order — units_in_order filtered to quizzes."""
    return [
        n
        for n in units_in_order(course, drafts=drafts, with_data=with_data)
        if is_quiz_unit(n)
    ]


def build_outline(course, user, *, drafts="hide", with_data=None):
    """Return a nested list of node dicts with required/additional rollups.

    Folds the shared _walk_preorder stream into a tree (pre-order guarantees a parent
    is yielded before its children, so the parent dict exists when a child arrives),
    then a post-order pass sums the rollups. Two queries (nodes + the user's completed
    unit ids). `required` counts only obligatory lesson units; `additional_done` counts
    completed non-obligatory lesson units; quiz units are excluded from both.

    `drafts`/`with_data` are validated here only in this task — the filtering
    itself (dict-creation gating + container pruning) is Task 5's deliverable.
    """
    _check_drafts(drafts, with_data)
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
        if is_unit and not unit_is_visible(node, drafts=drafts, with_data=with_data):
            continue
        d = {
            "node": node,
            "children": [],
            "required_total": 0,
            "required_done": 0,
            "additional_done": 0,
            "is_unit": is_unit,
            "completed": is_unit and node.pk in completed,
            # Additive only: build_outline also feeds build_unit_nav (the rail),
            # build_student_breakdown (the teacher tree) and outline_with_tags,
            # all of which ignore this key. Pre-order guarantees the parent dict
            # exists; pruning runs after the fold and never re-parents, so a depth
            # assigned here stays correct.
            "depth": 0
            if node.parent_id is None
            else by_pk[node.parent_id]["depth"] + 1,
        }
        by_pk[node.pk] = d
        if node.parent_id is None:
            roots.append(d)
        else:
            by_pk[node.parent_id]["children"].append(d)

    prune = drafts != "keep-with-data"

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
            if prune:
                d["children"] = [
                    k for k in d["children"] if k["is_unit"] or k["children"]
                ]
            d["required_total"] = sum(k["required_total"] for k in d["children"])
            d["required_done"] = sum(k["required_done"] for k in d["children"])
            d["additional_done"] = sum(k["additional_done"] for k in d["children"])

    for r in roots:
        rollup(r)
    if prune:
        roots = [r for r in roots if r["is_unit"] or r["children"]]
    return roots


def tree_titles_have_math(tree):
    """True iff any node title anywhere in a build_outline tree carries maths.

    COLLECT + MUST RECURSE, the same shape as _tabs_has_math (courses/views.py):
    on a unit page the contents tree is unit_nav["tree"], which build_unit_nav
    sets to the ENTIRE course outline, and _unit_tree_node.html renders all of
    it into the DOM whether collapsed or not. Scanning only the current unit and
    its prev/next therefore leaves a maths title three sections away rendering
    raw -- and it fails SILENTLY, since the page looks correct for the unit under
    test.

    Delegates its leaf test to titles_have_math (which delegates to
    has_math_delimiters); never inline a `"\\(" in title` check here.

    `item.get("children") or []` is cheap defensiveness, not a response to a
    known producer: build_outline unconditionally sets "children": [] on every
    node dict and prunes by rebuilding the list, never by deleting the key.
    """
    for item in tree or []:
        if titles_have_math([item["node"].title]):
            return True
        if tree_titles_have_math(item.get("children") or []):
            return True
    return False


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
        unit_id__in=unit_pks,
        content_type_id__in=question_ct_ids,
        parent__isnull=True,
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


def quiz_gradeable_max(units):
    """Map every unit pk to the sum of `max_marks` over its AUTO+REVIEW question
    elements (NOT_MARKED excluded) — the "fully gradeable maximum", independent of
    any submission (mirrors compute_scores's `possible` for a fully-reviewed
    submission, courses/quiz.py). Units with no gradeable questions map to 0.
    One batched Element scan (no N+1)."""
    unit_pks = [u.pk for u in units]
    result = {pk: Decimal("0") for pk in unit_pks}
    if not unit_pks:
        return result
    question_ct_ids = {
        ContentType.objects.get_for_model(m).id for m in _QUESTION_MODELS
    }
    elements = Element.objects.filter(
        unit_id__in=unit_pks,
        content_type_id__in=question_ct_ids,
        parent__isnull=True,
    ).prefetch_related("content_object")
    gradeable = {
        QuestionElement.MarkingMode.AUTO,
        QuestionElement.MarkingMode.REVIEW,
    }
    for el in elements:
        q = el.content_object
        if isinstance(q, QuestionElement) and q.marking_mode in gradeable:
            result[el.unit_id] += q.max_marks
    return result


def submission_is_counted(sub, total_review, reviewed_counts):
    """SUBMITTED ∧ not pending (every [R] reviewed). The single rule the matrix
    and build_course_results share for "this submission's score counts"."""
    if sub.status != QuizSubmission.Status.SUBMITTED:
        return False
    total_r = total_review.get(sub.unit_id, 0)
    reviewed_r = reviewed_counts.get(sub.pk, 0)
    return not (total_r > 0 and reviewed_r < total_r)


def build_course_results(course, student, *, drafts, with_data=None):
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

    `drafts` is REQUIRED (Task 8): every caller must now decide. `with_data`
    stays optional — ignored outside "keep-with-data". Validated by the
    nested quiz_units_in_order -> units_in_order call, same as before.
    """
    units = quiz_units_in_order(course, drafts=drafts, with_data=with_data)
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


def build_student_breakdown(course, student, *, drafts, with_data=None):
    """Compose build_outline + build_course_results into one teacher-facing tree
    (spec §3). NOT pure — calls two query-backed builders. Quiz units gain `pill`.

    Forwards drafts/with_data into BOTH internal calls: build_outline defaults to
    "hide", so leaving it unthreaded would drop draft units from the tree while
    pill_by_unit (from build_course_results) still carries their results.
    """
    tree = build_outline(course, student, drafts=drafts, with_data=with_data)
    results = build_course_results(course, student, drafts=drafts, with_data=with_data)
    pill_by_unit = {r["unit"].pk: _quiz_pill(r) for r in results["rows"]}

    def attach(nodes):
        for d in nodes:
            node = d["node"]
            if d["is_unit"] and node.unit_type == ContentNode.UnitType.QUIZ:
                d["pill"] = pill_by_unit.get(node.pk)
            attach(d["children"])

    attach(tree)
    return {"student": student, "tree": tree}


def frontier_columns(course, expanded_pks, *, drafts="keep", with_data=None):
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

    `drafts` defaults to "keep" (NOT "keep-with-data"): build_matrix_columns
    (test-only, Step 5) and several test call sites call this bare, and a
    restrictive default would raise on every one of them. The strictness lives
    on the matrix builders below, which take `drafts` as a required keyword
    and forward it here. Under "keep" this filtering is a total no-op — see
    the `total and` conjunct note on the drop rule below.

    A leaf/container node whose subtree HAS units and NONE of them is visible
    (per unit_is_visible) is dropped entirely: no `columns` entry, no
    `cells_by_depth`/header cell, and — if it was the expand target — no
    `expanded_nodes` entry either (it never reaches the branch that would add
    one). This drop is done INSIDE `walk`, not as a post-filter on
    `result["columns"]`: `columns`, `cells_by_depth` (-> `header_rows`), and
    the `leaves` counter (-> colspan) are three outputs of the SAME traversal,
    positionally coupled. A post-filter would leave a stale `<th>` and an
    over-counted `colspan` in `header_rows`, silently shifting every column
    header off its data for the rest of the row.
    """
    _check_drafts(drafts, with_data)
    nodes = list(course.nodes.all())
    children = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)

    def subtree_pks(root):
        """As before, but a unit only contributes to lesson_pks/quiz_pks when
        it is VISIBLE — else the matrix would divide by units it never shows."""
        lesson_pks, quiz_pks = set(), set()
        stack = [root]
        while stack:
            n = stack.pop()
            if is_obligatory_lesson(n) and unit_is_visible(
                n, drafts=drafts, with_data=with_data
            ):
                lesson_pks.add(n.pk)
            elif is_quiz_unit(n) and unit_is_visible(
                n, drafts=drafts, with_data=with_data
            ):
                quiz_pks.add(n.pk)
            stack.extend(children.get(n.pk, []))
        return lesson_pks, quiz_pks

    def unit_counts(root):
        """(total_units, visible_units) over root's subtree (inclusive)."""
        stack, total, visible = [root], 0, 0
        while stack:
            n = stack.pop()
            if n.kind == ContentNode.Kind.UNIT:
                total += 1
                visible += unit_is_visible(n, drafts=drafts, with_data=with_data)
            stack.extend(children.get(n.pk, []))
        return total, visible

    columns = []
    expanded_nodes = []
    cells_by_depth = {}

    def walk(parent_id, depth):
        """Append leaf columns + header cells (pre-order); return the leaf count
        produced under parent_id (= the colspan of an expanded ancestor)."""
        leaves = 0
        for node in children.get(parent_id, []):
            total, visible = unit_counts(node)
            # Drop ONLY when the subtree HAS units and none is visible. The
            # `total and` conjunct is load-bearing: a container with ZERO
            # units (e.g. a childless chapter) must NEVER be dropped, in any
            # mode -- including "keep", where this guard must be a no-op
            # (unit_is_visible is unconditionally True under "keep", so
            # `visible == total` always and this branch never fires).
            if total and not visible:
                # Suppresses columns.append, cells_by_depth AND leaves together.
                continue
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
                has_lessons = bool(lesson_pks)
                has_quizzes = bool(quiz_pks)
                columns.append(
                    {
                        "node": node,
                        "title": node.title,
                        "lesson_pks": lesson_pks,
                        "quiz_pks": quiz_pks,
                        "has_lessons": has_lessons,
                        "has_quizzes": has_quizzes,
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
                        "has_lessons": has_lessons,
                        "has_quizzes": has_quizzes,
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
    over frontier_columns so the single walk stays single-source (spec §2).

    Deliberately left un-parameterised (Task 8, Step 5): it has ZERO production
    callers (the real chain is views_analytics -> build_results_matrix /
    build_progress_matrix -> frontier_columns), so it stays a bare "keep" call.
    Do not add drafts/with_data here defensively — a test written against this
    alias instead of the real chain is exactly the green-but-uncovered outcome
    the analytics drill-down test (ANA3) exists to catch.
    """
    return frontier_columns(course, frozenset())["columns"]


def _pct(a, b):
    """Whole-number percent, rounded once (ROUND_HALF_EVEN). Caller guarantees b>0."""
    return int(round(Decimal(100) * Decimal(a) / Decimal(b)))


def _fmt_mark(value):
    """Decimal mark -> compact fixed-point string: no exponent notation (`:f`
    guarantees fixed-point, so Decimal('1E+2') renders '100'), no trailing zeros
    (normalize)."""
    return f"{Decimal(value).normalize():f}"


def _cell(percent, label=None):
    return {
        "percent": percent,
        "label": label
        if label is not None
        else (f"{percent}%" if percent is not None else "—"),
    }


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


def build_progress_matrix(
    course, students, expanded=frozenset(), *, drafts, with_data=None
):
    """Required-lesson completion %, students × frontier columns. No N+1. See spec.

    `drafts` is REQUIRED (Task 8): every caller — the analytics matrix view,
    the gradebook export's build_matrix_table, and tests — must decide.
    """
    _check_drafts(drafts, with_data)
    students = list(students)
    fc = frontier_columns(course, expanded, drafts=drafts, with_data=with_data)
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
        "has_lessons": any(c["lesson_pks"] for c in columns),
        "expanded_nodes": fc["expanded_nodes"],
        "header_rows": fc["header_rows"],
        "total_rows": fc["total_rows"],
        "mode": "progress",
    }


def build_results_matrix(
    course, students, expanded=frozenset(), values="percent", *, drafts, with_data=None
):
    """Quiz score %, students × frontier columns. Excludes not-started /
    in-progress / awaiting-review from the ratio (neutral, not 0). No N+1.
    values="raw" relabels cells/overall/footer as earned/max (percent kept for
    colouring); footer becomes class totals Σearned/Σmx.

    `drafts` is REQUIRED (Task 8): every caller — the analytics matrix view,
    the gradebook export's build_matrix_table, and tests — must decide.
    """
    _check_drafts(drafts, with_data)
    students = list(students)
    fc = frontier_columns(course, expanded, drafts=drafts, with_data=with_data)
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
    raw = values == "raw"

    def _score_cell(earned, mx):
        pct = _pct(earned, mx)
        if raw:
            return _cell(pct, label=f"{_fmt_mark(earned)}/{_fmt_mark(mx)}")
        return _cell(pct)

    col_e = [Decimal("0")] * len(columns)  # raw-mode per-column accumulators
    col_m = [Decimal("0")] * len(columns)
    ov_e = ov_m = Decimal("0")
    rows = []
    for s in students:
        cells = []
        tot_e = tot_m = Decimal("0")
        for i, c in enumerate(columns):
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
                col_e[i] += earned
                col_m[i] += mx
                cells.append(_score_cell(earned, mx))
            else:
                cells.append(_cell(None))
        if tot_m > 0:
            ov_e += tot_e
            ov_m += tot_m
            overall = _score_cell(tot_e, tot_m)
        else:
            overall = _cell(None)
        rows.append({"student": s, "cells": cells, "overall": overall})

    if raw:
        averages = [
            _score_cell(col_e[i], col_m[i]) if col_m[i] > 0 else _cell(None)
            for i in range(len(columns))
        ]
        overall_average = _score_cell(ov_e, ov_m) if ov_m > 0 else _cell(None)
    else:
        averages = [
            _avg_cell([r["cells"][i]["percent"] for r in rows])
            for i in range(len(columns))
        ]
        overall_average = _avg_cell([r["overall"]["percent"] for r in rows])

    return {
        "columns": _public_columns(columns),
        "rows": rows,
        "averages": averages,
        "overall_average": overall_average,
        "has_quizzes": bool(all_quiz_pks),
        "has_lessons": any(c["lesson_pks"] for c in columns),
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


def _stamp_current_chain(tree, current_pk):
    """Set contains_current on EVERY dict in a build_outline tree.

    True for the node whose pk is current_pk and for every ancestor of it; False
    everywhere else. The key is always present so callers (and the template's
    {% if item.contains_current %}) never have to distinguish absent from False.

    Pure dict mutation over an already-materialised tree — no queries. Units are
    stamped too, which is what lets _top_level_part still return a root that IS the
    current unit (the depth-1 part-chip case).
    """

    def walk(d):
        hit = d["node"].pk == current_pk
        for child in d["children"]:
            if walk(child):
                hit = True
        d["contains_current"] = hit
        return hit

    for root in tree:
        walk(root)


def _top_level_part(tree):
    """The root dict whose subtree contains the current node, or None.

    REQUIRES a tree already stamped by _stamp_current_chain. If current_pk is itself a
    root, returns that root dict (its is_unit tells the caller it is a depth-1 unit with
    no enclosing part). Reads the flag directly, not via .get(), so an unstamped tree
    raises KeyError loudly instead of silently blanking part_progress.
    """
    for root in tree:
        if root["contains_current"]:
            return root
    return None


def _current_ancestors(tree):
    """Root→parent ContentNodes on the stamped current chain, excluding the unit.

    REQUIRES a tree already stamped by _stamp_current_chain, and reads
    contains_current directly (not via .get()) so an unstamped tree raises KeyError
    loudly — the same contract _top_level_part uses. That is distinct from a stamped
    tree with no match, which legitimately returns [] (build_unit_nav already handles
    the no-match case defensively for prev/next).

    Pure dict traversal over an already-materialised tree — no queries.

    NOTE: courses/views_manage.py::_unit_ancestors does the same job for the BUILDER
    breadcrumb by walking node.parent. The duplication is deliberate: the builder side
    has no materialised tree to read from, so a parent walk is right there, whereas
    here a walk would cost up to 3 extra queries per page load.
    """
    ancestors = []
    level = tree
    while True:
        match = next((d for d in level if d["contains_current"]), None)
        if match is None:
            return ancestors
        if not match["is_unit"]:
            ancestors.append(match["node"])
        level = match["children"]


def build_unit_nav(course, user, current_node, *, drafts="hide", with_data=None):
    """Pure navigation context for a unit page (mirrors build_lesson_context's role:
    the single source both unit views call, so they cannot drift).

    Returns {tree, current_pk, prev, next, part_progress, course_progress, ancestors,
    hidden_path}. ancestors is the root→parent chain of the current unit (0–3 nodes,
    unit excluded); hidden_path joins all but the deepest with HIDDEN_PATH_SEP and is
    the collapsed "…" crumb's tooltip and accessible name. Prev/Next
    are the immediate neighbours of current_node among the is_unit leaves of the
    already-computed build_outline tree, located by pk (the walk builds its own node
    instances, distinct from the view's current_node). No queries beyond
    build_outline's.

    Forwards drafts/with_data into build_outline and computes nothing itself: it
    has no unit list of its own to filter, only the tree build_outline returns.
    """
    tree = build_outline(course, user, drafts=drafts, with_data=with_data)
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
    _stamp_current_chain(tree, current_node.pk)
    top = _top_level_part(tree)
    if top is not None and not top["is_unit"] and top["required_total"] > 0:
        part_progress = {
            "done": top["required_done"],
            "total": top["required_total"],
            "title": top["node"].title,
        }

    ancestors = _current_ancestors(tree)

    return {
        "tree": tree,
        "current_pk": current_node.pk,
        "prev": prev_node,
        "next": next_node,
        "part_progress": part_progress,
        "course_progress": course_progress,
        "ancestors": ancestors,
        "hidden_path": HIDDEN_PATH_SEP.join(a.title for a in ancestors[:-1]),
    }


def build_resume(course, user, tree):
    """The outline resume card's target, or None when there is nothing to resume.

    Consumes the caller's ALREADY-BUILT build_outline tree -- never rebuilds it, so
    the card costs no extra tree queries. Returns
    {"node": ContentNode, "state": str, "ancestors": [ContentNode]} or None.

    `node` is the ContentNode (leaf["node"]), NEVER the build_outline leaf dict:
    a dict reaches {% url ... node_pk=resume.node.pk %} as "" against urls.py's
    <int:node_pk> and raises NoReverseMatch, 500-ing the whole outline.

    The 6 steps are ordered and their precedence is load-bearing; see the spec's
    "Definition of the target".
    """
    leaves = _flatten_unit_leaves(tree)
    open_leaves = [d for d in leaves if not d["completed"]]
    # STEP 1, first so no later step can index an empty candidate set. Covers both
    # "course has no visible units" and "student completed everything".
    if not open_leaves:
        return None

    open_pks = [d["node"].pk for d in open_leaves]
    leaf_pks = [d["node"].pk for d in leaves]

    # Both names are read unconditionally by steps 3 and 4 below, so any edit that
    # REPLACES rather than extends either line raises UnboundLocalError on every
    # cold path.
    flight, ts_f = None, None

    # SOURCES A/B/C -- the in-flight candidate. Membership is a filter INSIDE each
    # query (unit_id__in=open_pks), never a post-check on the LIMIT 1 result: each
    # source returns one row, so one row for a since-unpublished unit at the head of
    # the ordering would discard every older still-valid candidate behind it. It
    # also removes the join to ContentNode -- open_pks is already course-scoped and
    # visibility-filtered.
    #
    # Each ordering carries a deterministic secondary key. For A/B the (student,
    # unit) unique constraint makes -unit_id pin the row; for C it pins the UNIT,
    # which is all the algorithm needs.
    #
    # A -- lesson work. updated_at is auto_now: the first open in
    # views.py::build_lesson_context, every `seen` batch, every practice-state write.
    # NOTE: completed=False here is DELIBERATE REDUNDANCY and is NOT falsifiable --
    # open_pks is derived from exactly this filter (build_outline's completed set,
    # rollups.py:244-250, leaf key at :265), so no mutant of it can go RED. It
    # states the intent locally; do not spend a falsification round on it.
    a = (
        UnitProgress.objects.filter(student=user, unit_id__in=open_pks, completed=False)
        .order_by("-updated_at", "-unit_id")
        .values_list("unit_id", "updated_at")
        .first()
    )
    # B -- WHEN THE QUIZ WAS OPENED, and nothing more. QuizSubmission.updated is
    # auto_now (models.py:3008) and the answer path (views.py::quiz_answer) saves the
    # QuestionResponse and creates an Attempt but NEVER saves the submission, so for
    # an IN_PROGRESS row updated == created in practice.
    # status=IN_PROGRESS here IS load-bearing and IS tested: closing a submission
    # normally writes UnitProgress.completed, but seed_demo_course.py:346/414
    # finalizes without any UnitProgress row, so a SUBMITTED submission's unit can
    # still be in open_pks.
    b = (
        QuizSubmission.objects.filter(
            student=user,
            unit_id__in=open_pks,
            status=QuizSubmission.Status.IN_PROGRESS,
        )
        .order_by("-updated", "-unit_id")
        .values_list("unit_id", "updated")
        .first()
    )
    # C -- ACTUAL quiz answering, and the only source that can see it. The
    # values_list projection is NORMATIVE: C's unit_id lives on the joined
    # QuizSubmission, so `.first()` then `row.submission.unit_id` would cost a
    # SECOND query and silently break the 4-query budget.
    # last_attempt_at__isnull=False is required: Postgres sorts NULLs FIRST under
    # DESC, so without it a null row wins the LIMIT 1 and the step-3 comparison
    # raises TypeError against None.
    c = (
        QuestionResponse.objects.filter(
            submission__student=user,
            submission__unit_id__in=open_pks,
            submission__status=QuizSubmission.Status.IN_PROGRESS,
            last_attempt_at__isnull=False,
        )
        .order_by("-last_attempt_at", "-submission__unit_id")
        .values_list("submission__unit_id", "last_attempt_at")
        .first()
    )

    # Assembly order A, B, C is NORMATIVE. max() returns the FIRST maximal element,
    # so with source_rank dropped an A-then-C order yields A while the correct build
    # yields C -- that ordering is what makes the rank mutant killable. Assembling
    # [C, B, A] would make the mutant coincidentally right.
    by_pk = {d["node"].pk: d["node"] for d in open_leaves}
    candidates = [
        (row[1], rank, row[0]) for rank, row in enumerate((a, b, c)) if row is not None
    ]
    if candidates:
        ts_f, _rank, flight_pk = max(candidates, key=lambda t: (t[0], t[1]))
        flight = by_pk[flight_pk]

    done, ts_d = None, None

    # STEP 3. Both names are already bound, so this runs correctly in every task.
    # The ts comparison is ESSENTIAL: views.py::build_lesson_context mints a
    # UnitProgress row on EVERY enrolled lesson GET, so without it one stray click
    # a year ago pins the card to that unit forever. >= (not >) keeps an in-flight
    # unit winning a tie -- the friendlier reading of "where you left off".
    if flight is not None and (done is None or ts_f >= ts_d):
        return {"node": flight, "state": "resume", "ancestors": []}

    # STEP 4. `done` is a pk; its POSITION in the outline is what matters. Dead
    # until source D assigns `done`; laid down here so the control flow is final.
    if done is not None:
        idx = next(i for i, leaf in enumerate(leaves) if leaf["node"].pk == done)
        # No default on next(): source D filters unit_id__in=leaf_pks, so a missing
        # index is an invariant break and should raise StopIteration loudly rather
        # than degrade into a TypeError four lines later. Same house style as
        # _current_ancestors raising KeyError on an unstamped tree.
        forward = next(
            (
                leaf
                for i, leaf in enumerate(leaves)
                if i > idx and not leaf["completed"]
            ),
            None,
        )
        if forward is not None:
            return {"node": forward["node"], "state": "next", "ancestors": []}
        # The wrap-around: they finished the last unit but skipped something. A card
        # that vanishes while unfinished units remain is worse than one pointing
        # back. Its own state, because "Up next" is false about an EARLIER unit.
        return {"node": open_leaves[0]["node"], "state": "gap", "ancestors": []}

    # STEP 5: the student has history, but all of it is on units that are no longer
    # visible. Deliberately UNFILTERED by open/leaves and by status -- that is the
    # whole point: these two probes are the only thing that can see such rows, and
    # they are what stops step 6 lying to the student. Lazy: only reached when
    # steps 3-4 both fail. `or` short-circuits, so this costs 1 query or 2.
    has_history = (
        UnitProgress.objects.filter(student=user, unit__course=course).exists()
        or QuizSubmission.objects.filter(student=user, unit__course=course).exists()
    )
    if has_history:
        return {"node": open_leaves[0]["node"], "state": "next", "ancestors": []}

    # STEP 6: genuinely nothing.
    return {"node": open_leaves[0]["node"], "state": "start", "ancestors": []}
