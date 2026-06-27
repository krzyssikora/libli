# tests/test_analytics_rollups.py
from decimal import Decimal

import pytest

from courses.models import Element
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rollups import build_matrix_columns
from courses.rollups import build_progress_matrix
from courses.rollups import build_results_matrix
from courses.rollups import frontier_columns
from courses.rollups import is_obligatory_lesson
from courses.rollups import is_quiz_unit
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import UnitProgressFactory
from tests.factories import UserFactory


def _chapter(course, **kw):
    # unit_type=None: chapters carry no unit_type (the test_courses_rollups
    # convention; ContentNodeFactory defaults unit_type="lesson").
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


def _section(course, parent, **kw):
    kw.setdefault("unit_type", None)
    return ContentNodeFactory(course=course, kind="section", parent=parent, **kw)


@pytest.mark.django_db
def test_predicates():
    course = CourseFactory()
    ch = _chapter(course)
    les = _lesson(course, ch)
    qz = _quiz(course, ch)
    assert is_obligatory_lesson(les) and not is_quiz_unit(les)
    assert is_quiz_unit(qz) and not is_obligatory_lesson(qz)
    assert not is_obligatory_lesson(_lesson(course, ch, obligatory=False))


@pytest.mark.django_db
def test_build_matrix_columns_partition():
    course = CourseFactory()
    ch1, ch2 = _chapter(course), _chapter(course)
    l1 = _lesson(course, ch1)
    q1 = _quiz(course, ch1)
    l2 = _lesson(course, ch2)
    cols = build_matrix_columns(course)
    assert [c["node"].pk for c in cols] == [ch1.pk, ch2.pk]
    assert cols[0]["lesson_pks"] == {l1.pk} and cols[0]["quiz_pks"] == {q1.pk}
    assert cols[1]["lesson_pks"] == {l2.pk} and cols[1]["quiz_pks"] == set()


@pytest.mark.django_db
def test_progress_matrix_cells_overall_and_average():
    course = CourseFactory()
    ch = _chapter(course)
    l1 = _lesson(course, ch)
    _lesson(course, ch)  # second obligatory lesson → denominator = 2
    s1, s2 = UserFactory(), UserFactory()
    UnitProgressFactory(student=s1, unit=l1, completed=True)  # s1: 1/2 -> 50%
    # s2: 0/2 -> 0%  (defined, NOT None)
    m = build_progress_matrix(course, [s1, s2])
    assert m["mode"] == "progress"
    assert m["rows"][0]["cells"][0]["percent"] == 50
    assert m["rows"][0]["cells"][0]["label"] == "50%"
    assert m["rows"][1]["cells"][0]["percent"] == 0  # attempted-denominator, not None
    assert m["rows"][0]["overall"]["percent"] == 50
    # average of [50, 0] = 25
    assert m["averages"][0]["percent"] == 25
    assert m["overall_average"]["percent"] == 25


@pytest.mark.django_db
def test_progress_column_with_no_obligatory_lessons_is_none():
    course = CourseFactory()
    ch = _chapter(course)
    _quiz(course, ch)  # all-quiz chapter -> no obligatory lessons
    s1 = UserFactory()
    m = build_progress_matrix(course, [s1])
    assert m["rows"][0]["cells"][0]["percent"] is None
    assert m["rows"][0]["cells"][0]["label"] == "—"
    assert m["averages"][0]["percent"] is None  # mean of zero defined cells


@pytest.mark.django_db
def test_progress_overall_parity_with_build_outline():
    from courses.rollups import build_outline

    course = CourseFactory()
    ch = _chapter(course)
    l1, l2 = _lesson(course, ch), _lesson(course, ch)
    _lesson(course, ch)  # third lesson → denominator = 3
    s1 = UserFactory()
    UnitProgressFactory(student=s1, unit=l1, completed=True)
    UnitProgressFactory(student=s1, unit=l2, completed=True)  # 2/3
    m = build_progress_matrix(course, [s1])
    tree = build_outline(course, s1)
    done = sum(d["required_done"] for d in tree)
    total = sum(d["required_total"] for d in tree)
    assert m["rows"][0]["overall"]["percent"] == int(round(Decimal(100) * done / total))


@pytest.mark.django_db
def test_progress_matrix_query_count_size_independent():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course = CourseFactory()
    ch = _chapter(course)
    _lesson(course, ch)

    def add_students(n):
        return [UserFactory() for _ in range(n)]

    s = add_students(3)
    build_progress_matrix(course, s)  # warm caches
    with CaptureQueriesContext(connection) as c1:
        build_progress_matrix(course, s)
    s2 = s + add_students(20)
    with CaptureQueriesContext(connection) as c2:
        build_progress_matrix(course, s2)
    assert len(c1) == len(c2)


