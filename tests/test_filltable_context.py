import pytest
from django.contrib.contenttypes.models import ContentType

from courses.models import Element
from courses.models import FillTableElement
from courses.views import build_lesson_context

pytestmark = pytest.mark.django_db


@pytest.fixture
def unit_with_element():
    """Factory fixture: unit_with_element(el) attaches the passed unsaved concrete
    element to a fresh lesson unit and returns the unit."""
    from tests.factories import make_course_with_unit

    def _make(el):
        el.save()
        _course, unit = make_course_with_unit()
        Element.objects.create(
            unit=unit,
            content_type=ContentType.objects.get_for_model(type(el)),
            object_id=el.pk,
        )
        return unit

    return _make


@pytest.fixture
def ctx_for():
    """Factory fixture: ctx_for(unit) calls build_lesson_context for that unit and
    returns the ctx dict. May be invoked more than once per test, so each call gets
    its own uniquely-named user."""
    import itertools

    from tests.factories import make_verified_user

    counter = itertools.count()

    def _make(unit):
        n = next(counter)
        user = make_verified_user(
            username=f"student_filltable_ctx_{n}",
            email=f"student_filltable_ctx_{n}@school.edu",
        )
        return build_lesson_context(unit, user)

    return _make


def test_has_fill_table_flag(unit_with_element, ctx_for):
    unit = unit_with_element(
        FillTableElement(data={"cells": [[{"kind": "answer", "answer": "1"}]]})
    )
    assert ctx_for(unit)["has_fill_table"] is True


def test_has_fill_table_flag_false_without_element():
    from tests.factories import make_course_with_unit
    from tests.factories import make_verified_user

    _course, unit = make_course_with_unit()
    user = make_verified_user(username="student_filltable_ctx_none")
    ctx = build_lesson_context(unit, user)
    assert ctx["has_fill_table"] is False


def test_has_math_only_when_static_cell_has_math(unit_with_element, ctx_for):
    plain = unit_with_element(
        FillTableElement(data={"cells": [[{"kind": "answer", "answer": "1"}]]})
    )
    assert ctx_for(plain)["has_math"] is False
    mathy = unit_with_element(
        FillTableElement(
            data={
                "cells": [
                    [
                        {"kind": "static", "html": r"\(x\)"},
                        {"kind": "answer", "answer": "1"},
                    ]
                ]
            }
        )
    )
    assert ctx_for(mathy)["has_math"] is True
