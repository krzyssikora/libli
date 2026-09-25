"""Results page renders converted questions as they ended (spec §4) + analytics tag
(§5)."""

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit


def _setup(client):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    token_stem, _ = parse("{{11}} {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=3)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    fb = Element.objects.create(unit=unit, content_object=q)
    unanswered = add_element(
        unit, ShortTextQuestionElement.objects.create(stem="U?", accepted="Paris")
    )
    nm = add_element(
        unit,
        ShortTextQuestionElement.objects.create(
            stem="N?",
            accepted="Oslo",
            marking_mode=QuestionElement.MarkingMode.NOT_MARKED,
        ),
    )
    return user, unit, fb, unanswered, nm


def _answer(client, unit, el, data):
    return client.post(
        f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/",
        data,
        HTTP_X_REQUESTED_WITH="fetch",
    )


def _finish_and_get_results(client, unit):
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    return client.get(reverse("courses:quiz_results", kwargs=kw)).content.decode()


@pytest.mark.django_db
def test_results_render_questions_as_they_ended(client):
    _u, unit, fb, unanswered, nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})
    _answer(client, unit, fb, {"reveal": "1"})
    _answer(client, unit, nm, {"answer": "Bergen"})
    body = _finish_and_get_results(client, unit)
    assert "<form" not in body.split("quiz-results__list")[1]
    listing = body.split("quiz-results__list")[1].split("</ol>")[0]
    assert "<button" not in listing and 'type="submit"' not in listing  # spec §4
    assert body.count("data-answer-switch") == 2  # fb (partial) + unanswered short text
    assert "answer shown" in body
    assert 'value="Paris"' in body  # unanswered key visible
    assert "Not answered (0/1)" in body  # spec §4: auto-marked unanswered shows 0 / 1
    assert "Oslo" not in body  # N question never shows a key
    assert "Correct answer:" not in body and "Expected:" not in body
    assert f'name="answer_view_{fb.pk}"' in body


@pytest.mark.django_db
def test_results_stored_correct_key_edited_all_green(client):
    # The results branch renders the student's copy with locked=False, so THIS is
    # where quiz_render_state's all-correct override is visible (spec §2.6).
    import re

    _u, unit, fb, _un, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "9"]})
    Blank.objects.filter(question=fb.content_object, order=1).update(accepted="7")
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    blanks = re.findall(r'<input[^>]*name="blank"[^>]*>', row)
    assert blanks and all("is-correct" in b for b in blanks)
    assert "data-answer-switch" not in row


@pytest.mark.django_db
def test_results_mirror_case_partial_line_over_green_parts(client):
    import re

    _u, unit, fb, _un, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})  # stored 0.5
    Blank.objects.filter(question=fb.content_object, order=1).update(accepted="5")
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    blanks = re.findall(r'<input[^>]*name="blank"[^>]*>', row)
    assert all("is-correct" in b for b in blanks[:2])
    assert "Partial" in row and "data-answer-switch" in row  # accepted as-is (§2.6)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "mode,answer,badge,switch,key_shown",
    [
        ("A", "Paris", "Correct (1/1)", False, False),
        ("A", "Rome", "Incorrect (0/1)", True, True),
        ("A", None, "Not answered (0/1)", True, True),
        ("N", "Rome", "Answer recorded", False, False),
        ("N", None, "Not answered", False, False),
        ("R", "Rome", "Awaiting review", False, False),
        ("R", None, "Awaiting review", False, False),
    ],
)
def test_results_row_matrix(client, mode, answer, badge, switch, key_shown):
    user = make_login(client, "stu_m")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?",
        accepted="Paris",
        marking_mode=mode,
        max_attempts=1,
        explanation="<p>Because.</p>",
    )
    el = add_element(unit, q)
    if answer is not None:
        _answer(client, unit, el, {"answer": answer})
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    assert badge in row
    assert ("data-answer-switch" in row) is switch
    assert ("data-answer-key" in row) is key_shown  # N/R never show a key
    # Explanation: hidden for recorded / review / reviewed outcomes, as today (an
    # unanswered R row's outcome is "review", so it is hidden there too).
    assert ("Because." in row) is (mode == "A" or (mode == "N" and answer is None))


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "number"])
@pytest.mark.parametrize("mode", ["N", "R"])
@pytest.mark.parametrize("answered", [True, False])
def test_results_nr_rows_never_show_the_key(client, kind, mode, answered):
    from courses.models import ShortNumericQuestionElement

    user = make_login(client, "stu_nr")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(
            stem=parse("{{11}}")[0], marking_mode=mode, max_attempts=1
        )
        Blank.objects.create(question=q, order=0, accepted="11")
        data = {"blank": ["5"]}
    else:
        q = ShortNumericQuestionElement.objects.create(
            stem="?", value="3.14", marking_mode=mode, max_attempts=1
        )
        data = {"answer": "9"}
    el = add_element(unit, q)
    if answered:
        _answer(client, unit, el, data)
    row = _finish_and_get_results(client, unit).split("quiz-results__item")[1]
    assert "data-answer-key" not in row and "data-answer-switch" not in row


