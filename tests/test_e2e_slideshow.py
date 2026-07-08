"""Playwright e2e for unit-level slideshow mode client pagination (Task 8).

Tests:
  1. Prev/Next paginate a 3-slide lesson and update the counter; Next disables
     at the last slide.
  2. Arrow keys inside a text-input answer field do NOT change slides (the
     field owns the arrow key).
  3. Arrow keys inside a radio/select answer control do NOT change slides.
  4. Arrow keys DO paginate when focus is on the control bar / non-editable
     content (positive case for the same guard).
  5. A single-slide unit renders no control bar (degenerate no-op).

Marked e2e (excluded from the default run; run with -m e2e).
Mirrors the harness in tests/test_e2e_html_element.py.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import add_element
from tests.factories import make_verified_user
from tests.factories import seed_slideshow_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _unit_path(unit):
    from django.urls import reverse

    if unit.unit_type == "quiz":
        name = "courses:quiz_unit"
    else:
        name = "courses:lesson_unit"
    return reverse(name, kwargs={"slug": unit.course.slug, "node_pk": unit.pk})


def _seed_slideshow_lesson_3(username):
    """Enrolled lesson unit with 3 slides (t | brk | t | brk | t)."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "lesson", layout=["t", "brk", "t", "brk", "t"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_lesson_single(username):
    """Enrolled lesson unit with a single slide (no break -> no control bar)."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "lesson", layout=["t"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_quiz_text(username):
    """Enrolled quiz unit, 3 slides; slide 0 holds a short-text question."""
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = seed_slideshow_unit(course, "quiz", layout=["q", "brk", "t", "brk", "t"])
    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


def _seed_slideshow_quiz_choice(username):
    """Enrolled quiz unit, 3 slides; slide 0 holds a single-choice (radio) question."""
    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import SlideBreakElement
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory

    student = _seed_student(username)
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="quiz")

    q = ChoiceQuestionElement.objects.create(stem="Pick one", multiple=False)
    Choice.objects.create(question=q, text="A", is_correct=True)
    Choice.objects.create(question=q, text="B", is_correct=False)
    add_element(unit, q)
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="x"))
    add_element(unit, SlideBreakElement.objects.create())
    add_element(unit, TextElement.objects.create(body="x"))

    EnrollmentFactory(student=student, course=course)
    return student, _unit_path(unit)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_prev_next_paginate_and_counter(page, live_server):
    student, path = _seed_slideshow_lesson_3("s1")
    _login(page, live_server, "s1")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_be_visible()
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")
    expect(page.locator(".slide.is-active")).to_have_count(1)
    page.get_by_role("button", name="Next").click()
    expect(page.locator("[data-slideshow-counter]")).to_have_text("2 / 3")
    page.get_by_role("button", name="Next").click()
    expect(page.get_by_role("button", name="Next")).to_be_disabled()


@pytest.mark.django_db(transaction=True)
def test_arrow_in_text_field_does_not_change_slide(page, live_server):
    student, path = _seed_slideshow_quiz_text("s2")
    _login(page, live_server, "s2")
    page.goto(f"{live_server.url}{path}")
    field = page.locator(".slide.is-active input[type=text]").first
    field.click()
    field.press("ArrowRight")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")


@pytest.mark.django_db(transaction=True)
def test_arrow_in_select_or_radio_does_not_change_slide(page, live_server):
    # Non-caret answer control: arrows change the control's own selection, NOT
    # the slide.
    student, path = _seed_slideshow_quiz_choice("s3")
    _login(page, live_server, "s3")
    page.goto(f"{live_server.url}{path}")
    ctrl = page.locator(
        ".slide.is-active input[type=radio], .slide.is-active select"
    ).first
    ctrl.focus()
    ctrl.press("ArrowDown")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("1 / 3")


@pytest.mark.django_db(transaction=True)
def test_arrow_on_bar_advances_slide(page, live_server):
    # Positive case: arrows DO paginate when focus is on the control bar /
    # non-editable content.
    student, path = _seed_slideshow_lesson_3("s4")
    _login(page, live_server, "s4")
    page.goto(f"{live_server.url}{path}")
    page.get_by_role("button", name="Next").focus()
    page.keyboard.press("ArrowRight")
    expect(page.locator("[data-slideshow-counter]")).to_have_text("2 / 3")


@pytest.mark.django_db(transaction=True)
def test_single_slide_no_control_bar(page, live_server):
    student, path = _seed_slideshow_lesson_single("s5")
    _login(page, live_server, "s5")
    page.goto(f"{live_server.url}{path}")
    expect(page.locator(".slideshow-bar")).to_have_count(0)
