"""Multiple choice in the quiz answer reveal (spec 2026-09-25 §1, §2.1, §2.6, §4, D8).

Task 1: picks painted from the first Check, nothing on an unpicked option before the
lock. Task 2 adds Show answer and the results page (same file)."""

import dataclasses
import re

import pytest
from django.test.signals import template_rendered
from django.urls import reverse

from courses.models import Choice
from courses.models import QuestionResponse
from tests.factories import ContentNodeFactory
from tests.factories import CourseFactory
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_pa
from tests.factories import make_quiz_unit
from tests.reveal_pr3_kit import choice
from tests.reveal_pr3_kit import markers
from tests.reveal_pr3_kit import option

UNMARKED = {"Alphaopt": None, "Betaopt": None, "Gammaopt": None}
HALF = {"Alphaopt": "correct", "Betaopt": None, "Gammaopt": "wrong"}
LOCKED_HALF = {"Alphaopt": "correct", "Betaopt": "missed", "Gammaopt": "wrong"}


def _quiz(client, username="stu"):
    user = make_login(client, username)
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    return unit


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


# ── hooks ─────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_part_verdicts_one_entry_per_option_picked_only():
    kit = choice()
    q = kit.question
    result = q.mark({kit.a.pk, kit.c.pk})
    assert q.part_verdicts(result, {kit.a.pk, kit.c.pk}) == [True, None, False]
    assert q.part_verdicts(q.mark(set()), set()) == [None, None, None]
    single = choice(multiple=False)
    sq = single.question
    assert sq.part_verdicts(sq.mark({single.c.pk}), {single.c.pk}) == [
        None,
        None,
        False,
    ]


@pytest.mark.django_db
def test_choice_marks_unlocked_quiz_reads_verdicts_never_mark_result():
    kit = choice()
    q = kit.question
    choices = list(q.choices.all())
    picked = {kit.a.pk, kit.c.pk}
    full = q.mark(picked)  # carries the key: must be ignored while unlocked
    marks = q.choice_marks(
        choices, picked, full, "quiz", False, verdicts=[True, None, False]
    )
    assert {pk: m["kind"] for pk, m in marks.items()} == {
        kit.a.pk: "correct",
        kit.c.pk: "wrong",
    }
    # Unlocked without verdicts: nothing, even when handed a mark_result.
    assert q.choice_marks(choices, picked, full, "quiz", False) == {}


@pytest.mark.django_db
def test_choice_marks_locked_adds_missed_unless_fully_correct():
    kit = choice()
    q = kit.question
    choices = list(q.choices.all())
    picked = {kit.a.pk, kit.c.pk}
    wrong = q.mark(picked)
    marks = q.choice_marks(
        choices, picked, wrong, "quiz", True, verdicts=[True, None, False]
    )
    assert marks[kit.b.pk]["kind"] == "missed"
    # §2.6 reverse case (P4): a stored-correct answer shows no ＋ whatever the
    # fresh key. MarkResult is a frozen dataclass: build the stored-correct
    # result with replace().
    stored_correct = dataclasses.replace(wrong, correct=True)
    marks = q.choice_marks(
        choices, picked, stored_correct, "quiz", True, verdicts=[True, None, True]
    )
    assert {m["kind"] for m in marks.values()} == {"correct"} and kit.b.pk not in marks
    # Analytics' call (no verdicts): picks from the key, as on master.
    marks = q.choice_marks(choices, picked, q.mark(picked), "quiz", True)
    assert {pk: m["kind"] for pk, m in marks.items()} == {
        kit.a.pk: "correct",
        kit.b.pk: "missed",
        kit.c.pk: "wrong",
    }


# ── quiz: before the lock ─────────────────────────────────────────────────────


@pytest.mark.django_db
def test_unlocked_wrong_check_marks_picks_and_leaks_nothing(client):
    # The PR 3 no-leak test (spec §2.1): an unlocked, wrong choice question's HTML
    # carries no marker, class or attribute on any unpicked option.
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    before = option(_page(client, unit), "Betaopt")
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert markers(body) == HALF
    assert option(body, "Betaopt") == before  # byte-identical to the pre-Check markup
    assert "question__choice--picked" not in body  # tint stays locked-only (P3)
    assert "question__choices--marked" in body  # markers sit inline (P3)
    assert "correct answer, not chosen" not in body and "Betafb" not in body
    assert "data-answer-key" not in body and "data-answer-switch" not in body


