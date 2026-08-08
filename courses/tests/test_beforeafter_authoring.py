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


def _make_row(client, course, unit, label="Show solution"):
    """Create a real before/after row through the SAVE view (add is render-only)."""
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "beforeafter",
            "element": "new",
            "unit": unit.pk,
            "unit_token": unit.updated.isoformat(),
            "button_label": label,
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    return unit.elements.get()


def test_row_renders_type_tag_and_summary(client):
    """el-tag is the ONLY consumer of the _ELEMENT_LABELS entry.

    Mutants: drop the el-tag span -> the entry has no consumer and the row ships
    untagged; drop the element_summary branch -> the label falls back to the
    generic and shows nothing useful.
    """
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    _make_row(client, course, unit)

    body = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    # Assert on the TAG MARKUP, not the bare string: from Task 10 onward the
    # add-menu card also renders {% trans "Before / after" %} on this same page,
    # so `"Before / after" in body` is satisfied whether or not the row emits
    # el-tag -- the bare-substring trap this repo has hit before.
    assert '<span class="el-tag">Before / after</span>' in body
    # Scoped to the editor pane: _editor_scope.html also renders a live PREVIEW
    # (views_manage.py:1534), which emits the student template's ba__label span --
    # so a bare `"Show solution" in body` is true whether or not element_summary
    # has a branch. The same trap the el-tag assertion above avoids.
    editor_pane = body.split('data-scope="preview"')[0]
    assert ">Show solution</button>" in editor_pane  # the el-row__label button
    assert 'class="el-edit-slot"' in body  # hosts the open form
    assert "element-list--nested" in body  # child-row wrapper
    # Mutant: emit one slot / drop the `{% for slot_id, children in
    # obj.resolved_slots %}` loop -> this drops to 1.
    assert body.count('data-ba-slot="') == 2


def test_element_title_wins_over_button_label(client):
    """Mutant: drop the {% if el.title %} branch -> before/after becomes the only
    type whose author-set Element.title is ignored in the editor tree.
    """
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    el = _make_row(client, course, unit)
    el.title = "My comparison"
    el.save(update_fields=["title"])

    body = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    ).content.decode()
    assert "My comparison" in body
