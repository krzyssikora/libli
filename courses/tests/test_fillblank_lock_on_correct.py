"""A fully-correct fill-blank answer locks its blanks (lesson mode).

Before this, a lesson fill-blank stayed editable after a correct answer: question.js
hid the Check button but left every <input name="blank"> writable, so a student could
retype the answer (and, via implicit Enter submission, overwrite the stored practice
state with a wrong one). The server side of the lock lives here; the live JS-fetch
path is covered by tests/test_e2e_fillblank_lock.py.

The lock is deliberately paired with `element.pk == feedback_for_pk`: the no-JS
re-render passes ONE mark_result down to EVERY element on the page (see
_lesson_article.html), so a bare `mark_result.correct` check would lock every other
fill-blank on the unit too (test_sibling_fillblank_is_not_locked pins that).
"""

import re

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import Enrollment
from courses.models import FillBlankQuestionElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db

_BLANK_INPUT_RE = re.compile(r'<input[^>]*name="blank"[^>]*>')
_CHECK_BUTTON_RE = re.compile(r'<button[^>]*type="submit"[^>]*>')


def _enrolled(client):
    student = make_student(client, "fb_lock")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    return student, course, unit


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _check_url(unit, element_pk):
    return reverse(
        "courses:check_answer",
        kwargs={"slug": unit.course.slug, "node_pk": unit.pk, "element_pk": element_pk},
    )


def _make_fillblank(unit, author_stem, accepted):
    """Author stem -> tokenized stem + Blank rows + join row. A plain .objects.create
    runs NO tokenizer, so the stem must go through fillblank.parse() or no input
    renders at all."""
    token_stem, _blanks = parse(author_stem)
    obj = FillBlankQuestionElement.objects.create(stem=token_stem)
    for i, acc in enumerate(accepted):
        Blank.objects.create(question=obj, order=i, accepted=acc)
    return obj, Element.objects.create(unit=unit, content_object=obj)


def _fillblank_forms(html):
    """The rendered fill-blank forms, in page order. Scoping matters: a lesson page
    carries other <form>s (nav/search/notes) whose submit buttons must not be
    mistaken for this question's Check button."""
    blocks = [b.split("</form>")[0] for b in html.split("el--fillblank")[1:]]
    assert blocks, "no fill-blank element rendered"
    return blocks


def _blank_inputs(html):
    tags = _BLANK_INPUT_RE.findall(html)
    assert tags, "no <input name='blank'> rendered — the stem was not tokenized"
    return tags


def test_restore_correct_locks_every_blank(client):
    # Reload after a correct answer: the restore path re-marks server-side, so the
    # refilled blanks must come back read-only, not editable.
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(
        unit, "Cap is {{paris}} on the {{seine}}.", ["paris", "seine"]
    )
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(row.pk): {"answer": ["paris", "seine"]}},
    )
    body = client.get(_lesson_url(unit)).content.decode()
    tags = _blank_inputs(body)
    assert len(tags) == 2
    for tag in tags:
        assert "readonly" in tag, f"blank stayed editable after a correct answer: {tag}"


def test_restore_correct_disables_the_check_button(client):
    # No-JS students get no boot pass to hide the button; a solved question must not
    # offer a re-check.
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"answer": ["paris"]}}
    )
    body = client.get(_lesson_url(unit)).content.decode()
    (form,) = _fillblank_forms(body)
    buttons = _CHECK_BUTTON_RE.findall(form)
    assert buttons, "no Check button rendered"
    assert all("disabled" in b for b in buttons)


def test_restore_incorrect_keeps_the_check_button_live(client):
    # Pairs with the test above: the disable must key on the verdict, not on
    # "an answer was restored".
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"answer": ["london"]}}
    )
    body = client.get(_lesson_url(unit)).content.decode()
    (form,) = _fillblank_forms(body)
    buttons = _CHECK_BUTTON_RE.findall(form)
    assert buttons, "no Check button rendered"
    assert not any("disabled" in b for b in buttons)


def test_restore_incorrect_leaves_blanks_editable(client):
    # A wrong answer must stay retryable — the lock is for the correct verdict only.
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    UnitProgress.objects.create(
        student=student, unit=unit, element_state={str(row.pk): {"answer": ["london"]}}
    )
    body = client.get(_lesson_url(unit)).content.decode()
    for tag in _blank_inputs(body):
        assert "readonly" not in tag, f"a wrong answer must stay editable: {tag}"


def test_restore_partially_correct_leaves_blanks_editable(client):
    # One of two blanks right => mark_result.correct is False => no lock.
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(unit, "{{paris}} on the {{seine}}.", ["paris", "seine"])
    UnitProgress.objects.create(
        student=student,
        unit=unit,
        element_state={str(row.pk): {"answer": ["paris", "thames"]}},
    )
    body = client.get(_lesson_url(unit)).content.decode()
    for tag in _blank_inputs(body):
        assert "readonly" not in tag, f"a partly-wrong answer must stay editable: {tag}"


def test_nojs_correct_post_locks_blanks(client):
    # No fetch header => the full-page re-render path, where mark_result is the
    # page-level context value.
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    body = client.post(_check_url(unit, row.pk), {"blank": ["paris"]}).content.decode()
    for tag in _blank_inputs(body):
        assert "readonly" in tag, f"blank stayed editable after a correct POST: {tag}"


def test_nojs_wrong_post_leaves_blanks_editable(client):
    student, course, unit = _enrolled(client)
    _obj, row = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    body = client.post(_check_url(unit, row.pk), {"blank": ["london"]}).content.decode()
    for tag in _blank_inputs(body):
        assert "readonly" not in tag, (
            f"a wrong POST must leave the blank editable: {tag}"
        )


def test_sibling_fillblank_is_not_locked(client):
    # The no-JS re-render hands the SAME mark_result to every element on the page.
    # Answering question 1 correctly must not lock question 2's untouched blank.
    student, course, unit = _enrolled(client)
    _one, row_one = _make_fillblank(unit, "Cap is {{paris}}.", ["paris"])
    _two, _row_two = _make_fillblank(unit, "River is {{seine}}.", ["seine"])
    body = client.post(
        _check_url(unit, row_one.pk), {"blank": ["paris"]}
    ).content.decode()
    tags = _blank_inputs(body)
    assert len(tags) == 2
    assert "readonly" in tags[0], "the answered question's blank should be locked"
    assert "readonly" not in tags[1], "an unanswered sibling must stay editable"
