"""Task 6: viewer-conditional draft filtering on every student-facing call site.

Fixture specs, in the Task 5 style. OUT10 is the mutant the rest of the roster
(OUT1-4, ACC1, OUT5b) cannot catch: hard-coding drafts="hide" at the call sites
loses drafts for the AUTHOR too, and only a view-level, author-vs-student test
can see that.
"""

import pytest
from django.urls import reverse

from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from courses.rollups import units_under
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import NoteFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import UnitProgressFactory
from tests.factories import add_element
from tests.factories import make_login


@pytest.mark.django_db
def test_author_keeps_drafts_on_student_surfaces(client):
    """OUT10. One course, one Part, three lesson units A, B, C with B drafted.
    The author (course owner) still sees B on both the outline and unit-nav;
    the student does not.

    Mutant: hard-code drafts="hide" at the call sites instead of evaluating
    the viewer-conditional expression -> the author loses B on both surfaces.
    """
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    a = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=0,
        title="Unit-A",
    )
    b = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        title="Unit-B-Drafted",
        published=False,
    )
    c = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=2,
        title="Unit-C",
    )
    # make_login always mints a NEW user, so create+login the student now (this
    # switches the session away from owner), then switch back with force_login
    # (both users are already verified -- no allauth redirect risk either way).
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)

    outline_url = reverse("courses:course_outline", kwargs={"slug": course.slug})
    lesson_url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": a.pk}
    )

    # --- author ---
    client.force_login(owner)
    resp = client.get(outline_url)
    assert b.title in resp.content.decode()

    resp = client.get(lesson_url)
    assert resp.context["unit_nav"]["next"].pk == b.pk

    # --- student ---
    client.force_login(student)
    resp = client.get(outline_url)
    assert b.title not in resp.content.decode()

    resp = client.get(lesson_url)
    assert resp.context["unit_nav"]["next"].pk == c.pk


@pytest.mark.django_db
def test_author_sees_own_drafted_quiz_result(client):
    """Companion to OUT8, the author path at the SAME site (course_results,
    courses/views.py). After a quiz the author submitted to is drafted, their
    own results page still lists it -- only a non-author student's page
    drops the row (OUT8 covers that side).

    Mutant: hard-code drafts="hide" at course_results -> the author loses
    the row too.
    """
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", published=True
    )
    QuizSubmissionFactory(
        student=owner, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )

    quiz.published = False
    quiz.save(update_fields=["published"])

    resp = client.get(reverse("courses:course_results", kwargs={"slug": course.slug}))
    unit_pks = {row["unit"].pk for row in resp.context["summary"]["rows"]}
    assert quiz.pk in unit_pks


@pytest.mark.django_db
def test_author_reset_count_includes_drafted_units_state(client):
    """Companion to OUT6, the author path at the SAME site (progress_reset,
    courses/views.py). The author's OWN reset confirmation count includes
    practice state on a drafted unit; OUT6 covers a non-author student's
    count excluding it.

    Mutant: hard-code drafts="hide" at progress_reset -> the author's count
    silently narrows too.
    """
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    u1 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, order=0
    )
    u2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        published=False,
    )
    UnitProgressFactory(student=owner, unit=u1, element_state={"1": {"x": 1}})
    UnitProgressFactory(student=owner, unit=u2, element_state={"1": {"x": 1}})

    resp = client.get(
        reverse("courses:progress_reset_course", kwargs={"slug": course.slug})
    )
    assert resp.context["affected_count"] == 2


def _make_quiz_nav_fixture(client):
    """Course owned by `owner`, one Part holding three quiz units A (with one
    question), B (drafted), C. `owner` (author) and `student` (enrolled) are
    both created, and the client is left logged in as `owner`."""
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    qa = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=part,
        order=0,
        title="Quiz-A",
    )
    question = ShortTextQuestionElement.objects.create(stem="Q?", accepted="a")
    element = add_element(qa, question)
    qb = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=part,
        order=1,
        title="Quiz-B-Drafted",
        published=False,
    )
    qc = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="quiz",
        parent=part,
        order=2,
        title="Quiz-C",
    )
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    client.force_login(owner)
    return owner, student, course, qa, qb, qc, element


