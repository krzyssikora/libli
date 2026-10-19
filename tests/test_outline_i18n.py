"""Polish catalogue guards for the student course outline redesign.

Spec 2026-10-18-student-course-outline-redesign §3.9: plural forms, the new
"Nie rozpoczęto", the UI-language `lang` on every new string, and integer-only
SVG / style numbers under a comma-decimal locale.
"""

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _container(course, kind, parent=None, order=0, title=None):
    kw = {"title": title} if title else {}
    return ContentNodeFactory(
        course=course, kind=kind, unit_type=None, parent=parent, order=order, **kw
    )


def _lesson(course, parent, order=0, **kw):
    kw.setdefault("unit_type", "lesson")
    return ContentNodeFactory(
        course=course, kind="unit", parent=parent, order=order, **kw
    )


def _student(client, course, name):
    user = make_login(client, name)
    EnrollmentFactory(student=user, course=course)
    return user


def _polish_soup(client, course):
    session = client.session
    session["_language"] = "pl"
    session.save()
    url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    resp = client.get(url, HTTP_ACCEPT_LANGUAGE="pl")
    assert resp.status_code == 200
    return BeautifulSoup(resp.content.decode(), "html.parser")


def _label(soup):
    return soup.select_one("span.outline__progress-label").get_text(strip=True)


@pytest.mark.parametrize(
    "total,expected",
    [
        (1, "1 z 1 lekcji ukończonej"),
        (2, "1 z 2 lekcji ukończonych"),
        (5, "1 z 5 lekcji ukończonych"),
    ],
)
def test_some_done_label_plurals(client, total, expected):
    course = CourseFactory()
    units = [_lesson(course, None, i) for i in range(total)]
    user = _student(client, course, f"sd{total}")
    UnitProgressFactory(student=user, unit=units[0], completed=True)
    assert _label(_polish_soup(client, course)) == expected


@pytest.mark.parametrize(
    "lessons,sections,expected",
    [
        (1, 1, "1 lekcja w 1 dziale"),
        (2, 2, "2 lekcje w 2 działach"),
        (5, 5, "5 lekcji w 5 działach"),
    ],
)
def test_nothing_done_label_plurals(client, lessons, sections, expected):
    course = CourseFactory()
    for i in range(sections):
        part = _container(course, "part", order=i)
        _lesson(course, part, 0)
    assert lessons == sections  # one lesson per part
    _student(client, course, f"nd{lessons}")
    assert _label(_polish_soup(client, course)) == expected


def test_card_long_count_and_topics_label_in_polish(client):
    course = CourseFactory()
    p1 = _container(course, "part", order=0)
    a, _b = _lesson(course, p1, 0), _lesson(course, p1, 1)
    p2 = _container(course, "part", order=1)
    _lesson(course, p2, 0)
    user = _student(client, course, "cl")
    UnitProgressFactory(student=user, unit=a, completed=True)
    soup = _polish_soup(client, course)
    long = soup.select_one(f"#node-{p1.pk} .outline-card__meta .outline-count__long")
    assert long.get_text(strip=True) == "1 z 2 lekcji"
    assert soup.select_one("span.outline-list__count").get_text(strip=True) == (
        "Działy · 2"
    )


def test_start_button_in_polish_carries_ui_lang_on_an_en_course(client):
    course = CourseFactory(language="en")
    _lesson(course, None, 0)
    _student(client, course, "sb")
    btn = _polish_soup(client, course).select_one("a.outline__start")
    assert btn.get_text(strip=True) == "Zacznij pierwszą lekcję"
    assert btn["lang"] == "pl"


def test_status_word_in_polish_carries_ui_lang(client):
    course = CourseFactory(language="en")
    part = _container(course, "part")
    chapter = _container(course, "chapter", part, 0)
    _lesson(course, chapter, 0)
    row = _container(course, "chapter", part, 1)
    _lesson(course, row, 0)
    _lesson(course, row, 1)
    _student(client, course, "sw")
    soup = _polish_soup(client, course)
    head = soup.select_one(f'details[data-node="{chapter.pk}"] > summary')
    status = head.select_one(".outline-status")
    assert status.get_text(strip=True) == "Nie rozpoczęto"
    assert status["lang"] == "pl"
    # A depth-1 row's long count span carries the UI language too, not just cards.
    long = head.select_one(".outline-count__long")
    assert long["lang"] == "pl"
    assert long.get_text(strip=True) == "0 z 1 lekcji"
    card_long = soup.select_one(
        f"#node-{part.pk} .outline-card__meta .outline-count__long"
    )
    assert card_long["lang"] == "pl"


def test_svg_and_style_numbers_have_no_decimal_comma(client):
    course = CourseFactory()
    part = _container(course, "part")
    saved = _container(course, "chapter", part, 0)
    done = _container(course, "chapter", part, 1)
    saved_unit = _lesson(course, saved, 0)
    _lesson(course, saved, 1)
    done_unit = _lesson(course, done, 0)
    _lesson(course, done, 1)
    user = _student(client, course, "dc")
    UnitProgressFactory(student=user, unit=saved_unit, element_state={"1": {}})
    UnitProgressFactory(student=user, unit=done_unit, completed=True)
    soup = _polish_soup(client, course)
    arc = soup.select_one(
        f'details[data-node="{saved.pk}"] > summary circle.outline-ring__arc'
    )
    assert arc["stroke-dasharray"] == "9 100"
    assert "," not in arc["stroke-dasharray"]
    fill = soup.select_one(f"#node-{part.pk} .outline-card__fill")
    assert fill["style"] == "width: 25%"
    assert "," not in fill["style"]
