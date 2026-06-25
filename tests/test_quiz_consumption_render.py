"""Student-facing quiz page (quiz_unit) render regressions:
- a fresh (unanswered) short-text/short-numeric input must be empty, never "None";
- a quiz containing a math element must load KaTeX.
"""

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import ExtendedResponseQuestionElement
from courses.models import MathElement
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _enrolled_quiz(client):
    user = make_login(client, "stu")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    return course, unit


def _quiz_url(course, unit):
    return reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )


@pytest.mark.django_db
def test_fresh_quiz_shorttext_input_is_empty_not_none(client):
    course, unit = _enrolled_quiz(client)
    q = ShortTextQuestionElement.objects.create(stem="<p>Cap?</p>", accepted="Paris")
    Element.objects.create(unit=unit, content_object=q)
    resp = client.get(_quiz_url(course, unit))
    assert resp.status_code == 200
    assert 'value="None"' not in resp.content.decode()


@pytest.mark.django_db
def test_fresh_quiz_shortnumeric_input_is_empty_not_none(client):
    from decimal import Decimal

    course, unit = _enrolled_quiz(client)
    q = ShortNumericQuestionElement.objects.create(
        stem="<p>Pi?</p>", value=Decimal("3.14"), tolerance=Decimal("0.01")
    )
    Element.objects.create(unit=unit, content_object=q)
    resp = client.get(_quiz_url(course, unit))
    assert resp.status_code == 200
    assert 'value="None"' not in resp.content.decode()


@pytest.mark.django_db
def test_fresh_quiz_extended_response_textarea_is_empty_not_none(client):
    course, unit = _enrolled_quiz(client)
    q = ExtendedResponseQuestionElement.objects.create(stem="<p>Discuss.</p>")
    Element.objects.create(unit=unit, content_object=q)
    resp = client.get(_quiz_url(course, unit))
    assert resp.status_code == 200
    assert "None</textarea>" not in resp.content.decode()


@pytest.mark.django_db
def test_quiz_with_math_element_loads_katex(client):
    course, unit = _enrolled_quiz(client)
    Element.objects.create(
        unit=unit, content_object=MathElement.objects.create(latex="x^2")
    )
    resp = client.get(_quiz_url(course, unit))
    assert resp.status_code == 200
    # The math element renders raw latex into a [data-katex] node; KaTeX must be
    # loaded (gated by has_math) or the latex shows unrendered.
    assert "katex.min.js" in resp.content.decode()


@pytest.mark.django_db
def test_quiz_with_text_element_inline_math_loads_katex(client):
    # Inline \(...\) math typed into a text element's prose must trigger KaTeX.
    course, unit = _enrolled_quiz(client)
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body=r"<p>Let \(x = 2\).</p>"),
    )
    resp = client.get(_quiz_url(course, unit))
    assert resp.status_code == 200
    assert "katex.min.js" in resp.content.decode()
