"""Deterministic help-screenshot capture (regeneration tool, not a CI test).

Run explicitly to (re)generate committed help screenshots:

    uv run playwright install chromium   # first time only
    uv run python -m pytest tests/capture_help_screenshots.py

This file is deliberately NOT prefixed `test_`, so pytest does not auto-collect it
in the unit CI job (bare `pytest -n auto`) or the e2e job (`pytest -m e2e`). Passing
its path explicitly bypasses the `python_files` filter, so the `test_`-named function
below still runs. It is NOT marked `@pytest.mark.e2e` (that would make the explicit
run deselect it under the default `-m 'not e2e'`).
"""

import os

import pytest
from django.conf import settings
from django.core.management import call_command

pytestmark = pytest.mark.django_db(transaction=True)  # committed rows visible to server


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


DEMO_PASSWORD = "demo-pass-123"  # mirrors the seed's DEMO_PASSWORD


def _login(page, live_server, username, password=DEMO_PASSWORD):
    page.goto(f"{live_server.url}/accounts/login/")
    form = page.locator("form[action*='login']")
    form.locator("input[name='login']").fill(username)
    form.locator("input[name='password']").fill(password)
    form.locator("button[type='submit']").click()


def test_capture_help_screenshots(live_server, page):
    call_command("seed_demo_course")

    page.set_viewport_size({"width": 1280, "height": 800})
    page.emulate_media(color_scheme="light", reduced_motion="reduce")

    # Tripwire: fail if any image request on the captured page returns >= 400. The
    # builder tree renders no MEDIA image (the demo image is exercised only in lesson
    # views — slice 3), so today this guards static assets and future MEDIA-rendering
    # captures; the Task 5 image fix is validated by the seed test, not here.
    bad_images = []

    def _on_response(resp):
        if resp.request.resource_type == "image" and resp.status >= 400:
            bad_images.append((resp.url, resp.status))

    page.on("response", _on_response)

    _login(page, live_server, "demo_teacher")
    page.goto(f"{live_server.url}/manage/courses/demo-course/build/")
    page.locator(".builder__tree").wait_for(state="visible")
    page.wait_for_load_state("networkidle")

    assert not bad_images, f"broken image request(s) on builder page: {bad_images}"

    out_dir = settings.BASE_DIR / "core" / "static" / "core" / "img" / "help"
    out_dir.mkdir(parents=True, exist_ok=True)
    page.locator("section.builder").screenshot(path=str(out_dir / "builder-tree.png"))
