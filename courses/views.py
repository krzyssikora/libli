import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
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
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from courses import quiz as quiz_svc
from courses import state as state_svc
from courses.access import can_access_course
from courses.access import can_see_drafts
from courses.access import get_node_or_404
from courses.access import is_enrolled
from courses.constants import COURSE_LANGUAGES
from courses.htmlsandbox import has_math_delimiters
from courses.htmlsandbox import titles_have_math
from courses.marking import MarkResult  # noqa: F401  (documents the return type)
from courses.marking import blank_matches
from courses.marking import parse_number
from courses.models import Attempt  # noqa: F401
from courses.models import BeforeAfterElement
from courses.models import CalloutElement
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Course
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import FillGateElement
from courses.models import FillTableElement
from courses.models import GuessNumberElement
from courses.models import MarkDoneElement
from courses.models import MatchPairQuestionElement
from courses.models import MathElement
from courses.models import MultiGridQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import SlideBreakElement
from courses.models import SpoilerElement
from courses.models import StepperElement
from courses.models import Subject
from courses.models import SwitchGateElement
from courses.models import SwitchGridElement
from courses.models import TextElement
from courses.models import UnitProgress
from courses.numbering import callout_numbers
from courses.quiz import answer_from_json
from courses.quiz import answer_is_empty  # noqa: F401
from courses.quiz import answer_to_json  # noqa: F401
from courses.quiz import ephemeral_quiz_feedback
from courses.quiz import locked_after
from courses.quiz import parse_attempt
from courses.quiz import quiz_feedback_context
from courses.quiz import rehydrate  # noqa: F401
from courses.quiz import selected_ids
from courses.rendering import unit_edit_context
from courses.rollups import build_course_results
from courses.rollups import build_outline
from courses.rollups import build_resume
from courses.rollups import build_unit_nav
from courses.rollups import tree_titles_have_math
from courses.rollups import units_in_order
from courses.rollups import units_under
from courses.scoring import earned_marks
from courses.scoring import to_stored_fraction
from courses.slideshow import partition_into_slides


