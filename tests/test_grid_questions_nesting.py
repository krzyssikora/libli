"""The two grid question types nest in a container, in a LESSON unit only.

`choice_grid` (the "Matrix question") and `multi_grid` (the "Multi-select grid") were
the last two question types held out of `NESTABLE_TYPE_KEYS`. Everything they need
already existed -- `render_element`'s question branch, `CalloutElement`'s generic
child loop, `unit_has_nested_question`'s all-models predicate -- so widening the two
frozensets and adding the two form-key aliases is the whole change.

The parametrized authority tests live with their siblings
(courses/tests/test_nested_question_gates.py for resolve_scope/paste_allowed's
lesson-only clause, test_nested_question_add.py for the endpoint, and
test_spoiler_nesting.py for the add-menu cards). This file carries what those
matrices do NOT reach:

* the MOVE, which is how existing content gets repaired -- an author who already has
  a grid stranded next to the callout it belongs to marks it and pastes it in. That
  path is `paste_allowed`'s clause 2, keyed on `model_to_key(type(...))` rather than
  on a posted form key, so nothing in the add-side matrices exercises it.
* the SAVE. `element_add` is render-only -- it returns an empty form fragment and
  creates no row -- so every add-side assertion is about MARKUP. Nothing there proves
  a nested grid reaches the database with its `parent` set, and a save that dropped
  the scope would 200 while stranding the grid exactly where it started.
* the STUDENT page, which is the point of the feature. A gate can open while the
  render stays broken; `render_element` reaches a nested question through a different
  branch than a nested container, and a grid is the first nested type whose widget is
  a <table>.
* `validate_nesting`, so an archive carrying this new shape still imports (and a
  quiz-nested one still does not). The DOCUMENT-level walk only -- a full
  export/import round trip of a nested grid is not covered here.

Deliberately NOT re-tested here: that a grid MARKS correctly when nested. Marking runs
off `element_pk` in `check_answer` and never consults the parent, and
tests/test_marking_choicegrid.py already covers the marking itself -- a nested copy
would pass for reasons that have nothing to do with nesting.
"""

import pytest
from django.urls import reverse

from courses import builder
from courses.builder import NESTABLE_QUESTION_KEYS
from courses.builder import NESTABLE_TYPE_KEYS
from courses.models import CalloutElement
from courses.models import ChoiceGridQuestionElement
from courses.models import Element
from courses.models import Enrollment
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.transfer.export import SERIALIZERS
from courses.transfer.payloads import validate_nesting
from courses.transfer.schema import TransferError
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db

GRID_KEYS = ["choice_grid", "multi_grid"]


def _choice_grid():
    """A 2x2 matrix question. Returns (question, first_row, true_column)."""
    q = ChoiceGridQuestionElement.objects.create(stem="MATRIXSTEM")
    yes = GridColumn.objects.create(question=q, label="MATRIXCOLYES")
    no = GridColumn.objects.create(question=q, label="MATRIXCOLNO")
    r1 = GridRow.objects.create(
        question=q, statement="MATRIXROWONE", correct_column=yes
    )
    GridRow.objects.create(question=q, statement="MATRIXROWTWO", correct_column=no)
    return q, r1, yes


def _multi_grid():
    q = MultiGridQuestionElement.objects.create(stem="MULTISTEM")
    a = MultiGridColumn.objects.create(question=q, label="MULTICOLA")
    MultiGridColumn.objects.create(question=q, label="MULTICOLB")
    r1 = MultiGridRow.objects.create(question=q, statement="MULTIROWONE")
    r1.correct_columns.add(a)
    return q, r1, a


GRID_FACTORIES = [
    pytest.param(_choice_grid, id="choice_grid"),
    pytest.param(_multi_grid, id="multi_grid"),
]


# --------------------------------------------------------------------------
# The allowlists themselves
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", GRID_KEYS)
def test_a_grid_key_is_nestable_and_is_a_question(key):
    """Both sets, not just the wider one. In NESTABLE_TYPE_KEYS alone a grid nests
    fine -- and nests in a QUIZ, where no question may go."""
    assert key in NESTABLE_TYPE_KEYS
    assert key in NESTABLE_QUESTION_KEYS


@pytest.mark.parametrize("key", GRID_KEYS)
def test_a_grid_key_is_a_serializer_key(key):
    """The invariant NESTABLE_TYPE_KEYS <= set(SERIALIZERS): a nestable key with no
    serializer exports a container whose child silently vanishes from the archive."""
    assert key in SERIALIZERS


