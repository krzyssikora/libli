"""The lesson-only rule at the three `builder` authorities.

A question may be nested only in a LESSON unit. Three write paths in `builder` can
create or preserve such a nesting and each carries its own clause:

- `resolve_scope` -- the add/save path, refusing a NEW nesting;
- `paste_allowed` -- the clipboard path, refusing a MOVE or COPY into a container;
- `rename_node` -- the unit_type flip, refusing to PRESERVE an existing nesting by
  turning its lesson into a quiz.

The first two read `NESTABLE_QUESTION_KEYS`. The third deliberately does not: it goes
through `unit_has_nested_question()`, which spans every concrete question model, so a
nested `extended_response` planted by a crafted POST still bars the flip. The
`extended_response` case below is what pins that difference -- a `fill_blank` case
alone stays green under the narrowed predicate.
"""

import ast
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from courses import builder
from courses.builder import NestingError
from courses.models import CalloutElement
from courses.models import ChoiceQuestionElement
from courses.models import ContentNode
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import TabsElement
from courses.models import TextElement
from courses.views_manage import PASTE_REFUSAL_MESSAGES
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_course_with_unit
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _join(unit, obj, parent=None, tab=""):
    return Element.objects.create(
        unit=unit, content_object=obj, parent=parent, tab_id=tab
    )


def _callout(unit, parent=None, tab=""):
    return _join(unit, CalloutElement.objects.create(kind="example"), parent, tab)


def _choice(unit, parent=None, tab=""):
    return _join(
        unit,
        ChoiceQuestionElement.objects.create(stem="Pick one.", multiple=False),
        parent,
        tab,
    )


def _units():
    """(course, lesson, quiz) -- one course holding one of each unit type.

    make_course_with_unit() hard-codes unit_type="lesson" and splats **kw into
    CourseFactory, so the quiz half must come from make_quiz_unit(course=...).
    """
    course, lesson = make_course_with_unit()
    return course, lesson, make_quiz_unit(course=course)


# The nestable question types, as the FORM keys element_add hands over. Shared by the
# three parametrized cases below so a type widened at one authority can never be
# forgotten at the other two.
#
# `choicegridquestion` / `multigridquestion` joined the set when the two grid types
# were widened; unlike the other three their form key had no alias at all, so an
# un-aliased key falls through resolve_scope's `_NESTABLE_FORM_KEY_ALIASES.get(k, k)`
# UNCHANGED and misses NESTABLE_TYPE_KEYS -- which is why the acceptance half below
# is the one that fails without the alias entry.
QUESTION_FORM_KEYS = [
    "choicequestion",
    "shorttextquestion",
    "shortnumericquestion",
    "choicegridquestion",
    "multigridquestion",
]


# --------------------------------------------------------------------------
# Authority 1: resolve_scope
# --------------------------------------------------------------------------


@pytest.mark.parametrize("form_key", QUESTION_FORM_KEYS)
def test_resolve_scope_refuses_a_question_into_a_quiz_container(form_key):
    """FORM keys, as element_add hands them over: the clause tests the ALIASED key,
    so a clause written against the raw `type_key` would let every one of them
    through."""
    _course, _lesson, quiz = _units()
    dest = _callout(quiz)
    with pytest.raises(NestingError):
        builder.resolve_scope(quiz, str(dest.pk), CalloutElement.SLOT_ID, form_key)


@pytest.mark.parametrize("form_key", QUESTION_FORM_KEYS)
def test_resolve_scope_accepts_the_same_question_into_a_lesson_container(form_key):
    """The other direction, same call. Without it the refusal above is satisfied by
    dropping the keys from NESTABLE_TYPE_KEYS altogether."""
    _course, lesson, _quiz = _units()
    dest = _callout(lesson)
    parent, tab = builder.resolve_scope(
        lesson, str(dest.pk), CalloutElement.SLOT_ID, form_key
    )
    assert parent == dest
    assert tab == CalloutElement.SLOT_ID


def test_resolve_scope_still_accepts_a_non_question_into_a_quiz_container():
    """Nesting itself is untouched in a quiz -- only questions are refused."""
    _course, _lesson, quiz = _units()
    dest = _callout(quiz)
    parent, _tab = builder.resolve_scope(
        quiz, str(dest.pk), CalloutElement.SLOT_ID, "text"
    )
    assert parent == dest


def test_resolve_scope_still_accepts_a_question_at_top_level_in_a_quiz():
    """A quiz is made of questions. `parent`/`tab` absent means top level and
    resolve_scope returns before any clause runs -- pinned so a future clause is
    never hoisted above that early return."""
    _course, _lesson, quiz = _units()
    parent, tab = builder.resolve_scope(quiz, "", "", "choicequestion")
    assert (parent, tab) == (None, "")


