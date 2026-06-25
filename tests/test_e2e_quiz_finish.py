"""e2e: 'Finish quiz' must record answers the student typed but never 'Checked'.

Guards the flush-on-finish path in quiz.js: a student types into questions,
clicks Finish (without per-question Check), and the answers are still saved and
scored on the results page.
"""

import os
from decimal import Decimal

import pytest

from tests.factories import TEST_PASSWORD
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


@pytest.mark.django_db(transaction=True)
def test_finish_records_typed_but_unchecked_answers(page, live_server):
    from django.urls import reverse

    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import QuestionResponse
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="finstu", email="finstu@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug="fc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title="Finish quiz"
    )
    q1 = ShortTextQuestionElement.objects.create(
        stem="<p>2+2?</p>", accepted="4", marking_mode="A", max_marks=Decimal("1")
    )
    q2 = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of France?</p>",
        accepted="Paris",
        marking_mode="A",
        max_marks=Decimal("1"),
    )
    e1 = Element.objects.create(unit=unit, content_object=q1)
    e2 = Element.objects.create(unit=unit, content_object=q2)

    _login(page, live_server, "finstu")
    path = reverse("courses:quiz_unit", kwargs={"slug": "fc", "node_pk": unit.pk})
    page.goto(f"{live_server.url}{path}")
    page.wait_for_selector("form.question__form")

    forms = page.locator("form.question__form")
    forms.nth(0).locator("input[name='answer']").fill("4")
    forms.nth(1).locator("input[name='answer']").fill("Paris")
    # NOTE: deliberately do NOT click any per-question "Check".

    page.on("dialog", lambda d: d.accept())  # the Finish confirm
    page.locator("[data-finish-btn]").click()
    page.wait_for_selector(".quiz-results", timeout=8000)

    # Both typed answers were flushed + recorded.
    assert QuestionResponse.objects.filter(submission__unit=unit, element=e1).exists()
    assert QuestionResponse.objects.filter(submission__unit=unit, element=e2).exists()
    # And scored: 2 correct answers of 1 mark each.
    body = page.content()
    assert "2.00 / 2.00" in body or "2 / 2" in body
