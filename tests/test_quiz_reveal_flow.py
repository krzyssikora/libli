"""Show answer + whole-element quiz responses end to end (spec 2026-09-25 §2.4, §3)."""

import re

import pytest
from django.urls import reverse

from courses.fillblank import parse
from courses.models import Attempt
from courses.models import Blank
from courses.models import ChoiceQuestionElement
from courses.models import Element
from courses.models import ExtendedResponseQuestionElement
from courses.models import FillBlankQuestionElement
from courses.models import QuestionElement
from courses.models import QuestionResponse
from courses.models import ShortTextQuestionElement
from tests.factories import EnrollmentFactory
from tests.factories import add_element
from tests.factories import make_login
from tests.factories import make_quiz_unit
from tests.reveal_pr3_kit import extended

_BLANK = re.compile(r'<input[^>]*name="blank"[^>]*>')


def _quiz(client, enrolled=True):
    user = make_login(client, "stu")
    unit = make_quiz_unit()
    if enrolled:
        EnrollmentFactory(student=user, course=unit.course)
    return user, unit


def _fb(unit, accepted=("11", "9"), **kw):
    kw.setdefault("max_attempts", 3)
    token_stem, _ = parse(" ".join("{{" + a + "}}" for a in accepted))
    q = FillBlankQuestionElement.objects.create(stem=token_stem, **kw)
    for i, a in enumerate(accepted):
        Blank.objects.create(question=q, order=i, accepted=a)
    return Element.objects.create(unit=unit, content_object=q)


def _url(unit, el):
    return f"/courses/{unit.course.slug}/u/{unit.pk}/quiz/q/{el.pk}/answer/"


def _fetch(client, unit, el, data):
    return client.post(_url(unit, el), data, HTTP_X_REQUESTED_WITH="fetch")


