"""Render-tier tests for the outline's course head, list header and start button.

Spec 2026-10-18-student-course-outline-redesign §2.1 (D1, D2), §3.1, §3.3, §3.6, §3.9.
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.rollups import _progress_width
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _container(course, parent=None, order=0, title=None):
    kw = {"title": title} if title else {}
    return ContentNodeFactory(
        course=course, kind="part", unit_type=None, parent=parent, order=order, **kw
    )


def _lesson(course, parent=None, order=0, **kw):
    kw.setdefault("unit_type", "lesson")
    return ContentNodeFactory(
        course=course, kind="unit", parent=parent, order=order, **kw
    )


def _student(client, course, name):
    user = make_login(client, name)
    EnrollmentFactory(student=user, course=course)
    return user


def _complete(user, *units):
    for u in units:
        UnitProgressFactory(student=user, unit=u, completed=True)


def _url(course):
    return reverse("courses:course_outline", kwargs={"slug": course.slug})


def _soup(client, course):
    return BeautifulSoup(client.get(_url(course)).content.decode(), "html.parser")


def _two_topics_four_lessons(course):
    a = _container(course, order=0)
    b = _container(course, order=1)
    units = [_lesson(course, a, 0), _lesson(course, a, 1)]
    units += [_lesson(course, b, 0), _lesson(course, b, 1)]
    return units


def _fake_resume(monkeypatch, unit, state):
    monkeypatch.setattr(
        "courses.views.build_resume",
        lambda c, u, t: {"node": unit, "state": state, "ancestors": []},
    )


def test_title_has_its_id_and_the_bar_is_hidden_from_at(client):
    course = CourseFactory(title="Algebra")
    _two_topics_four_lessons(course)
    _student(client, course, "h1")
    soup = _soup(client, course)
    head = soup.select_one("section.outline > header.outline__head")
    assert head is not None
    title = head.select_one("h1.outline__title#outline-title")
    assert title.get_text(strip=True) == "Algebra"
    bar = head.select_one("div.outline__progress > div.outline__bar")
    assert bar["aria-hidden"] == "true"
    label = head.select_one("div.outline__progress > span.outline__progress-label")
    assert label["lang"] == "en"


def test_progress_label_some_done(client):
    course = CourseFactory()
    units = _two_topics_four_lessons(course)
    user = _student(client, course, "pl1")
    _complete(user, units[0])
    label = _soup(client, course).select_one("span.outline__progress-label")
    assert label.get_text(strip=True) == "1 of 4 lessons completed"


def test_progress_label_nothing_done(client):
    course = CourseFactory()
    _two_topics_four_lessons(course)
    _student(client, course, "pl0")
    label = _soup(client, course).select_one("span.outline__progress-label")
    assert label.get_text(strip=True) == "4 lessons in 2 topics"


def test_progress_label_without_containers(client):
    course = CourseFactory()
    for i in range(4):
        _lesson(course, None, i)
    _student(client, course, "plr")
    soup = _soup(client, course)
    label = soup.select_one("span.outline__progress-label")
    assert label.get_text(strip=True) == "4 lessons"
    list_head = soup.select_one("div.outline-list__head")
    assert list_head.has_attr("hidden")
    assert list_head.select_one("span.outline-list__count") is None
    assert list_head.select_one("button[data-outline-toggle-all]") is not None


def test_no_progress_block_when_no_required_lessons(client):
    course = CourseFactory()
    _lesson(course, None, 0, unit_type="quiz")
    _student(client, course, "np")
    soup = _soup(client, course)
    assert soup.select_one("header.outline__head") is not None
    assert soup.select_one("div.outline__progress") is None


def test_course_bar_width_is_not_full_before_completion(client):
    course = CourseFactory()
    part = _container(course)
    units = [_lesson(course, part, i) for i in range(40)]
    user = _student(client, course, "w39")
    _complete(user, *units[:39])
    soup = _soup(client, course)
    fill = soup.select_one("div.outline__bar > span.outline__fill")
    width = _progress_width(39, 40)
    assert width != 100
    assert fill["style"] == f"width: {width}%"


def test_course_bar_has_no_fill_when_nothing_done(client):
    course = CourseFactory()
    _two_topics_four_lessons(course)
    _student(client, course, "w0")
    soup = _soup(client, course)
    assert soup.select_one("div.outline__bar") is not None
    assert soup.select_one("span.outline__fill") is None


def test_start_state_renders_the_button_not_the_card(client):
    course = CourseFactory()
    units = _two_topics_four_lessons(course)
    _student(client, course, "st1")
    soup = _soup(client, course)
    assert soup.select_one("a.resume") is None
    btn = soup.select_one("header.outline__head a.outline__start")
    assert btn is not None
    assert {"btn", "btn--primary"} <= set(btn["class"])
    assert btn["lang"] == "en"
    assert btn["href"] == reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": units[0].pk}
    )


def test_start_button_links_to_quiz_unit_for_a_quiz(client):
    course = CourseFactory()
    quiz = _lesson(course, None, 0, unit_type="quiz")
    _lesson(course, None, 1)
    _student(client, course, "stq")
    btn = _soup(client, course).select_one("a.outline__start")
    assert btn["href"] == reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )


def test_start_button_carries_the_ui_language_on_a_foreign_course(client):
    course = CourseFactory(language="en")
    _lesson(course, None, 0)
    _student(client, course, "stl")
    session = client.session
    session["_language"] = "pl"
    session.save()
    r = client.get(_url(course), HTTP_ACCEPT_LANGUAGE="pl")
    soup = BeautifulSoup(r.content.decode(), "html.parser")
    assert soup.select_one("a.outline__start")["lang"] == "pl"
    assert soup.select_one("span.outline__progress-label")["lang"] == "pl"


def test_start_button_accessible_name_has_no_arrow(client):
    course = CourseFactory()
    _lesson(course, None, 0)
    _student(client, course, "sta")
    btn = _soup(client, course).select_one("a.outline__start")
    assert btn.get_text(strip=True) == "Start the first lesson"
    arrow = btn.select_one("svg.outline__start-arrow.icon")
    assert arrow is not None and arrow["aria-hidden"] == "true"
    assert btn.select_one("svg.resume__arrow") is None


@pytest.mark.parametrize("state", ["resume", "next", "gap"])
def test_returning_states_keep_the_card(client, monkeypatch, state):
    course = CourseFactory()
    unit = _lesson(course, None, 0)
    _student(client, course, f"rs-{state}")
    _fake_resume(monkeypatch, unit, state)
    soup = _soup(client, course)
    assert soup.select_one("a.outline__start") is None
    card = soup.select_one("header.outline__head a.resume")
    assert card is not None


def test_course_reset_lives_in_a_menu_iff_saved_work(client):
    course = CourseFactory()
    units = _two_topics_four_lessons(course)
    user = _student(client, course, "rst")
    soup = _soup(client, course)
    assert soup.select_one("a.outline__reset") is None
    assert soup.select_one(".outline__actions details.outline-menu") is None

    UnitProgressFactory(student=user, unit=units[0], element_state={"1": {}})
    soup = _soup(client, course)
    menu = soup.select_one(".outline__actions > details.outline-menu")
    summary = menu.select_one("summary.outline-menu__button")
    assert summary["aria-describedby"] == "outline-title"
    assert summary["aria-label"] == "More actions"
    assert summary["lang"] == "en"
    reset = menu.select_one("div.outline-menu__panel > a.outline__reset")
    assert "outline-menu__item" in reset["class"]
    assert "btn" not in reset["class"]
    assert reset["href"] == (
        reverse("courses:progress_reset_course", kwargs={"slug": course.slug})
        + "?next="
        + _url(course)
    )
    assert len(soup.select("a.outline__reset")) == 1


def test_actions_row_holds_results_notes_and_menu(client):
    course = CourseFactory()
    units = _two_topics_four_lessons(course)
    user = _student(client, course, "act")
    UnitProgressFactory(student=user, unit=units[0], element_state={"1": {}})
    soup = _soup(client, course)
    head = soup.select_one("header.outline__head")
    children = [c for c in head.children if getattr(c, "name", None)]
    # DOM order is fixed (§3.1): title, progress, next step, actions.
    assert [c.name for c in children] == ["h1", "div", "a", "div"]
    assert "outline__progress" in children[1]["class"]
    assert "resume" in children[2]["class"]  # saved work => the `resume` card
    actions = children[3]
    assert "outline__actions" in actions["class"]
    kids = [c for c in actions.children if getattr(c, "name", None)]
    assert "outline__results" in kids[0]["class"]
    assert "outline__notes" in kids[1]["class"]
    assert kids[2].name == "details" and "outline-menu" in kids[2]["class"]
    assert len(kids) == 3
    for a in kids[:2]:
        assert {"btn", "btn--ghost", "btn--small"} <= set(a["class"])
    assert kids[0]["href"] == reverse(
        "courses:course_results", kwargs={"slug": course.slug}
    )
    assert kids[1]["href"] == reverse(
        "notes:course_notes", kwargs={"slug": course.slug}
    )
    assert head.select_one("[data-outline-toggle-all]") is None


def test_list_header_sits_before_the_nav_and_counts_topics(client):
    course = CourseFactory()
    _two_topics_four_lessons(course)
    _student(client, course, "lh")
    soup = _soup(client, course)
    nav = soup.select_one("nav.outline-tree")
    prev = nav.find_previous_sibling()
    assert prev.name == "div" and "outline-list__head" in prev["class"]
    assert not prev.has_attr("hidden")
    count = prev.select_one("span.outline-list__count")
    assert count.get_text(strip=True) == "Topics · 2"
    assert count["lang"] == "en"
    toggle = prev.select_one("button.outline__toggle-all[data-outline-toggle-all]")
    assert toggle.has_attr("hidden")
    assert "btn" not in toggle["class"]
    assert toggle["data-label-expand"] == "Expand all"
    assert toggle["data-label-collapse"] == "Collapse all"
    assert nav.select_one(".outline-list__head") is None


def test_author_preview_shows_progress_ui_but_no_next_step(client):
    """Review Focus 5: an owner previewing (not enrolled, drafts kept) gets the empty
    progress UI from their own progress, no next step, and the draft still listed."""
    author = make_login(client, "auth")
    course = CourseFactory(owner=author)
    part = _container(course)
    _lesson(course, part, 0)
    draft = _lesson(course, part, 1, published=False)
    r = client.get(_url(course))
    assert r.status_code == 200
    soup = BeautifulSoup(r.content.decode(), "html.parser")
    assert soup.select_one("a.resume") is None
    assert soup.select_one("a.outline__start") is None
    assert soup.select_one(f'li[data-unit="{draft.pk}"]') is not None
    label = soup.select_one("span.outline__progress-label")
    assert label.get_text(strip=True) == "2 lessons in 1 topic"
    assert soup.select_one("div.outline__bar") is not None
    assert soup.select_one("span.outline__fill") is None
