import pytest
from django.urls import reverse

from courses.models import BeforeAfterElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db

# Three separate mutants, each of which leaves the rest of the suite green:
#   * drop the FORM_FOR_TYPE entry
#   * drop "beforeafter" from the element_add allow-tuple
#   * drop it from the element_save allow-tuple
# Plus: the row branch omitting el-edit-slot (Task 9).


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_add_form_renders_the_beforeafter_edit_partial(client):
    """Proves _edit_beforeafter.html exists (else 500) and carries the field."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "beforeafter", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="button_label"' in html
    assert 'class="el-editor' in html  # the grid item the scroll fix keys on
    # Assert the heading ELEMENT: _editor_scope.html:55 includes _add_menu.html in
    # every fragment, so from Task 10 on the bare string is always present.
    # Mutant: omit the _EDITOR_TYPE_LABELS entry -> _render_open_form falls back to
    # .get(type_key, type_key) (views_manage.py:1751) and the heading reads
    # "beforeafter" -- NOT "no heading".
    assert '<p class="editor-form__type">Before / after</p>' in html


def test_save_round_trips_the_button_label(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "beforeafter",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "button_label": "Show solution",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    obj = BeforeAfterElement.objects.get()
    assert obj.button_label == "Show solution"
    assert "Show solution" in obj.render(element=obj.join_row())
