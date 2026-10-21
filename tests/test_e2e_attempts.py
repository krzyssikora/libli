"""Playwright e2e for the attempts defaults (course -> quiz -> question).

Drives the real UI: the course form's reset choice, the editor's quiz Settings
panel, the question form's Attempts select and its CSS-only limit reveal.
Marked e2e (excluded from the default run; run with -m e2e).
"""

import os
import pathlib

import pytest
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import attempts
from tests.factories import make_verified_user
from tests.helpers_editor_rows import reopen

pytestmark = pytest.mark.e2e

ZERO_MSG = "0 isn't a limit. To use the course's setting, choose 'Same as course'."
READY = "[data-edit-slot] select[name='attempts_mode']"


@pytest.fixture(scope="session", autouse=True)
def _allow_async_unsafe():
    # Sync Playwright + Django ORM in the same thread.
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


def _make_student(username):
    return make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()
    page.wait_for_url(lambda url: "/accounts/login/" not in url)


def _seed_quiz(owner, slug, own_attempts):
    """Course + quiz unit with one short-text question; returns (course, unit, el)."""
    from courses.models import Element
    from courses.models import ShortTextQuestionElement
    from tests.factories import ContentNodeFactory
    from tests.factories import CourseFactory

    course = CourseFactory(slug=slug, owner=owner)
    unit = ContentNodeFactory(
        course=course, kind="unit", unit_type="quiz", parent=None, title="Q"
    )
    st = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of France?</p>", accepted="Paris", **attempts(own_attempts)
    )
    return course, unit, Element.objects.create(unit=unit, content_object=st)


def _editor_url(live_server, course, unit):
    return f"{live_server.url}/manage/courses/{course.slug}/build/unit/{unit.pk}/edit/"


def _wrong_answers_then_locked(browser, live_server, course, unit, student, accepted):
    """The student answers wrong `accepted` times (each accepted by the server),
    and the question is then locked."""
    from courses.models import Enrollment

    Enrollment.objects.get_or_create(student=student, course=course)
    ctx = browser.new_context()
    try:
        page = ctx.new_page()
        _login(page, live_server, student.username)
        page.goto(f"{live_server.url}/courses/{course.slug}/u/{unit.pk}/quiz/")
        q = page.locator("[data-question]").first
        answer = q.locator("input[name='answer']")
        expect(answer).to_be_enabled()
        for _ in range(accepted):
            expect(answer).to_be_enabled()
            answer.fill("London")
            with page.expect_response(
                lambda r: "/answer/" in r.url and r.request.method == "POST"
            ) as resp:
                q.locator("button[type='submit']:not([name='reveal'])").click()
            assert resp.value.status == 200, "an attempt within the limit is accepted"
            expect(q.locator("[data-question-feedback] .is-incorrect")).to_be_visible()
        # The last accepted attempt used the limit up: the question is locked.
        expect(answer).to_be_disabled()
    finally:
        ctx.close()


@pytest.mark.django_db(transaction=True)
def test_course_reset_through_the_ui(page, browser, live_server):
    pa = _make_pa_user("att_pa1")
    course, unit, _el = _seed_quiz(pa, "att-reset", 2)
    _login(page, live_server, "att_pa1")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/edit/")
    page.select_option("select[name='attempts_mode']", "limited")
    page.locator("input[name='attempts_limit']").fill("3")
    page.get_by_label("Make every quiz and question use the course setting").check()
    page.locator("form:has(select[name='attempts_mode']) button[type='submit']").click()
    expect(page.get_by_text("now uses the course setting")).to_be_visible()

    student = _make_student("att_st1")
    # The question's own 2 is gone: three wrong answers are accepted, the third
    # one using the course's 3 up.
    _wrong_answers_then_locked(browser, live_server, course, unit, student, 3)


@pytest.mark.django_db(transaction=True)
def test_question_override_beats_unlimited_quiz(page, browser, live_server):
    pa = _make_pa_user("att_pa2")
    course, unit, _el = _seed_quiz(pa, "att-override", 2)
    _login(page, live_server, "att_pa2")
    page.goto(_editor_url(live_server, course, unit))
    page.locator("details.unit-settings summary").click()
    page.select_option("#unit-attempts-mode", "unlimited")
    with page.expect_navigation():
        page.locator("details.unit-settings button[type='submit']").click()
    # A fresh render of the editor: the saved setting is Unlimited.
    expect(page.locator("#unit-attempts-mode")).to_have_value("unlimited")

    student = _make_student("att_st2")
    _wrong_answers_then_locked(browser, live_server, course, unit, student, 2)


