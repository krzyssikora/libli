"""End-to-end: open the dialog, paste an image, submit, verify the stored row."""

import os

import pytest
from django.contrib.auth.models import Group

from institution.roles import STUDENT
from institution.roles import seed_roles
from support.models import IssueReport
from support.models import SupportSettings
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

# transaction=True is MANDATORY, not stylistic. live_server runs in a background
# thread on its own connection; under a plain django_db mark the test's rows (the
# SupportSettings row, the student) stay in an uncommitted transaction the server
# cannot see, so the login fails and IssueReport.objects.get() finds nothing.
# 109 e2e tests in this repo use transaction=True; effectively none use the plain
# marker.
pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Every e2e module in this repo declares this, and it lives in NO shared
    conftest — not the root one, not tests/conftest.py, not pyproject.toml. The
    sync Playwright API trips Django's async_unsafe guard, so ORM calls in the
    test body raise SynchronousOnlyOperation without it. Task 10 Step 3 runs this
    file alone, so no sibling module's fixture can cover for a missing one here.
    """
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _student(username="reporter"):
    """A verified Student created directly, so the test can log in through the
    real allauth form rather than force_login."""
    seed_roles()
    user = make_verified_user(
        username=username,
        email=f"{username}@t.example.com",
        password=TEST_PASSWORD,
    )
    user.groups.add(Group.objects.get(name=STUDENT))
    return user


def _login(page, live_server, username):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(TEST_PASSWORD)
    form.locator("button[type='submit']").click()


# A 1x1 PNG as a data: URL, fetched inside the page so the paste carries real
# image bytes. Playwright cannot portably put an image on the OS clipboard, so
# Ctrl+V would paste NOTHING — and because the screenshot is optional the submit
# would still succeed, giving a test that cannot fail. A synthetic ClipboardEvent
# carrying a DataTransfer is the only mechanism that exercises the paste handler.
PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)

PASTE_SCRIPT = """
async (dataUrl) => {
  const blob = await (await fetch(dataUrl)).blob();
  const file = new File([blob], "clip", { type: "image/png" });
  const dt = new DataTransfer();
  dt.items.add(file);
  const event = new ClipboardEvent("paste", {
    clipboardData: dt, bubbles: true, cancelable: true
  });
  document.getElementById("report-dialog").dispatchEvent(event);
}
"""


def test_a_student_reports_an_issue_with_a_pasted_screenshot(page, live_server):
    row = SupportSettings.load()
    row.audience = SupportSettings.Audience.ALL
    row.save()

    _student()
    _login(page, live_server, "reporter")
    page.goto(f"{live_server.url}/home/")

    page.click("[data-account-menu] [data-menu-trigger]")
    page.click("[data-report-trigger]")
    page.wait_for_selector("#report-dialog[open]")

    page.evaluate(PASTE_SCRIPT, PNG_DATA_URL)
    # Synchronise on the condition, never a sleep.
    page.wait_for_function(
        "document.querySelector('[data-report-file]').files.length === 1"
    )

    page.fill("[data-report-description]", "The submit button does nothing.")
    page.click("#report-dialog button[type=submit]")
    page.wait_for_selector("[data-report-banner]:not([hidden])")

    report = IssueReport.objects.get()
    assert report.description == "The submit button does nothing."
    assert report.screenshot.name.endswith(".png")
    assert report.telemetry["viewport_w"] > 0


@pytest.mark.parametrize("status", [500, 403])
def test_a_non_json_response_keeps_the_dialog_open_with_the_text(
    page, live_server, status
):
    """Mutant: assume JSON on every response (drop the Content-Type check)."""
    row = SupportSettings.load()
    row.audience = SupportSettings.Audience.ALL
    row.save()
    _student()
    _login(page, live_server, "reporter")
    page.goto(f"{live_server.url}/home/")

    # Django's CSRF failure view really does return a 403 with an HTML body, so
    # this is the shape the client must survive, not a contrived one.
    page.route(
        "**/report/",
        lambda route: route.fulfill(
            status=status, content_type="text/html", body="<html>boom</html>"
        ),
    )
    page.click("[data-account-menu] [data-menu-trigger]")
    page.click("[data-report-trigger]")
    page.fill("[data-report-description]", "typed text must survive")
    page.click("#report-dialog button[type=submit]")

    page.wait_for_selector("[data-report-banner]:not([hidden])")
    assert page.is_visible("#report-dialog[open]")
    assert page.input_value("[data-report-description]") == "typed text must survive"


def test_an_empty_description_renders_under_its_field(page, live_server):
    """The per-field branch of the error contract, driven through the real UI."""
    row = SupportSettings.load()
    row.audience = SupportSettings.Audience.ALL
    row.save()
    _student()
    _login(page, live_server, "reporter")
    page.goto(f"{live_server.url}/home/")
    page.click("[data-account-menu] [data-menu-trigger]")
    page.click("[data-report-trigger]")
    # The textarea is `required`, so clear the browser guard to reach the server.
    page.eval_on_selector(
        "[data-report-description]", "el => el.removeAttribute('required')"
    )
    page.click("#report-dialog button[type=submit]")
    page.wait_for_selector('[data-error-for="description"]:not([hidden])')


def test_a_non_field_error_lands_in_the_banner(page, live_server):
    """Mutant: render only per-field keys — an __all__ error is then returned by
    the server and silently dropped, leaving a form that refuses to submit and
    says nothing."""
    row = SupportSettings.load()
    row.audience = SupportSettings.Audience.ALL
    row.save()
    _student()
    _login(page, live_server, "reporter")
    page.goto(f"{live_server.url}/home/")
    page.route(
        "**/report/",
        lambda route: route.fulfill(
            status=400,
            content_type="application/json",
            body='{"ok": false, "message": null, "errors": {"__all__": ["nope"]}}',
        ),
    )
    page.click("[data-account-menu] [data-menu-trigger]")
    page.click("[data-report-trigger]")
    page.fill("[data-report-description]", "anything")
    page.click("#report-dialog button[type=submit]")
    banner = page.wait_for_selector("[data-report-banner]:not([hidden])")
    assert "nope" in banner.inner_text()
