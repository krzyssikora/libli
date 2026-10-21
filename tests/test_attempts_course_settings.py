"""Course-level attempts default and reset (spec 2026-10-20 §5.3/§5.4)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from courses import attempts as A
from courses.forms import CourseForm
from courses.models import ContentNode
from courses.models import ShortTextQuestionElement
from tests.factories import CourseFactory
from tests.factories import add_element
from tests.factories import attempts
from tests.factories import make_pa
from tests.factories import make_quiz_unit

pytestmark = pytest.mark.django_db


def _form_data(course, **over):
    form = CourseForm(instance=course)
    data = {}
    for name in form.fields:
        value = form[name].value()
        if value is None:
            continue
        data[name] = (
            [str(v) for v in value] if isinstance(value, (list, tuple)) else value
        )
    data.update(over)
    return data


def _post(client, course, **over):
    url = reverse("courses:manage_course_edit", kwargs={"slug": course.slug})
    return client.post(url, _form_data(course, **over), follow=True)


def _q(unit, own, marking="A"):
    q = ShortTextQuestionElement.objects.create(
        stem="x", accepted="a", marking_mode=marking, **own
    )
    add_element(unit, q)
    return q


def test_saves_course_default(client):
    make_pa(client)
    course = CourseFactory()
    _post(client, course, attempts_mode="limited", attempts_limit="3")
    course.refresh_from_db()
    assert (course.attempts_mode, course.attempts_limit) == ("limited", 3)


def test_course_cannot_inherit_and_zero_has_the_course_message():
    course = CourseFactory()
    form = CourseForm(_form_data(course, attempts_mode="inherit"), instance=course)
    assert form.errors["attempts_mode"] == [str(A.MSG_CHOOSE)]
    form = CourseForm(
        _form_data(course, attempts_mode="limited", attempts_limit="0"), instance=course
    )
    assert form.errors["attempts_limit"] == [str(A.ZERO_MESSAGES["course_level"])]


def test_hidden_junk_saves_null():
    course = CourseFactory()
    form = CourseForm(
        _form_data(course, attempts_mode="unlimited", attempts_limit="abc"),
        instance=course,
    )
    assert form.is_valid(), form.errors
    c = form.save()
    assert (c.attempts_mode, c.attempts_limit) == ("unlimited", None)


def test_absent_keys_keep_stored_values():
    course = CourseFactory(attempts_mode="limited", attempts_limit=5)
    data = _form_data(course)
    data.pop("attempts_mode")
    data.pop("attempts_limit")
    form = CourseForm(data, instance=course)
    assert form.is_valid(), form.errors
    c = form.save()
    assert (c.attempts_mode, c.attempts_limit) == ("limited", 5)


def test_reset_choice_only_when_overrides_exist():
    course = CourseFactory()
    assert "attempts_reset" not in CourseForm(instance=course).fields
    assert "attempts_reset" not in CourseForm().fields  # create
    _q(make_quiz_unit(course=course), attempts(3))
    field = CourseForm(instance=course).fields["attempts_reset"]
    assert (
        dict(field.widget.choices)["keep"]
        == "Keep specific settings (1 question has its own)"
    )


def test_reset_end_to_end(client):
    make_pa(client)
    course = CourseFactory()
    qa = make_quiz_unit(course=course, attempts_mode="limited", attempts_limit=2)
    qb = make_quiz_unit(course=course)
    _q(qa, attempts(3))
    _q(qb, attempts(4))
    _q(qb, attempts(None))
    resp = _post(
        client,
        course,
        attempts_mode="limited",
        attempts_limit="3",
        attempts_reset="reset",
    )
    assert (
        "Settings saved. 1 quiz and 3 questions now use the course setting."
        in resp.content.decode()
    )
    assert (
        not ContentNode.objects.filter(course=course)
        .exclude(attempts_mode="inherit")
        .exists()
    )


def test_keep_shows_no_message_and_changes_nothing(client):
    make_pa(client)
    course = CourseFactory()
    q = _q(make_quiz_unit(course=course), attempts(3))
    resp = _post(client, course, attempts_reset="keep")
    q.refresh_from_db()
    assert q.attempts_limit == 3
    assert "Settings saved" not in resp.content.decode()


def test_invalid_post_keeps_the_reset_pick(client):
    make_pa(client)
    course = CourseFactory()
    _q(make_quiz_unit(course=course), attempts(3))
    url = reverse("courses:manage_course_edit", kwargs={"slug": course.slug})
    resp = client.post(
        url,
        _form_data(
            course, attempts_mode="limited", attempts_limit="0", attempts_reset="reset"
        ),
    )
    assert resp.status_code == 200
    # Django's RadioSelect puts id= between value= and checked: parse, don't substring.
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.content, "html.parser")
    assert soup.select_one('input[name="attempts_reset"][value="reset"]').has_attr(
        "checked"
    )


def test_units_are_locked_before_any_question_or_course_write(client):
    make_pa(client)
    course = CourseFactory()
    _q(make_quiz_unit(course=course), attempts(3))
    with CaptureQueriesContext(connection) as ctx:
        _post(client, course, attempts_reset="reset")
    sqls = [q["sql"] for q in ctx.captured_queries]

    def first(pred):
        return next(i for i, s in enumerate(sqls) if pred(s))

    lock = first(lambda s: 'FROM "courses_contentnode"' in s and "FOR UPDATE" in s)
    q_write = first(
        lambda s: s.startswith('UPDATE "courses_') and "questionelement" in s
    )
    c_write = first(lambda s: s.startswith('UPDATE "courses_course"'))
    assert lock < q_write and lock < c_write


def test_dormant_lesson_override_survives_reset_and_revives_as_quiz(client):
    """Accepted consequence of P9 (spec §5.4): not "fixed"."""
    from courses.quiz import effective_unit_attempts
    from tests.factories import ContentNodeFactory

    make_pa(client)
    course = CourseFactory()
    _q(make_quiz_unit(course=course), attempts(3))  # makes the reset choice appear
    lesson = ContentNodeFactory(
        course=course,
        kind="unit",
        unit_type="lesson",
        attempts_mode="limited",
        attempts_limit=2,
    )
    _post(client, course, attempts_reset="reset")
    ContentNode.objects.filter(pk=lesson.pk).update(unit_type="quiz")
    lesson.refresh_from_db()
    assert effective_unit_attempts(lesson) == (2, "quiz")


def test_reset_is_atomic_with_the_course_save(client, monkeypatch):
    make_pa(client)
    course = CourseFactory()
    q = _q(make_quiz_unit(course=course), attempts(3))

    def boom(self, commit=True):
        raise RuntimeError("save failed")

    monkeypatch.setattr(CourseForm, "save", boom)
    with pytest.raises(RuntimeError):
        _post(client, course, attempts_reset="reset")
    q.refresh_from_db()
    assert q.attempts_limit == 3  # rolled back


def test_stale_editor_save_is_refused_after_a_reset(client):
    make_pa(client)
    course = CourseFactory()
    unit = make_quiz_unit(course=course)  # own mode inherit
    q = _q(unit, attempts(3))
    el = q.elements.get()
    stale_token = unit.updated.isoformat()
    _post(client, course, attempts_reset="reset")
    resp = client.post(
        reverse("courses:manage_element_save", kwargs={"slug": course.slug}),
        {
            "unit": unit.pk,
            "element": el.pk,
            "type": "shorttextquestion",
            "unit_token": stale_token,
            "el_title": "",
            "stem": "x",
            "explanation": "",
            "accepted": "a",
            "marking_mode": "A",
            "max_marks": "1",
            "attempts_mode": "limited",
            "attempts_limit": "3",
        },
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert resp.status_code == 409
    q.refresh_from_db()
    assert q.attempts_mode == "inherit"  # the reset was not silently undone


def test_course_reset_does_not_unlock_an_exhausted_question(client):
    """D13 at course level: the reset never clears a locked response."""
    from courses.models import QuestionResponse
    from tests.factories import EnrollmentFactory
    from tests.factories import make_login

    user = make_login(client, "stu")
    course = CourseFactory()
    unit = make_quiz_unit(course=course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", **attempts(1)
    )
    el = add_element(unit, q)
    EnrollmentFactory(student=user, course=course)
    answer = f"/courses/{course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"
    client.post(answer, {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    assert QuestionResponse.objects.get(element=el).locked is True
    make_pa(client)
    _post(
        client,
        course,
        attempts_mode="limited",
        attempts_limit="3",
        attempts_reset="reset",
    )
    client.force_login(user)
    resp = client.post(answer, {"answer": "London"}, HTTP_X_REQUESTED_WITH="fetch")
    assert resp.status_code == 409
    assert QuestionResponse.objects.get(element=el).locked is True


def test_new_course_form_shows_the_model_default():
    # An unbound form with no instance gets no initial from the model, so the
    # declared fields must carry it -- else the page posts limited + "" (CI #408).
    form = CourseForm()
    assert form["attempts_mode"].value() == "limited"
    assert str(form["attempts_limit"].value()) == "1"


def test_new_course_created_from_the_rendered_defaults(client):
    # What the browser submits when the author fills only title and slug.
    user = make_pa(client)
    form = CourseForm(initial={"owner": user.pk})
    data = {}
    for name in form.fields:
        value = form[name].value()
        if value is None:
            continue
        data[name] = (
            [str(v) for v in value] if isinstance(value, (list, tuple)) else value
        )
    # A browser always submits a <select> (its first option when none is
    # selected) and a text input ("" when empty); it never omits them.
    data.setdefault("attempts_mode", form.fields["attempts_mode"].choices[0][0])
    data.setdefault("attempts_limit", "")
    data.update(title="New", slug="new-course")
    response = client.post(reverse("courses:manage_course_create"), data)
    assert response.status_code == 302
    course = CourseFactory._meta.model.objects.get(slug="new-course")
    assert (course.attempts_mode, course.attempts_limit) == ("limited", 1)
