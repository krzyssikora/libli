"""The per-question drill-down page. Two specs' test ids live here: T30, T31, T31b,
T33, T35-T39, T41 are the per-question drill-down spec's (2026-09-14); T18-T32 added
from Task B1 on are the analytics student pages spec's (2026-09-16). Same number, two
tests (e.g. test_t31_each_path_segment_… vs test_t31_option_table_…): -k by NAME.

Every PA/owner-viewed pupil gets an Enrollment row: reviewable_students serves
PA and owner from Enrollment alone, and GroupMembershipFactory creates none."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from courses.models import Blank
from courses.models import Choice
from courses.models import ChoiceGridQuestionElement
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import GridColumn
from courses.models import GridRow
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.views_analytics import _expand_qs
from tests.answer_summary_fixtures import TOKEN0
from tests.answer_summary_fixtures import TOKEN1
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_teacher
from tests.factories import make_verified_user

pytestmark = pytest.mark.django_db


def _url(course, student_pk, node_pk, qs=""):
    path = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": course.slug, "student_pk": student_pk, "node_pk": node_pk},
    )
    return f"{path}{qs}"


def _quiz_with_question(course, *, published=True, title="Quiz"):
    quiz = ContentNodeFactory(
        course=course,
        parent=None,
        kind="unit",
        unit_type="quiz",
        published=published,
        title=title,
    )
    q = ShortTextQuestionElement.objects.create(
        stem="<p>Capital?</p>", accepted="Warsaw", max_marks=Decimal("1")
    )
    Element.objects.create(unit=quiz, content_object=q)
    return quiz


def _submitted(student, quiz, **kw):
    kw.setdefault("status", QuizSubmission.Status.SUBMITTED)
    return QuizSubmission.objects.create(student=student, unit=quiz, **kw)


def _soup(response):
    return BeautifulSoup(response.content.decode(), "html.parser")


# --- T30 access --------------------------------------------------------------
def test_t30_access_matrix(client):
    pa = make_pa(client, "pa")
    owner = make_verified_user(username="owner", email="owner@test.example.com")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    pupil_a = make_verified_user(username="pupila", email="pupila@test.example.com")
    pupil_b = UserFactory()
    for pupil in (pupil_a, pupil_b):
        EnrollmentFactory(student=pupil, course=course)
        _submitted(pupil, quiz)
    group_a = GroupFactory(course=course)
    group_b = GroupFactory(course=course)
    GroupMembershipFactory(group=group_a, student=pupil_a)
    GroupMembershipFactory(group=group_b, student=pupil_b)
    teacher_a = make_teacher(client, "teachera")
    group_a.teachers.add(teacher_a)
    teacher_b = make_teacher(client, "teacherb")
    group_b.teachers.add(teacher_b)
    archived_teacher = make_teacher(client, "archivedteacher")
    group_b.teachers.add(archived_teacher)  # active group, so step 2 passes
    old_group = GroupFactory(course=course, archived=True)
    old_group.teachers.add(archived_teacher)
    GroupMembershipFactory(group=old_group, student=pupil_a)
    staff = make_teacher(client, "staffnogroup")
    staff.is_staff = True
    staff.save(update_fields=["is_staff"])
    # Pinned up front so every mutant's flip is real (spec T30).
    assert not pa.is_staff and not owner.is_staff and not teacher_a.is_staff
    assert staff.is_staff

    url = _url(course, pupil_a.pk, quiz.pk)
    expected = [
        (pa, 200),
        (owner, 200),
        (teacher_a, 200),
        (teacher_b, 404),
        (archived_teacher, 404),
        (staff, 404),
        (pupil_a, 404),
    ]
    actual = {}
    for viewer, _status in expected:
        client.force_login(viewer)
        actual[viewer.username] = client.get(url).status_code
    # ONE dict comparison, so a failure lists EVERY flipped row (spec T30).
    assert actual == {viewer.username: status for viewer, status in expected}
    client.logout()
    anonymous = client.get(url)
    assert anonymous.status_code == 302
    assert "/accounts/login/" in anonymous.url


# --- T31 resolution ----------------------------------------------------------
def test_t31_each_path_segment_404s_on_its_own(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    _submitted(pupil, quiz)
    assert client.get(_url(course, pupil.pk, quiz.pk)).status_code == 200

    # Submissions exist on these nodes, so step 5 cannot be what 404s them.
    other = CourseFactory(owner=owner)
    other_quiz = _quiz_with_question(other)
    _submitted(pupil, other_quiz)
    assert client.get(_url(course, pupil.pk, other_quiz.pk)).status_code == 404
    lesson = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    _submitted(pupil, lesson)
    assert client.get(_url(course, pupil.pk, lesson.pk)).status_code == 404

    missing = get_user_model().objects.order_by("-pk").first().pk + 1000
    assert client.get(_url(course, missing, quiz.pk)).status_code == 404

    no_submission = UserFactory()
    EnrollmentFactory(student=no_submission, course=course)
    assert client.get(_url(course, no_submission.pk, quiz.pk)).status_code == 404


def test_t31b_group_teacher_opens_a_draft_quiz_the_pupil_has_data_on(client):
    teacher = make_teacher(client, "draftteacher")
    course = CourseFactory(owner=UserFactory())
    quiz = _quiz_with_question(course, published=False)
    pupil = UserFactory()
    group = GroupFactory(course=course)
    group.teachers.add(teacher)
    GroupMembershipFactory(group=group, student=pupil)
    _submitted(pupil, quiz)
    client.force_login(teacher)
    assert client.get(_url(course, pupil.pk, quiz.pk)).status_code == 200


# --- header pill + Review link (full parity is T27) ---------------------------
def test_awaiting_header_has_one_review_link(client):
    from courses.models import ExtendedResponseQuestionElement
    from courses.models import QuestionElement

    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = _quiz_with_question(course)
    q = ExtendedResponseQuestionElement.objects.create(
        stem="Discuss.",
        required_keywords="",
        forbidden_keywords="",
        marking_mode=QuestionElement.MarkingMode.REVIEW,
        max_marks=Decimal("1"),
    )
    Element.objects.create(unit=quiz, content_object=q)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    status = soup.select_one(".answers__status")
    assert status.select_one(".pill--awaiting") is not None
    review_url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    assert len(status.select(f'a[href="{review_url}"]')) == 1


AUTO = QuestionElement.MarkingMode.AUTO
REVIEW = QuestionElement.MarkingMode.REVIEW
NOT_MARKED = QuestionElement.MarkingMode.NOT_MARKED


def _empty_quiz(course, title):
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title=title
    )


def _add(quiz, model=ShortTextQuestionElement, **fields):
    fields.setdefault("stem", "<p>Q</p>")
    fields.setdefault("max_marks", Decimal("1"))
    if model is ShortTextQuestionElement:
        fields.setdefault("accepted", "Warsaw")
    if model is ExtendedResponseQuestionElement:
        fields.setdefault("required_keywords", "")
        fields.setdefault("forbidden_keywords", "")
    return Element.objects.create(
        unit=quiz, content_object=model.objects.create(**fields)
    )


def _respond(sub, element, **fields):
    return QuestionResponse.objects.create(submission=sub, element=element, **fields)


def _owner_view(client):
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    pupil = UserFactory()
    EnrollmentFactory(student=pupil, course=course)
    return course, pupil


def _polish(client):
    from core.middleware import LANGUAGE_SESSION_KEY

    session = client.session
    session[LANGUAGE_SESSION_KEY] = "pl"
    session.save()


def _items(soup):
    return soup.select("li.answers__item")


def _badge(item):
    return item.select_one(".answers__verdict .badge").get_text(" ", strip=True)


# --- T35 core: the in-progress fixture -----------------------------------------
def test_t35_in_progress_rows_count_and_overrides(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Live quiz")
    q1 = _add(quiz, max_attempts=2)
    _add(quiz, ExtendedResponseQuestionElement, marking_mode=REVIEW)  # q2
    q3 = _add(quiz, marking_mode=NOT_MARKED)
    q4 = _add(quiz, marking_mode=REVIEW)
    q5 = _add(quiz, max_attempts=None)
    q6 = _add(quiz)
    sub = _submitted(pupil, quiz, status=QuizSubmission.Status.IN_PROGRESS)
    _respond(sub, q1, latest_answer="Krakow", fraction=Decimal("0"), attempt_count=1)
    # q2: no response at all
    _respond(sub, q3, latest_answer=None, attempt_count=0)  # empty-submit row
    _respond(sub, q4, latest_answer="abc", attempt_count=1, locked=True)
    _respond(sub, q5, latest_answer="Warsaw", fraction=Decimal("1"), attempt_count=1)
    _respond(sub, q6, latest_answer=None, attempt_count=0)  # empty-submit row

    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    status = soup.select_one(".answers__status")
    assert status.select_one(".pill--progress") is not None
    assert "3 of 6 questions answered" in status.get_text(" ", strip=True)
    items = _items(soup)
    assert [i.select_one(".answers__qnum").get_text(strip=True) for i in items] == [
        "1.",
        "2.",
        "3.",
        "4.",
        "5.",
        "6.",
    ]
    assert _badge(items[0]).startswith("Incorrect")
    assert "attempt 1 of 2" in items[0].get_text(" ", strip=True)
    # D5: the key shows although q1 still has an attempt left (not locked)
    assert "Correct answer: Warsaw" in items[0].get_text(" ", strip=True)
    assert _badge(items[1]) == "Not answered"  # unanswered REVIEW, in progress
    assert _badge(items[2]) == "Not answered"  # empty NOT_MARKED row
    assert _badge(items[3]) == "Answer recorded"  # answered REVIEW, in progress
    assert items[3].select("a.answers__row-review") == []
    assert "attempt 1 of 1" in items[3].get_text(" ", strip=True)
    assert _badge(items[4]).startswith("Correct")
    assert "attempt 1" in items[4].get_text(" ", strip=True)
    assert "attempt 1 of" not in items[4].get_text(" ", strip=True)
    assert _badge(items[5]) == "Not answered"


def test_t35_submitted_unanswered_review_rows_link_with_distinct_names(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Essay quiz")
    _add(quiz, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _add(quiz, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("0"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    items = _items(soup)
    assert [_badge(i) for i in items] == [
        "Awaiting review (up to 1 mark)",
        "Awaiting review (up to 1 mark)",
    ]
    links = [i.select_one("a.answers__row-review") for i in items]
    expected_href = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": sub.pk},
    )
    assert [a["href"] for a in links] == [expected_href, expected_href]
    names = [a.get_text(" ", strip=True) for a in links]
    assert len(set(names)) == 2, names


def test_t35_teacher_voice_only(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Voice quiz")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="Krakow", fraction=Decimal("0"), attempt_count=1)
    cquiz_q = ChoiceQuestionElement.objects.create(
        stem="<p>Pick</p>", max_marks=Decimal("1"), multiple=True
    )
    for order, text_ in enumerate(("A", "B")):
        Choice.objects.create(
            question=cquiz_q, text=text_, is_correct=text_ == "B", order=order
        )
    cel = Element.objects.create(unit=quiz, content_object=cquiz_q)
    _respond(
        sub,
        cel,
        latest_answer=_pick(cquiz_q, "A"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    text = (
        _soup(client.get(_url(course, pupil.pk, quiz.pk)))
        .select_one("section.answers")
        .get_text(" ", strip=True)
        .lower()
    )
    assert "your answer" not in text and "you chose" not in text
    assert "chosen, incorrect" in text and "correct, not chosen" in text


# --- T27 header parity ----------------------------------------------------------
def _breakdown_pill(soup, title):
    for unit in soup.select("div.breakdown-unit"):
        if unit.select_one(".breakdown-unit__title").get_text(strip=True) == title:
            return unit.select_one(".pill")
    raise AssertionError(f"no breakdown row titled {title!r}")


def _status(client, course, pupil, quiz):
    return _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(
        ".answers__status"
    )


def _pill_quizzes(course, pupil):
    scored = _empty_quiz(course, "Q scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("5"))
    ungraded = _empty_quiz(course, "Q ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "Q awaiting")
    _add(awaiting)
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    awaiting_sub = _submitted(
        pupil, awaiting, score=Decimal("1"), max_score=Decimal("1")
    )
    reviewed = _empty_quiz(course, "Q reviewed")
    rel = _add(reviewed, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    rsub = _submitted(pupil, reviewed, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        rsub,
        rel,
        latest_answer="essay",
        attempt_count=1,
        locked=True,
        earned_marks=Decimal("1"),
        fraction=Decimal("1"),
        reviewed_at=timezone.now(),
    )
    live = _empty_quiz(course, "Q live")
    _add(live)
    _add(live)
    live_sub = _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)
    _respond(
        live_sub,
        live.elements.order_by("order", "pk").first(),
        latest_answer="x",
        attempt_count=1,
    )
    return scored, ungraded, awaiting, awaiting_sub, reviewed, live


def test_t26_header_by_pill_kind(client):
    course, pupil = _owner_view(client)
    scored, ungraded, awaiting, _sub, _reviewed, live = _pill_quizzes(course, pupil)
    s = _status(client, course, pupil, scored)
    assert s.select_one(".pill") is None
    assert s.select_one(".answers__score").get_text(" ", strip=True) == "1 / 5 marks"
    assert s.select_one(".answers__percent").get_text(strip=True) == "20%"
    for quiz, kind in (
        (ungraded, "pill--submitted"),
        (awaiting, "pill--awaiting"),
        (live, "pill--progress"),
    ):
        status = _status(client, course, pupil, quiz)
        assert kind in status.select_one(".pill")["class"]
        assert status.select_one(".answers__score") is None
    assert "1 of 2 questions answered" in _status(client, course, pupil, live).get_text(
        " ", strip=True
    )


def test_t27_header_pill_matches_the_breakdown_pill_except_scored(client):
    course, pupil = _owner_view(client)
    scored, ungraded, awaiting, awaiting_sub, reviewed, live = _pill_quizzes(
        course, pupil
    )
    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    # (1) parity for every kind that still renders a pill. `reviewed` (REVIEW-only,
    # fully reviewed, max_score 1) is SCORED since the results-table spec §4, which
    # deliberately overrides the student-pages spec §2.8: it is in part (2) now.
    for quiz, kind in (
        (ungraded, "pill--submitted"),
        (awaiting, "pill--awaiting"),
        (live, "pill--progress"),
    ):
        header = _status(client, course, pupil, quiz).select_one(".pill")
        row = _breakdown_pill(breakdown, quiz.title)
        assert kind in header["class"], quiz.title
        assert header["class"] == row["class"], quiz.title
        assert header.get_text(" ", strip=True) == row.get_text(" ", strip=True)
    # (2) scored: no header pill; the breakdown keeps its pill, same numbers
    for quiz, marks, pill_text in (
        (scored, "1 / 5 marks", "scored 1/5 (20%)"),
        (reviewed, "1 / 1 marks", "scored 1/1 (100%)"),
    ):
        status = _status(client, course, pupil, quiz)
        assert status.select_one(".pill") is None, quiz.title
        assert (
            _breakdown_pill(breakdown, quiz.title).get_text(" ", strip=True)
            == pill_text
        )
        assert status.select_one(".answers__score").get_text(" ", strip=True) == marks
    # (3) exactly one Review link; (4) no "scored" text on the awaiting strip
    awaiting_status = _status(client, course, pupil, awaiting)
    review_url = reverse(
        "courses:manage_review_submission",
        kwargs={"slug": course.slug, "submission_pk": awaiting_sub.pk},
    )
    assert len(awaiting_status.select(f'a[href="{review_url}"]')) == 1
    assert "scored" not in awaiting_status.get_text(" ", strip=True)


def test_rt_t10b_reviewed_review_only_header_shows_its_score(client):
    """results-table spec T10b: a fully reviewed REVIEW-only quiz with max_score > 0
    is scored in the per-question header (no pill), in Polish."""
    course, pupil = _owner_view(client)
    _polish(client)
    *_others, reviewed, _live = _pill_quizzes(course, pupil)
    status = _status(client, course, pupil, reviewed)
    assert status.select_one(".pill") is None
    assert status.select_one(".answers__score").get_text(" ", strip=True) == (
        "1 / 1 pkt"
    )
    assert status.select_one(".answers__percent").get_text(strip=True) == "100%"


def test_rt_t10d_reviewed_review_only_progress_pill_is_scored(client):
    """results-table spec T10d: the same quiz in PROGRESS mode renders the scored
    pill, not „przesłano"."""
    course, pupil = _owner_view(client)
    _polish(client)
    *_others, reviewed, _live = _pill_quizzes(course, pupil)
    page = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    soup = _soup(client.get(f"{page}?mode=progress"))
    pill = _breakdown_pill(soup, reviewed.title)
    assert "pill--scored" in pill["class"]
    assert pill.get_text(" ", strip=True) == "wynik 1/1 (100%)"


