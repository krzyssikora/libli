import pytest
from django.urls import reverse

from courses.element_forms import build_choice_formset
from courses.marking import MarkResult
from courses.models import Choice
from courses.models import ChoiceQuestionElement
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit


def _lesson_choice():
    course = CourseFactory(slug="ilf")
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    q = ChoiceQuestionElement.objects.create(stem="<p>Pick</p>", multiple=True)
    a = Choice.objects.create(
        question=q, text="A", is_correct=True, feedback="need A", order=0
    )
    c = Choice.objects.create(
        question=q, text="C", is_correct=False, feedback="trap C", order=1
    )
    el = add_element(unit, q)
    return q, el, a, c


@pytest.mark.django_db
def test_inline_feedback_wrong_and_missed_markers():
    q, el, a, c = _lesson_choice()
    # student picked only the trap C -> C wrong-selected, A missed-correct
    res = MarkResult(
        correct=False,
        fraction=0.0,
        reveal=frozenset({a.pk}),
        annotated=frozenset({a.pk, c.pk}),
    )
    html = q.render(
        element=el, mode="lesson", mark_result=res, selected_ids=frozenset({c.pk})
    )
    assert "data-question-inline" in html
    assert "trap C" in html and "need A" in html
    assert "question__choice-marker--wrong" in html  # selected distractor C
    assert "question__choice-marker--missed" in html  # missed correct A
    assert 'class="question__choice-feedback"' in html


@pytest.mark.django_db
def test_inline_feedback_absent_initial_state():
    q, el, a, c = _lesson_choice()
    # initial GET / preview: mark_result is None -> must not raise, no markers/feedback
    html = q.render(element=el, mode="lesson")
    assert "question__choice-marker" not in html
    assert "question__choice-feedback" not in html


@pytest.mark.django_db
def test_lesson_render_suppresses_bottom_reveal_list():
    q, el, a, c = _lesson_choice()
    res = MarkResult(
        correct=False,
        fraction=0.0,
        reveal=frozenset({a.pk}),
        annotated=frozenset({a.pk, c.pk}),
    )
    html = q.render(
        element=el,
        mode="lesson",
        mark_result=res,
        selected_ids=frozenset({c.pk}),
        feedback_for_pk=el.pk,
    )
    # inline feedback present, but the duplicate bottom reveal <ul> is gone
    assert "trap C" in html
    assert "question__reveal" not in html


@pytest.mark.django_db
def test_check_answer_fetch_returns_inline_full_element(client):
    user = make_login(client, "stu")
    q, el, a, c = _lesson_choice()
    # check_answer gates on can_access_course (enrolled OR staff OR owner); a plain
    # make_login user is none of these, so WITHOUT this enrollment the POST 403s.
    EnrollmentFactory(student=user, course=el.unit.course)
    url = reverse(
        "courses:check_answer",
        kwargs={
            "slug": el.unit.course.slug,
            "node_pk": el.unit.pk,
            "element_pk": el.pk,
        },
    )
    body = client.post(
        url, {"choice": [str(c.pk)]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "trap C" in body  # inline feedback for the selected distractor
    assert "need A" in body  # inline feedback for the missed correct option
    assert "question__choice-feedback" in body
    assert "question__reveal" not in body  # no duplicate bottom list


@pytest.mark.django_db
def test_element_try_lesson_choice_returns_inline(client):
    make_pa(client, "pa")  # manage-gated
    q, el, a, c = _lesson_choice()
    url = reverse(
        "courses:manage_element_try",
        kwargs={"slug": el.unit.course.slug, "pk": el.pk},
    )
    body = client.post(
        url, {"choice": [str(c.pk)]}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "question__choice-feedback" in body
    assert "trap C" in body
    assert "question__reveal" not in body


@pytest.mark.django_db
def test_element_try_quiz_choice_returns_feedback_partial(client):
    # A choice question in a QUIZ unit also carries data-question-inline, but the
    # element_try quiz branch returns the (form-LESS) _quiz_question_feedback.html.
    # Guards the server side of the editor.js fall-through: a 200 with NO <form>.
    from courses.models import Enrollment

    user = make_pa(client, "pa2")
    course = CourseFactory(slug="qcp")
    Enrollment.objects.create(student=user, course=course)
    unit = make_quiz_unit(course=course, parent=None)
    q = ChoiceQuestionElement.objects.create(
        stem="<p>Q</p>", multiple=False, marking_mode="A"
    )
    Choice.objects.create(question=q, text="A", is_correct=True, order=0)
    bad = Choice.objects.create(
        question=q, text="B", is_correct=False, feedback="x", order=1
    )
    el = add_element(unit, q)
    url = reverse(
        "courses:manage_element_try",
        kwargs={"slug": course.slug, "pk": el.pk},
    )
    resp = client.post(
        url, {"choice": [str(bad.pk)], "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    )
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "<form" not in body  # quiz feedback fragment is form-less -> falls through


@pytest.mark.django_db
def test_choice_feedback_help_text_mentions_both_cases():
    fs = build_choice_formset(multiple=True)
    help_text = str(fs.forms[0].fields["feedback"].help_text)
    assert help_text  # non-empty
    # mentions the missed-correct case, not only distractors
    assert "correct" in help_text.lower()
