import pytest
from django.urls import reverse
from django.utils import translation

from courses.models import QuizSubmission
from courses.models import ShortTextQuestionElement
from courses.rendering import unit_edit_context
from notes.models import NOTE_MAX_LEN
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import ElementFactory
from tests.factories import EnrollmentFactory
from tests.factories import GroupFactory
from tests.factories import QuizSubmissionFactory
from tests.factories import add_element
from tests.factories import make_ca
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.factories import make_teacher


def _lesson_unit(course):
    """A top-level lesson unit. Factored out to keep every call under 88 chars."""
    return ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )


@pytest.mark.django_db
def test_owner_without_change_course_perm_gets_the_link(client):
    """Ownership ALONE must grant the link. The actor deliberately holds no
    courses.change_course: built with make_pa this row would pass via the
    permission branch and never exercise `owner_id == user.id`, so deleting the
    ownership check outright would leave it green."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    ctx = unit_edit_context(owner, unit)

    assert ctx["can_edit_unit"] is True
    assert ctx["unit_editor_url"] == reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    # The predicate identity, TESTED rather than merely asserted in a docstring:
    # follow the URL. `can_edit_unit` is only a safe gate while it stays exactly
    # what views_manage.editor enforces; if a future change adds a gate there,
    # this is the row that notices instead of shipping a link that 403s.
    assert client.get(ctx["unit_editor_url"]).status_code == 200


@pytest.mark.django_db
def test_platform_admin_non_owner_gets_the_link(client):
    """A PA holds courses.change_course, so the permission branch grants it on
    every course — including one they do not own."""
    pa = make_pa(client, "pa")
    # is_staff deliberately NOT set here, unlike the CA and teacher rows below.
    # Production PAs are is_staff too, but this row is asserting the
    # courses.change_course branch: setting is_staff would make it indistinguishable
    # under Step 5b's is_staff-broadening mutation, which expects this row GREEN.
    course = CourseFactory()  # owner is None
    unit = _lesson_unit(course)

    ctx = unit_edit_context(pa, unit)

    assert ctx["can_edit_unit"] is True


@pytest.mark.django_db
def test_course_admin_non_owner_does_not_get_the_link(client):
    """THE row this design rests on. The Course Admin role group holds
    grouping.change_group, NOT courses.change_course — so a CA who does not own
    the course gets nothing. Adding courses.change_course to the CA role, or
    broadening the predicate to is_staff, must break here."""
    ca = make_ca(client, "ca")
    # is_staff must be set BY HAND. _make_role is only make_login + groups.add;
    # it never calls accounts.services.set_user_role, which is the sole place
    # is_staff is synced — so make_ca() alone yields is_staff=False while the
    # production Course Admin has role_is_staff(COURSE_ADMIN) is True. Without
    # this line the fixture does not model the actor the docstring claims, and
    # Step 5's is_staff mutation would leave this row GREEN.
    ca.is_staff = True
    ca.save(update_fields=["is_staff"])
    course = CourseFactory()
    unit = _lesson_unit(course)
    # Inert here, and deliberately kept: unit_edit_context is request-free and
    # consults only can_manage_course (owner_id + courses.change_course), so no
    # enrollment can change this row's outcome. It mirrors the spec's matrix row,
    # where enrollment IS load-bearing (it keeps the page-level actor off a 403).
    EnrollmentFactory(student=ca, course=course)

    ctx = unit_edit_context(ca, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None
    # The other half of the predicate identity (see the owner row): the URL this
    # actor is NOT given must genuinely refuse them.
    editor_url = reverse(
        "courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk}
    )
    assert client.get(editor_url).status_code == 403


@pytest.mark.django_db
def test_course_admin_who_owns_the_course_gets_the_link(client):
    """The other half of the pair: a CA reaches this link through OWNERSHIP
    alone, which is also how they come to see the course under Groups at all."""
    ca = make_ca(client, "ca2")
    course = CourseFactory(owner=ca)
    unit = _lesson_unit(course)

    ctx = unit_edit_context(ca, unit)

    assert ctx["can_edit_unit"] is True


@pytest.mark.django_db
def test_group_teacher_with_read_access_does_not_get_the_link(client):
    """A read-access actor who must NOT get the link.

    Two things make this row work, and neither is the one you would guess:

    - `is_staff = True` is LOAD-BEARING, for Step 5b's mutation. It also means the
      actor passes can_access_course on the STAFF branch: accessible_courses
      short-circuits with `if user.is_staff: return Course.objects.all()` before
      the groups__teachers clause is ever evaluated.
    - Because of that short-circuit the group scaffolding below does NOT drive the
      outcome. It is kept to mirror the spec's matrix row (a real group teacher on
      a non-archived group of THIS course), not to grant access.

    Do not "simplify" by deleting `is_staff = True` to restore the group as the
    access route — that is precisely what Step 5b's mutation depends on.
    """
    teacher = make_teacher(client, "teach")
    teacher.is_staff = True  # load-bearing; see the docstring
    teacher.save(update_fields=["is_staff"])
    course = CourseFactory()
    unit = _lesson_unit(course)
    group = GroupFactory(course=course, archived=False)
    group.teachers.add(teacher)

    ctx = unit_edit_context(teacher, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None


@pytest.mark.django_db
def test_enrolled_student_does_not_get_the_link(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    unit = _lesson_unit(course)
    EnrollmentFactory(student=student, course=course)

    ctx = unit_edit_context(student, unit)

    assert ctx["can_edit_unit"] is False
    assert ctx["unit_editor_url"] is None


def _editor_href(course, unit):
    return reverse("courses:manage_editor", kwargs={"slug": course.slug, "pk": unit.pk})


@pytest.mark.django_db
def test_lesson_unit_shows_the_link_to_the_owner(client):
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, unit) in body
    # The whole anchor, not just the URL: the new-tab behaviour IS the feature's
    # ergonomic premise ("the walkthrough stays where it is"), so losing
    # target="_blank" would ship green while destroying the reader's place.
    assert 'target="_blank"' in body
    assert 'rel="noopener"' in body


@pytest.mark.django_db
def test_lesson_unit_hides_the_link_from_an_enrolled_student(client):
    """The actor MUST be enrolled. A bare make_student gets 403 before any
    template renders, and the assertion would then pass for the wrong reason —
    staying green even if the {% if can_edit_unit %} guard were deleted."""
    student = make_student(client, "stu")
    course = CourseFactory()
    unit = _lesson_unit(course)
    EnrollmentFactory(student=student, course=course)

    resp = client.get(f"/courses/{course.slug}/u/{unit.pk}/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, unit) not in body
    # Both assertions are required and neither catches the other's mutation:
    # inverting the predicate is caught by the href; deleting the template guard
    # is caught ONLY here, because an unguarded anchor renders href="None",
    # which does not contain the reversed manage_editor URL.
    assert "unit-strip__edit" not in body


@pytest.mark.django_db
def test_quiz_unit_shows_the_link_to_the_owner(client):
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = make_quiz_unit(course=course)

    # No submission for this actor: quiz_unit redirects to quiz_results once one
    # is SUBMITTED.
    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/")

    assert resp.status_code == 200
    assert _editor_href(course, quiz) in resp.content.decode()


@pytest.mark.django_db
def test_quiz_unit_hides_the_link_from_an_enrolled_student(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    quiz = make_quiz_unit(course=course)
    EnrollmentFactory(student=student, course=course)

    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, quiz) not in body
    assert "unit-strip__edit" not in body


@pytest.mark.django_db
def test_quiz_results_shows_the_link_to_the_owner(client):
    """quiz_results filters submissions by student=request.user and REDIRECTS to
    quiz_unit when there is none — and the owner, being non-enrolled, never
    accumulates one naturally. All three kwargs are required: the factory
    defaults `unit` to a brand-new quiz unit in a brand-new course, and `status`
    to IN_PROGRESS."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = make_quiz_unit(course=course)
    QuizSubmissionFactory(
        student=owner, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )

    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/results/")

    # Assert we landed on quiz_results, not on a 302 to quiz_unit (which also
    # renders the strip and would pass the body assertion against the wrong page).
    assert resp.status_code == 200
    assert _editor_href(course, quiz) in resp.content.decode()


