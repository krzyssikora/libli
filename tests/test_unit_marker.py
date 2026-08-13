"""unit_marker / marker_label: the single student-facing kind rule."""

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from courses.rollups import MARKER_ADDITIONAL
from courses.rollups import MARKER_NONE
from courses.rollups import MARKER_QUIZ
from courses.rollups import marker_label
from courses.rollups import unit_marker
from tests.factories import TEST_PASSWORD
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_verified_user


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


def _outline_soup(client, course):
    resp = client.get(reverse("courses:course_outline", kwargs={"slug": course.slug}))
    assert resp.status_code == 200
    return BeautifulSoup(resp.content.decode(), "html.parser")


@pytest.mark.django_db
def test_outline_marks_quiz_and_additional_but_not_required(client):
    course = CourseFactory()
    student = make_verified_user(
        username="s_outline", email="s_outline@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    req = ContentNodeFactory(
        course=course, unit_type="lesson", obligatory=True, title="Required one"
    )
    add = ContentNodeFactory(
        course=course, unit_type="lesson", obligatory=False, title="Extra practice"
    )
    quiz = ContentNodeFactory(course=course, unit_type="quiz", title="End test")
    client.force_login(student)
    soup = _outline_soup(client, course)

    def row(node):
        return soup.select_one(f"li#node-{node.pk} a.outline-unit")

    # present for additional + quiz, and INSIDE the anchor (not a detached sibling)
    assert row(add).select_one(".unit-kind-chip").get_text(strip=True) == "Additional"
    assert row(quiz).select_one(".unit-kind-chip").get_text(strip=True) == "Quiz"
    assert (
        f"unit-kind-chip--{MARKER_QUIZ}"
        in row(quiz).select_one(".unit-kind-chip")["class"]
    )

    # ABSENT for a required lesson — the load-bearing assertion. Without it every
    # mutant that marks every row stays green.
    assert row(req).select_one(".unit-kind-chip") is None


@pytest.mark.django_db
def test_outline_chip_follows_the_title_and_precedes_the_tick(client):
    """§4 argues at length for right-gutter placement; without a position
    assertion, moving the chip before the title keeps every other check green."""
    course = CourseFactory()
    student = make_verified_user(
        username="s_pos", email="s_pos@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    quiz = ContentNodeFactory(course=course, unit_type="quiz", title="Ordered")
    # COMPLETED, so .badge--done actually renders — otherwise the "precedes the
    # tick" half of this test asserts nothing and moving the chip after the tick
    # stays green.
    UnitProgressFactory(student=student, unit=quiz, completed=True)
    client.force_login(student)
    anchor = _outline_soup(client, course).select_one(
        f"li#node-{quiz.pk} a.outline-unit"
    )

    classes = [" ".join(c.get("class", [])) for c in anchor.find_all(recursive=False)]
    title_i = next(i for i, c in enumerate(classes) if "outline-unit__title" in c)
    chip_i = next(i for i, c in enumerate(classes) if "unit-kind-chip" in c)
    done_i = next(i for i, c in enumerate(classes) if "badge--done" in c)
    assert chip_i == title_i + 1, f"chip must directly follow the title, got {classes}"
    assert chip_i < done_i, f"chip must precede the tick, got {classes}"


@pytest.mark.django_db
def test_outline_chip_is_tagged_with_the_ui_language_not_the_course_language(client):
    """The chip sits inside lang="{{ course.language }}"; its word is a UI string."""
    course = CourseFactory(language="pl")  # deliberately NOT the UI locale
    student = make_verified_user(
        username="s_lang", email="s_lang@t.example.com", password=TEST_PASSWORD
    )
    EnrollmentFactory(student=student, course=course)
    ContentNodeFactory(course=course, unit_type="quiz", title="Lang")
    client.force_login(student)
    chip = _outline_soup(client, course).select_one(".unit-kind-chip")
    assert chip["lang"] == "en"
