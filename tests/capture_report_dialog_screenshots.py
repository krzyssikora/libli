"""Light + dark capture of the report dialog (spec 2026-08-22-issue-reporting-design).

Regeneration/verification tool, not CI. Run explicitly:

    uv run pytest tests/capture_report_dialog_screenshots.py -m e2e

Not `test_`-prefixed as a FILENAME, so `python_files=["test_*.py"]` never
auto-collects it; the `test_`-named function inside is collected only when this
path is passed explicitly. Mirrors tests/capture_nested_question_screenshots.py.

Why it exists: the dialog's visual design pass (spec, "Visual design pass") is
judged by looking at a real render in both themes, not by a geometry assertion.
Was previously a parametrized test inside test_e2e_support_report.py; moved here
because it writes to a git-tracked path and every `-m e2e` run would otherwise
leave two modified binary files in `git status`.

The theme is set on the USER, not via the libli_theme cookie: a <dialog> renders
in the top layer and does not pick up the cookie-driven theme in this codebase,
so a cookie-set dark run would silently photograph a light dialog.

Output goes to SHOT_DIR (env) or docs/superpowers/screenshots/ — the two PNGs
committed there are the ones the design pass judges.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import Group

from institution.roles import STUDENT
from institution.roles import seed_roles
from support.models import SupportSettings
from tests.factories import TEST_PASSWORD
from tests.factories import make_verified_user

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Every e2e module in this repo declares this, and it lives in NO shared
    conftest — not the root one, not tests/conftest.py, not pyproject.toml. The
    sync Playwright API trips Django's async_unsafe guard, so ORM calls in the
    test body raise SynchronousOnlyOperation without it. Running this file alone
    (as intended — see the module docstring) means no sibling module's fixture
    can cover for a missing one here.
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


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_capture_report_dialog_screenshot(page, live_server, theme):
    """Not an assertion test — it produces the two images the design pass judges."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    row = SupportSettings.load()
    row.audience = SupportSettings.Audience.ALL
    row.save()
    user = _student()
    user.theme = theme
    user.save()
    _login(page, live_server, "reporter")
    page.goto(f"{live_server.url}/home/")
    page.click("[data-account-menu] [data-menu-trigger]")
    page.click("[data-report-trigger]")
    page.wait_for_selector("#report-dialog[open]")
    page.fill("[data-report-description]", "The submit button does nothing.")
    page.screenshot(path=str(OUT_DIR / f"report-dialog-{theme}.png"))
