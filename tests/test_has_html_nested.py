"""Task 6: `has_html` must fire for a NESTED html element, not just a top-level
one, at BOTH context builders -- build_lesson_context (courses/views.py) and
build_quiz_context (courses/views.py:~1198), which is a SEPARATE code path, not
a duplicate.

Each test builds an ISOLATED unit whose ONLY html element lives nested inside
a TabsElement (tabs > html). Isolation is asserted explicitly: no top-level
html element exists anywhere in the unit, so the test cannot pass vacuously
off some other, unrelated top-level html element.
"""

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import HtmlElement
from courses.models import TabsElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login


def _unit_with_only_nested_html(unit):
    """tabs (top-level) > html (child, parent=tabs join row). No top-level html
    element is created anywhere -- that is the isolation this task's tests
    depend on."""
    tabs = TabsElement.objects.create(data=TabsElement.default_data())
    top = Element.objects.create(unit=unit, content_object=tabs)
    tab_id = tabs.data["tabs"][0]["id"]
    html_el = HtmlElement.objects.create(html="<p>nested</p>")
    Element.objects.create(unit=unit, content_object=html_el, parent=top, tab_id=tab_id)


def _assert_isolated(unit):
    """The unit's ONLY html element is nested: no top-level (parent__isnull=True)
    html element exists. Without this check either test would pass whether or
    not the depth-agnostic fix is correct."""
    assert not Element.objects.filter(
        unit=unit,
        parent__isnull=True,
        content_type__app_label="courses",
        content_type__model="htmlelement",
    ).exists()
    assert Element.objects.filter(
        unit=unit,
        parent__isnull=False,
        content_type__app_label="courses",
        content_type__model="htmlelement",
    ).exists()


@pytest.mark.django_db
def test_lesson_with_only_nested_html_loads_the_bundle(client):
    user = make_login(client, "stu-lesson")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _unit_with_only_nested_html(unit)
    _assert_isolated(unit)

    resp = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert resp.status_code == 200
    assert "html_element.js" in resp.content.decode()


@pytest.mark.django_db
def test_quiz_with_only_nested_html_loads_the_bundle(client):
    # Same shape, but a QUIZ unit: build_quiz_context (views.py's quiz builder) is
    # a SEPARATE code path from build_lesson_context. A fix at only one site
    # leaves this test failing.
    user = make_login(client, "stu-quiz")
    course = CourseFactory()
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    _unit_with_only_nested_html(unit)
    _assert_isolated(unit)

    resp = client.get(
        reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    )
    assert resp.status_code == 200
    assert "html_element.js" in resp.content.decode()
