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


def _seed_stepper_n(username, slug, n):
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
    el = StepperElement.objects.create(prompt="")
    for i in range(n):
        StepperStep.objects.create(stepper=el, content=f"s{i}")
    Element.objects.create(unit=unit, content_object=el)
    return course, unit


@pytest.mark.django_db(transaction=True)
def test_stepper_state_survives_reload(live_server, page):
    """Walk two steps -> state POST -> reload -> first 3 steps restored, 4th still
    hidden, button still visible (the mid-walk restore branch)."""

    def _is_state_post(r):
        return "/state/" in r.url and r.request.method == "POST"

    course, unit = _seed_stepper_n("stpreload", "stepper-reload", 5)
    _login(page, live_server, "stpreload")
    url = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    page.goto(f"{live_server.url}{url}")
    steps = page.locator(".stepper__step")
    btn = page.locator(".stepper__next")
    # Await EACH click's fire-and-forget /state/ POST before the next action.
    # Awaiting only the second click races the first ({shown:2}) write, which under
    # threaded LiveServerThread can commit last and leave stored=2 -> flaky RED.
    with page.expect_response(_is_state_post):
        btn.click()  # reveal step 1 (shown=2); await its POST
    with page.expect_response(_is_state_post):
        btn.click()  # reveal step 2 (shown=3); await its POST before reloading
    page.reload()
    # After reload: first three steps visible, 4th hidden, button still visible.
    assert steps.nth(0).is_visible()
    assert steps.nth(1).is_visible()
    assert steps.nth(2).is_visible()
    assert not steps.nth(3).is_visible()
    assert btn.is_visible()


def _make_pa_user(username):
    from django.contrib.auth.models import Group

    from institution.roles import PLATFORM_ADMIN
    from institution.roles import seed_roles

    seed_roles()
    from tests.factories import make_verified_user

    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    user.groups.add(Group.objects.get(name=PLATFORM_ADMIN))
    return user


@pytest.mark.django_db(transaction=True)
def test_editor_preview_stepper_click_sends_no_post(live_server, page):
    """In the editor preview save_url is "" -> a Show-next click POSTs nothing and
    raises no pageerror (saveFlag no-ops on empty stateUrl)."""
    from courses.models import Element
    from courses.models import StepperElement
    from courses.models import StepperStep
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    pa = _make_pa_user("stp_ed")
    course = CourseFactory(slug="stepper-ed", owner=pa)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="lesson", parent=None, title="U"
    )
    el = StepperElement.objects.create(prompt="")
    for c in ("a", "b", "c"):
        StepperStep.objects.create(stepper=el, content=c)
    Element.objects.create(unit=unit, content_object=el)

    posts = []
    errors = []
    page.on(
        "request",
        lambda r: (
            posts.append(r.url) if "/state/" in r.url and r.method == "POST" else None
        ),
    )
    page.on("pageerror", lambda e: errors.append(str(e)))

    _login(page, live_server, "stp_ed")
    page.goto(
        f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"
    )
    preview_btn = page.locator('[data-scope="preview"] .stepper__next')
    preview_btn.wait_for(state="visible")
    preview_btn.click()

    assert errors == [], f"unexpected pageerror(s): {errors}"
    assert posts == [], f"editor preview must not POST state: {posts}"
