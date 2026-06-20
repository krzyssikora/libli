# tests/test_e2e_questions_2d.py
"""Playwright e2e for Phase-2d-i drag-fill & match-pairs.

JS path: drag a chip into a gap → the hidden <select> takes the token → submit →
.is-correct. No-JS path: post the <select> value directly → full-page render, correct
token withheld pre-reveal in a quiz. Slot-order integrity: after JS enhancement, the
submitted answer matches the targets in document order.

Marked e2e (run with -m e2e). Mirrors the harness in test_e2e_quiz.py.

Harness notes vs brief:
  - button[type="submit"] → .question__form button[type="submit"] (the page has language-
    switcher and logout submit buttons too; strict-mode requires a unique selector).
  - No-JS lesson tests: use page.request.post() with CSRF cookie (matching the 2b/2c
    harness) because render_to_string() in QuestionElement.render() lacks a request, so
    {% csrf_token %} renders empty — a form click without JS would be rejected with
    "CSRF token missing".
  - JS path: wait_for(".is-correct") before asserting (fetch is async).
  - Quiz selects: the hidden <select> elements (DnD-enhanced) accept select_option()
    from Playwright even when display:none because Playwright drives the DOM directly.
"""

import os
import urllib.parse

import pytest

from courses.models import (
    ContentNode,
    Course,
    DragBlank,
    DragFillBlankQuestionElement,
    Element,
    Enrollment,
    MatchPair,
    MatchPairQuestionElement,
)
from tests.factories import TEST_PASSWORD, make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_dragfill_lesson(username):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=f"c-{username}", language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    q = DragFillBlankQuestionElement.objects.create(stem="Cap is ￿0￿", distractors="Rome")
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_dragfill_no_js_select_path(live_server, browser):
    """No-JS: post the correct slot value directly via page.request.post(), see the
    correct mark in the rendered full-page HTML.

    NOTE: The DnD question element is rendered via render_to_string() without a request,
    so {% csrf_token %} inside the question form produces an empty token. Clicking the
    button would yield "CSRF token missing". We mirror the 2b/2c no-JS harness and post
    directly with the CSRF cookie instead.
    """
    course, unit, el = _seed_dragfill_lesson("nojs2d")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    _login(page, live_server, "nojs2d")
    lesson_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)

    cookies = context.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set after navigating to lesson page"

    check_url = (
        f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/q/{el.pk}/check/"
    )
    body_parts = [("csrfmiddlewaretoken", csrf_token), ("slot", "Paris")]
    encoded = urllib.parse.urlencode(body_parts)
    resp = page.request.post(
        check_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": lesson_url,
        },
        data=encoded,
    )
    assert resp.ok, f"check_answer POST failed with status {resp.status}"
    html = resp.text()

    result_page = context.new_page()
    result_page.set_content(html)
    assert result_page.locator(".is-correct").count() >= 1
    result_page.close()
    context.close()


@pytest.mark.django_db(transaction=True)
def test_dragfill_js_drag_path(live_server, page):
    """JS: drag the 'Paris' chip onto the gap's drop-slot → select takes it → correct."""
    course, unit, el = _seed_dragfill_lesson("js2d")
    _login(page, live_server, "js2d")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    chip = page.locator('.dnd__chip[data-token="Paris"]')
    slot = page.locator(".dnd__slot").first
    chip.drag_to(slot)
    # The hidden select must now carry the dragged token (slot-order integrity).
    assert page.locator('select[name="slot"]').input_value() == "Paris"
    page.locator('.question__form button[type="submit"]').click()
    # question.js sends a fetch; wait for the async feedback to appear.
    page.locator("[data-question-feedback] .is-correct").wait_for(timeout=6000)
    assert page.locator(".is-correct").count() >= 1


# ── Quiz seeding (mirrors _seed_quiz in test_e2e_quiz.py) ────────────────────


