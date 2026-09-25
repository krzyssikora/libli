"""Playwright: Show answer + switch in the live quiz and the editor (spec §2.3, §3.1)."""  # noqa: E501

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


def _seed_quiz(username, slug, max_attempts=3):
    from django.contrib.auth import get_user_model

    from courses.fillblank import parse
    from courses.models import Blank
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import FillBlankQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug)
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    q = FillBlankQuestionElement.objects.create(
        stem=parse("log {{11}} = {{9}} · {{2}} = {{22}}")[0], max_attempts=max_attempts
    )
    for i, a in enumerate(["11", "9", "2", "22"]):
        Blank.objects.create(question=q, order=i, accepted=a)
    Element.objects.create(unit=unit, content_object=q)
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_show_answer_flow_and_switch(browser, live_server):
    _student("rev_stu")
    course, unit = _seed_quiz("rev_stu", "e2e-reveal")
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_stu")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    blanks = q.locator("[data-answer-yours] input[name='blank']")
    blanks.nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator(".question__verdict.is-partial").wait_for(timeout=6000)
    assert "is-incorrect" in blanks.nth(1).get_attribute("class")
    # Measured, not just classed: app.css's input[type=text] (0,1,1) must not win.
    paint = "el => getComputedStyle(el).borderTopColor"
    assert blanks.nth(0).evaluate(paint) != blanks.nth(1).evaluate(paint)
    # Colours persist until the next Check (spec §1.2): editing a green part keeps it.
    blanks.nth(0).fill("12")
    assert "is-correct" in blanks.nth(0).get_attribute("class")
    blanks.nth(0).fill("11")
    # Confirm must be ACCEPTED explicitly: Playwright auto-dismisses dialogs.
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    yours = q.locator("[data-answer-view='yours']")
    assert yours.is_checked() and yours.is_enabled()  # not frozen
    key = q.locator("[data-answer-key]")
    assert not key.is_visible()
    q.locator("label:has([data-answer-view='key'])").click()
    assert key.is_visible() and key.locator("input").nth(1).input_value() == "9"
    # Reload with "Correct answer" SELECTED must still reopen on "Your answer"
    # (autocomplete="off" defeats form-state restoration, D3).
    page.reload()
    q = page.locator("[data-question]").first
    assert q.locator("[data-answer-view='yours']").is_checked()
    assert not q.locator("[data-answer-view='key']").is_checked()


@pytest.mark.django_db(transaction=True)
def test_results_page_switch_shows_the_key(browser, live_server):
    # On the results page the :has() scope is a plain <div data-answer-scope>, not a
    # form -- click the switch there too, not only in the quiz / editor.
    _student("rev_res")
    course, unit = _seed_quiz("rev_res", "e2e-reveal-results", max_attempts=1)
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_res")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)  # 1 attempt: locked
    page.once("dialog", lambda d: d.accept())
    page.locator("[data-finish-btn]").click()
    page.wait_for_url("**/results/**")
    row = page.locator(".quiz-results__item").first
    assert not row.locator("[data-answer-key]").is_visible()
    row.locator("label:has([data-answer-view='key'])").click()
    assert row.locator("[data-answer-key]").is_visible()
    assert not row.locator("[data-answer-yours]").is_visible()


@pytest.mark.django_db(transaction=True)
def test_short_text_verdict_colours_are_computed(browser, live_server):
    # Short text's .question__text-input.is-* rules sit on the app.css
    # input[type=text] collision: measure, don't trust the specificity argument.
    from django.contrib.auth import get_user_model

    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    _student("rev_st")
    user = get_user_model().objects.get(username="rev_st")
    course = CourseFactory(slug="e2e-reveal-st")
    Enrollment.objects.get_or_create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    for accepted in ("Paris", "Oslo"):
        Element.objects.create(
            unit=unit,
            content_object=ShortTextQuestionElement.objects.create(
                stem="?", accepted=accepted, max_attempts=3
            ),
        )
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_st")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    qs = page.locator("[data-question]")
    paint = "el => getComputedStyle(el).borderTopColor"
    plain = qs.nth(1).locator("input[name='answer']").evaluate(paint)
    qs.nth(0).locator("input[name='answer']").fill("Rome")
    qs.nth(0).locator("button[type='submit']:not([name='reveal'])").click()
    qs.nth(0).locator("input.is-incorrect").wait_for(timeout=6000)
    wrong = qs.nth(0).locator("input[name='answer']").evaluate(paint)
    assert wrong != plain