def test_t28_heading_is_name_then_title(client):
    course, pupil = _owner_view(client)
    pupil.first_name, pupil.last_name = "Anna", "Nowak"
    pupil.save()
    quiz = _empty_quiz(course, r"Sets \(A\)")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    head = _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(
        ".manage__head"
    )
    assert (
        head.select_one(".answers__student").get_text(strip=True)
        == pupil.list_display_name
    )
    h1 = head.select_one("h1")
    assert h1.get_text(" ", strip=True) == r"Sets \(A\)"
    assert "—" not in h1.get_text()
    assert h1.select_one("[data-math-title]") is not None
    assert head.select_one(".answers__student").get("data-math-title") is None


def test_t29_polish_header_score_uses_a_decimal_comma(client):
    course, pupil = _owner_view(client)
    _polish(client)
    thirds = _empty_quiz(course, "Thirds")
    _add(thirds)
    _submitted(pupil, thirds, score=Decimal("0.67"), max_score=Decimal("1"))
    status = _status(client, course, pupil, thirds)
    assert (
        status.select_one(".answers__score").get_text(" ", strip=True) == "0,67 / 1 pkt"
    )


# --- T41 on the page: grids reach the header --------------------------------------
def test_t41_grid_quizzes_header_pills(client):
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Grid review")
    q = MultiGridQuestionElement.objects.create(
        stem="<p>Pick</p>", marking_mode=REVIEW, max_marks=Decimal("1")
    )
    col = MultiGridColumn.objects.create(question=q, label="a")
    MultiGridRow.objects.create(question=q, statement="r1").correct_columns.set([col])
    Element.objects.create(unit=quiz, content_object=q)
    _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("0"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    assert soup.select_one(".answers__status .pill--awaiting") is not None
    assert len(soup.select(".answers__status a.answers__review")) == 1
    assert len(soup.select("li.answers__item a.answers__row-review")) == 1


# --- T33 page cases: accepted splits after content edits ---------------------------
def test_t33_key_edited_after_answering_keeps_badge_and_remarks_parts(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Edited key")
    el = _add(quiz, ShortNumericQuestionElement, value="1/2", tolerance="")
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="1/2", fraction=Decimal("1"), attempt_count=1)
    q = el.content_object
    q.value = "3"
    q.save()
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert _badge(item).startswith("Correct")
    assert item.select_one(".answers__glyph--incorrect") is not None
    assert "Correct answer: 3" in item.get_text(" ", strip=True)


def test_t33_switched_to_auto_never_reviewed_badges_answer_recorded(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Switched")
    el = _add(quiz, marking_mode=REVIEW)
    sub = _submitted(pupil, quiz, status=QuizSubmission.Status.IN_PROGRESS)
    _respond(sub, el, latest_answer="Warsaw", attempt_count=1, locked=True)
    q = el.content_object
    q.marking_mode = AUTO
    q.save()
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    item = _items(soup)[0]
    assert _badge(item) == "Answer recorded"
    assert item.select_one(".answers__glyph--correct") is not None
    assert "1 of 1 question answered" in soup.select_one(".answers__status").get_text(
        " ", strip=True
    )


def test_t33_reviewed_then_switched_to_auto_badges_from_the_review(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Reviewed switch")
    answered = _add(quiz, marking_mode=REVIEW)
    blank = _add(quiz, marking_mode=REVIEW)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("2"))
    now = timezone.now()
    _respond(
        sub,
        answered,
        latest_answer="Warsaw",
        attempt_count=1,
        locked=True,
        earned_marks=Decimal("1"),
        fraction=Decimal("1"),
        reviewed_at=now,
    )
    _respond(
        sub,
        blank,
        latest_answer=None,
        attempt_count=0,
        locked=True,
        earned_marks=Decimal("0"),
        fraction=Decimal("0"),
        reviewed_at=now,
    )
    for el in (answered, blank):
        q = el.content_object
        q.marking_mode = AUTO
        q.save()
    items = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert _badge(items[0]).startswith("Correct")
    assert _badge(items[1]).startswith("Incorrect")
    assert "Not answered" in items[1].select_one(".answers__part").get_text(
        " ", strip=True
    )
    assert items[1].select_one(".answers__glyph--incorrect") is not None


def test_t33_lowered_max_attempts_never_prints_n_of_smaller_max(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Lowered")
    el = _add(quiz, max_attempts=3)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="Krakow", fraction=Decimal("0"), attempt_count=3)
    q = el.content_object
    q.max_attempts = 1
    q.save()
    text = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0].get_text(
        " ", strip=True
    )
    assert "attempt 3" in text
    assert "attempt 3 of" not in text


# --- review feedback ---------------------------------------------------------------
def test_review_feedback_shows_on_any_row_with_feedback(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Feedback")
    el = _add(quiz)  # AUTO now; feedback left from an earlier review
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer="Warsaw",
        fraction=Decimal("1"),
        attempt_count=1,
        review_feedback="Well argued",
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert "Well argued" in item.get_text(" ", strip=True)


# --- T35 rest: stems, stage, empty states, glyph unit, language ------------------
def test_token_stems_render_gap_markers_matching_the_part_labels(client):
    from courses.fillblank import SENTINEL
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Gaps")
    q = FillBlankQuestionElement.objects.create(
        stem=f"2 + {SENTINEL}0{SENTINEL} = {SENTINEL}1{SENTINEL}",
        max_marks=Decimal("1"),
    )
    assert SENTINEL in FillBlankQuestionElement.objects.get(pk=q.pk).stem
    Blank.objects.create(question=q, accepted="2")
    Blank.objects.create(question=q, accepted="4")
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub, el, latest_answer=["2", "5"], fraction=Decimal("0.5"), attempt_count=1
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    stem = item.select_one(".answers__stem")
    assert SENTINEL not in str(stem)
    assert [g.get_text() for g in stem.select(".answers__gap")] == ["[1]", "[2]"]
    assert [
        p.select_one(".answers__label").get_text(strip=True)
        for p in item.select(".answers__part")
    ] == ["Gap 1", "Gap 2"]


def test_dragimage_row_renders_a_static_numbered_stage(client):
    from tests.factories import DragZoneFactory

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Image")
    zone = DragZoneFactory(correct_label="Heart")
    DragZoneFactory(question=zone.question, correct_label="Liver")
    q = zone.question  # stem is blank: a prompt-less question
    Element.objects.create(unit=quiz, content_object=q)
    _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    stage = item.select_one(".dragimage__stage")
    assert stage is not None
    assert stage.select_one("img.dragimage__img")["alt"] == q.alt
    assert [b.get_text(strip=True) for b in stage.select("span.dragimage__badge")] == [
        "1",
        "2",
    ]
    assert item.select("select, form, [data-dnd], [data-zone]") == []


def test_zero_question_quiz_and_zero_part_question_empty_states(client):
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    course, pupil = _owner_view(client)
    empty = _empty_quiz(course, "Nothing here")
    _submitted(pupil, empty, status=QuizSubmission.Status.IN_PROGRESS)
    soup = _soup(client.get(_url(course, pupil.pk, empty.pk)))
    assert "This quiz has no questions." in soup.select_one("section.answers").get_text(
        " ", strip=True
    )
    assert " of 0 " not in soup.select_one(".answers__status").get_text(" ", strip=True)
    assert soup.select("ol.answers__list") == []

    quiz = _empty_quiz(course, "Emptied")
    from courses.fillblank import SENTINEL

    q = FillBlankQuestionElement.objects.create(
        stem=f"{SENTINEL}0{SENTINEL}", max_marks=Decimal("1")
    )
    Blank.objects.create(question=q, accepted="2")
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=["2"], fraction=Decimal("1"), attempt_count=1)
    q.blanks.all().delete()
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert "(this question no longer has any parts)" in item.get_text(" ", strip=True)


def test_an_empty_part_that_scores_true_shows_no_tick_and_no_sr_correct(client):
    from courses.models import MultiGridColumn
    from courses.models import MultiGridQuestionElement
    from courses.models import MultiGridRow

    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Empty set")
    q = MultiGridQuestionElement.objects.create(
        stem="<p>Pick</p>", max_marks=Decimal("1")
    )
    MultiGridColumn.objects.create(question=q, label="a")
    MultiGridRow.objects.create(question=q, statement="r1")  # empty correct set
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=[[]], fraction=Decimal("1"), attempt_count=1)
    part = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0].select_one(
        ".answers__part"
    )
    assert "Not answered" in part.get_text(" ", strip=True)
    assert part.select(".answers__glyph") == []
    assert [s.get_text(strip=True) for s in part.select(".sr-only")] == []


