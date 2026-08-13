"""unit_marker / marker_label: the single student-facing kind rule."""

import pytest
from django.template.loader import render_to_string
from django.utils import translation

from courses.rollups import MARKER_ADDITIONAL
from courses.rollups import MARKER_NONE
from courses.rollups import MARKER_QUIZ
from courses.rollups import marker_label
from courses.rollups import unit_marker
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory


@pytest.mark.django_db
def test_marker_table():
    """Every branch, including the ones that exist to be SILENT.

    The two quiz rows are a pair on purpose: together they pin that `obligatory`
    is ignored on a quiz, which one row alone cannot.
    """
    course = CourseFactory()
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True)
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    quiz_ob = ContentNodeFactory(course=course, unit_type="quiz", obligatory=True)
    quiz_opt = ContentNodeFactory(course=course, unit_type="quiz", obligatory=False)
    chapter = ContentNodeFactory(course=course, kind="chapter", unit_type=None)
    untyped = ContentNodeFactory(course=course, unit_type=None)

    assert unit_marker(req) == MARKER_NONE
    assert unit_marker(add) == MARKER_ADDITIONAL
    assert unit_marker(quiz_ob) == MARKER_QUIZ
    assert unit_marker(quiz_opt) == MARKER_QUIZ
    assert unit_marker(chapter) == MARKER_NONE
    assert unit_marker(untyped) == MARKER_NONE


def test_marker_is_quiet_for_non_nodes():
    """A partial included without `with node=...` resolves to Django's
    string_if_invalid (default ''). A bare attribute access would raise
    AttributeError and 500 the course outline; fail quiet instead."""
    assert unit_marker("") == MARKER_NONE
    assert unit_marker(None) == MARKER_NONE


@pytest.mark.django_db
def test_labels_under_default_locale():
    """LANGUAGE_CODE is 'en' (config/settings/base.py:142)."""
    course = CourseFactory()
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    quiz = ContentNodeFactory(course=course, unit_type="quiz")
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True)

    assert str(marker_label(unit_marker(add))) == "Additional"
    assert str(marker_label(unit_marker(quiz))) == "Quiz"
    assert str(marker_label(unit_marker(req))) == ""
    assert marker_label("nonsense") == ""


@pytest.mark.xfail(reason="PL msgstr lands in Task 6", strict=True)
@pytest.mark.django_db
def test_label_is_a_lazy_proxy_not_a_frozen_string():
    """Pins the §6 catalog entry end-to-end AND proves gettext_lazy: a plain
    gettext call in a module-level dict would freeze the import-time language."""
    course = CourseFactory()
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    with translation.override("pl"):
        assert str(marker_label(unit_marker(add))) == "Dodatkowa"


@pytest.mark.django_db
def test_chip_partial_renders_only_when_marked():
    course = CourseFactory()
    quiz = ContentNodeFactory(course=course, unit_type="quiz")
    req = ContentNodeFactory(course=course, unit_type="lesson", obligatory=True)

    marked = render_to_string("courses/_unit_kind_chip.html", {"node": quiz})
    assert "unit-kind-chip" in marked
    assert f"unit-kind-chip--{MARKER_QUIZ}" in marked
    assert "Quiz" in marked

    assert render_to_string("courses/_unit_kind_chip.html", {"node": req}).strip() == ""


@pytest.mark.django_db
def test_icon_partial_carries_a_hidden_label_and_a_title():
    course = CourseFactory()
    add = ContentNodeFactory(course=course, unit_type="lesson", obligatory=False)
    html = render_to_string("courses/_unit_kind_icon.html", {"node": add})
    assert 'class="unit-kind unit-kind--additional"' in html
    assert 'title="Additional"' in html
    assert 'lang="en"' in html  # UI locale, not the course's
    assert 'aria-hidden="true"' in html  # on the <svg>
    assert "visually-hidden unit-kind__label" in html
    assert "Additional</span>" in html


def test_glyph_partial_emits_nothing_for_an_empty_marker():
    """The three-way {% elif %} pin. With an {% else %} branch this would emit
    the *additional* '+' glyph. No surface test can reach it, because the chip
    and icon partials guard the include behind {% if m %}."""
    assert "<svg" not in render_to_string("courses/_unit_kind_glyph.html", {"m": ""})