@pytest.mark.django_db(transaction=True)
def test_enter_in_a_blank_checks_not_reveals(browser, live_server):
    _student("rev_enter")
    course, unit = _seed_quiz("rev_enter", "e2e-reveal-enter")
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_enter")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)  # button now exists
    # NOW Enter: implicit submission uses the FIRST submit button -- which must be
    # Check. Show answer would lock and draw the switch.
    q.locator("input[name='blank']").nth(1).fill("5")
    # Sync on the Enter POST itself -- the partial verdict is ALREADY on screen from
    # the first Check, so waiting for it would pass before the response lands.
    with page.expect_request(
        lambda r: r.method == "POST" and "/answer/" in r.url
    ) as req:
        q.locator("input[name='blank']").nth(1).press("Enter")
    assert "reveal" not in (req.value.post_data or "")
    q.get_by_text("1 attempt left").wait_for(
        timeout=6000
    )  # only the Enter response says 1
    assert q.locator("[data-answer-switch]").count() == 0
    assert q.locator("[data-reveal-btn]").count() == 1


@pytest.mark.django_db(transaction=True)
def test_previewer_reveal_keeps_client_counter(browser, live_server):
    # The client counter only matters on the stateless previewer path.
    from django.contrib.auth import get_user_model

    _student("rev_prev")
    course, unit = _seed_quiz("rev_prev", "e2e-reveal-prev")
    user = get_user_model().objects.get(username="rev_prev")
    from courses.models import Enrollment

    Enrollment.objects.filter(student=user).delete()  # not enrolled ...
    user.is_staff = True  # ... but staff -> previewer
    user.save()
    page = browser.new_context().new_page()
    _login(page, live_server, "rev_prev")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)
    assert q.get_attribute("data-attempts-made") == "1"
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)
    assert q.get_attribute("data-attempts-made") == "1"


@pytest.mark.django_db(transaction=True)
def test_reveal_sent_when_submitter_is_missing(browser, live_server):
    # Old engines (Safari < 15.4) have no SubmitEvent.submitter: the click fallback
    # must still send reveal=1.
    _student("rev_old")
    course, unit = _seed_quiz("rev_old", "e2e-reveal-old")
    ctx = browser.new_context()
    ctx.add_init_script(
        "Object.defineProperty(SubmitEvent.prototype, 'submitter', {get() { return undefined; }});"  # noqa: E501
    )
    page = ctx.new_page()
    _login(page, live_server, "rev_old")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
    q = page.locator("[data-question]").first
    q.locator("input[name='blank']").nth(0).fill("11")
    q.locator("button[type='submit']:not([name='reveal'])").click()
    q.locator("[data-reveal-btn]").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())
    q.locator("[data-reveal-btn]").click()
    q.locator("[data-answer-switch]").wait_for(timeout=6000)


@pytest.mark.django_db(transaction=True)
def test_editor_try_it_reveal_switch_survives_freeze(browser, live_server):
    from courses.fillblank import parse
    from courses.models import Blank
    from courses.models import Element
    from courses.models import FillBlankQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.test_e2e_questions import _editor_url
    from tests.test_e2e_questions import _make_pa_user

    owner = _make_pa_user("rev_author")
    course = CourseFactory(slug="e2e-reveal-editor", owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    q = FillBlankQuestionElement.objects.create(
        stem=parse("{{11}} {{9}}")[0], max_attempts=3
    )
    Blank.objects.create(question=q, order=0, accepted="11")
    Blank.objects.create(question=q, order=1, accepted="9")
    Element.objects.create(unit=unit, content_object=q)

    page = browser.new_context().new_page()
    _login(page, live_server, "rev_author")
    page.goto(_editor_url(live_server, unit))
    q_el = page.locator('[data-scope="preview"] [data-question]').first
    q_el.locator("input[name='blank']").nth(0).fill("11")
    q_el.locator("button[type='submit']:not([name='reveal'])").click()
    q_el.locator("[data-reveal-btn]").wait_for(timeout=6000)
    page.once("dialog", lambda d: d.accept())
    q_el.locator("[data-reveal-btn]").click()
    q_el.locator("[data-answer-switch]").wait_for(timeout=6000)
    assert q_el.locator(
        "[data-answer-view='key']"
    ).is_enabled()  # editor freeze skipped it
    q_el.locator("label:has([data-answer-view='key'])").click()
    assert q_el.locator("[data-answer-key]").is_visible()
    # The reveal consumed no attempt: the client counter stayed at 1 (spec §3.1).
    assert q_el.get_attribute("data-attempts-made") == "1"