def _wants_fragment(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _question_has_math(q):
    """True if a question carries inline math in its stem or any of its parts —
    used to decide whether a consumption/results page must load KaTeX."""
    if has_math_delimiters(q.stem):
        return True
    if isinstance(q, ChoiceQuestionElement):
        return any(
            has_math_delimiters(c.text) or has_math_delimiters(c.feedback)
            for c in q.choices.all()
        )
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
    if isinstance(q, ChoiceGridQuestionElement):
        return any(has_math_delimiters(c.label) for c in q.columns.all()) or any(
            has_math_delimiters(r.statement) for r in q.rows.all()
        )
    if isinstance(q, MultiGridQuestionElement):
        return any(has_math_delimiters(c.label) for c in q.columns.all()) or any(
            has_math_delimiters(r.statement) for r in q.rows.all()
        )
    return False


def _table_has_math(el):
    from courses.models import TableElement

    if not isinstance(el, TableElement):
        return False
    data = el.normalize_data(el.data)
    return any(
        has_math_delimiters(cell.get("html", ""))
        for row in data["cells"]
        for cell in row
    )


def _fill_table_has_math(obj):
    """Math detection for a FillTableElement: any STATIC cell (never an answer cell —
    the accepted answer never reaches the client, so it can't drive KaTeX) carrying
    inline math delimiters is enough to arm KaTeX for the lesson."""
    if not isinstance(obj, FillTableElement):
        return False
    data = obj.normalize_data(obj.data)
    return any(
        cell.get("kind") != "answer" and has_math_delimiters(cell.get("html", ""))
        for row in data["cells"]
        for cell in row
    )


def _gallery_has_math(el):
    from courses.models import GalleryElement

    if not isinstance(el, GalleryElement):
        return False
    data = el.normalize_data(el.data)
    return any(has_math_delimiters(img.get("desc", "")) for img in data["images"])


def _switch_grid_has_math(obj):
    """Math detection for a SwitchGridElement: any line's stem or any cycler option
    carrying inline math delimiters is enough to arm KaTeX for the lesson."""
    for line in obj.lines or []:
        if has_math_delimiters(line.get("stem", "")):
            return True
        for cyc in line.get("cyclers", []) or []:
            if any(has_math_delimiters(o) for o in (cyc.get("options") or [])):
                return True
    return False


def _element_has_math(obj):
    """Per-type math detection for ONE concrete element. The SINGLE source of truth
    for "does this element carry math?", covering every top-level-capable type so the
    lesson/quiz context builders and the tabs recursion all agree -- adding a new
    math-bearing element type means adding exactly one clause here, not touching three
    inlined chains. A nested gallery description or table cell is found the same way a
    top-level one is.

    The trailing helpers (`_table_has_math`/`_gallery_has_math`/`_tabs_has_math`/
    `_fill_table_has_math`) each self-guard with their own isinstance check and return
    False for a non-matching type, so the final fallback dispatches those four kinds
    without an explicit isinstance ladder here."""
    if isinstance(obj, MathElement):
        return True
    if isinstance(obj, TextElement):
        return has_math_delimiters(obj.body)
    if isinstance(obj, QuestionElement):
        return _question_has_math(obj)
    if isinstance(obj, FillGateElement):
        return has_math_delimiters(obj.stem)
    if isinstance(obj, SwitchGateElement):
        return has_math_delimiters(obj.stem) or any(
            has_math_delimiters(o) for o in (obj.options or [])
        )
    if isinstance(obj, SpoilerElement):
        return _spoiler_has_math(obj)
    if isinstance(obj, CalloutElement):
        return _callout_has_math(obj)
    if isinstance(obj, BeforeAfterElement):
        return _before_after_has_math(obj)
    if isinstance(obj, SwitchGridElement):
        return _switch_grid_has_math(obj)
    if isinstance(obj, StepperElement):
        return has_math_delimiters(obj.prompt) or any(
            has_math_delimiters(s.content) for s in obj.steps.all()
        )
    if isinstance(obj, MarkDoneElement):
        return has_math_delimiters(obj.prompt) or any(
            has_math_delimiters(i.content) for i in obj.items.all()
        )
    if isinstance(obj, GuessNumberElement):
        return has_math_delimiters(obj.stem) or has_math_delimiters(obj.success_message)
    return (
        _table_has_math(obj)
        or _gallery_has_math(obj)
        or _tabs_has_math(obj)
        or _fill_table_has_math(obj)
        or _twocolumn_has_math(obj)
    )


def _tabs_has_math(el):
    """COLLECT + MUST RECURSE. `has_math` consumes the element list AFTER the RENDER
    filter has removed nested children, so it has to walk into them itself. Dispatches
    each child through _element_has_math -- an isinstance(child, MathElement) shortcut
    would pass a bare-MathElement test while silently missing math inside a nested
    gallery description or table cell."""
    from courses.models import TabsElement

    if not isinstance(el, TabsElement):
        return False
    # The LABELS are content too: math.js typesets them (`.el--tabs` is in its scope
    # list) and tabs.js copies the typeset nodes onto the strip buttons. A unit whose
    # only math is a tab label must still arm KaTeX, or the strip ships raw LaTeX.
    if any(has_math_delimiters(t["label"]) for t in el.normalized_data["tabs"]):
        return True
    join = el.join_row()
    if join is None:
        return False
    return any(
        _element_has_math(child.content_object)
        for child in join.children.prefetch_related("content_object")
    )


def _callout_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. Children are dispatched
    through _element_has_math, never has_math_delimiters directly: callout > tabs >
    table is legal, and a non-recursive walk passes a depth-1 test while silently
    missing math two containers deep.

    ORDER IS LOAD-BEARING: heading -> body -> children, with the transient guard on
    the CHILDREN walk only. A top-of-function `join_row() is None` guard (correct in
    _twocolumn_has_math, which has no text of its own) would make a transient callout
    carrying math in its heading or body report False.

    `heading` is the STORED field, never `display_heading` -- the per-kind defaults
    are translated labels and can never carry math.
    """
    from courses.models import CalloutElement

    if not isinstance(el, CalloutElement):
        return False
    if has_math_delimiters(el.heading):
        return True
    if has_math_delimiters(el.body):
        return True
    # The transient guard sits HERE, after heading/body -- never at the top. A
    # top-of-function guard (correct in _twocolumn_has_math, which has no text of its
    # own) would make a transient callout with heading/body math report False. The
    # spec chose to KEEP the guard rather than rely on resolved_children() == [], so
    # the "move it to the top" mutant stays applicable.
    if el.join_row() is None:
        return False
    return any(_element_has_math(c.content_object) for c in el.resolved_children())


def _spoiler_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. The body always renders now
    (alongside any children), so it is OR'd in unconditionally rather than only as a
    childless fallback."""
    from courses.models import SpoilerElement

    if not isinstance(el, SpoilerElement):
        return False
    # The toggle label is content too — `.spoiler__toggle` is in math.js's scope list
    # — and it is the ONE part of a nestable spoiler that is not a child element.
    if has_math_delimiters(el.label):
        return True
    if has_math_delimiters(el.body):
        return True
    return any(_element_has_math(c.content_object) for c in el.resolved_children())


def _twocolumn_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _tabs_has_math. has_math consumes the element
    list AFTER the render filter strips nested children, so it walks into them here."""
    from courses.models import TwoColumnElement

    if not isinstance(el, TwoColumnElement):
        return False
    join = el.join_row()
    if join is None:
        return False
    return any(
        _element_has_math(child.content_object)
        for child in join.children.prefetch_related("content_object")
    )


def _before_after_has_math(el):
    """COLLECT + MUST RECURSE, mirrors _twocolumn_has_math. has_math consumes the
    element list AFTER the render filter strips nested children, so it walks into
    them here. The transient guard sits at the top because this element has no
    text of its own to check first."""
    from courses.models import BeforeAfterElement

    if not isinstance(el, BeforeAfterElement):
        return False
    # No redundant `join_row() is None` guard: resolved_slots() already returns
    # empty pairs for a transient join row, and calling join_row() here would
    # issue the SAME query twice per element on every lesson render.
    return any(
        _element_has_math(child.content_object)
        for _slot_id, children in el.resolved_slots()
        for child in children
    )


def build_lesson_context(node, user):
    """Shared element/has_*/progress context for a LESSON unit. Reached through
    full_lesson_render_context, which serves every render site (see its docstring --
    do not re-enumerate them here, or the list drifts in two places).
    Enrolled: UnitProgress.get_or_create + seen-count, as a normal view. Non-enrolled
    but authorised: a read-only .filter().first() lookup that feeds practice state and
    the completion pill without creating a row on a GET."""
    # RENDER: children render inside their tabs, not as top-level siblings.
    elements = list(
        node.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
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
    choicegrid_qs = [q for q in questions if isinstance(q, ChoiceGridQuestionElement)]
    multigrid_qs = [q for q in questions if isinstance(q, MultiGridQuestionElement)]
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
    if choicegrid_qs:
        prefetch_related_objects(choicegrid_qs, "columns", "rows")
    if multigrid_qs:
        prefetch_related_objects(
            multigrid_qs, "columns", "rows", "rows__correct_columns"
        )
    # ACCEPTED LIMITATION: `elements` is scoped to parent__isnull=True, so a tab-/
    # column-nested checklist's items aren't in this prefetch (bounded per-item N+1 on
    # the nested render path only; correctness unaffected, items <= 20).
    markdone_els = [
        e.content_object
        for e in elements
        if e.content_object.__class__.__name__ == "MarkDoneElement"
    ]
    if markdone_els:
        prefetch_related_objects(markdone_els, "items")
    # SECOND ACCEPTED LIMITATION, same shape: `choice_qs`/`fill_qs` are built from
    # `elements` (parent__isnull=True), so a NESTED choice question re-queries
    # choices.all() per render. Bounded (per-unit question counts are small) and
    # pre-existing for nested fill_blank's `blanks`. Closing it would cost an extra
    # flat query on EVERY lesson render, including the vast majority with no nesting.

    question_models = [
        ChoiceQuestionElement,
        ShortTextQuestionElement,
        ShortNumericQuestionElement,
        FillBlankQuestionElement,
        DragFillBlankQuestionElement,
        MatchPairQuestionElement,
        DragToImageQuestionElement,
        ChoiceGridQuestionElement,
        MultiGridQuestionElement,
        ExtendedResponseQuestionElement,
    ]
    question_ct_ids = {ContentType.objects.get_for_model(m).id for m in question_models}

    # Single source of truth: _element_has_math() knows every type. (Previously this
    # was a ~12-clause inlined OR-chain duplicated between here and build_quiz_context.)
    has_math = any(_element_has_math(el.content_object) for el in elements)
    # Flat unit-wide (NOT parent__isnull=True) so an html element nested in a tab,
    # column or spoiler still arms html_element.js -- children keep their own `unit`
    # FK. Matches every sibling has_* flag. app_label-pinned like
    # has_stateful_elements, to avoid cold-cache ContentType SELECTs.
    has_html = node.elements.filter(
        content_type__app_label="courses", content_type__model="htmlelement"
    ).exists()
    # Flat unit-wide (NOT scoped to parent__isnull=True) so a question nested in a
    # spoiler/tab — children keep their own `unit` FK — is still detected, arming
    # question.js/dnd.js. The nestable question types are named by
    # builder.NESTABLE_QUESTION_KEYS (choice, short_text, short_numeric, fill_blank
    # and the two grids), so this fires for any of them nested in a container;
    # top-level behaviour is unchanged. Counting them here would only go stale.
    has_questions = node.elements.filter(content_type_id__in=question_ct_ids).exists()
    # has_fill_table: plain CT-model filter, moved here unchanged. The block
    # comment below belongs to has_filltable_gate, NOT to this line.
    has_fill_table = node.elements.filter(
        content_type__model="filltableelement"
    ).exists()
    # CT-free by construction, per house convention (see the has_html comment
    # above and the has_stateful_elements one below). A reverse-GenericRelation
    # filter here would make get_extra_restriction resolve FillTableElement's
    # ContentType and emit a cold-cache CT SELECT on every lesson page that
    # HAS a fill-table. NO TEST CAN CATCH THAT -- test_html_element's fixtures
    # hold only HtmlElements, so has_fill_table is False and this whole term
    # short-circuits before the queryset is built; and its assertion is a
    # RELATIVE A/B (len(q3) == len(q1)), which pays any fixed cost in both arms.
    # That is why the shape is pinned by a source assertion instead.
    # Short-circuited on has_fill_table so a unit with no fill-table costs zero
    # extra queries. NOT scoped to parent__isnull=True: a gate nested in a tab
    # or callout keeps its own `unit` FK.
    has_filltable_gate = (
        has_fill_table
        and FillTableElement.objects.filter(
            pk__in=node.elements.filter(
                content_type__app_label="courses",
                content_type__model="filltableelement",
            ).values_list("object_id", flat=True),
            data__gate=True,
        ).exists()
    )
    # Flat query (NOT scoped to parent__isnull=True) so a gate nested inside a tab —
    # children keep their own `unit` FK — is still detected. Both gate types arm the
    # pre-hide + reveal.js; only fill-gates need fillgate.js. A gating fill-table
    # arms them too, which is what loads reveal.js on a unit with no other gate.
    has_reveal_gate = (
        node.elements.filter(
            content_type__model__in=[
                "revealgateelement",
                "fillgateelement",
                "switchgateelement",
            ]
        ).exists()
        or has_filltable_gate
    )
    has_fill_gate = node.elements.filter(content_type__model="fillgateelement").exists()
    has_switch_gate = node.elements.filter(
        content_type__model="switchgateelement"
    ).exists()
    has_switch_grid = node.elements.filter(
        content_type__model="switchgridelement"
    ).exists()
    has_stepper = node.elements.filter(content_type__model="stepperelement").exists()
    has_markdone = node.elements.filter(content_type__model="markdoneelement").exists()
    has_guess_number = node.elements.filter(
        content_type__model="guessnumberelement"
    ).exists()
    # Flat query (NOT scoped to parent__isnull=True) so an instance nested inside a
    # tab -- children keep their own `unit` FK -- is still detected.
    has_before_after = node.elements.filter(
        content_type__app_label="courses",
        content_type__model="beforeafterelement",
    ).exists()

    # Capability, NOT stored state: true iff this unit CONTAINS a state-bearing element
    # type, regardless of whether this student has stored anything (spec D1). Flat over
    # node.elements (NOT parent__isnull=True) so a gate or question nested in a tab,
    # column or spoiler still counts -- children keep their own `unit` FK.
    # app_label pins the join the way Element.content_type's own limit_choices_to does;
    # get_for_model ct-ids were rejected to avoid cold-cache CT SELECTs. NOT
    # because tests/test_html_element.py catches them -- it does not: its
    # assertion is len(q3) == len(q1), a RELATIVE A/B that pays any fixed cost
    # in both arms. See test_filltable_gate_query_shape.py for why that shape
    # needs a source assertion instead.
    # Called through the module attribute so test 6's monkeypatch can bind.
    has_stateful_elements = node.elements.filter(
        content_type__app_label="courses",
        content_type__model__in=state_svc.stateful_element_model_names(),
    ).exists()

    progress = None
    seen_ids = set()
    state = {}
    state_row = None
    if is_enrolled(user, node.course):
        # UNCHANGED: this row feeds progress/seen_ids/seen_count. The rule is "the
        # STATE read never creates a row", NOT "no get_or_create on a GET".
        progress, _ = UnitProgress.objects.get_or_create(student=user, unit=node)
        seen_ids = set(progress.seen_element_ids)
        state_row = progress
    elif user.is_authenticated:
        # Non-enrolled but can view (author/teacher): read an EXISTING row for their
        # practice state AND the completion pill -- an explicit "Mark as done" click
        # persists for them too (see complete()), and without this assignment the
        # write would land but never re-render. Still .filter().first(), never
        # get_or_create: a passive GET must not mint a row for a previewer.
        state_row = UnitProgress.objects.filter(student=user, unit=node).first()
        progress = state_row
    if state_row:
        # int-keyed {Element.pk: blob} — the render seam looks up by the join-row pk.
        # Read-side fail-open: drop any non-int-coercible key and any non-dict value
        # rather than 500 the lesson from inside a template tag.
        state = {}
        for k, blob in (state_row.element_state or {}).items():
            if not isinstance(blob, dict):
                continue
            try:
                state[int(k)] = blob
            except (TypeError, ValueError):
                continue
    # Slide-break join-rows are never "seen" (mirrors the `seen` view's exclusion) —
    # without this, element_count could never equal seen_count for a lesson with a
    # break.
    break_ct_id = ContentType.objects.get_for_model(SlideBreakElement).id
    current_ids = [el.pk for el in elements if el.content_type_id != break_ct_id]
    seen_count = len(seen_ids.intersection(current_ids))
    return {
        "course": node.course,
        "unit": node,
        "is_quiz": False,
        "elements": elements,
        "slides": partition_into_slides(elements),
        "has_math": has_math,
        "has_html": has_html,
        "has_questions": has_questions,
        "has_reveal_gate": has_reveal_gate,
        "has_fill_gate": has_fill_gate,
        "has_switch_gate": has_switch_gate,
        "has_switch_grid": has_switch_grid,
        "has_fill_table": has_fill_table,
        "has_filltable_gate": has_filltable_gate,
        "has_stepper": has_stepper,
        "has_markdone": has_markdone,
        "has_guess_number": has_guess_number,
        "has_before_after": has_before_after,
        "has_stateful_elements": has_stateful_elements,
        "element_state": state,
        "slug": node.course.slug,
        "node_pk": node.pk,
        "submitted_values": None,
        "progress": progress,
        "element_count": len(current_ids),
        "seen_count": seen_count,
        "callout_numbers": callout_numbers(node),
    }


def _widen_has_math_for_titles(ctx, node):
    """OR the node-title scan into ctx["has_math"] on a unit-page context.

    Call AFTER ctx["unit_nav"] is assigned -- the tree it scans is that value.

    The contents tree in the DOM is the WHOLE course outline (build_unit_nav sets
    unit_nav["tree"] to it), so one maths title anywhere in the course needs KaTeX
    on every unit page of that course.

    The second scan (`[node.title]`) is REDUNDANT TODAY and kept deliberately --
    the same reasoning as the is_author flag in full_lesson_render_context: every
    present caller resolves `node` through get_node_or_404(..., viewer=user, ...),
    which 404s an unpublished unit before this render is reached, so the on-screen
    unit is always in the tree already. It is defence-in-depth for a future render
    site that reaches these templates WITHOUT that view-level gate, which would
    otherwise silently lose the current unit's own title. Do not delete it as dead
    code without re-verifying that every caller still carries the gate.
    """
    ctx["has_math"] = (
        ctx["has_math"]
        or tree_titles_have_math(ctx["unit_nav"]["tree"])
        or titles_have_math([node.title])
    )


def full_lesson_render_context(node, user, *, notes_show=False, tags_panel=False):
    """Full context for rendering courses/lesson_unit.html: lesson context +
    unit nav + feedback defaults + the author's notes + tag panel + the
    edit-unit link. Single-sourced so every render site (lesson_unit GET,
    check_answer re-render, notes no-JS re-render) stays consistent."""
    from notes.rendering import lesson_notes_context  # lazy: avoid import cycle
    from tags.rendering import unit_tags_context

    ctx = build_lesson_context(node, user)
    drafts = "keep" if can_see_drafts(user, node.course) else "hide"
    # Task 15 §5: the student-facing draft banner's `{% if is_author and not
    # unit.published %}` gate. Reuses `drafts` rather than a second
    # can_see_drafts call -- the two questions ("can this viewer see drafts
    # in general" / "is this viewer an author") are the same question here.
    #
    # REDUNDANT TODAY, KEPT DELIBERATELY: every caller of this function (and
    # of quiz_unit/_quiz_render_feedback below) resolves `node` through
    # get_node_or_404(..., viewer=user, ...), which already 404s a
    # non-author before this render is ever reached -- so on every present
    # call site `{% if is_author and not unit.published %}` is
    # observationally identical to `{% if not unit.published %}` alone. This
    # flag is defence-in-depth for a future render site that reaches this
    # template WITHOUT that view-level viewer= gate; it would otherwise leak
    # the banner (and the Publish button behind it) to a non-author. Do not
    # delete it as dead code without re-verifying that every caller still
    # carries the gate.
    ctx["is_author"] = drafts == "keep"
    ctx["unit_nav"] = build_unit_nav(node.course, user, node, drafts=drafts)
    _widen_has_math_for_titles(ctx, node)
    ctx.update(
        feedback_for_pk=None,
        selected_ids=frozenset(),
        submitted_values=None,
        mark_result=None,
    )
    ctx.update(lesson_notes_context(user, node, show=notes_show))
    ctx.update(unit_tags_context(user, node, panel_open=tags_panel))
    ctx.update(unit_edit_context(user, node))
    return ctx


@login_required
def my_courses(request):
    courses = Course.objects.filter(enrollments__student=request.user).order_by("title")
    return render(request, "courses/my_courses.html", {"courses": courses})


@login_required
def course_outline(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    from notes.services import note_counts_for_outline  # lazy: avoid cycle
    from tags import services as tag_services

    drafts = "keep" if can_see_drafts(request.user, course) else "hide"
    outline = build_outline(course, request.user, drafts=drafts)
    tags_by_unit, course_tags = tag_services.tags_for_outline(request.user, course)
    course_tag_ids = {t.pk for t in course_tags}
    active_tag_ids = [
        int(x)
        for x in request.GET.getlist("tags")
        if x.isdigit() and int(x) in course_tag_ids
    ]
    tag_services.outline_with_tags(outline, tags_by_unit, active_tag_ids)
    base = reverse("courses:course_outline", kwargs={"slug": course.slug})
    # The whole outline is in the DOM, so scan the whole tree.
    has_math = tree_titles_have_math(outline)
    # Enrolled-only: can_access_course also admits authors, teachers and staff
    # previewing a course they are not taking, and a "Start the course" CTA would be
    # noise for them. Mirrors the `seen` write route, which is enrolled-only by
    # design. Runs AFTER outline_with_tags, but the target is deliberately
    # INDEPENDENT of the active tag filter: outline_with_tags annotates without
    # pruning, and the filter hides rows rather than restricting scope, so filtering
    # to one tag must not change where "Continue" sends you.
    resume = (
        build_resume(course, request.user, outline)
        if is_enrolled(request.user, course)
        else None
    )
    return render(
        request,
        "courses/outline.html",
        {
            "course": course,
            "outline": outline,
            "note_counts": note_counts_for_outline(request.user, course),
            "active_tag_ids": active_tag_ids,
            "filter_chips": tag_services.filter_chip_hrefs(
                base, course_tags, active_tag_ids
            ),
            "has_math": has_math,
            "resume": resume,
        },
    )


@login_required
def course_results(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not can_access_course(request.user, course):
        raise PermissionDenied
    # student is always request.user — no IDOR surface. `course` is passed
    # top-level as the template's canonical source (summary also carries it).
    drafts = "keep" if can_see_drafts(request.user, course) else "hide"
    summary = build_course_results(course, request.user, drafts=drafts)
    # build_course_results builds "rows" with three rows.append calls, so it is
    # a real list -- scanning it here and then passing it to the template
    # iterates it twice safely. Were it a generator, the scan would exhaust it and
    # the page would render EMPTY, a silent severe failure no test here would
    # catch, which is why the return type is pinned rather than assumed.
    has_math = titles_have_math(r["unit"].title for r in summary["rows"])
    return render(
        request,
        "courses/course_results.html",
        {"course": course, "summary": summary, "has_math": has_math},
    )


@login_required
def progress_reset(request, slug, node_pk=None):
    """Clear the student's OWN practice state for a node's subtree, or the course.

    GET renders a confirmation interstitial (side-effect free); POST performs it.
    NOT POST-only: the count needs a server round-trip, and reset is the student's
    protection against automatic persistence -- shipping it as a one-click no-undo
    form for no-JS students would make the safety valve the hazard.
    """
    node = None
    if node_pk is None:
        course = get_object_or_404(Course, slug=slug)
    else:
        # NOT optional: can_access_course authorizes against `slug`, but nothing
        # otherwise ties node_pk to that course -- a foreign node_pk would resolve
        # its own subtree and wipe the student's state THERE.
        node = get_node_or_404(node_pk, slug, viewer=request.user, require_unit=False)
        course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied

    drafts = "keep" if can_see_drafts(request.user, course) else "hide"

    # targets is UNFILTERED -- it drives the WRITE. Reset is the student's
    # protection against automatic persistence; leaving hidden state behind is
    # precisely the failure it exists to prevent. visible_targets is a SECOND
    # call, and drives only the count.
    if node is None:
        targets = units_in_order(course)
        visible_targets = units_in_order(course, drafts=drafts)
    else:
        targets = units_under(node)
        visible_targets = units_under(node, drafts=drafts)

    rows = UnitProgress.objects.filter(student=request.user, unit__in=targets)
    fallback = reverse("courses:course_outline", args=[slug])

    # Validate `next` ONCE, for BOTH methods. Validating only the POST would leave the
    # GET piping request.GET["next"] straight into the Cancel href -- a libli-hosted,
    # plausibly-styled page whose Cancel button navigates off-site. That is the same
    # open-redirect class the spec rejects for HTTP_REFERER, reached from the other
    # side.
    raw_next = (
        (request.POST.get("next") if request.method == "POST" else None)
        or request.GET.get("next")
        or ""
    )
    safe_next = (
        raw_next
        if raw_next
        and url_has_allowed_host_and_scheme(
            raw_next,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
        else ""
    )

    if request.method == "POST":
        # .update() deliberately bypasses save(): it fires neither auto_now on
        # updated_at nor the completed => completed_at invariant. Both are fine --
        # reset does not touch `completed`, and leaving updated_at alone keeps
        # build_resume's source A pointing where the student was. IDOR-safe against
        # other STUDENTS by construction (student=request.user); the cross-COURSE
        # hole is closed by get_node_or_404 above, not by this filter.
        # A DIRECT write, bypassing save_element_state -- the house style, and the
        # reason the lockstep contract lives on the field itself (see models.py).
        rows.update(element_state={})
        return redirect(safe_next or fallback)

    # Honest blast radius: lessons that actually HOLD work, not every lesson in the
    # subtree. Telling a student "this clears 14 lessons" when 3 have anything makes
    # a harmless reset sound destructive. Filter the COUNT, never the WRITE (the
    # POST branch above uses the unfiltered `rows`/`targets`).
    affected_count = (
        rows.exclude(element_state={}).filter(unit__in=visible_targets).count()
    )
    return render(
        request,
        "courses/progress_reset_confirm.html",
        {
            "course": course,
            "node": None if node_pk is None else node,
            "affected_count": affected_count,
            "next": safe_next,
            "cancel_url": safe_next or fallback,
        },
    )


@login_required
def lesson_unit(request, slug, node_pk):
    node = get_node_or_404(node_pk, slug, viewer=request.user, require_unit=True)
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    if node.unit_type == ContentNode.UnitType.QUIZ:
        return redirect("courses:quiz_unit", slug=slug, node_pk=node_pk)
    ctx = full_lesson_render_context(
        node,
        request.user,
        notes_show=bool(request.GET.get("notes")),
        tags_panel=request.GET.get("panel") == "tags",
    )
    return render(request, "courses/lesson_unit.html", ctx)


@login_required
def node_permalink(request, node_pk):
    """Slug-free permalink to any ContentNode.

    Stored links carry only a pk, so this survives a course being re-slugged and
    lets the redirect target change without touching a single stored body.

    404 -- NOT PermissionDenied -- for an inaccessible node. get_node_or_404's
    docstring states the convention: "a foreign node always 404s before any 403."
    Every other node-addressed view scopes by slug first; this one has no slug, so
    returning 403 would make it an existence oracle for every node in the install.
    """
    node = get_object_or_404(ContentNode.objects.select_related("course"), pk=node_pk)
    if not can_access_course(request.user, node.course):
        raise Http404("node is not accessible")
    if (
        node.kind == ContentNode.Kind.UNIT
        and not node.published
        and not can_see_drafts(request.user, node.course)
    ):
        raise Http404("node is not published")
    if node.kind == ContentNode.Kind.UNIT:
        # Branch explicitly rather than letting lesson_unit forward a quiz: that
        # would cost a second redirect hop on every quiz link and couple this view
        # to another's implementation detail.
        name = (
            "courses:quiz_unit"
            if node.unit_type == ContentNode.UnitType.QUIZ
            else "courses:lesson_unit"
        )
        return redirect(name, slug=node.course.slug, node_pk=node.pk)
    return redirect(
        reverse("courses:course_outline", kwargs={"slug": node.course.slug})
        + f"#node-{node.pk}"
    )


def _progress_json(progress):
    return {
        "seen_element_ids": list(progress.seen_element_ids),
        "completed": progress.completed,
        "completed_at": progress.completed_at.isoformat()
        if progress.completed_at
        else None,
    }


def _seen_current_ids(node):
    """Element pks a student must see to complete `node`. Excludes slide breaks
    (never "seen") and nested children: the frontend only reports
    .lesson-block[data-element-id] ids, which _lesson_article.html emits for
    top-level elements only. A nested pk here could never be satisfied, so the
    unit would never complete."""
    break_ct = ContentType.objects.get_for_model(SlideBreakElement)
    return set(
        node.elements.filter(parent__isnull=True)
        .exclude(content_type=break_ct)
        .values_list("pk", flat=True)
    )


@require_POST
@login_required
def seen(request, slug, node_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_lesson=True
    )
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
        # ASYMMETRY, deliberate: SCROLL-tracking is not recorded for a previewer, but
        # completion via the explicit button IS (see complete()). So "untracked" is
        # narrow -- their practice state and their completion both persist; only this
        # signal is dropped. The synthetic response therefore reports completed=False
        # even when a stored row says True: this endpoint's contract is "here is your
        # scroll-tracking", not "here is your progress row". Do not "fix" it to echo
        # the stored row -- that breaks
        # tests/test_courses_progress.py::test_previewer_seen_no_write_and_ignores_stored_completion  # noqa: E501
        # and quietly turns a write-free endpoint into a state reporter.
        return JsonResponse(
            {"seen_element_ids": [], "completed": False, "completed_at": None}
        )
    current = _seen_current_ids(node)
    incoming = {
        x
        for x in data
        if isinstance(x, int) and not isinstance(x, bool) and x in current
    }
    with transaction.atomic():
        # Lock BEFORE the read that feeds this save. The save writes every column
        # from the in-memory instance, so a read taken without the lock lets a
        # concurrent complete() commit its completed=True in between and then be
        # silently overwritten here -- a LOST UPDATE, not a lock-exclusion failure.
        # FOR UPDATE cannot protect a writer whose READ preceded it; the rule is
        # ORDERING, not exclusion (on PostgreSQL a plain UPDATE already blocks on an
        # existing FOR UPDATE). save_element_state and complete both lock first for
        # the same reason; this endpoint was the one that did not.
        # Guarded by test_seen_locks_the_row_before_reading_it, which asserts on the
        # emitted SQL because a single-connection test cannot tell locked from
        # unlocked by outcome.
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        merged = set(progress.seen_element_ids) | incoming
        progress.seen_element_ids = sorted(merged)
        if not progress.completed and current and current.issubset(merged):
            progress.completed = True  # completed_at stamped in save()
        progress.save()
    return JsonResponse(_progress_json(progress))


@require_POST
@login_required
def complete(request, slug, node_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_lesson=True
    )
    course = node.course
    # can_access_course is DELIBERATELY the sole guard on this write: the row is the
    # viewer's OWN record, not course analytics, so any viewer who can open the lesson
    # may mark it done -- the same reversal PR #136 applied to element_state_save.
    # Do not "restore" an enrollment check here; both directions are pinned by
    # tests/test_courses_progress.py (see test_unrelated_logged_in_user_is_denied).
    if not can_access_course(request.user, course):
        raise PermissionDenied
    with transaction.atomic():
        # Re-read under the lock instead of keeping get_or_create's instance. The rule
        # here is ORDERING, not exclusion: on PostgreSQL a plain UPDATE already blocks
        # on an existing FOR UPDATE, so the lock is not about which writers opt into
        # it. What FOR UPDATE cannot do is protect a writer whose READ happened before
        # the lock -- that writer carries a stale row across the block and writes it
        # back afterwards, losing the update. That is why save_element_state locks
        # BEFORE it reads, and why seen -- which does not -- can still lose one.
        # Collapsing this back to `progress, _ = get_or_create(...)` is byte-identical
        # in every sequential test, so this comment is the only thing protecting the
        # re-fetch.
        UnitProgress.objects.get_or_create(student=request.user, unit=node)
        progress = UnitProgress.objects.select_for_update().get(
            student=request.user, unit=node
        )
        if not progress.completed:
            progress.completed = True
            progress.save()  # completed_at stamped in save()
    return redirect("courses:lesson_unit", slug=slug, node_pk=node_pk)


def save_element_state(user, unit, element_pk, blob):
    """Atomic per-student practice-state write, shared by check_answer and
    element_state_save. `blob` is a dict to STORE (upserts the row), or None to
    DELETE the key. On delete, operate only on an EXISTING row — never spawn a row
    just to pop a missing key (a passive previewer clicking Check on a blank
    question must not create a spurious empty-state row)."""
    with transaction.atomic():
        if blob is None:
            progress = (
                UnitProgress.objects.select_for_update()
                .filter(student=user, unit=unit)
                .first()
            )
            if progress is None:
                return  # nothing to delete; do not spawn a row
            progress.element_state.pop(str(element_pk), None)
        else:
            UnitProgress.objects.get_or_create(student=user, unit=unit)
            progress = UnitProgress.objects.select_for_update().get(
                student=user, unit=unit
            )
            progress.element_state[str(element_pk)] = blob
        progress.save()


@require_POST
@login_required
def element_state_save(request, slug, node_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_lesson=True
    )
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied

    is_json = request.content_type == "application/json"
    raw_fields = None
    if is_json:
        try:
            data = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return HttpResponseBadRequest("invalid JSON")
        if not isinstance(data, dict):
            return HttpResponseBadRequest("expected an object")
        raw_element = data.get("element")
        payload = data.get("state")
        raw_fields = data.get("fields")
        if raw_fields is not None and payload is not None:
            return HttpResponseBadRequest("state and fields are mutually exclusive")
    else:
        # Form-encoded fallback: mark-done's no-JS form only. It posts `element` +
        # a repeated `item` field; synthesize the blob so BOTH paths run the SAME
        # validator. getlist yields STRINGS -- the validator int-coerces.
        raw_element = request.POST.get("element")
        payload = {"items": request.POST.getlist("item")}

    try:
        element_pk = int(raw_element)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("bad element")

    element = Element.objects.filter(pk=element_pk, unit=node).first()
    if element is None:
        return HttpResponseBadRequest("unknown element")
    obj = element.content_object
    if obj is None:
        return HttpResponseBadRequest("unknown element")

    model = element.content_type.model
    if raw_fields is not None:
        # SLICE 1: the question write path does not exist yet. Slice 3 replaces this
        # branch with build_answer + answer_to_json behind an isinstance fallback.
        return HttpResponseBadRequest("fields is not supported yet")
    if not is_json and model != "markdoneelement":
        return HttpResponseBadRequest("form-encoded save is mark-done only")

    # Validate BEFORE the atomic write block: a rejected/unknown save must not spawn
    # a UnitProgress row for a passive previewer.
    result = state_svc.validate_state(element, obj, payload)

    def _stored():
        row = UnitProgress.objects.filter(student=request.user, unit=node).first()
        blob = (row.element_state or {}).get(str(element.pk)) if row else None
        return blob if isinstance(blob, dict) else {}

    def _resp(blob):
        if is_json:
            return JsonResponse({"element": element.pk, "state": blob})
        return redirect(
            reverse("courses:lesson_unit", args=[slug, node_pk])
            + f"#markdone-{element.pk}"
        )

    if result is state_svc.REJECT:
        # Echo what is STORED (never the rejected input): the client ADOPTS the echo,
        # which makes a silent rejection self-correcting rather than a desync.
        return _resp(_stored())

    # Practice state is personal self-tracking (ungraded, absent from analytics), so
    # ANY viewer who can access the lesson persists their own -- not just enrolled
    # students. This deliberately diverges from seen/quiz, which ignore previewers so
    # authors don't pollute their own SCROLL-tracking and quiz analytics -- quiz now
    # SERVES previewers live forms, but still records nothing for them. It is those
    # two specifically, NOT progress writes in general: an explicit "Mark as done"
    # click now persists for previewers too (see complete()). The can_access_course
    # gate above is the only guard the write needs.
    if result is state_svc.EMPTY:
        save_element_state(request.user, node, element.pk, None)
        blob = {}
    else:
        save_element_state(request.user, node, element.pk, result)
        blob = result
    return _resp(blob)


@require_POST
@login_required
def check_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_lesson=True
    )
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
    result = question.mark(answer)

    if getattr(question, "RESTORABLE_IN_LESSON", False):
        # Practice-state (slice 3): persist the answer only — never the verdict; it
        # is re-marked on restore. Empty answer clears any prior stored answer.
        if answer_is_empty(answer):
            save_element_state(request.user, node, element.pk, None)
        else:
            save_element_state(
                request.user, node, element.pk, {"answer": answer_to_json(answer)}
            )

    if _wants_fragment(request):
        if isinstance(question, ChoiceQuestionElement):
            # Choice: return the full re-rendered element so inline per-option feedback
            # lands in the choices list (question.js swaps the form body). render() sets
            # reveal_template=None for lesson mode -> no duplicate bottom reveal list.
            selected = selected_ids(answer)
            return HttpResponse(
                question.render(
                    element=element,
                    mode="lesson",
                    selected_ids=selected,
                    mark_result=result,
                    feedback_for_pk=element.pk,
                )
            )
        return render(
            request,
            "courses/elements/_question_feedback.html",
            question.feedback_context(result),
        )
    # No-JS: re-render the whole lesson unit with this question's feedback inline.
    from courses.builder import ancestor_pks

    ctx = full_lesson_render_context(node, request.user)
    selected = selected_ids(answer)
    submitted = None if isinstance(answer, (set, frozenset)) else answer
    ctx.update(
        feedback_for_pk=element.pk,
        selected_ids=selected,
        submitted_values=submitted,
        mark_result=result,
        # A spoiler renders `open` when the checked element is anywhere in its
        # subtree. Ancestry, not direct childhood, so a question inside a callout
        # inside a spoiler opens the spoiler too.
        feedback_ancestor_pks=ancestor_pks(element),
    )
    return render(request, "courses/lesson_unit.html", ctx)


@require_POST
@login_required
def fillgate_check(request, element_pk):
    """Server-side check for a Fill-in-&-confirm gate. Reports correctness only —
    NOTHING is persisted. Flat route (no slug/node_pk): the course is derived from
    the element's join row for the access gate."""
    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk
    )
    # Access check FIRST (before the type 404), so a user without course access
    # cannot distinguish a fill-gate from a non-fill-gate id by probing pks.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    concrete = element.content_object
    if not isinstance(concrete, FillGateElement):
        raise Http404("not a fill-gate element")
    answers = concrete.answers or []
    n = len(answers)
    values = (request.POST.getlist("blank") + [""] * n)[:n]
    results = [blank_matches(values[i], answers[i]) for i in range(n)]
    return JsonResponse({"correct": bool(results) and all(results), "blanks": results})


