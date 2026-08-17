"""Playwright e2e for Task 9: the hover preview must read `.asset-cell`'s
`data-url`, not the rendered thumb's own `src`.

Ordering reason: `_asset_cell.html` and `_picker_grid.html` still emit the
FULL-RESOLUTION original as both the thumb's `src` and the cell's `data-url`
(Task 11 has not converted either template yet). That means, against the real
rendered markup, the two attributes hold the identical string today and no
test driving only the real markup can tell the repointed JS apart from the
un-repointed JS -- both would read the same URL. Every test below therefore
sets the cell's `data-url` to a value that diverges from the thumb's own
`src`/attributes via `page.evaluate`, exactly as the implementation plan's
brief prescribes, so the assertions are meaningful NOW and keep meaning
identical after Task 11 lands a real thumbnail URL in the thumb's `src`.
"""

import os

import pytest
from playwright.sync_api import expect

from tests.test_e2e_media_manager import _isolated_media  # noqa: F401
from tests.test_e2e_media_manager import _open_manager
from tests.test_e2e_media_manager import _png_bytes
from tests.test_e2e_media_manager import _seed_assets

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session", autouse=True)
def _allow_sync_orm_under_playwright():
    # Sync Playwright + Django ORM in the same thread. Module-local in every
    # tests/test_e2e_*.py -- it is NOT in any conftest.py.
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    yield


@pytest.mark.django_db(transaction=True)
def test_hover_preview_loads_the_original_not_the_thumb(page, live_server):
    """Synthetic markup for the ordering reason in the module docstring: until
    _asset_cell.html converts (Task 11), the thumb's own src IS the original,
    so a test driving only the real markup would pass identically on the
    un-repointed JS and prove nothing. Diverging the two attributes here is
    what makes the assertion able to fail today."""
    user, course = _seed_assets(
        "prev-orig-pa", "prev-orig", ("asset_0_1.png", (400, 300))
    )
    _open_manager(page, live_server, "prev-orig-pa", course)
    page.evaluate(
        """() => {
             const cell = document.querySelector('.asset-cell');
             const thumb = cell.querySelector('[data-asset-preview]');
             cell.setAttribute('data-url', '/media/ORIGINAL.png');
             thumb.setAttribute('src', '/media/THUMB.png');
           }"""
    )
    page.hover(".asset-cell [data-asset-preview]")
    # "attached", not the default "visible": both ORIGINAL.png and THUMB.png
    # are synthetic paths that 404, so the image never actually loads and
    # stays hidden either way -- only the `src` attribute is under test here.
    page.wait_for_selector(".asset-preview [data-asset-preview-img]", state="attached")
    src = page.locator("[data-asset-preview-img]").get_attribute("src")
    assert "ORIGINAL" in src
    assert "THUMB" not in src


@pytest.mark.django_db(transaction=True)
def test_broken_original_shows_caption_only_via_the_error_handler(page, live_server):
    """After the repoint, `anchor.complete && anchor.naturalWidth === 0`
    would interrogate the THUMB while a different (the cell's) URL is
    loading, so a broken original would silently leave the overlay image
    revealed with nothing loaded. That branch moves to the overlay image's
    own error handler (media_preview.js:54-58).

    The image's own `hidden` PROPERTY is asserted directly, not Playwright's
    visual is_visible(): `[data-asset-preview-img]` is styled `height: auto`
    with no intrinsic size, so a broken image can render at a collapsed
    (near-zero) box for reasons that have nothing to do with the `hidden`
    attribute the JS actually toggles -- that would make a visual visibility
    check pass on a build that left the image un-hidden. The thumb itself
    (the real seeded asset) loads fine, so on the un-repointed JS the anchor's
    own currentSrc is valid and the overlay copies THAT -- successfully
    revealing the image -- which is exactly the case this must catch.
    """
    user, course = _seed_assets(
        "prev-brk-pa", "prev-brk", ("asset_0_1.png", (400, 300))
    )
    page.route("**/broken-original.png", lambda route: route.abort())
    _open_manager(page, live_server, "prev-brk-pa", course)
    page.evaluate(
        "document.querySelector('.asset-cell')"
        ".setAttribute('data-url', '/media/broken-original.png')"
    )
    # Condition, not a sleep: wait for the aborted request itself to fail
    # rather than an arbitrary 300ms. This is tied to the exact event the
    # error handler reacts to, so it can't under- or over-wait it.
    with page.expect_event(
        "requestfailed", lambda request: "broken-original.png" in request.url
    ):
        page.hover(".asset-cell [data-asset-preview]")
    page.wait_for_selector(".asset-preview")
    assert page.eval_on_selector("[data-asset-preview-img]", "el => el.hidden") is True
    assert page.locator(".asset-preview__caption").is_visible()


@pytest.mark.django_db(transaction=True)
def test_the_caption_paints_before_the_image(page, live_server):
    """Accepted consequence of the repoint: today the overlay copies the
    grid img's already-loaded original (same URL, browser-cached, so the
    synchronous flash-guard in open() reveals it in the same frame as the
    caption) and paints instantly; after the repoint it fetches the cell's
    data-url on every hover, so a genuinely UNRESOLVED request must leave the
    image hidden while the caption is already showing.

    A real (non-synthetic) cell cannot exercise this before Task 11: its
    data-url and its thumb's src are still the identical, already-cached
    URL, so holding that one request open would delay BOTH the pre- and
    post-repoint code paths identically and prove nothing about the repoint.
    Diverging the two (as in the other two tests here) and holding the
    CELL's URL open is what isolates the repoint's effect: on the
    un-repointed JS the overlay never touches this held URL at all -- it
    copies the thumb's own already-complete src -- so the image reveals
    immediately, before the route is ever released, and the "still hidden"
    assertion below fails.
    """
    user, course = _seed_assets(
        "prev-ord-pa", "prev-ord", ("asset_0_1.png", (400, 300))
    )
    held = {"route": None}
    page.route(
        "**/pending-original.png", lambda route: held.__setitem__("route", route)
    )
    _open_manager(page, live_server, "prev-ord-pa", course)
    page.evaluate(
        "document.querySelector('.asset-cell')"
        ".setAttribute('data-url', '/media/pending-original.png')"
    )
    page.hover(".asset-cell [data-asset-preview]")
    expect(page.locator(".asset-preview")).to_be_visible()
    assert page.locator(".asset-preview__caption").inner_text() != ""
    # The request must be genuinely pending (not merely fast) at this point,
    # or the assertion below is a race rather than an observation.
    assert held["route"] is not None
    assert page.eval_on_selector("[data-asset-preview-img]", "el => el.hidden") is True
    # fulfill(), not continue_(): "/media/pending-original.png" is a synthetic
    # path with no file behind it, so continuing to the real server would 404
    # and the image would stay hidden via the error handler -- indistinguishable
    # from the assertion this is meant to prove.
    held["route"].fulfill(content_type="image/png", body=_png_bytes())
    expect(page.locator("[data-asset-preview-img]")).to_be_visible()
