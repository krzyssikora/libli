"""Task 15: the unit-settings Published checkbox and the three draft/submission
banners.

WR6/WR17/WR10 pin the settings form and the banner-form plumbing; OUT5c and
QZ6 pin the two editor-page banners; QZ7/QZ8/QZ9 are written here because this
is where the quiz surfaces are assembled, but are implemented by earlier
tasks (Tasks 3, 6 and 11) and are green on arrival.
"""

import pytest
from django.urls import reverse

from courses.models import QuestionResponse
from courses.models import QuizSubmission
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import GroupMembershipFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import ShortTextQuestionElement
from tests.factories import UserFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _tok(node):
    return node.updated.isoformat()


def _flag_url(course):
    return reverse("courses:manage_node_flag", kwargs={"slug": course.slug})


def _editor_url(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.mark.django_db
def test_wr6_settings_form_round_trips_published_including_unchecking(client):
    """WR6: the unit-settings form round-trips `published`, both directions --
    checking it AND unchecking it (absent-means-false, like `obligatory`)."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="wr6", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False, title="U"
    )
    url = reverse("courses:manage_node_rename", kwargs={"slug": course.slug})

    resp = client.post(
        url,
        {
            "node": unit.pk,
            "token": _tok(unit),
            "has_settings": "1",
            "ctx": "editor",
            "title": unit.title,
            "published": "on",
        },
    )
    assert resp.status_code == 302
    unit.refresh_from_db()
    assert unit.published is True

    resp2 = client.post(
        url,
        {
            "node": unit.pk,
            "token": _tok(unit),
            "has_settings": "1",
            "ctx": "editor",
            "title": unit.title,
            # "published" absent -- must turn it back off
        },
    )
    assert resp2.status_code == 302
    unit.refresh_from_db()
    assert unit.published is False


@pytest.mark.django_db
def test_wr17_banner_form_renders_required_hidden_inputs(client):
    """WR17 (second half): the draft banner's own <form> actually renders
    flag/value/scope/ctx as hidden inputs -- without them every click 422s."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="wr17", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False, title="U"
    )
    resp = client.get(_editor_url(course, unit))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert 'name="flag" value="published"' in html
    assert 'name="value" value="1"' in html
    assert 'name="scope" value="node"' in html
    assert 'name="ctx" value="editor"' in html


@pytest.mark.django_db
def test_wr10_ctx_editor_redirects_to_manage_editor_not_the_builder(client):
    """WR10 (ctx=editor arm): the draft banner's Publish, posted from the
    editor page, redirects to manage_editor. Mutant: let `_wants_fragment`
    decide instead of `ctx` -- the banner posts are ordinary no-JS-shaped
    forms, so `_wants_fragment` is false and the author lands on the
    builder instead."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="wr10a", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False, title="U"
    )
    resp = client.post(
        _flag_url(course),
        {
            "node": unit.pk,
            "token": _tok(unit),
            "flag": "published",
            "value": "1",
            "scope": "node",
            "ctx": "editor",
        },
    )
    assert resp.status_code == 302
    assert resp.url == _editor_url(course, unit)
    unit.refresh_from_db()
    assert unit.published is True


@pytest.mark.django_db
def test_wr10_ctx_unit_redirects_to_the_unit_url_on_success_and_on_conflict(client):
    """WR10 (ctx=unit arm): the draft banner's Publish, posted from the
    student-facing render by an author, redirects back to the SAME unit URL
    -- on a clean write, and on a stale-token conflict too. Kept separate
    from the ctx=editor arm (see WR10's brief): this is the only test that
    drives the ctx=unit response-contract column."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="wr10b", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False, title="U"
    )
    expected = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    good_token = _tok(unit)

    resp = client.post(
        _flag_url(course),
        {
            "node": unit.pk,
            "token": good_token,
            "flag": "published",
            "value": "1",
            "scope": "node",
            "ctx": "unit",
        },
    )
    assert resp.status_code == 302
    assert resp.url == expected
    unit.refresh_from_db()
    assert unit.published is True

    # good_token is now stale -- a second POST against it must 409-redirect,
    # still to the unit URL, and must not write.
    resp2 = client.post(
        _flag_url(course),
        {
            "node": unit.pk,
            "token": good_token,
            "flag": "published",
            "value": "0",
            "scope": "node",
            "ctx": "unit",
        },
    )
    assert resp2.status_code == 302
    assert resp2.url == expected
    unit.refresh_from_db()
    assert unit.published is True  # unwritten


