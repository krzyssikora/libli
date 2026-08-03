import pytest

from courses.builder import NestingError
from courses.builder import resolve_scope
from courses.models import Element
from courses.models import TextElement
from courses.models import TwoColumnElement
from tests.factories import make_course_with_unit


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
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), cid, "choicequestion")  # questions can't nest


@pytest.mark.django_db
def test_resolve_scope_rejects_non_container_parent():
    _, unit = make_course_with_unit()
    txt = TextElement.objects.create(body="hi")
    join = Element.objects.create(unit=unit, content_object=txt)
    with pytest.raises(NestingError):
        resolve_scope(unit, str(join.pk), "c000abc", "text")