def _auto_q(unit, marks="1"):
    from courses.models import QuestionElement

    q = ShortTextQuestionElement.objects.create(
        stem="q",
        accepted="a",
        marking_mode=QuestionElement.MarkingMode.AUTO,
        max_marks=Decimal(marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


def _review_q(unit, marks="10"):
    from courses.models import QuestionElement

    q = ShortTextQuestionElement.objects.create(
        stem="q",
        accepted="a",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal(marks),
    )
    return Element.objects.create(unit=unit, content_object=q)


@pytest.mark.django_db
def test_results_matrix_counts_submitted_not_started_and_in_progress():
    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "10")
    s1, s2, s3 = UserFactory(), UserFactory(), UserFactory()
    QuizSubmission.objects.create(
        student=s1,
        unit=qz,
        status="submitted",
        score=Decimal("8.00"),
        max_score=Decimal("10.00"),
    )
    QuizSubmission.objects.create(
        student=s2,
        unit=qz,
        status="in_progress",
        score=Decimal("0.00"),
        max_score=Decimal("0.00"),
    )
    # s3: no submission (not started)
    m = build_results_matrix(course, [s1, s2, s3])
    assert m["mode"] == "results"
    assert m["rows"][0]["cells"][0]["percent"] == 80  # s1 counted
    assert m["rows"][1]["cells"][0]["percent"] is None  # s2 in_progress -> neutral
    assert m["rows"][2]["cells"][0]["percent"] is None  # s3 not started -> neutral
    # average over defined cells only ([80]) = 80
    assert m["averages"][0]["percent"] == 80


@pytest.mark.django_db
def test_results_matrix_excludes_awaiting_review_until_reviewed():
    """A SUBMITTED quiz with an unreviewed [R] is excluded (neutral) until the
    [R] is reviewed — exercises submission_is_counted's pending branch (spec §3)."""
    from django.utils import timezone

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    el = _review_q(qz, "10")  # one [R] question
    s1 = UserFactory()
    sub = QuizSubmission.objects.create(
        student=s1,
        unit=qz,
        status="submitted",
        score=Decimal("7.00"),
        max_score=Decimal("10.00"),
    )
    resp = QuestionResponse.objects.create(submission=sub, element=el, locked=True)
    # unreviewed [R] -> awaiting review -> excluded from the ratio (neutral)
    m = build_results_matrix(course, [s1])
    assert m["rows"][0]["cells"][0]["percent"] is None
    # once reviewed -> counted (reads the frozen score/max)
    resp.reviewed_at = timezone.now()
    resp.earned_marks = Decimal("7.00")
    resp.save()
    m2 = build_results_matrix(course, [s1])
    assert m2["rows"][0]["cells"][0]["percent"] == 70


@pytest.mark.django_db
def test_results_overall_parity_with_build_course_results():
    from courses.rollups import build_course_results

    course = CourseFactory()
    ch = _chapter(course)
    q1, q2 = _quiz(course, ch), _quiz(course, ch)
    _auto_q(q1, "10")
    _auto_q(q2, "10")
    s1 = UserFactory()
    QuizSubmission.objects.create(
        student=s1,
        unit=q1,
        status="submitted",
        score=Decimal("5.00"),
        max_score=Decimal("10.00"),
    )
    QuizSubmission.objects.create(
        student=s1,
        unit=q2,
        status="submitted",
        score=Decimal("9.00"),
        max_score=Decimal("10.00"),
    )
    m = build_results_matrix(course, [s1])
    assert (
        m["rows"][0]["overall"]["percent"]
        == build_course_results(course, s1)["percent"]
    )


@pytest.mark.django_db
def test_results_matrix_query_count_size_independent():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course = CourseFactory()
    ch = _chapter(course)
    qz = _quiz(course, ch)
    _auto_q(qz, "10")

    def students(n):
        out = []
        for _ in range(n):
            u = UserFactory()
            QuizSubmission.objects.create(
                student=u,
                unit=qz,
                status="submitted",
                score=Decimal("8.00"),
                max_score=Decimal("10.00"),
            )
            out.append(u)
        return out

    s = students(3)
    build_results_matrix(course, s)  # warm ContentType cache
    with CaptureQueriesContext(connection) as c1:
        build_results_matrix(course, s)
    s2 = s + students(20)
    with CaptureQueriesContext(connection) as c2:
        build_results_matrix(course, s2)
    assert len(c1) == len(c2)


@pytest.mark.django_db
def test_frontier_empty_matches_build_matrix_columns():
    course = CourseFactory()
    ch1, _ch2 = _chapter(course, title="A"), _chapter(course, title="B")
    l1 = _lesson(course, ch1)
    fc = frontier_columns(course, set())
    base = build_matrix_columns(course)
    assert [c["node"].pk for c in fc["columns"]] == [c["node"].pk for c in base]
    assert fc["columns"][0]["lesson_pks"] == {l1.pk}
    assert fc["columns"][0]["title"] == "A"  # root title, no breadcrumb prefix
    assert fc["expanded_nodes"] == []
    assert fc["columns"][0]["expandable"] is True  # has the lesson child
    assert fc["columns"][1]["expandable"] is False  # _ch2 has no children


@pytest.mark.django_db
def test_frontier_expand_chapter_replaces_with_children():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    _sec = _section(course, ch, title="Sec")
    _other = _lesson(course, ch, title="Loose")
    fc = frontier_columns(course, {ch.pk})
    # ch is gone as a column; its children (_sec, _other) take its place, in order
    titles = [c["title"] for c in fc["columns"]]
    assert titles == ["Ch ▸ Sec", "Ch ▸ Loose"]
    assert [e["pk"] for e in fc["expanded_nodes"]] == [ch.pk]
    assert fc["expanded_nodes"][0]["title"] == "Ch"


@pytest.mark.django_db
def test_frontier_recursive_expand():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    _leaf = _lesson(course, sec, title="U")
    fc = frontier_columns(course, {ch.pk, sec.pk})
    assert [c["title"] for c in fc["columns"]] == ["Ch ▸ Sec ▸ U"]
    assert [e["pk"] for e in fc["expanded_nodes"]] == [ch.pk, sec.pk]


@pytest.mark.django_db
def test_frontier_stale_descendant_pk_is_inert():
    """Sec's pk lingers but Ch is collapsed -> Sec is never reached; no stale chip."""
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    _lesson(course, sec)
    fc = frontier_columns(course, {sec.pk})  # parent ch NOT expanded
    assert [c["node"].pk for c in fc["columns"]] == [ch.pk]  # ch is the column
    assert fc["expanded_nodes"] == []  # sec not reached -> no chip


@pytest.mark.django_db
def test_frontier_ignores_unknown_and_leaf_pks():
    course = CourseFactory()
    ch = _chapter(course)
    leaf = _lesson(course, ch)
    # leaf has no children; 999999 unknown
    fc = frontier_columns(course, {leaf.pk, 999999})
    assert [c["node"].pk for c in fc["columns"]] == [ch.pk]
    assert fc["expanded_nodes"] == []


@pytest.mark.django_db
def test_progress_partition_invariant_under_expansion():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    l1 = _lesson(course, sec)
    l2 = _lesson(course, ch)  # sibling of sec
    s = UserFactory()
    UnitProgressFactory(student=s, unit=l1, completed=True)  # 1 of 2 obligatory
    flat = build_progress_matrix(course, [s])
    expanded = build_progress_matrix(course, [s], {ch.pk})
    # expanding regroups, never changes the student's overall
    assert (
        flat["rows"][0]["overall"]["percent"]
        == expanded["rows"][0]["overall"]["percent"]
    )
    # the chapter is gone as a column; its children are columns now
    assert expanded["expanded_nodes"][0]["pk"] == ch.pk
    assert expanded["columns"][0]["expandable"] is True  # sec still expandable
    # expansion actually regrouped: ch's two children (sec, l2) are now the columns
    assert [c["node"].pk for c in expanded["columns"]] == [sec.pk, l2.pk]


@pytest.mark.django_db
def test_results_partition_invariant_under_expansion():
    course = CourseFactory()
    ch = _chapter(course, title="Ch")
    sec = _section(course, ch, title="Sec")
    qz = _quiz(course, sec)
    _auto_q(qz, "10")
    s = UserFactory()
    QuizSubmission.objects.create(
        student=s,
        unit=qz,
        status="submitted",
        score=Decimal("7"),
        max_score=Decimal("10"),
    )
    flat = build_results_matrix(course, [s])
    expanded = build_results_matrix(course, [s], {ch.pk})
    assert flat["rows"][0]["overall"]["percent"] == 70
    assert expanded["rows"][0]["overall"]["percent"] == 70  # unchanged by expansion


@pytest.mark.django_db
def test_builders_expose_expanded_nodes_and_expandable():
    course = CourseFactory()
    ch = _chapter(course)
    _section(course, ch)
    m = build_progress_matrix(course, [])
    assert m["expanded_nodes"] == []
    assert m["columns"][0]["expandable"] is True
    assert set(m["columns"][0].keys()) == {"node", "title", "expandable"}


@pytest.mark.django_db
def test_progress_query_count_constant_under_expansion():
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    course = CourseFactory()
    ch = _chapter(course)
    sec = _section(course, ch)
    _lesson(course, sec)
    s = [UserFactory() for _ in range(3)]
    build_progress_matrix(course, s)  # warm
    with CaptureQueriesContext(connection) as c1:
        build_progress_matrix(course, s)
    with CaptureQueriesContext(connection) as c2:
        build_progress_matrix(course, s, {ch.pk, sec.pk})
    assert len(c1) == len(c2)  # only in-memory grouping changes


@pytest.mark.django_db
def test_build_course_results_rows_carry_submission_pk():
    from courses.rollups import build_course_results

    course = CourseFactory()
    ch = _chapter(course)
    qz1 = _quiz(course, ch)
    qz2 = _quiz(course, ch)
    _review_q(qz1, "10")
    s = UserFactory()
    sub = QuizSubmission.objects.create(
        student=s,
        unit=qz1,
        status="submitted",
        score=Decimal("0"),
        max_score=Decimal("0"),
    )
    res = build_course_results(course, s)
    by_unit = {r["unit"].pk: r for r in res["rows"]}
    assert by_unit[qz1.pk]["submission_pk"] == sub.pk
    assert by_unit[qz2.pk]["submission_pk"] is None  # not_started -> no submission
