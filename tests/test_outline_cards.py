"""Render-tier tests for the outline's container markup: cards, rows, counts, menus.

Spec 2026-10-18-student-course-outline-redesign §3.2 (cards), §3.4 (rows), §3.7 (menus).
"""

import pytest
from bs4 import BeautifulSoup
from django.template.loader import render_to_string
from django.urls import reverse

from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
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


def _quiz(course, parent, order=0):
    return _lesson(course, parent, order, unit_type="quiz")


def _student(client, course, name):
    user = make_login(client, name)
    EnrollmentFactory(student=user, course=course)
    return user


def _complete(user, *units):
    for u in units:
        UnitProgressFactory(student=user, unit=u, completed=True)


def _save_state(user, unit):
    UnitProgressFactory(student=user, unit=unit, element_state={"1": {}})


def _url(course):
    return reverse("courses:course_outline", kwargs={"slug": course.slug})


def _get(client, course, query=""):
    return client.get(_url(course) + query)


def _soup(client, course, query=""):
    return BeautifulSoup(_get(client, course, query).content.decode(), "html.parser")


def _summary(soup, node):
    return soup.select_one(f'details[data-node="{node.pk}"] > summary')


def _li(soup, node):
    return soup.select_one(f"li#node-{node.pk}")


def _two_parts(client, name):
    """Part 1 (1/4 required done) > chapters A (1/2) and B (0/2); Part 2 (0/2)."""
    course = CourseFactory()
    p1 = _container(course, "part", order=0, title="Part One")
    a = _container(course, "chapter", p1, 0, title="Chapter A")
    b = _container(course, "chapter", p1, 1, title="Chapter B")
    a1, _a2 = _lesson(course, a, 0), _lesson(course, a, 1)
    _lesson(course, b, 0), _lesson(course, b, 1)
    p2 = _container(course, "part", order=1, title="Part Two")
    c = _container(course, "chapter", p2, 0, title="Chapter C")
    _lesson(course, c, 0), _lesson(course, c, 1)
    user = _student(client, course, name)
    _complete(user, a1)
    return course, user, {"p1": p1, "p2": p2, "a": a, "b": b, "c": c, "a1": a1}


def test_root_containers_render_as_numbered_cards(client):
    course, _, _ = _two_parts(client, "cards1")
    soup = _soup(client, course)
    cards = soup.select("li.outline-node--card")
    assert [c.select_one(".outline-card__num").get_text(strip=True) for c in cards] == [
        "1",
        "2",
    ]
    assert all(
        c.select_one(".outline-card__num")["aria-hidden"] == "true" for c in cards
    )


def test_card_bar_width_and_counts(client):
    course, _, n = _two_parts(client, "cards2")
    card = _li(_soup(client, course), n["p1"])
    assert card.select_one(".outline-card__fill")["style"] == "width: 25%"
    assert card.select_one(".outline-count__short").get_text(strip=True) == "1/4"
    long = card.select_one(".outline-card__meta .outline-count__long")
    assert long.get_text(strip=True) == "1 of 4 lessons"
    assert "visually-hidden" not in long["class"], "the card's long count is visible"
    assert long["lang"] == "en"
    assert card.select_one(".outline-count__short")["aria-hidden"] == "true"


def test_card_with_nothing_done_has_an_empty_track(client):
    course, _, n = _two_parts(client, "cards3")
    card = _li(_soup(client, course), n["p2"])
    head = card.select_one("summary.outline-node__head")
    bar = head.select_one(".outline-card__bar")
    assert bar is not None and bar["aria-hidden"] == "true"
    assert bar.select_one(".outline-card__fill") is None
    assert head.select_one(".outline-count__short").get_text(strip=True) == "0/2"


