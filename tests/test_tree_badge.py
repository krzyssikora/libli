import re

import pytest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import make_login

# Scoped to the UNIT badge span only (requires the load-bearing tree__badge--unit
# colour hook). Groups: 1=per-type modifier, 2=title attr, 3=inner text. Attribute
# order is fixed by the template, so this stays deterministic.
UNIT_BADGE_RE = re.compile(
    r'<span class="tree__badge tree__badge--unit'
    r'(?: tree__badge--(lesson|quiz))?"'
    r'(?: title="([^"]*)")?>'
    r"([^<]*)</span>"
)
# The title input's hover-title (edit #3). [^>]* spans the tag's line break
# because it also matches newlines (any char except '>').
TITLE_INPUT_RE = re.compile(r'<input class="tree__title"[^>]*\btitle="([^"]*)"')


def _render_unit(unit_type, title="Intro", lang=None):
    """Render a single leaf unit row. Units render no child scope, so a trivial
    context suffices. `lang` wraps the render in that locale. No explicit slug —
    CourseFactory's Sequence slug default keeps every call unique."""
    course = CourseFactory()
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title=title
    )
    ctx = {"node": unit, "children_map": {}, "is_first": True, "is_last": True}
    if lang:
        with translation.override(lang):
            return render_to_string("courses/manage/_tree_node.html", ctx)
    return render_to_string("courses/manage/_tree_node.html", ctx)


def _badge(body):
    m = UNIT_BADGE_RE.search(body)
    assert m, "unit badge span not found"
    return {
        "modifier": m.group(1),
        "title": m.group(2),
        "text": m.group(3),
        "span": m.group(0),
    }


@pytest.mark.django_db
def test_lesson_badge_is_L_with_localized_tooltip():
    b = _badge(_render_unit("lesson"))
    assert b["text"] == "L"
    assert b["title"] == "Lesson"
    assert b["modifier"] == "lesson"


@pytest.mark.django_db
def test_quiz_badge_is_Q_with_tooltip():
    b = _badge(_render_unit("quiz"))
    assert b["text"] == "Q"
    assert b["title"] == "Quiz"
    assert b["modifier"] == "quiz"


@pytest.mark.django_db
def test_unit_badge_keeps_accent_colour_class():
    for ut in ("lesson", "quiz"):
        assert "tree__badge--unit" in _badge(_render_unit(ut))["span"]


@pytest.mark.django_db
def test_title_input_has_hover_title():
    m = TITLE_INPUT_RE.search(_render_unit("lesson", title="Intro"))
    assert m, "title input title attr not found"
    assert m.group(1) == "Intro"


@pytest.mark.django_db
def test_letter_is_not_translated_under_pl():
    assert _badge(_render_unit("lesson", lang="pl"))["text"] == "L"
    assert _badge(_render_unit("quiz", lang="pl"))["text"] == "Q"


@pytest.mark.django_db
def test_lesson_tooltip_localizes_to_pl():
    assert _badge(_render_unit("lesson", lang="pl"))["title"] == "Lekcja"


@pytest.mark.django_db
def test_container_node_keeps_word_badge(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    ContentNodeFactory(course=course, kind="chapter", parent=None, title="Foundations")
    body = client.get(
        reverse("courses:manage_builder", kwargs={"slug": "c1"})
    ).content.decode()
    assert "tree__badge tree__badge--chapter" in body
    assert ">Chapter</span>" in body
    assert not UNIT_BADGE_RE.search(body), (
        "no unit badge expected for a chapter-only tree"
    )
