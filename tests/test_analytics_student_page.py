"""The teacher's student page. Two specs' ids live here: test_t6…test_t28b are the
student-pages spec's (2026-09-16); test_rt_* are the results-table spec's
(2026-09-17). Select by NAME."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils import timezone

from courses import rollups
from courses.color_bands import band_style
from courses.color_bands import course_color_bands
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rollups import _fmt_mark
from courses.rollups import build_results_matrix
from courses.rollups import build_student_breakdown
from courses.views_analytics import _expand_qs
from courses.views_analytics import _with_data_for
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
    titles = [row["title"] for row in _table_rows(soup)]
    assert titles == ["Whole course", "Mixed chapter", "Chapter quiz", "Unstarted quiz"]
    assert soup.select("ul.breakdown__tree") == []
    unstarted = _table_row(soup, "Unstarted quiz")
    assert unstarted["status"].select_one(".pill.pill--none") is not None


def test_t7_results_mode_hides_the_chapter_chip_progress_shows_it(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, results = _get(client, f"{path}?mode=results")
    _resp, progress = _get(client, f"{path}?mode=progress")
    assert results.select(".rollup") == []
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


def _row(soup, title):
    for row in soup.select(".breakdown-unit"):
        if row.select_one(".breakdown-unit__title").get_text(" ", strip=True) == title:
            return row
    raise AssertionError(f"no row titled {title!r}")


def test_t12_additional_tag_sits_between_title_and_marker(client, monkeypatch):
    monkeypatch.setitem(
        rollups.UNIT_MARKER_LABELS, rollups.MARKER_ADDITIONAL, "SENTINEL-ADDITIONAL"
    )
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, path)
    extra = _row(soup, "Extra lesson")
    classes = [
        " ".join(child.get("class", [])) for child in extra.find_all(recursive=False)
    ]
    assert classes == [
        "breakdown-unit__title",
        "badge breakdown-unit__tag",
        "badge badge--todo",
    ]
    assert extra.select_one(".breakdown-unit__tag").get_text(strip=True) == (
        "SENTINEL-ADDITIONAL"
    )
    assert _row(soup, "Lonely lesson").select_one(".breakdown-unit__tag") is None
    quiz = _row(soup, "Chapter quiz")
    assert quiz.select_one(".breakdown-unit__tag") is None
    assert quiz.select_one(".unit-kind-chip") is None


def test_t13_quiz_rows_carry_a_pill_lesson_rows_a_marker(client):
    _course, _student, _mixed, path = _page_fixture(client)
    _resp, soup = _get(client, path)
    quiz = _row(soup, "Chapter quiz")
    assert quiz.select_one(".pill") is not None
    assert quiz.select_one(".badge--done, .badge--todo") is None
    done = _row(soup, r"Required lesson \(x\)")
    assert done.select_one(".pill") is None
    assert done.select_one(".badge--done")["aria-label"] == "Completed"
    todo = _row(soup, "Lonely lesson")
    assert todo.select_one(".badge--done") is None
    assert todo.select_one(".badge--todo")["aria-label"] == "Not completed"


# --- results-table spec (2026-09-17): Results-mode sums ---------------------------
def _auto(quiz, max_marks):
    question = ShortTextQuestionElement.objects.create(
        stem="<p>Q</p>", accepted="a", max_marks=Decimal(max_marks)
    )
    return Element.objects.create(unit=quiz, content_object=question)


def _review(quiz, max_marks):
    question = ExtendedResponseQuestionElement.objects.create(
        stem="<p>E</p>",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(max_marks),
    )
    return Element.objects.create(unit=quiz, content_object=question)


def _sub(student, quiz, score, max_score):
    return QuizSubmission.objects.create(
        student=student,
        unit=quiz,
        status=QuizSubmission.Status.SUBMITTED,
        score=Decimal(score),
        max_score=Decimal(max_score),
    )


def _quiz(course, parent, title, **kw):
    return _node(course, parent, "unit", title, unit_type="quiz", **kw)


def _student_path(course, student):
    return reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": student.pk},
    )


def _results_fixture(client):
    """One student, three root chapters (spec §7 T1-T6):

    Rozdział A (d0)          2/7   12/15   80%
      Sekcja A1 (d1)         2/5   12/15   80%
        A1 oceniony          8/10 (AUTO)
        A1 sprawdzony        4/5  (REVIEW-only, fully reviewed: T1b)
        A1 do sprawdzenia    awaiting review, stored 3/5 -- never counted
        A1 w toku            in progress
        A1 nierozpoczęty     not started
      Lekcja A               a lesson: pruned
      Sekcja A2 (d1)         0/2   no counted quiz (T1c)
        A2 nierozpoczęty, A2 do sprawdzenia
    Rozdział B (d0)          1/2   16.5/22  75%
      B połowa               16.5/22
      B bez punktów          submitted, max_score 0 (T5)
    Rozdział C (d0)          one quiz: a percent, no summary (T2)
      Sekcja C1 (d1)
        C1 jedyny            3/4
    Whole course             4/10  31.5/41  77%
    """
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory(
        first_name="Anna", last_name="Nowak", display_name="Anna Nowak"
    )
    EnrollmentFactory(student=student, course=course)
    a = _node(course, None, "chapter", "Rozdział A")
    a1 = _node(course, a, "section", "Sekcja A1")
    marked = _quiz(course, a1, "A1 oceniony")
    _auto(marked, "10")
    _sub(student, marked, "8", "10")
    reviewed = _quiz(course, a1, "A1 sprawdzony")
    essay = _review(reviewed, "5")
    QuestionResponse.objects.create(
        submission=_sub(student, reviewed, "4", "5"),
        element=essay,
        latest_answer="esej",
        attempt_count=1,
        locked=True,
        earned_marks=Decimal("4"),
        fraction=Decimal("0.8"),
        reviewed_at=timezone.now(),
    )
    awaiting = _quiz(course, a1, "A1 do sprawdzenia")
    _review(awaiting, "5")
    _sub(student, awaiting, "3", "5")
    live = _quiz(course, a1, "A1 w toku")
    _auto(live, "5")
    QuizSubmission.objects.create(
        student=student, unit=live, status=QuizSubmission.Status.IN_PROGRESS
    )
    _auto(_quiz(course, a1, "A1 nierozpoczęty"), "5")
    _node(course, a, "unit", "Lekcja A", unit_type="lesson", obligatory=True)
    a2 = _node(course, a, "section", "Sekcja A2")
    _auto(_quiz(course, a2, "A2 nierozpoczęty"), "2")
    pending = _quiz(course, a2, "A2 do sprawdzenia")
    _review(pending, "2")
    _sub(student, pending, "0", "0")
    b = _node(course, None, "chapter", "Rozdział B")
    half = _quiz(course, b, "B połowa")
    _auto(half, "22")
    _sub(student, half, "16.5", "22")
    _sub(student, _quiz(course, b, "B bez punktów"), "0", "0")
    c = _node(course, None, "chapter", "Rozdział C")
    c1 = _node(course, c, "section", "Sekcja C1")
    single = _quiz(course, c1, "C1 jedyny")
    _auto(single, "4")
    _sub(student, single, "3", "4")
    return course, student, _student_path(course, student)


def _grid(course, student, expand=()):
    """The matrix exactly as analytics_matrix builds it in Results + raw mode."""
    return build_results_matrix(
        course,
        [student],
        {node.pk for node in expand},
        "raw",
        drafts="keep-with-data",
        with_data=_with_data_for(course),
    )


def _grid_cell(course, student, node, expand=()):
    matrix = _grid(course, student, expand)
    cells = matrix["rows"][0]["cells"]
    for column, cell in zip(matrix["columns"], cells, strict=True):
        if column["node"] == node:
            return cell
    raise AssertionError(f"no grid column for {node.title!r}")


def _label(d):
    return f"{_fmt_mark(d['score_sum'])}/{_fmt_mark(d['max_sum'])}"


def _results(client, path):
    resp, soup = _get(client, f"{path}?mode=results")
    return resp.context["breakdown"], soup


def _all_nodes(tree):
    for d in tree:
        yield d
        yield from _all_nodes(d["children"])


def test_rt_t1_results_summaries_equal_the_grid(client):
    course, student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    chapter_a = _find(tree, "Rozdział A")
    a1, a2 = _find(tree, "Sekcja A1"), _find(tree, "Sekcja A2")
    # Both branches below run: a summary heading with a counted quiz, one without.
    assert a1["summary"] and a1["counted"] > 0
    assert a2["summary"] and a2["counted"] == 0
    cases = (
        (chapter_a, ()),  # top-level
        (_find(tree, "Rozdział B"), ()),  # top-level
        # Nested: expand the ANCESTOR, never the section itself -- an expanded
        # node becomes a spanning header with no cell.
        (a1, (chapter_a["node"],)),
        (a2, (chapter_a["node"],)),
    )
    for d, ancestors in cases:
        title = d["node"].title
        cell = _grid_cell(course, student, d["node"], ancestors)
        if d["counted"] == 0:
            assert cell["percent"] is None and cell["label"] == "—", title
            assert d["percent"] is None, title
        else:
            assert d["percent"] == cell["percent"], title
            assert _label(d) == cell["label"], title


def test_rt_t1b_a_reviewed_review_only_quiz_is_scored_and_summed(client):
    course, student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    quiz = _find(tree, "A1 sprawdzony")
    got = (quiz["shows_score"], quiz["score"], quiz["max_score"], quiz["percent"])
    assert got == (True, Decimal("4"), Decimal("5"), 80)
    a1 = _find(tree, "Sekcja A1")
    assert _label(a1) == "12/15"
    ancestors = (_find(tree, "Rozdział A")["node"],)
    assert _grid_cell(course, student, a1["node"], ancestors)["label"] == "12/15"


def test_rt_t1c_a_summary_with_no_counted_quiz_has_no_percent(client):
    _course, _student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    a2 = _find(breakdown["tree"], "Sekcja A2")
    assert (a2["quiz_total"], a2["counted"], a2["summary"]) == (2, 0, True)
    assert (a2["score_sum"], a2["max_sum"], a2["percent"]) == (0, 0, None)
    assert isinstance(a2["score_sum"], Decimal)
    assert isinstance(a2["max_sum"], Decimal)


def _uncounted_course(client):
    """Two quizzes, neither started: the course total has no counted quiz."""
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = _node(course, None, "chapter", "Rozdział")
    _auto(_quiz(course, chapter, "Pierwszy"), "1")
    _auto(_quiz(course, chapter, "Drugi"), "1")
    return _student_path(course, student)


def test_rt_t1c_a_course_total_with_no_counted_quiz_has_no_percent(client):
    breakdown, _soup = _results(client, _uncounted_course(client))
    total = breakdown["total"]
    assert (total["quiz_total"], total["counted"], total["summary"]) == (2, 0, True)
    assert (total["score_sum"], total["max_sum"], total["percent"]) == (0, 0, None)
    assert isinstance(total["score_sum"], Decimal)


def test_rt_t2_a_one_quiz_section_has_a_percent_but_no_summary(client):
    _course, _student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    for title in ("Sekcja C1", "Rozdział C"):
        d = _find(breakdown["tree"], title)
        assert (d["quiz_total"], d["percent"], d["summary"]) == (1, 75, False), title


def test_rt_t3_course_total_equals_the_grids_overall(client):
    course, student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    total = breakdown["total"]
    overall = _grid(course, student)["rows"][0]["overall"]
    assert (total["quiz_total"], total["counted"], total["summary"]) == (10, 4, True)
    assert total["percent"] == overall["percent"]
    assert _label(total) == overall["label"]


def _one_quiz_course(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    quiz = _quiz(course, _node(course, None, "chapter", "Rozdział"), "Jedyny")
    _auto(quiz, "2")
    _sub(student, quiz, "1", "2")
    return _student_path(course, student)


def test_rt_t3_a_one_quiz_course_has_no_total_summary(client):
    breakdown, _soup = _results(client, _one_quiz_course(client))
    assert breakdown["total"]["quiz_total"] == 1
    assert breakdown["total"]["summary"] is False


def _drafts_fixture(client):
    """Spec T4. Data is COURSE-wide (_with_data_for): 'Szkic bez danych' has none
    from any student; 'Szkic cudzy' has data from ANOTHER student only."""
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student, other = UserFactory(), UserFactory()
    for pupil in (student, other):
        EnrollmentFactory(student=pupil, course=course)
    chapter = _node(course, None, "chapter", "Rozdział")
    live = _quiz(course, chapter, "Opublikowany")
    _auto(live, "4")
    _sub(student, live, "2", "4")
    kept = _quiz(course, chapter, "Szkic z danymi", published=False)
    _auto(kept, "4")
    _sub(student, kept, "3", "4")
    _auto(_quiz(course, chapter, "Szkic bez danych", published=False), "4")
    theirs = _quiz(course, chapter, "Szkic cudzy", published=False)
    _auto(theirs, "4")
    _sub(other, theirs, "4", "4")
    return course, student, chapter, _student_path(course, student)


def test_rt_t4_drafts_are_the_grids_drafts(client):
    course, student, chapter, path = _drafts_fixture(client)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    heading = _find(tree, "Rozdział")
    # A draft WITH data counts on both pages: its 3/4 is inside 5/8.
    cell = _grid_cell(course, student, chapter)
    assert heading["percent"] == cell["percent"]
    assert _label(heading) == cell["label"] == "5/8"
    # R-a: assert the denominator BEFORE the absence check, so the spec's
    # drafts="keep" mutant goes red here, not one line earlier.
    assert heading["quiz_total"] == 3
    # A draft with no data from ANY student has no row and no share of quiz_total.
    assert _find(tree, "Szkic bez danych") is None
    # A draft only ANOTHER student attempted is on this page, not started.
    assert _find(tree, "Szkic cudzy")["pill"] == {"kind": "not_started"}


def test_rt_t5_a_zero_max_quiz_is_in_quiz_total_not_in_counted(client):
    _course, _student, path = _results_fixture(client)
    breakdown, _soup = _results(client, path)
    b = _find(breakdown["tree"], "Rozdział B")
    assert (b["quiz_total"], b["counted"]) == (2, 1)
    assert _find(breakdown["tree"], "B bez punktów")["shows_score"] is False


RESULTS_ONLY_KEYS = frozenset(
    {
        "quiz_total",
        "counted",
        "score_sum",
        "max_sum",
        "percent",
        "summary",
        "shows_score",
        "score",
        "max_score",
        "color",
        "text_color",
    }
)


def test_rt_t7_progress_mode_carries_no_results_keys(client):
    """Each node dict's OWN top-level keys, walked through `children` only -- never
    inside `pill`: a scored Progress pill legitimately carries `percent`."""
    _course, _student, path = _results_fixture(client)
    resp, _soup = _get(client, f"{path}?mode=progress")
    breakdown = resp.context["breakdown"]
    assert "total" not in breakdown
    nodes = list(_all_nodes(breakdown["tree"]))
    assert any((d.get("pill") or {}).get("kind") == "scored" for d in nodes)
    for d in nodes:
        leaked = sorted(RESULTS_ONLY_KEYS & set(d))
        assert not leaked, (d["node"].title, leaked)


def test_rt_invariant_a_quiz_without_a_row_raises(monkeypatch):
    """Spec §2.1: the pruned tree's quiz nodes ARE build_course_results's rows, so a
    missing row is a bug and must raise, never render an unscored quiz."""
    course = CourseFactory()
    _quiz(course, _node(course, None, "chapter", "Rozdział"), "Quiz")
    real = rollups.build_course_results

    def without_rows(*args, **kwargs):
        results = real(*args, **kwargs)
        results["rows"] = []
        return results

    monkeypatch.setattr(rollups, "build_course_results", without_rows)
    with pytest.raises(KeyError):
        build_student_breakdown(course, UserFactory(), drafts="keep", mode="results")


# Custom bands: with the defaults, a hard-coded palette would pass (spec T6).
CUSTOM_BANDS = [
    {"key": "none", "min": 0, "color": "#101010"},
    {"key": "weak", "min": 40, "color": "#202020"},
    {"key": "ok", "min": 60, "color": "#303030"},
    {"key": "good", "min": 75, "color": "#404040"},
    {"key": "excellent", "min": 90, "color": "#f0f0f0"},
]


def _custom_bands(course):
    course.color_bands = CUSTOM_BANDS
    course.save(update_fields=["color_bands"])
    return course_color_bands(course)


def test_rt_t6_results_nodes_carry_the_course_band_colours(client):
    course, _student, path = _results_fixture(client)
    bands = _custom_bands(course)
    breakdown, _soup = _results(client, path)
    tree = breakdown["tree"]
    for title in ("Rozdział A", "A1 oceniony"):  # a container AND a quiz, both 80%
        d = _find(tree, title)
        style = band_style(d["percent"], bands)
        assert (d["color"], d["text_color"]) == (style["bg"], style["fg"]), title
        assert d["color"] == "#404040", title  # precondition: a CUSTOM band
    total = breakdown["total"]
    assert total["color"] == band_style(total["percent"], bands)["bg"]
    # Every node is painted, whatever it renders; a None percent paints nothing.
    for title in ("Sekcja A2", "A1 w toku"):
        d = _find(tree, title)
        assert (d["color"], d["text_color"]) == (None, None), title


# --- results-table spec: the rendered table ----------------------------------------
def _table_rows(soup):
    rows = []
    for tr in soup.select("table.results-table tbody tr"):
        status, score, pct = tr.select("td")
        th = tr.select_one("th")
        rows.append(
            {
                "tr": tr,
                "th": th,
                "title": th.get_text(" ", strip=True),
                "status": status,
                "score": score,
                "pct": pct,
            }
        )
    return rows


def _table_row(soup, title):
    for row in _table_rows(soup):
        if row["title"] == title:
            return row
    raise AssertionError(f"no Results-table row titled {title!r}")


def _cells(row):
    return [row[key].get_text(" ", strip=True) for key in ("status", "score", "pct")]


def test_rt_t1b_a_reviewed_review_only_row_shows_its_score(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    row = _table_row(soup, "A1 sprawdzony")
    assert _cells(row) == ["", "4/5", "80%"]
    assert row["status"].select(".pill") == []


def test_rt_t1c_an_uncounted_summary_renders_a_count_and_no_figures(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    row = _table_row(soup, "Sekcja A2")
    assert _cells(row) == ["0/2", "", ""]
    assert row["pct"].get("style") is None


def test_rt_t1c_an_uncounted_course_total_renders_a_count_and_no_figures(client):
    _resp, soup = _get(client, f"{_uncounted_course(client)}?mode=results")
    total = _table_rows(soup)[0]
    assert total["title"] == "Whole course"
    assert _cells(total) == ["0/2", "", ""]
    assert total["pct"].get("style") is None


def test_rt_t2_one_quiz_headings_render_no_figures(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    for title in ("Sekcja C1", "Rozdział C"):  # each has a percent (75), no summary
        row = _table_row(soup, title)
        assert "results-table__section" in row["tr"]["class"], title
        assert _cells(row) == ["", "", ""], title
        assert row["pct"].get("style") is None, title


def test_rt_t3_the_total_row_comes_first(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    first = _table_rows(soup)[0]
    assert first["title"] == "Whole course"
    assert first["tr"]["class"] == ["results-table__section", "results-table__total"]
    assert _cells(first) == ["4/10", "31.5/41", "77%"]
    assert len(soup.select("tr.results-table__total")) == 1


def test_rt_t3_a_one_quiz_course_renders_no_total_row(client):
    _resp, soup = _get(client, f"{_one_quiz_course(client)}?mode=results")
    assert soup.select("tr.results-table__total") == []
    assert _table_rows(soup)[0]["title"] == "Rozdział"


def test_rt_t4_another_students_draft_renders_not_started(client):
    _course, _student, _chapter, path = _drafts_fixture(client)
    _polish(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    status = _table_row(soup, "Szkic cudzy")["status"]
    assert status.select_one(".pill--none").get_text(strip=True) == "nie rozpoczęto"


def test_rt_t5_a_zero_max_quiz_counts_in_the_denominator_only(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    assert _cells(_table_row(soup, "Rozdział B"))[0] == "1/2"
    assert _table_row(soup, "B bez punktów")["status"].select_one(".pill--submitted")


def test_rt_t5b_polish_cells_read_exactly(client):
    _course, _student, path = _results_fixture(client)
    _polish(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    total = _table_rows(soup)[0]
    assert total["title"] == "Cały kurs"
    assert _cells(total) == ["4/10", "31,5/41", "77%"]
    assert _cells(_table_row(soup, "Rozdział B")) == ["1/2", "16,5/22", "75%"]
    assert _cells(_table_row(soup, "B połowa")) == ["", "16,5/22", "75%"]


def _parts_course(client, with_parts):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    if with_parts:
        part = _node(course, None, "part", "Część 1")
        chapter = _node(course, part, "chapter", "Rozdział 1")
        section = _node(course, chapter, "section", "Sekcja 1")
        _quiz(course, section, "Q1")
        _quiz(course, section, "Q2")
        _quiz(course, chapter, "Q3")
        _quiz(course, _node(course, None, "part", "Część 2"), "Q4")
        expected = [
            ("Whole course", 0),
            ("Część 1", 0),
            ("Rozdział 1", 1),
            ("Sekcja 1", 2),
            ("Q1", 3),
            ("Q2", 3),
            ("Q3", 2),
            ("Część 2", 0),
            ("Q4", 1),
        ]
    else:
        chapter = _node(course, None, "chapter", "Rozdział bez części")
        section = _node(course, chapter, "section", "Sekcja")
        _quiz(course, section, "Q1")
        _quiz(course, section, "Q2")
        _quiz(course, chapter, "Q3")
        expected = [
            ("Whole course", 0),
            ("Rozdział bez części", 0),
            ("Sekcja", 1),
            ("Q1", 2),
            ("Q2", 2),
            ("Q3", 1),
        ]
    return _student_path(course, student), expected


@pytest.mark.parametrize("with_parts", [True, False])
def test_rt_t5c_rows_are_preorder_with_their_depth_class(client, with_parts):
    path, expected = _parts_course(client, with_parts)
    _resp, soup = _get(client, f"{path}?mode=results")
    got = [
        (
            row["title"],
            [c for c in row["th"]["class"] if c.startswith("results-table__d")],
        )
        for row in _table_rows(soup)
    ]
    assert got == [(title, [f"results-table__d{depth}"]) for title, depth in expected]


def test_rt_t5e_status_cells_show_the_pill_for_their_status(client):
    course, student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=results")
    for title, kind in (
        ("A1 nierozpoczęty", "pill--none"),
        ("A1 w toku", "pill--progress"),
        ("A1 do sprawdzenia", "pill--awaiting"),
    ):
        pills = _table_row(soup, title)["status"].select(".pill")
        assert len(pills) == 1 and kind in pills[0]["class"], title
    awaiting = QuizSubmission.objects.get(
        student=student, unit__course=course, unit__title="A1 do sprawdzenia"
    )
    review = _table_row(soup, "A1 do sprawdzenia")["status"].select_one(
        "a.breakdown-unit__review"
    )
    assert review["href"] == reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": awaiting.pk},
    )
    assert _table_row(soup, "A1 oceniony")["status"].select(".pill") == []


def test_rt_t6_percent_cells_carry_the_band_inline(client):
    course, _student, path = _results_fixture(client)
    bands = _custom_bands(course)
    _resp, soup = _get(client, f"{path}?mode=results")
    for title in ("Rozdział A", "A1 oceniony"):  # a heading AND a quiz row, both 80%
        style = band_style(80, bands)
        expected = f"background:{style['bg']};color:{style['fg']}"
        assert _table_row(soup, title)["pct"].get("style") == expected, title


def test_rt_t7_progress_renders_the_tree_not_the_table(client):
    _course, _student, path = _results_fixture(client)
    _resp, soup = _get(client, f"{path}?mode=progress")
    assert soup.select('[class*="results-table"]') == []
    assert soup.select_one("ul.breakdown__tree") is not None
    assert soup.select(
        "ul.breakdown__tree .badge--done, ul.breakdown__tree .badge--todo"
    )


def test_rt_t7b_a_course_without_quizzes_says_so(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    chapter = _node(course, None, "chapter", "Rozdział")
    _node(course, chapter, "unit", "Lekcja", unit_type="lesson", obligatory=True)
    _polish(client)
    _resp, soup = _get(client, f"{_student_path(course, student)}?mode=results")
    assert soup.select("table.results-table") == []
    empty = soup.select_one("p.results-table-empty")
    assert empty.get_text(strip=True) == "Ten kurs nie ma jeszcze quizów"


@pytest.mark.parametrize(
    ("title", "has_math"),
    [(r"Quiz \(x^2\)", True), ("Quiz bez wzorów", False)],
    ids=["maths", "plain"],
)
def test_rt_t8d_scroll_wrapper_is_a_region_only_with_maths(client, title, has_math):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    student = UserFactory()
    EnrollmentFactory(student=student, course=course)
    _quiz(course, _node(course, None, "chapter", "Rozdział"), title)
    resp, soup = _get(client, f"{_student_path(course, student)}?mode=results")
    assert resp.context["has_math"] is has_math
    wrap = soup.select_one("div.results-table-wrap")
    caption = soup.select_one("table.results-table > caption")
    if has_math:
        assert wrap.get("role") == "region"
        assert wrap.get("tabindex") == "0"
        assert caption.get("id")
        assert wrap.get("aria-labelledby") == caption.get("id")
    else:
        for attr in ("role", "tabindex", "aria-labelledby"):
            assert wrap.get(attr) is None, attr


def test_rt_t9_heading_and_title_name_the_view(client):
    _course, _student, _mixed, path = _page_fixture(client)  # student: Anna Nowak
    _polish(client)
    for mode, word in (("results", "Wyniki"), ("progress", "Postęp")):
        _resp, soup = _get(client, f"{path}?mode={mode}")
        h1 = soup.select_one("h1").get_text(" ", strip=True)
        title = soup.select_one("title").get_text(strip=True)
        assert h1 == f"{word} — Anna Nowak", mode
        assert title.startswith(f"{word} · "), mode
        assert "Nowak" not in title, mode  # the <title> never names the student
        assert "ucznia" not in h1 and "ucznia" not in title, mode
        current = soup.select_one('.breakdown__view a[aria-current="page"]')
        assert current.get_text(strip=True) == word
