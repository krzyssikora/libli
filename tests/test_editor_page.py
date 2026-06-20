import re

import pytest
from django.urls import reverse

from courses.models import Choice
from courses.models import ChoiceQuestionElement
from courses.models import TextElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import make_pa


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.mark.django_db
def test_editor_renders_unit_with_elements(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    add_element(unit, TextElement.objects.create(body="<p>Hello world</p>"))
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content
    assert b'data-scope="preview"' in resp.content
    assert b"Hello world" in resp.content  # preview reuses 1a renderer


@pytest.mark.django_db
def test_editor_404_on_non_unit(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    part = ContentNodeFactory(course=course, parent=None, kind="part", unit_type=None)
    resp = client.get(_editor_url(course, part))
    assert resp.status_code == 404


@pytest.mark.django_db
def test_editor_404_on_foreign_course_slug(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    other = CourseFactory()
    unit = ContentNodeFactory(
        course=other, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(
        reverse(
            "courses:manage_editor",
            kwargs={"slug": course.slug, "pk": unit.pk},
        )
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_editor_empty_unit_shows_empty_state(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    assert b'data-scope="editor"' in resp.content


@pytest.mark.django_db
def test_editor_shows_ancestors_and_type_chip(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa, slug="editorbc")
    ch = ContentNodeFactory(course=course, kind="chapter", parent=None, title="Ch1")
    sec = ContentNodeFactory(course=course, kind="section", parent=ch, title="Sec A")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=sec, title="Intro"
    )
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    html = client.get(url).content.decode()
    assert "Ch1" in html and "Sec A" in html
    assert "Intro" in html
    assert "Lesson" in html


@pytest.mark.django_db
def test_element_form_renders_inside_matching_row_slot(client):
    from courses.models import Element

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa, slug="editslot")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = Element.objects.create(
        unit=unit, content_object=TextElement.objects.create(body="<p>hi</p>")
    )
    url = reverse(
        "courses:manage_element_form", kwargs={"slug": course.slug, "pk": el.pk}
    )
    html = client.get(url, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "el-row--editing" in html
    assert 'data-op="element-save"' in html


@pytest.mark.django_db
def test_preview_question_is_answerable_via_try_endpoint(client):
    # The live preview is a "try it" surface: questions render answerable (enabled
    # inputs + Check), but the form points at the manage-gated, non-persisting try
    # endpoint — NOT the student check_answer (which needs enrollment and, rendered
    # without a request, has no CSRF token). editor.js posts it via fetch+CSRF header.
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa, slug="prevq")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False)
    el = add_element(unit, q)

    html = client.get(_editor_url(course, unit)).content.decode()
    preview = html[html.index('data-scope="preview"') :]

    assert "data-question" in preview  # the question renders in the preview
    # Form posts to the authoring try endpoint, not the student check endpoint.
    try_url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk}
    )
    assert f'action="{try_url}"' in preview
    assert "/check/" not in preview  # never the persisting student endpoint
    # Inputs + Check are enabled (answerable).
    btn = re.search(r'<button[^>]*type="submit"[^>]*>\s*Check\s*</button>', preview)
    assert btn is not None and "disabled" not in btn.group(0)
    for m in re.finditer(r'<input[^>]*name="choice"[^>]*>', preview):
        assert "disabled" not in m.group(0)


@pytest.mark.django_db
def test_preview_shows_unit_title(client):
    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa, slug="editorprev")
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Preview Me"
    )
    url = reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})
    html = client.get(url).content.decode()
    assert 'data-scope="preview"' in html
    assert "Preview Me" in html
