"""Short text + number: quiz reveal and lesson in-place feedback (spec §2.2, §5a)."""

import re

import pytest
from django.urls import reverse

from courses.models import Element
from courses.models import Enrollment
from courses.models import ShortNumericQuestionElement
from courses.models import ShortTextQuestionElement
from courses.models import UnitProgress
from tests.factories import make_course_with_unit
from tests.factories import make_quiz_unit
from tests.factories import make_student

_INPUT = re.compile(r'<input[^>]*name="answer"[^>]*>')


@pytest.fixture
def st_quiz(db):
    unit = make_quiz_unit()
    q = ShortTextQuestionElement.objects.create(
        stem="Capital?", accepted="Paris", max_attempts=3
    )
    return q, Element.objects.create(unit=unit, content_object=q)


def test_quiz_locked_wrong_shows_key_copy(st_quiz):
    q, el = st_quiz
    html = q.render(
        element=el,
        mode="quiz",
        action_url="/x/",
        feedback_for_pk=el.pk,
        submitted_values="Rome",
        verdicts=[False],
        key_values="Paris",
        locked=True,
    )
    key = html.split("data-answer-key")[1]
    assert 'value="Paris"' in key and "name=" not in key.split("data-answer-switch")[0]
    assert 'aria-label="Correct answer"' in key
    (yours,) = _INPUT.findall(html)
    assert "is-incorrect" in yours and 'aria-invalid="true"' in yours


@pytest.mark.parametrize(
    "model", [ShortTextQuestionElement, ShortNumericQuestionElement]
)
def test_check_is_the_first_submit_button_single_part(db, model):
    unit = make_quiz_unit()
    q = model.objects.create(
        stem="?",
        **({"accepted": "a"} if model is ShortTextQuestionElement else {"value": "1"}),
    )
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(
        element=el,
        mode="quiz",
        action_url="/x/",
        feedback_for_pk=el.pk,
        submitted_values="x",
        can_reveal=True,
    )
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', html)
    assert 'name="reveal"' not in buttons[0] and 'name="reveal"' in buttons[1]


@pytest.mark.parametrize(
    "model", [ShortTextQuestionElement, ShortNumericQuestionElement]
)
@pytest.mark.parametrize("verdict", [True, False])
def test_quiz_part_cues_per_single_part_type(db, model, verdict):
    unit = make_quiz_unit()
    q = model.objects.create(
        stem="?",
        **({"accepted": "a"} if model is ShortTextQuestionElement else {"value": "1"}),
    )
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(
        element=el,
        mode="quiz",
        action_url="/x/",
        feedback_for_pk=el.pk,
        submitted_values="x",
        verdicts=[verdict],
    )
    (inp,) = _INPUT.findall(html)
    if verdict:
        assert "is-correct" in inp and "aria-invalid" not in inp
        assert '<span class="sr-only">correct</span>' in html
        assert '<span class="sr-only">incorrect</span>' not in html
    else:
        assert "is-incorrect" in inp and 'aria-invalid="true"' in inp
        assert '<span class="sr-only">incorrect</span>' in html


def test_numeric_key_copy_prints_tolerance_unfiltered(db):
    unit = make_quiz_unit()
    q = ShortNumericQuestionElement.objects.create(
        stem="pi?", value="3.14", tolerance="0.01"
    )
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(
        element=el,
        mode="quiz",
        action_url="/x/",
        feedback_for_pk=el.pk,
        submitted_values="4",
        key_values="3.14",
        locked=True,
    )
    key = html.split("data-answer-key")[1]
    assert 'value="3.14"' in key and "± 0.01" in key


def _lesson(client, q):
    student = make_student(client, "st_lesson")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    el = Element.objects.create(unit=unit, content_object=q)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    return student, unit, el, url


def _make(kind):
    if kind == "text":
        return (
            ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris"),
            "Rome",
            "Paris",
        )
    return (
        ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14"),
        "9",
        "3.14",
    )


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["text", "number"])
def test_lesson_check_paints_input_no_list(client, kind):
    q, wrong, key = _make(kind)
    _s, _u, _el, url = _lesson(client, q)
    body = client.post(
        url, {"answer": wrong}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "data-question-inline" in body
    (inp,) = _INPUT.findall(body)
    assert "is-incorrect" in inp and 'aria-invalid="true"' in inp
    assert "Correct answer:" not in body and "Expected:" not in body and key not in body
    assert "data-answer-key" not in body and 'name="reveal"' not in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["text", "number"])
