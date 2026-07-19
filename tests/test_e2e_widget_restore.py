"""Playwright e2e: the deferred WIDGET question types re-arm their JS widget from a
server-side practice-state restore after reload.

The Django test client (courses/tests/test_question_restore.py) proves the server
renders the correct <select> values, but cannot observe whether dnd.js painted the
overlay / inline slots. These e2es drive the REAL gesture, reload, and assert the
VISIBLE widget shows the restored answer -- the actual falsification of "the JS widget
cannot be re-armed from server-rendered selects". Marked e2e (run with -m e2e).
"""

import os

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e

_PNG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg=="
)


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


def _size_stage(page, w=400, h=300):
    page.wait_for_selector("[data-dragimage-stage]")
    page.evaluate(
        """([w, h, src]) => {
            const stage = document.querySelector('[data-dragimage-stage]');
            stage.style.width = w + 'px';
            stage.style.height = h + 'px';
            stage.style.position = 'relative';
            stage.style.display = 'block';
            const img = stage.querySelector('img');
            if (img) {
                img.src = src;
                img.style.width = w + 'px';
                img.style.height = h + 'px';
            }
        }""",
        [w, h, _PNG_DATA_URI],
    )
    page.wait_for_function(
        """() => {
            const t = document.querySelector('.dragimage__target');
            if (!t) return false;
            const r = t.getBoundingClientRect();
            return r.width > 4 && r.height > 4;
        }"""
    )


def _seed_dragimage_lesson(username, slug):
    # One import per line (ruff force-single-line); keep sorted.
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import DragToImageQuestionElement
    from courses.models import DragZone
    from courses.models import Element
    from courses.models import Enrollment
    from courses.models import MediaAsset

    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    media = MediaAsset.objects.create(
        course=course,
        kind="image",
        file="courses/media/x.png",
        original_filename="x.png",
    )
    q = DragToImageQuestionElement.objects.create(
        media=media, alt="Diagram", distractors="Liver"
    )
    DragZone.objects.create(
        question=q, correct_label="Heart", x=0.1, y=0.1, w=0.3, h=0.3, order=0
    )
    DragZone.objects.create(
        question=q, correct_label="Lung", x=0.6, y=0.6, w=0.3, h=0.3, order=1
    )
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


def _lesson_url(live_server, course, unit):
    return f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/"


@pytest.mark.django_db(transaction=True)
def test_dragimage_overlay_restores_correct_after_reload(live_server, page):
    course, unit, el = _seed_dragimage_lesson("wr_di_ok", "wr-di-ok")
    _login(page, live_server, "wr_di_ok")
    page.goto(_lesson_url(live_server, course, unit))
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    page.locator('.dnd__chip[data-token="Heart"]').drag_to(targets.nth(0))
    page.locator('.dnd__chip[data-token="Lung"]').drag_to(targets.nth(1))
    with page.expect_response(lambda r: "/check/" in r.url):
        page.locator('.question__form button[type="submit"]').click()

    page.reload()
    _size_stage(page)
    # The overlay targets (VISIBLE widget) must show the restored answer on load.
    targets = page.locator(".dragimage__target")
    expect(targets.nth(0)).to_have_text("Heart")
    expect(targets.nth(1)).to_have_text("Lung")
    # And the native selects (source of truth the overlay paints from) are pre-selected.
    assert page.locator('select[name="slot"]').nth(0).input_value() == "Heart"
    assert page.locator('select[name="slot"]').nth(1).input_value() == "Lung"


@pytest.mark.django_db(transaction=True)
def test_dragimage_overlay_restores_incorrect_and_stays_editable(live_server, page):
    course, unit, el = _seed_dragimage_lesson("wr_di_bad", "wr-di-bad")
    _login(page, live_server, "wr_di_bad")
    page.goto(_lesson_url(live_server, course, unit))
    _size_stage(page)

    targets = page.locator(".dragimage__target")
    page.locator('.dnd__chip[data-token="Liver"]').drag_to(targets.nth(0))  # wrong
    page.locator('.dnd__chip[data-token="Lung"]').drag_to(targets.nth(1))
    with page.expect_response(lambda r: "/check/" in r.url):
        page.locator('.question__form button[type="submit"]').click()

    page.reload()
    _size_stage(page)
    targets = page.locator(".dragimage__target")
    expect(targets.nth(0)).to_have_text("Liver")  # the WRONG answer still painted
    # Editability BY GESTURE (not by attribute): re-drag a different chip onto slot 0.
    page.locator('.dnd__chip[data-token="Heart"]').drag_to(targets.nth(0))
    expect(page.locator(".dragimage__target").nth(0)).to_have_text("Heart")
    assert page.locator('select[name="slot"]').nth(0).input_value() == "Heart"


def _seed_dragfill_lesson(username, slug):
    # One import per line (ruff force-single-line); keep sorted.
    from courses.models import ContentNode
    from courses.models import Course
    from courses.models import DragBlank
    from courses.models import DragFillBlankQuestionElement
    from courses.models import Element
    from courses.models import Enrollment

    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    course = Course.objects.create(title="C", slug=slug, language="en")
    Enrollment.objects.create(student=user, course=course)
    unit = ContentNode.objects.create(
        course=course, kind="unit", unit_type="lesson", title="U"
    )
    q = DragFillBlankQuestionElement.objects.create(
        stem="Cap is ￿0￿", distractors="Rome"
    )
    DragBlank.objects.create(question=q, correct_token="Paris")
    el = Element.objects.create(unit=unit, content_object=q)
    return course, unit, el


@pytest.mark.django_db(transaction=True)
def test_dragfill_inline_slot_restores_after_reload(live_server, page):
    course, unit, el = _seed_dragfill_lesson("wr_df", "wr-df")
    _login(page, live_server, "wr_df")
    page.goto(_lesson_url(live_server, course, unit))

    # Real drag: chip 'Paris' onto the inline drop-slot.
    page.locator('.dnd__chip[data-token="Paris"]').drag_to(
        page.locator(".dnd__slot").first
    )
    assert page.locator('select[name="slot"]').input_value() == "Paris"
    with page.expect_response(lambda r: "/check/" in r.url):
        page.locator('.question__form button[type="submit"]').click()

    page.reload()
    page.wait_for_selector(".dnd__slot")
    # The VISIBLE inline slot (buildInlineSlots seeds it from sel.value on boot)
    # shows the restored token.
    expect(page.locator(".dnd__slot").first).to_have_text("Paris")
    assert page.locator('select[name="slot"]').input_value() == "Paris"
