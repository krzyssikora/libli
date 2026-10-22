"""Playwright e2e: a correct lesson answer locks the question in the LIVE JS path.

The server side (fetch fragment, no-JS POST, reload) is covered for every
inline-feedback type by courses/tests/test_question_lock_on_correct.py. This file
drives the real UI for the two reported failure shapes:

* multiple choice: after a correct Check the student could still untick / tick
  options under the painted "correct" verdict, then print the page;
* short text: the hidden Check button still fires on implicit Enter, so a student
  could retype a solved answer and re-POST it over the stored practice state.

Marked e2e (excluded from the default run; run with -m e2e).
Harness mirrors test_e2e_fillblank_lock.py.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_unit(username, slug):
    from django.contrib.auth import get_user_model

    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    Enrollment.objects.get_or_create(student=owner, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="L"
    )
    return course, unit


def _open(browser, live_server, username, course, unit):
    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, username)
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("[data-question]")
    return ctx, page


@pytest.mark.django_db(transaction=True)
def test_correct_multiple_choice_locks_the_options(browser, live_server):
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element

    _make_pa_user("mclock_js")
    course, unit = _seed_unit("mclock_js", "e2e-mc-lock")
    q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=True)
    Choice.objects.create(question=q, text="a", is_correct=True, order=0)
    Choice.objects.create(question=q, text="b", is_correct=True, order=1)
    Choice.objects.create(question=q, text="c", is_correct=False, order=2)
    Element.objects.create(unit=unit, content_object=q)

    ctx, page = _open(browser, live_server, "mclock_js", course, unit)
    question = page.locator("[data-question]").first
    boxes = question.locator("input[name='choice']")

    # Wrong first: the lock is verdict-keyed, so a retry must stay possible.
    boxes.nth(0).check()
    boxes.nth(2).check()
    question.locator("button[type='submit']").click()
    question.locator(".question__verdict.is-incorrect").wait_for(timeout=6000)
    assert boxes.nth(2).is_enabled(), "a wrong answer must stay retryable"

    boxes.nth(2).uncheck()
    boxes.nth(1).check()
    question.locator("button[type='submit']").click()
    question.locator(".question__verdict.is-correct").wait_for(timeout=6000)

    for i in range(3):
        assert boxes.nth(i).is_disabled(), f"option {i} still live after correct"
    # A real click on a disabled checkbox must not change what is printed.
    question.locator(".question__choice-text").nth(0).click(force=True)
    question.locator(".question__choice-text").nth(2).click(force=True)
    states = [boxes.nth(i).is_checked() for i in range(3)]
    assert states == [True, True, False], f"solved picks changed: {states}"

    # And the reload (server restore) comes back locked with the same picks.
    page.reload()
    page.wait_for_selector("[data-question]")
    boxes = page.locator("[data-question]").first.locator("input[name='choice']")
    assert [boxes.nth(i).is_checked() for i in range(3)] == [True, True, False]
    assert all(boxes.nth(i).is_disabled() for i in range(3))

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_correct_short_text_ignores_enter(browser, live_server):
    from courses.models import Element
    from courses.models import ShortTextQuestionElement

    _make_pa_user("stlock_js")
    course, unit = _seed_unit("stlock_js", "e2e-st-lock")
    q = ShortTextQuestionElement.objects.create(stem="Capital?", accepted="paris")
    Element.objects.create(unit=unit, content_object=q)

    ctx, page = _open(browser, live_server, "stlock_js", course, unit)
    question = page.locator("[data-question]").first
    field = question.locator("input[name='answer']")

    field.fill("paris")
    question.locator("button[type='submit']").click()
    question.locator(".question__verdict.is-correct").wait_for(timeout=6000)
    assert field.is_disabled(), "the solved answer still accepts typing"

    # Assert on REQUESTS, not on a later DOM state: a re-POST is the harm.
    posts = []
    page.on(
        "request",
        lambda r: (
            posts.append(r.url) if r.method == "POST" and "/check/" in r.url else None
        ),
    )
    # Re-focus the field the way a student clicking back into it would (a disabled
    # input refuses focus, so Enter then lands on the body), retype, press Enter.
    field.evaluate("el => { el.focus(); el.value = 'london'; }")
    page.keyboard.press("Enter")
    # Absence of a request has no condition to wait on: a short fixed window.
    page.wait_for_timeout(500)
    assert posts == [], f"Enter re-submitted a solved answer: {posts}"

    ctx.close()


@pytest.mark.django_db(transaction=True)
def test_solved_choice_marks_its_picks_in_dark_mode(browser, live_server):
    # Chrome draws a disabled checkbox / radio grey whatever accent-color or opacity
    # says, so on the dark surface a locked tick was barely distinguishable from an
    # empty box. The locked options are drawn by CSS instead: a pick is filled with
    # the brand colour, a non-pick stays an empty outline.
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element

    _make_pa_user("mcdark_js")
    course, unit = _seed_unit("mcdark_js", "e2e-mc-dark")
    for multiple in (True, False):
        q = ChoiceQuestionElement.objects.create(stem="Pick", multiple=multiple)
        Choice.objects.create(question=q, text="a", is_correct=True, order=0)
        Choice.objects.create(question=q, text="b", is_correct=False, order=1)
        Element.objects.create(unit=unit, content_object=q)

    ctx, page = _open(browser, live_server, "mcdark_js", course, unit)
    page.evaluate("document.documentElement.dataset.theme = 'dark'")
    for i in range(2):
        question = page.locator("[data-question]").nth(i)
        question.locator("input[name='choice']").nth(0).check()
        question.locator("button[type='submit']").click()
        question.locator(".question__verdict.is-correct").wait_for(timeout=6000)
        boxes = question.locator("input[name='choice']")
        assert boxes.nth(0).is_disabled()
        picked, empty = (
            boxes.nth(k).evaluate("el => getComputedStyle(el).backgroundColor")
            for k in range(2)
        )
        primary = page.evaluate(
            "() => { const p = document.createElement('i');"
            " p.style.color = 'var(--primary)'; document.body.append(p);"
            " const c = getComputedStyle(p).color; p.remove(); return c; }"
        )
        kind = "checkbox" if i == 0 else "radio"
        assert empty != primary, f"an unpicked locked {kind} is filled: {empty}"
        if kind == "checkbox":
            assert picked == primary, f"a locked tick is not brand-filled: {picked}"
        else:
            # The radio is a ring + dot: the brand colour is on the border.
            ring = boxes.nth(0).evaluate("el => getComputedStyle(el).borderTopColor")
            assert ring == primary, f"a locked radio pick is not brand-ringed: {ring}"

    ctx.close()
