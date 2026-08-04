import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def _unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def _editor_with_banner(client):
    """`?changed=1` is the one banner reachable without a mutation, so it is what
    pins the render slot's LOCATION."""
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _unit(course)
    return client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
        + "?changed=1"
    )


def test_the_banner_renders_inside_the_swapped_pane(client):
    """A message outside [data-scope] survives no fragment swap: applyFragments
    replaces only those two elements, and editor.html's chrome is outside both.
    That is why the block moves into _editor_scope.html."""
    resp = _editor_with_banner(client)

    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="editor-error"' in body
    assert body.index('id="editor-error"') > body.index('data-scope="editor"')


def test_the_banner_is_not_rendered_twice(client):
    """editor.html's old block must be REMOVED, not left beside the new one, or
    every settings-save 422 shows its message twice.

    Counts `class="op-error"`, NOT the new block's id: editor.html:58-59 render
    the div with no id at all, so an id-based count returns 1 whether or not
    Step 4 was done -- vacuous, and the removal would ship unguarded."""
    resp = _editor_with_banner(client)

    assert resp.content.decode().count('class="op-error"') == 1
