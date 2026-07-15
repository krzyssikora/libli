"""Playwright e2e: inline per-option MCQ feedback lands in the LIVE choice form.

`question.js` must, for `data-question-inline` forms, swap the live form's inner
HTML (extracted from the full-element `check_answer` response) instead of the
bottom `[data-question-feedback]` slot, so per-option feedback renders inside
each `.question__choice` <li> rather than in a duplicate bottom reveal list.

Marked e2e (excluded from the default run; run with -m e2e).
Follows the harness in tests/test_e2e_questions.py verbatim (owner-login,
single `page`, no separate student context — see Task 5 plan notes).
"""

import os
import re

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _choice_li(question_el, text):
    """The `.question__choice` <li> whose option TEXT is exactly *text*.

    `.question__choice` uses substring has_text matching, which would let "A"
    also match the "trap C" <li> (it contains the letter "a"). Anchor on the
    leaf `.question__choice-text` span instead, then walk up to its <li>.
    """
    pattern = re.compile(rf"^{re.escape(text)}$")
    span = question_el.locator(".question__choice-text").filter(has_text=pattern)
    return span.locator("xpath=ancestor::li[1]")


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
    """Log in via the allauth HTML form (works with JS enabled or disabled)."""
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _seed_inline_feedback_question(username, slug):
    """PA-owned course + lesson unit with a multi-select MCQ: A correct
    (feedback "need A"), C a distractor (feedback "trap C"). No B option —
    the seed is deliberately just A/C so "tick only A" is unambiguous."""
    from django.contrib.auth import get_user_model

    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import add_element

    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="Lesson"
    )
    q = ChoiceQuestionElement.objects.create(
        stem="Pick the right one(s)", multiple=True
    )
    Choice.objects.create(question=q, text="A", is_correct=True, feedback="need A")
    Choice.objects.create(question=q, text="C", is_correct=False, feedback="trap C")
    add_element(unit, q)
    return unit


def test_lesson_inline_feedback_under_wrong_option(page, live_server):
    _make_pa_user("cif_owner1")
    unit = _seed_inline_feedback_question("cif_owner1", slug="cif-wrong")

    _login(page, live_server, "cif_owner1")
    lesson_url = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)
    page.wait_for_selector("[data-question]")

    question_el = page.locator("[data-question]").first
    # Tick only the distractor "C" (misses the correct "A").
    c_li = _choice_li(question_el, "C")
    c_li.locator("input[type='checkbox']").check()
    question_el.locator("button[type='submit']").click()

    # Corrective feedback lands INLINE, inside the same .question__choice <li>.
    a_li = _choice_li(question_el, "A")
    expect(a_li.locator(".question__choice-feedback")).to_have_text("need A")
    expect(c_li.locator(".question__choice-feedback")).to_have_text("trap C")

    # No duplicate bottom reveal list.
    expect(question_el.locator(".question__reveal")).to_have_count(0)


def test_lesson_correct_answer_hides_check_no_feedback(page, live_server):
    _make_pa_user("cif_owner2")
    unit = _seed_inline_feedback_question("cif_owner2", slug="cif-correct")

    _login(page, live_server, "cif_owner2")
    lesson_url = f"{live_server.url}/courses/{unit.course.slug}/u/{unit.pk}/"
    page.goto(lesson_url)
    page.wait_for_selector("[data-question]")

    question_el = page.locator("[data-question]").first
    # Tick ONLY the sole correct option "A" (no "B" in this seed).
    a_li = _choice_li(question_el, "A")
    a_li.locator("input[type='checkbox']").check()
    question_el.locator("button[type='submit']").click()

    expect(question_el.locator(".question__verdict.is-correct")).to_be_visible()
    expect(question_el.locator(".question__choice-feedback")).to_have_count(0)
    expect(question_el.locator("button[type='submit']")).to_be_hidden()