@pytest.mark.django_db
def test_unlocked_render_context_has_no_mark_result(client):
    # Spec §2.1: mark_result (whose reveal is the whole key) stays None in an
    # unlocked choice render's context.
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    seen = []

    def grab(sender, template, context, **kwargs):
        if template.name == "courses/elements/choicequestion.html":
            seen.append(context.get("mark_result"))

    unit2 = make_quiz_unit(course=unit.course)
    kit2 = choice()
    el2 = add_element(unit2, kit2.question)
    template_rendered.connect(grab)
    try:
        _fetch(client, unit, el, kit.half)  # fetch Check
        _page(client, unit)  # resume
        client.post(_url(unit2, el2), kit2.half)  # no-JS re-render
    finally:
        template_rendered.disconnect(grab)
    assert seen and all(m is None for m in seen)


@pytest.mark.django_db
def test_unlocked_single_choice_marks_only_the_pick(client):
    unit = _quiz(client)
    kit = choice(multiple=False)
    el = add_element(unit, kit.question)
    before = option(_page(client, unit), "Alphaopt")
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert markers(body) == {"Alphaopt": None, "Betaopt": None, "Gammaopt": "wrong"}
    assert option(body, "Alphaopt") == before


@pytest.mark.django_db
def test_option_feedback_waits_for_the_lock(client):
    # P2: Gammafb (a wrong pick) and Betafb (a missed correct option -- names the
    # key) are both withheld until the question locks.
    unit = _quiz(client)
    kit = choice(max_attempts=2)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert "Gammafb" not in body and "Betafb" not in body
    body = _fetch(client, unit, el, kit.half).content.decode()  # last attempt: locked
    assert "Gammafb" in body and "Betafb" in body


