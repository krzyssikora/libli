"""Task 12: the confirm strip and no-JS interstitial -- real counts, the four
copy variants, and the quiz warning. Task 11 already covers the strip's
mechanics (WR13, WR18); this file covers what it renders.
"""

import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UserFactory
from tests.factories import make_login
from tests.factories import make_quiz_unit

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _setup(client):
    owner = make_login(client, "owner")
    course = CourseFactory(slug="c1", owner=owner)
    return owner, course


def _tok(node):
    return node.updated.isoformat()


def _url(course):
    return reverse("courses:manage_node_flag", kwargs={"slug": course.slug})


@pytest.mark.django_db
def test_qz5_quiz_hide_confirmation_depends_on_submissions_and_names_the_count(
    client,
):
    """QZ5: unpublishing a quiz WITH submissions opens the confirm strip;
    unpublishing one WITHOUT submissions applies immediately. One test, both
    halves. Extended (per the Task 12 brief) to assert the quiz-variant COPY
    -- not just which response comes back -- so it reddens against THIS
    task's deliverable rather than only Task 11's routing, which already
    made the bare "which response" half green."""
    _, course = _setup(client)

    quiz_with = make_quiz_unit(course=course, title="Test 2", published=True)
    s1, s2 = UserFactory(), UserFactory()
    QuizSubmissionFactory(
        unit=quiz_with, student=s1, status=QuizSubmission.Status.SUBMITTED
    )
    QuizSubmissionFactory(
        unit=quiz_with, student=s2, status=QuizSubmission.Status.SUBMITTED
    )
    s3 = UserFactory()
    QuizSubmissionFactory(
        unit=quiz_with, student=s3, status=QuizSubmission.Status.IN_PROGRESS
    )

    resp = client.get(
        _url(course),
        {
            "node": quiz_with.pk,
            "flag": "published",
            "value": "0",
            "scope": "node",
            "token": _tok(quiz_with),
        },
        **FETCH,
    )
    assert resp.status_code == 200
    assert any(t.name == "courses/manage/_flag_strip.html" for t in resp.templates)
    html = resp.content.decode()
    assert "2 students have submitted." in html
    assert "1 student is part-way through." in html
    quiz_with.refresh_from_db()
    assert quiz_with.published is True  # unwritten -- the strip, not the write

    quiz_without = make_quiz_unit(course=course, title="Test 3", published=True)
    resp2 = client.post(
        _url(course),
        {
            "node": quiz_without.pk,
            "flag": "published",
            "value": "0",
            "scope": "node",
            "token": _tok(quiz_without),
        },
        **FETCH,
    )  # no confirmed=1 -- needs_confirmation must be False for this quiz
    assert resp2.status_code == 200
    assert 'data-scope="top"' in resp2.content.decode()
    quiz_without.refresh_from_db()
    assert quiz_without.published is False


@pytest.mark.django_db
def test_qz10_hiding_a_chapter_aggregates_the_quiz_warning_over_the_subtree(client):
    """QZ10: hiding a CHAPTER containing a quiz with submissions shows the
    submission warning, counts aggregated over the subtree. Mutant: render
    the plain container copy -> the CA takes students' results out of reach
    with no warning, on the higher-blast-radius path. QZ5 is unit-scope and
    green without this."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter", title="Ch3")
    ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=True
    )
    quiz = make_quiz_unit(course=course, parent=chapter, title="Quiz", published=True)
    s1, s2 = UserFactory(), UserFactory()
    QuizSubmissionFactory(unit=quiz, student=s1, status=QuizSubmission.Status.SUBMITTED)
    QuizSubmissionFactory(unit=quiz, student=s2, status=QuizSubmission.Status.SUBMITTED)

    resp = client.get(
        _url(course),
        {"node": chapter.pk, "flag": "published", "scope": "subtree"},
        **FETCH,
    )
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "2 students have submitted." in html


@pytest.mark.django_db
def test_tree11_container_anchor_carries_no_value_and_strip_numbers_are_correct(
    client,
):
    """TREE11: a container anchor's href carries NO `value`; following it
    returns the mixed strip, and the strip's rendered numbers are correct
    (5 units, 2 live -> the strip says "5" and "2 are live"). Mutant A:
    require `value` on GET -> every container anchor 422s. Mutant B: count
    over the restricted set or over all nodes rather than units."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter", title="Ch3")
    for i in range(5):
        ContentNodeFactory(
            course=course,
            parent=chapter,
            kind="unit",
            unit_type="lesson",
            published=(i < 2),
        )

    resp = client.get(
        _url(course),
        {"node": chapter.pk, "flag": "published", "scope": "subtree"},  # no value
        **FETCH,
    )
    assert resp.status_code == 200  # mutant A: this would be 422
    html = resp.content.decode()
    assert "Publish or hide 5" in html
    assert "2 are live, 3 are drafts." in html