@require_POST
@login_required
def switchgate_check(request, element_pk):
    """Server-side check for a Choose & confirm gate. Reports correctness only —
    NOTHING is persisted. Soft pk lookup: a missing or wrong-type pk is a 200
    {"correct": false}, NOT a 404 (deliberate deviation from fillgate_check's
    get_object_or_404)."""
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, SwitchGateElement):
        return JsonResponse({"correct": False})
    # Resolved element: apply the same access check fillgate_check uses.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    try:
        choice = int(request.POST.get("choice", ""))
    except (TypeError, ValueError):
        return JsonResponse({"correct": False})
    return JsonResponse({"correct": choice == concrete.answer})


@require_POST
@login_required
def switchgrid_check(request, element_pk):
    """Server-side check for a Switch grid self-check. Reports per-cycler and overall
    correctness only — NOTHING is persisted. Soft pk lookup (switchgate parity):
    a missing/wrong-type pk is a 200 {"correct": False, "cells": []}, not 404."""
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, SwitchGridElement):
        return JsonResponse({"correct": False, "cells": []})
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied

    try:
        indices = json.loads(request.POST.get("indices", ""))
    except (TypeError, ValueError):
        return JsonResponse({"correct": False, "cells": []})
    if not isinstance(indices, list):
        return JsonResponse({"correct": False, "cells": []})

    cells = []
    all_correct = True
    for i, line in enumerate(concrete.lines or []):
        row = []
        sub = indices[i] if (i < len(indices) and isinstance(indices[i], list)) else []
        for j, cyc in enumerate(line.get("cyclers", []) or []):
            submitted = sub[j] if (j < len(sub) and isinstance(sub[j], int)) else None
            ok = submitted == cyc.get("answer")
            row.append(ok)
            all_correct = all_correct and ok
        cells.append(row)
    return JsonResponse({"correct": all_correct, "cells": cells})