def test_shorttext_with_empty_expected_renders_no_hint(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "No key")
    el = _add(quiz, accepted="")
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="x", fraction=Decimal("0"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert "Correct answer:" not in item.get_text(" ", strip=True)


def test_course_language_tags_given_expected_and_content_labels(client):
    from courses.models import MatchPair
    from courses.models import MatchPairQuestionElement

    course, pupil = _owner_view(client)
    course.language = "pl"
    course.save(update_fields=["language"])
    quiz = _empty_quiz(course, "Pary")
    q = MatchPairQuestionElement.objects.create(
        stem="<p>Dopasuj</p>", max_marks=Decimal("1")
    )
    MatchPair.objects.create(question=q, left="kot", right="cat")
    MatchPair.objects.create(question=q, left="pies", right="dog")
    el = Element.objects.create(unit=quiz, content_object=q)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub, el, latest_answer=["dog", "dog"], fraction=Decimal("0.5"), attempt_count=1
    )
    part = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0].select(
        ".answers__part"
    )[0]
    assert part.select_one(".answers__label")["lang"] == "pl"
    assert part.select_one(".answers__given")["lang"] == "pl"
    assert part.select_one(".answers__expected strong")["lang"] == "pl"


def test_answered_extendedresponse_keyword_parts_never_say_not_answered(client):
    """Spec T32's rendered check: keyword parts always have given=None, so only
    the kind == "answer" gate keeps "Not answered" off them."""
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Keywords")
    el = _add(
        quiz,
        ExtendedResponseQuestionElement,
        required_keywords="alpha\nbeta",
        forbidden_keywords="gamma",
    )
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub, el, latest_answer="alpha only", fraction=Decimal("0.5"), attempt_count=1
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    keyword_parts = item.select(".answers__part--keyword")
    assert len(keyword_parts) == 3
    for part in keyword_parts:
        assert "Not answered" not in part.get_text(" ", strip=True)