# --------------------------------------------------------------------------
# The MOVE path (paste_allowed clause 2 / 2b)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("make_grid", GRID_FACTORIES)
def test_an_existing_grid_may_be_moved_into_a_callout_in_a_lesson(make_grid):
    """The repair path for content authored before the widening: the grid already
    exists at top level and the author marks it and pastes it into the callout.

    mode="move" deliberately -- that is what an author repairing existing content
    does, and it is the mode that leaves nothing behind at top level.
    """
    _course, lesson = make_course_with_unit()
    grid, _row, _col = make_grid()
    marked = add_element(lesson, grid)
    dest = add_element(lesson, CalloutElement.objects.create(kind="task"))

    assert builder.paste_allowed(
        lesson, marked, dest, CalloutElement.SLOT_ID, "move"
    ) == (True, None)


@pytest.mark.parametrize("make_grid", GRID_FACTORIES)
def test_the_same_move_is_refused_in_a_quiz(make_grid):
    """Clause 2b. Without `multi_grid`/`choice_grid` in NESTABLE_QUESTION_KEYS this
    returns (True, None) -- the widening would have opened a hole rather than a
    feature.
    """
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    grid, _row, _col = make_grid()
    marked = add_element(quiz, grid)
    dest = add_element(quiz, CalloutElement.objects.create(kind="task"))

    assert builder.paste_allowed(
        quiz, marked, dest, CalloutElement.SLOT_ID, "move"
    ) == (False, "question_in_quiz")


@pytest.mark.parametrize("make_grid", GRID_FACTORIES)
def test_a_grid_still_pastes_to_top_level_in_a_quiz(make_grid):
    """The control for the refusal above: clause 2b lives inside the
    `dest_parent is not None` branch, so building a quiz out of grids -- the ordinary
    way -- must stay legal. mode="copy": a top-level move to top level reports
    `own_slot` for a reason unrelated to this rule.
    """
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    grid, _row, _col = make_grid()
    marked = add_element(quiz, grid)

    assert builder.paste_allowed(quiz, marked, None, "", "copy") == (True, None)


# --------------------------------------------------------------------------
# The SAVE path (element_save)
# --------------------------------------------------------------------------


def _grid_post(unit, type_key, parent_join):
    """The wire shape the grid editor posts, scoped into a container slot.

    Copied from tests/test_save_choicegrid.py::_post and given `parent`/`tab`. The
    two formsets are what make this test worth having: both grid branches in
    `save_element` rebuild their columns/rows through formsets, and a branch that
    returns the concrete object without threading the resolved scope back would
    leave the row at TOP LEVEL -- a 200 that silently strands the grid exactly where
    it was before this feature.
    """
    row_correct = (
        {"rows-0-correct_temp_id": "c1", "rows-1-correct_temp_id": "c2"}
        if type_key == "choicegridquestion"
        # The multi-select twin: a row names a SET, so the field is plural and holds
        # a COMMA-JOINED string (element_forms.py:1165 is a CharField, seeded with
        # ",".join(...) -- NOT a repeated key, which Django would collapse to the
        # last value). A copy of the choice-grid keys here fails validation rather
        # than proving anything about nesting.
        else {"rows-0-correct_temp_ids": "c1", "rows-1-correct_temp_ids": "c2"}
    )
    return {
        "type": type_key,
        "element": "new",
        "unit": str(unit.pk),
        "unit_token": unit.updated.isoformat(),
        "parent": str(parent_join.pk),
        "tab": CalloutElement.SLOT_ID,
        "stem": "Pick the truths",
        "explanation": "",
        "marking_mode": "A",  # MarkingMode.AUTO == "A" (one char), NOT "AUTO"
        "max_attempts": "0",
        "max_marks": "1",
        "columns-TOTAL_FORMS": "2",
        "columns-INITIAL_FORMS": "0",
        "columns-MIN_NUM_FORMS": "0",
        "columns-MAX_NUM_FORMS": "1000",
        "columns-0-label": "True",
        "columns-0-temp_id": "c1",
        "columns-1-label": "False",
        "columns-1-temp_id": "c2",
        "rows-TOTAL_FORMS": "2",
        "rows-INITIAL_FORMS": "0",
        "rows-MIN_NUM_FORMS": "0",
        "rows-MAX_NUM_FORMS": "1000",
        "rows-0-statement": "2+2=4",
        "rows-1-statement": "5 is even",
        **row_correct,
    }


