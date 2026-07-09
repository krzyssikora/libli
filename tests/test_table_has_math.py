"""has_math gating for TableElement: a table cell carrying inline math must
flip has_math (and therefore trigger a KaTeX asset load) on both the lesson
and quiz consumption pages."""

import pytest
from django.urls import reverse

from courses.models import Enrollment
from courses.models import TableElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _enrolled(client, unit_type):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type=unit_type
    )
    return course, unit


def _lesson_url(course, unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def _quiz_url(course, unit):
    return reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


def test_lesson_table_with_math_loads_katex(client):
    course, unit = _enrolled(client, "lesson")
    table = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{"html": r"\(x\)"}]]})
    )
    add_element(unit, table)
    resp = client.get(_lesson_url(course, unit))
    assert resp.status_code == 200
    assert "katex.min.js" in resp.content.decode()


def test_lesson_table_without_delimiters_does_not_load_katex(client):
    course, unit = _enrolled(client, "lesson")
    table = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{"html": "plain text"}]]})
    )
    add_element(unit, table)
    resp = client.get(_lesson_url(course, unit))
    assert resp.status_code == 200
    assert "katex.min.js" not in resp.content.decode()


def test_quiz_table_with_math_loads_katex(client):
    course, unit = _enrolled(client, "quiz")
    table = TableElement.objects.create(
        data=TableElement.normalize_data({"cells": [[{"html": r"\(x\)"}]]})
    )
    add_element(unit, table)
    resp = client.get(_quiz_url(course, unit))
    assert resp.status_code == 200
    assert "katex.min.js" in resp.content.decode()
