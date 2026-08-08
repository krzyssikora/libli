"""Playwright e2e: a correct fill-blank answer locks its blanks in the LIVE JS path.

The server side (restore + no-JS POST) is covered by
courses/tests/test_fillblank_lock_on_correct.py. This file drives the real UI, which
is the only place the question.js fetch path exists: before the fix, question.js hid
the Check button on a correct verdict but left every <input name="blank"> writable,
so the student could retype a correct answer and — via implicit Enter submission —
overwrite the stored practice state with a wrong one.

Also measures the locked box: the editable blank is pinned to 8ch, so the lock has
to release that width (via `size` + the :read-only rule) or a long correct answer
sits clipped in a box the student can no longer scroll by typing.

Marked e2e (excluded from the default run; run with -m e2e).
Harness mirrors test_e2e_questions_2b.py.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

LONG_ANSWER = "Constantinople"  # 14 chars — well past the editable box's 8ch


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


def _seed(username, slug):
    """Course + lesson with ONE two-blank fill-blank question.

    A plain .objects.create runs no tokenizer, so the stem carries the U+FFFF tokens
    literally (same shortcut as test_e2e_questions_2b.py).
    """
    from django.contrib.auth import get_user_model

    from courses.models import Blank
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import FillBlankQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    User = get_user_model()
    owner = User.objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    Enrollment.objects.get_or_create(student=owner, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="L"
    )
    fb = FillBlankQuestionElement.objects.create(stem="￿0￿ on the ￿1￿.")
    Blank.objects.create(question=fb, order=0, accepted=LONG_ANSWER)
    Blank.objects.create(question=fb, order=1, accepted="Bosphorus")
    Element.objects.create(unit=unit, content_object=fb)
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_correct_answer_locks_the_blanks(browser, live_server):
    _make_pa_user("fblock_js")
    course, unit = _seed("fblock_js", "e2e-fb-lock")

    ctx = browser.new_context()
    page = ctx.new_page()
    _login(page, live_server, "fblock_js")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    page.wait_for_selector("[data-question]")

    q = page.locator("[data-question]").first
    blanks = q.locator("input[name='blank']")

    # A wrong answer must leave the blanks editable — the lock is verdict-keyed, and
    # a student has to be able to retry.
    blanks.nth(0).fill("Rome")
    blanks.nth(1).fill("Tiber")
    q.locator("button[type='submit']").click()
    q.locator("[data-question-feedback] .is-incorrect").wait_for(timeout=6000)
    assert blanks.nth(0).is_editable(), "a wrong answer must stay retryable"

    # Correct answer -> verdict, then every blank is locked.
    blanks.nth(0).fill(LONG_ANSWER)
    blanks.nth(1).fill("Bosphorus")
    q.locator("button[type='submit']").click()
    q.locator("[data-question-feedback] .is-correct").wait_for(timeout=6000)

    for i in range(2):
        assert blanks.nth(i).evaluate("el => el.readOnly"), (
            f"blank {i} is still writable after a correct answer"
        )
        assert not blanks.nth(i).is_editable(), f"blank {i} still accepts typing"

    # The answered text must still be readable: a locked box cannot be scrolled by
    # typing, so it has to have grown to fit its value.
    metrics = blanks.nth(0).evaluate(
        "el => ({ scroll: el.scrollWidth, client: el.clientWidth })"
    )
    assert metrics["scroll"] <= metrics["client"] + 1, (
        f"locked blank clips its answer: {metrics}"
    )

    # And the answer survives a reload (the server renders the locked state too).
    page.reload()
    page.wait_for_selector("[data-question]")
    reloaded = page.locator("[data-question]").first.locator("input[name='blank']")
    assert reloaded.nth(0).input_value() == LONG_ANSWER
    assert reloaded.nth(0).evaluate("el => el.readOnly"), (
        "the restored correct answer came back editable"
    )

    ctx.close()