@pytest.mark.django_db
def test_quiz_results_hides_the_link_from_an_enrolled_student(client):
    student = make_student(client, "stu")
    course = CourseFactory()
    quiz = make_quiz_unit(course=course)
    EnrollmentFactory(student=student, course=course)
    QuizSubmissionFactory(
        student=student, unit=quiz, status=QuizSubmission.Status.SUBMITTED
    )

    resp = client.get(f"/courses/{course.slug}/u/{quiz.pk}/quiz/results/")

    assert resp.status_code == 200
    body = resp.content.decode()
    assert _editor_href(course, quiz) not in body
    assert "unit-strip__edit" not in body


@pytest.mark.django_db
def test_check_answer_nojs_rerender_carries_the_link(client):
    """full_lesson_render_context covers the check_answer POST re-render, not just
    the lesson_unit GET. Fixture shape copied from
    tests/test_courses_views.py::test_check_answer_nojs_rerender_includes_unit_nav,
    with owner= added."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)
    q = ShortTextQuestionElement.objects.create(
        stem="2+2?", accepted="4", marking_mode="A", max_marks=1
    )
    el = add_element(unit, q)
    EnrollmentFactory(student=owner, course=course)

    # No X-Requested-With header -> full-page no-JS re-render.
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/q/{el.pk}/check/", {"answer": "5"}
    )

    assert resp.status_code == 200
    assert _editor_href(course, unit) in resp.content.decode()


@pytest.mark.django_db
def test_notes_invalid_nojs_422_rerender_carries_the_link(client):
    """The notes no-JS validation re-render returns 422 BY DESIGN — assert that,
    not 200. This is the path a manager hits while annotating during the very
    walkthrough this feature serves. Fixture shape from test_notes_views.py's
    test_create_note_invalid_no_js_422_repopulates_rejected_text."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)
    el = ElementFactory(unit=unit)
    EnrollmentFactory(student=owner, course=course)

    # Over-cap body (NOT a blank one — that is a different validation branch).
    resp = client.post(
        f"/courses/{course.slug}/u/{unit.pk}/notes/add/",
        {"element": el.pk, "body": "z" * (NOTE_MAX_LEN + 1)},
    )

    assert resp.status_code == 422
    assert _editor_href(course, unit) in resp.content.decode()


