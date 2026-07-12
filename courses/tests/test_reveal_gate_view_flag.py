import pytest
from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.urls import reverse

from courses import builder
from courses.models import Element
from courses.models import Enrollment
from courses.models import RevealGateElement
from courses.models import TabsElement
from courses.models import TextElement

pytestmark = pytest.mark.django_db


def lesson_url(unit):
    return reverse(
        "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


@pytest.fixture
def client_student(client):
    """Log a plain Student into `client` (fixed username so lesson fixtures can
    enrol the SAME user -- see lesson_with_gate/lesson_with_tab_gate/plain_lesson,
    which all depend on this fixture to guarantee shared identity + ordering)."""
    from tests.factories import make_student

    make_student(client, "student")
    return client


def _enrol_student(course):
    student = get_user_model().objects.get(username="student")
    Enrollment.objects.get_or_create(student=student, course=course)


def _add_top_level_gate(unit, label="Show more"):
    post = QueryDict(mutable=True)
    post["label"] = label
    post["unit_token"] = unit.updated.isoformat()  # REQUIRED: _check_token
    builder.save_element(unit.course, unit.pk, "revealgate", "new", post, {})
    unit.refresh_from_db()


@pytest.fixture
def lesson_with_gate(client_student):
    """A lesson unit with a TOP-LEVEL reveal-gate element."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    _add_top_level_gate(unit)
    _enrol_student(unit.course)
    return unit


@pytest.fixture
def lesson_with_tab_gate(client_student):
    """A lesson unit whose ONLY reveal-gate lives nested inside a tab -- mirrors
    lesson_unit_with_tabs in test_reveal_gate_palette.py, but the tab child is a
    RevealGateElement rather than a TextElement, so a flat (non-parent-scoped)
    query is required to detect it."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=RevealGateElement.objects.create(label=""),
        parent=join,
        tab_id=tab,
    )
    _enrol_student(unit.course)
    return unit


@pytest.fixture
def plain_lesson(client_student):
    """A lesson unit with ordinary content and NO reveal-gate anywhere."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="plain text")
    )
    _enrol_student(unit.course)
    return unit


def test_flag_true_top_level_gate(client_student, lesson_with_gate):
    html = client_student.get(lesson_url(lesson_with_gate)).content.decode()
    assert "reveal-armed" in html  # setter present
    assert "reveal.js" in html  # engine included


def test_flag_true_tab_nested_gate(client_student, lesson_with_tab_gate):
    # a lesson whose ONLY gate is inside a tab
    html = client_student.get(lesson_url(lesson_with_tab_gate)).content.decode()
    assert "reveal-armed" in html


def test_flag_false_no_gate(client_student, plain_lesson):
    html = client_student.get(lesson_url(plain_lesson)).content.decode()
    assert "reveal-armed" not in html
    assert "reveal.js" not in html
