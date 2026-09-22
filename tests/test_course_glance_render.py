"""Render contract of courses/_course_glance.html and its placements."""

import re
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.db import connection
from django.template.loader import render_to_string
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation

from courses.models import Element
from courses.models import ShortTextQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import make_login
from tests.test_course_glance import _shaped_course


def _render(**ctx):
    ctx.setdefault("progress_done", 0)
    ctx.setdefault("progress_total", 0)
    ctx.setdefault("results_pct", None)
    html = render_to_string("courses/_course_glance.html", ctx)
    return BeautifulSoup(html, "html.parser")


def _tracks(soup):
    return soup.select(".glance__track")


@pytest.mark.parametrize(
    ("width", "fill", "dot"),
    [(None, False, False), (0, False, True), (1, True, False), (100, True, False)],
)
def test_results_fill_rules(width, fill, dot):
    soup = _render(progress_width=None, results_width=width, results_pct=width)
    track = _tracks(soup)[1]
    assert bool(track.select(".glance__fill")) is fill
    assert bool(track.select(".glance__dot")) is dot
    if fill:
        assert track.select_one(".glance__fill")["style"] == f"width: {width}%"


def test_progress_zero_of_n_draws_neither_fill_nor_dot():
    soup = _render(progress_width=None, results_width=None, progress_total=4)
    track = _tracks(soup)[0]
    assert not track.select(".glance__fill") and not track.select(".glance__dot")


def test_progress_fill_width():
    soup = _render(
        progress_width=37, results_width=None, progress_done=3, progress_total=8
    )
    assert _tracks(soup)[0].select_one(".glance__fill")["style"] == "width: 37%"


def test_labels_are_hidden_and_tracks_carry_names():
    soup = _render(
        progress_width=50,
        results_width=80,
        progress_done=1,
        progress_total=2,
        results_pct=80,
    )
    for label in soup.select(".glance__label"):
        assert label["aria-hidden"] == "true"
    progress, results = _tracks(soup)
    assert progress["role"] == "img" and results["role"] == "img"
    assert progress["aria-label"] == "Progress: 1 of 2 lessons"
    assert results["aria-label"] == "Results: 80%"


def test_english_plural_uses_count():
    one = _tracks(
        _render(
            progress_width=None, results_width=None, progress_done=0, progress_total=1
        )
    )[0]
    two = _tracks(
        _render(
            progress_width=None, results_width=None, progress_done=0, progress_total=2
        )
    )[0]
    assert one["aria-label"] == "Progress: 0 of 1 lesson"
    assert two["aria-label"] == "Progress: 0 of 2 lessons"


def test_none_figures_are_spoken():
    progress, results = _tracks(_render(progress_width=None, results_width=None))
    assert progress["aria-label"] == "Progress: no lessons to track"
    assert results["aria-label"] == "Results: no scores yet"


def test_no_visible_digits():
    soup = _render(
        progress_width=37,
        results_width=80,
        progress_done=3,
        progress_total=8,
        results_pct=80,
    )
    assert not re.search(r"\d", soup.select_one(".glance").get_text())


def test_decorative_emits_no_roles_or_labels():
    soup = _render(progress_width=70, results_width=85, decorative=True)
    for track in _tracks(soup):
        assert not track.has_attr("role") and not track.has_attr("aria-label")
    assert len(soup.select(".glance__fill")) == 2


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (1, "Postęp: 0 z 1 lekcji"),
        (3, "Postęp: 0 z 3 lekcji"),
        (5, "Postęp: 0 z 5 lekcji"),
    ],
)
def test_polish_progress_label(total, expected):
    with translation.override("pl"):
        track = _tracks(
            _render(
                progress_width=None,
                results_width=None,
                progress_done=0,
                progress_total=total,
            )
        )[0]
    assert track["aria-label"] == expected


def test_polish_results_and_labels():
    with translation.override("pl"):
        soup = _render(progress_width=None, results_width=80, results_pct=80)
    assert _tracks(soup)[1]["aria-label"] == "Wyniki: 80%"  # single %, not %%
    labels = [x.get_text(strip=True) for x in soup.select(".glance__label")]
    assert labels == ["Postęp", "Wyniki"]
    with translation.override("pl"):
        none = _tracks(_render(progress_width=None, results_width=None))
    assert none[0]["aria-label"] == "Postęp: brak lekcji obowiązkowych"
    assert none[1]["aria-label"] == "Wyniki: jeszcze brak punktów"


def test_every_polish_plural_index_is_filled():
    from pathlib import Path

    from django.conf import settings

    po = (Path(settings.BASE_DIR) / "locale/pl/LC_MESSAGES/django.po").read_text(
        encoding="utf-8"
    )
    block = po.split('msgid "Progress: %(done)s of %(counter)s lesson"', 1)[1]
    block = block.split("\n\n", 1)[0]
    for i in range(3):
        m = re.search(rf'msgstr\[{i}\] "(.*)"', block)
        assert m and m.group(1), f"msgstr[{i}] is empty"


PAGES = ["home", "courses:my_courses"]  # URL names; reversed inside each test


def _glance_for(soup, title):
    """The .glance that follows the course title link on either page."""
    link = soup.find("a", string=title)
    assert link is not None, f"{title} not listed"
    return link.find_next(class_="glance")