@pytest.mark.django_db
def test_results_reviewed_row_shows_teacher_marks(client):
    from django.utils import timezone

    from courses.models import QuestionResponse

    user = make_login(client, "stu_r")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="Essay?", accepted="Paris", marking_mode="R", max_attempts=1
    )
    el = add_element(unit, q)
    _answer(client, unit, el, {"answer": "Rome"})
    body_url_kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=body_url_kw))
    QuestionResponse.objects.filter(element=el).update(
        reviewed_at=timezone.now(), earned_marks="0.50", review_feedback="Half right."
    )
    body = client.get(
        reverse("courses:quiz_results", kwargs=body_url_kw)
    ).content.decode()
    row = body.split("quiz-results__item")[1]
    assert "Reviewed (0.5/1)" in row and "Half right." in row
    assert "data-answer-switch" not in row and 'value="Paris"' not in row


@pytest.mark.django_db
def test_results_short_text_row_every_input_disabled(client):
    # Short text / number have no fieldset: freezing on the results page relies on
    # locked=True reaching the controls include (spec §4).
    import re

    user = make_login(client, "stu_dis")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ShortTextQuestionElement.objects.create(
        stem="?", accepted="Paris", max_attempts=1
    )
    el = add_element(unit, q)
    _answer(client, unit, el, {"answer": "Rome"})
    row = _finish_and_get_results(client, unit).split("quiz-results__item")[1]
    inputs = re.findall(r'<input[^>]*type="text"[^>]*>', row)
    assert len(inputs) == 2  # yours + key copy
    assert all("disabled" in t for t in inputs)
    assert 'name="answer"' in inputs[0]


@pytest.mark.django_db
def test_results_controls_are_all_disabled(client):
    _u, unit, fb, _un, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})
    body = _finish_and_get_results(client, unit)
    row = body.split("quiz-results__item")[1]
    yours = row.split("data-answer-yours")[1].split("data-answer-key")[0]
    assert "disabled" in yours  # fieldset is `data-answer-yours disabled` (Task 6)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
@pytest.mark.parametrize("answered", [True, False])
def test_analytics_expected_answer_per_type(client, kind, answered):
    # Spec §5: _results_row's keys feed analytics; every converted type, answered
    # (wrong) and unanswered, must still show its expected answer there.
    from courses.models import ShortNumericQuestionElement
    from tests.factories import make_pa

    user = make_login(client, "stu_an")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(
            stem=parse("{{zetakey}}")[0], max_attempts=1
        )
        Blank.objects.create(question=q, order=0, accepted="zetakey")
        data, key = {"blank": ["no"]}, "zetakey"
    elif kind == "text":
        q = ShortTextQuestionElement.objects.create(
            stem="?", accepted="Parisxyz", max_attempts=1
        )
        data, key = {"answer": "no"}, "Parisxyz"
    else:
        q = ShortNumericQuestionElement.objects.create(
            stem="?", value="3.14159", max_attempts=1
        )
        data, key = {"answer": "1"}, "3.14159"
    el = add_element(unit, q)
    if answered:
        _answer(client, unit, el, data)
    _finish_and_get_results(client, unit)
    client.logout()
    make_pa(client, "pa_an")
    url = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": unit.course.slug, "student_pk": user.pk, "node_pk": unit.pk},
    )
    assert key in client.get(url).content.decode()


@pytest.mark.django_db
def test_analytics_keeps_expected_answers_and_tags_reveal(client):
    from tests.factories import make_pa

    user, unit, fb, unanswered, _nm = _setup(client)
    _answer(client, unit, fb, {"blank": ["11", "5"]})
    _answer(client, unit, fb, {"reveal": "1"})
    _finish_and_get_results(client, unit)
    make_pa(client, "teacher_pa")
    from courses.models import QuizSubmission

    sub = QuizSubmission.objects.get(student=user, unit=unit)
    assert sub.status == QuizSubmission.Status.SUBMITTED
    url = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={
            "slug": unit.course.slug,
            "student_pk": sub.student_id,
            "node_pk": unit.pk,
        },
    )
    body = client.get(url).content.decode()
    assert "answer shown" in body
    assert "Paris" in body  # the unanswered row still shows its expected answer


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
def test_results_helper_never_marks_an_unanswered_row(monkeypatch, kind):
    # Spec §4: an unanswered converted row renders neutral controls WITHOUT mark().
    # _results_row may call mark() itself (spec §5 allows it), so the row is built
    # first and mark is patched to raise only around the helper.
    from courses import views
    from courses.models import ShortNumericQuestionElement

    unit = make_quiz_unit()
    if kind == "fillblank":
        q = FillBlankQuestionElement.objects.create(stem=parse("{{11}}")[0])
        Blank.objects.create(question=q, order=0, accepted="11")
        key = 'value="11"'
    elif kind == "text":
        q = ShortTextQuestionElement.objects.create(stem="U?", accepted="Paris")
        key = 'value="Paris"'
    else:
        q = ShortNumericQuestionElement.objects.create(stem="N?", value="3.14")
        key = 'value="3.14"'
    el = add_element(unit, q)
    row = views._results_row(q, None)

    def _boom(*args, **kwargs):
        raise AssertionError("mark() called for an unanswered results row")

    monkeypatch.setattr(type(q), "mark", _boom)
    html = views._results_question_html(el, q, None, row)
    assert "data-answer-switch" in html and key in html
