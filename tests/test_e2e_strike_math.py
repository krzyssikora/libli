"""e2e: <s> strikes inline KaTeX too (courses.css `s .katex`).

Pixel-based on purpose: text-decoration never reaches KaTeX's inline-blocks, so the
rendered HTML is identical with and without the rule. The same formula is rendered
struck and unstruck on one page; only the struck copy may carry a dark row spanning
(nearly) its full width.
"""

import io
import os

import pytest
from PIL import Image

from tests.test_e2e_callout_container import _lesson_url
from tests.test_e2e_callout_container import _login
from tests.test_e2e_callout_container import _seed_unit

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _widest_dark_run(png):
    """Longest share of the image's width covered by dark pixels in a single row."""
    im = Image.open(io.BytesIO(png)).convert("L")
    w, h = im.size
    best = 0
    for y in range(h):
        best = max(best, sum(1 for x in range(w) if im.getpixel((x, y)) < 128))
    return best / w


def test_strike_crosses_inline_math(page, live_server):
    from courses.models import TextElement
    from tests.factories import add_element

    user, _course, unit = _seed_unit("pa_strike_math")
    add_element(
        unit,
        TextElement.objects.create(
            body=r"<p><s>Skreślone \(x^2+\frac{1}{2}\) tekst</s></p>"
            r"<p>Zwykłe \(x^2+\frac{1}{2}\) tekst</p>"
        ),
    )
    _login(page, live_server, user.username)
    page.goto(_lesson_url(live_server, unit))
    page.wait_for_selector("s .katex")
    struck = page.locator("s .katex").first.screenshot()
    plain = page.locator("p:not(:has(s)) .katex").first.screenshot()

    assert _widest_dark_run(struck) > 0.9, "struck formula has no full-width line"
    assert _widest_dark_run(plain) < 0.9, "unstruck formula reads as struck"