# --------------------------------------------------------------------------
# Authority 2: paste_allowed (+ the endpoint's message)
# --------------------------------------------------------------------------


def test_paste_allowed_refuses_a_question_into_a_quiz_container():
    _course, _lesson, quiz = _units()
    dest = _callout(quiz)
    marked = _choice(quiz)
    assert builder.paste_allowed(
        quiz, marked, dest, CalloutElement.SLOT_ID, "move"
    ) == (False, "question_in_quiz")


def test_paste_allowed_accepts_the_same_paste_in_a_lesson():
    _course, lesson, _quiz = _units()
    dest = _callout(lesson)
    marked = _choice(lesson)
    assert builder.paste_allowed(
        lesson, marked, dest, CalloutElement.SLOT_ID, "move"
    ) == (True, None)


def test_paste_allowed_still_permits_a_TOP_LEVEL_paste_into_a_quiz():
    """The clause lives INSIDE the `dest_parent is not None` branch. Hoisted above
    it, this pasting-a-question-around-a-quiz case -- the ordinary way a quiz is
    authored -- starts returning question_in_quiz.

    mode="copy": a move of a top-level element to top level is its own slot and
    would report `own_slot` for a reason that has nothing to do with this rule.
    """
    _course, _lesson, quiz = _units()
    marked = _choice(quiz)
    assert builder.paste_allowed(quiz, marked, None, "", "copy") == (True, None)


def test_paste_allowed_still_permits_a_non_question_into_a_quiz_container():
    _course, _lesson, quiz = _units()
    dest = _callout(quiz)
    marked = _join(quiz, TextElement.objects.create(body="<p>x</p>"))
    assert builder.paste_allowed(
        quiz, marked, dest, CalloutElement.SLOT_ID, "move"
    ) == (True, None)


def _depth_4_container(unit):
    """A container sitting at depth 4, built through the ORM.

    UNREACHABLE through resolve_scope: clause 4 forbids a container at depth
    MAX_NEST_DEPTH-1 or deeper, so no authoring path produces this. Modelled on
    courses/tests/test_nesting_rule.py::_mk, which exists for the same reason.
    """
    cur = None
    for _ in range(3):
        tabs = TabsElement.objects.create(data=TabsElement.default_data())
        cur = _join(
            unit,
            tabs,
            cur,
            "" if cur is None else cur.content_object.data["tabs"][0]["id"],
        )
    dest = _callout(unit, cur, cur.content_object.data["tabs"][0]["id"])
    assert builder.element_depth(dest) == builder.MAX_NEST_DEPTH
    return dest


@pytest.mark.parametrize(
    ("unit_type", "expected"),
    [("quiz", "question_in_quiz"), ("lesson", "too_deep")],
)
def test_question_in_quiz_is_reported_BEFORE_too_deep(unit_type, expected):
    """Precedence, both directions. A question is a leaf, so min_headroom is
    MAX_NEST_DEPTH and too_deep needs a destination at depth 4 -- hence the hand-built
    chain. The lesson half is what fails if the clause is placed AFTER clause 3:
    without it, a clause in either position reports question_in_quiz for the quiz.
    """
    _course, lesson, quiz = _units()
    unit = quiz if unit_type == "quiz" else lesson
    dest = _depth_4_container(unit)
    marked = _choice(unit)
    assert builder.paste_allowed(
        unit, marked, dest, CalloutElement.SLOT_ID, "move"
    ) == (False, expected)


def test_every_paste_reason_has_a_message():
    """`ast`, not a source regex: paste_allowed's docstring lists the reason names in
    prose, so a regex over the source would sweep them and pass while a real
    `return False, "..."` had no entry. Restricted to Return nodes inside the
    function, which is exactly what it can hand the endpoint.
    """
    tree = ast.parse(Path(builder.__file__).read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "paste_allowed"
    )
    returned = {
        n.value.elts[1].value
        for n in ast.walk(fn)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Tuple)
        and len(n.value.elts) == 2
        and isinstance(n.value.elts[1], ast.Constant)
        and isinstance(n.value.elts[1].value, str)
    }
    # Not vacuous: the walk really did find the reasons, including the new one.
    assert "question_in_quiz" in returned
    # SUBSET, never equality: the map also holds `parent_gone`, which paste_allowed
    # never returns -- the paste VIEW supplies it from ParentGoneError.
    assert returned <= set(PASTE_REFUSAL_MESSAGES)


