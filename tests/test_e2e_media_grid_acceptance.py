"""Task 13 acceptance checks, NARROWED to PR 1 of 2 (media library + picker
grids only) per the dispatcher's explicit instructions, which override the
task-13 brief where they differ.

In scope here:
  - Acceptance criterion 1: the grid selects the thumb, at DPR 1 AND DPR 3.
  - Acceptance criterion 3: grid initial-viewport bytes under a threshold
    derived from an actual measurement taken in this same test run, not
    typed from memory or from the 58.6MB library total.

Deliberately NOT in this file (out of scope for PR 1, per the dispatcher):
  - Acceptance criterion 2 (a student `el-full` surface selecting the `web`
    derivative) -- no PR-1 surface renders `web` at all; it is generated and
    backfilled but nothing consumes it yet.
  - The brief's geometry-baseline suite (both TOC states x 640/641/1280 x
    landscape/portrait, `tests/data/media_derivatives_geometry_baseline.json`
    and its master-side probe) -- that exists for student surfaces this PR
    does not touch.

Because of that narrowing, this file's name deliberately differs from the
brief's prescribed `tests/test_e2e_media_derivatives_geometry.py`: nothing
here measures geometry (box width/height), only source selection and byte
counts, so `_grid_acceptance` describes the actual contents.
"""

import os
from io import BytesIO

import pytest
from PIL import Image

from tests.factories import CourseFactory
from tests.factories import make_image_asset
from tests.factories import make_verified_user
from tests.test_e2e_media_manager import _isolated_media  # noqa: F401
from tests.test_e2e_media_manager import _open_manager

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


def _noisy_png_bytes(size):
    """A non-trivial-content PNG via PIL's Image.effect_noise (C-level, fast
    even at these dimensions).

    NOT a flat colour fill: a single-colour PNG compresses to a few dozen
    bytes at ANY resolution, thumb or original alike, which would make every
    byte-count assertion below pass identically on a build that regressed to
    serving the original -- there would be nothing to measure. Noise, by
    contrast, is realistically-sized (hundreds of KB at these dimensions) and
    still compresses noticeably better once downsized to the thumb's pixel
    count, giving the size test a real, measurable gap to assert on.
    """
    bands = [Image.effect_noise(size, 40) for _ in range(3)]
    img = Image.merge("RGB", bands)
    buf = BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.django_db(transaction=True)
def test_grid_selects_the_thumb_at_dpr_1_and_3(browser, live_server):
    """Acceptance criterion 1.

    The `grid` preset's strategy is FIXED: a single `src` pointing at the
    thumb, with NO `srcset`. The browser therefore has no candidates to
    choose between, so `currentSrc` is DPR-independent by construction --
    this test does not (and cannot) prove density-switching, because there
    is nothing to switch between. What it pins is the ABSENCE of
    density-switching: it fails if the tag regresses to emitting the
    original (currentSrc would contain the original filename, not the
    `-512.webp` thumb, at DPR 1 already) or if it starts emitting a `srcset`
    whose DPR-3 candidate is the full-resolution file (currentSrc would then
    DIFFER between the DPR 1 and DPR 3 contexts below, and a `srcset`
    attribute would be present at all, which the middle assertion also
    checks for directly).
    """
    user = make_verified_user("grid-dpr-pa")
    course = CourseFactory(owner=user, slug="grid-dpr")
    raw = _noisy_png_bytes((2000, 1500))
    asset = make_image_asset(course, filename="wide.png", raw=raw, derivatives=True)
    assert asset.thumb.name, "fixture setup must actually produce a thumb"
    thumb_url = asset.thumb.url
    original_url = asset.file.url
    assert thumb_url != original_url

    seen = {}
    for dpr in (1, 3):
        ctx = browser.new_context(device_scale_factor=dpr)
        try:
            page = ctx.new_page()
            _open_manager(page, live_server, user.username, course)
            img = page.locator(".asset-cell img.asset-thumb")
            assert img.get_attribute("srcset") is None, (
                "the grid preset must never emit a srcset -- a srcset with a "
                "full-resolution DPR-3 candidate is exactly the regression "
                "this test exists to catch"
            )
            seen[dpr] = img.evaluate("el => el.currentSrc")
        finally:
            ctx.close()

    assert thumb_url in seen[1], (
        f"DPR-1 currentSrc must resolve to the thumb; got {seen[1]!r}"
    )
    assert original_url not in seen[1], (
        f"DPR-1 currentSrc must NOT be the full-resolution original; got {seen[1]!r}"
    )
    assert seen[1] == seen[3], (
        "with no srcset there is nothing for the browser to switch between "
        "-- a diverging currentSrc between DPR 1 and DPR 3 means a srcset "
        "(or some other density-dependent source) crept back in"
    )