def test_all_quiz_card_has_no_bar_count_or_meta_row(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    _quiz(course, chapter)
    _student(client, course, "quizcard")
    card = _li(_soup(client, course), part)
    assert "outline-node--card" in card["class"]
    assert card.select_one(".outline-card__meta") is None
    assert card.select_one(".outline-card__bar") is None
    assert card.select_one(".outline-count") is None


def test_additional_chip_still_renders(client):
    course = CourseFactory()
    part = _container(course, "part")
    _lesson(course, part, 0)
    optional = _lesson(course, part, 1, obligatory=False)
    user = _student(client, course, "chip")
    _complete(user, optional)
    head = _summary(_soup(client, course), part)
    cell = head.select_one(".outline-card__countcell")
    chip = cell.select_one(".rollup.rollup--additional")
    assert chip.get_text(" ", strip=True) == "+1 additional"
    assert cell.select_one(".outline-count") is not None
    assert chip.find_previous_sibling(class_="outline-count") is not None


def test_card_meta_has_exactly_two_children(client):
    course, _, n = _two_parts(client, "meta2")
    meta = _summary(_soup(client, course), n["p1"]).select_one(".outline-card__meta")
    kids = meta.find_all(recursive=False)
    assert [k["class"][0] for k in kids] == [
        "outline-card__bar",
        "outline-card__countcell",
    ]


def test_chevron_is_the_last_child_of_a_card_summary(client):
    course, _, n = _two_parts(client, "chev")
    head = _summary(_soup(client, course), n["p1"])
    kids = head.find_all(recursive=False)
    assert "outline-card__num" in kids[0]["class"]
    assert "outline-node__title" in kids[1]["class"]
    assert kids[1]["id"] == f"node-title-{n['p1'].pk}"
    assert "outline-card__meta" in kids[2]["class"]
    assert "outline-node__chevron" in kids[-1]["class"]
    assert len(kids) == 4


def _ring_course(client, name):
    course = CourseFactory()
    part = _container(course, "part")
    done = _container(course, "chapter", part, 0, title="Done")
    prog = _container(course, "chapter", part, 1, title="Prog")
    none = _container(course, "chapter", part, 2, title="None")
    d1 = _lesson(course, done, 0)
    p1 = _lesson(course, prog, 0)
    _lesson(course, prog, 1)
    _lesson(course, none, 0)
    user = _student(client, course, name)
    _complete(user, d1, p1)
    return course, done, prog, none


def test_depth1_row_ring_classes_and_status_word(client):
    course, done, prog, none = _ring_course(client, "rings")
    soup = _soup(client, course)
    for node, state, word in [
        (done, "done", "Completed"),
        (prog, "progress", "In progress"),
        (none, "none", "Not started"),
    ]:
        head = _summary(soup, node)
        ring = head.select_one(".outline-ring")
        assert f"outline-ring--{state}" in ring["class"], node.title
        assert ring["aria-hidden"] == "true"
        status = head.select_one(".outline-status")
        assert "visually-hidden" in status["class"]
        assert status.get_text(strip=True) == word
        assert status["lang"] == "en"
        assert "outline-node__chevron" in head.find_all(recursive=False)[-1]["class"]
    done_ring = _summary(soup, done).select_one(".outline-ring")
    assert done_ring.select_one("circle.outline-ring__fill")["r"] == "9"
    assert done_ring.select_one("path.outline-ring__tick") is not None
    none_ring = _summary(soup, none).select_one(".outline-ring")
    assert none_ring.select_one("circle.outline-ring__track")["r"] == "8"
    assert none_ring.select_one(".outline-ring__arc") is None
    assert none_ring.select_one("svg")["viewbox"] == "0 0 20 20"


def test_all_quiz_row_has_an_empty_ring_slot_and_no_status_word(client):
    course = CourseFactory()
    part = _container(course, "part")
    _lesson(course, part, 0)
    chapter = _container(course, "chapter", part, 1)
    _quiz(course, chapter)
    _student(client, course, "quizrow")
    head = _summary(_soup(client, course), chapter)
    ring = head.select_one(".outline-ring")
    assert ring is not None and ring["aria-hidden"] == "true"
    assert ring["class"] == ["outline-ring"]
    assert not ring.contents
    assert head.select_one(".outline-status") is None
    assert head.select_one(".outline-count") is None


def test_depth1_summary_accessible_text_starts_with_title_then_count(client):
    course, _, n = _two_parts(client, "acc")
    summary = _summary(_soup(client, course), n["a"])
    assert summary.get_text(" ", strip=True).startswith("Chapter A 1/2 1 of 2 lessons")


def _current_course(client, name):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part, 0)
    other = _container(course, "chapter", part, 1)
    unit = _lesson(course, chapter, 0)
    _lesson(course, other, 0)
    _student(client, course, name)
    return course, chapter, unit


def test_exactly_one_current_row_with_aria_current(client, monkeypatch):
    course, chapter, unit = _current_course(client, "cur1")
    monkeypatch.setattr(
        "courses.views.build_resume",
        lambda c, u, t: {"node": unit, "state": "next", "ancestors": []},
    )
    soup = _soup(client, course)
    assert len(soup.select('[aria-current="step"]')) == len(soup.select(".is-current"))
    assert len(soup.select(".is-current")) == 1
    row = soup.select_one("summary.is-current")
    assert row == _summary(soup, chapter)
    assert row["aria-current"] == "step"
    assert "outline-node__head" in row["class"]


def test_no_current_row_in_start_state(client):
    """The REAL build_resume: it stamps contains_current in every state, start
    included, so a template that read contains_current would light a row here."""
    course, _, _ = _current_course(client, "cur2")
    r = _get(client, course)
    assert r.context["resume"]["state"] == "start"
    soup = BeautifulSoup(r.content.decode(), "html.parser")
    assert soup.select(".is-current") == []
    assert soup.select('[aria-current="step"]') == []


