"""Playwright e2e: inline math in an image caption is typeset on the student
lesson page. Two independent gaps let it ship raw: the server never armed KaTeX
for a caption-only page (_element_has_math), and math.js's renderInlineText
selector list skipped .el--image even when KaTeX was loaded. Each test isolates
one of them. Marked e2e (excluded from the default run)."""

import os
import types

import pytest

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _lesson_with_captioned_image(page, live_server, username, *, extra_math):
    from django.urls import reverse

    from courses.models import ImageElement
    from courses.models import MathElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory
    from tests.factories import EnrollmentFactory
    from tests.factories import add_element
    from tests.factories import make_image_asset

    student = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = CourseFactory()
    unit = ContentNodeFactory(course=course, kind="unit", unit_type="lesson")
    add_element(
        unit,
        ImageElement.objects.create(
            media=make_image_asset(course),
            alt="diagram",
            figcaption=r"Wykres \(y=x^2\)",
        ),
    )
    if extra_math:
        add_element(unit, MathElement.objects.create(latex=r"a^2+b^2=c^2"))
    EnrollmentFactory(student=student, course=course)

    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login/" not in url)

    path = reverse(
        "courses:lesson_unit", kwargs={"slug": course.slug, "node_pk": unit.pk}
    )
    return types.SimpleNamespace(lesson_url=f"{live_server.url}{path}")


def _assert_caption_typeset(page):
    caption = page.locator(".el--image figcaption")
    caption.locator(".katex").first.wait_for(state="attached", timeout=5000)
    assert "\\(" not in caption.text_content()


@pytest.mark.django_db(transaction=True)
def test_caption_is_the_only_math_on_the_page(live_server, page):
    ctx = _lesson_with_captioned_image(
        page, live_server, "cap_math_only", extra_math=False
    )
    page.goto(ctx.lesson_url)
    _assert_caption_typeset(page)


@pytest.mark.django_db(transaction=True)
def test_caption_beside_other_math(live_server, page):
    # KaTeX is armed by the MathElement regardless of the caption, so this one
    # fails only if math.js skips .el--image.
    ctx = _lesson_with_captioned_image(
        page, live_server, "cap_math_extra", extra_math=True
    )
    page.goto(ctx.lesson_url)
    page.locator(".el--math .katex").first.wait_for(state="attached", timeout=5000)
    _assert_caption_typeset(page)