def _student_with_two_courses(client):
    student = make_login(client, "glance_student")
    started = CourseFactory(title="Started Course")
    EnrollmentFactory(student=student, course=started)
    done = ContentNodeFactory(
        course=started, kind="unit", unit_type="lesson", parent=None, obligatory=True
    )
    ContentNodeFactory(
        course=started, kind="unit", unit_type="lesson", parent=None, obligatory=True
    )
    UnitProgressFactory(student=student, unit=done, completed=True)
    quiz = ContentNodeFactory(
        course=started, kind="unit", unit_type="quiz", parent=None
    )
    q = ShortTextQuestionElement.objects.create(
        stem="q", accepted="a", marking_mode="A", max_marks=Decimal("10")
    )
    Element.objects.create(unit=quiz, content_object=q)
    QuizSubmissionFactory(
        student=student,
        unit=quiz,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("10"),
    )
    untouched = CourseFactory(title="Untouched Course")
    EnrollmentFactory(student=student, course=untouched)
    ContentNodeFactory(
        course=untouched, kind="unit", unit_type="lesson", parent=None, obligatory=True
    )
    return student


@pytest.mark.django_db
@pytest.mark.parametrize("url", PAGES)
def test_pages_render_each_state(client, url):
    _student_with_two_courses(client)
    resp = client.get(reverse(url))
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.content, "html.parser")

    started = _glance_for(soup, "Started Course")
    p_track, r_track = started.select(".glance__track")
    assert p_track.select_one(".glance__fill")["style"] == "width: 50%"
    assert r_track.select(".glance__dot") and not r_track.select(".glance__fill")
    assert r_track["aria-label"] == "Results: 0%"

    untouched = _glance_for(soup, "Untouched Course")
    p_track, r_track = untouched.select(".glance__track")
    assert not p_track.select(".glance__fill") and not p_track.select(".glance__dot")
    assert p_track["aria-label"] == "Progress: 0 of 1 lesson"
    assert not r_track.select(".glance__fill") and not r_track.select(".glance__dot")
    assert not re.search(r"\d", started.get_text() + untouched.get_text())


@pytest.mark.django_db
@pytest.mark.parametrize("url", PAGES)
def test_one_broken_course_does_not_break_the_page(client, url, monkeypatch, caplog):
    import courses.rollups as rollups

    _student_with_two_courses(client)
    real = rollups.course_glance

    def flaky(course, user, *, drafts):
        if course.title == "Untouched Course":
            raise RuntimeError("inconsistent tree")
        return real(course, user, drafts=drafts)

    monkeypatch.setattr(rollups, "course_glance", flaky)
    with caplog.at_level("ERROR", logger="courses.rollups"):
        resp = client.get(reverse(url))
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.content, "html.parser")
    assert _glance_for(soup, "Started Course").select(".glance__fill")
    broken = _glance_for(soup, "Untouched Course").select(".glance__track")
    assert broken[0]["aria-label"] == "Progress: no lessons to track"
    assert "inconsistent tree" in caplog.text


@pytest.mark.django_db
def test_teaching_and_studio_panels_have_no_glance(client):
    # The user teaches one course, owns another, AND is enrolled in a third, so a
    # glance DOES render (in My learning) -- the guard is not vacuous.
    teacher = make_login(client, "glance_teacher")
    taught = CourseFactory(title="Taught Course")
    GroupFactory(course=taught).teachers.add(teacher)
    CourseFactory(title="Owned Course", owner=teacher)
    EnrollmentFactory(student=teacher, course=CourseFactory(title="Learned Course"))
    soup = BeautifulSoup(client.get(reverse("home")).content, "html.parser")
    learning = soup.select_one('[data-section="learning"]')
    teaching = soup.select_one('[data-section="teaching"]')
    studio = soup.select_one('[data-section="manage"]')
    assert learning.select(".glance")
    assert teaching.find("a", string="Taught Course")  # panel content unchanged
    assert not teaching.select(".glance")
    assert studio.find("a", string="Owned Course")
    assert not studio.select(".glance")


def _landing(client, lang):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = lang
    session.save()
    resp = client.get("/")
    assert resp.status_code == 200
    return resp


def _cards(resp):
    soup = BeautifulSoup(resp.content, "html.parser")
    visual = soup.select_one(".landing-visual")
    assert visual is not None and visual["aria-hidden"] == "true"
    return visual, {
        c.select_one(".glance-card__title").get_text(strip=True): c
        for c in visual.select(".glance-card")
    }


@pytest.mark.django_db
def test_landing_polish_titles_and_states(client):
    resp = _landing(client, "pl")
    visual, cards = _cards(resp)
    assert list(cards) == ["Hiszpański A2", "Matematyka", "Biologia"]
    assert not visual.select("a") and not visual.select('[role="img"]')
    assert not visual.select(".dash-card")

    def widths(card):
        return [f["style"] for f in card.select(".glance__fill")]

    assert widths(cards["Hiszpański A2"]) == ["width: 70%", "width: 85%"]
    assert widths(cards["Matematyka"]) == ["width: 20%", "width: 55%"]
    biology = cards["Biologia"]
    assert widths(biology) == ["width: 5%"]
    results_track = biology.select(".glance__track")[1]
    assert not results_track.select(".glance__fill, .glance__dot")
    assert "width: %" not in resp.content.decode()


@pytest.mark.django_db
def test_landing_english_titles(client):
    _visual, cards = _cards(_landing(client, "en"))
    assert list(cards) == ["Spanish A2", "Mathematics", "Biology"]


@pytest.mark.django_db
@pytest.mark.parametrize("url", PAGES)
def test_view_query_cost_is_linear_in_courses(client, url):
    student = make_login(client, "glance_queries")
    counts = {}
    for n in (1, 2, 3):
        EnrollmentFactory(student=student, course=_shaped_course(student, 2))
        client.get(reverse(url))  # warm caches for this N
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(reverse(url)).status_code == 200
        counts[n] = len(ctx)
    assert counts[3] - counts[2] == counts[2] - counts[1]
    # The absolute per-course cost is recorded in Task 6 (verification notes).
    print(f"per-course queries on {url}: {counts[2] - counts[1]}")
