"""Task 8: analytics/gradebook/review keep a draft unit that HOLDS DATA (a
draft pulled back for a typo fix must not blank a mid-term gradebook column)
and drop draft containers that never went live — across all FIVE call chains:
analytics matrices, student breakdown, gradebook export, and the review queue.
"""

import pytest

from courses.gradebook import build_quiz_gradebook
from courses.review import pending_reviews_for
from courses.rollups import build_outline
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from courses.rollups import build_student_breakdown
from courses.rollups import frontier_columns
from courses.views_analytics import _with_data_for
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory
from tests.factories import make_login


def _chapter(course, **kw):
    kw.setdefault("unit_type", None)
    return ContentNodeFactory(course=course, kind="chapter", parent=None, **kw)


def _lesson(course, parent, obligatory=True, **kw):
    return ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=parent,
        obligatory=obligatory,
        **kw,
    )


def _quiz(course, parent, **kw):
    return ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=parent, **kw
    )


@pytest.mark.django_db
def test_ana1_draft_quiz_keeps_gradebook_column_only_when_it_holds_data():
    """A draft quiz with an INTERRUPTED (IN_PROGRESS) attempt keeps its column —
    has_submissions takes ANY status, not just SUBMITTED. The "no data" quiz has
    literally zero QuizSubmission rows, not merely no submitted one."""
    course = CourseFactory()
    ch = _chapter(course)
    interrupted = _quiz(course, ch, title="Interrupted", published=False)
    untouched = _quiz(course, ch, title="Untouched", published=False)
    s = UserFactory()
    QuizSubmissionFactory(student=s, unit=interrupted, status="in_progress")
    # untouched: zero QuizSubmission rows at all.

    with_data = _with_data_for(course)
    assert interrupted.pk in with_data
    assert untouched.pk not in with_data

    table = build_quiz_gradebook(
        course, [s], numbers_only=False, drafts="keep-with-data", with_data=with_data
    )
    labels = [c["label"] for c in table["columns"]]
    assert any("Interrupted" in label for label in labels)
    assert all("Untouched" not in label for label in labels)


@pytest.mark.django_db
def test_ana2_draft_lesson_with_unit_progress_keeps_its_column():
    """Mutant: implement "holds data" as the QuizSubmission check alone — a
    draft LESSON's UnitProgress row must also keep the column."""
    course = CourseFactory()
    ch = _chapter(course, title="DraftLessonChapter")
    lesson = _lesson(course, ch, published=False)
    s = UserFactory()
    UnitProgressFactory(student=s, unit=lesson, completed=False)

    with_data = _with_data_for(course)
    assert lesson.pk in with_data

    m = build_progress_matrix(course, [s], drafts="keep-with-data", with_data=with_data)
    titles = [c["title"] for c in m["columns"]]
    assert "DraftLessonChapter" in titles


@pytest.mark.django_db
def test_ana3_matrices_and_drill_down_filtered_through_the_view(client):
    """views_analytics calls the MATRIX BUILDERS, never frontier_columns directly.
    Mutant: filter build_matrix_columns (zero production callers) instead of the
    real chain -> both the flat matrix and every expansion stay unfiltered."""
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    outer = _chapter(course, title="Outer")
    inner_data = _quiz(course, outer, title="InnerData", published=False)
    _inner_empty = _quiz(course, outer, title="InnerEmpty", published=False)
    s = UserFactory()
    EnrollmentFactory(student=s, course=course)
    QuizSubmissionFactory(student=s, unit=inner_data, status="in_progress")

    resp = client.get(f"/manage/courses/{course.slug}/analytics/?mode=results")
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.context["matrix"]["columns"]]
    assert "Outer" in titles  # holds data via inner_data -> not dropped

    resp2 = client.get(
        f"/manage/courses/{course.slug}/analytics/?mode=results&expand={outer.pk}"
    )
    assert resp2.status_code == 200
    titles2 = [c["title"] for c in resp2.context["matrix"]["columns"]]
    assert "InnerData" in titles2
    assert "InnerEmpty" not in titles2


@pytest.mark.django_db
def test_ana4_lesson_pks_denominator_matches_displayed_columns():
    """Filter lesson_pks/quiz_pks by the same rule, or the matrix divides by
    units it does not display."""
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    published_lesson = _lesson(course, ch, published=True)
    _lesson(course, ch, published=False)  # draft, no data -> must not count
    s = UserFactory()
    UnitProgressFactory(student=s, unit=published_lesson, completed=True)

    with_data = _with_data_for(course)
    fc = frontier_columns(
        course, frozenset(), drafts="keep-with-data", with_data=with_data
    )
    assert fc["columns"][0]["lesson_pks"] == {published_lesson.pk}

    m = build_progress_matrix(course, [s], drafts="keep-with-data", with_data=with_data)
    # 1/1, not 1/2 -- the draft, dataless lesson must not inflate the denominator.
    assert m["rows"][0]["cells"][0]["percent"] == 100


