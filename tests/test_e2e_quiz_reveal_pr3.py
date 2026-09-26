# tests/test_e2e_quiz_reveal_pr3.py
"""Playwright: multiple choice and extended response in the quiz answer reveal
(spec 2026-09-25 §1, §3.1, §4, D7, D8)."""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed(username, slug, maker, unit_type="quiz"):
    from django.contrib.auth import get_user_model

    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="Q"
    )
    q = maker()
    Element.objects.create(unit=unit, content_object=q)
    return course, unit


def _url(live_server, course, unit, unit_type="quiz"):
    tail = "quiz/" if unit_type == "quiz" else ""
    return f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/{tail}"


def _check(q):
    q.locator("button[type='submit']:not([name='reveal'])").click()


def _reveal(page, q):
    # Register BEFORE the click: Playwright auto-dismisses a confirm (memory
    # playwright-auto-dismisses-confirm), which would silently cancel the reveal.
    page.once("dialog", lambda d: d.accept())
    q.locator("button[name='reveal']").click()


@pytest.mark.django_db(transaction=True)
def test_choice_marks_picks_then_show_answer_adds_missed(browser, live_server):
    from tests.reveal_pr3_kit import choice

    _student("c_stu")
    course, unit = _seed("c_stu", "e2e-pr3-choice", lambda: choice().question)
    page = browser.new_context().new_page()
    _login(page, live_server, "c_stu")
    page.goto(_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    q.get_by_label("Alphaopt").check()
    q.get_by_label("Gammaopt").check()
    _check(q)
    q.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    ok = q.locator(".question__choice-marker--correct")
    bad = q.locator(".question__choice-marker--wrong")
    assert ok.count() == 1 and bad.count() == 1
    assert q.locator(".question__choice-marker--missed").count() == 0
    colour = "el => getComputedStyle(el).color"
    assert ok.evaluate(colour) != bad.evaluate(colour)  # measured, not just classed
    # The marker sits on the option's own line (P3): same row as the option text.
    top = "el => Math.round(el.getBoundingClientRect().top)"
    # A `has=ok` filter would re-chain ok's full "[data-question] >> ..." selector
    # relative to each candidate .question__choice, which never matches (the
    # candidate has no nested [data-question]); a native CSS :has() avoids that.
    text = q.locator(
        ".question__choice:has(.question__choice-marker--correct)"
    ).locator(".question__choice-text")
    assert abs(ok.evaluate(top) - text.evaluate(top)) < 12
    # quiz.js keeps the client counter on [data-question] (set after a Check).
    assert q.get_attribute("data-attempts-made") == "1"
    _reveal(page, q)
    q.locator(".question__choice-marker--missed").wait_for(timeout=6000)
    assert q.locator(".question__choice-marker--missed").count() == 1
    assert "answer shown" in q.inner_text()
    assert q.get_attribute("data-attempts-made") == "1"  # a reveal is no attempt
    assert q.locator("[data-answer-switch]").count() == 0  # D8
    for box in q.locator("input[name='choice']").all():
        assert box.is_disabled()


@pytest.mark.django_db(transaction=True)
def test_extended_show_answer_reveals_keywords(browser, live_server):
    from tests.reveal_pr3_kit import extended

    _student("e_stu")
    course, unit = _seed("e_stu", "e2e-pr3-er", extended)
    page = browser.new_context().new_page()
    _login(page, live_server, "e_stu")
    page.goto(_url(live_server, course, unit))
    q = page.locator("[data-question]").first
    q.locator("textarea[name='answer']").fill("alphakw only")
    _check(q)
    q.locator(".question__verdict.is-partial").wait_for(timeout=6000)
    assert q.locator(".question__reveal-keywords").count() == 0
    assert q.locator("form form").count() == 0
    _reveal(page, q)
    q.locator(".question__reveal-keywords").wait_for(timeout=6000)
    assert q.locator("textarea[name='answer']").is_disabled()
    assert q.locator("textarea[name='answer']").input_value() == "alphakw only"
    assert "answer shown" in q.inner_text()


@pytest.mark.django_db(transaction=True)
def test_extended_lesson_check_lands_in_the_box(browser, live_server):
    # Review Focus 4: data-question-inline + a fragment response (P5).
    from tests.reveal_pr3_kit import extended

    _student("el_stu")
    course, unit = _seed("el_stu", "e2e-pr3-erl", extended, unit_type="lesson")
    page = browser.new_context().new_page()
    _login(page, live_server, "el_stu")
    page.goto(_url(live_server, course, unit, unit_type="lesson"))
    q = page.locator("[data-question]").first
    q.locator("textarea[name='answer']").fill("nothing relevant")
    _check(q)
    box = q.locator("[data-question-feedback]")
    box.locator(".question__reveal-keywords").wait_for(timeout=6000)
    assert q.locator("form form").count() == 0
    assert q.locator("textarea[name='answer']").input_value() == "nothing relevant"


@pytest.mark.django_db(transaction=True)
def test_results_page_shows_choice_marks_and_keywords(browser, live_server):
    from courses.models import Element
    from tests.reveal_pr3_kit import choice
    from tests.reveal_pr3_kit import extended

    _student("r_stu")
    course, unit = _seed(
        "r_stu", "e2e-pr3-res", lambda: choice(max_attempts=1).question
    )
    Element.objects.create(unit=unit, content_object=extended(max_attempts=1))
    page = browser.new_context().new_page()
    _login(page, live_server, "r_stu")
    page.goto(_url(live_server, course, unit))
    q1 = page.locator("[data-question]").nth(0)
    q2 = page.locator("[data-question]").nth(1)
    q1.get_by_label("Gammaopt").check()
    _check(q1)
    q1.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    q2.locator("textarea[name='answer']").fill("nothing relevant")
    _check(q2)
    q2.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())  # Finish asks (data-confirm)
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/quiz/results/", timeout=6000)
    assert page.locator(".quiz-results__item form").count() == 0
    assert page.locator(".question__choice-marker--missed").count() == 2
    assert page.locator(".question__reveal-keywords").count() == 1
    boxes = page.locator(".quiz-results__item input, .quiz-results__item textarea")
    for box in boxes.all():
        assert box.is_disabled()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("unit_type", ["quiz", "lesson"])
