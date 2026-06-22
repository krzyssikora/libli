# tests/test_questions_2diii_authoring.py
import pytest
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.urls import reverse

from courses.element_forms import ExtendedResponseQuestionElementForm
from courses.models import ExtendedResponseQuestionElement
from courses.templatetags.courses_manage_extras import _ELEMENT_LABELS
from courses.templatetags.courses_manage_extras import element_type_label
from courses.views_manage import _EDITOR_TYPE_LABELS
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_pa

pytestmark = pytest.mark.django_db


def test_editor_type_label_present():
    assert str(_EDITOR_TYPE_LABELS["extendedresponsequestion"])


def test_element_outline_label_is_short():
    # The outline tile uses element_type_label(content_type, obj) -> _ELEMENT_LABELS
    # keyed on content_type.model. There is NO string-keyed `element_label` callable.
    assert str(_ELEMENT_LABELS["extendedresponsequestionelement"]) == "Essay"
    ct = ContentType.objects.get_for_model(ExtendedResponseQuestionElement)
    assert str(element_type_label(ct)) == "Essay"


def test_edit_partial_renders_keyword_textareas():
    form = ExtendedResponseQuestionElementForm()
    html = render_to_string(
        "courses/manage/editor/_edit_extendedresponsequestion.html", {"form": form}
    )
    assert 'name="required_keywords"' in html
    assert 'name="forbidden_keywords"' in html


def test_element_add_opens_form_not_400(client):
    # The type_key must pass the element_add allowlist (else 400 "bad type").
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_add", kwargs={"slug": course.slug}),
        {"type": "extendedresponsequestion", "unit": unit.pk},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 200
    assert b'name="required_keywords"' in resp.content


def test_element_save_creates_element(client):
    make_pa(client, "pa")
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "type": "extendedresponsequestion",
            "unit": unit.pk,
            "element": "new",
            "unit_token": unit.updated.isoformat(),
            "stem": "Explain photosynthesis.",
            "explanation": "",
            "required_keywords": "chlorophyll\nlight",
            "forbidden_keywords": "",
            "marking_mode": "A",
            "max_attempts": "1",
            "max_marks": "1",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code in (200, 204)
    obj = ExtendedResponseQuestionElement.objects.get(stem="Explain photosynthesis.")
    assert obj.required_keywords == "chlorophyll\nlight"