@pytest.mark.django_db
def test_resume_nojs_previewer_and_editor_paint_the_same(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    assert markers(_page(client, unit)) == HALF  # resume
    unit2 = make_quiz_unit(course=unit.course)
    kit2 = choice()
    el2 = add_element(unit2, kit2.question)
    assert (
        markers(client.post(_url(unit2, el2), kit2.half).content.decode()) == HALF
    )  # no-JS
    client.logout()
    staff = make_login(client, "prev_staff")
    staff.is_staff = True  # staff + not enrolled = the previewer path
    staff.save()
    unit3 = make_quiz_unit()
    kit3 = choice()
    el3 = add_element(unit3, kit3.question)
    fetched = _fetch(client, unit3, el3, {**kit3.half, "attempt": "1"}).content.decode()
    assert markers(fetched) == HALF
    nojs = client.post(_url(unit3, el3), {**kit3.half, "attempt": "1"}).content.decode()
    assert markers(nojs) == HALF
    client.logout()
    pa = make_pa(client, "pa_choice")
    course = CourseFactory(owner=pa)
    qunit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz"
    )
    kit4 = choice()
    el4 = add_element(qunit, kit4.question)
    url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el4.pk}
    )
    body = client.post(
        url, {**kit4.half, "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert markers(body) == HALF


@pytest.mark.django_db
def test_locked_wrong_marks_all_three_with_no_switch(client):
    # D8: ✓ ✗ ＋ on the options, no switch, no key copy.
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert markers(body) == LOCKED_HALF
    assert "question__choice--picked" in body
    assert "data-answer-switch" not in body and "data-answer-key" not in body
    assert markers(_page(client, unit)) == LOCKED_HALF


@pytest.mark.django_db
def test_stored_correct_then_key_edited_shows_picks_correct_no_missed(client):
    # Spec §2.6 reverse case (P4).
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.right)
    Choice.objects.filter(pk=kit.b.pk).update(is_correct=False)
    Choice.objects.filter(pk=kit.c.pk).update(is_correct=True)
    page = _page(client, unit)
    assert markers(page) == {
        "Alphaopt": "correct",
        "Betaopt": "correct",
        "Gammaopt": None,
    }
    # B is now wrong-and-picked, so it is in the fresh `annotated`; its feedback
    # (written for a wrong pick) must not print beside the ✓ (P4).
    assert "Betafb" not in page


@pytest.mark.django_db
def test_edited_options_after_answer_render(client):
    # Review Focus 1: a picked option deleted, a new correct option added.
    unit = _quiz(client)
    kit = choice(max_attempts=2)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    kit.c.delete()
    Choice.objects.create(question=kit.question, text="Deltaopt", is_correct=True)
    page = _page(client, unit)
    assert "Gammaopt" not in page
    assert "question__choice-marker--missed" not in page  # not locked yet
    body = _fetch(client, unit, el, {"choice": [kit.a.pk]}).content.decode()  # locks
    assert option(body, "Deltaopt").count("question__choice-marker--missed") == 1
    assert QuestionResponse.objects.get(element=el).locked


# ── Task 2: Show answer ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_show_answer_offered_after_a_wrong_check_check_first(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    assert 'name="reveal"' not in _page(client, unit)  # no button before a Check
    body = _fetch(client, unit, el, kit.half).content.decode()
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', body)
    assert 'name="reveal"' not in buttons[0]  # Check first (spec §3.1)
    assert sum('name="reveal"' in b for b in buttons) == 1
    assert "data-confirm" in body and "(0 of 1)" in body


@pytest.mark.django_db
def test_enrolled_reveal_locks_marks_missed_and_uses_no_attempt(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    # The posted answer is ignored (spec §3.2): the stored picks are shown.
    body = _fetch(
        client, unit, el, {"reveal": "1", "choice": [kit.b.pk]}
    ).content.decode()
    assert markers(body) == LOCKED_HALF
    assert "answer shown" in body and 'name="reveal"' not in body
    assert "data-answer-switch" not in body  # D8
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.revealed_at is not None and r.attempt_count == 1
    assert markers(_page(client, unit)) == LOCKED_HALF


@pytest.mark.django_db
def test_nojs_reveal_rerenders_the_page_locked(client):
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    client.post(_url(unit, el), kit.half)
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert markers(page) == LOCKED_HALF and "answer shown" in page


@pytest.mark.django_db
def test_previewer_and_editor_reveal_lock_ephemerally(client):
    staff = make_login(client, "prev_staff2")
    staff.is_staff = True
    staff.save()
    unit = make_quiz_unit()
    kit = choice()
    el = add_element(unit, kit.question)
    body = _fetch(
        client, unit, el, {**kit.half, "reveal": "1", "attempt": "1"}
    ).content.decode()
    assert markers(body) == LOCKED_HALF and "answer shown" in body
    client.logout()
    pa = make_pa(client, "pa_choice2")
    course = CourseFactory(owner=pa)
    qunit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz"
    )
    kit2 = choice()
    el2 = add_element(qunit, kit2.question)
    url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el2.pk}
    )
    body = client.post(
        url, {**kit2.half, "reveal": "1", "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert markers(body) == LOCKED_HALF and body.count("data-question-feedback") == 1
    assert QuestionResponse.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_choice_never_reveal(client, mode):
    unit = _quiz(client)
    kit = choice(marking_mode=mode)
    el = add_element(unit, kit.question)
    body = _fetch(client, unit, el, kit.half).content.decode()
    assert 'name="reveal"' not in body
    assert "question__choice-marker" not in body  # N/R: never a verdict
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 409
    client.logout()
    staff = make_login(client, f"prev_{mode}")
    staff.is_staff = True
    staff.save()
    unit2 = make_quiz_unit()
    kit2 = choice(marking_mode=mode)
    el2 = add_element(unit2, kit2.question)
    body = _fetch(
        client, unit2, el2, {**kit2.half, "reveal": "1", "attempt": "1"}
    ).content.decode()
    assert "answer shown" not in body


# ── Task 2: results page ──────────────────────────────────────────────────────


def _rows(html):
    return html.split('class="quiz-results__item')[1:]


@pytest.mark.django_db
def test_results_choice_rows_as_they_ended(client):
    unit = _quiz(client)
    wrong, unanswered, right = choice(), choice(), choice()
    el_w = add_element(unit, wrong.question)
    add_element(unit, unanswered.question)
    el_r = add_element(unit, right.question)
    _fetch(client, unit, el_w, wrong.half)
    _fetch(client, unit, el_w, {"reveal": "1"})
    _fetch(client, unit, el_r, right.right)
    rows = _rows(_results(client, unit))
    assert markers(rows[0]) == LOCKED_HALF and "answer shown" in rows[0]
    # Spec §4 (PR 3): an unanswered choice row shows ＋ on the correct options.
    assert markers(rows[1]) == {
        "Alphaopt": "missed",
        "Betaopt": "missed",
        "Gammaopt": None,
    }
    assert "Not answered" in rows[1]
    assert markers(rows[2]) == {
        "Alphaopt": "correct",
        "Betaopt": "correct",
        "Gammaopt": None,
    }
    for row in rows:
        assert "<form" not in row and 'type="submit"' not in row
        assert "question__reveal" not in row  # the old list is gone
        assert "data-answer-switch" not in row  # D8
        inputs = re.findall(r"<input\b[^>]*>", row)
        assert inputs and all("disabled" in i for i in inputs)


@pytest.mark.django_db
def test_results_stored_correct_key_edited_choice_shows_picks_correct(client):
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.right)
    Choice.objects.filter(pk=kit.b.pk).update(is_correct=False)
    # C becomes correct and is unpicked: without P4 it would get ＋ beside "Correct".
    Choice.objects.filter(pk=kit.c.pk).update(is_correct=True)
    row = _rows(_results(client, unit))[0]
    assert markers(row) == {
        "Alphaopt": "correct",
        "Betaopt": "correct",
        "Gammaopt": None,
    }
    assert "Correct" in row and "Betafb" not in row  # no wrong-pick feedback by a ✓


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["N", "R"])
def test_results_nr_choice_rows_show_picks_without_verdicts(client, mode):
    unit = _quiz(client)
    kit = choice(marking_mode=mode)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    row = _rows(_results(client, unit))[0]
    assert markers(row) == UNMARKED
    assert row.count("question__choice--picked") == 2  # the picks are still legible