def test_editor_try_it_extended(browser, live_server, unit_type):
    # The editor preview renders lesson markup in both unit types (P5): the quiz
    # try-it answers with the whole element (swap + freeze), the lesson try-it with
    # the fragment (the no-<form> fall-through). Pattern: PR 1's
    # tests/test_e2e_quiz_reveal.py::test_editor_try_it_reveal_switch_survives_freeze.
    from courses.models import Element
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.reveal_pr3_kit import extended
    from tests.test_e2e_questions import _editor_url
    from tests.test_e2e_questions import _make_pa_user

    owner = _make_pa_user(f"er_author_{unit_type}")
    course = CourseFactory(slug=f"e2e-pr3-er-editor-{unit_type}", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type=unit_type, parent=None, title="Q"
    )
    Element.objects.create(unit=unit, content_object=extended())
    page = browser.new_context().new_page()
    _login(page, live_server, f"er_author_{unit_type}")
    page.goto(_editor_url(live_server, unit))
    q = page.locator('[data-scope="preview"] [data-question]').first
    q.locator("textarea[name='answer']").fill("nothing relevant")
    _check(q)
    if unit_type == "lesson":
        q.locator("[data-question-feedback] .question__reveal-keywords").wait_for(
            timeout=6000
        )
        assert q.locator("form form").count() == 0
        assert q.locator("[data-reveal-btn]").count() == 0  # D11
        return
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)
    assert q.locator(".question__reveal-keywords").count() == 0  # not before the lock
    _reveal(page, q)
    q.locator(".question__reveal-keywords").wait_for(timeout=6000)
    assert q.locator("textarea[name='answer']").is_disabled()  # editor freeze
    assert q.locator("textarea[name='answer']").input_value() == "nothing relevant"
    assert q.locator("form form").count() == 0
    assert q.locator("[data-answer-switch]").count() == 0  # D7
    assert q.get_attribute("data-attempts-made") == "1"