@pytest.mark.django_db
def test_out5c_editor_page_renders_draft_banner_for_draft_only(client):
    """OUT5c: the editor page renders the draft banner for a draft unit, and
    not for a published one. Nothing else covers the editor-page banner --
    E2E3 covers only the student render, WR17 only the redirect."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="out5c", owner=owner)
    draft = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False, title="Draft"
    )
    live = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=True, title="Live"
    )

    resp = client.get(_editor_url(course, draft))
    assert "Draft — not visible to students" in resp.content.decode()

    resp2 = client.get(_editor_url(course, live))
    assert "Draft — not visible to students" not in resp2.content.decode()


@pytest.mark.django_db
def test_draft_quiz_unit_get_renders_the_banner_for_its_author(client):
    """Fix round 1, IMPORTANT 1: the extended E2E3 only drives the
    `lesson_unit` GET path -- nothing anywhere renders a draft QUIZ for its
    author and checks for the banner. This pins the banner's presence on
    `quiz_unit`'s own render (`courses/views.py:1372`) specifically.

    NOT an `is_author`-isolation test: `is_author` is currently redundant
    with `not unit.published` on every reachable path, because
    `get_node_or_404(..., viewer=request.user, ...)` already 404s a
    non-author before this template is ever reached. This test cannot (and
    does not try to) prove the flag itself gates anything -- it proves the
    banner block exists and is wired into `quiz_unit`'s context at all,
    which was previously unverified on this path."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="quizauthorbanner", owner=owner)
    quiz = make_quiz_unit(course=course, title="Quiz", published=False)

    url = reverse("courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": quiz.pk})
    resp = client.get(url)
    assert resp.status_code == 200
    assert "Draft — not visible to students" in resp.content.decode()


@pytest.mark.django_db
def test_draft_quiz_no_js_answer_rerender_renders_the_banner_for_its_author(client):
    """Fix round 1, IMPORTANT 1: the no-JS `quiz_answer` re-render
    (`_quiz_render_feedback`, `courses/views.py:1405`) is the path the
    brief specifically flagged as easy to miss, because it builds its own
    context from `request` rather than reusing a shared helper. Nothing
    exercised it before this test.

    NOT an `is_author`-isolation test, for the same reason as the GET test
    above -- it pins the banner's presence on THIS render path, not the
    flag in isolation."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="quizanswerbanner", owner=owner)
    quiz = make_quiz_unit(course=course, title="Quiz", published=False)
    question = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris"
    )
    element = add_element(quiz, question)

    url = reverse(
        "courses:quiz_answer",
        kwargs={"slug": course.slug, "node_pk": quiz.pk, "element_pk": element.pk},
    )
    resp = client.post(url, {"answer": "Paris"})  # no fetch header -> no-JS re-render
    assert resp.status_code == 200
    assert "Draft — not visible to students" in resp.content.decode()


@pytest.mark.django_db
def test_qz6_in_progress_only_editor_banner_says_part_way_not_submitted(client):
    """QZ6: in-progress rows are counted on their own line, never as
    "submitted". A published quiz with only an IN_PROGRESS row must still
    carry the editor banner (Mutant B: trigger on SUBMITTED only -> no
    banner at all, and unchecking Published below strands the attempt in
    silence), and must not claim anyone submitted (Mutant A: count every row
    into the submitted figure)."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="qz6", owner=owner)
    quiz = make_quiz_unit(course=course, title="Quiz", published=True)
    student = UserFactory()
    QuizSubmissionFactory(
        unit=quiz, student=student, status=QuizSubmission.Status.IN_PROGRESS
    )

    resp = client.get(_editor_url(course, quiz))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "1 student is part-way through." in html
    assert "has submitted" not in html
    assert "have submitted" not in html