@require_POST
@login_required
def guessnumber_check(request, element_pk):
    """Server-side check for a Guess-the-number self-check. Reports correctness and
    a direction only — NOTHING is persisted. Soft pk lookup: a missing or wrong-type
    pk is a 200 {"correct": false, "direction": null}, NOT a 404 (switchgate parity,
    a deliberate deviation from fillgate_check's get_object_or_404)."""
    miss = JsonResponse({"correct": False, "direction": None})
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, GuessNumberElement):
        return miss
    # Resolved element: apply the same access check the sibling gates use.
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    n = parse_number(request.POST.get("guess", ""))
    if n is None:
        return miss
    if abs(n - concrete.target) <= concrete.tolerance:
        return JsonResponse({"correct": True, "direction": None})
    return JsonResponse(
        {"correct": False, "direction": "high" if n > concrete.target else "low"}
    )


@require_POST
@login_required
def filltable_check(request, element_pk):
    """Server-side self-check for a Fill-in table. Per-cell correctness only —
    NOTHING is persisted, no marks. Soft pk lookup (a missing/wrong-type pk is a
    200 empty-set body, not 404) BEFORE any access dereference, mirroring
    switchgrid_check. Response shape deliberately differs: flat r/c dicts + a
    top-level `all_correct` (not switchgrid's nested `correct`)."""
    from courses.filltable import answer_cells
    from courses.filltable import split_alternatives

    empty = {"cells": [], "all_correct": False}
    element = (
        Element.objects.select_related("unit__course").filter(pk=element_pk).first()
    )
    concrete = element.content_object if element else None
    if not isinstance(concrete, FillTableElement):
        return JsonResponse(empty)
    if not can_access_course(request.user, element.unit.course):
        raise PermissionDenied
    nd = concrete.normalize_data(concrete.data)
    case_sensitive = nd["case_sensitive"]
    cells = []
    all_correct = True
    for r, c, answer in answer_cells(nd["cells"]):
        got = request.POST.get(f"r{r}c{c}", "")
        alts = split_alternatives(answer)
        ok = blank_matches(got, alts, case_sensitive=case_sensitive)
        cells.append({"r": r, "c": c, "correct": ok})
        all_correct = all_correct and ok
    if not cells:
        return JsonResponse(empty)  # zero answer cells: never a vacuous True
    return JsonResponse({"cells": cells, "all_correct": all_correct})


