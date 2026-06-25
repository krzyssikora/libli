"""e2e: inline \\(...\\) math in a quiz question stem must render (KaTeX).

The quiz page loads quiz.js (not question.js), so the initial stem typeset pass
lives in quiz.js — this guards against it regressing.
"""

import os

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


@pytest.mark.django_db(transaction=True)
def test_quiz_stem_inline_math_renders(page, live_server):
    from django.urls import reverse

    from courses.models import Choice
    from courses.models import ChoiceQuestionElement
    from courses.models import Element
    from courses.models import Enrollment
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="mathstu", email="mathstu@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug="mc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="quiz", title="Math quiz"
    )
    q = ChoiceQuestionElement.objects.create(
        stem=r"<p>Is \(\frac{1}{2}\) less than one?</p>", multiple=False
    )
    Choice.objects.create(question=q, text="Yes", is_correct=True, order=0)
    Choice.objects.create(question=q, text="No", is_correct=False, order=1)
    Element.objects.create(unit=unit, content_object=q)

    _login(page, live_server, "mathstu")
    path = reverse("courses:quiz_unit", kwargs={"slug": "mc", "node_pk": unit.pk})
    page.goto(f"{live_server.url}{path}")
    # KaTeX wraps rendered math in a .katex element inside the stem.
    stem_math = page.locator(".question__stem .katex")
    stem_math.wait_for(state="attached", timeout=5000)
    assert stem_math.count() >= 1
    # The raw LaTeX source must no longer be visible as text.
    assert "\\frac" not in page.locator(".question__stem").inner_text()


@pytest.mark.django_db(transaction=True)
def test_text_element_inline_math_renders(page, live_server):
    from django.urls import reverse

    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import TextElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    user = make_verified_user(
        username="txtstu", email="txtstu@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug="tc")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNodeFactory(
        course=course, parent=None, kind="unit", unit_type="lesson", title="Prose math"
    )
    Element.objects.create(
        unit=unit,
        content_object=TextElement.objects.create(
            body=r"<p>The identity \(e^{i\pi} + 1 = 0\) is elegant.</p>"
        ),
    )

    _login(page, live_server, "txtstu")
    path = reverse("courses:lesson_unit", kwargs={"slug": "tc", "node_pk": unit.pk})
    page.goto(f"{live_server.url}{path}")
    prose_math = page.locator(".el--text .katex")
    prose_math.wait_for(state="attached", timeout=5000)
    assert prose_math.count() >= 1
    assert "e^{i" not in page.locator(".el--text").inner_text()