@pytest.mark.django_db
def test_author_quiz_unit_nav_steps_through_drafted_quiz(client):
    """Companion to OUT10, a second build_unit_nav call site (quiz_unit,
    courses/views.py). The author's unit_nav still steps from quiz A to
    drafted quiz B; the student's nav skips straight to C.

    Mutant: hard-code drafts="hide" at quiz_unit -> the author's next/prev
    jump straight from A to C too.
    """
    owner, student, course, qa, qb, qc, _element = _make_quiz_nav_fixture(client)
    quiz_url = reverse(
        "courses:quiz_unit", kwargs={"slug": course.slug, "node_pk": qa.pk}
    )

    client.force_login(owner)
    resp = client.get(quiz_url)
    assert resp.context["unit_nav"]["next"].pk == qb.pk

    client.force_login(student)
    resp = client.get(quiz_url)
    assert resp.context["unit_nav"]["next"].pk == qc.pk


@pytest.mark.django_db
def test_author_quiz_answer_rerender_nav_steps_through_drafted_quiz(client):
    """Companion to OUT10, a third build_unit_nav call site
    (_quiz_render_feedback, courses/views.py) -- the no-JS quiz-answer
    re-render, driven here with a plain POST carrying no
    X-Requested-With: fetch header. The author's re-rendered nav still steps
    through drafted quiz B; the student's skips it.

    Mutant: hard-code drafts="hide" at _quiz_render_feedback -> the author's
    re-rendered nav skips the draft too.
    """
    owner, student, course, qa, qb, qc, element = _make_quiz_nav_fixture(client)
    answer_url = reverse(
        "courses:quiz_answer",
        kwargs={"slug": course.slug, "node_pk": qa.pk, "element_pk": element.pk},
    )

    client.force_login(owner)
    resp = client.post(answer_url, {"answer": "a"})
    assert resp.context["unit_nav"]["next"].pk == qb.pk

    client.force_login(student)
    resp = client.post(answer_url, {"answer": "a"})
    assert resp.context["unit_nav"]["next"].pk == qc.pk


@pytest.mark.django_db
def test_author_notes_hub_shows_note_on_drafted_unit(client):
    """Companion to OUT10, a fourth, cross-app call site (the notes hub,
    notes/views.py). The author's own note on a drafted lesson unit still
    shows on their notes hub; a non-author student's own note on the same
    unit does not show on theirs.

    Mutant: hard-code drafts="hide" at the notes hub view -> the author's
    own note disappears too.
    """
    owner = make_login(client, "owner")
    course = CourseFactory(owner=owner)
    unit = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        published=False,
        title="Drafted-Lesson",
    )
    NoteFactory(author=owner, unit=unit, body="Owner note")

    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    NoteFactory(author=student, unit=unit, body="Student note")

    notes_url = reverse("notes:course_notes", kwargs={"slug": course.slug})

    client.force_login(owner)
    resp = client.get(notes_url)
    unit_pks = {row["unit"].pk for row in resp.context["units"]}
    assert unit.pk in unit_pks

    client.force_login(student)
    resp = client.get(notes_url)
    unit_pks = {row["unit"].pk for row in resp.context["units"]}
    assert unit.pk not in unit_pks