# --- T39 maths ---------------------------------------------------------------
def _script_srcs(soup):
    return [s["src"] for s in soup.select("script[src]")]


def test_t39_pupil_typed_maths_loads_katex_and_question_js(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Plain")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=r"\(x\)", fraction=Decimal("0"), attempt_count=1)
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    katex = [
        i for i, s in enumerate(srcs) if s.endswith("math.js") and "question" not in s
    ]
    question = [i for i, s in enumerate(srcs) if s.endswith("courses/js/question.js")]
    assert katex and question and question[0] > katex[0], srcs


def test_t39_review_feedback_maths_alone_loads_katex(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Plain feedback")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer="Warsaw",
        fraction=Decimal("1"),
        attempt_count=1,
        review_feedback=r"See \(y\)",
    )
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert any(s.endswith("courses/js/question.js") for s in srcs)


def test_t39_no_maths_anywhere_loads_neither(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Plain none")
    el = _add(quiz)
    sub = _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="Warsaw", fraction=Decimal("1"), attempt_count=1)
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert not any("katex" in s or s.endswith("question.js") for s in srcs)


def test_t39_shorttext_accepted_maths_alone_loads_question_js(client):
    """`_question_has_math` has no ShortTextQuestionElement branch (courses/views.py),
    so a delimiter in `accepted` reaches the page only through
    `_answers_have_math`'s own `part.expected` check -- pins that field."""
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Shorttext accepted maths")
    el = _add(quiz, accepted=r"\(x\)")
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="wrong", fraction=Decimal("0"), attempt_count=1)
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert any(s.endswith("courses/js/question.js") for s in srcs)


