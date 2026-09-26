"""The PR 2 types through every quiz, results and lesson path (spec 2026-09-25 §2,
§4, §5, §5a). Task 3 converts the drag types; Task 4 widens KINDS_UNDER_TEST."""

import re

import pytest
from django.urls import reverse
from django.utils import translation

from courses.models import DragBlank
from courses.models import Enrollment
from courses.models import QuestionResponse
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_course_with_unit
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.factories import make_student
from tests.reveal_pr2_kit import DND_KINDS
from tests.reveal_pr2_kit import GRID_KINDS
from tests.reveal_pr2_kit import build
from tests.reveal_pr2_kit import key
from tests.reveal_pr2_kit import paint
from tests.reveal_pr2_kit import parts
from tests.reveal_pr2_kit import yours

KINDS_UNDER_TEST = DND_KINDS + GRID_KINDS

_CONTROL = re.compile(r"<(?:input|select)\b[^>]*>")
_SR_OK = '<span class="sr-only">correct</span>'
_SR_BAD = '<span class="sr-only">incorrect</span>'


def _quiz(client, username="stu"):
    user = make_login(client, username)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


def _add(unit, kind, **kw):
    kit = build(kind, **kw)
    return kit, add_element(unit, kit.question)


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _fetch(client, unit, el, data):
    return client.post(_url(unit, el), data, HTTP_X_REQUESTED_WITH="fetch")


def _page(client, unit):
    return client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()


def _results(client, unit):
    kw = {"slug": unit.course.slug, "node_pk": unit.pk}
    client.post(reverse("courses:quiz_finish", kwargs=kw))
    return client.get(reverse("courses:quiz_results", kwargs=kw)).content.decode()


def _no_answers(kit, html):
    """Lesson / pre-lock invariant: no list, no copy, no switch, no Show answer."""
    assert "question__reveal" not in html
    assert "data-answer-key" not in html and "data-answer-switch" not in html
    assert 'name="reveal"' not in html
    assert kit.leak not in html