def _stored_result(question, response):
    # MarkResult + answer_from_json imported at views.py top.
    m = question.mark(answer_from_json(question, response.latest_answer))
    return MarkResult(
        correct=(response.fraction == Decimal("1.0000")),
        fraction=float(response.fraction or 0),
        reveal=m.reveal,
        annotated=m.annotated,
    )


def build_quiz_context(node, user):
    """Element/render context for a QUIZ unit. Parallels build_lesson_context
    but threads per-question quiz state (responses, locked, attempts_left),
    plus the edit-unit link context."""
    # RENDER: children render inside their tabs, not as top-level siblings.
    elements = list(
        node.elements.filter(parent__isnull=True)
        .order_by("order", "pk")
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
    choicegrid_qs = [q for q in questions if isinstance(q, ChoiceGridQuestionElement)]
    multigrid_qs = [q for q in questions if isinstance(q, MultiGridQuestionElement)]
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
    if choicegrid_qs:
        prefetch_related_objects(choicegrid_qs, "columns", "rows")
    if multigrid_qs:
        prefetch_related_objects(
            multigrid_qs, "columns", "rows", "rows__correct_columns"
        )

    submission = None
    # Hoisted: is_enrolled was already called here and its result discarded.
    # `previewing` must not cost a second Enrollment query -- this builder is
    # otherwise carefully prefetched.
    enrolled = is_enrolled(user, node.course)
    if enrolled:
        submission, _ = QuizSubmission.objects.get_or_create(student=user, unit=node)
    quiz_submitted = bool(
        submission and submission.status == QuizSubmission.Status.SUBMITTED
    )

    responses = {}
    if submission is not None:
        responses = {r.element_id: r for r in submission.responses.all()}

    # Per-element render state. Task 8 (fresh quiz) leaves feedback_html empty for
    # every question; the no-JS answer path (Task 9) and resume (Task 12) fill it.
    # Also carries server-side question numbering (Task 5, slideshow-mode): a
    # 1-based counter over question join-rows in document order, contiguous
    # across slide breaks. Quiz-only — the lesson builder never sets qnum, so
    # lessons never number their questions.
    render_states = {}
    qnum = 0
    for el in elements:
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        qnum += 1
        r = responses.get(el.pk)
        state = {
            "qnum": qnum,
            "selected_ids": frozenset(),
            "submitted_values": None,
            "locked": bool(r.locked) if r else False,
            "attempts_left": None,
            "feedback_html": "",
            "mark_result": None,
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
            # Only a LOCKED question hands its result to the element render: the
            # types that mark their options inline key the reveal off it, and while
            # attempts remain the answer key must stay withheld. Same gate
            # quiz_feedback_context applies to reveal_template.
            if r.locked:
                state["mark_result"] = result
            fb_ctx = quiz_feedback_context(q, r, result=result)
            state["attempts_left"] = fb_ctx.get("attempts_left")
            state["feedback_html"] = render_to_string(
                "courses/elements/_quiz_question_feedback.html", fb_ctx
            )
        render_states[el.pk] = state

    # Over-inclusive vs build_lesson_context's precise per-stem detection: load
    # KaTeX whenever the quiz has any question (a question may carry math in its
    # stem/choices) regardless of whether _element_has_math would detect it. A few
    # KB of unused assets is an accepted tradeoff. The non-question types defer to
    # the shared _element_has_math() so this stays in lockstep with the lesson path.
    has_math = bool(questions) or any(
        _element_has_math(el.content_object) for el in elements
    )
    # Flat unit-wide (NOT parent__isnull=True) so an html element nested in a tab,
    # column or spoiler still arms html_element.js -- children keep their own `unit`
    # FK. Matches every sibling has_* flag. app_label-pinned like
    # has_stateful_elements, to avoid cold-cache ContentType SELECTs. Separate code
    # path from build_lesson_context's has_html -- both must change together.
    has_html = node.elements.filter(
        content_type__app_label="courses", content_type__model="htmlelement"
    ).exists()
    # Flat query (NOT scoped to parent__isnull=True) so an instance nested inside a
    # tab -- children keep their own `unit` FK -- is still detected. Same query as
    # build_lesson_context's has_before_after (views.py:445).
    has_before_after = node.elements.filter(
        content_type__app_label="courses",
        content_type__model="beforeafterelement",
    ).exists()
    ctx = {
        "course": node.course,
        "unit": node,
        "is_quiz": True,
        "elements": elements,
        "slides": partition_into_slides(elements),
        "responses": responses,
        "render_states": render_states,
        "submission": submission,
        "quiz_submitted": quiz_submitted,
        # A non-enrolled previewer gets LIVE question forms: their answers are graded
        # ephemerally by quiz_answer and nothing is persisted. `read_only` now gates
        # exactly ONE thing -- the Finish form -- and does NOT mean "the page is
        # inert". Inputs freeze on `quiz_submitted` alone.
        "previewing": not enrolled,
        "read_only": quiz_submitted or not enrolled,
        "has_math": has_math,
        "has_html": has_html,
        "has_before_after": has_before_after,
        "has_questions": True,
        "callout_numbers": callout_numbers(node),
    }
    from tags.rendering import unit_tags_context

    ctx.update(unit_tags_context(user, node, panel_open=False))
    ctx.update(unit_edit_context(user, node))
    return ctx


@login_required
def quiz_unit(request, slug, node_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_quiz=True
    )
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied
    ctx = build_quiz_context(node, request.user)
    sub = ctx["submission"]
    if sub is not None and sub.status == QuizSubmission.Status.SUBMITTED:
        target = reverse(
            "courses:quiz_results", kwargs={"slug": slug, "node_pk": node_pk}
        )
        if request.GET.get("panel") == "tags":
            target += "?panel=tags"
        return redirect(target)
    drafts = "keep" if can_see_drafts(request.user, course) else "hide"
    # Task 15 §5: the student-facing draft banner's is_author flag -- see the
    # matching comment in full_lesson_render_context.
    ctx["is_author"] = drafts == "keep"
    ctx["unit_nav"] = build_unit_nav(course, request.user, node, drafts=drafts)
    _widen_has_math_for_titles(ctx, node)
    ctx["tags_panel_open"] = request.GET.get("panel") == "tags"
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
        if question.INLINE_QUIZ_REVEAL:
            # The marking lives IN the options list, which sits outside the feedback
            # box — so returning the box alone would swap in "Correct" while leaving
            # the options unmarked. Return the whole element and let quiz.js swap the
            # live form's body (the data-question-inline contract question.js already
            # implements for the lesson path).
            selected, _submitted = rehydrate(question, response.latest_answer)
            return HttpResponse(
                question.render(
                    element=element,
                    mode="quiz",
                    feedback_for_pk=element.pk,
                    action_url=reverse(
                        "courses:quiz_answer",
                        kwargs={
                            "slug": node.course.slug,
                            "node_pk": node.pk,
                            "element_pk": element.pk,
                        },
                    ),
                    selected_ids=selected,
                    mark_result=result if response.locked else None,
                    locked=response.locked,
                    attempts_left=fb_ctx.get("attempts_left"),
                    feedback_html=render_to_string(
                        "courses/elements/_quiz_question_feedback.html", fb_ctx
                    ),
                )
            )
        return render(request, "courses/elements/_quiz_question_feedback.html", fb_ctx)
    # No-JS: full quiz_unit re-render. Inject THIS question's fragment into its
    # single feedback box (render_states[pk]["feedback_html"]) and rehydrate its
    # inputs — the same render path resume (Task 12) uses, so no double container.
    ctx = build_quiz_context(node, request.user)
    drafts = "keep" if can_see_drafts(request.user, node.course) else "hide"
    # Task 15 §5: the student-facing draft banner's is_author flag -- see the
    # matching comment in full_lesson_render_context.
    ctx["is_author"] = drafts == "keep"
    ctx["unit_nav"] = build_unit_nav(node.course, request.user, node, drafts=drafts)
    # The quiz page renders TWICE: this no-JS answer path re-renders
    # quiz_unit.html with its own context, so applying the widening only in
    # quiz_unit would leave this render on the un-widened flag. Masked today
    # because has_math = bool(questions) or ... and this path is reachable only
    # when the quiz HAS questions -- but that over-inclusiveness is an "accepted
    # tradeoff" the code comment says may be tightened later, at which point the
    # omission goes live. Knowingly uncovered BEHAVIOURALLY (a gate assertion
    # here would be vacuous); pinned instead by the call-site count test.
    _widen_has_math_for_titles(ctx, node)
    fragment = render_to_string("courses/elements/_quiz_question_feedback.html", fb_ctx)
    st = ctx["render_states"].get(element.pk)
    if st is not None:
        st["feedback_html"] = fragment
        # A previewer has responses == {}, so build_quiz_context derives locked=False
        # for every question while the injected fragment still emits data-quiz-locked
        # -- "Answer recorded" beside a live Check button. True no-op for a student:
        # writes the value build_quiz_context already derived from the saved response.
        st["locked"] = response.locked
        selected, submitted = rehydrate(question, response.latest_answer)
        st["selected_ids"] = selected
        st["submitted_values"] = submitted
        # Same locked-only gate build_quiz_context applies. Needed here for the
        # PREVIEWER, whose responses map is empty, so build_quiz_context derived
        # nothing to mark this question's options with.
        st["mark_result"] = result if response.locked else None
    return render(request, "courses/quiz_unit.html", ctx)


@require_POST
@login_required
def quiz_answer(request, slug, node_pk, element_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_quiz=True
    )
    course = node.course
    if not can_access_course(request.user, course):
        raise PermissionDenied

    element = get_object_or_404(
        Element.objects.select_related("unit__course"), pk=element_pk, unit=node
    )
    question = element.content_object
    if not isinstance(question, QuestionElement):
        raise Http404("not a question element")

    if not is_enrolled(request.user, course):
        # Previewer: grade ephemerally, persist NOTHING (no QuizSubmission, no
        # QuestionResponse, no Attempt). Returns before the transaction below, so
        # no write path is reachable.
        #
        # SAFETY INVARIANT for the client-supplied `attempt`: can_access_course
        # above delegates to accessible_courses (courses/access.py), which is
        # staff | owned | enrolled | taught. So reaching here implies staff, owner,
        # or group teacher -- a plain student is either enrolled (persisted path
        # below) or already denied. If accessible_courses ever widens, this becomes
        # a student-reachable answer oracle. Pinned by
        # tests/test_quiz_previewer_answer.py::test_non_privileged_user_still_denied.
        #
        # Resolution now precedes this branch, so a previewer gets the student's 404
        # rules instead of a blanket 403. Deliberate.
        attempt = parse_attempt(request.POST)
        stand_in, result, validation = ephemeral_quiz_feedback(
            question, question.build_answer(request.POST), attempt
        )
        return _quiz_render_feedback(
            request,
            node,
            element,
            question,
            stand_in,
            result=result,
            validation=validation,
        )

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
        # ONE lock rule, shared with the ephemeral previewer path -- see
        # courses.quiz.locked_after and tests/test_quiz_lock_rule_parity.py.
        response.locked = locked_after(question, result, response.attempt_count)
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


@require_POST
@login_required
def quiz_finish(request, slug, node_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_quiz=True
    )
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
            quiz_svc.finalize_submission(node, submission)
            progress, _ = UnitProgress.objects.get_or_create(
                student=request.user, unit=node
            )
            if not progress.completed:
                progress.completed = True
                progress.save()
            from notifications.services import notify_needs_review

            notify_needs_review(submission, actor=request.user)

            from integrations.services import emit_result_finalized

            emit_result_finalized(submission)
    return redirect("courses:quiz_results", slug=slug, node_pk=node_pk)


@login_required
def quiz_results(request, slug, node_pk):
    node = get_node_or_404(
        node_pk, slug, viewer=request.user, require_unit=True, require_quiz=True
    )
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
    pending_count = 0
    pending_marks = Decimal("0.00")
    has_math = False
    # One-time post-submit render; the per-question choices/blanks access in
    # _results_row is an accepted N+1 here (not worth a prefetch pass for 2c).
    for el in node.elements.order_by("order", "pk").prefetch_related("content_object"):
        q = el.content_object
        if not isinstance(q, QuestionElement):
            continue
        if q.marking_mode == QuestionElement.MarkingMode.REVIEW:
            pending_count += 1
            pending_marks += q.max_marks
        if not has_math:
            has_math = _question_has_math(q)
        r = responses.get(el.pk)
        rows.append(_results_row(q, r))
    has_math = has_math or titles_have_math([node.title])
    ctx = {
        "course": course,
        "unit": node,
        "submission": submission,
        "rows": rows,
        "pending_count": pending_count,
        "pending_marks": pending_marks,
        "has_math": has_math,
    }
    from tags.rendering import unit_tags_context

    ctx.update(
        unit_tags_context(
            request.user, node, panel_open=request.GET.get("panel") == "tags"
        )
    )
    ctx.update(unit_edit_context(request.user, node))
    return render(request, "courses/quiz_results.html", ctx)


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
        "marks": None,
        "answered": response is not None and response.latest_answer is not None,
        "review_feedback": (response.review_feedback if response else ""),
        "review_earned": (response.earned_marks if response else None),
    }
    if mode == QuestionElement.MarkingMode.NOT_MARKED:
        row["outcome"] = "recorded" if response else "not_answered"
    elif mode == QuestionElement.MarkingMode.REVIEW:
        if response is not None and response.reviewed_at is not None:
            row["outcome"] = "reviewed"
            row["earned"] = response.earned_marks
        else:
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
            # Per-option markers, same vocabulary the locked quiz page uses. Without
            # these _reveal_choice.html shows the answer KEY only — it was the one
            # reveal partial of seven that never marked the student's own answer, so
            # a multi-select row could not distinguish a correct option the student
            # picked from one they missed. locked=True: a submitted question is
            # terminal, so the withhold window is over by definition.
            row["marks"] = question.choice_marks(
                row["choices"],
                selected_ids(
                    answer_from_json(question, response.latest_answer)
                    if response is not None and response.latest_answer is not None
                    else set()
                ),
                row["reveal_result"],
                "quiz",
                True,
            )
    # Suppress the reveal on a correct outcome ONLY for types whose reveal is the
    # answer key alone — echoing it would tell the student nothing they did not just
    # get right. A reveal that marks their OWN answer (choice) still says WHAT they
    # answered, which the results page is otherwise the only place to see, and a
    # submitted quiz redirects here. Precomputed: `A and B or C` binds the wrong way
    # in a template.
    row["show_reveal"] = bool(row["reveal_template"]) and (
        row["outcome"] != "correct" or bool(row["marks"])
    )
    return row


@login_required
def catalog(request):
    """Browse open courses the student may self-enroll in. Filters are GET params
    composed on the (unfiltered) eligible set; option lists derive from that
    unfiltered set so picking one filter never erases the others' options."""
    from grouping.services import catalog_courses_for

    eligible = catalog_courses_for(request.user)

    subjects = (
        Subject.objects.filter(courses__in=eligible.values("pk"))
        .distinct()
        .localized_order()
    )
    lang_labels = dict(COURSE_LANGUAGES)
    languages = [
        {"code": code, "label": lang_labels.get(code, code)}
        for code in eligible.values_list("language", flat=True).distinct()
    ]

    sel_subject = request.GET.get("subject") or ""
    sel_language = request.GET.get("language") or ""
    q = (request.GET.get("q") or "").strip()

    qs = eligible
    if sel_subject:
        qs = qs.filter(subjects__id=sel_subject).distinct()
    if sel_language:
        qs = qs.filter(language=sel_language)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(overview__icontains=q))
    qs = qs.order_by("title")
    qs = qs.prefetch_related("subjects")

    enrolled_ids = set(
        Enrollment.objects.filter(
            student=request.user, course__in=qs.values("pk")
        ).values_list("course_id", flat=True)
    )
    return render(
        request,
        "courses/catalog.html",
        {
            "courses": qs,
            "enrolled_ids": enrolled_ids,
            "subjects": subjects,
            "languages": languages,
            "sel_subject": sel_subject,
            "sel_language": sel_language,
            "q": q,
        },
    )


