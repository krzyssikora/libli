import pytest

from courses.builder import NestingError
from courses.builder import resolve_scope
from courses.models import Element
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit
from tests.factories import make_quiz_unit


@pytest.mark.django_db
def test_two_column_is_nestable_under_its_transfer_key_only():
    from courses.builder import NESTABLE_TYPE_KEYS

    assert "two_column" in NESTABLE_TYPE_KEYS
    # the FORM key is never a member -- resolve_scope translates it via
    # _NESTABLE_FORM_KEY_ALIASES before testing membership
    assert "twocolumn" not in NESTABLE_TYPE_KEYS


@pytest.mark.django_db
def test_resolve_scope_accepts_two_column_parent():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    parent_join, tab_id = resolve_scope(unit, str(join.pk), cid, "text")
    assert parent_join == join and tab_id == cid


@pytest.mark.django_db
def test_resolve_scope_rejects_unknown_column():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), "cffffff", "text")


@pytest.mark.django_db
def test_resolve_scope_accepts_a_container_child_in_two_column():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    # depth-1 parent: a container child lands at depth 2 and is legal
    parent_join, tab_id = resolve_scope(unit, str(join.pk), cid, "tabs")
    assert parent_join == join and tab_id == cid
    # extended_response is the question type the widening deliberately left OUT, so
    # the allowlist still refuses it. (`choicequestion` used to sit here; it is now
    # accepted in a LESSON -- see the test below.)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), cid, "extendedresponsequestion")


@pytest.mark.django_db
def test_resolve_scope_accepts_a_question_child_in_a_lesson_two_column():
    """The FORM key, `choicequestion` -- the exact string element_add hands
    resolve_scope after collapsing the choice-single/choice-multi cards. If the
    alias were keyed on a card name instead, this would 400 while the drift test
    stayed green. The quiz-refusal companion lands with the gate that makes it
    pass, not here."""
    _, unit = make_course_with_unit()  # a LESSON
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    parent_join, tab_id = resolve_scope(unit, str(join.pk), cid, "choicequestion")
    assert parent_join == join and tab_id == cid


@pytest.mark.django_db
def test_resolve_scope_refuses_a_question_child_in_a_QUIZ_two_column():
    """The quiz-refusal companion the acceptance test above deferred. Same FORM key
    (`choicequestion`), same column, only the unit's type differs -- so the alias
    still has to resolve for the clause to be reached at all."""
    course, _lesson = make_course_with_unit()
    quiz = make_quiz_unit(course=course)
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=quiz, content_object=col)
    cid = col.data["columns"][0]["id"]
    with pytest.raises(NestingError):
        resolve_scope(quiz, str(join.pk), cid, "choicequestion")
    # Not "a quiz refuses every nested child": a text child is still fine.
    parent_join, tab_id = resolve_scope(quiz, str(join.pk), cid, "text")
    assert parent_join == join and tab_id == cid


@pytest.mark.django_db
def test_resolve_scope_rejects_non_container_parent():
    _, unit = make_course_with_unit()
    txt = TextElement.objects.create(body="hi")
    join = Element.objects.create(unit=unit, content_object=txt)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), "c000abc", "text")
