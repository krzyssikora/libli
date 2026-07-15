import pytest

from courses.builder import NestingError
from courses.builder import resolve_scope
from courses.models import Element
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit


@pytest.mark.django_db
def test_two_column_not_nestable_itself():
    from courses.builder import NESTABLE_TYPE_KEYS

    assert "two_column" not in NESTABLE_TYPE_KEYS
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
def test_resolve_scope_rejects_container_child_in_two_column():
    _, unit = make_course_with_unit()
    col = TwoColumnElement(data=TwoColumnElement.default_data())
    col.save()
    join = Element.objects.create(unit=unit, content_object=col)
    cid = col.data["columns"][0]["id"]
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), cid, "tabs")  # containers can't nest
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), cid, "choicequestion")  # questions can't nest


@pytest.mark.django_db
def test_resolve_scope_rejects_non_container_parent():
    _, unit = make_course_with_unit()
    txt = TextElement.objects.create(body="hi")
    join = Element.objects.create(unit=unit, content_object=txt)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), "c000abc", "text")
