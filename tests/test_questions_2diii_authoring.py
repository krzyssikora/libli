# tests/test_questions_2diii_authoring.py
import pytest
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from courses.element_forms import ExtendedResponseQuestionElementForm
from courses.models import ExtendedResponseQuestionElement
from courses.templatetags.courses_manage_extras import _ELEMENT_LABELS
from courses.templatetags.courses_manage_extras import element_type_label
from courses.views_manage import _EDITOR_TYPE_LABELS

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
