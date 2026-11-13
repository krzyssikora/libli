"""e2e: slow form POSTs (course import upload + confirm, course deletion) show a
busy cue -- a disabled, spinning submit button and a status line -- instead of
looking idle. core/js/busy_submit.js.

Each test holds the SUBMIT, not the request: a listener registered after
busy_submit.js's own cancels the first submit, so the busy state is asserted
without racing the request (holding the navigation POST with page.route hangs
sync Playwright). Releasing drops the listener and calls requestSubmit(), a
genuine submit, so the page's handler runs again and navigation proceeds."""

import io
import os

import pytest
from django.contrib.auth.models import Permission
from playwright.sync_api import expect

from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.fixture(autouse=True)
def _staging_tmp(settings, tmp_path):
    settings.TRANSFER_STAGING_DIR = tmp_path / "staging"


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


def _owner(username, *codenames):
    user = make_verified_user(
        username=username, email=f"{username}@t.example.com", password=TEST_PASSWORD
    )
    for codename in codenames:
        user.user_permissions.add(
            Permission.objects.get(codename=codename, content_type__app_label="courses")
        )
    return user


def _hold_submit(page, form_selector):
    page.evaluate(
        "(sel) => { window.__hold = (e) => e.preventDefault();"
        " document.querySelector(sel).addEventListener('submit', window.__hold); }",
        form_selector,
    )


def _release_submit(page, form_selector):
    page.evaluate(
        "(sel) => { const f = document.querySelector(sel);"
        " f.removeEventListener('submit', window.__hold); f.requestSubmit(); }",
        form_selector,
    )


def _assert_busy(page, form_selector, note_text):
    submit = page.locator(f"{form_selector} button[type='submit']")
    expect(submit).to_be_disabled()
    assert submit.get_attribute("aria-busy") == "true"
    animation = submit.evaluate("b => getComputedStyle(b, '::before').animationName")
    assert animation == "btn-busy-spin"
    note = page.locator(f"{form_selector} [data-busy-note]")
    expect(note).to_be_visible()
    expect(note).to_contain_text(note_text)


@pytest.mark.django_db(transaction=True)
def test_course_delete_shows_busy_cue(page, live_server):
    from courses.models import Course

    owner = _owner("deleter", "delete_course", "change_course")
    course = Course.objects.create(title="Doomed", slug="doomed", owner=owner)
    _login(page, live_server, "deleter")
    page.goto(f"{live_server.url}/manage/courses/{course.slug}/delete/")

    form = "form[data-busy-submit]"
    expect(page.locator(f"{form} [data-busy-note]")).to_be_hidden()  # idle: no note
    _hold_submit(page, form)
    page.locator(f"{form} button[type='submit']").click()
    _assert_busy(page, form, "Deleting the course")

    _release_submit(page, form)
    page.wait_for_url(f"{live_server.url}/manage/courses/")
    assert not Course.objects.filter(pk=course.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_course_import_upload_and_confirm_show_busy_cue(page, live_server, tmp_path):
    from courses.models import ContentNode
    from courses.models import Course
    from courses.transfer.export import write_archive

    owner = _owner("importer", "add_course")
    src = Course.objects.create(title="Algebra I", slug="algebra-i", owner=owner)
    ContentNode.objects.create(course=src, kind="unit", title="U", unit_type="lesson")
    buf = io.BytesIO()
    write_archive(src, None, buf)
    archive = tmp_path / "a.zip"
    archive.write_bytes(buf.getvalue())

    _login(page, live_server, "importer")
    page.goto(f"{live_server.url}/manage/courses/import/")
    page.locator("input#id_archive").set_input_files(str(archive))

    form = "form[data-busy-submit]"
    _hold_submit(page, form)
    page.locator(f"{form} button[type='submit']").click()
    _assert_busy(page, form, "Checking the archive")
    _release_submit(page, form)

    expect(page.locator("h1")).to_contain_text("Import summary")
    _hold_submit(page, form)
    page.locator(f"{form} button[type='submit']").click()
    _assert_busy(page, form, "Importing")
    _release_submit(page, form)

    page.wait_for_selector('[data-scope="top"]', state="attached")
    assert Course.objects.filter(slug="algebra-i-2").exists()
