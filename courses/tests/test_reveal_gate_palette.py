import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import TabsElement
from courses.models import TextElement

pytestmark = pytest.mark.django_db


def unit_editor_url(unit):
    return reverse(
        "courses:manage_editor", kwargs={"slug": unit.course.slug, "pk": unit.pk}
    )


@pytest.fixture
def client_pa(client):
    """Log a Platform Admin into `client` and return the client itself, so tests
    can pass it straight to `_editor_html`."""
    from tests.factories import make_pa

    make_pa(client, "pa")
    return client


@pytest.fixture
def lesson_unit():
    """A LESSON-type unit belonging to a fresh course. No shared `lesson_unit`
    fixture exists in this project -- define it locally, same as the sibling
    reveal-gate builder tests (test_reveal_gate_form_builder.py)."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    return unit


@pytest.fixture
def quiz_unit():
    """A QUIZ-type unit belonging to a fresh course. `make_course_with_unit` only
    forwards **kw to CourseFactory (not the unit), so build the pair directly here
    the same way test_editor_page.py does for non-lesson units."""
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory()
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    return unit


@pytest.fixture
def lesson_unit_with_tabs():
    """A lesson unit carrying a tabs element with one child, so the editor page
    renders BOTH the top-level add-menu and the nested (in-tab) add-menu --
    mirrors test_element_row_renders_nested_children_indented in
    tests/test_tabs_editor_partial.py."""
    from tests.factories import make_course_with_unit

    _course, unit = make_course_with_unit()
    obj = TabsElement.objects.create(data=TabsElement.default_data())
    join = Element.objects.create(unit=unit, content_object=obj)
    tab = obj.data["tabs"][0]["id"]
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(body="child body"),
        parent=join,
        tab_id=tab,
    )
    return unit


def _editor_html(client, unit):
    resp = client.get(unit_editor_url(unit))
    return resp.content.decode()


def test_interactive_group_in_lesson(client_pa, lesson_unit):
    html = _editor_html(client_pa, lesson_unit)
    assert 'data-add-type="revealgate"' in html
    assert "Interactive" in html  # group heading present


def test_interactive_group_absent_in_quiz(client_pa, quiz_unit):
    html = _editor_html(client_pa, quiz_unit)
    assert 'data-add-type="revealgate"' not in html
    assert "Interactive" not in html  # whole group hidden, no stray heading


def test_gate_card_in_nested_add_menu(client_pa, lesson_unit_with_tabs):
    # the in-tab add-menu (rendered with nested=True) must also offer the gate,
    # since revealgate is nestable -- guards against placing the group inside
    # the {% if not nested %} block.
    html = _editor_html(client_pa, lesson_unit_with_tabs)
    assert html.count('data-add-type="revealgate"') >= 2  # top-level + nested