def test_t39_extendedresponse_keyword_label_maths_loads_question_js(client):
    """`_question_has_math` has no ExtendedResponseQuestionElement branch, so a
    delimiter in `required_keywords` reaches the page only through
    `_answers_have_math`'s own `part.label` check -- pins that field."""
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Keyword label maths")
    el = _add(quiz, ExtendedResponseQuestionElement, required_keywords=r"\(y\)")
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="no match", fraction=Decimal("0"), attempt_count=1)
    srcs = _script_srcs(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    assert any(s.endswith("courses/js/question.js") for s in srcs)


# --- T37 breakdown links and the back link -------------------------------------
def _breakdown_title_span(soup, title):
    for unit in soup.select("div.breakdown-unit"):
        span = unit.select_one(":scope > span.breakdown-unit__title")
        if span is not None and span.get_text(strip=True) == title:
            return span
    raise AssertionError(f"no breakdown title {title!r}")


def _results_title_cell(soup, title):
    rows = "table.results-table tbody tr:not(.results-table__section) > th"
    for th in soup.select(rows):
        if th.get_text(strip=True) == title:
            return th
    raise AssertionError(f"no Results-table quiz title {title!r}")


@pytest.mark.parametrize("mode", ["progress", "results"])
def test_t37_quiz_titles_link_iff_the_pupil_has_a_submission(client, mode):
    course, pupil = _owner_view(client)
    scored = _empty_quiz(course, "L scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("1"))
    ungraded = _empty_quiz(course, "L ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "L awaiting")
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _submitted(pupil, awaiting, score=Decimal("0"), max_score=Decimal("0"))
    live = _empty_quiz(course, "L live")
    _add(live)
    _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)
    notyet = _empty_quiz(course, "L not started")
    _add(notyet)

    qs = f"?scope=all&mode={mode}&student={pupil.pk}&values=raw"
    breakdown_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    soup = _soup(client.get(breakdown_path + qs))
    drill = _expand_qs("all", mode, [], [pupil.pk], "raw")
    title_of = _breakdown_title_span if mode == "progress" else _results_title_cell
    for quiz in (scored, ungraded, awaiting, live):
        link = title_of(soup, quiz.title).select_one("a.breakdown-unit__link")
        assert link is not None, quiz.title
        assert link["href"] == _url(course, pupil.pk, quiz.pk, f"?{drill}")
    assert title_of(soup, notyet.title).select("a") == []


def test_rt_t10b_header_matches_the_table_row(client):
    """results-table spec T10b: the header of a fully reviewed REVIEW-only quiz shows
    the same figures as its Results-table row."""
    course, pupil = _owner_view(client)
    _polish(client)
    *_others, reviewed, _live = _pill_quizzes(course, pupil)
    page = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    table = _soup(client.get(f"{page}?mode=results"))
    row = _results_title_cell(table, reviewed.title).find_parent("tr")
    _status_cell, score, percent = (td.get_text(strip=True) for td in row.select("td"))
    status = _status(client, course, pupil, reviewed)
    assert (score, percent) == ("1/1", "100%")
    assert status.select_one(".answers__score").get_text(" ", strip=True) == "1 / 1 pkt"
    assert status.select_one(".answers__percent").get_text(strip=True) == percent


def test_t37_back_link_round_trips_scope_mode_expand_subset_and_values(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Back")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    qs = f"?scope=all&mode=results&expand={quiz.pk}&student={pupil.pk}&values=raw"
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk, qs)))
    back = soup.select_one("section.answers .manage__head a")["href"]
    expected_path = reverse(
        "courses:manage_analytics_student",
        kwargs={"slug": course.slug, "student_pk": pupil.pk},
    )
    drill = _expand_qs("all", "results", [quiz.pk], [pupil.pk], "raw")
    assert back == f"{expected_path}?{drill}"


