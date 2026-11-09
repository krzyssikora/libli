"""e2e: a locked quiz choice question shows WHICH option the student picked.

The defect this pins is purely visual and so cannot be caught by markup assertions:
the chosen input is always `checked` in the DOM, but it is hidden and locking the
question disables it, so only the card can show the pick. A correct answer must not
render a green "Correct" verdict beside options that all look untouched.

These tests therefore MEASURE rendered colours (the picked card against an unpicked
one) rather than trusting `to_be_visible()` — see the same trap in tests/test_e2e_*:
a non-empty box is not evidence of legibility.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.e2e_pick import pick
from tests.factories import TEST_PASSWORD
from tests.factories import attempts
from tests.factories import make_verified_user

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


def _seed(username, slug, max_attempts=1):
    from django.contrib.auth import get_user_model

    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    student = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    q = ChoiceQuestionElement.objects.create(
        stem="<p>Capital of France?</p>", multiple=False, **attempts(max_attempts)
    )
    Choice.objects.create(question=q, text="Paris", is_correct=True, order=0)
    Choice.objects.create(question=q, text="London", is_correct=False, order=1)
    Choice.objects.create(question=q, text="Berlin", is_correct=False, order=2)
    Element.objects.create(unit=unit, content_object=q)
    return course, unit


def _bg(locator):
    return locator.evaluate("el => getComputedStyle(el).backgroundColor")


def _border(locator):
    return locator.evaluate("el => getComputedStyle(el).borderTopColor")


@pytest.mark.django_db(transaction=True)
def test_correct_answer_visibly_marks_the_chosen_option(page, live_server):
    make_verified_user(
        username="stuA", email="stuA@t.example.com", password=TEST_PASSWORD
    )
    course, unit = _seed("stuA", "e2e-choice-correct")
    _login(page, live_server, "stuA")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")

    options = page.locator(".question__choice")
    pick(options.nth(0).locator("input"))
    page.locator("form.question__form button[type=submit]").click()
    expect(page.locator(".question__verdict.is-correct")).to_be_visible()

    picked, other = options.nth(0), options.nth(1)
    # The card the student chose must be distinguishable from one they did not:
    # the input is hidden, so its card is all that shows what they picked.
    assert _bg(picked) != _bg(other), (
        "the chosen card renders identically to an unchosen one, so nothing shows "
        "the student what they picked"
    )
    assert _border(picked) != _border(other)
    expect(picked.locator(".question__choice-marker--correct")).to_have_count(1)
    # The tick IS the reveal; no duplicate answer list underneath.
    expect(page.locator(".question__reveal")).to_have_count(0)


@pytest.mark.django_db(transaction=True)
def test_wrong_answer_separates_the_pick_from_the_answer_key(page, live_server):
    make_verified_user(
        username="stuB", email="stuB@t.example.com", password=TEST_PASSWORD
    )
    course, unit = _seed("stuB", "e2e-choice-wrong")
    _login(page, live_server, "stuB")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")

    options = page.locator(".question__choice")
    pick(options.nth(1).locator("input"))  # London — wrong
    page.locator("form.question__form button[type=submit]").click()
    expect(page.locator(".question__verdict.is-incorrect")).to_be_visible()

    # The student's wrong pick is crossed; the correct option they missed is flagged
    # separately, so the two are never confused for each other.
    expect(options.nth(1).locator(".question__choice-marker--wrong")).to_have_count(1)
    expect(options.nth(0).locator(".question__choice-marker--missed")).to_have_count(1)
    assert _bg(options.nth(1)) != _bg(options.nth(2))


@pytest.mark.django_db(transaction=True)
def test_only_the_pick_is_marked_while_attempts_remain(page, live_server):
    make_verified_user(
        username="stuC", email="stuC@t.example.com", password=TEST_PASSWORD
    )
    course, unit = _seed("stuC", "e2e-choice-open", max_attempts=3)
    _login(page, live_server, "stuC")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")

    options = page.locator(".question__choice")
    pick(options.nth(1).locator("input"))  # wrong, but 2 attempts left
    page.locator("form.question__form button[type=submit]").click()
    expect(page.locator(".question__verdict.is-incorrect")).to_be_visible()

    # PR 3 (spec 2026-09-25 §2.1): replaces
    # `expect(page.locator(".question__choice-marker")).to_have_count(0)` -- choice
    # now marks the pick (✗) from the first Check; only the correct, unpicked
    # option must stay withheld until the lock.
    expect(options.nth(1).locator(".question__choice-marker--wrong")).to_have_count(1)
    expect(options.nth(0).locator(".question__choice-marker--missed")).to_have_count(0)
    expect(options.nth(2).locator(".question__choice-marker")).to_have_count(0)
    expect(options.nth(0).locator("input")).to_be_enabled()
