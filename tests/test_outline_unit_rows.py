"""Render-tier tests for the outline's unit rows: leading glyph, quiz icon, highlight.

Spec 2026-10-18-student-course-outline-redesign §3.5.
"""

import pytest
from bs4 import BeautifulSoup

from courses.models import UnitProgress
from notes import services
from tests.factories import CourseFactory
from tests.factories import TagFactory
from tests.factories import UnitTagFactory
from tests.test_outline_cards import _complete
from tests.test_outline_cards import _container
from tests.test_outline_cards import _get
from tests.test_outline_cards import _lesson
from tests.test_outline_cards import _quiz
from tests.test_outline_cards import _save_state
from tests.test_outline_cards import _soup
from tests.test_outline_cards import _student

pytestmark = pytest.mark.django_db


def _row(soup, unit):
    return soup.select_one(f"#node-{unit.pk} > a.outline-unit")


def _fake_resume(monkeypatch, unit, state):
    monkeypatch.setattr(
        "courses.views.build_resume",
        lambda c, u, t: {"node": unit, "state": state, "ancestors": []},
    )


def test_lesson_row_starts_with_a_decorative_ring(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    lesson = _lesson(course, chapter)
    _student(client, course, "ur1")
    a = _row(_soup(client, course), lesson)
    first = a.find(True)
    assert "outline-ring" in first["class"]
    assert "outline-ring--none" in first["class"]
    assert first["aria-hidden"] == "true"
    assert first.get_text(strip=True) == ""


def test_quiz_row_has_icon_and_exactly_one_quiz_label(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    quiz = _quiz(course, chapter)
    _student(client, course, "ur2")
    a = _row(_soup(client, course), quiz)
    icon = a.select_one("svg.outline-quiz-icon")
    assert icon is not None
    assert a.find(True) == icon
    assert icon["aria-hidden"] == "true"
    assert icon["viewbox"] == "0 0 20 20"
    assert a.select_one(".outline-ring") is None
    assert len(a.select(".unit-kind-chip--quiz")) == 1


def test_completed_lesson_with_saved_state_draws_done(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    lesson = _lesson(course, chapter)
    user = _student(client, course, "ur3")
    _save_state(user, lesson)
    UnitProgress.objects.filter(student=user, unit=lesson).update(completed=True)
    ring = _row(_soup(client, course), lesson).find(True)
    assert "outline-ring--done" in ring["class"]
    assert ring.select_one(".outline-ring__tick") is not None


def test_progress_ring_uses_the_floor_arc(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    lesson = _lesson(course, chapter)
    user = _student(client, course, "ur3b")
    _save_state(user, lesson)
    ring = _row(_soup(client, course), lesson).find(True)
    assert "outline-ring--progress" in ring["class"]
    assert ring.select_one(".outline-ring__arc")["stroke-dasharray"] == "9 100"


def test_resume_target_lesson_at_depth2_draws_progress_but_is_not_current(
    client, monkeypatch
):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    lesson = _lesson(course, chapter)
    _student(client, course, "ur4")
    _fake_resume(monkeypatch, lesson, "resume")
    soup = _soup(client, course)
    a = _row(soup, lesson)
    ring = a.find(True)
    assert "outline-ring--progress" in ring["class"]
    assert "is-current" not in a["class"]
    assert not a.has_attr("aria-current")


@pytest.mark.parametrize("where", ["root", "depth1"])
def test_root_and_depth1_unit_targets_are_current_and_draw_progress(
    client, monkeypatch, where
):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    _lesson(course, chapter)
    target = _lesson(course, None if where == "root" else part, 5)
    _student(client, course, f"ur5-{where}")
    _fake_resume(monkeypatch, target, "resume")
    soup = _soup(client, course)
    assert len(soup.select('[aria-current="step"]')) == len(soup.select(".is-current"))
    assert len(soup.select(".is-current")) == 1
    a = _row(soup, target)
    assert "is-current" in a["class"] and a["aria-current"] == "step"
    assert "outline-ring--progress" in a.find(True)["class"]


def test_unit_row_keeps_chips_badges_and_links(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    lesson = _lesson(course, chapter, 0)
    quiz = _quiz(course, chapter, 1)
    user = _student(client, course, "ur6")
    _complete(user, lesson)
    tag = TagFactory(author=user, name="Algebra")
    UnitTagFactory(tag=tag, unit=lesson)
    services.create_note(user, lesson, None, "n")
    r = _get(client, course)
    soup = BeautifulSoup(r.content.decode(), "html.parser")
    a = _row(soup, lesson)
    assert "outline-unit--done" in a["class"]
    assert a.select_one(".badge--done")["aria-label"] == "Completed"
    assert a.select_one(".outline-unit__title").get_text(strip=True) == lesson.title
    li = soup.select_one(f"#node-{lesson.pk}")
    assert li.select_one(".tag-chip").get_text(strip=True) == "Algebra"
    edit = li.select_one("a.outline-unit__edit-tags")
    assert edit["href"].endswith("?panel=tags")
    assert li.select_one("a.badge--notes") is not None
    qa = _row(soup, quiz)
    kids = [c for c in qa.find_all(True, recursive=False)]
    assert kids[1]["class"][0] == "outline-unit__title"
    assert "unit-kind-chip--quiz" in kids[2]["class"]