@pytest.mark.parametrize(
    ("type_key", "model"),
    [
        ("choicegridquestion", ChoiceGridQuestionElement),
        ("multigridquestion", MultiGridQuestionElement),
    ],
)
def test_a_grid_saves_INTO_the_callout_not_beside_it(client, type_key, model):
    """The write that the add endpoint only opens a form for.

    `element_add` creates no row at all -- it returns an empty form fragment -- so
    every add-side test is an assertion about MARKUP. This is the first assertion
    that a nested grid reaches the database with its `parent` and `tab_id` set, which
    is the whole point: a 200 with `parent=None` is precisely the stranded-sibling
    shape this feature exists to end.
    """
    owner = make_login(client, "owner")
    course, unit = make_course_with_unit(owner=owner)  # a LESSON unit
    callout_row = add_element(unit, CalloutElement.objects.create(kind="task"))

    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        _grid_post(unit, type_key, callout_row),
        HTTP_X_REQUESTED_WITH="fetch",
    )

    assert resp.status_code == 200
    child = Element.objects.get(parent=callout_row)
    assert isinstance(child.content_object, model)
    assert child.tab_id == CalloutElement.SLOT_ID
    # The formsets really ran: a branch that saved the question and dropped its
    # children would satisfy every assertion above.
    assert [c.label for c in child.content_object.columns.all()] == ["True", "False"]
    assert child.content_object.rows.count() == 2
    # And the answering fragment shows the new row, so the author sees it land in the
    # callout. element_save re-renders the container's editor scope; a grid whose
    # editor row raised inside that render would 500 rather than reach here, but a
    # row rendered OUTSIDE the callout would still 200 -- hence the id assertion.
    assert f'data-element="{child.pk}"' in resp.content.decode()


# --------------------------------------------------------------------------
# The student page
# --------------------------------------------------------------------------


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


@pytest.fixture
def enrolled(client):
    student = make_student(client, "grid")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    return unit


def test_a_matrix_nested_in_a_callout_renders_its_grid_on_the_student_page(
    enrolled, client
):
    """The payoff, and the one assertion that fails if only the gates were widened.

    Asserts the ROW STATEMENT and the radio `name="row_<pk>"`, not the stem: a stem
    renders from `question__stem` markup shared with every other question type, so a
    stem-only assertion stays green on a build that emits the wrapper and drops the
    table. The row input is emitted by `render_choice_grid` alone.
    """
    unit = enrolled
    callout_row = add_element(unit, CalloutElement.objects.create(kind="task"))
    grid, first_row, yes = _choice_grid()
    nested = Element.objects.create(
        unit=unit,
        content_object=grid,
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    body = client.get(_lesson_url(unit)).content.decode()

    # It rendered INSIDE the callout, not merely somewhere on the page.
    assert "callout__child" in body
    assert "MATRIXROWONE" in body
    assert f'name="row_{first_row.pk}"' in body
    assert f'value="{yes.pk}"' in body
    # ...and its Check posts to the CHILD's own endpoint. The full reversed URL, not
    # a bare pk: Element and ContentNode draw from independent Postgres sequences, so
    # a bare f"/{pk}/" could match the node segment instead.
    assert f'action="{_check_url(unit, nested.pk)}"' in body


def test_a_multigrid_nested_in_a_callout_renders_its_grid_on_the_student_page(
    enrolled, client
):
    """The twin. Its widget differs from the matrix's by ONE attribute
    (`type="checkbox"` vs `type="radio"`), which is why both are asserted -- a
    render that fell back to the choice-grid template would otherwise pass.
    """
    unit = enrolled
    callout_row = add_element(unit, CalloutElement.objects.create(kind="task"))
    grid, first_row, col_a = _multi_grid()
    nested = Element.objects.create(
        unit=unit,
        content_object=grid,
        parent=callout_row,
        tab_id=CalloutElement.SLOT_ID,
    )

    body = client.get(_lesson_url(unit)).content.decode()

    assert "callout__child" in body
    assert "MULTIROWONE" in body
    assert f'name="row_{first_row.pk}"' in body
    assert f'value="{col_a.pk}"' in body
    assert 'type="checkbox"' in body
    assert f'action="{_check_url(unit, nested.pk)}"' in body


# --------------------------------------------------------------------------
# The archive
# --------------------------------------------------------------------------


def _nested_grid_doc(key, unit_type):
    """A minimal two-element nesting as validate_nesting reads it: a callout parent
    and one grid child. Only the keys the walk touches are present -- it is pure
    dict-walking and never builds a model."""
    return [
        {
            "id": "parent",
            "type": "callout",
            "unit": "n1",
            "parent": None,
            "tab": "",
        },
        {
            "id": "child",
            "type": key,
            "unit": "n1",
            "parent": "parent",
            "tab": CalloutElement.SLOT_ID,
        },
    ], {"n1": unit_type}


@pytest.mark.parametrize("key", GRID_KEYS)
def test_validate_nesting_accepts_a_grid_nested_in_a_lesson(key):
    elements, unit_types = _nested_grid_doc(key, "lesson")
    validate_nesting(elements, unit_types=unit_types)  # does not raise


@pytest.mark.parametrize("key", GRID_KEYS)
def test_validate_nesting_refuses_a_grid_nested_in_a_quiz(key):
    """The archive-side half of the lesson-only rule. `unit_types=None` (a caller
    that passes no versions) would skip the clause entirely, so it is passed here."""
    elements, unit_types = _nested_grid_doc(key, "quiz")
    with pytest.raises(TransferError):
        validate_nesting(elements, unit_types=unit_types)
