"""Question editor attempts field (spec 2026-10-20 §5.1)."""

import pytest
from django.urls import reverse

from courses import attempts as A
from courses.element_forms import FORM_FOR_TYPE
from courses.element_forms import ShortTextQuestionElementForm
from courses.element_forms import _MarkingFieldsMixin
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db

QUESTION_FORMS = [
    f for f in FORM_FOR_TYPE.values() if issubclass(f, _MarkingFieldsMixin)
]


def _data(**over):
    d = {
        "stem": "Capital?",
        "explanation": "",
        "accepted": "Paris",
        "marking_mode": "A",
        "max_marks": "1",
    }
    d.update(over)
    return d


def _bound(unit, instance=None, **over):
    return ShortTextQuestionElementForm(
        data=_data(**over), instance=instance, unit=unit
    )


def test_ten_question_forms():
    assert len(QUESTION_FORMS) == 10


@pytest.mark.parametrize("FormCls", QUESTION_FORMS)
def test_every_question_form_exposes_both_fields_in_a_quiz(FormCls):
    # DragToImage's _CourseScopedMediaForm defaults course=None, so all ten
    # construct with unit= alone.
    form = FormCls(unit=make_quiz_unit())
    assert {"attempts_mode", "attempts_limit"} <= set(form.fields)
    assert "max_attempts" not in form.fields


@pytest.mark.parametrize("FormCls", QUESTION_FORMS)
def test_every_question_form_lists_both_fields_in_meta(FormCls):
    # The mixin injects the fields regardless of Meta.fields, but construct_instance
    # only saves fields named in Meta.fields: a form that omits one silently drops
    # the author's choice on save.
    assert {"attempts_mode", "attempts_limit"} <= set(FormCls._meta.fields)


def test_unit_is_required():
    with pytest.raises(TypeError):
        ShortTextQuestionElementForm()


def test_inherit_label_names_its_source():
    unit = make_quiz_unit(attempts_mode="limited", attempts_limit=3)
    choices = dict(
        ShortTextQuestionElementForm(unit=unit).fields["attempts_mode"].choices
    )
    assert choices["inherit"] == "Same as quiz (currently: 3)"
    course = CourseFactory(attempts_mode="unlimited", attempts_limit=None)
    form = ShortTextQuestionElementForm(unit=make_quiz_unit(course=course))
    assert dict(form.fields["attempts_mode"].choices)["inherit"] == (
        "Same as course (currently: unlimited)"
    )


def test_limit_input_has_no_min_or_max():
    html = str(ShortTextQuestionElementForm(unit=make_quiz_unit())["attempts_limit"])
    assert "min=" not in html and "max=" not in html


def test_saves_limited():
    form = _bound(make_quiz_unit(), attempts_mode="limited", attempts_limit="4")
    assert form.is_valid(), form.errors
    q = form.save()
    assert (q.attempts_mode, q.attempts_limit) == ("limited", 4)


@pytest.mark.parametrize("junk", ["-1", "99999", "abc"])
@pytest.mark.parametrize("mode", ["unlimited", "inherit"])
def test_hidden_junk_is_harmless(mode, junk):
    form = _bound(make_quiz_unit(), attempts_mode=mode, attempts_limit=junk)
    assert form.is_valid(), form.errors
    q = form.save()
    assert (q.attempts_mode, q.attempts_limit) == (mode, None)


@pytest.mark.parametrize(
    "unit_kw,raw,field,message",
    [
        ({}, "", "attempts_limit", A.MSG_ENTER),
        ({}, "0", "attempts_limit", A.ZERO_MESSAGES["course"]),
        (
            {"attempts_mode": "limited", "attempts_limit": 2},
            "0",
            "attempts_limit",
            A.ZERO_MESSAGES["quiz"],
        ),
        ({}, "40000", "attempts_limit", A.MSG_CAP),
    ],
)
def test_limit_errors(unit_kw, raw, field, message):
    form = _bound(
        make_quiz_unit(**unit_kw), attempts_mode="limited", attempts_limit=raw
    )
    assert not form.is_valid()
    assert form.errors[field] == [str(message)]


@pytest.mark.parametrize("mode", ["", "bogus"])
def test_mode_errors(mode):
    form = _bound(make_quiz_unit(), attempts_mode=mode, attempts_limit="3")
    assert form.errors["attempts_mode"] == [str(A.MSG_CHOOSE)]


def test_absent_mode_keeps_stored_values():
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a", **attempts(3))
    form = _bound(unit, instance=q)  # no attempts keys posted
    assert form.is_valid(), form.errors
    form.save()
    q.refresh_from_db()
    assert (q.attempts_mode, q.attempts_limit) == ("limited", 3)


def test_lesson_question_ignores_crafted_attempts_keys():
    lesson = ContentNodeFactory(kind="unit", unit_type="lesson")
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a", **attempts(3))
    form = _bound(lesson, instance=q, attempts_mode="unlimited", attempts_limit="")
    assert "attempts_mode" not in form.fields
    assert form.is_valid(), form.errors
    form.save()
    q.refresh_from_db()
    assert (q.attempts_mode, q.attempts_limit) == ("limited", 3)


def test_editor_renders_the_select(client):
    make_pa(client)
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(stem="x", accepted="a")
    el = add_element(unit, q)
    url = reverse(
        "courses:manage_element_form", kwargs={"slug": unit.course.slug, "pk": el.pk}
    )
    html = client.get(url).content.decode()
    assert 'name="attempts_mode"' in html
    assert "Same as course (currently: 1)" in html
    assert "data-attempts-limit" in html
