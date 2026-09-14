"""The per-question drill-down page (spec §3, §5; T30, T31, T31b, T33, T35-T39, T41).

Every PA/owner-viewed pupil gets an Enrollment row: reviewable_students serves
PA and owner from Enrollment alone, and GroupMembershipFactory creates none."""

from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import QuizSubmission
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
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


# --- header pill + Review link (full parity is T36, Task 7) -------------------
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
    links = status.select("a.answers__review")
    assert [a["href"] for a in links] == [
        reverse(
            "courses:manage_review_submission",
            kwargs={"slug": course.slug, "submission_pk": sub.pk},
        )
    ]


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
    assert [_badge(i).split(" (")[0] for i in items] == [
        "Awaiting review",
        "Awaiting review",
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
    text = (
        _soup(client.get(_url(course, pupil.pk, quiz.pk)))
        .select_one("section.answers")
        .get_text(" ", strip=True)
        .lower()
    )
    assert "your answer" not in text and "you chose" not in text


# --- T36 header parity ----------------------------------------------------------
def _breakdown_pill(soup, title):
    for unit in soup.select("div.breakdown-unit"):
        if unit.select_one(".breakdown-unit__title").get_text(strip=True) == title:
            return unit.select_one(".pill")
    raise AssertionError(f"no breakdown row titled {title!r}")


def test_t36_header_pill_matches_the_breakdown_pill(client):
    course, pupil = _owner_view(client)
    scored = _empty_quiz(course, "Q scored")
    _add(scored)
    _submitted(pupil, scored, score=Decimal("1"), max_score=Decimal("1"))
    ungraded = _empty_quiz(course, "Q ungraded")
    _submitted(pupil, ungraded, score=Decimal("0"), max_score=Decimal("0"))
    awaiting = _empty_quiz(course, "Q awaiting")
    _add(awaiting)
    _add(awaiting, ExtendedResponseQuestionElement, marking_mode=REVIEW)
    _submitted(pupil, awaiting, score=Decimal("1"), max_score=Decimal("1"))
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
    _submitted(pupil, live, status=QuizSubmission.Status.IN_PROGRESS)

    breakdown = _soup(
        client.get(
            reverse(
                "courses:manage_analytics_student",
                kwargs={"slug": course.slug, "student_pk": pupil.pk},
            )
        )
    )
    expected_kinds = {
        scored: "pill--scored",
        ungraded: "pill--submitted",
        awaiting: "pill--awaiting",
        reviewed: "pill--submitted",
        live: "pill--progress",
    }
    for quiz, kind in expected_kinds.items():
        header = _soup(client.get(_url(course, pupil.pk, quiz.pk))).select_one(
            ".answers__status .pill"
        )
        row = _breakdown_pill(breakdown, quiz.title)
        assert kind in header["class"], (quiz.title, header["class"])
        assert header["class"] == row["class"], quiz.title
        assert header.get_text(" ", strip=True) == row.get_text(" ", strip=True)
    awaiting_status = _soup(client.get(_url(course, pupil.pk, awaiting.pk))).select_one(
        ".answers__status"
    )
    assert len(awaiting_status.select("a.answers__review")) == 1
    assert "scored" not in awaiting_status.get_text(" ", strip=True)


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
