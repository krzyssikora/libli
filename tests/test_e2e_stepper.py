"""Playwright e2e for the Step-by-step stepper. Marked e2e (run with -m e2e).
Harness mirrors tests/test_e2e_choicegrid.py (fixtures, HTML-form login)."""

import os

import pytest
from django.urls import reverse

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


def _seed_stepper(username, slug):
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import StepperElement
    from courses.models import StepperStep
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory(slug=slug, owner=student)
    Enrollment.objects.get_or_create(student=student, course=course)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = StepperElement.objects.create(prompt=r"Compute \(2^4\cdot 2^6\)")
    for c in ("first", "second", "third"):
        StepperStep.objects.create(stepper=el, content=c)
    Element.objects.create(unit=unit, content_object=el)
    return course, unit


def test_stepper_reveals_one_at_a_time(live_server, page):
    course, unit = _seed_stepper("stepstu", "stepper-e2e")
    _login(page, live_server, "stepstu")
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{url}")
    # Inline \(...\) math is typeset by KaTeX (proves the math.js .stepper selector).
    assert page.locator(".stepper .katex").count() > 0
    steps = page.locator(".stepper__step")
    btn = page.locator(".stepper__next")
    # After boot: only step 0 visible; button visible.
    assert steps.nth(0).is_visible()
    assert not steps.nth(1).is_visible()
    assert not steps.nth(2).is_visible()
    assert btn.is_visible()
    btn.click()
    assert steps.nth(1).is_visible()
    assert not steps.nth(2).is_visible()
    btn.click()
    assert steps.nth(2).is_visible()
    assert not btn.is_visible()  # button gone after the last step