# --- T38 query budget --------------------------------------------------------------
def _stored_answer(key, q):
    if key == "choice":
        return [q.choices.first().pk]
    if key == "choicegrid":
        return [q.columns.first().pk, ""]
    if key == "multigrid":
        return [[], []]
    return {
        "shorttext": "x",
        "shortnumeric": "1",
        "extendedresponse": "alpha",
        "fillblank": ["2", "5"],
        "dragfill": ["cat", "cat"],
        "dragimage": ["Heart", "Heart"],
        "matchpair": ["1", "3", "2"],
    }[key]


def _every_type_quiz(course, pupil, title, copies):
    from tests.answer_summary_fixtures import build_all_types

    quiz = _empty_quiz(course, title)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("20"))
    for _ in range(copies):
        for key, q in build_all_types().items():
            el = Element.objects.create(unit=quiz, content_object=q)
            _respond(
                sub,
                el,
                latest_answer=_stored_answer(key, q),
                fraction=Decimal("0"),
                attempt_count=1,
            )
    return quiz


def _page_queries(client, url):
    assert client.get(url).status_code == 200  # warm ContentType/session caches
    with CaptureQueriesContext(connection) as captured:
        assert client.get(url).status_code == 200
    return len(captured)


def test_t38_query_count_does_not_grow_with_questions(client):
    course, pupil = _owner_view(client)
    one = _every_type_quiz(course, pupil, "One of each", 1)
    two = _every_type_quiz(course, pupil, "Two of each", 2)
    assert _page_queries(client, _url(course, pupil.pk, one.pk)) == _page_queries(
        client, _url(course, pupil.pk, two.pk)
    )


# --- T29 / T30 marks read the same everywhere (spec §5.5) --------------------------
def test_t29_polish_marks_use_a_decimal_comma_in_badge_and_pill(client):
    course, pupil = _owner_view(client)
    _polish(client)
    half = _empty_quiz(course, "Half")
    el = _add(half)
    sub = _submitted(pupil, half, score=Decimal("0.5"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer="x", fraction=Decimal("0.5"), attempt_count=1)
    thirds = _empty_quiz(course, "Thirds")
    _add(thirds)
    _submitted(pupil, thirds, score=Decimal("0.67"), max_score=Decimal("1"))

    badge = _badge(_items(_soup(client.get(_url(course, pupil.pk, half.pk))))[0])
    assert "(0,5/1)" in badge
    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    assert _breakdown_pill(breakdown, "Thirds").get_text(" ", strip=True) == (
        "wynik 0,67/1 (67%)"
    )


def test_t29_english_marks_keep_a_decimal_point(client):
    course, pupil = _owner_view(client)
    thirds = _empty_quiz(course, "Thirds")
    _add(thirds)
    _submitted(pupil, thirds, score=Decimal("0.67"), max_score=Decimal("1"))
    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    assert _breakdown_pill(breakdown, "Thirds").get_text(" ", strip=True) == (
        "scored 0.67/1 (67%)"
    )


def test_t30_polish_export_keeps_a_decimal_point(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Exported")
    _add(quiz, marking_mode=QuestionElement.MarkingMode.AUTO)
    _submitted(pupil, quiz, score=Decimal("0.5"), max_score=Decimal("1"))
    body = client.get(
        reverse("courses:manage_analytics_export", kwargs={"slug": course.slug}),
        {"shape": "quiz", "format": "csv"},
    ).content.decode("utf-8-sig")
    assert "0.5" in body
    assert "0,5" not in body


@pytest.mark.parametrize(
    ("mode", "word"), [("results", "Wyniki"), ("progress", "Postęp")]
)
def test_rt_t10_back_link_names_the_view(client, mode, word):
    """results-table spec T9/T10 (O7, O8): the back link names the view it returns
    to, never „Wyniki ucznia"."""
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Back word")
    _add(quiz)
    _submitted(pupil, quiz, score=Decimal("1"), max_score=Decimal("1"))
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk, f"?mode={mode}")))
    back = soup.select_one("section.answers .manage__head a")
    assert back.get_text(" ", strip=True) == f"← {word}"
    assert "ucznia" not in back.get_text()


def _choice_quiz(
    course, title, *, marking_mode=None, correct=("B",), texts=("A", "B", "C")
):
    quiz = _empty_quiz(course, title)
    fields = {"stem": "<p>Pick</p>", "max_marks": Decimal("1"), "multiple": True}
    if marking_mode is not None:
        fields["marking_mode"] = marking_mode
    question = ChoiceQuestionElement.objects.create(**fields)
    for order, text in enumerate(texts):
        Choice.objects.create(
            question=question, text=text, is_correct=text in correct, order=order
        )
    el = Element.objects.create(unit=quiz, content_object=question)
    return quiz, question, el


def _pick(question, *texts):
    return sorted(c.pk for c in question.choices.all() if c.text in texts)