@pytest.mark.django_db
def test_editor_banner_quiet_vs_loud_copy_selection(client):
    """The editor banner is `is_quiet`'s SECOND consumer (the strip is the
    first, Task 12). Nothing else pins this banner's loud/quiet choice:
    QZ1-QZ4 test the predicate in isolation and Task 12's split test covers
    only the strip."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="qzquiet", owner=owner)
    quiz = make_quiz_unit(course=course, title="Quiz", published=True)
    archived_group = GroupFactory(course=course, archived=True)
    quiet_student = UserFactory()
    GroupMembershipFactory(group=archived_group, student=quiet_student)
    QuizSubmissionFactory(
        unit=quiz, student=quiet_student, status=QuizSubmission.Status.SUBMITTED
    )

    resp = client.get(_editor_url(course, quiz))
    html = resp.content.decode()
    assert "all from archived groups" in html
    assert "student has submitted" not in html

    live_group = GroupFactory(course=course, archived=False)
    loud_student = UserFactory()
    GroupMembershipFactory(group=live_group, student=loud_student)
    QuizSubmissionFactory(
        unit=quiz, student=loud_student, status=QuizSubmission.Status.SUBMITTED
    )

    resp2 = client.get(_editor_url(course, quiz))
    html2 = resp2.content.decode()
    assert "have submitted" in html2
    assert "all from archived groups" not in html2


@pytest.mark.django_db
def test_qz7_student_404s_on_quiz_results_and_row_gone_from_course_results(client):
    """QZ7: a student who submitted 404s on `quiz_results` while the quiz is
    drafted, and the row is gone from their `course_results`. Both halves in
    one test. Already implemented (Tasks 3 and 6); the RED gate for it lives
    in Step 4's falsification, not in this file's baseline run."""
    course = CourseFactory(slug="qz7")
    quiz = make_quiz_unit(course=course, title="Quiz", published=True)
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    QuizSubmissionFactory(
        unit=quiz, student=student, status=QuizSubmission.Status.SUBMITTED
    )

    quiz.published = False
    quiz.save(update_fields=["published"])

    results_url = reverse(
        "courses:quiz_results", kwargs={"slug": course.slug, "node_pk": quiz.pk}
    )
    resp = client.get(results_url)
    assert resp.status_code == 404

    course_results_url = reverse("courses:course_results", kwargs={"slug": course.slug})
    resp2 = client.get(course_results_url)
    assert resp2.status_code == 200
    unit_pks = [r["unit"].pk for r in resp2.context["summary"]["rows"]]
    assert quiz.pk not in unit_pks


@pytest.mark.django_db
def test_qz8_in_progress_only_quiz_still_gets_confirm_strip_on_unpublish(client):
    """QZ8: a quiz with ONLY in-progress attempts still gets a confirm strip
    on unpublish, reporting the in-progress count. Already implemented
    (Task 11's ANY-status `needs_confirmation`); falsified in Step 4."""
    owner = make_login(client, "owner")
    course = CourseFactory(slug="qz8", owner=owner)
    quiz = make_quiz_unit(course=course, title="Quiz", published=True)
    QuizSubmissionFactory(unit=quiz, status=QuizSubmission.Status.IN_PROGRESS)

    resp = client.post(
        _flag_url(course),
        {
            "node": quiz.pk,
            "token": _tok(quiz),
            "flag": "published",
            "value": "0",
            "scope": "node",
        },
        **FETCH,
    )
    assert resp.status_code == 200
    assert any(t.name == "courses/manage/_flag_strip.html" for t in resp.templates)
    html = resp.content.decode()
    assert "1 student is part-way through." in html
    quiz.refresh_from_db()
    assert quiz.published is True  # unwritten -- the strip, not the write


@pytest.mark.django_db
def test_qz9_interrupted_attempt_resumes_on_republication(client):
    """QZ9: an interrupted attempt resumes on republication -- same
    `QuizSubmission`/`QuestionResponse`, answers intact, no second row.
    Already implemented (pre-existing `quiz_unit`/`quiz_answer` behaviour,
    gated by Task 3's `viewer=`); falsified in Step 4."""
    course = CourseFactory(slug="qz9")
    quiz = make_quiz_unit(course=course, title="Quiz", published=True)
    question = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=None
    )
    element = add_element(quiz, question)
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)

    answer_url = reverse(
        "courses:quiz_answer",
        kwargs={"slug": course.slug, "node_pk": quiz.pk, "element_pk": element.pk},
    )

    resp = client.post(answer_url, {"answer": "Wrong one"})
    assert resp.status_code == 200
    submission = QuizSubmission.objects.get(student=student, unit=quiz)
    response = QuestionResponse.objects.get(submission=submission, element=element)
    assert response.attempt_count == 1
    assert response.latest_answer == "Wrong one"

    quiz.published = False
    quiz.save(update_fields=["published"])

    # Stranded: the endpoint 404s and the response is untouched.
    resp2 = client.post(answer_url, {"answer": "Wrong two"})
    assert resp2.status_code == 404
    response.refresh_from_db()
    assert response.attempt_count == 1
    assert response.latest_answer == "Wrong one"
    assert QuizSubmission.objects.filter(student=student, unit=quiz).count() == 1

    quiz.published = True
    quiz.save(update_fields=["published"])

    # Resumes on republication: SAME submission/response rows, answer updates.
    resp3 = client.post(answer_url, {"answer": "Wrong two"})
    assert resp3.status_code == 200
    assert QuizSubmission.objects.filter(student=student, unit=quiz).count() == 1
    assert (
        QuestionResponse.objects.filter(submission=submission, element=element).count()
        == 1
    )
    response.refresh_from_db()
    assert response.attempt_count == 2
    assert response.latest_answer == "Wrong two"
    assert QuizSubmission.objects.get(pk=submission.pk).pk == submission.pk