@pytest.mark.django_db
def test_reset_count_excludes_drafts_on_both_branches(client):
    """OUT6. Two lesson units under a Part, both holding practice state; one
    is drafted. Both the course-wide reset confirmation AND the node-scoped
    one (reversed against the parent Part) must report 1, not 2.

    Mutant: filter units_under but leave units_in_order unfiltered -> the
    course-wide branch, the commonly used one, still reports 2.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    u1 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, order=0
    )
    u2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        published=False,
    )
    UnitProgressFactory(student=student, unit=u1, element_state={"1": {"x": 1}})
    UnitProgressFactory(student=student, unit=u2, element_state={"1": {"x": 1}})

    course_url = reverse("courses:progress_reset_course", kwargs={"slug": course.slug})
    resp = client.get(course_url)
    assert resp.context["affected_count"] == 1

    node_url = reverse(
        "courses:progress_reset", kwargs={"slug": course.slug, "node_pk": part.pk}
    )
    resp = client.get(node_url)
    assert resp.context["affected_count"] == 1


@pytest.mark.django_db
def test_reset_post_still_clears_a_drafted_units_state(client):
    """OUT6b. Same fixture as OUT6; POSTing the course-wide reset must still
    clear the DRAFTED unit's element_state.

    Mutant: filter `targets` rather than only the count -> the drafted unit
    keeps its state, which resurfaces on republish. Without this assertion
    the safe and unsafe implementations are indistinguishable, since OUT6
    alone is green on both.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    part = ContentNodeFactory(course=course, kind="part", parent=None, unit_type=None)
    u1 = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=part, order=0
    )
    u2 = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        parent=part,
        order=1,
        published=False,
    )
    UnitProgressFactory(student=student, unit=u1, element_state={"1": {"x": 1}})
    UnitProgressFactory(student=student, unit=u2, element_state={"1": {"x": 1}})

    course_url = reverse("courses:progress_reset_course", kwargs={"slug": course.slug})
    resp = client.post(course_url, {})
    assert resp.status_code == 302

    progress2 = UnitProgress.objects.get(student=student, unit=u2)
    assert progress2.element_state == {}


@pytest.mark.django_db
def test_student_results_drops_a_drafted_quiz_they_submitted_to(client):
    """OUT8. A published quiz unit the student submitted to; the author then
    drafts it. The student's course_results page must no longer carry a row
    for it.

    Mutant: put the keep-with-data filter inside build_course_results instead
    of in each caller -> the student's own submission keeps the row alive for
    them. This is the one call site where "holds data" and "the viewer is a
    student" are true at once.
    """
    course = CourseFactory()
    student = make_login(client, "student")
    EnrollmentFactory(student=student, course=course)
    quiz = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", published=True
    )
    QuizSubmissionFactory(
        student=student, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )

    quiz.published = False
    quiz.save(update_fields=["published"])

    resp = client.get(reverse("courses:course_results", kwargs={"slug": course.slug}))
    unit_pks = {row["unit"].pk for row in resp.context["summary"]["rows"]}
    assert quiz.pk not in unit_pks


@pytest.mark.django_db
def test_all_draft_course_is_absent_from_the_catalogue(client):
    """OUT9. An open-visibility course whose only units are drafted must not
    appear in the catalogue for a non-enrolled student. Publishing one of the
    units makes it appear. catalog_detail's unit_count must also count only
    published units -- a course with one published unit and several drafts
    must not advertise the drafted ones.

    Mutant: leave the Exists(... kind="unit") subquery without published=True.
    """
    course = CourseFactory(visibility="open")
    student = make_login(client, "student")
    units = [
        ContentNodeFactory(
            course=course, kind="unit", unit_type="lesson", published=False
        )
        for _ in range(9)
    ]

    resp = client.get(reverse("courses:catalog"))
    assert course.pk not in {c.pk for c in resp.context["courses"]}

    units[0].published = True
    units[0].save(update_fields=["published"])

    resp = client.get(reverse("courses:catalog"))
    assert course.pk in {c.pk for c in resp.context["courses"]}

    resp = client.get(reverse("courses:catalog_detail", kwargs={"slug": course.slug}))
    assert resp.context["unit_count"] == 1


@pytest.mark.django_db
def test_units_under_hides_a_draft_unit_passed_directly():
    """units_under short-circuits with `if node.kind == UNIT: return {node}`
    before its stack walk, and that early-return branch is predicate-guarded
    but had NO test until now -- Task 5's fixtures only ever passed containers
    into units_under."""
    course = CourseFactory()
    draft_unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", published=False
    )
    assert units_under(draft_unit, drafts="hide") == set()