def test_the_paste_endpoint_shows_the_questions_own_message(client):
    """Asserted on the ENDPOINT, not on paste_allowed: a reason key with no entry in
    PASTE_REFUSAL_MESSAGES still returns 422, and _refused falls back to a generic
    "That placement is not allowed." A key-only assertion is green through that
    half-fix.
    """
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    quiz = make_quiz_unit(course=course)
    dest = _callout(quiz)
    marked = _choice(quiz)
    quiz.refresh_from_db()
    client.post(
        reverse("courses:manage_element_clip", kwargs={"slug": course.slug}),
        {"ctx": "editor", "element": marked.pk, "unit": quiz.pk, "action": "select"},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    quiz.refresh_from_db()
    resp = client.post(
        reverse("courses:manage_element_paste", kwargs={"slug": course.slug}),
        {
            "ctx": "editor",
            "parent": dest.pk,
            "tab": CalloutElement.SLOT_ID,
            "mode": "move",
            "unit": quiz.pk,
            "unit_token": quiz.updated.isoformat(),
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 422
    body = resp.content.decode()
    assert "Questions can only be placed inside a container in a lesson unit." in body
    assert "That placement is not allowed." not in body


# --------------------------------------------------------------------------
# Authority 3: rename_node's lesson -> quiz flip
# --------------------------------------------------------------------------


def _rename(course, node, unit_type):
    """The repo's rename_node call shape (tests/test_manage_builder.py).

    `token` must match node.updated EXACTLY or _check_token raises ConflictError
    before the flip guard runs, and `title` must be non-blank or full_clean rejects
    it -- either way the test would go green for the wrong reason.
    """
    node.refresh_from_db()
    return builder.rename_node(
        course, node.pk, node.title, node.updated.isoformat(), unit_type=unit_type
    )


def _nest_question(unit, model):
    parent = _callout(unit)
    return _join(unit, model.objects.create(stem="Q?"), parent, CalloutElement.SLOT_ID)


@pytest.mark.parametrize(
    "model", [FillBlankQuestionElement, ExtendedResponseQuestionElement]
)
def test_a_lesson_holding_a_nested_question_cannot_become_a_quiz(model):
    """`extended_response` is the case that pins the WIDTH of the predicate: it is
    not in NESTABLE_QUESTION_KEYS, so narrowing unit_has_nested_question to that set
    leaves the fill_blank case green and reopens the hole. It cannot be authored
    nested -- hence the direct Element.objects.create in _nest_question.
    """
    course, lesson, _quiz = _units()
    _nest_question(lesson, model)
    with pytest.raises(ValidationError):
        _rename(course, lesson, "quiz")
    lesson.refresh_from_db()
    assert lesson.unit_type == ContentNode.UnitType.LESSON


def test_a_lesson_whose_question_is_TOP_LEVEL_can_still_become_a_quiz():
    """`parent__isnull=False` is load-bearing: dropping it bars the flip for every
    lesson that has any question at all, which is most of them."""
    course, lesson, _quiz = _units()
    _join(lesson, FillBlankQuestionElement.objects.create(stem="Q?"))
    _rename(course, lesson, "quiz")
    lesson.refresh_from_db()
    assert lesson.unit_type == ContentNode.UnitType.QUIZ


def test_a_lesson_with_a_nested_NON_question_can_still_become_a_quiz():
    course, lesson, _quiz = _units()
    parent = _callout(lesson)
    _join(
        lesson,
        TextElement.objects.create(body="<p>x</p>"),
        parent,
        CalloutElement.SLOT_ID,
    )
    _rename(course, lesson, "quiz")
    lesson.refresh_from_db()
    assert lesson.unit_type == ContentNode.UnitType.QUIZ


def test_a_quiz_holding_a_nested_question_accepts_a_quiz_to_quiz_no_op():
    """The guard reads the PRE-assignment unit_type and fires only on a real change,
    so re-submitting the settings form on an already-quiz unit is not a refusal the
    author can do nothing about."""
    course, _lesson, quiz = _units()
    _nest_question(quiz, FillBlankQuestionElement)
    _rename(course, quiz, "quiz")
    quiz.refresh_from_db()
    assert quiz.unit_type == ContentNode.UnitType.QUIZ


def test_a_quiz_holding_a_nested_question_can_always_become_a_lesson():
    """The other direction is unconditional -- it only ever makes the nesting more
    correct, and it is the escape hatch the refusal message points at."""
    course, _lesson, quiz = _units()
    _nest_question(quiz, FillBlankQuestionElement)
    _rename(course, quiz, "lesson")
    quiz.refresh_from_db()
    assert quiz.unit_type == ContentNode.UnitType.LESSON


def test_unit_has_nested_question_is_scoped_to_its_own_unit():
    """The predicate filters on `unit`, so one lesson's nested question must not bar
    a sibling unit's flip."""
    course, lesson, _quiz = _units()
    other = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _nest_question(other, FillBlankQuestionElement)
    assert builder.unit_has_nested_question(other) is True
    assert builder.unit_has_nested_question(lesson) is False
    _rename(course, lesson, "quiz")
    lesson.refresh_from_db()
    assert lesson.unit_type == ContentNode.UnitType.QUIZ