@pytest.mark.django_db
def test_quiz_answer_nojs_rerender_carries_the_link(client):
    """build_quiz_context covers _quiz_render_feedback's no-JS full re-render, not
    just the quiz_unit GET. No precedent exists to copy: every server-side
    quiz-answer test in the suite sends HTTP_X_REQUESTED_WITH="fetch" and returns
    at the fragment branch before reaching the builder.

    The actor must be an ENROLLED owner — quiz_answer raises PermissionDenied for
    non-enrolled users, and the owner needs the link."""
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    quiz = make_quiz_unit(course=course)
    EnrollmentFactory(student=owner, course=course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Rome", marking_mode="A", max_marks=1
    )
    el = add_element(quiz, q)

    # No preparatory GET needed: quiz_answer get_or_creates the submission itself.
    # Note the `quiz/` URL segment — the lesson `check/` route does NOT carry it,
    # so pattern-matching off the check_answer test above produces a 404.
    # THE ABSENCE OF HTTP_X_REQUESTED_WITH IS THE ENTIRE POINT OF THIS TEST.
    resp = client.post(
        f"/courses/{course.slug}/u/{quiz.pk}/quiz/q/{el.pk}/answer/",
        {"answer": "Paris"},
    )

    assert resp.status_code == 200
    assert _editor_href(course, quiz) in resp.content.decode()


@pytest.mark.parametrize("msgid", ["Edit unit", "(opens in a new tab)"])
def test_pl_translation_present(msgid):
    """Catalog half — the common repo pattern (13 of the 17 tests/test_i18n_*.py
    files are exactly this; cf. tests/test_i18n_stepper.py)."""
    with translation.override("pl"):
        assert translation.gettext(msgid) != msgid


@pytest.mark.django_db
def test_edit_link_label_renders_in_polish(client):
    """Render half — the rarer pattern (only 4 test_i18n_* files issue a request).
    Catalog health cannot prove the template routes the label through {% trans %}
    or that the Polish string reaches the page.

    translation.override ALONE renders English: SessionLocaleMiddleware
    re-activates a language per request from the session key / Accept-Language,
    discarding whatever the test process activated, and conftest.py pins en before
    every test. All three activations below are required — copied from
    tests/test_i18n_quiz.py::test_quiz_finish_label_translated_pl.
    """
    owner = make_student(client, "owner")
    course = CourseFactory(owner=owner)
    unit = _lesson_unit(course)

    session = client.session
    session["_language"] = "pl"
    session.save()
    with translation.override("pl"):
        resp = client.get(
            f"/courses/{course.slug}/u/{unit.pk}/", HTTP_ACCEPT_LANGUAGE="pl"
        )

    assert resp.status_code == 200
    assert "Edytuj jednostkę" in resp.content.decode()