def _deep_course(client, name):
    """part > chapter > section > unit, with saved state on the unit."""
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    section = _container(course, "section", chapter, title="Section S")
    unit = _lesson(course, section)
    user = _student(client, course, name)
    _save_state(user, unit)
    return course, part, chapter, section


def test_depth2_head_has_count_pair_and_no_ring_or_chip(client):
    course, _, _, section = _deep_course(client, "deep")
    soup = _soup(client, course)
    head = _summary(soup, section)
    kids = head.find_all(recursive=False)
    assert "outline-node__chevron" in kids[0]["class"]
    assert kids[1]["id"] == f"node-title-{section.pk}"
    assert head.select_one(".outline-ring") is None
    assert head.select_one(".outline-status") is None
    assert head.select_one(".outline-count__short").get_text(strip=True) == "0/1"
    long = head.select_one(".outline-count__long")
    assert "visually-hidden" in long["class"]
    assert long.get_text(strip=True) == "0 of 1 lesson"
    assert not soup.select(".rollup:-soup-contains('lessons:')")


def test_reset_links_live_only_inside_menus(client):
    course, *_ = _deep_course(client, "menus")
    soup = _soup(client, course)
    links = soup.select("a.outline-node__reset")
    assert len(links) == 3, "one menu per stateful container: part, chapter, section"
    assert all(a.find_parent("details", class_="outline-menu") for a in links)
    assert not any(a.find_parent("summary") for a in links)


def test_menu_present_iff_node_has_state_and_href_unchanged(client):
    course = CourseFactory()
    part = _container(course, "part")
    stateful = _container(course, "chapter", part, 0)
    clean = _container(course, "chapter", part, 1)
    unit = _lesson(course, stateful)
    _lesson(course, clean)
    user = _student(client, course, "menu-iff")
    _save_state(user, unit)
    soup = _soup(client, course)

    def menu_after(node):
        details = soup.select_one(f'details[data-node="{node.pk}"]')
        sib = details.find_next_sibling()
        return sib if sib is not None and "outline-menu" in sib["class"] else None

    assert menu_after(clean) is None
    menu = menu_after(stateful)
    assert menu.name == "details"
    button = menu.select_one(":scope > summary.outline-menu__button")
    assert button["aria-label"] == "More actions"
    assert button["aria-describedby"] == f"node-title-{stateful.pk}"
    assert button["lang"] == "en"
    assert button.get_text(strip=True) == "⋯"
    link = menu.select_one(".outline-menu__panel > a.outline-node__reset")
    assert "outline-menu__item" in link["class"]
    assert link.get_text(strip=True) == "Start fresh"
    assert link["href"] == (
        reverse(
            "courses:progress_reset",
            kwargs={"slug": course.slug, "node_pk": stateful.pk},
        )
        + "?next="
        + _url(course)
    )
    assert menu_after(part) is not None, "the card holds saved work too"


def test_every_aria_describedby_resolves(client):
    course, *_ = _deep_course(client, "describedby")
    soup = _soup(client, course)
    ids = {el["id"] for el in soup.select("[id]")}
    described = soup.select("[aria-describedby]")
    assert len(described) >= 3
    assert all(el["aria-describedby"] in ids for el in described)


def test_arc_dasharray_is_an_integer_pair(client):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    unit = _lesson(course, chapter)
    user = _student(client, course, "arc")
    _save_state(user, unit)
    ring = _summary(_soup(client, course), chapter).select_one(".outline-ring")
    assert "outline-ring--progress" in ring["class"]
    arc = ring.select_one("circle.outline-ring__arc")
    assert arc["stroke-dasharray"] == "9 100"
    assert arc["pathlength"] == "100"
    assert ring.select_one("circle.outline-ring__track")["r"] == "8"


class _Node:
    pk = 1
    kind = "chapter"
    title = "Bare"


class _Course:
    language = "en"
    slug = "c"


def _bare(**extra):
    item = {
        "node": _Node(),
        "is_unit": False,
        "children": [],
        "required_total": 2,
        "required_done": 1,
        "additional_done": 0,
        "depth": 0,
    }
    item.update(extra)
    return render_to_string(
        "courses/_outline_node.html",
        {"item": item, "course": _Course(), "note_counts": {}},
    )