@pytest.mark.django_db
def test_quiz_warning_quiet_vs_loud_copy_selection(client):
    """The quiet/loud split, or `is_quiet` is exercised only by QZ1-QZ4 in
    isolation and its wiring into the strip is unpinned. All submitters in
    an archived group -> the quiet note; add one submitter in a live group
    -> the loud lines, and the quiet note must NOT also render."""
    _, course = _setup(client)
    quiz = make_quiz_unit(course=course, title="Test 2", published=True)
    archived_group = GroupFactory(course=course, archived=True)
    quiet_student = UserFactory()
    GroupMembershipFactory(group=archived_group, student=quiet_student)
    QuizSubmissionFactory(
        unit=quiz, student=quiet_student, status=QuizSubmission.Status.SUBMITTED
    )

    resp = client.get(
        _url(course),
        {"node": quiz.pk, "flag": "published", "value": "0", "scope": "node"},
        **FETCH,
    )
    html = resp.content.decode()
    assert "all from archived groups" in html
    assert "have submitted" not in html

    live_group = GroupFactory(course=course, archived=False)
    loud_student = UserFactory()
    GroupMembershipFactory(group=live_group, student=loud_student)
    QuizSubmissionFactory(
        unit=quiz, student=loud_student, status=QuizSubmission.Status.SUBMITTED
    )

    resp2 = client.get(
        _url(course),
        {"node": quiz.pk, "flag": "published", "value": "0", "scope": "node"},
        **FETCH,
    )
    html2 = resp2.content.decode()
    assert "have submitted" in html2
    assert "all from archived groups" not in html2


@pytest.mark.django_db
def test_no_js_container_interstitial_round_trip_writes(client):
    """Task 11's carried-forward defect: the minimal templates emitted
    `value` only `{% if value %}`, but a container's GET anchor sends NO
    `value` by design (a mixed container derives both directions from
    counts) -- so confirming the no-JS interstitial for a mixed container
    POSTed without `value` and hit "Missing value." 422. `value` now rides
    on the two submit buttons instead of a hidden input. GET the
    interstitial as a non-fetch request, then POST what its form actually
    contains, and assert the write lands."""
    _, course = _setup(client)
    chapter = ContentNodeFactory(course=course, kind="chapter", title="Ch3")
    live = ContentNodeFactory(
        course=course, parent=chapter, kind="unit", unit_type="lesson", published=True
    )
    draft = ContentNodeFactory(
        course=course,
        parent=chapter,
        kind="unit",
        unit_type="lesson",
        published=False,
    )

    resp = client.get(
        _url(course), {"node": chapter.pk, "flag": "published", "scope": "subtree"}
    )  # no fetch header -> no-JS path; no value -> mixed container's anchor shape
    assert resp.status_code == 200
    assert any(
        t.name == "courses/manage/node_confirm_flag.html" for t in resp.templates
    )
    html = resp.content.decode()
    assert 'name="value" value="0"' in html  # the Hide button really is there

    resp2 = client.post(
        _url(course),
        {
            "node": chapter.pk,
            "flag": "published",
            "value": "0",  # what the Hide button actually posts
            "scope": "subtree",
            "token": _tok(chapter),
            "confirmed": "1",
        },
    )  # no fetch header -> the no-JS redirect path
    assert resp2.status_code == 302

    live.refresh_from_db()
    draft.refresh_from_db()
    assert live.published is False
    assert draft.published is False