def test_t19_option_kinds_equal_the_marks_the_page_computed(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Kinds", correct=("B", "C"))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "A", "B"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    resp = client.get(_url(course, pupil.pk, quiz.pk))
    row = resp.context["rows"][0]
    by_text = {c.pk: c.text for c in question.choices.all()}
    expected = {by_text[pk]: mark["kind"] for pk, mark in row["marks"].items()}
    got = {o.text: o.mark for o in row["parts"][0].options}
    assert {t: k for t, k in got.items() if k is not None} == expected
    assert {t for t, k in got.items() if k is None} == set(by_text.values()) - set(
        expected
    )
    assert got == {"A": "wrong", "B": "correct", "C": "missed"}


def _option_rows(item):
    table = item.select_one("table.answers__options")
    assert table is not None
    return table.select("tbody tr")


def _ths(item):
    return [
        th.get_text(" ", strip=True) for th in item.select("table.answers__options th")
    ]


def test_t31_option_table_columns_and_cells(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz, question, el = _choice_quiz(course, "Table", correct=("B",))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "A"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert _ths(item) == ["Wybór ucznia", "Klucz", "Odpowiedź"]
    cells = [
        [td.get_text(" ", strip=True) for td in tr.select("td")]
        for tr in _option_rows(item)
    ]
    # column 1: ● iff picked (plus its sr-only label); column 2: ✓ iff correct
    assert cells == [
        ["● wybrana, niepoprawna", "", "A"],
        ["○ poprawna, niewybrana", "✓", "B"],
        ["○", "", "C"],
    ]


def test_t21b_one_verdict_label_per_option_row_in_column_one(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Labels", correct=("B",))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "A"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    for tr in _option_rows(item):
        labels = tr.select(".sr-only")
        tds = tr.select("td")
        assert len(labels) <= 1
        assert all(label.find_parent("td") is tds[0] for label in labels)
    classes = [tr.get("class", []) for tr in _option_rows(item)]
    assert classes == [
        ["answers__option", "is-wrong"],
        ["answers__option", "is-missed"],
        ["answers__option"],
    ]


def test_t18_non_auto_choice_table_has_no_key_column(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Review", marking_mode=REVIEW)
    sub = _submitted(pupil, quiz)
    _respond(sub, el, latest_answer=_pick(question, "C"), attempt_count=1)
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    assert _ths(item) == ["Student's choice", "Answer"]
    rows = _option_rows(item)
    assert all(len(tr.select("td")) == 2 for tr in rows)
    assert rows[2].select_one(".sr-only").get_text(strip=True) == "chosen"
    assert rows[0].select_one(".sr-only") is None


def test_t20_every_option_in_author_order(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Order", texts=("A", "B", "C"))
    Choice.objects.filter(question=question, text="A").update(order=2)
    Choice.objects.filter(question=question, text="C").update(order=0)
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "B"),
        fraction=Decimal("1"),
        attempt_count=1,
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    texts = [tr.select("td")[-1].get_text(strip=True) for tr in _option_rows(item)]
    assert texts == ["C", "B", "A"]


def test_t32_empty_key_caption_distinguishes_it_from_non_auto(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "No key", correct=())
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "A"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    caption = item.select_one("table.answers__options caption")
    assert caption.get_text(" ", strip=True) == "correct answer: (none)"
    assert "is-wrong" in _option_rows(item)[0]["class"]


def _loginable_pupil(course, username):
    """A student the test client can log in as. NOT UserFactory: it sets
    skip_postgeneration_save, so its password never reaches the database, the
    session auth hash fails on the next request, and a @login_required page
    answers 302."""
    pupil = make_verified_user(username=username, email=f"{username}@test.example.com")
    EnrollmentFactory(student=pupil, course=course)
    return pupil


def test_t19_student_results_page_shows_the_same_kinds(client):
    course, _factory_pupil = _owner_view(client)
    pupil = _loginable_pupil(course, "parity")
    quiz, question, el = _choice_quiz(course, "Parity", correct=("B", "C"))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "A", "B"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    item = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))[0]
    teacher = {
        tr.select("td")[-1].get_text(strip=True): next(
            (c[3:] for c in tr["class"] if c.startswith("is-")), None
        )
        for tr in _option_rows(item)
    }
    client.force_login(pupil)
    resp = client.get(
        reverse(
            "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
        )
    )
    assert resp.status_code == 200
    student = {}
    # PR 3 (spec 2026-09-25 §4, §8): replaces the old `_reveal_choice.html` list
    # selectors (`li.question__reveal-item`, `.question__reveal-mark`) -- choice's
    # results row is now the question itself.
    for li in _soup(resp).select("li.question__choice"):
        mark = li.select_one(".question__choice-marker")
        kind = None
        if mark is not None:
            kind = next(c.split("--")[1] for c in mark["class"] if "--" in c)
        student[li.select_one(".question__choice-text").get_text(strip=True)] = kind
    assert teacher == student == {"A": "wrong", "B": "correct", "C": "missed"}


def test_t22_maths_in_an_option_loads_katex(client):
    course, pupil = _owner_view(client)
    quiz, question, el = _choice_quiz(course, "Maths", texts=("A", r"\(x^2\)"))
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(
        sub,
        el,
        latest_answer=_pick(question, "A"),
        fraction=Decimal("0"),
        attempt_count=1,
    )
    soup = _soup(client.get(_url(course, pupil.pk, quiz.pk)))
    assert any("katex" in src for src in _script_srcs(soup))


# --- T24 labels + grid for multi-part questions -------------------------------
def _fillblank_quiz(course, title, *, marking_mode=None):
    quiz = _empty_quiz(course, title)
    fields = {"stem": f"<p>2 + {TOKEN0} = {TOKEN1}</p>", "max_marks": Decimal("1")}
    if marking_mode is not None:
        fields["marking_mode"] = marking_mode
    question = FillBlankQuestionElement.objects.create(**fields)
    Blank.objects.create(question=question, accepted="2", order=0)
    Blank.objects.create(question=question, accepted="4", order=1)
    el = Element.objects.create(unit=quiz, content_object=question)
    return quiz, el


def _answered_page(client, course, pupil, quiz, el, answers, fraction):
    sub = _submitted(pupil, quiz, score=Decimal("0"), max_score=Decimal("1"))
    _respond(sub, el, latest_answer=answers, fraction=fraction, attempt_count=1)
    resp = client.get(_url(course, pupil.pk, quiz.pk))
    return resp, _items(_soup(resp))[0]


def test_blank_grid_statement_never_borrows_the_student_answer_label(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Blank row")
    grid = ChoiceGridQuestionElement.objects.create(
        stem="<p>G</p>", max_marks=Decimal("1")
    )
    yes = GridColumn.objects.create(question=grid, label="yes", order=0)
    no = GridColumn.objects.create(question=grid, label="no", order=1)
    GridRow.objects.create(question=grid, statement="", correct_column=yes, order=0)
    GridRow.objects.create(question=grid, statement="r2", correct_column=no, order=1)
    el = Element.objects.create(unit=quiz, content_object=grid)
    # all correct -> NOT columned, so the non-columned label branch renders
    resp, item = _answered_page(
        client, course, pupil, quiz, el, [yes.pk, no.pk], Decimal("1")
    )
    assert resp.context["rows"][0]["columned"] is False
    assert "Student's answer:" not in item.get_text(" ", strip=True)


def test_single_part_answer_is_labelled(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Single")
    el = _add(quiz)
    _resp, item = _answered_page(
        client, course, pupil, quiz, el, "Krakow", Decimal("0")
    )
    part = item.select_one(".answers__part")
    assert (
        part.select_one(".answers__label").get_text(strip=True) == "Odpowiedź ucznia:"
    )
    assert "Poprawna odpowiedź: Warsaw" in part.get_text(" ", strip=True)
    assert item.select_one(".answers__header-row") is None


def test_t24_extended_response_with_keywords_is_not_columned(client):
    course, pupil = _owner_view(client)
    quiz = _empty_quiz(course, "Essay")
    el = _add(quiz, ExtendedResponseQuestionElement, required_keywords="alpha\nbeta")
    resp, item = _answered_page(
        client, course, pupil, quiz, el, "alpha", Decimal("0.5")
    )
    assert resp.context["rows"][0]["columned"] is False
    parts = item.select(".answers__part")
    assert (
        parts[0].select_one(".answers__label").get_text(strip=True)
        == "Student's answer:"
    )
    assert item.select_one(".answers__header-row") is None


def test_t24b_the_expected_term(client):
    course, pupil = _owner_view(client)
    right, rel = _fillblank_quiz(course, "All right")
    partly, pel = _fillblank_quiz(course, "Partly")
    review, vel = _fillblank_quiz(course, "Review", marking_mode=REVIEW)
    all_right, _i = _answered_page(
        client, course, pupil, right, rel, ["2", "4"], Decimal("1")
    )
    partial, _i = _answered_page(
        client, course, pupil, partly, pel, ["2", "5"], Decimal("0.5")
    )
    sub = _submitted(pupil, review)
    _respond(sub, vel, latest_answer=["2", "5"], attempt_count=1)
    non_auto = client.get(_url(course, pupil.pk, review.pk))
    assert all_right.context["rows"][0]["columned"] is False
    assert partial.context["rows"][0]["columned"] is True
    assert non_auto.context["rows"][0]["columned"] is False


def test_t24c_every_columned_part_emits_three_children(client):
    course, pupil = _owner_view(client)
    _polish(client)
    quiz = _empty_quiz(course, "Grid")
    grid = ChoiceGridQuestionElement.objects.create(
        stem="<p>G</p>", max_marks=Decimal("1")
    )
    yes = GridColumn.objects.create(question=grid, label="yes", order=0)
    no = GridColumn.objects.create(question=grid, label="no", order=1)
    GridRow.objects.create(question=grid, statement="", correct_column=yes, order=0)
    GridRow.objects.create(question=grid, statement="r2", correct_column=no, order=1)
    el = Element.objects.create(unit=quiz, content_object=grid)
    # row 1 (blank statement) answered right, row 2 wrong -> partially correct
    resp, item = _answered_page(
        client, course, pupil, quiz, el, [yes.pk, yes.pk], Decimal("0.5")
    )
    assert resp.context["rows"][0]["columned"] is True
    parts = item.select(".answers__parts--columned > .answers__part")
    assert len(parts) == 2
    for part in parts:
        assert [c["class"][0] for c in part.find_all(recursive=False)] == [
            "answers__label",
            "answers__given-cell",
            "answers__expected",
        ]
    assert parts[0].select_one(".answers__label").get_text(strip=True) == ""
    assert parts[0].select_one(".answers__expected").get_text(strip=True) == ""
    header = item.select_one(".answers__parts--columned > .answers__header-row")
    assert [s.get_text(strip=True) for s in header.find_all(recursive=False)] == [
        "",
        "Odpowiedź ucznia",
        "Klucz",
    ]


def _outcome_quiz(course, pupil):
    quiz = _empty_quiz(course, "Outcomes")
    sub = _submitted(pupil, quiz, score=Decimal("1.5"), max_score=Decimal("4"))
    for fraction in ("1", "0.5", "0"):
        el = _add(quiz)
        _respond(
            sub, el, latest_answer="x", fraction=Decimal(fraction), attempt_count=1
        )
    _add(quiz)  # untouched -> not_answered
    return quiz


EXPECTED_BADGES = [
    ("is-correct", "badge--correct"),
    ("is-partial", "badge--partial"),
    ("is-incorrect", "badge--incorrect"),
    ("is-not_answered", "badge--muted"),
]


def test_t25_badge_modifier_per_outcome_on_both_verdict_pages(client):
    course, _factory_pupil = _owner_view(client)
    # _loginable_pupil is defined in Task B6; see its docstring
    pupil = _loginable_pupil(course, "outcomes")
    quiz = _outcome_quiz(course, pupil)
    items = _items(_soup(client.get(_url(course, pupil.pk, quiz.pk))))
    got = [
        (
            next(c for c in item["class"] if c.startswith("is-")),
            item.select_one(".answers__verdict .badge")["class"][1],
        )
        for item in items
    ]
    assert got == EXPECTED_BADGES
    client.force_login(pupil)
    resp = client.get(
        reverse(
            "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
        )
    )
    assert resp.status_code == 200
    student = [
        (
            next(c for c in li["class"] if c.startswith("is-")),
            li.select_one(".question__feedback-panel .badge")["class"][1],
        )
        for li in _soup(resp).select("li.quiz-results__item")
    ]
    assert student == EXPECTED_BADGES
