import pytest
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa
from tests.helpers_editor_rows import rendered_rows

pytestmark = pytest.mark.django_db


def _lesson_unit(course):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


def test_manage_element_add_renders_stepper_editor_200(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = _lesson_unit(course)
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "stepper", "unit": unit.pk},
    )
    assert resp.status_code == 200
    assert b"steps-TOTAL_FORMS" in resp.content  # management form present
    assert b'data-fsrows="steps"' in resp.content  # editor mounted
    # Exact, and scoped to [data-fsrows-list] with the <template> decomposed: the
    # blueprint always emits one [data-fsrow-item], so a `count(...) >= 1` on the
    # raw body would pass on a render with ZERO rows.
    assert len(rendered_rows(resp.content.decode())) == 1  # extra=1 on a fresh stepper