@pytest.mark.django_db
def test_check_returns_whole_element_painted_no_key(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    body = _fetch(client, unit, el, {"blank": ["11", "5"]}).content.decode()
    assert "data-question-inline" in body and "<form" in body
    right, wrong = _BLANK.findall(body)
    assert "is-correct" in right and "is-incorrect" in wrong
    assert "data-answer-key" not in body
    assert 'value="9"' not in body  # the key never leaves before the lock
    assert 'name="reveal"' in body


@pytest.mark.django_db
def test_reveal_locks_at_current_marks_without_an_attempt(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    body = _fetch(client, unit, el, {"blank": ["", ""], "reveal": "1"}).content.decode()
    r = QuestionResponse.objects.get(element=el)
    assert r.locked and r.revealed_at is not None
    assert r.attempt_count == 1 and Attempt.objects.filter(response=r).count() == 1
    assert "answer shown" in body and "Partly correct" in body
    assert "Answer recorded" not in body
    assert "data-answer-key" in body and 'value="9"' in body
    right, wrong = _BLANK.findall(body)[:2]  # stored answer, not the emptied form
    assert 'value="11"' in right and "is-correct" in right


@pytest.mark.django_db
def test_second_reveal_is_refused(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    _fetch(client, unit, el, {"reveal": "1"})
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 409
    assert QuestionResponse.objects.get(element=el).attempt_count == 1


@pytest.mark.django_db
def test_reveal_before_any_attempt_is_refused(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 409
    resp = client.post(_url(unit, el), {"reveal": "1"})
    assert resp.status_code == 302
    assert resp.url == reverse(
        "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )


@pytest.mark.django_db
def test_reveal_refused_for_not_marked_and_unconverted(client, monkeypatch):
    # PR 3 (spec 2026-09-25 §8): replaces the ChoiceQuestionElement half (converted
    # in PR 3) with ExtendedResponseQuestionElement, the only type still
    # unconverted at this point in the plan.
    monkeypatch.setattr(ExtendedResponseQuestionElement, "SUPPORTS_REVEAL", False)
    _u, unit = _quiz(client)
    nm = _fb(unit, marking_mode=QuestionElement.MarkingMode.NOT_MARKED)
    _fetch(client, unit, nm, {"blank": ["1", "2"]})  # locks on first submit
    assert _fetch(client, unit, nm, {"reveal": "1"}).status_code == 409
    q = extended(max_attempts=3)
    er = add_element(unit, q)
    QuestionResponse.objects.create(
        submission=QuestionResponse.objects.get(element=nm).submission,
        element=er,
        attempt_count=1,
        latest_answer="x",
    )
    assert _fetch(client, unit, er, {"reveal": "1"}).status_code == 409


@pytest.mark.django_db
def test_exhausted_but_unlocked_can_still_reveal(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=3)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    _fetch(client, unit, el, {"blank": ["11", "6"]})
    q = el.content_object
    q.max_attempts = 1  # author lowered the limit below the student's count
    q.save()
    assert _fetch(client, unit, el, {"reveal": "1"}).status_code == 200
    assert QuestionResponse.objects.get(element=el).locked


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
def test_locked_wrong_has_key_copy_and_no_old_list(client, kind):
    # Spec §2.1: a converted type's locked question shows the key copy and NEVER the
    # old _reveal_* list beside it -- in the fetch response and on resume.
    from courses.models import ShortNumericQuestionElement

    _u, unit = _quiz(client)
    if kind == "fillblank":
        el, data = _fb(unit, max_attempts=1), {"blank": ["11", "5"]}
    elif kind == "text":
        el = add_element(
            unit,
            ShortTextQuestionElement.objects.create(
                stem="?", accepted="Paris", max_attempts=1
            ),
        )
        data = {"answer": "Rome"}
    else:
        el = add_element(
            unit,
            ShortNumericQuestionElement.objects.create(
                stem="?", value="3.14", tolerance="0.01", max_attempts=1
            ),
        )
        data = {"answer": "9"}
    body = _fetch(client, unit, el, data).content.decode()
    page = client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()
    for html in (body, page):
        assert "data-answer-key" in html
        assert "question__reveal" not in html
        assert "Correct answer:" not in html and "Expected:" not in html


@pytest.mark.django_db
@pytest.mark.parametrize("kind", ["fillblank", "text", "number"])
@pytest.mark.parametrize("mode", ["N", "R"])
def test_not_marked_and_review_never_show_the_key(client, kind, mode):
    # Spec §2.2: N/R lock on first submission, are never "fully correct", and have a
    # non-None key_answer() -- only key_view's AUTO conjunct keeps the key hidden.
    from courses.models import ShortNumericQuestionElement

    _u, unit = _quiz(client)
    if kind == "fillblank":
        el, data = _fb(unit, marking_mode=mode), {"blank": ["11", "5"]}
    elif kind == "text":
        el = add_element(
            unit,
            ShortTextQuestionElement.objects.create(
                stem="?", accepted="Paris", marking_mode=mode
            ),
        )
        data = {"answer": "Rome"}
    else:
        el = add_element(
            unit,
            ShortNumericQuestionElement.objects.create(
                stem="?", value="3.14", marking_mode=mode
            ),
        )
        data = {"answer": "9"}
    body = _fetch(client, unit, el, data).content.decode()
    page = client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()
    for html in (body, page):
        assert "data-answer-key" not in html and "data-answer-switch" not in html


@pytest.mark.django_db
def test_nojs_enrolled_validation_keeps_prior_answer_painted(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    client.post(_url(unit, el), {"blank": ["11", "5"]})
    page = client.post(_url(unit, el), {"blank": ["", ""]}).content.decode()
    assert "is-validation" in page
    right, wrong = _BLANK.findall(page)[:2]
    assert 'value="11"' in right and "is-correct" in right
    assert 'value="5"' in wrong and "is-incorrect" in wrong
    assert "data-answer-key" not in page


@pytest.mark.django_db
def test_unlimited_attempts_partial_offers_reveal(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=None)
    body = _fetch(client, unit, el, {"blank": ["11", "5"]}).content.decode()
    assert 'name="reveal"' in body and "attempts left" not in body


@pytest.mark.django_db
def test_single_attempt_wrong_locks_with_key_no_button(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=1)
    body = _fetch(client, unit, el, {"blank": ["11", "5"]}).content.decode()
    assert "data-answer-key" in body and "data-answer-switch" in body
    assert 'name="reveal"' not in body


@pytest.mark.django_db
def test_validation_stays_a_fragment_for_converted_and_choice(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    body = _fetch(client, unit, el, {"blank": ["", ""]}).content.decode()
    assert "<form" not in body and "is-validation" in body
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    ch = add_element(unit, q)
    body = _fetch(client, unit, ch, {}).content.decode()
    assert "<form" not in body and "is-validation" in body


@pytest.mark.django_db
def test_resume_paints_and_offers_reveal_then_shows_key(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    page_url = reverse(
        "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
    )
    page = client.get(page_url).content.decode()
    right, wrong = _BLANK.findall(page)[:2]
    assert "is-correct" in right and "is-incorrect" in wrong
    assert 'name="reveal"' in page and "data-answer-key" not in page
    _fetch(client, unit, el, {"reveal": "1"})
    page = client.get(page_url).content.decode()
    assert "data-answer-key" in page and "answer shown" in page


@pytest.mark.django_db
def test_resume_after_blank_added(client):
    _u, unit = _quiz(client)
    el = _fb(unit, max_attempts=1)
    _fetch(client, unit, el, {"blank": ["11", "5"]})
    q = el.content_object
    Blank.objects.create(question=q, order=2, accepted="7")
    q.stem = parse("{{11}} {{9}} {{7}}")[0]
    q.save()
    page = client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    )
    assert page.status_code == 200
    blanks = _BLANK.findall(page.content.decode())
    assert len(blanks) == 3
    assert "is-incorrect" in blanks[2]  # mark() pads the short stored answer with ""


@pytest.mark.django_db
def test_nojs_reveal_rerenders_quiz_with_key(client):
    _u, unit = _quiz(client)
    el = _fb(unit)
    client.post(_url(unit, el), {"blank": ["11", "5"]})
    page = client.post(_url(unit, el), {"reveal": "1"}).content.decode()
    assert "data-answer-key" in page and "answer shown" in page


@pytest.mark.django_db
def test_previewer_reveal_divergences(client):
    user = make_login(client, "author")
    user.is_staff = True  # staff + not enrolled = the previewer path
    user.save()
    unit = make_quiz_unit()
    el = _fb(unit)
    # Empty form on reveal: marked as-is, locked, 0 marks, switch shown.
    body = _fetch(
        client, unit, el, {"blank": ["", ""], "reveal": "1", "attempt": "1"}
    ).content.decode()
    assert "answer shown" in body and "0 / 1" in body and "data-answer-switch" in body
    # Form edited after the last Check: the confirm text shows the Check's marks, the
    # lock marks the edited form -- they differ, accepted on this path (spec §3.3).
    body = _fetch(
        client, unit, el, {"blank": ["11", "5"], "attempt": "1"}
    ).content.decode()
    assert "(0.5 of 1)" in body
    body = _fetch(
        client, unit, el, {"blank": ["", "5"], "reveal": "1", "attempt": "1"}
    ).content.decode()
    assert "answer shown" in body and "0 / 1" in body
    # Fully correct form on reveal: Correct, no switch.
    body = _fetch(
        client, unit, el, {"blank": ["11", "9"], "reveal": "1", "attempt": "1"}
    ).content.decode()
    assert (
        "Correct" in body
        and "answer shown" in body
        and "data-answer-switch" not in body
    )


def _staff_previewer(client):
    user = make_login(client, "prev_staff")
    user.is_staff = True  # staff + not enrolled = the previewer path
    user.save()
    return make_quiz_unit()


@pytest.mark.django_db
def test_nojs_previewer_check_paints_and_offers_reveal(client):
    # The previewer has no stored responses, so the no-JS re-render only shows
    # the colours / button through _quiz_render_feedback's st.update(state).
    unit = _staff_previewer(client)
    el = _fb(unit)
    page = client.post(
        _url(unit, el), {"blank": ["11", "5"], "attempt": "1"}
    ).content.decode()
    right, wrong = _BLANK.findall(page)[:2]
    assert "is-correct" in right and "is-incorrect" in wrong
    assert 'name="reveal"' in page


@pytest.mark.django_db
def test_nojs_previewer_reveal_works(client):
    # No `attempt` is posted without JS: parse_attempt floors it at 1 (spec §3.3), so
    # the previewer's Show answer still reveals.
    unit = _staff_previewer(client)
    el = _fb(unit)
    page = client.post(
        _url(unit, el), {"blank": ["11", "5"], "reveal": "1"}
    ).content.decode()
    assert "answer shown" in page and "data-answer-key" in page


@pytest.mark.django_db
def test_nojs_previewer_validation_keeps_empty_form(client):
    unit = _staff_previewer(client)
    el = _fb(unit)
    page = client.post(
        _url(unit, el), {"blank": ["", ""], "attempt": "1"}
    ).content.decode()
    assert "is-validation" in page
    assert all(
        "is-correct" not in t and "is-incorrect" not in t for t in _BLANK.findall(page)
    )


@pytest.mark.django_db
def test_ephemeral_fetch_validation_is_a_fragment(client):
    unit = _staff_previewer(client)
    el = _fb(unit)
    body = _fetch(
        client, unit, el, {"blank": ["", ""], "attempt": "1"}
    ).content.decode()
    assert "<form" not in body and "is-validation" in body
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    ch = add_element(unit, q)
    body = _fetch(client, unit, ch, {"attempt": "1"}).content.decode()
    assert "<form" not in body and "is-validation" in body


@pytest.mark.django_db
def test_key_edit_then_reveal_keeps_stored_marks(client):
    _u, unit = _quiz(client)
    el = _fb(unit, ["11", "9", "2", "22"])
    _fetch(client, unit, el, {"blank": ["11", "", "", ""]})  # stored 0.25
    Blank.objects.filter(question=el.content_object, order=1).update(accepted="")
    body = _fetch(client, unit, el, {"reveal": "1"}).content.decode()
    assert "0.25 / 1" in body


@pytest.mark.django_db
def test_confirm_marks_match_line_marks(client):
    _u, unit = _quiz(client)
    el = _fb(unit, ["11", "9", "2", "22"])
    body = _fetch(client, unit, el, {"blank": ["11", "", "", ""]}).content.decode()
    assert "(0.25 of 1)" in body and "0.25 / 1" in body


@pytest.mark.django_db
def test_key_edit_after_stored_correct_paints_all_green(client):
    # NOTE: on resume a stored-correct fill-blank renders render_inputs(locked=True),
    # which is all is-correct regardless of verdicts -- this guards resume only.
    # The override in quiz_render_state is pinned by the RESULTS-page test in
    # Task 10 (test_results_stored_correct_key_edited_all_green).
    _u, unit = _quiz(client)
    el = _fb(unit)
    _fetch(client, unit, el, {"blank": ["11", "9"]})
    Blank.objects.filter(question=el.content_object, order=1).update(accepted="7")
    page = client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    ).content.decode()
    assert all("is-correct" in t for t in _BLANK.findall(page)[:2])


@pytest.mark.django_db
def test_locked_choice_still_whole_element_with_marks(client):
    _u, unit = _quiz(client)
    from courses.models import Choice

    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=1)
    Choice.objects.create(question=q, text="A", is_correct=True)
    b = Choice.objects.create(question=q, text="B", is_correct=False)
    el = add_element(unit, q)
    body = _fetch(
        client, unit, el, {"choice": str(b.pk)}
    ).content.decode()  # WRONG, locks
    assert "<form" in body and "question__choice-marker" in body
    # Spec §2.2: a wrong locked choice keeps its inline marks -- no switch, no copy.
    assert "data-answer-switch" not in body and "data-answer-key" not in body


@pytest.mark.django_db
def test_editor_try_quiz_reveal(client):
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import make_pa

    pa = make_pa(client, "pa")
    course = CourseFactory(owner=pa)
    unit = ContentNodeFactory(course=course, parent=None, kind="unit", unit_type="quiz")
    el = _fb(unit)
    url = reverse(
        "courses:manage_element_try", kwargs={"slug": course.slug, "pk": el.pk}
    )
    body = client.post(
        url, {"blank": ["11", "5"], "attempt": "1"}, HTTP_X_REQUESTED_WITH="fetch"
    ).content.decode()
    assert 'name="reveal"' in body and "is-incorrect" in body
    body = client.post(
        url,
        {"blank": ["11", "5"], "reveal": "1", "attempt": "1"},
        HTTP_X_REQUESTED_WITH="fetch",
    ).content.decode()
    assert "data-answer-key" in body and "answer shown" in body
    assert body.count("data-question-feedback") == 1
    assert body.count('name="reveal"') == 0  # locked: no second Show answer
    assert QuestionResponse.objects.count() == 0
