"""A fully-correct lesson answer locks the question (every inline-feedback type).

Fill-blank got this first (test_fillblank_lock_on_correct.py). Every OTHER lesson
question type only hid its Check button after a correct answer: the options /
inputs / drop slots stayed live, so a student could change a solved answer to a
wrong one while the "correct" verdict stayed painted (and printed), and a text
input's implicit Enter could still re-POST over the stored practice state.

"Locked" here means the browser treats the control as disabled: either the
control carries `disabled` itself or it sits inside a `<fieldset disabled>`.

The lock is paired with `element.pk == feedback_for_pk`: the no-JS re-render hands
ONE page-level mark_result to every element, so a bare `mark_result.correct` would
lock every sibling question too (test_sibling_question_is_not_locked pins that).
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import DragBlank
from courses.models import DragFillBlankQuestionElement
from courses.models import DragToImageQuestionElement
from courses.models import DragZone
from courses.models import Element
from courses.models import Enrollment
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import MatchPair
from courses.models import MatchPairQuestionElement
from courses.models import MediaAsset
from courses.models import MultiGridColumn
from courses.models import MultiGridQuestionElement
from courses.models import MultiGridRow
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


# Each builder creates the question on `unit` and returns
# (join_row, correct POST data, wrong POST data).
def _single_choice(unit):
    q = ChoiceQuestionElement.objects.create(stem="Q", multiple=False)
    right = Choice.objects.create(question=q, text="a", is_correct=True)
    wrong = Choice.objects.create(question=q, text="b", is_correct=False)
    return _add(unit, q), {"choice": [right.pk]}, {"choice": [wrong.pk]}


def _multiple_choice(unit):
    q = ChoiceQuestionElement.objects.create(stem="Q", multiple=True)
    a = Choice.objects.create(question=q, text="a", is_correct=True)
    b = Choice.objects.create(question=q, text="b", is_correct=True)
    c = Choice.objects.create(question=q, text="c", is_correct=False)
    return _add(unit, q), {"choice": [a.pk, b.pk]}, {"choice": [a.pk, c.pk]}


def _short_text(unit):
    q = ShortTextQuestionElement.objects.create(stem="Q", accepted="paris")
    return _add(unit, q), {"answer": "paris"}, {"answer": "london"}


def _short_numeric(unit):
    q = ShortNumericQuestionElement.objects.create(stem="Q", value="42", tolerance="")
    return _add(unit, q), {"answer": "42"}, {"answer": "41"}


def _choice_grid(unit):
    q = ChoiceGridQuestionElement.objects.create(stem="Q")
    col_a = GridColumn.objects.create(question=q, label="A")
    col_b = GridColumn.objects.create(question=q, label="B")
    r = GridRow.objects.create(question=q, statement="r1", correct_column=col_a)
    key = f"row_{r.pk}"
    return _add(unit, q), {key: str(col_a.pk)}, {key: str(col_b.pk)}


def _multi_grid(unit):
    q = MultiGridQuestionElement.objects.create(stem="Q")
    col_a = MultiGridColumn.objects.create(question=q, label="A")
    col_b = MultiGridColumn.objects.create(question=q, label="B")
    r = MultiGridRow.objects.create(question=q, statement="r1")
    r.correct_columns.add(col_a)
    key = f"row_{r.pk}"
    return _add(unit, q), {key: [str(col_a.pk)]}, {key: [str(col_b.pk)]}


def _match_pair(unit):
    q = MatchPairQuestionElement.objects.create(stem="Q", distractors="renal")
    MatchPair.objects.create(question=q, left="Heart", right="cardiac")
    return _add(unit, q), {"slot": ["cardiac"]}, {"slot": ["renal"]}


def _drag_fill(unit):
    q = DragFillBlankQuestionElement.objects.create(
        stem="Cap is ￿0￿", distractors="Rome"
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    return _add(unit, q), {"slot": ["Paris"]}, {"slot": ["Rome"]}


def _drag_image(unit):
    media = MediaAsset.objects.create(
        course=unit.course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )
    q = DragToImageQuestionElement.objects.create(
        media=media, alt="Diagram", distractors="Liver"
    )
    DragZone.objects.create(
        question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0
    )
    DragZone.objects.create(
        question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1
    )
    return _add(unit, q), {"slot": ["Heart", "Lung"]}, {"slot": ["Lung", "Heart"]}


BUILDERS = [
    pytest.param(_single_choice, id="choice"),
    pytest.param(_multiple_choice, id="mchoice"),
    pytest.param(_short_text, id="shorttext"),
    pytest.param(_short_numeric, id="shortnumeric"),
    pytest.param(_choice_grid, id="choicegrid"),
    pytest.param(_multi_grid, id="multigrid"),
    pytest.param(_match_pair, id="matchpair"),
    pytest.param(_drag_fill, id="dragfill"),
    pytest.param(_drag_image, id="dragimage"),
]


def _add(unit, obj):
    return Element.objects.create(unit=unit, content_object=obj)


def _enrolled(client):
    student = make_student(client, "q_lock")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    return student, unit


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _question_form(html, unit, row):
    """This question's <form>, found by its action. A lesson page carries other
    forms (nav, notes, sibling questions) that must not be mistaken for it."""
    form = BeautifulSoup(html, "html.parser").find(
        "form", action=_check_url(unit, row.pk)
    )
    assert form is not None, "question form not rendered"
    return form


def _is_disabled(tag):
    if tag.has_attr("disabled"):
        return True
    return any(fs.has_attr("disabled") for fs in tag.find_parents("fieldset"))


def _answer_controls(form):
    controls = [
        t
        for t in form.find_all(["input", "select", "textarea"])
        if t.get("type") != "hidden"
    ]
    assert controls, "no answer controls rendered"
    return controls


def _check_button(form):
    buttons = form.find_all("button", attrs={"type": "submit"})
    assert len(buttons) == 1, f"expected one Check button, got {len(buttons)}"
    return buttons[0]


def _assert_locked(form):
    live = [str(t) for t in _answer_controls(form) if not _is_disabled(t)]
    assert not live, f"answer controls stayed editable after a correct answer: {live}"
    assert _is_disabled(_check_button(form)), "Check button stayed live"


def _assert_unlocked(form):
    dead = [str(t) for t in _answer_controls(form) if _is_disabled(t)]
    assert not dead, f"a wrong answer must stay editable: {dead}"
    assert not _is_disabled(_check_button(form)), "Check button disabled"


@pytest.mark.parametrize("build", BUILDERS)
def test_fetch_correct_check_locks_the_question(client, build):
    # The live path: question.js swaps this fragment's form body into the page.
    _student, unit = _enrolled(client)
    row, right, _wrong = build(unit)
    body = client.post(
        _check_url(unit, row.pk), right, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    _assert_locked(_question_form(body, unit, row))


@pytest.mark.parametrize("build", BUILDERS)
def test_nojs_correct_check_locks_the_question(client, build):
    _student, unit = _enrolled(client)
    row, right, _wrong = build(unit)
    body = client.post(_check_url(unit, row.pk), right).content.decode()
    _assert_locked(_question_form(body, unit, row))


@pytest.mark.parametrize("build", BUILDERS)
def test_reload_after_correct_check_locks_the_question(client, build):
    # Restore path: the stored answer is re-marked server-side on the next GET.
    _student, unit = _enrolled(client)
    row, right, _wrong = build(unit)
    client.post(_check_url(unit, row.pk), right, HTTP_X_REQUESTED_WITH="fetch")
    body = client.get(_lesson_url(unit)).content.decode()
    _assert_locked(_question_form(body, unit, row))


@pytest.mark.parametrize("build", BUILDERS)
def test_wrong_answer_stays_editable(client, build):
    # The lock keys on the verdict, not on "an answer was checked / restored".
    _student, unit = _enrolled(client)
    row, _right, wrong = build(unit)
    fetched = client.post(
        _check_url(unit, row.pk), wrong, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    _assert_unlocked(_question_form(fetched, unit, row))
    reloaded = client.get(_lesson_url(unit)).content.decode()
    _assert_unlocked(_question_form(reloaded, unit, row))


def test_sibling_question_is_not_locked(client):
    # The no-JS re-render hands the SAME mark_result to every element on the page:
    # answering question 1 correctly must not lock an untouched question 2.
    _student, unit = _enrolled(client)
    row_one, right, _wrong = _multiple_choice(unit)
    row_two, _right_two, _wrong_two = _multiple_choice(unit)
    body = client.post(_check_url(unit, row_one.pk), right).content.decode()
    _assert_locked(_question_form(body, unit, row_one))
    _assert_unlocked(_question_form(body, unit, row_two))
