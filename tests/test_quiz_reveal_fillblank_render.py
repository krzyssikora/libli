"""Fill in the blanks through the new render path (spec 2026-09-25 §2.2–§2.4, §4)."""

import re

import pytest

from courses.fillblank import parse
from courses.models import Blank
from courses.models import Element
from courses.models import FillBlankQuestionElement
from tests.factories import make_quiz_unit

_INPUT = re.compile(r"<input[^>]*>")


@pytest.fixture
def fb(db):
    unit = make_quiz_unit()
    token_stem, _ = parse("log {{11}} = {{9}}")
    q = FillBlankQuestionElement.objects.create(stem=token_stem, max_attempts=3)
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    return q, Element.objects.create(unit=unit, content_object=q)


def _render(q, el, **kw):
    kw.setdefault("mode", "quiz")
    kw.setdefault("action_url", "/x/")
    return q.render(element=el, feedback_for_pk=el.pk, **kw)


def test_unlocked_paints_and_offers_reveal_no_key(fb):
    q, el = fb
    html = _render(
        q,
        el,
        submitted_values=["11", "5"],
        verdicts=[True, False],
        can_reveal=True,
        reveal_earned="0.50",
    )
    right, wrong = _INPUT.findall(html)[:2]
    assert "is-correct" in right and "is-incorrect" in wrong
    assert 'aria-invalid="true"' in wrong and "aria-invalid" not in right
    # Colour is never the only cue (spec §2.1): each painted blank is followed by
    # its .sr-only verdict.
    assert re.search(r'value="5"[^>]*>\s*<span class="sr-only">incorrect</span>', html)
    assert re.search(r'value="11"[^>]*>\s*<span class="sr-only">correct</span>', html)
    assert "data-reveal-btn" in html and 'name="reveal"' in html
    assert "data-answer-key" not in html and "data-answer-switch" not in html
    assert html.count("data-question-feedback") == 1


def test_check_is_the_first_submit_button(fb):
    q, el = fb
    html = _render(q, el, submitted_values=["11", "5"], can_reveal=True)
    buttons = re.findall(r'<button[^>]*type="submit"[^>]*>', html)
    assert 'name="reveal"' not in buttons[0] and 'name="reveal"' in buttons[1]


def test_no_reveal_button_when_quiz_submitted(fb):
    q, el = fb
    html = _render(
        q, el, submitted_values=["11", "5"], can_reveal=True, quiz_submitted=True
    )
    assert 'name="reveal"' not in html


def test_locked_key_copy_is_nameless_disabled_unique_ids(fb):
    q, el = fb
    html = _render(
        q,
        el,
        submitted_values=["11", "5"],
        verdicts=[True, False],
        key_values=["11", "9"],
        locked=True,
    )
    key = html.split("data-answer-key")[1].split("data-answer-switch")[0]
    assert 'value="9"' in key
    assert "name=" not in key
    assert key.count("disabled") >= 2
    assert "data-answer-switch" in html
    # With the copy drawn: still ONE feedback box, ONE Check, no Show answer (locked).
    assert html.count("data-question-feedback") == 1
    assert (
        len(re.findall(r'<button[^>]*type="submit"(?![^>]*name="reveal")[^>]*>', html))
        == 1
    )  # noqa: E501
    assert 'name="reveal"' not in html
    yours_radio = re.search(r'<input[^>]*value="yours"[^>]*>', html).group(0)
    assert "checked" in yours_radio
    # (The -key id suffixing is pinned by Task 4's
    # test_ids_suffixed_internal_refs_rewritten_external_untouched: this render has no
    # ids at all, so a uniqueness check here could never fail.)


def test_switch_is_outside_every_fieldset(fb):
    q, el = fb
    html = _render(
        q, el, submitted_values=["11", "5"], key_values=["11", "9"], locked=True
    )
    before_switch = html.split("data-answer-switch")[0]
    assert before_switch.count("<fieldset") == before_switch.count("</fieldset>")


def test_results_mode_has_no_form_or_buttons(fb):
    q, el = fb
    html = _render(
        q,
        el,
        mode="results",
        submitted_values=["11", "5"],
        verdicts=[True, False],
        key_values=["11", "9"],
        locked=True,
        feedback_html="<p>line</p>",
    )
    assert "<form" not in html and "<button" not in html
    assert "data-answer-scope" in html and "<p>line</p>" in html
    # The results fieldset is `data-answer-yours disabled` (attribute order pinned
    # so this split sees the fieldset's own `disabled`).
    yours = html.split("data-answer-yours")[1].split("data-answer-key")[0]
    assert "disabled" in yours


def test_lesson_mode_paints_with_sr_text(fb):
    q, el = fb
    html = _render(
        q,
        el,
        mode="lesson",
        action_url=None,
        submitted_values=["11", "5"],
        mark_result=q.mark(["11", "5"]),
    )
    assert re.search(
        r'value="5"[^>]*aria-invalid="true"[^>]*>\s*<span class="sr-only">incorrect</span>',  # noqa: E501
        html,
    )
    right = re.search(r'<input[^>]*value="11"[^>]*>', html).group(0)
    assert "aria-invalid" not in right
    assert re.search(r'value="11"[^>]*>\s*<span class="sr-only">correct</span>', html)


def test_fill_gate_render_is_unchanged():
    from courses.fillblank import parse
    from courses.fillblank import render_inputs

    token_stem, _ = parse("{{a}}")
    assert "sr-only" not in render_inputs(token_stem, ["a"], locked=True)


@pytest.mark.django_db
def test_quiz_page_with_a_choice_question_still_renders(client):
    # _quiz_article.html forwards the new keys for EVERY question; choice overrides
    # render(), so its signature must accept them (a TypeError here 500s the page).
    from django.urls import reverse

    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from tests.factories import EnrollmentFactory
    from tests.factories import add_element
    from tests.factories import make_login

    user = make_login(client, "stu_ch")
    unit = make_quiz_unit()
    EnrollmentFactory(student=user, course=unit.course)
    q = ChoiceQuestionElement.objects.create(stem="?", max_attempts=3)
    Choice.objects.create(question=q, text="A", is_correct=True)
    add_element(unit, q)
    resp = client.get(
        reverse(
            "courses:quiz_unit", kwargs={"slug": unit.course.slug, "node_pk": unit.pk}
        )
    )
    assert resp.status_code == 200


def test_lesson_mode_never_draws_key_or_button(fb):
    q, el = fb
    html = _render(
        q,
        el,
        mode="lesson",
        action_url=None,
        submitted_values=["11", "5"],
        key_values=["11", "9"],
        can_reveal=True,
        locked=True,
    )
    assert "data-answer-key" not in html and 'name="reveal"' not in html
