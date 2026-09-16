"""The student results page (spec §4; T6-T13, T15, T16, T28b)."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse

from courses.models import QuizSubmission
from courses.rollups import build_student_breakdown
from courses.views_analytics import _expand_qs
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory
from tests.factories import make_login

pytestmark = pytest.mark.django_db


def _polish(client):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()


def _node(course, parent, kind, title, **kw):
    unit_type = kw.pop("unit_type", None)
    return ContentNodeFactory(
        course=course, parent=parent, kind=kind, unit_type=unit_type, title=title, **kw
    )


def _titles(tree):
    out = []

    def walk(nodes):
        for d in nodes:
            out.append(d["node"].title)
            walk(d["children"])

    walk(tree)
    return out


def _find(tree, title):
    for d in tree:
        if d["node"].title == title:
            return d
        hit = _find(d["children"], title)
        if hit is not None:
            return hit
    return None


def test_t10_results_keeps_a_deep_quiz_with_every_ancestor():
    course = CourseFactory()
    part = _node(course, None, "part", "Part")
    chapter = _node(course, part, "chapter", "Chapter")
    section = _node(course, chapter, "section", "Section")
    quiz = _node(course, section, "unit", "Deep quiz", unit_type="quiz")
    _node(course, section, "unit", "Side lesson", unit_type="lesson", obligatory=True)
    student = UserFactory()
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )

    tree = build_student_breakdown(course, student, drafts="keep", mode="results")[
        "tree"
    ]
    assert _titles(tree) == ["Part", "Chapter", "Section", "Deep quiz"]
    assert _find(tree, "Deep quiz")["pill"]["kind"] in {"submitted", "scored"}


def test_t15_default_mode_is_progress_and_keeps_lessons():
    course = CourseFactory()
    chapter = _node(course, None, "chapter", "Chapter")
    _node(course, chapter, "unit", "Lesson", unit_type="lesson", obligatory=True)
    _node(course, chapter, "unit", "Quiz", unit_type="quiz")
    tree = build_student_breakdown(course, UserFactory(), drafts="keep")["tree"]
    assert _titles(tree) == ["Chapter", "Lesson", "Quiz"]


def test_units_are_stamped_additional_as_a_boolean():
    course = CourseFactory()
    chapter = _node(course, None, "chapter", "Chapter")
    _node(course, chapter, "unit", "Required", unit_type="lesson", obligatory=True)
    _node(course, chapter, "unit", "Extra", unit_type="lesson", obligatory=False)
    _node(course, chapter, "unit", "Quiz", unit_type="quiz")
    tree = build_student_breakdown(course, UserFactory(), drafts="keep")["tree"]
    assert _find(tree, "Required")["additional"] is False
    assert _find(tree, "Extra")["additional"] is True
    assert _find(tree, "Quiz")["additional"] is False  # never the raw "quiz" marker


def _page_fixture(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    mixed = _node(course, None, "chapter", "Mixed chapter")
    lesson = _node(
        course,
        mixed,
        "unit",
        r"Required lesson \(x\)",
        unit_type="lesson",
        obligatory=True,
    )
    _node(course, mixed, "unit", "Extra lesson", unit_type="lesson", obligatory=False)
    quiz = _node(course, mixed, "unit", "Chapter quiz", unit_type="quiz")
    _node(course, mixed, "unit", "Unstarted quiz", unit_type="quiz")
    _node(course, mixed, "unit", "Typeless unit", unit_type=None)
    lonely = _node(course, None, "chapter", "Lessons-only chapter")
    _node(course, lonely, "unit", "Lonely lesson", unit_type="lesson", obligatory=True)
    # display_name equal to "First Last", so list_display_name adds no parenthetical
    student = UserFactory(
        first_name="Anna", last_name="Nowak", display_name="Anna Nowak"
    )
    EnrollmentFactory(student=student, course=course)
    UnitProgressFactory(student=student, unit=lesson, completed=True)
    QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("1"),
        max_score=Decimal("1"),
    )
    path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )
    return course, student, mixed, path


def _get(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    return resp, BeautifulSoup(resp.content.decode(), "html.parser")


def _unit_titles(soup):
    return [s.get_text(" ", strip=True) for s in soup.select(".breakdown-unit__title")]


def _head(soup, title):
    for head in soup.select(".breakdown-node__head"):
        if head.select_one(".breakdown-node__title").get_text(strip=True) == title:
            return head
    return None


def test_t6_results_mode_shows_quizzes_only(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    assert _unit_titles(soup) == ["Chapter quiz", "Unstarted quiz"]
    assert _head(soup, "Lessons-only chapter") is None
    unstarted = soup.select(".breakdown-unit")[1]
    assert unstarted.select_one(".pill.pill--none") is not None


def test_t7_results_mode_hides_the_chapter_chip_progress_shows_it(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, results = _get(client, f"{path}?mode=results")
    _resp, progress = _get(client, f"{path}?mode=progress")
    assert _head(results, "Mixed chapter").select_one(".rollup") is None
    assert _head(progress, "Mixed chapter").select_one(".rollup") is not None


def test_t8_progress_mode_keeps_lessons_and_chips(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=progress")
    titles = _unit_titles(soup)
    assert "Extra lesson" in titles and "Lonely lesson" in titles
    assert _head(soup, "Lessons-only chapter").select_one(".rollup") is not None


@pytest.mark.parametrize("query", ["", "?mode=nonsense"])
def test_t9_missing_or_unknown_mode_renders_progress(client, query):
    _course, _student, _mixed, path = _page_fixture(client)
    resp, soup = _get(client, f"{path}{query}")
    assert resp.context["mode"] == "progress"
    assert "Lonely lesson" in _unit_titles(soup)


def test_t11_switch_links_the_other_mode_and_keeps_every_param(client):
    course, student, mixed, path = _page_fixture(client)
    query = f"?scope=all&mode=results&expand={mixed.pk}&student={student.pk}&values=raw"
    _resp, soup = _get(client, f"{path}{query}")
    switch = soup.select_one(".breakdown__view")
    current = switch.select_one('a[aria-current="page"]')
    assert current.get_text(strip=True) == "Results"
    others = [a for a in switch.select("a") if a is not current]
    assert [a.get_text(strip=True) for a in others] == ["Progress"]
    expected = _expand_qs("all", "progress", [mixed.pk], [student.pk], "raw")
    assert others[0]["href"] == f"{path}?{expected}"


def test_t16_has_math_is_computed_from_the_pruned_tree(client):
    _course, _student, _mixed, path = _page_fixture(client)
    results, _soup = _get(client, f"{path}?mode=results")
    progress, _soup = _get(client, f"{path}?mode=progress")
    assert results.context["has_math"] is False  # the maths title is a lesson's
    assert progress.context["has_math"] is True


def test_t28b_one_page_name_in_both_modes(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _polish(client)
    for mode, word in (("results", "Wyniki"), ("progress", "Postęp")):
        _resp, soup = _get(client, f"{path}?mode={mode}")
        assert (
            soup.select_one("h1").get_text(" ", strip=True)
            == "Wyniki ucznia — Anna Nowak"
        )
        assert (
            soup.select_one("title").get_text(strip=True).startswith("Wyniki ucznia ·")
        )
        current = soup.select_one('.breakdown__view a[aria-current="page"]')
        assert current.get_text(strip=True) == word