def test_childless_arm_renders_from_a_bare_dict():
    html = _bare()
    assert "outline-node--card" not in html and "outline-card__num" not in html
    soup = BeautifulSoup(html, "html.parser")
    head = soup.select_one("div.outline-node__head")
    assert head.select_one(".outline-node__title")["id"] == "node-title-1"
    assert head.select_one(".outline-count__short").get_text(strip=True) == "1/2"
    assert "visually-hidden" in head.select_one(".outline-count__long")["class"]
    for absent in (
        ".outline-ring",
        ".outline-card__bar",
        ".outline-node__chevron",
        ".outline-menu",
    ):
        assert head.select_one(absent) is None, absent

    soup = BeautifulSoup(_bare(has_state=True), "html.parser")
    menu = soup.select_one("div.outline-node__head > details.outline-menu")
    assert menu is not None
    assert menu.find_next_sibling() is None, "the menu sits at the end of the head"
    ids = {el["id"] for el in soup.select("[id]")}
    assert menu.select_one("summary")["aria-describedby"] in ids


def test_no_bar_or_count_when_no_required_lessons(client):
    course = CourseFactory()
    opt_part = _container(course, "part", order=0)
    optional = _lesson(course, opt_part, obligatory=False)
    quiz_part = _container(course, "part", order=1)
    _lesson(course, quiz_part, 0)
    quiz_chapter = _container(course, "chapter", quiz_part, 1)
    _quiz(course, quiz_chapter)
    user = _student(client, course, "noreq")
    _complete(user, optional)
    soup = _soup(client, course)

    meta = _summary(soup, opt_part).select_one(".outline-card__meta")
    assert meta is not None, "the +N chip still needs the meta row"
    assert meta.select_one(".rollup--additional") is not None
    assert meta.select_one(".outline-card__bar") is None
    assert meta.select_one(".outline-count") is None
    assert "0/0" not in meta.get_text()

    assert _summary(soup, quiz_chapter).select_one(".outline-count") is None


@pytest.mark.parametrize("source", ["saved_state", "bare_visit", "quiz_in_progress"])
def test_resume_from_each_real_source_lights_the_current_row(client, source):
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part)
    _lesson(course, chapter, 0)
    user = _student(client, course, f"src-{source}")
    if source == "quiz_in_progress":
        target = _quiz(course, chapter, 1)
        QuizSubmissionFactory(
            student=user, unit=target, status=QuizSubmission.Status.IN_PROGRESS
        )
    else:
        target = _lesson(course, chapter, 1)
        state = {"1": {}} if source == "saved_state" else {}
        UnitProgressFactory(student=user, unit=target, element_state=state)

    r = _get(client, course)
    assert r.context["resume"]["state"] == "resume"
    assert r.context["resume"]["node"].pk == target.pk
    soup = BeautifulSoup(r.content.decode(), "html.parser")
    row = soup.select_one("summary.is-current")
    assert row == _summary(soup, chapter)
    assert "outline-ring--progress" in row.select_one(".outline-ring")["class"]
    assert row.select_one(".outline-status").get_text(strip=True) == "In progress"


def test_every_li_keeps_its_node_id_and_filtered_cards_are_hidden(client):
    from tags.models import Tag
    from tags.models import UnitTag

    course, user, n = _two_parts(client, "ids")
    soup = _soup(client, course)
    for li in soup.select("li.outline-node"):
        assert li.get("id", "").startswith("node-"), li.get("class")

    tag = Tag.objects.create(author=user, name="exam")
    UnitTag.objects.create(tag=tag, unit=n["a1"])
    soup = _soup(client, course, f"?tags={tag.pk}")
    assert _li(soup, n["p2"]).has_attr("hidden")
    assert "outline-node--card" in _li(soup, n["p2"])["class"]
    assert not _li(soup, n["p1"]).has_attr("hidden")


def test_depth1_row_meta_wraps_count_and_chip_only_when_present(client):
    """The phone layout moves .outline-row__meta under the title, so it must hold
    exactly the count and the "+N" chip, and be absent from a row with neither."""
    course = CourseFactory()
    part = _container(course, "part")
    chapter = _container(course, "chapter", part, 0)
    _lesson(course, chapter, 0)
    extra = _lesson(course, chapter, 1, obligatory=False)
    quiz_chapter = _container(course, "chapter", part, 1)
    _quiz(course, quiz_chapter)
    user = _student(client, course, "rowmeta")
    _complete(user, extra)
    soup = _soup(client, course)

    head = _summary(soup, chapter)
    meta = head.select_one(":scope > .outline-row__meta")
    assert meta is not None
    kids = [" ".join(k["class"]) for k in meta.find_all(recursive=False)]
    assert kids == ["outline-count", "rollup rollup--additional"]
    # the status word stays a direct child, after the meta, before the chevron
    order = [k["class"][-1] for k in head.find_all(recursive=False)]
    tail = ["outline-row__meta", "outline-status", "outline-node__chevron"]
    assert order[-3:] == tail

    assert _summary(soup, quiz_chapter).select_one(".outline-row__meta") is None
