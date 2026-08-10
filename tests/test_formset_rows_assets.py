import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_formset_rows_js_exports():
    src = open(finders.find("courses/js/formset_rows.js"), encoding="utf-8").read()
    assert "window.libliInitFormsetRows" in src
    assert "__prefix__" in src
    # The module is prefix-agnostic: it must never hardcode one formset's prefix.
    assert "steps-TOTAL_FORMS" not in src


def test_editor_page_loads_formset_rows_js(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(
        reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    )
    assert b"courses/js/formset_rows.js" in resp.content