def test_lesson_nojs_restore_and_try_paint_both_types(client, kind):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_pa

    q, wrong, _key = _make(kind)
    student, unit, el, url = _lesson(client, q)

    def _no_list(html):
        assert "question__reveal" not in html
        assert "Correct answer:" not in html and "Expected:" not in html

    body = client.post(url, {"answer": wrong}).content.decode()  # no-JS
    assert "is-incorrect" in _INPUT.findall(body)[0]
    _no_list(body)
    page = client.get(
        reverse(
            "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    )
    assert "is-incorrect" in _INPUT.findall(page.content.decode())[0]  # restore
    _no_list(page.content.decode())
    pa = make_pa(client, f"pa_{kind}")
    course = CourseFactory(owner=pa)
    lu = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    q2, wrong2, _k = _make(kind)
    el2 = Element.objects.create(unit=lu, content_object=q2)
    try_url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el2.pk}
    )
    tbody = client.post(
        try_url, {"answer": wrong2}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "is-incorrect" in _INPUT.findall(tbody)[0]
    _no_list(tbody)


@pytest.mark.django_db
def test_lesson_nojs_and_restore_paint(client):
    q = ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14")
    student, unit, el, url = _lesson(client, q)
    body = client.post(url, {"answer": "3.14"}).content.decode()
    assert "is-correct" in _INPUT.findall(body)[0]
    UnitProgress.objects.filter(student=student, unit=unit).update(
        element_state={str(el.pk): {"answer": "9"}}
    )
    page = client.get(
        reverse(
            "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    )
    assert "is-incorrect" in _INPUT.findall(page.content.decode())[0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "model,right_answer,wrong_answer",
    [
        (ShortTextQuestionElement, "Paris", "Rome"),
        (ShortNumericQuestionElement, "3.14", "9"),
    ],
)
def test_lesson_sr_text_on_both_aria_invalid_only_on_wrong(
    client, model, right_answer, wrong_answer
):
    kw = (
        {"accepted": "Paris"}
        if model is ShortTextQuestionElement
        else {"value": "3.14"}
    )
    q = model.objects.create(stem="?", **kw)
    _s, _u, _el, url = _lesson(client, q)
    wrong = client.post(url, {"answer": wrong_answer}).content.decode()
    assert re.search(
        r'aria-invalid="true"[^>]*>\s*<span class="sr-only">incorrect</span>', wrong
    )
    right = client.post(url, {"answer": right_answer}).content.decode()
    assert '<span class="sr-only">correct</span>' in right
    assert "aria-invalid" not in _INPUT.findall(right)[0]


@pytest.mark.django_db
def test_lesson_nested_in_callout_paints_on_nojs_and_restore(client):
    from courses.models import CalloutElement
    from tests.factories import add_element

    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    student = make_student(client, "st_nested")
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    callout_row = add_element(unit, CalloutElement.objects.create(kind="example"))
    nested = Element.objects.create(
        unit=unit, content_object=q, parent=callout_row, tab_id=CalloutElement.SLOT_ID
    )
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": nested.pk},
    )
    body = client.post(url, {"answer": "Rome"}).content.decode()  # no-JS
    assert "is-incorrect" in _INPUT.findall(body)[0]
    page = client.get(
        reverse("courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk})
    ).content.decode()
    assert "is-incorrect" in _INPUT.findall(page)[0]  # restore


@pytest.mark.django_db
def test_nojs_lesson_check_leaves_sibling_unpainted(client):
    from courses.fillblank import parse
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    token_stem, _ = parse("{{11}}")
    fbq = FillBlankQuestionElement.objects.create(stem=token_stem)
    Blank.objects.create(question=fbq, order=0, accepted="11")
    student, unit, fb_el, url = _lesson(client, fbq)
    st = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    Element.objects.create(unit=unit, content_object=st)
    body = client.post(url, {"blank": ["5"]})  # no-JS re-render of the whole unit
    assert body.status_code == 200
    (sibling,) = _INPUT.findall(body.content.decode())
    assert "is-correct" not in sibling and "is-incorrect" not in sibling


@pytest.mark.django_db
def test_nojs_short_text_check_beside_fillblank_sibling_is_safe(client):
    # The feedback_for_pk guard's real job: without it a fill-blank sibling would run
    # part_verdicts on a SHORT-TEXT result, whose reveal is a string -> item["correct"]
    # on characters -> 500.
    from courses.fillblank import parse
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    st = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    _s, unit, _el, url = _lesson(client, st)
    token_stem, _ = parse("{{11}}")
    fbq = FillBlankQuestionElement.objects.create(stem=token_stem)
    Blank.objects.create(question=fbq, order=0, accepted="11")
    Element.objects.create(unit=unit, content_object=fbq)
    resp = client.post(url, {"answer": "Rome"})  # no-JS: whole unit re-rendered
    assert resp.status_code == 200
    blank = re.search(r'<input[^>]*name="blank"[^>]*>', resp.content.decode()).group(0)
    assert "is-correct" not in blank and "is-incorrect" not in blank


@pytest.mark.django_db
def test_editor_try_lesson_paints_single_part(client):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_pa

    pa = make_pa(client, "pa_try")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson"
    )
    q = ShortNumericQuestionElement.objects.create(stem="pi?", value="3.14")
    el = Element.objects.create(unit=unit, content_object=q)
    url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk}
    )
    body = client.post(
        url, {"answer": "4"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert "is-incorrect" in _INPUT.findall(body)[0]
    assert "Expected:" not in body


def test_key_copy_escapes_a_raw_key(st_quiz):
    q, el = st_quiz
    q.accepted = "a<b"
    html = q.render(
        element=el,
        mode="quiz",
        action_url="/x/",
        feedback_for_pk=el.pk,
        submitted_values="x",
        key_values="a<b",
        locked=True,
    )
    key = html.split("data-answer-key")[1].split("data-answer-switch")[0]
    assert 'value="a&lt;b"' in key and "<b" not in key.replace("&lt;b", "")


@pytest.mark.django_db
def test_fillblank_key_copy_keeps_latex_backslashes(db):
    from courses.fillblank import parse
    from courses.models import Blank
    from courses.models import FillBlankQuestionElement

    unit = make_quiz_unit()
    q = FillBlankQuestionElement.objects.create(stem=parse("{{x}}")[0])
    Blank.objects.create(question=q, order=0, accepted="\\(x\\)")
    el = Element.objects.create(unit=unit, content_object=q)
    html = q.render(
        element=el,
        mode="quiz",
        action_url="/x/",
        feedback_for_pk=el.pk,
        submitted_values=["y"],
        key_values=["\\(x\\)"],
        locked=True,
    )
    assert 'value="\\(x\\)"' in html.split("data-answer-key")[1]


@pytest.mark.django_db
def test_numeric_key_copy_tolerance_matches_old_reveal_in_pl(db):
    from django.template.loader import render_to_string
    from django.utils import translation

    from courses.marking import MarkResult

    unit = make_quiz_unit()
    q = ShortNumericQuestionElement.objects.create(
        stem="x?", value="3.5", tolerance="0.25"
    )
    el = Element.objects.create(unit=unit, content_object=q)
    with translation.override("pl"):
        html = q.render(
            element=el,
            mode="quiz",
            action_url="/x/",
            feedback_for_pk=el.pk,
            submitted_values="4",
            key_values="3.5",
            locked=True,
        )
        old = render_to_string(
            "courses/elements/_reveal_shortnumeric.html",
            {
                "mark_result": MarkResult(
                    correct=False,
                    fraction=0.0,
                    reveal={"value": "3.5", "tolerance": "0.25"},
                )
            },
        )
    key = html.split("data-answer-key")[1].split("data-answer-switch")[0]
    assert 'value="3.5"' in key
    # Same tolerance text in both renders (no localisation drift, e.g. 0,25).
    old_tol = re.search(r"± (\S+?)\s*</p>", old).group(1)
    new_tol = re.search(r"± (\S+?)(\s|<|$)", key).group(1)
    assert old_tol == new_tol == "0.25"


@pytest.mark.django_db
def test_lesson_correct_keeps_input_editable(client):
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="Paris")
    _s, _u, _el, url = _lesson(client, q)
    body = client.post(url, {"answer": "Paris"}).content.decode()
    (inp,) = _INPUT.findall(body)
    assert "is-correct" in inp and "disabled" not in inp and "readonly" not in inp
