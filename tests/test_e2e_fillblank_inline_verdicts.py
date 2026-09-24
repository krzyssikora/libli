"""Playwright e2e: a lesson fill-blank check marks each blank in place.

The server side is covered by courses/tests/test_fillblank_inline_verdicts.py. This
drives the live question.js path, where the check answers with the whole element and
the form body is swapped (data-question-inline) — the only way the per-blank classes
reach the inputs the student is looking at. It also measures the COMPUTED colours: a
class the cascade overrides (app.css's `input[type=text]` rule) would pass every
server test and still paint nothing.

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


def _seed(username, slug):
    """Course + lesson with ONE four-blank fill-blank (the log example)."""
    from django.contrib.auth import get_user_model

    from courses.models import Blank
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import FillBlankQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    owner = get_user_model().objects.get(username=username)
    course = CourseFactory(slug=slug, owner=owner)
    Enrollment.objects.get_or_create(student=owner, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="L"
    )
    fb = FillBlankQuestionElement.objects.create(
        stem="log 9^11 = ￿0￿ · log ￿1￿ = 11 · ￿2￿ = ￿3￿",
        explanation="<p>Power rule.</p>",
    )
    for i, acc in enumerate(["11", "9", "2", "22"]):
        Blank.objects.create(question=fb, order=i, accepted=acc)
    Element.objects.create(unit=unit, content_object=fb)
    return course, unit


_PAINT = (
    "el => { const s = getComputedStyle(el);"
    " return [s.backgroundColor, s.borderTopColor]; }"
)


@pytest.mark.django_db(transaction=True)
def test_check_marks_each_blank_in_place(browser, live_server):
    _make_pa_user("fbverd_js")
    course, unit = _seed("fbverd_js", "e2e-fb-verdicts")

    page = browser.new_context().new_page()
    _login(page, live_server, "fbverd_js")
    page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/")
    q = page.locator("[data-question]").first
    blanks = q.locator("input[name='blank']")
    plain = blanks.nth(1).evaluate(_PAINT)

    blanks.nth(0).fill("11")
    blanks.nth(2).fill("5")
    q.locator("button[type='submit']").click()
    q.locator("[data-question-feedback] .question__verdict.is-incorrect").wait_for(
        timeout=6000
    )

    # Each blank carries its own verdict — right, empty, wrong, empty.
    classes = [blanks.nth(i).get_attribute("class") for i in range(4)]
    assert "is-correct" in classes[0], classes
    for i in (1, 2, 3):
        assert "is-incorrect" in classes[i], classes
        assert blanks.nth(i).get_attribute("aria-invalid") == "true"

    # The classes must actually PAINT, and paint differently.
    right, wrong = blanks.nth(0).evaluate(_PAINT), blanks.nth(1).evaluate(_PAINT)
    assert right != plain and wrong != plain and right != wrong, (plain, right, wrong)

    # What the student typed survives the swap, and the blanks stay retryable.
    assert blanks.nth(0).input_value() == "11"
    assert blanks.nth(2).input_value() == "5"
    assert blanks.nth(2).is_editable()

    # No answer list; the verdict line and the explanation stay.
    feedback = q.locator("[data-question-feedback]")
    assert "Correct answer" not in feedback.inner_text()
    assert "Power rule." in feedback.inner_text()

    # A retry still works through the swapped form (its submit listener survived).
    for i, v in enumerate(["11", "9", "2", "22"]):
        blanks.nth(i).fill(v)
    q.locator("button[type='submit']").click()
    q.locator("[data-question-feedback] .question__verdict.is-correct").wait_for(
        timeout=6000
    )
    assert blanks.nth(3).evaluate("el => el.readOnly"), "a solved question locks"