# ── quiz: before the lock ─────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_check_answers_whole_element_painted_no_key(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert "data-question-inline" in body and "<form" in body
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    assert "data-answer-key" not in body and "question__reveal" not in body
    assert kit.leak not in body  # only booleans before the lock (spec §2.1)
    assert 'name="reveal"' in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_empty_check_is_a_bare_validation_fragment(client, kind):
    # Spec §2.4: validation responses stay the feedback fragment (no swap), use no
    # attempt, and leave the earlier paint in place on resume.
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    _fetch(client, unit, el, kit.half)
    body = _fetch(client, unit, el, kit.empty).content.decode()
    assert "<form" not in body and "is-validation" in body
    assert QuestionResponse.objects.get(element=el).attempt_count == 1
    assert paint(kind, yours(_page(client, unit))) == ["correct", "incorrect"]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_cues_on_every_painted_part(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    right, wrong = parts(
        kind, yours(_fetch(client, unit, el, kit.half).content.decode())
    )
    assert _SR_OK in right and "aria-invalid" not in right
    assert _SR_BAD in wrong and 'aria-invalid="true"' in wrong


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_one_feedback_box_check_first_at_most_one_reveal(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    for body in (
        _fetch(client, unit, el, kit.half).content.decode(),
        _page(client, unit),
    ):
        # Only THIS question's form: the full page has other submit buttons.
        body = re.search(r"<form[^>]*data-answer-scope.*?</form>", body, re.S).group(0)
        assert body.count("data-question-feedback") == 1
        buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', body)
        assert 'name="reveal"' not in buttons[0]  # Check first (spec §3.1)
        assert sum('name="reveal"' in b for b in buttons) == 1


# ── quiz: locked ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_locked_wrong_shows_a_neutralised_painted_key_copy(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind, max_attempts=1)
    body = _fetch(client, unit, el, kit.half).content.decode()
    k = key(body)
    assert kit.leak in k and kit.leak not in yours(body)
    assert paint(kind, k) == ["correct", "correct"]
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    controls = _CONTROL.findall(k)
    assert controls and all("name=" not in c and "disabled" in c for c in controls)
    if kind in DND_KINDS:
        assert all("data-slot" in s for s in re.findall(r"<select\b[^>]*>", k))
    assert body.count("data-answer-switch") == 1
    assert "question__reveal" not in body
    assert 'name="reveal"' not in body  # locked: no Show answer


@pytest.mark.django_db
@pytest.mark.parametrize("kind", DND_KINDS)
def test_each_copy_is_its_own_dnd_root(client, kind):
    # Spec §2.4: data-dnd / the pool / the stage live inside the controls include,
    # once per copy -- never on the outer [data-question] div.
    unit = _quiz(client)
    kit, el = _add(unit, kind, max_attempts=1)
    kit2, el2 = _add(unit, kind)  # max_attempts=3: stays open after one Check
    root = re.compile(r"\bdata-dnd(?=[\s=>])")
    open_body = _fetch(client, unit, el2, kit2.half).content.decode()
    assert len(root.findall(open_body)) == 1
    body = _fetch(client, unit, el, kit.half).content.decode()
    outer = re.search(r"<div[^>]*\bel--question\b[^>]*>", body).group(0)
    assert "data-dnd" not in outer and "data-question" in outer
    assert len(root.findall(yours(body))) == 1 and len(root.findall(key(body))) == 1
    assert body.count("data-dnd-pool") == 2
    if kind == "dragimage":
        assert body.count("data-dragimage-stage") == 2


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_never_show_the_key(client, kind, mode):
    unit = _quiz(client)
    kit, el = _add(unit, kind, marking_mode=mode)
    body = _fetch(client, unit, el, kit.half).content.decode()
    for html in (body, _page(client, unit), _results(client, unit)):
        assert "data-answer-key" not in html and "data-answer-switch" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_resume_paints_then_reveal_shows_the_key(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    _fetch(client, unit, el, kit.half)
    page = _page(client, unit)
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    assert 'name="reveal"' in page and "data-answer-key" not in page
    revealed = _fetch(client, unit, el, {"reveal": "1"}).content.decode()
    assert "data-answer-key" in revealed and "answer shown" in revealed
    assert QuestionResponse.objects.get(element=el).attempt_count == 1
    page = _page(client, unit)
    assert kit.leak in key(page) and "answer shown" in page


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_nojs_check_and_reveal_paint_the_full_page(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    page = client.post(_url(unit, el), kit.half).content.decode()
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert kit.leak in key(page)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_nojs_previewer_check_paints_and_offers_reveal(client, kind):
    user = make_login(client, "prev_staff")
    user.is_staff = True  # staff + not enrolled = the previewer path
    user.save()
    unit = make_quiz_unit()
    kit, el = _add(unit, kind)
    page = client.post(_url(unit, el), {**kit.half, "attempt": "1"}).content.decode()
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    assert 'name="reveal"' in page
    page = client.post(_url(unit, el), {**kit.half, "reveal": "1"}).content.decode()
    assert kit.leak in key(page)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_editor_try_it_quiz_reveal(client, kind):
    pa = make_pa(client, f"pa_{kind}")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    kit, el = _add(unit, kind)
    url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk}
    )
    body = client.post(
        url, {**kit.half, "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert (
        paint(kind, yours(body)) == ["correct", "incorrect"] and 'name="reveal"' in body
    )
    body = client.post(
        url, {**kit.half, "reveal": "1", "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert kit.leak in key(body) and "answer shown" in body
    assert body.count("data-question-feedback") == 1 and 'name="reveal"' not in body
    assert QuestionResponse.objects.count() == 0


# ── results page + analytics ─────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_results_render_each_question_read_only(client, kind):
    unit = _quiz(client)
    kit, el = _add(unit, kind)
    _un_kit, _un_el = _add(unit, kind)  # left unanswered
    _fetch(client, unit, el, kit.half)
    _fetch(client, unit, el, {"reveal": "1"})
    body = _results(client, unit)
    answered, unanswered = body.split('class="quiz-results__item')[1:3]
    for row in (answered, unanswered):
        assert "data-answer-scope" in row and "<form" not in row
        assert 'type="submit"' not in row and "question__reveal" not in row
        assert "data-answer-switch" in row
        assert re.search(r"<fieldset[^>]*data-answer-yours[^>]*\bdisabled", row)
        assert all("disabled" in c for c in _CONTROL.findall(key(row)))
    assert paint(kind, yours(answered)) == ["correct", "incorrect"]
    assert paint(kind, yours(unanswered)) == [None, None]
    assert "answer shown" in answered


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_results_helper_never_marks_an_unanswered_row(monkeypatch, kind):
    from courses import views

    unit = make_quiz_unit()
    kit, el = _add(unit, kind)
    row = views._results_row(kit.question, None)

    def _boom(*args, **kwargs):
        raise AssertionError("mark() called for an unanswered results row")

    monkeypatch.setattr(type(kit.question), "mark", _boom)
    html = str(views._results_question_html(el, kit.question, None, row))
    assert kit.leak in key(html) and paint(kind, yours(html)) == [None, None]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
@pytest.mark.parametrize("answered", [True, False])
def test_analytics_still_shows_the_expected_answer(client, kind, answered):
    # Spec §5: _results_row keeps its keys; analytics shows the expected answer.
    user = make_login(client, "stu_an")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    kit, el = _add(unit, kind, max_attempts=1)
    if answered:
        _fetch(client, unit, el, kit.half)
    _results(client, unit)
    client.logout()
    make_pa(client, "pa_an")
    url = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": unit.course.slug, "student_pk": user.pk, "node_pk": unit.pk},
    )
    assert kit.key_text in client.get(url).content.decode()


# ── lessons (D13, spec §5a) ──────────────────────────────────────────────────


def _lesson(client, kind, username="ls"):
    student = make_student(client, username)
    course, unit = make_course_with_unit()
    Enrollment.objects.create(student=student, course=course)
    kit = build(kind)
    el = add_element(unit, kit.question)
    url = reverse(
        "courses:check_answer",
        kwargs={"slug": course.slug, "node_pk": unit.pk, "element_pk": el.pk},
    )
    return kit, unit, el, url


def _lesson_page(client, unit):
    return client.get(
        reverse(
            "courses:lesson_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_lesson_fetch_check_paints_in_place_no_list(client, kind):
    kit, _unit, _el, url = _lesson(client, kind)
    body = client.post(url, kit.half, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert "data-question-inline" in body and "<form" in body
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    right, wrong = parts(kind, yours(body))
    assert _SR_BAD in wrong and 'aria-invalid="true"' in wrong
    assert _SR_OK in right and "aria-invalid" not in right
    _no_answers(kit, body)
    assert "Correct answer" not in body and "Correct token" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_lesson_nojs_restore_and_editor_try_paint(client, kind):
    kit, unit, _el, url = _lesson(client, kind)
    page = client.post(url, kit.half).content.decode()  # no-JS re-render
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    _no_answers(kit, page)
    page = _lesson_page(client, unit)  # practice-state restore
    assert paint(kind, yours(page)) == ["correct", "incorrect"]
    _no_answers(kit, page)
    pa = make_pa(client, f"pa_ls_{kind}")
    course = CourseFactory(owner=pa)
    lu = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="lesson")
    kit2, el2 = _add(lu, kind)
    try_url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el2.pk}
    )
    body = client.post(
        try_url, kit2.half, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert paint(kind, yours(body)) == ["correct", "incorrect"]
    _no_answers(kit2, body)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_lesson_correct_answer_keeps_controls_editable(client, kind):
    kit, _unit, _el, url = _lesson(client, kind)
    body = client.post(url, kit.right, HTTP_X_REQUESTED_WITH="fetch").content.decode()
    assert paint(kind, yours(body)) == ["correct", "correct"]
    assert "disabled" not in yours(body) and "data-lock-on-correct" not in body


# ── Review Focus (plan) ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_deleted_distractor_after_answer_renders_wrong(client):
    unit = _quiz(client)
    kit, el = _add(unit, "matchpair", max_attempts=1)
    _fetch(client, unit, el, kit.half)  # picked "gammadis" for part 2
    q = kit.question
    q.distractors = ""
    q.save()
    page = _page(client, unit)
    assert paint("matchpair", yours(page)) == ["correct", "incorrect"]
    wrong = parts("matchpair", yours(page))[1]
    assert '<option value="" selected>' in wrong  # placeholder: not in the pool
    assert "data-answer-key" in page
    assert (
        '<option value="gammadis"'
        not in _results(client, unit).split("quiz-results__item")[1]
    )


@pytest.mark.django_db
def test_key_copy_escapes_and_keeps_latex_tokens(client):
    unit = _quiz(client)
    kit, el = _add(unit, "dragfill", max_attempts=1)
    DragBlank.objects.filter(question=kit.question, order=1).update(correct_token="a<b")
    DragBlank.objects.filter(question=kit.question, order=0).update(
        correct_token=r"\(x^2\)"
    )
    body = _fetch(client, unit, el, {"slot": ["nope", "nope"]}).content.decode()
    k = key(body)
    assert 'value="a&lt;b" selected' in k and "<b" not in k.replace("&lt;b", "")
    assert 'value="\\(x^2\\)" selected' in k


@pytest.mark.django_db
def test_key_copy_preselects_normalised_duplicate(client):
    unit = _quiz(client)
    kit, el = _add(unit, "dragfill", max_attempts=1)
    DragBlank.objects.filter(question=kit.question, order=0).update(
        correct_token="paris"
    )
    DragBlank.objects.filter(question=kit.question, order=1).update(
        correct_token="Paris"
    )
    body = _fetch(client, unit, el, {"slot": ["gammadis", "gammadis"]}).content.decode()
    second = parts("dragfill", key(body))[1]
    assert 'value="paris" selected' in second  # the pool's surviving raw form


@pytest.mark.django_db
def test_dragimage_key_copy_geometry_unlocalized_in_pl():
    # Rendered directly: through a view, LocaleMiddleware would pick the language
    # from the request and override translation.override().
    unit = make_quiz_unit()
    kit, el = _add(unit, "dragimage", max_attempts=1)
    q = kit.question
    with translation.override("pl"):
        body = q.render(
            element=el,
            mode="quiz",
            action_url="/x/",
            feedback_for_pk=el.pk,
            submitted_values=["alphakey", "gammadis"],
            verdicts=[True, False],
            key_values=q.key_answer(),
            locked=True,
        )
    assert body.count('data-x="0.5"') == 2 and 'data-w="0.25"' in key(body)
    assert "0,5" not in body and "0,25" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_formless_render_keeps_its_controls(kind):
    # The `{% else %}` branch (no join row) renders through the same include.
    kit = build(kind)
    html = kit.question.render()
    assert len(parts(kind, html)) == 2
    if kind in DND_KINDS:
        assert re.search(r"\bdata-dnd(?=[\s=>])", html)
