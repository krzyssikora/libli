"""The prepaint watchdog term is driven by has_filltable_gate, not by the mere
presence of a fill-table. Asserted as an A/B: the term's presence in a gated
render alone would prove nothing about what drives it."""

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import FillTableElement
from tests.factories import make_course_with_unit
from tests.factories import make_student

pytestmark = pytest.mark.django_db


def _lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


def _render_unit_with_filltable(client, slug, gate):
    student = make_student(client, slug)
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    ft = FillTableElement.objects.create(
        data={"gate": gate, "cells": [[{"kind": "answer", "answer": "1"}]]}
    )
    Element.objects.create(unit=unit, content_object=ft)
    return client.get(_lesson_url(unit)).content.decode()


def test_prepaint_watchdog_term_appears_only_when_gated(client):
    gated_body = _render_unit_with_filltable(client, "ftbl_pp1", gate=True)
    plain_body = _render_unit_with_filltable(client, "ftbl_pp2", gate=False)

    assert "__fillTableBooted" in gated_body
    assert "__fillTableBooted" not in plain_body
    assert "reveal-armed" in gated_body
    assert "reveal-armed" not in plain_body
