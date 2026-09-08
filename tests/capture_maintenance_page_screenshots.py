"""Produce the images the design pass judges for the deploy maintenance page.

Not an assertion test -- run it on its own; the assertions live in
tests/test_maintenance_page_wiring.py.

    uv run pytest tests/capture_maintenance_page_screenshots.py -m e2e

Loaded over file:// ON PURPOSE. The page is static and self-contained by
requirement -- it renders while the app container is down -- so there is no
server to point at, and file:// is the honest reproduction of what Caddy hands
the browser. It is also the sharper check: anything the page reaches for over
the network is simply missing here, the same way it is missing in production.

Dark is judged on its own, not as "light but inverted". The card is a
--surface-raised panel cut by a --border-default hairline, and a hairline is
exactly where a token that reads fine on white disappears on near-black.

Phone as well as desktop: the reader who meets this page is mid-lesson, and on
mat-pp that is more often a phone than a laptop.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

pytestmark = pytest.mark.e2e

PAGE = Path(settings.BASE_DIR) / "maintenance.html"

OUT_DIR = Path(
    os.environ.get(
        "SHOT_DIR", Path(settings.BASE_DIR) / "docs" / "superpowers" / "screenshots"
    )
)


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    """Same shim the other capture scripts carry: conftest reaches the ORM from
    Playwright's event loop during setup, and Django refuses that by default.
    """
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800},
    "phone": {"width": 390, "height": 780},
}


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("shape", sorted(VIEWPORTS))
def test_capture(browser, shape, scheme):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(
        viewport=VIEWPORTS[shape],
        color_scheme=scheme,
        device_scale_factor=2,
    )
    page = context.new_page()
    page.goto(PAGE.as_uri())
    # The dots pulse on a 1.4 s loop; without settling the capture the two
    # schemes disagree on opacity and the pair cannot be compared.
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT_DIR / f"maintenance-{shape}-{scheme}.png"))
    context.close()