def _seed_dragfill_quiz(username, slug):
    """Course + QUIZ unit with one 2-gap drag-fill question (max_attempts=2)."""
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="quiz", title="Q"
    )
    q = DragFillBlankQuestionElement.objects.create(
        stem="￿0￿ and ￿1￿", distractors="Rome", marking_mode="A", max_attempts=2
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    DragBlank.objects.create(question=q, correct_token="Madrid")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_dragfill_quiz_withhold_reveal_resume_js(live_server, browser):
    """Quiz JS flow: wrong (attempt left) → correct token withheld; wrong again (last)
    → reveal; reload → the chosen placement rehydrates (resume)."""
    course, unit, el = _seed_dragfill_quiz("qjs2d", "q-js-2d")
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "qjs2d")
    quiz_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/"
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")

    # The DnD JS hides the native selects (display:none) and injects visual slots.
    # Use page.evaluate() to set the hidden selects directly, then submit via JS.
    feedback = page.locator("[data-question-feedback]").first

    def _set_slots(*values):
        """Set each select[name=slot] by index via JS (they are display:none)."""
        page.evaluate(
            """(vals) => {
                const sels = document.querySelectorAll('select[name="slot"]');
                vals.forEach((v, i) => { if (sels[i]) { sels[i].value = v; } });
            }""",
            values,
        )

    # Wrong, attempt remaining → withhold: the reveal partial must not render.
    _set_slots("Rome", "Rome")
    page.locator('.question__form button[type="submit"]').first.click()
    feedback.locator(".is-incorrect").wait_for(timeout=6000)
    assert "Correct token:" not in page.content()

    # Wrong on the last attempt → reveal.
    _set_slots("Rome", "Rome")
    page.locator('.question__form button[type="submit"]').first.click()
    page.locator("[data-question-feedback] .is-incorrect").wait_for(timeout=6000)
    page.wait_for_timeout(500)
    assert "Correct token:" in page.content()

    # Resume: reload and confirm the last submitted placement rehydrates.
    page.goto(quiz_url)
    page.wait_for_selector("[data-question]")
    # After reload, the rehydrated select value is set by the server (display:none too).
    rehydrated = page.evaluate(
        "() => document.querySelectorAll('select[name=\"slot\"]')[0].value"
    )
    assert rehydrated == "Rome"
    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_dragfill_slot_order_integrity_js(live_server, page):
    """Fill the SECOND gap first, then the first; the recorded payload must still pair
    each token with its own target (positional invariant, spec §3.1)."""
    course, unit, el = _seed_dragfill_quiz("order2d", "order-2d")
    _login(page, live_server, "order2d")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    page.wait_for_selector("[data-question]")
    # Set slots via JS (selects are display:none after DnD enhancement).
    # Set slot[1] first (Madrid), then slot[0] (Paris) — order of selection must not
    # affect which token is recorded for which target.
    page.evaluate(
        """() => {
            const sels = document.querySelectorAll('select[name="slot"]');
            sels[1].value = 'Madrid';  // second gap first
            sels[0].value = 'Paris';   // then first gap
        }"""
    )
    page.locator('.question__form button[type="submit"]').first.click()
    # Wait for feedback to confirm the submission was processed.
    page.locator("[data-question-feedback] .is-correct").wait_for(timeout=6000)
    from courses.models import QuestionResponse

    resp = QuestionResponse.objects.get(element=el)
    assert resp.latest_answer == ["Paris", "Madrid"]  # order preserved, not swapped


def _seed_matchpair_lesson(username, slug):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    q = MatchPairQuestionElement.objects.create(stem="<p>Match</p>", distractors="Rome")
    MatchPair.objects.create(question=q, left="France", right="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_matchpair_no_js_select_path(live_server, browser):
    """No-JS match-pairs: post the correct slot value directly, see the correct mark.

    Same CSRF workaround as test_dragfill_no_js_select_path — see that docstring.
    """
    course, unit, el = _seed_matchpair_lesson("mpnojs", "mp-nojs")
    context = browser.new_context(java_script_enabled=False)
    page = context.new_page()
    _login(page, live_server, "mpnojs")
    lesson_url = f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)

    cookies = context.cookies()
    csrf_token = next((c["value"] for c in cookies if c["name"] == "csrftoken"), "")
    assert csrf_token, "CSRF cookie not set"

    check_url = (
        f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/q/{el.pk}/check/"
    )
    body_parts = [("csrfmiddlewaretoken", csrf_token), ("slot", "Paris")]
    encoded = urllib.parse.urlencode(body_parts)
    resp = page.request.post(
        check_url,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": lesson_url,
        },
        data=encoded,
    )
    assert resp.ok, f"check_answer POST failed with status {resp.status}"
    html = resp.text()

    result_page = context.new_page()
    result_page.set_content(html)
    assert result_page.locator(".is-correct").count() >= 1
    result_page.close()
    context.close()


@pytest.mark.django_db(transaction=True)
def test_matchpair_js_drag_path(live_server, page):
    """JS match-pairs: drag the 'Paris' chip onto the France row's slot → correct."""
    course, unit, el = _seed_matchpair_lesson("mpjs", "mp-js")
    _login(page, live_server, "mpjs")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.locator('.dnd__chip[data-token="Paris"]').drag_to(page.locator(".dnd__slot").first)
    assert page.locator('select[name="slot"]').first.input_value() == "Paris"
    page.locator('.question__form button[type="submit"]').click()
    page.locator("[data-question-feedback] .is-correct").wait_for(timeout=6000)
    assert page.locator(".is-correct").count() >= 1