@pytest.mark.django_db
def test_ana5_gradebook_and_review_queue_drop_never_published_quizzes():
    """Proves quiz_units_in_order carries the keyword on BOTH surfaces the
    plan calls out as easy to miss: build_quiz_gradebook and pending_reviews_for."""
    owner = UserFactory()
    course = CourseFactory(owner=owner)
    ch = _chapter(course)
    live = _quiz(course, ch, title="Live")
    _draft = _quiz(course, ch, title="Draft", published=False)  # never published
    s = UserFactory()
    EnrollmentFactory(student=s, course=course)
    QuizSubmissionFactory(student=s, unit=live, status="in_progress")

    with_data = _with_data_for(course)
    assert _draft.pk not in with_data

    table = build_quiz_gradebook(
        course, [s], numbers_only=False, drafts="keep-with-data", with_data=with_data
    )
    labels = [c["label"] for c in table["columns"]]
    assert any("Live" in label for label in labels)
    assert all("Draft" not in label for label in labels)

    data = pending_reviews_for(
        owner, course, drafts="keep-with-data", with_data=with_data
    )
    assert [sub.unit_id for sub in data["in_progress"]] == [live.pk]


@pytest.mark.django_db
def test_ana6_container_drop_rule_and_header_alignment():
    course = CourseFactory()
    all_draft = _chapter(course, title="AllDraft")
    _lesson(course, all_draft, published=False)
    _quiz(course, all_draft, published=False)

    optional_only = _chapter(course, title="OptionalOnly")
    _lesson(course, optional_only, obligatory=False, published=True)

    empty_ch = _chapter(course, title="Empty")  # no units at all

    to_expand = _chapter(course, title="ToExpand")
    _lesson(course, to_expand, published=False)
    _quiz(course, to_expand, published=False)

    with_data = frozenset()

    # (a), (b), (d) + alignment: collapsed frontier.
    fc = frontier_columns(
        course, frozenset(), drafts="keep-with-data", with_data=with_data
    )
    titles = [c["title"] for c in fc["columns"]]
    assert "AllDraft" not in titles  # (a)
    assert "OptionalOnly" in titles  # (b)
    assert "Empty" in titles  # (d), partial (see the mode loop below)
    assert len(fc["header_rows"][-1]) == len(fc["columns"])  # alignment
    header_titles = [c["title"] for row in fc["header_rows"] for c in row]
    assert "AllDraft" not in header_titles

    # (c): expanding an all-draft chapter drops it -- it never becomes a
    # spanning header cell, and is absent from expanded_nodes.
    fc_expanded = frontier_columns(
        course, {to_expand.pk}, drafts="keep-with-data", with_data=with_data
    )
    assert "ToExpand" not in [c["title"] for c in fc_expanded["columns"]]
    assert to_expand.pk not in [e["pk"] for e in fc_expanded["expanded_nodes"]]

    # (d): a childless container keeps its column in ALL THREE modes.
    for drafts_mode, wd in (("hide", None), ("keep", None), ("keep-with-data", set())):
        fc_mode = frontier_columns(
            course, frozenset(), drafts=drafts_mode, with_data=wd
        )
        assert "Empty" in [c["title"] for c in fc_mode["columns"]]
    assert empty_ch  # fixture used


@pytest.mark.django_db
def test_out7_teacher_breakdown_keeps_draft_with_data_students_own_view_hides_it():
    """build_student_breakdown keeps a draft unit that holds data even though
    its `user` argument IS the student being reviewed -- with_data is the
    COURSE-WIDE frozenset the teacher's request built, not this student's own
    data. Pin BOTH denominators: the teacher's (keeps the draft) and the
    student's own outline (drops it) deliberately diverge."""
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    _lesson(course, ch, published=True)
    draft_lesson = _lesson(course, ch, published=False)
    student = UserFactory()
    other_student = UserFactory()
    # Someone else's data keeps the draft lesson alive course-wide.
    UnitProgressFactory(student=other_student, unit=draft_lesson, completed=True)

    with_data = _with_data_for(course)
    assert draft_lesson.pk in with_data

    bd = build_student_breakdown(
        course, student, drafts="keep-with-data", with_data=with_data
    )
    teacher_total = sum(r["required_total"] for r in bd["tree"])
    assert teacher_total == 2  # both lessons counted: someone holds data on it

    student_own_outline = build_outline(course, student, drafts="hide")
    student_total = sum(r["required_total"] for r in student_own_outline)
    assert student_total == 1  # the student's own page never sees with_data

    assert teacher_total != student_total  # the deliberate divergence, pinned