@login_required
def catalog_detail(request, slug):
    """Pre-enroll overview: modal fragment (XHR) or full-page fallback. Gated by
    can_self_enroll OR is_enrolled (NOT can_access_course). The body branches on
    is_enrolled so an already-enrolled user never sees an Enroll button."""
    from grouping.services import can_self_enroll

    course = get_object_or_404(Course, slug=slug)
    enrolled = is_enrolled(request.user, course)
    if not (enrolled or can_self_enroll(request.user, course)):
        raise Http404
    ctx = {
        "course": course,
        "enrolled": enrolled,
        "unit_count": course.nodes.filter(kind="unit", published=True).count(),
    }
    if _wants_fragment(request):
        return render(request, "courses/_catalog_detail.html", ctx)
    return render(request, "courses/catalog_detail.html", ctx)


@login_required
@require_POST
def self_enroll(request, slug):
    """Self-enroll the student in an open course. Re-checks eligibility server-side
    (the button is never trusted); ineligible -> 404. Calls the enroll_self service."""
    from grouping.services import can_self_enroll
    from grouping.services import enroll_self

    course = get_object_or_404(Course, slug=slug)
    if not can_self_enroll(request.user, course):
        raise Http404
    enroll_self(request.user, course)
    messages.success(
        request, _("You're now enrolled in %(course)s.") % {"course": course.title}
    )
    return redirect("courses:course_outline", slug=course.slug)