@pytest.mark.django_db
def test_results_auto_row_answered_while_not_marked_shows_the_key(client):
    # Answered while N (no stored fraction), switched to AUTO before Finish:
    # _results_row reads it "not_answered"; like any unanswered auto row it shows
    # the key (spec §4) -- ＋ on the correct options, the picks kept.
    unit = _quiz(client)
    kit = choice(marking_mode="N")
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    kit.question.marking_mode = "A"
    kit.question.save()
    row = _rows(_results(client, unit))[0]
    assert markers(row) == LOCKED_HALF and "Not answered" in row


@pytest.mark.django_db
def test_edited_options_then_reveal_and_results_render(client):
    # Review Focus 1, the Task 2 paths: a picked option deleted and a correct one
    # added after the answer -- Show answer and the results page still render.
    unit = _quiz(client)
    kit = choice()
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    kit.c.delete()
    Choice.objects.create(question=kit.question, text="Deltaopt", is_correct=True)
    resp = _fetch(client, unit, el, {"reveal": "1"})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Gammaopt" not in body
    assert option(body, "Deltaopt").count("question__choice-marker--missed") == 1
    row = _rows(_results(client, unit))[0]
    assert "Gammaopt" not in row
    assert option(row, "Deltaopt").count("question__choice-marker--missed") == 1


@pytest.mark.django_db
def test_results_option_feedback_shows_on_marked_options(client):
    # The old list printed annotated feedback as question__nudge; the options now do.
    unit = _quiz(client)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    _fetch(client, unit, el, kit.half)
    row = _rows(_results(client, unit))[0]
    assert "Betafb" in option(row, "Betaopt") and "Gammafb" in option(row, "Gammaopt")


@pytest.mark.django_db
@pytest.mark.parametrize("answered", [True, False])
def test_analytics_still_shows_the_choice_key(client, answered):
    # Spec §5: _results_row keeps its keys; analytics shows the expected answer.
    user = make_login(client, "stu_an")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    kit = choice(max_attempts=1)
    el = add_element(unit, kit.question)
    if answered:
        _fetch(client, unit, el, kit.half)
    _results(client, unit)
    client.logout()
    make_pa(client, "pa_an")
    url = reverse(
        "courses:manage_analytics_student_quiz",
        kwargs={"slug": unit.course.slug, "student_pk": user.pk, "node_pk": unit.pk},
    )
    body = client.get(url).content.decode()
    assert "Alphaopt" in body and "Betaopt" in body
    # answer_summary._choice rows: a missed correct option is `is-missed` (B when
    # answered with A + C; A and B when unanswered), the key column is present.
    assert body.count("answers__option is-missed") == (1 if answered else 2)
    assert "Answer key" in body