def _seed_grid_course(username, slug, count, raw, *, derivatives):
    # Explicit email: two courses are seeded in the byte-threshold test below,
    # and make_verified_user's default email is the same literal for every
    # caller that omits one -- a second call in the same test would collide
    # on accounts_user's unique email constraint.
    user = make_verified_user(username, email=f"{username}@t.example.com")
    course = CourseFactory(owner=user, slug=slug)
    for i in range(count):
        make_image_asset(
            course, filename=f"photo_{i:03d}.png", raw=raw, derivatives=derivatives
        )
    return user, course


def _measure_media_bytes(browser, live_server, username, course):
    """Open the manager grid in a fresh context and sum the real bytes of
    every /media/courses/media/... response observed up to networkidle.

    A fresh context per call: independent HTTP cache, so a cached response
    from one measurement can never silently deflate the bytes of another.
    """
    urls = []
    total = {"bytes": 0}

    def _on_response(response):
        if "/media/courses/media/" not in response.url:
            return
        try:
            body = response.body()
        except Exception:  # noqa: BLE001 - aborted/redirected responses, not under test
            return
        total["bytes"] += len(body)
        urls.append(response.url)

    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    try:
        page = ctx.new_page()
        page.on("response", _on_response)
        _open_manager(page, live_server, username, course)
        page.wait_for_load_state("networkidle")
    finally:
        ctx.close()
    return total["bytes"], urls


@pytest.mark.django_db(transaction=True)
def test_grid_initial_viewport_bytes_are_under_the_measured_threshold(
    browser, live_server
):
    """Acceptance criterion 3.

    The threshold is derived from an actual measurement taken earlier in
    THIS test (the "before" course, which serves originals via the tag's
    documented blank-thumb fallback -- real shipped behaviour, not a
    simulation of master), not from the 58.6MB library total and not typed
    from memory. Both courses use the same non-trivial noise content (see
    `_noisy_png_bytes`), so neither measurement can pass by accident because
    the fixture images happened to compress to nothing.

    150 assets, far more than fit in a 1280x800 first paint of an 8rem-cell
    grid -- MEASURED (via a throwaway diagnostic run, not guessed) to leave
    ~40 rows below Chromium's native lazy-load preload distance, so
    `loading="lazy"` (set unconditionally for the grid preset) has real rows
    to defer. Both measurements assert fewer than `n` responses fired, which
    is what pins the lazy-loading attribute rather than merely observing
    that thumbs are smaller than originals.
    """
    raw = _noisy_png_bytes((800, 600))
    n = 150

    before_user, before_course = _seed_grid_course(
        "grid-byt-before", "grid-byt-before", n, raw, derivatives=False
    )
    before_bytes, before_urls = _measure_media_bytes(
        browser, live_server, before_user.username, before_course
    )
    assert before_bytes > 0, "the 'before' course must actually transfer image bytes"
    assert len(before_urls) < n, (
        "lazy loading must defer some of the 'before' course's images too, or "
        "this run isn't measuring an initial viewport"
    )

    after_user, after_course = _seed_grid_course(
        "grid-byt-after", "grid-byt-after", n, raw, derivatives=True
    )
    after_bytes, after_urls = _measure_media_bytes(
        browser, live_server, after_user.username, after_course
    )
    assert after_bytes > 0, "the 'after' course must actually transfer image bytes"
    assert len(after_urls) < n, (
        "the grid preset's loading=lazy must defer some of the 'after' "
        "course's images too -- if every cell fired, this measures the "
        "whole grid, not the initial viewport, and the byte comparison "
        "below would not isolate the thumb-vs-original difference"
    )

    threshold = before_bytes // 2  # derived from the measurement above, not typed
    assert after_bytes < before_bytes, (
        f"the thumb-served grid ({after_bytes} bytes) must transfer meaningfully "
        f"fewer bytes than the same grid serving originals ({before_bytes} bytes)"
    )
    assert after_bytes < threshold, (
        f"after_bytes={after_bytes} is not under the measured threshold "
        f"({threshold} bytes, half of the measured before_bytes={before_bytes})"
    )
