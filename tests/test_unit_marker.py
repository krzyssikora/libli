"""unit_marker / marker_label: the single student-facing kind rule."""

import pytest
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