@pytest.mark.django_db(transaction=True)
def test_zero_shows_the_d9_message(page, live_server):
    pa = _make_pa_user("att_pa3")
    course, unit, el = _seed_quiz(pa, "att-zero", 0)
    _login(page, live_server, "att_pa3")
    page.goto(_editor_url(live_server, course, unit))
    reopen(page, el.pk, ready=READY)
    slot = page.locator("[data-edit-slot]")
    slot.locator("select[name='attempts_mode']").select_option("limited")
    slot.locator("input[name='attempts_limit']").fill("0")
    slot.locator("form[data-op='element-save'] button[type=submit]").click()
    expect(slot.get_by_text(ZERO_MSG)).to_be_visible()


@pytest.mark.django_db(transaction=True)
def test_limit_input_reveals_after_a_fragment_swap(page, live_server):
    pa = _make_pa_user("att_pa4")
    course, unit, el = _seed_quiz(pa, "att-reveal", 0)
    _login(page, live_server, "att_pa4")
    page.goto(_editor_url(live_server, course, unit))
    reopen(page, el.pk, ready=READY)
    # Save as-is: the editor swaps the fragment; then open the form again.
    save = "[data-edit-slot] form[data-op='element-save'] button[type=submit]"
    page.locator(save).click()
    expect(page.locator("[data-edit-slot] form")).to_have_count(0)
    reopen(page, el.pk, ready=READY)

    mode = page.locator("[data-edit-slot] select[name='attempts_mode']")
    limit = page.locator("[data-edit-slot] input[name='attempts_limit']")
    expect(mode).to_have_value("inherit")
    expect(limit).to_be_hidden()
    mode.select_option("limited")
    expect(limit).to_be_visible()
    mode.select_option("unlimited")
    expect(limit).to_be_hidden()


@pytest.mark.django_db(transaction=True)
def test_capture_attempts_screens(page, live_server):
    """Screenshots for the owner (light + dark). Skipped unless ATTEMPTS_SHOTS_DIR
    is set; writes only into that directory."""
    shots = os.environ.get("ATTEMPTS_SHOTS_DIR")
    if not shots:
        pytest.skip("ATTEMPTS_SHOTS_DIR not set")
    out = pathlib.Path(shots)
    out.mkdir(parents=True, exist_ok=True)

    pa = _make_pa_user("att_pa5")
    course, unit, el = _seed_quiz(pa, "att-shots", 0)
    # A second question with its own limit, so the quiz panel and the course form
    # both offer the reset radios.
    from courses.models import Element
    from courses.models import ShortTextQuestionElement

    other = ShortTextQuestionElement.objects.create(
        stem="<p>Capital of Spain?</p>", accepted="Madrid", **attempts(2)
    )
    Element.objects.create(unit=unit, content_object=other)
    page.set_viewport_size({"width": 1280, "height": 1000})
    _login(page, live_server, "att_pa5")

    def both(name, element):
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.reload()
            if name == "quiz-settings":
                page.locator("details.unit-settings summary").click()
            element.screenshot(path=str(out / f"{name}-{scheme}.png"))

    for scheme in ("light", "dark"):
        # The theme is read at page load, so reload under each scheme.
        page.emulate_media(color_scheme=scheme)
        page.goto(_editor_url(live_server, course, unit))
        reopen(page, el.pk, ready=READY)
        row = page.locator(f'[data-element="{el.pk}"] .el-editor__marking-fields')
        row.scroll_into_view_if_needed()
        row.screenshot(path=str(out / f"question-inherit-{scheme}.png"))
        row.locator("select[name='attempts_mode']").select_option("limited")
        expect(row.locator("input[name='attempts_limit']")).to_be_visible()
        row.screenshot(path=str(out / f"question-limited-{scheme}.png"))

    page.goto(_editor_url(live_server, course, unit))
    page.locator("details.unit-settings summary").click()
    panel = page.locator("details.unit-settings")
    expect(panel.locator("input[name='attempts_reset']").first).to_be_visible()
    both("quiz-settings", panel)

    page.goto(f"{live_server.url}/manage/courses/{course.slug}/edit/")
    form = page.locator("form:has(select[name='attempts_mode'])")
    expect(form.locator("input[name='attempts_reset']").first).to_be_visible()
    both("course-form", form)
